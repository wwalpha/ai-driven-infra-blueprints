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
    check_iam_role_suffix,
    naming_rule_rows,
    naming_rules,
    naming_target_matches,
    provider_naming_errors,
    value_available,
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
PATTERN_BOUNDARIES = "-/:._ "


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
    """Accept extra boundary-separated components without guessing their meaning."""
    return bool(pattern_values(pattern, value, fixed=fixed))


def pattern_values(pattern, value, component=None, fixed=None):
    """Collect every possible binding, including optional and extra components."""
    fixed = fixed or {}
    if "suffix" in fixed:
        pattern = pattern.replace("[-{{suffix}}]", "-{{suffix}}").replace(
            "[/{{suffix}}]", "/{{suffix}}"
        )
    tokens = re.split(r"(\{\{[a-z_]+\}\}|\[|\])", pattern)
    positions = {(0, None)} | {
        (pos + 1, None) for pos, char in enumerate(value) if char in PATTERN_BOUNDARIES
    }
    optional = []
    for token in tokens:
        if token == "[":
            optional.append(positions.copy())
        elif token == "]":
            if not optional:
                raise ValueError("invalid naming pattern")
            positions.update(optional.pop())
        elif token.startswith("{{"):
            key = token[2:-2]
            if key in fixed:
                expected = fixed[key]
                positions = {
                    (pos + len(expected), expected if key == component else observed)
                    for pos, observed in positions
                    if value.startswith(expected, pos)
                }
            else:
                positions = {
                    (end, value[pos:end] if key == component else observed)
                    for pos, observed in positions
                    for end in range(pos + 1, len(value) + 1)
                    if value[pos] not in "-/:." and value[end - 1] not in "-/:."
                }
        else:
            positions = {
                (pos + len(token), observed)
                for pos, observed in positions
                if value.startswith(token, pos)
            }
    if optional:
        raise ValueError("invalid naming pattern")
    return {
        observed
        for pos, observed in positions
        if pos == len(value) or (pos < len(value) and value[pos] in PATTERN_BOUNDARIES)
    }


def component_facts(artifact, name):
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
    return values, conflicts


def confirmed_components(artifact, name):
    return component_facts(artifact, name)[0]


def pattern_prefix_applies(pattern, value):
    prefix = re.split(r"\[|\{\{", pattern)[0]
    return (
        bool(prefix)
        and value.startswith(prefix)
        and (len(value) == len(prefix) or value[len(prefix)] in PATTERN_BOUNDARIES)
    )


def naming_value(name):
    value = name.get("value")
    return (
        literal(value)
        if name.get("value_available") is True and value_available(value, value)
        else None
    )


def applicable_patterns(artifact, name):
    """A single resource/property rule proves scope; alternatives need evidence."""
    kind, prop = name["resourceType"], name["property"]
    value = naming_value(name) or ""
    rules = artifact["naming_context"].get("rules", {}).get(kind.partition(".")[0], [])
    patterns = {
        pattern
        for rule in rules
        for target_kind, target, pattern, scope in naming_rules(rule["text"])
        if target_kind == kind
        and naming_target_matches(prop, {target}, kind)
        and (
            scope == "mandatory"
            or (scope == "prefix" and pattern_prefix_applies(pattern, value))
        )
    }
    if (
        name["resourceType"] == "Organizations.Policy"
        and name.get("conditions", {}).get("Type") != "SERVICE_CONTROL_POLICY"
    ):
        return set()
    if len(patterns) <= 1:
        return patterns
    return {pattern for pattern in patterns if pattern_matches(pattern, value)}


