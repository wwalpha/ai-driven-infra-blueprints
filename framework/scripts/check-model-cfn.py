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
from design_layout import GROUPED, REQUIRED_NAME_TAG_TYPES, resource_mode, resource_name_fields
from model_design import LINK, entries, properties, stack_model
from model_files import model_parts, read_model
from policy_tables import JSON_LINK, invalid_constant, literal, unique_object


class Unknown(ValueError):
    """An input cannot be compared without inventing a decision or reading AWS."""


class MissingResource(Unknown):
    """A required resource is demonstrably absent from the declared local stacks."""

    def __init__(self, reason, evidence):
        super().__init__(reason)
        self.evidence = evidence


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
    if any(isinstance(value, str) and value.lower() in {"unset", "pending_deploy", "tbd", "未確定"} for value in (left, right)):
        raise Unknown("unconfirmed value cannot establish configuration equality")
    if isinstance(left, Reference) or isinstance(right, Reference):
        if isinstance(left, Reference) and isinstance(right, Reference):
            if (left.stack, left.logical_id) == (right.stack, right.logical_id) and left.attribute != right.attribute:
                raise Unknown("different generated attributes need property-specific comparison")
            return left == right
        raise Unknown("generated value cannot be compared with a literal without resolving its value")
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return False
        pairs = ((left[k], right[k]) for k in left)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        pairs = zip(left, right)
    else:
        # YAML decoder scalars carry source marks as subclasses; compare their primitive types.
        for kind in (bool, str, int, float):
            if isinstance(left, kind) or isinstance(right, kind):
                return isinstance(left, kind) and isinstance(right, kind) and left == right
        return type(left) is type(right) and left == right
    unresolved = None
    for a, b in pairs:
        try:
            if not equal(a, b):
                return False
        except Unknown as error:
            unresolved = error
    if unresolved:
        raise unresolved
    return True


