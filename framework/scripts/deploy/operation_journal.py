"""Only unfinished AWS operations and atomic publication ownership survive an invocation."""

import copy
import json
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from model.sources import model_session, session_reads
from task_contract_core import task_reads, task_snapshot
from utils.cloudformation.format import decode
from utils.cloudformation.inputs import Blocked
from utils.file_operations import atomic_replace_file
from utils.json_format import fingerprint
from utils.sealed_evidence import read_sealed, sealed

from deploy import change_sets, generation_resume, observed, observed_resume
from deploy import context as deploy_context
from deploy.model_cache import RunModels
from deploy.recovery import cleanup_unexecuted, require_authorized
from deploy.scheduler import FAILED, SUCCESS

# No approvals, failure archives, repair histories, workflow bindings or completed records.
OPERATION_FIELDS = {
    "status",
    "stackId",
    "stackStatus",
    "changeSetId",
    "changeDigest",
    "changes",
    "clientToken",
    "executionStarted",
    "executionEvidence",
    "operationType",
    "absentBeforeCreate",
    "operationStackId",
    "externalOperation",
    "observedSynced",
    "cleanupStatus",
    "cleanupStackId",
    "failureTemplateSafety",
    "bootstrap",
    "preparationId",
    "changeSetStarted",
    "changeSetCreateSeconds",
    "expectedOutputs",
    "preExecutionRecovery",
    "delivery",
}
PUBLICATION_FIELDS = {
    "repository",
    "taskFile",
    "taskDigest",
    "inputDigest",
    "environment",
    "directory",
    "target",
    "pendingObserved",
    "pendingGeneration",
    "modelInputs",
    "inputDigests",
    "generationProducers",
}


def location(target):
    identity = [
        target.get("awsExecutionAccountId", target["awsAccountId"]),
        target["awsRegion"],
    ]
    return (
        Path(tempfile.gettempdir()).resolve()
        / ("blueprint-cfn-operations-" + fingerprint(identity))
        / "journal.json"
    )


