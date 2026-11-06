"""Short deterministic CLI operations. The supervising LLM chooses when to sync."""

from __future__ import annotations

import copy
import json
import sys
from argparse import Namespace
from collections.abc import Callable
from contextlib import ExitStack, redirect_stdout
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from contracts.deploy import DEPLOY_RUNNING, DEPLOY_SUCCESS
from contracts.model import REFERENCE_PENDING_DEPLOY
from contracts.target import AWS_ACCOUNT_ID_KEY, IAC_ENGINE_KEY
from contracts.validation import VALIDATION_FAIL, VALIDATION_PASS
from model.sources import model_session, publication_lock
from task_contract_core import TaskSnapshot, selected_task, task_snapshot
from utils.aws.client import AwsError

from deploy import (
    cli_guidance,
    completion,
    context,
    current_state,
    failures,
    generation_resume,
    inputs,
    observed,
    observed_resume,
    operation_journal,
    recovery,
    run_context,
    temporary,
)
from deploy import progress as deploy_progress
from deploy.cli_guidance import DeployStepBlocked as Blocked
from deploy.model_cache import RunModels
from deploy.scheduler import run_group
from deploy.timing import Timing
from deploy.typing import StackUnit


def restore(backend: SimpleNamespace, task: TaskSnapshot) -> None:
    """Resume only this Task's local save; shared records contain requests only."""
    progress = deploy_progress.read_task(backend.root, task)
    saved = progress.get("runContext") if progress else None
    if saved:
        if (
            saved.get("taskDigest") != task.task_digest
            or saved.get("target") != backend.target
            or saved.get("stepUnits") != backend.units
        ):
            raise Blocked("local Deploy save belongs to different fixed inputs")
        changed_inputs = {
            relative
            for relative, digest in saved["consumedInputs"].items()
            if (
                backend.file_digest(backend.root / relative, fresh=True)
                if (backend.root / relative).is_file()
                else None
            )
            != digest
        }
        if changed_inputs:
            raise Blocked(
                "fixed execution inputs changed; retain current AWS request evidence"
            )
        current_identities = backend.run_context.get("inputIdentities", {})
        backend.run_context.update(copy.deepcopy(saved))
        if backend.phase == "update":
            backend.run_context["inputIdentities"].update(
                {
                    path: revision
                    for path, revision in current_identities.items()
                    if path not in saved["consumedInputs"]
                }
            )
        backend.states = backend.run_context["states"]
        for state in backend.states.values():
            if state["status"] == "READY":
                state["status"] = "CHANGESET_CREATING"
    backend.expected_digests = backend.run_context["inputDigests"]


def guard_local_publication(backend, task):
    current = task_snapshot(backend.root, executable=False, live=True)
    alias = backend.target.get("alias")
    if (
        current.status != "running"
        or current.name != task.name
        or current.task_digest != task.task_digest
        or context.load_target(
            backend.root,
            backend.environment,
            None if alias else backend.target[AWS_ACCOUNT_ID_KEY],
            alias,
        )
        != backend.target
    ):
        raise Blocked("local publication Task/target authority changed")
    return current


def recover_local_publication(backend, task):
    """Settle this Task's saved bytes before loading a possibly interrupted Model."""
    backend.run_context = {"taskFile": task.name, "taskDigest": task.task_digest}
    backend.states = {name: {} for name in backend.requested_stacks}
    progress = deploy_progress.read_task(backend.root, task)
    saved = progress.get("runContext") if progress else None
    if not saved or not (
        saved.get("pendingObserved") or saved.get("pendingGeneration")
    ):
        return
    if (
        saved.get("taskDigest") != task.task_digest
        or saved.get("target") != backend.target
        or set(saved.get("states", {})) != set(backend.requested_stacks)
    ):
        raise Blocked("local publication belongs to different fixed inputs")
    if getattr(backend, "action", None) != "checkpoint":
        for name in backend.requested_stacks:
            current_state.read(backend.aws, name)
    backend.run_context = copy.deepcopy(saved)
    backend.units = backend.run_context["stepUnits"]
    backend.states = backend.run_context["states"]
    backend.save = partial(save, backend)
    backend.guard = partial(guard_local_publication, backend, task)
    if saved.get("pendingObserved"):
        observed_resume.reconcile(
            backend.root,
            backend.run_context,
            backend.target,
            backend.environment,
            backend.directory,
        )
    generation_resume.recover_publications(backend)
    backend.save()


def save(backend):
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)


