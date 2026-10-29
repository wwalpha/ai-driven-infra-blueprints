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
from validation import runner as validator_runner
from validation.design_links import check_design_artifacts as validate_artifacts
from validation.design_links import check_local_links as validate_links
from validation.diagnostics import ArtifactReferences, Diagnostic
from validation.findings import CheckResult, Findings, finish_result
from validation.runner import Validator
from validation_cache import PassCache

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def comparison(root):
    return SimpleNamespace(
        root=root, environment="dev", directory="team", redacted=lambda value: value
    )


def mismatch_plan(root):
    return sync_runtime.Generation(
        root,
        root / "stage",
        set(),
        [],
        [],
        sync_runtime.GenerationInputs(root, read_only=True),
        ExitStack(),
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
                cause_kind="input_invalid",
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


def check_equal_messages_do_not_hide_another_service_failure(tmp_path):
    findings = Findings(tmp_path)
    for service in ("s3", "sqs"):
        diagnostic = Diagnostic.create(
            tmp_path,
            code="generation.render",
            cause_kind="input_invalid",
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


@pytest.mark.parametrize(
    "missing,extra", [(False, False), (True, False), (False, True), (True, True)]
)
def check_artifact_differences(tmp_path, missing, extra):
    view, index = artifacts_fixture(tmp_path, complete=False)
    present = view.with_suffix("") / "present.json"
    present.parent.mkdir()
    present.write_text("{}", encoding="utf-8")
    text = "[JSON](iam/present.json)\n"
    orphan = view.with_suffix("") / "extra.json"
    if missing:
        text += "[Missing](iam/missing.json)\n"
    if extra:
        orphan.write_text("{}", encoding="utf-8")
    findings = Findings(tmp_path)
    validate_links(
        view,
        text,
        anchors={},
        unavailable=set(),
        findings=findings,
        root=tmp_path,
        design_index=None,
        markdown_design_artifacts=index,
    )
    assert index.complete[view.resolve()]
    assert index.sources[present.resolve()] == {view.resolve(): ("dev", "team", "iam")}
    findings.evaluate(
        "design.artifacts",
        {("dev", "team", "iam")},
        partial(
            validate_artifacts,
            scope={("dev", "team", "iam")},
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
            scope={("dev", "team", "iam"), ("dev", "team", "s3")},
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


@pytest.mark.parametrize(
    "scope",
    [None, {("dev", "team", "s3")}, {("dev", "team", "s3"), ("dev", "team", "sqs")}],
)
@pytest.mark.parametrize("other_markdown", [False, True])
def check_scoped_orphans_without_markdown(tmp_path, scope, other_markdown):
    entries = [
        ("dev", "team", "s3"),
        ("dev", "team", "sqs"),
        ("stg", "team", "s3"),
        ("dev", "other", "s3"),
    ]
    for entry in entries:
        artifact = tmp_path / "docs/designs" / Path(*entry) / "orphan.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{}", encoding="utf-8")
    if other_markdown:
        (tmp_path / "docs/designs/dev/team/iam.md").write_text(
            "# IAM\n", encoding="utf-8"
        )
    validator = Validator(tmp_path, scope)
    validator.accounts = {entry[:2]: {} for entry in entries}
    validator.check_design_artifacts()
    selected = entries if scope is None else sorted(scope)
    assert len(validator.findings.diagnostics) == 2 * len(selected)
    assert not validator.findings.processing_errors
    assert all(d.service is None for d in validator.findings.diagnostics)
    assert {d.target_path for d in validator.findings.diagnostics} == {
        f"docs/designs/{'/'.join(entry)}/orphan.json" for entry in selected
    }
    assert {d.code for d in validator.findings.diagnostics} == {
        "design.artifact.owner-missing",
        "design.artifact.unreferenced",
    }
    ordinary, judgments = validation_issues(
        validator.findings, comparison(tmp_path), ["s3", "sqs", "iam"]
    )
    assert not ordinary and len(judgments) == len(validator.findings.diagnostics)


def check_unavailable_services_still_scan_orphans(tmp_path):
    scope = {("dev", "team", service) for service in ("s3", "sqs")}
    errors = {}
    for env, directory, service in scope:
        view = tmp_path / "docs/designs" / env / directory / f"{service}.md"
        artifact = view.with_suffix("") / "orphan.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{}", encoding="utf-8")
        errors[view] = "missing Markdown"
    validator = Validator(tmp_path, scope, workers=1)
    validator.accounts = {("dev", "team"): {}}
    with (
        patch.object(Validator, "check_design_service_ownership"),
        patch.object(Validator, "check_stack_designs"),
        patch.object(Validator, "check_source_inputs"),
        patch.object(Validator, "check_observed_values"),
    ):
        validator.check_scoped_designs(view_errors=errors)
    assert len(validator.findings.diagnostics) == 4
    assert all(d.service is None for d in validator.findings.diagnostics)
    assert not validator.findings.processing_errors
    assert validator.findings.unverified


def read_inside(root, reader, path, *args, **kwargs):
    assert path.resolve().is_relative_to(root.resolve()), path
    return reader(path, *args, **kwargs)


@pytest.mark.parametrize(
    "invalid",
    ["../sqs/foreign.json", "../../../../../../outside.json", "absolute", "symlink"],
)
def check_invalid_json_links_continue_without_external_reads(tmp_path, invalid):
    view, index = artifacts_fixture(tmp_path)
    valid = view.with_suffix("") / "valid.json"
    valid.parent.mkdir()
    valid.write_text("{}", encoding="utf-8")
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    if invalid == "absolute":
        invalid = str(outside)
    elif invalid == "symlink":
        (valid.parent / "escaped.json").symlink_to(outside)
        invalid = "iam/escaped.json"
    text = (
        '# IAM\n\n## リソース詳細\n\n<a id="iam-policy"></a>\n\n### IAM.ManagedPolicy: Policy\n\n'
        "| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n"
        f"| 1 | IAM.ManagedPolicy.PolicyDocument | [JSON]({invalid}) | 不正パス |\n"
        "| 2 | IAM.ManagedPolicy.PolicyDocument | [JSON](iam/valid.json) | 正常パス |\n"
    )
    view.write_text(text, encoding="utf-8")
    validator = Validator(tmp_path, {("dev", "team", "iam")})
    validator.accounts = {("dev", "team"): {}}
    validator.markdown_design_artifacts = index
    with (
        patch.object(design_tables, "design_model_values", return_value={}),
        patch.object(design_tables, "bound_resource_anchors", return_value={}),
        patch.object(
            design_tables._design_document, "model_reference_tables", return_value=[]
        ),
        patch.object(
            design_tables,
            "validation_rows",
            side_effect=lambda rows, *args, **kwargs: rows,
        ),
        patch(
            "validation.design_links.input_text",
            side_effect=partial(read_inside, tmp_path, design_tables.input_text),
        ) as reads,
    ):
        validator.check_design_tables({}, set(), {}, {}, [view])
        validate_links(
            view,
            text,
            anchors={},
            unavailable=set(),
            findings=validator.findings,
            root=tmp_path,
            design_index=None,
        )
        validator.check_design_artifacts()
    placements = [
        d
        for d in validator.findings.diagnostics
        if d.code == "design.artifact.placement" and d.location == invalid
    ]
    assert len(placements) == 1
    diagnostic = placements[0]
    assert diagnostic.source_path == "docs/designs/dev/team/iam.md"
    assert diagnostic.service == ("dev", "team", "iam")
    assert invalid in diagnostic.message
    assert set(index.sources) == {valid}
    assert index.complete[view] is True
    assert reads.call_count == 1
    assert not validator.findings.processing_errors
    assert not any(
        d.code == "design.artifact.missing" for d in validator.findings.diagnostics
    )
    assert validator.findings.relative(outside) == str(outside)


def check_child_validator_keeps_diagnostic_correspondence(tmp_path):
    parent = Validator(
        tmp_path, {("dev", "team", "s3"), ("dev", "team", "sqs")}, workers=1
    )
    parent.schema_catalog = object()
    with (
        patch.object(Validator, "check_design_service_ownership"),
        patch.object(Validator, "check_stack_designs"),
        patch.object(Validator, "check_generated_service_models"),
        patch.object(
            validator_runner,
            "_callback_Validator_check_scoped_designs_validate",
            side_effect=partial(diagnostic_child, tmp_path),
        ),
    ):
        parent.check_scoped_designs()
    assert len(parent.findings.diagnostics) == 2
    assert parent.findings.unstructured_errors == ["independent s3", "independent sqs"]
    assert len(parent.errors) == 4


def diagnostic_child(root, parent, snapshot, scope):
    validator = Validator(root, scope)
    service = next(iter(scope))
    validator.findings.add_diagnostic(
        Diagnostic.create(
            root,
            code="generation.mismatch",
            check_id="generated",
            service=service,
            source_path=f"model/{'/'.join(service)}.properties",
            message="confirmed mismatch",
        ),
        display_error="wrapper: confirmed mismatch",
    )
    validator.check(False, "independent " + service[2])
    return validator


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
        validator.check_design_artifacts,
    )
    assert index.complete[view] is False
    assert not any(
        d.code == "design.artifact.unreferenced" for d in validator.findings.diagnostics
    )
    assert validator.findings.unverified


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({}, "PASS"),
        ({"complete": False}, "FAIL"),
        ({"status": "FAIL"}, "FAIL"),
        ({"status": "FAIL"}, "FAIL"),
        ({"unavailable_services": {"dev/team/iam": {}}}, "FAIL"),
        ({"unverified": [{"code": "not-executed"}]}, "FAIL"),
    ],
)
def check_metadata_completion(tmp_path, metadata, expected):
    findings = Findings(tmp_path)
    result = findings.evaluate("test", set(), Mock(return_value=metadata))
    assert result.status == expected and findings.status == expected
    before = dict(findings.results)
    assert findings.get_result("test", frozenset()) is result
    assert findings.results == before and findings.status == expected
    assert isinstance(result.metadata["unverified"], list)
    assert isinstance(result.metadata["unavailable_services"], dict)
    if expected == "FAIL":
        assert (
            result.metadata["reason"].strip()
            and result.metadata["reason"] != "unspecified"
        )


