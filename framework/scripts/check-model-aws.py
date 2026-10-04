#!/usr/bin/env python3
"""Read authoritative models and compare selected settings with read-only AWS SDK APIs.

Exit 0: complete match; 1: differences; 2: incomplete (possibly with differences).
--coverage is offline. No AI, CloudFormation template comparison, or model writes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

sys.modules.setdefault("model_aws_compare", sys.modules[__name__])

from design_catalog import DesignSchemaCatalog, selected_properties
from model_design import LINK, catalog_outputs, entries, pipeline_rows, properties
from model_files import model_parts, read_model
from policy_tables import invalid_constant, literal, unique_object

MISSING = {"absent": True}
SERVICES = tuple("athena cloudformation-stacks cloudtrail cloudwatch-logs codebuild codecommit "
                 "codepipeline config data-firehose ec2 eventbridge glue guardduty iam kms lambda "
                 "macie mwaa quicksight route53 s3 secrets-manager security-hub security_group sqs "
                 "transit-gateway vpc vpc-endpoint".split())
ROOT = Path(__file__).resolve().parents[2]
MODULES = {}


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def service_module(service):
    if service not in SERVICES:
        raise ValueError("unimplemented service: " + service)
    if service not in MODULES:
        MODULES[service] = load_file("aws_compare_" + service.replace("-", "_"),
                                   Path(__file__).with_name("aws-compare-services") / (service + ".py"))
    return MODULES[service]


@dataclass(frozen=True)
class Field:
    getter: str = ""
    path: str = ""
    norm: str = "typed"
    default: object = None
    classification: str = "supported"
    reason: str = ""


def fields(resource_type, getter, mapping, norms=None, defaults=None):
    """Explicit property/API-response mapping; inputs live in the service's fetch()."""
    if isinstance(mapping, str):
        mapping = {path: path for path in mapping.split()}
    return {resource_type + "." + prop: Field(getter, path, (norms or {}).get(prop, "typed"),
                                             (defaults or {}).get(prop, MISSING))
            for prop, path in mapping.items()}


def unavailable(reason):
    return Field(classification="sdk_unavailable", reason=reason)


def metadata(reason):
    return Field(classification="local_metadata", reason=reason)


class Unresolved(ValueError):
    pass


class AcquisitionError(Exception):
    def __init__(self, api, code, status="acquisition_failed", request=None):
        self.api, self.code, self.status, self.request = api, code, status, request
        super().__init__(code)  # Never include SDK error messages or credentials.


def sdk_error(api, error, request):
    detail = getattr(error, "response", {}).get("Error", {})
    code = detail.get("Code", type(error).__name__)
    missing = code in {"ResourceNotFoundException", "ResourceNotFound", "EntityNotFoundException", "NoSuchEntity",
                      "NotFoundException", "NoSuchBucket", "QueueDoesNotExist", "AWS.SimpleQueueService.NonExistentQueue",
                      "InvalidInstanceID.NotFound", "InvalidVpcID.NotFound", "InvalidSubnetID.NotFound",
                      "InvalidGroup.NotFound", "NoSuchHostedZone", "TrailNotFoundException", "RepositoryDoesNotExistException"}
    if api == "cloudformation.describe_stacks" and code == "ValidationError":
        missing = bool(re.fullmatch(r"Stack with id .+ does not exist", detail.get("Message", "")))
    return AcquisitionError(api, code, "resource_missing" if missing else "acquisition_failed", request)


def one(items, api):
    if not items:
        raise AcquisitionError(api, "ResourceNotFound", "resource_missing")
    if len(items) != 1:
        raise Unresolved("resource selector is ambiguous")
    return items[0]


def select(value, path):
    if not path:
        return value
    part, _, rest = path.partition(".")
    array = part.endswith("[]")
    child = value.get(part.removesuffix("[]"), MISSING) if isinstance(value, dict) else MISSING
    if array:
        if child == MISSING:
            return MISSING
        if not isinstance(child, list):
            raise Unresolved("SDK response has an invalid array type")
        return [select(item, rest) for item in child] if rest else child
    return select(child, rest) if rest else child


def project(tree, path, value):
    """Put an SDK leaf projection back into a tree without losing array membership."""
    part, _, rest = path.partition(".")
    if part.endswith("[]"):
        name = part[:-2]
        if value == MISSING:
            tree[name] = MISSING
        elif not rest:
            tree[name] = value
        else:
            array = tree.setdefault(name, [])
            if not isinstance(array, list):
                raise Unresolved("inconsistent SDK array projections")
            while len(array) < len(value):
                array.append({})
            if len(array) != len(value):
                raise Unresolved("inconsistent SDK array lengths")
            for item, child in zip(array, value):
                project(item, rest, child)
    elif rest:
        project(tree.setdefault(part, {}), rest, value)
    else:
        tree[part] = value


