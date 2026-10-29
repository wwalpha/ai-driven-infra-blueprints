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
from model.dependency_index import revision as file_revision
from model.sources import model_session
from task_contract_core import TaskSnapshot, selected_task, task_snapshot

from deploy import (
    change_sets,
    cli_guidance,
    context,
    contracts,
    generation_resume,
    git_publication,
    handoff,
    observed,
    observed_resume,
    operation_journal,
    operation_reset,
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


def restore(backend: SimpleNamespace, journal: Path, task: TaskSnapshot) -> None:
    """Read original IDs without recovery polling, publication or new execution."""
    records = operation_journal.read(journal) or []
    worktree.check_pending_progress(backend, records, operation_journal.unfinished)
    owned = []
    retained = []
    names = {u["name"] for u in backend.units}
    for record in records:
        if operation_journal.target_identity(
            record["target"]
        ) != operation_journal.target_identity(backend.target):
            raise Blocked("unfinished operation Account/Region changed")
        publication = record["publication"]
        overlap = names & record["operations"].keys()
        same = (
            publication.get("repository") == str(backend.root)
            and publication.get("taskFile") == task.name
        )
        if same or overlap:
            if (
                not same
                or not publication.get("stepwise")
                or publication.get("taskDigest") != task.task_digest
                or publication.get("target") != backend.target
                or publication.get("inputDigest") != backend.run_context["inputDigest"]
                or publication.get("stepUnits") != backend.units
                or not record["operations"].keys() <= names
            ):
                raise Blocked(
                    "unfinished operation ownership/inputs changed; retain evidence for review"
                )
            owned.append(record)
        else:
            retained.append(record)
    if len(owned) > 1:
        raise Blocked("multiple unfinished publications own this Task")
    backend.retained_records = retained
    if owned:
        record = owned[0]
        backend.run_context.update(copy.deepcopy(record["publication"]))
        for name, operation in record["operations"].items():
            operation_journal.validate_operation(backend.target, name, operation)
            unit = next(u for u in backend.units if u["name"] == name)
            if unit != operation["unit"]:
                raise Blocked("unfinished Stack unit changed: " + name)
            backend.states[name] = copy.deepcopy(operation["state"])
    backend.expected_digests = backend.run_context["inputDigests"]


def reconcile_before_model_load(
    backend: SimpleNamespace, journal: Path, task: TaskSnapshot, args: Namespace
) -> list[StackUnit] | None:
    """Reconcile partial publication before even the Stack Model readers run."""
    records = operation_journal.read(journal) or []
    owned = [
        r
        for r in records
        if r["publication"].get("repository") == str(backend.root)
        and r["publication"].get("taskFile") == task.name
        and (
            r["publication"].get("pendingObserved")
            or any(
                plan["generated"]["outputs"] is not None
                for plan in r["publication"].get("pendingGeneration", {}).values()
            )
        )
    ]
    if not owned:
        return None
    if len(owned) != 1:
        raise Blocked("ambiguous pending publication owner")
    record = owned[0]
    run = copy.deepcopy(record["publication"])
    if (
        not run.get("stepwise")
        or run.get("taskDigest") != task.task_digest
        or run.get("target") != backend.target
    ):
        raise Blocked("pending publication Task/Target changed")
    _, _, _, lifecycle = wt.load(backend.root, backend.root.name)
    units = {u["name"]: u for u in run["stepUnits"]}
    if any(
        units.get(n) != entry["unit"]
        for n, entry in lifecycle.get("deployCheckpoints", {}).items()
    ):
        raise Blocked("pending publication checkpoint unit differs from signed inputs")
    units.update({n: op["unit"] for n, op in record["operations"].items()})
    if set(units) != set(args.stack):
        raise Blocked("pending publication needs its complete original Stack scope")
    selected = sorted(units.values(), key=lambda u: (int(u["deployOrder"]), u["name"]))
    if args.action == "status":
        return selected
    if args.action != "sync":
        raise Blocked("pending publication requires explicit sync before Model loading")
    if run.get("pendingObserved") and not set(
        run["pendingObserved"]["evidence"]
    ) <= set(args.sync_stack):
        raise Blocked("sync must select the saved publication Stack scope")
    run["states"] = {n: {"status": "NOT_STARTED"} for n in units}
    run["states"].update(
        {n: copy.deepcopy(op["state"]) for n, op in record["operations"].items()}
    )
    backend.run_context, backend.states, backend.units = run, run["states"], selected
    backend.retained_records = [r for r in records if r is not record]
    backend.expected_digests = run["inputDigests"]
    backend.guard = operation_journal.RecoveryGuard(backend, task)
    backend.save = operation_journal.JournalSave(journal, backend)
    checkpoint_receipts(backend)
    operation_reset.check_fences(journal, backend.target, args.stack, backend)
    backend.guard()
    if run.get("pendingObserved"):
        observed_resume.reconcile(
            backend.root, run, backend.target, backend.environment, backend.directory
        )
    elif run.get("pendingGeneration"):
        generation_resume.recover_publications(backend)
    backend.save()
    return None


def checkpoint_receipts(backend: SimpleNamespace) -> dict:
    """Only current Task lifecycle metadata can supply integrated completion proof."""
    _, _, _, state = wt.load(backend.root, backend.root.name)
    if (
        wt.task_worktree(backend.root, state) != backend.root
        or state["task_file"] != backend.run_context["taskFile"]
    ):
        raise Blocked("step operations require the current managed Deploy worktree")
    receipts = state.get("deployCheckpoints", {})
    for unit in backend.units:
        name = unit["name"]
        if name not in receipts:
            continue
        entry = receipts[name]
        if (
            entry["unit"] != unit
            or entry["taskDigest"] != backend.run_context["taskDigest"]
            or backend.input_digest(unit, fresh=True) != entry["inputDigest"]
            or (
                not wt.ancestor(backend.root, entry["commit"], state["branch"])
                if backend.phase == "deploy"
                else not wt.ancestor(backend.root, entry["commit"], state["base"])
            )
        ):
            raise Blocked("integrated checkpoint inputs/base changed: " + name)
        backend.states[name] = {
            "status": "SUCCESS",
            "observedSynced": True,
            "checkpointed": True,
            "stackId": entry["stackId"],
            "stackStatus": entry["stackStatus"],
            "observedCoverage": entry.get("coverage", {}),
            "observedServices": entry.get("services", []),
        }
        backend.run_context["inputDigests"][name] = entry["inputDigest"]
    pending = backend.run_context.get("checkpointPending")
    if pending and set(pending["stacks"]) <= receipts.keys():
        # A crash after receipt save and before Journal acknowledgement needs no new commit.
        if contracts.validation_snapshot(backend.root) != pending.get("after"):
            raise Blocked("checkpoint acknowledgement candidate changed")
        backend.run_context.pop("checkpointPending")
    if backend.phase == "deploy":
        backend.run_context["gitPublication"] = git_publication.describe(
            backend.root, state, worktree.read_progress(backend.root, state)
        )
    return receipts


def adopt_verified_repair(backend: SimpleNamespace, task: TaskSnapshot) -> None:
    """Only the existing exact child attribution permits a new attempt after failure."""
    run = backend.run_context
    changed = {
        p
        for p, digest in run["consumedInputs"].items()
        if backend.file_digest(backend.root / p, fresh=True) != digest
    }
    if not changed:
        return
    if (
        run.get("pendingObserved")
        or run.get("pendingGeneration")
        or run.get("checkpointPending")
    ):
        raise Blocked("settle publication/checkpoint before accepting repaired inputs")
    _, _, _, lifecycle = wt.load(backend.root, backend.root.name)
    repair = lifecycle.get("iacRepair", {})
    if (
        repair.get("commit") != wt.output(backend.root, "rev-parse", "HEAD")
        or contracts.accepted_changes(backend.root, task.text, changed) != changed
        or any(
            repair["changes"][p]["before"] != run["consumedInputs"][p] for p in changed
        )
    ):
        raise Blocked("changed Deploy inputs have no exact verified repair attribution")
    restarted = set()
    for unit in backend.units:
        name = unit["name"]
        if not changed & {
            p.relative_to(backend.root).as_posix()
            for p in backend.deployment_input_paths([unit])
        }:
            continue
        state = backend.states[name]
        operation = operation_journal.operation_record(backend, unit)
        if state["status"] != "FAILED" or operation_journal.aws_unfinished(
            backend.target, name, operation, backend.aws
        ):
            raise Blocked(
                "repaired Stack original operation is not confirmed failed: " + name
            )
        backend.states[name] = {"status": "NOT_STARTED", "checkpointRequired": True}
        run["inputDigests"].pop(name, None)
        restarted.add(name)
    if not restarted:
        raise Blocked("repaired inputs do not belong to a failed Stack")
    for p in changed:
        run["consumedInputs"][p] = backend.file_digest(backend.root / p, fresh=True)
        run["inputIdentities"][p] = file_revision(backend.root / p)
    run.pop("currentFailure", None)


def verify_success(backend: SimpleNamespace, units: list[StackUnit]) -> None:
    for unit in units:
        name = unit["name"]
        state = backend.states[name]
        if state.get("status") != "SUCCESS":
            raise Blocked("sync requires confirmed AWS success: " + name)
        backend.load_inputs(unit)
        operation = operation_journal.operation_record(backend, unit)
        operation_journal.validate_operation(backend.target, name, operation)
        if state.get("noChangeEvidence"):
            if operation_journal.aws_unfinished(
                backend.target, name, operation, backend.aws
            ):
                raise Blocked("No Change success is unconfirmed: " + name)
        elif backend.poll(unit, state) != state.get("stackStatus"):
            raise Blocked("original execution success is unconfirmed: " + name)
        change_sets.verify_outputs(
            backend.aws, unit, state, state.get("expectedOutputs", {})
        )


def sync(backend: SimpleNamespace, names: list[str]) -> None:
    context = backend.run_context
    units = [u for u in backend.units if u["name"] in names]
    if not names or len(names) != len(set(names)) or len(units) != len(names):
        raise Blocked("sync needs distinct --sync-stack names within Deployment scope")
    if any(backend.states[n].get("checkpointed") for n in names):
        raise Blocked("requested Stack is already checkpointed")
    backend.guard()
    verify_success(backend, units)
    pending = context.get("checkpointPending")
    if pending is None:
        if wt.changed_paths(backend.root):
            raise Blocked("sync requires clean inputs or its own retained publication")
        pending = {
            "stacks": [],
            "before": contracts.validation_snapshot(backend.root),
            "after": None,
        }
        context["checkpointPending"] = pending
    elif pending.get("after") is not None:
        if contracts.validation_snapshot(backend.root) != pending["after"]:
            raise Blocked("synchronized candidate changed before next sync")
    pending["stacks"] = sorted(set(pending["stacks"]) | set(names))
    pending["after"] = None
    backend.save()
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
    unsynced = [u for u in units if not backend.states[u["name"]].get("observedSynced")]
    if unsynced or context.get("pendingObserved"):
        observed.sync_successful(backend, units, backend.states)
    if context.get("pendingGeneration"):
        generation_resume.run(backend)
    pending["after"] = contracts.validation_snapshot(backend.root)
    backend.guard()
    backend.save()


def describe(backend: SimpleNamespace) -> dict:
    context = backend.run_context
    states = backend.states
    pending = context.get("checkpointPending")
    publication = copy.deepcopy(context.get("gitPublication"))
    if publication is not None:
        publication["checkpointRequired"] = pending["stacks"] if pending else []
    complete = (
        generation_resume.complete(context)
        and all(s.get("checkpointed") for s in states.values())
        and not pending
    )
    publication_pending = (
        getattr(backend, "phase", None) == "deploy"
        and context.get("gitPublication", {}).get("status") != "SUCCESS"
    )
    uncertain = any(
        s.get("pollReadFailures") or s.get("schedulerError") for s in states.values()
    )
    failed = uncertain or any(
        s["status"] == "FAILED" and s.get("cleanupStatus") != "DELETE_INTENT"
        for s in states.values()
    )
    running = any(
        s["status"] == "RUNNING" or s.get("cleanupStatus") == "DELETE_INTENT"
        for s in states.values()
    )
    approval = any(
        s.get("failure", {}).get("classification") == "APPROVAL"
        for s in states.values()
    )
    can_advance = (
        running
        and not uncertain
        or not failed
        and not approval
        and any(
            s["status"] in {"NOT_STARTED", "BLOCKED", "READY", "CHANGESET_CREATING"}
            for s in states.values()
        )
    )
    return {
        "result": "PUBLICATION_PENDING"
        if complete and publication_pending
        else "COMPLETE"
        if complete
        else "STOPPED"
        if failed
        else "PENDING",
        "gitPublication": publication,
        "repairFailure": context.get("currentFailure"),
        "states": {
            name: {
                "aws": state["status"],
                "stackId": state.get("stackId"),
                "stackStatus": state.get("stackStatus"),
                "changeSetId": state.get("changeSetId"),
                "changes": state.get("changes", []),
                "observed": "COMPLETE" if state.get("observedSynced") else "PENDING",
                "coverage": state.get("observedCoverage", {}),
                "generation": "COMPLETE"
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
        "nextActions": ([] if complete or not can_advance else [{"action": "advance"}])
        + [
            {"action": "sync", "stacks": [name]}
            for name, state in states.items()
            if state["status"] == "SUCCESS" and not state.get("observedSynced")
        ]
        + (
            [{"action": "sync", "stacks": pending["stacks"]}]
            if pending and context.get("pendingGeneration")
            else []
        )
        + (
            [{"action": "checkpoint", "stacks": pending["stacks"]}]
            if pending
            and pending.get("after") is not None
            and not context.get("pendingGeneration")
            and not context.get("pendingObserved")
            and not context.get("generationError")
            else []
        )
        + context.get("gitPublication", {}).get("nextActions", []),
    }


def run(
    args: Namespace,
    root: Path,
    timing: Timing,
    backend_type: Callable[..., SimpleNamespace],
    load_units: Callable[[Path, str, str, list[str]], tuple[int, list[StackUnit]]],
) -> int:
    backend = None
    journal = None
    ready = False
    try:
        task = task_snapshot(root, live=True)
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
        )
        if args.action == "status":
            worktree.require(root, task)
        else:
            worktree.bind(root, task, selected, args.environment, args.stack)
        target = context.check_deploy_context(
            root, args.environment, args.aws_account_id, args.alias, args.profile
        )
        if target["iacEngine"] != "cloudformation":
            raise Blocked("step operations require CloudFormation")
        directory = args.alias or args.aws_account_id
        journal = operation_journal.location(target)
        with (
            ExitStack() as resources,
            selected_task(root, task.name),
            redirect_stdout(sys.stderr),
        ):
            resources.enter_context(operation_journal.locked(journal))
            backend = backend_type(
                root,
                args.environment,
                directory,
                target,
                args.profile,
                args.approve_change_set,
            )
            backend.phase, backend.timing = phase, timing
            backend.check_reset_fences = partial(
                operation_reset.check_fences, journal, target, args.stack, backend
            )
            retained_units = reconcile_before_model_load(backend, journal, task, args)
            limit, units = (
                (1, retained_units)
                if retained_units is not None
                else load_units(root, args.environment, directory, args.stack)
            )
            if args.sequential:
                limit = 1
            backend.units = units
            backend.run_context = run_context.new_context(
                root, task, target, args.environment, directory, units, backend
            )
            backend.run_context["stepwise"] = True
            backend.run_context["stepUnits"] = copy.deepcopy(units)
            backend.states = backend.run_context["states"]
            restore(backend, journal, task)
            run = backend.run_context
            if args.action == "advance":
                adopt_verified_repair(backend, task)
            receipts = checkpoint_receipts(backend)
            backend.save = operation_journal.JournalSave(journal, backend)
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
            if args.action != "status":
                operation_reset.check_fences(journal, target, args.stack, backend)
                operation_journal.publication_conflicts(backend, task)
                backend.guard()
            ready = True
            if args.action == "advance":
                if run.get("pendingObserved") or any(
                    r["generated"]["outputs"] is not None
                    for r in run.get("pendingGeneration", {}).values()
                ):
                    raise Blocked(
                        "settle pending publication with explicit sync before new AWS work"
                    )
                temporary.reclaim(journal, root, target)
                backend.workdir = temporary.create(
                    journal, root, task, target, args.stack
                )
                for unit in units:
                    if unit["name"] not in receipts:
                        backend.states[unit["name"]]["checkpointRequired"] = True
                if set(args.approve_change_set) - {
                    s.get("changeSetId") for s in backend.states.values()
                }:
                    raise Blocked(
                        "approval must name this scope's current unfinished ChangeSet"
                    )
                models = RunModels(root, run)
                resources.enter_context(model_session(models))
                for unit in units:
                    state = backend.states[unit["name"]]
                    if state["status"] == "READY":
                        state["status"] = "CHANGESET_CREATING"
                    if state["status"] in {"RUNNING", "CHANGESET_CREATING"}:
                        backend.load_inputs(unit)
                run_group(
                    units,
                    limit,
                    backend.states,
                    backend,
                    backend.save,
                    single_step=True,
                )
                if "- Runtime recovery: `allowed`" in task.text.splitlines():
                    for unit in units:
                        state = backend.states[unit["name"]]
                        if state["status"] == "FAILED":
                            backend.repair(unit, state)
                            state["checkpointRequired"] = True
                if any(
                    s["status"] in {"FAILED", "BLOCKED"}
                    and not s.get("bootstrap")
                    and s.get("cleanupStatus") != "DELETE_INTENT"
                    for s in backend.states.values()
                ) and not run.get("currentFailure"):
                    run["currentFailure"] = handoff.record_failure(backend)
                backend.save()
            elif args.action in {"sync", "checkpoint"}:
                models = RunModels(root, run)
                resources.enter_context(model_session(models))
                backend.after_observed = models.apply_observed
                if args.action == "sync":
                    sync(backend, args.sync_stack)
                else:
                    pending = run.get("checkpointPending")
                    if pending:
                        verify_success(
                            backend, [u for u in units if u["name"] in args.sync_stack]
                        )
                    wt.deploy_stack_checkpoint(backend, args.sync_stack)
                    if phase == "deploy":
                        git_publication.sync(backend)
                    backend.save()
            result = describe(backend)
        print(json.dumps(result, indent=2))
        return 2 if result["result"] == "STOPPED" and args.action == "advance" else 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    **(
                        {
                            "states": describe(backend)["states"],
                            "pendingGeneration": describe(backend)["pendingGeneration"],
                        }
                        if ready
                        else {}
                    ),
                    "result": "STOPPED",
                    **cli_guidance.stopped("STEP", error),
                },
                indent=2,
            )
        )
        return 2
    finally:
        if backend is not None and backend.workdir is not None:
            try:
                temporary.reclaim(journal, root, backend.target)
            except (OSError, ValueError, KeyError, TypeError):
                pass
