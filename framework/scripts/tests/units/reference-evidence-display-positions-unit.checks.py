"""Offline reference proof through the shared evaluator and comparison pipeline."""

import json
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.methods import ORDERED, UNORDERED, CompareOutcome, compare_values
from comparison.references import ReferenceDecision
from comparison.result import identifier, setting_result
from issues.aggregate import aggregate
from issues.artifact import detail_payload
from support.comparison_cases import projected
from support.regression_cases import case_ids
from utils.iac_values import (
    Expression,
    ResourceReference,
    safe_value,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    fixture,
    typed_duplicate_reference,
    unproven_reference,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="ambiguous-unordered-")
)
def test_unordered_ambiguous_reference_has_no_individual_claim(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_ambiguous_unordered)


def _execute_ambiguous_unordered(case):
    refs = [
        ResourceReference({"$resource": ["kms", f"00{i}"], "$attribute": "KeyId"})
        for i in (1, 2)
    ]
    decision = compare_values(
        case["data"]["desired"],
        refs,
        "Setting",
        rules={"Setting": UNORDERED},
        reference=unproven_reference,
    )
    resolver = Mock(return_value=("resolved", "fixture"))
    result = setting_result(
        "test",
        "001",
        "Setting",
        case["data"]["desired"],
        refs,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    TestCase().assertTrue(
        decision.equal is None and result.records[0]["category"] == "uncompared"
    )
    fields = result.display_differences[identifier(result.records[0])]
    TestCase().assertTrue([field["model"] for field in fields] == ["対応未確定"] * 2)
    TestCase().assertTrue(resolver.call_count == 2)
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
        "warnings": projected(result.warnings),
    }


def expression_unconfirmed_reference(left, right, path):
    if not isinstance(right, (Expression, ResourceReference)):
        return ReferenceDecision(NotImplemented)
    equal = True if left == "matched" else None if left == "pending" else False
    if isinstance(right, Expression) and left == "matched":
        equal = right.operands[1][1]["$resource"][1] == "001"
    return ReferenceDecision(
        equal,
        (
            {
                "path": path,
                "model": safe_value(left),
                "iac": safe_value(right),
                "local_comparison": "matched"
                if equal is True
                else "uncompared"
                if equal is None
                else "difference",
                "identity": "unproven",
                "allowed_forms": None,
                "format": {},
                "reason": "fixture",
            },
        ),
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="expression-display-")
)
def test_uncompared_expression_real_correspondence_and_issue_display(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_expression_display)


def _execute_expression_display(case):
    shape = case["data"]["shape"]
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    expr = Expression("Join", ["", ["prefix/", ref]])
    actual = {
        "join": expr,
        "nested": {"Value": expr},
        "nested_join": Expression("Join", ["", ["outer/", expr]]),
        "sub": Expression("Sub", ["prefix/${Key}", {"Key": ref}]),
        "reference": ref,
    }[shape]
    desired = {"Value": "pending"} if shape == "nested" else "pending"
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=expression_unconfirmed_reference,
    )
    TestCase().assertTrue(
        decision.equal is None and decision.correspondence and decision.diagnostics
    )
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args,
        actual_error=None,
        redact=safe_value,
        display_reference=lambda ref: ("resolved", "fixture"),
    )
    TestCase().assertTrue(before.records == after.records and (not after.warnings))
    field = after.display_differences[identifier(after.records[0])][0]
    TestCase().assertTrue(field["model"] == "pending")
    TestCase().assertTrue(
        "resolved" in field["iac"]
        and "kms/001.KeyId" in field["iac"]
        and ("fixture" in field["iac"])
    )
    artifact = dict(
        version=6,
        **aggregate(
            after.records, "fixture", "team", ["test"], after.display_differences
        ),
    )
    TestCase().assertTrue(
        detail_payload(artifact, "iac")["items"][0]["value_differences"] == [field]
    )
    return {
        "records": projected(after.records),
        "display": projected(after.display_differences),
        "detail": detail_payload(artifact, "iac"),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="unordered-expression-")
)
def test_unordered_expression_only_uncompared_selected_and_ambiguous(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_unordered_expression)


def _execute_unordered_expression(case):
    refs = [
        ResourceReference({"$resource": ["kms", f"00{i}"], "$attribute": "KeyId"})
        for i in (1, 2)
    ]
    actual = [Expression("Join", ["", ["prefix/", ref]]) for ref in refs]
    desired = case["data"]["desired"]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": UNORDERED},
        reference=expression_unconfirmed_reference,
    )
    TestCase().assertTrue(
        decision.equal is None and decision.correspondence and decision.diagnostics
    )
    resolver = Mock(return_value=("resolved", "fixture"))
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args, actual_error=None, redact=safe_value, display_reference=resolver
    )
    TestCase().assertTrue(before.records == after.records and (not after.warnings))
    fields = after.display_differences[identifier(after.records[0])]
    TestCase().assertTrue([field["model"] for field in fields] == ["pending"])
    TestCase().assertTrue("kms/002.KeyId" in fields[0]["iac"])
    resolver.assert_called_once_with(refs[1])
    ambiguous = compare_values(
        ["pending", "pending"],
        actual,
        "Setting",
        rules={"Setting": UNORDERED},
        reference=expression_unconfirmed_reference,
    )
    result = setting_result(
        "test",
        "001",
        "Setting",
        ["pending", "pending"],
        actual,
        ambiguous,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    TestCase().assertTrue(ambiguous.equal is None)
    fields = result.display_differences[identifier(result.records[0])]
    TestCase().assertTrue([field["model"] for field in fields] == ["対応未確定"] * 2)
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
        "warnings": projected(result.warnings),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="expression-redaction-")
)
def test_uncompared_expression_redaction_and_resolution_failure(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_expression_redaction)


