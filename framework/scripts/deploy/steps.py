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

import worktree_task as wt
from model.sources import model_session
from task_contract_core import TaskSnapshot, selected_task, set_status, task_snapshot
from utils.aws.client import AwsError

from deploy import (
    cli_guidance,
    context,
    contracts,
    current_request,
    current_state,
    generation_resume,
    git_publication,
    handoff,
    observed,
    observed_resume,
    operation_journal,
    recovery,
    run_context,
    temporary,
    worktree,
)
from deploy.cli_guidance import DeployStepBlocked as Blocked
from deploy.model_cache import RunModels
from deploy.scheduler import run_group
from deploy.timing import Timing
from deploy.typing import StackUnit


def restore(backend: SimpleNamespace, task: TaskSnapshot) -> None:
    """Resume only this Task's local save; shared records contain requests only."""
    lifecycle = worktree.require(backend.root, task)
    if lifecycle is None:
        lifecycle = worktree.progress_state(backend)
    progress = worktree.read_progress(backend.root, lifecycle) if lifecycle else None
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
            current_state.refresh(backend, backend.units)
            if (
                contracts.accepted_changes(
                    backend.root, task.text, changed_inputs, contract_file=task.name
                )
                != changed_inputs
            ):
                raise Blocked(
                    "fixed execution inputs changed without verified implement authority"
                )
            for unit in backend.units:
                paths = {
                    path.relative_to(backend.root).as_posix()
                    for path in backend.deployment_input_paths([unit])
                }
                if paths & changed_inputs and current_request.reconcile(backend, unit):
                    raise Blocked(
                        "current request must settle before changing its inputs: "
                        + unit["name"]
                    )
            for key in (
                "pendingObserved",
                "pendingGeneration",
                "generationError",
                "checkpointPending",
                "modelInputs",
                "generationProducers",
            ):
                if key in saved:
                    backend.run_context[key] = copy.deepcopy(saved[key])
            backend.expected_digests = backend.run_context["inputDigests"]
            return
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
    worktree.require(backend.root, current)
    alias = backend.target.get("alias")
    if (
        current.status != "running"
        or current.task_digest != task.task_digest
        or context.load_target(
            backend.root,
            backend.environment,
            None if alias else backend.target["awsAccountId"],
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
    lifecycle = worktree.progress_state(backend)
    progress = worktree.read_progress(backend.root, lifecycle)
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


def checkpoint_receipts(backend: SimpleNamespace) -> dict:
    """Git receipts describe saved snapshots; they never manufacture AWS success."""
    if backend.phase != "deploy":
        return {}
    _, _, _, state = wt.load(backend.root, backend.root.name)
    receipts = state.get("deployCheckpoints", {})
    return receipts


def save(backend):
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)


def refresh_requests(backend, units=None):
    units = backend.units if units is None else units
    current_state.refresh(backend, units)
    for unit in units:
        state = backend.states[unit["name"]]
        try:
            request = current_request.reconcile(backend, unit)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            state.update(requestPending=True, requestError=str(error))
            continue
        if request and request.get("settled"):
            if (
                request.get("operation") == "execute_change_set"
                and request.get("token") == state.get("clientToken")
                and not current_request.owns(state, request)
            ):
                state.update(
                    requestPending=True, requestError="current request identity differs"
                )
                continue
            if (
                current_request.owns(state, request)
                and request["operation"] == "execute_change_set"
                and request.get("trackingReason")
                not in {"ORIGINAL_STACK_DELETED", "ORIGINAL_STACK_REPLACED"}
            ):
                status = backend.poll(unit, state)
                if status in {"ATTEMPT_SUCCESS", "ATTEMPT_FAIL"}:
                    request["result"] = (
                        "SUCCESS" if status == "ATTEMPT_SUCCESS" else "FAIL"
                    )
            elif state.get("externalOperation"):
                current = state["currentStack"]
                state.clear()
                state.update(
                    status="NOT_STARTED",
                    currentStack=current,
                    stackId=current.get("StackId"),
                    stackStatus=current["StackStatus"],
                )
            current_request.end_tracking(state, request)
            backend.save()
            current_request.release(backend, request)
            continue
        state["requestPending"] = bool(request)
        if state.get("cleanupStatus") == "DELETE_INTENT":
            state["status"] = "NOT_STARTED"
            continue
        if request:
            if (
                request.get("service") == "secretsmanager"
                and current_state.category(state["currentStack"]) != "RUNNING"
            ):
                continue
            own_request = current_request.owns(state, request)
            if not own_request:
                if state["status"] != "SETTLED":
                    state["externalOperation"] = True
                    state["status"] = "RUNNING"
            elif request.get("operation") == "create_change_set":
                state["status"] = (
                    "NOT_STARTED"
                    if state.get("createUnconfirmed")
                    else "CHANGESET_CREATING"
                )
            else:
                state["status"] = (
                    "RUNNING"
                    if current_state.category(state["currentStack"]) == "RUNNING"
                    else "BLOCKED"
                )
        elif (
            state["status"] == "RUNNING"
            or state.get("attemptResult") == "UNKNOWN"
            and state["status"] != "SETTLED"
        ) and (
            state.get("clientToken")
            or current_state.category(state["currentStack"]) != "RUNNING"
        ):
            if state.get("externalOperation"):
                current = state["currentStack"]
                state.clear()
                state.update(
                    status="NOT_STARTED",
                    currentStack=current,
                    stackId=current.get("StackId"),
                    stackStatus=current["StackStatus"],
                )
            else:
                try:
                    status = backend.poll(unit, state)
                    current_state.record_attempt(state, status)
                    settled = state.get("settledRequest")
                    if settled:
                        current_request.end_tracking(state, settled)
                    backend.save()
                    if settled:
                        current_request.release(backend, settled)
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    RuntimeError,
                ) as error:
                    state["requestError"] = str(error)

        elif (
            state["status"] != "SETTLED"
            and current_state.category(state["currentStack"]) == "RUNNING"
        ):
            state.update(status="RUNNING", externalOperation=True)


