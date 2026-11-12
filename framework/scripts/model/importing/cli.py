"""Single-service Import primitives; the LLM supplies selections, Review and consent."""

import argparse
import hashlib
import json
import re
import tempfile
from dataclasses import asdict
from functools import partial as _bind_framework_callback
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import import_guard
import task_contract_core as task_contract
import utils.project_targets as _imports_project_targets
from aws_mapping_compare import MODEL_ONLY
from aws_mapping_compare import value as mapping_value
from contracts.model import (
    MODEL_PENDING_DEPLOY,
    MODEL_UNSET,
    RESOURCE_MODE_IMPORT,
    RESOURCE_TYPE_KEY,
)
from contracts.repository import DESIGNS_DIRECTORY, PROJECT_FILENAME
from contracts.target import AWS_ACCOUNT_ID_KEY, AWS_REGION_KEY
from generation_inputs import GenerationInputs
from import_guard import (
    file_hash,
    require_import_changes,
    workflow,
)
from task_contract_core import (
    section,
    selected_task,
    task_read_scope,
    task_reads,
    task_snapshot,
)
from utils.aws.diagnostics import classify_aws_failure
from utils.aws.identity import import_profile
from utils.aws_mappings import definition_root, mapping_alias
from utils.file_operations import atomic_files
from utils.input_cache import input_context, input_scope, memoized, recording_inputs
from utils.json_format import json_text
from utils.property_path import definition_path
from utils.script_loader import module as load_script
from utils.source_reads import FileReads as FileReads
from validation_scope import active_scope

import model.importing.references as _imports_model_importing_references
import model.importing.repository as repository
import model.importing.scope as _imports_model_importing_scope
import model.references as _imports_model_references
import model.sources as _imports_model_sources
from model.core import entries as entries
from model.importing import approval as import_approval
from model.importing import limitations, sdk_inventory
from model.importing.evidence import (
    acquired,
    acquisition_complete,
    evidence_store,
    read_acquisition,
)
from model.importing.evidence import (
    discard_acquisition as discard_acquisition,
)
from model.importing.inventory import inventory_for
from model.importing.limitations import sensitive as sensitive
from model.importing.scope import (
    model_path,
    read_consumers,
    restrict,
)
from model.importing.sources import (
    pending_items,
    selection_records,
    verify_values,
)
from model.literal_values import (
    array_paths,
    normalize,
    optional_projection_absence,
    validation_errors,
)
from model.operations import prepare_edit, publish_edit
from model.render import owned_artifacts, view_plan
from model.sources import (
    SourceWriteContext,
    _publish_transaction,
    candidate_sources,
    json_read,
    load_model,
    publication_lock,
    safe,
)
from model.sources import candidate_base as before_model

ROOT = Path(__file__).resolve().parents[4]


def comparator():
    return load_script("model/adapters/aws.py", "model.adapters.aws")


def import_context(root, target, runner=None, service=None, *, no_profile=False):
    profile = import_profile(target, no_profile=no_profile)
    target = dict(target)
    target.pop("awsProfile", None)
    if profile is not None:
        target["awsProfile"] = profile
    region = target.get(AWS_REGION_KEY)
    if not isinstance(region, str) or not re.fullmatch(
        r"[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*", region
    ):
        raise ValueError("AWS target RegionMismatch; use the project.json awsRegion")
    return comparator().Context(
        root,
        target,
        cli_runner=runner,
        services=(service,) if service else (),
        import_mode=True,
    )


def target_for(root, environment, service, selector=None):
    select_target = _imports_project_targets.select_target
    if (
        not environment
        or not service
        or any(
            not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", x)
            for x in (environment, service)
        )
    ):
        raise ValueError("environment and service are required exact identifiers")
    topology = json_read((root / PROJECT_FILENAME).read_text(encoding="utf-8"))
    choices = [
        t
        for t in topology["targets"]
        if isinstance(t, dict) and t.get("environment") == environment
    ]
    if not choices:
        raise ValueError("environment is not registered")
    if selector is None and len(choices) > 1:
        choices = [
            t
            for t in choices
            if (
                root
                / "model"
                / environment
                / t.get("alias", t[AWS_ACCOUNT_ID_KEY])
                / (service + ".properties")
            ).is_file()
        ]
    if selector is None:
        if len(choices) != 1:
            raise ValueError(
                "target is required when the environment has multiple targets for this service"
            )
        selector = choices[0].get("alias", choices[0][AWS_ACCOUNT_ID_KEY])
    choices = [
        t for t in choices if t.get("alias", t.get(AWS_ACCOUNT_ID_KEY)) == selector
    ]
    if len(choices) != 1:
        raise ValueError("target must resolve exactly once")
    entry = choices[0]
    target = select_target(
        topology,
        environment,
        alias=entry.get("alias"),
        account_id=None if "alias" in entry else selector,
    )
    target.update(environment=environment, directory=selector)
    return target


def inventory(ctx, service, resource_types=None):
    return inventory_for(ctx).discover(service, resource_types)


@task_read_scope
def contract_scope(root, scope):
    selected = _imports_model_importing_scope.selected
    workflow(root)
    text = task_snapshot(root).text
    if "- Task type: `design`" not in section(text, "## Task contract"):
        raise ValueError("normal import requires a registered design Task Contract")
    declared = active_scope(root)
    pins = [
        line
        for line in section(text, "## Task contract")
        if line.startswith("- IMPORT target:")
    ]
    if pins:
        expected = (
            "- IMPORT target: `" + "/".join(next(iter(scope))) + "`"
            if len(scope) == 1
            else None
        )
        if pins != [expected]:
            raise ValueError("IMPORT acquisition must match the fixed Task target")
    elif declared != scope:
        raise ValueError(
            "IMPORT initially requires exactly one acquisition target in Validation scope"
        )
    if (
        len(scope) != 1
        or selected(root) not in scope
        or declared is None
        or not scope <= declared
    ):
        raise ValueError(
            "IMPORT requires one fixed environment/target/service within Validation scope"
        )
    if task_contract.status(text) != "running":
        raise ValueError("IMPORT requires a running Task Contract")


