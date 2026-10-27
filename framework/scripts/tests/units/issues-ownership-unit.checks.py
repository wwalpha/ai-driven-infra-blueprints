#!/usr/bin/env python3
"""Cause and owner evidence, independent routing and v6 Review contracts."""

import json
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from issues.artifact import validate_artifact, validation_status
from issues.ownership import resolve
from issues.review import review_snapshot
from issues.runner import validation_issues
from model.core import (
    FrameworkUnsupportedError,
    ModelNeedsFixError,
    ReferenceResolutionError,
)
from model.format import parse
from model.sources import load_model
from model.validations.full_inputs import check_model_inputs as validate_model_inputs
from model.validations.schema import validate_required_properties
from support.issues_scan_fixtures import (
    fixture,
    mechanical,
    review_for,
    snapshot_artifact,
    write_model,
)
from support.pytest_cli import run
from utils.aws_mappings import mapping_alias
from validation.design import check_model_files as validate_models
from validation.design import check_service_file as validate_service
from validation.diagnostics import Diagnostic, InputValidationError, stable_id
from validation.findings import Findings, FindingsError, reference_identity
from validation.framework_contracts import check_structure as validate_structure

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCOPE = {("dev", "team", "iam"), ("dev", "team", "kms")}


def diagnostic(root, **fields):
    return Diagnostic.create(
        root,
        **(
            dict(
                code="test.input",
                check_id="test",
                service=None,
                source_path="model/dev/team/iam.properties",
                message="proven violation",
                cause_kind="input_invalid",
            )
            | fields
        ),
    )


def comparison(root):
    return SimpleNamespace(
        root=root, environment="dev", directory="team", redacted=lambda value: value
    )


@pytest.mark.parametrize(
    "source,explicit,status,owner",
    [
        ("model/dev/team/iam.properties", None, "assigned", ("dev", "team", "iam")),
        ("docs/designs/dev/team/iam.md", None, "assigned", ("dev", "team", "iam")),
        ("model/dev/team/iam.properties", ("dev", "team", "kms"), "unresolved", None),
        ("project.json", None, "unresolved", None),
        (None, None, "unresolved", None),
        (None, ("dev", "team", "iam"), "assigned", ("dev", "team", "iam")),
        ("model/dev/team/s3.properties", None, "outside", ("dev", "team", "s3")),
        ("model/stg/team/iam.properties", None, "outside", ("stg", "team", "iam")),
        ("model/dev/other/iam.properties", None, "outside", ("dev", "other", "iam")),
        (None, ("dev", "team", "INVALID"), "unresolved", None),
        ("model/dev/team/../team/iam.properties", None, "unresolved", None),
    ],
)
def check_owner_evidence(tmp_path, source, explicit, status, owner):
    result = resolve(
        tmp_path,
        diagnostic(
            tmp_path,
            source_path=source,
            service=explicit,
            target_path="model/dev/team/kms.properties",
        ),
        SCOPE,
    )
    assert result["status"] == status and result["owner"] == owner
    assert result["evidence"]


def check_shared_multiple_and_redirected_sources(tmp_path):
    actual, alias = tmp_path / "actual", tmp_path / "alias"
    actual.mkdir()
    alias.symlink_to(actual, target_is_directory=True)
    assert resolve(alias, diagnostic(alias), SCOPE)["owner"] == ("dev", "team", "iam")
    shared = diagnostic(
        tmp_path, source_path="project.json", affected_services=tuple(SCOPE)
    )
    assert resolve(tmp_path, shared, SCOPE)["status"] == "unresolved"
    path = tmp_path / "model/dev/team/iam.properties"
    path.parent.mkdir(parents=True)
    target = path.with_name("kms.properties")
    target.write_text("", encoding="utf-8")
    path.symlink_to(target)
    assert resolve(tmp_path, diagnostic(tmp_path), SCOPE)["status"] == "unresolved"


def check_cause_does_not_change_existing_identity(tmp_path):
    original = diagnostic(
        tmp_path, location="desired.row.001-001.value", cause_key="cause"
    )
    for cause in ("input_invalid", "check_failure", "dependency_wait", "unclassified"):
        classified = replace(original, cause_kind=cause)
        assert classified.identity == original.identity
        assert stable_id(classified.identity) == stable_id(original.identity)
        assert classified.record()["cause_kind"] == cause
    assert original.identity == (
        original.code,
        original.service,
        original.source_path,
        original.target_path,
        original.location,
        original.cause_key,
    )
    typed = Findings(tmp_path, source_path="model/dev/team/iam.properties")
    typed.input_failure(InputValidationError("invalid syntax"))
    typed.check_id = "another.caller"
    typed.input_failure(InputValidationError("invalid syntax"))
    assert len(typed.diagnostics) == 1
    assert typed.diagnostics[0].identity == (
        "validation.input",
        ("dev", "team", "iam"),
        "model/dev/team/iam.properties",
        None,
        None,
        "invalid syntax",
    )


