#!/usr/bin/env python3
"""Check or refresh the CloudFormation provider schemas used by this blueprint."""

from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.request
import zipfile
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any

import utils.aws_mappings as _imports_utils_aws_mappings
import utils.aws_schemas as _imports_utils_aws_schemas
from utils.cloudformation.format import boolean_literal
from utils.input_cache import input_bytes, input_select, input_text
from utils.json_format import canonical_json

REGION = "ap-northeast-1"
SOURCE_URL = (
    f"https://schema.cloudformation.{REGION}.amazonaws.com/CloudformationSchema.zip"
)
IDENTIFIER_OUTPUT = "IDENTIFIER_OUTPUT"

# The pinned provider schemas omit these API character constraints.
# https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreateRole.html
# https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateSecurityGroup.html
DESCRIPTION_PATTERNS = {
    (
        "AWS::IAM::Role",
        "Description",
    ): r"\A[\u0009\u000A\u000D\u0020-\u007E\u00A1-\u00FF]*\Z",
    (
        "AWS::EC2::SecurityGroup",
        "GroupDescription",
    ): r"\A[a-zA-Z0-9 ._:/()#,@\[\]+=&;{}!$*\-]*\Z",
}

# Supported SSM secure string slots; paths retain array wildcards.
SSM_SECURE_PROPERTIES = {
    "Resources/AWS::DirectoryService::MicrosoftAD/Properties/Password",
    "Resources/AWS::DirectoryService::SimpleAD/Properties/Password",
    "Resources/AWS::ElastiCache::ReplicationGroup/Properties/AuthToken",
    "Resources/AWS::IAM::User/Properties/LoginProfile/Password",
    "Resources/AWS::KinesisFirehose::DeliveryStream/Properties/RedshiftDestinationConfiguration/Password",
    "Resources/AWS::OpsWorks::App/Properties/AppSource/Password",
    "Resources/AWS::OpsWorks::Stack/Properties/RdsDbInstances/*/DbPassword",
    "Resources/AWS::OpsWorks::Stack/Properties/CustomCookbooksSource/Password",
    "Resources/AWS::RDS::DBCluster/Properties/MasterUserPassword",
    "Resources/AWS::RDS::DBInstance/Properties/MasterUserPassword",
    "Resources/AWS::Redshift::Cluster/Properties/MasterUserPassword",
}

DYNAMIC_REFERENCE_START = re.compile(r"\{\{\s*resolve\b")
DYNAMIC_REFERENCE = re.compile(r"\{\{resolve:([^{}]*)\}\}")
SECRETS_MANAGER_REFERENCE = re.compile(
    r"(?:arn:[a-z0-9-]+:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:)?[a-zA-Z0-9/_+=.@-]+"
    r"(?::(?P<fields>[^\r\n]*))?"
)


def aws_type(material: Path) -> str:
    return "AWS::" + material.stem.replace("_", "::", 1)


def design_type(material: Path) -> str:
    return material.stem.replace("_", ".", 1)


def material_files(root: Path) -> list[Path]:
    definition_root = _imports_utils_aws_mappings.definition_root
    root = definition_root(root)
    return sorted(
        input_select(root / "framework" / "materials" / "aws", "*.properties")
    )


def manifest_text(root: Path, files: list[Path]) -> str:
    return "".join(
        f"{hashlib.sha256(input_bytes(path)).hexdigest()}  {path.relative_to(root).as_posix()}\n"
        for path in files
    )


