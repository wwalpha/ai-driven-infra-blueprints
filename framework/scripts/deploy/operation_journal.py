"""Only unfinished AWS operations and atomic publication ownership survive an invocation."""

import copy
import errno
import json
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import worktree_state
from model.sources import model_session, session_reads
from task_contract_core import paths_in, task_reads, task_snapshot
from utils.aws.client import AwsError
from utils.cloudformation.export_resolution import (
    describe_exports,
    merge_hints,
    resolve_exports,
    stack_name,
)
from utils.cloudformation.format import decode
from utils.cloudformation.inputs import Blocked
from utils.file_operations import atomic_replace_file
from utils.json_format import fingerprint
from utils.local_evidence import read_sealed, sealed

from deploy import change_sets, generation_resume, observed, observed_resume, worktree
from deploy import context as deploy_context
from deploy.model_cache import RunModels
from deploy.recovery import cleanup_unexecuted, require_authorized
from deploy.scheduler import FAILED, SUCCESS

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# No approvals, failure archives, repair histories, workflow bindings or completed records.
OPERATION_FIELDS = {
    "failureDetected",
    "attemptResult",
    "needsCurrentReview",
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
    "bootstrapAttempted",
    "emptyStackRecreated",
    "failureEvents",
    "preparationId",
    "changeSetStarted",
    "changeSetCreateSeconds",
    "expectedOutputs",
    "noChangeEvidence",
    "preExecutionRecovery",
    "delivery",
    "checkpointRequired",
    "observedCoverage",
    "observedServices",
    "failure",
    "schedulerError",
    "pollReadFailures",
    "unconfirmedPolls",
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
    "stepwise",
    "stepUnits",
    "consumedInputs",
    "inputIdentities",
    "checkpointPending",
    "generationError",
    "currentFailure",
}


def location(target):
    identity = [
        target.get("awsExecutionAccountId", target["awsAccountId"]),
        target["awsRegion"],
    ]
    return (
        Path(tempfile.gettempdir()).resolve()
        / ("blueprint-cfn-current-v3-" + fingerprint(identity))
        / "journal.json"
    )


def safe_path(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise Blocked("operation journal path must be absolute and not redirected")
    return path


def private_path(path, *, directory=False, permissions=0o077):
    path = safe_path(path)
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not kind(info.st_mode)
        or os.name != "nt"
        and (info.st_uid != os.getuid() or info.st_mode & permissions)
        or not directory
        and info.st_nlink != 1
    ):
        raise Blocked("operation journal path must be private and owned: " + str(path))
    return info


@contextmanager
def locked(path):
    path = safe_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_path(path.parent, directory=True)
    lock = safe_path(path.with_suffix(".lock"))
    flags = os.O_CREAT | os.O_RDWR
    if os.name != "nt":
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock, flags, 0o600)
    try:
        info = private_path(lock, permissions=0o022)
        opened = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise Blocked("operation lock identity changed")
        try:
            if os.name == "nt":
                if opened.st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            raise Blocked(
                "controller active; operation lock busy: " + str(lock)
            ) from error
        yield
    finally:
        os.close(descriptor)


