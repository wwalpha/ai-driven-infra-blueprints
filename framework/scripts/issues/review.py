"""Current diagnostic decisions and independent Human facts; no inventory reads."""

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from task_contract_core import safe_path
from utils.yaml_format import yaml_read

from .integrity import selected_scope


@dataclass(frozen=True)
class Snapshot:
    """Serialized values cannot be changed by callers after review validation."""

    data: str
    cleanup: tuple[tuple[str, str], ...]


def required_text(item, key):
    value = item.get(key) if isinstance(item, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"review/confirmation needs {key}")
    return value


def validate_confirmations(data, environment, directory):
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "environment", "target", "confirmations"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or data["environment"] != environment
        or data["target"] != directory
    ):
        raise ValueError("invalid Human confirmation file scope/version")
    items = data["confirmations"]
    if not isinstance(items, list):
        raise ValueError("confirmations must be a list")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "service",
            "fact",
            "scope",
            "exceptions",
            "evidence",
            "related_issues",
        }:
            raise ValueError("invalid Human confirmation fields")
        key = required_text(item, "id")
        if key in seen:
            raise ValueError("duplicate Human confirmation ID")
        seen.add(key)
        selected_scope(environment, directory, [required_text(item, "service")])
        for field in ("fact", "evidence"):
            required_text(item, field)
        if not isinstance(item["scope"], dict) or set(item["scope"]) != {
            "resource",
            "property",
        }:
            raise ValueError("confirmation needs explicit resource/property scope")
        for field in ("resource", "property"):
            required_text(item["scope"], field)
        if not isinstance(item["exceptions"], list) or any(
            not isinstance(value, str) or not value.strip()
            for value in item["exceptions"]
        ):
            raise ValueError("invalid confirmation exceptions")
        related = item["related_issues"]
        if not isinstance(related, list) or any(
            not isinstance(record, dict) or set(record) != {"id", "message"}
            for record in related
        ):
            raise ValueError("invalid related Issue records")
        ids = [required_text(record, "id") for record in related]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate related Issue record")
        for record in related:
            required_text(record, "message")
    return data


def human_confirmations(root, environment, directory):
    selected_scope(environment, directory, ["human-confirmations"])
    path = safe_path(root, f"issues/{environment}/{directory}/human-confirmations.yaml")
    if not path.is_file():
        raise ValueError(
            "human-confirmations.yaml is required before switching to snapshots; register Human facts explicitly (an empty confirmations list is permitted)"
        )
    return validate_confirmations(
        yaml_read(path.read_text(encoding="utf-8")), environment, directory
    )


def reviewed_ids(values, expected, channel):
    if (
        not isinstance(values, list)
        or any(not isinstance(value, str) for value in values)
        or len(values) != len(set(values))
        or set(values) != set(expected)
    ):
        raise ValueError(f"all {channel} IDs require explicit review")


def affects_confirmation(record, confirmation, environment, target):
    if record.get("service") is not None:
        if record["service"] != confirmation["service"]:
            return False
    elif record.get("scope"):
        scope = record["scope"]
        scopes = [scope] if isinstance(scope, str) else scope
        if f"{environment}/{target}/{confirmation['service']}" not in scopes:
            return False
    return all(
        confirmation["scope"][field] == "*"
        or record.get(field) in (None, "*", confirmation["scope"][field])
        for field in ("resource", "property")
    )


