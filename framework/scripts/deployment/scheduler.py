"""Ordered group control through an injected backend, without AWS transport."""
import copy
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from cloudformation_inputs import Blocked

SUCCESS = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
FAILED = {"CREATE_FAILED", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "DELETE_COMPLETE", "DELETE_FAILED",
          "UPDATE_FAILED", "UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED",
          "IMPORT_ROLLBACK_COMPLETE", "IMPORT_ROLLBACK_FAILED"}


def read_parallel(units, states, method, limit):
    """Workers own copies only; all decisions and persistence remain on the controller."""
    def read(unit):
        state = copy.deepcopy(states[unit["name"]])
        try:
            return unit, state, method(unit, state), None
        except Exception as error:
            return unit, state, None, error
    if len(units) <= 1:
        return [read(unit) for unit in units]
    with ThreadPoolExecutor(max_workers=limit) as pool:
        return list(pool.map(read, units))


def run_group(units, limit, states, backend, save=lambda: None, sleep=time.sleep, drain_only=False):
    """Single event loop owns the queue; AWS executions overlap, Python decisions do not."""
    pending = [unit for unit in units if states[unit["name"]]["status"] != "SUCCESS"]
    if not pending:
        return "COMPLETE"
    order = min(int(unit["deployOrder"]) for unit in pending)
    group = [unit for unit in pending if int(unit["deployOrder"]) == order]
    stopped = drain_only or any(state["status"] == "FAILED" for state in states.values())
    if not stopped and hasattr(backend, 'prepare_delivery_group'):
        try:
            backend.prepare_delivery_group(group, states)
        except Exception as error:
            candidate = next((u for u in group if states[u['name']]['status'] not in {'RUNNING', 'SUCCESS'}), None)
            if candidate:
                states[candidate['name']].update(status='BLOCKED', reason=str(error))
            stopped = True
            save()
    while True:
        # Poll every running stack before reusing any freed slot.
        active = [unit for unit in group if states[unit["name"]]["status"] == "RUNNING"]
        for unit, snapshot, status, error in read_parallel(active, states, backend.poll, limit):
            state = states[unit["name"]]
            state.update(snapshot)
            try:
                if error:
                    raise error
                state["stackStatus"] = status
                if state.get("failureDetected") or "ROLLBACK" in status or status.endswith("_FAILED"):
                    stopped = True
                if status in SUCCESS:
                    state["status"] = "SUCCESS"
                elif status in FAILED:
                    state["status"] = "FAILED"
                    stopped = True
                elif not status.endswith("_IN_PROGRESS"):
                    raise Blocked(f"unrecognized stack status: {status}")
                state.pop("pollError", None)
                if state["status"] in {"SUCCESS", "FAILED"}:
                    state["executionSeconds"] = time.time() - state.get("executionStarted", time.time())
            except Exception as error:
                # Lost read access is not proof of terminal failure. Drain/retry only.
                state["pollError"] = str(error)
                stopped = True
            save()
        running = sum(states[unit["name"]]["status"] == "RUNNING" for unit in group)
        assert running <= limit
        # Start multiple change sets without waiting for one to become CREATE_COMPLETE.
        # Preparation is bounded too; do not speculate across DeployOrder barriers.
        preparing = sum(states[u["name"]]["status"] == "CHANGESET_CREATING" for u in group)
        if not stopped:
            pending = [u for u in group if states[u["name"]]["status"] in {"NOT_STARTED", "BLOCKED"}]
            for unit in pending[:max(0, limit - running - preparing)]:
                state = states[unit["name"]]
                try:
                    begin = getattr(backend, "begin_prepare", backend.prepare)
                    state["status"] = begin(unit, state)
                except Exception as error:
                    state["status"] = "BLOCKED"
                    state["reason"] = str(error)
                    stopped = True
                if state["status"] == "BLOCKED":
                    stopped = True
                save()
                if stopped:
                    break
        if not stopped:
            creating = [u for u in group if states[u["name"]]["status"] == "CHANGESET_CREATING"]
            for unit, snapshot, change_set, error in read_parallel(creating, states, backend.describe_change_set if creating else backend.poll, limit):
                state = states[unit["name"]]
                state.update(snapshot)
                try:
                    if error:
                        raise error
                    # Workers fetch only. Classification and approval decisions stay here.
                    state["status"] = backend.review_prepared(unit, state, change_set)
                except Exception as error:
                    state["status"], state["reason"] = "BLOCKED", str(error)
                if state["status"] == "BLOCKED":
                    stopped = True
                save()
        if not stopped:
            ready = [u for u in group if states[u["name"]]["status"] == "READY"]
            for unit in ready[:max(0, limit - running)]:
                state = states[unit["name"]]
                try:
                    # Persist execution intent before AWS mutation, including interruptions.
                    state["status"] = "RUNNING"
                    state["clientToken"] = state.get("clientToken", uuid.uuid4().hex)
                    state["executionStarted"] = time.time()
                    save()
                    backend.execute(unit, state)
                except Exception as error:
                    state["reason"] = str(error)
                    stopped = True
                save()
                if stopped:
                    break
        running = sum(states[u["name"]]["status"] == "RUNNING" for u in group)
        if not running:
            if stopped:
                return "STOPPED"
            if all(states[unit["name"]]["status"] == "SUCCESS" for unit in group):
                return "GROUP_COMPLETE"
        sleep(5)