def check_registered_handlers_execute_once(tmp_path):
    validator = Validator(tmp_path, {("dev", "team", "s3")})
    validator.generated_models_checked = True
    with (
        patch.object(
            validator_runner._imports_sync_views, "saved_design_validation"
        ) as context,
        patch.object(
            validator_runner._imports_sync_runtime, "compare_generation"
        ) as generation,
        patch.object(validator_runner.design, "check_policy_tables") as policy,
        patch.object(validator, "design_files", return_value=[]),
    ):
        context.return_value.__enter__.return_value = None
        for name in ("framework.generated-service-model", "framework.policy-tables"):
            validator.findings.evaluate(
                name, validator.scope, validator.registered_checks()[name]
            )
    assert generation.call_count == 1
    assert policy.call_count == 1


@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("complete", [None, False, True])
def check_completion_requires_evidence(tmp_path, started, complete):
    findings = Findings(tmp_path)
    result = findings.result("required", None)
    result.status, result.started, result.checks = "PASS", started, 10
    if complete is not None:
        result.metadata["complete"] = complete
    assert finish_result(result).status == ("PASS" if complete is True else "FAIL")
    if complete is not True:
        calls = []
        checked = findings.evaluate("required", None, lambda: calls.append(1))
        assert calls == [1] and checked.metadata["complete"]
        assert checked.status == "PASS"