def read(path):
    path = safe_path(path)
    if not path.exists():
        return None
    private_path(path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    try:
        owner = safe_path(Path(envelope["payload"]["publication"]["repository"]))
    except (KeyError, TypeError) as error:
        raise Blocked("invalid unfinished-operation ownership") from error
    record = read_sealed(owner, path)
    if not isinstance(record, dict):
        raise Blocked("invalid unfinished-operation ownership")
    # Retain the original signed record entrance; peers are unfinished operations only.
    peers = record.pop("peers", [])
    if not isinstance(peers, list):
        raise Blocked("invalid unfinished-operation peers")
    records = [record, *peers]
    names = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "target",
            "operations",
            "publication",
        }:
            raise Blocked("invalid unfinished-operation ownership")
        if not isinstance(record["operations"], dict):
            raise Blocked("invalid unfinished operations")
        if (
            not isinstance(record["publication"], dict)
            or record["publication"].get("target") != record["target"]
        ):
            raise Blocked("unfinished publication target differs from operation")
        safe_path(Path(record["publication"]["repository"]))
        if names & record["operations"].keys():
            raise Blocked("conflicting unfinished Stack operations")
        names.update(record["operations"])
        producers = record["publication"].get("generationProducers", {})
        if not isinstance(producers, dict):
            raise Blocked("invalid pending generation Producer evidence")
        for operation in [*record["operations"].values(), *producers.values()]:
            if (
                not isinstance(operation, dict)
                or set(operation) != {"unit", "inputDigest", "state"}
                or not isinstance(operation["unit"], dict)
                or not isinstance(operation["state"], dict)
                or set(operation["state"]) - OPERATION_FIELDS
            ):
                raise Blocked("invalid unfinished operation fields")
        if any(
            op["state"].get("status") != "SUCCESS"
            or not op["state"].get("observedSynced")
            for op in producers.values()
        ):
            raise Blocked(
                "pending generation Producer has no Observed completion evidence"
            )
        if set(record["publication"]) - PUBLICATION_FIELDS:
            raise Blocked("invalid publication ownership fields")
    return records


def target_identity(target):
    return (
        target.get("awsExecutionAccountId", target["awsAccountId"]),
        target["awsRegion"],
    )


