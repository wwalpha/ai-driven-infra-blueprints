"""Common offline adapter contract checks."""

import json
from collections import Counter
from copy import deepcopy
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aws_mapping_compare import value as mapping_value
from contracts.model import (
    MODEL_REF_KEY,
    REFERENCE_LOGICAL_ID_KEY,
    RESOURCE_LOGICAL_ID_KEY,
)
from model.importing import cli, inventory, limitations
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls, EC2NetworkCalls
from model.importing.contract_fixtures import InvalidFixture
from model.importing.discovery import ADAPTER_INVENTORIES
from model.literal_values import optional_projection_absence
from model.reference_nodes import parse

ACCOUNT = "123456789012"
TARGET = {
    "awsAccountId": ACCOUNT,
    "awsRegion": "ap-northeast-1",
    "environment": "dev",
    "directory": "contract",
}


class UnverifiedFixture(ValueError):
    """The fixture does not establish the requested evidence."""


def fixture_context(root: Path, service: str, calls: type, payload: Any):
    ctx = cli.import_context(root, TARGET, service=service, no_profile=True)
    ctx.verified = True
    fake = calls(ctx, payload)
    ctx.pages, ctx.call = fake.pages, fake.call
    return ctx, fake


def fixture_resource(root: Path, ctx: Any, service: str, record: Any, number="fixture"):
    _, mapped = inventory.inventory_for(ctx).mapping(service)
    model = SimpleNamespace(
        ctx=ctx,
        path=root / "model/dev/contract" / (service + ".properties"),
        service=service,
        values={},
        resources=[],
    )
    return cli.selector_resource(model, number, record, mapped)


def fixture_parent(parent, attribute, value):
    node = parse(value)
    if (node.logical_id, node.attribute) != (
        parent.spec[RESOURCE_LOGICAL_ID_KEY],
        attribute,
    ):
        raise ValueError("fixture parent reference differs")
    return parent


def bind_fixture_parent(child, parent, attribute):
    parent.spec[RESOURCE_LOGICAL_ID_KEY] = parent.kind.replace(".", "_") + "_001"
    child.spec["parentReference"] = json.dumps(
        {
            MODEL_REF_KEY: {
                REFERENCE_LOGICAL_ID_KEY: parent.spec[RESOURCE_LOGICAL_ID_KEY],
                "attribute": attribute,
            }
        }
    )
    child.reference = partial(fixture_parent, parent, attribute)


def clear_fetch(ctx: Any) -> None:
    ctx.fetch_cache.clear()
    ctx._flights.clear()


def import_normalize(
    ctx: Any, kind: str, key: str, raw: Any, norm: str = "typed"
) -> None:
    raw = cli.normalize_import_value(ctx, raw, norm)
    shape = "projection" if cli.array_paths(key) else "leaf"
    path = cli.schema_property(kind, key)
    extracted = cli.normalize(path, raw, shape)
    if any(
        (
            item == cli.comparator().MISSING
            and not optional_projection_absence(kind, path, item)
        )
        or cli.unsafe(item)
        for item in extracted.values
    ):
        raise UnverifiedFixture("Fixture contains sensitive or unresolved values")
    errors = cli.validation_errors(ctx.catalog, kind, path, extracted)
    if errors:
        raise UnverifiedFixture(
            "Fixture value is invalid for the Model: " + "; ".join(errors)
        )


def fixture_properties(
    ctx: Any,
    resource: Any,
    mapping: Any,
    properties: list[str],
    kind: str,
    expected: dict[str, Any],
    branches: list[str],
    *,
    model_failure_is_broken: bool = False,
) -> dict[str, Any]:
    items = {}
    for key in properties:
        name = key.removeprefix(kind + ".")
        prop = mapping.properties[key]
        case = expected.get(name)
        if cli.sensitive(resource, key) or (
            prop.source != "aws" and limitations.contract(ctx.root, key, "unobservable")
        ):
            items[key] = {
                "status": "unverified",
                "reason": "Sensitive or explicitly unobservable Property",
            }
            continue
        if (
            case is None
            or prop.transform != "identity"
            or (prop.field.path, prop.field.norm) != case[:2]
        ):
            items[key] = {
                "status": "unverified",
                "reason": "No executable property/branch fixture",
            }
            continue
        _, raw = mapping_value(ctx, resource, mapping, prop, key)
        actual = (
            raw
            if prop.field.norm == "kms"
            else cli.comparator().normalize(ctx, raw, prop.field.norm)
        )
        if actual != case[2]:
            items[key] = {
                "status": "broken",
                "reason": "Adapter result differs from fixture",
            }
            continue
        try:
            import_normalize(ctx, kind, key, raw, prop.field.norm)
        except UnverifiedFixture as error:
            if not model_failure_is_broken:
                raise InvalidFixture(str(error)) from error
            items[key] = {
                "status": "broken",
                "reason": "SDK attribute is rejected by Import Model validation: "
                + str(error),
            }
            continue
        items[key] = {
            "status": "verified",
            "reason": "Offline fixture only; AWS retrieval remains unverified",
            "branches": list(branches),
        }
    return items


