#!/usr/bin/env python3
"""Ownership, artifact evidence and validation completion contracts."""

import sys
from contextlib import ExitStack
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import issues.runner as scan_runner
import pytest
import sync_runtime
from issues.runner import validation_issues
from model.core import ReferenceResolutionError
from support.pytest_cli import run
from validation import design_tables
from validation.design_links import check_design_artifacts as validate_artifacts
from validation.design_links import check_local_links as validate_links
from validation.diagnostics import ArtifactReferences, Diagnostic, service_scope
from validation.findings import Findings, FindingsError
from validation.runner import Validator

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def comparison(root):
    return SimpleNamespace(
        root=root, environment="dev", directory="team", redacted=lambda value: value
    )


def mismatch_plan(root):
    return sync_runtime.Generation(
        root, root / "stage", set(), [], [], None, ExitStack()
    )


def check_generation_file_ownership(tmp_path):
    plan = mismatch_plan(tmp_path)
    services = ["codepipeline", "iam", "s3", "sqs"]
    for service in services:
        view = tmp_path / "docs/designs/dev/team" / f"{service}.md"
        artifact = view.with_suffix("") / "same-name.json"
        plan.expected_outputs[view] = {view: "expected", artifact: "{}"}
    sync_runtime._compare_generation(plan)
    assert len(plan.failure_records) == 8
    assert len(plan.failures) == 8 and not plan.saved
    findings = Findings(tmp_path)
    for diagnostic in plan.failure_records * 2:
        findings.add_diagnostic(diagnostic)
    ordinary, judgments = validation_issues(findings, comparison(tmp_path), services)
    assert not judgments and len(ordinary) == 8
    assert {item["service"] for item in ordinary} == set(services)
    assert len({item["id"] for item in ordinary}) == 8
    assert all(item["diagnostic"]["target_path"] for item in ordinary)
    before = {item["id"] for item in ordinary}
    findings.diagnostics = [
        replace(d, message="new translated prose")
        for d in reversed(findings.diagnostics)
    ]
    assert {
        item["id"]
        for item in validation_issues(findings, comparison(tmp_path), services)[0]
    } == before


def check_shared_cause_keeps_owners_and_unknown(tmp_path):
    findings = Findings(tmp_path)
    affected = (("dev", "team", "s3"), ("dev", "team", "sqs"))
    for owner in affected:
        findings.add_diagnostic(
            Diagnostic.create(
                tmp_path,
                code="generation.render",
                check_id="generated",
                service=owner,
                source_path=tmp_path / "model/dev/team" / f"{owner[2]}.properties",
                message="same resource and cause",
                cause_key="proven-producer-row-001",
                affected_services=affected,
                location="desired.row.001-001",
            )
        )
    findings.add_diagnostic(
        Diagnostic.create(
            tmp_path,
            code="generation.candidate",
            check_id="generated",
            service=None,
            message="s3 and sqs: unknown",
            affected_services=affected,
        )
    )
    ordinary, judgments = validation_issues(
        findings, comparison(tmp_path), ["s3", "sqs"]
    )
    assert {item["service"] for item in ordinary} == {"s3", "sqs"}
    assert len(judgments) == 1 and judgments[0]["service"] is None
    assert all(
        item["diagnostic"]["cause_key"] == "proven-producer-row-001"
        for item in ordinary
    )
    assert service_scope(tmp_path, tmp_path / "outside/s3.md") is None


def check_equal_messages_do_not_hide_another_service_failure(tmp_path):
    findings = Findings(tmp_path)
    for service in ("s3", "sqs"):
        diagnostic = Diagnostic.create(
            tmp_path,
            code="generation.render",
            check_id="generated",
            service=("dev", "team", service),
            source_path=f"model/dev/team/{service}.properties",
            message="same resource name and error",
        )
        result = findings.evaluate(
            "generated",
            {diagnostic.service},
            partial(findings.add_diagnostic, diagnostic),
        )
        assert result.status == "FAIL"
    assert len(findings.errors) == len(findings.diagnostics) == 2


def artifacts_fixture(root, *, complete=True):
    view = root / "docs/designs/dev/team/iam.md"
    view.parent.mkdir(parents=True)
    view.write_text("# IAM\n", encoding="utf-8")
    index = ArtifactReferences()
    index.start(view)
    if complete:
        index.finish(view)
    return view, index