def _parent_handler(tmp_path, findings, scope, child_id, mode, status):
    assert findings.get_result("unrelated", None).status == "FAIL"
    child = CheckResult(
        child_id,
        frozenset(scope),
        findings.candidate,
        status=status,
        metadata={"complete": True, "reason": "invalid child property"},
    )
    if mode in {"imported", "same-key"}:
        source = Findings(tmp_path)
        child.candidate = source.candidate
        source.results[(child_id, frozenset(scope), source.candidate)] = child
        findings.include_diagnostics(source)
    elif mode == "replaced":
        findings.results[(child_id, frozenset(scope), findings.candidate)] = child
    else:
        existing = findings.result(child_id, scope)
        existing.status, existing.metadata = child.status, child.metadata


@pytest.mark.parametrize("mode", ["preregistered", "replaced", "imported", "same-key"])
@pytest.mark.parametrize("status", ["PASS", "FAIL"])
def check_parent_uses_required_child_results(tmp_path, mode, status):
    findings = Findings(tmp_path)
    scope = {("dev", "team", "s3")}
    child_id = "parent" if mode == "same-key" else "child"
    findings.result(child_id, scope)
    unrelated = findings.result("unrelated", None)
    unrelated.metadata.update(complete=True, reason="unrelated invalid input")

    parent = findings.evaluate(
        "parent",
        scope,
        partial(_parent_handler, tmp_path, findings, scope, child_id, mode, status),
    )
    assert parent.status == status
    assert parent.metadata["complete"]
    if status == "FAIL":
        assert "invalid child property" in parent.metadata["reason"]
    assert "unrelated" not in parent.metadata.get("reason", "")