def check_proven_required_property_and_generic_exception(tmp_path):
    findings = Findings(tmp_path, source_path="model/dev/team/iam.properties")
    values = {
        "desired.resource.001.resourceType": "IAM.Role",
        "desired.resource.001.logicalId": "IAM_Role_001",
    }
    result = findings.evaluate(
        "required",
        SCOPE,
        partial(
            validate_required_properties, values, Path(__file__).resolve().parents[4]
        ),
    )
    assert result.status == "FAIL"
    assert any(
        "required provider schema property missing" in d.message
        for d in findings.diagnostics
    )
    assert all(d.cause_kind == "input_invalid" for d in findings.diagnostics)
    findings.evaluate("unexpected", SCOPE, Mock(side_effect=ValueError("same prose")))
    assert [d.cause_kind for d in findings.diagnostics] == [
        "input_invalid",
        "check_failure",
    ]
    ordinary, judgments = validation_issues(
        findings, comparison(tmp_path), ["iam", "kms"]
    )
    assert len(ordinary) == 1 and not judgments
    assert len(findings.processing_errors) == len(findings.unverified) == 1
    assert (
        findings.processing_errors[0]["diagnostic_id"]
        == findings.unverified[0]["diagnostic_id"]
    )


def check_model_read_is_processing_with_proven_owner(tmp_path):
    path = tmp_path / "model/dev/team/iam.properties"
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    findings = Findings(tmp_path)
    with patch(
        "validation.design._imports_model_sources.load_model",
        side_effect=OSError("read denied"),
    ):
        validate_models(findings, tmp_path, {("dev", "team", "iam")})
    ordinary, judgments = validation_issues(findings, comparison(tmp_path), ["iam"])
    assert not ordinary and not judgments
    assert findings.diagnostics[0].cause_kind == "check_failure"
    assert findings.unverified[0]["service"] == "iam"
    assert (
        findings.unverified[0]["diagnostic"]["source_path"]
        == "model/dev/team/iam.properties"
    )


@pytest.mark.parametrize(
    "error,cause",
    [
        (ModelNeedsFixError("bad"), "input_invalid"),
        (FrameworkUnsupportedError("unsupported"), "check_failure"),
        (ReferenceResolutionError("pending"), "dependency_wait"),
    ],
)
def check_reference_taxonomy(tmp_path, error, cause):
    findings = Findings(tmp_path)
    findings.warn(error)
    records = [*findings.reference_errors, *findings.warnings]
    assert records and all(item["cause_kind"] == cause for item in records)
    assert bool(findings.processing_errors) == (cause == "check_failure")
    assert bool(findings.unverified) == (cause != "input_invalid")
    if cause == "dependency_wait":
        assert (
            findings.warnings[0]["diagnostic_id"]
            == findings.unverified[0]["diagnostic_id"]
        )


def check_source_path_and_unstructured_violation_retained(tmp_path):
    findings = Findings(tmp_path)
    path = tmp_path / "docs/designs/dev/team/iam.md"
    validate_service(path, "kms", (), findings=findings)
    findings.check_file(False, path, "unknown cause with IAM in prose")
    ordinary, judgments = validation_issues(findings, comparison(tmp_path), ["iam"])
    assert len(ordinary) == 1 and ordinary[0]["service"] == "iam"
    assert not judgments and len(findings.unverified) == 1
    assert findings.unverified[0]["cause_kind"] == "unclassified"
    assert findings.unverified[0]["service"] == "iam"
    assert len({item["id"] for item in [*ordinary, *findings.unverified]}) == 2


def check_model_syntax_is_explicit_input_error(tmp_path):
    with pytest.raises(InputValidationError):
        parse("not a properties Model")
    with pytest.raises(InputValidationError):
        parse('# model-format: 2\ndesired.row.001-001.value=`{"broken":}`\n')