@pytest.mark.parametrize("missing,extra", [(True, False), (False, True), (True, True)])
def check_artifact_differences(tmp_path, missing, extra):
    view, index = artifacts_fixture(tmp_path)
    absent = view.with_suffix("") / "missing.json"
    orphan = view.with_suffix("") / "extra.json"
    if missing:
        index.add(absent, view, ("dev", "team", "iam"))
    if extra:
        orphan.parent.mkdir()
        orphan.write_text("{}", encoding="utf-8")
    findings = Findings(tmp_path)
    findings.evaluate(
        "design.artifacts",
        {("dev", "team", "iam")},
        partial(
            validate_artifacts,
            [view],
            accounts={("dev", "team"): {}},
            findings=findings,
            markdown_design_artifacts=index,
            root=tmp_path,
        ),
    )
    assert [d.code for d in findings.diagnostics] == (
        ["design.artifact.missing"] if missing else []
    ) + (["design.artifact.unreferenced"] if extra else [])
    for diagnostic in findings.diagnostics:
        assert diagnostic.service == ("dev", "team", "iam")
        assert diagnostic.target_path.endswith(".json")
        assert diagnostic.source_path == (
            "docs/designs/dev/team/iam.md"
            if diagnostic.code.endswith("missing")
            else None
        )


def check_incomplete_collection_preserves_missing_and_independent_service(tmp_path):
    view, index = artifacts_fixture(tmp_path, complete=False)
    index.add(view.with_suffix("") / "missing.json", view, ("dev", "team", "iam"))
    orphan = view.with_suffix("") / "unknown.json"
    orphan.parent.mkdir()
    orphan.write_text("{}", encoding="utf-8")
    independent = view.with_name("s3.md")
    independent.write_text("# S3\n", encoding="utf-8")
    index.start(independent)
    index.finish(independent)
    extra = independent.with_suffix("") / "extra.json"
    extra.parent.mkdir()
    extra.write_text("{}", encoding="utf-8")
    findings = Findings(tmp_path)
    result = findings.evaluate(
        "design.artifacts",
        None,
        partial(
            validate_artifacts,
            [view, independent],
            accounts={("dev", "team"): {}},
            findings=findings,
            markdown_design_artifacts=index,
            root=tmp_path,
        ),
    )
    assert result.status == "FAIL" and result.metadata["complete"] is False
    assert len(findings.diagnostics) == 2
    assert {d.code for d in findings.diagnostics} == {
        "design.artifact.missing",
        "design.artifact.unreferenced",
    }
    assert findings.diagnostics[1].service[2] == "s3"
    assert findings.unverified[0]["target_path"].endswith("unknown.json")


@pytest.mark.parametrize("stage", ["reference", "security-group"])
def check_expansion_failure_does_not_claim_unreferenced(tmp_path, stage):
    view, index = artifacts_fixture(tmp_path)
    artifact = view.with_suffix("") / "retained.json"
    artifact.parent.mkdir()
    artifact.write_text("{}", encoding="utf-8")
    validator = Validator(tmp_path, {("dev", "team", "iam")})
    validator.markdown_design_artifacts = index
    validator.accounts = {("dev", "team"): {}}
    with (
        patch.object(design_tables, "design_model_values", return_value={}),
        patch.object(design_tables, "bound_resource_anchors", return_value={}),
        patch.object(
            design_tables._design_document,
            "model_reference_tables",
            side_effect=ValueError("expansion") if stage == "reference" else None,
            return_value=[],
        ),
        patch.object(
            design_tables._design_document,
            "model_resource_reference_tables",
            side_effect=ValueError("expansion"),
        ),
        patch.object(
            design_tables,
            "security_group_table_lines",
            side_effect=ValueError("expansion") if stage == "security-group" else None,
            return_value=[],
        ),
    ):
        validator.check_design_tables({}, set(), {}, {}, [view])
    validator.findings.evaluate(
        "design.artifacts",
        validator.scope,
        partial(validator.check_design_artifacts, [view]),
    )
    assert index.complete[view] is False
    assert not validator.findings.diagnostics
    assert validator.findings.unverified


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({}, "PASS"),
        ({"complete": False}, "NOT_RUN"),
        ({"status": "NOT_RUN"}, "NOT_RUN"),
        ({"status": "FAIL"}, "FAIL"),
        ({"unavailable_services": {"dev/team/iam": {}}}, "NOT_RUN"),
        ({"unverified": [{"code": "not-executed"}]}, "NOT_RUN"),
    ],
)
def check_metadata_completion(tmp_path, metadata, expected):
    findings = Findings(tmp_path)
    result = findings.evaluate("test", set(), Mock(return_value=metadata))
    assert result.status == expected and findings.status == expected
    assert isinstance(result.metadata["unverified"], list)
    assert isinstance(result.metadata["unavailable_services"], dict)
    if expected == "NOT_RUN":
        assert result.metadata["complete"] is False