def naming_violations(artifact, name):
    """Evidence shared by Scan decisions and validation of additional Naming Issues."""
    patterns = naming_patterns(artifact, name)
    applicable = applicable_patterns(artifact, name)
    common = artifact["naming_context"].get("rules", {}).get("common", [])
    common_rule = next((rule["path"] for rule in common), "")
    violations = []
    actual = naming_value(name)
    if name.get("required_missing"):
        violations.append(dict(violation="required_missing", applied_rule=common_rule))
    provider_errors = name.get("provider_errors", [])
    if actual is not None:
        provider_errors = list(
            dict.fromkeys(
                [
                    *provider_errors,
                    *provider_naming_errors(
                        name["resourceType"],
                        name["property"],
                        actual,
                        name.get("conditions"),
                    ),
                ]
            )
        )
    for error in provider_errors:
        violations.append(dict(violation="provider_constraint", applied_rule=error))
    if name.get("property") == "(no selected naming property)":
        return violations
    exempt = name["resourceType"] + "." + name["property"] in NAMING_EXEMPT_PROPERTIES
    create = name.get("resourceMode", "CREATE") == "CREATE"
    if not patterns and not exempt and create:
        violations.append(dict(violation="rule_missing", applied_rule=common_rule))
    if actual is None:
        return violations
    if (
        create
        and applicable
        and not any(pattern_matches(pattern, actual) for pattern in applicable)
    ):
        violations.extend(
            dict(violation="format", applied_rule=pattern)
            for pattern in sorted(applicable)
        )
    confirmed = confirmed_components(artifact, name)
    for component, expected in confirmed.items():
        relevant = [p for p in applicable if "{{" + component + "}}" in p]
        if not relevant or any(
            pattern_matches(pattern, actual, {component: expected})
            for pattern in relevant
        ):
            continue
        observed = set().union(
            *(pattern_values(pattern, actual, component) for pattern in relevant)
        )
        # A component mismatch is evidence only when every binding identifies one value.
        if len(observed) == 1 and None not in observed:
            violations.extend(
                dict(
                    violation="confirmed_mismatch",
                    applied_rule=pattern,
                    expected=expected,
                    actual=next(iter(observed)),
                )
                for pattern in sorted(relevant)
            )
    if create:
        errors = mandatory_name_errors(artifact, name, actual)
        violations.extend(
            dict(violation="format", applied_rule=rule, constraint=error)
            for rule, error in errors
        )
    return violations


def mandatory_name_errors(artifact, name, actual):
    """Explicit service rules remain obligations independently of recommended formats."""
    kind, prop = name["resourceType"], name["property"]
    rules = sorted(naming_patterns(artifact, name))
    rule = rules[0] if rules else ""
    target = artifact["naming_context"].get("target_context", {})
    errors = []
    if (kind, prop) == ("IAM.Role", "RoleName") and "suffix" in target:
        errors.extend(check_iam_role_suffix(actual, target.get("suffix")))
    if kind in {"Glue.Job", "Glue.SecurityConfiguration"} and prop == "Name":
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", actual):
            errors.append("Glue Name must use lower-kebab-case")
        if (
            kind == "Glue.SecurityConfiguration"
            and name.get("same_type_count", 1) > 1
            and not re.match(r"glsc-(?:0[1-9]|[1-9][0-9])(?:-|$)", actual)
        ):
            errors.append(
                "Multiple Glue SecurityConfigurations require a positive two-digit sequence"
            )
    if (kind, prop) == ("SecretsManager.Secret", "Name") and (
        actual.endswith("-")
        or actual.startswith("/")
        or actual.endswith("/")
        or "//" in actual
    ):
        errors.append(
            "Secret Name must have non-empty path components and no trailing hyphen"
        )
    if (kind, prop) == ("SecretsManager.Secret", "Name") and not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*){2,}", actual
    ):
        errors.append(
            "Secret Name requires application/environment/purpose_path with lower-kebab-case components"
        )
    suffix = target.get("suffix")
    applicable = applicable_patterns(artifact, name)
    terminal_suffix_patterns = {
        pattern
        for entry in artifact["naming_context"]
        .get("rules", {})
        .get(kind.partition(".")[0], [])
        for target_kind, target_prop, pattern, scope in naming_rules(entry["text"])
        if target_kind == kind
        and naming_target_matches(prop, {target_prop}, kind)
        and scope == "mandatory"
        and pattern.endswith("[-{{suffix}}]")
    }
    if (
        suffix
        and applicable
        and not any(
            "{{suffix}}" not in pattern
            or (
                pattern_matches(pattern, actual, {"suffix": suffix})
                and (
                    pattern not in terminal_suffix_patterns
                    or (kind, prop) == ("IAM.Role", "RoleName")
                    or actual.endswith("-" + suffix)
                )
            )
            for pattern in applicable
        )
    ):
        errors.append("Configured target suffix is required in the applicable pattern")
        rule = sorted(applicable)[0]
    return [(rule, error) for error in errors]