def safe_path(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise Blocked("operation journal path must be absolute and not redirected")
    return path


@contextmanager
def locked(path):
    path = safe_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise Blocked(
            f"controller active or interrupted; verify lock ownership before maintenance: {lock}"
        ) from error
    try:
        yield
    finally:
        handle.close()
        lock.unlink()


def read(path):
    path = safe_path(path)
    if not path.exists():
        return None
    envelope = json.loads(path.read_text(encoding="utf-8"))
    try:
        owner = Path(envelope["payload"]["publication"]["repository"])
    except (KeyError, TypeError) as error:
        raise Blocked("invalid unfinished-operation ownership") from error
    record = read_sealed(owner, path)
    if not isinstance(record, dict) or set(record) != {
        "target",
        "operations",
        "publication",
    }:
        raise Blocked("invalid unfinished-operation journal; retain for investigation")
    if not isinstance(record["operations"], dict):
        raise Blocked("invalid unfinished operations")
    producers = record["publication"].get("generationProducers", {})
    if not isinstance(producers, dict):
        raise Blocked("invalid pending generation Producer evidence")
    for operation in [*record["operations"].values(), *producers.values()]:
        if (
            set(operation) != {"unit", "inputDigest", "state"}
            or set(operation["state"]) - OPERATION_FIELDS
        ):
            raise Blocked("invalid unfinished operation fields")
    if any(
        op["state"].get("status") != "SUCCESS" or not op["state"].get("observedSynced")
        for op in producers.values()
    ):
        raise Blocked("pending generation Producer has no Observed completion evidence")
    if set(record["publication"]) - PUBLICATION_FIELDS:
        raise Blocked("invalid publication ownership fields")
    return record


def unfinished(state):
    return bool(
        state.get("bootstrap")
        or state.get("cleanupStatus") == "DELETE_INTENT"
        or state.get("status") == "RUNNING"
        or state.get("status") == "SUCCESS"
        and not state.get("observedSynced")
        or state.get("changeSetId")
        and not state.get("executionEvidence")
        and state.get("status")
        in {"NOT_STARTED", "CHANGESET_CREATING", "READY", "BLOCKED"}
    )


def operation_record(backend, unit, fields=OPERATION_FIELDS):
    return {
        "unit": copy.deepcopy(unit),
        "inputDigest": backend.run_context["inputDigests"].get(unit["name"]),
        "state": {
            k: copy.deepcopy(v)
            for k, v in backend.states[unit["name"]].items()
            if k in fields
        },
    }


def generation_producers(backend):
    context = backend.run_context
    if not context.get("pendingGeneration"):
        context.pop("generationProducers", None)
        return
    required = {
        p["stack"]
        for record in context["pendingGeneration"].values()
        for p in record["producers"]
    }
    for record in context["pendingGeneration"].values():
        required.update(generation_resume.dependency_producers(context, record))
    prior = context.get("generationProducers", {})
    # Phase-one recovery has no current dependency index yet; retain its bounded proof.
    shared = session_reads(backend.root)
    if shared is None or shared.dependency_index is None:
        required.update(prior)
    proofs = {name: prior[name] for name in required & prior.keys()}
    for unit in backend.units:
        state = backend.states[unit["name"]]
        if (
            unit["name"] in required
            and state.get("status") == "SUCCESS"
            and state.get("observedSynced")
            and not state.get("failureDetected")
            and not state.get("schedulerError")
        ):
            proofs[unit["name"]] = operation_record(
                backend,
                unit,
                (
                    *observed_resume.EVIDENCE_FIELDS,
                    "observedSynced",
                    "expectedOutputs",
                    "changes",
                ),
            )
    context["generationProducers"] = proofs


def save(path, backend):
    context = backend.run_context
    generation_producers(backend)
    operations = copy.deepcopy(getattr(backend, "prepared_operations", {}))
    operations.update(
        {
            unit["name"]: operation_record(backend, unit)
            for unit in backend.units
            if unfinished(backend.states[unit["name"]])
        }
    )
    publication = {}
    if operations or context.get("pendingObserved") or context.get("pendingGeneration"):
        publication = {
            k: copy.deepcopy(v) for k, v in context.items() if k in PUBLICATION_FIELDS
        }
    if "inputDigests" in publication:
        publication["inputDigests"] = {
            name: publication["inputDigests"].get(name) for name in operations
        }
    path = safe_path(path)
    if (
        not operations
        and not context.get("pendingObserved")
        and not context.get("pendingGeneration")
    ):
        path.unlink(missing_ok=True)
        return
    payload = {
        "target": context["target"],
        "operations": operations,
        "publication": publication,
    }
    atomic_replace_file(path, sealed(backend.root, payload), mode=0o600)


def _restore_template(backend, unit, state):
    stack = backend.aws("describe_stacks", StackName=state["stackId"])["Stacks"][0]
    if (
        stack.get("StackId") != state["stackId"]
        or stack.get("StackStatus") not in SUCCESS
        or stack.get("StackStatus") != state.get("stackStatus")
    ):
        raise Blocked("unfinished successful operation Stack identity/state changed")
    template = backend.aws("get_template", StackName=state["stackId"])["TemplateBody"]
    if isinstance(template, str):
        template, errors = decode(template)
        if errors:
            raise Blocked("unfinished operation template cannot be decoded")
    if not isinstance(template, dict) or template.get("Transform"):
        raise Blocked("unfinished operation template is unverifiable")
    parameters = {
        k: str(v["Default"])
        for k, v in template.get("Parameters", {}).items()
        if "Default" in v
    }
    parameters.update(
        {p["ParameterKey"]: p["ParameterValue"] for p in stack.get("Parameters", [])}
    )
    backend.templates[unit["name"]] = (template, parameters)


def _recovery_guard(backend, task, /):
    from_snapshot = backend.run_context
    if (
        deploy_context.load_target(
            backend.root,
            backend.environment,
            backend.target["awsAccountId"],
            backend.target.get("alias"),
        )
        != backend.target
    ):
        raise Blocked("project target changed during unfinished-operation recovery")
    current = task_snapshot(backend.root, live=True)
    if current.task_digest != task.task_digest:
        raise Blocked("Task changed during unfinished operation recovery")
    for relative, digest in from_snapshot.get("modelInputs", {}).items():
        path = backend.root / relative
        # Pending publication checks classify before/after bytes under the existing lock.
        if from_snapshot.get("pendingObserved") or from_snapshot.get(
            "pendingGeneration"
        ):
            continue
        if (
            backend.file_digest(path, fresh=True) if path.is_file() else None
        ) != digest:
            raise Blocked(
                "Model changed before unfinished observation recovery: " + relative
            )
    for unit in backend.units:
        state = backend.states[unit["name"]]
        if not state.get("bootstrap") and state.get("cleanupStatus") != "DELETE_INTENT":
            continue
        if (
            backend.input_digest(unit, fresh=True)
            != backend.expected_digests[unit["name"]]
        ):
            raise Blocked("unfinished runtime operation inputs changed")
        owner = state.get("bootstrap", {}).get("owner")
        if (
            owner
            and backend.input_digest(owner["unit"], fresh=True) != owner["inputDigest"]
        ):
            raise Blocked("unfinished bootstrap owner inputs changed")


def recover(backend, path, task, scope):
    """Settle original tokens before any new run. Never resubmit an uncertain mutation."""
    record = read(path)
    backend.prepared_operations = {}
    backend.recovered_operations = {}
    backend.pending_publication = {}
    if record is None:
        return
    if record["target"] != backend.target or set(record["operations"]) - set(scope):
        raise Blocked(
            "unfinished operations require their exact target and encompassing Stack scope"
        )
    # Unexecuted ChangeSets carry no historical Task ownership or approval forward.
    if (
        not record["publication"].get("pendingObserved")
        and not record["publication"].get("pendingGeneration")
        and all(
            not op["state"].get("executionEvidence")
            and op["state"].get("status") != "RUNNING"
            and not op["state"].get("bootstrap")
            and op["state"].get("cleanupStatus") != "DELETE_INTENT"
            for op in record["operations"].values()
        )
    ):
        for name, operation in record["operations"].items():
            state = operation["state"]
            change = backend.describe_change_set(operation["unit"], state)
            if state.get("stackId") is None:
                # Creation intent had a stable AWS name but its response was interrupted.
                if (
                    change.get("StackName") != name
                    or not change.get("StackId")
                    or not change.get("ChangeSetId")
                ):
                    raise Blocked("ChangeSet creation submission is unconfirmed")
                state.update(
                    stackId=change["StackId"], changeSetId=change["ChangeSetId"]
                )
            if (
                change.get("StackId") != state["stackId"]
                or change.get("ChangeSetId") != state["changeSetId"]
                or change.get("ExecutionStatus") not in {"AVAILABLE", "UNAVAILABLE"}
            ):
                raise Blocked(
                    "unfinished ChangeSet execution is unknown; retain and investigate AWS"
                )
            backend.prepared_operations[name] = operation
        return
    context = record["publication"]
    if (
        context.get("repository") != str(backend.root)
        or context.get("taskFile") != task.name
        or context.get("taskDigest") != task.task_digest
    ):
        raise Blocked(
            "unfinished publication/operation belongs to another Task; recover its owner before new work"
        )
    context["states"] = {name: {"status": "NOT_STARTED"} for name in scope}
    context["states"].update(
        {name: op["state"] for name, op in record["operations"].items()}
    )
    context["metrics"] = {"observedSyncSeconds": 0, "inputLoadSeconds": 0}
    context.setdefault("inputDigests", {})
    backend.run_context, backend.states = context, context["states"]
    backend.expected_digests = context["inputDigests"]
    backend.units = [op["unit"] for op in record["operations"].values()]
    backend.save = backend.recovery_save = JournalSave(path, backend)
    backend.guard = RecoveryGuard(backend, task)
    with task_reads(backend.root, live=True):
        if context.get("pendingObserved"):
            observed_resume.reconcile(
                backend.root,
                context,
                backend.target,
                backend.environment,
                backend.directory,
            )
        if context.get("pendingGeneration"):
            generation_resume.reconcile(
                backend.root,
                context,
                backend.target,
                backend.environment,
                backend.directory,
            )
    models = RunModels(backend.root, context)
    backend.recovered_models = models
    with model_session(models):
        backend.after_observed = models.apply_observed
        for name, operation in record["operations"].items():
            state, unit = operation["state"], operation["unit"]
            context["inputDigests"][name] = operation["inputDigest"]
            if state.get("bootstrap") or state.get("cleanupStatus") == "DELETE_INTENT":
                recover_runtime(backend, unit, state, operation)
            if state.get("status") == "RUNNING":
                # Original poll verifies ChangeSet, StackId, terminal event and token.
                for _ in range(120):
                    try:
                        status = backend.poll(unit, state)
                    except change_sets.OutputNotReflected:
                        backend.save()
                        raise
                    if status == "RECHECK":
                        state["status"] = "NOT_STARTED"
                        break
                    if status in SUCCESS | FAILED:
                        state.update(
                            status="SUCCESS" if status in SUCCESS else "FAILED",
                            stackStatus=status,
                        )
                        break
                    if not status.endswith("_IN_PROGRESS"):
                        raise Blocked("unknown unfinished AWS operation state")
                    backend.save()
                    time.sleep(5)
                else:
                    raise Blocked(
                        "AWS operation still unconfirmed; retain original token; do not Execute again"
                    )
                backend.save()
            if state.get("status") == "SUCCESS" and not state.get("observedSynced"):
                _restore_template(backend, unit, state)
                try:
                    change_sets.verify_outputs(
                        backend.aws, unit, state, state.get("expectedOutputs", {})
                    )
                except change_sets.OutputNotReflected:
                    state["status"] = "FAILED"
                    backend.save()
                    raise
            elif state.get("changeSetId") and not state.get("executionEvidence"):
                change = backend.describe_change_set(unit, state)
                if (
                    change.get("StackId") != state.get("stackId")
                    or change.get("ChangeSetId") != state["changeSetId"]
                ):
                    raise Blocked("unfinished ChangeSet identity changed")
                if change.get("ExecutionStatus") in {
                    "EXECUTE_IN_PROGRESS",
                    "EXECUTE_COMPLETE",
                }:
                    raise Blocked(
                        "ChangeSet executed without original token evidence; inspect AWS before continuing"
                    )
                if change.get("ExecutionStatus") not in {"AVAILABLE", "UNAVAILABLE"}:
                    raise Blocked("unfinished ChangeSet submission unknown")
                backend.prepared_operations[name] = operation
        from_run_sync(backend)
        backend.recovered_operations = {
            name: operation_record(backend, operation["unit"])
            for name, operation in record["operations"].items()
            if backend.states[name].get("status") == "SUCCESS"
        }
        if context.get("pendingGeneration"):
            backend.pending_publication = {
                key: copy.deepcopy(context[key])
                for key in (
                    "pendingGeneration",
                    "modelInputs",
                    "generationProducers",
                    "inputDigest",
                )
                if key in context
            }
        backend.save()


# Callable objects keep callbacks explicit without nested definitions/imports.
class JournalSave:
    def __init__(self, path, backend):
        self.path, self.backend = path, backend

    def __call__(self):
        save(self.path, self.backend)


class RecoveryGuard:
    def __init__(self, backend, task):
        self.backend, self.task = backend, task

    def __call__(self):
        return _recovery_guard(self.backend, self.task)


def from_run_sync(backend):
    backend.guard()
    generation_resume.recover_publications(backend)
    unsynced = [
        u
        for u in backend.units
        if backend.states[u["name"]].get("status") == "SUCCESS"
        and not backend.states[u["name"]].get("observedSynced")
    ]
    if unsynced or backend.run_context.get("pendingObserved"):
        observed.sync_successful(backend, unsynced, backend.states)
    if backend.run_context.get("pendingObserved") or any(
        item["generated"]["outputs"] is not None
        for item in backend.run_context.get("pendingGeneration", {}).values()
    ):
        raise Blocked("unfinished Observed/publication could not be settled")


def verify_producer(backend, operation):
    """Recheck only a pending service's completed Producer, never replay its Execute."""
    unit, state = operation["unit"], operation["state"]
    observed_resume.evidence({unit["name"]: state}, [unit["name"]])
    execution = state.get("executionEvidence")
    if execution and execution.get("inputDigest") != operation["inputDigest"]:
        raise Blocked("Producer execution input evidence changed: " + unit["name"])
    _restore_template(backend, unit, state)
    if execution and backend.poll(unit, state) != state["stackStatus"]:
        raise Blocked(
            "Producer terminal token evidence is unconfirmed: " + unit["name"]
        )
    change_sets.verify_outputs(
        backend.aws, unit, state, state.get("expectedOutputs", {})
    )
    outputs, _, _ = observed.collect_successful(backend, [unit], {unit["name"]: state})
    shared = session_reads(backend.root)
    if any(shared.read(path) != text.encode("utf-8") for path, text in outputs.items()):
        raise Blocked("Producer Observed values no longer match AWS: " + unit["name"])


def adopt_recovered(backend):
    proofs = backend.run_context.get("generationProducers", {})
    recovered = getattr(backend, "recovered_operations", {})
    units = {unit["name"]: unit for unit in backend.units}
    for name, operation in {**proofs, **recovered}.items():
        if name not in units:
            if name in recovered:
                raise Blocked("recovered AWS success is outside current scope: " + name)
            continue
        if operation["unit"] != units[name]:
            raise Blocked("recovered Stack definition changed: " + name)
        backend.claim_inputs(units[name])
        if backend.run_context["inputDigests"][name] != operation["inputDigest"]:
            raise Blocked("recovered successful Stack inputs changed: " + name)
        if name not in recovered:
            verify_producer(backend, operation)
        backend.states[name] = copy.deepcopy(operation["state"])


def recover_runtime(backend, unit, state, operation):
    # Runtime mutation is authorized separately and cannot absorb changed IaC.
    backend.guard()
    require_authorized(backend.root)
    if backend.input_digest(unit, fresh=True) != operation["inputDigest"]:
        raise Blocked(
            "unfinished Secrets/cleanup operation requires its original inputs"
        )
    backend.load_inputs(unit)
    if state.get("bootstrap"):
        status = backend.poll(unit, state)
        if status != state.get("stackStatus") or status not in {
            "ROLLBACK_COMPLETE",
            "UPDATE_ROLLBACK_COMPLETE",
        }:
            raise Blocked("unfinished bootstrap failure evidence changed")
        owner = state["bootstrap"]["owner"]
        owner_unit = owner["unit"]
        if (
            owner_unit["name"] != owner["stack"]
            or backend.input_digest(owner_unit, fresh=True) != owner["inputDigest"]
        ):
            raise Blocked("unfinished bootstrap owner inputs changed")
        if owner["stack"] != unit["name"]:
            current = backend.aws("describe_stacks", StackName=owner["stackId"])[
                "Stacks"
            ][0]
            if (
                current.get("StackId") != owner["stackId"]
                or current.get("StackStatus") not in SUCCESS
            ):
                raise Blocked("unfinished bootstrap owner identity/state changed")
            backend.load_inputs(owner_unit)
            if (
                backend.states.get(owner["stack"], {}).get("status", "NOT_STARTED")
                == "NOT_STARTED"
            ):
                backend.states[owner["stack"]] = {
                    "status": "SUCCESS",
                    "stackId": owner["stackId"],
                    "observedSynced": True,
                }
            if not any(u["name"] == owner["stack"] for u in backend.units):
                backend.units.append(owner_unit)
        backend.bootstrap(unit, state, state["bootstrap"])
    elif state.get("cleanupStatus") == "DELETE_INTENT":
        backend.wait_cleanup(state)
        backend.reset_after_cleanup(state)
    state["status"] = "NOT_STARTED"


def adopt_prepared(backend, path, approvals):
    """Only an unexecuted current ChangeSet may cross an explicit approval interruption."""
    matched = set()
    for unit in backend.units:
        operation = backend.prepared_operations.get(unit["name"])
        if not operation:
            continue
        state = operation["state"]
        change_id = state["changeSetId"]
        backend.claim_inputs(unit)
        unchanged = backend.input_digest(unit, fresh=True) == operation["inputDigest"]
        if not unchanged and change_id in approvals:
            raise Blocked(
                "approved ChangeSet inputs changed; obtain approval for a fresh ChangeSet"
            )
        change = backend.describe_change_set(unit, state)
        if (
            change.get("StackId") != state["stackId"]
            or change.get("ChangeSetId") != change_id
        ):
            raise Blocked("unfinished ChangeSet target changed before adoption")
        if state.get("operationType") == "CREATE" and (
            not unchanged or change.get("Status") == "FAILED"
        ):
            require_authorized(backend.root)
            shell = {
                key: state[key]
                for key in (
                    "stackId",
                    "changeSetId",
                    "operationType",
                    "absentBeforeCreate",
                )
            }
            # Only the original FAILED/UNAVAILABLE empty CREATE shell can be removed.
            active = backend.states[unit["name"]]
            active.update(stackId=state["stackId"], preExecutionRecovery=shell)
            cleanup_unexecuted(backend.aws, backend.save, backend.wait_cleanup, active)
            backend.reset_after_cleanup(active)
            backend.prepared_operations.pop(unit["name"])
            continue
        if not unchanged:
            backend.prepared_operations.pop(unit["name"])
            continue
        backend.load_inputs(unit)
        if state.get("operationType") == "UPDATE":
            backend.verify_stack_ownership(unit)
        backend.states[unit["name"]] = {**state, "status": "BLOCKED"}
        backend.prepared_operations.pop(unit["name"])
        if change_id in approvals:
            matched.add(change_id)
    if set(approvals) != matched:
        raise Blocked(
            "approve only the current unfinished ChangeSet ID after explicit Human consent"
        )
    backend.save()
