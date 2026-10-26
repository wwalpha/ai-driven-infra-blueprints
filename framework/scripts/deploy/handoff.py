"""One-shot repair evidence; no Deploy history, workflow registry or retry inheritance."""

import copy
import json
import re
import uuid
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from task_contract_core import paths_in, safe_path, task_snapshot
from utils.aws import cloudformation
from utils.aws.client import connection_context
from utils.aws.identity import execution_account, select_profile
from utils.cloudformation.inputs import Blocked, load_template_inputs
from utils.file_operations import sha
from utils.sealed_evidence import evidence_store, read_sealed, write_sealed
from utils.type_contracts import JsonObject
from utils.type_contracts import JsonValue as JsonValue

from deploy import change_sets, context, inputs, operation_journal


def repair_lock(root: Path) -> AbstractContextManager[None]:
    return operation_journal.locked(evidence_store(root) / "deploy-repair.json")


def locked(path: Path) -> AbstractContextManager[None]:
    request = __read_request_owner(operation_journal.safe_path(path))
    return repair_lock(Path(request["repository"]))


def external(root: Path, path: str | Path) -> Path:
    path = Path(path)
    if (
        not path.is_absolute()
        or any(p.is_symlink() for p in (path, *path.parents))
        or path.resolve().is_relative_to(root.resolve())
    ):
        raise Blocked("handoff evidence must be outside repository without symlinks")
    return path


def record_failure(backend: SimpleNamespace) -> str | None:
    """Current failure proof is an optional repair entrance, never a new-run input."""
    selected = {
        name: copy.deepcopy(state)
        for name, state in backend.states.items()
        if state.get("status") in {"FAILED", "BLOCKED"}
    }
    for state in selected.values():
        state.pop("approvedChangeDigest", None)
    if not selected:
        return None
    path = evidence_store(backend.root) / (
        "deploy-failure-" + uuid.uuid4().hex + ".json"
    )
    context = backend.run_context
    with repair_lock(backend.root):
        write_sealed(
            backend.root,
            path,
            {
                "repository": str(backend.root),
                "taskFile": context["taskFile"],
                "taskDigest": context["taskDigest"],
                "target": backend.target,
                "environment": backend.environment,
                "directory": backend.directory,
                "states": selected,
                "inputs": {**context["consumedInputs"], **context["modelInputs"]},
            },
        )
    return str(path)


def referenced_failures(root: Path, *, excluding: Path | None = None) -> set[Path]:
    """Caller holds Repair lock; an unreadable request cannot prove any orphan safe."""
    result = set()
    for path in evidence_store(root).glob("deploy-repair-*/request.json"):
        if path == excluding:
            continue
        operation_journal.private_path(external(root, path))
        request = read_sealed(root, path)
        failure = external(root, request["failureEvidence"])
        operation_journal.private_path(failure)
        read_sealed(root, failure)
        result.add(failure)
    return result


def failure_templates(root: Path, target: dict[str, str]) -> set[Path]:
    """Caller holds Journal then Repair; uncertain evidence prevents reclamation."""
    paths = referenced_failures(root) | set(
        evidence_store(root).glob("deploy-failure-*.json")
    )
    needed = set()
    for path in paths:
        operation_journal.private_path(external(root, path))
        failure = read_sealed(root, path)
        if failure["repository"] != str(root):
            raise Blocked("failure evidence repository is unknown")
        if operation_journal.target_identity(
            failure["target"]
        ) != operation_journal.target_identity(target):
            continue
        if not isinstance(failure["states"], dict):
            raise Blocked("failure Stack evidence is unknown")
        for state in failure["states"].values():
            if not isinstance(state, dict) or not isinstance(
                state.get("delivery", {}), dict
            ):
                raise Blocked("failure delivery evidence is unknown")
            delivery = state.get("delivery", {})
            if delivery:
                template = Path(delivery["path"])
                operation_journal.private_path(
                    external(root, template), permissions=0o022
                )
                needed.add(template)
    return needed


def discard_failure(root: Path, path: Path) -> None:
    """Explicit abandonment of an unconsumed proof grants no old Task authority."""
    path = external(root, path)
    operation_journal.private_path(path)
    failure = read_sealed(root, path)
    if (
        failure["repository"] != str(root)
        or path.parent != evidence_store(root)
        or not re.fullmatch(r"deploy-failure-[a-zA-Z0-9-]+\.json", path.name)
    ):
        raise Blocked("failure evidence ownership is unknown")
    with (
        operation_journal.locked(operation_journal.location(failure["target"])),
        repair_lock(root),
    ):
        operation_journal.private_path(path)
        if read_sealed(root, path) != failure:
            raise Blocked("failure evidence changed before discard")
        if path in referenced_failures(root):
            raise Blocked("failure evidence is referenced by a repair request")
        path.unlink()