def retry_terminal_attempts(backend, previous_terminal):
    retried = False
    for name in previous_terminal:
        state = backend.states[name]
        if (
            state.get("attemptResult") == "UNKNOWN"
            and not state.get("endedRequest")
            or state.get("requestPending")
            or state.get("requestError")
            or state.get("bootstrap", {}).get("stage")
            in {
                "BOOTSTRAP_INTENT",
                "VALUE_CHECKED_MISSING",
                "PUT_SUBMITTED",
            }
        ):
            continue
        unit = next(
            (u for u in getattr(backend, "units", []) if u["name"] == name), None
        )
        if unit and any(
            other["name"] != name
            and other["deployOrder"] == unit["deployOrder"]
            and backend.states[other["name"]]["status"]
            in {"NOT_STARTED", "READY", "CHANGESET_CREATING"}
            for other in backend.units
        ):
            continue
        retained = {
            key: state[key]
            for key in (
                "currentStack",
                "stackId",
                "stackStatus",
                "cleanupStatus",
                "cleanupStackId",
                "emptyStackRecreated",
                "bootstrapAttempted",
                "endedRequest",
            )
            if key in state
        }
        state.clear()
        state.update(retained, status="NOT_STARTED")
        retried = True
    if retried:
        backend.run_context.pop("deployResult", None)


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
    if final and (
        backend.phase != "deploy" or not worktree.require(backend.root, task)
    ):
        raise Blocked("--final requires managed CloudFormation Deploy sync")
    if final:
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
    context["snapshotValidation"] = "NOT_RUN"
    for unit in units:
        if unit["name"] not in context["inputDigests"]:
            backend.claim_inputs(unit)
    pending = context.get("checkpointPending")
    if pending is None:
        if git_publication.output_changes(backend.root, {"task_file": task.name}):
            raise Blocked("sync requires clean inputs or its own retained publication")
        pending = {
            "stacks": [],
            "before": contracts.validation_snapshot(backend.root),
            "after": None,
        }
        if final:
            pending["final"] = {
                "taskBefore": task.text,
                "taskAfter": set_status(task.text, "completed"),
            }
        context["checkpointPending"] = pending
        for unit in units:
            backend.states[unit["name"]].pop("observedSynced", None)
    elif bool(pending.get("final")) != final or set(names) != set(pending["stacks"]):
        raise Blocked(
            "resume the saved checkpoint without changing its final intent or Stack scope"
        )
    elif pending.get("after") is not None:
        if contracts.validation_snapshot(backend.root) != pending["after"]:
            raise Blocked("synchronized candidate changed before next sync")
    pending["stacks"] = sorted(set(pending["stacks"]) | set(names))
    pending["after"] = None
    backend.save()
    resumed_observation = bool(context.get("pendingObserved"))
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
    if not context.get("pendingObserved"):
        for unit in units:
            backend.states[unit["name"]].pop("checkpointed", None)
    if units:
        observed.sync_successful(backend, units, backend.states)
    if resumed_observation:
        # Finish the retained candidate first, then collect the facts chosen for this sync.
        observed.sync_successful(backend, units, backend.states)
    if context.get("pendingGeneration"):
        generation_resume.run(backend)
    elif context.get("generationError"):
        raise Blocked("generationError has no recoverable generation candidate")
    if final:
        worktree.end_unexecuted(context)
        blockers = worktree.final_blockers(context)
        if blockers:
            backend.save()
            raise Blocked("final sync requires: " + json.dumps(blockers))
    pending["after"] = contracts.validation_snapshot(backend.root)
    backend.guard()
    backend.save()
    publish_snapshot(backend, pending["stacks"])