@task_read_scope
def record_outputs(root, identity, sources, views, consumers=None):
    """Check the predeclared plan without changing an approved Task/acquisition."""
    allowed_source = _imports_model_importing_scope.allowed_source
    consumers = set(consumers or {identity})
    environment, target, service = identity
    document = root / DESIGNS_DIRECTORY / environment / target / (service + ".md")
    for file in sources:
        if not allowed_source(root, file, identity):
            raise ValueError(
                "IMPORT output is outside selected environment/target/service"
            )
    if any(
        file != document
        and not (file.parent == document.with_suffix("") and file.suffix == ".json")
        for file in views
    ):
        raise ValueError("IMPORT view is outside selected environment/target/service")
    paths = {file.relative_to(root).as_posix() for file in sources | views}
    for relative in paths:
        task_contract.safe_path(root, relative)
    contract_scope(root, {identity})
    snapshot = task_snapshot(root)
    text = snapshot.text
    fixed = "- IMPORT target: `" + "/".join(identity) + "`"
    declared = active_scope(root)
    if fixed not in section(text, "## Task contract") or not consumers <= declared:
        raise ValueError(
            "IMPORT Task must declare its fixed target and direct consumers before acquisition"
        )
    for heading in ("## Allowed paths", "## Modified files"):
        if not paths <= task_contract.paths_in(text, heading):
            raise ValueError(
                "IMPORT Task must declare exact output paths before acquisition: "
                + heading
            )


def unsafe(value):
    text = json_text(value)
    return (
        "[REDACTED]" in text
        or any(x in text for x in (MODEL_PENDING_DEPLOY, MODEL_UNSET))
        or comparator().redacted(value) != value
    )


def model_literal(value):
    text = value if isinstance(value, str) else json_text(value)
    if any(c in text for c in "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029`"):
        raise ValueError("AWS value cannot be represented losslessly as a Model scalar")
    return "`" + text + "`"


def schema_property(kind, prop):
    if (
        kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}
        and prop == kind + ".Name"
    ):
        return "Tags[].Value"
    return prop.removeprefix(kind + ".")


@memoized
def property_catalog():
    return comparator().DesignSchemaCatalog(ROOT)


@memoized
def property_schema(prop):
    kind = ".".join(prop.split(".")[:2])
    return property_catalog().property_schema(
        kind, definition_path(schema_property(kind, prop))
    )


def normalize_import_value(ctx, value, norm):
    return (
        comparator().normalize(ctx, value, norm)
        if norm in {"boolean", "number"}
        else value
    )


def normalize_records(ctx, service, records):
    return [
        inventory_for(ctx).normalize(service, record, _normalize_records)
        for record in records
    ]


def empty_capture(value: Any, missing: Any) -> str | None:
    """Inspect an already-acquired sensitive projection without retaining its values."""
    if value == missing:
        return "missing"
    if isinstance(value, list):
        states = [empty_capture(item, missing) for item in value]
        if all(state in {"missing", "empty"} for state in states):
            return "missing" if "missing" in states else "empty"
    if value == {}:
        return "empty"
    return None


def selector_resource(model, record_id, record, mapped):
    m = comparator()
    kind = record["kind"]
    seed_rows = []
    proxy = m.Resource(
        model,
        record_id,
        {RESOURCE_TYPE_KEY: kind, "resourceMode": RESOURCE_MODE_IMPORT},
        seed_rows,
    )
    for prop, item in mapped.items():
        field = item.field
        if prop.startswith(kind + ".") and field.getter in record["getters"]:
            raw = m.select(record["getters"][field.getter], field.path)
            if (
                raw not in (m.MISSING, None)
                and not sensitive(proxy, prop)
                and not unsafe(raw)
            ):
                try:
                    seed_rows.append(
                        (
                            record_id + "-" + str(len(seed_rows) + 1).zfill(3),
                            {
                                "property": prop,
                                "value": model_literal(raw),
                                "valueShape": "projection"
                                if array_paths(prop)
                                else "leaf",
                            },
                        )
                    )
                except ValueError:
                    pass  # A non-scalar seed cannot be an adapter selector.
    for prop, raw in {
        **record.get("seedProperties", {}),
        **record.get("selectorProperties", {}),
    }.items():
        if not any(row["property"] == prop for _, row in seed_rows) and not unsafe(raw):
            try:
                seed_rows.append(
                    (
                        record_id + "-" + str(len(seed_rows) + 1).zfill(3),
                        {
                            "property": prop,
                            "value": model_literal(raw),
                            "valueShape": "projection" if array_paths(prop) else "leaf",
                        },
                    )
                )
            except ValueError:
                pass  # Unrepresentable data cannot be an adapter selector.
    return proxy