@pytest.mark.parametrize(
    "state", ["PASS", "FAIL", "missing", "incomplete", "stale", "scope"]
)
def check_explicit_aggregation_requires_children(tmp_path, state):
    findings = Findings(tmp_path)
    scope = {("dev", "team", "s3")}
    if state != "missing":
        child = findings.result(
            "child", {("stg", "team", "s3")} if state == "scope" else scope
        )
        child.status = "FAIL" if state == "FAIL" else "PASS"
        child.metadata.update(complete=state != "incomplete", reason="child cause")
        if state == "stale":
            findings.candidate = object()
    parent = findings.aggregate("parent", scope, [("child", scope)])
    assert parent.status == ("PASS" if state == "PASS" else "FAIL")
    assert parent.metadata["complete"] == (state in {"PASS", "FAIL"})
    if state != "PASS":
        assert "child" in parent.metadata["reason"]


@pytest.mark.parametrize(
    "state", ["PASS", "FAIL", "incomplete", "interrupted", "missing"]
)
def check_aggregate_replaces_only_its_reservation(tmp_path, state):
    findings = Findings(tmp_path)
    scope = {("dev", "team", "s3")}
    reservation = findings.result("parent", scope)
    assert findings.status == "FAIL"
    if state != "missing":
        source = Findings(tmp_path)
        if state == "interrupted":
            source.evaluate("parent", scope, Mock(side_effect=KeyboardInterrupt()))
        else:
            # Imported results need not have started in this Findings instance.
            child = CheckResult(
                "parent",
                frozenset(scope),
                source.candidate,
                status="FAIL" if state == "FAIL" else "PASS",
                metadata={
                    "complete": state != "incomplete",
                    "reason": "actual child cause",
                },
            )
            source.results[("parent", frozenset(scope), source.candidate)] = child
        findings.include_diagnostics(source)
    parent = findings.aggregate("parent", scope, [("parent", scope)])
    assert parent.status == ("PASS" if state == "PASS" else "FAIL")
    assert findings.get_result("parent", scope) is parent
    assert all(result is not reservation for result in findings.results.values())
    assert findings.status == parent.status
    if state != "PASS":
        assert parent.metadata["reason"]
        if state in {"FAIL", "incomplete"}:
            assert "actual child cause" in parent.metadata["reason"]
    if state not in {"PASS", "missing"}:
        assert any(
            result is not parent and result.status == "FAIL"
            for result in findings.results.values()
        )


def _status_handler(findings, later, outcome):
    active = findings.get_result("parent", None)
    before = (active.status, dict(active.metadata))
    assert findings.status in {"PASS", "FAIL"}
    assert (active.status, active.metadata) == before
    assert later.metadata == {}
    findings.evaluate("nested", None, lambda: findings.status and None)
    if outcome == "exception":
        raise RuntimeError("actual handler error")
    if outcome == "interrupt":
        raise KeyboardInterrupt("actual interruption")
    if outcome == "child":
        findings.evaluate(
            "bad-child",
            None,
            lambda: {"status": "FAIL", "reason": "bad child type"},
        )
    if outcome == "reentry":
        findings.evaluate("parent", None, lambda: None)
    if outcome == "unstarted":
        findings.result("unstarted-child", None)


@pytest.mark.parametrize(
    "outcome", ["PASS", "exception", "interrupt", "child", "reentry", "unstarted"]
)
def check_status_read_during_handler_preserves_completion(tmp_path, outcome):
    findings = Findings(tmp_path)
    later = findings.result("later-required", None)

    result = findings.evaluate(
        "parent", None, partial(_status_handler, findings, later, outcome)
    )
    assert result.status == ("PASS" if outcome == "PASS" else "FAIL")
    assert findings.evaluate("later-required", None, lambda: None).status == "PASS"
    assert findings.status == result.status
    if outcome == "PASS":
        assert result.started and result.metadata["complete"]
    else:
        assert result.metadata["reason"]


@pytest.mark.parametrize("complete", [False, True])
def check_aggregate_keeps_same_key_failure(tmp_path, complete):
    findings = Findings(tmp_path)
    child = CheckResult(
        "parent",
        None,
        findings.candidate,
        metadata={"complete": complete, "reason": "actual same-key failure"},
    )
    findings.results[(child.check_id, child.scope, child.candidate)] = child
    parent = findings.aggregate("parent", None, [("parent", None)])
    assert parent.status == findings.status == "FAIL"
    assert "actual same-key failure" in parent.metadata["reason"]
    assert any(result is child for result in findings.results.values())