def naming_decision(artifact, name):
    violations = naming_violations(artifact, name)
    pending = []
    if name.get("property") != "(no selected naming property)" and not name.get(
        "required_missing"
    ):
        if naming_value(name) is None:
            pending.append(
                "Selected name value is unavailable; mandatory checks are unverified"
            )
        elif name.get("provider_checked") is not True:
            pending.append("Provider constraints have not been checked")
    confirmed, conflicts = component_facts(artifact, name)
    patterns = applicable_patterns(artifact, name)
    if any("{{" + key + "}}" in pattern for key in conflicts for pattern in patterns):
        pending.append("Conflicting confirmed component values require review")
    if any(value is None for value in name.get("conditions", {}).values()) and (
        name.get("resourceMode", "CREATE") == "CREATE"
        or name["resourceType"] in {"SQS.Queue", "SNS.Topic"}
    ):
        pending.append("A selected condition for mandatory Naming rules is unconfirmed")
    if name["resourceType"] in {"SQS.Queue", "SNS.Topic"}:
        key = "FifoQueue" if name["resourceType"] == "SQS.Queue" else "FifoTopic"
        value = name.get("conditions", {}).get(key, False)
        if (
            value is not None
            and not isinstance(value, bool)
            and (not isinstance(value, str) or value.lower() not in {"true", "false"})
        ):
            pending.append("FIFO condition is unconfirmed")
    if name.get("resourceMode", "CREATE") == "CREATE":
        if name["resourceType"] == "IAM.Role" and "suffix" not in artifact[
            "naming_context"
        ].get("target_context", {}):
            pending.append("Selected target suffix configuration is unavailable")
        kind, prop = name["resourceType"], name["property"]
        rules = (
            artifact["naming_context"].get("rules", {}).get(kind.partition(".")[0], [])
        )
        mandatory = {
            pattern
            for rule in rules
            for target_kind, target, pattern, scope in naming_rules(rule["text"])
            if target_kind == kind
            and naming_target_matches(prop, {target}, kind)
            and scope == "mandatory"
        }
        if len(mandatory) > 1 and not patterns and naming_value(name) is not None:
            pending.append("No mandatory pattern can be selected; review required")
        if (
            any(
                "{{suffix}}" in re.sub(r"\[[^\]]*\]", "", pattern)
                for pattern in patterns
            )
            and "suffix" not in confirmed
        ):
            pending.append("Required target suffix is unconfirmed")
        if name["resourceType"] == "Organizations.Policy" and "Type" not in name.get(
            "conditions", {}
        ):
            pending.append(
                "Policy Type is required to determine mandatory pattern applicability"
            )
    return dict(
        status="VIOLATION_CANDIDATE"
        if violations
        else "REVIEW_REQUIRED"
        if pending
        else "AUTO_PASS",
        applied_rules=sorted(patterns),
        rule_refs=["common", name["resourceType"].partition(".")[0]],
        violations=violations,
        pending=pending,
        basis="Mandatory Name, Provider constraints, applicable structure and proven component bindings; recommendations alone are not violations",
    )


def review_names(artifact):
    """Never trust an asserted AUTO_PASS; recompute from the immutable Scan evidence."""
    pending = []
    seen = set()
    target = artifact["naming_context"].get("target_context", {})
    if any("decision" in name for name in artifact["naming"]["names"]) and (
        target.get("environment") != artifact.get("environment")
        or target.get("alias", target.get("awsAccountId")) != artifact.get("target")
        or "suffix" not in target
    ):
        raise ValueError("incomplete Naming target context; rescan required")
    for name in artifact["naming"]["names"]:
        key = required_text(name, "id")
        if key in seen:
            raise ValueError("duplicate naming ID")
        seen.add(key)
        if (
            "naming_context_id" in name
            and name["naming_context_id"] != artifact["naming_context_id"]
        ):
            raise ValueError("Naming item context ID mismatch")
        if "decision" not in name:
            pending.append(name)
            continue
        decision = naming_decision(artifact, name)
        if name["decision"] != decision:
            raise ValueError("Naming decision does not match Scan evidence")
        if decision["status"] != "AUTO_PASS":
            pending.append(name)
    return pending


def validate_naming_issue(artifact, item, name):
    violation = item["violation"]
    applied = required_text(item, "applied_rule")
    if name.get("resourceMode") == "IMPORT" and (
        violation in {"format", "rule_missing"}
        or (
            violation == "required_missing"
            and name["resourceType"] not in {"IAM.Role", "CodeBuild.Project"}
        )
    ):
        raise ValueError("IMPORT is exempt from framework naming conventions")
    candidates = naming_violations(artifact, name)
    if violation == "required_missing" and applied in naming_patterns(artifact, name):
        candidates = [dict(candidate, applied_rule=applied) for candidate in candidates]
    if not any(
        candidate["violation"] == violation
        and candidate["applied_rule"] == applied
        and (
            violation != "confirmed_mismatch"
            or all(
                item.get(key) == candidate.get(key) for key in ("expected", "actual")
            )
        )
        for candidate in candidates
    ):
        raise ValueError(
            "Naming "
            + violation
            + " violation is not established by mandatory constraints and confirmed bindings"
        )
    if violation != "confirmed_mismatch" and (
        "expected" in item
        or ("actual" in item and item["actual"] != literal(name.get("value")))
    ):
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