def _normalize_records(ctx, service, records):
    """Reuse Mapping and adapter getters without constructing any public Model source."""
    m = comparator()
    mapping, mapped = inventory_for(ctx).mapping(service)
    ctx.comparisons[service] = mapping, mapped
    model = SimpleNamespace(
        ctx=ctx,
        path=ctx.root
        / "model"
        / ctx.target["environment"]
        / ctx.target["directory"]
        / (service + ".properties"),
        service=service,
        values={},
        resources=[],
    )
    normalized = []
    for record in records:
        kind = record["kind"]
        record_id = hashlib.sha256(
            (kind + "\0" + record["identity"]).encode("utf-8")
        ).hexdigest()
        seed = next(iter(record["getters"].values()), {})
        proxy = selector_resource(model, record_id, record, mapped)
        for getter, payload in record["getters"].items():
            ctx.fetch_cache[model.path, record_id, getter] = payload
            ctx.fetch_trace[model.path, record_id, getter] = []
        properties = {
            p: item
            for p, item in mapped.items()
            if p.startswith(kind + ".") and item.include
        }
        fields = {p: item.field for p, item in properties.items()}
        fields.update(
            {
                p: item.field
                for p, item in mapped.items()
                if p in MODEL_ONLY and p.startswith(kind + ".")
            }
        )
        if kind == "EC2.Subnet" and "association" in record["getters"]:
            fields.update(
                {
                    p: item.field
                    for p, item in mapped.items()
                    if p == "EC2.SubnetRouteTableAssociation.RouteTableId"
                    and item.include
                }
            )
        if kind == "EC2.FlowLog":
            resource_type = next(
                (
                    name
                    for prefix, name in [
                        ("vpc-", "VPC"),
                        ("subnet-", "Subnet"),
                        ("eni-", "NetworkInterface"),
                    ]
                    if seed.get("ResourceId", "").startswith(prefix)
                ),
                None,
            )
            if resource_type:
                ctx.fetch_cache[model.path, record_id, "resource_type"] = {
                    "ResourceType": resource_type
                }
                ctx.fetch_trace[model.path, record_id, "resource_type"] = []
        if {kind + ".Tags[].Key", kind + ".Tags[].Value"} <= fields.keys() and seed.get(
            "Tags"
        ):
            tags = [
                tag
                for tag in seed["Tags"]
                if tag.get("Key") != "Name"
                or kind
                not in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}
            ]
            ctx.fetch_cache[model.path, record_id, "tags"] = {
                "Tags": sorted(tags, key=lambda tag: tag["Key"])
            }
            ctx.fetch_trace[model.path, record_id, "tags"] = []
            fields.update(
                {
                    kind + ".Tags[]." + leaf: m.Field("tags", "Tags[]." + leaf)
                    for leaf in ("Key", "Value")
                }
            )
        captured = {}
        for prop, field in fields.items():
            hidden = sensitive(proxy, prop)
            restriction = limitations.contract(
                ctx.root, prop, "withheld" if hidden else "unobservable"
            )
            safe_empty = False
            try:
                if (
                    restriction is not None
                    and hidden
                    and field.classification == "supported"
                    and field.getter in record["getters"]
                ):
                    _, probe = mapping_value(
                        ctx, proxy, mapping, properties[prop], prop
                    )
                    absence = empty_capture(probe, m.MISSING)
                    if absence == "missing":
                        captured[prop] = {
                            "status": "missing",
                            "reason": "AWS optional value not retrieved",
                        }
                        continue
                    safe_empty = absence == "empty"
                conditional = prop in limitations.CONDITIONAL_CODE
                if conditional and restriction is None:
                    raise ValueError(
                        "Lambda code-source limitation contract is invalid"
                    )
                if restriction is not None and not safe_empty and not conditional:
                    captured[prop] = restriction
                    continue
                if hidden and not safe_empty:
                    raise ValueError("sensitive Property")
                if prop in record.get("selectorProperties", {}):
                    value = record["selectorProperties"][prop]
                elif field.classification != "supported":
                    raise ValueError(field.classification + ": " + field.reason)
                elif prop in properties and field.getter != "tags":
                    response, value = mapping_value(
                        ctx, proxy, mapping, properties[prop], prop
                    )
                    getter = mapping.getters.get(field.getter, {})
                    if (
                        kind == "QuickSight.Group"
                        and getter.get("kind") == "sdk"
                        and (
                            not sdk_inventory.verified_detail(
                                ctx, proxy, record, getter, response
                            )
                            or not limitations.sdk_response(ctx.root, getter, response)
                        )
                    ):
                        raise ValueError(
                            "SDK detail Identity or request evidence is invalid"
                        )
                else:
                    value = m.select(ctx.fetch(proxy, field.getter), field.path)
                if value == m.MISSING:
                    omitted = limitations.contract(ctx.root, prop, "not_returned")
                    getter = mapping.getters.get(field.getter, {})
                    verified_omission = (
                        sdk_inventory.verified_detail(
                            ctx, proxy, record, getter, response
                        )
                        and limitations.sdk_omission(
                            ctx.root, getter, response, field.path
                        )
                        if omitted is not None and getter.get("kind") == "sdk"
                        else field.getter in record.get("verifiedDetailGetters", ())
                        and limitations.missing_leaf(response, field.path)
                    )
                    if omitted is not None and verified_omission:
                        omitted["evidence"]["identity"] = record["identity"]
                        captured[prop] = omitted
                        continue
                    conditional_restriction = (
                        limitations.conditional_code_capture(
                            ctx.root, prop, response, record["identity"]
                        )
                        if conditional
                        and record.get("identityStatus", "known") == "known"
                        else None
                    )
                    if conditional and record.get("identityStatus", "known") != "known":
                        raise ValueError("Lambda identity is unknown")
                    captured[prop] = conditional_restriction or {
                        "status": "missing",
                        "reason": "Lambda Image uses an image source"
                        if conditional
                        else "AWS optional value not retrieved",
                    }
                    continue
                value = normalize_import_value(ctx, value, field.norm)
                shape = "projection" if array_paths(prop) else "leaf"
                property_kind = ".".join(prop.split(".")[:2])
                field_path = schema_property(property_kind, prop)
                extracted = normalize(field_path, value, shape)
                for item in extracted.values:
                    if (
                        item == m.MISSING
                        and not optional_projection_absence(
                            property_kind, field_path, item
                        )
                    ) or unsafe(item):
                        raise ValueError("sensitive or unresolved AWS value")
                errors = validation_errors(
                    property_catalog(), property_kind, field_path, extracted
                )
                if errors:
                    raise ValueError("; ".join(errors))
                captured[prop] = {
                    "status": "captured",
                    "value": value,
                    "valueShape": shape,
                    "source": "verified_selector"
                    if prop in record.get("selectorProperties", {})
                    else properties[prop].source
                    if prop in properties
                    else "aws",
                }
            except (
                ValueError,
                KeyError,
                TypeError,
                m.AcquisitionError,
                m.Unresolved,
            ) as error:
                reason = (
                    error.code
                    if isinstance(error, m.AcquisitionError)
                    else "sensitive Property"
                    if sensitive(proxy, prop)
                    else type(error).__name__
                )
                captured[prop] = {
                    "status": "unavailable",
                    "reason": reason,
                    **(
                        {"errorCode": error.code}
                        if isinstance(error, m.AcquisitionError)
                        else {}
                    ),
                }
        identity = inventory_for(ctx).identity(kind, record)
        normalized.append(
            {
                "record": record_id,
                "kind": kind,
                "identity": record["identity"],
                **identity,
                "properties": captured,
                **{
                    key: record[key]
                    for key in ("provenance", "structureStatus", "structureReason")
                    if key in record
                },
            }
        )
    return normalized