@pytest.mark.parametrize(
    "cause", ["input_invalid", "check_failure", "dependency_wait", "unclassified"]
)
@pytest.mark.parametrize("assign", [True, False])
def check_v6_owner_assignment_and_unresolved_snapshot(tmp_path, cause, assign):
    findings = Findings(tmp_path)
    findings.add_diagnostic(
        diagnostic(tmp_path, source_path="project.json", cause_kind=cause)
    )
    ordinary, judgments = validation_issues(findings, comparison(tmp_path), ["iam"])
    assert not ordinary and len(judgments) == 1
    data = snapshot_artifact(tmp_path, services=["iam"], target="team")
    data.update(
        judgments=judgments,
        unverified=findings.unverified,
        processing_errors=findings.processing_errors,
    )
    review = review_for(data)
    key = judgments[0]["id"]
    review["diagnostic_assignments"] = {
        key: dict(
            status="assigned", service="iam", evidence="explicit Resource inspected"
        )
        if assign
        else dict(status="unresolved", reason="shared input")
    }
    review["diagnostic_decisions"] = (
        [dict(id=key, outcome="issue", reason="input violation proven")]
        if assign and cause == "input_invalid"
        else []
    )
    validate_artifact(data)
    result = json.loads(review_snapshot(data, review).data)
    assert len(result["ordinary"]) == int(assign and cause == "input_invalid")
    if not result["ordinary"]:
        assert result["unverified"][0]["diagnostic_id"] == key
    assert bool(result["processing_errors"]) == (cause == "check_failure")
    assert validation_status(result) == (
        "ERROR"
        if cause == "check_failure"
        else "FAIL"
        if result["ordinary"]
        else "INCOMPLETE"
    )


@pytest.mark.parametrize(
    "assignment",
    [
        "iam",
        {"status": "assigned", "service": "s3", "evidence": "out of scope"},
        {"status": "assigned", "service": "iam", "evidence": ""},
        {"status": "unresolved", "reason": ""},
    ],
)
def check_review_rejects_unproven_assignment(tmp_path, assignment):
    findings = Findings(tmp_path)
    findings.add_diagnostic(diagnostic(tmp_path, source_path="project.json"))
    _, judgments = validation_issues(findings, comparison(tmp_path), ["iam"])
    data = snapshot_artifact(tmp_path, services=["iam"], target="team")
    data["judgments"] = judgments
    review = review_for(data)
    review["diagnostic_assignments"] = {judgments[0]["id"]: assignment}
    with pytest.raises(ValueError):
        review_snapshot(data, review)


def check_python_owner_needs_no_llm_assignment(tmp_path):
    findings = Findings(tmp_path)
    findings.add_diagnostic(diagnostic(tmp_path))
    ordinary, judgments = validation_issues(findings, comparison(tmp_path), ["iam"])
    assert len(ordinary) == 1 and not judgments
    data = snapshot_artifact(
        tmp_path, services=["iam"], target="team", ordinary=ordinary
    )
    review = review_for(data)
    assert not review["diagnostic_assignments"]
    review_snapshot(data, review)
    review["diagnostic_assignments"] = {
        ordinary[0]["id"]: dict(status="assigned", service="iam", evidence="redundant")
    }
    with pytest.raises(ValueError):
        review_snapshot(data, review)


def check_outside_diagnostics_do_not_require_assignment(tmp_path):
    findings = Findings(tmp_path)
    findings.add_diagnostic(
        diagnostic(tmp_path, source_path="model/stg/team/iam.properties")
    )
    ordinary, judgments = validation_issues(findings, comparison(tmp_path), ["iam"])
    assert not ordinary and not judgments and not findings.unverified
    assert findings.information[0]["ownership"]["status"] == "outside"


def check_wrapped_findings_keep_classification_and_ids(tmp_path):
    child, parent = Findings(tmp_path), Findings(tmp_path)
    child.add_diagnostic(diagnostic(tmp_path))
    parent.evaluate("wrapped", SCOPE, Mock(side_effect=FindingsError(child)))
    assert parent.diagnostics == child.diagnostics
    assert parent.diagnostic_errors == child.diagnostic_errors
    assert not parent.processing_errors


def check_identical_service_failures_keep_independent_ids(tmp_path):
    findings = Findings(tmp_path)
    for owner in sorted(SCOPE):
        findings.processing_failure("worker", {owner}, RuntimeError("same failure"))
    assert len(findings.diagnostics) == len(findings.processing_errors) == 2
    assert len({item["diagnostic_id"] for item in findings.processing_errors}) == 2
    findings.processing_failure(
        "worker", {sorted(SCOPE)[0]}, RuntimeError("different failure")
    )
    assert len(findings.diagnostics) == len(findings.processing_errors) == 3
    assert len({item["diagnostic_id"] for item in findings.processing_errors}) == 3