def put_row(tree, path, value):
    """Catalog-ordered repeated rows: a repeated scalar starts a new array element."""
    part, _, rest = path.partition(".")
    indexed = re.fullmatch(r"(.+)\[(\d+)\]", part)
    if indexed:
        name, number = indexed.group(1), int(indexed.group(2)) - 1
        array = tree.setdefault(name, [])
        while len(array) <= number:
            array.append({})
        put_row(array[number], rest, value)
    elif part.endswith("[]"):
        name = part[:-2]
        array = tree.setdefault(name, [])
        if not rest:
            array.extend(value if isinstance(value, list) else [value])
        else:
            if not array or ("[]" not in rest and select(array[-1], rest) != MISSING):
                array.append({})
            put_row(array[-1], rest, value)
    elif rest:
        put_row(tree.setdefault(part, {}), rest, value)
    elif part in tree:
        # Repeated list-valued rows are individual resource references.
        old = tree[part]
        tree[part] = (old if isinstance(old, list) else [old]) + (value if isinstance(value, list) else [value])
    else:
        tree[part] = value


# Only collections with set/map semantics are reordered. Stages/actions and subnet
# placement in MWAA/QuickSight retain order. Full objects move together, never leaves.
MAP_ARRAYS = {
    "Tags": "Key", "HostedZoneTags": "Key", "EnvironmentVariables": "Name",
    "Features": "Name", "Policies": "PolicyName", "BlockDeviceMappings": "DeviceName",
    "Targets": "Id", "ExternalSecretRotationMetadata": "Key",
}
SET_ARRAYS = {"ManagedPolicyArns", "Roles", "SecurityGroupIds", "SecurityGroupIdList",
              "RouteTableIds", "ResourceTypes", "ResourceRecords", "managedDataIdentifierIds",
              "Actions", "ObjectPrefixes", "DataResources", "EventSelectors"}


def canonical(value, path=""):
    if isinstance(value, dict):
        return {key: canonical(item, path + "." + key) for key, item in value.items()}
    if isinstance(value, list):
        items = [canonical(item, path + "[]") for item in value]
        name = path.rsplit(".", 1)[-1]
        if name in MAP_ARRAYS or name in SET_ARRAYS or path.endswith("LifecycleConfiguration.Rules"):
            key = MAP_ARRAYS.get(name, "Id")
            return sorted(items, key=lambda item: stable(item.get(key, MISSING) if isinstance(item, dict) else item))
        return items
    return value