def _execute_expression_redaction(case):
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    actual = Expression("Join", ["", ["{{resolve:secretsmanager:never-expose}}", ref]])
    decision = compare_values(
        case["data"]["desired"],
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=expression_unconfirmed_reference,
    )
    args = (
        "test",
        "001",
        "Setting",
        case["data"]["desired"],
        actual,
        decision,
        "stack",
        [{}],
        {},
    )
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args,
        actual_error=None,
        redact=safe_value,
        display_reference=Mock(side_effect=ValueError("display bug")),
    )
    TestCase().assertTrue(
        decision.equal is None and decision.correspondence and decision.diagnostics
    )
    TestCase().assertTrue(
        before.records == after.records and after.records[0]["category"] == "uncompared"
    )
    TestCase().assertTrue(
        "never-expose"
        not in json.dumps([after.records, after.warnings, after.display_differences])
    )
    TestCase().assertTrue("ValueError: display bug" in after.warnings[0]["message"])
    TestCase().assertTrue(
        "未解決" in after.display_differences[identifier(after.records[0])][0]["iac"]
    )
    return {
        "records": projected(after.records),
        "display": projected(after.display_differences),
        "warnings": projected(after.warnings),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="duplicate-evidence-")
)
def test_uncompared_duplicate_positions_and_ambiguous_evidence(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_duplicate_evidence)


def _execute_duplicate_evidence(case):
    ref = ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    desired = case["data"]["desired"]
    actual = [ref, ref]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=lambda left, right, path: ReferenceDecision(None),
    )
    TestCase().assertTrue(decision.equal is None and (not decision.diagnostics))
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    batch = setting_result(
        *args,
        actual_error=None,
        redact=safe_value,
        display_reference=lambda ref: ("resolved", "Observed"),
    )
    fields = batch.display_differences[identifier(batch.records[0])]
    TestCase().assertTrue([field["model"] for field in fields] == desired)
    TestCase().assertTrue(
        [field["path"] for field in fields]
        == ["IaC:[0]（参照情報）", "IaC:[1]（参照情報）"]
    )
    TestCase().assertTrue(all(("kms/007.KeyId" in field["iac"] for field in fields)))
    ambiguous = CompareOutcome(
        None, correspondence=(((0,), (0,)), ((0,), (1,)), ((1,), (1,)))
    )
    result = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        ambiguous,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=lambda ref: ("resolved", "Observed"),
    )
    TestCase().assertTrue(
        [
            field["model"]
            for field in result.display_differences[identifier(result.records[0])]
        ]
        == ["対応未確定", "second"]
    )
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
        "warnings": projected(result.warnings),
    }


def pending_only_display(ref):
    if ref["$resource"][1] != "002":
        raise ValueError("unnecessary")
    return "resolved", "fixture"


def alternating_duplicate_reference(outcomes, left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    equal = next(outcomes)
    return ReferenceDecision(
        equal,
        (
            {
                "path": path,
                "model": left,
                "iac": right,
                "local_comparison": "matched" if equal else "uncompared",
            },
        ),
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="ordered-duplicate-")
)
def test_ordered_duplicate_matched_reference_is_not_displayed(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_ordered_duplicate)


def _execute_ordered_duplicate(case):
    join = case["data"]["join"]
    refs = [
        ResourceReference({"$resource": ["kms", identity], "$attribute": "KeyId"})
        for identity in ("001", "001", "002")
    ]
    actual = (
        [Expression("Join", ["", ["prefix/", ref]]) for ref in refs] if join else refs
    )
    desired = ["matched", "matched", "pending"]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=expression_unconfirmed_reference,
    )
    resolver = Mock(side_effect=pending_only_display)
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args, actual_error=None, redact=safe_value, display_reference=resolver
    )
    TestCase().assertTrue(
        decision.equal is None
        and before.records == after.records
        and (not after.warnings)
    )
    fields = after.display_differences[identifier(after.records[0])]
    TestCase().assertTrue(len(fields) == 1 and fields[0]["model"] == "pending")
    TestCase().assertTrue(
        "kms/002.KeyId" in fields[0]["iac"] and "fixture" in fields[0]["iac"]
    )
    resolver.assert_called_once_with(refs[2])
    artifact = dict(
        version=6,
        **aggregate(
            after.records, "fixture", "team", ["test"], after.display_differences
        ),
    )
    TestCase().assertTrue(
        detail_payload(artifact, "iac")["items"][0]["value_differences"] == fields
    )
    return {
        "records": projected(after.records),
        "display": projected(after.display_differences),
        "detail": detail_payload(artifact, "iac"),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="duplicate-status-")
)
def test_duplicate_key_with_different_statuses_uses_positions(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_duplicate_status)


