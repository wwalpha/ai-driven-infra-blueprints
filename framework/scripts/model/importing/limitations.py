"""Property limitations validated within the existing Import Selection and Review."""

import re
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aws_mapping import response_shape, runtime_registry
from design.catalog import DesignSchemaCatalog
from utils.aws_mappings import owners
from utils.aws_sdk import aws_runtime, sdk_for
from utils.property_path import definition_path
from utils.script_loader import module

from model.core import entries, resource_row_index

# Only explicit Mapping contracts with independently checked read-API absence qualify.
UNOBSERVABLE = {
    "LakeFormation.Resource.UseServiceLinkedRole": (
        "lakeformation",
        "describe_resource",
        "ResourceInfo.UseServiceLinkedRole",
        "REQUEST_INPUT_NOT_OBSERVABLE",
    ),
    "SQS.QueuePolicy.Id": (
        "sqs",
        "get_queue_attributes",
        "Id",
        "PROVIDER_OUTPUT_NOT_OBSERVABLE",
    ),
    "Glue.Table.Id": (
        "glue",
        "get_table",
        "Table.Id",
        "PROVIDER_OUTPUT_NOT_OBSERVABLE",
    ),
}

CONDITIONAL_CODE = {
    "Lambda.Function.Code.S3Bucket": "Code.ResolvedS3Object.S3Bucket",
    "Lambda.Function.Code.S3Key": "Code.ResolvedS3Object.S3Key",
}


def sensitive(resource: Any, prop: str) -> bool:
    return resource.module.sensitive(prop or "") or bool(
        re.search(
            r"password|credential|accesskey|secretstring|secretbinary|privatekey|token|authorization|username",
            prop or "",
            re.I,
        )
    )


def contract(root: Path, prop: str, status: str) -> dict[str, Any] | None:
    kind = ".".join(prop.split(".")[:2])
    service = owners(root).get(kind)
    if service is None:
        return None
    mapping = runtime_registry(root, service)
    mapped = mapping.properties.get(prop)
    if mapped is None or not mapped.include:
        return None
    reference = "framework/mappings/aws/" + service + ".yaml#" + prop
    if status == "unobservable" and prop in CONDITIONAL_CODE:
        path = CONDITIONAL_CODE[prop]
        getter = mapping.getters.get(mapped.field.getter, {})
        if (
            mapped.source != "aws"
            or mapped.field.classification != "supported"
            or mapped.field.getter != "base"
            or mapped.field.path != path
            or getter.get("kind") != "adapter"
        ):
            return None
        model = sdk_for(root).service_model("lambda")
        shape = model.operation_model("GetFunction").output_shape
        try:
            response_shape(shape, path)
        except ValueError:
            return None
        return {
            "status": "unobservable",
            "reasonCode": "OPTIONAL_CODE_SOURCE_NOT_RETURNED",
            "reason": "GetFunction did not return the optional code source; the existing value is not AWS verified",
            "evidence": {
                "mapping": reference,
                "api": "lambda.get_function",
                "missingPath": path,
            },
        }
    if status == "withheld":
        adapter = module("model/adapters/aws.py", "model.adapters.aws")
        if service not in adapter.SERVICES or not sensitive(
            SimpleNamespace(module=adapter.service_module(service)),
            prop,
        ):
            return None
        getter = mapping.getters.get(mapped.field.getter, {})
        reader = adapter.service_module(service)
        if (
            mapped.source != "aws"
            or mapped.field.classification != "supported"
            or not getter
        ):
            return None
        if getter["kind"] == "sdk" and (
            (getter["service"], getter["operation"]) not in reader.APIS
            or getattr(reader, "SDK_OPERATIONS", {}).get(kind) != getter["operation"]
            or not callable(getattr(reader, "fetch_sdk", None))
        ):
            return None
        if getter["kind"] == "adapter" and (
            kind not in getter["resources"]
            or not reader.APIS
            or not callable(getattr(reader, "fetch", None))
        ):
            return None
        if getter["kind"] == "cloudcontrol" and "read" not in DesignSchemaCatalog(
            root
        ).schema(kind).get("handlers", {}):
            return None
        return {
            "status": "withheld",
            "reasonCode": "SENSITIVE_VALUE_WITHHELD",
            "reason": "Value is withheld by the Import sensitive-property contract",
            "evidence": {"mapping": reference, "policy": "import-sensitive-property"},
        }
    if (
        status != "unobservable"
        or prop not in UNOBSERVABLE
        or mapped.source == "aws"
        or mapped.field.classification != "sdk_unavailable"
        or not mapped.constraint
    ):
        return None
    api, operation, path, reason_code = UNOBSERVABLE[prop]
    model = sdk_for(root).service_model(api)
    operation_name = aws_runtime().operation_name(model, operation)
    if operation_name is None:
        return None
    shape = model.operation_model(operation_name).output_shape
    try:
        response_shape(shape, path)
    except ValueError:
        return {
            "status": "unobservable",
            "reasonCode": reason_code,
            "reason": mapped.constraint,
            "evidence": {
                "mapping": reference,
                "api": api + "." + operation,
                "absentPath": path,
            },
        }
    return None