@pytest.mark.parametrize(
    "fault",
    ["version", "cause", "channel", "duplicate", "known-owner", "cross-channel"],
)
def check_v6_diagnostic_contract_rejects_misrouting(tmp_path, fault):
    findings = Findings(tmp_path)
    findings.add_diagnostic(diagnostic(tmp_path))
    ordinary, _ = validation_issues(findings, comparison(tmp_path), ["iam"])
    data = snapshot_artifact(
        tmp_path, services=["iam"], target="team", ordinary=ordinary
    )
    if fault == "version":
        data["version"] = 5
    elif fault == "cause":
        ordinary[0]["cause_kind"] = "future"
    elif fault == "channel":
        ordinary[0]["cause_kind"] = "unclassified"
    elif fault == "duplicate":
        data["ordinary"] *= 2
    elif fault == "known-owner":
        data["judgments"], data["ordinary"] = ordinary, []
    else:
        data["unverified"] = [
            dict(ordinary[0], cause_kind="check_failure", diagnostic={})
        ]
    with pytest.raises(ValueError):
        validate_artifact(data)


@pytest.mark.parametrize(
    "fault", ["syntax", "required", "property-owner", "service-id", "markdown-required"]
)
def check_real_input_violations_are_never_processing_failures(tmp_path, fault):
    framework = Path(__file__).resolve().parents[4]
    with mapping_alias(framework, tmp_path):
        fixture(tmp_path, services=("s3",))
        model = tmp_path / "model/dev/123456789012/s3.properties"
        view = tmp_path / "docs/designs/dev/123456789012/s3.md"
        values = dict(load_model(model).authoritative)
        if fault == "required":
            for suffix in ("property", "value", "comment"):
                values.pop("desired.row.001-001." + suffix)
            write_model(model, values)
        elif fault == "property-owner":
            values["desired.row.001-003.property"] = "IAM.Role.RoleName"
            write_model(model, values)
        elif fault == "syntax":
            model.write_text("# invalid format\n", encoding="utf-8")
        elif fault == "service-id":
            values["desired.service.s3.serviceId"] = "iam"
            write_model(model, values)
        else:
            view.write_text(
                view.read_text(encoding="utf-8").replace(
                    "- Design service ID:", "- Missing service ID:"
                ),
                encoding="utf-8",
            )
        validators = []
        errors, _, _ = mechanical(
            tmp_path, {("dev", "123456789012", "s3")}, jobs=1, validator_out=validators
        )
    findings = validators[0].findings
    assert errors and not findings.processing_errors, findings.processing_errors
    assert any(d.cause_kind == "input_invalid" for d in findings.diagnostics)
    assert len({d.identity for d in findings.diagnostics}) == len(findings.diagnostics)
    if fault in {"syntax", "required"}:
        inputs = [d for d in findings.diagnostics if d.code == "validation.input"]
        assert len(inputs) == 1
        assert inputs[0].source_path == "model/dev/123456789012/s3.properties"
        if fault == "syntax":
            assert len(findings.diagnostics) == 1
        else:
            assert all(d.cause_kind == "input_invalid" for d in findings.diagnostics)


def check_missing_markdown_headings_scan_to_review(tmp_path):
    framework = Path(__file__).resolve().parents[4]
    with mapping_alias(framework, tmp_path):
        fixture(tmp_path, services=("s3", "sqs"))
        view = tmp_path / "docs/designs/dev/123456789012/s3.md"
        text = view.read_text(encoding="utf-8")
        for heading in ("## リソース一覧", "## リソース詳細"):
            assert heading in text
            text = text.replace(heading, "")
        view.write_text(text, encoding="utf-8")
        validators = []
        mechanical(
            tmp_path,
            {("dev", "123456789012", service) for service in ("s3", "sqs")},
            jobs=1,
            validator_out=validators,
        )
    findings = validators[0].findings
    context = comparison(tmp_path)
    context.directory = "123456789012"
    ordinary, judgments = validation_issues(findings, context, ["s3", "sqs"])
    headings = [
        item
        for item in ordinary
        if item["diagnostic"]["location"] in {"## リソース一覧", "## リソース詳細"}
    ]
    assert len(headings) == 2, (ordinary, judgments, findings.unverified)
    assert len({item["id"] for item in headings}) == 2
    assert all(
        item["cause_kind"] == "input_invalid"
        and item["service"] == "s3"
        and item["diagnostic"]["source_path"] == "docs/designs/dev/123456789012/s3.md"
        and item["diagnostic"]["check_id"] == "design.service"
        for item in headings
    )
    assert not judgments and not findings.processing_errors
    data = snapshot_artifact(tmp_path, services=["s3", "sqs"], ordinary=ordinary)
    validate_artifact(data)
    result = json.loads(review_snapshot(data, review_for(data)).data)
    assert {item["id"] for item in result["ordinary"]} == {
        item["id"] for item in ordinary
    }


