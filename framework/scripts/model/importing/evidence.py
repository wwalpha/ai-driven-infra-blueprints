"""Versioned Import acquisition and temporary evidence retention."""

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import import_guard as _imports_import_guard
from contracts.target import (
    AWS_ACCOUNT_ID_KEY,
    AWS_EXECUTION_ACCOUNT_ID_KEY,
    AWS_REGION_KEY,
)
from utils.json_format import json_text
from utils.local_evidence import private, read_sealed, write_sealed
from utils.local_evidence import shared_store as evidence_store

import model.importing.inventory as _imports_model_importing_inventory
import model.importing.limitations as limitations
import model.importing.repository as _imports_model_importing_repository
from model.format import FORMAT_FIELDS as FORMAT_FIELDS
from model.format import require_format as require_format


def acquired(root, identity, ctx, records, sources, consumers, dry_run, *, source_sets):
    base_revision = _imports_import_guard.base_revision
    publication_revision = _imports_model_importing_repository.publication_revision
    workflow = _imports_import_guard.workflow
    working_revision = _imports_import_guard.working_revision

    inventory_for = _imports_model_importing_inventory.inventory_for
    if not ctx.verified or ctx.services != (identity[2],) or not ctx.trace:
        raise ValueError(
            "IMPORT acquisition requires a verified single-service AWS context"
        )
    if not dry_run:
        task_start_commit = _imports_model_importing_repository.task_start_commit
        name = workflow(root)
        if task_start_commit(root, name) is not None:
            publication_revision(root, name)
    directory = Path(tempfile.mkdtemp(prefix="session-", dir=evidence_store(root)))
    try:
        value = {
            "version": 3,
            **FORMAT_FIELDS,
            "root": str(root.resolve()),
            "task": None if dry_run else workflow(root),
            "base": base_revision(root),
            "head": working_revision(root),
            "scope": list(identity),
            "dryRun": dry_run,
            "acquiredAt": datetime.now(timezone.utc).isoformat(),
            "status": "acquired",
            "connection": {
                key: ctx.target.get(key)
                for key in (
                    "environment",
                    "directory",
                    AWS_EXECUTION_ACCOUNT_ID_KEY,
                    AWS_ACCOUNT_ID_KEY,
                    AWS_REGION_KEY,
                    "awsProfile",
                )
            },
            "sts": {
                "account": ctx.target.get(
                    AWS_EXECUTION_ACCOUNT_ID_KEY, ctx.target[AWS_ACCOUNT_ID_KEY]
                ),
                "verified": True,
            },
            "trace": ctx.trace,
            "records": records,
            "sources": sources,
            "sourceSets": source_sets,
            "inventory": inventory_for(ctx).statuses,
            "metrics": dict(ctx.metrics),
            "consumers": [list(item) for item in sorted(consumers)],
        }
        write_sealed(root, directory / "acquisition.json", value)
        (directory / "candidates").mkdir()
        # This is a disposition/evidence document, never a Model mutation language.
        (directory / "selection.json").write_text(
            json_text(
                {"resources": [], "excluded": [], "unreflected": [], "limitations": []}
            )
            + "\n",
            encoding="utf-8",
        )
        return directory / "acquisition.json", value
    except Exception:
        try:
            shutil.rmtree(directory)
        except OSError:
            ctx.cleanup_failed = True
        raise


def read_acquisition(root, file, identity, dry_run):
    base_revision = _imports_import_guard.base_revision
    publication_revision = _imports_model_importing_repository.publication_revision
    workflow = _imports_import_guard.workflow
    working_revision = _imports_import_guard.working_revision
    file = Path(file).absolute()
    store = evidence_store(root)
    if (
        file.name != "acquisition.json"
        or file.parent.parent != store
        or not file.parent.name.startswith("session-")
        or file.parent.is_symlink()
    ):
        raise ValueError(
            "IMPORT acquisition must use its original external evidence identifier"
        )
    private(file.parent, directory=True)
    value = read_sealed(root, file)
    require_format(value, 3, "acquisition")
    require_fresh_acquisition(value)
    if (
        value.get("version") != 3
        or value.get("root") != str(root.resolve())
        or value.get("scope") != list(identity)
        or value.get("dryRun") is not dry_run
        or value.get("base") != base_revision(root)
        or "head" not in value
        or value["head"] != working_revision(root)
        or value.get("status") != "acquired"
        or value.get("task") != (None if dry_run else workflow(root))
        or value.get("sts", {}).get("verified") is not True
    ):
        raise ValueError(
            "IMPORT acquisition is stale or belongs to another Task/Worktree/scope"
        )
    if not dry_run:
        task_start_commit = _imports_model_importing_repository.task_start_commit
        name = workflow(root)
        if task_start_commit(root, name) is not None:
            publication_revision(root, name)
    validate_inventory(value)
    if not isinstance(value.get("sourceSets"), list):
        raise ValueError(
            "IMPORT acquisition has no properties v2 input file-set snapshot"
        )
    return value


