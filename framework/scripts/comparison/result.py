"""Comparison records and display evidence; predicates run before output redaction."""

import hashlib
import json
import re
from dataclasses import dataclass, field

from utils.iac_values import safe_value

import comparison.values as _imports_comparison_values

from .deferral import failure_category
from .methods import MISSING


def identifier(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:20]


def safe_text(text):
    value = safe_value(text)
    value = re.sub(
        r"(?i)((?:password|secretstring|token|credential)\s*[=:]\s*)[^\s,;]+",
        r"\1<masked>",
        value,
    )
    return value.replace("\n", " ").replace("\r", " ")


def _formatted(value):
    if value is MISSING:
        return "欠落"
    if (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z_$][\w ./$:-]*", value)
        and value not in {"null", "true", "false"}
    ):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _difference_path(path):
    if isinstance(path, str):
        return path
    if len(path) == 3:
        parent, key, value = path
        return _difference_path(parent) + f"[{key}={_formatted(safe_value(value))}]"
    parent, suffix = path
    return _difference_path(parent) + suffix


def _shown_value(raw, pointer, shown):
    if raw is MISSING or pointer is None:
        return raw
    for token in pointer:
        # A secret enclosing object can already have been replaced by a mask.
        if not isinstance(shown, (dict, list)):
            return shown
        shown = shown[token]
    return shown


def value_differences(
    decision, desired, actual, property_name="", *, redact=safe_value
):
    """Render the detector's evidence; never compare values or resolve references."""
    left, right = redact(desired, property_name), redact(actual, property_name)
    return [
        {
            "path": safe_text(_difference_path(item.path) or property_name),
            "model": _formatted(_shown_value(item.model, item.model_pointer, left)),
            "iac": _formatted(_shown_value(item.iac, item.iac_pointer, right)),
        }
        for item in decision.differences
    ]


def redacted(value, prop="", *, sensitive_values=()):
    value = safe_value(value, prop)
    if prop in {
        "id",
        "service",
        "resource",
        "resourceType",
        "resourceMode",
        "property",
        "stack",
        "code",
        "naming_context_id",
        "job_id",
        "diagnostic_id",
        "scope",
    }:
        return value
    if isinstance(value, str) and any(
        secret in value for secret in sensitive_values if secret
    ):
        return "<masked sensitive parameter>"
    if isinstance(value, dict):
        return {
            key: redacted(item, key, sensitive_values=sensitive_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            redacted(item, prop, sensitive_values=sensitive_values) for item in value
        ]
    return value


def record(
    category,
    service,
    identity,
    prop,
    reason,
    desired=None,
    actual=None,
    stack=None,
    source=None,
    template=None,
    cause=None,
    *,
    redact=safe_value,
    **details,
):
    result = dict(
        category=category,
        service=service,
        resource=identity,
        property=prop,
        reason=reason,
        desired=redact(desired, prop),
        actual=redact(actual, prop),
        stack=stack,
        model=source,
        iac=template,
    )
    if cause:
        result["cause"] = redact(cause)
    result.update(details)
    return result


@dataclass
class RowResult:
    records: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    display_differences: dict = field(default_factory=dict)
    failure: Exception | None = None


def setting_result(
    service,
    identity,
    prop,
    desired,
    actual,
    decision,
    stack,
    sources,
    template,
    *,
    actual_error,
    redact,
    cause=None,
    default_source=None,
    missing=None,
    deferred_children=(),
):
    unverified = _imports_comparison_values.unverified
    source = sources[0] or default_source
    if decision.equal is None:
        item = record(
            failure_category(actual_error)
            if actual_error is not None
            else "uncompared",
            service,
            identity,
            prop,
            str(actual_error)
            if actual_error is not None
            else "reference identity or property format is unproven",
            stack=None if actual_error is not None else stack,
            source=source,
            template=template,
            cause=getattr(actual_error, "iac_cause", None),
            redact=redact,
            reference_diagnostics=list(decision.diagnostics),
        )
        return RowResult([item])
    if decision.equal:
        return RowResult(
            [
                record(
                    "matched",
                    service,
                    identity,
                    prop,
                    "reference expression equivalent"
                    if decision.equivalent
                    else "equal",
                    stack=stack,
                    source=source,
                    template=template,
                    redact=redact,
                    **(
                        {"reference_diagnostics": list(decision.diagnostics)}
                        if decision.diagnostics
                        else {}
                    ),
                )
            ]
        )
    details = {"model_sources": sources}
    if deferred_children:
        details["deferred_children"] = list(deferred_children)
    reason = missing or "value mismatch"
    if decision.diagnostics:
        details["reference_diagnostics"] = list(decision.diagnostics)
        errors = [
            item["reason"]
            for item in decision.diagnostics
            if item["reason"].startswith("KMS format")
            and item["reason"] != "KMS format is unproven"
        ]
        if errors:
            reason = "; ".join(dict.fromkeys(errors))
    # The predicate sees raw values; masking is applied only to emitted evidence.
    differences = value_differences(decision, desired, actual, prop, redact=redact)
    item = record(
        "difference",
        service,
        identity,
        prop,
        reason,
        desired,
        None if missing else actual,
        stack,
        source,
        template,
        cause,
        redact=redact,
        **details,
    )
    records = [item]
    for pointer in sorted(
        set(unverified(desired)) | (set() if missing else set(unverified(actual)))
    ):
        records.append(
            record(
                "uncompared",
                service,
                identity,
                prop + "#" + pointer,
                "unresolved/unverified intrinsic; JSON Pointer=" + repr(pointer),
                stack=stack,
                source=source,
                template=template,
                redact=redact,
            )
        )
    return RowResult(records, display_differences={identifier(item): differences})