@pytest.mark.parametrize("cause", ["input_invalid", "unclassified"])
def check_generic_check_identity_and_deduplication(tmp_path, cause):
    findings = Findings(tmp_path)
    path = tmp_path / "model/dev/team/iam.properties"
    for check in ("rule.one", "rule.two", "rule.one"):
        findings.check(
            False,
            "same prose",
            cause_kind=cause,
            source_path=path,
            check_id=check,
            location="desired.row.001-001.value",
        )
    assert len(findings.diagnostics) == len(findings.errors) == 2
    ordinary, judgments = validation_issues(findings, comparison(tmp_path), ["iam"])
    assert not judgments
    assert len(ordinary) == (2 if cause == "input_invalid" else 0)
    assert len(findings.unverified) == (2 if cause == "unclassified" else 0)
    original = findings.diagnostics[0]
    identities = {
        stable_id(
            replace(
                original, details=dict(resourceLogicalId=resource, property=prop)
            ).identity
        )
        for resource, prop in (("Role1", "Name"), ("Role2", "Name"), ("Role1", "Path"))
    }
    assert len(identities) == 3
    assert (
        replace(original, location="desired.row.002-001.value").identity
        != original.identity
    )


@pytest.mark.parametrize(
    "category", ["REFERENCE_UNRESOLVED", "REFERENCE_PENDING_DEPLOY"]
)
def check_waiting_reference_ids_in_both_channels(tmp_path, category):
    findings = Findings(tmp_path)
    for target, message in (
        ("Key1", "pending"),
        ("Key2", "pending"),
        ("Key1", "translated"),
    ):
        findings.warn(
            ReferenceResolutionError(
                message,
                category=category,
                model="model/dev/team/iam.properties",
                modelKey="desired.row.001-001.value",
                resourceLogicalId="Role1",
                targetLogicalId=target,
                attribute="Arn",
            )
        )
    assert len(findings.warnings) == len(findings.unverified) == 2
    ids = [item["diagnostic_id"] for item in findings.warnings]
    assert len(set(ids)) == 2
    assert ids == [item["diagnostic_id"] for item in findings.unverified]
    assert not findings.errors and not findings.processing_errors
    assert all(item["category"] == category for item in findings.warnings)
    ordinary, judgments = validation_issues(findings, comparison(tmp_path), ["iam"])
    assert not ordinary and not judgments
    data = snapshot_artifact(tmp_path, services=["iam"], target="team")
    data.update(warnings=findings.warnings, unverified=findings.unverified)
    validate_artifact(data)
    result = json.loads(review_snapshot(data, review_for(data)).data)
    assert ids == [item["diagnostic_id"] for item in result["unverified"]]


@pytest.mark.parametrize(
    "category", ["REFERENCE_UNRESOLVED", "REFERENCE_PENDING_DEPLOY"]
)
@pytest.mark.parametrize(
    "field,other",
    [
        ("producerModel", "model/stg/team/kms.properties"),
        ("producerModelKey", "observed.row.002-001.value"),
    ],
)
def check_waiting_reference_producer_identity(tmp_path, category, field, other):
    diagnostic = ReferenceResolutionError(
        "pending",
        category=category,
        model="model/dev/team/iam.properties",
        modelKey="desired.row.001-001.value",
        resourceLogicalId="Role1",
        targetLogicalId="Key1",
        attribute="Arn",
        pointer="/Statement/0/Resource",
        producerModel="model/dev/team/kms.properties",
        producerModelKey="observed.row.001-001.value",
    ).diagnostic
    findings = Findings(tmp_path)
    for item in (diagnostic, dict(diagnostic, **{field: other}), diagnostic):
        findings.warn(item)
    assert len(findings.warnings) == len(findings.unverified) == 2
    ids = [item["diagnostic_id"] for item in findings.warnings]
    assert all(ids) and len(set(ids)) == 2
    assert ids == [item["diagnostic_id"] for item in findings.unverified]
    assert not findings.errors and not findings.processing_errors