def sync(backend: SimpleNamespace, names: list[str], *, final=False) -> None:
    context = backend.run_context
    units = [u for u in backend.units if u["name"] in names]
    if (
        (not names and not final)
        or len(names) != len(set(names))
        or len(units) != len(names)
    ):
        raise Blocked("sync needs distinct --sync-stack names within Deployment scope")
    backend.guard()
    task = task_snapshot(backend.root, executable=False, live=True)
    if final and backend.phase != "deploy":
        raise Blocked("--final requires CloudFormation Deploy sync")
    if final:
        preview = {**context, "states": copy.deepcopy(backend.states)}
        completion.end_unexecuted(preview)
        if not completion.attempts_finished(
            preview["states"], context.get("deployResult")
        ) or any(
            deploy_progress.unresolved_request(item)
            for item in preview["states"].values()
        ):
            raise Blocked(
                "final sync requires settled AWS requests; continue the current Task"
            )
        missing = [
            name
            for name, state in backend.states.items()
            if not state.get("observedSynced") and name not in names
        ]
        if missing:
            raise Blocked(
                "final sync needs --sync-stack for current observations: "
                + ", ".join(missing)
            )
    pending = context.get("syncPending")
    if pending is not None and (
        pending["final"] != final
        or not set(pending["stacks"]) <= set(names)
        or set(pending["stacks"]) != set(names)
        and not context.get("pendingGeneration")
    ):
        raise Blocked(
            "resume the saved sync without changing its final intent or Stack scope"
        )
    context["snapshotValidation"] = "NOT_RUN"
    for unit in units:
        if unit["name"] not in context["inputDigests"]:
            backend.claim_inputs(unit)
    if pending is None:
        for unit in units:
            backend.states[unit["name"]].pop("observedSynced", None)
    context["syncPending"] = {"stacks": sorted(names), "final": final}
    backend.save()
    resumed_observation = bool(context.get("pendingObserved"))
    saved_observed = set(context.get("pendingObserved", {}).get("evidence", {}))
    if context.get("pendingObserved"):
        if not set(context["pendingObserved"]["evidence"]) <= set(names):
            raise Blocked("finish the saved Observed Stack scope before another sync")
        observed_resume.reconcile(
            backend.root,
            context,
            backend.target,
            backend.environment,
            backend.directory,
        )
    if context.get("pendingGeneration"):
        generation_resume.recover_publications(backend)
    if resumed_observation:
        observed.sync_successful(backend, units, backend.states)
        units = [
            unit
            for unit in units
            if unit["name"] not in saved_observed
            or not backend.states[unit["name"]].get("observedSynced")
        ]
    if units:
        observed.sync_successful(backend, units, backend.states)
    if context.get("pendingGeneration"):
        generation_resume.run(backend)
    elif context.get("generationError"):
        raise Blocked("generationError has no recoverable generation candidate")
    if final:
        completion.end_unexecuted(context)
        blockers = completion.final_blockers(context)
        if blockers:
            if not context.get("pendingObserved") and not context.get(
                "pendingGeneration"
            ):
                context.pop("syncPending")
            backend.save()
            raise Blocked("final sync requires: " + json.dumps(blockers))
    context["snapshotValidation"] = VALIDATION_FAIL
    backend.save()
    with publication_lock(backend.root, read_only=True):
        validated = completion.validate_local(
            backend.root, task, deploy=backend.phase == "deploy"
        )
        backend.guard()
        context["snapshotValidation"] = VALIDATION_PASS
        context.pop("syncPending")
        backend.save()
        if final:
            completion.finish_local(backend.root, task, validated)


def next_actions(backend, complete, can_advance):
    context, states = backend.run_context, backend.states
    pending = context.get("syncPending")
    if complete:
        return []
    if getattr(backend, "task_status", "running") == "completed":
        return [
            {
                "action": "review",
                "reason": "completed Task has incomplete Deploy evidence",
            }
        ]
    if pending:
        if context.get("generationError") and not context.get("pendingGeneration"):
            return [{"action": "review", "reason": context["generationError"]}]
        return [
            {"action": "sync", "stacks": pending["stacks"], "final": pending["final"]}
        ]
    actions = [{"action": "advance"}] if can_advance else []
    actions += [
        {"action": "sync", "stacks": [name]}
        for name, state in states.items()
        if not state.get("observedSynced")
        or any(
            record.get("approved")
            and not record.get("referenceSynced")
            and record["stack"] == name
            for item in states.values()
            for record in item.get("deferredConsumers", [])
        )
    ]
    preview = {**context, "states": copy.deepcopy(states)}
    if context.get("stepUnits"):
        completion.end_unexecuted(preview)
    if not completion.final_blockers(preview):
        actions.append({"action": "sync", "final": True, "stacks": []})
    if not actions:
        actions.append(
            {
                "action": "review",
                "reason": context.get("generationError")
                or "current request, AWS observation or attempt evidence is unconfirmed",
            }
        )
    return actions


