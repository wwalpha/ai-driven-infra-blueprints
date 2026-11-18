"""Property limitations validated within the existing Import Selection and Review."""

import re
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aws_mapping import response_shape, runtime_registry
from design.catalog import DesignSchemaCatalog
from services.registry import REGISTRY
from utils.aws_mappings import owners
from utils.aws_sdk import aws_runtime, sdk_for
from utils.property_path import definition_path
from utils.script_loader import module

from model.core import entries, resource_row_index


# Only explicit Mapping contracts with independently checked read-API absence qualify.
def conditional_capture(prop: str):
    kind = ".".join(prop.split(".")[:2])
    capture = REGISTRY.import_profile(kind).conditional_capture
    return capture if capture and prop in capture.paths else None


def missing_leaf(response: Any, path: str) -> bool:
    """Prove a scalar leaf is absent under an intact object path."""
    parts = path.split(".")
    if not path or any(
        not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts
    ):
        return False
    parent = response
    for part in parts[:-1]:
        if not isinstance(parent, dict) or part not in parent:
            return False
        parent = parent[part]
    return isinstance(parent, dict) and parts[-1] not in parent


def sensitive(resource: Any, prop: str) -> bool:
    return resource.module.sensitive(prop or "") or bool(
        re.search(
            r"password|credential|accesskey|secretstring|secretbinary|privatekey|token|authorization|username",
            prop or "",
            re.I,
        )
    )


def response_structure(value: Any, schema: dict[str, Any]) -> bool:
    """Accept only structures fully described by an unambiguous provider schema."""
    if any(key in schema for key in ("$ref", "oneOf", "anyOf", "allOf")):
        return False
    kind = schema.get("type", "object" if "properties" in schema else None)
    if kind == "object":
        fields = schema.get("properties", {})
        return (
            isinstance(value, dict)
            and set(schema.get("required", ())) <= value.keys()
            and all(
                key in fields and response_structure(item, fields[key])
                for key, item in value.items()
            )
        )
    if kind == "array":
        return (
            isinstance(value, list)
            and bool(schema.get("items"))
            and all(response_structure(item, schema["items"]) for item in value)
        )
    types = {
        "string": (str,),
        "boolean": (bool,),
        "integer": (int,),
        "number": (int, float),
    }
    return type(value) in types.get(kind, ())


def sdk_shapes(root: Path, getter: Any, path: str) -> tuple[Any, Any] | None:
    """Resolve an optional scalar leaf through the exact SDK result and Mapping path."""
    if any(
        not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in path.split(".")
    ):
        return None
    model = sdk_for(root).service_model(getter["service"])
    name = aws_runtime().operation_name(model, getter["operation"])
    if name is None:
        return None
    output = model.operation_model(name).output_shape
    try:
        result = (
            output
            if getter["result"] == "$"
            else response_shape(output, getter["result"])
        )
        parent_path, _, leaf = path.rpartition(".")
        parent = response_shape(result, parent_path) if parent_path else result
        shape = response_shape(result, path)
    except (ValueError, AttributeError):
        return None
    if leaf in parent.required_members or shape.type_name not in {
        "string",
        "boolean",
        "integer",
        "long",
        "float",
        "double",
    }:
        return None
    return output, result


def sdk_response(root: Path, getter: Any, response: Any) -> bool:
    """Validate SDK output and transport status using the operation's output shape."""
    if not isinstance(response, dict):
        return False
    model = sdk_for(root).service_model(getter["service"])
    name = aws_runtime().operation_name(model, getter["operation"])
    if name is None:
        return False
    output = model.operation_model(name).output_shape
    metadata = response.get("ResponseMetadata", {})
    if not isinstance(metadata, dict):
        return False
    statuses = [
        response[key]
        for key, shape in output.members.items()
        if shape.serialization.get("location") == "statusCode" and key in response
    ]
    if "HTTPStatusCode" in metadata:
        statuses.append(metadata["HTTPStatusCode"])
    if any(type(status) is not int or not 200 <= status < 300 for status in statuses):
        return False
    payload = {
        key: value for key, value in response.items() if key != "ResponseMetadata"
    }
    return not aws_runtime().ParamValidator().validate(payload, output).has_errors()


def sdk_omission(root: Path, getter: Any, response: Any, path: str) -> bool:
    """Validate the whole SDK response before accepting an absent optional leaf."""
    shapes = sdk_shapes(root, getter, path)
    if shapes is None or not sdk_response(root, getter, response):
        return False
    result = response
    if getter["result"] != "$":
        for part in getter["result"].split("."):
            if not isinstance(result, dict) or part not in result:
                return False
            result = result[part]
    return missing_leaf(result, path)


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
    if status == "not_returned":
        getter = mapping.getters.get(mapped.field.getter, {})
        if (
            mapped.source != "aws"
            or mapped.field.classification != "supported"
            or getter.get("kind") not in {"cloudcontrol", "sdk"}
            or mapped.transform != "identity"
            or required(root, kind, prop)
            or (
                sdk_shapes(root, getter, mapped.field.path) is None
                if getter.get("kind") == "sdk"
                else not missing_leaf({}, mapped.field.path)
            )
            or sensitive(
                SimpleNamespace(module=SimpleNamespace(sensitive=lambda _: False)), prop
            )
        ):
            return None
        return {
            "status": status,
            "reasonCode": "OPTIONAL_PROPERTY_NOT_RETURNED",
            "reason": "Successful identified Get omitted an optional Property; existing values are not AWS verified",
            "evidence": {
                "mapping": reference,
                "getter": mapped.field.getter,
                "path": mapped.field.path,
            },
        }
    if status == "unobservable" and (conditional := conditional_capture(prop)):
        return conditional.contract(
            root,
            conditional.paths[prop],
            mapped,
            mapping.getters.get(mapped.field.getter, {}),
            reference,
        )
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
    unobservable = REGISTRY.import_profile(kind).unobservable.get(prop)
    if (
        status != "unobservable"
        or unobservable is None
        or mapped.source == "aws"
        or mapped.field.classification != "sdk_unavailable"
        or not mapped.constraint
    ):
        return None
    api, operation, path, reason_code = unobservable
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


def conditional_code_capture(
    root: Path, prop: str, response: Any, identity: Any
) -> dict[str, Any] | None:
    """Classify only a successful, identified Zip response with a missing source field."""
    conditional = conditional_capture(prop)
    if conditional is None:
        raise ValueError("Lambda code-source contract or response is invalid")
    return conditional.capture(
        conditional.paths[prop].rsplit(".", 1)[1],
        response,
        identity,
        contract(root, prop, "unobservable"),
    )


def valid_capture(
    root: Path, prop: str, capture: dict[str, Any], record: dict[str, Any]
) -> bool:
    if capture.get("status") == "not_returned":
        expected = contract(root, prop, "not_returned")
        if expected is None:
            return False
        expected["evidence"]["identity"] = record.get("identity")
        return capture == expected and bool(record.get("identity"))
    conditional = conditional_capture(prop)
    if conditional is None:
        return contract(root, prop, capture.get("status", "")) == capture
    return conditional.valid(
        prop, capture, record, partial(contract, root, prop, "unobservable")
    )


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
            or not valid_capture(root, item["property"], capture, record)
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
                or conditional_capture(item["property"]) is not None
                and not prior
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
