"""Deploy attempt and observation completion decisions."""

import task_contract_core as tasks
from contracts.deploy import DEPLOY_SUCCESS
from contracts.validation import VALIDATION_PASS

from deploy import current_state


def attempts_finished(states, result):
    return bool(states) and all(
        saved.get("status") in {DEPLOY_SUCCESS, "FAILED", "SETTLED"}
        or saved.get("status") in {"READY", "NOT_STARTED"}
        and saved.get("unexecutedReason")
        in {
            "PREVIOUS_DEPLOY_ORDER_FAILED",
            "CURRENT_EXECUTION_CONSTRAINT",
            "DEPLOY_ENDED_WITHOUT_EXECUTION",
        }
        for saved in states.values()
    )


def end_unexecuted(context):
    units = {unit["name"]: unit for unit in context["stepUnits"]}
    failed_orders = [
        int(units[name]["deployOrder"])
        for name, item in context["states"].items()
        if item["status"] == "FAILED" and name in units
    ]
    for name, item in context["states"].items():
        if (
            item["status"] in {"READY", "NOT_STARTED", "BLOCKED", "CHANGESET_CREATING"}
            and not item.get("clientToken")
        ):
            order = int(units[name]["deployOrder"])
            item.update(
                status="NOT_STARTED",
                unexecutedReason="PREVIOUS_DEPLOY_ORDER_FAILED"
                if any(value < order for value in failed_orders)
                else "CURRENT_EXECUTION_CONSTRAINT"
                if item.get("failure") or item.get("schedulerError")
                else "DEPLOY_ENDED_WITHOUT_EXECUTION",
            )


def final_blockers(context):
    """Candidate prerequisites do not depend on Git publication or Task status."""
    blockers = []
    for key in ("pendingObserved", "pendingGeneration", "generationError"):
        if context.get(key):
            blockers.append({"reason": key})
    states = context["states"]
    for name, item in states.items():
        for record in item.get("deferredConsumers", []):
            if record.get("approved") and not record.get("referenceSynced"):
                blockers.append(
                    {
                        "stack": record["stack"],
                        "consumer": record["consumer"],
                        "reason": "approved reference synchronization needs sync",
                    }
                )
        if not item.get("observedSynced") or not item.get("currentStack"):
            blockers.append({"stack": name, "reason": "current observation needs sync"})
        if current_category(item) in {"RUNNING", "UNKNOWN"}:
            blockers.append(
                {"stack": name, "reason": "current AWS is running or unreadable"}
            )
    if not attempts_finished(states, context.get("deployResult")):
        blockers.append(
            {"reason": "attempts or explicit unexecuted reasons are incomplete"}
        )
    return blockers


def current_category(item):
    return current_state.category(item.get("currentStack", {}))




def candidate_incomplete(task, state, saved, candidate_tree):
    final = state.get("deployPublication", {}).get("finalCandidate")
    return (
        saved is None
        or final_blockers(saved["runContext"])
        or saved["runContext"].get("checkpointPending")
        or saved["runContext"].get("snapshotValidation") != VALIDATION_PASS
        or not final
        or final.get("taskAfter") != task.text
        or final.get("source") != state["tip"]
        or final.get("tree") != candidate_tree()
        or final.get("taskAfter")
        != tasks.set_status(final.get("taskBefore", ""), "completed")
    )
