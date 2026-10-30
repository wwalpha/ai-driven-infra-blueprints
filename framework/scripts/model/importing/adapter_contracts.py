"""Executable, in-process Import adapter evidence; no AWS calls or saved receipts."""

from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aws_mapping_compare import value as mapping_value
from botocore.validate import ParamValidator
from utils.aws_sdk import aws_runtime

from model.importing import cli, inventory
from model.importing.discovery import resolve

ACCOUNT = "123456789012"
TARGET = {
    "awsAccountId": ACCOUNT,
    "awsRegion": "ap-northeast-1",
    "environment": "dev",
    "directory": "contract",
}


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


class FakeCalls:
    def __init__(self, ctx: Any, payload: dict[str, Any]) -> None:
        self.ctx = ctx
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.sdk = aws_runtime().sdk_session()
        self.error: Exception | None = None

    def request(self, api: str, operation: str, inputs: dict[str, Any]) -> None:
        if (api, operation) not in self.ctx.allowed or not operation.startswith(
            ("list_", "get_", "describe_", "batch_get_")
        ):
            raise ValueError("Operation is outside the read-only allowlist")
        model = self.sdk.get_service_model(api)
        name = aws_runtime().operation_name(model, operation)
        if name is None:
            raise ValueError("Unknown SDK operation")
        shape = model.operation_model(name).input_shape
        if shape is None and inputs:
            raise ValueError("Operation accepts no input parameters")
        errors = ParamValidator().validate(inputs, shape) if shape else None
        if errors and errors.has_errors():
            raise ValueError(errors.generate_report())
        self.calls.append((api, operation, inputs))

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "quicksight",
            "list_namespaces",
            {"AwsAccountId": ACCOUNT},
        ):
            return {"Namespaces": [{"Name": "default"}]}
        if (api, operation, inputs) == (
            "quicksight",
            "list_groups",
            {"AwsAccountId": ACCOUNT, "Namespace": "default"},
        ):
            return {"GroupList": [{"GroupName": "group"}]}
        if (api, operation, inputs) != (
            "quicksight",
            "list_vpc_connections",
            {"AwsAccountId": ACCOUNT},
        ):
            raise ValueError("Unexpected inventory request or scope")
        return {"VPCConnectionSummaries": [{"VPCConnectionId": "connection"}]}

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) == (
            "quicksight",
            "describe_group",
            {"AwsAccountId": ACCOUNT, "Namespace": "default", "GroupName": "group"},
        ):
            return {"Group": {"GroupName": "group"}}
        if (api, operation, inputs) != (
            "quicksight",
            "describe_vpc_connection",
            {"AwsAccountId": ACCOUNT, "VPCConnectionId": "connection"},
        ):
            raise ValueError("Unexpected adapter request or scope")
        return {"VPCConnection": deepcopy(self.payload)}


def vpc_fixture(root: Path, mapping: Any, prop: Any) -> None:
    """Execute the real inventory, selector builder, adapter and mapped projection."""
    if (prop.field.getter, prop.field.path, prop.field.norm) != (
        "vpc",
        "DnsResolvers",
        "typed",
    ):
        raise ValueError("Fixture does not match the current Mapping")
    definition = mapping.getters.get("vpc", {})
    if definition.get(
        "kind"
    ) != "adapter" or "QuickSight.VPCConnection" not in definition.get("resources", ()):
        raise ValueError("VPC adapter registration is invalid")
    expected = ["10.0.0.2", "10.0.0.3"]
    ctx = cli.import_context(root, TARGET, service="quicksight", no_profile=True)
    ctx.verified = True
    fake = FakeCalls(ctx, {"VPCConnectionId": "connection", "DnsResolvers": expected})
    ctx.pages, ctx.call = fake.pages, fake.call
    plan = resolve(mapping, mapping.properties, "QuickSight.VPCConnection")
    if plan.mode != "adapter":
        raise ValueError("Unexpected discovery plan")
    record = inventory.adapter_inventory(
        ctx, "quicksight", ("QuickSight.VPCConnection",)
    )[0]
    _, mapped = inventory.inventory_for(ctx).mapping("quicksight")
    model = SimpleNamespace(
        ctx=ctx,
        path=root / "model/dev/contract/quicksight.properties",
        service="quicksight",
        values={},
        resources=[],
    )
    resource = cli.selector_resource(model, "fixture", record, mapped)
    for value in (expected, [], None):
        fake.payload = {"VPCConnectionId": "connection"}
        if value is not None:
            fake.payload["DnsResolvers"] = value
        ctx.fetch_cache.clear()
        ctx._flights.clear()
        fake.calls.clear()
        _, raw = mapping_value(
            ctx, resource, mapping, prop, "QuickSight.VPCConnection.DnsResolvers"
        )
        actual = cli.comparator().normalize(ctx, raw, prop.field.norm)
        if actual != (
            cli.comparator().MISSING if value is None else value
        ) or fake.calls != [
            (
                "quicksight",
                "describe_vpc_connection",
                {"AwsAccountId": ACCOUNT, "VPCConnectionId": "connection"},
            )
        ]:
            raise ValueError("Adapter result or request differs from fixture")
        if value is not None:
            extracted = cli.normalize("DnsResolvers", actual, "leaf")
            if cli.validation_errors(
                ctx.catalog,
                "QuickSight.VPCConnection",
                "DnsResolvers",
                extracted,
            ):
                raise ValueError("Normalized DNS resolver value is invalid")
    ctx.fetch_cache.clear()
    ctx._flights.clear()
    fake.error = cli.comparator().AcquisitionError(
        "quicksight.describe_vpc_connection", "AccessDenied"
    )
    try:
        mapping_value(
            ctx, resource, mapping, prop, "QuickSight.VPCConnection.DnsResolvers"
        )
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("API failure was changed") from error
    else:
        raise ValueError("API failure was swallowed")
    fake.error = None
    resource.rows[:] = [
        row
        for row in resource.rows
        if not row[1]["property"].endswith(".VPCConnectionId")
    ]
    ctx.fetch_cache.clear()
    ctx._flights.clear()
    try:
        mapping_value(
            ctx, resource, mapping, prop, "QuickSight.VPCConnection.DnsResolvers"
        )
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing selector was accepted")
    resource.rows.append(
        (
            "fixture-999",
            {
                "property": "QuickSight.VPCConnection.VPCConnectionId",
                "value": "`connection`",
            },
        )
    )
    ctx.target["awsAccountId"] = "999999999999"
    ctx.fetch_cache.clear()
    ctx._flights.clear()
    try:
        resource.module.fetch(ctx, resource, "vpc")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Account scope mismatch was accepted")