def publish_snapshot(backend, names):
    wt.deploy_stack_checkpoint(backend, names)
    git_publication.sync(backend)


def next_actions(backend, complete, can_advance, publication):
    """Derive executable routes from the saved candidate, never change its intent."""
    context, states = backend.run_context, backend.states
    pending = context.get("checkpointPending")
    git_actions = (publication or {}).get("nextActions", [])
    if pending:
        if context.get("generationError") and not context.get("pendingGeneration"):
            actions = [{"action": "review", "reason": context["generationError"]}]
        elif (
            context.get("pendingObserved")
            or context.get("pendingGeneration")
            or pending.get("after") is not None
        ):
            actions = [{"action": "checkpoint", "stacks": pending["stacks"]}]
        else:
            actions = [
                {
                    "action": "sync",
                    "stacks": pending["stacks"],
                    "final": bool(pending.get("final")),
                }
            ]
        return actions + git_actions
    if complete:
        return (
            [{"action": "finalize", "taskId": Path(context["taskFile"]).stem}]
            if (publication or {}).get("status") == "SUCCESS"
            else git_actions
        )
    if getattr(backend, "task_status", "running") == "completed":
        return [
            {
                "action": "review",
                "reason": "locally completed candidate is incomplete; inspect saved checkpoint evidence",
            }
        ] + git_actions
    actions = [{"action": "advance"}] if can_advance else []
    actions += [
        {"action": "sync", "stacks": [name]}
        for name, state in states.items()
        if not state.get("observedSynced")
    ]
    preview = {**context, "states": copy.deepcopy(states)}
    if context.get("stepUnits"):
        worktree.end_unexecuted(preview)
    if not worktree.final_blockers(preview):
        actions.append({"action": "sync", "final": True, "stacks": []})
    if not actions and not git_actions:
        actions.append(
            {
                "action": "review",
                "reason": context.get("generationError")
                or "current request, AWS observation or attempt evidence is unconfirmed",
            }
        )
    return actions + git_actions