@pytest.mark.parametrize(
    "category", ["REFERENCE_UNRESOLVED", "REFERENCE_PENDING_DEPLOY"]
)
@pytest.mark.parametrize("consumer_key", [None, "desired.row.001-001.value"])
def check_waiting_reference_producer_path_normalization(
    tmp_path, category, consumer_key
):
    diagnostic = ReferenceResolutionError(
        "pending",
        category=category,
        model="model/dev/team/iam.properties",
        modelKey=consumer_key,
        targetLogicalId="Key1",
        attribute="Arn",
        producerModelKey="observed.row.001-001.value",
    ).diagnostic
    relative = "model/dev/team/kms.properties"
    findings = Findings(tmp_path)
    for path in (
        relative,
        str(tmp_path / relative),
        relative.replace("/", "\\"),
        str(tmp_path / relative).replace("/", "\\"),
        "./model/dev/team/../team/kms.properties",
    ):
        findings.warn(dict(diagnostic, producerModel=path))
    assert len(findings.warnings) == len(findings.unverified) == 1
    assert (
        findings.warnings[0]["diagnostic_id"] == findings.unverified[0]["diagnostic_id"]
    )


@pytest.mark.parametrize(
    "kind,category,expected",
    [
        (ModelNeedsFixError, "MODEL_NEEDS_FIX", "9928103453da35d7c300"),
        (FrameworkUnsupportedError, "FRAMEWORK_UNSUPPORTED", "d0bc063478c24923355b"),
        (ReferenceResolutionError, "REFERENCE_UNRESOLVED", "a8564548361268499f7c"),
        (
            ReferenceResolutionError,
            "REFERENCE_PENDING_DEPLOY",
            "d3891b2dad18585aa168",
        ),
    ],
)
def check_existing_reference_ids_unchanged(tmp_path, kind, category, expected):
    details = (
        dict(
            producerModel="model/dev/team/kms.properties",
            producerModelKey="observed.row.001-001.value",
        )
        if category in {"MODEL_NEEDS_FIX", "FRAMEWORK_UNSUPPORTED"}
        else {}
    )
    diagnostic = kind(
        "pending",
        category=category,
        model="model/dev/team/iam.properties",
        modelKey="desired.row.001-001.value",
        resourceLogicalId="Role1",
        targetLogicalId="Key1",
        attribute="Arn",
        **details,
    ).diagnostic
    assert stable_id(reference_identity(tmp_path, diagnostic)) == expected


@pytest.mark.parametrize("entrance", ["model", "view"])
def check_model_literal_uses_authority_path(tmp_path, entrance):
    framework = Path(__file__).resolve().parents[4]
    with mapping_alias(framework, tmp_path):
        fixture(tmp_path, services=("s3",))
        path = tmp_path / "model/dev/123456789012/s3.properties"
        values = dict(load_model(path).authoritative)
        row = next(
            key.removesuffix("property") + "value"
            for key, value in values.items()
            if key.endswith(".property")
            and value == "S3.Bucket.VersioningConfiguration.Status"
        )
        values[row] = "`INVALID`"
        source = (
            path
            if entrance == "model"
            else tmp_path / "docs/designs/dev/123456789012/s3.md"
        )
        findings = validate_model_inputs(source, values, tmp_path)
    diagnostics = [
        d for d in findings.diagnostics if d.check_id.startswith("model.literal.")
    ]
    assert diagnostics
    assert all(
        d.source_path == "model/dev/123456789012/s3.properties" for d in diagnostics
    )
    assert all(d.cause_kind == "input_invalid" for d in diagnostics)
    assert all(
        resolve(tmp_path, d, {("dev", "123456789012", "s3")})["owner"]
        == ("dev", "123456789012", "s3")
        for d in diagnostics
    )


def check_shared_framework_input_has_no_guessed_owner(tmp_path):
    findings = Findings(tmp_path)
    validate_structure(findings, tmp_path, consumer=False, definitions_root=tmp_path)
    assert findings.diagnostics
    assert all(d.cause_kind == "input_invalid" for d in findings.diagnostics)
    ordinary, judgments = validation_issues(
        findings, comparison(tmp_path), ["iam", "kms"]
    )
    assert not ordinary and len(judgments) == len(findings.diagnostics)
    assert all(item["ownership"]["status"] == "unresolved" for item in judgments)
    assert all(item["diagnostic"]["source_path"] for item in judgments)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
