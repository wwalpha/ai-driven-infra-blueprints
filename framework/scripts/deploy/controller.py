"""Assemble deployment state and functions; AWS clients live in utils.aws.client."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable, Sequence
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import utils.aws.client as _imports_utils_aws_client
from issue_gate import print_warning, require_target_no_issues
from model.core import ARTIFACT_PROPERTIES
from utils.aws.identity import execution_account, select_profile
from utils.cloudformation.inputs import Blocked, load_template_inputs
from utils.json_format import fingerprint
from utils.type_contracts import JsonObject
from utils.type_contracts import JsonValue as JsonValue

import deploy.failures as _imports_deploy_failures
from deploy import change_sets, delivery, inputs, secret_bootstrap
from deploy import recovery as repair_ops
from deploy import session as session_ops
from deploy.guards import call, secret_value_missing
from deploy.inputs import load_units
from deploy.secret_bootstrap import BOOTSTRAP_STAGES
from deploy.timing import Timing
from deploy.typing import (
    AwsResponse,
    AwsValue,
    DeliveryBoundary,
    StackState,
    StackUnit,
    States,
    Target,
)


def create_runtime(
    root: Path,
    environment: str,
    directory: str,
    target: Target,
    profile: str | None = None,
    approvals: Iterable[str] = (),
) -> SimpleNamespace:
    connection_context = _imports_utils_aws_client.connection_context
    selected = select_profile(target, profile)
    account = execution_account(target)
    runtime = SimpleNamespace(
        root=root,
        environment=environment,
        directory=directory,
        target=target,
        profile=selected,
        approvals=set(approvals),
        timing=Timing(root),
        templates={},
        expected_digests={},
        workdir=None,
        states={},
        save=lambda: None,
        guard=lambda: None,
        hashes={},
        session={},
        refresh_validation=lambda unit: None,
    )
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
    runtime.connection = connection_context(
        runtime.profile, target["awsRegion"], account
    )
    return runtime


def aws(
    runtime: SimpleNamespace,
    operation: str,
    service: str = "cloudformation",
    **arguments: AwsValue,
) -> AwsResponse:
    try:
        return call(runtime, service, operation, arguments)
    except Exception as error:
        error.deploy_service, error.deploy_operation = service, operation
        raise


def paths(runtime: SimpleNamespace, unit: StackUnit) -> tuple[Path, Path]:
    return inputs.paths(
        runtime.root, runtime.environment, runtime.directory, runtime.target, unit
    )


def source_path(runtime: SimpleNamespace, artifact: dict[str, str]) -> Path:
    return delivery.source_path(runtime.root, artifact)


def file_digest(runtime: SimpleNamespace, path: Path, fresh: bool = False) -> str:
    return inputs.file_digest(runtime.hashes, path, fresh)


def deployment_input_paths(
    runtime: SimpleNamespace, units: Iterable[StackUnit]
) -> list[Path]:
    return inputs.deployment_input_paths(
        runtime.root, runtime.environment, runtime.directory, runtime.target, units
    )


def input_digest(runtime: SimpleNamespace, unit: StackUnit, fresh: bool = False) -> str:
    return fingerprint(
        [
            runtime.file_digest(path, fresh)
            for path in runtime.deployment_input_paths([unit])
        ]
    )


def load_inputs(runtime: SimpleNamespace, unit: StackUnit) -> None:
    """Decode current immutable files cheaply; never persist parameter/secret contents."""
    template, parameters = runtime.paths(unit)
    try:
        runtime.templates[unit["name"]] = load_template_inputs(template, parameters)
    except (Blocked, ValueError):
        error = Blocked(
            "invalid/transform template or parameter input; inspect exact authorized source offline"
        )
        error.deploy_input_kind = "DECODE"
        error.code = "InputDecodeError"
        raise error from None
    document, _ = runtime.templates[unit["name"]]
    for artifact in unit.get("artifacts", []):
        runtime.source_path(artifact)
        resource = document.get("Resources", {}).get(artifact["resource"], {})
        if (resource.get("Type"), artifact["property"]) not in ARTIFACT_PROPERTIES:
            raise Blocked(
                "artifact resource/type/property does not match the declared template"
            )
    if not unit.get("artifacts") and template.stat().st_size > 1024 * 1024:
        raise Blocked("template exceeds the 1 MiB CloudFormation limit")
    if hasattr(runtime, "states") and unit["name"] in runtime.states:
        runtime.states[unit["name"]].setdefault("successfulPreparationOperations", {})[
            "decode_input"
        ] = runtime.input_digest(unit)


def placement(runtime: SimpleNamespace) -> SimpleNamespace:
    return delivery.placement(
        runtime.root,
        runtime.environment,
        runtime.directory,
        runtime.target,
        runtime.session,
        runtime.save,
        runtime.aws,
        runtime.connection,
    )


def verify_object(
    runtime: SimpleNamespace, obj: JsonObject, boundary: DeliveryBoundary | None = None
) -> AwsResponse:
    return delivery.verify_object(runtime.placement(), obj, boundary)


def upload(
    runtime: SimpleNamespace,
    path: Path,
    bucket: str,
    prefix: str,
    boundary: DeliveryBoundary | None = None,
) -> JsonObject:
    return delivery.upload(
        runtime.placement(),
        runtime.file_digest,
        path,
        bucket,
        prefix,
        {} if boundary is None else boundary,
    )


def exports_for(
    runtime: SimpleNamespace,
    units: Iterable[StackUnit],
    boundary: DeliveryBoundary,
) -> dict[str, AwsResponse]:
    if "exports" not in boundary:
        names = {}
        for unit in units:
            document, parameters = runtime.templates[unit["name"]]
            pseudo = {
                "AWS::AccountId": runtime.target.get(
                    "awsExecutionAccountId", runtime.target["awsAccountId"]
                ),
                "AWS::Region": runtime.target["awsRegion"],
                "AWS::StackName": unit["name"],
            }
            names[unit["name"]] = change_sets.import_names(document, parameters, pseudo)
        boundary["importNames"] = names
        boundary["exports"] = change_sets.fetch_exports(
            runtime.aws, set().union(*names.values()) if names else set()
        )
    return boundary["exports"]


def artifact_bindings(
    runtime: SimpleNamespace,
    unit: StackUnit,
    document: JsonObject,
    parameters: JsonObject,
    boundary: DeliveryBoundary | None = None,
) -> list[tuple[dict[str, str], JsonObject, str, tuple[str, ...] | None]]:
    boundary = {} if boundary is None else boundary
    if unit["name"] not in runtime.templates:
        # Direct callers supply the current document explicitly.
        names = change_sets.import_names(
            document,
            parameters,
            {
                "AWS::StackName": unit["name"],
                "AWS::Region": runtime.target["awsRegion"],
                "AWS::AccountId": runtime.target.get(
                    "awsExecutionAccountId", runtime.target["awsAccountId"]
                ),
            },
        )
        exports = change_sets.fetch_exports(runtime.aws, names)
    else:
        exports = runtime.exports_for([unit], boundary)
    return delivery.artifact_bindings(
        runtime.target, unit, document, parameters, exports
    )


def prepare_delivery_group(
    runtime: SimpleNamespace, units: Sequence[StackUnit], states: States
) -> None:
    return delivery.prepare_delivery_group(
        runtime.placement(),
        units,
        states,
        runtime.templates,
        runtime.workdir,
        runtime.paths,
        runtime.input_digest,
        runtime.file_digest,
        runtime.check_imports,
        runtime.exports_for,
    )


def template_arguments(
    runtime: SimpleNamespace,
    unit: StackUnit,
    state: StackState,
    stage_only: bool = False,
    boundary: DeliveryBoundary | None = None,
) -> JsonObject:
    boundary = {} if boundary is None else boundary
    runtime.exports_for([unit], boundary)
    return delivery.template_arguments(
        runtime.placement(),
        unit,
        state,
        runtime.templates[unit["name"]],
        runtime.paths(unit)[0],
        runtime.workdir,
        runtime.input_digest,
        runtime.file_digest,
        boundary,
        stage_only,
    )


def check_imports(
    runtime: SimpleNamespace, unit: StackUnit, boundary: DeliveryBoundary | None = None
) -> None:
    boundary = {} if boundary is None else boundary
    return change_sets.check_imports(
        runtime.target,
        runtime.templates,
        runtime.states,
        runtime.aws,
        unit,
        runtime.exports_for([unit], boundary),
    )


def describe_change_set(
    runtime: SimpleNamespace, unit: StackUnit, state: StackState
) -> AwsResponse:
    return change_sets.describe_change_set(runtime.aws, unit, state)


def verify_stack_ownership(runtime: SimpleNamespace, unit: StackUnit) -> None:
    return change_sets.verify_stack_ownership(runtime.aws, runtime.templates, unit)


def begin_prepare(runtime: SimpleNamespace, unit: StackUnit, state: StackState) -> str:
    return change_sets.begin_prepare(
        unit,
        state,
        runtime.aws,
        runtime.save,
        runtime.check_imports,
        runtime.template_arguments,
        runtime.cleanup_failed_create,
        runtime.reset_after_cleanup,
        runtime.verify_stack_ownership,
        runtime.paths,
    )


def review_prepared(
    runtime: SimpleNamespace,
    unit: StackUnit,
    state: StackState,
    change_set: AwsResponse | None = None,
) -> str:
    return change_sets.review_prepared(
        unit,
        state,
        runtime.approvals,
        runtime.aws,
        runtime.describe_change_set,
        change_set,
    )


def prepare(runtime: SimpleNamespace, unit: StackUnit, state: StackState) -> str:
    """Compatibility entry point; the controller uses nonblocking preparation."""
    runtime.begin_prepare(unit, state)
    while True:
        result = runtime.review_prepared(unit, state)
        if result != "CHANGESET_CREATING":
            return result
        time.sleep(5)


def execute(runtime: SimpleNamespace, unit: StackUnit, state: StackState) -> None:
    expected = runtime.expected_digests.get(unit["name"])
    try:
        current = change_sets.verify_execution(
            unit,
            state,
            expected,
            runtime.input_digest,
            runtime.file_digest,
            runtime.template_arguments,
            runtime.check_imports,
            runtime.describe_change_set,
            boundary={},
        )
        evidence = change_sets.record_execution(
            runtime.aws, unit, state, current, runtime.input_digest(unit, fresh=True)
        )
        if state.get("executionEvidence") not in (None, evidence):
            raise Blocked("persisted execution evidence changed")
        state["executionEvidence"] = evidence
        template_safety = _imports_deploy_failures.template_safety
        state["failureTemplateSafety"] = template_safety(
            runtime.templates[unit["name"]][0]
        )
        runtime.save()
    except Exception:
        state["status"] = "BLOCKED"
        raise
    runtime.aws(
        "execute_change_set",
        StackName=state["stackId"],
        ChangeSetName=state["changeSetId"],
        ClientRequestToken=state["clientToken"],
    )
    runtime.save()


def bootstrap_plan(
    runtime: SimpleNamespace, unit: StackUnit, state: StackState
) -> JsonObject:
    return secret_bootstrap.bootstrap_plan(
        runtime.root,
        runtime.environment,
        runtime.directory,
        runtime.target,
        runtime.templates,
        runtime.states,
        runtime.units,
        runtime.aws,
        runtime.check_secret_arn,
        unit,
        state,
    )


def check_secret_arn(runtime: SimpleNamespace, arn: str) -> None:
    return secret_bootstrap.check_secret_arn(runtime.target, arn)


def bootstrap_current(runtime: SimpleNamespace, entry: JsonObject) -> tuple[bool, bool]:
    return secret_bootstrap.bootstrap_current(runtime.aws, entry)


def bootstrap(
    runtime: SimpleNamespace,
    unit: StackUnit,
    state: StackState,
    entry: JsonObject | None = None,
) -> bool:
    return secret_bootstrap.bootstrap(
        runtime.root,
        runtime.states,
        runtime.guard,
        runtime.save,
        runtime.aws,
        runtime.bootstrap_plan,
        runtime.bootstrap_current,
        runtime.finish_repair,
        unit,
        state,
        entry,
    )


def cleanup_failed_create(
    runtime: SimpleNamespace,
    unit: StackUnit,
    state: StackState,
    *,
    empty_only: bool = False,
) -> bool:
    return repair_ops.cleanup_failed_create(
        runtime.templates,
        runtime.aws,
        runtime.save,
        runtime.wait_cleanup,
        unit,
        state,
        empty_only=empty_only,
    )


def wait_cleanup(runtime: SimpleNamespace, state: StackState) -> None:
    return repair_ops.wait_cleanup(runtime.aws, runtime.save, state)


def reset_after_cleanup(
    runtime: SimpleNamespace, state: StackState, *, retain_delivery: bool = False
) -> None:
    return repair_ops.reset_after_cleanup(
        runtime.save, state, retain_delivery=retain_delivery
    )


def finish_repair(
    runtime: SimpleNamespace, unit: StackUnit, state: StackState, entry: JsonObject
) -> None:
    return repair_ops.finish_repair(
        runtime.refresh_validation,
        runtime.save,
        runtime.cleanup_failed_create,
        runtime.reset_after_cleanup,
        unit,
        state,
        entry,
    )


def repair(runtime: SimpleNamespace, unit: StackUnit, state: StackState) -> bool:
    """Runtime recovery only. External IaC work always returns to the supervising LLM."""
    history = state.setdefault("repairs", [])
    try:
        runtime.guard()
        require_target_no_issues(
            runtime.root, (runtime.environment, runtime.directory), warn=print_warning
        )
        repair_ops.require_authorized(runtime.root)
        if state.get("stackStatus") not in {
            "ROLLBACK_COMPLETE",
            "UPDATE_ROLLBACK_COMPLETE",
        }:
            raise Blocked(
                "unsafe rollback state; no automatic delete or ResourcesToSkip"
            )
        if runtime.session.get("pendingRequest"):
            raise Blocked("external IaC repair requires supervising LLM handoff")
        pending = (
            history[-1:]
            if history and history[-1].get("classification") == "RUNTIME_BOOTSTRAP"
            else []
        )
        if pending and pending[0].get("stage") in BOOTSTRAP_STAGES:
            return runtime.bootstrap(unit, state, pending[0])
        if any(
            secret_value_missing(e.get("ResourceStatusReason"))
            for e in state.get("failureEvents", [])
        ):
            return runtime.bootstrap(unit, state)
        # This unchanged-input exception is independent of IaC repair, once per Stack.
        if (
            state.get("stackStatus") == "ROLLBACK_COMPLETE"
            and not state.get("emptyStackRecreated")
            and not history
            and runtime.cleanup_failed_create(unit, state, empty_only=True)
        ):
            state["emptyStackRecreated"] = True
            runtime.reset_after_cleanup(state)
            return True
        state["failureClassification"] = (
            "HUMAN_REQUIRED" if state.get("emptyStackRecreated") else "NEEDS_DIAGNOSIS"
        )
        runtime.save()
        return False
    except Exception as error:
        state["failureClassification"] = "HUMAN_REQUIRED"
        state["reason"] = str(error)
        runtime.save()
        return False


def poll(runtime: SimpleNamespace, unit: StackUnit, state: StackState) -> str:
    failures = _imports_deploy_failures
    state["pollCount"] = state.get("pollCount", 0) + 1
    # An old *_COMPLETE is not evidence that the new execution completed.
    state["pollApiCount"] = state.get("pollApiCount", 0) + 1
    events = runtime.aws("describe_stack_events", StackName=unit["name"])["StackEvents"]
    operation = [
        event
        for event in events
        if event.get("ResourceType") == "AWS::CloudFormation::Stack"
        and event.get("ClientRequestToken") == state.get("clientToken")
    ]
    if not operation:
        state["pollApiCount"] += 1
        current = runtime.describe_change_set(unit, state)
        if current.get("ExecutionStatus") == "AVAILABLE":
            state["status"] = "BLOCKED"
            raise Blocked(
                "execution not submitted; saved change set remains unexecuted"
            )
        return "UPDATE_IN_PROGRESS"  # Submission may be pending; never re-execute or release its slot.
    state["operationStackId"] = operation[0].get("StackId")
    document, _ = runtime.templates.get(unit["name"], ({}, {}))
    state["failureEvents"] = []
    state["successEvents"] = []
    for item in events:
        if item.get("ClientRequestToken") != state.get("clientToken"):
            continue
        resource_status = item.get("ResourceStatus", "")
        if resource_status.endswith("_FAILED") or resource_status == "DELETE_SKIPPED":
            state["failureEvents"].append(failures.event(item, document))
        elif resource_status in {
            "CREATE_COMPLETE",
            "UPDATE_COMPLETE",
            "IMPORT_COMPLETE",
        }:
            state["successEvents"].append(
                {
                    key: value
                    for key, value in failures.event(item, document).items()
                    if key not in {"reasonDigest", "ResourceStatusReason"}
                }
            )
    event_status = operation[0]["ResourceStatus"]
    if "ROLLBACK" in event_status or event_status.endswith("_FAILED"):
        state["failureDetected"] = True
    state["pollApiCount"] += 1
    stack_status = runtime.aws("describe_stacks", StackName=unit["name"])["Stacks"][0][
        "StackStatus"
    ]
    if stack_status.endswith("_IN_PROGRESS"):
        return stack_status
    if event_status.endswith("_IN_PROGRESS"):
        return event_status
    if stack_status != event_status:
        raise Blocked(
            "stack status/event terminal status disagree; retrying observation"
        )
    return stack_status


def controller_main(
    argv: Sequence[str] | None = None,
    root: Path | None = None,
    timing: Timing | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--alias")
    selector.add_argument("--aws-account-id")
    parser.add_argument(
        "--stack",
        action="append",
        required=True,
        help="exact StackName; repeat for scope",
    )
    parser.add_argument(
        "--state",
        type=Path,
        required=True,
        help="persistent session path outside repository",
    )
    parser.add_argument(
        "--timing-log",
        type=Path,
        help="external JSONL phase durations, including authentication and AWS calls",
    )
    parser.add_argument("--profile")
    parser.add_argument("--approve-change-set", action="append", default=[])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--observe-only",
        action="store_true",
        help="resume observation/drain only, without mutation or accepting changed definitions",
    )
    parser.add_argument(
        "--repair-result",
        type=Path,
        help="accept a helper-verified child result into this same session",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="limit this session to one stack at a time without changing the design",
    )
    parser.add_argument(
        "--pause-after-group",
        action="store_true",
        help="update phase only: explicit producer/consumer IaC handoff",
    )
    args = parser.parse_args(argv)
    if (args.repair_result or args.observe_only) and not args.resume:
        parser.error("--repair-result/--observe-only require --resume")
    if args.repair_result and args.observe_only:
        parser.error("--repair-result cannot be combined with --observe-only")
    root = (root if root is not None else Path.cwd()).resolve()
    return session_ops.run(
        args, root, timing, Path(__file__).parent.parent, create_runtime, load_units
    )


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
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
