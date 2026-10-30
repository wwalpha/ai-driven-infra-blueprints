"""Human Reset/Fence resolution; immutable evidence survives independently of the journal."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable

from utils.aws.client import AwsError, connection_context, request
from utils.aws.identity import execution_account, select_profile
from utils.cloudformation.inputs import Blocked
from utils.file_operations import atomic_replace_file
from utils.json_format import fingerprint
from utils.project_targets import load_target
from utils.sealed_evidence import read_sealed, sealed
from utils.type_contracts import JsonObject

from deploy import lost_seal
from deploy import operation_journal as J
from deploy.context import check_deploy_context
from deploy.typing import Target

Document = JsonObject
IDENTIFIER = re.compile(r"[0-9a-f]{64}")
STACK_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,127}")
COMPLETE = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}


def digest(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def read_private(path: Path) -> bytes:
    """Retain the journal's owner/link protections across opening the actual file."""
    before = J.private_path(path)
    flags = os.O_RDONLY | (os.O_NOFOLLOW if os.name != "nt" else 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        value = stream.read()
        after = J.private_path(path)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or (
            opened.st_dev,
            opened.st_ino,
        ) != (after.st_dev, after.st_ino):
            raise Blocked("reset evidence file identity changed: " + str(path))
    return value


def directory(path: Path) -> Path:
    J.safe_path(path)
    path.mkdir(mode=0o700, exist_ok=True)
    J.private_path(path, directory=True)
    return path


def sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def save_once(path: Path, content: bytes) -> None:
    J.safe_path(path)
    if path.exists():
        if read_private(path) != content:
            raise Blocked(
                "reset evidence already exists with different bytes: " + str(path)
            )
        return
    atomic_replace_file(path, content, fsync=True, mode=0o600)
    sync_directory(path.parent)


def select(
    root: Path, environment: str, account: str | None, alias: str | None
) -> tuple[Target, Path, str]:
    root = J.safe_path(root)
    J.private_path(root / "project.json", permissions=0o022)
    target = load_target(root, environment, account, alias)
    if target["iacEngine"] != "cloudformation":
        raise Blocked("operation reset requires a CloudFormation target")
    journal = J.safe_path(J.location(target))
    return (
        target,
        journal,
        hashlib.sha256((root / "project.json").read_bytes()).hexdigest(),
    )


def templates(journal: Path) -> dict[str, str]:
    """Preserve all local input evidence even when the JSON cannot identify references."""
    result = {}
    for folder in sorted(journal.parent.glob("inputs-*")):
        J.private_path(folder, directory=True)
        for path in sorted(folder.iterdir()):
            result[path.relative_to(journal.parent).as_posix()] = hashlib.sha256(
                read_private(path)
            ).hexdigest()
    return result


def validated_records(journal: Path, target: Target) -> list[Document]:
    records = J.read(journal)
    if not records:
        raise Blocked("empty operation journal")
    for record in records:
        if J.target_identity(record["target"]) != J.target_identity(target):
            raise Blocked(
                "operation journal Account/Region differs from selected target"
            )
        publication = record["publication"]
        if not all(
            isinstance(publication.get(k), str) and publication[k]
            for k in ("repository", "taskFile", "taskDigest")
        ):
            raise Blocked("invalid operation journal publication identity")
        for key in ("pendingObserved", "pendingGeneration", "generationProducers"):
            if key in publication and not isinstance(publication[key], dict):
                raise Blocked("invalid operation journal shared publication")
        for name, operation in {
            **publication.get("generationProducers", {}),
            **record["operations"],
        }.items():
            if not isinstance(name, str) or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9-]{0,127}", name
            ):
                raise Blocked("invalid operation journal StackName")
            J.validate_operation(record["target"], name, operation)
    return records