def unchanged(root, checksums):
    safe = _imports_model_sources.safe
    for relative, expected in checksums.items():
        file = root / relative
        safe(root, file)
        if file_hash(file) != expected:
            raise ValueError(
                "Model sources changed during import; concurrent changes were not overwritten: "
                + relative
            )


@input_scope
@task_read_scope
def resume_acquisition(
    root, environment, service, evidence, selector=None, dry_run=False
):
    """Read the LLM's checkpoint after verifying the original session and live baseline."""
    safe = _imports_model_sources.safe
    root = root.resolve()
    target = target_for(root, environment, service, selector)
    identity = (environment, target["directory"], service)
    evidence = Path(evidence).absolute()
    with publication_lock(root, read_only=True):
        acquisition = read_acquisition(root, evidence, identity, dry_run)
        unchanged(root, acquisition["sources"])
        unchanged_sets(root, acquisition["sourceSets"])
        complete = acquisition_complete(acquisition)
        file = evidence.parent / "checkpoint.json"
        safe(evidence.parent, file)
        answers = import_approval.verify_checkpoint(
            acquisition, json_read(file.read_text(encoding="utf-8"))
        )
    return {
        "status": "resumed" if complete else "incomplete",
        "answers": answers,
        "model": "unchanged",
        "markdown": "not-run",
        "designValidation": "not-run",
    }


def source_state(root, inputs):
    files = {
        path.relative_to(root).as_posix(): None
        if raw is None
        else hashlib.sha256(raw).hexdigest()
        for path, raw in inputs.contents.items()
        if path.is_relative_to(root)
    }
    sets = [
        {
            "base": base.relative_to(root).as_posix(),
            "pattern": pattern,
            "recursive": recursive,
            "kinds": None if kinds is None else list(kinds),
            "paths": [path.relative_to(root).as_posix() for path in paths],
        }
        for (base, pattern, recursive, kinds), paths in inputs.selections.items()
        if base.is_relative_to(root)
    ]
    return dict(sorted(files.items())), sorted(sets, key=json_text)


def unchanged_sets(root, sets):
    for record in sets:
        if not isinstance(record, dict) or set(record) != {
            "base",
            "pattern",
            "recursive",
            "kinds",
            "paths",
        }:
            raise ValueError("IMPORT invalid input file-set snapshot")
        relative = PurePosixPath(record["base"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or str(relative) != record["base"]
            or "\\" in record["base"]
        ):
            raise ValueError("IMPORT unsafe input file-set base")
        base = root / relative
        safe(root, base)
        if (
            type(record["recursive"]) is not bool
            or not isinstance(record["pattern"], str)
            or not isinstance(record["paths"], list)
        ):
            raise ValueError("IMPORT invalid input file-set selector")
        pattern = PurePosixPath(record["pattern"])
        if pattern.is_absolute() or ".." in pattern.parts or "\\" in record["pattern"]:
            raise ValueError("IMPORT unsafe input file-set pattern")
        live = GenerationInputs.live_select(
            base, record["pattern"], record["recursive"], record["kinds"]
        )
        if [path.relative_to(root).as_posix() for path in live] != record["paths"]:
            raise ValueError(
                "IMPORT source file set changed after acquisition: " + record["base"]
            )


def replacement_inputs(before, selected_records, reads):
    incoming = _imports_model_references.incoming
    warnings = [{**warning, "phase": "before"} for warning in before.warnings]
    for rid, record in selected_records.items():
        if record.get("_action") not in {"replace", "bind"}:
            continue
        producer = "/".join(
            (before.scope.environment, before.scope.target, before.scope.service, rid)
        )
        for scope, usage in incoming(before, rid, reads, warnings=warnings):
            owner_id = (
                usage.consumer_key.split(".")[2].rpartition("-")[0]
                if usage.consumer_key.startswith("desired.row.")
                else usage.consumer_key.split(".")[2]
            )
            consumer = "/".join(
                (scope.environment, scope.target, scope.service, owner_id)
            )
            if consumer != producer:
                warnings.append(
                    {
                        "code": "reference.replace_impact",
                        "message": "replacement or first binding affects an incoming reference",
                        "resource": rid,
                        "producer": producer,
                        "consumer": consumer,
                        **asdict(usage),
                    }
                )
    files, sets = source_state(before.scope.root, reads)
    return {"inputs": files, "fileSets": sets, "warnings": warnings}


class ImportStageError(ValueError):
    def __init__(self, phase, code, category="unknown", source="unknown", api=None):
        self.phase, self.code = phase, code
        self.category, self.source, self.api = category, source, api
        super().__init__("AWS account mismatch" if code == "AccountMismatch" else code)


def check_evidence_store(root):
    operation = "access"
    path = None
    try:
        directory = evidence_store(root)
        operation = "create"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False
        ) as stream:
            path = Path(stream.name)
            operation = "write"
            stream.write("Import UTF-8: 日本語")
        operation = "read"
        if path.read_text(encoding="utf-8") != "Import UTF-8: 日本語":
            raise ValueError("UTF-8 mismatch")
        operation = "delete"
        path.unlink()
        path = None
    except (OSError, ValueError, UnicodeError) as error:
        raise ImportStageError(
            "temporary_storage", operation, "unknown", "local_check"
        ) from error
    finally:
        if path is not None and operation != "delete":
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