def describe(backend: SimpleNamespace) -> dict:
    context = backend.run_context
    states = backend.states
    pending = context.get("checkpointPending")
    publication = git_publication.display(backend)
    if publication is not None:
        publication["checkpointRequired"] = pending["stacks"] if pending else []
        if pending:
            publication["nextActions"] = [
                action
                for action in publication.get("nextActions", [])
                if action.get("action") != "deploy-publish"
            ]
            publication["retryable"] = False
            if publication.get("status") != "CONFLICT":
                publication["reason"] = (
                    "finish the pending Stack checkpoint before Git publication"
                )
    complete = (
        getattr(backend, "task_status", "running") == "completed"
        and generation_resume.complete(context)
        and worktree.attempts_finished(states, context.get("deployResult"))
        and all(s.get("observedSynced") for s in states.values())
        and context.get("snapshotValidation") == "PASS"
        and not pending
        and all(
            s.get("status") != "RUNNING"
            and not s.get("requestPending")
            and current_state.category(s.get("currentStack", {})) != "RUNNING"
            for s in states.values()
        )
    )
    publication_pending = (
        getattr(backend, "phase", None) == "deploy"
        and (publication or {}).get("status") != "SUCCESS"
    )
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
        if states[unit["name"]]["status"] != "SUCCESS"
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
        in {"RUNNING", "NOT_STARTED", "READY", "CHANGESET_CREATING", "SETTLED"}
        and not s.get("requestError")
        and not s.get("schedulerError")
        and s.get("failure", {}).get("classification") != "APPROVAL"
        for s in candidates
    )
    return {
        "result": "PUBLICATION_PENDING"
        if complete and publication_pending
        else "COMPLETE"
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
        "finalBlockers": worktree.final_blockers(context),
        "deployResult": context.get(
            "deployResult",
            "FAIL"
            if failed
            else "UNKNOWN"
            if uncertain
            or any(s.get("attemptResult") == "UNKNOWN" for s in states.values())
            else "SUCCESS"
            if all(s["status"] == "SUCCESS" for s in states.values())
            else "PENDING",
        ),
        "modelSave": "PENDING"
        if context.get("pendingObserved")
        else "COMPLETE"
        if all(s.get("observedSynced") for s in states.values())
        else "PENDING",
        "snapshotValidation": context.get("snapshotValidation", "NOT_RUN"),
        "gitPublication": publication,
        "repairFailure": context.get("currentFailure"),
        "states": {
            name: {
                "aws": current_state.category(state.get("currentStack", {})),
                "attempt": state["status"],
                "attemptResult": state.get("attemptResult"),
                "endedRequest": state.get("endedRequest"),
                "requestPending": state.get("requestPending", False),
                "requestError": state.get("requestError"),
                "stackId": state.get("stackId"),
                "stackStatus": state.get("stackStatus"),
                "changeSetId": state.get("changeSetId"),
                "changes": state.get("changes", []),
                "observed": "COMPLETE" if state.get("observedSynced") else "PENDING",
                "coverage": state.get("observedCoverage", {}),
                "generation": "PENDING"
                if context.get("generationError")
                else "COMPLETE"
                if state.get("checkpointed")
                else "NOT_STARTED"
                if not state.get("observedSynced")
                else "PENDING"
                if context.get("pendingGeneration")
                else "COMPLETE",
                "checkpoint": "CHECKPOINTED"
                if state.get("checkpointed")
                else "PENDING",
                "failure": state.get("failure"),
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
                "reason": "REFERENCE_PENDING_DEPLOY"
                if r["reason"] == "REFERENCE_PENDING_DEPLOY"
                else "PUBLICATION_PENDING",
                "producers": r["producers"],
                "consumer": view,
            }
            for view, r in context.get("pendingGeneration", {}).items()
        },
        "nextActions": next_actions(backend, complete, can_advance, publication),
    }


