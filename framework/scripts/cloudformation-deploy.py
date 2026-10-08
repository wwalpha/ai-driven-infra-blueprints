#!/usr/bin/env python3
"""Deploy ordered CloudFormation groups with resumable state outside Git."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from deployment import aws_adapter, delivery, change_sets, repair as repair_ops, secret_bootstrap, session as session_ops
from deployment.secret_bootstrap import BOOTSTRAP_STAGES
from deployment.aws_adapter import secret_value_missing
from model_design import markdown_for
from model_references import deployment_bucket
from model_core import properties, stack_model, deployment_settings, ARTIFACT_PROPERTIES
from model_files import read_model
from deploy_preparation import Timing
from issue_gate import require_target_no_issues
from iac_values import fingerprint
from task_contract import task_path
from cloudformation_inputs import Blocked, load_template_inputs
from cloudformation_observed import mappings, removed_resources


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
        return aws_adapter.call(self.root, self.environment, self.directory, self.target,
                                self.profile, self.timing, self.guard, operation, *arguments, service=service)

    def paths(self, unit):
        template = self.root / "infra/cloudformation/templates" / self.target.get("alias", "") / unit["template"]
        parameters = self.root / "infra/cloudformation/parameters" / self.environment / self.directory / unit["parameters"]
        return template, parameters

    def source_path(self, artifact):
        return delivery.source_path(self.root, artifact)

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

    def placement(self):
        return delivery.placement(self.root, self.environment, self.directory, self.target,
                                  self.session, self.save, self.aws)

    def verify_object(self, obj):
        return delivery.verify_object(self.placement(), obj)

    def upload(self, path, bucket, prefix):
        return delivery.upload(self.placement(), self.file_digest, self.uploaded, path, bucket, prefix)

    def artifact_bindings(self, unit, document, parameters):
        return delivery.artifact_bindings(self.target, self.aws, unit, document, parameters)

    def prepare_delivery_group(self, units, states):
        return delivery.prepare_delivery_group(self.placement(), units, states, self.templates, self.workdir,
                                               self.validated_digests, self.paths, self.input_digest,
                                               self.file_digest, self.uploaded, self.check_imports)

    def template_arguments(self, unit, state, stage_only=False):
        return delivery.template_arguments(self.placement(), unit, state, self.templates[unit["name"]],
                                           self.paths(unit)[0], self.workdir, self.validated_digests,
                                           self.input_digest, self.file_digest, self.uploaded, stage_only)

    def check_imports(self, unit):
        return change_sets.check_imports(self.target, self.templates, self.states, self.aws, unit)

    def describe_change_set(self, unit, state):
        return change_sets.describe_change_set(self.aws, unit, state)

    def verify_stack_ownership(self, unit):
        return change_sets.verify_stack_ownership(self.aws, self.templates, unit)

    def begin_prepare(self, unit, state):
        return change_sets.begin_prepare(unit, state, self.aws, self.save, self.check_imports, self.template_arguments,
                                         self.cleanup_failed_create, self.reset_after_cleanup, self.verify_stack_ownership, self.paths)

    def review_prepared(self, unit, state, change_set=None):
        return change_sets.review_prepared(unit, state, self.approvals, self.aws, self.describe_change_set, change_set)

    def prepare(self, unit, state):
        """Compatibility entry point; the controller uses nonblocking preparation."""
        self.begin_prepare(unit, state)
        while True:
            result = self.review_prepared(unit, state)
            if result != "CHANGESET_CREATING":
                return result
            time.sleep(5)

    def execute(self, unit, state):
        expected = self.expected_digests.get(unit["name"], self.validated_digests.get(unit["name"]))
        change_sets.verify_execution(unit, state, expected, self.input_digest, self.file_digest,
                                     self.template_arguments, self.check_imports, self.describe_change_set)
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
        return repair_ops.repair_plan(self.root, self.environment, self.directory, self.target,
                                      getattr(self, 'mapping_plan', ({}, {})), self.paths, self.aws, unit, state)

    def bootstrap_plan(self, unit, state):
        return secret_bootstrap.bootstrap_plan(self.root, self.environment, self.directory, self.target,
                                               self.templates, self.states, getattr(self, 'mapping_plan', ({}, {})),
                                               self.mapping_units, self.aws, self.check_secret_arn, unit, state)

    def check_secret_arn(self, arn):
        return secret_bootstrap.check_secret_arn(self.target, arn)

    def bootstrap_current(self, entry):
        return secret_bootstrap.bootstrap_current(self.aws, entry)

    def bootstrap(self, unit, state, entry=None):
        return secret_bootstrap.bootstrap(self.root, self.states, self.guard, self.save, self.aws,
                                         self.bootstrap_plan, self.bootstrap_current, self.finish_repair, unit, state, entry)

    def cleanup_failed_create(self, unit, state, *, empty_only=False):
        return repair_ops.cleanup_failed_create(self.templates, self.aws, self.save, self.wait_cleanup,
                                                unit, state, empty_only=empty_only)

    def wait_cleanup(self, state):
        return repair_ops.wait_cleanup(self.aws, self.save, state)

    def reset_after_cleanup(self, state):
        return repair_ops.reset_after_cleanup(self.save, state)

    def finish_repair(self, unit, state, entry):
        return repair_ops.finish_repair(self.refresh_validation, self.save, self.cleanup_failed_create,
                                        self.reset_after_cleanup, unit, state, entry)

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
            runtime = history[-1:] if history and history[-1].get('classification') == 'RUNTIME_BOOTSTRAP' else []
            if runtime and runtime[0].get('stage') in BOOTSTRAP_STAGES:
                return self.bootstrap(unit, state, runtime[0])
            if any(secret_value_missing(e.get('ResourceStatusReason')) for e in state.get('failureEvents', [])):
                # A failed safety proof must never fall through to empty-stack recreation or IaC repair.
                return self.bootstrap(unit, state)
            pending = history[-1:] if history and history[-1].get('stage') in {'REPAIR_INTENT', 'VALIDATING', 'VALIDATED'} else []
            if pending:
                entry = pending[0]
                return repair_ops.resume_candidate(self.root, self.workdir, self.file_digest, self.input_digest,
                                            self.expected_digests, self.session['infraManifest'], self.save,
                                            self.finish_repair, unit, state, entry)
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
            return repair_ops.apply_candidate(self.root, self.workdir, self.file_digest, self.input_digest,
                                          self.deployment_input_paths, self.expected_digests,
                                          self.session['infraManifest'], self.save, self.finish_repair,
                                          unit, state, history, path, text, failure_class)
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
        state["failureEvents"] = []
        for event in events:
            if event.get('ClientRequestToken') != state.get('clientToken') or not (
                    event.get('ResourceStatus', '').endswith('_FAILED') or event.get('ResourceStatus') == 'DELETE_SKIPPED'):
                continue
            failure = {key: event.get(key) for key in ('LogicalResourceId', 'ResourceType', 'ResourceStatus', 'ResourceStatusReason')}
            if secret_value_missing(failure['ResourceStatusReason']):
                failure['ResourceStatusReason'] = 'SECRET_CURRENT_VALUE_MISSING'
            elif any(e.get('classification') == 'RUNTIME_BOOTSTRAP' for e in state.get('repairs', [])):
                failure['ResourceStatusReason'] = 'resource failure after runtime bootstrap; Human diagnosis required'
            state['failureEvents'].append(failure)
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
    return session_ops.run(args, root, timing, Path(__file__).parent, AwsBackend, load_units)


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