class CloudFormationSchemaCatalog:
    def __init__(self, root: Path, *, definitions=None) -> None:
        schemas_for = _imports_utils_aws_schemas.schemas_for
        self.root = root
        self.definitions = definitions if definitions is not None else schemas_for(root)
        self.directory = self.definitions.directory
        self.resource_types = dict(self.definitions.resource_types)
        self.schemas: dict[str, dict[str, Any]] = {}
        self._schema_lock = Lock()

    @staticmethod
    def canonical_type(resource_type: str) -> str:
        return (
            resource_type
            if resource_type.startswith("AWS::")
            else "AWS::" + resource_type.replace(".", "::", 1)
        )

    def schema(self, resource_type: str) -> dict[str, Any]:
        resource_type = self.canonical_type(resource_type)
        with self._schema_lock:
            if resource_type not in self.schemas:
                # The public catalog permits local overrides; isolate each resource once.
                self.schemas[resource_type] = deepcopy(
                    self.definitions.cloudformation(resource_type)
                )
            return self.schemas[resource_type]

    @staticmethod
    def _pointer(document: dict[str, Any], reference: str) -> Any:
        node: Any = document
        for part in reference[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def _resolve(self, document: dict[str, Any], node: Any) -> Any:
        seen: set[str] = set()
        while isinstance(node, dict) and str(node.get("$ref", "")).startswith("#/"):
            reference = node["$ref"]
            if reference in seen:
                break
            seen.add(reference)
            target = self._pointer(document, reference)
            node = {
                **target,
                **{key: value for key, value in node.items() if key != "$ref"},
            }
        return node

    def property_schema(self, resource_type: str, property_path: str) -> dict[str, Any]:
        document = self.schema(resource_type)
        node: Any = document
        for raw_part in property_path.split("."):
            is_array = raw_part.endswith("[]")
            name = raw_part.removesuffix("[]")
            node = self._resolve(document, node)
            candidates = [node] if isinstance(node, dict) else []
            if isinstance(node, dict):
                for keyword in ("allOf", "anyOf", "oneOf"):
                    candidates.extend(
                        self._resolve(document, item) for item in node.get(keyword, [])
                    )
            matches = [
                candidate["properties"][name]
                for candidate in candidates
                if isinstance(candidate, dict)
                and name in candidate.get("properties", {})
            ]
            if not matches:
                raise KeyError(f"{resource_type}.{property_path}")
            node = self._resolve(document, matches[0])
            if is_array:
                array_candidates = [node] if isinstance(node, dict) else []
                if isinstance(node, dict):
                    for keyword in ("allOf", "anyOf", "oneOf"):
                        array_candidates.extend(
                            self._resolve(document, item)
                            for item in node.get(keyword, [])
                        )
                arrays = [
                    candidate
                    for candidate in array_candidates
                    if isinstance(candidate, dict) and candidate.get("type") == "array"
                ]
                if not arrays:
                    raise KeyError(
                        f"{resource_type}.{property_path}: [] used for non-array"
                    )
                node = self._resolve(document, arrays[0].get("items", {}))
        if not isinstance(node, dict):
            raise KeyError(f"{resource_type}.{property_path}")
        return node

    def required_properties(self, resource_type: str) -> set[str]:
        schema = self.schema(resource_type)
        return set(schema.get("required", []))

    def literal_errors(
        self, resource_type: str, property_path: str, raw_value: str
    ) -> list[str]:
        node = self.property_schema(resource_type, property_path)
        expected = node.get("type")
        if expected == "string" or (
            isinstance(expected, list) and "string" in expected
        ):
            dynamic_errors = self._dynamic_reference_errors(
                resource_type, property_path, raw_value
            )
            if dynamic_errors is not None:
                # AWS resolves references at deployment; their text is not the property value.
                return dynamic_errors
        errors = self._literal_errors(node, raw_value)
        pattern = DESCRIPTION_PATTERNS.get(
            (self.canonical_type(resource_type), property_path)
        )
        if pattern and not errors:
            errors.extend(
                self._literal_errors({"type": "string", "pattern": pattern}, raw_value)
            )
        return errors

    def _dynamic_reference_errors(
        self, resource_type: str, property_path: str, raw_value: str
    ) -> list[str] | None:
        if DYNAMIC_REFERENCE_START.search(raw_value) is None:
            return None
        if DYNAMIC_REFERENCE_START.search(DYNAMIC_REFERENCE.sub("", raw_value)):
            return ["invalid CloudFormation dynamic reference syntax"]
        resource_type = self.canonical_type(resource_type)
        if (
            resource_type.startswith("AWS::EC2::")
            and property_path.split(".")[-1] == "UserData"
        ):
            return ["CloudFormation dynamic references are unsupported in EC2 UserData"]
        for match in DYNAMIC_REFERENCE.finditer(raw_value):
            kind, _, target = match[1].partition(":")
            if kind == "secretsmanager":
                secret = SECRETS_MANAGER_REFERENCE.fullmatch(target)
                if secret is None or target.endswith("\\"):
                    return ["invalid Secrets Manager dynamic reference syntax"]
                fields = (
                    secret["fields"].split(":") if secret["fields"] is not None else []
                )
                if len(fields) > 4 or (
                    fields and fields[0] not in {"", "SecretString"}
                ):
                    return ["invalid Secrets Manager dynamic reference syntax"]
                if len(fields) == 4 and fields[2] and fields[3]:
                    return ["invalid Secrets Manager dynamic reference syntax"]
            elif kind in {"ssm", "ssm-secure"}:
                if re.fullmatch(r"[a-zA-Z0-9_.\-/]+(?::[0-9]+)?", target) is None:
                    return ["invalid SSM dynamic reference syntax"]
                if kind == "ssm-secure":
                    path = (
                        "Resources/"
                        + resource_type
                        + "/Properties/"
                        + property_path.replace("[]", "/*").replace(".", "/")
                    )
                    if path not in SSM_SECURE_PROPERTIES:
                        return [
                            "SSM secure dynamic reference is unsupported for this resource property"
                        ]
            else:
                return ["unsupported CloudFormation dynamic reference provider"]
        return []

    def _literal_errors(self, node: dict[str, Any], raw_value: str) -> list[str]:
        if raw_value.lower() in {
            "n/a",
            "none",
            "not-used",
            "not used",
            "unset",
            "unused",
            "未使用",
        } and raw_value not in node.get("enum", []):
            return [
                "unused optional properties must be omitted instead of using a sentinel value"
            ]
        expected_type = node.get("type")
        if isinstance(expected_type, list):
            alternatives = [
                self._literal_errors({**node, "type": kind}, raw_value)
                for kind in expected_type
            ]
            if any(not errors for errors in alternatives):
                return []
            return [
                f"must satisfy one of {expected_type}",
                *dict.fromkeys(error for errors in alternatives for error in errors),
            ]
        value: Any = raw_value
        try:
            if expected_type == "boolean":
                value = boolean_literal(raw_value)
            elif expected_type == "integer":
                if re.fullmatch(r"-?\d+", raw_value) is None:
                    raise ValueError
                value = int(raw_value)
            elif expected_type == "number":
                value = float(raw_value)
            elif expected_type in {"array", "object", "null"}:
                value = json.loads(raw_value)
        except (ValueError, json.JSONDecodeError):
            return [f"must be {expected_type}"]

        actual_types = {
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
            "null": value is None,
        }
        errors: list[str] = []
        if expected_type in actual_types and not actual_types[expected_type]:
            errors.append(f"must be {expected_type}")
            return errors
        if "enum" in node and value not in node["enum"]:
            errors.append(f"must be one of {node['enum']}")
        if "const" in node and value != node["const"]:
            errors.append(f"must equal {node['const']!r}")
        if isinstance(value, str):
            if "minLength" in node and len(value) < node["minLength"]:
                errors.append(f"length must be >= {node['minLength']}")
            if "maxLength" in node and len(value) > node["maxLength"]:
                errors.append(f"length must be <= {node['maxLength']}")
            pattern = node.get("pattern")
            if pattern:
                try:
                    if re.search(pattern, value) is None:
                        errors.append(f"must match {pattern}")
                except re.error:
                    pass  # Provider regex dialect may exceed Python regular expressions.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in node and value < node["minimum"]:
                errors.append(f"must be >= {node['minimum']}")
            if "maximum" in node and value > node["maximum"]:
                errors.append(f"must be <= {node['maximum']}")
        return errors


def refresh(root: Path) -> None:
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
        archive = response.read()
    selected = {aws_type(path) for path in material_files(root)}
    schemas: dict[str, tuple[str, dict[str, Any]]] = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        for filename in source.namelist():
            if not filename.endswith(".json"):
                continue
            schema = json.loads(source.read(filename))
            if schema.get("typeName") in selected:
                schemas[schema["typeName"]] = (Path(filename).name, schema)
    missing = sorted(selected - schemas.keys())
    if missing:
        raise RuntimeError(f"provider schemas missing: {', '.join(missing)}")

    directory = root / "framework" / "materials" / "cloudformation-schema" / REGION
    directory.mkdir(parents=True, exist_ok=True)
    index = {
        "region": REGION,
        "resourceTypes": {
            resource_type: schemas[resource_type][0]
            for resource_type in sorted(schemas)
        },
        "source": SOURCE_URL,
    }
    expected = {"index.json", *(filename for filename, _ in schemas.values())}
    for stale in input_select(directory, "*.json"):
        if stale.name not in expected:
            stale.unlink()
    (directory / "index.json").write_text(canonical_json(index), encoding="utf-8")
    for filename, schema in schemas.values():
        (directory / filename).write_text(canonical_json(schema), encoding="utf-8")

    schema_files = sorted(input_select(directory, "*.json"))
    metadata = {
        "schema.archiveSha256": hashlib.sha256(archive).hexdigest(),
        "schema.manifest": "framework/materials/cloudformation-schema.sha256",
        "schema.region": REGION,
        "schema.resourceTypeCount": str(len(schemas)),
        "schema.source": "AWS CloudFormation resource provider schemas",
        "schema.sourceUrl": SOURCE_URL,
    }
    (root / "framework" / "materials" / "cloudformation-schema.properties").write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(metadata.items())),
        encoding="utf-8",
    )
    (root / "framework" / "materials" / "cloudformation-schema.sha256").write_text(
        manifest_text(root, schema_files), encoding="utf-8"
    )