def failure_branches(
    ctx: Any,
    fake: Any,
    resource: Any,
    mapping: Any,
    sample: str,
    api: str,
    selector: str,
) -> None:
    clear_fetch(ctx)
    fake.error = cli.comparator().AcquisitionError(api, "AccessDenied")
    try:
        mapping_value(ctx, resource, mapping, mapping.properties[sample], sample)
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("API failure was changed") from error
    else:
        raise ValueError("API failure was swallowed")
    fake.error = None
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith("." + selector)
    ]
    clear_fetch(ctx)
    try:
        mapping_value(ctx, resource, mapping, mapping.properties[sample], sample)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing selector was accepted")


def missing_values(
    ctx: Any,
    fake: Any,
    resource: Any,
    mapping: Any,
    items: dict[str, Any],
    payload: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> None:
    for key, evidence in items.items():
        if evidence["status"] != "verified":
            continue
        prop = mapping.properties[key]
        field = prop.field.path.split(".", 1)[0].removesuffix("[]")
        if field in required:
            continue
        fake.payload = {name: value for name, value in payload.items() if name != field}
        clear_fetch(ctx)
        _, raw = mapping_value(ctx, resource, mapping, prop, key)
        actual = cli.comparator().normalize(ctx, raw, prop.field.norm)
        if actual not in (cli.comparator().MISSING, []):
            evidence.update(status="broken", reason="Missing value was not preserved")
        elif "missing-value" not in evidence["branches"]:
            evidence["branches"].append("missing-value")
    fake.payload = payload
    clear_fetch(ctx)


def contracts(mapping: Any, kind: str) -> dict[str, list[str]]:
    """Discover included adapter/SDK getters and their actual mapped properties."""
    result: dict[str, list[str]] = {}
    for key, prop in sorted(mapping.properties.items()):
        definition = mapping.getters.get(prop.field.getter, {})
        if (
            key.startswith(kind + ".")
            and prop.include
            and prop.source == "aws"
            and (not definition or definition.get("kind") in {"adapter", "sdk"})
        ):
            result.setdefault(prop.field.getter, []).append(key)
    return result


def direct_resource(
    root,
    mapping,
    kind,
    api,
    operation,
    inputs,
    envelope,
    cloud,
    payload,
    *,
    calls=DirectCalls,
    record=None,
    identifier=None,
):
    service = mapping.service
    ctx, fake = fixture_context(root, service, calls, payload)
    fake.api, fake.operation, fake.inputs, fake.envelope = (
        api,
        operation,
        inputs,
        envelope,
    )
    fake.typename = "AWS::" + kind.replace(".", "::")
    fake.cloud_properties = cloud
    fake.identifier = (
        identifier
        if identifier is not None
        else cloud.get("Arn", cloud.get("Id", "fixture"))
    )
    if record is None:
        source = inventory.inventory_for(ctx)
        _, mapped = source.mapping(service)
        record = source.cloud_record(
            service,
            kind,
            {"Identifier": fake.identifier, "Properties": json.dumps(cloud)},
            source.schema(kind),
            mapping,
            mapped,
        )
    return ctx, fake, fixture_resource(root, ctx, service, record)


def direct_properties(
    ctx, fake, resource, mapping, properties, kind, cases, payload, required
):
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied"],
    )
    if fake.calls:
        if fake.calls != [(fake.api, fake.operation, fake.inputs)]:
            raise ValueError("SDK request differs from fixture: " + str(fake.calls))
        missing_values(ctx, fake, resource, mapping, items, payload, required=required)
    return items


