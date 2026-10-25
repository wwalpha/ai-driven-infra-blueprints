"""Display cause identity, validation evidence and lossless reports; offline fixtures."""

import json
import sys
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from functools import partial
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import issues.runner as scan_runner
import pytest
import sync_runtime
from comparison.result import redacted
from design.document import (
    DisplayMismatchError,
    SavedIdentityError,
    model_reference_tables,
    model_resource_reference_tables,
    require_saved_identity,
)
from issues.aggregate import MAX_EXAMPLES, MAX_GROUPS
from issues.artifact import detail_payload, validate_artifact
from issues.publication import render_snapshot
from issues.reports import ordinary_report
from issues.review import review_snapshot
from issues.runner import validation_issues
from model.core import ReferenceDiagnosticError
from model.render import generate_markdown
from support.issues_scan_fixtures import review_for, snapshot_artifact
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from support.pytest_cli import run
from utils.aws_mappings import mapping_alias
from utils.input_cache import input_context
from validation import design, design_links, design_tables
from validation.diagnostics import (
    ArtifactReferences,
    Diagnostic,
    display_diagnostics,
    stable_id,
)
from validation.findings import Findings, finish_result

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture
def pipeline(tmp_path):
    with (
        mapping_alias(FRAMEWORK, tmp_path),
        patch("socket.socket", side_effect=AssertionError("network forbidden")),
    ):
        project(tmp_path)
        scope, producer = resource(
            tmp_path, "codebuild", "CodeBuild.Project", attribute="Name"
        )
        producer["desired.row.001-001.value"] = "`build-project`"
        save(scope, producer)
        view = tmp_path / "docs/designs/qa/team/codebuild.md"
        view.parent.mkdir(parents=True)
        view.write_text(generate_markdown(view, producer, FRAMEWORK), encoding="utf-8")
        scope, values = resource(
            tmp_path, "codepipeline", "CodePipeline.Pipeline", attribute="Name"
        )
        values["desired.row.001-001.value"] = "`pipeline`"
        number = 2
        for stage in (1, 2):
            for action in (1, 2):
                for field, value in (
                    ("Name", f"action-{stage}-{action}"),
                    ("ActionTypeId.Category", "Build"),
                    ("ActionTypeId.Owner", "AWS"),
                    ("ActionTypeId.Provider", "CodeBuild"),
                    ("ActionTypeId.Version", "1"),
                    (
                        "Configuration",
                        {"ProjectName": reference("CodeBuild_Project_001", "Name")},
                    ),
                ):
                    row = f"desired.row.001-{number:03d}."
                    values[row + "property"] = (
                        "CodePipeline.Pipeline.Stages[].Actions[]." + field
                    )
                    values[row + "value"] = (
                        "`"
                        + (value if isinstance(value, str) else json.dumps(value))
                        + "`"
                    )
                    values[row + "comment"] = (
                        "ProjectName: ビルド"
                        if field == "Configuration"
                        else "アクション"
                    )
                    number += 1
            row = f"desired.row.001-{number:03d}."
            values[row + "property"] = "CodePipeline.Pipeline.Stages[].Name"
            values[row + "value"] = f"`stage-{stage}`"
            values[row + "comment"] = "ステージ"
            number += 1
        save(scope, values)
        path = view.with_name("codepipeline.md")
        expected = generate_markdown(path, values, FRAMEWORK)
        link = "[build-project](codebuild.md#saved-001)"
        saved = expected.replace(link, "`build-project`")
        # Include the renderer's generated array-source markers in the same cause.
        path.write_text(saved, encoding="utf-8")
        yield tmp_path, values, path, saved, expected


def mismatch(pipeline):
    root, values, path, saved, expected = pipeline
    with pytest.raises(DisplayMismatchError) as caught:
        model_reference_tables(path, saved, tuple(values.items()), FRAMEWORK)
    return caught.value


