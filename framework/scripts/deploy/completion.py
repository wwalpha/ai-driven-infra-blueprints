"""Deploy attempt and observation completion decisions."""

import task_contract_core as tasks
from contracts.deploy import DEPLOY_SUCCESS
from contracts.validation import VALIDATION_PASS
from utils.cloudformation.inputs import Blocked
from utils.git_changes import collect_working_paths
from utils.project_targets import load_target_directory
from utils.script_loader import module

from deploy import contracts, current_state, progress


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
        if item["status"] in {
            "READY",
            "NOT_STARTED",
            "BLOCKED",
            "CHANGESET_CREATING",
        } and not item.get("clientToken"):
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
        if (
            not item.get("observedSynced")
            or not item.get("currentStack")
            or any(
                coverage.get("status") == "UNCONFIRMED"
                for coverage in item.get("observedCoverage", {}).values()
            )
        ):
            blockers.append({"stack": name, "reason": "current observation needs sync"})
        if current_category(item) in {"RUNNING", "UNKNOWN"}:
            blockers.append(
                {"stack": name, "reason": "current AWS is running or unreadable"}
            )
    if not attempts_finished(states, context.get("deployResult")) or any(
        progress.unresolved_request(item) for item in states.values()
    ):
        blockers.append(
            {"reason": "attempts or explicit unexecuted reasons are incomplete"}
        )
    return blockers


def current_category(item):
    return current_state.category(item.get("currentStack", {}))


def local_ready(context):
    return (
        not final_blockers(context)
        and not context.get("syncPending")
        and context.get("snapshotValidation") == VALIDATION_PASS
    )


def require_local(root, task):
    if task.status != "running":
        raise Blocked("only a running Deploy Task can complete")
    targets = {
        (environment, directory) for environment, directory, _ in task.scope or ()
    }
    if len(targets) != 1:
        raise Blocked("Deploy completion requires one explicit Target")
    environment, directory = next(iter(targets))
    target = load_target_directory(root, environment, directory)
    if target["iacEngine"] == "terraform":
        return
    saved = progress.read_task(root, task)
    if (
        saved is None
        or saved["identity"]["target"] != target
        or saved["identity"]["environment"] != environment
        or saved["runContext"].get("directory") != directory
        or saved["runContext"].get("repository") != str(root)
        or not local_ready(saved["runContext"])
    ):
        raise Blocked(
            "Deploy completion requires settled requests and validated local sync"
        )


def verify_observation_delta(root, baseline="HEAD"):
    changed = set(collect_working_paths(root).all_paths)
    if baseline != "HEAD":
        changed.update(
            contracts.paths(
                root, "diff", "--no-renames", "--name-only", "-z", baseline, "HEAD"
            )
        )
    if "project.json" in changed or any(p.startswith("infra/") for p in changed):
        raise ValueError("Deploy cannot change project configuration or IaC")
    sources = {root / p for p in changed if p.startswith("model/")}
    observed = module("model/observed.py", "model.observed")
    observed.verify_observed_outputs(
        {
            p: contracts.subprocess_bytes(
                root, baseline, p.relative_to(root).as_posix()
            )
            for p in sources
        },
        {p: p.read_text(encoding="utf-8") for p in sources},
    )


def validate_local(root, task, *, deploy=True):
    validator_type = module("validation/runner.py", "validation.runner").Validator
    manifest = contracts.validation_snapshot(root)
    head = contracts.output(root, "rev-parse", "HEAD")
    tasks.verify_snapshot(task)
    if deploy:
        verify_observation_delta(root, head)
    validator = validator_type(
        root, set(task.scope), cache=False, model_validation="change"
    )
    validator.run()
    if validator.report():
        validator.display_report()
        raise Blocked("local Deploy Model/View or Task Acceptance validation failed")
    verify_local_inputs(root, task, (head, manifest))
    return head, manifest


def verify_local_inputs(root, task, validated):
    head, manifest = validated
    tasks.verify_snapshot(task)
    if head != contracts.output(
        root, "rev-parse", "HEAD"
    ) or manifest != contracts.validation_snapshot(root):
        raise Blocked("local Deploy inputs changed during validation")


def finish_local(root, task, validated):
    require_local(root, task)
    verify_local_inputs(root, task, validated)
    tasks.atomic_files(
        {task.path: tasks.set_status(task.text, "completed")}, staging_directory=root
    )
    tasks.invalidate_task_reads(root)