def snapshot(
    root: Path,
    environment: str,
    account: str | None,
    alias: str | None,
    mode: str,
    selected: Iterable[str],
) -> tuple[Document, bytes]:
    target, journal, project_sha = select(root, environment, account, alias)
    if mode not in {"all", "record"}:
        raise Blocked("reset mode must be ALL or RECORD")
    requested = list(selected)
    if len(set(requested)) != len(requested) or any(
        not isinstance(item, str) or not IDENTIFIER.fullmatch(item)
        for item in requested
    ):
        raise Blocked("invalid or duplicate reset record ID")
    if (mode == "record" and not requested) or (mode == "all" and requested):
        raise Blocked("RECORD requires exact record IDs; ALL accepts no record IDs")
    if not journal.exists():
        raise Blocked("operation journal is absent; there is nothing to reset")
    raw = read_private(journal)
    records, summaries, error = [], [], None
    try:
        records = validated_records(journal, target)
        summaries = [
            {
                "id": fingerprint(record),
                "repository": record["publication"]["repository"],
                "taskFile": record["publication"]["taskFile"],
                "stacks": sorted(
                    record["operations"].keys()
                    | record["publication"].get("generationProducers", {}).keys()
                ),
                "generationProducers": sorted(
                    record["publication"].get("generationProducers", {})
                ),
                "operations": {
                    name: {
                        "status": operation["state"].get("status"),
                        "stackId": operation["state"].get("stackId"),
                        "changeSetId": operation["state"].get("changeSetId"),
                        "hasExecutionEvidence": bool(
                            operation["state"].get("executionEvidence")
                        ),
                        "observedSynced": bool(
                            operation["state"].get("observedSynced")
                        ),
                        "hasBootstrap": bool(operation["state"].get("bootstrap")),
                        "cleanupStatus": operation["state"].get("cleanupStatus"),
                    }
                    for name, operation in {
                        **record["publication"].get("generationProducers", {}),
                        **record["operations"],
                    }.items()
                },
                "publicationPaths": sorted(J.publication_paths(record["publication"])),
                "pendingObserved": bool(record["publication"].get("pendingObserved")),
                "pendingGeneration": bool(
                    record["publication"].get("pendingGeneration")
                ),
            }
            for record in records
        ]
    except (
        Blocked,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        OSError,
    ) as failure:
        # The original is still preserved byte-for-byte; no unverified field grants scope.
        records, summaries, error = [], [], type(failure).__name__
    if error and mode == "record":
        raise Blocked("RECORD reset requires a valid signed, structured journal")
    ids = {item["id"] for item in summaries}
    if not set(requested) <= ids:
        raise Blocked("requested reset record is not in this journal")
    chosen = ids if mode == "all" else set(requested)
    for summary in summaries:
        summary["selected"] = summary["id"] in chosen
    removed = [record for record in records if fingerprint(record) in chosen]
    retained = [record for record in records if fingerprint(record) not in chosen]
    replacement = J.records_text(retained)
    unknown = bool(error) or any(
        not record["operations"]
        and not record["publication"].get("generationProducers")
        for record in removed
    )
    value = {
        "version": 1,
        "repository": str(root),
        "environment": environment,
        "account": account,
        "alias": alias,
        "target": target,
        "journal": str(journal),
        "projectSha256": project_sha,
        "mode": mode,
        "selected": sorted(chosen),
        "beforeSha256": digest(raw),
        "afterSha256": digest(
            replacement.encode("utf-8") if replacement is not None else None
        ),
        "replacement": replacement,
        "validationError": error,
        "unknownScope": unknown,
        "records": summaries,
        "removedRecords": removed,
        "templates": templates(journal),
    }
    if read_private(journal) != raw:
        raise Blocked("operation journal snapshot changed during reset planning")
    value["id"] = fingerprint(value)
    return value, raw


def plan(
    root: Path,
    environment: str,
    account: str | None,
    alias: str | None,
    mode: str,
    records: Iterable[str] = (),
) -> Document:
    _, journal, _ = select(root, environment, account, alias)
    with J.locked(journal):
        value, _ = snapshot(root, environment, account, alias, mode, records)
        folder = directory(journal.parent / "reset-plans")
        save_once(
            folder / (value["id"] + ".json"),
            sealed(journal.parent, value).encode("utf-8"),
        )
        return value


def load_plan(journal: Path, identifier: str) -> Document:
    if not IDENTIFIER.fullmatch(identifier):
        raise Blocked("invalid reset Plan fingerprint")
    path = journal.parent / "reset-plans" / (identifier + ".json")
    J.private_path(path.parent, directory=True)
    read_private(path)
    value = read_sealed(journal.parent, path)
    verify_plan(value, identifier)
    return value