def issue_request(
    root: Path, failure_path: Path, diagnosis: JsonObject, allowed: Iterable[str]
) -> JsonObject:
    failure_path = external(root, failure_path)
    failure = read_sealed(root, failure_path)
    task = task_snapshot(root)
    if (
        failure["repository"] != str(root)
        or failure["taskFile"] != task.name
        or failure["taskDigest"] != task.task_digest
    ):
        raise Blocked("failure evidence belongs to another current Task")
    if "- External IaC repair: `allowed`" not in task.text.splitlines():
        raise Blocked("external implement repair is not authorized")
    for state in failure["states"].values():
        if state.get("failure", {}).get("classification") not in {
            "IAC_CANDIDATE",
            "INPUT_CANDIDATE",
        } and not (
            state.get("status") == "FAILED"
            and state.get("stackStatus")
            in {"ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}
            and state.get("failureEvents")
        ):
            raise Blocked(
                "failure needs investigation/Human action rather than IaC repair"
            )
    if not isinstance(diagnosis, dict) or set(diagnosis) != set(failure["states"]):
        raise Blocked("diagnosis must cover every current failed Stack")
    allowed = sorted(set(allowed))
    if not allowed or any(
        not p.startswith("infra/cloudformation/") or p not in failure["inputs"]
        for p in allowed
    ):
        raise Blocked("repair paths must be exact consumed CloudFormation IaC inputs")
    for name, entry in diagnosis.items():
        if (
            len(entry.get("reason", "").strip()) < 32
            or not entry.get("inputRefs")
            or not entry.get("modelRefs")
        ):
            raise Blocked(
                "repair diagnosis needs concrete cause and approved Model/input evidence: "
                + name
            )
        for field, prefix in (
            ("inputRefs", "infra/cloudformation/"),
            ("modelRefs", "model/"),
        ):
            for ref in entry[field]:
                relative = ref["path"]
                path = safe_path(root, relative)
                if (
                    not relative.startswith(prefix)
                    or failure["inputs"].get(relative) != ref["sha256"]
                    or sha(path) != ref["sha256"]
                ):
                    raise Blocked(
                        "diagnosis input/Model evidence is stale or outside current failure"
                    )
                if field == "modelRefs" and (
                    not ref.get("key", "").startswith("desired.")
                    or not re.search(
                        r"^" + re.escape(ref["key"]) + r"\s*=",
                        path.read_text(encoding="utf-8"),
                        re.M,
                    )
                ):
                    raise Blocked(
                        "diagnosis Model reference is not an authoritative desired entry"
                    )
    request = {
        k: copy.deepcopy(failure[k])
        for k in (
            "repository",
            "taskFile",
            "taskDigest",
            "target",
            "environment",
            "directory",
            "inputs",
        )
    }
    request.update(
        requestId=uuid.uuid4().hex,
        allowedPaths=allowed,
        validationScope=sorted(paths_in(task.text, "## Validation scope")),
        diagnosis=diagnosis,
        failureEvidence=str(failure_path),
    )
    require_settled(root, request)
    return request


def verify_inputs(
    root: Path,
    request: JsonObject,
    *,
    child_paths: Iterable[str] = (),
    contract_file: str | None = None,
) -> None:
    """A single request freezes approved design and non-delegated input bytes."""
    for relative, digest in request["inputs"].items():
        if relative in child_paths:
            continue
        path = safe_path(root, relative)
        if (sha(path) if path.is_file() else None) != digest:
            raise Blocked(
                "repair dependency changed outside delegated paths: " + relative
            )


def dependency_read(
    connection: tuple, operation: str, **arguments: JsonValue
) -> JsonObject:
    if operation not in {"list_exports", "list_imports"}:
        raise Blocked("repair dependency proof permits only Import/Export reads")
    return getattr(cloudformation, operation)(connection, **arguments)


def dependency_reader(root: Path, request: JsonObject) -> Callable[..., JsonObject]:
    target = context.check_deploy_context(
        root,
        request["environment"],
        request["target"]["awsAccountId"] if request["directory"].isdigit() else None,
        None if request["directory"].isdigit() else request["directory"],
    )
    if target != request["target"]:
        raise Blocked("repair target changed before dependency proof")
    return partial(
        dependency_read,
        connection_context(
            select_profile(target), target["awsRegion"], execution_account(target)
        ),
    )


def require_settled(
    root: Path, request: JsonObject, *, changed: Iterable[str] = ()
) -> None:
    """Caller holds Journal then Repair until request publication/checkpoint completes."""
    target = request["target"]
    stacks = set(request["diagnosis"])
    if not stacks:
        raise Blocked("repair request has no failed Stack scope")
    files = set(changed) | set(request["allowedPaths"])
    for entry in request["diagnosis"].values():
        files.update(
            ref["path"] for field in ("inputRefs", "modelRefs") for ref in entry[field]
        )
    records = operation_journal.read(operation_journal.location(target)) or []
    pending = {}
    for record in records:
        if operation_journal.target_identity(
            record["target"]
        ) != operation_journal.target_identity(target):
            raise Blocked("unfinished operation Account/Region changed")
        publication = record["publication"]
        if publication.get("pendingObserved") or publication.get("pendingGeneration"):
            owner = operation_journal.safe_path(publication["repository"])
            paths = operation_journal.publication_paths(publication)
            producers = set(publication.get("generationProducers", {}))
            observed = publication.get("pendingObserved")
            if observed:
                producers.update(observed["evidence"])
            for plan in publication.get("pendingGeneration", {}).values():
                producers.update(p["stack"] for p in plan["producers"])
            if not paths or not owner.is_dir():
                raise Blocked("unfinished publication scope/ownership is unknown")
            if (
                producers & stacks
                or operation_journal.same_repository(root, owner, require_known=True)
                and paths & files
            ):
                raise Blocked(
                    "unfinished publication conflicts with repair/checkpoint files or Producers"
                )
        pending.update(
            {
                name: op["state"]
                for name, op in record["operations"].items()
                if operation_journal.unfinished(op["state"])
            }
        )
    if not pending:
        return
    if pending.keys() & stacks:
        raise Blocked(
            "drain and synchronize unfinished operations before implement handoff"
        )
    _, units = inputs.load_units(
        root, request["environment"], request["directory"], sorted(stacks)
    )
    imports = {}
    for unit in units:
        template, parameters = inputs.paths(
            root, request["environment"], request["directory"], target, unit
        )
        if any(
            request["inputs"].get(p.relative_to(root).as_posix())
            != sha(safe_path(root, p.relative_to(root).as_posix()))
            for p in (template, parameters)
        ):
            raise Blocked("repair dependency inputs are not the current failure inputs")
        document, values = load_template_inputs(template, parameters)
        imports[unit["name"]] = change_sets.import_names(
            document,
            values,
            {
                "AWS::StackName": unit["name"],
                "AWS::Region": target["awsRegion"],
                "AWS::AccountId": target.get(
                    "awsExecutionAccountId", target["awsAccountId"]
                ),
            },
        )
    if imports.keys() != stacks:
        raise Blocked("repair dependency Stack scope is incomplete")
    operation_journal.require_independent(
        pending, stacks, dependency_reader(root, request), imports=imports
    )


def discard_request(state: JsonObject) -> None:
    """Delete only verified files owned by the delivered one-shot handoff."""
    request_path = state.get("deployRepair")
    if not request_path:
        return
    path = Path(request_path)
    if not path.exists():
        return
    envelope = __read_request_owner(path)
    parent = Path(envelope["repository"])
    with repair_lock(parent):
        expected = (
            evidence_store(parent)
            / ("deploy-repair-" + envelope["requestId"])
            / "request.json"
        )
        if (
            path != expected
            or not state.get("verified")
            or state.get("merged") != state.get("commit")
        ):
            raise Blocked("cannot discard an unverified handoff")
        result_path, validation_path = (
            path.with_name("result.json"),
            path.with_name("validation.json"),
        )
        result, validation = (
            read_sealed(parent, result_path),
            read_sealed(parent, validation_path),
        )
        if result.get("commit") != state["commit"] or any(
            value.get("requestId") != envelope["requestId"]
            for value in (result, validation)
        ):
            raise Blocked("handoff discard commit/request evidence changed")
        failure_path = external(parent, envelope["failureEvidence"])
        failure = read_sealed(parent, failure_path)
        if (
            failure["taskFile"] != envelope["taskFile"]
            or failure["taskDigest"] != envelope["taskDigest"]
        ):
            raise Blocked("handoff failure evidence changed")
        logs = [
            path.with_name(f"static-{number}.log")
            for number in range(1, state.get("repairStaticRuns", 0) + 1)
        ]
        owned = {path, result_path, validation_path, *logs}
        if set(path.parent.iterdir()) != owned or any(p.is_symlink() for p in owned):
            raise Blocked("unknown files in one-shot handoff need preservation")
        referenced = referenced_failures(parent, excluding=path)
        files = [*logs, validation_path, result_path, path]
        if failure_path not in referenced:
            operation_journal.private_path(failure_path)
            files.insert(0, failure_path)
        for file in files:
            file.unlink()
        path.parent.rmdir()


def __read_request_owner(path: Path) -> JsonObject:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    return read_sealed(Path(envelope["payload"]["repository"]), path)