@input_scope
@task_read_scope
def acquire(
    root,
    environment,
    service,
    selector=None,
    dry_run=False,
    cli_runner=None,
    no_profile=False,
    resource_types=None,
):
    root = root.resolve()
    target = target_for(root, environment, service, selector)
    identity = environment, target["directory"], service
    with (
        restrict(identity),
        read_consumers({identity}),
        input_context(),
        publication_lock(root, read_only=True),
    ):
        if not dry_run:
            contract_scope(root, {identity})
            source = model_path(root, identity).relative_to(root).as_posix()
            changed = repository.changed_paths(root)
            parts_prefix = source.removesuffix(".properties") + "/"
            if source in changed or any(
                path.startswith(parts_prefix) for path in changed
            ):
                raise ValueError(
                    "IMPORT Task already changed this service; use display recovery or a new Task"
                )
            require_import_changes(root, generation=True)
        inputs = GenerationInputs(root)
        verified = False
        phase = "unknown"
        try:
            with task_reads(root), recording_inputs(inputs):
                before = before_model(model_path(root, identity), inputs)
                ctx = import_context(
                    root, target, cli_runner, service, no_profile=no_profile
                )
                check_evidence_store(root)
                try:
                    ctx.verify()
                except Exception as error:
                    raise ImportStageError(
                        "sts", *classify_aws_failure(error), api="sts.get_caller_identity"
                    ) from error
                verified = True
                phase = "acquisition"
                raw_records = inventory(ctx, service, resource_types)
                phase = "unknown"
                records = normalize_records(ctx, service, raw_records)
            phase = "input_validation"
            try:
                inputs.verify()
            except ValueError as error:
                raise ImportStageError(
                    "input_validation", "InputValidationFailed"
                ) from error
            phase = "unknown"
            files, sets = source_state(root, inputs)
            phase = "evidence"
            ctx.cleanup_failed = False
            evidence, value = acquired(
                root,
                identity,
                ctx,
                records,
                files,
                {identity},
                dry_run,
                source_sets=sets,
            )
            phase = "unknown"
            return {
                "status": "acquired" if acquisition_complete(value) else "incomplete",
                "scope": list(identity),
                "evidence": str(evidence),
                "records": records,
                "inventory": value["inventory"],
                "candidates": str(evidence.parent / "candidates"),
                "selection": str(evidence.parent / "selection.json"),
                "connection": value["connection"],
                "sts": value["sts"],
                "warnings": list(before.warnings),
                "model": "unchanged",
                "markdown": "not-run",
                "designValidation": "not-run",
                "dryRun": dry_run,
            }
        except Exception as error:
            if not verified or isinstance(error, ImportStageError):
                raise
            if phase == "acquisition" and isinstance(
                error, comparator().AcquisitionError
            ):
                failure = ImportStageError(
                    "acquisition",
                    error.code,
                    error.failure_category,
                    error.classification_source,
                    error.api,
                )
            else:
                failure = ImportStageError(phase, "UnknownError")
            failure.cleanup_failed = phase == "evidence" and ctx.cleanup_failed
            raise failure from error
        finally:
            inputs.close()


@task_read_scope
def review_inputs(root, identity, evidence, acquisition, inputs):
    Resolver = _imports_model_importing_references.Resolver
    unchanged(root, acquisition["sources"])
    unchanged_sets(root, acquisition["sourceSets"])
    before = before_model(model_path(root, identity), inputs)
    output, after = candidate_sources(root, evidence.parent / "candidates", before)
    selection_file, draft_file = (
        evidence.parent / "selection.json",
        evidence.parent / "review-input.json",
    )
    for file in (selection_file, draft_file):
        safe(evidence.parent, file)
    selection_text, draft_text = selection_file.read_bytes(), draft_file.read_bytes()
    selection, draft = json_read(selection_text), json_read(draft_text)
    if (
        not isinstance(draft, dict)
        or "risks" not in draft
        or set(draft) - {"risks", "referenceProvenance"}
        or "referenceProvenance" in draft
        and not isinstance(draft["referenceProvenance"], dict)
    ):
        raise ValueError(
            "IMPORT Review requires risks and optional complete referenceProvenance after map; flags grant no approval"
        )
    selected_records = selection_records(
        selection,
        acquisition["records"],
        before.authoritative,
        after.authoritative,
        property_schema,
    )
    proposed_references = draft.get(
        "referenceProvenance", import_approval.reference_provenance(before)
    )
    if proposed_references != import_approval.reference_provenance(after):
        raise ValueError(
            "IMPORT candidate reference map differs from the complete Review after map"
        )
    references = Resolver(
        root, identity[0], identity[1], local={identity[2]: after}, read_context=inputs
    )
    changes = verify_values(
        before, after, selected_records, property_schema, references
    )
    impact = replacement_inputs(before, selected_records, inputs)
    warnings = [
        {**warning, "phase": phase}
        for phase, items in (
            ("after", after.warnings),
            ("physical", references.warnings),
        )
        for warning in items
    ]
    specs = import_approval.reference_provenance(after)
    warnings = [*impact["warnings"], *warnings]
    for warning in warnings:
        warning.setdefault("phase", "incoming")
        key = warning.get(
            "consumerKey", warning.get("consumer_key", warning.get("key"))
        )
        if key:
            warning.setdefault("consumerKey", key)
            if key.startswith("desired.row."):
                warning.setdefault("resource", key.split(".")[2].rpartition("-")[0])
            elif key.startswith("desired.resource."):
                warning.setdefault("resource", key.split(".")[2])
            matching = sorted(
                identity
                for identity, spec in specs.items()
                if spec["consumerKey"] == key
                and spec.get("pointer") == warning.get("pointer")
            )
            if warning["phase"] == "physical":
                warning["referenceIds"] = matching
    impact["warnings"] = sorted(warnings, key=json_text)
    # Resolve physical and incoming dependencies before binding the final Review.
    for path in after.dependencies:
        if path not in after.files:
            inputs.read(path)
    impact["inputs"], impact["fileSets"] = source_state(root, inputs)
    review = import_approval.build_review(
        acquisition,
        selection,
        before,
        dict(after.authoritative),
        draft["risks"],
        property_schema,
        proposed_references=proposed_references,
        reference_impact=impact,
    )
    if comparator().redacted(review) != review:
        raise ValueError("IMPORT Review contains sensitive data")
    return (
        before,
        after,
        output,
        selection,
        review,
        changes,
        {selection_file: selection_text, draft_file: draft_text},
    )