def test_pipeline_display_is_not_identity_or_missing_producer(pipeline):
    root, values, path, saved, expected = pipeline
    error = mismatch(pipeline)
    assert len(error.positions) == 4 and not error.other_changes
    assert any(
        item["property"] == "Stages[2].Actions[1].Configuration.ProjectName"
        for item in error.positions
    )
    findings = Findings(root)
    design.check_resource_names(
        {path: ("codepipeline", ("CodePipeline.Pipeline",))},
        [path],
        design_sources={path: values},
        findings=findings,
        root=root,
        scope={("qa", "team", "codepipeline")},
        definitions_root=FRAMEWORK,
    )
    assert findings.status == "FAIL"
    assert {item.code for item in findings.diagnostics} == {"design.display.mismatch"}
    assert not findings.reference_errors
    assert all("invalid resource identity" not in item for item in findings.errors)
    dependent = finish_result(
        findings.result("design.identity", {("qa", "team", "codepipeline")})
    )
    assert (
        dependent.status == "NOT_RUN"
        and dependent.metadata["unverified"][0]["cause_keys"]
    )
    recovered = model_resource_reference_tables(path, saved, values, FRAMEWORK)
    assert len(recovered) == 1 and isinstance(recovered[0][2], DisplayMismatchError)
    assert {d.cause_key for d in display_diagnostics(root, path, error, "full")} == {
        d.cause_key
        for d in display_diagnostics(root, path, recovered[0][2], "resource")
    }


@pytest.mark.parametrize("field", ["logicalId", "anchor", "malformed", "ownership"])
@pytest.mark.parametrize("check_display", [True, False])
def test_real_identity_errors_stay_invalid(pipeline, field, check_display):
    root, values, path, saved, expected = pipeline
    if field == "logicalId":
        text = expected.replace(
            "resource-logical-id: CodePipeline_Pipeline_001",
            "resource-logical-id: Wrong",
        )
    elif field == "anchor":
        text = expected.replace('id="saved-001"', 'id="wrong"')
    elif field == "ownership":
        text = expected.replace("### CodePipeline.Pipeline:", "### CodeBuild.Project:")
    else:
        text = expected.replace(
            "resource-logical-id: CodePipeline_Pipeline_001", "resource-logical-id:"
        )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SavedIdentityError):
        require_saved_identity(text, expected)
    findings = Findings(root)
    design.check_resource_names(
        {path: ("codepipeline", ("CodePipeline.Pipeline",))},
        [path],
        design_sources={path: values},
        findings=findings,
        root=root,
        scope={("qa", "team", "codepipeline")},
        definitions_root=FRAMEWORK,
        check_display=check_display,
    )
    assert findings.status == "FAIL"
    assert {item.code for item in findings.diagnostics} == {"design.identity.invalid"}


@pytest.mark.parametrize("error_type", [ValueError, OSError])
@pytest.mark.parametrize("stage", ["model_reference_tables", "expanded_display_rows"])
def test_unrelated_identity_expansion_failure_is_processing(
    pipeline, error_type, stage
):
    root, values, path, _, expected = pipeline
    path.write_text(expected, encoding="utf-8")
    target = (
        design._design_document
        if stage == "model_reference_tables"
        else design._dependency_design_layout
    )
    findings = Findings(root)
    scope = {("qa", "team", "codepipeline")}
    with patch.object(target, stage, side_effect=error_type("unrelated failure")):
        findings.evaluate(
            "design.identity",
            scope,
            partial(
                design.check_resource_names,
                {},
                [path],
                design_sources={path: values},
                findings=findings,
                root=root,
                scope=scope,
                definitions_root=FRAMEWORK,
            ),
        )
    assert findings.status == "FAIL" and not findings.diagnostics
    assert len(findings.processing_errors) == 1
    failure = findings.processing_errors[0]
    assert failure["code"] == "mechanical.processing"
    assert failure["exception"] == error_type.__name__
    assert failure["scope"] == ["qa/team/codepipeline"]
    assert not findings.result("design.identity", scope).metadata["complete"]