def grouped_resource(
    root,
    mapping,
    kind,
    parent_kind,
    parent_prop,
    child_prop,
    api,
    operation,
    identifier,
    payload,
    calls,
):
    service = mapping.service
    ctx, fake = fixture_context(root, service, calls, payload)
    fake.api, fake.operation, fake.inputs, fake.envelope = (
        api,
        operation,
        {child_prop: "fixture"},
        "$",
    )
    fake.typename = "AWS::" + kind.replace(".", "::")
    fake.identifier = identifier
    fake.cloud_properties = {"Id": identifier, child_prop: "fixture"}
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping(mapping.service)
    record = source.cloud_record(
        mapping.service,
        kind,
        {
            "Identifier": fake.identifier,
            "Properties": json.dumps(fake.cloud_properties),
        },
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, mapping.service, record, "child")
    parent = cli.selector_resource(
        resource.model,
        "parent",
        {
            "kind": parent_kind,
            "getters": {},
            "seedProperties": {parent_kind + "." + parent_prop: "fixture"},
        },
        mapped,
    )
    bind_fixture_parent(resource, parent, parent_prop)
    resource.model._anchor_resources = {"parent": [("parent", {"anchor": "parent"})]}
    resource.model.resources = [parent, resource]
    ctx.models[resource.model.path.resolve()] = resource.model
    return ctx, fake, resource


def grouped_failures(ctx, fake, resource, mapping, sample, kind, getter, child_prop):
    saved_rows = deepcopy(resource.rows)
    resource.rows[:] = [
        row
        for row in resource.rows
        if not row[1]["property"].endswith("." + child_prop)
    ]
    resource.rows.append(
        ("fixture-mismatch", {"property": kind + "." + child_prop, "value": "`other`"})
    )
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Grouped resource parent mismatch was accepted")
    resource.rows[:] = saved_rows
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        sample,
        fake.api + "." + fake.operation,
        child_prop,
    )


def network_resource(root, mapping, kind, operation, collection, payload, identifier):
    ctx, fake = fixture_context(root, mapping.service, EC2NetworkCalls, payload)
    fake.api, fake.operation, fake.collection = "ec2", operation, collection
    if kind in ADAPTER_INVENTORIES:
        record = inventory.adapter_inventory(ctx, mapping.service, (kind,))[0]
    else:
        source = inventory.inventory_for(ctx)
        _, mapped = source.mapping(mapping.service)
        fake.typename, fake.identifier, fake.cloud_properties = (
            "AWS::" + kind.replace(".", "::"),
            identifier,
            {"Id": identifier},
        )
        record = source.cloud_record(
            mapping.service,
            kind,
            {
                "Identifier": fake.identifier,
                "Properties": json.dumps(fake.cloud_properties),
            },
            source.schema(kind),
            mapping,
            mapped,
        )
    resource = fixture_resource(root, ctx, mapping.service, record)
    return ctx, fake, resource


def network_failures(ctx, fake, resource, getter):
    resource.module.fetch(ctx, resource, getter)
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous network resources were accepted")
    fake.duplicate = False
    clear_fetch(ctx)
    fake.error = cli.comparator().AcquisitionError(
        "ec2." + fake.operation, "AccessDenied"
    )
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("Network API failure was swallowed")
    fake.error = None
    resource.rows[:] = []
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing network selectors were accepted")


def run(root: Path, mapping: Any, kind: str, registry) -> dict[str, Any]:
    getters = contracts(mapping, kind)
    results = {}
    for getter, properties in getters.items():
        items = {}
        fixture, operation, selectors, additional = registry.get(
            (kind, getter), (None, None, None, ())
        )
        if fixture is not None and getter in mapping.getters:
            try:
                items = fixture(root, mapping, properties)
            except InvalidFixture:
                raise
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                cli.comparator().Unresolved,
                cli.comparator().AcquisitionError,
            ) as error:
                items = {
                    key: {"status": "broken", "reason": str(error)}
                    for key in properties
                }
        for key in properties:
            if key in items:
                continue
            if getter not in mapping.getters:
                items[key] = {"status": "broken", "reason": "Getter is not registered"}
            else:
                items[key] = {
                    "status": "unverified",
                    "reason": "No executable property/branch fixture",
                }
        statuses = Counter(item["status"] for item in items.values())
        results[getter] = {
            "status": "broken"
            if statuses["broken"]
            else "unverified"
            if statuses["unverified"]
            else "verified",
            "adapter": "framework/scripts/aws-compare-services/"
            + mapping.service
            + ".py",
            "getterKind": mapping.getters.get(getter, {}).get("kind"),
            "operation": mapping.getters.get(getter, {}).get("operation"),
            "fixtureOperation": operation,
            "fixtureAdditionalOperations": list(additional),
            "selectors": list(selectors) if selectors is not None else None,
            "paths": {
                key: {
                    "path": mapping.properties[key].field.path,
                    "normalize": mapping.properties[key].field.norm,
                }
                for key in properties
            },
            "properties": items,
        }
    return results
