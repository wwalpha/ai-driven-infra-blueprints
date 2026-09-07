"""Design catalogs: retain CFn schemas and add the pinned Macie Job API contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from cloudformation_schema import CloudFormationSchemaCatalog, manifest_text, material_files


MACIE_JOB = "Macie.ClassificationJob"


def design_material_files(root: Path) -> list[Path]:
    return sorted([*material_files(root), *(root / "framework/materials/api").glob("*.properties")])


class DesignSchemaCatalog(CloudFormationSchemaCatalog):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.api_schemas = {
            path.stem.replace("_", ".", 1): json.loads(path.read_text(encoding="utf-8"))
            for path in (root / "framework/materials/api").glob("*.json")
        }

    def schema(self, resource_type: str) -> dict:
        if resource_type in self.api_schemas:
            return self.api_schemas[resource_type]
        return super().schema(resource_type)

    def cloudformation_type(self, resource_type: str) -> str:
        if resource_type in self.api_schemas:
            raise ValueError(f"{resource_type}: CloudFormation unsupported; implementation remains incomplete if this resource is in scope")
        return super().schema(resource_type)["typeName"]

    def literal_errors(self, resource_type: str, property_path: str, raw_value: str) -> list[str]:
        if resource_type not in self.api_schemas:
            return super().literal_errors(resource_type, property_path, raw_value)
        node = self.property_schema(resource_type, property_path)
        try:
            value = raw_value if node.get("type") == "string" else json.loads(raw_value)
        except ValueError:
            return [f"{property_path}: must be {node.get('type')}"]
        return self.api_value_errors(resource_type, node, value, property_path)

    def api_value_errors(self, resource_type: str, node: dict, value, path: str) -> list[str]:
        """Validate the JSON Schema subset used by the pinned API snapshot."""
        node = self._resolve(self.schema(resource_type), node)
        expected = node.get("type")
        types = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
        if expected and type(value) is not types[expected]:
            return [f"{path}: must be {expected}"]
        errors = []
        if "enum" in node and value not in node["enum"]:
            errors.append(f"{path}: must be one of {node['enum']}")
        if "oneOf" in node and sum(not self.api_value_errors(resource_type, branch, value, path) for branch in node["oneOf"]) != 1:
            errors.append(f"{path}: must satisfy exactly one alternative")
        if isinstance(value, str):
            if path in self.schema(resource_type)["properties"] and value.lower() in {"n/a", "none", "not-used", "not used", "unset", "unused", "未使用"} and value not in node.get("enum", []):
                errors.append(f"{path}: omit unused optional properties instead of sentinel values")
            if "pattern" in node and re.search(node["pattern"], value) is None:
                errors.append(f"{path}: must match {node['pattern']}")
            bounds = ("minLength", "maxLength", len(value))
        elif isinstance(value, list):
            bounds = ("minItems", "maxItems", len(value))
            for index, item in enumerate(value):
                errors.extend(self.api_value_errors(resource_type, node["items"], item, f"{path}[{index}]"))
        elif isinstance(value, dict):
            bounds = ("minProperties", "maxProperties", len(value))
            for key in node.get("required", []):
                if key not in value:
                    errors.append(f"{path}.{key}: required property missing")
            for key, item in value.items():
                if "propertyNames" in node:
                    errors.extend(self.api_value_errors(resource_type, node["propertyNames"], key, f"{path} key"))
                child = node.get("properties", {}).get(key, node.get("additionalProperties", True))
                if child is False:
                    errors.append(f"{path}.{key}: unknown property")
                elif isinstance(child, dict):
                    errors.extend(self.api_value_errors(resource_type, child, item, f"{path}.{key}"))
        else:
            bounds = ("minimum", "maximum", value)
        lower, upper, size = bounds
        if lower in node and size < node[lower]:
            errors.append(f"{path}: {lower} must be >= {node[lower]}")
        if upper in node and size > node[upper]:
            errors.append(f"{path}: {upper} must be <= {node[upper]}")
        return errors

    def job_errors(self, values: dict) -> list[str]:
        """Cross-property API constraints; call after typed value validation."""
        errors = []
        if values.get("jobType") == "SCHEDULED" and "scheduleFrequency" not in values:
            errors.append("SCHEDULED requires scheduleFrequency")
        if values.get("jobType") == "ONE_TIME":
            for prop in ("scheduleFrequency", "initialRun"):
                if prop in values:
                    errors.append(f"ONE_TIME must omit {prop}")
        selector = values.get("managedDataIdentifierSelector", "RECOMMENDED")
        if selector in {"INCLUDE", "EXCLUDE"} and not values.get("managedDataIdentifierIds"):
            errors.append(f"{selector} requires managedDataIdentifierIds")
        if selector in {"ALL", "NONE", "RECOMMENDED"} and "managedDataIdentifierIds" in values:
            errors.append(f"{selector} must omit managedDataIdentifierIds")
        if selector == "NONE" and not values.get("customDataIdentifierIds"):
            errors.append("NONE requires customDataIdentifierIds")
        scoping = values.get("s3JobDefinition", {}).get("scoping", {})
        for block in scoping.values():
            for term in block.get("and", []):
                simple = term.get("simpleScopeTerm", {})
                key = simple.get("key")
                if key:
                    operators = {"OBJECT_EXTENSION": {"EQ", "NE"}, "OBJECT_KEY": {"STARTS_WITH"}}.get(
                        key, {"EQ", "NE", "GT", "GTE", "LT", "LTE"}
                    )
                    if simple.get("comparator") not in operators:
                        errors.append(f"{key}: invalid comparator")
                    if key in {"OBJECT_SIZE", "OBJECT_LAST_MODIFIED_DATE"} and len(simple.get("values", [])) != 1:
                        errors.append(f"{key}: requires exactly one value")
        return errors


def api_snapshot_errors(root: Path) -> list[str]:
    directory = root / "framework/materials/api"
    files = sorted(directory.glob("*"))
    try:
        catalog = DesignSchemaCatalog(root)
        if {path.name for path in files} != {"Macie_ClassificationJob.json", "Macie_ClassificationJob.properties"}:
            return ["API design catalog must contain the registered Macie Job snapshot and selection list"]
        if (root / "framework/materials/api-catalog.sha256").read_text(encoding="utf-8") != manifest_text(root, files):
            return ["API design catalog checksum mismatch"]
        schema = catalog.schema(MACIE_JOB)
        source = schema["source"]
        if schema["resourceType"] != MACIE_JOB or schema["cloudFormationType"] is not None:
            return ["Macie Job must be an API design type without a CloudFormation type"]
        if catalog.canonical_type(MACIE_JOB) in catalog.resource_types:
            return ["Macie Job API and CloudFormation catalogs overlap; explicit migration required"]
        if source["operation"] != "CreateClassificationJob" or source["apiVersion"] != "2020-01-01" or not re.fullmatch(r"[0-9a-f]{64}", source["modelSha256"]):
            return ["invalid Macie API snapshot provenance"]
        if schema["identifierOutputs"] != ["jobId"] or {"clientToken", "jobArn"} & schema["properties"].keys():
            return ["Macie catalog must separate jobId from runtime token and generated ARN"]
        selected = (directory / "Macie_ClassificationJob.properties").read_text(encoding="utf-8").splitlines()
        expected = [f"{MACIE_JOB}.{key}=" + ("IDENTIFIER_OUTPUT" if key == "jobId" else "") for key in sorted(schema["properties"])]
        if selected != expected:
            return ["Macie API selection list does not match its design schema"]
        for key in schema["properties"]:
            catalog.property_schema(MACIE_JOB, key)
    except (OSError, KeyError, ValueError, TypeError) as error:
        return [f"API design snapshot cannot be loaded: {error}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write-lock", action="store_true")
    parser.add_argument("--cloudformation-type", help="Resolve a selected design type; reject API-only and unknown types")
    args = parser.parse_args()
    if args.write_lock:
        files = sorted((args.repository_root / "framework/materials/api").glob("*"))
        (args.repository_root / "framework/materials/api-catalog.sha256").write_text(manifest_text(args.repository_root, files), encoding="utf-8")
    errors = api_snapshot_errors(args.repository_root)
    if not errors and args.cloudformation_type:
        try:
            print(DesignSchemaCatalog(args.repository_root).cloudformation_type(args.cloudformation_type))
        except (KeyError, ValueError) as error:
            errors.append(str(error))
    print("API design catalog: " + ("FAIL" if errors else "PASS"))
    for error in errors:
        print(f"- {error}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