def stable(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def policy(value):
    """IAM policy sets may reorder; paired statement fields remain one object."""
    if isinstance(value, str):
        try:
            value = json.loads(value, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        except json.JSONDecodeError:
            value = json.loads(unquote(value), object_pairs_hook=unique_object, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise Unresolved("policy must be a JSON object")
    def walk(item, name=""):
        if name in {"Statement", "Action", "NotAction", "Resource", "NotResource", "AWS", "Service", "Federated"}:
            values = item if isinstance(item, list) else [item]
            return sorted([walk(v) for v in values], key=stable)
        if isinstance(item, dict):
            return {k: walk(v, k) for k, v in item.items()}
        if isinstance(item, list):
            return sorted([walk(v) for v in item], key=stable)  # Condition value arrays are sets.
        return item
    return walk(value)


def redacted(value):
    """Defence in depth for output: configuration maps can contain credentials."""
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if re.search(r"password|token|secretaccesskey|accesskeyid|credentialpair|privatekey|authorization|username", key, re.I)
                      else redacted(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redacted(item) for item in value]
    return value


class Context:
    def __init__(self, root, target, session=None):
        self.root, self.target, self.session = Path(root), target, session
        self.clients, self.cache, self.models, self.fetch_cache, self.fetch_trace = {}, {}, {}, {}, {}
        self.verified = False
        self.allowed = {("sts", "get_caller_identity"), ("kms", "describe_key"), ("cloudformation", "list_exports")}
        for service in SERVICES:
            self.allowed.update(service_module(service).APIS)
        self.catalog = DesignSchemaCatalog(ROOT)
        self.trace = []

    def client(self, service):
        if service not in self.clients:
            self.clients[service] = self.session.client(service, region_name=self.target["awsRegion"])
        return self.clients[service]

    def call(self, service, operation, **inputs):
        if (service, operation) not in self.allowed or operation in {"get_secret_value", "batch_get_secret_value"}:
            raise ValueError("API is outside the read-only allowlist")
        if not self.verified and (service, operation) != ("sts", "get_caller_identity"):
            raise ValueError("AWS account has not been verified")
        api = service + "." + operation
        key = (service, operation, stable(inputs))
        self.trace.append({"api": api, "inputs": redacted(inputs)})
        if key not in self.cache:
            try:
                self.cache[key] = getattr(self.client(service), operation)(**inputs)
            except Exception as error:
                self.cache[key] = sdk_error(api, error, key)
        result = self.cache[key]
        if isinstance(result, AcquisitionError):
            raise result
        return result

    def pages(self, service, operation, **inputs):
        if (service, operation) not in self.allowed or not self.verified:
            raise ValueError("paginated API is outside verified read-only scope")
        key = (service, operation, "pages", stable(inputs))
        api = service + "." + operation
        self.trace.append({"api": api, "inputs": redacted(inputs), "pagination": "all"})
        if key not in self.cache:
            client = self.client(service)
            try:
                if client.can_paginate(operation):
                    self.cache[key] = client.get_paginator(operation).paginate(**inputs).build_full_result()
                else:
                    result, params, seen = {}, dict(inputs), set()
                    while True:
                        page = self.call(service, operation, **params)
                        for name, value in page.items():
                            if isinstance(value, list):
                                result.setdefault(name, []).extend(value)
                            else:
                                result[name] = value
                        token_name = next((name for name in ("NextToken", "nextToken", "Marker", "NextMarker") if page.get(name)), None)
                        if not token_name:
                            if page.get("IsTruncated") or page.get("HasMoreResults"):
                                raise Unresolved("pagination continuation is missing")
                            break
                        token = page[token_name]
                        if token in seen:
                            raise Unresolved("pagination token repeated")
                        seen.add(token)
                        params["Marker" if token_name == "NextMarker" else token_name] = token
                    self.cache[key] = result
            except AcquisitionError as error:
                self.cache[key] = error
            except Exception as error:
                self.cache[key] = sdk_error(api, error, key)
        if isinstance(self.cache[key], AcquisitionError):
            raise self.cache[key]
        return self.cache[key]

    def verify(self):
        response = self.call("sts", "get_caller_identity")
        if response.get("Account") != self.target.get("awsExecutionAccountId", self.target["awsAccountId"]):
            raise AcquisitionError("sts.get_caller_identity", "AccountMismatch")
        self.verified = True

    def model(self, path):
        if path.is_symlink():
            raise ValueError("model entrance must not be a symlink")
        path = path.resolve()
        if path not in self.models:
            self.models[path] = Model(self, path)
        return self.models[path]

    def fetch(self, resource, getter):
        key = (resource.model.path, resource.number, getter)
        if key not in self.fetch_cache:
            start = len(self.trace)
            try:
                self.fetch_cache[key] = resource.module.fetch(self, resource, getter)
            except (AcquisitionError, Unresolved) as error:
                self.fetch_cache[key] = error
            self.fetch_trace[key] = self.trace[start:]
        else:
            self.trace.extend(self.fetch_trace[key])
        value = self.fetch_cache[key]
        if isinstance(value, Exception):
            raise value
        return value


class Model:
    def __init__(self, ctx, path):
        self.ctx, self.path, self.service = ctx, path, path.stem
        self.values = properties(read_model(path))
        self.locations = {}
        for part in model_parts(path):
            for line, text in enumerate(part.read_text(encoding="utf-8").splitlines(), 1):
                if text and not text.startswith("#") and "=" in text:
                    self.locations[text.partition("=")[0]] = {"file": str(part), "line": line}
        rows = entries(self.values, "desired.row.")
        self.resources = [Resource(self, number, spec, [(rid, row) for rid, row in rows if rid.startswith(number + "-")])
                          for number, spec in entries(self.values, "desired.resource.")]


class Resource:
    def __init__(self, model, number, spec, rows):
        self.model, self.ctx, self.number, self.spec, self.rows = model, model.ctx, number, spec, rows
        self.kind = spec["resourceType"]
        self.module = service_module(model.service)

    def rows_for(self, prop):
        full = prop if prop.startswith(self.kind + ".") else self.kind + "." + prop
        return [(rid, row) for rid, row in self.rows if row["property"] == full]

    def current(self, prop):
        rows = self.rows_for(prop)
        if len(rows) != 1:
            return None
        rid, row = rows[0]
        raw = self.model.values.get("observed.row." + rid + ".value")
        if raw is None and not LINK.fullmatch(row["value"]):
            raw = row["value"]
        if raw is None:
            return None
        value = literal(raw)
        return value if value and value not in {"PENDING_DEPLOY", "UNSET"} and not value.startswith("arn:") else None

    def value(self, prop, norm="typed"):
        rows = self.rows_for(prop)
        if len(rows) != 1:
            raise Unresolved("selector requires exactly one confirmed " + prop)
        value = self.parse(rows[0][1], norm)
        if value == "":
            raise Unresolved("selector must not be empty")
        return value

    def optional(self, prop, default=None, norm="typed"):
        return self.value(prop, norm) if self.rows_for(prop) else default

    def parent(self):
        reference = self.spec.get("parentReference")
        if not reference:
            raise Unresolved("grouped resource has no confirmed parent")
        return self.reference(reference)

    def reference(self, value):
        link = LINK.fullmatch(value)
        if not link:
            raise Unresolved("invalid model reference")
        filename = link.group(2)
        if filename and (Path(filename).name != filename or not filename.endswith(".md")):
            raise Unresolved("reference must stay in the same target")
        path = self.model.path.parent / (Path(filename).stem + ".properties") if filename else self.model.path
        model = self.ctx.model(path)
        matches = [r for r in model.resources if r.spec.get("anchor") == link.group(3)]
        if len(matches) != 1:
            raise Unresolved("model reference is missing or ambiguous")
        return matches[0]

    def identity(self, mode="id"):
        descriptor = self.module.IDENTITIES.get(self.kind)
        if not descriptor:
            raise Unresolved("resource has no SDK identity mapping")
        getter, idpath, arnpath, nameprop = descriptor
        if mode == "name" and nameprop:
            self.ctx.fetch(self, getter)  # Confirm existence before using the selected name.
            return self.value(nameprop, "string")
        path = arnpath if mode == "arn" else idpath
        if not path:
            raise Unresolved("SDK identity cannot supply " + mode)
        value = select(self.ctx.fetch(self, getter), path)
        if value == MISSING or value is None:
            raise Unresolved("SDK identity is absent")
        return value

    def parse(self, row, norm="typed"):
        raw = row.get("document", row["value"])
        prop = row["property"]
        resource_type = ".".join(prop.split(".")[:2])
        path = prop[len(resource_type) + 1:]
        try:
            schema = self.ctx.catalog.property_schema(resource_type, path)
            schema_type = schema.get("type")
        except KeyError:
            schema, schema_type = {}, "string"
        if "document" in row:
            value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        elif LINK.fullmatch(raw):
            target = self.reference(raw)
            mode = "arn" if norm in {"arn", "policy", "iam_role", "log_group_arn"} else "name" if norm in {"name", "string"} else "id"
            value = target.identity(mode)
        else:
            value = literal(raw)
            explicit_empty = value == "" and raw.startswith("`") and schema_type == "string" and not schema.get("minLength", 0)
            if (not value and not explicit_empty) or value in {"UNSET", "PENDING_DEPLOY", "未確定", "TBD", "TODO"}:
                raise Unresolved("design value is unresolved")
            if path.endswith("[]") and value.startswith("["):
                value = json.loads(value, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                if not isinstance(value, list):
                    raise Unresolved("design array row must be a list")
            elif schema_type != "string" or norm in {"json", "policy", "set"}:
                try:
                    value = json.loads(value, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                except ValueError:
                    if schema_type not in {"array", "object"}:
                        raise Unresolved("design value has an invalid type") from None
                    if schema_type == "array" and norm in {"name", "id", "arn", "set", "kms", "typed"}:
                        value = [literal(item.strip()) for item in value.split(",")]
                    else:
                        raise Unresolved("design JSON is invalid") from None
        value = self.resolve_json(value, norm)
        if schema_type == "array" and not isinstance(value, list):
            value = [value]
        return value

    def resolve_json(self, value, norm="typed"):
        if isinstance(value, str) and LINK.fullmatch(value):
            target = self.reference(value)
            return target.identity("arn" if norm in {"arn", "policy", "iam_role", "log_group_arn"} else "name" if norm in {"name", "string"} else "id")
        if isinstance(value, list):
            return [self.resolve_json(item, norm) for item in value]
        if not isinstance(value, dict):
            return value
        if value == {"Ref": "AWS::AccountId"}:
            return self.ctx.call("sts", "get_caller_identity")["Account"]
        if value == {"Ref": "AWS::Region"}:
            return self.ctx.target["awsRegion"]
        if "Fn::GetAtt" in value or "Ref" in value:
            item = value.get("Fn::GetAtt", value.get("Ref"))
            logical = item[0] if isinstance(item, list) else item.split(".")[0]
            from model_design import cfn_resource_identity
            stack = cfn_resource_identity(self.spec["cfn-logicalId"])[0] if "cfn-logicalId" in self.spec else None
            matches = []
            for path in self.model.path.parent.glob("*.properties"):
                for resource in self.ctx.model(path).resources:
                    if "cfn-logicalId" in resource.spec:
                        matched = stack is not None and cfn_resource_identity(resource.spec["cfn-logicalId"]) == (stack, logical)
                    else:
                        matched = stack is None and resource.spec.get("logicalId") == logical
                    if matched:
                        matches.append(resource)
            if len(matches) != 1:
                raise Unresolved("model logical reference is missing or ambiguous")
            resource = matches[0]
            return resource.identity("arn" if "Fn::GetAtt" in value else "id")
        if "Fn::Sub" in value:
            expression = value["Fn::Sub"]
            substitutions = {}
            if isinstance(expression, list):
                expression, substitutions = expression
                substitutions = self.resolve_json(substitutions, norm)
            # Partition is obtained from verified STS ARN, never inferred from region.
            caller = self.ctx.call("sts", "get_caller_identity")
            substitutions.update({"AWS::AccountId": caller["Account"],
                                  "AWS::Region": self.ctx.target["awsRegion"],
                                  "AWS::Partition": caller["Arn"].split(":")[1]})
            def replace(match):
                key = match.group(1)
                if key.startswith("!"):
                    return "${" + key[1:] + "}"
                if key in substitutions:
                    return str(substitutions[key])
                return str(self.resolve_json({"Fn::GetAtt": key} if "." in key else {"Ref": key}, norm))
            return re.sub(r"\$\{([^}]+)\}", replace, expression)
        if "Fn::ImportValue" in value:
            name = self.resolve_json(value["Fn::ImportValue"], norm)
            exports = self.ctx.pages("cloudformation", "list_exports").get("Exports", [])
            matches = [item["Value"] for item in exports if item["Name"] == name]
            if len(matches) != 1:
                raise Unresolved("confirmed design export is missing or ambiguous")
            return matches[0]
        if any(key.startswith("Fn::") for key in value):
            raise Unresolved("unsupported design expression")
        return {key: self.resolve_json(item, norm) for key, item in value.items()}


def normalize(ctx, value, norm):
    if value == MISSING:
        return value
    if norm == "policy" and isinstance(value, list):
        return [normalize(ctx, item, norm) for item in value]
    if norm == "policy":
        return policy(value)
    if isinstance(value, list):
        result = [normalize(ctx, item, norm) for item in value]
        return sorted(result, key=stable) if norm == "set" else result
    if norm == "kms":
        if not isinstance(value, str) or not value:
            raise Unresolved("KMS reference is unresolved")
        return ctx.call("kms", "describe_key", KeyId=value)["KeyMetadata"]["KeyId"]
    if norm == "iam_role":
        if not isinstance(value, str) or not value:
            raise Unresolved("IAM role reference is unresolved")
        return value if value.startswith("arn:") else ctx.call("iam", "get_role", RoleName=value)["Role"]["Arn"]
    if norm == "dns":
        return value.rstrip(".").lower() if isinstance(value, str) else value
    if norm == "log_group_arn":
        return value.removesuffix(":*") if isinstance(value, str) else value
    if norm == "boolean":
        if type(value) is bool:
            return value
        if value in {"true", "false"}:
            return value == "true"
        raise Unresolved("invalid boolean")
    if norm == "number":
        if type(value) is bool:
            raise Unresolved("invalid number")
        return int(value)
    if norm in {"string", "protocol"}:
        text = str(value)
        return {"6": "tcp", "17": "udp", "1": "icmp", "58": "icmpv6"}.get(text, text) if norm == "protocol" else text
    if norm == "json" and isinstance(value, str):
        return json.loads(value, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    return value


def source(resource, rows):
    return [{"key": key, **resource.model.locations[key]}
            for rid, row in rows for field in ("value", "document")
            if (key := "desired.row." + rid + "." + field) in resource.model.locations and (field == "value" or "document" in row)]


def compare_resource(ctx, resource):
    results, failures = [], {}
    grouped = defaultdict(list)
    for rid, row in resource.rows:
        grouped[row["property"]].append((rid, row))
    expected, actual, pending = {}, {}, {}
    parsed = []
    field_map = resource.module.FIELDS
    outputs = set().union(*(catalog_outputs(ROOT, ".".join(prop.split(".")[:2])) for prop in grouped)) if grouped else set()
    for prop, rows in grouped.items():
        item = {"resource": resource.spec.get("logicalId", resource.number), "resourceType": resource.kind,
                "parent": resource.spec.get("parentReference"), "propertiesKey": prop,
                "modelKeys": ["desired.row." + rid + ".value" for rid, _ in rows], "source": source(resource, rows),
                "designValue": "[REDACTED]" if resource.module.sensitive(prop) else redacted([row["value"] for _, row in rows]),
                "awsValue": None, "apis": []}
        field = field_map.get(prop)
        if not field:
            results.append({**item, "status": "unimplemented", "reason": "no property/API mapping"})
            continue
        if field.classification != "supported":
            results.append({**item, "status": field.classification, "reason": field.reason})
            continue
        start = len(ctx.trace)
        try:
            response = ctx.fetch(resource, field.getter)
            value = select(response, field.path)
            if value == MISSING:
                value = field.default
            if resource.kind == "KMS.Alias" and response.get("ParentMismatch"):
                parent = resource.parent()
                results.append({**item, "status": "difference", "propertiesKey": "desired.resource." + resource.number + ".parentReference",
                                "designValue": parent.identity(), "awsValue": response.get("TargetKeyId"), "apis": ctx.trace[start:],
                                "reason": "alias belongs to a different KMS key"})
            if resource.kind == "Lambda.Function" and prop in {"Lambda.Function.Code.S3Bucket", "Lambda.Function.Code.S3Key"} and value == MISSING:
                results.append({**item, "status": "sdk_unavailable", "apis": ctx.trace[start:],
                                "reason": "GetFunction did not return Code.ResolvedS3Object; the original S3 upload location cannot be recovered from Code.Location"})
                continue
            if prop in outputs:
                if value == MISSING:
                    raise Unresolved("generated identifier is absent from SDK response")
                results.append({**item, "status": "identifier", "awsValue": redacted(value), "apis": ctx.trace[start:],
                                "reason": "resource identifier; not a desired configuration value"})
                continue
            values = [normalize(ctx, resource.parse(row, field.norm), field.norm) for _, row in rows]
            parsed.extend((rid, prop, val, row.get("comment", "")) for (rid, row), val in zip(rows, values))
            project(actual, prop, normalize(ctx, value, field.norm))
            pending[prop] = {**item, "apis": ctx.trace[start:], "normalization": field.norm}
        except AcquisitionError as error:
            key = error.request or (error.api, error.code, resource.number)
            failure = failures.setdefault(key, {**item, "status": error.status, "reason": error.code,
                                                "propertiesKey": None, "affectedKeys": [], "scope": "selected properties using this request",
                                                "apis": ctx.trace[start:] or [{"api": error.api}], "source": [], "modelKeys": []})
            failure["failureId"] = hashlib.sha256(stable(key).encode("utf-8")).hexdigest()
            failure["designValue"] = None
            failure.setdefault("designValues", {})[prop] = item["designValue"]
            failure["affectedKeys"].append(prop)
            failure["source"].extend(item["source"])
            failure["modelKeys"].extend(item["modelKeys"])
        except (Unresolved, ValueError, KeyError, TypeError) as error:
            results.append({**item, "status": "design_unresolved", "reason": str(error) if isinstance(error, Unresolved) else "invalid design or SDK value",
                            "apis": ctx.trace[start:]})
    # Restore catalog row order; grouping by property above must never reorder arrays.
    parsed.sort(key=lambda row: row[0])
    if resource.kind == "CodePipeline.Pipeline":
        rows = [[rid, prop.removeprefix(resource.kind + "."), stable(val) if isinstance(val, dict) else "`" + str(val) + "`", comment]
                for rid, prop, val, comment in parsed]
        for row in rows:
            if row[1].endswith(".Configuration"):
                row[3] = " / ".join(key + ": value" for key in json.loads(literal(row[2])))
        for rid, path, raw, _ in pipeline_rows(rows):
            path = re.sub(r"\.Actions\.(?!\[)", ".Actions[1].", path)
            val = literal(raw)
            try:
                val = json.loads(val)
            except ValueError:
                pass
            put_row(expected, resource.kind + "." + path, val)
    else:
        for rid, prop, value, _ in parsed:
            put_row(expected, prop, value)
    expected, actual = canonical(expected), canonical(actual)
    for prop, item in pending.items():
        desired, aws = select(expected, prop), select(actual, prop)
        # Never reveal variable plaintext; retain equality diagnostics only.
        hidden = resource.module.sensitive(prop)
        results.append({**item, "status": "match" if stable(desired) == stable(aws) else "difference",
                        "designValue": "[REDACTED]" if hidden else redacted(desired),
                        "awsValue": "[REDACTED]" if hidden else redacted(aws)})
    return results + list(failures.values())


def targets(root, environment=None, selector=None, all_targets=False):
    resolver = load_file("aws_compare_target", ROOT / "framework/scripts/check-deploy-context.py")
    topology = json.loads((root / "project.json").read_text(encoding="utf-8"))
    found = []
    seen = set()
    for entry in topology["targets"]:
        name = entry.get("alias", entry["awsAccountId"])
        if not all_targets and (entry["environment"] != environment or name != selector):
            continue
        key = (entry["environment"], name)
        if key in seen or Path(entry["environment"]).name != entry["environment"] or entry["environment"] in {".", "..", ""}:
            raise ValueError("duplicate or unsafe topology target")
        seen.add(key)
        target = resolver.load_target(root, entry["environment"], alias=entry.get("alias"),
                                      account_id=None if "alias" in entry else name)
        target.update(environment=entry["environment"], directory=name)
        found.append(target)
    if not found:
        raise ValueError("no matching topology target")
    return found


def inventory(root, selected_targets, services=None):
    requested = set(services or ())
    found = []
    for target in selected_targets:
        directory = root / "model" / target["environment"] / target["directory"]
        if not directory.is_dir():
            raise ValueError("target model directory is missing")
        paths = sorted(directory.glob("*.properties"))
        if requested:
            paths = [path for path in paths if path.stem in requested]
        if not paths:
            raise ValueError("no service entrance models for target")
        missing = requested - {path.stem for path in paths}
        if missing:
            raise ValueError("service entrance models are missing for target: " + ", ".join(sorted(missing)))
        for path in paths:
            found.append((target, path))
    return found


def coverage(root, items):
    counts, stack_counts, types, keys, models, problems, details = Counter(), Counter(), set(), set(), set(), [], []
    for target, path in items:
        service = path.stem
        models.add((target["environment"], target["directory"], service))
        try:
            module = service_module(service)
            values = properties(read_model(path))
            for _, resource in entries(values, "desired.resource."):
                types.add((service, resource["resourceType"]))
                if resource["resourceType"] not in module.RESOURCE_TYPES:
                    problems.append({"service": service, "resourceType": resource["resourceType"], "reason": "unimplemented resource type"})
            for _, row in entries(values, "desired.row."):
                prop = row["property"]
                rt = ".".join(prop.split(".")[:2])
                types.add((service, rt))
                if (service, prop) in keys:
                    continue
                keys.add((service, prop))
                field = module.FIELDS.get(prop)
                classification = field.classification if field else "unimplemented"
                counts[classification] += 1
                details.append({"service": service, "resourceType": rt, "propertiesKey": prop,
                                "classification": classification, "getter": field.getter if field else None,
                                "responsePath": field.path if field else None, "reason": field.reason if field else "no mapping"})
                if not field or rt not in module.RESOURCE_TYPES or (field.classification == "supported" and not field.getter):
                    problems.append(details[-1])
                if prop[len(rt) + 1:] not in selected_properties(ROOT, rt) and not prop.endswith((".Name", ".Region")):
                    problems.append({**details[-1], "reason": "key is outside catalog"})
            if service == "cloudformation-stacks":
                for key in values:
                    if key.startswith("desired."):
                        classification = module.classify(key)
                        stack_counts[classification] += 1
                        if classification == "unimplemented":
                            problems.append({"service": service, "key": key})
        except (OSError, ValueError, KeyError) as error:
            problems.append({"service": service, "reason": str(error)})
    return {"status": "incomplete" if problems else "coverage_complete", "services": sorted({s for _, _, s in models}),
            "modelCount": len(models), "resourceTypeCount": len(types), "keyCount": len(keys), "classifications": dict(counts),
            "stackFieldCounts": dict(stack_counts),
            "mappings": sorted(details, key=lambda x: (x["service"], x["propertiesKey"])), "problems": problems}


def summarize(results):
    merged, grouped = [], {}
    for item in results:
        if item["status"] == "acquisition_failed" and item.get("failureId"):
            key = (item.get("environment"), item.get("target"), item["failureId"])
            if key not in grouped:
                grouped[key] = dict(item, resource=None, propertiesKey=None, affectedResources=[])
                merged.append(grouped[key])
            group = grouped[key]
            group["affectedResources"].append({"service": item.get("service"), "resource": item["resource"],
                                               "keys": item["affectedKeys"], "source": item["source"],
                                               "designValues": item.get("designValues", {})})
            group["affectedKeys"] = sorted(set(group["affectedKeys"]) | set(item["affectedKeys"]))
            group["scope"] = "selected resources/keys sharing one failed SDK request"
        else:
            merged.append(item)
    results = merged
    counts = Counter(item["status"] for item in results)
    incomplete = set(counts) - {"match", "difference", "identifier", "local_metadata", "resource_missing"}
    state = "incomplete" if incomplete or not results else "different" if counts["difference"] or counts["resource_missing"] else "matched"
    return {"status": state, "exitCode": {"matched": 0, "different": 1, "incomplete": 2}[state], "counts": dict(counts), "results": results}


def run(root, items, profile=None, session_factory=None):
    # Reject every configured-profile conflict before creating any SDK session.
    for target, _ in items:
        if target.get("awsProfile") and profile is not None and profile != target["awsProfile"]:
            raise ValueError("explicit profile conflicts with target awsProfile")
    if session_factory is None:
        import boto3
        session_factory = boto3.Session
    contexts, results = {}, []
    for target, path in items:
        prefix = {"environment": target["environment"], "target": target["directory"], "service": path.stem}
        connection = (target["environment"], target["directory"])
        if connection not in contexts:
            try:
                session = session_factory(profile_name=target.get("awsProfile", profile), region_name=target["awsRegion"])
                ctx = Context(root, target, session)
                ctx.verify()
                contexts[connection] = ctx
            except Exception as error:
                contexts[connection] = error
        ctx = contexts[connection]
        if isinstance(ctx, Exception):
            results.append({**prefix, "resource": None, "propertiesKey": None, "status": "acquisition_failed",
                            "reason": ctx.code if isinstance(ctx, AcquisitionError) else type(ctx).__name__,
                            "affectedKeys": [row["property"] for _, row in entries(properties(read_model(path)), "desired.row.")],
                            "scope": "entire service; account/credentials were not verified", "apis": [{"api": "sts.get_caller_identity"}]})
            continue
        try:
            module = service_module(path.stem)
            model = ctx.model(path)
            values = module.compare(ctx, model) if path.stem == "cloudformation-stacks" else [item for resource in model.resources for item in compare_resource(ctx, resource)]
            results.extend({**prefix, **item} for item in values)
        except (OSError, ValueError, KeyError, AcquisitionError) as error:
            results.append({**prefix, "resource": None, "propertiesKey": None, "status": "design_unresolved",
                            "reason": error.code if isinstance(error, AcquisitionError) else "invalid model or SDK response", "apis": []})
    return summarize(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository holding project.json and authoritative model")
    parser.add_argument("--environment")
    parser.add_argument("--target", help="Confirmed alias, or account ID for a target without alias")
    parser.add_argument("--service", action="append", default=[], help="Exact service ID (repeatable)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--profile")
    parser.add_argument("--coverage", action="store_true", help="Offline key coverage; never creates an SDK session")
    parser.add_argument("--output", type=Path, help="Optional JSON result outside model; stdout otherwise")
    args = parser.parse_args()
    if args.all == bool(args.environment or args.target or args.service) or (not args.all and not all((args.environment, args.target, args.service))):
        parser.error("use --all alone, or specify --environment, --target and --service together")
    try:
        root = args.root.resolve()
        items = inventory(root, targets(root, args.environment, args.target, args.all), args.service)
        result = coverage(root, items) if args.coverage else run(root, items, args.profile)
        code = (2 if result["problems"] else 0) if args.coverage else result["exitCode"]
    except Exception as error:
        result, code = {"status": "incomplete", "reason": str(error) if type(error) is ValueError else type(error).__name__}, 2
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    if args.output:
        output = args.output.resolve()
        if output.is_relative_to(root) or output.suffix != ".json":
            parser.error("--output must be a .json file outside the repository")
        output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