@pytest.mark.parametrize("same_key", [False, True])
@pytest.mark.parametrize(
    "reason",
    [None, "actual incomplete check", "parent: required check has not started"],
)
def check_aggregate_reservation_and_actual_incomplete(tmp_path, same_key, reason):
    findings = Findings(tmp_path)
    parent = findings.result("parent", None)
    if reason:
        parent.metadata.update(complete=False, reason=reason)
    child_id = "parent" if same_key else "child"
    child = CheckResult(
        child_id, None, findings.candidate, status="PASS", metadata={"complete": True}
    )
    findings.results[(child_id, None, (findings.candidate, object()))] = child
    aggregate = findings.aggregate("parent", None, [(child_id, None)])
    assert aggregate.status == ("FAIL" if reason else "PASS")
    assert findings.status == aggregate.status
    if reason:
        assert reason in aggregate.metadata["reason"]


def read_during_handler(findings, later, reader, outcome, existing_failure):
    active = findings.get_result("normal-required", None)
    before = (active.status, dict(active.metadata), active.started, active.errors)
    records = findings.failures() if reader == "failures" else findings.status
    assert (active.status, active.metadata, active.started, active.errors) == before
    assert later.metadata == {}
    if existing_failure and reader == "failures":
        assert any("existing failure" in record["reason"] for record in records)
    if outcome == "exception":
        raise RuntimeError("actual exception")
    if outcome == "interrupt":
        raise KeyboardInterrupt("actual interruption")


@pytest.mark.parametrize("reader", ["status", "failures"])
@pytest.mark.parametrize("outcome", ["PASS", "exception", "interrupt"])
@pytest.mark.parametrize("existing_failure", [False, True])
def check_read_during_handler_has_no_result_side_effect(
    tmp_path, reader, outcome, existing_failure
):
    findings = Findings(tmp_path)
    if existing_failure:
        findings.evaluate(
            "earlier", None, lambda: {"status": "FAIL", "reason": "existing failure"}
        )
    later = findings.result("later", None)

    result = findings.evaluate(
        "normal-required",
        None,
        partial(
            read_during_handler, findings, later, reader, outcome, existing_failure
        ),
    )
    assert result.status == ("PASS" if outcome == "PASS" else "FAIL")
    if outcome == "PASS":
        assert result.metadata["complete"] is True
    else:
        assert "actual" in result.metadata["reason"]
    assert findings.evaluate("later", None, lambda: None).status == "PASS"
    assert findings.status == (
        "FAIL" if existing_failure or outcome != "PASS" else "PASS"
    )


def check_candidate_binding_retains_failures_not_stale_success(tmp_path):
    findings = Findings(tmp_path)
    common = findings.evaluate("validation.catalog", None, lambda: None)
    findings.evaluate("framework.generated-service-model", None, lambda: None)
    failed = findings.evaluate(
        "framework.policy-tables",
        None,
        lambda: {"status": "FAIL", "reason": "invalid policy"},
    )
    findings.bind_candidate(object(), {"validation.catalog"})
    retained = findings.get_result("validation.catalog", None)
    assert retained.started and retained.metadata is common.metadata
    assert retained.metadata["complete"] and retained.status == "PASS"
    assert findings.get_result("framework.generated-service-model", None) is None
    failure = findings.get_result("framework.policy-tables", None)
    assert failure.status == "FAIL" and failure.metadata is failed.metadata
    assert failure.metadata["reason"] == "invalid policy"
    assert findings.status == "FAIL"


def check_reentry_and_empty_interrupt_remain_failures(tmp_path):
    findings = Findings(tmp_path)
    nested = findings.evaluate(
        "recursive",
        None,
        lambda: findings.evaluate("recursive", None, lambda: None),
    )
    assert nested.status == "FAIL" and not nested.metadata["complete"]
    assert "reentr" in nested.metadata["reason"]
    interrupted = findings.evaluate(
        "interrupted", None, Mock(side_effect=KeyboardInterrupt())
    )
    assert interrupted.status == "FAIL" and not interrupted.metadata["complete"]
    assert "KeyboardInterrupt" in interrupted.metadata["reason"]
    assert "interrupted" in interrupted.metadata["reason"]
    assert all(item["reason"].strip() for item in findings.failures())


def _interrupted_handler(findings):
    findings.evaluate(
        "child",
        None,
        lambda: {"complete": True, "status": "FAIL", "reason": "bad child type"},
    )
    raise KeyboardInterrupt()