def verify_plan(value: object, identifier: str) -> None:
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != 1
        or value.get("id") != identifier
        or fingerprint({key: item for key, item in value.items() if key != "id"})
        != identifier
    ):
        raise Blocked("reset Plan fingerprint differs from its contents")


def report(value: Document) -> Document:
    return {
        key: item
        for key, item in value.items()
        if key not in {"replacement", "removedRecords"}
    } | {
        "warning": "Reset abandons recovery/publication information, including selected other Tasks. "
        "It proves no AWS, Observed, Model or generation success and approves no ChangeSet. "
        "Unverified scope requires separate Human investigation; Deploy remains fenced.",
    }


def challenge(value: Document) -> str:
    account, region = J.target_identity(value["target"])
    return f"RESET {account} {region} {value['mode'].upper()} {value['id']}"


def confirm(value: Document) -> Document:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Blocked("reset Apply requires a human-operated interactive console")
    print(json.dumps(report(value), ensure_ascii=False, indent=2))
    print(
        "Only the Human may choose and enter this approval. An LLM must never enter it."
    )
    expected = challenge(value)
    try:
        entered = input(
            "Confirm the displayed target, scope and Plan fingerprint by typing:\n"
            + expected
            + "\n> "
        )
    except EOFError as error:
        raise Blocked("Human reset approval cancelled") from error
    if entered != expected:
        raise Blocked("explicit Human reset approval does not match the Plan")
    return {
        "method": "interactive-console",
        "challenge": expected,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def archive(value: Document, raw: bytes, approval: Document) -> Path:
    journal = Path(value["journal"])
    active = directory(journal.parent / "resets")
    destination = J.safe_path(active / value["id"])
    if destination.exists():
        if verify_archive(journal, destination) != value:
            raise Blocked("reset archive differs from approved Plan")
        return destination
    folder = directory(directory(journal.parent / "reset-staging") / value["id"])
    sync_directory(folder.parent)
    save_once(folder / "plan.json", sealed(journal.parent, value).encode("utf-8"))
    save_once(folder / "original.bin", raw)
    if value["replacement"] is not None:
        save_once(folder / "replacement.bin", value["replacement"].encode("utf-8"))
    copied = directory(folder / "templates")
    for relative, expected in value["templates"].items():
        source = journal.parent / relative
        content = read_private(source)
        if digest(content) != expected:
            raise Blocked("reset template snapshot changed: " + relative)
        parent = directory(copied / source.parent.name)
        save_once(parent / source.name, content)
        sync_directory(copied)
    intent = folder / "intent.json"
    if intent.exists():
        prior = read_intent(journal, folder)
        if prior["plan"] != value["id"]:
            raise Blocked("reset intent differs from approved Plan")
    else:
        save_once(
            intent,
            sealed(
                journal.parent,
                {
                    "plan": value["id"],
                    "approval": approval,
                    "result": "PREPARED",
                },
            ).encode("utf-8"),
        )
    sync_directory(folder)
    verify_archive(journal, folder)
    # Activate the complete backup/fence together; incomplete copies cannot block Recover.
    os.replace(folder, destination)
    sync_directory(folder.parent)
    sync_directory(active)
    sync_directory(journal.parent)
    return destination


def read_intent(journal: Path, folder: Path) -> Document:
    J.private_path(folder, directory=True)
    intent = folder / "intent.json"
    read_private(intent)
    value = read_sealed(journal.parent, intent)
    if (
        not isinstance(value, dict)
        or set(value) != {"plan", "approval", "result"}
        or value["plan"] != folder.name
        or value["result"] != "PREPARED"
        or not isinstance(value["approval"], dict)
    ):
        raise Blocked("invalid reset intent; Human investigation required")
    return value


def verify_archive(journal: Path, folder: Path) -> Document:
    intent = read_intent(journal, folder)
    path = folder / "plan.json"
    read_private(path)
    value = read_sealed(journal.parent, path)
    verify_plan(value, folder.name)
    if intent["approval"].get("challenge") != challenge(value):
        raise Blocked("reset archive differs from approved Plan")
    if digest(read_private(folder / "original.bin")) != value["beforeSha256"]:
        raise Blocked("reset original evidence differs from its SHA-256")
    if (
        value["replacement"] is not None
        and digest(read_private(folder / "replacement.bin")) != value["afterSha256"]
    ):
        raise Blocked("reset replacement evidence differs from its SHA-256")
    for relative, expected in value["templates"].items():
        if digest(read_private(folder / "templates" / relative)) != expected:
            raise Blocked("reset template archive differs: " + relative)
    return value


def apply(
    root: Path,
    environment: str,
    account: str | None,
    alias: str | None,
    identifier: str,
) -> Document:
    target, journal, project_sha = select(root, environment, account, alias)
    with J.locked(journal):
        value = load_plan(journal, identifier)
        if (
            value["repository"] != str(root)
            or (value["environment"], value["account"], value["alias"])
            != (environment, account, alias)
            or value["target"] != target
            or value["projectSha256"] != project_sha
            or value["journal"] != str(journal)
        ):
            raise Blocked(
                "reset target/Repository configuration changed from approved Plan"
            )
        raw = read_private(journal) if journal.exists() else None
        folder = journal.parent / "resets" / identifier
        if digest(raw) != value["beforeSha256"]:
            if not folder.exists() or digest(raw) != value["afterSha256"]:
                raise Blocked("operation journal snapshot changed after Plan")
            verify_archive(journal, folder)
            confirm(value)
            save_once(
                folder / "result.json",
                sealed(
                    journal.parent,
                    {
                        "plan": identifier,
                        "result": "APPLIED",
                        "afterSha256": value["afterSha256"],
                    },
                ).encode("utf-8"),
            )
            return {
                "result": "ALREADY_APPLIED",
                "plan": identifier,
                "archive": str(folder),
            }
        current, raw = snapshot(
            root,
            environment,
            account,
            alias,
            value["mode"],
            value["selected"] if value["mode"] == "record" else (),
        )
        if current != value:
            raise Blocked("reset scope or template snapshot changed after Plan")
        approval = confirm(value)
        current, raw = snapshot(
            root,
            environment,
            account,
            alias,
            value["mode"],
            value["selected"] if value["mode"] == "record" else (),
        )
        if current != value:
            raise Blocked("reset snapshot changed during Human approval")
        folder = archive(value, raw, approval)
        verify_archive(journal, folder)
        # The durable intent is also the fence, and exists before the only journal mutation.
        current, _ = snapshot(
            root,
            environment,
            account,
            alias,
            value["mode"],
            value["selected"] if value["mode"] == "record" else (),
        )
        if current != value:
            raise Blocked("reset snapshot changed before journal replacement")
        if value["replacement"] is None:
            journal.unlink()
        else:
            atomic_replace_file(journal, value["replacement"], fsync=True, mode=0o600)
        sync_directory(journal.parent)
        save_once(
            folder / "result.json",
            sealed(
                journal.parent,
                {
                    "plan": identifier,
                    "result": "APPLIED",
                    "afterSha256": value["afterSha256"],
                },
            ).encode("utf-8"),
        )
        return {"result": "APPLIED", "plan": identifier, "archive": str(folder)}


def archives(journal: Path) -> list[tuple[Path, Document]]:
    folder = J.safe_path(journal.parent / "resets")
    if not folder.exists():
        return []
    J.private_path(folder, directory=True)
    result = []
    for path in sorted(folder.iterdir()):
        if not IDENTIFIER.fullmatch(path.name):
            raise Blocked(
                "unknown reset evidence; Human investigation required: " + str(path)
            )
        result.append((path, verify_archive(journal, path)))
    return result


def retained_templates(journal: Path) -> set[Path]:
    return {
        journal.parent / relative
        for _, value in archives(journal)
        for relative in value["templates"]
    }


def signed_document(journal: Path, path: Path) -> Document:
    J.private_path(path.parent, directory=True)
    read_private(path)
    return read_sealed(journal.parent, path)


def operations(value: Document) -> Iterable[tuple[str, Document]]:
    for record in value["removedRecords"]:
        yield from {
            **record["publication"].get("generationProducers", {}),
            **record["operations"],
        }.items()


def verified_completion(
    journal: Path,
    folder: Path,
    name: str,
    operation: Document,
) -> bool:
    identity = {
        "fence": folder.name,
        "stack": name,
        "operation": fingerprint(operation),
    }
    identifier = fingerprint(identity)
    intent = folder / ("verified-" + identifier + ".intent.json")
    result = folder / ("verified-" + identifier + ".json")
    if intent.exists() or result.exists():
        if signed_document(journal, intent) != identity:
            raise Blocked("reset fence verification intent changed: " + name)
        proof = signed_document(journal, result)
        if (
            proof.get("identity") != identity
            or proof.get("status") != "VERIFIED_COMPLETE"
            or proof.get("executionEvidence")
            != operation["state"].get("executionEvidence")
            or proof.get("stackId") != operation["state"].get("stackId")
            or not isinstance(operation["state"].get("expectedOutputs"), dict)
            or proof.get("expectedOutputs")
            != operation["state"].get("expectedOutputs", {})
            or proof.get("terminalStatus") not in COMPLETE
        ):
            raise Blocked("reset fence success evidence changed: " + name)
        return True
    return False


def completion(
    journal: Path,
    folder: Path,
    target: Target,
    name: str,
    operation: Document,
    backend: SimpleNamespace,
    *,
    resolved: bool = False,
) -> bool:
    """A receipt proves past completion, independently of the current Stack status."""
    J.validate_operation(target, name, operation)
    if verified_completion(journal, folder, name, operation):
        return True
    state = copy.deepcopy(operation["state"])
    if resolved:
        return False
    if not isinstance(state.get("expectedOutputs"), dict):
        return False
    if state.get("bootstrap") or state.get("cleanupStatus") == "DELETE_INTENT":
        return False
    # An external running operation has no original Execute token to certify.
    if state.get("externalOperation"):
        return False
    try:
        if state.get("executionEvidence"):
            status = backend.poll(operation["unit"], state)
            if status not in COMPLETE:
                return False
        elif not J.aws_unfinished(
            target, name, {**operation, "state": state}, backend.aws
        ):
            status = state.get("stackStatus")
            if status not in COMPLETE:
                return False
        else:
            return False
        stack = backend.aws("describe_stacks", StackName=state["stackId"])["Stacks"]
        if (
            len(stack) != 1
            or stack[0].get("StackId") != state["stackId"]
            or stack[0].get("StackStatus") != status
        ):
            return False
    except (Blocked, AwsError):
        return False
    # Persist the intent first: a missing/torn result can never silently become PENDING.
    identity = {
        "fence": folder.name,
        "stack": name,
        "operation": fingerprint(operation),
    }
    identifier = fingerprint(identity)
    intent = folder / ("verified-" + identifier + ".intent.json")
    result = folder / ("verified-" + identifier + ".json")
    save_once(intent, sealed(journal.parent, identity).encode("utf-8"))
    save_once(
        result,
        sealed(
            journal.parent,
            {
                "identity": identity,
                "status": "VERIFIED_COMPLETE",
                "executionEvidence": operation["state"].get("executionEvidence"),
                "stackId": operation["state"].get("stackId"),
                "terminalStatus": status,
                "expectedOutputs": operation["state"].get("expectedOutputs", {}),
            },
        ).encode("utf-8"),
    )
    return True


def resolution_challenge(value: Document) -> str:
    account, region = J.target_identity(value["target"])
    return f"RESOLVE {account} {region} {value['fence']} {','.join(value['stacks'])} {value['id']}"


def resolution_confirm(value: Document) -> Document:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Blocked("Fence Apply requires a human-operated interactive console")
    print(json.dumps(value, ensure_ascii=False, indent=2))
    print(
        "Only the Human may approve the scope and residual duplicate-execution risk. An LLM must never enter approval."
    )
    expected = resolution_challenge(value)
    try:
        entered = input(
            "Confirm the entire Fence Plan by typing:\n" + expected + "\n> "
        )
    except EOFError as error:
        raise Blocked("Human Fence approval cancelled") from error
    if entered != expected:
        raise Blocked("explicit Human Fence approval does not match the Plan")
    return {
        "method": "interactive-console",
        "challenge": expected,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def resolutions(journal: Path, folder: Path, value: Document) -> set[str]:
    path = J.safe_path(folder / "resolutions")
    if not path.exists():
        return set()
    J.private_path(path, directory=True)
    resolved: set[str] = set()
    for item in sorted(path.iterdir()):
        result = signed_document(journal, item)
        plan = result["plan"]
        verify_plan(plan, item.stem)
        if (
            item.name != plan["id"] + ".json"
            or plan["fence"] != folder.name
            or plan["archiveDigest"] != fingerprint(value)
            or plan["target"] != value["target"]
            or result.get("status") != "HUMAN_RESOLVED"
            or result["approval"].get("method") != "interactive-console"
            or result["approval"].get("challenge") != resolution_challenge(plan)
        ):
            raise Blocked("reset fence Human resolution evidence changed")
        resolved.update(plan["stacks"])
    return resolved


def fence_inventory(folder: Path) -> dict[str, str]:
    inventory = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise Blocked("unsafe reset fence snapshot path")
        if path.is_dir():
            J.private_path(path, directory=True)
        else:
            inventory[path.relative_to(folder).as_posix()] = digest(read_private(path))
    return inventory


def inspect_aws(
    aws: Callable[..., Document],
    target: Target,
    name: str,
    original: list[Document],
) -> Document:
    """Report only identities, statuses and evidence presence, never Output/secret values."""
    result: Document = {
        "stack": name,
        "originalEvidencePresent": bool(original),
        "operations": [],
    }
    try:
        response = aws("describe_stacks", StackName=name)
        stacks = response.get("Stacks")
        if (
            not isinstance(stacks, list)
            or len(stacks) != 1
            or response.get("NextToken")
        ):
            raise Blocked("incomplete Stack inventory")
        stack = stacks[0]
        J.validate_operation(
            target,
            name,
            {"unit": {"name": name}, "state": {"stackId": stack.get("StackId")}},
        )
        if not stack.get("StackId") or not isinstance(stack.get("StackStatus"), str):
            raise Blocked("incomplete Stack identity/status")
        result.update(stackId=stack["StackId"], stackStatus=stack["StackStatus"])
    except AwsError as error:
        result["stackStatus"] = "ABSENT" if error.stack_absent else "UNKNOWN"
        result["readError"] = error.code
    for operation in original:
        state = operation["state"]
        evidence = {
            "operation": fingerprint(operation),
            "stackId": state.get("stackId"),
            "changeSetId": state.get("changeSetId"),
            "hasExecutionEvidence": bool(state.get("executionEvidence")),
            "hasOutputRequirements": isinstance(state.get("expectedOutputs"), dict),
            "hasBootstrap": bool(state.get("bootstrap")),
            "cleanupStatus": state.get("cleanupStatus"),
            "status": "UNKNOWN",
        }
        if state.get("executionEvidence"):
            try:
                events = aws("describe_stack_events", StackName=state["stackId"])[
                    "StackEvents"
                ]
                matched = [
                    event
                    for event in events
                    if event.get("ResourceType") == "AWS::CloudFormation::Stack"
                    and event.get("ClientRequestToken") == state["clientToken"]
                    and event.get("StackId") == state["stackId"]
                ]
                if matched:
                    evidence["status"] = matched[0].get("ResourceStatus", "UNKNOWN")
            except (AwsError, KeyError, TypeError) as error:
                evidence["readError"] = type(error).__name__
        result["operations"].append(evidence)
    return result


def resolution_snapshot(
    root: Path,
    environment: str,
    account: str | None,
    alias: str | None,
    identifier: str,
    stacks: Iterable[str],
    risk: str,
    aws: Callable[..., Document],
) -> Document:
    target, journal, project_sha = select(root, environment, account, alias)
    selected = sorted(stacks)
    if (
        not IDENTIFIER.fullmatch(identifier)
        or not selected
        or len(set(selected)) != len(selected)
        or any(
            not isinstance(name, str) or not STACK_NAME.fullmatch(name)
            for name in selected
        )
        or not risk.strip()
    ):
        raise Blocked(
            "Fence Plan requires exact reset ID, unique StackNames and explicit residual risk"
        )
    folder = J.safe_path(journal.parent / "resets" / identifier)
    value = verify_archive(journal, folder)
    if J.target_identity(value["target"]) != J.target_identity(target):
        raise Blocked("Fence target Account/Region differs")
    original = list(operations(value))
    if not value["unknownScope"] and not set(selected) <= {
        name for name, _ in original
    }:
        raise Blocked("Fence Stack scope does not match the reset archive")
    resolved = resolutions(journal, folder, value)
    before = fence_inventory(folder)
    observations = [
        inspect_aws(aws, target, name, [op for stack, op in original if stack == name])
        for name in selected
    ]
    if before != fence_inventory(folder):
        raise Blocked("Fence evidence snapshot changed during inspection")
    result = {
        "version": 1,
        "repository": str(root),
        "environment": environment,
        "account": account,
        "alias": alias,
        "target": target,
        "journal": str(journal),
        "projectSha256": project_sha,
        "fence": identifier,
        "archiveDigest": fingerprint(value),
        "stacks": selected,
        "snapshot": before,
        "journalSha256": digest(read_private(journal)) if journal.exists() else None,
        "aws": observations,
        "residualRisk": risk,
        "status": "PENDING",
        "unknownScope": value["unknownScope"],
        "history": [
            {
                "stack": name,
                "operation": fingerprint(operation),
                "status": "VERIFIED_COMPLETE"
                if verified_completion(journal, folder, name, operation)
                else "HUMAN_RESOLVED"
                if name in resolved
                else "PENDING",
            }
            for name, operation in original
        ],
        "warning": "Original scope/evidence may be lost. Current successful or absent Stacks do not prove the old Execute completed. Duplicate execution remains possible. Human exception approval is not machine-verified safety; only these Stacks in this Fence are resolved. Other scope remains fenced. No Deploy starts automatically.",
    }
    result["id"] = fingerprint(result)
    return result


def resolution_plan(
    root: Path,
    environment: str,
    account: str | None,
    alias: str | None,
    identifier: str,
    stacks: Iterable[str],
    risk: str,
    aws: Callable[..., Document],
) -> Document:
    _, journal, _ = select(root, environment, account, alias)
    with J.locked(journal):
        value = resolution_snapshot(
            root, environment, account, alias, identifier, stacks, risk, aws
        )
        folder = directory(journal.parent / "fence-plans")
        save_once(
            folder / (value["id"] + ".json"),
            sealed(journal.parent, value).encode("utf-8"),
        )
        return value


def resolution_apply(
    root: Path,
    environment: str,
    account: str | None,
    alias: str | None,
    identifier: str,
    aws: Callable[..., Document],
) -> Document:
    _, journal, _ = select(root, environment, account, alias)
    with J.locked(journal):
        if not IDENTIFIER.fullmatch(identifier):
            raise Blocked("invalid Fence Plan fingerprint")
        value = signed_document(
            journal, journal.parent / "fence-plans" / (identifier + ".json")
        )
        verify_plan(value, identifier)
        current = resolution_snapshot(
            root,
            environment,
            account,
            alias,
            value["fence"],
            value["stacks"],
            value["residualRisk"],
            aws,
        )
        if value != current:
            raise Blocked("Fence target or snapshot changed after Plan")
        if any(
            item["stackStatus"].endswith("_IN_PROGRESS")
            or any(op["status"].endswith("_IN_PROGRESS") for op in item["operations"])
            for item in value["aws"]
        ):
            raise Blocked("Fence retains a known running AWS operation")
        approval = resolution_confirm(value)
        if current != resolution_snapshot(
            root,
            environment,
            account,
            alias,
            value["fence"],
            value["stacks"],
            value["residualRisk"],
            aws,
        ):
            raise Blocked("Fence snapshot changed during Human approval")
        folder = directory(journal.parent / "resets" / value["fence"] / "resolutions")
        save_once(
            folder / (identifier + ".json"),
            sealed(
                journal.parent,
                {
                    "plan": value,
                    "approval": approval,
                    "status": "HUMAN_RESOLVED",
                },
            ).encode("utf-8"),
        )
        return {
            "status": "HUMAN_RESOLVED",
            "fence": value["fence"],
            "stacks": value["stacks"],
            "plan": identifier,
        }


def read_fence_aws(connection: tuple, operation: str, **arguments: object) -> Document:
    if operation not in {"describe_stacks", "describe_stack_events"}:
        raise Blocked("Fence inspection permits only read-only Stack evidence")
    return request(connection, "cloudformation", operation, arguments)


def check_fences(
    journal: Path, target: Target, scope: Iterable[str], backend: SimpleNamespace
) -> None:
    if lost_seal.approved(journal, backend, scope):
        backend.reset_pending = []
        return
    selected = set(scope)
    pending = []
    for folder, value in archives(journal):
        if J.target_identity(value["target"]) != J.target_identity(target):
            raise Blocked("reset fence Account/Region differs from Deploy")
        resolved = resolutions(journal, folder, value)
        if value["unknownScope"] and selected - resolved:
            raise Blocked(
                "reset fence has unknown AWS execution scope; separate Human investigation required: "
                + str(folder)
            )
        for name, operation in operations(value):
            # Even Human resolution cannot hide damaged previously verified success evidence.
            verified = completion(
                journal,
                folder,
                value["target"],
                name,
                operation,
                backend,
                resolved=name in resolved,
            )
            if verified or name in resolved:
                continue
            if name in selected:
                raise Blocked(
                    "reset fence AWS execution is unfinished or unknown; Human investigation required: "
                    + name
                )
            pending.append({name: operation["state"]})
    backend.reset_pending = pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "plan",
            "apply",
            "fence-plan",
            "fence-apply",
            "lost-key-plan",
            "lost-key-apply",
        ),
    )
    parser.add_argument("--environment", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--aws-account-id")
    selector.add_argument("--alias")
    parser.add_argument("--mode", choices=("record", "all"))
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument("--fence", help="exact Reset archive fingerprint to resolve")
    parser.add_argument("--stack", action="append", default=[])
    parser.add_argument(
        "--risk",
        help="Human-specified impact scope and residual duplicate-execution risk",
    )
    parser.add_argument("--profile")
    parser.add_argument(
        "--plan", help="exact Plan SHA-256 fingerprint returned by plan"
    )
    args = parser.parse_args(argv)
    try:
        root = Path.cwd()
        if args.action.startswith(("fence-", "lost-key-")):
            if args.mode or args.record:
                raise Blocked(
                    "Fence operations accept no Reset mode or record selection"
                )
            if args.action == "fence-plan":
                if args.plan or not args.fence or not args.stack or not args.risk:
                    raise Blocked(
                        "fence-plan requires --fence, --stack and --risk; accepts no --plan"
                    )
            elif args.action == "fence-apply" and (
                not args.plan or args.fence or args.stack or args.risk
            ):
                raise Blocked(
                    "fence-apply requires --plan; scope comes only from that Plan"
                )
            if args.action.startswith("lost-key-") and args.fence:
                raise Blocked(
                    "lost-key recovery accepts no --fence; every archive is frozen"
                )
            target = check_deploy_context(
                root, args.environment, args.aws_account_id, args.alias, args.profile
            )
            aws = partial(
                read_fence_aws,
                connection_context(
                    select_profile(target, args.profile),
                    target["awsRegion"],
                    execution_account(target),
                ),
            )
            if args.action.startswith("lost-key-"):
                result = lost_seal.run(args, root, aws)
            elif args.action == "fence-plan":
                result = resolution_plan(
                    root,
                    args.environment,
                    args.aws_account_id,
                    args.alias,
                    args.fence,
                    args.stack,
                    args.risk,
                    aws,
                )
            else:
                result = resolution_apply(
                    root,
                    args.environment,
                    args.aws_account_id,
                    args.alias,
                    args.plan,
                    aws,
                )
        elif args.fence or args.stack or args.risk or args.profile:
            raise Blocked("Reset plan/apply accept no Fence scope or profile")
        elif args.action == "plan":
            if args.plan or not args.mode:
                raise Blocked("plan requires --mode and accepts no --plan")
            result = report(
                plan(
                    root,
                    args.environment,
                    args.aws_account_id,
                    args.alias,
                    args.mode,
                    args.record,
                )
            )
        else:
            if not args.plan or args.mode or args.record:
                raise Blocked("apply requires --plan; scope comes only from that Plan")
            result = apply(
                root, args.environment, args.aws_account_id, args.alias, args.plan
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        IndexError,
    ) as error:
        print(f"Operation reset: BLOCKED: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "Operation reset cancelled; inspect the retained Plan and archive before retry.",
            file=sys.stderr,
        )
        return 130