def unfinished(state):
    return bool(
        state.get("checkpointRequired")
        and (
            state.get("status") != "NOT_STARTED"
            or state.get("emptyStackRecreated")
            or state.get("bootstrapAttempted")
            or state.get("cleanupStatus")
        )
        or state.get("bootstrap")
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
    if backend.run_context.get("stepwise"):
        unit = next(
            u for u in backend.run_context["stepUnits"] if u["name"] == unit["name"]
        )
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
            or unit["name"] in context.get("checkpointPending", {}).get("stacks", [])
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
    records = copy.deepcopy(getattr(backend, "retained_records", []))
    if operations or context.get("pendingObserved") or context.get("pendingGeneration"):
        records.append(
            {
                "target": context["target"],
                "operations": operations,
                "publication": publication,
            }
        )
    write_records(path, records)


def records_text(records: list[dict]) -> str | None:
    """Encode the same signed entrance without changing the caller's records."""
    if records:
        payload, *peers = copy.deepcopy(records)
        if peers:
            payload["peers"] = peers
        owner = safe_path(Path(payload["publication"]["repository"]))
        return sealed(owner, payload)
    return None


def write_records(path, records):
    path = safe_path(path)
    text = records_text(records)
    if text is not None:
        atomic_replace_file(path, text, mode=0o600)
    else:
        path.unlink(missing_ok=True)


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
    alias = backend.target.get("alias")
    if (
        deploy_context.load_target(
            backend.root,
            backend.environment,
            None if alias else backend.target["awsAccountId"],
            alias,
        )
        != backend.target
    ):
        raise Blocked("project target changed during unfinished-operation recovery")
    current = task_snapshot(backend.root, live=True)
    worktree.require(backend.root, current)
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


def same_repository(root, owner, *, require_known=False):
    owner = safe_path(Path(owner))
    if root == owner:
        return True
    try:
        return (
            Path(
                worktree_state.output(
                    root, "rev-parse", "--path-format=absolute", "--git-common-dir"
                )
            ).resolve()
            == Path(
                worktree_state.output(
                    owner, "rev-parse", "--path-format=absolute", "--git-common-dir"
                )
            ).resolve()
        )
    except (OSError, ValueError) as error:
        if require_known:
            raise Blocked(
                "unfinished publication Repository ownership is unknown"
            ) from error
        return False


def publication_paths(context):
    paths = set(context.get("pendingObserved", {}).get("beforeManifest", {}))
    plans = [*context.get("pendingGeneration", {}).values()]
    if context.get("pendingObserved"):
        plans.append(context["pendingObserved"])
    for plan in plans:
        paths.update(plan.get("generated", {}).get("originals", {}))
        paths.update(plan.get("waitingModelManifest", {}))
        paths.update(plan.get("candidateManifest") or {})
    return paths


def publication_conflicts(backend, task):
    declared = paths_in(task.text, "## Modified files")
    for record in backend.retained_records:
        context = record["publication"]
        if context.get("repository") == str(backend.root):
            overlap = declared & publication_paths(context)
            if overlap:
                raise Blocked(
                    "unfinished publication shares current Task files: "
                    + ", ".join(sorted(overlap))
                )


def recover(backend, path, task, scope):
    """Settle scoped original tokens; keep every other owner's unfinished evidence."""
    backend.prepared_operations = {}
    backend.pending_publication = {}
    backend.retained_records = read(path) or []
    worktree.check_pending_progress(backend, backend.retained_records, unfinished)
    if any(
        r["publication"].get("stepwise")
        and (
            set(scope) & r["operations"].keys()
            or r["publication"].get("repository") == str(backend.root)
            and r["publication"].get("taskFile") == task.name
        )
        for r in backend.retained_records
    ):
        raise Blocked(
            "LLM-controlled operation pending; use --action advance/sync/checkpoint/status, never reset"
        )
    selected = set(scope)
    for record in backend.retained_records:
        if target_identity(record["target"]) != target_identity(backend.target):
            raise Blocked("unfinished operation Account/Region changed")
        if record["publication"].get("stepwise"):
            for name, operation in record["operations"].items():
                validate_operation(record["target"], name, operation)
            continue
        for name, operation in list(record["operations"].items()):
            validate_operation(record["target"], name, operation)
            if name not in selected and not aws_unfinished(
                record["target"], name, operation, backend.aws
            ):
                state = operation["state"]
                state["status"] = "SUCCESS"
                if state.get("observedSynced") and not (
                    record["publication"].get("pendingObserved")
                    or record["publication"].get("pendingGeneration")
                ):
                    del record["operations"][name]
    backend.retained_records = [
        r
        for r in backend.retained_records
        if r["operations"]
        or r["publication"].get("pendingObserved")
        or r["publication"].get("pendingGeneration")
    ]
    write_records(path, copy.deepcopy(backend.retained_records))
    for record in list(backend.retained_records):
        if target_identity(record["target"]) != target_identity(backend.target):
            raise Blocked("unfinished operation Account/Region changed")
        context = record["publication"]
        overlap = selected & record["operations"].keys()
        same_destination = (
            same_repository(backend.root, context["repository"])
            and context.get("environment") == backend.environment
            and context.get("directory") == backend.directory
            and record["target"] == backend.target
        )
        publication_requested = (
            not record["operations"]
            and same_destination
            and (
                publication_paths(context) & paths_in(task.text, "## Modified files")
                or any(
                    p["stack"] in selected
                    for plan in context.get("pendingGeneration", {}).values()
                    for p in plan["producers"]
                )
            )
        )
        if not overlap and not publication_requested:
            continue
        active = copy.deepcopy(record)
        remainder = copy.deepcopy(record)
        active["operations"] = {
            n: op for n, op in active["operations"].items() if n in selected
        }
        remainder["operations"] = {
            n: op for n, op in remainder["operations"].items() if n not in selected
        }
        backend.retained_records.remove(record)
        shared_publication = bool(
            context.get("pendingObserved") or context.get("pendingGeneration")
        )
        backend.publication_scope_blocked = bool(
            remainder["operations"] and shared_publication
        )
        if backend.publication_scope_blocked:
            # Keep the atomic plan and all operation proofs together until its full scope is authorized.
            active = copy.deepcopy(record)
        elif remainder["operations"]:
            backend.retained_records.append(remainder)
        backend.recovery_scope = selected
        backend.prepared_operations = {}
        _recover_record(backend, path, task, scope, active, same_destination)
        backend.retained_records = read(path) or []
    backend.prepared_operations.update(
        {
            name: operation
            for record in backend.retained_records
            for name, operation in record["operations"].items()
            if name in selected
            and not operation["state"].get("executionEvidence")
            and not operation["state"].get("bootstrap")
            and operation["state"].get("cleanupStatus") != "DELETE_INTENT"
            and operation["state"].get("status") != "RUNNING"
        }
    )
    # Prepared operations will be saved by the new run, other records stay intact.
    for record in backend.retained_records:
        for name in backend.prepared_operations:
            record["operations"].pop(name, None)
    for record in backend.retained_records:
        publication = record["publication"]
        if (
            publication.get("repository") == str(backend.root)
            and publication.get("taskDigest") == task.task_digest
        ):
            for view in backend.pending_publication.get("pendingGeneration", {}):
                publication.get("pendingGeneration", {}).pop(view, None)
    backend.retained_records = [
        r
        for r in backend.retained_records
        if r["operations"]
        or r["publication"].get("pendingObserved")
        or r["publication"].get("pendingGeneration")
    ]


def validate_operation(target, name, operation):
    unit, state = operation["unit"], operation["state"]
    if unit["name"] != name:
        raise Blocked("unfinished operation Stack name changed: " + name)
    execution = state.get("executionEvidence")
    if execution:
        if (
            not state.get("clientToken")
            or any(
                execution.get(key) != state.get(field)
                for key, field in (
                    ("StackId", "stackId"),
                    ("ChangeSetId", "changeSetId"),
                    ("clientToken", "clientToken"),
                    ("changeDigest", "changeDigest"),
                )
            )
            or execution.get("inputDigest") != operation["inputDigest"]
        ):
            raise Blocked("unfinished original execution evidence changed: " + name)
    elif state.get("status") == "RUNNING" and not state.get("externalOperation"):
        raise Blocked("unfinished execution has no original token evidence: " + name)
    account, region = target_identity(target)
    for field, kind in (("stackId", "stack"), ("changeSetId", "changeSet")):
        value = state.get(field)
        if value is None or field == "changeSetId" and not execution:
            continue  # A ChangeSet creation intent uses its original stable name.
        match = re.fullmatch(
            r"arn:(aws[a-z-]*):cloudformation:([^:]+):([^:]+):([^/]+)/([^/]+)/([^/]+)",
            value,
        )
        if (
            not match
            or (match[2], match[3], match[4]) != (region, account, kind)
            or kind == "stack"
            and match[5] != name
        ):
            raise Blocked(
                "unfinished AWS Account/Region/Stack identity differs: " + name
            )


def _recover_record(backend, path, task, scope, record, same_destination):
    context = record["publication"]
    context["states"] = {name: {"status": "NOT_STARTED"} for name in scope}
    context["states"].update(
        {name: op["state"] for name, op in record["operations"].items()}
    )
    context["metrics"] = {"observedSyncSeconds": 0, "inputLoadSeconds": 0}
    context.setdefault("inputDigests", {})
    backend.run_context, backend.states = context, context["states"]
    backend.expected_digests = context["inputDigests"]
    backend.units = [op["unit"] for op in record["operations"].values()]
    backend.save = JournalSave(path, backend)
    backend.guard = RecoveryGuard(backend, task)
    for name, operation in record["operations"].items():
        if name not in backend.recovery_scope:
            continue
        state, unit = operation["state"], operation["unit"]
        validate_operation(record["target"], name, operation)
        pending = aws_unfinished(record["target"], name, operation, backend.aws)
        if not pending:
            state["status"] = "SUCCESS"
        elif state.get("status") == "SUCCESS" and no_change_candidate(operation):
            raise Blocked("unverified no-change success cannot be recovered: " + name)
        context["inputDigests"][name] = operation["inputDigest"]
        running = state.get("status") == "RUNNING"
        if running:
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
            if (
                not running
                and state.get("executionEvidence")
                and backend.poll(unit, state) != state.get("stackStatus")
            ):
                raise Blocked(
                    "unfinished successful operation token is unconfirmed: " + name
                )
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
            if state.get("stackId") is None:
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
    backend.save()
    needs_local = (
        context.get("pendingObserved")
        or context.get("pendingGeneration")
        or any(
            s.get("status") == "SUCCESS"
            and not s.get("observedSynced")
            or s.get("bootstrap")
            or s.get("cleanupStatus") == "DELETE_INTENT"
            for s in backend.states.values()
        )
    )
    if needs_local:
        if not same_destination:
            raise Blocked(
                "AWS operation settled; local publication destination differs: "
                + str(sorted(record["operations"]))
            )
        if backend.publication_scope_blocked:
            raise Blocked(
                "shared publication requires explicit authority for its remaining Stacks"
            )
        observed_resume.reauthorize(backend, task)
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
        models = getattr(backend, "recovered_models", None) or RunModels(
            backend.root, context
        )
        models.run_context = context
        backend.recovered_models = models
        with model_session(models):
            backend.after_observed = models.apply_observed
            for name, operation in record["operations"].items():
                state = backend.states[name]
                if (
                    state.get("bootstrap")
                    or state.get("cleanupStatus") == "DELETE_INTENT"
                ):
                    recover_runtime(backend, operation["unit"], state, operation)
            from_run_sync(backend)
    if context.get("pendingGeneration"):
        for key in ("pendingGeneration", "modelInputs", "generationProducers"):
            destination = backend.pending_publication.setdefault(key, {})
            source = context.get(key, {})
            if any(
                destination[name] != source[name]
                for name in destination.keys() & source.keys()
            ):
                raise Blocked("unfinished publication inputs overlap: " + key)
            destination.update(copy.deepcopy(source))
    backend.save()


# Callable objects keep callbacks explicit without nested definitions/imports.
class JournalSave:
    def __init__(self, path, backend):
        self.path, self.backend = path, backend

    def __call__(self):
        worktree.save_progress(self.backend, OPERATION_FIELDS)
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


def no_change_candidate(operation):
    state = operation["state"]
    return not (
        state.get("status") == "RUNNING"
        or state.get("executionEvidence")
        or state.get("bootstrap")
        or state.get("cleanupStatus") == "DELETE_INTENT"
        or state.get("operationType") != "UPDATE"
        or state.get("absentBeforeCreate") is not False
        or not state.get("changeSetId")
        or not state.get("stackId")
    )


def record_no_change(aws, unit, state, change):
    if not isinstance(state.get("expectedOutputs"), dict):
        raise Blocked("no-change Output evidence is incomplete: " + unit["name"])
    change_sets.verify_no_change(unit["name"], state, change)
    change_sets.verify_outputs(aws, unit, state, state["expectedOutputs"])
    state["noChangeEvidence"] = {
        key: copy.deepcopy(change.get(key))
        for key in (
            "Status",
            "StatusReason",
            "ExecutionStatus",
            "Changes",
            "StackName",
            "StackId",
            "ChangeSetId",
            "NextToken",
        )
    }


def aws_unfinished(target, name, operation, aws, *, boundary=None):
    """Keep unknown AWS operations pending; never infer completion from read errors."""
    cache = boundary.setdefault("journalStates", {}) if boundary is not None else {}
    if name in cache:
        return cache[name]
    state = operation["state"]
    if (
        state.get("checkpointRequired")
        and state.get("status") == "FAILED"
        and state.get("executionEvidence")
    ):
        validate_operation(target, name, operation)
        stack = aws("describe_stacks", StackName=state["stackId"])["Stacks"][0]
        events = aws("describe_stack_events", StackName=state["stackId"])["StackEvents"]
        cache[name] = not (
            stack.get("StackId") == state["stackId"]
            and stack.get("StackStatus") == state.get("stackStatus")
            and stack.get("StackStatus") in FAILED
            and any(
                e.get("StackId") == state["stackId"]
                and e.get("ClientRequestToken") == state["clientToken"]
                and e.get("ResourceType") == "AWS::CloudFormation::Stack"
                and e.get("ResourceStatus") == state["stackStatus"]
                for e in events
            )
        )
        return cache[name]
    evidence = state.get("noChangeEvidence")
    if (
        evidence is not None
        or state.get("executionEvidence")
        or no_change_candidate(operation)
    ):
        validate_operation(target, name, operation)
    if evidence is not None:
        if not isinstance(evidence, dict) or not no_change_candidate(operation):
            raise Blocked("invalid no-change success evidence: " + name)
        change_sets.verify_no_change(name, state, evidence)
        try:
            change_sets.verify_no_change_completion(
                aws, operation["unit"], state, evidence
            )
            if not isinstance(state.get("expectedOutputs"), dict):
                raise Blocked("no-change Output evidence is incomplete: " + name)
            change_sets.verify_outputs(
                aws, operation["unit"], state, state["expectedOutputs"]
            )
        except AwsError:
            cache[name] = True
            return True
        cache[name] = False
        return False
    if not no_change_candidate(operation):
        cache[name] = True
        return True
    try:
        change = change_sets.describe_change_set(aws, operation["unit"], state)
    except AwsError:
        cache[name] = True
        return True
    if (
        change.get("ChangeSetId") != state["changeSetId"]
        or change.get("StackId") != state["stackId"]
        or change.get("StackName") != name
    ):
        raise Blocked("unfinished ChangeSet identity changed: " + name)
    if not change_sets.no_changes(change):
        if state.get("status") == "SUCCESS":
            raise Blocked("saved no-change success cannot be confirmed: " + name)
        cache[name] = True
        return True
    if not isinstance(state.get("expectedOutputs"), dict):
        raise Blocked("no-change Output evidence is incomplete: " + name)
    try:
        state["stackStatus"] = change_sets.verify_no_change_completion(
            aws, operation["unit"], state, change
        )
        record_no_change(aws, operation["unit"], state, change)
    except AwsError:
        cache[name] = True
        return True
    cache[name] = False
    return False


def dependency_states(backend, unit, *, imports, hints, boundary):
    """Unrelated unfinished Stacks are allowed only across proved dependency boundaries."""
    reset_pending = getattr(backend, "reset_pending", [])
    for group in reset_pending:
        require_independent(
            group,
            {unit["name"]},
            backend.aws,
            imports={unit["name"]: imports},
            hints=hints,
            boundary=boundary,
        )
    pending = {
        name: operation["state"]
        for record in getattr(backend, "retained_records", [])
        for name, operation in record["operations"].items()
        if aws_unfinished(
            backend.target, name, operation, backend.aws, boundary=boundary
        )
    }
    require_independent(
        pending,
        {unit["name"]},
        backend.aws,
        imports={unit["name"]: imports},
        hints=hints,
        boundary=boundary,
    )
    return {
        **{name: {"status": "RUNNING"} for group in reset_pending for name in group},
        **{name: {"status": "RUNNING"} for name in pending},
        **backend.states,
    }


def export_stack(entry):
    if not isinstance(entry, dict):
        raise Blocked("unfinished Stack dependency evidence unavailable: Export")
    return stack_name(entry.get("ExportingStackId"))


def require_independent(
    pending, stacks, aws, *, imports=None, hints=None, boundary=None
):
    """Share Delivery/live Import/Export proof between Deploy and repair handoff."""
    if not pending:
        return
    if set(pending) & stacks:
        raise Blocked(
            "unfinished operation conflicts with current Stack: "
            + ", ".join(sorted(set(pending) & stacks))
        )
    # Follow Producer -> Consumer from both scopes, never through shared ancestors.
    consumers = {}
    for name, state in pending.items():
        delivered = state.get("delivery", {}).get("imports")
        if not isinstance(delivered, dict):
            raise Blocked("unfinished Stack dependency evidence unavailable: " + name)
        for entry in delivered.values():
            consumers.setdefault(export_stack(entry), set()).add(name)
    boundary = {} if boundary is None else boundary
    planned = set().union(*(imports or {}).values()) if imports else set()
    hints = merge_hints(
        [
            {name: entry for name, entry in (hints or {}).items() if name in planned},
            *(state["delivery"]["imports"] for state in pending.values()),
        ]
    )
    identities = {
        name: state["stackId"]
        for name, state in pending.items()
        if state.get("stackId")
    }
    for entry in hints.values():
        identity = entry.get("ExportingStackId")
        name = stack_name(identity)
        if name in identities and identities[name] != identity:
            raise Blocked("unfinished Stack Producer identity changed")
        identities[name] = identity
    for name in sorted(stacks | set(pending)):
        try:
            describe_exports(
                aws, identities.get(name, name), boundary, successful=False
            )
        except AwsError as error:
            if not error.stack_absent or name in identities or name not in stacks:
                raise
            boundary.setdefault("absentExportStacks", set()).add(name)
    owners = resolve_exports(
        aws, planned | hints.keys(), hints=hints, boundary=boundary
    )
    for stack, names in (imports or {}).items():
        for name in names:
            consumers.setdefault(export_stack(owners[name]), set()).add(stack)
    for entry in owners.values():
        name, identity = (
            stack_name(entry["ExportingStackId"]),
            entry["ExportingStackId"],
        )
        if name in identities and identities[name] != identity:
            raise Blocked("unfinished Stack Producer identity changed")
        identities[name] = identity
    expanded = set()
    for start in sorted(stacks | set(pending)):
        reached, remaining = set(), [start]
        conflicts = set(pending) if start in stacks else stacks
        while remaining:
            name = remaining.pop()
            if name in conflicts:
                raise Blocked(
                    "unfinished Stack dependency conflicts with repair/deploy: "
                    + start
                    + " -> "
                    + name
                )
            if name in reached:
                continue
            reached.add(name)
            if name not in expanded:
                owned = (
                    {}
                    if name in boundary.get("absentExportStacks", ())
                    else describe_exports(
                        aws, identities.get(name, name), boundary, successful=False
                    )
                )
                for export in owned:
                    response = aws("list_imports", ExportName=export)
                    imported = (
                        response.get("Imports") if isinstance(response, dict) else None
                    )
                    if (
                        not isinstance(imported, list)
                        or response.get("NextToken") is not None
                        or any(
                            not isinstance(consumer, str) or not consumer
                            for consumer in imported
                        )
                    ):
                        raise Blocked("unfinished Stack Import inventory is incomplete")
                    consumers.setdefault(name, set()).update(imported)
                expanded.add(name)
            remaining.extend(consumers.get(name, ()))


def adopt_recovered(backend):
    # Recovered completion is AWS evidence, not an old IaC constraint or approval.
    units = {unit["name"]: unit for unit in backend.units}
    for name, operation in backend.run_context.get("generationProducers", {}).items():
        if name not in units:
            continue
        backend.claim_inputs(units[name])
        if (
            operation["unit"] == units[name]
            and backend.run_context["inputDigests"][name] == operation["inputDigest"]
        ):
            verify_producer(backend, operation)
            backend.states[name] = copy.deepcopy(operation["state"])


def recover_runtime(backend, unit, state, operation):
    # Runtime mutation is authorized separately and cannot absorb changed IaC.
    backend.guard()
    require_authorized(backend.root)
    owner_name = state.get("bootstrap", {}).get("owner", {}).get("stack")
    if owner_name and owner_name not in backend.states:
        raise Blocked(
            "unfinished bootstrap owner is outside current Task scope: " + owner_name
        )
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
        unchanged = (
            unit == operation["unit"]
            and backend.input_digest(unit, fresh=True) == operation["inputDigest"]
        )
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
