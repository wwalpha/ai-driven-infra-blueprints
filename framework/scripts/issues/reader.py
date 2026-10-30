"""Strict, shared input boundary for saved Issues scans and reviews."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from model.validations.naming import NamingRuleIndex
from utils.json_format import strict_json

from .artifact import validate_artifact
from .review import IncompleteNamingScan


@dataclass(frozen=True)
class LoadedScan:
    artifact: dict
    raw_sha256: str
    rule_index: NamingRuleIndex
    pending_name_ids: tuple[str, ...]


def _read_json(raw, label):
    try:
        value = strict_json(raw.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise ValueError(f"{label}: invalid JSON") from None
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected object")
    return value


def _field(parent, key, expected, prefix=""):
    name = f"{prefix}.{key}" if prefix else key
    if key not in parent:
        raise ValueError(f"Scan artifact: missing required field {name}")
    value = parent[key]
    if type(value) not in (expected if isinstance(expected, tuple) else (expected,)):
        raise ValueError(f"Scan artifact: invalid type at {name}")
    return value


def read_scan_artifact(path: Path) -> LoadedScan:
    raw = path.read_bytes()
    artifact = _read_json(raw, "Scan artifact")
    version = _field(artifact, "version", int)
    if version != 6:
        raise ValueError("Scan artifact: unsupported version")
    for key in (
        "root",
        "scan_id",
        "environment",
        "target",
        "executed_at",
        "naming_context_id",
        "machine_diagnostics",
    ):
        _field(artifact, key, str)
    for key in ("services", "target_services"):
        if any(type(item) is not str for item in _field(artifact, key, list)):
            raise ValueError(f"Scan artifact: invalid type at {key}")
    for key in (
        "service_results",
        "ordinary",
        "judgments",
        "information",
        "unverified",
        "processing_errors",
        "iac",
        "record_meta",
        "iac_issues",
        "check_results",
    ):
        if any(type(item) is not dict for item in _field(artifact, key, list)):
            raise ValueError(f"Scan artifact: invalid type at {key}")
    _field(artifact, "warnings", list)
    _field(artifact, "naming_context", dict)
    for key, child in (("naming", "names"), ("human_confirmations", "confirmations")):
        parent = _field(artifact, key, dict)
        if any(type(item) is not dict for item in _field(parent, child, list, key)):
            raise ValueError(f"Scan artifact: invalid type at {key}.{child}")
    overview = _field(artifact, "overview", dict)
    records = _field(overview, "records", dict, "overview")
    for key in ("difference", "uncompared", "error", "matched", "deferred", "excluded"):
        _field(records, key, int, "overview.records")
    for key in ("record_count", "issue_count", "pending_deploy_excluded"):
        _field(overview, key, int, "overview")
    _field(overview, "comparison_incomplete", bool, "overview")
    lint = _field(artifact, "cfn_lint", dict)
    _field(lint, "status", str, "cfn_lint")
    for key in ("jobs", "coverage"):
        if any(type(item) is not dict for item in _field(lint, key, list, "cfn_lint")):
            raise ValueError(f"Scan artifact: invalid type at cfn_lint.{key}")
    for result in artifact["service_results"]:
        for key in ("service", "status"):
            _field(result, key, str, "service_results[]")
    for record in artifact["iac"]:
        for key in ("service", "category"):
            _field(record, key, str, "iac[]")
    for meta in artifact["record_meta"]:
        for key in ("record_id", "category"):
            _field(meta, key, str, "record_meta[]")
        _field(meta, "issue_id", (str, type(None)), "record_meta[]")
    for issue in artifact["iac_issues"]:
        _field(issue, "members", list, "iac_issues[]")
        for key in ("id", "category"):
            _field(issue, key, str, "iac_issues[]")
        compact = _field(issue, "compact", dict, "iac_issues[]")
        _field(compact, "records", int, "iac_issues[].compact")
    try:
        rule_index = NamingRuleIndex(artifact["naming_context"])
        pending_names = validate_artifact(artifact, rule_index=rule_index)
    except IncompleteNamingScan as error:
        message = str(error)
        if message in {
            "incomplete Naming Scan: invalid naming_context_id; explicit rescan and Review required",
            "incomplete Naming Scan: missing names; explicit rescan and Review required",
            "incomplete Naming Scan target context; explicit rescan and Review required",
            "incomplete Naming Scan: duplicate naming ID; explicit rescan and Review required",
            "incomplete Naming Scan: Naming item context ID mismatch; explicit rescan and Review required",
            "incomplete Naming Scan: invalid or missing decision; explicit rescan and Review required",
            "incomplete Naming Scan: Naming decision does not match Scan evidence; explicit rescan and Review required",
        }:
            raise IncompleteNamingScan(message) from None
        raise ValueError("Scan artifact: invalid structure or integrity") from None
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        RecursionError,
        OverflowError,
    ):
        raise ValueError("Scan artifact: invalid structure or integrity") from None
    return LoadedScan(
        artifact,
        hashlib.sha256(raw).hexdigest(),
        rule_index,
        tuple(name["id"] for name in pending_names),
    )


def read_review_json(path: Path) -> dict:
    return _read_json(path.read_bytes(), "Review JSON")
