"""One-shot repair evidence; no Deploy history, workflow registry or retry inheritance."""

import copy
import json
import re
import sys
import uuid
from collections.abc import Iterable
from contextlib import AbstractContextManager
from pathlib import Path
from types import SimpleNamespace

from task_contract_core import paths_in, safe_path, task_snapshot
from utils.cloudformation.inputs import Blocked
from utils.file_operations import sha
from utils.sealed_evidence import evidence_store, read_sealed, write_sealed
from utils.type_contracts import JsonObject
from utils.type_contracts import JsonValue as JsonValue

from deploy import operation_journal


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
    discard_unused_failures(
        backend.root, backend.run_context["taskFile"], backend.run_context["taskDigest"]
    )
    path = evidence_store(backend.root) / (
        "deploy-failure-" + uuid.uuid4().hex + ".json"
    )
    context = backend.run_context
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


def discard_unused_failures(root: Path, task_file: str, task_digest: str) -> None:
    with repair_lock(root):
        store = evidence_store(root)
        referenced = set()
        # An unreadable request may own any failure: preserve rather than guess.
        for path in store.glob("deploy-repair-*/request.json"):
            try:
                request = read_sealed(root, external(root, path))
                referenced.add(request["failureEvidence"])
            except (Blocked, OSError, ValueError, KeyError, TypeError) as error:
                print(
                    f"Deploy failure evidence retained: {path}: {error}",
                    file=sys.stderr,
                )
                return
        for path in store.glob("deploy-failure-*.json"):
            if str(path) in referenced:
                continue
            try:
                failure = read_sealed(root, external(root, path))
                if (
                    failure["repository"],
                    failure["taskFile"],
                    failure["taskDigest"],
                ) == (
                    str(root),
                    task_file,
                    task_digest,
                ):
                    path.unlink()
            except (Blocked, OSError, ValueError, KeyError, TypeError) as error:
                print(
                    f"Deploy failure evidence retained: {path}: {error}",
                    file=sys.stderr,
                )


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
    require_settled(root, failure["target"])
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


def require_settled(root: Path, target: dict[str, str]) -> None:
    records = operation_journal.read(operation_journal.location(target)) or []
    for record in records:
        require_record_settled(record)


def require_record_settled(record: JsonObject) -> None:
    if (
        record["publication"].get("pendingObserved")
        or any(
            item["generated"]["outputs"] is not None
            for item in record["publication"].get("pendingGeneration", {}).values()
        )
        or any(
            op["state"].get("status") == "RUNNING"
            or op["state"].get("status") == "SUCCESS"
            and not op["state"].get("observedSynced")
            or op["state"].get("bootstrap")
            or op["state"].get("cleanupStatus") == "DELETE_INTENT"
            for op in record["operations"].values()
        )
    ):
        raise Blocked(
            "drain and synchronize unfinished operations before implement handoff"
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
        for file in [*logs, validation_path, result_path, failure_path, path]:
            file.unlink()
        path.parent.rmdir()


def __read_request_owner(path: Path) -> JsonObject:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    return read_sealed(Path(envelope["payload"]["repository"]), path)
