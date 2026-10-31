"""Assemble deployment state and functions; AWS clients live in utils.aws.client."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import sys
import time
from collections.abc import Iterable, Sequence
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import utils.aws.client as _imports_utils_aws_client
from model.core import ARTIFACT_PROPERTIES
from model.projection import deployment_bucket
from model.references import has_reference
from utils.aws.identity import execution_account, select_profile
from utils.cloudformation.environment import validate_environment_inputs
from utils.cloudformation.export_resolution import (
    describe_exports,
    merge_hints,
    resolve_exports,
)
from utils.cloudformation.format import decode
from utils.cloudformation.inputs import (
    Blocked,
    checked_parameters,
    load_template_inputs,
)
from utils.json_format import fingerprint
from utils.type_contracts import JsonObject
from utils.type_contracts import JsonValue as JsonValue

import deploy.failures as _imports_deploy_failures
from deploy import (
    change_sets,
    cli_guidance,
    current_request,
    current_state,
    delivery,
    inputs,
    observed,
    secret_bootstrap,
    steps,
    worktree,
)
from deploy import recovery as repair_ops
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
        loaded_inputs={},
        expected_digests={},
        workdir=None,
        states={},
        save=lambda: None,
        guard=partial(worktree.require, root),
        hashes={},
        run_context={},
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
    runtime.current_satisfied = partial(current_satisfied, runtime)
    runtime.describe_change_set = partial(describe_change_set, runtime)
    runtime.verify_stack_ownership = partial(verify_stack_ownership, runtime)
    runtime.observed_readiness = partial(observed.readiness, runtime)
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
        if service == "cloudformation" and operation in current_request.TOKENS:
            return current_request.send(runtime, operation, arguments, call)
        if service == "secretsmanager" and operation in {
            "put_secret_value",
            "update_secret_version_stage",
        }:
            entries = [
                state["bootstrap"]
                for state in runtime.states.values()
                if state.get("bootstrap", {}).get("secretId")
                == arguments.get("SecretId")
            ]
            if len(entries) != 1:
                raise Blocked(
                    "Secret submission needs its current scoped bootstrap owner"
                )
            return current_request.send(
                runtime,
                operation,
                arguments,
                call,
                service=service,
                stack_name=entries[0]["owner"]["stack"],
            )
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
    for artifact in unit.get("artifacts", []):
        runtime.source_path(artifact)
    return fingerprint(
        [
            runtime.file_digest(path, fresh)
            for path in runtime.deployment_input_paths([unit])
        ]
    )


def load_inputs(runtime: SimpleNamespace, unit: StackUnit) -> None:
    """Decode current immutable files cheaply; never persist parameter/secret contents."""
    name = unit["name"]
    for artifact in unit.get("artifacts", []):
        runtime.source_path(artifact)
    template, parameters = runtime.paths(unit)
    digest = fingerprint(
        [
            runtime.file_digest(path)
            for path in (
                template,
                parameters,
                *[runtime.source_path(a) for a in unit.get("artifacts", [])],
            )
        ]
    )
    loaded = getattr(runtime, "loaded_inputs", {})
    if name in runtime.templates and loaded.get(name) == digest:
        return
    try:
        runtime.templates[unit["name"]] = load_template_inputs(template, parameters)
    except (Blocked, ValueError):
        error = Blocked(
            "invalid/transform template or parameter input; inspect exact authorized source offline"
        )
        error.deploy_input_kind = "DECODE"
        error.code = "InputDecodeError"
        raise error from None
    validate_environment_inputs(
        runtime.root, *runtime.templates[name], runtime.target, name
    )
    runtime.loaded_inputs = loaded
    loaded[name] = digest
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
    source = (
        runtime.root
        / "model"
        / runtime.environment
        / runtime.directory
        / "cloudformation-stacks.properties"
    )
    if (template.stat().st_size > 51200 or unit.get("artifacts")) and has_reference(
        unit.get("templateBucket", "")
    ):
        unit["templateBucket"] = deployment_bucket(
            unit["templateBucket"], source, runtime.root
        )
    for artifact in unit.get("artifacts", []):
        if has_reference(artifact["bucket"]):
            artifact["bucket"] = deployment_bucket(
                artifact["bucket"], source, runtime.root
            )
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
        runtime.run_context,
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
        required = set().union(*names.values()) if names else set()
        if not required:
            boundary["exports"] = {}
            return boundary["exports"]
        states = list(runtime.states.values())
        hints = []
        for state in states:
            saved = state.get("delivery", {}).get("imports", {})
            if not isinstance(saved, dict):
                raise Blocked("saved Export evidence is incomplete")
            hints.append(
                {name: entry for name, entry in saved.items() if name in required}
            )
            if state.get("stackId") and any(
                record.get("export") in required
                for record in state.get("expectedOutputs", {}).values()
            ):
                describe_exports(runtime.aws, state["stackId"], boundary)
        boundary["exports"] = resolve_exports(
            runtime.aws,
            required,
            hints=merge_hints(hints),
            boundary=boundary,
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
        exports = resolve_exports(
            runtime.aws,
            names,
            hints=runtime.states.get(unit["name"], {})
            .get("delivery", {})
            .get("imports", {}),
            boundary=boundary,
        )
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
    exports = runtime.exports_for([unit], boundary)
    states = runtime.states
    verified = getattr(runtime, "verified_settled", set())
    if verified:
        states = {name: dict(state) for name, state in states.items()}
        for name in verified:
            producer = next(item for item in runtime.units if item["name"] == name)
            current_satisfied(runtime, producer)
            states[name]["status"] = "SUCCESS"
    return change_sets.check_imports(
        runtime.target,
        runtime.templates,
        states,
        runtime.aws,
        unit,
        exports,
    )


def current_satisfied(runtime: SimpleNamespace, unit: StackUnit) -> None:
    """Prove current inputs and identifiers without changing the attempt outcome."""
    name = unit["name"]
    state = runtime.states[name]
    if (
        state.get("requestPending")
        or state.get("requestError")
        or not state.get("observedSynced")
    ):
        raise Blocked(
            "current request or observed synchronization is incomplete: " + name
        )
    runtime.load_inputs(unit)
    expected_digest = runtime.expected_digests.get(name)
    if not expected_digest or runtime.input_digest(unit, fresh=True) != expected_digest:
        raise Blocked("fixed deployment inputs cannot be confirmed: " + name)
    current = current_state.read(runtime.aws, name)
    if current_request.reconcile(runtime, unit):
        raise Blocked("current Stack request is unresolved: " + name)
    if current_state.category(current) != "SUCCESS" or not current.get("StackId"):
        raise Blocked("current Stack is not stable and successful: " + name)
    if current_state.identity(current) != current_state.identity(
        state.get("currentStack", {})
    ):
        raise Blocked("current Stack observation needs synchronization: " + name)
    document, parameters = runtime.templates[name]
    delivery_record = state.get("delivery", {})
    if unit.get("artifacts"):
        if delivery_record.get("inputDigest") != expected_digest:
            raise Blocked("prepared artifact input differs: " + name)
        boundary = {}
        exports = runtime.exports_for([unit], boundary)
        imports = {
            key: {field: entry[field] for field in ("Value", "ExportingStackId")}
            for key, entry in exports.items()
            if key in boundary.get("importNames", {}).get(name, set())
        }
        if delivery_record.get("imports") != imports:
            raise Blocked("prepared artifact imports differ: " + name)
        document = copy.deepcopy(document)
        bindings = delivery.artifact_bindings(
            runtime.target, unit, document, parameters, exports
        )
        objects = delivery_record.get("objects", [])
        if not isinstance(objects, list) or len(objects) < len(bindings):
            raise Blocked("prepared artifact objects are incomplete: " + name)
        for (artifact, container, prop, fields), obj in zip(
            bindings, objects, strict=False
        ):
            source = runtime.source_path(artifact)
            digest = runtime.file_digest(source, fresh=True)
            if (
                obj.get("bucket") != artifact["bucket"]
                or obj.get("key") != artifact["keyPrefix"] + digest + source.suffix
                or obj.get("checksum")
                != base64.b64encode(bytes.fromhex(digest)).decode()
                or obj.get("size") != source.stat().st_size
            ):
                raise Blocked("prepared artifact differs from fixed input: " + name)
            runtime.verify_object(obj)
            if fields:
                container[prop][fields[1]] = obj["key"]
                container[prop].pop(fields[2], None)
                if obj.get("version"):
                    container[prop][fields[2]] = obj["version"]
            else:
                container[prop] = f"s3://{obj['bucket']}/{obj['key']}"
    actual = runtime.aws("get_template", StackName=current["StackId"]).get(
        "TemplateBody"
    )
    if isinstance(actual, str):
        actual, errors = decode(actual)
        if errors:
            raise Blocked("current Stack template is unreadable: " + name)
    if actual != document:
        raise Blocked("current Stack template differs from fixed input: " + name)
    actual_parameters = current.get("Parameters", [])
    if not isinstance(actual_parameters, list) or len(actual_parameters) != len(
        document.get("Parameters", {})
    ):
        raise Blocked("current Stack parameters are incomplete: " + name)
    actual_parameters = [
        {
            "ParameterKey": item.get("ParameterKey"),
            "ParameterValue": item.get("ParameterValue"),
        }
        for item in actual_parameters
        if isinstance(item, dict)
    ]
    if (
        len(actual_parameters) != len(document.get("Parameters", {}))
        or len({item["ParameterKey"] for item in actual_parameters})
        != len(actual_parameters)
        or any(item["ParameterValue"] in {None, "****"} for item in actual_parameters)
        or checked_parameters(document, actual_parameters)
        != checked_parameters(
            document,
            [
                {"ParameterKey": key, "ParameterValue": value}
                for key, value in parameters.items()
            ],
        )
    ):
        raise Blocked("current Stack parameters differ from fixed input: " + name)
    expected_outputs = change_sets.required_outputs(
        document, parameters, runtime.target, name
    )
    change_sets.verify_outputs(
        runtime.aws, unit, {"stackId": current["StackId"]}, expected_outputs
    )
    checked = {name: copy.deepcopy(state)}
    checked[name].pop("executionEvidence", None)
    checked[name].pop("endedRequest", None)
    checked[name].pop("changes", None)
    observed.collect_successful(runtime, [unit], checked)
    if any(
        item.get("status") in {"UNCONFIRMED", "UPDATED"}
        for item in checked[name].get("observedCoverage", {}).values()
    ):
        raise Blocked("current Stack identifiers need synchronization: " + name)
    if current_request.reconcile(runtime, unit):
        raise Blocked("current Stack request changed during verification: " + name)
    if current_state.identity(current) != current_state.identity(
        current_state.read(runtime.aws, name)
    ):
        raise Blocked("current Stack changed during verification: " + name)


def describe_change_set(
    runtime: SimpleNamespace, unit: StackUnit, state: StackState
) -> AwsResponse:
    return change_sets.describe_change_set(runtime.aws, unit, state)


def verify_stack_ownership(runtime: SimpleNamespace, unit: StackUnit) -> None:
    return change_sets.verify_stack_ownership(runtime.aws, runtime.templates, unit)


def begin_prepare(runtime: SimpleNamespace, unit: StackUnit, state: StackState) -> str:
    runtime.load_inputs(unit)
    runtime.observed_readiness(unit)
    document, parameters = runtime.templates[unit["name"]]
    state["expectedOutputs"] = change_sets.required_outputs(
        document, parameters, runtime.target, unit["name"]
    )
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
    result = change_sets.review_prepared(
        unit,
        state,
        runtime.approvals,
        runtime.aws,
        runtime.describe_change_set,
        change_set,
    )
    if result == "SUCCESS":
        state.pop("noChangeCandidate", None)
    return result


def prepare(runtime: SimpleNamespace, unit: StackUnit, state: StackState) -> str:
    """Synchronous preparation; the controller uses the nonblocking path."""
    runtime.begin_prepare(unit, state)
    while True:
        result = runtime.review_prepared(unit, state)
        if result != "CHANGESET_CREATING":
            return result
        time.sleep(5)


def execute(runtime: SimpleNamespace, unit: StackUnit, state: StackState) -> None:
    expected = runtime.expected_digests.get(unit["name"])
    try:
        runtime.load_inputs(unit)
        runtime.observed_readiness(unit)
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
        runtime.observed_readiness(
            unit, {"changes": change_sets.change_summary(current)}
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
    plan = secret_bootstrap.bootstrap_plan(
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
    owner = next(u for u in runtime.units if u["name"] == plan["owner"]["stack"])
    plan["owner"].update(
        unit=copy.deepcopy(owner), inputDigest=runtime.input_digest(owner, fresh=True)
    )
    return plan


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
    if unit["name"] not in runtime.templates:
        runtime.load_inputs(unit)
    runtime.observed_readiness(unit)
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
    if unit["name"] not in runtime.templates:
        runtime.load_inputs(unit)
    runtime.observed_readiness(unit)
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
    entry = state.get("bootstrap")
    try:
        runtime.guard()
        repair_ops.require_authorized(runtime.root)
        if state.get("stackStatus") not in {
            "ROLLBACK_COMPLETE",
            "UPDATE_ROLLBACK_COMPLETE",
        }:
            raise Blocked(
                "unsafe rollback state; no automatic delete or ResourcesToSkip"
            )
        if entry and entry.get("stage") in BOOTSTRAP_STAGES:
            return runtime.bootstrap(unit, state, entry)
        if any(
            secret_value_missing(e.get("ResourceStatusReason"))
            for e in state.get("failureEvents", [])
        ):
            return runtime.bootstrap(unit, state)
        # This unchanged-input exception is independent of IaC repair, once per Stack.
        if (
            state.get("stackStatus") == "ROLLBACK_COMPLETE"
            and not state.get("emptyStackRecreated")
            and not entry
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
    current = current_state.read(runtime.aws, unit["name"])
    state["currentStack"] = current_state.observation(current)
    state["stackStatus"] = current["StackStatus"]
    state["stackId"] = current.get("StackId")
    attempt_status = None
    evidence = state.get("executionEvidence", {})
    execution_stack = evidence.get("StackId")
    if (
        evidence.get("clientToken")
        and evidence["clientToken"] != state.get("clientToken")
    ) or (
        evidence.get("ChangeSetId")
        and not current_state.same_change_set(
            state.get("changeSetId"), evidence["ChangeSetId"]
        )
    ):
        return "UNCONFIRMED"
    if state.get("clientToken"):
        try:
            events = current_state.pages(
                runtime.aws,
                "describe_stack_events",
                "StackEvents",
                StackName=execution_stack or unit["name"],
            )
            matched = [
                event
                for event in events
                if event.get("ClientRequestToken") == state["clientToken"]
            ]
            state["failureEvents"] = [
                _imports_deploy_failures.event(
                    event, runtime.templates.get(unit["name"], ({}, {}))[0]
                )
                for event in matched
                if event.get("ResourceStatus", "").endswith("_FAILED")
                or event.get("ResourceStatus") == "DELETE_SKIPPED"
            ]
            stack_events = current_request.root_events(
                matched, state["clientToken"], execution_stack
            )
            if stack_events and stack_events[0].get("ResourceStatus") in {
                "CREATE_FAILED",
                "UPDATE_FAILED",
            }:
                state["failureDetected"] = True
            if stack_events and stack_events[0].get("ResourceStatus") in (
                current_state.SUCCESS | current_state.FAILED
            ) - {"CREATE_FAILED", "UPDATE_FAILED"}:
                attempt_status = stack_events[0]["ResourceStatus"]
                if attempt_status in current_state.FAILED:
                    state["failureDetected"] = True
        except (OSError, Blocked):
            pass  # Diagnostics cannot veto an otherwise confirmed current observation.
    request = current_request.reconcile(runtime, unit, state)
    if request and state.get("requestError"):
        raise Blocked(state["requestError"])
    if request and not request.get("settled"):
        state["requestPending"] = True
        return (
            "UNCONFIRMED"
            if current_state.category(current) != "RUNNING"
            else current["StackStatus"]
        )
    if request and not current_request.owns(state, request):
        return "UPDATE_IN_PROGRESS"
    if request and current_request.owns(state, request):
        state["settledRequest"] = request
        state["requestPending"] = False
    if request and current_request.owns(state, request):
        if request.get("trackingReason") in {
            "ORIGINAL_STACK_DELETED",
            "ORIGINAL_STACK_REPLACED",
        }:
            return "ATTEMPT_SETTLED"
        if request.get("result") == "SUCCESS":
            return "ATTEMPT_SUCCESS"
        if request.get("result") == "FAIL":
            return "ATTEMPT_FAIL"
        if attempt_status is None:
            attempt_status = request.get("attemptStatus")
        if request.get("result") == "SETTLED" and attempt_status is None:
            return "ATTEMPT_SETTLED"
    if (
        current["StackStatus"] == "UNKNOWN"
        and state.get("clientToken")
        and attempt_status is None
    ):
        return "UNCONFIRMED"
    if current["StackStatus"] == "UNKNOWN" and attempt_status in {
        None,
        "CREATE_FAILED",
        "UPDATE_FAILED",
    }:
        raise Blocked("current Stack state is unavailable: " + unit["name"])
    if (
        state.pop("externalOperation", False)
        and current_state.category(current) != "RUNNING"
    ):
        return "RECHECK"
    if (
        attempt_status in {"CREATE_FAILED", "UPDATE_FAILED"}
        and current_state.category(current) == "RUNNING"
    ):
        return current["StackStatus"]
    if attempt_status is not None:
        return (
            "ATTEMPT_FAIL"
            if attempt_status in current_state.FAILED
            else "ATTEMPT_SUCCESS"
        )
    if (
        state.get("attemptResult") == "UNKNOWN"
        and not state.get("endedRequest")
        and not state.get("clientToken")
    ):
        state["requestError"] = (
            "original execution identity is incomplete; current Stack status cannot prove its outcome"
        )
        return "UNCONFIRMED"
    if state.get("clientToken") and current_state.category(current) != "RUNNING":
        return "UNCONFIRMED"
    return current["StackStatus"]


def controller_main(
    argv: Sequence[str] | None = None,
    root: Path | None = None,
    timing: Timing | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Deploy the current authorized CloudFormation scope independently.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=cli_guidance.CONTROLLER_HELP,
    )
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
        "--timing-log",
        type=Path,
        help="external JSONL phase durations, including authentication and AWS calls",
    )
    parser.add_argument("--profile")
    parser.add_argument(
        "--action",
        choices=("advance", "sync", "checkpoint", "status"),
        required=True,
        help="short LLM-controlled operation; advance never publishes Model changes",
    )
    parser.add_argument(
        "--final",
        action="store_true",
        help="explicit final sync including completed Task in the validated candidate",
    )
    parser.add_argument(
        "--sync-stack",
        action="append",
        default=[],
        help="explicit StackName for current snapshot sync/checkpoint; repeat for an indivisible candidate",
    )
    parser.add_argument(
        "--approve-change-set",
        action="append",
        default=[],
        help="actual current ChangeSet ID explicitly approved by the Human; repeat per approved ID",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="limit this run to one stack at a time without changing the design",
    )
    args = parser.parse_args(argv)
    if (
        args.sync_stack
        and args.action not in {"sync", "checkpoint"}
        or args.action == "sync"
        and not args.sync_stack
        and not args.final
    ):
        parser.error("--sync-stack is required for sync and permitted with checkpoint")
    if args.final and args.action != "sync":
        parser.error("--final is accepted only with --action sync")
    root = (root if root is not None else Path.cwd()).resolve()
    return steps.run(args, root, timing, create_runtime, load_units)


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--timing-log", type=Path)
    args, _ = parser.parse_known_args(argv)
    root = (root if root is not None else Path.cwd()).resolve()
    reported = False
    try:
        timing = Timing(root, args.timing_log)
        with timing.phase("controller"):
            result = controller_main(argv, root, timing)
            reported = True
            # A nonzero result is a failed invocation even when handled internally.
            if result:
                raise Blocked(
                    "controller stopped; see current request/progress diagnostics"
                )
            return result
    except (OSError, ValueError, Blocked) as error:
        if not reported:
            print(
                json.dumps(
                    {"result": "STOPPED", **cli_guidance.stopped("CONTROLLER", error)},
                    indent=2,
                )
            )
        print(f"CloudFormation controller: BLOCKED ({error})", file=sys.stderr)
        return 2