def snapshot_errors(root: Path) -> list[str]:
    errors: list[str] = []
    metadata_path = (
        root / "framework" / "materials" / "cloudformation-schema.properties"
    )
    manifest_path = root / "framework" / "materials" / "cloudformation-schema.sha256"
    try:
        metadata = dict(
            line.split("=", 1)
            for line in input_text(metadata_path, encoding="utf-8").splitlines()
            if "=" in line
        )
        catalog = CloudFormationSchemaCatalog(root)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as error:
        return [f"schema snapshot cannot be loaded: {error}"]

    selected = {aws_type(path) for path in material_files(root)}
    if set(catalog.resource_types) != selected:
        errors.append(
            "schema index resource types do not match framework/materials/aws"
        )
    if (
        metadata.get("schema.sourceUrl") != SOURCE_URL
        or metadata.get("schema.region") != REGION
    ):
        errors.append("schema provenance does not match the configured regional source")
    if metadata.get("schema.resourceTypeCount") != str(len(selected)):
        errors.append("schema.resourceTypeCount does not match framework/materials/aws")
    if re.fullmatch(r"[0-9a-f]{64}", metadata.get("schema.archiveSha256", "")) is None:
        errors.append("schema.archiveSha256 is invalid")

    schema_files = sorted(input_select(catalog.directory, "*.json"))
    expected_names = {"index.json", *catalog.resource_types.values()}
    if {path.name for path in schema_files} != expected_names:
        errors.append("schema snapshot files do not match index.json")
    try:
        if input_text(manifest_path, encoding="utf-8") != manifest_text(
            root, schema_files
        ):
            errors.append(
                "framework/materials/cloudformation-schema.sha256 does not match the schema snapshot"
            )
    except FileNotFoundError:
        errors.append("framework/materials/cloudformation-schema.sha256 is missing")

    for material in material_files(root):
        resource_type = design_type(material)
        prefix = resource_type + "."
        catalog_pointers: set[str] = set()
        identifier_outputs: set[str] = set()
        try:
            schema = catalog.schema(resource_type)
            if schema.get("typeName") != aws_type(material):
                errors.append(f"schema typeName mismatch: {resource_type}")
                continue
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as error:
            errors.append(f"schema cannot be loaded: {resource_type}: {error}")
            continue
        for line in input_text(material, encoding="utf-8").splitlines():
            key, separator, marker = line.partition("=")
            if (
                not separator
                or not key.startswith(prefix)
                or marker not in {"", IDENTIFIER_OUTPUT}
            ):
                errors.append(f"invalid catalog line: {resource_type}: {line}")
                continue
            property_path = key[len(prefix) :]
            try:
                catalog.property_schema(resource_type, property_path)
            except (KeyError, TypeError) as error:
                errors.append(
                    f"catalog property is absent from provider schema: {resource_type}.{property_path}: {error}"
                )
                continue
            pointer = "/properties/" + property_path.replace("[]", "").replace(".", "/")
            catalog_pointers.add(pointer)
            if marker == IDENTIFIER_OUTPUT:
                identifier_outputs.add(pointer)
            elif pointer in schema.get("readOnlyProperties", []):
                errors.append(
                    f"read-only catalog property lacks identifier marker: {resource_type}.{property_path}"
                )

        primary = set(schema.get("primaryIdentifier", []))
        read_only = set(schema.get("readOnlyProperties", []))
        expected_outputs = {
            pointer
            for pointer in primary & read_only
            if not pointer.rsplit("/", 1)[-1].lower().endswith("arn")
        }
        allowed_outputs = expected_outputs | {
            pointer
            for pointer in read_only
            if pointer.rsplit("/", 1)[-1].lower().endswith(("id", "identifier"))
        }
        for pointer in sorted(expected_outputs - identifier_outputs):
            errors.append(
                f"generated primary identifier is missing: {resource_type}: {pointer}"
            )
        for pointer in sorted(identifier_outputs - allowed_outputs):
            errors.append(f"invalid identifier output: {resource_type}: {pointer}")
        for pointer in sorted((primary - read_only) - catalog_pointers):
            errors.append(
                f"selected primary identifier is missing: {resource_type}: {pointer}"
            )
        for pointer in sorted(
            pointer
            for pointer in primary & read_only
            if pointer.rsplit("/", 1)[-1].lower().endswith("arn")
        ):
            if pointer in catalog_pointers:
                errors.append(
                    f"generated ARN primary identifier is forbidden: {resource_type}: {pointer}"
                )
    return errors
