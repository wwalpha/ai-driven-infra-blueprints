"""Assemble deployment state and functions; AWS clients live in utils.aws.client."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from functools import partial

from deploy import delivery, change_sets, repair as repair_ops, secret_bootstrap, session as session_ops, inputs
from deploy.secret_bootstrap import BOOTSTRAP_STAGES
from deploy.guards import secret_value_missing, call
from deploy.inputs import load_units
from deploy.timing import Timing
from issue_gate import require_target_no_issues
from task_contract import task_path
from cloudformation_inputs import Blocked, load_template_inputs
from model.core import ARTIFACT_PROPERTIES
from utils.json_format import fingerprint

def create_runtime(root, environment, directory, target, profile=None, approvals=()):
    configured = target.get("awsProfile")
    if configured and profile is not None and profile != configured:
        raise Blocked("explicit AWS profile does not match target awsProfile")
    runtime = SimpleNamespace(root=root, environment=environment, directory=directory, target=target,
        profile=configured or profile, approvals=set(approvals), timing=Timing(root), templates={},
        expected_digests={}, workdir=None, states={}, save=lambda: None, guard=lambda: None,
        hashes={}, session={}, refresh_validation=lambda unit: None)
    runtime.aws = partial(aws, runtime)
    runtime.paths = partial(paths, runtime)
    runtime.source_path = partial(source_path, runtime)
    runtime.file_digest = partial(file_digest, runtime)
    runtime.deployment_input_paths = partial(deployment_input_paths, runtime)
    runtime.input_digest = partial(input_digest, runtime)
    runtime.load_inputs = partial(load_inputs, runtime)
    runtime.placement = partial(placement, runtime)
    runtime.verify_object = partial(verify_object, runtime)
    runtime.upload = partial(upload, runtime)
    runtime.artifact_bindings = partial(artifact_bindings, runtime)
    runtime.prepare_delivery_group = partial(prepare_delivery_group, runtime)
    runtime.template_arguments = partial(template_arguments, runtime)
    runtime.exports_for = partial(exports_for, runtime)
    runtime.check_imports = partial(check_imports, runtime)
    runtime.describe_change_set = partial(describe_change_set, runtime)
    runtime.verify_stack_ownership = partial(verify_stack_ownership, runtime)
    runtime.begin_prepare = partial(begin_prepare, runtime)
    runtime.review_prepared = partial(review_prepared, runtime)
    runtime.prepare = partial(prepare, runtime)
    runtime.execute = partial(execute, runtime)
    runtime.repair_plan = partial(repair_plan, runtime)
    runtime.bootstrap_plan = partial(bootstrap_plan, runtime)
    runtime.check_secret_arn = partial(check_secret_arn, runtime)
    runtime.bootstrap_current = partial(bootstrap_current, runtime)
    runtime.bootstrap = partial(bootstrap, runtime)
    runtime.cleanup_failed_create = partial(cleanup_failed_create, runtime)
    runtime.wait_cleanup = partial(wait_cleanup, runtime)
    runtime.reset_after_cleanup = partial(reset_after_cleanup, runtime)
    runtime.finish_repair = partial(finish_repair, runtime)
    runtime.repair = partial(repair, runtime)
    runtime.poll = partial(poll, runtime)
    from utils.aws.client import connection_context
    runtime.connection = connection_context(runtime.profile, target["awsRegion"], target.get("awsExecutionAccountId", target["awsAccountId"]))
    return runtime


def aws(runtime, operation, service="cloudformation", **arguments):
    return call(runtime, service, operation, arguments)

def paths(runtime, unit):
    return inputs.paths(runtime.root, runtime.environment, runtime.directory, runtime.target, unit)

def source_path(runtime, artifact):
    return delivery.source_path(runtime.root, artifact)

def file_digest(runtime, path, fresh=False):
    return inputs.file_digest(runtime.hashes, path, fresh)

def deployment_input_paths(runtime, units):
    return inputs.deployment_input_paths(runtime.root, runtime.environment, runtime.directory, runtime.target, units)

def input_digest(runtime, unit, fresh=False):
    return fingerprint([runtime.file_digest(path, fresh) for path in runtime.deployment_input_paths([unit])])

def load_inputs(runtime, unit):
    """Decode current immutable files cheaply; never persist parameter/secret contents."""
    template, parameters = runtime.paths(unit)
    runtime.templates[unit["name"]] = load_template_inputs(template, parameters)
    document, _ = runtime.templates[unit["name"]]
    for artifact in unit.get("artifacts", []):
        runtime.source_path(artifact)
        resource = document.get("Resources", {}).get(artifact["resource"], {})
        if (resource.get("Type"), artifact["property"]) not in ARTIFACT_PROPERTIES:
            raise Blocked("artifact resource/type/property does not match the declared template")
    if not unit.get("artifacts") and template.stat().st_size > 1024 * 1024:
        raise Blocked("template exceeds the 1 MiB CloudFormation limit")

def placement(runtime):
    return delivery.placement(runtime.root, runtime.environment, runtime.directory, runtime.target,
                              runtime.session, runtime.save, runtime.aws, runtime.connection)


def verify_object(runtime, obj, boundary=None):
    return delivery.verify_object(runtime.placement(), obj, boundary)


def upload(runtime, path, bucket, prefix, boundary=None):
    return delivery.upload(runtime.placement(), runtime.file_digest, path, bucket, prefix,
                           {} if boundary is None else boundary)


def exports_for(runtime, units, boundary):
    if 'exports' not in boundary:
        names = {}
        for unit in units:
            document, parameters = runtime.templates[unit['name']]
            pseudo = {'AWS::AccountId': runtime.target.get('awsExecutionAccountId', runtime.target['awsAccountId']),
                      'AWS::Region': runtime.target['awsRegion'], 'AWS::StackName': unit['name']}
            names[unit['name']] = change_sets.import_names(document, parameters, pseudo)
        boundary['importNames'] = names
        boundary['exports'] = change_sets.fetch_exports(runtime.aws, set().union(*names.values()) if names else set())
    return boundary['exports']


def artifact_bindings(runtime, unit, document, parameters, boundary=None):
    boundary = {} if boundary is None else boundary
    if unit['name'] not in runtime.templates:
        # Direct callers supply the current document explicitly.
        names = change_sets.import_names(document, parameters, {'AWS::StackName': unit['name'],
            'AWS::Region': runtime.target['awsRegion'], 'AWS::AccountId': runtime.target.get('awsExecutionAccountId', runtime.target['awsAccountId'])})
        exports = change_sets.fetch_exports(runtime.aws, names)
    else:
        exports = runtime.exports_for([unit], boundary)
    return delivery.artifact_bindings(runtime.target, unit, document, parameters, exports)


def prepare_delivery_group(runtime, units, states):
    return delivery.prepare_delivery_group(runtime.placement(), units, states, runtime.templates, runtime.workdir,
        runtime.paths, runtime.input_digest, runtime.file_digest, runtime.check_imports, runtime.exports_for)


def template_arguments(runtime, unit, state, stage_only=False, boundary=None):
    boundary = {} if boundary is None else boundary
    runtime.exports_for([unit], boundary)
    return delivery.template_arguments(runtime.placement(), unit, state, runtime.templates[unit['name']],
        runtime.paths(unit)[0], runtime.workdir, runtime.input_digest, runtime.file_digest, boundary, stage_only)


def check_imports(runtime, unit, boundary=None):
    boundary = {} if boundary is None else boundary
    return change_sets.check_imports(runtime.target, runtime.templates, runtime.states, runtime.aws, unit,
                                    runtime.exports_for([unit], boundary))


def describe_change_set(runtime, unit, state):
    return change_sets.describe_change_set(runtime.aws, unit, state)

def verify_stack_ownership(runtime, unit):
    return change_sets.verify_stack_ownership(runtime.aws, runtime.templates, unit)

def begin_prepare(runtime, unit, state):
    return change_sets.begin_prepare(unit, state, runtime.aws, runtime.save, runtime.check_imports, runtime.template_arguments,
                                     runtime.cleanup_failed_create, runtime.reset_after_cleanup, runtime.verify_stack_ownership, runtime.paths)

def review_prepared(runtime, unit, state, change_set=None):
    return change_sets.review_prepared(unit, state, runtime.approvals, runtime.aws, runtime.describe_change_set, change_set)

def prepare(runtime, unit, state):
    """Compatibility entry point; the controller uses nonblocking preparation."""
    runtime.begin_prepare(unit, state)
    while True:
        result = runtime.review_prepared(unit, state)
        if result != "CHANGESET_CREATING":
            return result
        time.sleep(5)

def execute(runtime, unit, state):
    expected = runtime.expected_digests.get(unit['name'])
    try:
        current = change_sets.verify_execution(unit, state, expected, runtime.input_digest, runtime.file_digest,
            runtime.template_arguments, runtime.check_imports, runtime.describe_change_set, boundary={})
        evidence = change_sets.record_execution(runtime.aws, unit, state, current, runtime.input_digest(unit, fresh=True))
        if state.get('executionEvidence') not in (None, evidence):
            raise Blocked('persisted execution evidence changed')
        state['executionEvidence'] = evidence
        runtime.save()
    except Exception:
        state['status'] = 'BLOCKED'
        raise
    runtime.aws('execute_change_set', StackName=state['stackId'], ChangeSetName=state['changeSetId'],
                ClientRequestToken=state['clientToken'])
    runtime.save()


def repair_plan(runtime, unit, state):
    return repair_ops.repair_plan(runtime.root, runtime.environment, runtime.directory, runtime.target,
                                  runtime.templates, runtime.paths, runtime.aws, unit, state)

def bootstrap_plan(runtime, unit, state):
    return secret_bootstrap.bootstrap_plan(runtime.root, runtime.environment, runtime.directory, runtime.target,
                                           runtime.templates, runtime.states,
                                           runtime.units, runtime.aws, runtime.check_secret_arn, unit, state)

def check_secret_arn(runtime, arn):
    return secret_bootstrap.check_secret_arn(runtime.target, arn)

def bootstrap_current(runtime, entry):
    return secret_bootstrap.bootstrap_current(runtime.aws, entry)

def bootstrap(runtime, unit, state, entry=None):
    return secret_bootstrap.bootstrap(runtime.root, runtime.states, runtime.guard, runtime.save, runtime.aws,
                                     runtime.bootstrap_plan, runtime.bootstrap_current, runtime.finish_repair, unit, state, entry)

def cleanup_failed_create(runtime, unit, state, *, empty_only=False):
    return repair_ops.cleanup_failed_create(runtime.templates, runtime.aws, runtime.save, runtime.wait_cleanup,
                                            unit, state, empty_only=empty_only)

def wait_cleanup(runtime, state):
    return repair_ops.wait_cleanup(runtime.aws, runtime.save, state)

def reset_after_cleanup(runtime, state, *, retain_delivery=False):
    return repair_ops.reset_after_cleanup(runtime.save, state, retain_delivery=retain_delivery)

def finish_repair(runtime, unit, state, entry):
    return repair_ops.finish_repair(runtime.refresh_validation, runtime.save, runtime.cleanup_failed_create,
                                    runtime.reset_after_cleanup, unit, state, entry)

def repair(runtime, unit, state):
    history = state.setdefault('repairs', [])
    try:
        runtime.guard()
        require_target_no_issues(runtime.root, (runtime.environment, runtime.directory))
        contract = task_path(runtime.root).read_text(encoding='utf-8')
        if '- Controlled repair: `allowed`' not in contract.splitlines():
            raise Blocked('controlled repair not authorized in task contract')
        if state.get('stackStatus') not in {'ROLLBACK_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'}:
            raise Blocked('unsafe rollback state; no automatic delete or ResourcesToSkip')
        bootstrap_history = history[-1:] if history and history[-1].get('classification') == 'RUNTIME_BOOTSTRAP' else []
        if bootstrap_history and bootstrap_history[0].get('stage') in BOOTSTRAP_STAGES:
            return runtime.bootstrap(unit, state, bootstrap_history[0])
        if any(secret_value_missing(e.get('ResourceStatusReason')) for e in state.get('failureEvents', [])):
            # A failed safety proof must never fall through to empty-stack recreation or IaC repair.
            return runtime.bootstrap(unit, state)
        pending = history[-1:] if history and history[-1].get('stage') in {'REPAIR_INTENT', 'VALIDATING', 'VALIDATED'} else []
        if pending:
            entry = pending[0]
            return repair_ops.resume_candidate(runtime.root, runtime.workdir, runtime.file_digest, runtime.input_digest,
                                        runtime.expected_digests, runtime.session['infraManifest'], runtime.save,
                                        runtime.finish_repair, unit, state, entry)
        try:
            path, text, failure_class = runtime.repair_plan(unit, state)
        except Blocked:
            if (state.get('stackStatus') == 'ROLLBACK_COMPLETE' and not state.get('emptyStackRecreated')
                    and runtime.cleanup_failed_create(unit, state, empty_only=True)):
                state['emptyStackRecreated'] = True
                runtime.reset_after_cleanup(state)
                return True
            raise
        runtime.guard()  # Diagnostics cannot admit concurrent IaC/model edits into the repair.
        return repair_ops.apply_candidate(runtime.root, runtime.workdir, runtime.file_digest, runtime.input_digest,
                                      runtime.deployment_input_paths, runtime.expected_digests,
                                      runtime.session['infraManifest'], runtime.save, runtime.finish_repair,
                                      unit, state, history, path, text, failure_class)
    except Exception as error:
        state['failureClassification'] = 'HUMAN_REQUIRED'
        state['reason'] = str(error)
        runtime.save()
        return False

def poll(runtime, unit, state):
    state["pollCount"] = state.get("pollCount", 0) + 1
    # An old *_COMPLETE is not evidence that the new execution completed.
    state["pollApiCount"] = state.get("pollApiCount", 0) + 1
    events = runtime.aws('describe_stack_events', StackName=unit["name"])["StackEvents"]
    operation = [event for event in events if event.get("ResourceType") == "AWS::CloudFormation::Stack"
                 and event.get("ClientRequestToken") == state.get("clientToken")]
    if not operation:
        state["pollApiCount"] += 1
        current = runtime.describe_change_set(unit, state)
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
    stack_status = runtime.aws('describe_stacks', StackName=unit["name"])["Stacks"][0]["StackStatus"]
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
    parser.add_argument("--skill-started-at", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--profile")
    parser.add_argument("--approve-change-set", action="append", default=[])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sequential", action="store_true", help="limit this session to one stack at a time without changing the design")
    parser.add_argument("--pause-after-group", action="store_true", help="update phase only: explicit producer/consumer IaC handoff")
    args = parser.parse_args(argv)
    root = (root if root is not None else Path.cwd()).resolve()
    return session_ops.run(args, root, timing, Path(__file__).parent.parent, create_runtime, load_units)


def main(argv=None, root=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--timing-log", type=Path)
    args, _ = parser.parse_known_args(argv)
    root = (root if root is not None else Path.cwd()).resolve()
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