@pytest.mark.parametrize(
    "metadata",
    [
        {"unverified": {}},
        {"unverified": ["bad"]},
        {"unavailable_services": []},
        {"unavailable_services": {"iam": []}},
        {"complete": 1},
        {"status": "unknown"},
    ],
)
def check_invalid_metadata_is_processing_failure(tmp_path, metadata):
    findings = Findings(tmp_path)
    result = findings.evaluate("test", None, Mock(return_value=metadata), isolate=True)
    assert result.status == "FAIL" and result.metadata["complete"] is False
    assert findings.processing_errors and findings.unverified


def fail_with_warning(findings):
    findings.check(False, "confirmed mismatch")
    findings.warn(ReferenceResolutionError("pending"))
    return {"unavailable_services": {"dev/team/iam": {"reason": "reference"}}}


def check_fail_with_unverified_reference(tmp_path):
    findings = Findings(tmp_path)
    result = findings.evaluate("generated", None, partial(fail_with_warning, findings))
    assert result.status == "FAIL" and result.metadata["complete"] is False
    assert result.metadata["unverified"] and result.metadata["unavailable_services"]
    assert not result.model_completion_allowed


def check_compare_forwards_and_skips_reference_duplicates(tmp_path):
    plan = mismatch_plan(tmp_path)
    path = tmp_path / "model/dev/team/iam.properties"
    sync_runtime.generation_failure(
        tmp_path,
        plan.failure_records,
        "generation.reference",
        path,
        "reference diagnostic",
    )
    sync_runtime.generation_failure(
        tmp_path, plan.failure_records, "generation.model", path, "independent failure"
    )
    findings = Findings(tmp_path)
    with (
        patch.object(sync_runtime, "prepare_generation", return_value=plan),
        patch.object(sync_runtime, "validate_generation"),
    ):
        result = findings.evaluate(
            "framework.generated-service-model",
            None,
            partial(sync_runtime.compare_generation, tmp_path, None, findings=findings),
        )
    assert findings.errors == ["independent failure"]
    assert len(findings.diagnostics) == 1 and result.status == "FAIL"
    parent = Findings(tmp_path)
    parent.include_diagnostics(findings)
    parent.include_diagnostics(findings)
    assert parent.diagnostics == findings.diagnostics


def check_missing_link_and_artifact_are_one_diagnostic(tmp_path):
    view, index = artifacts_fixture(tmp_path)
    missing = view.with_suffix("") / "missing.json"
    index.add(missing, view, ("dev", "team", "iam"))
    findings = Findings(tmp_path)
    validate_links(
        view,
        "[JSON](iam/missing.json)",
        anchors={},
        unavailable=set(),
        findings=findings,
        root=tmp_path,
        design_index=None,
    )
    validate_artifacts(
        [view],
        accounts={("dev", "team"): {}},
        findings=findings,
        markdown_design_artifacts=index,
        root=tmp_path,
    )
    assert len(findings.diagnostics) == len(findings.errors) == 1


def policy_fixture(validator):
    service = next(iter(validator.scope))[2]
    result = validator.findings.result("framework.policy-tables", validator.scope)
    if service == "s3":
        validator.check(False, "confirmed policy error")
        result.status, result.errors = "FAIL", ("confirmed policy error",)
    else:
        result.metadata.update(
            complete=False,
            reason="reference",
            unavailable_services={"dev/team/sqs": {"reason": "reference"}},
            unverified=[{"code": "reference-wait"}],
        )