def assigned_diagnostics(
    artifact: dict[str, Any], assignments: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    services = artifact["services"]
    ordinary = deepcopy(artifact["ordinary"])
    unresolved = []
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
    return ordinary, unresolved


def validate_diagnostic_decisions(
    ordinary: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    confirmations: dict[str, dict[str, Any]],
    services: list[str],
) -> tuple[set[str], list[dict[str, Any]]]:
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
    return excluded, conflicts


def matches_source(source, expected):
    return (
        isinstance(source, dict)
        and isinstance(expected, dict)
        and bool(source.get("path") and (source.get("key") or source.get("line")))
        and all(
            source[key] == expected.get(key)
            for key in ("path", "key", "line")
            if key in source
        )
    )


def matches_naming_item(item, name):
    if any(item.get(key) != name.get(key) for key in ("service", "resource")):
        return False
    prop = item.get("property")
    if not isinstance(prop, str):
        return False
    prop = prop.removeprefix(name.get("resourceType", "") + ".")
    if prop == name.get("property"):
        return True
    if name.get("property") != "Name tag" or prop not in {
        "Tags[].Value",
        "HostedZoneTags[].Value",
        "Tags",
        "HostedZoneTags",
    }:
        return False
    # Only a Scan-proven ordinary Tag may bypass Naming evidence.
    return not any(
        tag.get("is_name") is False
        and tag.get("property") == prop
        and matches_source(item.get("source"), tag.get("source"))
        for tag in name.get("tag_values", [])
    )


def review_additions(
    artifact: dict[str, Any], additions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    services = artifact["services"]
    if not isinstance(additions, list):
        raise ValueError("review issues must be a list")
    if not additions:
        return []
    naming = {item["id"]: item for item in artifact["naming"]["names"]}
    naming_causes = set()
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
                "diagnostic_id",
            }
            or item.get("service") not in services
        ):
            raise ValueError("review Issue ownership requires explicit scoped service")
        required_text(item, "message")
        if "diagnostic_id" in item or any(
            matches_target(record, item) for record in artifact["ordinary"]
        ):
            raise ValueError(
                "Existing diagnostics require diagnostic_decisions, not additional Issues"
            )
        if (
            any(matches_naming_item(item, name) for name in naming.values())
            or any(
                item.get("service") == name.get("service")
                and matches_source(item.get("source"), name.get("source"))
                for name in naming.values()
            )
            or item.get("rule") == "review.naming"
            or "naming_item_id" in item
        ):
            name = naming.get(required_text(item, "naming_item_id"))
            if (
                name is None
                or not matches_naming_item(item, name)
                or (
                    "source" in item
                    and not matches_source(item["source"], name.get("source"))
                )
            ):
                raise ValueError("Naming Issue must match its naming item")
            for key in ("rule", "violation", "evidence"):
                required_text(item, key)
            if any(
                matches_naming_item(record, name) for record in artifact["ordinary"]
            ):
                raise ValueError(
                    "Existing diagnostics require diagnostic_decisions, not additional Issues"
                )
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
            cause = (name["id"], item["violation"])
            if cause in naming_causes:
                raise ValueError("duplicate Naming violation")
            naming_causes.add(cause)
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
    return additions


def validate_review_unverified(
    artifact: dict[str, Any], unverified: list[dict[str, Any]]
) -> None:
    services = artifact["services"]
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
        [item["id"] for item in review_names(artifact)],
        "naming",
    )
    reviewed_ids(
        review["reviewed_judgments"],
        [item["id"] for item in artifact["judgments"]],
        "judgment",
    )
    reviewed_ids(review["reviewed_confirmations"], confirmations, "Human confirmation")
    ordinary, unresolved = assigned_diagnostics(
        artifact, review["diagnostic_assignments"]
    )
    excluded, conflicts = validate_diagnostic_decisions(
        ordinary, review["diagnostic_decisions"], confirmations, services
    )
    additions = review_additions(dict(artifact, ordinary=ordinary), review["issues"])
    diagnostic_index([*ordinary, *additions], services)
    unverified = review["unverified"]
    validate_review_unverified(artifact, unverified)
    data = deepcopy(artifact)
    data["reviewed"] = True
    data["automatically_reviewed_names"] = [
        item["id"]
        for item in artifact["naming"]["names"]
        if item["id"] not in review["reviewed_names"]
    ]
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