def review_snapshot(artifact, review):
    required = {
        "scan_id",
        "reviewed_naming_context_id",
        "reviewed_names",
        "reviewed_judgments",
        "reviewed_confirmations",
        "diagnostic_assignments",
        "diagnostic_decisions",
        "issues",
        "unverified",
        "confirmation_cleanup",
    }
    if not isinstance(review, dict) or set(review) != required:
        raise ValueError("invalid snapshot review fields")
    if (
        review["scan_id"] != artifact["scan_id"]
        or review["reviewed_naming_context_id"] != artifact["naming_context_id"]
    ):
        raise ValueError("review scan_id/naming_context_id mismatch")
    services = artifact["services"]
    validate_confirmations(
        artifact["human_confirmations"], artifact["environment"], artifact["target"]
    )
    confirmations = {
        item["id"]: item for item in artifact["human_confirmations"]["confirmations"]
    }
    reviewed_ids(
        review["reviewed_names"],
        [item["id"] for item in artifact["naming"]["names"]],
        "naming",
    )
    reviewed_ids(
        review["reviewed_judgments"],
        [item["id"] for item in artifact["judgments"]],
        "judgment",
    )
    reviewed_ids(review["reviewed_confirmations"], confirmations, "Human confirmation")
    ordinary = deepcopy(artifact["ordinary"])
    assignments = review["diagnostic_assignments"]
    unknown = {item["id"] for item in artifact["judgments"] if "message" in item}
    if not isinstance(assignments, dict) or set(assignments) != unknown:
        raise ValueError("diagnostic requires exact scoped service assignments")
    for item in artifact["judgments"]:
        if "message" in item:
            owner = assignments[item["id"]]
            if owner not in services:
                raise ValueError("diagnostic requires scoped service assignment")
            ordinary.append(dict(item, service=owner))
    decisions = review["diagnostic_decisions"]
    if not isinstance(decisions, list):
        raise ValueError("diagnostic_decisions must be a list")
    for item in ordinary:
        required_text(item, "id")
        required_text(item, "message")
        if item.get("service") not in services:
            raise ValueError("current diagnostic is outside selected services")
    by_id = {item["id"]: item for item in ordinary}
    if len(by_id) != len(ordinary):
        raise ValueError("duplicate current diagnostic ID")
    seen, excluded, conflicts = set(), set(), []
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("invalid diagnostic decision")
        key = required_text(decision, "id")
        if key not in by_id or key in seen:
            raise ValueError("unknown or duplicate current diagnostic decision")
        seen.add(key)
        outcome = decision.get("outcome")
        required_text(decision, "reason")
        if outcome not in {"issue", "excluded", "conflict"}:
            raise ValueError("invalid diagnostic outcome")
        if outcome == "issue":
            if set(decision) != {"id", "outcome", "reason"}:
                raise ValueError("invalid Issue decision fields")
            continue
        if set(decision) != {
            "id",
            "outcome",
            "reason",
            "confirmation_id",
            "target",
            "evidence",
        }:
            raise ValueError(
                "Human exclusion/conflict needs confirmation, target and evidence"
            )
        confirmation = confirmations.get(decision["confirmation_id"])
        diagnostic = by_id[key]
        if confirmation is None or confirmation["service"] != diagnostic["service"]:
            raise ValueError("Human confirmation does not cover diagnostic service")
        target = decision["target"]
        if not isinstance(target, dict) or set(target) != {"resource", "property"}:
            raise ValueError("decision requires resource/property target")
        for field in ("resource", "property"):
            required_text(target, field)
            if confirmation["scope"][field] not in {"*", target[field]} or (
                diagnostic.get(field) not in (None, "*", target[field])
            ):
                raise ValueError("Human confirmation does not cover diagnostic target")
        required_text(decision, "evidence")
        if outcome == "excluded":
            if not confirmation["exceptions"]:
                raise ValueError("exclusion requires an explicit Human exception")
            excluded.add(key)
        else:
            conflicts.append(
                dict(
                    code="human.confirmation_conflict",
                    service=diagnostic["service"],
                    diagnostic_id=key,
                    confirmation_id=confirmation["id"],
                    message=decision["reason"],
                    evidence=decision["evidence"],
                )
            )
    if seen != by_id.keys():
        raise ValueError("all current diagnostics require review")
    additions = review["issues"]
    if not isinstance(additions, list):
        raise ValueError("review issues must be a list")
    for item in additions:
        if (
            not isinstance(item, dict)
            or set(item)
            - {"service", "message", "source", "resource", "property", "rule"}
            or item.get("service") not in services
        ):
            raise ValueError("review Issue ownership requires explicit scoped service")
        required_text(item, "message")
    unverified = review["unverified"]
    if not isinstance(unverified, list):
        raise ValueError("review unverified must be a list")
    for item in unverified:
        if (
            not isinstance(item, dict)
            or set(item) != {"service", "check", "reason"}
            or item["service"] not in services
        ):
            raise ValueError("unverified review needs a scoped service/check/reason")
        required_text(item, "check")
        required_text(item, "reason")
    data = deepcopy(artifact)
    data["reviewed"] = True
    data["notice_overview"] = {}
    data["unverified"].extend(deepcopy(unverified))
    data["ordinary"] = [
        item for item in ordinary if item["id"] not in excluded
    ] + deepcopy(additions)
    data["unverified"].extend(conflicts)
    data["unverified"].extend(
        dict(code="service.not_run", **result)
        for result in data["service_results"]
        if result["status"] == "unverified"
    )
    cleanups = review["confirmation_cleanup"]
    if not isinstance(cleanups, list):
        raise ValueError("confirmation_cleanup must be a list")
    removed = set()
    for cleanup in cleanups:
        if not isinstance(cleanup, dict) or set(cleanup) != {
            "confirmation_id",
            "record_id",
            "reason",
            "check_id",
            "evidence",
        }:
            raise ValueError("invalid confirmation cleanup")
        key = (cleanup["confirmation_id"], cleanup["record_id"])
        confirmation = confirmations.get(key[0])
        if (
            key in removed
            or confirmation is None
            or not any(
                record["id"] == key[1] for record in confirmation["related_issues"]
            )
        ):
            raise ValueError("unknown or duplicate related Issue cleanup")
        required_text(cleanup, "reason")
        required_text(cleanup, "evidence")
        checks = [
            item
            for item in artifact["check_results"]
            if item["id"] == cleanup["check_id"]
            and item["status"] == "PASS"
            and item["complete"] is True
            and f"{artifact['environment']}/{artifact['target']}/{confirmation['service']}"
            in item["scope"]
        ]
        if len(checks) != 1:
            raise ValueError(
                "cleanup needs a completed current check covering the confirmation service"
            )
        if any(
            affects_confirmation(
                item, confirmation, artifact["environment"], artifact["target"]
            )
            for item in [
                *data["ordinary"],
                *data["unverified"],
                *data["processing_errors"],
            ]
        ):
            raise ValueError("cleanup contradicts current Issues or Human conflicts")
        removed.add(key)
    for item in data["human_confirmations"]["confirmations"]:
        item["related_issues"] = [
            record
            for record in item["related_issues"]
            if (item["id"], record["id"]) not in removed
        ]
    stamp = datetime.fromisoformat(
        required_text(data, "executed_at").replace("Z", "+00:00")
    )
    if stamp.utcoffset() is None:
        raise ValueError("Scan execution time requires an explicit timezone")
    return Snapshot(
        json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False),
        tuple(sorted(removed)),
    )