@pytest.mark.parametrize("document_message", ["same failure", "failure"])
def test_resource_message_cannot_hide_document_not_run(pipeline, document_message):
    root, values, path, _, _ = pipeline
    document_error = ValueError(document_message)
    resource_error = ValueError("same failure")
    findings = Findings(root)
    with (
        patch.object(
            design_tables._design_document,
            "model_reference_tables",
            side_effect=document_error,
        ),
        patch.object(
            design_tables._design_document,
            "model_resource_reference_tables",
            return_value=[("saved-001", None, resource_error)],
        ),
    ):
        design_tables.check_design_tables(
            {},
            set(),
            {},
            {},
            [path],
            design_sources={path: values},
            findings=findings,
            markdown_design_artifacts=ArtifactReferences(),
            markdown_iam_policy_artifacts={},
            root=root,
            schema_catalog=None,
            scope={("qa", "team", "codepipeline")},
            definitions_root=FRAMEWORK,
        )
    blocked = {item["resource"]: item for item in findings.unverified}
    assert set(blocked) == {"document", "CodePipeline_Pipeline_001"}
    assert blocked["document"]["checks"] == ["document reference integrity"]
    assert blocked["document"]["message"] == document_message
    assert blocked["CodePipeline_Pipeline_001"]["message"] == str(resource_error)
    assert all(item["status"] == "NOT_RUN" for item in blocked.values())
    assert all(item["scope"] == ["qa/team/codepipeline"] for item in blocked.values())
    assert findings.status == "FAIL"
    assert (
        finish_result(
            findings.result("design.tables.semantic", {("qa", "team", "codepipeline")})
        ).status
        == "NOT_RUN"
    )


@pytest.mark.parametrize("saved", [r"`left\|old`", r"`left\\\|old`", r"`left\\`"])
def test_escaped_pipe_retains_property_display_evidence(tmp_path, saved):
    path = tmp_path / "docs/designs/qa/team/codepipeline.md"
    wanted = r"`left\|new`"
    expected = (
        "<!-- resource-logical-id: CodePipeline_Pipeline_001 -->\n"
        '<a id="saved-001"></a>\n'
        "### CodePipeline.Pipeline: pipeline\n"
        "| No. | Property | Value | Source / Comment |\n"
        "| ---: | --- | --- | --- |\n"
        f"| 1 | Name | {wanted} | 名前 |\n"
    )
    error = DisplayMismatchError(path, expected.replace(wanted, saved), expected)
    assert not error.other_changes and len(error.positions) == 1
    position = error.positions[0]
    assert position["resourceLogicalId"] == "CodePipeline_Pipeline_001"
    assert position["anchor"] == "saved-001" and position["property"] == "Name"
    assert position["savedDisplay"] == saved and position["expectedDisplay"] == wanted
    changed = expected.replace(wanted, saved) + "独立した変更\n"
    other = DisplayMismatchError(path, changed, expected)
    assert other.other_changes
    assert {item["property"] for item in other.positions} == {"Name", "$document"}


def test_missing_producer_stays_missing(pipeline):
    root, values, path, saved, expected = pipeline
    values = {
        key: value.replace('"CodeBuild_Project_001"', '"CodeBuild_Project_999"')
        for key, value in values.items()
    }
    with input_context(fresh=True), pytest.raises(ReferenceDiagnosticError) as caught:
        model_reference_tables(path, saved, tuple(values.items()), FRAMEWORK)
    assert "MODEL_REF_TARGET_MISSING" in {
        item["code"] for item in caught.value.diagnostics
    }
    assert not isinstance(caught.value, DisplayMismatchError)
    findings = Findings(root)
    design.check_resource_names(
        {},
        [path],
        design_sources={path: values},
        findings=findings,
        root=root,
        scope={("qa", "team", "codepipeline")},
        definitions_root=FRAMEWORK,
    )
    assert findings.status == "FAIL" and not findings.diagnostics
    assert "MODEL_REF_TARGET_MISSING" in {d["code"] for d in findings.reference_errors}
    for handler in (
        lambda: design_tables.design_dependency_not_run(
            path, "document", "references", caught.value, findings=findings
        ),
        lambda: design_links.unavailable_semantics(
            findings, set(), path, caught.value, "reference"
        ),
    ):
        handler()
    assert not findings.diagnostics


def collect_display(root, findings, path, error):
    for stage in ("tables", "links", "identity"):
        for item in display_diagnostics(root, path, error, stage):
            findings.add_diagnostic(item)
    design_tables.design_dependency_not_run(
        path, "CodePipeline_Pipeline_001", "tables", error, findings=findings
    )


def mechanical_display(findings, *args, validator_out, **kwargs):
    validator_out.append(
        SimpleNamespace(
            findings=findings, errors=findings.errors, checks=findings.checks
        )
    )
    return findings.errors, findings.checks, ""


