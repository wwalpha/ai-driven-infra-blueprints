"""One approved, resumable Reset for selected recovery records and related old Fences."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from utils.cloudformation.inputs import Blocked
from utils.file_operations import atomic_replace_file
from utils.json_format import fingerprint
from utils.project_targets import load_target
from utils.sealed_evidence import read_sealed, sealed
from utils.type_contracts import JsonObject

from deploy import operation_journal as J
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


def inventory(journal):
    """Read raw selected files; damaged historical JSON is still resettable."""
    found = {}
    if journal.exists():
        found[journal.name] = read_private(journal)
    for path in sorted(journal.parent.glob("request-*.json")):
        found[path.name] = read_private(path)
    for folder in sorted((journal.parent / "resets").glob("*")):
        if not folder.is_dir() or (folder / "reset-v2.json").exists():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                found[path.relative_to(journal.parent).as_posix()] = read_private(path)
    return found


def related_stacks(raw):
    try:
        document = json.loads(raw)
        payload = document.get("payload", document)
        records = payload.get("removedRecords", [])
        return (
            {payload["name"]}
            if isinstance(payload.get("name"), str)
            else {
                name
                for record in records
                if isinstance(record, dict)
                for name in record.get("operations", {})
            }
        )
    except (ValueError, AttributeError, TypeError):
        return set()


def snapshot(root, environment, account, alias, mode, selected):
    target, journal, project_sha = select(root, environment, account, alias)
    requested = set(selected)
    if (
        mode not in {"all", "record"}
        or mode == "record"
        and not requested
        or mode == "all"
        and requested
    ):
        raise Blocked("Reset requires ALL or exact RECORD IDs")
    files = inventory(journal)
    summaries, names, replacement = [], set(), None
    originals = dict(files)
    records = []
    if journal.exists():
        try:
            records = J.read(journal) or []
        except (OSError, ValueError, KeyError, TypeError, Blocked):
            records = []
    for record in records:
        identifier = fingerprint(record)
        chosen = mode == "all" or identifier in requested
        stacks = sorted(record.get("operations", {}))
        summaries.append({"id": identifier, "stacks": stacks, "selected": chosen})
        if chosen:
            names.update(stacks)
    if mode == "record":
        groups = {}
        for relative, raw in files.items():
            if relative == journal.name:
                continue
            identifier = (
                relative.split("/")[1]
                if relative.startswith("resets/")
                else fingerprint(raw.hex())
            )
            group = groups.setdefault(identifier, {"files": {}, "stacks": set()})
            group["files"][relative] = raw
            group["stacks"].update(related_stacks(raw))
        known = {item["id"] for item in summaries} | groups.keys()
        if not records and journal.name in files:
            raw_id = fingerprint(files[journal.name].hex())
            known.add(raw_id)
            if raw_id in requested:
                replacement = json.dumps({"protocol": "current-request-v2"})
        if not requested <= known:
            raise Blocked("Reset selection is not in the current inventory")
        chosen = set(requested)
        previous = None
        while previous != (chosen, names):
            previous = (set(chosen), set(names))
            for record in records:
                identifier = fingerprint(record)
                stacks = set(record.get("operations", {}))
                if identifier in chosen or stacks & names:
                    chosen.add(identifier)
                    names.update(stacks)
            for identifier, group in groups.items():
                if identifier in chosen or group["stacks"] & names:
                    chosen.add(identifier)
                    names.update(group["stacks"])
        selected_files = {
            relative: raw
            for identifier, group in groups.items()
            if identifier in chosen
            for relative, raw in group["files"].items()
        }
        if records and any(fingerprint(record) in chosen for record in records):
            selected_files[journal.name] = files[journal.name]
            replacement = J.records_text(
                [record for record in records if fingerprint(record) not in chosen]
            )
        elif (
            not records
            and journal.name in files
            and fingerprint(files[journal.name].hex()) in chosen
        ):
            selected_files[journal.name] = files[journal.name]
        for item in summaries:
            item["selected"] = item["id"] in chosen
        files = selected_files
    if not files:
        raise Blocked("no selected recovery records or Fences")
    for relative, raw in files.items():
        if relative != journal.name:
            summaries.append(
                {
                    "id": relative.split("/")[1]
                    if relative.startswith("resets/")
                    else fingerprint(raw.hex()),
                    "path": relative,
                    "sha256": digest(raw),
                    "selected": True,
                }
            )
    value = {
        "version": 2,
        "repository": str(root),
        "environment": environment,
        "account": account,
        "alias": alias,
        "target": target,
        "projectSha256": project_sha,
        "journal": str(journal),
        "mode": mode,
        "selected": sorted(requested),
        "files": {relative: digest(raw) for relative, raw in files.items()},
        "replacement": replacement
        if replacement is not None
        else json.dumps({"protocol": "current-request-v2"})
        if journal.name in files
        else None,
        "records": summaries,
    }
    if any(inventory(journal).get(relative) != raw for relative, raw in files.items()):
        raise Blocked("Reset inventory changed during planning")
    value["id"] = fingerprint(value)
    return value, originals


def plan(root, environment, account, alias, mode, records=()):
    _, journal, _ = select(root, environment, account, alias)
    with J.locked(journal):
        value, originals = snapshot(root, environment, account, alias, mode, records)
        folder = directory(journal.parent / "reset-plans")
        archive = directory(folder / (value["id"] + ".originals"))
        for relative in value["files"]:
            destination = archive / relative
            for parent in reversed(destination.parents):
                if parent == archive or parent.is_relative_to(archive):
                    directory(parent)
            save_once(destination, originals[relative])
        save_once(
            folder / (value["id"] + ".json"),
            sealed(journal.parent, value).encode("utf-8"),
        )
        return value


def load_plan(journal, identifier):
    if not IDENTIFIER.fullmatch(identifier):
        raise Blocked("invalid Reset Plan ID")
    value = read_sealed(
        journal.parent, journal.parent / "reset-plans" / (identifier + ".json")
    )
    if (
        value.get("version") != 2
        or value.get("id") != identifier
        or fingerprint({key: item for key, item in value.items() if key != "id"})
        != identifier
    ):
        raise Blocked("Reset Plan differs from its approved contents")
    return value


def report(value):
    return {key: item for key, item in value.items() if key != "replacement"} | {
        "warning": "Reset discards only the listed recovery information and related Fences. It does not stop AWS or certify AWS, Model, snapshot or Git success."
    }


def challenge(value):
    account, region = J.target_identity(value["target"])
    return f"RESET {account} {region} {value['mode'].upper()} {value['id']}"


def confirm(value):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Blocked(
            "Reset requires explicit Human approval in an interactive console"
        )
    print(json.dumps(report(value), ensure_ascii=False, indent=2))
    expected = challenge(value)
    entered = input(
        "Only the Human may enter this approval. Type:\n" + expected + "\n> "
    )
    if entered != expected:
        raise Blocked("Human Reset approval does not match the Plan")
    return {
        "method": "interactive-console",
        "challenge": expected,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def apply(root, environment, account, alias, identifier):
    target, journal, _ = select(root, environment, account, alias)
    with J.locked(journal):
        value = load_plan(journal, identifier)
        if (
            value["repository"] != str(root)
            or value["target"] != target
            or value["journal"] != str(journal)
            or (value["environment"], value["account"], value["alias"])
            != (environment, account, alias)
        ):
            raise Blocked("Reset target changed from the approved Plan")
        folder = directory(directory(journal.parent / "resets") / identifier)
        # Mark this as a Reset transaction, never as a new live Fence.
        save_once(
            folder / "reset-v2.json", sealed(journal.parent, value).encode("utf-8")
        )
        approval_path = folder / "approval.json"
        if approval_path.exists():
            approval = read_sealed(journal.parent, approval_path)
            if approval.get("challenge") != challenge(value):
                raise Blocked("saved approval does not match this Reset")
        else:
            current = inventory(journal)
            if any(
                digest(current.get(relative)) != expected
                for relative, expected in value["files"].items()
            ):
                raise Blocked("Reset targets changed since planning")
            approval = confirm(value)
            save_once(approval_path, sealed(journal.parent, approval).encode("utf-8"))
        originals = directory(folder / "originals")
        for relative, expected in value["files"].items():
            source = J.safe_path(journal.parent / relative)
            destination = originals / relative
            for parent in reversed(destination.parents):
                if parent == originals or parent.is_relative_to(originals):
                    directory(parent)
            if destination.exists():
                if digest(read_private(destination)) != expected:
                    raise Blocked("Reset original backup changed: " + relative)
                continue
            original = (
                journal.parent / "reset-plans" / (identifier + ".originals") / relative
            )
            raw = read_private(original)
            if digest(raw) != expected:
                raise Blocked("Reset target changed before backup: " + relative)
            save_once(destination, raw)
        # Only after every original is durable may any target be processed.
        save_once(
            folder / "prepared.json",
            sealed(journal.parent, {"plan": identifier}).encode("utf-8"),
        )
        result = folder / "result.json"
        if result.exists():
            return {
                "result": "ALREADY_APPLIED",
                "plan": identifier,
                "archive": str(folder),
            }
        for relative, expected in value["files"].items():
            source = J.safe_path(journal.parent / relative)
            with J.locked(source) if relative.startswith("request-") else nullcontext():
                raw = read_private(source) if source.exists() else None
                replacement = (
                    value["replacement"].encode("utf-8")
                    if relative == journal.name and value["replacement"] is not None
                    else None
                )
                if raw == replacement:
                    continue
                if digest(raw) != expected:
                    # A new request/record is outside this approval, including on a crash retry.
                    continue
                if replacement is None:
                    source.unlink()
                else:
                    atomic_replace_file(source, replacement, fsync=True, mode=0o600)
                sync_directory(source.parent)
        save_once(
            result,
            sealed(journal.parent, {"plan": identifier, "result": "APPLIED"}).encode(
                "utf-8"
            ),
        )
        return {"result": "APPLIED", "plan": identifier, "archive": str(folder)}


def retained_templates(journal):
    return {
        path
        for folder in (journal.parent / "resets").glob("*")
        for path in folder.rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".template"}
    }


def check_fences(journal, target, scope, backend):
    """Compatibility entrance; historical Fences never gate current-state Deploy."""


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reset selected recovery records and related Fences once; never changes AWS."
    )
    parser.add_argument(
        "action", choices=("plan", "apply", "fence-plan", "fence-apply")
    )
    parser.add_argument("--environment", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--aws-account-id")
    selector.add_argument("--alias")
    parser.add_argument("--mode", choices=("record", "all"))
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument(
        "--fence", help="legacy Fence ID; processed by the same one-step Reset"
    )
    parser.add_argument(
        "--stack", action="append", default=[], help="compatibility display scope"
    )
    parser.add_argument("--risk", help="compatibility Human risk description")
    parser.add_argument("--profile", help="unused: Reset makes no AWS calls")
    parser.add_argument(
        "--plan", help="exact approved Reset Plan ID, also used for interrupted retries"
    )
    args = parser.parse_args(argv)
    try:
        if args.action in {"plan", "fence-plan"}:
            if args.plan:
                raise Blocked("plan accepts no --plan")
            mode = "record" if args.fence else args.mode
            selection = [args.fence] if args.fence else args.record
            result = report(
                plan(
                    Path.cwd(),
                    args.environment,
                    args.aws_account_id,
                    args.alias,
                    mode,
                    selection,
                )
            )
        else:
            if not args.plan:
                raise Blocked("apply requires --plan")
            result = apply(
                Path.cwd(), args.environment, args.aws_account_id, args.alias, args.plan
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Operation reset: BLOCKED: {error}", file=sys.stderr)
        return 2
