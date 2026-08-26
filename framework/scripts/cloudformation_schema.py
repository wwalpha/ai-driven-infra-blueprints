#!/usr/bin/env python3
"""Check or refresh the CloudFormation provider schemas used by this blueprint."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


REGION = "ap-northeast-1"
SOURCE_URL = f"https://schema.cloudformation.{REGION}.amazonaws.com/CloudformationSchema.zip"
IDENTIFIER_OUTPUT = "IDENTIFIER_OUTPUT"


def aws_type(material: Path) -> str:
    return "AWS::" + material.stem.replace("_", "::", 1)


def design_type(material: Path) -> str:
    return material.stem.replace("_", ".", 1)


def material_files(root: Path) -> list[Path]:
    return sorted((root / "framework" / "materials" / "aws").glob("*.properties"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def manifest_text(root: Path, files: list[Path]) -> str:
    return "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n"
        for path in files
    )


class CloudFormationSchemaCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / "framework" / "materials" / "cloudformation-schema" / REGION
        index = json.loads((self.directory / "index.json").read_text(encoding="utf-8"))
        self.resource_types: dict[str, str] = index["resourceTypes"]
        self.schemas: dict[str, dict[str, Any]] = {}

    @staticmethod
    def canonical_type(resource_type: str) -> str:
        return resource_type if resource_type.startswith("AWS::") else "AWS::" + resource_type.replace(".", "::", 1)

    def schema(self, resource_type: str) -> dict[str, Any]:
        resource_type = self.canonical_type(resource_type)
        if resource_type not in self.schemas:
            filename = self.resource_types[resource_type]
            self.schemas[resource_type] = json.loads(
                (self.directory / filename).read_text(encoding="utf-8")
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
            node = {**target, **{key: value for key, value in node.items() if key != "$ref"}}
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
                    candidates.extend(self._resolve(document, item) for item in node.get(keyword, []))
            matches = [
                candidate["properties"][name]
                for candidate in candidates
                if isinstance(candidate, dict) and name in candidate.get("properties", {})
            ]
            if not matches:
                raise KeyError(f"{resource_type}.{property_path}")
            node = self._resolve(document, matches[0])
            if is_array:
                array_candidates = [node] if isinstance(node, dict) else []
                if isinstance(node, dict):
                    for keyword in ("allOf", "anyOf", "oneOf"):
                        array_candidates.extend(
                            self._resolve(document, item) for item in node.get(keyword, [])
                        )
                arrays = [
                    candidate
                    for candidate in array_candidates
                    if isinstance(candidate, dict) and candidate.get("type") == "array"
                ]
                if not arrays:
                    raise KeyError(f"{resource_type}.{property_path}: [] used for non-array")
                node = self._resolve(document, arrays[0].get("items", {}))
        if not isinstance(node, dict):
            raise KeyError(f"{resource_type}.{property_path}")
        return node

    def required_properties(self, resource_type: str) -> set[str]:
        schema = self.schema(resource_type)
        return set(schema.get("required", []))

    def literal_errors(self, resource_type: str, property_path: str, raw_value: str) -> list[str]:
        node = self.property_schema(resource_type, property_path)
        if raw_value.lower() in {"n/a", "none", "not-used", "not used", "unset", "unused", "未使用"} and raw_value not in node.get("enum", []):
            return ["unused optional properties must be omitted instead of using a sentinel value"]
        expected_type = node.get("type")
        value: Any = raw_value
        try:
            if expected_type == "boolean":
                if raw_value.lower() not in {"true", "false"}:
                    raise ValueError
                value = raw_value.lower() == "true"
            elif expected_type == "integer":
                if re.fullmatch(r"-?\d+", raw_value) is None:
                    raise ValueError
                value = int(raw_value)
            elif expected_type == "number":
                value = float(raw_value)
            elif expected_type in {"array", "object"}:
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
                    pass  # cfn-lint performs the authoritative template-level regex check.
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
        "resourceTypes": {resource_type: schemas[resource_type][0] for resource_type in sorted(schemas)},
        "source": SOURCE_URL,
    }
    expected = {"index.json", *(filename for filename, _ in schemas.values())}
    for stale in directory.glob("*.json"):
        if stale.name not in expected:
            stale.unlink()
    (directory / "index.json").write_text(canonical_json(index), encoding="utf-8")
    for filename, schema in schemas.values():
        (directory / filename).write_text(canonical_json(schema), encoding="utf-8")

    schema_files = sorted(directory.glob("*.json"))
    metadata = {
        "schema.archiveSha256": hashlib.sha256(archive).hexdigest(),
        "schema.manifest": "framework/materials/cloudformation-schema.sha256",
        "schema.region": REGION,
        "schema.resourceTypeCount": str(len(schemas)),
        "schema.source": "AWS CloudFormation resource provider schemas",
        "schema.sourceUrl": SOURCE_URL,
    }
    (root / "framework" / "materials" / "cloudformation-schema.properties").write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(metadata.items())), encoding="utf-8"
    )
    (root / "framework" / "materials" / "cloudformation-schema.sha256").write_text(
        manifest_text(root, schema_files), encoding="utf-8"
    )


def snapshot_errors(root: Path) -> list[str]:
    errors: list[str] = []
    metadata_path = root / "framework" / "materials" / "cloudformation-schema.properties"
    manifest_path = root / "framework" / "materials" / "cloudformation-schema.sha256"
    try:
        metadata = dict(
            line.split("=", 1)
            for line in metadata_path.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        catalog = CloudFormationSchemaCatalog(root)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as error:
        return [f"schema snapshot cannot be loaded: {error}"]

    selected = {aws_type(path) for path in material_files(root)}
    if set(catalog.resource_types) != selected:
        errors.append("schema index resource types do not match framework/materials/aws")
    if metadata.get("schema.sourceUrl") != SOURCE_URL or metadata.get("schema.region") != REGION:
        errors.append("schema provenance does not match the configured regional source")
    if metadata.get("schema.resourceTypeCount") != str(len(selected)):
        errors.append("schema.resourceTypeCount does not match framework/materials/aws")
    if re.fullmatch(r"[0-9a-f]{64}", metadata.get("schema.archiveSha256", "")) is None:
        errors.append("schema.archiveSha256 is invalid")

    schema_files = sorted(catalog.directory.glob("*.json"))
    expected_names = {"index.json", *catalog.resource_types.values()}
    if {path.name for path in schema_files} != expected_names:
        errors.append("schema snapshot files do not match index.json")
    try:
        if manifest_path.read_text(encoding="utf-8") != manifest_text(root, schema_files):
            errors.append("framework/materials/cloudformation-schema.sha256 does not match the schema snapshot")
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
        for line in material.read_text(encoding="utf-8").splitlines():
            key, separator, marker = line.partition("=")
            if not separator or not key.startswith(prefix) or marker not in {"", IDENTIFIER_OUTPUT}:
                errors.append(f"invalid catalog line: {resource_type}: {line}")
                continue
            property_path = key[len(prefix) :]
            try:
                catalog.property_schema(resource_type, property_path)
            except (KeyError, TypeError) as error:
                errors.append(f"catalog property is absent from provider schema: {resource_type}.{property_path}: {error}")
                continue
            pointer = "/properties/" + property_path.replace("[]", "").replace(".", "/")
            catalog_pointers.add(pointer)
            if marker == IDENTIFIER_OUTPUT:
                identifier_outputs.add(pointer)
            elif pointer in schema.get("readOnlyProperties", []):
                errors.append(f"read-only catalog property lacks identifier marker: {resource_type}.{property_path}")

        primary = set(schema.get("primaryIdentifier", []))
        read_only = set(schema.get("readOnlyProperties", []))
        expected_outputs = {
            pointer
            for pointer in primary & read_only
            if not pointer.rsplit("/", 1)[-1].lower().endswith("arn")
        }
        for pointer in sorted(expected_outputs - identifier_outputs):
            errors.append(f"generated primary identifier is missing: {resource_type}: {pointer}")
        for pointer in sorted(identifier_outputs - expected_outputs):
            errors.append(f"invalid identifier output: {resource_type}: {pointer}")
        for pointer in sorted((primary - read_only) - catalog_pointers):
            errors.append(f"selected primary identifier is missing: {resource_type}: {pointer}")
        for pointer in sorted(
            pointer for pointer in primary & read_only if pointer.rsplit("/", 1)[-1].lower().endswith("arn")
        ):
            if pointer in catalog_pointers:
                errors.append(f"generated ARN primary identifier is forbidden: {resource_type}: {pointer}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        refresh(args.repository_root)
    errors = snapshot_errors(args.repository_root)
    if errors:
        print("CloudFormation schema snapshot: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"CloudFormation schema snapshot: PASS ({len(material_files(args.repository_root))} resource types)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