def validate_inventory(value):
    inventory = value.get("inventory")
    allowed = {
        "complete",
        "limited",
        "empty",
        "unsupported",
        "permission_denied",
        "requires_filter",
        "failed",
        "not_modelled",
    }
    if (
        not isinstance(inventory, dict)
        or not inventory
        or any(
            not isinstance(kind, str)
            or not isinstance(item, dict)
            or item.get("status") not in allowed
            for kind, item in inventory.items()
        )
    ):
        raise ValueError("IMPORT acquisition inventory status is invalid")
    records = {record["record"]: record for record in value.get("records", [])}
    if len(records) != len(value.get("records", [])):
        raise ValueError("IMPORT duplicate acquisition record")
    for kind, item in inventory.items():
        if item["status"] != "limited":
            continue
        expected = []
        for record in records.values():
            if record["kind"] != kind:
                continue
            if record.get("identityStatus", "known") != "known" or any(
                capture["status"] == "unavailable"
                for capture in record["properties"].values()
            ):
                raise ValueError("IMPORT limited inventory has unresolved acquisition")
            for prop, capture in record["properties"].items():
                if capture["status"] in {"unobservable", "withheld", "not_returned"}:
                    if not limitations.valid_capture(
                        Path(__file__).resolve().parents[4], prop, capture, record
                    ):
                        raise ValueError(
                            "IMPORT limited inventory has unverified limitation evidence"
                        )
                    expected.append(
                        {
                            "record": record["record"],
                            "property": prop,
                            "status": capture["status"],
                        }
                    )
        if (
            not expected
            or item.get("enumerationComplete") is not True
            or item.get("propertiesComplete") is not False
            or sorted(item.get("limitations", []), key=json_text)
            != sorted(expected, key=json_text)
        ):
            raise ValueError(
                "IMPORT limited inventory must bind every limitation to its acquired record"
            )
    return inventory


def acquisition_complete(value):
    require_format(value, 3, "acquisition")
    inventory = validate_inventory(value)
    if any(
        item["status"] not in {"complete", "limited", "empty", "not_modelled"}
        for item in inventory.values()
    ):
        return False
    for record in value.get("records", []):
        status = inventory.get(record["kind"], {}).get("status")
        if (
            status not in {"complete", "limited"}
            or record.get("identityStatus", "known") != "known"
            or not record.get("identity")
        ):
            return False
        allowed = (
            {"captured", "missing", "unobservable", "withheld", "not_returned"}
            if status == "limited"
            else {"captured", "missing"}
        )
        if any(
            capture["status"] not in allowed
            for capture in record["properties"].values()
        ):
            return False
    return True


def require_fresh_acquisition(value):
    """Acquisition cannot indefinitely authorize replay against an unchanged Git baseline."""
    acquired_at = datetime.fromisoformat(value["acquiredAt"])
    if acquired_at.tzinfo is None:
        raise ValueError("IMPORT evidence time must include its timezone")
    age = datetime.now(timezone.utc) - acquired_at
    if age < -timedelta(minutes=5) or age > timedelta(days=7):
        raise ValueError("IMPORT acquisition evidence expired")


def discard_acquisition(root, file):
    file = Path(file).absolute()
    if (
        file.name != "acquisition.json"
        or file.parent.parent != evidence_store(root)
        or not file.parent.name.startswith("session-")
        or file.parent.is_symlink()
    ):
        raise ValueError("IMPORT refusing to remove an unknown temporary directory")
    shutil.rmtree(file.parent)