def check_policy_fail_retains_other_service_unverified_scope(tmp_path):
    validator = Validator(
        tmp_path, {("dev", "team", "s3"), ("dev", "team", "sqs")}, workers=1
    )
    validator.schema_catalog = object()
    with (
        patch.object(Validator, "check_design_service_ownership"),
        patch.object(Validator, "check_stack_designs"),
        patch.object(Validator, "check_generated_service_models"),
        patch.object(Validator, "check_designs", policy_fixture),
        patch.object(Validator, "check_observed_values"),
    ):
        validator.check_scoped_designs()
    result = validator.findings.result("framework.policy-tables", validator.scope)
    assert result.status == "FAIL" and result.metadata["complete"] is False
    assert result.metadata["unavailable_services"] == {
        "dev/team/sqs": {"reason": "reference"}
    }
    assert result.metadata["unverified"] == [{"code": "reference-wait"}]


def check_candidate_failure_preserves_each_artifact_diagnostic(tmp_path):
    view = tmp_path / "docs/designs/dev/team/iam.md"
    stage = tmp_path / "stage"
    findings = Findings(stage)
    for name in ("one.json", "two.json"):
        findings.add_diagnostic(
            Diagnostic.create(
                stage,
                code="design.artifact.missing",
                check_id="design.artifacts",
                service=("dev", "team", "iam"),
                source_path="docs/designs/dev/team/iam.md",
                target_path=f"docs/designs/dev/team/iam/{name}",
                message=f"missing {name}",
            )
        )
    failures, generated = [], {view: []}
    with (
        patch.object(
            sync_runtime.sync_views,
            "validate_views",
            side_effect=FindingsError(findings),
        ),
        patch.object(sync_runtime, "restore_view"),
    ):
        sync_runtime.validate_candidates(
            stage, tmp_path, generated, {view: {}}, failures, 1, False
        )
    assert not generated and failures == findings.diagnostics


def mechanical_fixture(validator, *args, validator_out, **kwargs):
    validator_out.append(validator)
    return validator.errors, validator.checks, ""


def check_scan_artifact_keeps_diagnostics_and_incomplete_metadata(tmp_path):
    findings = Findings(tmp_path)
    diagnostic = Diagnostic.create(
        tmp_path,
        code="generation.mismatch",
        check_id="framework.generated-service-model",
        service=("dev", "team", "s3"),
        source_path="model/dev/team/s3.properties",
        target_path="docs/designs/dev/team/s3.md",
        message="confirmed mismatch",
    )
    findings.add_diagnostic(diagnostic)
    findings.errors.append("wrapper: " + diagnostic.message)
    findings.result(
        "framework.generated-service-model", {("dev", "team", "s3")}
    ).metadata.update(
        complete=False,
        unavailable_services={"dev/team/s3": {"reason": "reference"}},
        unverified=[{"code": "not-executed", "reason": "reference"}],
    )
    validator = SimpleNamespace(findings=findings, errors=findings.errors, checks=2)
    source = comparison(tmp_path)
    source.run = Mock(return_value=[])
    source.rows, source.models, source.metrics, source.display_differences = (
        {},
        {},
        {},
        {},
    )
    source.warnings, source.view_errors, source.catalog = [], {}, None
    lint = dict(
        jobs=[],
        coverage=[],
        status="checked",
        **{
            name: []
            for name in (
                "ordinary",
                "judgments",
                "warnings",
                "information",
                "unverified",
                "processing_errors",
            )
        },
    )
    with (
        patch.object(scan_runner, "Comparison", return_value=source),
        patch.object(
            scan_runner,
            "mechanical",
            side_effect=partial(mechanical_fixture, validator),
        ),
        patch.object(scan_runner, "view_text", return_value=""),
        patch.object(scan_runner, "review_materials", return_value=[]),
        patch.object(scan_runner, "naming_materials", return_value=({"names": []}, [])),
        patch.object(
            scan_runner, "human_confirmations", return_value={"confirmations": []}
        ),
        patch.object(scan_runner, "target_services", return_value=["s3"]),
        patch.object(
            scan_runner._imports_issues_cfn_lint, "run_lint", return_value=lint
        ),
    ):
        first = scan_runner.scan(tmp_path, "dev", "team", ["s3"])
    assert first["version"] == 4
    assert (
        first["ordinary"][0]["diagnostic"]["source_path"]
        == "model/dev/team/s3.properties"
    )
    assert (
        first["ordinary"][0]["id"]
        == validation_issues(findings, source, ["s3"])[0][0]["id"]
    )
    result = first["check_results"][0]
    assert result["status"] == "NOT_RUN" and result["complete"] is False
    assert result["unavailable_services"] and result["unverified"]
    assert first["unverified"]


if __name__ == "__main__":
    raise SystemExit(run(__file__))