def group_fixture(root: Path, mapping: Any, prop: Any) -> None:
    if (prop.field.getter, prop.field.path, prop.field.norm) != (
        "sdk-quicksight-group",
        "GroupName",
        "typed",
    ):
        raise ValueError("Fixture does not match the current Mapping")
    ctx = cli.import_context(root, TARGET, service="quicksight", no_profile=True)
    ctx.verified = True
    fake = FakeCalls(ctx, {})
    ctx.pages, ctx.call = fake.pages, fake.call
    plan = resolve(mapping, mapping.properties, "QuickSight.Group")
    if plan.mode != "scoped_sdk":
        raise ValueError("Unexpected discovery plan")
    record = inventory.sdk_inventory.collect(ctx, "QuickSight.Group")[0]
    _, mapped = inventory.inventory_for(ctx).mapping("quicksight")
    model = SimpleNamespace(
        ctx=ctx,
        path=root / "model/dev/contract/quicksight.properties",
        service="quicksight",
        values={},
        resources=[],
    )
    resource = cli.selector_resource(model, "fixture", record, mapped)
    fake.calls.clear()
    _, raw = mapping_value(ctx, resource, mapping, prop, "QuickSight.Group.GroupName")
    if cli.comparator().normalize(
        ctx, raw, prop.field.norm
    ) != "group" or fake.calls != [
        (
            "quicksight",
            "describe_group",
            {"AwsAccountId": ACCOUNT, "Namespace": "default", "GroupName": "group"},
        )
    ]:
        raise ValueError("SDK adapter result or request differs from fixture")
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".Namespace")
    ]
    ctx.fetch_cache.clear()
    ctx._flights.clear()
    try:
        mapping_value(ctx, resource, mapping, prop, "QuickSight.Group.GroupName")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing SDK selector was accepted")


def run(root: Path, mapping: Any, kind: str) -> dict[str, Any]:
    getters = contracts(mapping, kind)
    results = {}
    for getter, properties in getters.items():
        items = {}
        for key in properties:
            cases = {
                (
                    "QuickSight.VPCConnection",
                    "vpc",
                    "QuickSight.VPCConnection.DnsResolvers",
                ): vpc_fixture,
                (
                    "QuickSight.Group",
                    "sdk-quicksight-group",
                    "QuickSight.Group.GroupName",
                ): group_fixture,
            }
            fixture = cases.get((kind, getter, key))
            prop = mapping.properties[key]
            if getter not in mapping.getters:
                items[key] = {"status": "broken", "reason": "Getter is not registered"}
                continue
            if (
                fixture is None
                or prop.field.path != key.rsplit(".", 1)[-1]
                or prop.field.norm != "typed"
            ):
                items[key] = {
                    "status": "unverified",
                    "reason": "No executable property/branch fixture",
                }
                continue
            try:
                fixture(root, mapping, prop)
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                cli.comparator().Unresolved,
                cli.comparator().AcquisitionError,
            ) as error:
                items[key] = {"status": "broken", "reason": str(error)}
            else:
                items[key] = {
                    "status": "verified",
                    "reason": "Only the listed offline branches were exercised; other branches and AWS retrieval remain unverified",
                    "branches": ["normal", "missing-selector"]
                    + (
                        ["empty", "missing-value", "access-denied", "account-mismatch"]
                        if fixture is vpc_fixture
                        else []
                    ),
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