def collected(pipeline):
    root, values, path, saved, expected = pipeline
    findings = Findings(root)
    error = mismatch(pipeline)

    findings.evaluate(
        "design.display",
        {("qa", "team", "codepipeline")},
        partial(collect_display, root, findings, path, error),
    )
    comparison = SimpleNamespace(
        root=root,
        environment="qa",
        directory="team",
        redacted=lambda item: redacted(item, sensitive_values=("build-project",)),
    )
    records, unknown = validation_issues(findings, comparison, ["codepipeline"])
    assert not unknown
    artifact = snapshot_artifact(
        root, ["codepipeline"], ordinary=records, target="team"
    )
    artifact.update(environment="qa", unverified=findings.unverified)
    artifact["human_confirmations"].update(
        environment="qa",
        confirmations=[
            dict(
                id="human",
                service="codepipeline",
                fact="ビルド設定を確認済み",
                scope=dict(
                    resource="CodePipeline_Pipeline_001",
                    property="Stages[2].Actions[1].Configuration.ProjectName",
                ),
                exceptions=[],
                evidence="Human input",
            )
        ],
    )
    comparison.run = lambda: []
    (
        comparison.rows,
        comparison.models,
        comparison.metrics,
        comparison.display_differences,
    ) = {}, {}, {}, {}
    comparison.warnings, comparison.view_errors, comparison.catalog = [], {}, None

    lint = dict(
        jobs=[],
        coverage=[],
        status="checked",
        **{
            key: []
            for key in (
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
        patch.object(scan_runner, "Comparison", return_value=comparison),
        patch.object(
            scan_runner, "mechanical", side_effect=partial(mechanical_display, findings)
        ),
        patch.object(scan_runner, "view_text", return_value=""),
        patch.object(scan_runner, "review_materials", return_value=[]),
        patch.object(scan_runner, "naming_materials", return_value=({"names": []}, [])),
        patch.object(
            scan_runner,
            "human_confirmations",
            return_value=artifact["human_confirmations"],
        ),
        patch.object(scan_runner, "target_services", return_value=["codepipeline"]),
        patch.object(
            scan_runner._imports_issues_cfn_lint, "run_lint", return_value=lint
        ),
    ):
        scanned = scan_runner.scan(root, "qa", "team", ["codepipeline"])
    assert scanned["ordinary"] == records
    assert scanned["validation_status"] == "FAIL"
    assert {item["status"] for item in scanned["check_results"]} >= {"FAIL", "NOT_RUN"}
    return findings, scanned


@pytest.mark.parametrize("artifact_format", ["current", "v16"])
def test_cause_identity_keeps_all_routes_review_snapshot_and_human(
    pipeline, artifact_format
):
    root, _, path, _, _ = pipeline
    findings, artifact = collected(pipeline)
    if artifact_format == "v16":
        for record, diagnostic in zip(
            artifact["ordinary"], findings.diagnostics, strict=True
        ):
            # v16 IDs included the check but predated the extra display identity fields.
            key = stable_id(
                (
                    diagnostic.check_id,
                    diagnostic.code,
                    diagnostic.service,
                    diagnostic.source_path,
                    diagnostic.target_path,
                    diagnostic.location,
                    diagnostic.cause_key,
                )
            )
            record.update(id=key, key=key)
            record["diagnostic"]["diagnosticId"] = key
    validate_artifact(artifact)
    before = deepcopy(artifact)
    report = ordinary_report(root, artifact)
    assert artifact == before
    assert "build-project" not in json.dumps(artifact) and "build-project" not in report
    assert len(artifact["ordinary"]) == 16
    assert "表示差分: 原因4件（表示4件" in report
    assert report.count("対象件数: 1") == 4
    for item in artifact["ordinary"]:
        assert item["diagnostic"]["diagnosticId"] in report
    assert len({item["id"] for item in artifact["ordinary"]}) == 16
    assert (
        len({item["diagnostic"]["diagnosticId"] for item in artifact["ordinary"]}) == 16
    )
    assert len({item["diagnostic"]["cause_key"] for item in artifact["ordinary"]}) == 4
    assert report.count("原診断件数: 4") == 4
    routes = {"tables", "links", "identity", "design.tables.CodePipeline_Pipeline_001"}
    for item in artifact["ordinary"]:
        assert "check_ids" not in item["diagnostic"]
        assert item["diagnostic"]["checkId"] == item["diagnostic"]["check_id"]
        assert item["diagnostic"]["check_id"] in routes
    for line in report.splitlines():
        if "原診断件数:" not in line:
            continue
        members = [
            item
            for item in artifact["ordinary"]
            if item["diagnostic"]["cause_key"] in line
        ]
        assert len(members) == 4
        assert {item["diagnostic"]["check_id"] for item in members} == routes
        assert all(route in line for route in routes)
        assert all(item["diagnostic"]["diagnosticId"] in line for item in members)
        assert all(item["id"] in line for item in members)
    fields = {
        "cause_key",
        "service",
        "resourceLogicalId",
        "anchor",
        "property",
        "savedDisplay",
        "expectedDisplay",
        "sourcePath",
        "checkId",
        "diagnosticId",
    }
    assert all(fields <= item["diagnostic"].keys() for item in artifact["ordinary"])
    page = detail_payload(artifact, "ordinary", limit=50)
    assert page["total"] == len(page["items"]) == 16
    review = review_for(artifact)
    assert len(review["diagnostic_decisions"]) == 16
    assert {item["id"] for item in review["diagnostic_decisions"]} == {
        item["id"] for item in artifact["ordinary"]
    }
    partial = deepcopy(review)
    partial["diagnostic_decisions"].pop()
    with pytest.raises(ValueError, match="all current diagnostics require review"):
        review_snapshot(artifact, partial)
    reviewed = review_snapshot(artifact, review)
    rendered = render_snapshot(root, reviewed)[0]
    assert rendered.count("原診断件数: 4") == 4
    assert all(
        item["diagnostic"]["diagnosticId"] in rendered for item in artifact["ordinary"]
    )
    snapshot = json.loads(reviewed.data)
    assert len(snapshot["ordinary"]) == 16
    assert snapshot["ordinary"] == json.loads(json.dumps(artifact["ordinary"]))
    assert snapshot["human_confirmations"] == artifact["human_confirmations"]
    assert snapshot["unverified"] == artifact["unverified"]
    selected = next(
        item
        for item in artifact["ordinary"]
        if item["property"]
        == artifact["human_confirmations"]["confirmations"][0]["scope"]["property"]
    )
    human = deepcopy(artifact)
    human["human_confirmations"]["confirmations"][0]["exceptions"] = [
        dict(
            rule=selected["rule"],
            diagnostic_id=selected["id"],
            condition="Human exception",
        )
    ]
    decision = next(
        item for item in review["diagnostic_decisions"] if item["id"] == selected["id"]
    )
    decision.update(
        outcome="excluded",
        confirmation_id="human",
        target=dict(resource=selected["resource"], property=selected["property"]),
        evidence="Human confirmed this original diagnostic",
    )
    excluded = json.loads(review_snapshot(human, review).data)
    assert len(excluded["ordinary"]) == 15
    assert (
        sum(
            item["diagnostic"]["cause_key"] == selected["diagnostic"]["cause_key"]
            for item in excluded["ordinary"]
        )
        == 3
    )
    assert before == artifact
    if artifact_format == "v16":
        return
    reordered = Findings(root)
    for diagnostic in reversed(findings.diagnostics):
        reordered.add_diagnostic(replace(diagnostic, message="表示文章を変更"))
    assert {
        item["id"]
        for item in validation_issues(
            reordered,
            SimpleNamespace(
                root=root,
                environment="qa",
                directory="team",
                redacted=lambda value: value,
            ),
            ["codepipeline"],
        )[0]
    } == {item["id"] for item in artifact["ordinary"]}
    assert (
        finish_result(
            findings.result("design.tables.semantic", {("qa", "team", "codepipeline")})
        ).status
        == "NOT_RUN"
    )


def test_report_limit_keeps_all_artifact_members(pipeline):
    root, _, _, _, _ = pipeline
    _, artifact = collected(pipeline)
    template = artifact["ordinary"][0]
    artifact["ordinary"] = []
    for number in range(MAX_GROUPS + 3):
        for route in range(MAX_EXAMPLES + 2):
            record = deepcopy(template)
            record.update(id=f"raw-{number}-{route}", key=f"raw-{number}-{route}")
            record["diagnostic"].update(
                cause_key=f"cause-{number}",
                diagnosticId=f"diagnostic-{number}-{route}.",
                check_id=f"check-{route}",
                checkId=f"check-{route}",
            )
            artifact["ordinary"].append(record)
        artifact["unverified"].append(
            dict(
                code="design.tables.dependency",
                cause_keys=[f"cause-{number}"],
                resource=f"resource-{number}",
                status="NOT_RUN",
                complete=False,
            )
        )
    before = deepcopy(artifact)
    report = ordinary_report(root, artifact)
    assert report.count("対象件数: 1") == MAX_GROUPS
    assert "表示差分: 原因19件（表示16件" in report
    assert report.count(f"原診断件数: {MAX_EXAMPLES + 2}") == MAX_GROUPS
    assert (
        sum(
            item["diagnostic"]["diagnosticId"] in report
            for item in artifact["ordinary"]
        )
        == MAX_GROUPS * MAX_EXAMPLES
    )
    section = report.split("## 未検証範囲\n\n", 1)[1].split("\n## ", 1)[0]
    assert [
        json.loads(unescape(line[2:]))
        for line in section.splitlines()
        if line.startswith("- ")
    ] == artifact["unverified"]
    assert len(artifact["unverified"]) == MAX_GROUPS + 4
    total = (MAX_GROUPS + 3) * (MAX_EXAMPLES + 2)
    pages = [
        detail_payload(artifact, "ordinary", offset=i, limit=50)
        for i in range(0, total, 50)
    ]
    assert all(page["total"] == total for page in pages)
    assert [item for page in pages for item in page["items"]] == artifact["ordinary"]
    assert artifact == before


@pytest.mark.parametrize("reverse", [False, True])
def test_display_routes_merge_across_findings(pipeline, reverse):
    root, _, path, _, _ = pipeline
    error = mismatch(pipeline)
    routes = ["tables", "links", "identity", "generation"]
    parent = Findings(root)
    ids = set()
    for route in reversed(routes) if reverse else routes:
        child = Findings(root)
        for diagnostic in display_diagnostics(root, path, error, route):
            child.add_diagnostic(diagnostic)
            child.add_diagnostic(diagnostic)
            ids.add(diagnostic.identity)
        result = parent.evaluate(
            route,
            {("qa", "team", "codepipeline")},
            partial(parent.include_diagnostics, child),
        )
        assert result.status == "FAIL"
        assert len(result.errors) == 4
        parent.include_diagnostics(child)
    assert len(parent.diagnostics) == len(ids) == 16
    assert len(parent.errors) == 16 and not parent.unstructured_errors
    assert len({d.record()["diagnosticId"] for d in parent.diagnostics}) == 16
    assert len({d.cause_key for d in parent.diagnostics}) == 4
    assert {d.check_id for d in parent.diagnostics} == set(routes)


@pytest.mark.parametrize(
    "field",
    [
        "service",
        "source_path",
        "target_path",
        "location",
        "cause_key",
        "check_id",
        "resourceLogicalId",
        "anchor",
        "property",
        "occurrence",
    ],
)
def test_distinct_display_causes_stay_independent(tmp_path, field):
    original = Diagnostic.create(
        tmp_path,
        code="design.display.mismatch",
        check_id="tables",
        service=("qa", "team", "s3"),
        source_path="docs/designs/qa/team/s3.md",
        target_path="docs/designs/qa/team/s3/policy.json",
        location="saved/Name/1",
        cause_key="confirmed-cause",
        message="same display prose",
        details=dict(
            resourceLogicalId="S3_Bucket_001",
            anchor="saved",
            property="Name",
            occurrence=1,
            savedDisplay="saved",
            expectedDisplay="expected",
        ),
    )
    if field in original.details:
        other = replace(
            original,
            details={
                **original.details,
                field: 2 if field == "occurrence" else "other",
            },
        )
    else:
        other = replace(
            original,
            **{field: ("qa", "team", "sqs") if field == "service" else "other"},
        )
    findings = Findings(tmp_path)
    findings.add_diagnostic(original)
    findings.add_diagnostic(other)
    comparison = SimpleNamespace(
        root=tmp_path, environment="qa", directory="team", redacted=lambda value: value
    )
    records, unknown = validation_issues(findings, comparison, ["s3", "sqs"])
    assert not unknown and len(records) == len({item["id"] for item in records}) == 2
    artifact = snapshot_artifact(
        tmp_path, ["s3", "sqs"], ordinary=records, target="team"
    )
    artifact["environment"] = "qa"
    report = ordinary_report(tmp_path, artifact)
    assert report.count("対象件数: 1") == (1 if field == "check_id" else 2)
    assert all(item["diagnostic"]["diagnosticId"] in report for item in records)


def test_generation_keeps_unrelated_markdown_and_json(pipeline):
    root, _, path, saved, expected = pipeline
    plan = sync_runtime.Generation(
        root, root / "stage", set(), [], [], None, ExitStack()
    )
    plan.expected_outputs[path] = {path: expected}
    sync_runtime._compare_generation(plan)
    assert len(plan.failure_records) == 4
    assert {d.code for d in plan.failure_records} == {"design.display.mismatch"}
    assert not plan.saved
    plan.failure_records.clear()
    path.write_text(saved + "\n独立した不一致。\n", encoding="utf-8")
    artifact = path.with_suffix("") / "policy.json"
    artifact.parent.mkdir()
    artifact.write_text("{}", encoding="utf-8")
    plan.expected_outputs[path][artifact] = '{"required":true}'
    sync_runtime._compare_generation(plan)
    assert sum(d.code == "generation.mismatch" for d in plan.failure_records) == 2
    assert sum(d.code == "design.display.mismatch" for d in plan.failure_records) == 4


def test_links_not_run_remains_fail_with_causes(pipeline):
    root, _, path, _, _ = pipeline
    findings = Findings(root)
    design_links.unavailable_semantics(
        findings, set(), path, mismatch(pipeline), "view-display"
    )
    assert findings.status == "FAIL"
    result = finish_result(
        findings.result("design.links", {("qa", "team", "codepipeline")})
    )
    assert (
        result.status == "NOT_RUN"
        and len(result.metadata["unverified"][0]["cause_keys"]) == 4
    )


@pytest.mark.parametrize("saved", [b"invalid \xff", b"same\r\n", b"same"])
def test_generation_retains_byte_and_encoding_mismatches(tmp_path, saved):
    path = tmp_path / "docs/designs/dev/team/codepipeline.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(saved)
    plan = sync_runtime.Generation(
        tmp_path, tmp_path / "stage", set(), [], [], None, ExitStack()
    )
    plan.expected_outputs[path] = {path: "same\n"}
    sync_runtime._compare_generation(plan)
    assert [d.code for d in plan.failure_records] == ["generation.mismatch"]
    assert not plan.saved


def test_adjacent_independent_comment_differences_are_separate(pipeline):
    root, _, path, _, expected = pipeline
    rows = [line for line in expected.splitlines() if " | アクション |" in line][:2]
    changed = expected
    for index, line in enumerate(rows):
        changed = changed.replace(
            line, line.replace("アクション", f"独立した変更{index}"), 1
        )
    error = DisplayMismatchError(path, changed, expected)
    assert len(error.positions) == 2 and error.other_changes
    assert all(
        item["resourceLogicalId"] == "CodePipeline_Pipeline_001"
        for item in error.positions
    )
    assert (
        len({d.cause_key for d in display_diagnostics(root, path, error, "tables")})
        == 2
    )


@pytest.mark.parametrize("check_display", [True, False])
@pytest.mark.parametrize("difference", ["row", "heading"])
def test_name_display_comparison_can_be_disabled(tmp_path, check_display, difference):
    with mapping_alias(FRAMEWORK, tmp_path):
        scope, values = resource(
            tmp_path,
            "quicksight",
            "QuickSight.DataSource",
            attribute="Name",
        )
        values["desired.resource.001.resourceMode"] = "IMPORT"
        values["desired.row.001-001.value"] = "`QuickSight`"
        save(scope, values)
        path = tmp_path / "docs/designs/qa/team/quicksight.md"
        path.parent.mkdir(parents=True)
        expected = generate_markdown(path, values, FRAMEWORK)
        text = expected.replace(
            "`QuickSight`"
            if difference == "row"
            else "### QuickSight.DataSource: QuickSight",
            "`Quicksight`"
            if difference == "row"
            else "### QuickSight.DataSource: Quicksight",
        )
        assert text != expected
        path.write_text(text, encoding="utf-8")
        findings = Findings(tmp_path)
        with patch.object(
            design._imports_model_render,
            "resource_presentation",
            wraps=design._imports_model_render.resource_presentation,
        ) as presentation:
            design.check_resource_names(
                {path: ("quicksight", ("QuickSight.DataSource",))},
                [path],
                design_sources={path: values},
                findings=findings,
                root=tmp_path,
                scope={("qa", "team", "quicksight")},
                definitions_root=FRAMEWORK,
                check_display=check_display,
            )
        assert findings.status == ("FAIL" if check_display else "PASS"), findings.errors
        if not check_display:
            presentation.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