def required(root: Path, kind: str, prop: str) -> bool:
    catalog = DesignSchemaCatalog(root)
    path = definition_path(prop.removeprefix(kind + "."))
    parent, _, leaf = path.rpartition(".")
    schema = catalog.property_schema(kind, parent) if parent else catalog.schema(kind)
    return leaf.removesuffix("[]") in schema.get("required", ())


def row_state(values: Mapping[str, str], rid: str, prop: str) -> dict[str, str]:
    row_ids = {
        row_id
        for row_id, row in resource_row_index(values).get(rid, ())
        if row["property"] == prop
    }
    prefixes = tuple(
        f"{section}.row.{row_id}."
        for section in ("desired", "observed", "display")
        for row_id in row_ids
    )
    refs = {
        ref_id
        for ref_id, ref in entries(values, "desired.reference.")
        if any(
            ref.get("consumerKey", "").startswith(f"desired.row.{row_id}.")
            for row_id in row_ids
        )
    }
    prefixes += tuple(f"desired.reference.{ref_id}." for ref_id in refs)
    return {key: value for key, value in values.items() if key.startswith(prefixes)}


def validate(
    selection: dict[str, Any],
    selected: dict[str, Any],
    old: Mapping[str, str],
    new: Mapping[str, str],
    root: Path,
) -> list[dict[str, Any]]:
    items = selection.get("limitations", [])
    if not isinstance(items, list):
        raise ValueError("IMPORT limitations must be a list")
    by_record = {record["record"]: (rid, record) for rid, record in selected.items()}
    seen, validated = set(), []
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item) != {"record", "property", "reasonCode", "treatment", "reason"}
            or any(
                not isinstance(item[field], str) or not item[field].strip()
                for field in ("record", "property", "reasonCode", "treatment", "reason")
            )
        ):
            raise ValueError(
                "IMPORT limitation requires record/property/reasonCode/treatment/reason"
            )
        key = item["record"], item["property"]
        if key in seen or item["record"] not in by_record:
            raise ValueError("IMPORT duplicate limitation or unknown/unselected record")
        seen.add(key)
        rid, record = by_record[item["record"]]
        if not item["property"].startswith(record["kind"] + "."):
            raise ValueError(
                "IMPORT limitation Property belongs to another Resource Type"
            )
        capture = record["properties"].get(item["property"], {})
        expected = contract(root, item["property"], capture.get("status", ""))
        if (
            expected is None
            or capture != expected
            or item["reasonCode"] != expected["reasonCode"]
            or record.get("identityStatus", "known") != "known"
        ):
            raise ValueError(
                "IMPORT limitation is not eligible or its reason/evidence/identity differs"
            )
        if item["property"] in record.get("identityProperties", ()):
            raise ValueError("IMPORT limitation cannot waive identity")
        prior, proposed = (
            row_state(old, rid, item["property"]),
            row_state(new, rid, item["property"]),
        )
        if item["treatment"] == "retain_existing":
            if (
                record.get("_action") not in {"refresh", "bind", "replace"}
                or prior != proposed
                or not prior
                and required(root, record["kind"], item["property"])
            ):
                raise ValueError(
                    "IMPORT retain_existing requires unchanged existing IMPORT Rows or optional absence"
                )
        elif item["treatment"] == "omit_unobserved":
            if (
                record.get("_action") in {"refresh", "bind", "replace"}
                or prior
                or proposed
                or required(root, record["kind"], item["property"])
            ):
                raise ValueError(
                    "IMPORT omit_unobserved requires an absent optional Property on a new Resource"
                )
        else:
            raise ValueError("IMPORT invalid limitation treatment")
        selected[rid].setdefault("_limitations", []).append(item)
        validated.append(item)
    return validated