class Comparison:
    def __init__(self, root, environment, directory, services, decoder=None, runtime_parameters=None):
        self.root = root.resolve()
        self.environment, self.directory = environment, directory
        self.services = services
        self.runtime_parameters = {} if runtime_parameters is None else runtime_parameters
        if not isinstance(self.runtime_parameters, dict) or any(
                not isinstance(name, str) or not name or not isinstance(values, dict) or any(
                    not isinstance(key, str) or not key or not isinstance(value, str)
                    for key, value in values.items()) for name, values in self.runtime_parameters.items()):
            raise Unknown("runtime parameters must map StackName to parameter string values")
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
        self.inline_matches = {}
        self.findings, self.checked, self.excluded = [], 0, []
        self.stack_findings = []
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
        if self.runtime_parameters.keys() - {stack["name"] for _, stack in stacks}:
            raise Unknown("runtime parameters contain an undeclared StackName")
        for _, stack in stacks:
            name = stack["name"]
            document, template = None, path
            try:
                template = safe_path(self.root, self.root / "infra/cloudformation/templates" /
                                     self.target.get("alias", "") / stack["template"])
                document, errors = self.decoder(str(template))
                if errors or not isinstance(document, dict) or document.get("Transform"):
                    document = None  # Partial parse/Transform cannot establish resource coverage.
                    raise Unknown(f"invalid or Transform template: {template.relative_to(self.root)}")
                self.load_stack(stack, document, template)
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                self.stack_error(name, template, error, document)
        for name, unit in self.units.items():
            for output in unit["document"].get("Outputs", {}).values():
                if "Export" in output:
                    try:
                        if "Condition" in output and not self.condition(output["Condition"], name):
                            continue
                        export = self.resolve(output["Export"]["Name"], name)
                        if not isinstance(export, str):
                            raise Unknown(f"non-string Export name: {name}")
                        self.exports[export].append((name, output))
                    except (ValueError, KeyError, TypeError, IndexError) as error:
                        self.stack_error(name, unit["path"], error, unit["document"], coverage=False)
        for name, unit in self.units.items():
            for logical_id, resource in unit["document"].get("Resources", {}).items():
                try:
                    if "Condition" not in resource or self.condition(resource["Condition"], name):
                        self.resources[name, logical_id] = resource
                except (ValueError, KeyError, TypeError, IndexError) as error:
                    self.stack_error(name, unit["path"], error, {"Resources": {logical_id: resource}})

    def stack_error(self, name, path, error, document, coverage=True):
        resources = document.get("Resources", {}) if isinstance(document, dict) else None
        if not isinstance(resources, dict) or any(not isinstance(r, dict) or not isinstance(r.get("Type"), str)
                                                  for r in resources.values()):
            resources = None
        self.stack_findings.append(dict(status="unverified", stack=name, reason=str(error),
            cfn=self.location(document, path), coverage=coverage,
            resource_types=sorted({r.get("Type", "") for r in resources.values()}) if isinstance(resources, dict) else None,
            logical_ids=list(resources) if isinstance(resources, dict) else None))

    def load_stack(self, stack, document, template):
        name = stack["name"]
        for section in ("Parameters", "Resources", "Outputs"):
            contents = document.get(section, {})
            if not isinstance(contents, dict) or any(not isinstance(v, dict) for v in contents.values()):
                raise Unknown(f"invalid {section} section: {name}")
        if any(not isinstance(r.get("Type"), str) for r in document.get("Resources", {}).values()):
            raise Unknown(f"invalid resource Type: {name}")
        if any("Export" in o and (not isinstance(o["Export"], dict) or "Name" not in o["Export"])
               for o in document.get("Outputs", {}).values()):
            raise Unknown(f"invalid Export declaration: {name}")
        inputs = safe_path(self.root, self.root / "infra/cloudformation/parameters" /
                           self.environment / self.directory / stack["parameters"])
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
        runtime = self.runtime_parameters.get(name, {})
        if runtime.keys() - declarations.keys():
            raise Unknown(f"undeclared runtime parameter: {name}")
        parameters.update(runtime)
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
        keys = [k for k in value if k == "Ref" or k.startswith("Fn::") or
                (k == "Condition" and len(value) == 1 and isinstance(value[k], str))]
        if not keys:
            return {k: self.resolve(v, stack, seen) for k, v in value.items()}
        if len(value) != 1:
            raise Unknown("invalid intrinsic expression")
        key, argument = next(iter(value.items()))
        unit = self.units[stack]
        if key == "Ref":
            if argument in unit["parameters"]:
                return unit["parameters"][argument]
            if argument == "AWS::Partition":
                region = self.target["awsRegion"]
                if region.startswith("cn-"):
                    return "aws-cn"
                if region.startswith("us-gov-"):
                    return "aws-us-gov"
                if re.fullmatch(r"(?:af|ap|ca|eu|il|me|mx|sa|us)-[a-z]+-\d+", region) and not region.startswith("us-iso"):
                    return "aws"
                raise Unknown(f"unsupported partition for region: {region}")
            if argument in unit["document"].get("Resources", {}):
                resource = unit["document"]["Resources"][argument]
                if "Condition" in resource and not self.condition(resource["Condition"], stack, seen):
                    raise Unknown(f"inactive resource Ref: {argument}")
                kind = resource["Type"].removeprefix("AWS::").replace("::", ".")
                if kind in NAMED_REFS:
                    marker = ("named-ref", stack, argument)
                    if marker in seen:
                        raise Unknown(f"cyclic resource name: {argument}")
                    try:
                        names = at_path(resource.get("Properties", {}), NAMED_REFS[kind])
                    except KeyError:
                        names = []  # AWS-generated names remain symbolic.
                    if len(names) == 1:
                        name = self.resolve(names[0], stack, seen | {marker})
                        if not isinstance(name, str) or (kind == "KMS.Alias" and not name.startswith("alias/")):
                            raise Unknown(f"unresolved resource name: {argument}")
                        return name
                return Reference(stack, argument)
            raise Unknown(f"unresolved Ref: {argument}")
        if key == "Fn::GetAtt":
            parts = argument.split(".", 1) if isinstance(argument, str) else argument
            if len(parts) == 2 and parts[0] in unit["document"].get("Resources", {}):
                resource = unit["document"]["Resources"][parts[0]]
                if "Condition" in resource and not self.condition(resource["Condition"], stack, seen):
                    raise Unknown(f"inactive resource GetAtt: {parts[0]}")
                if parts[1] == "Arn" and resource["Type"] in {"AWS::S3::Bucket", "AWS::Logs::LogGroup"}:
                    name = self.resolve({"Ref": parts[0]}, stack, seen)
                    if isinstance(name, str):
                        partition = self.resolve({"Ref": "AWS::Partition"}, stack, seen)
                        if resource["Type"] == "AWS::S3::Bucket":
                            return f"arn:{partition}:s3:::{name}"
                        return f"arn:{partition}:logs:{self.target['awsRegion']}:{self.target['awsAccountId']}:log-group:{name}:*"
                return Reference(stack, *parts)
        if key == "Fn::ImportValue":
            if any(not error["coverage"] or error["stack"] not in self.units for error in self.stack_findings):
                raise Unknown("Export names are incomplete; ImportValue cannot be resolved uniquely")
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
        if key == "Fn::FindInMap":
            if not isinstance(argument, list) or len(argument) not in {3, 4}:
                raise Unknown("FindInMap requires three keys and optional DefaultValue")
            keys = self.resolve(argument[:3], stack, seen)
            if any(not isinstance(part, str) for part in keys):
                raise Unknown("FindInMap keys must resolve to strings")
            if len(argument) == 4 and (not isinstance(argument[3], dict) or set(argument[3]) != {"DefaultValue"}):
                raise Unknown("invalid FindInMap DefaultValue")
            mappings = unit["document"].get("Mappings", {})
            if not isinstance(mappings, dict):
                raise Unknown("invalid FindInMap Mappings section")
            mapping = mappings.get(keys[0])
            if not isinstance(mapping, dict):
                raise Unknown(f"missing FindInMap mapping: {keys[0]}")
            row = mapping.get(keys[1], {})
            if not isinstance(row, dict):
                raise Unknown(f"invalid FindInMap row: {keys[0]}/{keys[1]}")
            if keys[2] in row:
                return row[keys[2]]
            if len(argument) == 4:
                return self.resolve(argument[3]["DefaultValue"], stack, seen)
            raise Unknown(f"missing FindInMap key: {'/'.join(keys)}")
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
                         and row["property"][len(resource["resourceType"]) + 1:] in names
                         and row["property"] not in self.catalog_outputs(resource["resourceType"])]
            if resource["resourceType"] in REQUIRED_NAME_TAG_TYPES:
                rows = self.rows(service, identity)
                name_rows += [("Name", value) for (_, tag), (_, value) in zip(rows, rows[1:])
                              if tag["property"] == resource["resourceType"] + ".Tags[].Key"
                              and literal(tag["value"]) == "Name"
                              and value["property"] == resource["resourceType"] + ".Tags[].Value"]
            candidates = exact
            named_values, names_complete = [], True
            typed = [ref for ref, candidate in self.resources.items() if candidate.get("Type") == kind]
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
                            field == "Name" and resource["resourceType"] in NAME_TAG_TYPES | REQUIRED_NAME_TAG_TYPES) else at_path(props, field)
                        value = self.resolve(values[0], ref[0]) if len(values) == 1 else None
                        if not isinstance(value, str) or value.lower() in {"unset", "pending_deploy", "tbd", "未確定"}:
                            names_complete = False
                            continue
                        named_values.append(dict(stack=ref[0], logical_id=ref[1], value=value,
                                                 cfn=self.location(candidate, self.units[ref[0]]["path"])))
                        if value == expected:
                            named.append(ref)
                    except (KeyError, ValueError, TypeError, IndexError):
                        names_complete = False
                        continue
                if named:
                    candidates = named
            if resource["resourceType"] == "KMS.Key" and len(candidates) != 1:
                targets = []
                for child_id, child in entries(self.model(service), "desired.resource."):
                    link = LINK.fullmatch(child.get("parentReference", ""))
                    if child["resourceType"] != "KMS.Alias" or not link or link.group(2) or link.group(3) != resource["anchor"]:
                        continue
                    alias = self.match(service, child_id)
                    target = self.resolve(self.resources[alias].get("Properties", {}).get("TargetKeyId"), alias[0])
                    if not isinstance(target, Reference) or target.attribute not in {"Ref", "Arn"}:
                        raise Unknown("Alias TargetKeyId does not identify a local Key")
                    targets.append((target.stack, target.logical_id))
                if targets and len(set(targets)) == 1 and self.resources.get(targets[0], {}).get("Type") == kind:
                    candidates = [targets[0]]
            if len(candidates) != 1:
                incomplete = [error for error in self.stack_findings if error["coverage"] and (
                    error["resource_types"] is None or kind in error["resource_types"] or
                    resource["logicalId"] in (error["logical_ids"] or []))]
                if not candidates and not incomplete:
                    evidence = dict(expected=dict(resource_type=kind, logical_id=resource["logicalId"]),
                                    actual=named_values,
                                    coverage=dict(complete=True, resource_type=kind,
                                        scope="required resource type in declared local target stacks", stacks=[
                                        dict(stack=name, cfn=self.location(unit["document"], unit["path"]))
                                        for name, unit in self.units.items()]))
                    if not typed:
                        raise MissingResource("required resource type is absent from active CFn resources", evidence)
                    if name_rows and names_complete and expected and not LINK.fullmatch(expected) and expected.lower() not in {
                            "unset", "pending_deploy", "tbd", "未確定"}:
                        evidence["expected"].update(property=field, value=expected)
                        raise MissingResource("confirmed resource name is absent from active CFn resources", evidence)
                raise Unknown(f"resource correspondence unresolved ({len(candidates)} candidates)")
            if candidates[0] in self.matches.values():
                raise Unknown("multiple design resources map to the same CFn resource")
            self.matches[key] = candidates[0]
            return candidates[0]
        finally:
            self.matching.remove(key)

    def match_inline(self, service, identity, kind):
        key = service, identity, kind
        if key not in self.inline_matches:
            resource = dict(entries(self.model(service), "desired.resource."))[identity]
            rule = GROUPED.get(kind, {})
            if rule.get("parent") != resource["resourceType"] or rule.get("identityProperty") is not None or rule.get("maxCount") != 1:
                raise Unknown("inline grouped resource needs explicit correspondence")
            parent_ref = self.match(service, identity)
            parent = self.resolve({"Ref": parent_ref[1]}, parent_ref[0])
            candidates = []
            for ref, candidate in self.resources.items():
                if candidate.get("Type") != self.catalog.cloudformation_type(kind):
                    continue
                values = at_path(candidate.get("Properties", {}), rule["parentProperty"])
                if len(values) == 1 and equal(self.resolve(values[0], ref[0]), parent):
                    candidates.append(ref)
            if len(candidates) != 1:
                if not candidates and not any(error["coverage"] and (error["resource_types"] is None or
                        self.catalog.cloudformation_type(kind) in error["resource_types"]) for error in self.stack_findings):
                    raise MissingResource("required child resource is absent for the matched parent",
                        dict(expected=dict(resource_type=self.catalog.cloudformation_type(kind), parent=parent_ref),
                             actual=[], coverage=dict(complete=True, resource_type=self.catalog.cloudformation_type(kind))))
                raise Unknown(f"inline resource correspondence unresolved ({len(candidates)} candidates): {kind}")
            if candidates[0] in self.inline_matches.values() or candidates[0] in self.matches.values():
                raise Unknown("multiple design resources map to the same CFn resource")
            self.inline_matches[key] = candidates[0]
        return self.inline_matches[key]

    def expected(self, service, identity, field, row, kind=None, stack=None):
        if "document" in row:
            return self.resolve(read_json(row["document"]), stack)
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
            if target_resource["resourceType"] == "KMS.Alias":
                if field.rsplit(".", 1)[-1] in KEY_SELECTORS:
                    parent = target_resource.get("parentReference")
                    if not parent:
                        raise Unknown("Alias reference requires parentReference")
                    return self.expected(owner, target_id, "TargetKeyId", {"value": parent})
                if "arn" in field.lower():
                    raise Unknown("Alias name cannot substitute for an ARN reference")
                names = [r for _, r in self.rows(owner, target_id) if r["property"] == "KMS.Alias.AliasName"]
                if len(names) != 1:
                    raise Unknown("Alias reference requires one AliasName")
                return self.expected(owner, target_id, "AliasName", names[0])
            schema = self.catalog.schema(target_resource["resourceType"])
            if "arn" in field.lower():
                attrs = [p.rsplit("/", 1)[-1] for p in schema.get("readOnlyProperties", [])
                         if "arn" in p.rsplit("/", 1)[-1].lower()]
                if len(attrs) != 1:
                    raise Unknown("ARN reference attribute is ambiguous")
                return self.resolve({"Fn::GetAtt": [target_logical, attrs[0]]}, target_stack)
            leaf = field.rsplit(".", 1)[-1].removesuffix("[]")
            identifier = {p.rsplit("/", 1)[-1] for p in schema.get("primaryIdentifier", [])}
            aliases = {"Subnets": "SubnetId", "SubnetIds": "SubnetId",
                       "SecurityGroupIds": "GroupId", **{key: "KeyId" for key in KEY_SELECTORS},
                       "TargetKeyId": "KeyId", "S3BucketName": "BucketName", "Role": "RoleName"}
            if len(identifier) != 1 or aliases.get(leaf, leaf) not in identifier:
                raise Unknown("reference does not identify an unambiguous Ref return value")
            if target_resource["resourceType"] in NAMED_REFS:
                name = target_resource["resourceType"] + "." + NAMED_REFS[target_resource["resourceType"]]
                rows = [r for _, r in self.rows(owner, target_id) if r["property"] == name]
                if len(rows) == 1:
                    return self.expected(owner, target_id, NAMED_REFS[target_resource["resourceType"]], rows[0])
            return Reference(target_stack, target_logical)
        resource = dict(entries(self.model(service), "desired.resource."))[identity]
        kind = kind or resource["resourceType"]
        try:
            node = self.catalog.property_schema(kind, field)
        except KeyError:
            if (field == "Name" and resource["resourceType"] in NAME_TAG_TYPES) or (kind == "S3.Bucket" and field == "Region"):
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
                if prop.startswith(kind + ".") and prop in self.catalog_outputs(kind):
                    continue  # Generated identifiers are not configuration inputs.
                selected[prop].append((key, row))
            if kind in GROUPED:
                prop = kind + "." + GROUPED[kind]["parentProperty"]
                if resource.get("parentProperty") != prop or not resource.get("parentReference"):
                    raise Unknown("grouped resource requires valid parentProperty and parentReference")
                if prop not in selected:
                    selected[prop].append((None, {"value": resource["parentReference"]}))
            for prop, rows in selected.items():
                source = self.sources[service, f"desired.row.{rows[0][0]}.value" if rows[0][0] else
                                      f"desired.resource.{identity}.parentReference"]
                cfn = self.location(actual_resource, self.units[ref[0]]["path"])
                expected = actual = None
                try:
                    row_kind, field = kind, prop[len(kind) + 1:]
                    if not prop.startswith(kind + "."):
                        row_kind = next((child for child in GROUPED if prop.startswith(child + ".")), "")
                        field = prop[len(row_kind) + 1:]
                    row_ref = ref if row_kind == kind else self.match_inline(service, identity, row_kind)
                    candidate = self.resources[row_ref]
                    cfn = self.location(candidate, self.units[row_ref[0]]["path"])
                    expected = [self.expected(service, identity, field, row, row_kind, row_ref[0]) for _, row in rows]
                    props = candidate.get("Properties", {})
                    if row_kind == "S3.Bucket" and field == "Region":
                        actual = [self.target["awsRegion"]]
                    elif field == "Name" and kind in NAME_TAG_TYPES:
                        actual = [self.resolve(t["Value"], row_ref[0]) for t in props.get("Tags", [])
                                  if t.get("Key") == "Name"]
                    else:
                        actual = [self.resolve(v, row_ref[0]) for v in at_path(
                            props, field, lambda value: self.resolve(value, row_ref[0]))]
                    if field.rsplit(".", 1)[-1] in KEY_SELECTORS | {"TargetKeyId"}:
                        expected = [self.key_reference(v) for v in expected]
                        actual = [self.key_reference(v) for v in actual]
                    # One JSON array row may encode the complete primitive array.
                    if field.endswith("[]") and len(expected) == 1 and isinstance(expected[0], list):
                        expected = expected[0]
                    same = equal(expected, actual)
                    self.checked += 1
                    if not same:
                        self.finding("mismatch", service, logical, prop,
                                     "configuration value differs", source, cfn=cfn,
                                     expected=expected, actual=actual)
                except MissingResource as error:
                    self.finding("mismatch", service, logical, prop, str(error), source, cfn=cfn, **error.evidence)
                except KeyError:
                    self.finding("mismatch", service, logical, prop,
                                 "selected property is absent from CFn", source, cfn=cfn)
                except (ValueError, TypeError, IndexError) as error:
                    self.finding("unverified", service, logical, prop, str(error), source, cfn=cfn,
                                 expected=expected, actual=actual)
        except MissingResource as error:
            self.finding("mismatch", service, logical, "resource", str(error), source, **error.evidence)
        except (ValueError, KeyError) as error:
            self.finding("unverified", service, logical, "resource", str(error), source)

    def catalog_outputs(self, kind):
        from model_design import catalog_outputs
        return catalog_outputs(self.root, kind)

    def key_reference(self, value):
        if isinstance(value, str) and value.startswith("alias/"):
            aliases = [ref for ref, resource in self.resources.items() if resource.get("Type") == "AWS::KMS::Alias"
                       and self.resolve({"Ref": ref[1]}, ref[0]) == value]
            if len(aliases) > 1:
                raise Unknown("ambiguous AliasName in key reference")
            if aliases:
                ref = aliases[0]
                value = self.resolve(self.resources[ref].get("Properties", {}).get("TargetKeyId"), ref[0])
        if isinstance(value, Reference) and value.attribute == "Arn" and self.resources.get(
                (value.stack, value.logical_id), {}).get("Type") == "AWS::KMS::Key":
            return Reference(value.stack, value.logical_id)
        return value

    def run(self):
        self.load_stacks()
        service_results = {}
        for service in self.services:
            start, checked = len(self.findings), self.checked
            try:
                resources = entries(self.model(service), "desired.resource.")
                kinds, logical_ids = set(), set()
                for _, resource in resources:
                    if resource_mode(resource) != "CREATE" or resource["resourceType"] in self.catalog.api_schemas:
                        continue
                    logical_ids.add(resource["logicalId"])
                    try:
                        kinds.add(self.catalog.cloudformation_type(resource["resourceType"]))
                    except ValueError:
                        pass  # compare_resource records the unknown type without skipping healthy resources.
                kinds.update(self.catalog.cloudformation_type(child) for child in GROUPED
                             if any(row["property"].startswith(child + ".") for _, row in entries(self.model(service), "desired.row.")))
                for error in self.stack_findings:
                    if logical_ids and error["coverage"] and (error["resource_types"] is None or
                            kinds.intersection(error["resource_types"]) or logical_ids.intersection(error["logical_ids"])):
                        self.finding("unverified", service, error["stack"], "stack", error["reason"], cfn=error["cfn"])
                if not resources:
                    self.finding("unverified", service, "", "resource", "service contains no resources")
                for identity, resource in resources:
                    self.compare_resource(service, identity, resource)
                self.check_extra_resources(service, resources)
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                self.finding("unverified", service, "", "service", str(error))
            count = self.checked - checked
            service_results[service] = dict(checked_properties=count,
                status="FAIL" if len(self.findings) > start else "PASS" if count else "NOT_APPLICABLE")
        return {"environment": self.environment, "target": self.directory,
                "services": self.services, "checked_properties": self.checked,
                "findings": self.findings, "excluded": self.excluded,
                "stack_findings": self.stack_findings, "service_results": service_results,
                "status": "FAIL" if self.findings or self.stack_findings else "PASS" if self.checked else "NOT_APPLICABLE"}

    def check_extra_resources(self, service, resources):
        kinds = {r["resourceType"] for _, r in resources}
        inline = {child: [identity for identity, resource in resources
                          if any(row["property"].startswith(child + ".") for _, row in self.rows(service, identity))
                          and resource["resourceType"] != child] for child in GROUPED}
        kinds.update(child for child, parents in inline.items() if parents)
        for kind in kinds - self.catalog.api_schemas.keys():
            ids = [i for i, r in resources if r["resourceType"] == kind and resource_mode(r) == "CREATE"]
            parents = inline.get(kind, [])
            if any((service, i) not in self.matches for i in ids) or any(
                    (service, i, kind) not in self.inline_matches for i in parents):
                continue  # Already unverified; do not relabel ambiguous candidates as extras.
            mapped = {self.matches[service, i] for i in ids} | {self.inline_matches[service, i, kind] for i in parents}
            cfn_kind = self.catalog.cloudformation_type(kind)
            for ref, resource in self.resources.items():
                if resource.get("Type") == cfn_kind and ref not in mapped:
                    self.finding("mismatch", service, ref[1], "resource",
                                 "CFn resource has no CREATE resource in the selected service model",
                                 cfn=self.location(resource, self.units[ref[0]]["path"]))


