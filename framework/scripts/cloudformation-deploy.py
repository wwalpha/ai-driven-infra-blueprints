#!/usr/bin/env python3
"""Deploy ordered CloudFormation groups with resumable state outside Git."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlencode

from model_design import (properties, stack_model, markdown_for, deployment_settings,
                          deployment_bucket, ARTIFACT_PROPERTIES, LINK, cfn_resource_identity)
from model_files import read_model
from s3_delivery import preflight as placement_preflight, read as placement_read, upload_options, verify_encryption
from deploy_preparation import Timing
from issue_gate import require_target_no_issues
from issues_iac import Comparison, put_row, same
from task_contract import task_path, status, require_writable, paths_in
from cloudformation_inputs import Blocked, resolve_value, load_template_inputs, condition_active, output_value
from cloudformation_observed import MappingError, mappings, sync_successful, removed_resources
from validation_scope import active_scope as validation_scope

SUCCESS = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
FAILED = {"CREATE_FAILED", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "DELETE_COMPLETE", "DELETE_FAILED",
          "UPDATE_FAILED", "UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED",
          "IMPORT_ROLLBACK_COMPLETE", "IMPORT_ROLLBACK_FAILED"}


def load_units(root, environment, directory, scope):
    source = root / "model" / environment / directory / "cloudformation-stacks.properties"
    values = properties(read_model(source))
    limit, stacks = stack_model(values)
    design = root / "docs/designs" / environment / directory / "cloudformation-stacks.md"
    if design.read_text(encoding="utf-8") != markdown_for(design, values, root):
        raise Blocked("stack model/generated design mismatch; run sync-model before deploy")
    by_name = {stack["name"]: stack for _, stack in stacks}
    if not scope or len(set(scope)) != len(scope) or set(scope) - by_name.keys():
        raise Blocked("Deployment scope must contain unique designed StackName values")
    settings, artifacts = deployment_settings(values)
    selected = [dict(stack) for _, stack in stacks if stack["name"] in scope]
    for unit in selected:
        if settings:
            unit.update(settings)
            unit["templateBucket"] = deployment_bucket(settings["templateBucket"], design, root)
        assigned = [dict(artifact) for _, artifact in artifacts if artifact["stack"] == unit["name"]]
        for artifact in assigned:
            artifact["bucket"] = deployment_bucket(artifact["bucket"], design, root)
        if assigned:
            unit["artifacts"] = assigned
    return limit, selected


def read_parallel(units, states, method, limit):
    """Workers own copies only; all decisions and persistence remain on the controller."""
    def read(unit):
        state = copy.deepcopy(states[unit["name"]])
        try:
            return unit, state, method(unit, state), None
        except Exception as error:
            return unit, state, None, error
    if len(units) <= 1:
        return [read(unit) for unit in units]
    with ThreadPoolExecutor(max_workers=limit) as pool:
        return list(pool.map(read, units))


def run_group(units, limit, states, backend, save=lambda: None, sleep=time.sleep, drain_only=False):
    """Single event loop owns the queue; AWS executions overlap, Python decisions do not."""
    pending = [unit for unit in units if states[unit["name"]]["status"] != "SUCCESS"]
    if not pending:
        return "COMPLETE"
    order = min(int(unit["deployOrder"]) for unit in pending)
    group = [unit for unit in pending if int(unit["deployOrder"]) == order]
    stopped = drain_only or any(state["status"] == "FAILED" for state in states.values())
    if not stopped and hasattr(backend, 'prepare_delivery_group'):
        try:
            backend.prepare_delivery_group(group, states)
        except Exception as error:
            candidate = next((u for u in group if states[u['name']]['status'] not in {'RUNNING', 'SUCCESS'}), None)
            if candidate:
                states[candidate['name']].update(status='BLOCKED', reason=str(error))
            stopped = True
            save()
    while True:
        # Poll every running stack before reusing any freed slot.
        active = [unit for unit in group if states[unit["name"]]["status"] == "RUNNING"]
        for unit, snapshot, status, error in read_parallel(active, states, backend.poll, limit):
            state = states[unit["name"]]
            state.update(snapshot)
            try:
                if error:
                    raise error
                state["stackStatus"] = status
                if state.get("failureDetected") or "ROLLBACK" in status or status.endswith("_FAILED"):
                    stopped = True
                if status in SUCCESS:
                    state["status"] = "SUCCESS"
                elif status in FAILED:
                    state["status"] = "FAILED"
                    stopped = True
                elif not status.endswith("_IN_PROGRESS"):
                    raise Blocked(f"unrecognized stack status: {status}")
                state.pop("pollError", None)
                if state["status"] in {"SUCCESS", "FAILED"}:
                    state["executionSeconds"] = time.time() - state.get("executionStarted", time.time())
            except Exception as error:
                # Lost read access is not proof of terminal failure. Drain/retry only.
                state["pollError"] = str(error)
                stopped = True
            save()
        running = sum(states[unit["name"]]["status"] == "RUNNING" for unit in group)
        assert running <= limit
        # Start multiple change sets without waiting for one to become CREATE_COMPLETE.
        # Preparation is bounded too; do not speculate across DeployOrder barriers.
        preparing = sum(states[u["name"]]["status"] == "CHANGESET_CREATING" for u in group)
        if not stopped:
            pending = [u for u in group if states[u["name"]]["status"] in {"NOT_STARTED", "BLOCKED"}]
            for unit in pending[:max(0, limit - running - preparing)]:
                state = states[unit["name"]]
                try:
                    begin = getattr(backend, "begin_prepare", backend.prepare)
                    state["status"] = begin(unit, state)
                except Exception as error:
                    state["status"] = "BLOCKED"
                    state["reason"] = str(error)
                    stopped = True
                if state["status"] == "BLOCKED":
                    stopped = True
                save()
                if stopped:
                    break
        if not stopped:
            creating = [u for u in group if states[u["name"]]["status"] == "CHANGESET_CREATING"]
            for unit, snapshot, change_set, error in read_parallel(creating, states, backend.describe_change_set if creating else backend.poll, limit):
                state = states[unit["name"]]
                state.update(snapshot)
                try:
                    if error:
                        raise error
                    # Workers fetch only. Classification and approval decisions stay here.
                    state["status"] = backend.review_prepared(unit, state, change_set)
                except Exception as error:
                    state["status"], state["reason"] = "BLOCKED", str(error)
                if state["status"] == "BLOCKED":
                    stopped = True
                save()
        if not stopped:
            ready = [u for u in group if states[u["name"]]["status"] == "READY"]
            for unit in ready[:max(0, limit - running)]:
                state = states[unit["name"]]
                try:
                    # Persist execution intent before AWS mutation, including interruptions.
                    state["status"] = "RUNNING"
                    state["clientToken"] = state.get("clientToken", uuid.uuid4().hex)
                    state["executionStarted"] = time.time()
                    save()
                    backend.execute(unit, state)
                except Exception as error:
                    state["reason"] = str(error)
                    stopped = True
                save()
                if stopped:
                    break
        running = sum(states[u["name"]]["status"] == "RUNNING" for u in group)
        if not running:
            if stopped:
                return "STOPPED"
            if all(states[unit["name"]]["status"] == "SUCCESS" for unit in group):
                return "GROUP_COMPLETE"
        sleep(5)


def import_names(template, parameters, pseudo):
    """Resolve only stack-independent intrinsic expressions; unknown expressions block."""
    names = set()
    conditions = template.get("Conditions", {})
    def condition(name):
        return resolve_value({"Condition": name}, parameters, pseudo, conditions=conditions)

    def visit(value):
        if isinstance(value, dict):
            if "Fn::If" in value:
                argument = value["Fn::If"]
                if len(value) != 1 or not isinstance(argument, list) or len(argument) != 3:
                    raise Blocked("invalid Fn::If expression")
                visit(argument[1 if condition(argument[0]) else 2])
                return
            for key, child in value.items():
                if key == "Fn::ImportValue":
                    name = resolve_value(child, parameters, pseudo, conditions=conditions)
                    if not isinstance(name, str) or not name:
                        raise Blocked("ImportValue name must be nonempty")
                    names.add(name)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for section, contents in template.items():
        if section in {"Resources", "Outputs"}:
            for definition in contents.values():
                if "Condition" not in definition or condition(definition["Condition"]):
                    visit(definition)
        elif section not in {"Conditions", "Mappings", "Parameters"}:
            visit({section: contents})
    return names


def change_summary(change_set):
    result = []
    for change in change_set.get("Changes", []):
        resource = change.get("ResourceChange", {})
        if resource.get("Action") not in {"Add", "Modify", "Remove"}:
            raise Blocked("unknown change set action")
        if resource.get("Action") == "Modify" and resource.get("Replacement") not in {"True", "False", "Conditional"}:
            raise Blocked("unknown change set replacement")
        result.append({key: resource.get(key) for key in
                       ("LogicalResourceId", "PhysicalResourceId", "ResourceType", "Action", "Replacement", "PolicyAction")})
    return sorted(result, key=lambda item: item["LogicalResourceId"] or "")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def repair_template(text, logical, prop, value):
    """Change one property using source spans, preserving all other YAML bytes."""
    import yaml
    value = json.loads(json.dumps(value))
    if text.lstrip().startswith('{'):
        document = json.loads(text)
        document['Resources'][logical].setdefault('Properties', {})[prop] = value
        return json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    class Dumper(yaml.SafeDumper):
        pass
    def intrinsic(dumper, item):
        if len(item) == 1:
            key, argument = next(iter(item.items()))
            if key == 'Ref' or key.startswith('Fn::'):
                tag = '!' + key.removeprefix('Fn::')
                if isinstance(argument, list):
                    return dumper.represent_sequence(tag, argument, flow_style=True)
                if isinstance(argument, dict):
                    return dumper.represent_mapping(tag, argument, flow_style=True)
                return dumper.represent_scalar(tag, str(argument))
        return dumper.represent_dict(item)
    Dumper.add_representer(dict, intrinsic)
    node = yaml.compose(text)
    def child(node, key):
        found = [value for name, value in node.value if name.value == key]
        if len(found) != 1:
            raise Blocked('missing/ambiguous YAML mapping: ' + key)
        return found[0]
    resource = child(child(node, 'Resources'), logical)
    properties_nodes = [val for key, val in resource.value if key.value == 'Properties']
    missing_properties = not properties_nodes
    properties_node = child(resource, 'Properties') if properties_nodes else resource
    rendered = yaml.dump({prop: value}, Dumper=Dumper, allow_unicode=True, sort_keys=False).rstrip()
    found = [(key, val) for key, val in properties_node.value if key.value == prop]
    if len(found) > 1:
        raise Blocked('duplicate YAML property')
    if missing_properties:
        found = []
    if properties_node.flow_style:
        mapping = {'Properties': {prop: value}} if missing_properties else {prop: value}
        flow = yaml.dump(mapping, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                         default_flow_style=True, width=1000000).strip()[1:-1]
        if found:
            key, val = found[0]
            start, end = key.start_mark.index, val.end_mark.index
        else:
            start = end = properties_node.end_mark.index - 1
            flow = (', ' if properties_node.value else '') + flow
        result = text[:start] + flow + text[end:]
    elif found:
        key, val = found[0]
        start = text.rfind('\n', 0, key.start_mark.index) + 1
        end = val.end_mark.index
        # A block node ends at the next key's indentation; do not consume that key.
        end = text.rfind('\n', 0, end) + 1 if not text[text.rfind('\n', 0, end)+1:end].strip() else end
        if end < len(text) and text[end] == '\n':
            end += 1
        indent = key.start_mark.column
    elif not properties_node.flow_style:
        start = end = properties_node.end_mark.index
        if not text[text.rfind('\n', 0, end)+1:end].strip():
            start = end = text.rfind('\n', 0, end) + 1
        indent = properties_node.start_mark.column
    if not properties_node.flow_style:
        if missing_properties:
            rendered = 'Properties:\n' + '\n'.join('  ' + line for line in rendered.splitlines())
        replacement = '\n'.join(' ' * indent + line for line in rendered.splitlines()) + '\n'
        result = text[:start] + replacement + text[end:]
    # Fail closed if the source-span edit touched anything except the selected property.
    from cfnlint.decode import decode_str as loads
    before, errors = loads(text)
    after, later = loads(result)
    expected = copy.deepcopy(before)
    expected['Resources'][logical].setdefault('Properties', {})[prop] = value
    if errors or later or not same(json.loads(json.dumps(expected)), json.loads(json.dumps(after))):
        raise Blocked('repair source edit changed unrelated template content')
    return result


def merge_selected(actual, desired, prop=""):
    if isinstance(actual, dict) and isinstance(desired, dict):
        return dict(actual) | {key: merge_selected(actual.get(key), val, key) for key, val in desired.items()}
    if isinstance(actual, list) and isinstance(desired, list) and prop in {'Tags', 'HostedZoneTags'}:
        if not all(isinstance(item, dict) and 'Key' in item for item in actual + desired):
            raise Blocked('ambiguous keyed tag setting')
        replacements = {item['Key']: item for item in desired}
        if len(replacements) != len(desired) or len({item['Key'] for item in actual}) != len(actual):
            raise Blocked('duplicate tag identities')
        result = [merge_selected(item, replacements.pop(item['Key'])) if item['Key'] in replacements else item for item in actual]
        return result + list(replacements.values())
    if isinstance(actual, list) and isinstance(desired, list) and len(actual) != len(desired) and any(isinstance(item, dict) for item in actual + desired):
        raise Blocked('partial object-array membership cannot be changed without complete design')
    if isinstance(actual, list) and isinstance(desired, list) and len(actual) == len(desired):
        return [merge_selected(a, b) for a, b in zip(actual, desired)]
    return desired


class AwsBackend:
    def __init__(self, root, environment, directory, target, profile=None, approvals=()):
        configured_profile = target.get("awsProfile")
        if configured_profile and profile is not None and profile != configured_profile:
            raise Blocked("explicit AWS profile does not match target awsProfile")
        self.root, self.environment, self.directory = root, environment, directory
        self.target, self.profile, self.approvals = target, configured_profile or profile, set(approvals)
        self.timing = Timing(root)
        self.templates = {}
        self.validated_digests = {}
        self.validation_failures = {}
        self.expected_digests = {}
        self.workdir = None
        self.states = {}
        self.save = lambda: None
        self.guard = lambda: None
        self.hashes = {}
        self.session = {}
        self.refresh_validation = lambda unit: None
        self.uploaded = {}

    def aws(self, operation, *arguments, service="cloudformation"):
        if operation in {"create-change-set", "execute-change-set", "put-object", "delete-stack"}:
            self.guard()
            try:
                require_target_no_issues(self.root, (self.environment, self.directory))
            except (OSError, ValueError) as error:
                raise Blocked(str(error)) from error
        command = ["aws", "--region", self.target["awsRegion"]]
        if self.profile:
            command += ["--profile", self.profile]
        with self.timing.phase("awsApi", service=service, operation=operation):
            result = subprocess.run(command + [service, operation, *arguments, "--output", "json", "--no-cli-pager"],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise Blocked(result.stderr.strip())
            return json.loads(result.stdout or "{}")

    def paths(self, unit):
        template = self.root / "infra/cloudformation/templates" / self.target.get("alias", "") / unit["template"]
        parameters = self.root / "infra/cloudformation/parameters" / self.environment / self.directory / unit["parameters"]
        return template, parameters

    def source_path(self, artifact):
        path = (self.root / artifact["source"]).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_relative_to((self.root / "infra/cloudformation/artifacts").resolve()) or not path.is_file():
            raise Blocked(f"artifact source is missing or escapes its directory: {artifact['source']}")
        if artifact["property"] in {"Code", "Content"} and (path.suffix != ".zip" or not zipfile.is_zipfile(path)):
            raise Blocked("Lambda artifact must be a prebuilt ZIP file")
        return path

    def file_digest(self, path, fresh=False):
        stat = path.stat()
        identity = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
        previous = self.hashes.get(path)
        if fresh or previous is None or previous[:4] != identity:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            after = path.stat()
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino) != identity:
                raise Blocked("deployment input changed while hashing")
            self.hashes[path] = (*identity, digest)
        return self.hashes[path][4]

    def deployment_input_paths(self, units):
        return [path for unit in units
                for path in [*self.paths(unit), *[self.source_path(a) for a in unit.get("artifacts", [])]]]

    def input_digest(self, unit, fresh=False):
        return fingerprint([self.file_digest(path, fresh) for path in self.deployment_input_paths([unit])])

    def validate(self, unit):
        template, parameters = self.paths(unit)
        digest = self.input_digest(unit, fresh=True)
        if unit["name"] in self.expected_digests and self.expected_digests[unit["name"]] != digest:
            raise Blocked("deployment inputs changed before validation")
        result = subprocess.run(["cfn-lint", "--regions", self.target["awsRegion"], "--template", str(template), "--format", "json"],
                                capture_output=True, text=True)
        if result.returncode:
            events = []
            try:
                document, _ = load_template_inputs(template, parameters)
                for diagnostic in json.loads(result.stdout):
                    location = diagnostic.get('Location', {}).get('Path', [])
                    if len(location) < 3 or location[0] != 'Resources' or location[2] != 'Properties':
                        continue
                    logical, prop = location[1], location[3] if len(location) > 3 else ''
                    definition = document['Resources'][logical]
                    events.append({'LogicalResourceId': logical, 'ResourceType': definition['Type'],
                                   'ResourceStatus': 'STATIC_VALIDATION_FAILED',
                                   'ResourceStatusReason': str(prop) + ': ' + diagnostic.get('Message', '')})
            except (ValueError, KeyError, TypeError, Blocked):
                pass  # Invalid syntax/unknown location is HUMAN_REQUIRED, never a guessed edit.
            self.validation_failures[unit['name']] = events
            raise Blocked(f"cfn-lint failed: {unit['name']}: {result.stdout}{result.stderr}")
        self.load_inputs(unit)
        if self.input_digest(unit, fresh=True) != digest:
            raise Blocked("deployment inputs changed during validation")
        self.validated_digests[unit["name"]] = digest

    def load_inputs(self, unit):
        """Decode current immutable files cheaply; never persist parameter/secret contents."""
        template, parameters = self.paths(unit)
        self.templates[unit["name"]] = load_template_inputs(template, parameters)
        document, _ = self.templates[unit["name"]]
        for artifact in unit.get("artifacts", []):
            self.source_path(artifact)
            resource = document.get("Resources", {}).get(artifact["resource"], {})
            if (resource.get("Type"), artifact["property"]) not in ARTIFACT_PROPERTIES:
                raise Blocked("artifact resource/type/property does not match the declared template")
        if not unit.get("artifacts") and template.stat().st_size > 1024 * 1024:
            raise Blocked("template exceeds the 1 MiB CloudFormation limit")

    def verify_object(self, obj):
        arguments = ["--bucket", obj["bucket"], "--key", obj["key"], "--expected-bucket-owner", self.target.get("awsExecutionAccountId", self.target["awsAccountId"]),
                     "--checksum-mode", "ENABLED"]
        if obj.get("version"):
            arguments += ["--version-id", obj["version"]]
        current = placement_read(self, "head-object", *arguments)
        if current.get("ChecksumSHA256") != obj["checksum"] or current.get("ContentLength") != obj["size"]:
            raise Blocked("S3 artifact checksum/size changed; upload or execution blocked")
        if 'encryption' not in obj:
            raise Blocked('S3_PLACEMENT_INDETERMINATE: legacy object lacks resolved encryption conditions')
        conditions = placement_preflight(self, obj['bucket'], obj['prefix'], [obj['key']])
        if conditions != obj['encryption']:
            raise Blocked('S3_PLACEMENT_CHANGED: object placement conditions changed')
        verify_encryption(current, conditions)
        return current

    def upload(self, path, bucket, prefix):
        digest = self.file_digest(path)
        obj = {"bucket": bucket, "key": prefix + digest + path.suffix,
               "checksum": base64.b64encode(bytes.fromhex(digest)).decode(), "size": path.stat().st_size,
               "prefix": prefix}
        obj['encryption'] = placement_preflight(self, bucket, prefix, [obj['key']])
        cache_key = (bucket, obj["key"], digest)
        if cache_key in self.uploaded:
            self.verify_object(self.uploaded[cache_key])
            return dict(self.uploaded[cache_key])
        try:
            current = self.verify_object(obj)
        except Blocked as error:
            if not any(code in str(error) for code in ("(404)", "(NoSuchKey)", "(NotFound)")):
                raise
            try:
                current = self.aws("put-object", "--bucket", bucket, "--key", obj["key"], "--body", str(path),
                    "--expected-bucket-owner", self.target.get("awsExecutionAccountId", self.target["awsAccountId"]), "--if-none-match", "*",
                    "--checksum-algorithm", "SHA256", "--checksum-sha256", obj["checksum"],
                    *upload_options(obj['encryption']), service="s3api")
            except Blocked as error:
                if "(PreconditionFailed)" not in str(error):
                    raise Blocked('S3_PLACEMENT_UPLOAD_DENIED_OR_FAILED: ' + str(error)) from error
                current = self.verify_object(obj)
        if current.get("VersionId") not in {None, "null"}:
            obj["version"] = current["VersionId"]
        self.verify_object(obj)
        self.uploaded[cache_key] = dict(obj)
        return obj

    def artifact_bindings(self, unit, document, parameters):
        pseudo = {"AWS::AccountId": self.target.get("awsExecutionAccountId", self.target["awsAccountId"]), "AWS::Region": self.target["awsRegion"], "AWS::StackName": unit["name"]}
        # Resolve every mapping before the first upload, including bucket/prefix consistency.
        bindings = []
        exports = {e["Name"]: e["Value"] for e in self.aws("list-exports").get("Exports", [])} if unit.get("artifacts") else {}
        for artifact in unit.get("artifacts", []):
            resource = document["Resources"][artifact["resource"]]
            if not condition_active(document, parameters, pseudo, resource):
                continue
            container = resource["Properties"]
            parts = artifact["property"].split(".")
            for part in parts[:-1]:
                container = container[part]
            value = container[parts[-1]]
            fields = ARTIFACT_PROPERTIES[(resource["Type"], artifact["property"])]
            if fields:
                if not isinstance(value, dict) or not {fields[0], fields[1]} <= value.keys():
                    raise Blocked("artifact property must already declare its S3 bucket and key")
                bucket = resolve_value(value[fields[0]], parameters, pseudo, exports)
                key = resolve_value(value[fields[1]], parameters, pseudo, exports)
            else:
                uri = resolve_value(value, parameters, pseudo, exports)
                match = re.fullmatch(r"s3://([^/]+)/(.+)", uri)
                if not match:
                    raise Blocked("artifact property must declare an S3 URI")
                bucket, key = match.groups()
            if bucket != artifact["bucket"] or not key.startswith(artifact["keyPrefix"]):
                raise Blocked("artifact bucket/keyPrefix differs from the approved template")
            bindings.append((artifact, container, parts[-1], fields))
        return bindings

    def prepare_delivery_group(self, units, states):
        """Read all destinations, stage all files, then allow bounded change set creation."""
        pending = [u for u in units if states[u['name']]['status'] not in {'RUNNING', 'SUCCESS'}]
        destinations = {}
        for unit in pending:
            self.check_imports(unit)
            document, parameters = self.templates[unit['name']]
            bindings = self.artifact_bindings(unit, document, parameters)
            for artifact, _, _, _ in bindings:
                path = self.source_path(artifact)
                key = artifact['keyPrefix'] + self.file_digest(path) + path.suffix
                destinations.setdefault((artifact['bucket'], artifact['keyPrefix']), set()).add(key)
            delivery = states[unit['name']].get('delivery', {})
            for obj in delivery.get('objects', []):
                destinations.setdefault((obj['bucket'], obj.get('prefix', '')), set()).add(obj['key'])
        for (bucket, prefix), keys in destinations.items():
            placement_preflight(self, bucket, prefix, sorted(keys))
        # Artifact versions determine the actual execution-template byte size.
        for unit in pending:
            self.template_arguments(unit, states[unit['name']], stage_only=True)
        destinations = {}
        for unit in pending:
            delivery = states[unit['name']]['delivery']
            path = Path(delivery['path'])
            if path.stat().st_size > 51200:
                if not unit.get('templateBucket') or not unit.get('templateKeyPrefix'):
                    raise Blocked('large template requires designed TemplateBucket and TemplateKeyPrefix')
                key = unit['templateKeyPrefix'] + self.file_digest(path) + path.suffix
                destinations.setdefault((unit['templateBucket'], unit['templateKeyPrefix']), set()).add(key)
        for (bucket, prefix), keys in destinations.items():
            placement_preflight(self, bucket, prefix, sorted(keys))
        for unit in pending:
            self.template_arguments(unit, states[unit['name']])

    def template_arguments(self, unit, state, stage_only=False):
        """Prepare only declared S3 references in a copy outside the repository."""
        if state.get("delivery"):
            delivery = state["delivery"]
            document, parameters = self.templates[unit["name"]]
            self.artifact_bindings(unit, document, parameters)
            if self.input_digest(unit) != delivery["inputDigest"]:
                raise Blocked("prepared deployment inputs changed")
            path = Path(delivery["path"])
            if self.file_digest(path) != delivery["templateSha256"]:
                raise Blocked("prepared deployment template changed")
            for obj in delivery["objects"]:
                self.verify_object(obj)
            if delivery.get('arguments'):
                return delivery['arguments']
            path, objects = Path(delivery['path']), delivery['objects']
            input_digest = delivery['inputDigest']
        else:
            path, _ = self.paths(unit)
            document, parameters = self.templates[unit["name"]]
            document = copy.deepcopy(document)
            objects = []
            input_digest = self.input_digest(unit)
            if unit["name"] in self.validated_digests and self.validated_digests[unit["name"]] != input_digest:
                raise Blocked("deployment inputs changed after validation")
            bindings = self.artifact_bindings(unit, document, parameters)
            if bindings:
                if self.workdir is None:
                    raise Blocked("artifact packaging requires the external deployment session directory")
                for artifact, container, prop, fields in bindings:
                    obj = self.upload(self.source_path(artifact), artifact["bucket"], artifact["keyPrefix"])
                    objects.append(obj)
                    if fields:
                        container[prop][fields[1]] = obj["key"]
                        container[prop].pop(fields[2], None)
                        if obj.get("version"):
                            container[prop][fields[2]] = obj["version"]
                    else:
                        container[prop] = f"s3://{obj['bucket']}/{obj['key']}"
                self.workdir.mkdir(parents=True, exist_ok=True)
                path = self.workdir / (unit["name"] + ".json")
                path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                result = subprocess.run(["cfn-lint", "--regions", self.target["awsRegion"], "--template", str(path)], capture_output=True, text=True)
                if result.returncode:
                    raise Blocked("packaged template cfn-lint failed: " + result.stdout + result.stderr)
        size = path.stat().st_size
        if size > 1024 * 1024:
            raise Blocked("template exceeds the 1 MiB CloudFormation limit")
        state['delivery'] = {'inputDigest': input_digest, 'path': str(path),
                             'templateSha256': self.file_digest(path), 'objects': objects}
        self.save()
        if stage_only:
            return []
        arguments = ["--template-body", "file://" + str(path)]
        if size > 51200:
            if not unit.get("templateBucket") or not unit.get("templateKeyPrefix"):
                raise Blocked("large template requires designed TemplateBucket and TemplateKeyPrefix")
            obj = self.upload(path, unit["templateBucket"], unit["templateKeyPrefix"])
            objects.append(obj)
            suffix = "amazonaws.com.cn" if self.target["awsRegion"].startswith("cn-") else "amazonaws.com"
            url = f"https://s3.{self.target['awsRegion']}.{suffix}/{obj['bucket']}/{quote(obj['key'], safe='/')}"
            if obj.get("version"):
                url += "?" + urlencode({"versionId": obj["version"]})
            arguments = ["--template-url", url]
        if self.input_digest(unit) != input_digest:
            raise Blocked("deployment inputs changed while preparing artifacts")
        state["delivery"] = {"inputDigest": input_digest, "path": str(path), "arguments": arguments,
                             "templateSha256": self.file_digest(path), "objects": objects}
        self.save()
        return arguments

    def check_imports(self, unit):
        document, parameters = self.templates[unit["name"]]
        names = import_names(document, parameters, {"AWS::AccountId": self.target.get("awsExecutionAccountId", self.target["awsAccountId"]),
            "AWS::Region": self.target["awsRegion"], "AWS::StackName": unit["name"]})
        if names:
            exports = {entry["Name"]: entry for entry in self.aws("list-exports").get("Exports", [])}
            missing = names - exports.keys()
            if missing:
                raise Blocked("designed DeployOrder conflicts with Import/Export: missing export / producer deploy required: "
                              + ", ".join(sorted(missing)) + "; scope/order unchanged")
            for name in names:
                owner = exports[name].get("ExportingStackId", "").split(":stack/")[-1].split("/")[0]
                if owner in self.states and self.states[owner]["status"] != "SUCCESS":
                    raise Blocked(f"designed DeployOrder conflicts with Import/Export: producer {owner} has not succeeded")

    def describe_change_set(self, unit, state):
        return self.aws("describe-change-set", "--stack-name", unit["name"], "--change-set-name", state["changeSetId"])

    def verify_stack_ownership(self, unit):
        """Inspect the exact designed stack, never enumerate unrelated stacks."""
        actuals = self.aws("list-stack-resources", "--stack-name", unit["name"]).get("StackResourceSummaries", [])
        actual_by_id = {item["LogicalResourceId"]: item for item in actuals}
        if len(actual_by_id) != len(actuals):
            raise Blocked("existing stack has ambiguous resource ownership")
        document, _ = self.templates[unit["name"]]
        for logical, definition in document.get("Resources", {}).items():
            if logical in actual_by_id and actual_by_id[logical]["ResourceType"] != definition["Type"]:
                raise Blocked(f"existing stack resource type differs from designed ownership: {unit['name']}/{logical}")

    def begin_prepare(self, unit, state):
        self.check_imports(unit)  # Also recheck when resuming an approved change set.
        if state.get('cleanupStatus') == 'DELETE_INTENT':
            if not self.cleanup_failed_create(unit, state, empty_only=True):
                raise Blocked('failed CREATE resources are not all deleted; cleanup requires human')
            state['emptyStackRecreated'] = True
            self.reset_after_cleanup(state)
        arguments = self.template_arguments(unit, state)
        if not state.get("changeSetId"):
            try:
                stack = self.aws("describe-stacks", "--stack-name", unit["name"])["Stacks"][0]
            except Blocked as error:
                if "does not exist" not in str(error):
                    raise
                stack = None
            if stack and state.get('cleanupStatus') == 'DELETE_COMPLETE':
                raise Blocked('failed CREATE name was reused after cleanup; never adopt another stack')
            if stack and stack['StackStatus'] == 'ROLLBACK_COMPLETE':
                if state.get('stackId') and state['stackId'] != stack['StackId']:
                    raise Blocked('failed CREATE stack identity changed')
                state.update(stackStatus='ROLLBACK_COMPLETE', stackId=stack['StackId'])
                self.save()
                if not self.cleanup_failed_create(unit, state, empty_only=True):
                    raise Blocked('failed CREATE resources are not all deleted; cleanup requires human')
                state['emptyStackRecreated'] = True
                self.reset_after_cleanup(state)
                arguments = self.template_arguments(unit, state)
                stack = None
            if stack and stack["StackStatus"] not in SUCCESS | {"UPDATE_ROLLBACK_COMPLETE"}:
                raise Blocked(f"stack not updateable: {stack['StackStatus']}")
            if stack:
                self.verify_stack_ownership(unit)
            _, parameters = self.paths(unit)
            self.aws("validate-template", *arguments)
            state["operationType"] = "UPDATE" if stack else "CREATE"
            state["absentBeforeCreate"] = stack is None
            state["changeSetId"] = "blueprint-" + uuid.uuid4().hex
            state["changeSetStarted"] = time.time()
            self.save()
            started = time.perf_counter()
            response = self.aws("create-change-set", "--stack-name", unit["name"],
                "--change-set-name", state["changeSetId"],
                "--change-set-type", "UPDATE" if stack else "CREATE",
                *arguments, "--parameters", "file://" + str(parameters),
                "--capabilities", "CAPABILITY_NAMED_IAM")
            state["changeSetId"] = response["Id"]
            state["stackId"] = response.get("StackId")
            state["changeSetCreateSeconds"] = time.perf_counter() - started
            self.save()
        return "CHANGESET_CREATING"

    def review_prepared(self, unit, state, change_set=None):
        change_set = self.describe_change_set(unit, state) if change_set is None else change_set
        if change_set["Status"] in {"CREATE_PENDING", "CREATE_IN_PROGRESS"}:
            return "CHANGESET_CREATING"
        state["changeSetWaitSeconds"] = max(0, time.time() - state.get("changeSetStarted", time.time())
                                             - state.get("changeSetCreateSeconds", 0))
        if change_set["Status"] == "FAILED" and any(text in change_set.get("StatusReason", "") for text in
                ("didn't contain changes", "No updates are to be performed")):
            if self.aws("describe-stacks", "--stack-name", unit["name"])["Stacks"][0]["StackStatus"] in SUCCESS:
                state["reason"] = "no changes; existing stack terminal success"
                return "SUCCESS"
        if change_set["Status"] != "CREATE_COMPLETE" or change_set["ExecutionStatus"] != "AVAILABLE":
            raise Blocked("change set is not CREATE_COMPLETE/AVAILABLE: " + change_set.get("StatusReason", change_set["Status"]))
        summary = change_summary(change_set)
        digest = fingerprint(change_set.get("Changes", []))
        if state.get("changeDigest") and digest != state["changeDigest"]:
            raise Blocked("same change set contents changed; previous approval invalid")
        state["changeDigest"], state["changes"] = digest, summary
        destructive = any(item["Action"] == "Remove" or item["Replacement"] in {"True", "Conditional"} for item in summary)
        if destructive and state["changeSetId"] not in self.approvals:
            state["failureClassification"] = "HUMAN_REQUIRED"
            state["reason"] = "unapproved delete/replacement; change set unexecuted; human confirmation required"
            return "BLOCKED"
        state.pop("reason", None)
        return "READY"

    def prepare(self, unit, state):
        """Compatibility entry point; the controller uses nonblocking preparation."""
        self.begin_prepare(unit, state)
        while True:
            result = self.review_prepared(unit, state)
            if result != "CHANGESET_CREATING":
                return result
            time.sleep(5)

    def execute(self, unit, state):
        # Re-fetch the exact immutable approval artifact immediately before execution.
        expected = self.expected_digests.get(unit["name"], self.validated_digests.get(unit["name"]))
        if expected is not None and self.input_digest(unit, fresh=True) != expected:
            state["status"] = "BLOCKED"
            raise Blocked("deployment inputs changed before execution")
        if state.get("delivery") and self.file_digest(Path(state["delivery"]["path"]), fresh=True) != state["delivery"]["templateSha256"]:
            state["status"] = "BLOCKED"
            raise Blocked("prepared deployment template changed")
        try:
            self.template_arguments(unit, state)
        except Blocked:
            state['status'] = 'BLOCKED'  # No stack execution was sent; drain only already-running peers.
            raise
        self.check_imports(unit)
        current = self.describe_change_set(unit, state)
        if current["Status"] != "CREATE_COMPLETE" or current["ExecutionStatus"] != "AVAILABLE" or \
                fingerprint(current.get("Changes", [])) != state["changeDigest"]:
            state["status"] = "BLOCKED"
            raise Blocked("change set expired or changed before execution; approval invalid")
        removed = removed_resources([unit], {unit["name"]: state})
        if removed[unit["name"]]:
            # Deletions bypass the new template's false/absent Condition, but require ownership before mutation.
            loaded, mapped = mappings(self.root, self.environment, self.directory, self.templates,
                                     getattr(self, "mapping_units", [unit]), removed, target=self.target)
            if hasattr(self, "mapping_plan"):
                for name, resources in self.mapping_plan[1].items():
                    for logical, previous in resources.items():
                        if mapped[name].get(logical, ())[:2] != previous[:2]:
                            raise Blocked("resource mapping changed before execution")
                # Keep deletion mappings for earlier successful stacks in the same controller run.
                for name, resources in self.mapping_plan[1].items():
                    mapped[name] = resources | mapped[name]
            self.mapping_plan = (loaded, mapped)
        self.aws("execute-change-set", "--stack-name", unit["name"], "--change-set-name", state["changeSetId"],
                 "--client-request-token", state["clientToken"])

    def repair_plan(self, unit, state):
        """Use the existing typed model projection; error text selects scope, never values."""
        scope = validation_scope(self.root)
        if not scope:
            raise Blocked('repair needs explicit service Validation scope')
        owned = getattr(self, 'mapping_plan', ({}, {}))[1].get(unit['name'], {})
        affected = {owned[event['LogicalResourceId']][0].stem for event in state.get('failureEvents', [])
                    if event.get('LogicalResourceId') in owned}
        comparison = Comparison(self.root, self.environment, self.directory,
                                sorted(affected) or [service for env, directory, service in scope
                                 if (env, directory) == (self.environment, self.directory) and service != 'cloudformation-stacks'])
        if comparison.load_errors:
            raise Blocked('authoritative repair model cannot be loaded')
        path, (document, _, _) = comparison.stack(unit)
        failed = [event for event in state.get('failureEvents', [])
                  if event['ResourceType'] != 'AWS::CloudFormation::Stack' and event['ResourceStatus'].endswith('_FAILED')
                  and 'cancel' not in (event.get('ResourceStatusReason') or '').lower()]
        if not failed:
            raise Blocked('no resource failure diagnostics tied to this execution')
        direct, legacy = comparison.index()
        from cloudformation_observed import mapped_resource
        from model_design import catalog_outputs
        edits, classes, export_snapshot, producer_snapshots = [], [], {}, {}
        for event in failed:
            logical = event['LogicalResourceId']
            definition = document.get('Resources', {}).get(logical)
            if not definition or definition['Type'] != event['ResourceType']:
                raise Blocked('failed resource outside authoritative template ownership')
            source, identity, resource, _ = mapped_resource(direct, legacy, unit['name'], logical, definition['Type'], True)
            if (self.environment, self.directory, source.stem) not in scope:
                raise Blocked('failure outside service task scope')
            comparison.results = []
            comparison.compare_rows(source.stem, identity, resource, unit['name'], logical, path, definition, document)
            differences = [item for item in comparison.results if item['category'] == 'difference']
            reason = (event.get('ResourceStatusReason') or '').lower()
            kind = resource['resourceType']
            # Stable classes ignore request IDs and changing physical IDs.
            selector = ('VpcConfig' if kind == 'Lambda.Function' and 'subnet' in reason else
                        'CatalogId' if kind.startswith('Glue.') and ('catalog' in reason or 'accessdenied' in reason or 'access denied' in reason) else
                        next((key for key in ('KmsKeyId', 'KmsKeyArn', 'TargetKeyId', 'KeyPolicy')
                              if any(item['property'] == kind + '.' + key for item in differences)), None)
                        if 'kms' in reason or kind.startswith('KMS.') else None)
            selected = [item for item in differences if selector and item['property'] == kind + '.' + selector
                        or not selector and item['property'].rsplit('.', 1)[-1].lower() in reason]
            if not selected:
                def mentioned(item):
                    if isinstance(item, dict):
                        return any(mentioned(value) for value in item.values())
                    if isinstance(item, list):
                        return any(mentioned(value) for value in item)
                    return isinstance(item, str) and len(item) >= 8 and item.lower() in reason
                selected = [item for item in differences if mentioned(definition.get('Properties', {}).get(
                    item['property'].removeprefix(kind + '.')))]
            if len(selected) != 1:
                raise Blocked('failure has no unique model-derived property correction')
            prop = selected[0]['property'].removeprefix(kind + '.')
            if '.' in prop or prop in catalog_outputs(self.root, kind):
                raise Blocked('repair needs explicit property ownership')
            desired, exact = {}, False
            for _, row in comparison.rows[source.stem][identity]:
                short = row['property'].removeprefix(kind + '.')
                if short == 'Name' and kind in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'} and prop == 'Tags':
                    from policy_tables import literal
                    put_row(desired, 'Tags[]', {'Key': 'Name', 'Value': literal(row['value'])})
                elif row['property'].startswith(kind + '.') and short.split('.', 1)[0].removesuffix('[]') == prop:
                    put_row(desired, short, comparison.desired_value(source.stem, row, kind))
                    exact |= short == prop
            if prop not in desired:
                raise Blocked('repair projection incomplete')
            def render(value):
                if isinstance(value, dict) and '$resource' in value:
                    service, rid = value['$resource']
                    referenced = comparison.resources[service][rid]
                    name, ref = cfn_resource_identity(referenced['cfn-logicalId'])
                    attr = value['$attribute']
                    primary = comparison.catalog.schema(referenced['resourceType']).get('primaryIdentifier', [])
                    expression = {'Ref': ref} if primary == ['/properties/' + attr] else {'Fn::GetAtt': [ref, attr]}
                    if name != unit['name']:
                        # Never invent an export or alter a producer during consumer repair.
                        producer = next((u for _, u in comparison.templates() if u['name'] == name), None)
                        if not producer:
                            raise Blocked('reference producer unknown')
                        comparison.stack(producer)
                        producer_doc, params, pseudo = comparison.stack_inputs[name]
                        candidates = [resolve_value(output['Export']['Name'], params, pseudo, conditions=producer_doc.get('Conditions', {}))
                                      for output in producer_doc.get('Outputs', {}).values()
                                      if condition_active(producer_doc, params, pseudo, output)
                                      and output_value(producer_doc, params, pseudo, output.get('Value')) == expression and 'Export' in output]
                        if len(candidates) != 1:
                            raise Blocked('reference export ambiguous/missing')
                        if 'exports' not in export_snapshot:
                            export_snapshot['exports'] = self.aws('list-exports').get('Exports', [])
                        exports = export_snapshot['exports']
                        owners = [entry for entry in exports if entry['Name'] == candidates[0]
                                  and entry.get('ExportingStackId', '').split(':stack/')[-1].split('/')[0] == name]
                        if len(owners) != 1:
                            raise Blocked('reference export current owner not confirmed')
                        if name not in producer_snapshots:
                            producer_snapshots[name] = (self.aws('describe-stacks', '--stack-name', name)['Stacks'][0],
                                                        self.aws('get-template', '--stack-name', name)['TemplateBody'])
                        current, actual = producer_snapshots[name]
                        if current['StackStatus'] not in SUCCESS:
                            raise Blocked('reference producer is not terminal success')
                        if isinstance(actual, str):
                            from cfnlint.decode import decode_str
                            actual, errors = decode_str(actual)
                            if errors:
                                raise Blocked('reference producer template unreadable')
                        if actual.get('Resources', {}).get(ref, {}).get('Type') != comparison.catalog.cloudformation_type(referenced['resourceType']):
                            raise Blocked('reference producer actual resource ownership differs')
                        current_params = {key: str(val['Default']) for key, val in actual.get('Parameters', {}).items() if 'Default' in val}
                        current_params.update({item['ParameterKey']: item['ParameterValue'] for item in current.get('Parameters', [])})
                        actual_exports = [out for out in actual.get('Outputs', {}).values()
                            if condition_active(actual, current_params, pseudo, out) and 'Export' in out
                            and resolve_value(out['Export']['Name'], current_params, pseudo, conditions=actual.get('Conditions', {})) == candidates[0]
                            and output_value(actual, current_params, pseudo, out.get('Value')) == expression]
                        if len(actual_exports) != 1:
                            raise Blocked('reference export actual value expression differs from approved model')
                        return {'Fn::ImportValue': candidates[0]}
                    return expression
                if isinstance(value, dict):
                    return {key: render(val) for key, val in value.items()}
                if isinstance(value, list):
                    return [render(val) for val in value]
                return value
            value = render(desired[prop])
            if prop == 'CatalogId' and value == self.target.get('awsExecutionAccountId', self.target['awsAccountId']):
                value = {'Ref': 'AWS::AccountId'}
            # Retain unspecified nested settings, including security/policy statements.
            actual = definition.get('Properties', {}).get(prop)
            if not exact:
                if isinstance(actual, dict) and any(key.startswith('Fn::') or key == 'Ref' for key in actual):
                    raise Blocked('partial setting behind intrinsic is ambiguous')
                value = merge_selected(actual, value, prop)
            if len(failed) == 1 and isinstance(actual, dict) and set(actual) == {'Ref'} and actual['Ref'] in document.get('Parameters', {}) and isinstance(value, (str, bool, int, float)):
                parameter = actual['Ref']
                def uses(item):
                    if isinstance(item, dict):
                        return int(item == {'Ref': parameter}) + sum(uses(child) for child in item.values()) + sum(
                            str(child).count('${' + parameter + '}') for key, child in item.items() if key == 'Fn::Sub')
                    return sum(uses(child) for child in item) if isinstance(item, list) else 0
                if uses(document) != 1:
                    raise Blocked('parameter has other consumers; repair value is not proven for every use')
                parameter_path = self.paths(unit)[1]
                inputs = json.loads(parameter_path.read_text(encoding='utf-8'))
                matches = [item for item in inputs if item.get('ParameterKey') == parameter]
                if len(matches) != 1:
                    raise Blocked('repair parameter explicit value missing/ambiguous')
                matches[0]['ParameterValue'] = str(value).lower() if isinstance(value, bool) else str(value)
                require_writable(self.root, [parameter_path])
                return parameter_path, json.dumps(inputs, ensure_ascii=False, indent=2) + '\n', logical + ':' + prop
            edits.append((logical, prop, value))
            classes.append(logical + ':' + prop)
        # A template repair cannot silently affect any other designed stack instance.
        for _, other in comparison.templates():
            if other['name'] != unit['name'] and other['template'] == unit['template']:
                raise Blocked('shared template affects another stack; scope decision required')
        text = path.read_text(encoding='utf-8')
        for logical, prop, value in edits:
            text = repair_template(text, logical, prop, value)
        if text == path.read_text(encoding='utf-8'):
            raise Blocked('no material repair progress')
        require_writable(self.root, [path])
        return path, text, '|'.join(sorted(set(classes)))

    def cleanup_failed_create(self, unit, state, *, empty_only=False):
        if state.get('stackStatus') == 'PRE_EXECUTION':
            return
        if state.get('stackStatus') != 'ROLLBACK_COMPLETE':
            if state.get('stackStatus') != 'UPDATE_ROLLBACK_COMPLETE':
                raise Blocked('rollback recovery cannot be proven safe; no delete/ResourcesToSkip')
            return
        if not state.get('stackId'):
            raise Blocked('failed CREATE StackId missing; never delete by name')
        if state.get('cleanupStatus') == 'DELETE_COMPLETE' and state.get('cleanupStackId') == state['stackId']:
            return True
        if state.get('cleanupStatus') == 'DELETE_INTENT':
            try:
                current = self.aws('describe-stacks', '--stack-name', state['stackId'])['Stacks'][0]
            except Blocked as error:
                if 'does not exist' not in str(error):
                    raise
                state['cleanupStatus'] = 'DELETE_COMPLETE'
                self.save()
                return True
            if current['StackId'] != state['stackId']:
                raise Blocked('interrupted cleanup stack identity changed')
            if current['StackStatus'] in {'DELETE_IN_PROGRESS', 'DELETE_COMPLETE'}:
                self.wait_cleanup(state)
                return True
            if current['StackStatus'] != 'ROLLBACK_COMPLETE':
                raise Blocked('interrupted cleanup state unsafe')
        document, _ = self.templates[unit['name']]
        stack = self.aws('describe-stacks', '--stack-name', state['stackId'])['Stacks'][0]
        if (stack['StackId'] != state['stackId'] or stack['StackStatus'] != 'ROLLBACK_COMPLETE'
                or stack.get('EnableTerminationProtection') or stack.get('ParentId') or stack.get('RootId')):
            raise Blocked('failed CREATE identity/state changed or protected')
        actuals = self.aws('list-stack-resources', '--stack-name', state['stackId'])['StackResourceSummaries']
        empty = all(item.get('ResourceStatus') == 'DELETE_COMPLETE' for item in actuals)
        if empty_only and not empty:
            return False
        if not empty:
            if (state.get('operationType') != 'CREATE' or not state.get('absentBeforeCreate')
                    or state.get('operationStackId') != state['stackId']):
                raise Blocked('failed CREATE session provenance missing; never delete by name')
            if any(resource.get('DeletionPolicy', 'Delete') != 'Delete'
                   or resource.get('UpdateReplacePolicy', 'Delete') != 'Delete'
                   or resource['Type'].startswith(('Custom::', 'AWS::CloudFormation::'))
                   for resource in document.get('Resources', {}).values()) or any(
                       event['ResourceStatus'] == 'DELETE_SKIPPED' for event in state.get('failureEvents', [])):
                raise Blocked('failed CREATE contains retained/custom resources; cleanup requires human')
        if not empty and any(item['ResourceStatus'] not in {'DELETE_COMPLETE', 'CREATE_FAILED'}
               or item['ResourceStatus'] == 'CREATE_FAILED' and item.get('PhysicalResourceId')
               or item.get('LogicalResourceId') not in document.get('Resources', {})
               or item.get('ResourceType') != document['Resources'][item['LogicalResourceId']]['Type']
               for item in actuals):
            raise Blocked('failed CREATE still owns resources; cleanup requires human')
        state.update(cleanupStatus='DELETE_INTENT', cleanupStackId=state['stackId'])
        self.save()
        self.aws('delete-stack', '--stack-name', state['stackId'])
        self.wait_cleanup(state)
        return True

    def wait_cleanup(self, state):
        for _ in range(120):
            try:
                current = self.aws('describe-stacks', '--stack-name', state['stackId'])['Stacks'][0]['StackStatus']
            except Blocked as error:
                if 'does not exist' not in str(error):
                    raise
                current = 'DELETE_COMPLETE'
            if current == 'DELETE_COMPLETE':
                state['cleanupStatus'] = 'DELETE_COMPLETE'
                self.save()
                return
            if current != 'DELETE_IN_PROGRESS':
                raise Blocked('failed CREATE cleanup stopped: ' + current)
            time.sleep(5)
        raise Blocked('failed CREATE cleanup timeout; inspect same StackId before resuming')

    def reset_after_cleanup(self, state):
        retained = {key: state[key] for key in ('repairs', 'cleanupStatus', 'cleanupStackId', 'emptyStackRecreated') if key in state}
        state.clear()
        state.update(retained, status='NOT_STARTED')
        self.save()

    def finish_repair(self, unit, state, entry):
        self.refresh_validation(unit)
        entry['stage'] = 'VALIDATED'
        self.save()
        self.cleanup_failed_create(unit, state)
        self.reset_after_cleanup(state)
        entry['stage'] = 'RETRY_READY'
        self.save()

    def repair(self, unit, state):
        history = state.setdefault('repairs', [])
        try:
            self.guard()
            require_target_no_issues(self.root, (self.environment, self.directory))
            contract = task_path(self.root).read_text(encoding='utf-8')
            if '- Controlled repair: `allowed`' not in contract.splitlines():
                raise Blocked('controlled repair not authorized in task contract')
            if state.get('stackStatus') not in {'ROLLBACK_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE', 'PRE_EXECUTION'}:
                raise Blocked('unsafe rollback state; no automatic delete or ResourcesToSkip')
            pending = history[-1:] if history and history[-1].get('stage') in {'REPAIR_INTENT', 'VALIDATING', 'VALIDATED'} else []
            if pending:
                entry = pending[0]
                path = self.root / entry['path']
                require_writable(self.root, [path])
                candidate_path = Path(entry['candidatePath']).resolve()
                if not candidate_path.is_relative_to(self.workdir.resolve()) or self.file_digest(candidate_path, fresh=True) != entry['newFileDigest']:
                    raise Blocked('pending repair recovery copy missing/changed')
                if self.file_digest(path, fresh=True) == entry['oldFileDigest']:
                    path.write_bytes(candidate_path.read_bytes())
                if self.file_digest(path, fresh=True) != entry['newFileDigest'] or self.input_digest(unit, fresh=True) != entry['newDigest']:
                    raise Blocked('pending repair bytes changed')
                self.expected_digests[unit['name']] = entry['newDigest']
                self.session['infraManifest'][entry['path']] = entry['newFileDigest']
                entry['stage'] = 'VALIDATING'
                self.save()
                self.finish_repair(unit, state, entry)
                return True
            try:
                path, text, failure_class = self.repair_plan(unit, state)
            except Blocked:
                if (state.get('stackStatus') == 'ROLLBACK_COMPLETE' and not state.get('emptyStackRecreated')
                        and self.cleanup_failed_create(unit, state, empty_only=True)):
                    state['emptyStackRecreated'] = True
                    self.reset_after_cleanup(state)
                    return True
                raise
            self.guard()  # Diagnostics cannot admit concurrent IaC/model edits into the repair.
            logical_classes = set(failure_class.split('|'))
            attempts = [entry for entry in history if logical_classes & set(entry['failureClass'].split('|'))]
            candidate = hashlib.sha256(text.encode()).hexdigest()
            if any(sum(logical in entry['failureClass'].split('|') for entry in attempts) >= 3
                   for logical in logical_classes) or any(entry['newFileDigest'] == candidate for entry in attempts):
                raise Blocked('repair iteration limit/no material progress for logical failure class')
            entry = {'classification': 'AUTO_REPAIRABLE', 'failureClass': failure_class,
                     'path': path.relative_to(self.root).as_posix(), 'oldFileDigest': self.file_digest(path, fresh=True),
                     'newFileDigest': candidate, 'oldDigest': self.input_digest(unit, fresh=True),
                     'stage': 'REPAIR_INTENT', 'changeSetId': state.get('changeSetId')}
            self.workdir.mkdir(parents=True, exist_ok=True)
            candidate_path = self.workdir / ('repair-' + uuid.uuid4().hex + path.suffix)
            candidate_path.write_text(text, encoding='utf-8')
            entry['candidatePath'] = str(candidate_path)
            entry['newDigest'] = fingerprint([candidate if p == path else self.file_digest(p, fresh=True)
                for p in self.deployment_input_paths([unit])])
            history.append(entry)
            state['failureClassification'] = 'AUTO_REPAIRABLE'
            self.save()  # Persist authorized exact bytes before modifying IaC.
            path.write_text(text, encoding='utf-8')
            if self.input_digest(unit, fresh=True) != entry['newDigest']:
                raise Blocked('repair inputs changed outside the exact authorized candidate')
            self.expected_digests[unit['name']] = entry['newDigest']
            self.session['infraManifest'][entry['path']] = candidate
            entry['stage'] = 'VALIDATING'
            self.save()
            self.finish_repair(unit, state, entry)
            return True
        except Exception as error:
            state['failureClassification'] = 'HUMAN_REQUIRED'
            state['reason'] = str(error)
            self.save()
            return False

    def poll(self, unit, state):
        state["pollCount"] = state.get("pollCount", 0) + 1
        # An old *_COMPLETE is not evidence that the new execution completed.
        state["pollApiCount"] = state.get("pollApiCount", 0) + 1
        events = self.aws("describe-stack-events", "--stack-name", unit["name"])["StackEvents"]
        operation = [event for event in events if event.get("ResourceType") == "AWS::CloudFormation::Stack"
                     and event.get("ClientRequestToken") == state.get("clientToken")]
        if not operation:
            state["pollApiCount"] += 1
            current = self.describe_change_set(unit, state)
            if current.get("ExecutionStatus") == "AVAILABLE":
                state["status"] = "BLOCKED"
                raise Blocked("execution not submitted; saved change set remains unexecuted")
            return "UPDATE_IN_PROGRESS"  # Submission may be pending; never re-execute or release its slot.
        state["operationStackId"] = operation[0].get("StackId")
        state["failureEvents"] = [{key: event.get(key) for key in ("LogicalResourceId", "ResourceType", "ResourceStatus", "ResourceStatusReason")}
                                  for event in events if event.get("ClientRequestToken") == state.get("clientToken")
                                  and (event.get("ResourceStatus", "").endswith("_FAILED") or event.get("ResourceStatus") == "DELETE_SKIPPED")]
        event_status = operation[0]["ResourceStatus"]
        if "ROLLBACK" in event_status or event_status.endswith("_FAILED"):
            state["failureDetected"] = True
        state["pollApiCount"] += 1
        stack_status = self.aws("describe-stacks", "--stack-name", unit["name"])["Stacks"][0]["StackStatus"]
        if stack_status.endswith("_IN_PROGRESS"):
            return stack_status
        if event_status.endswith("_IN_PROGRESS"):
            return event_status
        if stack_status != event_status:
            raise Blocked("stack status/event terminal status disagree; retrying observation")
        return stack_status


def active_scope(root, requested, environment, account, alias=None):
    contract = task_path(root)
    text = contract.read_text(encoding="utf-8")
    if status(text, contract.name == "active.md") != "running":
        raise Blocked("completed task cannot deploy")
    for line in ("- Task type: `infrastructure`", "- AWS API execution: `allowed`", "- Deploy/apply: `allowed`",
                 f"- Target environment: `{environment}`", f"- Target AWS account: `{account}`"):
        if line not in text.splitlines():
            raise Blocked(f"active task must explicitly contain {line}")
    if not any(f"- Infrastructure phase: `{phase}`" in text.splitlines() for phase in ("deploy", "update")):
        raise Blocked("controller requires infrastructure deploy/update phase")
    if alias and f"- Target alias: `{alias}`" not in text.splitlines():
        raise Blocked("requested alias must exactly match active task Target alias")
    scopes = [line for line in text.splitlines() if line.startswith("- Deployment scope:")]
    if len(scopes) != 1 or set(re.findall(r"`([^`]+)`", scopes[0])) != set(requested):
        raise Blocked("requested StackName scope must exactly match active task Deployment scope")
    return "update" if "- Infrastructure phase: `update`" in text.splitlines() else "deploy"


def design_digest(root, environment, directory):
    scope = validation_scope(root)
    pending = ([root / "model" / env / target / (service + ".properties") for env, target, service in scope
                if (env, target) == (environment, directory)] if scope is not None
               else list((root / "model" / environment / directory).glob("*.properties")))
    pending.append(root / "model" / environment / directory / "cloudformation-stacks.properties")
    snapshot = {}
    while pending:
        path = pending.pop().resolve()
        if path in snapshot:
            continue
        values = {key: value for key, value in properties(read_model(path)).items() if not key.startswith("observed.")}
        snapshot[path] = values
        for value in values.values():
            link = LINK.fullmatch(value)
            if link and link.group(2):
                reference = (path.parent / link.group(2)).with_suffix(".properties").resolve()
                if not reference.is_relative_to(root / "model"):
                    raise Blocked("model reference escapes immutable design scope")
                pending.append(reference)
    return fingerprint({str(path.relative_to(root)): values for path, values in snapshot.items()})


def validation_digest(backend, unit_digests):
    # Reuse is invalidated by controller, validators, rules, catalog/schema and project changes.
    paths = sorted(path for path in (backend.root / "framework").rglob("*")
                   if path.is_file() and path.suffix in {".py", ".json", ".md", ".properties", ".sha256"})
    paths += [backend.root / "AGENTS.md", backend.root / "project.json"]
    try:
        lint_version = importlib.metadata.version("cfn-lint")
    except importlib.metadata.PackageNotFoundError:
        lint_version = None
    return fingerprint([unit_digests, backend.target, sys.version, lint_version,
                        [(str(path.relative_to(backend.root)), backend.file_digest(path)) for path in paths if path.is_file()]])


def run_session(units, limit, session, backend, save, pause_after_group=False, sleep=time.sleep):
    """Observed synchronization is an idempotent, persisted barrier between groups."""
    def sync_completed():
        unsynced = [u for u in units if session["states"][u["name"]]["status"] == "SUCCESS"
                    and not session["states"][u["name"]].get("observedSynced")]
        if not unsynced:
            return True
        started = time.perf_counter()
        try:
            sync_successful(backend, unsynced, session["states"])
            session.pop("observedError", None)
            return True
        except Exception as error:
            session["observedError"] = str(error)
            return False
        finally:
            session["metrics"]["observedSyncSeconds"] += time.perf_counter() - started
            save()

    while True:
        if not sync_completed():
            # A restart may contain both unsynced successes and still-running peers.
            run_group(units, limit, session["states"], backend, save, sleep=sleep, drain_only=True)
            return "STOPPED"
        result = run_group(units, limit, session["states"], backend, save, sleep=sleep)
        if result == "GROUP_COMPLETE":
            completed = sorted({int(u["deployOrder"]) for u in units
                                if all(session["states"][v["name"]]["status"] == "SUCCESS"
                                       for v in units if v["deployOrder"] == u["deployOrder"])})
            session["metrics"]["deployOrderCount"] = len(completed)
            # Sync even the final group before returning COMPLETE.
            if pause_after_group:
                if not sync_completed():
                    return "STOPPED"
                return "COMPLETE" if all(s["status"] == "SUCCESS" for s in session["states"].values()) else "GROUP_COMPLETE"
            continue
        if result == "STOPPED":
            for state in session['states'].values():
                if state['status'] == 'BLOCKED':
                    state['failureClassification'] = 'HUMAN_REQUIRED'
            # Do not abandon successful peers' observed values after another stack fails.
            synced = sync_completed()
            failed = [u for u in units if session["states"][u["name"]]["status"] == "FAILED"]
            if synced and failed and hasattr(backend, "repair"):
                repaired = all([backend.repair(u, session["states"][u["name"]]) for u in failed])
                save()
                if repaired:
                    continue
        return result


def controller_main(argv=None, root=None, timing=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--alias")
    selector.add_argument("--aws-account-id")
    parser.add_argument("--stack", action="append", required=True, help="exact StackName; repeat for scope")
    parser.add_argument("--state", type=Path, required=True, help="persistent session path outside repository")
    parser.add_argument("--timing-log", type=Path, help="external JSONL phase durations, including authentication and AWS calls")
    parser.add_argument("--profile")
    parser.add_argument("--approve-change-set", action="append", default=[])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sequential", action="store_true", help="limit this session to one stack at a time without changing the design")
    parser.add_argument("--pause-after-group", action="store_true", help="update phase only: explicit producer/consumer IaC handoff")
    args = parser.parse_args(argv)
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    state_path = args.state.resolve()
    lock_path = None
    lock = None
    session = None
    persist = None
    invocation_started = time.perf_counter()
    try:
        if state_path.is_relative_to(root):
            raise Blocked("deployment session must be outside repository; never store AWS status in Git")
        spec = importlib.util.spec_from_file_location("deploy_context", Path(__file__).with_name("check-deploy-context.py"))
        context = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(context)
        selected = context.load_target(root, args.environment, args.aws_account_id, args.alias)
        phase = active_scope(root, args.stack, args.environment, selected["awsAccountId"], args.alias)
        if args.pause_after_group and phase != "update":
            raise Blocked("--pause-after-group requires the explicit update phase")
        context_started = time.perf_counter()
        with timing.phase("authenticationContext"):
            target = context.check_deploy_context(root, args.environment, args.aws_account_id, args.alias, args.profile)
        context_seconds = time.perf_counter() - context_started
        if target["iacEngine"] != "cloudformation":
            raise Blocked("controller requires CloudFormation target")
        lock_target = {key: value for key, value in target.items() if key != "awsProfile"}
        lock_path = Path(tempfile.gettempdir()) / ("blueprint-cfn-" + fingerprint([args.environment, lock_target]) + ".lock")
        try:
            lock = lock_path.open("x")
        except FileExistsError as error:
            raise Blocked(f"controller session already active or interrupted; verify no controller is running before removing {lock_path}") from error
        directory = args.alias or args.aws_account_id
        limit, units = load_units(root, args.environment, directory, args.stack)
        if args.sequential:
            limit = 1
        backend = AwsBackend(root, args.environment, directory, target, args.profile, args.approve_change_set)
        backend.timing = timing
        if phase == "deploy" and not args.resume:
            paths = sorted({str(path.relative_to(root)) for unit in units for path in backend.paths(unit)})
            revision = subprocess.run(["git", "status", "--porcelain", "--", *paths], cwd=root,
                                      capture_output=True, text=True, timeout=30)
            if revision.returncode or revision.stdout.strip():
                raise Blocked("deploy template/parameter revision must be clean; cannot deploy uncommitted IaC")
        digest = fingerprint([str(root), target, args.environment, phase, limit, units])
        current_design = design_digest(root, args.environment, directory)
        backend.workdir = state_path.with_name(state_path.name + ".files").resolve()
        if backend.workdir.is_relative_to(root):
            raise Blocked("deployment files directory must be outside repository")
        unit_digests = {unit["name"]: backend.input_digest(unit) for unit in units}
        def infra_manifest():
            return {path.relative_to(root).as_posix(): backend.file_digest(path)
                    for path in sorted(set(backend.deployment_input_paths(units)))}
        current_infra = infra_manifest()
        if args.resume:
            session = json.loads(state_path.read_text(encoding="utf-8"))
            for unit in units:
                state = session['states'][unit['name']]
                pending = state.get('repairs', [])[-1:]
                if not pending or pending[0].get('stage') not in {'REPAIR_INTENT', 'VALIDATING', 'VALIDATED'}:
                    continue
                entry = pending[0]
                if entry.get('classification') != 'AUTO_REPAIRABLE':
                    raise Blocked('unapproved pending repair')
                relative = entry['path']
                if current_infra.get(relative) == entry['newFileDigest'] and backend.input_digest(unit) == entry['newDigest']:
                    session['unitDigests'][unit['name']] = entry['newDigest']
                    session['infraManifest'][relative] = entry['newFileDigest']
                    entry['stage'] = 'VALIDATING'  # Resume repeats affected validation, never assumes interrupted PASS.
                elif current_infra.get(relative) != entry['oldFileDigest'] or backend.input_digest(unit) != entry['oldDigest']:
                    raise Blocked('pending repair bytes/digest changed outside authorized transaction')
            # Older sessions watched all infra; retain only current execution inputs.
            previous_infra = {path: digest for path, digest in session.get('infraManifest', current_infra).items()
                              if path in current_infra}
            changed_infra = {path for path in previous_infra.keys() | current_infra.keys()
                             if previous_infra.get(path) != current_infra.get(path)}
            handoff = {path.relative_to(root).as_posix() for unit in units
                       if phase == 'update' and session['states'][unit['name']]['status'] == 'NOT_STARTED'
                       for path in backend.deployment_input_paths([unit])}
            if changed_infra - handoff:
                raise Blocked('unauthorized IaC change outside recorded repair; cannot resume')
            session['infraManifest'] = current_infra
            if phase == 'deploy':
                from deploy_preparation import repair_changes
                paths = sorted({str(path.relative_to(root)) for unit in units for path in backend.paths(unit)})
                revision = subprocess.run(['git', 'status', '--porcelain', '--', *paths], cwd=root,
                                          capture_output=True, text=True, timeout=30)
                if revision.returncode:
                    raise Blocked('cannot verify resumed IaC revision')
                if revision.stdout.strip():
                    repaired = {entry['path'] for state in session['states'].values() for entry in state.get('repairs', [])
                                if entry.get('stage') != 'REPAIR_INTENT'}
                    repair_changes(root, task_path(root).read_text(encoding='utf-8'), repaired)
                    # Exact input digests/manifest below reject any other dirty bytes.
                    if not repaired:
                        raise Blocked('deploy revision dirty without repair evidence')
            if session.get("version", 1) not in {1, 2}:
                raise Blocked("unsupported controller session version")
            if session["inputDigest"] != digest:
                raise Blocked("target, design or scope changed; cannot resume this session")
            for name, state in session["states"].items():
                if (phase == "deploy" or state["status"] != "NOT_STARTED") and session["unitDigests"][name] != unit_digests[name]:
                    raise Blocked(f"prepared/executed unit IaC changed; cannot resume: {name}")
            session["unitDigests"] = unit_digests
            if session.get("designDigest", current_design) != current_design or session.get("profile", backend.profile) != backend.profile:
                raise Blocked("intended model or AWS profile changed; cannot resume")
        else:
            if state_path.exists() or args.approve_change_set:
                raise Blocked("new session requires unused state path and no approvals")
            session = {"inputDigest": digest, "unitDigests": unit_digests,
                       "states": {unit["name"]: {"status": "NOT_STARTED"} for unit in units}}
        # v1 sessions resume conservatively: no cached validation or observed barrier is assumed.
        session.update(version=2, designDigest=current_design, profile=backend.profile)
        session.setdefault('repository', str(root))
        session.setdefault('taskFile', task_path(root).relative_to(root).as_posix())
        from deploy_preparation import sha, task_digest
        session.setdefault('taskDigest', task_digest(task_path(root).read_text(encoding='utf-8')))
        session.setdefault('infraManifest', current_infra)
        backend.session = session
        contract = task_path(root).read_text(encoding='utf-8')
        if '- Controlled repair: `allowed`' in contract.splitlines() and f'- Deploy repair session: `{state_path}`' not in contract.splitlines():
            raise Blocked('controlled repair session path must match task contract')
        metrics = session.setdefault("metrics", {})
        for key in ("controllerInvocationCount", "validationCount", "deployOrderCount", "observedSyncSeconds",
                    "inputLoadSeconds", "mappingCheckSeconds", "lintSeconds", "totalControllerSeconds", "contextCheckSeconds"):
            metrics.setdefault(key, 0)
        metrics["controllerInvocationCount"] += 1
        metrics["contextCheckSeconds"] += context_seconds
        for change_id in args.approve_change_set:
            matches = [state for state in session["states"].values() if state.get("changeSetId") == change_id]
            if len(matches) != 1 or matches[0]["status"] != "BLOCKED" or not matches[0].get("changeDigest"):
                raise Blocked("approve only the saved blocked change set after human confirmation")
        backend.states = session["states"]
        backend.expected_digests = session["unitDigests"]
        previous_duration = metrics["totalControllerSeconds"]
        def save():
            metrics["totalControllerSeconds"] = previous_duration + time.perf_counter() - invocation_started
            metrics["awsPollCount"] = sum(s.get("pollApiCount", 0) for s in session["states"].values())
            temporary = state_path.with_suffix(state_path.suffix + ".tmp")
            temporary.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
            temporary.replace(state_path)
        backend.save = save
        persist = save
        def guard():
            active_scope(root, args.stack, args.environment, selected["awsAccountId"], args.alias)
            if context.load_target(root, args.environment, args.aws_account_id, args.alias) != target:
                raise Blocked("project target changed before mutation")
            if design_digest(root, args.environment, directory) != current_design:
                raise Blocked("intended model changed before mutation")
            if infra_manifest() != session['infraManifest']:
                raise Blocked('unauthorized IaC change outside controlled repair')
            if task_digest(task_path(root).read_text(encoding='utf-8')) != session['taskDigest']:
                raise Blocked('task contract changed before mutation')
            if any(backend.input_digest(unit) != unit_digests[unit["name"]] for unit in units):
                raise Blocked("deployment inputs changed before mutation")
            if validation_digest(backend, unit_digests) != session.get("validationDigest"):
                raise Blocked("validation dependencies changed before mutation")
        backend.guard = guard
        def refresh_validation(unit):
            # Reuse validator/cache, but schema/naming/policy/model checks concern only affected services.
            mapped = backend.mapping_plan[1][unit['name']]
            affected = {(args.environment, directory, entry[0].stem) for entry in mapped.values()}
            spec = importlib.util.spec_from_file_location('repair_validator', root / 'framework/scripts/validate-blueprint.py')
            validator_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(validator_module)
            validator = validator_module.Validator(root, affected, validation_scope(root), cache=True,
                                                   iac_paths=set(backend.deployment_input_paths([unit])))
            if validator.run():
                raise Blocked('affected repair repository validation failed')
            backend.validate(unit)
            backend.mapping_plan = mappings(root, args.environment, directory, backend.templates, units,
                                            removed_resources(units, session['states']), target=target)
            session['validationDigest'] = validation_digest(backend, unit_digests)
            session['validationStatus'] = 'PASS'
            metrics['validationCount'] += 1
            save()
        backend.refresh_validation = refresh_validation
        save()
        # Cheap whole-scope diagnostics precede lint and every change set.
        try:
            session.pop("validationErrors", None)
            session.pop("validationError", None)
            for state in session["states"].values():
                state.pop("preflightErrors", None)
            started = time.perf_counter()
            try:
                for unit in units:
                    backend.load_inputs(unit)
            finally:
                metrics["inputLoadSeconds"] += time.perf_counter() - started
            started = time.perf_counter()
            try:
                backend.mapping_units = units
                backend.mapping_plan = mappings(root, args.environment, directory, backend.templates, units,
                                                removed_resources(units, session["states"]), target=target)
            finally:
                metrics["mappingCheckSeconds"] += time.perf_counter() - started
            digest = validation_digest(backend, unit_digests)
            if session.get("validationStatus") == "PASS" and session.get("validationDigest") == digest:
                backend.validated_digests = dict(unit_digests)
            else:
                session["validationStatus"] = "RUNNING"
                session["validationDigest"] = digest
                metrics["validationCount"] += 1
                save()
                started = time.perf_counter()
                try:
                    for unit in units:
                        try:
                            backend.validate(unit)
                        except Blocked:
                            state = session['states'][unit['name']]
                            events = getattr(backend, 'validation_failures', {}).get(unit['name'])
                            if state['status'] != 'NOT_STARTED' or not events:
                                raise
                            state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=events)
                            save()
                            if not backend.repair(unit, state):
                                raise
                            digest = validation_digest(backend, unit_digests)
                finally:
                    metrics["lintSeconds"] += time.perf_counter() - started
                if any(backend.input_digest(unit, fresh=True) != unit_digests[unit["name"]] for unit in units):
                    raise Blocked("deployment inputs changed during scope validation")
                session["validationDigest"], session["validationStatus"] = digest, "PASS"
                metrics["validatedInputDigest"] = fingerprint(unit_digests)
                save()
        except Exception as error:
            session["result"] = "STOPPED"
            session["validationStatus"], session["validationError"] = "FAILED", str(error)
            if isinstance(error, MappingError):
                session["validationErrors"] = error.errors
                for name, errors in error.errors.items():
                    session["states"][name]["preflightErrors"] = errors
            save()
            # A resumed invocation may already own executions; validation cannot abandon them.
            run_group(units, limit, session["states"], backend, save, drain_only=True)
            raise
        for unit in units:
            state = session['states'][unit['name']]
            if state.get('repairs') and state['repairs'][-1].get('stage') in {'REPAIR_INTENT', 'VALIDATING', 'VALIDATED'}:
                if not backend.repair(unit, state):
                    session['result'] = 'STOPPED'
                    save()
                    return 2
        session["result"] = run_session(units, limit, session, backend, save, args.pause_after_group)
        save()
        print(json.dumps(session, indent=2))
        return 2 if session["result"] == "STOPPED" else 0
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"CloudFormation controller: BLOCKED: {error}", file=sys.stderr)
        return 2
    finally:
        if persist is not None:
            persist()
        if lock is not None:
            lock.close()
            lock_path.unlink(missing_ok=True)


def main(argv=None, root=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--timing-log", type=Path)
    args, _ = parser.parse_known_args(argv)
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    try:
        timing = Timing(root, args.timing_log)
        with timing.phase("controller"):
            result = controller_main(argv, root, timing)
            # A nonzero result is a failed invocation even when handled internally.
            if result:
                raise Blocked("controller stopped; see session/diagnostics")
            return result
    except (OSError, ValueError, Blocked) as error:
        print(f"CloudFormation controller: BLOCKED ({error})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
