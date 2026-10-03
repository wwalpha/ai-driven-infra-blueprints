#!/usr/bin/env python3
"""Run one ordered CloudFormation group; keep resumable change sets outside Git."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, urlencode

from model_design import (properties, stack_model, markdown_for, deployment_settings,
                          deployment_bucket, ARTIFACT_PROPERTIES)
from model_files import read_model
from issue_gate import require_target_no_issues

SUCCESS = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
FAILED = {"CREATE_FAILED", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "DELETE_COMPLETE", "DELETE_FAILED",
          "UPDATE_FAILED", "UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED",
          "IMPORT_ROLLBACK_COMPLETE", "IMPORT_ROLLBACK_FAILED"}


class Blocked(RuntimeError):
    pass


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


def run_group(units, limit, states, backend, save=lambda: None, sleep=time.sleep, drain_only=False):
    """Single event loop owns the queue; AWS executions overlap, Python decisions do not."""
    pending = [unit for unit in units if states[unit["name"]]["status"] != "SUCCESS"]
    if not pending:
        return "COMPLETE"
    order = min(int(unit["deployOrder"]) for unit in pending)
    group = [unit for unit in pending if int(unit["deployOrder"]) == order]
    stopped = drain_only or any(state["status"] == "FAILED" for state in states.values())
    while True:
        # Poll every running stack before reusing any freed slot.
        for unit in group:
            state = states[unit["name"]]
            if state["status"] != "RUNNING":
                continue
            try:
                status = backend.poll(unit, state)
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
            except Exception as error:
                # Lost read access is not proof of terminal failure. Drain/retry only.
                state["pollError"] = str(error)
                stopped = True
            save()
        running = sum(states[unit["name"]]["status"] == "RUNNING" for unit in group)
        assert running <= limit
        if not stopped and running < limit:
            unit = next((unit for unit in group if states[unit["name"]]["status"] in {"NOT_STARTED", "BLOCKED", "READY"}), None)
            if unit is not None:
                state = states[unit["name"]]
                try:
                    state["status"] = backend.prepare(unit, state)
                    save()
                    if state["status"] == "READY":
                        # Persist intent before AWS mutation; resume polls this unit, never reexecutes it.
                        state["status"] = "RUNNING"
                        state["clientToken"] = state.get("clientToken", uuid.uuid4().hex)
                        save()
                        backend.execute(unit, state)
                except Exception as error:
                    if state["status"] != "RUNNING":
                        state["status"] = "BLOCKED"
                    state["reason"] = str(error)
                    stopped = True
                if state["status"] == "BLOCKED":
                    stopped = True
                save()
                continue
        if not running:
            if stopped:
                return "STOPPED"
            if all(states[unit["name"]]["status"] == "SUCCESS" for unit in group):
                return "GROUP_COMPLETE"
        sleep(5)


def resolve_value(value, parameters, pseudo, exports=None, conditions=None):
    """Resolve the same explicit inputs for imports and artifact destinations."""
    def resolve(value, seen=frozenset()):
        if isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, list):
            return [resolve(part, seen) for part in value]
        if not isinstance(value, dict) or len(value) != 1:
            raise Blocked("cannot resolve ImportValue expression")
        key, argument = next(iter(value.items()))
        if key == "Condition":
            if not isinstance(argument, str) or argument in seen or argument not in (conditions or {}):
                raise Blocked(f"unresolved or cyclic Condition: {argument}")
            result = resolve(conditions[argument], seen | {argument})
            if type(result) is not bool:
                raise Blocked(f"non-boolean Condition: {argument}")
            return result
        if key == "Fn::If" and isinstance(argument, list) and len(argument) == 3:
            active = resolve({"Condition": argument[0]}, seen)
            return resolve(argument[1 if active else 2], seen)
        if key == "Fn::Equals" and isinstance(argument, list) and len(argument) == 2:
            left, right = resolve(argument, seen)
            return any(isinstance(left, kind) and isinstance(right, kind) and left == right
                       for kind in (str, bool, int, float)) and isinstance(left, bool) == isinstance(right, bool)
        if key in {"Fn::And", "Fn::Or", "Fn::Not"} and isinstance(argument, list):
            operands = resolve(argument, seen)
            if (all(type(part) is bool for part in operands) and
                    (len(operands) == 1 if key == "Fn::Not" else 2 <= len(operands) <= 10)):
                return not operands[0] if key == "Fn::Not" else all(operands) if key == "Fn::And" else any(operands)
            raise Blocked(f"invalid condition operands: {key}")
        if key == "Fn::ImportValue" and exports is not None:
            name = resolve(argument, seen)
            if name in exports:
                return exports[name]
            raise Blocked(f"unresolved artifact bucket export: {name}")
        if key == "Ref" and argument in parameters | pseudo:
            return (parameters | pseudo)[argument]
        if key == "Fn::Join" and isinstance(argument, list) and len(argument) == 2:
            delimiter, parts = resolve(argument, seen)
            if isinstance(delimiter, str) and isinstance(parts, list) and all(isinstance(part, str) for part in parts):
                return delimiter.join(parts)
            raise Blocked("invalid Join operands")
        if key == "Fn::Sub":
            text, variables = (argument, {}) if isinstance(argument, str) else argument
            substitutions = parameters | pseudo | {key: resolve(val, seen) for key, val in variables.items()}
            def replace(match):
                key = match.group(1)
                if key.startswith("!"):
                    return "${" + key[1:] + "}"
                if key not in substitutions:
                    raise Blocked(f"unresolved ImportValue variable: {key}")
                return substitutions[key]
            return re.sub(r"\$\{([^}]+)\}", replace, text)
        raise Blocked(f"unsupported ImportValue expression: {key}")
    return resolve(value)


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


class AwsBackend:
    def __init__(self, root, environment, directory, target, profile=None, approvals=()):
        configured_profile = target.get("awsProfile")
        if configured_profile and profile is not None and profile != configured_profile:
            raise Blocked("explicit AWS profile does not match target awsProfile")
        self.root, self.environment, self.directory = root, environment, directory
        self.target, self.profile, self.approvals = target, configured_profile or profile, set(approvals)
        self.templates = {}
        self.validated_digests = {}
        self.expected_digests = {}
        self.workdir = None
        self.states = {}
        self.save = lambda: None

    def aws(self, operation, *arguments, service="cloudformation"):
        if operation in {"create-change-set", "execute-change-set", "put-object"}:
            try:
                require_target_no_issues(self.root, (self.environment, self.directory))
            except (OSError, ValueError) as error:
                raise Blocked(str(error)) from error
        command = ["aws", "--region", self.target["awsRegion"]]
        if self.profile:
            command += ["--profile", self.profile]
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

    def input_digest(self, unit):
        paths = [*self.paths(unit), *[self.source_path(a) for a in unit.get("artifacts", [])]]
        return fingerprint([hashlib.sha256(path.read_bytes()).hexdigest() for path in paths])

    def validate(self, unit):
        from cfnlint.decode import decode
        template, parameters = self.paths(unit)
        digest = self.input_digest(unit)
        if unit["name"] in self.expected_digests and self.expected_digests[unit["name"]] != digest:
            raise Blocked("deployment inputs changed before validation")
        result = subprocess.run(["cfn-lint", "--regions", self.target["awsRegion"], "--template", str(template)],
                                capture_output=True, text=True)
        if result.returncode:
            raise Blocked(f"cfn-lint failed: {unit['name']}: {result.stdout}{result.stderr}")
        document, errors = decode(str(template))
        if errors or not isinstance(document, dict) or document.get("Transform"):
            raise Blocked("invalid/transform template; imports must be resolvable before change set")
        inputs = json.loads(parameters.read_text(encoding="utf-8"))
        if not isinstance(inputs, list) or not all(isinstance(item, dict) and isinstance(item.get("ParameterKey"), str)
                                                 and isinstance(item.get("ParameterValue"), str) for item in inputs):
            raise Blocked("parameter file must contain explicit stack-specific ParameterKey/ParameterValue entries")
        if len({item["ParameterKey"] for item in inputs}) != len(inputs):
            raise Blocked("duplicate parameter key")
        defaults = {key: str(value["Default"]) for key, value in document.get("Parameters", {}).items() if "Default" in value}
        self.templates[unit["name"]] = (document, defaults | {item["ParameterKey"]: item["ParameterValue"] for item in inputs})
        for artifact in unit.get("artifacts", []):
            self.source_path(artifact)
            resource = document.get("Resources", {}).get(artifact["resource"], {})
            if (resource.get("Type"), artifact["property"]) not in ARTIFACT_PROPERTIES:
                raise Blocked("artifact resource/type/property does not match the declared template")
        if not unit.get("artifacts") and template.stat().st_size > 1024 * 1024:
            raise Blocked("template exceeds the 1 MiB CloudFormation limit")
        if self.input_digest(unit) != digest:
            raise Blocked("deployment inputs changed during validation")
        self.validated_digests[unit["name"]] = digest

    def verify_object(self, obj):
        arguments = ["--bucket", obj["bucket"], "--key", obj["key"], "--expected-bucket-owner", self.target["awsAccountId"],
                     "--checksum-mode", "ENABLED"]
        if obj.get("version"):
            arguments += ["--version-id", obj["version"]]
        current = self.aws("head-object", *arguments, service="s3api")
        if current.get("ChecksumSHA256") != obj["checksum"] or current.get("ContentLength") != obj["size"]:
            raise Blocked("S3 artifact checksum/size changed; upload or execution blocked")
        return current

    def upload(self, path, bucket, prefix):
        location = self.aws("get-bucket-location", "--bucket", bucket, "--expected-bucket-owner", self.target["awsAccountId"], service="s3api")
        region = location.get("LocationConstraint") or "us-east-1"
        if ("eu-west-1" if region == "EU" else region) != self.target["awsRegion"]:
            raise Blocked("deployment bucket region does not match target")
        contents = path.read_bytes()
        digest = hashlib.sha256(contents)
        obj = {"bucket": bucket, "key": prefix + digest.hexdigest() + path.suffix,
               "checksum": base64.b64encode(digest.digest()).decode(), "size": len(contents)}
        try:
            current = self.verify_object(obj)
        except Blocked as error:
            if not any(code in str(error) for code in ("(404)", "(NoSuchKey)", "(NotFound)")):
                raise
            try:
                current = self.aws("put-object", "--bucket", bucket, "--key", obj["key"], "--body", str(path),
                    "--expected-bucket-owner", self.target["awsAccountId"], "--if-none-match", "*",
                    "--checksum-algorithm", "SHA256", "--checksum-sha256", obj["checksum"], service="s3api")
            except Blocked as error:
                if "(PreconditionFailed)" not in str(error):
                    raise
                current = self.verify_object(obj)
        if current.get("VersionId") not in {None, "null"}:
            obj["version"] = current["VersionId"]
        self.verify_object(obj)
        return obj

    def artifact_bindings(self, unit, document, parameters):
        pseudo = {"AWS::AccountId": self.target["awsAccountId"], "AWS::Region": self.target["awsRegion"], "AWS::StackName": unit["name"]}
        # Resolve every mapping before the first upload, including bucket/prefix consistency.
        bindings = []
        exports = {e["Name"]: e["Value"] for e in self.aws("list-exports").get("Exports", [])} if unit.get("artifacts") else {}
        for artifact in unit.get("artifacts", []):
            resource = document["Resources"][artifact["resource"]]
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

    def template_arguments(self, unit, state):
        """Prepare only declared S3 references in a copy outside the repository."""
        if state.get("delivery"):
            delivery = state["delivery"]
            document, parameters = self.templates[unit["name"]]
            self.artifact_bindings(unit, document, parameters)
            if self.input_digest(unit) != delivery["inputDigest"]:
                raise Blocked("prepared deployment inputs changed")
            path = Path(delivery["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != delivery["templateSha256"]:
                raise Blocked("prepared deployment template changed")
            for obj in delivery["objects"]:
                self.verify_object(obj)
            return delivery["arguments"]
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
                             "templateSha256": hashlib.sha256(path.read_bytes()).hexdigest(), "objects": objects}
        self.save()
        return arguments

    def check_imports(self, unit):
        document, parameters = self.templates[unit["name"]]
        names = import_names(document, parameters, {"AWS::AccountId": self.target["awsAccountId"],
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

    def prepare(self, unit, state):
        self.check_imports(unit)  # Also recheck when resuming an approved change set.
        arguments = self.template_arguments(unit, state)
        if not state.get("changeSetId"):
            try:
                stack = self.aws("describe-stacks", "--stack-name", unit["name"])["Stacks"][0]
            except Blocked as error:
                if "does not exist" not in str(error):
                    raise
                stack = None
            if stack and stack["StackStatus"] not in SUCCESS | {"UPDATE_ROLLBACK_COMPLETE"}:
                raise Blocked(f"stack not updateable: {stack['StackStatus']}")
            _, parameters = self.paths(unit)
            self.aws("validate-template", *arguments)
            state["changeSetId"] = "blueprint-" + uuid.uuid4().hex
            self.save()
            response = self.aws("create-change-set", "--stack-name", unit["name"],
                "--change-set-name", state["changeSetId"],
                "--change-set-type", "UPDATE" if stack else "CREATE",
                *arguments, "--parameters", "file://" + str(parameters),
                "--capabilities", "CAPABILITY_NAMED_IAM")
            state["changeSetId"] = response["Id"]
            self.save()
        while True:
            change_set = self.describe_change_set(unit, state)
            if change_set["Status"] not in {"CREATE_PENDING", "CREATE_IN_PROGRESS"}:
                break
            time.sleep(5)
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
            state["reason"] = "unapproved delete/replacement; change set unexecuted; human confirmation required"
            return "BLOCKED"
        state.pop("reason", None)
        return "READY"

    def execute(self, unit, state):
        # Re-fetch the exact immutable approval artifact immediately before execution.
        self.template_arguments(unit, state)
        current = self.describe_change_set(unit, state)
        if current["Status"] != "CREATE_COMPLETE" or current["ExecutionStatus"] != "AVAILABLE" or \
                fingerprint(current.get("Changes", [])) != state["changeDigest"]:
            state["status"] = "BLOCKED"
            raise Blocked("change set expired or changed before execution; approval invalid")
        self.aws("execute-change-set", "--stack-name", unit["name"], "--change-set-name", state["changeSetId"],
                 "--client-request-token", state["clientToken"])

    def poll(self, unit, state):
        # An old *_COMPLETE is not evidence that the new execution completed.
        events = self.aws("describe-stack-events", "--stack-name", unit["name"])["StackEvents"]
        operation = [event for event in events if event.get("ResourceType") == "AWS::CloudFormation::Stack"
                     and event.get("ClientRequestToken") == state.get("clientToken")]
        if not operation:
            current = self.describe_change_set(unit, state)
            if current.get("ExecutionStatus") == "AVAILABLE":
                state["status"] = "BLOCKED"
                raise Blocked("execution not submitted; saved change set remains unexecuted")
            return "UPDATE_IN_PROGRESS"  # Submission may be pending; never re-execute or release its slot.
        event_status = operation[0]["ResourceStatus"]
        if "ROLLBACK" in event_status or event_status.endswith("_FAILED"):
            state["failureDetected"] = True
        stack_status = self.aws("describe-stacks", "--stack-name", unit["name"])["Stacks"][0]["StackStatus"]
        if stack_status.endswith("_IN_PROGRESS"):
            return stack_status
        if event_status.endswith("_IN_PROGRESS"):
            return event_status
        if stack_status != event_status:
            raise Blocked("stack status/event terminal status disagree; retrying observation")
        return stack_status


def active_scope(root, requested, environment, account, alias=None):
    text = (root / "tasks/active.md").read_text(encoding="utf-8")
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


def main(argv=None, root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--alias")
    selector.add_argument("--aws-account-id")
    parser.add_argument("--stack", action="append", required=True, help="exact StackName; repeat for scope")
    parser.add_argument("--state", type=Path, required=True, help="persistent session path outside repository")
    parser.add_argument("--profile")
    parser.add_argument("--approve-change-set", action="append", default=[])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    root = root or Path(__file__).resolve().parents[2]
    state_path = args.state.resolve()
    lock_path = None
    lock = None
    try:
        if state_path.is_relative_to(root):
            raise Blocked("deployment session must be outside repository; never store AWS status in Git")
        spec = importlib.util.spec_from_file_location("deploy_context", Path(__file__).with_name("check-deploy-context.py"))
        context = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(context)
        selected = context.load_target(root, args.environment, args.aws_account_id, args.alias)
        phase = active_scope(root, args.stack, args.environment, selected["awsAccountId"], args.alias)
        target = context.check_deploy_context(root, args.environment, args.aws_account_id, args.alias, args.profile)
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
        backend = AwsBackend(root, args.environment, directory, target, args.profile, args.approve_change_set)
        digest = fingerprint([str(root), target, args.environment, phase, limit, units])
        backend.workdir = state_path.with_name(state_path.name + ".files").resolve()
        if backend.workdir.is_relative_to(root):
            raise Blocked("deployment files directory must be outside repository")
        unit_digests = {unit["name"]: backend.input_digest(unit) for unit in units}
        if args.resume:
            session = json.loads(state_path.read_text(encoding="utf-8"))
            if session["inputDigest"] != digest:
                raise Blocked("target, design or scope changed; cannot resume this session")
            for name, state in session["states"].items():
                if (phase == "deploy" or state["status"] != "NOT_STARTED") and session["unitDigests"][name] != unit_digests[name]:
                    raise Blocked(f"prepared/executed unit IaC changed; cannot resume: {name}")
            session["unitDigests"] = unit_digests
        else:
            if state_path.exists() or args.approve_change_set:
                raise Blocked("new session requires unused state path and no approvals")
            session = {"inputDigest": digest, "unitDigests": unit_digests,
                       "states": {unit["name"]: {"status": "NOT_STARTED"} for unit in units}}
        for change_id in args.approve_change_set:
            matches = [state for state in session["states"].values() if state.get("changeSetId") == change_id]
            if len(matches) != 1 or matches[0]["status"] != "BLOCKED" or not matches[0].get("changeDigest"):
                raise Blocked("approve only the saved blocked change set after human confirmation")
        backend.states = session["states"]
        backend.expected_digests = session["unitDigests"]
        def save():
            temporary = state_path.with_suffix(state_path.suffix + ".tmp")
            temporary.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
            temporary.replace(state_path)
        backend.save = save
        save()
        # Validate every scoped stack before creating any change set. No template deduplication.
        try:
            for unit in units:
                backend.validate(unit)
        except Exception:
            # A resumed invocation may already own executions; validation cannot abandon them.
            run_group(units, limit, session["states"], backend, save, drain_only=True)
            raise
        session["result"] = run_group(units, limit, session["states"], backend, save)
        save()
        print(json.dumps(session, indent=2))
        if session["result"] == "GROUP_COMPLETE":
            print("Update successful stacks' observed values, sync-model and validate; --resume then advances the next group.")
        return 2 if session["result"] == "STOPPED" else 0
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"CloudFormation controller: BLOCKED: {error}", file=sys.stderr)
        return 2
    finally:
        if lock is not None:
            lock.close()
            lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
