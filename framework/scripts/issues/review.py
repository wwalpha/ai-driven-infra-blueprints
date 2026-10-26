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


def required_text(item, key):
    value = item.get(key) if isinstance(item, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"review/confirmation needs {key}")
    return value


TARGET_FIELDS = ("service", "resource", "property", "rule")


def target_identity(record):
    if not isinstance(record, dict):
        return (None,) * len(TARGET_FIELDS)
    return tuple(
        value
        if isinstance(value := record.get(field), str)
        and value.strip() == value
        and value
        and "*" not in value
        else None
        for field in TARGET_FIELDS
    )


def matches_target(record, target, *, uncertain=False):
    """Unknown identity may signal a conflict, but never authorizes exclusion."""
    return all(
        uncertain if actual is None or expected is None else actual == expected
        for actual, expected in zip(
            target_identity(record), target_identity(target), strict=True
        )
    )


def required_identity(record, fields, label):
    identity = dict(zip(TARGET_FIELDS, target_identity(record), strict=True))
    for field in fields:
        if identity[field] is None:
            raise ValueError(f"{label} needs concrete {field}")


def validate_confirmations(data, environment, directory):
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "environment", "target", "confirmations"}
        or type(data["version"]) is not int
        or data["version"] != 2
        or data["environment"] != environment
        or data["target"] != directory
    ):
        raise ValueError(
            "Human confirmation file requires version 2, exact environment/target scope and confirmations"
        )
    items = data["confirmations"]
    if not isinstance(items, list):
        raise ValueError("confirmations must be a list")
    seen = set()
    for item in items:
        fields = {"id", "service", "fact", "scope", "exceptions", "evidence"}
        if not isinstance(item, dict):
            raise ValueError("Human confirmation must be an object")
        if set(item) != fields:
            raise ValueError(
                f"invalid Human confirmation fields: missing {sorted(fields - set(item))}; "
                f"unexpected {sorted(set(item) - fields, key=str)}"
            )
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
        required_identity(
            item["scope"], ("resource", "property"), f"confirmation {key} scope"
        )
        if not isinstance(item["exceptions"], list):
            raise ValueError(f"confirmation {key} exceptions must be a list")
        for exception in item["exceptions"]:
            if not isinstance(exception, dict) or set(exception) != {
                "rule",
                "diagnostic_id",
                "condition",
            }:
                raise ValueError(
                    f"confirmation {key} exception needs rule/diagnostic_id/condition"
                )
            required_identity(exception, ("rule",), f"confirmation {key} exception")
            required_text(exception, "diagnostic_id")
            required_text(exception, "condition")
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


def review_snapshot(artifact, review):
    if artifact.get("version") != 6:
        raise ValueError("unsupported scan artifact version; version 6 required")
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
    unresolved = []
    assignments = review["diagnostic_assignments"]
    unknown = {item["id"] for item in artifact["judgments"] if "message" in item}
    if not isinstance(assignments, dict) or set(assignments) != unknown:
        raise ValueError("diagnostic requires exact scoped service assignments")
    for item in artifact["judgments"]:
        if "message" in item:
            assignment = assignments[item["id"]]
            if not isinstance(assignment, dict):
                raise ValueError(
                    "diagnostic assignment requires status and evidence/reason"
                )
            status = assignment.get("status")
            if status == "unresolved" and set(assignment) == {"status", "reason"}:
                required_text(assignment, "reason")
                unresolved.append(
                    dict(
                        item,
                        diagnostic_id=item["id"],
                        assignment=deepcopy(assignment),
                        complete=False,
                    )
                )
                continue
            if (
                status != "assigned"
                or set(assignment) != {"status", "service", "evidence"}
                or assignment["service"] not in services
            ):
                raise ValueError(
                    "diagnostic requires scoped service assignment with evidence"
                )
            required_text(assignment, "evidence")
            assigned = dict(
                item, service=assignment["service"], assignment=deepcopy(assignment)
            )
            if item["cause_kind"] == "input_invalid":
                ordinary.append(assigned)
            else:
                unresolved.append(
                    dict(assigned, diagnostic_id=item["id"], complete=False)
                )
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
        required_text(decision, "evidence")
        expected = dict(
            service=confirmation["service"],
            **confirmation["scope"],
            rule=diagnostic.get("rule"),
        )
        if target != confirmation["scope"] or not matches_target(
            diagnostic, expected, uncertain=outcome == "conflict"
        ):
            raise ValueError("Human confirmation does not cover diagnostic target/rule")
        if outcome == "excluded":
            if not any(
                exception["rule"] == diagnostic["rule"]
                and exception["diagnostic_id"] == key
                for exception in confirmation["exceptions"]
            ):
                raise ValueError(
                    "exclusion requires a Human exception for this rule/diagnostic_id/condition"
                )
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
                    **{
                        field: diagnostic.get(field)
                        for field in ("resource", "property", "rule")
                    },
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
    for item in unresolved:
        retained = next(
            (
                value
                for value in data["unverified"]
                if value.get("diagnostic_id") == item["diagnostic_id"]
            ),
            None,
        )
        if retained is None:
            data["unverified"].append(deepcopy(item))
        else:
            retained.update(deepcopy(item))
        for failure in data["processing_errors"]:
            if failure.get("diagnostic_id") == item["diagnostic_id"]:
                failure.update(deepcopy(item))
    data["ordinary"] = [
        item for item in ordinary if item["id"] not in excluded
    ] + deepcopy(additions)
    data["unverified"].extend(conflicts)
    data["unverified"].extend(
        dict(code="service.not_run", **result)
        for result in data["service_results"]
        if result["status"] == "unverified"
    )
    stamp = datetime.fromisoformat(
        required_text(data, "executed_at").replace("Z", "+00:00")
    )
    if stamp.utcoffset() is None:
        raise ValueError("Scan execution time requires an explicit timezone")
    return Snapshot(
        json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)
    )