def run(
    args: Namespace,
    root: Path,
    timing: Timing,
    backend_type: Callable[..., SimpleNamespace],
    load_units: Callable[[Path, str, str, list[str]], tuple[int, list[StackUnit]]],
) -> int:
    backend = None
    try:
        task = task_snapshot(root, executable=False, live=True)
        if task.status == "completed" and args.action == "advance":
            lifecycle = worktree.require(root, task)
            progress = worktree.read_progress(root, lifecycle) if lifecycle else None
            if progress and progress["runContext"].get("checkpointPending"):
                raise Blocked(
                    "locally completed candidate still needs --action checkpoint; advance is unavailable"
                )
            raise Blocked(
                "completed Deploy cannot advance; use deploy-publish for saved Git work or finalize after publication"
            )
        selected = context.load_target(
            root, args.environment, args.aws_account_id, args.alias
        )
        phase = run_context.active_scope(
            root,
            args.stack,
            args.environment,
            selected["awsAccountId"],
            args.alias,
            snapshot=task,
            allow_saved=args.action in {"status", "checkpoint", "sync"},
        )
        if getattr(args, "final", False) and (
            args.action != "sync"
            or phase != "deploy"
            or selected["iacEngine"] != "cloudformation"
        ):
            raise Blocked(
                "--final requires managed CloudFormation Deploy --action sync"
            )
        if getattr(args, "final", False):
            worktree.require(root, task)
        progress_identity = worktree.bind(
            root, task, selected, args.environment, args.stack
        )
        authentication_error = None
        if args.action == "checkpoint":
            target = selected
        else:
            try:
                target = context.check_deploy_context(
                    root,
                    args.environment,
                    args.aws_account_id,
                    args.alias,
                    args.profile,
                )
            except AwsError as error:
                if args.action == "advance":
                    raise
                target, authentication_error = selected, error.code
        if target["iacEngine"] != "cloudformation":
            raise Blocked("step operations require CloudFormation")
        directory = args.alias or args.aws_account_id
        journal = operation_journal.location(target)
        with (
            ExitStack() as resources,
            selected_task(root, task.name),
            redirect_stdout(sys.stderr),
        ):
            resources.enter_context(
                operation_journal.locked(worktree.progress_path(root, create=True))
            )
            backend = backend_type(
                root,
                args.environment,
                directory,
                target,
                args.profile,
                args.approve_change_set,
            )
            backend.phase, backend.timing = phase, timing
            if phase == "deploy":
                backend.progress_identity = progress_identity
                backend.progress_root = root
                backend.progress_directory = directory
                backend.progress_destination = worktree.progress_path(root, create=True)
            if authentication_error:
                backend.aws = partial(current_state.unavailable, authentication_error)
            backend.requested_stacks = args.stack
            backend.action = args.action
            backend.task_status = task.status
            if task.status != "completed":
                recover_local_publication(backend, task)
            limit, units = load_units(root, args.environment, directory, args.stack)
            if args.sequential:
                limit = 1
            backend.units = units
            backend.run_context = run_context.new_context(
                root, task, target, args.environment, directory, units, backend
            )
            backend.run_context.update(stepUnits=copy.deepcopy(units))
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
            previous_terminal = {
                name
                for name, state in backend.states.items()
                if state["status"] == "FAILED"
                or state.get("attemptResult") == "UNKNOWN"
            }
            if args.action != "checkpoint" and task.status != "completed":
                refresh_requests(
                    backend,
                    [unit for unit in units if unit["name"] in args.sync_stack]
                    if args.action == "sync"
                    else units,
                )
                if args.action == "advance":
                    previous_terminal.update(
                        name
                        for name, state in backend.states.items()
                        if backend.states[name]["status"] == "SUCCESS"
                        and state.get("needsCurrentReview")
                    )
                    retry_terminal_attempts(backend, previous_terminal)
            checkpoint_receipts(backend)
            if args.action == "advance" and run.get("checkpointPending"):
                raise Blocked("resume the saved checkpoint before advance")
            if args.action == "advance":
                backend.guard()
                backend.workdir = temporary.create(
                    journal, root, task, target, args.stack
                )
                resources.callback(
                    temporary.reclaim, journal, root, target, task=task, run_context=run
                )
                models = RunModels(root, run)
                resources.enter_context(model_session(models))
                for unit in units:
                    state = backend.states[unit["name"]]
                    if state["status"] in {"RUNNING", "CHANGESET_CREATING", "READY"}:
                        backend.load_inputs(unit)
                    if state.get("requestError"):
                        state.update(status="BLOCKED", reason=state["requestError"])
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
                        if backend.states[unit["name"]]["status"] == "FAILED":
                            backend.repair(unit, backend.states[unit["name"]])
                if any(
                    s["status"] in {"FAILED", "BLOCKED"}
                    for s in backend.states.values()
                ) and not run.get("currentFailure"):
                    run["currentFailure"] = handoff.record_failure(backend)
                backend.save()
            elif args.action in {"sync", "checkpoint"}:
                if task.status == "completed" and not run.get("checkpointPending"):
                    git_publication.sync(backend)
                else:
                    models = RunModels(root, run)
                    resources.enter_context(model_session(models))
                    backend.after_observed = models.apply_observed
                    if args.action == "sync":
                        sync(
                            backend,
                            args.sync_stack,
                            final=getattr(args, "final", False),
                        )
                    elif run.get("checkpointPending"):
                        if run.get("pendingGeneration"):
                            generation_resume.run(backend)
                        if run["checkpointPending"].get("final"):
                            worktree.end_unexecuted(run)
                        if run["checkpointPending"].get(
                            "after"
                        ) is None and not run.get("pendingObserved"):
                            run["checkpointPending"]["after"] = (
                                contracts.validation_snapshot(root)
                            )
                            backend.save()
                        publish_snapshot(
                            backend,
                            args.sync_stack or run["checkpointPending"]["stacks"],
                        )
                    else:
                        git_publication.sync(backend)
            backend.task_status = task_snapshot(
                root, executable=False, live=True
            ).status
            result = describe(backend)
        print(json.dumps(result, indent=2))
        return 2 if result["result"] == "STOPPED" and args.action == "advance" else 0
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
                    **cli_guidance.stopped("STEP", error),
                },
                indent=2,
            )
        )
        return 2