@input_scope
@task_read_scope
def review_acquisition(
    root, environment, service, evidence, selector=None, dry_run=False
):
    root, evidence = root.resolve(), Path(evidence).absolute()
    target = target_for(root, environment, service, selector)
    identity = environment, target["directory"], service
    with (
        restrict(identity),
        read_consumers({identity}),
        input_context(),
        publication_lock(root, read_only=True),
    ):
        acquisition = read_acquisition(root, evidence, identity, dry_run)
        inputs = GenerationInputs(root)
        try:
            with task_reads(root), recording_inputs(inputs):
                _, _, _, _, review, _, external = review_inputs(
                    root, identity, evidence, acquisition, inputs
                )
            inputs.verify()
            if any(file.read_bytes() != raw for file, raw in external.items()):
                raise ValueError("IMPORT Review inputs changed during verification")
            destination = evidence.parent / "review.json"
            safe(evidence.parent, destination)
            atomic_files(
                {destination: json_text(review) + "\n"},
                staging_directory=evidence.parent,
            )
            return {
                "status": "reviewed",
                "review": review,
                "reviewFile": str(destination),
                "model": "unchanged",
                "markdown": "not-run",
                "designValidation": "not-run",
            }
        finally:
            inputs.close()


def _callback_publish_acquisition_current(
    acquisition,
    before,
    evidence,
    expected_task,
    external,
    identity,
    output,
    review_file,
    review_raw,
    root,
    /,
    changes,
):
    # GenerationInputs verifies these exact Task bytes live before the first save.
    with task_reads(root):
        if (
            task_contract.task_revision(root, selected=expected_task[0])
            != expected_task
        ):
            raise ValueError("IMPORT Task changed before publication")
        unchanged(root, acquisition["sources"])
        unchanged_sets(root, acquisition["sourceSets"])
        if (
            candidate_sources(root, evidence.parent / "candidates", before)[0] != output
            or any(file.read_bytes() != raw for file, raw in external.items())
            or review_file.read_bytes() != review_raw
            or read_acquisition(root, evidence, identity, False) != acquisition
        ):
            raise ValueError(
                "IMPORT candidate, selection, acquisition or Review changed before publication"
            )
        record_outputs(root, identity, set(changes), set())


def _callback_publish_acquisition_finish_model(
    acquisition,
    after,
    before,
    evidence,
    external,
    identity,
    review_file,
    review_raw,
    root,
    /,
):
    if (
        read_acquisition(root, evidence, identity, False) != acquisition
        or any(file.read_bytes() != raw for file, raw in external.items())
        or review_file.read_bytes() != review_raw
        or candidate_sources(root, evidence.parent / "candidates", before)[1].files
        != after.files
    ):
        raise ValueError(
            "IMPORT candidate, selection, acquisition or Review changed during publication"
        )