def describe(backend: SimpleNamespace) -> dict:
    context = backend.run_context
    states = backend.states
    complete = getattr(
        backend, "task_status", "running"
    ) == "completed" and completion.local_ready(context)
    uncertain = any(
        s.get("pollReadFailures") or s.get("schedulerError") for s in states.values()
    )
    failed = any(
        (s["status"] == "FAILED" or s.get("failureDetected"))
        and s.get("cleanupStatus") != "DELETE_INTENT"
        for s in states.values()
    )
    units = getattr(backend, "units", [])
    active = [
        unit
        for unit in units
        if states[unit["name"]]["status"] != DEPLOY_SUCCESS
        and unit["name"] not in getattr(backend, "verified_settled", set())
    ]
    order = min((int(unit["deployOrder"]) for unit in active), default=None)
    candidates = (
        [states[unit["name"]] for unit in active if int(unit["deployOrder"]) == order]
        if units
        else list(states.values())
    )
    can_advance = any(
        s["status"]
        in {DEPLOY_RUNNING, "NOT_STARTED", "READY", "CHANGESET_CREATING", "SETTLED"}
        and not s.get("schedulerError")
        and s.get("failure", {}).get("classification") != "APPROVAL"
        for s in candidates
    )
    return {
        "result": "COMPLETE"
        if complete
        else "STOPPED"
        if (
            failed
            or uncertain
            or any(s["status"] == "BLOCKED" for s in states.values())
        )
        and not can_advance
        else "PENDING",
        "task": getattr(backend, "task_status", "running"),
        "finalBlockers": completion.final_blockers(context),
        "deployResult": context.get(
            "deployResult",
            "FAIL"
            if failed
            else "UNKNOWN"
            if uncertain
            or any(s.get("attemptResult") == "UNKNOWN" for s in states.values())
            else "SUCCESS"
            if all(s["status"] == DEPLOY_SUCCESS for s in states.values())
            else "PENDING",
        ),
        "modelSave": "PENDING"
        if context.get("pendingObserved")
        else "COMPLETE"
        if all(s.get("observedSynced") for s in states.values())
        else "PENDING",
        "snapshotValidation": context.get("snapshotValidation", "NOT_RUN"),
        "currentFailure": context.get("currentFailure"),
        "states": {
            name: {
                "aws": current_state.category(state.get("currentStack", {})),
                "attempt": state["status"],
                "attemptResult": state.get("attemptResult"),
                "stackId": state.get("stackId"),
                "stackStatus": state.get("stackStatus"),
                "progress": {
                    **state.get("progress", {"available": False, "partial": True}),
                    "phase": current_state.progress_phase(
                        state.get("stackStatus"),
                        state["status"],
                        (state.get("failure") or {}).get("stage"),
                    ),
                    "stackStatus": state.get("stackStatus"),
                    "asOf": state.get("currentStack", {}).get("observedAt"),
                },
                "changeSetId": state.get("changeSetId"),
                "changes": state.get("changes", []),
                "observed": "COMPLETE" if state.get("observedSynced") else "PENDING",
                "coverage": state.get("observedCoverage", {}),
                "deferredConsumers": state.get("deferredConsumers", []),
                "generation": "PENDING"
                if context.get("generationError")
                else "NOT_STARTED"
                if not state.get("observedSynced")
                else "PENDING"
                if context.get("pendingGeneration")
                else "COMPLETE",
                "failure": state.get("failure"),
                **(
                    {"diagnostic": diagnostic}
                    if (diagnostic := failures.diagnostic(state))
                    else {}
                ),
                **{
                    key: state[key]
                    for key in (
                        "failureClassification",
                        "changeSetFailure",
                        "failureEvents",
                    )
                    if state.get(key)
                },
                **(
                    {"stackStatusReason": state["currentStack"]["statusReason"]}
                    if state.get("currentStack", {}).get("statusReason")
                    else {}
                ),
                "unexecutedReason": state.get("unexecutedReason")
                if state["status"] in {"READY", "NOT_STARTED"}
                else None,
                "runtime": state.get("cleanupStatus")
                or state.get("bootstrap", {}).get("stage"),
            }
            for name, state in states.items()
        },
        "pendingGeneration": {
            view: {
                "reason": REFERENCE_PENDING_DEPLOY
                if r["reason"] == REFERENCE_PENDING_DEPLOY
                else "PUBLICATION_PENDING",
                "producers": r["producers"],
                "consumer": view,
            }
            for view, r in context.get("pendingGeneration", {}).items()
        },
        "nextActions": next_actions(backend, complete, can_advance),
    }


