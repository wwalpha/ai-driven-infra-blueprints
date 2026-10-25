"""External Deploy sessions, immutable guards, target locks and observed barriers."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from argparse import Namespace
from collections.abc import Callable, Iterable, Sequence
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

from model.dependency_index import revision as file_revision
from model.sources import model_session
from task_contract_core import (
    TaskSnapshot,
    paths_in,
    task_reads,
    task_snapshot,
)
from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint
from utils.type_contracts import JsonValue as JsonValue

import deploy.context as _imports_deploy_context
import deploy.contracts as _imports_deploy_contracts
import deploy.observed as _dependency_deploy_observed
from deploy import handoff, observed_resume
from deploy import resume as repair_resume
from deploy.model_cache import SessionModels
from deploy.scheduler import run_group
from deploy.secret_bootstrap import BOOTSTRAP_STAGES
from deploy.timing import Timing
from deploy.typing import (
    Save,
    SchedulerBackend,
    Session,
    Sleep,
    StackUnit,
    States,
    Target,
)


def save_session(path: Path, session: Session) -> None:
    handoff.save(path, session)


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


def require_session_format(session: Session) -> None:
    expected = {
        "version": 5,
        "modelFormat": 2,
        "snapshotVersion": 2,
        "referenceMeaningVersion": 1,
    }
    if any(
        type(session.get(key)) is not int or session[key] != value
        for key, value in expected.items()
    ):
        raise Blocked(
            "controller session format is incompatible; v5 lazy input identities and consumed manifests are required; retain the original session/controller without automatic migration"
        )


def _callback_run_session_sync_once(backend, save, session, units, /):
    unsynced = [
        u
        for u in units
        if session["states"][u["name"]]["status"] == "SUCCESS"
        and not session["states"][u["name"]].get("observedSynced")
    ]
    if not unsynced:
        return True
    started = time.perf_counter()
    try:
        if hasattr(backend, "guard"):
            backend.guard()
        outputs = sync_successful(backend, unsynced, session["states"])
        if hasattr(backend, "after_observed"):
            backend.after_observed(outputs or {})
        session.pop("pendingObserved", None)
        session.pop("observedError", None)
        session.pop("observedRecoveryError", None)
        return True
    except Exception as error:
        for unit in unsynced:
            session["states"][unit["name"]].pop("observedSynced", None)
        session.setdefault("observedError", str(error))
        session["observedRecoveryError"] = str(error)
        failure = {
            "stage": session.get("pendingObserved", {}).get("stage", "PLANNING"),
            "cause": str(error),
        }
        failures = session.setdefault("observedFailures", [])
        if not failures or failures[-1] != failure:
            failures.append(failure)
        return False
    finally:
        session["metrics"]["observedSyncSeconds"] += time.perf_counter() - started
        save()


# Peers may have completed while an earlier persisted plan was blocked.
def _callback_run_session_sync_completed(session, sync_once, /):
    # Peers may have completed while an earlier persisted plan was blocked.
    while True:
        pending = session.get("pendingObserved")
        if not sync_once():
            return False
        if not pending:
            return True


def run_session(
    units: Sequence[StackUnit],
    limit: int,
    session: Session,
    backend: SchedulerBackend,
    save: Save,
    pause_after_group: bool = False,
    sleep: Sleep = time.sleep,
) -> str:
    """Observed synchronization is an idempotent, persisted barrier between groups."""
    sync_once = _bind_framework_callback(
        _callback_run_session_sync_once, backend, save, session, units
    )

    sync_completed = _bind_framework_callback(
        _callback_run_session_sync_completed, session, sync_once
    )

    backend.sync_completed = sync_completed
    while True:
        if not sync_completed():
            # A restart may contain both unsynced successes and still-running peers.
            run_group(
                units,
                limit,
                session["states"],
                backend,
                save,
                sleep=sleep,
                drain_only=True,
            )
            return "STOPPED"
        result = run_group(units, limit, session["states"], backend, save, sleep=sleep)
        if result == "GROUP_COMPLETE":
            completed = sorted(
                {
                    int(u["deployOrder"])
                    for u in units
                    if all(
                        session["states"][v["name"]]["status"] == "SUCCESS"
                        for v in units
                        if v["deployOrder"] == u["deployOrder"]
                    )
                }
            )
            session["metrics"]["deployOrderCount"] = len(completed)
            # Sync even the final group before returning COMPLETE.
            if pause_after_group:
                if not sync_completed():
                    return "STOPPED"
                return (
                    "COMPLETE"
                    if all(s["status"] == "SUCCESS" for s in session["states"].values())
                    else "GROUP_COMPLETE"
                )
            continue
        if result == "STOPPED":
            # Do not abandon successful peers' observed values after another stack fails.
            synced = sync_completed()
            handoff.record_stop(session, units)
            save()
            failed = [
                u for u in units if session["states"][u["name"]]["status"] == "FAILED"
            ]
            if (
                synced
                and failed
                and not any(s.get("schedulerError") for s in session["states"].values())
                and hasattr(backend, "repair")
            ):
                repaired = all(
                    [backend.repair(u, session["states"][u["name"]]) for u in failed]
                )
                save()
                if repaired:
                    continue
        return result


def current_manifest(root, session, backend):
    return {
        relative: backend.file_digest(root / relative)
        for relative in session["infraManifest"]
    }


def _callback_claim_inputs(root, session, backend, save, /, unit):
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
        if file_revision(path) != session["inputIdentities"][relative]:
            raise Blocked("deployment inputs changed before first use: " + relative)
    digest = backend.input_digest(unit, fresh=True)
    expected = session["unitDigests"].get(name)
    if expected is not None and digest != expected:
        raise Blocked("prepared/executed unit IaC changed: " + name)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if file_revision(path) != session["inputIdentities"][relative]:
            raise Blocked("deployment inputs changed while claiming: " + relative)
        session["infraManifest"][relative] = backend.file_digest(path)
    session["unitDigests"][name] = digest
    save()


def _callback_run_save(
    invocation_started, metrics, previous_duration, session, state_path, /
):
    metrics["totalControllerSeconds"] = (
        previous_duration + time.perf_counter() - invocation_started
    )
    metrics["awsPollCount"] = sum(
        s.get("pollApiCount", 0) for s in session["states"].values()
    )
    save_session(state_path, session)


def _callback_run_guard(
    args, backend, context, root, selected, session, target, /
) -> TaskSnapshot:
    with task_reads(root, live=True):
        snapshot = task_snapshot(root)
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
        if snapshot.task_digest != session["taskDigest"]:
            raise Blocked("task contract changed before mutation")
        if current_manifest(root, session, backend) != session["infraManifest"]:
            raise Blocked("unauthorized IaC change outside accepted input revision")
        return snapshot


# Runtime bootstrap does not change IaC or grant a validation/hash exception.
def _callback_run_refresh_validation(backend, unit_digests, /, unit):
    # Runtime bootstrap does not change IaC or grant a validation/hash exception.
    backend.load_inputs(unit)
    if backend.input_digest(unit, fresh=True) != unit_digests[unit["name"]]:
        raise Blocked("runtime recovery changed immutable IaC inputs")


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
    state_path = args.state.resolve()
    lock_path = None
    lock = None
    session = None
    persist = None
    handoff_lock = None
    model_scope = None
    invocation_started = time.perf_counter()
    try:
        if state_path.is_relative_to(root):
            raise Blocked(
                "deployment session must be outside repository; never store AWS status in Git"
            )
        context = _imports_deploy_context
        selected = context.load_target(
            root, args.environment, args.aws_account_id, args.alias
        )
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
            context_started = time.perf_counter()
            with timing.phase("authenticationContext"):
                target = context.check_deploy_context(
                    root,
                    args.environment,
                    args.aws_account_id,
                    args.alias,
                    args.profile,
                )
            context_seconds = time.perf_counter() - context_started
            if target["iacEngine"] != "cloudformation":
                raise Blocked("controller requires CloudFormation target")
            lock_target = {
                key: value for key, value in target.items() if key != "awsProfile"
            }
            lock_path = Path(tempfile.gettempdir()) / (
                "blueprint-cfn-"
                + fingerprint([args.environment, lock_target])
                + ".lock"
            )
            try:
                lock = lock_path.open("x")
            except FileExistsError as error:
                raise Blocked(
                    f"controller session already active or interrupted; verify no controller is running before removing {lock_path}"
                ) from error
            candidate_lock = handoff.locked(state_path)
            candidate_lock.__enter__()
            handoff_lock = candidate_lock
            directory = args.alias or args.aws_account_id
            if args.resume:
                session = json.loads(state_path.read_text(encoding="utf-8"))
                handoff.restore(root, state_path, session)
                require_session_format(session)
                if session.get("pendingObserved") and not getattr(
                    args, "observe_only", False
                ):
                    # Recovery precedes Stack metadata and every read-only Model snapshot.
                    sha = _imports_deploy_contracts.sha
                    try:
                        if any(
                            sha(root / path) != digest
                            for path, digest in session["infraManifest"].items()
                        ):
                            raise Blocked(
                                "IaC changed during pending observed publication"
                            )
                        observed_resume.reconcile(
                            root, session, target, args.environment, directory
                        )
                    except Exception as error:
                        session["observedRecoveryError"] = str(error)
                        save_session(state_path, session)
                        raise
                    save_session(state_path, session)
            if session is None:
                session = {"modelInputManifest": {}}
            models = SessionModels(root, session)
            model_scope = model_session(models)
            model_scope.__enter__()
            limit, units = load_units(root, args.environment, directory, args.stack)
            if args.sequential:
                limit = 1
            backend = backend_type(
                root,
                args.environment,
                directory,
                target,
                args.profile,
                args.approve_change_set,
            )
            backend.timing = timing
            backend.phase = phase
            digest = fingerprint(
                [str(root), target, args.environment, phase, limit, units]
            )
            backend.workdir = state_path.with_name(state_path.name + ".files").resolve()
            if backend.workdir.is_relative_to(root):
                raise Blocked("deployment files directory must be outside repository")
            units_by_name = {u["name"]: u for u in units}
            unit_digests = {
                name: backend.input_digest(units_by_name[name], fresh=True)
                for name in session.get("unitDigests", {})
            }
            current_infra = (
                current_manifest(root, session, backend) if args.resume else {}
            )
            identities = {
                p.relative_to(root).as_posix(): file_revision(p)
                for p in backend.deployment_input_paths(units)
            }
            if args.resume:
                if getattr(args, "observe_only", False):
                    if (
                        session["inputDigest"] != digest
                        or session.get("repository") != str(root)
                        or session.get("taskFile") != initial_task.name
                    ):
                        raise Blocked(
                            "observation session target/Task identity changed"
                        )
                    return repair_resume.observe_only(
                        backend, units, limit, state_path, session
                    )
                require_session_format(session)
                if session.get("workflow", {}).get("status") == "CLOSED":
                    raise Blocked(
                        "closed workflow cannot resume AWS execution; unresolved history still owns overlapping scope"
                    )
                if getattr(args, "repair_result", None):
                    repair_resume.accept(
                        root,
                        args.repair_result,
                        session,
                        backend,
                        units,
                        unit_digests,
                        current_infra,
                    )
                elif session.get("pendingRequest"):
                    raise Blocked(
                        "pending external repair requires --resume --repair-result"
                    )
                previous_infra = session["infraManifest"]
                changed_infra = {
                    path
                    for path in previous_infra.keys() | current_infra.keys()
                    if previous_infra.get(path) != current_infra.get(path)
                }
                update_handoff = {
                    path.relative_to(root).as_posix()
                    for unit in units
                    if phase == "update"
                    and session["states"][unit["name"]]["status"] == "NOT_STARTED"
                    for path in backend.deployment_input_paths([unit])
                }
                if changed_infra - update_handoff:
                    raise Blocked(
                        "unauthorized IaC change outside recorded repair; cannot resume"
                    )
                session["infraManifest"] = current_infra
                require_session_format(session)
                for relative, expected in session["modelInputManifest"].items():
                    path = root / relative
                    actual = (
                        hashlib.sha256(path.read_bytes()).hexdigest()
                        if path.is_file()
                        else None
                    )
                    if actual != expected:
                        raise Blocked(
                            "consumed Model input changed; cannot resume: " + relative
                        )
                prior_identities = session["inputIdentities"]
                writable = update_handoff if phase == "update" else set()
                if any(
                    prior_identities.get(path) != current
                    for path, current in identities.items()
                    if path not in writable
                    and path not in session["infraManifest"]
                    and not getattr(args, "repair_result", None)
                ):
                    raise Blocked("deployment input identity changed; cannot resume")
                session["inputIdentities"] = identities
                if session["inputDigest"] != digest:
                    raise Blocked(
                        "target, design or scope changed; cannot resume this session"
                    )
                for name, state in session["states"].items():
                    if (
                        (phase == "deploy" or state["status"] != "NOT_STARTED")
                        and name in session["unitDigests"]
                        and session["unitDigests"][name] != unit_digests[name]
                    ):
                        raise Blocked(
                            f"prepared/executed unit IaC changed; cannot resume: {name}"
                        )
                session["unitDigests"] = unit_digests
                if session["profile"] != backend.profile:
                    raise Blocked("AWS profile changed; cannot resume")
            else:
                if state_path.exists() or args.approve_change_set:
                    raise Blocked(
                        "new session requires unused state path and no approvals"
                    )
                session.update(
                    {
                        "inputDigest": digest,
                        "unitDigests": unit_digests,
                        "workflow": handoff.new_workflow(),
                        "inputRevision": 0,
                        "states": {
                            unit["name"]: {"status": "NOT_STARTED"} for unit in units
                        },
                    }
                )
                session.update(
                    version=5,
                    modelFormat=2,
                    snapshotVersion=2,
                    referenceMeaningVersion=1,
                    profile=backend.profile,
                )
                session["repository"] = str(root)
                session["taskFile"] = initial_task.name
                session["taskDigest"] = initial_task.task_digest
                session["infraManifest"] = current_infra
                session["inputIdentities"] = identities
                session["unitInputPaths"] = {
                    u["name"]: [
                        p.relative_to(root).as_posix()
                        for p in backend.deployment_input_paths([u])
                    ]
                    for u in units
                }
                session["environment"] = args.environment
                session["directory"] = directory
                session["target"] = target
                session["logicalTarget"] = [
                    args.environment,
                    directory,
                    target["awsAccountId"],
                    target["awsRegion"],
                ]
                budget_lines = re.findall(
                    r"^- Repair cycle budget: `([0-9]+)`$", initial_task.text, re.M
                )
                if budget_lines and (
                    len(budget_lines) != 1 or int(budget_lines[0]) <= 0
                ):
                    raise Blocked("invalid repair cycle budget")
                session["repairBudget"] = int(budget_lines[0]) if budget_lines else 20
                session["validationScope"] = sorted(
                    paths_in(initial_task.text, "## Validation scope")
                )
                session["effectiveDigests"] = {}
                session["declaredConsumers"] = {}
            handoff.bind(root, state_path, session)
            backend.session = session
            contract = initial_task.text
            if (
                "- External IaC repair: `allowed`" in contract.splitlines()
                and f"- Deploy repair session: `{state_path}`"
                not in contract.splitlines()
            ):
                raise Blocked("external repair session path must match task contract")
            metrics = session.setdefault("metrics", {})
            for key in (
                "controllerInvocationCount",
                "deployOrderCount",
                "observedSyncSeconds",
                "inputLoadSeconds",
                "totalControllerSeconds",
                "contextCheckSeconds",
            ):
                metrics.setdefault(key, 0)
            metrics["controllerInvocationCount"] += 1
            metrics["contextCheckSeconds"] += context_seconds
            for change_id in args.approve_change_set:
                matches = [
                    state
                    for state in session["states"].values()
                    if state.get("changeSetId") == change_id
                ]
                if (
                    len(matches) != 1
                    or matches[0]["status"] != "BLOCKED"
                    or not matches[0].get("changeDigest")
                ):
                    raise Blocked(
                        "approve only the saved blocked change set after human confirmation"
                    )
            backend.states = session["states"]
            backend.expected_digests = session["unitDigests"]
            previous_duration = metrics["totalControllerSeconds"]
            save = _bind_framework_callback(
                _callback_run_save,
                invocation_started,
                metrics,
                previous_duration,
                session,
                state_path,
            )
            backend.save = save
            persist = save
            backend.claim_inputs = _bind_framework_callback(
                _callback_claim_inputs, root, session, backend, save
            )
            backend.guard = _bind_framework_callback(
                _callback_run_guard,
                args,
                backend,
                context,
                root,
                selected,
                session,
                target,
            )
            backend.after_observed = models.apply_observed
            refresh_validation = _bind_framework_callback(
                _callback_run_refresh_validation, backend, unit_digests
            )
            backend.refresh_validation = refresh_validation
            backend.units = units
        save()
        for unit in units:
            state = session["states"][unit["name"]]
            repair_resume.recover(backend, unit, state)
            if (
                state.get("repairs")
                and state["repairs"][-1].get("classification") == "RUNTIME_BOOTSTRAP"
                and state["repairs"][-1].get("stage") in BOOTSTRAP_STAGES
            ):
                if not backend.repair(unit, state):
                    session["result"] = "STOPPED"
                    save()
                    return 2
        session["result"] = run_session(
            units, limit, session, backend, save, args.pause_after_group
        )
        handoff.record_outcomes(session)
        if session.get("repairOutcomeUnverified"):
            session["result"] = "STOPPED"
        save()
        print(json.dumps(session, indent=2))
        return 2 if session["result"] == "STOPPED" else 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ImportError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"CloudFormation controller: BLOCKED: {error}", file=sys.stderr)
        return 2
    finally:
        try:
            if persist is not None:
                persist()
        finally:
            try:
                if handoff_lock is not None:
                    handoff_lock.__exit__(None, None, None)
            finally:
                if model_scope is not None:
                    model_scope.__exit__(None, None, None)
                if lock is not None:
                    lock.close()
                    lock_path.unlink(missing_ok=True)


def sync_successful(
    backend: SimpleNamespace, units: Sequence[StackUnit], states: States
) -> dict[Path, str] | None:
    return _dependency_deploy_observed.sync_successful(backend, units, states)
