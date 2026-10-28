"""Current diagnostic decisions and independent Human facts; no inventory reads."""

import builtins
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from model.core import literal
from model.validations.naming import (
    NAMING_EXEMPT_PROPERTIES,
    naming_rule_rows,
    naming_target_matches,
)
from task_contract_core import safe_path
from utils.yaml_format import yaml_read

from .integrity import selected_scope
from .records import identifier


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


def diagnostic_index(
    ordinary: list[dict[str, Any]], services: list[str]
) -> dict[str, dict[str, Any]]:
    for item in ordinary:
        required_text(item, "id")
        required_text(item, "message")
        if item.get("service") not in services:
            raise ValueError("current diagnostic is outside selected services")
    by_id = {item["id"]: item for item in ordinary}
    if len(by_id) != len(ordinary):
        raise ValueError("duplicate current diagnostic ID")
    return by_id


def naming_patterns(artifact, name):
    kind, prop = required_text(name, "resourceType"), required_text(name, "property")
    rules = artifact["naming_context"].get("rules", {}).get(kind.partition(".")[0], [])
    return {
        pattern
        for rule in rules
        for target_kind, target, pattern in naming_rule_rows(rule["text"])
        if target_kind == kind and naming_target_matches(prop, {target}, kind)
    }


def pattern_matches(pattern, value, fixed=None):
    """Prove only literal structure; unknown components remain unrestricted."""
    fixed = fixed or {}
    tokens = re.split(r"(\{\{[a-z_]+\}\}|\[|\])", pattern)
    positions, optional = {0}, []
    for token in tokens:
        if token == "[":
            optional.append(positions.copy())
        elif token == "]":
            if not optional:
                raise ValueError("invalid naming pattern")
            positions.update(optional.pop())
        elif token.startswith("{{"):
            component = token[2:-2]
            if component in fixed:
                expected = fixed[component]
                positions = {
                    pos + len(expected)
                    for pos in positions
                    if value.startswith(expected, pos)
                }
            else:
                positions = (
                    set(range(min(positions) + 1, len(value) + 1))
                    if positions
                    else set()
                )
        else:
            positions = {
                pos + len(token) for pos in positions if value.startswith(token, pos)
            }
    if optional:
        raise ValueError("invalid naming pattern")
    return len(value) in positions


def confirmed_components(artifact, name):
    target = artifact["naming_context"].get("target_context", {})
    values = {
        component: target[key]
        for component, key in (
            ("environment", "environment"),
            ("account_id", "awsAccountId"),
            ("region", "awsRegion"),
            ("target_alias", "alias"),
            ("suffix", "suffix"),
        )
        if isinstance(target.get(key), str) and target[key]
    }
    conflicts = set()
    for confirmation in artifact["human_confirmations"]["confirmations"]:
        if confirmation["service"] != name["service"] or confirmation["scope"] != {
            "resource": name["resource"],
            "property": name["property"],
        }:
            continue
        fact = re.fullmatch(
            r"([a-z_]+)\s*=\s*([a-zA-Z0-9_.-]+)", confirmation["fact"].strip()
        )
        for component, value in [fact.groups()] if fact else []:
            if component in conflicts:
                continue
            if component in values and values[component] != value:
                values.pop(component)
                conflicts.add(component)
            else:
                values[component] = value
    return values


def validate_naming_issue(artifact, item, name):
    violation = item["violation"]
    applied = required_text(item, "applied_rule")
    patterns = naming_patterns(artifact, name)
    value = name.get("value")
    actual = (
        literal(value)
        if name.get("value_available") and isinstance(value, str)
        else None
    )
    if violation == "rule_missing":
        common = artifact["naming_context"]["rules"].get("common", [])
        if (
            patterns
            or name["resourceType"] + "." + name["property"] in NAMING_EXEMPT_PROPERTIES
            or applied not in {rule["path"] for rule in common}
            or name.get("pattern_review") == "not applicable"
        ):
            raise ValueError("Naming rule coverage is not missing")
    elif violation == "provider_constraint":
        if actual is None or applied not in name.get("provider_errors", []):
            raise ValueError("Naming provider constraint is not established")
    elif violation == "required_missing":
        common = artifact["naming_context"]["rules"].get("common", [])
        if (
            not name.get("required_missing")
            or value is not None
            or applied not in patterns | {rule["path"] for rule in common}
        ):
            raise ValueError("Naming item does not establish a missing required name")
    elif applied not in patterns:
        raise ValueError("Naming applied_rule does not apply to this item")
    if violation == "format":
        if actual is None or any(
            pattern_matches(pattern, actual) for pattern in patterns
        ):
            raise ValueError("Naming format violation is not established")
    if violation == "confirmed_mismatch":
        expected, observed = (
            required_text(item, "expected"),
            required_text(item, "actual"),
        )
        confirmed = confirmed_components(artifact, name)
        if (
            not actual
            or expected == observed
            or any(pattern_matches(pattern, actual, confirmed) for pattern in patterns)
            or not any(
                expected == value
                and "{{" + component + "}}" in applied
                and pattern_matches(applied, actual, {**confirmed, component: observed})
                for component, value in confirmed.items()
            )
        ):
            raise ValueError("Naming mismatch is not established by confirmed values")
    elif "expected" in item or ("actual" in item and item["actual"] != actual):
        raise ValueError("Naming evidence contradicts the naming item")