def check_parent_interrupt_keeps_child_cause_and_incomplete_state(tmp_path):
    findings = Findings(tmp_path)

    result = findings.evaluate("parent", None, partial(_interrupted_handler, findings))
    assert result.status == "FAIL" and not result.metadata["complete"]
    assert (
        "child" in result.metadata["reason"]
        and "bad child type" in result.metadata["reason"]
    )
    assert "KeyboardInterrupt" in result.metadata["reason"]
    empty = findings.evaluate("empty-error", None, lambda: findings.check(False, ""))
    assert empty.status == "FAIL" and empty.metadata["reason"].strip()


def check_policy_not_planned_without_display(tmp_path):
    validator = Validator(
        tmp_path, {("dev", "team", "s3")}, check_display=False, workers=1
    )
    validator.schema_catalog = object()
    with (
        patch.object(Validator, "check_design_service_ownership"),
        patch.object(Validator, "check_stack_designs"),
        patch.object(Validator, "check_designs"),
        patch.object(Validator, "check_observed_values"),
    ):
        validator.check_scoped_designs()
    assert (
        validator.findings.get_result("framework.policy-tables", validator.scope)
        is None
    )
    assert validator.findings.status == "PASS"


def _scoped_generate(validator):
    return {
        "complete": True,
        "generated": sorted("/".join(entry) for entry in validator.scope),
    }


def _scoped_designs(state, validator):
    validator.check(True, "service executed")
    if state == "missing":
        return
    if state == "interrupted":
        validator.findings.evaluate(
            "framework.policy-tables",
            validator.scope,
            Mock(side_effect=KeyboardInterrupt()),
        )
    else:
        validator.findings.evaluate(
            "framework.policy-tables",
            validator.scope,
            lambda: {
                "complete": state != "incomplete",
                "status": "FAIL" if state == "FAIL" else "PASS",
                "reason": "invalid policy",
            },
        )


@pytest.mark.parametrize("preregistered", [False, True])
@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize(
    "state", ["PASS", "FAIL", "missing", "incomplete", "interrupted"]
)
def check_scoped_aggregation_and_cache_evidence(tmp_path, count, state, preregistered):
    scope = {("dev", "team", service) for service in ("s3", "sqs")[:count]}
    cache = PassCache(tmp_path, False)
    cache.common = "same-inputs"

    with (
        patch.object(cache, "service_key", side_effect=lambda entry: "/".join(entry)),
        patch.object(Validator, "check_design_service_ownership"),
        patch.object(Validator, "check_stack_designs"),
        patch.object(Validator, "_check_generated_service_models", _scoped_generate),
        patch.object(
            Validator,
            "check_designs",
            autospec=True,
            side_effect=partial(_scoped_designs, state),
        ),
        patch.object(Validator, "check_observed_values"),
    ):
        validator = Validator(tmp_path, scope, workers=1)
        validator.schema_catalog, validator.cache = object(), cache
        if preregistered:
            validator.findings.result("framework.policy-tables", scope)
        validator.check_scoped_designs()
        policy = validator.findings.get_result("framework.policy-tables", scope)
        assert policy.status == ("PASS" if state == "PASS" else "FAIL")
        assert len(validator.service_cache_pending) == (count if state == "PASS" else 0)
        if state == "PASS":
            assert policy.metadata["complete"] and validator.findings.status == "PASS"
            validator.finalize_service_cache("same-inputs")
            reused = Validator(tmp_path, scope, workers=1)
            reused.schema_catalog, reused.cache = object(), cache
            if preregistered:
                reused.findings.result("framework.policy-tables", scope)
            with (
                patch.object(
                    Validator,
                    "check_designs",
                    side_effect=AssertionError("cached service reran"),
                ),
                patch.object(
                    Validator,
                    "_check_generated_service_models",
                    side_effect=AssertionError("cached generation reran"),
                ),
            ):
                reused.check_scoped_designs()
            assert reused.findings.status == "PASS"
            assert reused.findings.get_result(
                "framework.policy-tables", scope
            ).metadata["complete"]
        else:
            assert policy.metadata["reason"]
            assert validator.findings.status == "FAIL"


def check_result_lookup_is_candidate_and_scope_specific(tmp_path):
    findings = Findings(tmp_path)
    scope = {("dev", "team", "s3")}
    assert findings.get_result("design.stacks", scope) is None
    assert not findings.results and findings.status == "PASS"
    result = findings.result("design.stacks", scope)
    assert result.status == "FAIL"
    assert findings.get_result("design.stacks", list(scope)) is result
    before = dict(findings.results)
    for other in (None, set(), {("stg", "team", "s3")}):
        assert findings.get_result("design.stacks", other) is None
    assert findings.results == before and findings.status == "FAIL"
    findings.bind_candidate(object(), set())
    assert findings.get_result("design.stacks", scope).status == "FAIL"
    assert findings.status == "FAIL"
    assert findings.result("design.stacks", scope) is not result
    assert findings.status == "FAIL"