def _execute_duplicate_status(case):
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    desired, actual = (case["data"]["desired"], [ref, ref])
    outcomes = iter((True, None))
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=partial(alternating_duplicate_reference, outcomes),
    )
    resolver = Mock(return_value=("resolved", "fixture"))
    result = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    TestCase().assertTrue(decision.equal is None)
    fields = result.display_differences[identifier(result.records[0])]
    TestCase().assertTrue(
        len(fields) == 1 and fields[0]["path"] == "IaC:[1]（比較未確定）"
    )
    resolver.assert_called_once()
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
        "warnings": projected(result.warnings),
    }


def missing_duplicate_reference(outcomes, left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    has_evidence = next(outcomes)
    diagnostic = {
        "path": path,
        "model": left,
        "iac": right,
        "local_comparison": "matched",
    }
    return ReferenceDecision(
        True if has_evidence else None, (diagnostic,) if has_evidence else ()
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="duplicate-missing-")
)
def test_duplicate_position_evidence_missing_or_correspondence_ambiguous(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_duplicate_missing)


def _execute_duplicate_missing(case):
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    desired, actual = (case["data"]["desired"], [ref, ref])
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=partial(missing_duplicate_reference, iter((True, False))),
    )
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    resolver = Mock(return_value=("resolved", "fixture"))
    result = setting_result(
        *args, actual_error=None, redact=safe_value, display_reference=resolver
    )
    fields = result.display_differences[identifier(result.records[0])]
    TestCase().assertTrue(
        len(fields) == 1 and fields[0]["path"] == "IaC:[1]（参照情報）"
    )
    ambiguous = replace(
        decision, correspondence=(((0,), (0,)), ((0,), (1,)), ((1,), (1,)))
    )
    result = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        ambiguous,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    fields = result.display_differences[identifier(result.records[0])]
    TestCase().assertTrue(len(fields) == 2 and fields[0]["model"] == "対応未確定")
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="typed-duplicate-")
)
def test_typed_duplicate_position_evidence(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_typed_duplicate)


def _execute_typed_duplicate(case):
    shape = case["data"]["shape"]
    masked = case["data"]["masked"]
    comparison = fixture()
    if masked:
        comparison.sensitive_values.add("confirmed")
    refs = [
        ResourceReference({"$resource": ["kms", identity], "$attribute": "KeyId"})
        for identity in ("001", "001", "002")
    ]
    actual = refs
    if shape == "join":
        actual = [Expression("Join", ["", ["prefix/", ref]]) for ref in refs]
    elif shape == "sub":
        actual = [Expression("Sub", ["${Key}", {"Key": ref}]) for ref in refs]
    desired = ["confirmed", "confirmed", "pending"]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=partial(
            typed_duplicate_reference, comparison, iter((True, True, None))
        ),
        diagnostic_kind="KMS.Key",
    )
    baseline_resolver = Mock(return_value=("resolved", "fixture"))
    baseline = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        replace(decision, reference_positions=()),
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=comparison.redacted,
        display_reference=baseline_resolver,
    )
    TestCase().assertTrue(
        len(baseline.display_differences[identifier(baseline.records[0])]) == 3
    )
    TestCase().assertTrue(baseline_resolver.call_count == 3)
    resolver = Mock(side_effect=pending_only_display)
    batch = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=comparison.redacted,
        display_reference=resolver,
    )
    TestCase().assertTrue(decision.equal is None)
    TestCase().assertTrue(
        [d["path"] for d in decision.diagnostics] == ["KMS.Key.Setting[]"] * 3
    )
    TestCase().assertTrue(
        decision.reference_positions
        == (
            ((0,), (0,), "matched"),
            ((1,), (1,), "matched"),
            ((2,), (2,), "uncompared"),
        )
    )
    fields = batch.display_differences[identifier(batch.records[0])]
    TestCase().assertTrue(len(fields) == 1 and fields[0]["model"] == "pending")
    TestCase().assertTrue("kms/002.KeyId" in fields[0]["iac"])
    resolver.assert_called_once_with(refs[2])
    TestCase().assertTrue(not batch.warnings)
    artifact = dict(
        version=6,
        **aggregate(
            batch.records, "fixture", "team", ["test"], batch.display_differences
        ),
    )
    TestCase().assertTrue(
        detail_payload(artifact, "iac")["items"][0]["value_differences"] == fields
    )
    if masked:
        TestCase().assertTrue(
            "confirmed"
            not in json.dumps(
                [batch.records, batch.warnings, batch.display_differences]
            )
        )
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
        "detail": detail_payload(artifact, "iac"),
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