def naming_failure_recorded(artifact, item):
    if item["failure_kind"] == "input_unavailable":
        return any(
            judgment.get("kind") == "input-load-error"
            and judgment.get("service") == item["service"]
            for judgment in artifact["judgments"]
        )
    scope = "/".join((artifact["environment"], artifact["target"], item["service"]))
    for failure in artifact["processing_errors"]:
        if (
            failure.get("phase") != "materials.naming"
            or scope not in failure.get("scope", [])
            or failure.get("cause_kind") != "check_failure"
        ):
            continue
        if item["failure_kind"] == "execution_failure":
            return True
        error_type = getattr(builtins, failure.get("exception", ""), None)
        if isinstance(error_type, type) and issubclass(
            error_type, (OSError, UnicodeError)
        ):
            return True
    return False


def review_snapshot(artifact: dict[str, Any], review: dict[str, Any]) -> Snapshot:
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
    by_id = diagnostic_index(ordinary, services)
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
    naming = {item["id"]: item for item in artifact["naming"]["names"]}
    for item in additions:
        if (
            not isinstance(item, dict)
            or set(item)
            - {
                "service",
                "message",
                "source",
                "resource",
                "property",
                "rule",
                "naming_item_id",
                "violation",
                "evidence",
                "expected",
                "actual",
                "applied_rule",
            }
            or item.get("service") not in services
        ):
            raise ValueError("review Issue ownership requires explicit scoped service")
        required_text(item, "message")
        naming_target = any(
            all(
                item.get(key) == name.get(key)
                for key in ("service", "resource", "property")
            )
            for name in naming.values()
        )
        if (
            naming_target
            or "naming" in str(item.get("rule", "")).lower()
            or "naming_item_id" in item
        ):
            name = naming.get(required_text(item, "naming_item_id"))
            if name is None or any(
                item.get(key) != name.get(key)
                for key in ("service", "resource", "property")
            ):
                raise ValueError("Naming Issue must match its naming item")
            for key in ("rule", "violation", "evidence"):
                required_text(item, key)
            if item["rule"] != "review.naming" or item["violation"] not in {
                "required_missing",
                "format",
                "confirmed_mismatch",
                "rule_missing",
                "provider_constraint",
            }:
                raise ValueError("Naming Issue needs a concrete violation")
            if name.get("resourceMode") == "IMPORT" and item["violation"] in {
                "format",
                "rule_missing",
            }:
                raise ValueError("IMPORT is exempt from framework naming conventions")
            validate_naming_issue(artifact, item, name)
        elif set(item) & {
            "violation",
            "evidence",
            "expected",
            "actual",
            "applied_rule",
        }:
            raise ValueError("Naming evidence requires a naming item")
    additions = [
        dict(item, id=identifier(["issues.review", item])) for item in additions
    ]
    diagnostic_index([*ordinary, *additions], services)
    unverified = review["unverified"]
    if not isinstance(unverified, list):
        raise ValueError("review unverified must be a list")
    for item in unverified:
        if not isinstance(item, dict) or item.get("service") not in services:
            raise ValueError("unverified review needs a scoped service/check/reason")
        check = required_text(item, "check")
        required_text(item, "reason")
        fields = {"service", "check", "reason"}
        if check == "naming":
            fields.add("failure_kind")
            if item.get("failure_kind") not in {
                "input_unavailable",
                "read_failure",
                "execution_failure",
            }:
                raise ValueError(
                    "Naming unverified requires a concrete execution failure"
                )
            if not naming_failure_recorded(artifact, item):
                raise ValueError("Naming unverified requires a recorded scan failure")
        if set(item) != fields:
            raise ValueError("invalid unverified review fields")
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
    ] + additions
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
