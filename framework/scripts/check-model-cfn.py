#!/usr/bin/env python3
"""Read-only desired-model / CloudFormation comparison for explicitly selected services."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re

from design_catalog import DesignSchemaCatalog
from design_layout import resource_mode, resource_name_fields
from model_design import LINK, entries, properties, stack_model
from model_files import model_parts, read_model
from policy_tables import JSON_LINK, invalid_constant, literal, unique_object


class Unknown(ValueError):
    """An input cannot be compared without inventing a decision or reading AWS."""


@dataclass(frozen=True)
class Reference:
    stack: str
    logical_id: str
    attribute: str = "Ref"


def read_json(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def safe_path(root, path):
    path = path.absolute()
    if not path.is_relative_to(root) or path.resolve() != path:
        raise Unknown(f"unsafe input path: {path}")
    return path


def at_path(document, path, resolve=lambda value: value):
    """Keep array order and cardinality; never zip away missing elements."""
    nodes = [document]
    for part in path.split("."):
        array = part.endswith("[]")
        key = part.removesuffix("[]")
        next_nodes = []
        for node in nodes:
            node = resolve(node) if isinstance(node, dict) and any(
                k == "Ref" or k.startswith("Fn::") for k in node) else node
            if not isinstance(node, dict) or key not in node:
                raise KeyError(path)
            value = resolve(node[key]) if array else node[key]
            if array:
                if not isinstance(value, list):
                    raise Unknown(f"non-array at {path}")
                next_nodes.extend(value)
            else:
                next_nodes.append(value)
        nodes = next_nodes
    return nodes


def equal(left, right):
    if isinstance(left, Reference) or isinstance(right, Reference):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


class Comparison:
    def __init__(self, root, environment, directory, services, decoder=None):
        self.root = root.resolve()
        self.environment, self.directory = environment, directory
        self.services = services
        project = read_json((self.root / "project.json").read_text(encoding="utf-8"))
        targets = [t for t in project["targets"] if t["environment"] == environment
                   and t.get("alias", t["awsAccountId"]) == directory]
        if len(targets) != 1 or targets[0]["iacEngine"] != "cloudformation":
            raise Unknown("select exactly one CloudFormation target from project.json")
        self.target = targets[0]
        if not services or len(set(services)) != len(services) or any(
                not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", s) or s == "cloudformation-stacks"
                for s in services):
            raise Unknown("select unique, explicit design service IDs")
        self.catalog = DesignSchemaCatalog(self.root)
        self.base = self.root / "model" / environment / directory
        self.models, self.sources = {}, {}
        self.units, self.resources, self.exports = {}, {}, defaultdict(list)
        self.matches, self.matching = {}, set()
        self.findings, self.checked, self.excluded = [], 0, []
        if decoder is None:
            from cfnlint.decode import decode
            decoder = decode
        self.decoder = decoder

    def location(self, node, path):
        mark = getattr(node, "start_mark", None)
        return {"path": path.relative_to(self.root).as_posix(),
                "line": mark.line + 1 if mark else 1}

    def finding(self, status, service, resource, prop, reason, source=None, **details):
        self.findings.append(dict(status=status, service=service, resource=resource,
                                  property=prop, reason=reason, model=source, **details))

    def model(self, service):
        if service not in self.models:
            path = safe_path(self.root, self.base / f"{service}.properties")
            values = properties(read_model(path))
            metadata = entries(values, "desired.service.")
            if len(metadata) != 1 or metadata[0][1].get("serviceId") != service:
                raise Unknown(f"service metadata does not match {service}")
            self.models[service] = values
            for part in model_parts(path):
                for number, line in enumerate(part.read_text(encoding="utf-8").splitlines(), 1):
                    if line and not line.startswith("#"):
                        self.sources[service, line.partition("=")[0]] = {
                            "path": part.relative_to(self.root).as_posix(), "line": number}
        return self.models[service]

    def load_stacks(self):
        path = safe_path(self.root, self.base / "cloudformation-stacks.properties")
        _, stacks = stack_model(properties(read_model(path)))
        for _, stack in stacks:
            name = stack["name"]
            template = safe_path(self.root, self.root / "infra/cloudformation/templates" /
                                 self.target.get("alias", "") / stack["template"])
            inputs = safe_path(self.root, self.root / "infra/cloudformation/parameters" /
                               self.environment / self.directory / stack["parameters"])
            document, errors = self.decoder(str(template))
            if errors or not isinstance(document, dict) or document.get("Transform"):
                raise Unknown(f"invalid or Transform template: {template.relative_to(self.root)}")
            declarations = document.get("Parameters", {})
            supplied = read_json(inputs.read_text(encoding="utf-8"))
            if not isinstance(supplied, list) or any(not isinstance(p, dict) or
                    set(p) != {"ParameterKey", "ParameterValue"} or
                    not isinstance(p["ParameterKey"], str) or not isinstance(p["ParameterValue"], str)
                    for p in supplied):
                raise Unknown(f"explicit parameter array required: {inputs.relative_to(self.root)}")
            parameters = {p["ParameterKey"]: p["ParameterValue"] for p in supplied}
            if len(parameters) != len(supplied) or parameters.keys() - declarations.keys():
                raise Unknown(f"duplicate or undeclared parameter: {inputs.relative_to(self.root)}")
            for key, declaration in declarations.items():
                if key not in parameters:
                    if "Default" not in declaration:
                        raise Unknown(f"missing parameter: {name}/{key}")
                    parameters[key] = declaration["Default"]
                kind = declaration["Type"]
                if kind.startswith("AWS::SSM::Parameter::Value"):
                    raise Unknown(f"SSM parameter needs AWS current value: {name}/{key}")
                if kind == "Number":
                    parameters[key] = read_json(str(parameters[key]))
                elif kind == "CommaDelimitedList" or kind.startswith("List<"):
                    value = parameters[key]
                    parameters[key] = [p.strip() for p in value.split(",")] if isinstance(value, str) else value
                    if kind == "List<Number>":
                        parameters[key] = [read_json(str(v)) for v in parameters[key]]
                else:
                    parameters[key] = str(parameters[key])
            parameters.update({"AWS::AccountId": self.target["awsAccountId"],
                               "AWS::Region": self.target["awsRegion"], "AWS::StackName": name})
            self.units[name] = {"document": document, "parameters": parameters, "path": template}
        for name, unit in self.units.items():
            for output in unit["document"].get("Outputs", {}).values():
                if "Export" in output:
                    export = self.resolve(output["Export"]["Name"], name)
                    if not isinstance(export, str):
                        raise Unknown(f"non-string Export name: {name}")
                    self.exports[export].append((name, output))
        for name, unit in self.units.items():
            for logical_id, resource in unit["document"].get("Resources", {}).items():
                if "Condition" not in resource or self.condition(resource["Condition"], name):
                    self.resources[name, logical_id] = resource

    def condition(self, name, stack, seen=frozenset()):
        result = self.resolve({"Condition": name}, stack, seen)
        if type(result) is not bool:
            raise Unknown(f"non-boolean Condition: {name}")
        return result

    def resolve(self, value, stack, seen=frozenset()):
        if isinstance(value, list):
            return [self.resolve(v, stack, seen) for v in value]
        if not isinstance(value, dict):
            return value
        keys = [k for k in value if k == "Ref" or k == "Condition" or k.startswith("Fn::")]
        if not keys:
            return {k: self.resolve(v, stack, seen) for k, v in value.items()}
        if len(value) != 1:
            raise Unknown("invalid intrinsic expression")
        key, argument = next(iter(value.items()))
        unit = self.units[stack]
        if key == "Ref":
            if argument in unit["parameters"]:
                return unit["parameters"][argument]
            if argument in unit["document"].get("Resources", {}):
                return Reference(stack, argument)
            raise Unknown(f"unresolved Ref: {argument}")
        if key == "Fn::GetAtt":
            parts = argument.split(".", 1) if isinstance(argument, str) else argument
            if len(parts) == 2 and parts[0] in unit["document"].get("Resources", {}):
                return Reference(stack, *parts)
        if key == "Fn::ImportValue":
            export = self.resolve(argument, stack, seen)
            candidates = self.exports.get(export, []) if isinstance(export, str) else []
            marker = ("export", export)
            if len(candidates) != 1 or marker in seen:
                raise Unknown(f"unresolved, ambiguous or cyclic ImportValue: {export}")
            producer, output = candidates[0]
            if "Condition" in output and not self.condition(output["Condition"], producer):
                raise Unknown(f"inactive Export: {export}")
            return self.resolve(output["Value"], producer, seen | {marker})
        if key == "Fn::Sub":
            text, variables = (argument, {}) if isinstance(argument, str) else argument
            def replace(match):
                name = match.group(1)
                if name.startswith("!"):
                    return "${" + name[1:] + "}"
                result = self.resolve(variables[name], stack, seen) if name in variables else self.resolve(
                    {"Fn::GetAtt": name} if "." in name else {"Ref": name}, stack, seen)
                if isinstance(result, (dict, list, Reference)):
                    raise Unknown(f"generated value inside Sub: {name}")
                return str(result)
            return re.sub(r"\$\{([^}]+)\}", replace, text)
        if key == "Condition":
            marker = ("condition", stack, argument)
            if marker in seen:
                raise Unknown(f"cyclic Condition: {argument}")
            expression = unit["document"].get("Conditions", {}).get(argument)
            if expression is None:
                raise Unknown(f"missing Condition: {argument}")
            return self.resolve(expression, stack, seen | {marker})
        if key == "Fn::If":
            return self.resolve(argument[1 if self.condition(argument[0], stack, seen) else 2], stack, seen)
        resolved = self.resolve(argument, stack, seen)
        if key == "Fn::Equals":
            return equal(*resolved)
        if key in {"Fn::And", "Fn::Or", "Fn::Not"} and all(type(v) is bool for v in resolved):
            return not resolved[0] if key == "Fn::Not" else all(resolved) if key == "Fn::And" else any(resolved)
        if key == "Fn::Join" and isinstance(resolved[0], str) and all(isinstance(v, str) for v in resolved[1]):
            return resolved[0].join(resolved[1])
        if key == "Fn::Split" and all(isinstance(v, str) for v in resolved):
            return resolved[1].split(resolved[0])
        if key == "Fn::Select":
            index = int(resolved[0])
            if index < 0 or index >= len(resolved[1]):
                raise Unknown("Select index out of range")
            return resolved[1][index]
        raise Unknown(f"unsupported intrinsic: {key}")

    def rows(self, service, identity):
        return [(key, row) for key, row in entries(self.model(service), "desired.row.")
                if key.startswith(identity + "-")]

    def match(self, service, identity):
        key = service, identity
        if key in self.matches:
            return self.matches[key]
        if key in self.matching:
            raise Unknown("cyclic resource identity")
        self.matching.add(key)
        try:
            resource = dict(entries(self.model(service), "desired.resource."))[identity]
            kind = self.catalog.cloudformation_type(resource["resourceType"])
            exact = [r for r in self.resources if r[1] == resource["logicalId"]]
            names = resource_name_fields(resource["resourceType"])
            name_rows = [(row["property"][len(resource["resourceType"]) + 1:], row)
                         for _, row in self.rows(service, identity)
                         if row["property"].startswith(resource["resourceType"] + ".")
                         and row["property"][len(resource["resourceType"]) + 1:] in names]
            candidates = exact
            if name_rows:
                if len(name_rows) != 1:
                    raise Unknown("resource name is not unique")
                field, row = name_rows[0]
                expected = literal(row["value"])
                named = []
                for ref, candidate in self.resources.items():
                    if candidate.get("Type") != kind:
                        continue
                    props = candidate.get("Properties", {})
                    try:
                        values = [t["Value"] for t in props.get("Tags", []) if t.get("Key") == "Name"] if (
                            field == "Name" and resource["resourceType"] in NAME_TAG_TYPES) else at_path(props, field)
                        if len(values) == 1 and self.resolve(values[0], ref[0]) == expected:
                            named.append(ref)
                    except (KeyError, ValueError, TypeError, IndexError):
                        continue
                if named:
                    candidates = named
            if len(candidates) != 1:
                raise Unknown(f"resource correspondence unresolved ({len(candidates)} candidates)")
            if candidates[0] in self.matches.values():
                raise Unknown("multiple design resources map to the same CFn resource")
            self.matches[key] = candidates[0]
            return candidates[0]
        finally:
            self.matching.remove(key)

    def expected(self, service, identity, field, row):
        if "document" in row:
            return read_json(row["document"])
        raw = literal(row["value"])
        if JSON_LINK.fullmatch(raw):
            raise Unknown("policy JSON missing authoritative desired document")
        if link := LINK.fullmatch(raw):
            relative = Path(link.group(2))
            if relative.is_absolute() or relative.parent != Path(".") or relative.suffix not in {"", ".md"}:
                raise Unknown("reference must point to a same-target service model")
            owner = relative.stem if link.group(2) else service
            referenced = [(i, r) for i, r in entries(self.model(owner), "desired.resource.")
                          if r.get("anchor") == link.group(3)]
            if len(referenced) != 1 or resource_mode(referenced[0][1]) != "CREATE":
                raise Unknown("unresolved or IMPORT design reference")
            target_id, target_resource = referenced[0]
            target_stack, target_logical = self.match(owner, target_id)
            schema = self.catalog.schema(target_resource["resourceType"])
            if "arn" in field.lower():
                attrs = [p.rsplit("/", 1)[-1] for p in schema.get("readOnlyProperties", [])
                         if "arn" in p.rsplit("/", 1)[-1].lower()]
                if len(attrs) != 1:
                    raise Unknown("ARN reference attribute is ambiguous")
                return Reference(target_stack, target_logical, attrs[0])
            leaf = field.rsplit(".", 1)[-1].removesuffix("[]")
            identifier = {p.rsplit("/", 1)[-1] for p in schema.get("primaryIdentifier", [])}
            aliases = {"Subnets": "SubnetId", "SubnetIds": "SubnetId",
                       "SecurityGroupIds": "GroupId", "KmsKeyId": "KeyId", "TargetKeyId": "KeyId"}
            if len(identifier) != 1 or aliases.get(leaf, leaf) not in identifier:
                raise Unknown("reference does not identify an unambiguous Ref return value")
            return Reference(target_stack, target_logical)
        resource = dict(entries(self.model(service), "desired.resource."))[identity]
        try:
            node = self.catalog.property_schema(resource["resourceType"], field)
        except KeyError:
            if field == "Name" and resource["resourceType"] in NAME_TAG_TYPES:
                return raw
            raise Unknown(f"unsupported design property: {field}") from None
        if raw.lower() in {"unset", "pending_deploy", "tbd", "未確定"}:
            raise Unknown("unconfirmed design value")
        if node.get("type") == "string":
            return read_json(raw) if raw.startswith('"') and raw.endswith('"') else raw
        try:
            return read_json(raw)
        except ValueError:
            raise Unknown(f"design literal cannot be typed: {field}") from None

    def compare_resource(self, service, identity, resource):
        source = self.sources.get((service, f"desired.resource.{identity}.resourceType"))
        logical = resource["logicalId"]
        kind = resource["resourceType"]
        try:
            if resource_mode(resource) == "IMPORT":
                self.excluded.append(dict(service=service, resource=logical, reason="IMPORT"))
                return
            if kind in self.catalog.api_schemas:
                self.excluded.append(dict(service=service, resource=logical, reason="CFn unsupported API type"))
                return
            ref = self.match(service, identity)
            actual_resource = self.resources[ref]
            cfn = self.location(actual_resource, self.units[ref[0]]["path"])
            if actual_resource.get("Type") != self.catalog.cloudformation_type(kind):
                self.finding("mismatch", service, logical, "Type", "resource type differs", source, cfn=cfn)
                return
            selected = defaultdict(list)
            for key, row in self.rows(service, identity):
                prop = row["property"]
                if not prop.startswith(kind + "."):
                    self.finding("unverified", service, logical, prop,
                                 "inline grouped resource needs explicit correspondence", source, cfn=cfn)
                    continue
                field = prop[len(kind) + 1:]
                if prop in self.catalog_outputs(kind):
                    continue  # Generated identifiers are not configuration inputs.
                selected[field].append((key, row))
            for field, rows in selected.items():
                source = self.sources[service, f"desired.row.{rows[0][0]}.value"]
                try:
                    expected = [self.expected(service, identity, field, row) for _, row in rows]
                    props = actual_resource.get("Properties", {})
                    if field == "Name" and kind in NAME_TAG_TYPES:
                        actual = [self.resolve(t["Value"], ref[0]) for t in props.get("Tags", [])
                                  if t.get("Key") == "Name"]
                    else:
                        actual = [self.resolve(v, ref[0]) for v in at_path(
                            props, field, lambda value: self.resolve(value, ref[0]))]
                    # One JSON array row may encode the complete primitive array.
                    if "[]" in field and len(expected) == 1 and isinstance(expected[0], list):
                        expected = expected[0]
                    self.checked += 1
                    if not equal(expected, actual):
                        self.finding("mismatch", service, logical, kind + "." + field,
                                     "configuration value differs", source, cfn=cfn,
                                     expected=expected, actual=actual)
                except KeyError:
                    self.finding("mismatch", service, logical, kind + "." + field,
                                 "selected property is absent from CFn", source, cfn=cfn)
                except (ValueError, TypeError, IndexError) as error:
                    self.finding("unverified", service, logical, kind + "." + field, str(error), source, cfn=cfn)
        except (ValueError, KeyError) as error:
            self.finding("unverified", service, logical, "resource", str(error), source)

    def catalog_outputs(self, kind):
        from model_design import catalog_outputs
        return catalog_outputs(self.root, kind)

    def run(self):
        self.load_stacks()
        for service in self.services:
            resources = entries(self.model(service), "desired.resource.")
            if not resources:
                self.finding("unverified", service, "", "resource", "service contains no resources")
            for identity, resource in resources:
                self.compare_resource(service, identity, resource)
            self.check_extra_resources(service, resources)
        return {"environment": self.environment, "target": self.directory,
                "services": self.services, "checked_properties": self.checked,
                "findings": self.findings, "excluded": self.excluded,
                "status": "FAIL" if self.findings else "PASS" if self.checked else "NOT_APPLICABLE"}

    def check_extra_resources(self, service, resources):
        kinds = {r["resourceType"] for _, r in resources}
        for kind in kinds - self.catalog.api_schemas.keys():
            ids = [i for i, r in resources if r["resourceType"] == kind and resource_mode(r) == "CREATE"]
            if any((service, i) not in self.matches for i in ids):
                continue  # Already unverified; do not relabel ambiguous candidates as extras.
            mapped = {self.matches[service, i] for i in ids}
            cfn_kind = self.catalog.cloudformation_type(kind)
            for ref, resource in self.resources.items():
                if resource.get("Type") == cfn_kind and ref not in mapped:
                    self.finding("mismatch", service, ref[1], "resource",
                                 "CFn resource has no CREATE resource in the selected service model",
                                 cfn=self.location(resource, self.units[ref[0]]["path"]))


NAME_TAG_TYPES = {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target-directory", required=True)
    parser.add_argument("--service", action="append", required=True)
    args = parser.parse_args()
    try:
        result = Comparison(args.repository_root, args.environment, args.target_directory, args.service).run()
        code = 1 if result["findings"] else 0
    except (ImportError, OSError, ValueError, KeyError, TypeError, IndexError) as error:
        result = {"status": "ERROR", "environment": args.environment, "target": args.target_directory,
                  "services": args.service, "findings": [{"status": "unverified", "reason": str(error)}]}
        code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=lambda v: vars(v) if isinstance(v, Reference) else str(v)))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