@input_scope
@task_read_scope
def publish_acquisition(
    root, environment, service, evidence, selector=None, dry_run=False
):
    root, evidence = root.resolve(), Path(evidence).absolute()
    target = target_for(root, environment, service, selector)
    identity = environment, target["directory"], service
    with (
        restrict(identity),
        read_consumers({identity}),
        input_context(),
        publication_lock(root, read_only=True) as journal,
    ):
        acquisition = read_acquisition(root, evidence, identity, dry_run)
        if not acquisition_complete(acquisition):
            raise ValueError("IMPORT publication requires complete acquisition")
        review_file = evidence.parent / "review.json"
        safe(evidence.parent, review_file)
        if not review_file.is_file():
            raise ValueError(
                "IMPORT publication requires review.json containing the complete current Review"
            )
        review_raw = review_file.read_bytes()
        reviewed = json_read(review_raw)
        import_approval.verify_review(reviewed, reviewed)
        inputs = GenerationInputs(root)
        context = None
        try:
            with task_reads(root), recording_inputs(inputs):
                before, after, output, selection, expected, changes, external = (
                    review_inputs(root, identity, evidence, acquisition, inputs)
                )
                import_approval.verify_review(reviewed, expected)
                document = (
                    root
                    / DESIGNS_DIRECTORY
                    / identity[0]
                    / identity[1]
                    / (identity[2] + ".md")
                )
                managed = owned_artifacts(document, before.values)
                display_error = None
                try:
                    views, view_originals = view_plan(
                        document, after.values, root, managed
                    )
                except (OSError, ValueError, KeyError, TypeError) as error:
                    views = {}
                    display_error = str(error)
                inputs.verify()
            if dry_run:
                return {
                    "status": "dry-run",
                    "review": expected,
                    "model": "unchanged",
                    "markdown": "not-run",
                }
            import_approval.review_binding(expected, acquisition)
            record_outputs(root, identity, set(output), set(views))
            expected_task = inputs.expected_task
            current = _bind_framework_callback(
                _callback_publish_acquisition_current,
                acquisition,
                before,
                evidence,
                expected_task,
                external,
                identity,
                output,
                review_file,
                review_raw,
                root,
            )
            selected_records = selection_records(
                selection,
                acquisition["records"],
                before.authoritative,
                after.authoritative,
                property_schema,
            )
            if pending_items(
                selection, selected_records, after.values, property_schema
            ):
                raise ValueError("IMPORT has unresolved items; publication refused")
            if not expected["completion"]["propertiesResolved"]:
                raise ValueError("IMPORT properties are unresolved")
            finish_model = _bind_framework_callback(
                _callback_publish_acquisition_finish_model,
                acquisition,
                after,
                before,
                evidence,
                external,
                identity,
                review_file,
                review_raw,
                root,
            )
            owner = {
                "task": expected_task[0],
                "workflow": "import",
                "scope": list(identity),
            }
            context = SourceWriteContext._authorized(
                root,
                inputs,
                SimpleNamespace(action="import"),
                current,
                frozenset(output),
                import_owner=owner,
                finish=finish_model,
            )
            plan = prepare_edit(before, output, context)
            publish_edit(plan, context)
            result = {
                "status": "saved",
                "model": "reflected" if output else "unchanged",
                "markdown": "not-run",
                "designValidation": "not-run",
                "warnings": list(after.warnings),
                "changes": changes,
            }
            if display_error is None:
                try:
                    changed, candidate = candidate_sources(
                        root, evidence.parent / "candidates", after
                    )
                    if (
                        task_contract.task_revision(
                            root, selected=expected_task[0], live=True
                        )
                        != expected_task
                        or read_acquisition(root, evidence, identity, False)
                        != acquisition
                        or any(
                            file.read_bytes() != raw for file, raw in external.items()
                        )
                        or review_file.read_bytes() != review_raw
                        or changed
                        or candidate.files != after.files
                        or any(
                            (file.read_bytes() if file.is_file() else None) != raw
                            for file, raw in view_originals.items()
                        )
                    ):
                        raise ValueError(
                            "IMPORT display inputs changed before publication"
                        )
                    if views:
                        _publish_transaction(
                            root,
                            {p: text for p, text in views.items() if text is not None},
                            {p for p, text in views.items() if text is None},
                            journal,
                            import_owner=owner,
                        )
                    result.update(
                        status="complete",
                        markdown="generated" if views else "unchanged",
                    )
                except (OSError, ValueError) as error:
                    display_error = str(error)
            if display_error is not None:
                result.update(
                    status="display-failed",
                    markdown="retained" if document.is_file() else "not-generated",
                    viewComplete=False,
                    displayError=display_error,
                )
            return result
        finally:
            if context is not None:
                context.close()
            else:
                inputs.close()


def _callback_recover_transaction_authorize(
    acquisition,
    evidence,
    expected_task,
    identity,
    publication_revision,
    name,
    root,
    revision,
    /,
    record,
):
    with task_reads(root, live=True):
        if record.get("importOwner") != {
            "task": name,
            "workflow": "import",
            "scope": list(identity),
        }:
            raise ValueError(
                "pending transaction belongs to a different Task or is not an Import transaction"
            )
        if (
            task_contract.task_revision(root, selected=name) != expected_task
            or publication_revision(root, name) != revision
            or read_acquisition(root, evidence, identity, False) != acquisition
        ):
            raise ValueError("Import recovery Task/Worktree/acquisition changed")
        paths = {root / relative for relative in record["originals"]}
        sources = {path for path in paths if path.is_relative_to(root / "model")}
        record_outputs(root, identity, sources, paths - sources)


@input_scope
@task_read_scope
def recover_transaction(
    root, environment, service, evidence, selector=None, dry_run=False
):
    """Restore only this Task's interrupted source/display transaction, with no AWS calls."""
    publication_revision = repository.publication_revision
    if dry_run:
        raise ValueError("a dry-run acquisition cannot authorize transaction recovery")
    root, evidence = root.resolve(), Path(evidence).absolute()
    target = target_for(root, environment, service, selector)
    identity = environment, target["directory"], service
    with restrict(identity), read_consumers({identity}), input_context():
        contract_scope(root, {identity})
        acquisition = read_acquisition(root, evidence, identity, False)
        if not acquisition_complete(acquisition):
            raise ValueError(
                "IMPORT transaction recovery requires complete acquisition"
            )
        name = workflow(root)
        revision = publication_revision(root, name)
        expected_task = task_contract.task_revision(root, selected=name)
        authorize = _bind_framework_callback(
            _callback_recover_transaction_authorize,
            acquisition,
            evidence,
            expected_task,
            identity,
            publication_revision,
            name,
            root,
            revision,
        )
        with publication_lock(root, recovery_check=authorize, import_recovery=True):
            pass
        return {"status": "recovered", "aws": "not-contacted", "scope": list(identity)}


