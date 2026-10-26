"""Immutable Mapping data and lexical SDK paths without registry initialization."""

import re
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType

from utils.json_format import exact
from utils.yaml_format import yaml_read as yaml_read

NORMALIZATIONS = frozenset(
    {
        "typed",
        "set",
        "name",
        "id",
        "arn",
        "policy",
        "kms",
        "iam_role",
        "dns",
        "log_group_arn",
        "boolean",
        "number",
        "string",
        "protocol",
        "json",
    }
)


def text(value, label):
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or re.search(r"\b(?:TODO|unimplemented)\b", value, re.I)
    ):
        raise ValueError(f"{label}: concrete nonempty text required")
    return value


def response_shape(shape, path):
    """Validate exact SDK casing and explicit [] traversal, without AWS access."""
    for part in text(path, "AWS path").split("."):
        array = part.endswith("[]")
        name = part[:-2] if array else part
        if shape.type_name != "structure" or name not in shape.members:
            raise ValueError(f"unknown SDK response path: {path}")
        shape = shape.members[name]
        if array:
            if shape.type_name != "list":
                raise ValueError(f"SDK path is not an array: {path}")
            shape = shape.member
    return shape


@dataclass(frozen=True)
class Identity:
    getter: str
    id_path: str
    arn_path: str | None
    name_property: str | None


@dataclass(frozen=True)
class Property:
    field: object
    include: bool
    show: bool
    name: str
    source: str
    constraint: str = ""
    transform: str = "identity"
    environment: object = None


def readonly(value):
    if isinstance(value, dict):
        return MappingProxyType({key: readonly(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(readonly(item) for item in value)
    return value


@dataclass(frozen=True, init=False)
class Registry:
    root: Path
    service: str
    resource_types: frozenset
    adapter_resource_types: frozenset
    getters: object
    identities: object
    properties: object
    fields: object

    def __init__(self, root, service, document, properties):
        result = {
            key: replace(
                prop, field=replace(prop.field, default=readonly(prop.field.default))
            )
            for key, prop in properties.items()
        }
        values = {
            "root": Path(root),
            "service": service,
            "resource_types": frozenset(document["resourceTypes"]),
            "adapter_resource_types": frozenset(
                resource
                for definition in document["getters"].values()
                if definition["kind"] == "adapter"
                for resource in definition["resources"]
            ),
            "getters": readonly(document["getters"]),
            "identities": MappingProxyType(
                {
                    resource: Identity(
                        value["identity"]["getter"],
                        value["identity"]["idPath"],
                        value["identity"]["arnPath"],
                        value["identity"]["nameProperty"],
                    )
                    for resource, value in document["resourceTypes"].items()
                    if "identity" in value
                }
            ),
            "properties": MappingProxyType(result),
            "fields": MappingProxyType(
                {key: prop.field for key, prop in result.items() if prop.include}
            ),
        }
        for key, value in values.items():
            object.__setattr__(self, key, value)

    def at_root(self, root):
        """Bind caller context without copying or revalidating static definitions."""
        result = object.__new__(Registry)
        for key, value in vars(self).items():
            object.__setattr__(result, key, Path(root) if key == "root" else value)
        return result


def mapping_path(root, service):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", text(service, "service")):
        raise ValueError("invalid Mapping service")
    return Path(root) / "framework/mappings/aws" / (service + ".yaml")


@dataclass(frozen=True)
class EnvironmentDefinition:
    path: tuple
    encoding: str
    value_path: tuple = ()
    plaintext: bool = False
    type_field: str = "Type"
    keys: tuple = ()


def path_tokens(path):
    if path == "$":
        return ()
    if (
        not isinstance(path, str)
        or re.fullmatch(
            r"(?:\[\]|\*|[A-Za-z][A-Za-z0-9_]*(?:\[\])?)(?:\.(?:\*|[A-Za-z][A-Za-z0-9_]*(?:\[\])?))*",
            path,
        )
        is None
    ):
        raise ValueError("invalid environment Value path: " + str(path))
    return tuple(re.findall(r"[A-Za-z][A-Za-z0-9_]*|\[\]|\*", path))


def definition(raw):
    """Reject unknown metadata identically in executable and catalog Mapping loads."""
    if not isinstance(raw, dict):
        raise ValueError("environment definition must be an object")
    encoding = raw.get("encoding")
    required = {"path", "encoding"}
    if encoding == "json":
        required.add("valuePath")
    elif encoding == "glue":
        required.add("keys")
    elif encoding != "value":
        raise ValueError("unknown environment encoding")
    exact(
        raw,
        required
        | ({"plaintext"} if "plaintext" in raw else set())
        | ({"typeField"} if "typeField" in raw else set()),
        "environment",
    )
    if type(raw.get("plaintext", False)) is not bool:
        raise ValueError("environment plaintext must be boolean")
    path = path_tokens(raw["path"])
    value_path = path_tokens(raw["valuePath"]) if encoding == "json" else ()
    if encoding == "json" and value_path not in (("[]", "Value"), ("[]", "value")):
        raise ValueError("encoded environment array requires [].Value")
    if raw.get("typeField", "Type") not in {"Type", "type"}:
        raise ValueError("unknown environment type field")
    keys = raw.get("keys", [])
    if encoding == "glue" and (
        not isinstance(keys, list)
        or not keys
        or any(
            not isinstance(key, str) or not key.startswith("--customer-")
            for key in keys
        )
        or len(set(keys)) != len(keys)
    ):
        raise ValueError(
            "environment argument keys must be explicit customer arguments"
        )
    return EnvironmentDefinition(
        path,
        encoding,
        value_path,
        raw.get("plaintext", False),
        raw.get("typeField", "Type"),
        tuple(keys),
    )


def validate_definition(catalog, kind, prop, spec):
    """Verify real provider positions; only encoded string contents have virtual paths."""
    if spec is None:
        return
    schema = catalog.schema(kind)
    node = catalog.property_schema(kind, prop)
    for index, token in enumerate(spec.path):
        node = catalog._resolve(schema, node)
        if token == "[]":
            if node.get("type") != "array":
                raise ValueError("environment Value path is not an array")
            node = node.get("items", {})
        elif token == "*":
            if node.get("type") != "object":
                raise ValueError("environment Value path is not a typed map")
            if isinstance(node.get("additionalProperties"), dict):
                node = node["additionalProperties"]
            elif len(node.get("patternProperties", {})) == 1:
                node = next(iter(node["patternProperties"].values()))
            else:
                raise ValueError("environment Value path is not a typed map")
        else:
            if token in node.get("properties", {}):
                node = node["properties"][token]
            elif (
                spec.encoding == "json"
                and index == len(spec.path) - 1
                and node.get("type") == "object"
                and node.get("additionalProperties", True) is not False
            ):
                node = {"type": "string"}
            else:
                raise ValueError("unknown environment Value path component: " + token)
    node = catalog._resolve(schema, node)
    if spec.encoding == "glue":
        if node.get("type") != "object":
            raise ValueError("environment arguments require an object")
    elif node.get("type") != "string":
        raise ValueError("environment Value path must select a string")