NAME_TAG_TYPES = {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}
KEY_SELECTORS = {"KmsKey", "KmsKeyId", "KMSKeyId", "KMSMasterKeyID"}
NAMED_REFS = {"KMS.Alias": "AliasName", "S3.Bucket": "BucketName", "IAM.Role": "RoleName",
              "Logs.LogGroup": "LogGroupName", "Glue.Connection": "ConnectionInput.Name", "Glue.Job": "Name"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target-directory", required=True)
    parser.add_argument("--service", action="append", required=True)
    parser.add_argument("--runtime-parameters", type=Path,
                        help='JSON object: {"StackName": {"ParameterKey": "effective value"}}; comparison only')
    args = parser.parse_args()
    try:
        runtime = read_json(args.runtime_parameters.read_text(encoding="utf-8")) if args.runtime_parameters else None
        if args.runtime_parameters and runtime is None:
            raise Unknown("runtime parameters must map StackName to parameter string values")
        result = Comparison(args.repository_root, args.environment, args.target_directory, args.service,
                            runtime_parameters=runtime).run()
        code = 1 if result["status"] == "FAIL" else 0
    except (ImportError, OSError, ValueError, KeyError, TypeError, IndexError) as error:
        result = {"status": "ERROR", "environment": args.environment, "target": args.target_directory,
                  "services": args.service, "findings": [{"status": "unverified", "reason": str(error)}]}
        code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=lambda v: vars(v) if isinstance(v, Reference) else str(v)))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