@pytest.mark.parametrize("stack_status", [None, "PASS", "unstarted", "FAIL"])
@pytest.mark.parametrize("environment", ["dev", "stg"])
def check_iac_stack_lookup_and_file_fallback(tmp_path, stack_status, environment):
    design = tmp_path / "docs/designs/dev/team/cloudformation-stacks.md"
    template = tmp_path / "infra/cloudformation/templates/role.yaml"
    parameters = tmp_path / "infra/cloudformation/parameters/dev/team/role.json"
    for path, text in (
        (
            design,
            "# CloudFormation\n\n## Stack一覧\n"
            "| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |\n"
            "| ---: | ---: | --- | --- | --- | --- |\n"
            "| 1 | 10 | app-role | role.yaml | role.json | ロール |\n",
        ),
        (
            template,
            "Parameters:\n  Environment:\n    Type: String\nResources:\n"
            "  Role:\n    Type: AWS::IAM::Role\n    Properties:\n"
            "      RoleName: !Ref Environment\n",
        ),
        (
            parameters,
            '[{"ParameterKey":"Environment","ParameterValue":"' + environment + '"}]',
        ),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    validator = Validator(
        tmp_path, iac_paths={template, parameters}, model_validation="change"
    )
    findings = validator.findings
    plan = SimpleNamespace(
        destinations={
            design: {
                "desired.stack.001.template": "role.yaml",
                "desired.stack.001.parameters": "role.json",
            }
        },
        generated={design: []} if stack_status is not None else {},
    )
    if stack_status is not None:
        result = findings.result("design.stacks", None)
        if stack_status != "unstarted":
            result.status = stack_status
            result.metadata["complete"] = True
    before = dict(findings.results)
    definitions = validator.candidate_stacks(plan)
    assert findings.results == before
    with patch.object(
        validator_runner.cloudformation,
        "stack_design",
        wraps=validator_runner.cloudformation.stack_design,
    ) as read_design:
        checked = findings.evaluate(
            "iac.environment",
            None,
            partial(
                validator.check_cloudformation_environment_parameters,
                stack_definitions=definitions,
            ),
        )
    assert checked.status == ("PASS" if environment == "dev" else "FAIL")
    assert findings.status == (
        "FAIL"
        if environment != "dev"
        else "FAIL"
        if stack_status == "unstarted"
        else stack_status or "PASS"
    )
    assert read_design.call_count == int(stack_status is None)
    assert findings.get_result("design.stacks", None) is before.get(
        ("design.stacks", None, findings.candidate)
    )


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
    assert result.status != "PASS"


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
    assert parent.errors == findings.errors
    assert parent.diagnostic_errors == findings.diagnostic_errors
    assert not parent.unstructured_errors


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
        scope={("dev", "team", "iam")},
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


def mechanical_fixture(validator, *args, validator_out, **kwargs):
    validator_out.append(validator)
    return validator.errors, validator.checks, ""


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize(
    "code", ["generation.mismatch", "codebuild.plaintext-reference"]
)
@pytest.mark.parametrize("independent", ["independent failure", "confirmed mismatch"])
def check_scan_artifact_keeps_diagnostics_and_incomplete_metadata(
    tmp_path, wrapped, code, independent
):
    findings = Findings(tmp_path)
    diagnostic = Diagnostic.create(
        tmp_path,
        code=code,
        cause_kind="input_invalid",
        check_id="framework.generated-service-model",
        service=("dev", "team", "s3"),
        source_path="model/dev/team/s3.properties",
        target_path="docs/designs/dev/team/s3.md",
        message="confirmed mismatch",
    )
    child = Findings(tmp_path)
    child.add_diagnostic(
        diagnostic,
        display_error=("wrapper: " if wrapped else "") + diagnostic.message,
    )
    child.check(False, independent)
    findings.include_diagnostics(child)
    reference = dict(
        category="MODEL_NEEDS_FIX",
        code="REFERENCE_TEST",
        model="model/dev/team/s3.properties",
        message="reference failure",
        fixModels=["model/dev/team/s3.properties"],
    )
    findings.warn(reference)
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
            scan_runner,
            "human_confirmations",
            return_value=dict(
                version=2, environment="dev", target="team", confirmations=[]
            ),
        ),
        patch.object(scan_runner, "target_services", return_value=["s3"]),
        patch.object(
            scan_runner._imports_issues_cfn_lint, "run_lint", return_value=lint
        ),
    ):
        first = scan_runner.scan(tmp_path, "dev", "team", ["s3"])
    assert len(first["ordinary"]) == 2
    assert [item["message"] for item in first["judgments"]] == [independent]
    assert first["version"] == 6
    assert (
        first["ordinary"][1]["diagnostic"]["source_path"]
        == "model/dev/team/s3.properties"
    )
    assert (
        first["ordinary"][1]["id"]
        == validation_issues(findings, source, ["s3"])[0][0]["id"]
    )
    result = first["check_results"][0]
    assert result["status"] == "FAIL" and result["complete"] is False
    assert result["unavailable_services"] and result["unverified"]
    assert first["unverified"]


