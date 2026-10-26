"""Ordered group control through an injected backend, without AWS transport."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial as _bind_framework_callback
from typing import TypeVar

from utils.cloudformation.inputs import Blocked
from utils.type_contracts import JsonValue as JsonValue

from deploy import failures
from deploy.typing import Save, SchedulerBackend, Sleep, StackState, StackUnit, States

ReadResult = TypeVar("ReadResult")

SUCCESS = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
FAILED = {
    "CREATE_FAILED",
    "ROLLBACK_COMPLETE",
    "ROLLBACK_FAILED",
    "DELETE_COMPLETE",
    "DELETE_FAILED",
    "UPDATE_FAILED",
    "UPDATE_ROLLBACK_COMPLETE",
    "UPDATE_ROLLBACK_FAILED",
    "IMPORT_ROLLBACK_COMPLETE",
    "IMPORT_ROLLBACK_FAILED",
}


def _callback_read_parallel_read(method, states, /, unit):
    state = copy.deepcopy(states[unit["name"]])
    try:
        return unit, state, method(unit, state), None
    except Exception as error:
        return unit, state, None, error


def read_parallel(
    units: Sequence[StackUnit],
    states: States,
    method: Callable[[StackUnit, StackState], ReadResult],
    limit: int,
) -> list[tuple[StackUnit, StackState, ReadResult | None, Exception | None]]:
    """Workers own copies only; all decisions and persistence remain on the controller."""
    read = _bind_framework_callback(_callback_read_parallel_read, method, states)
    if len(units) <= 1:
        return [read(unit) for unit in units]
    with ThreadPoolExecutor(max_workers=limit) as pool:
        return list(pool.map(read, units))


def run_group(
    units: Sequence[StackUnit],
    limit: int,
    states: States,
    backend: SchedulerBackend,
    save: Save = lambda: None,
    sleep: Sleep = time.sleep,
    drain_only: bool = False,
) -> str:
    """Single event loop owns the queue; AWS executions overlap, Python decisions do not."""
    pending = [unit for unit in units if states[unit["name"]]["status"] != "SUCCESS"]
    if not pending:
        return (
            "STOPPED"
            if any(s.get("schedulerError") for s in states.values())
            else "COMPLETE"
        )
    order = min(int(unit["deployOrder"]) for unit in pending)
    group = [unit for unit in pending if int(unit["deployOrder"]) == order]
    active = [u for u in units if states[u["name"]]["status"] == "RUNNING"]
    violation = None
    if len(active) > limit:
        violation = f"RUNNING stacks exceed concurrency limit {limit}: " + ", ".join(
            u["name"] for u in active
        )
    elif any(int(u["deployOrder"]) != order for u in active):
        violation = "RUNNING stacks cross the active DeployOrder barrier"
    if violation:
        for unit in active:
            states[unit["name"]].setdefault("schedulerError", violation)
        save()
    stopped = drain_only or any(
        state["status"] == "FAILED" or state.get("schedulerError")
        for state in states.values()
    )
    while True:
        # Poll every running stack before reusing any freed slot.
        active = [
            unit
            for unit in (units if stopped else group)
            if states[unit["name"]]["status"] == "RUNNING"
        ]
        for unit, snapshot, status, error in read_parallel(
            active, states, backend.poll, limit
        ):
            state = states[unit["name"]]
            state.update(snapshot)
            try:
                if error:
                    raise error
                if status == "RECHECK":
                    state.clear()
                    state["status"] = "NOT_STARTED"
                    save()
                    continue
                state["stackStatus"] = status
                if (
                    state.get("failureDetected")
                    or "ROLLBACK" in status
                    or status.endswith("_FAILED")
                ):
                    stopped = True
                if status in SUCCESS:
                    state["status"] = "SUCCESS"
                elif status in FAILED:
                    state["status"] = "FAILED"
                    stopped = True
                elif not status.endswith("_IN_PROGRESS"):
                    raise Blocked(f"unrecognized stack status: {status}")
                state.pop("pollError", None)
                state.pop("pollReadFailures", None)
                if state["status"] in {"SUCCESS", "FAILED"}:
                    state["executionSeconds"] = time.time() - state.get(
                        "executionStarted", time.time()
                    )
            except Exception as error:
                # Lost read access is not proof of terminal failure. Drain/retry only.
                state["pollError"] = str(error)
                state["pollReadFailures"] = state.get("pollReadFailures", 0) + 1
                failures.exception(state, error, "POLL")
                stopped = True
            save()
        if any(s.get("pollReadFailures", 0) >= 3 for s in states.values()):
            return "STOPPED"
        if any(
            states[u["name"]]["status"] == "SUCCESS"
            and not states[u["name"]].get("observedSynced")
            for u in group
        ) and hasattr(backend, "sync_completed"):
            if not backend.sync_completed():
                stopped = True
        running = sum(states[unit["name"]]["status"] == "RUNNING" for unit in group)
        # Start multiple change sets without waiting for one to become CREATE_COMPLETE.
        # Preparation is bounded too; do not speculate across DeployOrder barriers.
        preparing = sum(
            states[u["name"]]["status"] in {"CHANGESET_CREATING", "READY"}
            for u in group
        )
        if not stopped:
            pending = [
                u
                for u in group
                if states[u["name"]]["status"] in {"NOT_STARTED", "BLOCKED"}
            ]
            for unit in pending[: max(0, limit - running - preparing)]:
                state = states[unit["name"]]
                try:
                    state.setdefault("preparationId", uuid.uuid4().hex)
                    started = time.perf_counter()
                    try:
                        if hasattr(backend, "claim_inputs"):
                            backend.claim_inputs(unit)
                        if hasattr(backend, "load_inputs"):
                            backend.load_inputs(unit)
                    finally:
                        metrics = getattr(backend, "run_context", {}).get("metrics", {})
                        metrics["inputLoadSeconds"] = (
                            metrics.get("inputLoadSeconds", 0)
                            + time.perf_counter()
                            - started
                        )
                    if hasattr(backend, "observed_readiness"):
                        backend.observed_readiness(unit)
                    if hasattr(backend, "prepare_delivery_group"):
                        backend.prepare_delivery_group([unit], states)
                    begin = getattr(backend, "begin_prepare", backend.prepare)
                    state["status"] = begin(unit, state)
                except Exception as error:
                    failures.exception(
                        state,
                        error,
                        "INPUT_DECODE"
                        if getattr(error, "deploy_input_kind", None) == "DECODE"
                        else "PREPARATION",
                    )
                    state["status"] = "BLOCKED"
                    state["reason"] = str(error)
                    stopped = True
                if state["status"] == "BLOCKED":
                    stopped = True
                save()
                if stopped:
                    break
        if not stopped:
            creating = [
                u for u in group if states[u["name"]]["status"] == "CHANGESET_CREATING"
            ]
            for unit, snapshot, change_set, error in read_parallel(
                creating,
                states,
                backend.describe_change_set if creating else backend.poll,
                limit,
            ):
                state = states[unit["name"]]
                state.update(snapshot)
                try:
                    if error:
                        raise error
                    # Workers fetch only. Classification and approval decisions stay here.
                    state["status"] = backend.review_prepared(unit, state, change_set)
                except Exception as error:
                    failures.exception(state, error, "CHANGESET_REVIEW")
                    state["status"], state["reason"] = "BLOCKED", str(error)
                if state["status"] == "BLOCKED":
                    stopped = True
                save()
        if not stopped:
            ready = [u for u in group if states[u["name"]]["status"] == "READY"]
            for unit in ready[: max(0, limit - running)]:
                state = states[unit["name"]]
                try:
                    # Persist execution intent before AWS mutation, including interruptions.
                    state["status"] = "RUNNING"
                    state["clientToken"] = state.get("clientToken", uuid.uuid4().hex)
                    state["executionStarted"] = time.time()
                    save()
                    backend.execute(unit, state)
                except Exception as error:
                    failures.exception(state, error, "EXECUTE")
                    state["reason"] = str(error)
                    stopped = True
                save()
                if stopped:
                    break
        running = sum(
            states[u["name"]]["status"] == "RUNNING"
            for u in (units if stopped else group)
        )
        if not running:
            if stopped:
                return "STOPPED"
            if all(states[unit["name"]]["status"] == "SUCCESS" for unit in group):
                return "GROUP_COMPLETE"
        sleep(5)
