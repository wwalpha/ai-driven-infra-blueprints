"""Independent Deploy invocations with lazy, immutable current-worktree inputs."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import time
from argparse import Namespace
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

from model.dependency_index import revision as file_revision
from model.sources import model_session
from task_contract_core import TaskSnapshot, task_reads, task_snapshot
from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint
from utils.type_contracts import JsonValue as JsonValue

import deploy.context as context
import deploy.observed as _dependency_deploy_observed
from deploy import (
    cli_guidance,
    generation_resume,
    git_publication,
    handoff,
    operation_journal,
    operation_reset,
    temporary,
    worktree,
)
from deploy.model_cache import RunModels
from deploy.scheduler import run_group
from deploy.timing import Timing
from deploy.typing import (
    DeployRunContext,
    Save,
    SchedulerBackend,
    Sleep,
    StackUnit,
    States,
    Target,
)


def active_scope(
    root: Path,
    requested: Iterable[str],
    environment: str,
    account: str,
    alias: str | None = None,
    *,
    snapshot: TaskSnapshot | None = None,
) -> str:
    snapshot = snapshot or task_snapshot(root)
    text = snapshot.text
    if snapshot.status != "running":
        raise Blocked("completed task cannot deploy")
    for line in (
        "- Task type: `infrastructure`",
        "- AWS API execution: `allowed`",
        "- Deploy/apply: `allowed`",
        f"- Target environment: `{environment}`",
        f"- Target AWS account: `{account}`",
    ):
        if line not in text.splitlines():
            raise Blocked(f"active task must explicitly contain {line}")
    if not any(
        f"- Infrastructure phase: `{phase}`" in text.splitlines()
        for phase in ("deploy", "update")
    ):
        raise Blocked("controller requires infrastructure deploy/update phase")
    if alias and f"- Target alias: `{alias}`" not in text.splitlines():
        raise Blocked("requested alias must exactly match active task Target alias")
    scopes = [
        line for line in text.splitlines() if line.startswith("- Deployment scope:")
    ]
    if len(scopes) != 1 or set(re.findall(r"`([^`]+)`", scopes[0])) != set(requested):
        raise Blocked(
            "requested StackName scope must exactly match active task Deployment scope"
        )
    return (
        "update"
        if "- Infrastructure phase: `update`" in text.splitlines()
        else "deploy"
    )


def _callback_run_deploy_sync_once(backend, save, run_context, units, /):
    if getattr(backend, "sync_failed", False):
        return False
    unsynced = [
        u
        for u in units
        if run_context["states"][u["name"]]["status"] == "SUCCESS"
        and not run_context["states"][u["name"]].get("observedSynced")
    ]
    if (
        not unsynced
        and not run_context.get("pendingGeneration")
        and not run_context.get("generationError")
    ):
        return True
    started = time.perf_counter()
    stage = "OBSERVED" if unsynced else "GENERATION"
    backend._generation_finalized = False
    try:
        if unsynced and any(
            record["generated"]["outputs"] is not None
            for record in run_context.get("pendingGeneration", {}).values()
        ):
            stage = "GENERATION"
        if hasattr(backend, "guard"):
            backend.guard()
        if unsynced and stage == "GENERATION":
            # Finish an interrupted candidate before another Model transaction changes inputs.
            generation_resume.run(backend)
        if unsynced:
            stage = "OBSERVED"
            sync_successful(backend, unsynced, run_context["states"])
            run_context.pop("pendingObserved", None)
            run_context.pop("observedError", None)
            run_context.pop("observedRecoveryError", None)
        if run_context.get("pendingGeneration") or run_context.get("generationError"):
            stage = "GENERATION"
            generation_resume.run(backend)
        return True
    except Exception as error:
        backend.sync_failed = True
        run_context[
            "generationFailure" if stage == "GENERATION" else "observedFailure"
        ] = cli_guidance.safe_error(error)
        if stage == "GENERATION":
            if backend._generation_finalized and not run_context.get("generationError"):
                run_context["generationReportError"] = str(error)
            else:
                run_context["generationError"] = str(error)
            return False
        run_context.setdefault("observedError", str(error))
        run_context["observedRecoveryError"] = str(error)
        failure = {
            "stage": run_context.get("pendingObserved", {}).get("stage", "PLANNING"),
            "cause": str(error),
        }
        failures = run_context.setdefault("observedFailures", [])
        if not failures or failures[-1] != failure:
            failures.append(failure)
        return False
    finally:
        run_context["metrics"]["observedSyncSeconds"] += time.perf_counter() - started
        save()
        git_publication.sync(backend)


# Peers may have completed while an earlier persisted plan was blocked.
def _callback_run_deploy_sync_completed(run_context, sync_once, /):
    # Peers may have completed while an earlier persisted plan was blocked.
    while True:
        pending = run_context.get("pendingObserved")
        if not sync_once():
            return False
        if not pending:
            return True


def run_deploy(
    units: Sequence[StackUnit],
    limit: int,
    run_context: DeployRunContext,
    backend: SchedulerBackend,
    save: Save,
    pause_after_group: bool = False,
    sleep: Sleep = time.sleep,
) -> str:
    """Observed synchronization is an idempotent, persisted barrier between groups."""
    backend.sync_failed = False
    sync_once = _bind_framework_callback(
        _callback_run_deploy_sync_once, backend, save, run_context, units
    )

    sync_completed = _bind_framework_callback(
        _callback_run_deploy_sync_completed, run_context, sync_once
    )

    backend.sync_completed = sync_completed
    while True:
        if not sync_completed():
            # A restart may contain both unsynced successes and still-running peers.
            run_group(
                units,
                limit,
                run_context["states"],
                backend,
                save,
                sleep=sleep,
                drain_only=True,
            )
            return "STOPPED"
        result = run_group(
            units, limit, run_context["states"], backend, save, sleep=sleep
        )
        if result == "GROUP_COMPLETE":
            completed = sorted(
                {
                    int(u["deployOrder"])
                    for u in units
                    if all(
                        run_context["states"][v["name"]]["status"] == "SUCCESS"
                        for v in units
                        if v["deployOrder"] == u["deployOrder"]
                    )
                }
            )
            run_context["metrics"]["deployOrderCount"] = len(completed)
            # Sync even the final group before returning COMPLETE.
            if pause_after_group:
                if not sync_completed():
                    return "STOPPED"
                if generation_resume.complete(run_context):
                    return "COMPLETE"
                if all(
                    s["status"] == "SUCCESS" for s in run_context["states"].values()
                ):
                    run_context["generationError"] = generation_resume.describe(
                        run_context
                    )
                    save()
                    return "STOPPED"
                return "GROUP_COMPLETE"
            continue
        if result == "STOPPED":
            # Do not abandon successful peers' observed values after another stack fails.
            synced = sync_completed()
            save()
            failed = [
                u
                for u in units
                if run_context["states"][u["name"]]["status"] == "FAILED"
            ]
            if (
                synced
                and failed
                and not any(
                    s.get("schedulerError") for s in run_context["states"].values()
                )
                and hasattr(backend, "repair")
            ):
                repaired = all(
                    [
                        backend.repair(u, run_context["states"][u["name"]])
                        for u in failed
                    ]
                )
                save()
                if repaired:
                    continue
        if result == "COMPLETE" and not generation_resume.complete(run_context):
            run_context["generationError"] = generation_resume.describe(run_context)
            save()
            return "STOPPED"
        return result


def current_manifest(
    root: Path, run_context: DeployRunContext, backend: SimpleNamespace
) -> dict[str, str]:
    return {
        relative: backend.file_digest(root / relative, fresh=True)
        for relative in run_context["consumedInputs"]
    }


def _callback_claim_inputs(root, run_context, backend, save, /, unit):
    name = unit["name"]
    paths = backend.deployment_input_paths([unit])
    if getattr(backend, "phase", None) == "deploy" and paths:
        revision = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--",
                *[p.relative_to(root).as_posix() for p in paths],
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if revision.returncode or revision.stdout.strip():
            raise Blocked("deploy inputs must be committed before use: " + name)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if file_revision(path) != run_context["inputIdentities"][relative]:
            raise Blocked("deployment inputs changed before first use: " + relative)
    digest = backend.input_digest(unit, fresh=True)
    expected = run_context["inputDigests"].get(name)
    if expected is not None and digest != expected:
        raise Blocked("prepared/executed unit IaC changed: " + name)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if file_revision(path) != run_context["inputIdentities"][relative]:
            raise Blocked("deployment inputs changed while claiming: " + relative)
        run_context["consumedInputs"][relative] = backend.file_digest(path)
    run_context["inputDigests"][name] = digest
    save()


def _callback_run_guard(
    args, backend, context, root, selected, run_context, target, /
) -> TaskSnapshot:
    with task_reads(root, live=True):
        snapshot = task_snapshot(root)
        worktree.require(root, snapshot)
        active_scope(
            root,
            args.stack,
            args.environment,
            selected["awsAccountId"],
            args.alias,
            snapshot=snapshot,
        )
        if (
            context.load_target(root, args.environment, args.aws_account_id, args.alias)
            != target
        ):
            raise Blocked("project target changed before mutation")
        if snapshot.task_digest != run_context["taskDigest"]:
            raise Blocked("task contract changed before mutation")
        if (
            current_manifest(root, run_context, backend)
            != run_context["consumedInputs"]
        ):
            raise Blocked("unauthorized IaC change outside accepted input revision")
        return snapshot


# Runtime bootstrap does not change IaC or grant a validation/hash exception.
def _callback_run_refresh_validation(backend, unit_digests, /, unit):
    # Runtime bootstrap does not change IaC or grant a validation/hash exception.
    backend.load_inputs(unit)
    if backend.input_digest(unit, fresh=True) != unit_digests[unit["name"]]:
        raise Blocked("runtime recovery changed immutable IaC inputs")


def new_context(
    root: Path,
    task: TaskSnapshot,
    target: Target,
    environment: str,
    directory: str,
    units: Sequence[StackUnit],
    backend: SimpleNamespace,
) -> DeployRunContext:
    context = DeployRunContext(
        repository=str(root),
        taskFile=task.name,
        taskDigest=task.task_digest,
        target=target,
        environment=environment,
        directory=directory,
        inputDigest=fingerprint([str(root), target, environment, units]),
        states={u["name"]: {"status": "NOT_STARTED"} for u in units},
        inputDigests={},
        consumedInputs={},
        inputIdentities={
            p.relative_to(root).as_posix(): file_revision(p)
            for p in backend.deployment_input_paths(units)
        },
        metrics={"observedSyncSeconds": 0, "inputLoadSeconds": 0},
    )
    pending = getattr(backend, "pending_publication", {}).get("pendingGeneration", {})
    if pending:
        context["pendingGeneration"] = copy.deepcopy(pending)
        for record in context["pendingGeneration"].values():
            if record["generated"]["outputs"] is not None:
                raise Blocked("settle unfinished generated candidates before a new run")
            record["identity"]["inputDigest"] = context["inputDigest"]
    return context


def _save(backend, journal):
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    operation_journal.save(journal, backend)


def run(
    args: Namespace,
    root: Path,
    timing: Timing,
    script_directory: Path,
    backend_type: Callable[
        [Path, str, str, Target, str | None, Iterable[str]], SimpleNamespace
    ],
    load_units: Callable[[Path, str, str, list[str]], tuple[int, list[StackUnit]]],
) -> int:
    resources = ExitStack()
    backend = None
    journal = None
    stage = "TARGET_SELECTION"
    try:
        selected = context.load_target(
            root, args.environment, args.aws_account_id, args.alias
        )
        stage = "TASK_AUTHORITY"
        initial_task = task_snapshot(root, live=True)
        with task_reads(root, snapshot=initial_task):
            phase = active_scope(
                root,
                args.stack,
                args.environment,
                selected["awsAccountId"],
                args.alias,
                snapshot=initial_task,
            )
            if args.pause_after_group and phase != "update":
                raise Blocked("--pause-after-group requires the explicit update phase")
            worktree.bind(root, initial_task, selected, args.environment, args.stack)
            stage = "AUTHENTICATION"
            with timing.phase("authenticationContext"):
                target = context.check_deploy_context(
                    root,
                    args.environment,
                    args.aws_account_id,
                    args.alias,
                    args.profile,
                )
            if target["iacEngine"] != "cloudformation":
                raise Blocked("controller requires CloudFormation target")
            stage = "RECOVERY"
            directory = args.alias or args.aws_account_id
            journal = operation_journal.location(target)
            resources.enter_context(operation_journal.locked(journal))
            backend = backend_type(
                root,
                args.environment,
                directory,
                target,
                args.profile,
                args.approve_change_set,
            )
            backend.timing, backend.phase = timing, phase
            if not args.recover_operations:
                backend.check_reset_fences = _bind_framework_callback(
                    operation_reset.check_fences, journal, target, args.stack, backend
                )
                operation_reset.check_fences(journal, target, args.stack, backend)
            temporary.reclaim(journal, root, target)
            backend.workdir = temporary.create(
                journal, root, initial_task, target, args.stack
            )
            # Only unfinished operations are read. Old Session files and registries are not inputs.
            operation_journal.recover(backend, journal, initial_task, args.stack)
            operation_journal.publication_conflicts(backend, initial_task)
            if args.recover_operations and not backend.pending_publication:
                publication = (
                    git_publication.retry(root, initial_task)
                    if phase == "deploy"
                    else None
                )
                progress = (
                    worktree.read_progress(root, worktree.require(root, initial_task))
                    if phase == "deploy"
                    else None
                )
                recovered_context = {
                    "states": progress["states"] if progress else {},
                    "gitPublication": publication,
                }
                print(
                    json.dumps(
                        {
                            "result": "RECOVERED",
                            **cli_guidance.controller_result(
                                "RECOVERED", recovered_context, args, root
                            ),
                        },
                        indent=2,
                    )
                )
                return 0
            run_context = {"modelInputs": {}, **backend.pending_publication}
            models = getattr(backend, "recovered_models", None)
            if models is None:
                models = RunModels(root, run_context)
            else:
                run_context["modelInputs"].update(models.run_context["modelInputs"])
                models.run_context = run_context
            resources.enter_context(model_session(models))
            stage = "INPUTS"
            limit, units = load_units(root, args.environment, directory, args.stack)
            if args.sequential:
                limit = 1
            current = new_context(
                root,
                initial_task,
                target,
                args.environment,
                directory,
                units,
                backend,
            )
            run_context.update(current)
            backend.run_context = run_context
            backend.states, backend.units = run_context["states"], units
            backend.expected_digests = run_context["inputDigests"]
            backend.save = _bind_framework_callback(_save, backend, journal)
            backend.claim_inputs = _bind_framework_callback(
                _callback_claim_inputs, root, run_context, backend, backend.save
            )
            backend.guard = _bind_framework_callback(
                _callback_run_guard,
                args,
                backend,
                context,
                root,
                selected,
                run_context,
                target,
            )
            backend.after_observed = models.apply_observed
            backend.refresh_validation = _bind_framework_callback(
                _callback_run_refresh_validation, backend, run_context["inputDigests"]
            )
            operation_journal.adopt_recovered(backend)
            worktree.adopt_successes(backend)
            if args.recover_operations:
                if run_context.get("pendingGeneration"):
                    generation_resume.run(backend)
                backend.save()
                print(
                    json.dumps(
                        {
                            "result": "STOPPED"
                            if run_context.get("pendingGeneration")
                            else "RECOVERED",
                            **cli_guidance.controller_result(
                                "RECOVERED", run_context, args, root
                            ),
                        },
                        indent=2,
                    )
                )
                return 2 if run_context.get("pendingGeneration") else 0
            operation_journal.adopt_prepared(backend, journal, args.approve_change_set)
        stage = "CONTROLLER"
        result = run_deploy(
            units, limit, run_context, backend, backend.save, args.pause_after_group
        )
        backend.save()
        if result == "COMPLETE" and run_context.get("gitPublication", {}).get(
            "status"
        ) in {"PENDING", "CONFLICT"}:
            result = "PUBLICATION_PENDING"
        failure = handoff.record_failure(backend) if result == "STOPPED" else None
        print(
            json.dumps(
                {
                    "result": result,
                    **cli_guidance.controller_result(
                        result,
                        run_context,
                        args,
                        root,
                        repair_failure=failure,
                        task_text=initial_task.text,
                    ),
                    "repairFailure": failure,
                    "states": {
                        name: {
                            key: value
                            for key, value in state.items()
                            if key != "approvedChangeDigest"
                        }
                        for name, state in backend.states.items()
                    },
                    "metrics": run_context["metrics"],
                },
                indent=2,
            )
        )
        return 2 if result == "STOPPED" else 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ImportError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"result": "STOPPED", **cli_guidance.stopped(stage, error)}, indent=2
            )
        )
        print(f"CloudFormation controller: BLOCKED: {error}", file=sys.stderr)
        return 2
    finally:
        try:
            if backend is not None and backend.workdir is not None:
                temporary.reclaim(journal, root, target)
        except (Blocked, OSError, ValueError, KeyError, TypeError) as error:
            print(f"Deploy temporary files retained: {error}", file=sys.stderr)
        finally:
            resources.close()


def sync_successful(
    backend: SimpleNamespace, units: Sequence[StackUnit], states: States
) -> dict[Path, str] | None:
    return _dependency_deploy_observed.sync_successful(backend, units, states)