def check_diagnostic_merge_positions_and_equal_messages(tmp_path):
    parent, child = Findings(tmp_path), Findings(tmp_path)
    parent.check(False, "unstructured parent")
    child.check(False, "unstructured child")
    for resource in ("one", "two"):
        child.add_diagnostic(
            Diagnostic.create(
                tmp_path,
                code="resource.invalid",
                check_id="identity",
                service=("dev", "team", "s3"),
                location=resource,
                message="same error",
            )
        )
    child.warn(
        dict(
            category="MODEL_NEEDS_FIX",
            code="MODEL_REF_INVALID_SYNTAX",
            model=str(tmp_path / "model/dev/team/s3.properties"),
            modelKey="desired.row.001-001.value",
            message="bad reference",
        )
    )
    for _ in range(2):
        result = parent.evaluate(
            f"merge-{_}",
            None,
            partial(parent.include_diagnostics, child),
        )
        assert result.status == "FAIL" and parent.status == "FAIL"
    assert len(parent.diagnostics) == 2
    assert parent.errors.count("same error") == 2
    assert parent.diagnostic_errors == {
        2: child.diagnostics[0].identity,
        3: child.diagnostics[1].identity,
        4: child.diagnostic_errors[3],
    }
    assert parent.reference_error_positions == {4: child.reference_errors[0]}
    assert parent.unstructured_errors == [
        "unstructured parent",
        "unstructured child",
        "unstructured child",
    ]
    result = parent.evaluate(
        "duplicate-add",
        None,
        partial(parent.add_diagnostic, child.diagnostics[0]),
    )
    assert result.status == "FAIL" and parent.errors.count("same error") == 2


if __name__ == "__main__":
    raise SystemExit(run(__file__))


def check_fail_reasons_and_returned_results(tmp_path):
    scope = {("dev", "team", "one")}
    findings = Findings(tmp_path)
    missing = findings.result("mandatory", scope)
    assert findings.status == "FAIL" and "not started" in missing.metadata["reason"]
    executed = []
    assert (
        findings.evaluate("mandatory", scope, lambda: executed.append(True)).status
        == "PASS"
    )
    assert executed == [True]
    for exception in (
        RuntimeError("validator crashed"),
        KeyboardInterrupt("validation interrupted"),
    ):
        result = findings.evaluate(
            type(exception).__name__, scope, Mock(side_effect=exception)
        )
        assert result.status == "FAIL" and str(exception) in result.metadata["reason"]
    returned = CheckResult(
        "returned",
        frozenset(scope),
        object(),
        status="FAIL",
        errors=("invalid property type",),
        metadata={"complete": True},
    )
    result = findings.evaluate("return-result", scope, lambda: returned)
    assert (
        result.status == "FAIL" and "invalid property type" in result.metadata["reason"]
    )
    invalid = findings.evaluate("metadata", scope, lambda: {"reason": []})
    assert (
        invalid.status == "FAIL"
        and "reason must be a string" in invalid.metadata["reason"]
    )
    child = Findings(tmp_path)
    child.result("child.mandatory", scope)
    nested = findings.evaluate(
        "parent.required", scope, lambda: findings.include_diagnostics(child)
    )
    assert nested.status == "FAIL" and "child.mandatory" in nested.metadata["reason"]
    records = findings.failures()
    assert records and all(
        record["check_id"]
        and record["scope"] == [list(next(iter(scope)))]
        and record["reason"].strip()
        and record["status"] == "FAIL"
        for record in records
    )
