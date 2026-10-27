"""Typed design references; identity lookup belongs to model.identity.Resolver."""

import json
import re
from dataclasses import dataclass

from utils.json_format import strict_json
from utils.reference_contracts import reference_context

from model.core import ModelNeedsFixError
from model.reference_values import reference_value
from model.reference_values import resolve as resolve


@dataclass(frozen=True)
class ReferenceNode:
    logical_id: str
    attribute: str
    pointer: str = ""


def is_reference(value):
    return isinstance(value, dict) and "$modelRef" in value


def parse(value, pointer=""):
    body = value.get("$modelRef") if isinstance(value, dict) else None
    details = {"pointer": pointer}
    if isinstance(body, dict):
        for source, name in (
            ("logicalId", "targetLogicalId"),
            ("attribute", "attribute"),
        ):
            if isinstance(body.get(source), str):
                details[name] = body[source]
    if not is_reference(value) or set(value) != {"$modelRef"}:
        raise ModelNeedsFixError(
            f"invalid $modelRef object: JSON Pointer={pointer!r}",
            code="MODEL_REF_INVALID_SYNTAX",
            **details,
        )
    body = value["$modelRef"]
    if not isinstance(body, dict) or set(body) != {"logicalId", "attribute"}:
        raise ModelNeedsFixError(
            f"$modelRef requires exactly logicalId and attribute: JSON Pointer={pointer!r}",
            code="MODEL_REF_INVALID_SYNTAX",
            **details,
        )
    for key in ("logicalId", "attribute"):
        if (
            not isinstance(body[key], str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", body[key]) is None
        ):
            raise ModelNeedsFixError(
                f"invalid $modelRef {key}: JSON Pointer={pointer!r}",
                code="MODEL_REF_INVALID_SYNTAX",
                **details,
            )
    return ReferenceNode(body["logicalId"], body["attribute"], pointer)


def nodes(value, pointer="", *, errors=None):
    """Enumerate atomic nodes, including JSON encoded inside a string."""
    if is_reference(value):
        try:
            yield parse(value, pointer)
        except ModelNeedsFixError as error:
            if errors is None:
                raise
            errors.extend(error.diagnostics)
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from nodes(
                child,
                pointer + "/" + key.replace("~", "~0").replace("/", "~1"),
                errors=errors,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from nodes(child, pointer + "/" + str(index), errors=errors)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            encoded = strict_json(value)
        except ValueError:
            return
        yield from nodes(encoded, pointer, errors=errors)


def receiving_property(property_name, pointer):
    path = property_name
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if token.startswith("Fn::"):
            break
        path += "[]" if token.isdigit() else "." + token
    return path


def context_at(value, property_name, pointer, context=None):
    """Select context by the exact JSON position, with zero-based pointer indexes."""
    path = property_name
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, str):
            value = strict_json(value)
        if isinstance(value, dict):
            context = reference_context(path, value, context)
            value = value[token]
            path += "." + token
        else:
            value = value[int(token)]
            path += "[]"
    return context


def reference_document(node):
    """Reproduce the existing Model reference declaration for a display leaf."""
    return {"$modelRef": {"logicalId": node.logical_id, "attribute": node.attribute}}


def project(value, render=None, pointer=""):
    """Copy a tree for display; never alter Desired or design JSON."""
    if is_reference(value):
        node = parse(value, pointer)
        return render(node) if render else "unresolved"
    if isinstance(value, dict):
        return {
            key: project(
                child, render, pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            project(child, render, pointer + "/" + str(index))
            for index, child in enumerate(value)
        ]
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            encoded = strict_json(value)
        except ValueError:
            return value
        displayed = project(encoded, render, pointer)
        return (
            value if displayed == encoded else json.dumps(displayed, ensure_ascii=False)
        )
    return value


def display_value(resolver, scope, node):
    result = reference_value(resolver, scope, node)
    return (
        result.value
        if result.status == "resolved"
        else "PENDING_DEPLOY"
        if result.status == "pending_deploy"
        else result.status
    )
