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

from deploy import (
    change_sets,
    context,
    current_request,
    current_state,
    inputs,
    operation_journal,
)


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
    if any(evidence_store(root).glob("deploy-cleanup-*")):
        raise Blocked(
            "repair evidence cleanup is incomplete; retain temporary templates"
        )
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
                if (
                    template.is_absolute()
                    and not any(p.is_symlink() for p in (template, *template.parents))
                    and template.resolve().is_relative_to(root.resolve())
                ):
                    continue
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
    if operation not in {
        "describe_stacks",
        "describe_stack_events",
        "describe_change_set",
        "get_template",
        "list_exports",
        "list_imports",
    }:
        raise Blocked("repair dependency proof permits only Import/Export reads")
    if operation in {"describe_stacks", "describe_stack_events"} and not arguments.get(
        "StackName"
    ):
        raise Blocked("repair dependency proof requires a scoped StackName")
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
    journal_path = operation_journal.location(target)
    if journal_path.exists() and json.loads(journal_path.read_bytes()) == {
        "protocol": "current-request-v2"
    }:
        reader = dependency_reader(root, request)
        for name in sorted(stacks):
            path = current_request.location(target, name)
            with operation_journal.locked(path):
                current = current_state.read(reader, name)
                record = current_request.read(path)
                if current_state.category(current) in {"RUNNING", "UNKNOWN"}:
                    raise Blocked("repair target AWS operation is not settled: " + name)
                if record:
                    if not current_request.settled(reader, record, current):
                        raise Blocked("repair target request is not settled: " + name)
                    path.unlink()
        return
    records = operation_journal.read(journal_path) or []
    pending = {}
    reader = None
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
        for name, op in record["operations"].items():
            if not operation_journal.unfinished(op["state"]):
                continue
            reader = reader or dependency_reader(root, request)
            if operation_journal.aws_unfinished(target, name, op, reader):
                pending[name] = op["state"]
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
        pending, stacks, reader or dependency_reader(root, request), imports=imports
    )


def discard_request(state: JsonObject) -> None:
    """Invalidate atomically, then retry only the sealed, verified deletion plan."""
    request_path = state.get("deployRepair")
    if not request_path:
        return
    path = operation_journal.safe_path(request_path)
    if (
        path.name != "request.json"
        or not re.fullmatch(r"deploy-repair-[a-zA-Z0-9-]+", path.parent.name)
        or not state.get("verified")
        or not state.get("commit")
        or state.get("merged") != state["commit"]
    ):
        raise Blocked("cannot discard an unverified handoff")
    request_id = path.parent.name.removeprefix("deploy-repair-")
    directory = path.parent.with_name("deploy-cleanup-" + request_id)
    receipt = directory.with_suffix(".json")
    operation_journal.safe_path(directory)
    operation_journal.safe_path(receipt)
    owner = path if path.exists() else receipt
    if not owner.exists():
        if path.parent.exists() or directory.exists():
            raise Blocked("handoff cleanup ownership evidence is missing")
        return
    operation_journal.private_path(owner)
    parent = Path(__read_request_owner(owner)["repository"])
    with repair_lock(parent):
        if path != evidence_store(parent) / path.parent.name / "request.json":
            raise Blocked("handoff cleanup ownership changed")
        if path.exists():
            if directory.exists():
                raise Blocked("active and invalidated handoff both exist")
            plan = __discard_plan(parent, path, state)
            if receipt.exists():
                operation_journal.private_path(receipt)
                if read_sealed(parent, receipt) != plan:
                    raise Blocked("handoff cleanup plan changed")
            else:
                write_sealed(parent, receipt, plan)
            # The active request and all its references disappear in one rename.
            path.parent.rename(directory)
        elif path.parent.exists():
            raise Blocked("active handoff ownership evidence is missing")
        __finish_discard(parent, path, directory, receipt, state)


def __discard_plan(parent: Path, path: Path, state: JsonObject) -> JsonObject:
    operation_journal.private_path(path.parent, directory=True, permissions=0o022)
    for file in (
        path,
        path.with_name("result.json"),
        path.with_name("validation.json"),
    ):
        operation_journal.private_path(file)
    request, result, validation = (
        read_sealed(parent, file)
        for file in (
            path,
            path.with_name("result.json"),
            path.with_name("validation.json"),
        )
    )
    if (
        request["repository"] != str(parent)
        or path.parent.name != "deploy-repair-" + request["requestId"]
        or result.get("commit") != state["commit"]
        or any(
            value.get("requestId") != request["requestId"]
            for value in (result, validation)
        )
    ):
        raise Blocked("handoff discard commit/request evidence changed")
    failure_path = external(parent, request["failureEvidence"])
    operation_journal.private_path(failure_path)
    failure = read_sealed(parent, failure_path)
    if (
        failure_path.parent != evidence_store(parent)
        or not re.fullmatch(r"deploy-failure-[a-zA-Z0-9-]+\.json", failure_path.name)
        or failure.get("repository") != str(parent)
        or failure["taskFile"] != request["taskFile"]
        or failure["taskDigest"] != request["taskDigest"]
    ):
        raise Blocked("handoff failure evidence changed")
    names = [
        *(
            f"static-{number}.log"
            for number in range(1, state.get("repairStaticRuns", 0) + 1)
        ),
        "validation.json",
        "result.json",
        "request.json",
    ]
    if {file.name for file in path.parent.iterdir()} != set(names):
        raise Blocked("unknown files in one-shot handoff need preservation")
    for name in names:
        operation_journal.private_path(path.with_name(name), permissions=0o022)
    referenced_failures(parent, excluding=path)
    return {
        "repository": str(parent),
        "requestId": request["requestId"],
        "requestPath": str(path),
        "commit": state["commit"],
        "files": {name: sha(path.with_name(name)) for name in names},
        "failureEvidence": str(failure_path),
        "failureDigest": sha(failure_path),
    }


def __finish_discard(
    parent: Path, path: Path, directory: Path, receipt: Path, state: JsonObject
) -> None:
    operation_journal.private_path(receipt)
    plan = read_sealed(parent, receipt)
    if (
        plan["repository"] != str(parent)
        or plan["requestPath"] != str(path)
        or directory.name != "deploy-cleanup-" + plan["requestId"]
        or plan["commit"] != state["commit"]
    ):
        raise Blocked("handoff cleanup commit/request evidence changed")
    failure = external(parent, plan["failureEvidence"])
    if failure.parent != evidence_store(parent) or not re.fullmatch(
        r"deploy-failure-[a-zA-Z0-9-]+\.json", failure.name
    ):
        raise Blocked("handoff cleanup failure ownership changed")
    if failure.exists():
        operation_journal.private_path(failure)
        read_sealed(parent, failure)
        if sha(failure) != plan["failureDigest"]:
            raise Blocked("handoff cleanup failure evidence changed")
    if directory.exists():
        operation_journal.private_path(directory, directory=True, permissions=0o022)
        files = list(directory.iterdir())
        for file in files:
            operation_journal.private_path(file, permissions=0o022)
            if file.name not in plan["files"] or sha(file) != plan["files"][file.name]:
                raise Blocked("unknown files or changed handoff cleanup evidence")
        referenced = referenced_failures(parent)
        for name in plan["files"]:
            file = directory / name
            if file.exists():
                file.unlink()
        if failure.exists() and failure not in referenced:
            failure.unlink()
        directory.rmdir()
    # Keep authentication through rmdir, including an interrupted empty-directory cleanup.
    receipt.unlink()


def __read_request_owner(path: Path) -> JsonObject:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    return read_sealed(Path(envelope["payload"]["repository"]), path)