def run(
    args: Namespace,
    root: Path,
    timing: Timing,
    backend_type: Callable[..., SimpleNamespace],
    load_units: Callable[..., tuple[int, list[StackUnit]]],
) -> int:
    backend = None
    try:
        task = task_snapshot(root, executable=False, live=True)
        if task.status == "completed" and args.action != "status":
            raise Blocked("completed Deploy permits status only")
        selected = context.load_target(
            root, args.environment, args.aws_account_id, args.alias
        )
        phase = run_context.active_scope(
            root,
            args.stack,
            args.environment,
            selected[AWS_ACCOUNT_ID_KEY],
            args.alias,
            snapshot=task,
            allow_saved=args.action in {"status", "checkpoint", "sync"},
        )
        if getattr(args, "final", False) and (
            args.action != "sync"
            or phase != "deploy"
            or selected[IAC_ENGINE_KEY] != "cloudformation"
        ):
            raise Blocked("--final requires CloudFormation Deploy --action sync")
        fixed = deploy_progress.identity(task, selected, args.environment, args.stack)
        authentication_error = None
        try:
            target = context.check_deploy_context(
                root, args.environment, args.aws_account_id, args.alias, args.profile
            )
        except AwsError as error:
            if args.action in {"advance", "sync"}:
                raise
            target, authentication_error = selected, error
        if target[IAC_ENGINE_KEY] != "cloudformation":
            raise Blocked("step operations require CloudFormation")
        directory = args.alias or args.aws_account_id
        journal = operation_journal.location(root, task.name)
        with (
            ExitStack() as resources,
            selected_task(root, task.name),
            redirect_stdout(sys.stderr),
        ):
            destination = deploy_progress.progress_path(root, task.name, create=True)
            resources.enter_context(operation_journal.locked(destination))
            deploy_progress.require_no_correction(destination)
            saved = deploy_progress.read_task(root, task)
            if saved is not None and saved["identity"] != fixed:
                raise Blocked("Deploy Task/Target/Stack identity changed")
            backend = backend_type(
                root,
                args.environment,
                directory,
                target,
                args.profile,
                args.approve_change_set,
            )
            backend.phase, backend.timing = phase, timing
            backend.progress_identity = fixed
            backend.progress_root = root
            backend.progress_directory = directory
            backend.progress_task_file = task.name
            backend.progress_destination = destination
            if authentication_error:
                backend.aws = partial(
                    current_state.unavailable, authentication_error.code
                )
            backend.requested_stacks = args.stack
            backend.action = args.action
            backend.task_status = task.status
            if task.status != "completed":
                recover_local_publication(backend, task)
            if authentication_error and args.action == "checkpoint":
                raise authentication_error
            snapshot = inputs.stack_snapshot(
                root
                / "model"
                / args.environment
                / directory
                / "cloudformation-stacks.properties"
            )
            limit, units = load_units(
                root, args.environment, directory, args.stack, snapshot=snapshot
            )
            if args.sequential:
                limit = 1
            backend.units = units
            backend.run_context = run_context.new_context(
                root, task, target, args.environment, directory, units, backend
            )
            backend.run_context.update(
                stepUnits=copy.deepcopy(units), deployContract=task.text
            )
            backend.states = backend.run_context["states"]
            restore(backend, task)
            run = backend.run_context
            backend.save = partial(save, backend)
            backend.guard = partial(
                run_context._callback_run_guard,
                args,
                backend,
                context,
                root,
                selected,
                run,
                target,
            )
            backend.claim_inputs = partial(
                run_context._callback_claim_inputs, root, run, backend, backend.save
            )
            backend.refresh_validation = partial(
                run_context._callback_run_refresh_validation,
                backend,
                run["inputDigests"],
            )
            backend.wait_cleanup = partial(
                recovery.wait_cleanup, backend.aws, backend.save, single_step=True
            )
            if args.action != "checkpoint" and task.status != "completed":
                current_state.refresh(
                    backend,
                    [unit for unit in units if unit["name"] in args.sync_stack]
                    if args.action == "sync"
                    else units,
                )
                if args.action == "status":
                    for unit in units:
                        state = backend.states[unit["name"]]
                        current = state.get("currentStack", {})
                        evidence = state.get("executionEvidence", {})
                        token = state.get("clientToken")
                        stack_id = evidence.get("StackId") or current.get("StackId")
                        if (
                            not token
                            or (
                                evidence.get("clientToken")
                                and evidence["clientToken"] != token
                            )
                            or (
                                evidence.get("ChangeSetId")
                                and not current_state.same_change_set(
                                    state.get("changeSetId"), evidence["ChangeSetId"]
                                )
                            )
                            or (
                                state.get("progress")
                                and not state["progress"].get("stale")
                            )
                        ):
                            continue
                        if not stack_id or current.get("StackId") != stack_id:
                            state["progress"] = {
                                "available": False,
                                "partial": True,
                                "stale": True,
                            }
                            continue
                        try:
                            events = current_state.pages(
                                partial(current_state._event_page, backend.aws),
                                "describe_stack_events",
                                "StackEvents",
                                StackName=stack_id,
                            )
                            state["progress"] = current_state.event_progress(
                                current, events, token, stack_id, unit["name"]
                            )
                        except (OSError, AwsError, ValueError, RuntimeError):
                            state["progress"] = {
                                "available": False,
                                "partial": True,
                                "stale": True,
                            }
            if args.action == "advance" and run.get("syncPending"):
                raise Blocked("resume the saved sync before advance")
            if args.action == "advance":
                backend.guard()
                backend.workdir = temporary.create(journal, args.stack)
                try:
                    resources.callback(
                        temporary.reclaim,
                        journal,
                        root,
                        directory=backend.workdir,
                        backend=backend,
                        stacks=args.stack,
                    )
                except BaseException:
                    try:
                        backend.workdir.rmdir()
                    except OSError:
                        pass
                    raise
                models = RunModels(root, run)
                resources.enter_context(model_session(models))
                for unit in units:
                    state = backend.states[unit["name"]]
                    if state["status"] in {
                        DEPLOY_RUNNING,
                        "CHANGESET_CREATING",
                        "READY",
                    }:
                        backend.load_inputs(unit)
                run_group(
                    units,
                    limit,
                    backend.states,
                    backend,
                    backend.save,
                )
                if any(s["status"] == "FAILED" for s in backend.states.values()):
                    run["deployResult"] = "FAIL"
                if "- Runtime recovery: `allowed`" in task.text.splitlines():
                    for unit in units:
                        state = backend.states[unit["name"]]
                        if state["status"] == "FAILED" and not state.get(
                            "bootstrapAttempted"
                        ):
                            backend.repair(unit, state)
                if any(
                    s["status"] in {"FAILED", "BLOCKED"}
                    for s in backend.states.values()
                ) and not run.get("currentFailure"):
                    run["currentFailure"] = failures.record_failure(backend)
                backend.save()
            elif args.action in {"sync", "checkpoint"}:
                models = RunModels(root, run)
                resources.enter_context(model_session(models))
                backend.after_observed = models.apply_observed
                pending = run.get("syncPending")
                if args.action == "checkpoint":
                    if pending is None:
                        raise Blocked("no local sync to resume; use --action sync")
                    sync(
                        backend,
                        args.sync_stack or pending["stacks"],
                        final=pending["final"],
                    )
                else:
                    sync(backend, args.sync_stack, final=getattr(args, "final", False))
            backend.task_status = task_snapshot(
                root, executable=False, live=True
            ).status
            result = describe(backend)
            if authentication_error:
                result.update(
                    cli_guidance.stopped("AUTHENTICATION", authentication_error)
                )
                result["result"] = "STOPPED"
        print(json.dumps(result, indent=2))
        return (
            2
            if (
                authentication_error
                or result["result"] == "STOPPED"
                and args.action == "advance"
            )
            else 0
        )
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "result": "STOPPED",
                    "modelSave": "COMPLETE"
                    if backend
                    and any(s.get("observedSynced") for s in backend.states.values())
                    else "PENDING",
                    "snapshotValidation": backend.run_context.get(
                        "snapshotValidation", "NOT_RUN"
                    )
                    if backend
                    else "NOT_RUN",
                    **cli_guidance.stopped(
                        "STEP",
                        error,
                        template_paths=temporary.diagnostic_paths(
                            journal, backend, args.stack
                        )
                        if backend and "journal" in locals()
                        else (),
                    ),
                },
                indent=2,
            )
        )
        return 2