@input_scope
@task_read_scope
def recover_display(root, environment, service, evidence, selector=None):
    root, evidence = root.resolve(), Path(evidence).absolute()
    target = target_for(root, environment, service, selector)
    identity = environment, target["directory"], service
    with (
        restrict(identity),
        read_consumers({identity}),
        input_context(),
        publication_lock(root, read_only=True) as journal,
    ):
        contract_scope(root, {identity})
        acquisition = read_acquisition(root, evidence, identity, False)
        if not acquisition_complete(acquisition):
            raise ValueError("IMPORT display recovery requires complete acquisition")
        name = workflow(root)
        base = repository.task_start_commit(root, name)
        if base is None:
            raise ValueError("IMPORT display recovery requires a Task baseline")
        review_file = evidence.parent / "review.json"
        safe(evidence.parent, review_file)
        review_raw = review_file.read_bytes()
        reviewed = json_read(review_raw)
        import_approval.verify_review(reviewed, reviewed)
        import_approval.review_binding(reviewed, acquisition)
        with tempfile.TemporaryDirectory(
            prefix="import-display-baseline-"
        ) as directory:
            baseline = Path(directory).resolve()
            import_guard.archive_sources(
                root,
                base,
                ["model", PROJECT_FILENAME, "infra/cloudformation"],
                baseline,
            )
            # Task contracts can be untracked. Use only the live contracts, whose
            # original bytes and file set are checked by the acquisition and Review.
            contracts = task_contract.contract_snapshot(root)
            (baseline / "tasks").mkdir()
            for task in contracts.tasks:
                (baseline / task.name).write_bytes(task.raw)
            with (
                selected_task(baseline, name),
                mapping_alias(definition_root(root), baseline),
                task_reads(baseline),
            ):
                if any(
                    item["base"] == "tasks"
                    for item in reviewed["referenceImpact"]["fileSets"]
                ):
                    task_contract.contract_snapshot(baseline)
                old_inputs = GenerationInputs(baseline)
                try:
                    with recording_inputs(old_inputs):
                        before, after, _, selection, expected, _, external = (
                            review_inputs(
                                baseline, identity, evidence, acquisition, old_inputs
                            )
                        )
                        import_approval.verify_review(reviewed, expected)
                        old_inputs.verify()
                    if pending_items(
                        selection,
                        selection_records(
                            selection,
                            acquisition["records"],
                            before.authoritative,
                            after.authoritative,
                            property_schema,
                        ),
                        after.values,
                        property_schema,
                    ):
                        raise ValueError("IMPORT display recovery has unresolved items")
                    document = (
                        root
                        / DESIGNS_DIRECTORY
                        / environment
                        / identity[1]
                        / (service + ".md")
                    )
                    managed = owned_artifacts(document, before.values)
                finally:
                    old_inputs.close()
        inputs = GenerationInputs(root)
        try:
            with task_reads(root), recording_inputs(inputs):
                current = load_model(model_path(root, identity), inputs)
                changed, candidate = candidate_sources(
                    root, evidence.parent / "candidates", current
                )
                approved_files = {
                    root / file.relative_to(baseline): text
                    for file, text in after.files.items()
                }
                if (
                    changed
                    or candidate.files != current.files
                    or current.files != approved_files
                ):
                    raise ValueError(
                        "IMPORT saved Model differs from approved candidate"
                    )
                output, originals = view_plan(document, current.values, root, managed)
            record_outputs(root, identity, set(), set(output))
            inputs.verify()
            if (
                read_acquisition(root, evidence, identity, False) != acquisition
                or review_file.read_bytes() != review_raw
                or any(file.read_bytes() != raw for file, raw in external.items())
                or any(
                    (file.read_bytes() if file.is_file() else None) != raw
                    for file, raw in originals.items()
                )
            ):
                raise ValueError(
                    "IMPORT display recovery inputs changed before publication"
                )
            if output:
                _publish_transaction(
                    root,
                    {p: text for p, text in output.items() if text is not None},
                    {p for p, text in output.items() if text is None},
                    journal,
                    import_owner={
                        "task": name,
                        "workflow": "import",
                        "scope": list(identity),
                    },
                )
            return {
                "status": "complete",
                "markdown": "generated" if output else "unchanged",
            }
        finally:
            inputs.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "acquire",
            "review",
            "publish",
            "resume",
            "recover-display",
            "recover-transaction",
        ),
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target")
    parser.add_argument("--service", required=True)
    parser.add_argument("--task-file")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-profile", action="store_true")
    parser.add_argument("--resource-type", action="append")
    args = parser.parse_args(argv)
    if args.action != "acquire" and (args.no_profile or args.resource_type):
        parser.error("--no-profile and --resource-type apply only to acquisition")
    functions = {
        "acquire": acquire,
        "review": review_acquisition,
        "publish": publish_acquisition,
        "resume": resume_acquisition,
        "recover-display": recover_display,
        "recover-transaction": recover_transaction,
    }
    try:
        with selected_task(args.repository_root, args.task_file):
            kwargs = {"selector": args.target}
            if args.action == "acquire":
                kwargs.update(
                    dry_run=args.dry_run,
                    no_profile=args.no_profile,
                    resource_types=args.resource_type,
                )
            else:
                if args.evidence is None:
                    raise ValueError("IMPORT action requires its original --evidence")
                kwargs.update(evidence=args.evidence)
                if args.action != "recover-display":
                    kwargs["dry_run"] = args.dry_run
            result = functions[args.action](
                args.repository_root, args.environment, args.service, **kwargs
            )
        print(
            json.dumps(
                result, ensure_ascii=True, allow_nan=False, separators=(",", ":")
            )
        )
        return (
            3
            if result.get("status") == "display-failed"
            else 2
            if result.get("status") == "incomplete"
            else 0
        )
    except ImportStageError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "phase": error.phase,
                    "api": error.api,
                    "code": error.code,
                    "failureCategory": error.category,
                    "classificationSource": error.source,
                    "evidence": None,
                    "model": "unchanged",
                    **(
                        {"cleanup": "failed"}
                        if getattr(error, "cleanup_failed", False)
                        else {}
                    ),
                },
                ensure_ascii=True,
            )
        )
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=True))
        return 1
