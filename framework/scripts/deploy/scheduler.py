"""Ordered group control through an injected backend, without AWS transport."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial as _bind_framework_callback
from typing import TypeVar

from utils.cloudformation.environment import EnvironmentValuePending
from utils.type_contracts import JsonValue as JsonValue

from deploy import current_request, current_state, failures
from deploy.current_state import FAILED as FAILED
from deploy.current_state import SUCCESS as SUCCESS
from deploy.typing import Save, SchedulerBackend, Sleep, StackState, StackUnit, States

ReadResult = TypeVar("ReadResult")


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
    single_step: bool = False,
) -> str:
    """Single event loop owns the queue; AWS executions overlap, Python decisions do not."""
    for state in states.values():
        state.pop("schedulerError", None)
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
        state.get("schedulerError") for state in states.values()
    )
    input_blocked = set()
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
            accepted = False
            try:
                if error:
                    raise error
                if status == "RECHECK":
                    request = state.get("settledRequest")
                    state.clear()
                    state["status"] = "NOT_STARTED"
                    save()
                    if request:
                        current_request.release(backend, request)
                    continue
                current_state.record_attempt(state, status)
                accepted = True
                if status == "UNCONFIRMED":
                    input_blocked.add(unit["name"])
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
            save()
            request = state.pop("settledRequest", None)
            if request and accepted:
                current_request.release(backend, request)
        if any(s.get("pollReadFailures", 0) >= 3 for s in states.values()):
            return "STOPPED"
        if (
            any(
                states[u["name"]]["status"] == "SUCCESS"
                and not states[u["name"]].get("observedSynced")
                for u in group
            )
            and not single_step
            and hasattr(backend, "sync_completed")
        ):
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
                and u["name"] not in input_blocked
                and not states[u["name"]].get("requestError")
                and states[u["name"]].get("attemptResult") != "UNKNOWN"
            ]
            pending.sort(key=lambda u: states[u["name"]]["status"] == "BLOCKED")
            for unit in pending[: max(0, limit - running - preparing)]:
                state = states[unit["name"]]
                try:
                    state.pop("unexecutedReason", None)
                    state.setdefault("preparationId", uuid.uuid4().hex)
                    measured = getattr(backend, "_timed_input_loads", set())
                    started = (
                        None
                        if unit["name"] in measured
                        or unit["name"] in getattr(backend, "loaded_inputs", {})
                        else time.perf_counter()
                    )
                    backend._timed_input_loads = measured
                    try:
                        if hasattr(backend, "claim_inputs"):
                            backend.claim_inputs(unit)
                        if hasattr(backend, "load_inputs"):
                            backend.load_inputs(unit)
                        measured.add(unit["name"])
                    finally:
                        if started is not None:
                            metrics = getattr(backend, "run_context", {}).setdefault(
                                "metrics", {}
                            )
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
                    input_blocked.add(unit["name"])
                if state["status"] == "BLOCKED":
                    input_blocked.add(unit["name"])
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
                    input_blocked.add(unit["name"])
                save()
        if not stopped:
            ready = [u for u in group if states[u["name"]]["status"] == "READY"]
            for unit in ready[: max(0, limit - running)]:
                state = states[unit["name"]]
                try:
                    state.pop("unexecutedReason", None)
                    # Persist execution intent before AWS mutation, including interruptions.
                    state["status"] = "RUNNING"
                    state["clientToken"] = state.get("clientToken", uuid.uuid4().hex)
                    state["executionStarted"] = time.time()
                    save()
                    backend.execute(unit, state)
                except Exception as error:
                    failures.exception(state, error, "EXECUTE")
                    state["reason"] = str(error)
                    if isinstance(error, EnvironmentValuePending):
                        state["status"] = "BLOCKED"
                        input_blocked.add(unit["name"])
                    elif state["status"] == "BLOCKED":
                        input_blocked.add(unit["name"])
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
            if all(
                states[unit["name"]]["status"] in {"SUCCESS", "FAILED", "SETTLED"}
                or unit["name"] in input_blocked
                for unit in group
            ):
                return (
                    "GROUP_COMPLETE"
                    if not input_blocked
                    and all(states[u["name"]]["status"] == "SUCCESS" for u in group)
                    else "STOPPED"
                )
        if single_step:
            return "STOPPED" if stopped else "ACTIVE"
        sleep(5)
