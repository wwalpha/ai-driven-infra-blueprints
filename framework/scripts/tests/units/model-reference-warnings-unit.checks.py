"""Reference diagnostics retain literal validation and never require live AWS or Git."""

import copy
import json
import shutil
import sys
from collections import Counter
from contextlib import ExitStack, closing, nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import model.references as references
import model.sources as sources
import pytest
import sync_runtime as runtime
from design.layout import expanded_display_rows
from generation_inputs import GenerationInputs
from import_guard import file_hash
from model.cli import main
from model.core import ReferenceResolutionError
from model.display import display_rows, row_table
from model.format import owner
from model.importing.cli import replacement_inputs
from model.importing.references import Resolver
from model.importing.scope import read_consumers, read_context, restrict
from model.operations import _mask_references, _same
from model.projection import deployment_bucket, reference_display
from model.references import Usage, diagnose, incoming, usages
from model.sources import Scope, _source_snapshot, load_model
from model.validations.full_inputs import check_model_inputs as _check_model_inputs
from support.import_model_fixtures import dependency_fixture
from support.model_sources import write_model
from support.model_v2_fixtures import logs_fixture
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.input_cache import input_context
from utils.source_reads import FileReads
from validation.findings import CheckResult, Findings
from validation.runner import Validator

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_child_results_keep_scope_and_incomplete_state(tmp_path):
    parent = Findings(tmp_path)
    for service, status in (("one", "FAIL"), ("two", "FAIL")):
        child = Findings(tmp_path)
        result = child.result("required", None)
        result.status = status
        result.metadata.update(complete=False, reason="interrupted")
        parent.include_diagnostics(child, scope={("dev", "target", service)})
        if service == "one":
            assert parent.status == "FAIL"
    assert parent.status == "FAIL"
    assert {(r.scope, r.status) for r in parent.results.values()} == {
        (frozenset({("dev", "target", "one")}), "FAIL"),
        (frozenset({("dev", "target", "two")}), "FAIL"),
    }


def warn_and_check(findings, pending):
    findings.warn(pending)
    findings.check(True, "independent model check")


def check_pending_warning_does_not_hide_interrupted_checks(tmp_path):
    findings = Findings(tmp_path)
    pending = ReferenceResolutionError(
        "physical value is pending", category="REFERENCE_PENDING_DEPLOY"
    )

    assert (
        findings.evaluate(
            "model", set(), partial(warn_and_check, findings, pending)
        ).status
        == "PASS"
    )
    assert findings.checks == 1 and findings.warnings and not findings.unverified

    assert (
        findings.evaluate("interrupted", set(), Mock(side_effect=pending)).status
        == "FAIL"
    )
    assert findings.status == "FAIL"


def check_child_results_with_same_identity_are_not_lost(tmp_path):
    parent = Findings(tmp_path)
    for status in ("PASS", "FAIL"):
        child = Findings(tmp_path)
        child.result("required", None).status = status
        child.result("required", None).metadata["complete"] = True
        parent.include_diagnostics(child, scope={("dev", "target", "one")})
    assert [r.status for r in parent.results.values()] == ["PASS", "FAIL"]
    assert parent.status == "FAIL"
    parent.bind_candidate(object(), {"required"})
    assert parent.status == "FAIL"
    assert [
        r.status for r in parent.results.values() if r.candidate is parent.candidate
    ] == ["PASS", "FAIL"]


@pytest.mark.parametrize("retained", [True, False])
def check_pending_view_reports_retained_or_not_generated(tmp_path, retained):
    path = tmp_path / "docs/designs/dev/target/service.md"
    info = {
        "reason": "reference",
        "retainedView": str(path) if retained else None,
        "diagnostics": [{"category": "REFERENCE_PENDING_DEPLOY"}],
    }
    states = runtime.pending_view_states(tmp_path, {path: info})
    assert states == {
        "dev/target/service": (
            "RETAINED_PENDING_DEPLOY" if retained else "NOT_GENERATED_PENDING_DEPLOY"
        )
    }
    info["diagnostics"][0]["category"] = "REFERENCE_UNRESOLVED"
    assert not runtime.pending_view_states(tmp_path, {path: info})


def record_model_check(parent, executed, state, scope):
    executed.append("model")
    if state == "unchecked":
        parent.findings.result("required-model-check", scope).metadata.update(
            complete=False, reason="interrupted"
        )


def generate_pending_view(validator, state, scope):
    result = validator.findings.result("framework.generated-service-model", scope)
    result.status = "FAIL"
    result.metadata = {
        "complete": False,
        "unavailable_services": {"dev/target/service": {"reason": "reference"}},
        "view_states": {"dev/target/service": "RETAINED_PENDING_DEPLOY"}
        if state in {"pending", "unchecked"}
        else {},
    }
    if state == "failure":
        validator.findings.check(False, "generation failed")


@pytest.mark.parametrize("state", ["pending", "unchecked", "unresolved", "failure"])
def check_pending_view_is_separate_from_model_validation(tmp_path, monkeypatch, state):
    scope = {("dev", "target", "service")}
    parent = Validator(tmp_path, scope, model_validation="change")
    parent.task_type = "design"
    parent.change_plan = SimpleNamespace(views=scope)
    executed = []

    monkeypatch.setattr(
        parent,
        "check_changed_inputs",
        partial(record_model_check, parent, executed, state, scope),
    )
    monkeypatch.setattr(
        Validator,
        "check_generated_service_models",
        lambda validator: generate_pending_view(validator, state, scope),
    )
    parent.check_changed_designs()
    assert executed == ["model"]
    assert parent.findings.status == "FAIL"
    result = parent.findings.get_result("framework.generated-service-model", scope)
    assert result.status == "FAIL" and not result.metadata["complete"]
    assert result.metadata["reason"]


@pytest.fixture(autouse=True)
def synthetic_project(tmp_path):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "projectName": "fixture",
                "targets": [
                    {
                        "environment": "dev",
                        "alias": "target",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "terraform",
                    }
                ],
            }
        )
        + "\n"
    )


def _callback_check_reference_leaf_preservation_masked(text, start=7):
    usage = Usage(
        "desired.row.001-001.value",
        None,
        start,
        len(text) - 7,
        text[start:-7],
        "dev/target/service",
        "resource",
        "001",
    )
    return _mask_references(text, [usage])


def check_reference_leaf_preservation():
    masked = _callback_check_reference_leaf_preservation_masked
    reference = masked("prefix-old-suffix")
    assert _same(
        {"target": reference, "timeout": 30},
        {"target": masked("prefix-new-suffix"), "timeout": 30},
    )
    assert not _same(
        {"target": reference, "timeout": 30},
        {"target": masked("prefix-new-suffix"), "timeout": 31},
    )
    assert not _same(reference, masked("changed-new-suffix", 8))
    assert not _same({"target": reference}, {"target": 3})


def _check_typed_findings_unresolved():
    raise ReferenceResolutionError("missing target", key="desired.row.001-001.value")


def check_typed_findings(tmp_path):
    findings = Findings(tmp_path)
    unresolved = _check_typed_findings_unresolved
    result = findings.evaluate("links", set(), unresolved)
    assert result.status == "FAIL" and result.metadata["reason"] not in {
        "reference",
        "unspecified",
        "",
    }
    assert result.warnings and not result.errors
    findings.evaluate(
        "structure", set(), lambda: findings.check(False, "bad structure")
    )
    assert findings.errors == ["bad structure"]


def check_incomplete_references_keep_known_records(tmp_path):
    dependency_fixture(tmp_path)
    file = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    values["desired.reference.origin.producerLogicalId"] = "ServiceA_Resource_999"
    write_model(file, values)
    producer = load_model(tmp_path / "model/stg/cde/service-a.properties")
    warnings = []
    records = incoming(producer, "ServiceA_Resource_999", warnings=warnings)
    assert records and warnings and records[0][1].logical_id == "ServiceA_Resource_999"
    assert (
        records[0][0].path == file
        and records[0][1].consumer_key == "desired.row.002-001.value"
    )
    assert (
        json.loads(json.dumps(warnings))
        and incoming(producer, "ServiceA_Resource_999") == records
    )
    assert (
        load_model(file).warnings
        and load_model(file).authoritative["desired.row.002-001.value"]
        == "same-name-stg"
    )


def check_reference_analysis_keeps_invalid_source_error(tmp_path):
    dependency_fixture(tmp_path)
    file = tmp_path / "model/stg/cde/service-b.properties"
    file.write_text("# model-format: 2\ninvalid\n")
    with pytest.raises(ValueError) as caught:
        incoming(load_model(tmp_path / "model/stg/cde/service-a.properties"), "001")
    assert not isinstance(caught.value, ReferenceResolutionError)


def check_deleted_target_retains_before_value(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    shutil.copytree(before, after)
    dependency_index.rebuild(after)
    file = after / "model/stg/cde/service-a.properties"
    values = dict(load_model(file).authoritative)
    write_model(
        file,
        {
            key: raw
            for key, raw in values.items()
            if owner(key, values) != ("resource", "001")
        },
    )
    warnings = []
    result = incoming(load_model(file), "ServiceA_Resource_001", warnings=warnings)
    assert result and warnings and result[0][1].text == "same-name-stg"
    assert any(
        warning["scope"] == "stg/cde/service-b" and warning["consumerKey"]
        for warning in warnings
    )
    assert (
        load_model(after / "model/stg/cde/service-b.properties").authoritative[
            "desired.row.002-001.value"
        ]
        == load_model(before / "model/stg/cde/service-b.properties").authoritative[
            "desired.row.002-001.value"
        ]
    )


def check_replace_keeps_snapshot_and_reports_impact(tmp_path):
    dependency_fixture(tmp_path)
    with closing(GenerationInputs(tmp_path)) as reads:
        before = load_model(tmp_path / "model/stg/cde/service-a.properties", reads)
        impact = replacement_inputs(before, {"001": {"_action": "replace"}}, reads)
        assert impact["inputs"] and impact["fileSets"]
        assert all(
            file_hash(tmp_path / relative) == checksum
            for relative, checksum in impact["inputs"].items()
        )
        assert any(
            warning["code"] == "reference.replace_impact"
            for warning in impact["warnings"]
        )


def _check_reference_view_retained_but_io_still_fails_fail(*a, **k):
    raise ReferenceResolutionError("missing target")


def _check_reference_view_retained_but_io_still_fails_io_fail(*a, **k):
    raise OSError("write denied")


def check_reference_view_retained_but_io_still_fails(tmp_path, monkeypatch):
    root, stage = tmp_path / "root", tmp_path / "stage"
    path = root / "docs/designs/dev/target/service.md"
    path.parent.mkdir(parents=True)
    path.write_text("saved view")
    artifact = path.with_suffix("") / "policy.json"
    artifact.parent.mkdir()
    artifact.write_text('{"original":true}')
    (root / "project.json").write_bytes((tmp_path / "project.json").read_bytes())
    write_model(root / "model/dev/target/service.properties", {})
    for name in (
        "validate_mappings",
        "validate_required_properties",
        "validate_kms_policy_accounts",
    ):
        monkeypatch.setattr(runtime, name, lambda *a, **k: None)
    fail = _check_reference_view_retained_but_io_still_fails_fail
    monkeypatch.setattr(runtime, "markdown_for", fail)
    warnings, unavailable, failures = [], {}, []
    generated = runtime.generate_views(
        stage,
        root,
        {path: {}},
        failures,
        definitions_root=root,
        warnings=warnings,
        unavailable=unavailable,
    )
    assert generated == {} and not failures and warnings
    assert path in unavailable
    assert (stage / path.relative_to(root)).read_text() == "saved view"
    assert (stage / artifact.relative_to(root)).read_text() == '{"original":true}'
    io_fail = _check_reference_view_retained_but_io_still_fails_io_fail
    monkeypatch.setattr(runtime, "markdown_for", io_fail)
    runtime.generate_views(stage, root, {path: {}}, failures, definitions_root=root)
    assert any("write denied" in failure.message for failure in failures)


def _callback_check_completion_only_waives_reference_not_run_mixed(findings, /):
    findings.check(False, "literal mismatch")
    raise ReferenceResolutionError("missing target")


def check_completion_only_waives_reference_not_run(tmp_path):
    result = CheckResult("check", frozenset(), object())
    assert result.status == "FAIL"
    result.metadata["reason"] = "reference"
    assert result.status == "FAIL"
    findings = Findings(tmp_path)
    mixed = _bind_framework_callback(
        _callback_check_completion_only_waives_reference_not_run_mixed, findings
    )
    result = findings.evaluate("mixed", set(), mixed)
    assert result.status == "FAIL" and result.warnings and result.errors


def check_json_leaf_warning_keeps_sibling_error(tmp_path):
    resolver = Resolver(
        tmp_path, "dev", "target", definitions_root=Path(__file__).resolve().parents[4]
    )
    with pytest.raises(ValueError, match="literal differs"):
        resolver.verify_tree(
            "CodeBuild.Project.VpcConfig",
            {"VpcId": "[vpc](vpc.md#missing)", "timeout": 30},
            {"VpcId": "resource", "timeout": 31},
            {},
            location={"key": "desired.row.001-001.document"},
        )
    assert resolver.warnings[0]["pointer"] == "/VpcId"
    assert resolver.warnings[0]["key"] == "desired.row.001-001.document"


def check_json_cli_warning_success(tmp_path, monkeypatch, capsys):
    dependency_fixture(tmp_path)
    file = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    values["desired.reference.origin.producerLogicalId"] = "ServiceA_Resource_999"
    write_model(file, values)
    assert (
        main(
            [
                "incoming",
                str(file.with_name("service-a.properties")),
                "ServiceA_Resource_999",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert (
        payload["warnings"]
        and payload["status"] == "incomplete"
        and payload["references"]
    )


def check_generation_metadata_reaches_findings(tmp_path, monkeypatch):
    path = tmp_path / "docs/designs/dev/target/service.md"
    plan = runtime.Generation(
        tmp_path,
        tmp_path / "stage",
        {("dev", "target", "service")},
        [],
        [],
        None,
        ExitStack(),
    )
    plan.unavailable[path] = {
        "reason": "reference",
        "status": "FAIL",
        "retainedView": str(path),
    }
    plan.reference_warnings.append(
        ReferenceResolutionError("missing target").diagnostic
    )
    monkeypatch.setattr(runtime, "prepare_generation", lambda *a, **k: plan)
    monkeypatch.setattr(runtime, "validate_generation", lambda *a, **k: None)
    findings = Findings(tmp_path)
    assert runtime.compare_generation(tmp_path, plan.scope, findings=findings) == ()
    metadata = findings.result("framework.generated-service-model", plan.scope).metadata
    assert metadata["complete"] is False
    assert metadata["unavailable_services"]["dev/target/service"][
        "retainedView"
    ] == str(path)
    assert findings.warnings


def _check_bucket_missing_source_and_real_errors_denied(*args, **kwargs):
    raise PermissionError("read denied")


def check_bucket_missing_source_and_real_errors(tmp_path, monkeypatch):
    view = tmp_path / "docs/designs/dev/target/cloudformation-stacks.md"
    with pytest.raises(ReferenceResolutionError) as caught:
        deployment_bucket("[bucket](s3.md#s3-bucket)", view, tmp_path)
    assert caught.value.diagnostic["reference"] == "[bucket](s3.md#s3-bucket)"
    source = tmp_path / "model/dev/target/s3.properties"
    write_model(
        source,
        {
            "desired.service.s3.serviceId": "s3",
            "desired.service.s3.ownedCatalogResourceTypes": "S3.Bucket",
        },
    )
    saved = source.read_bytes()
    source.write_text("# model-format: 2\ninvalid\n")
    with pytest.raises(ValueError) as caught:
        deployment_bucket("[bucket](s3.md#s3-bucket)", view, tmp_path)
    assert not isinstance(caught.value, ReferenceResolutionError)
    source.write_bytes(saved)
    denied = _check_bucket_missing_source_and_real_errors_denied
    monkeypatch.setattr(sources, "_source_snapshot", denied)
    with pytest.raises(PermissionError, match="read denied"):
        deployment_bucket("[bucket](s3.md#s3-bucket)", view, tmp_path)


def check_link_display_and_readback_classification(tmp_path):
    definitions = Path(__file__).resolve().parents[4]
    prop = "CodeBuild.Project.VpcConfig.Subnets"
    with pytest.raises(ReferenceResolutionError):
        display_rows(
            "CodeBuild.Project", [["1", prop, "`subnet-a`", "配置先"]], definitions
        )
    rows = display_rows(
        "CodeBuild.Project",
        [["1", prop, "[subnet-a](vpc.md#subnet-a)", "配置先"]],
        definitions,
    )
    document = ["### CodeBuild.Project: project", "", *row_table(rows)]
    document = [
        line.replace("[subnet-a](vpc.md#subnet-a)", "`subnet-a`") for line in document
    ]
    findings = Findings(tmp_path)
    result = findings.evaluate(
        "display", None, lambda: expanded_display_rows(document, definitions)
    )
    assert result.status == "FAIL"
    assert result.warnings and not result.errors
    with pytest.raises(ValueError) as caught:
        display_rows("CodeBuild.Project", [["1", prop, "[1]", "配置先"]], definitions)
    assert not isinstance(caught.value, ReferenceResolutionError)
    with pytest.raises(ValueError) as caught:
        expanded_display_rows(
            [line.replace("Subnets[1]", "Subnets[2]") for line in document], definitions
        )
    assert not isinstance(caught.value, ReferenceResolutionError)


def codebuild_values(anchor="project", missing_name=False, second=False):
    values = {
        "display.service.title": "# CodeBuild 詳細設計",
        "desired.service.codebuild.serviceId": "codebuild",
        "desired.service.codebuild.ownedCatalogResourceTypes": "CodeBuild.Project",
    }
    for rid in ["001", "002"] if second else ["001"]:
        values.update(
            {
                f"desired.resource.{rid}.resourceType": "CodeBuild.Project",
                f"desired.resource.{rid}.resourceMode": "CREATE",
                "desired.service.identity.lastAllocated": '{"CodeBuild.Project":2}'
                if second
                else '{"CodeBuild.Project":1}',
                f"desired.resource.{rid}.logicalId": "CodeBuild_Project_" + rid,
                f"desired.resource.{rid}.anchor": anchor if rid == "001" else "other",
                f"display.resource.{rid}.comment": "合成 Project",
                f"display.resource.{rid}.label": "project" if rid == "001" else "other",
            }
        )
        rows = [
            ("Artifacts.Type", "`NO_ARTIFACTS`"),
            ("Environment.Type", "`LINUX_CONTAINER`"),
            ("Environment.ComputeType", "`BUILD_GENERAL1_SMALL`"),
            ("Environment.Image", "`image`"),
            ("ServiceRole", "[role](iam.md#iam-role)"),
            ("Source.Type", "`NO_SOURCE`"),
        ]
        if not missing_name or second and rid == "001":
            rows.append(("Name", "`project`" if rid == "001" else "`other`"))
        for n, (prop, value) in enumerate(rows, 1):
            prefix = f"desired.row.{rid}-{n:03d}."
            values.update(
                {
                    prefix + "property": "CodeBuild.Project." + prop,
                    prefix + "value": value,
                    prefix + "comment": "合成設定",
                }
            )
    return values


@pytest.mark.parametrize("anchor", ["project", "broken"])
@pytest.mark.parametrize("second", [False, True])
def check_independent_model_validation(tmp_path, anchor, second):
    values = codebuild_values(anchor, missing_name=True, second=second)
    result = _check_model_inputs(
        tmp_path / "model/dev/target/codebuild.properties",
        values,
        tmp_path,
        definitions_root=Path(__file__).resolve().parents[4],
    )
    assert any(
        "CodeBuild.Project.Name must appear exactly once" in e for e in result.errors
    )
    assert values["desired.resource.001.logicalId"] == "CodeBuild_Project_001"


def _check_generation_warning_keeps_independent_error_unavailable(*a, **k):
    raise ReferenceResolutionError("resource anchor mismatch")


def check_generation_warning_keeps_independent_error(tmp_path, monkeypatch):
    root, stage = tmp_path / "root", tmp_path / "stage"
    path = root / "docs/designs/dev/target/codebuild.md"
    values = codebuild_values("broken", missing_name=True)
    root.mkdir()
    (root / "project.json").write_bytes((tmp_path / "project.json").read_bytes())
    write_model(root / "model/dev/target/codebuild.properties", values)
    for name in (
        "validate_mappings",
        "validate_required_properties",
        "validate_kms_policy_accounts",
    ):
        monkeypatch.setattr(runtime, name, lambda *a, **k: None)
    unavailable = _check_generation_warning_keeps_independent_error_unavailable
    monkeypatch.setattr(runtime, "markdown_for", unavailable)
    failures, warnings, unverified = [], [], {}
    assert (
        runtime.generate_views(
            stage,
            root,
            {path: values},
            failures,
            definitions_root=Path(__file__).resolve().parents[4],
            warnings=warnings,
            unavailable=unverified,
        )
        == {}
    )
    assert not failures
    assert warnings and path in unverified
    assert not (stage / path.relative_to(root)).exists()
    checked = _check_model_inputs(
        root / "model/dev/target/codebuild.properties",
        values,
        root,
        definitions_root=Path(__file__).resolve().parents[4],
    )
    assert any(
        "CodeBuild.Project.Name must appear exactly once" in e for e in checked.errors
    )


def _callback_check_unavailable_service_keeps_source_errors_and_no_cache_generation(
    scope, /, self
):
    result = self.findings.result("framework.generated-service-model", scope)
    result.metadata = {
        "unavailable_services": {
            "dev/target/codebuild": {
                "status": "FAIL",
                "reason": "reference",
                "retainedView": None,
            }
        }
    }


@pytest.mark.parametrize("missing_name", [False, True])
def check_unavailable_service_keeps_source_errors_and_no_cache(
    tmp_path, monkeypatch, missing_name
):
    root = tmp_path
    scope = {("dev", "target", "codebuild")}
    path = root / "model/dev/target/codebuild.properties"
    values = codebuild_values("broken", missing_name=missing_name)
    write_model(path, values)
    validator = Validator(
        root, scope, workers=1, definitions_root=Path(__file__).resolve().parents[4]
    )
    validator.cache = SimpleNamespace(
        common=None, service_key=lambda _: "key", load=lambda _: None, save=Mock()
    )
    monkeypatch.setattr(Validator, "check_design_service_ownership", lambda *a: None)
    monkeypatch.setattr(Validator, "check_stack_designs", lambda *a: None)
    generation = _bind_framework_callback(
        _callback_check_unavailable_service_keeps_source_errors_and_no_cache_generation,
        scope,
    )
    monkeypatch.setattr(Validator, "check_generated_service_models", generation)
    validator.check_scoped_designs()
    assert bool(validator.errors) is missing_name, validator.errors
    assert validator.warnings
    if missing_name:
        assert any("Name must appear exactly once" in e for e in validator.errors)
    result = validator.findings.result("design.service", scope)
    assert result.metadata["reason"] not in {"dependency", "unspecified", ""}
    # A missing saved raw View prevents completion even when generation only waits.
    assert result.status != "PASS"
    validator.cache.save.assert_not_called()


@pytest.mark.parametrize("missing_name", [False, True])
def check_model_warning_only_completion_and_literal_error(tmp_path, missing_name):
    values = codebuild_values("broken", missing_name=missing_name)
    if missing_name:
        # A separate literal error must survive the unresolved anchor too.
        values.update(
            {
                "desired.row.001-999.property": "CodeBuild.Project.TimeoutInMinutes",
                "desired.row.001-999.value": "`invalid-integer`",
                "desired.row.001-999.comment": "不正な設定",
            }
        )
    findings = _check_model_inputs(
        tmp_path / "model/dev/target/codebuild.properties",
        values,
        tmp_path,
        definitions_root=Path(__file__).resolve().parents[4],
    )
    assert bool(findings.errors) is missing_name, findings.errors
    assert findings.warnings
    if missing_name:
        assert any("provider schema violation" in e for e in findings.errors)
    else:
        assert findings.status == "PASS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("TimeoutInMinutes", "`invalid-integer`"),
        ("Tags", "`123`"),
        ("Environment", "`123`"),
    ],
)
def check_full_model_rejects_invalid_native_values(tmp_path, field, value):
    values = codebuild_values()
    values.update(
        {
            "desired.row.001-999.property": "CodeBuild.Project." + field,
            "desired.row.001-999.value": value,
            "desired.row.001-999.comment": "invalid fixture",
        }
    )
    findings = _check_model_inputs(
        tmp_path / "model/dev/target/codebuild.properties",
        values,
        tmp_path,
        definitions_root=Path(__file__).resolve().parents[4],
    )
    assert any(
        "provider schema violation" in error and field in error
        for error in findings.errors
    ), findings.errors


def check_model_document_uses_authoritative_json(tmp_path):
    values = {
        "desired.service.iam.serviceId": "iam",
        "desired.service.iam.ownedCatalogResourceTypes": "IAM.Role",
        "desired.resource.001.resourceType": "IAM.Role",
        "desired.resource.001.resourceMode": "IMPORT",
        "desired.resource.001.logicalId": "IAM_Role_001",
        "desired.resource.001.anchor": "iam-role",
        "desired.service.identity.lastAllocated": '{"IAM.Role":1}',
        "desired.row.001-001.property": "IAM.Role.RoleName",
        "desired.row.001-001.value": "`role`",
        "desired.row.001-001.comment": "ロール名",
        "desired.row.001-002.property": "IAM.Role.AssumeRolePolicyDocument",
        "desired.row.001-002.value": "[policy](iam/policy.json)",
        "desired.row.001-002.document": '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"*","Resource":"*"}]}',
        "desired.row.001-002.comment": "合成設定",
    }
    result = _check_model_inputs(
        tmp_path / "model/dev/target/iam.properties",
        values,
        tmp_path,
        definitions_root=Path(__file__).resolve().parents[4],
    )
    assert not result.errors, result.errors
    assert not result.warnings


@pytest.mark.parametrize("missing_name", [False, True])
def check_analysis_generation_keeps_independent_checks(
    tmp_path, monkeypatch, missing_name
):
    model = tmp_path / "model/dev/target/codebuild.properties"
    write_model(model, codebuild_values("broken", missing_name=missing_name))
    # Actual saved references warn without abandoning independent source validation.
    snapshot = load_model(model)
    assert (
        snapshot.warnings
        and snapshot.authoritative["desired.row.001-005.value"]
        == "[role](iam.md#iam-role)"
    )
    plan = runtime.prepare_generation(
        tmp_path,
        {("dev", "target", "codebuild")},
        write=False,
        definitions_root=Path(__file__).resolve().parents[4],
    )
    try:
        assert not plan.failures, plan.failures
        assert plan.reference_warnings
        view = tmp_path / "docs/designs/dev/target/codebuild.md"
        assert view in plan.generated and view not in plan.unavailable
        assert load_model(model).authoritative == snapshot.authoritative
    finally:
        plan.close()


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))


def _callback_check_shared_snapshot_parses_each_producer_once_and_rechecks_permission_counted(
    parsed, read, /, scope, inputs
):
    parsed[scope.path, read_context(scope.root)] += 1
    return read(scope, inputs)


def check_shared_snapshot_parses_each_producer_once_and_rechecks_permission(
    tmp_path, monkeypatch
):
    dependency_fixture(tmp_path)
    left = tmp_path / "model/dev/cde/service-a.properties"
    right = left.with_name("service-b.properties")
    original = {file: file.read_bytes() for file in (left, right)}
    parsed = Counter()
    read = sources._read_model
    counted = _bind_framework_callback(
        _callback_check_shared_snapshot_parses_each_producer_once_and_rechecks_permission_counted,
        parsed,
        read,
    )
    monkeypatch.setattr(sources, "_read_model", counted)
    inputs = sources.FileReads()
    sources.load_model(left, inputs)
    sources.load_model(right, inputs)
    sources.load_model(left, inputs)
    assert parsed == {(left, None): 1, (right, None): 1}, parsed
    with (
        restrict(("dev", "cde", "service-a")),
        read_consumers({("dev", "cde", "service-a"), ("dev", "cde", "service-b")}),
    ):
        sources.load_model(left, inputs)
        sources.load_model(right, inputs)
    assert len(parsed) == 6 and all(count == 1 for count in parsed.values()), parsed
    with restrict(("dev", "cde", "service-a")):
        with pytest.raises(ValueError, match="outside selected"):
            sources.load_model(right, inputs)
    assert {file: file.read_bytes() for file in original} == original


def check_cross_environment_direct_link_preserves_scope_and_dependency(tmp_path):
    data = json.loads((tmp_path / "project.json").read_text())
    data["targets"].append(
        {**data["targets"][0], "environment": "release", "alias": "other"}
    )
    (tmp_path / "project.json").write_text(json.dumps(data))
    producer = tmp_path / "model/release/other/network.v1.properties"
    write_model(
        producer,
        {
            "desired.resource.007.resourceType": "EC2.VPC",
            "desired.resource.007.logicalId": "EC2_VPC_001",
            "desired.resource.007.anchor": "saved-producer",
            "desired.service.identity.lastAllocated": '{"EC2.VPC":1}',
        },
    )
    consumer = tmp_path / "model/dev/target/service.properties"
    values = {
        "desired.row.001-101.value": "[producer](../../release/other/network.v1.md#saved-producer)",
        "desired.note.002.text": "[ordinary](https://example.invalid/#fixed) old-id",
    }
    write_model(consumer, reference_rows(values))
    dependency_index.rebuild(tmp_path)
    snapshot = load_model(consumer, FileReads())
    records = usages(snapshot)
    assert len(records) == 1 and records[0].producer_scope == "release/other/network.v1"
    assert producer in snapshot.dependencies and not snapshot.warnings
    assert snapshot.authoritative == values

    for restricted in (False, True):
        with (
            restrict(("release", "other", "network.v1"))
            if restricted
            else nullcontext()
        ):
            records = incoming(load_model(producer), "007")
            assert len(records) == 1 and records[0][0].path == consumer
    for invalid in (
        "[unsafe](../../../service.md#saved-producer)",
        "[unsafe](/service.md#saved-producer)",
        "[unsafe](../../unknown/target/service.md#saved-producer)",
    ):
        write_model(consumer, reference_rows({"desired.row.001-101.value": invalid}))
        with pytest.raises(ValueError):
            load_model(consumer, FileReads())


def reference_rows(values):
    """Author Resource-valued rows explicitly; free-text notes remain ordinary prose."""
    for key in tuple(values):
        if key.startswith("desired.row.") and key.endswith(".value"):
            prefix = key.removesuffix("value")
            values.setdefault(prefix + "property", "EC2.VPC.Peer")
            values.setdefault(prefix + "comment", "合成参照")
    if (
        any(key.startswith("desired.row.") for key in values)
        and "desired.resource.001.resourceType" not in values
    ):
        values.update(
            {
                "desired.resource.001.resourceType": "Fixture.Consumer",
                "desired.resource.001.logicalId": "Fixture_Consumer_001",
                "desired.resource.001.anchor": "consumer",
                "desired.service.identity.lastAllocated": '{"Fixture.Consumer":1}',
            }
        )
    return values


def _usage_spec(
    values, identity, key, text, *, pointer=None, occurrence="1", **overrides
):
    reference_rows(values)
    spec = dict(
        consumerKey=key,
        text=text,
        occurrence=occurrence,
        producerKind="resource",
        producerScope="dev/target/service",
        producerLogicalId="EC2_VPC_001",
        resourceType="EC2.VPC",
        format="link",
        labelPolicy="fixed",
    )
    if pointer is not None:
        spec["pointer"] = pointer
    spec.update(overrides)
    values.update(
        {
            f"desired.reference.{identity}.{field}": value
            for field, value in spec.items()
        }
    )


def _callback_check_usage_index_preserves_order_and_all_candidates_counted(
    calls, producer, /, snapshot, address, reads, cache
):
    calls.append(address)
    return producer(snapshot, address, reads, cache)


def check_usage_index_preserves_order_and_all_candidates(tmp_path, monkeypatch):
    file = tmp_path / "model/dev/target/service.properties"
    link, missing = (
        "[producer](service.md#saved-producer)",
        "[producer](service.md#missing)",
    )
    key, nested = "desired.row.001-101.value", "desired.row.001-001.document"
    values = {
        "desired.resource.001.resourceType": "EC2.VPC",
        "desired.resource.001.logicalId": "EC2_VPC_001",
        "desired.resource.001.anchor": "saved-producer",
        "desired.service.identity.lastAllocated": '{"EC2.VPC":1}',
        key: link
        + " "
        + link
        + " "
        + missing
        + " [web](https://example.invalid/#fixed)",
        nested: json.dumps({"a/b": [{"~key": link}]}),
        "desired.row.001-001.property": "EC2.VPC.Tags",
        "desired.row.001-001.value": "`[]`",
        "desired.row.001-001.comment": "synthetic",
    }
    _usage_spec(values, "a-wrong", key, link, producerLogicalId="EC2_VPC_999")
    _usage_spec(values, "b-right", key, link)
    _usage_spec(values, "c-second", key, link, occurrence="2")
    _usage_spec(values, "d-nested", nested, link, pointer="/a~1b/0/~0key")
    snapshot = load_model(write_model(file, reference_rows(values)))
    calls = []
    producer = references._producer
    counted = _bind_framework_callback(
        _callback_check_usage_index_preserves_order_and_all_candidates_counted,
        calls,
        producer,
    )
    monkeypatch.setattr(references, "_producer", counted)
    records = usages(snapshot)
    assert [record.metadata_id for record in records] == [
        "a-wrong",
        "b-right",
        "c-second",
        "d-nested",
        None,
    ]
    assert [record.producer_id for record in records] == [
        None,
        "001",
        "001",
        "001",
        None,
    ]
    assert records[-1].logical_id is None and records[3].pointer == "/a~1b/0/~0key"
    assert calls == ["dev/target/service"]
    assert usages(snapshot, _producer_scope="other/target/service") == ()
    uncoalesced = usages(snapshot, _coalesce=False)
    assert len(uncoalesced) == 8 and uncoalesced[:4] == records[:4]
    warnings, dependencies = diagnose(snapshot)
    assert warnings == snapshot.warnings and dependencies == dict(snapshot.dependencies)
    assert len(warnings) == 2


def _callback_check_usage_index_skips_accumulated_direct_links_counted(
    calls, original, /, *args
):
    calls.append(1)
    return original(*args)


def check_usage_index_skips_accumulated_direct_links(tmp_path, monkeypatch):
    file = tmp_path / "model/dev/target/service.properties"
    values = {
        f"desired.row.001-{index + 100:03d}.value": "[producer](service.md#saved-producer)"
        for index in range(1, 101)
    }
    snapshot = load_model(write_model(file, reference_rows(values)))
    calls = []
    original = references._producer
    counted = _bind_framework_callback(
        _callback_check_usage_index_skips_accumulated_direct_links_counted,
        calls,
        original,
    )
    monkeypatch.setattr(references, "_producer", counted)
    records = references.usages(snapshot)
    assert len(records) == 100 and len(calls) == 1


@pytest.mark.parametrize(
    "case",
    ["wrong-id", "missing-producer", "missing-anchor", "ambiguous", "name", "context"],
)
def check_usage_index_retains_conflicting_direct_links(tmp_path, case):
    file = tmp_path / "model/dev/target/service.properties"
    key, link = "desired.row.001-101.value", "[producer](service.md#saved-producer)"
    values = {
        "desired.resource.001.resourceType": "EC2.VPC",
        "desired.resource.001.logicalId": "EC2_VPC_001",
        "desired.resource.001.anchor": "saved-producer",
        "desired.service.identity.lastAllocated": '{"EC2.VPC":1}',
        key: link,
    }
    overrides = {}
    if case == "wrong-id":
        overrides["producerLogicalId"] = "EC2_VPC_999"
    elif case == "missing-producer":
        overrides["producerScope"] = "dev/target/absent"
    elif case == "missing-anchor":
        values[key] = link = "[producer](service.md#missing)"
    elif case == "ambiguous":
        values.update(
            {
                "desired.resource.002.resourceType": "EC2.VPC",
                "desired.resource.002.logicalId": "EC2_VPC_001",
            }
        )
        with pytest.raises(ValueError, match="duplicate logicalId"):
            load_model(write_model(file, reference_rows(values)))
        return
    elif case == "name":
        overrides.update(format="name", property="EC2.VPC.Name", labelPolicy="none")
    _usage_spec(values, "declared", key, link, **overrides)
    if case == "context":
        prefix = "desired.reference.declared."
        for field in ("producerLogicalId", "resourceType"):
            del values[prefix + field]
        values.update(
            {
                prefix + "producerKind": "context",
                prefix + "producerScope": "dev/target",
                prefix + "format": "literal",
                prefix + "contextProperty": "executionAccountId",
                prefix + "labelPolicy": "none",
            }
        )
    records = usages(load_model(write_model(file, reference_rows(values))))
    assert len(records) == 2 and records[0].metadata_id == "declared"
    assert records[1].metadata_id is None and records[1].text == link


def _callback_check_usage_index_keeps_producer_order_and_io_errors_counted(
    calls, producer, /, snapshot, address, reads, cache
):
    calls.append(address)
    return producer(snapshot, address, reads, cache)


def _callback_check_usage_index_keeps_producer_order_and_io_errors_denied(
    calls, /, snapshot, address, reads, cache
):
    calls.append(address)
    raise OSError("producer read denied")


def check_usage_index_keeps_producer_order_and_io_errors(tmp_path, monkeypatch):
    file = tmp_path / "model/dev/target/service.properties"
    values = {}
    for index, service in enumerate(("second", "first"), 1):
        key, link = (
            f"desired.row.001-{index + 100:03d}.value",
            f"[producer]({service}.md#saved-producer)",
        )
        values[key] = link
        _usage_spec(values, service, key, link, producerScope="dev/target/" + service)
        write_model(
            file.with_name(service + ".properties"),
            {
                "desired.resource.001.resourceType": "EC2.VPC",
                "desired.resource.001.logicalId": "EC2_VPC_001",
                "desired.resource.001.anchor": "saved-producer",
                "desired.service.identity.lastAllocated": '{"EC2.VPC":1}',
            },
        )
    snapshot = load_model(write_model(file, reference_rows(values)))
    calls = []
    producer = references._producer
    counted = _bind_framework_callback(
        _callback_check_usage_index_keeps_producer_order_and_io_errors_counted,
        calls,
        producer,
    )
    monkeypatch.setattr(references, "_producer", counted)
    assert len(references.usages(snapshot)) == 2
    assert calls == ["dev/target/first", "dev/target/second"]
    calls.clear()
    denied = _bind_framework_callback(
        _callback_check_usage_index_keeps_producer_order_and_io_errors_denied, calls
    )
    monkeypatch.setattr(references, "_producer", denied)
    with pytest.raises(OSError, match="producer read denied"):
        references.usages(snapshot)
    assert calls == ["dev/target/first"]


def check_usage_index_is_invocation_local(tmp_path):
    key, link = "desired.row.001-101.value", "[producer](service.md#saved-producer)"
    values = {
        key: link,
        "desired.resource.001.resourceType": "EC2.VPC",
        "desired.resource.001.logicalId": "EC2_VPC_001",
        "desired.resource.001.anchor": "saved-producer",
        "desired.service.identity.lastAllocated": '{"EC2.VPC":1}',
    }
    snapshot = SimpleNamespace(
        authoritative=dict(reference_rows(values)),
        scope=Scope(tmp_path, "dev", "target", "service"),
    )
    with input_context():
        assert usages(snapshot)[0].metadata_id is None
        _usage_spec(values, "new", key, link)
        snapshot.authoritative = dict(reference_rows(values))
        assert len(usages(snapshot)) == 1 and usages(snapshot)[0].metadata_id == "new"
        values["desired.reference.new.producerLogicalId"] = "EC2_VPC_999"
        snapshot.authoritative = dict(reference_rows(values))
        assert len(usages(snapshot)) == 2
        values = {
            k: v for k, v in values.items() if not k.startswith("desired.reference.")
        }
        snapshot.authoritative = dict(reference_rows(values))
        assert len(usages(snapshot)) == 1 and usages(snapshot)[0].metadata_id is None
        snapshot.authoritative = {}
        assert usages(snapshot) == ()
        values = {key: link}
        _usage_spec(values, "invalid", key, link, occurrence="2")
        snapshot.authoritative = values
        with pytest.raises(ValueError, match="occurrence"):
            usages(snapshot)


def reference_values(mode="identifier", count=32):
    values = {
        "desired.resource.001.resourceType": "Logs.LogGroup",
        "desired.resource.001.resourceMode": "IMPORT",
        "desired.resource.001.logicalId": "Logs_LogGroup_001",
        "desired.service.identity.lastAllocated": '{"Logs.LogGroup":1}',
        "desired.row.001-001.property": "Logs.LogGroup.LogGroupName",
        "desired.row.001-001.value": "`fixture-001`",
        "desired.row.001-001.comment": "合成値",
        "observed.row.001-001.value": "`fixture-001`",
    }
    for index in range(count):
        text = "fixture-001" if index % 2 else "stale"
        key = f"desired.note.{index:03d}.text"
        values[key] = text
        spec = {
            "consumerKey": key,
            "text": text,
            "occurrence": "1",
            "producerKind": "resource",
            "producerScope": "dev/target/service",
            "producerLogicalId": "Logs_LogGroup_001",
            "resourceType": "Logs.LogGroup",
            "format": mode,
            "property": "Logs.LogGroup.LogGroupName",
            "labelPolicy": "none",
        }
        values.update(
            {
                f"desired.reference.r{index:03d}.{field}": raw
                for field, raw in spec.items()
            }
        )
    return values


def diagnostic_snapshot(root, values):
    file = root / "model/dev/target/service.properties"
    write_model(file, values)
    return _source_snapshot(Scope(root, "dev", "target", "service"), FileReads())


def _callback_check_diagnose_lazy_parsing_and_exact_results_counted(
    calls, original, /, values, prefix
):
    calls[prefix] += 1
    return original(values, prefix)


@pytest.mark.parametrize("mode", ["name", "identifier"])
def check_diagnose_lazy_parsing_and_exact_results(tmp_path, monkeypatch, mode):
    snapshot = diagnostic_snapshot(tmp_path, reference_values(mode))
    calls = Counter()
    original = references.entries
    counted = _bind_framework_callback(
        _callback_check_diagnose_lazy_parsing_and_exact_results_counted, calls, original
    )
    monkeypatch.setattr(references, "entries", counted)
    warnings, dependencies = references.diagnose(snapshot)
    expected = tuple(
        {
            "code": "reference.mismatch",
            "message": "producer name/identifier differs from saved text",
            "consumerKey": f"desired.note.{index:03d}.text",
            "pointer": None,
            "reference": f"r{index:03d}",
            "text": "stale",
        }
        for index in range(0, 32, 2)
    )
    assert warnings == expected
    assert dependencies == dict(snapshot.dependencies)
    assert calls == {"desired.resource.": 1, "desired.row.": 1, "desired.reference.": 2}
    expected = copy.deepcopy(expected)
    warnings[0]["message"] = "caller mutation"
    dependencies.clear()
    again, dependencies = references.diagnose(snapshot)
    assert again == expected
    assert dependencies == dict(snapshot.dependencies)


def _callback_check_diagnose_producers_are_separate_counted(
    calls, original, /, values, prefix
):
    if prefix in ("desired.resource.", "desired.row."):
        calls[id(values), prefix] += 1
    return original(values, prefix)


def check_diagnose_producers_are_separate(tmp_path, monkeypatch):
    values = reference_values(count=4)
    other = dict(reference_values(count=0))
    other["observed.row.001-001.value"] = "`stale`"
    write_model(tmp_path / "model/dev/target/other.properties", other)
    for index in (0, 1):
        values[f"desired.reference.r{index:03d}.producerScope"] = "dev/target/other"
    snapshot = diagnostic_snapshot(tmp_path, values)
    calls = Counter()
    original = references.entries
    counted = _bind_framework_callback(
        _callback_check_diagnose_producers_are_separate_counted, calls, original
    )
    monkeypatch.setattr(references, "entries", counted)
    warnings, dependencies = references.diagnose(snapshot, FileReads())
    assert [w["reference"] for w in warnings] == ["r001", "r002"]
    assert len(calls) == 4 and set(calls.values()) == {1}
    other_path = tmp_path / "model/dev/target/other.properties"
    assert dependencies == {
        **snapshot.dependencies,
        other_path: other_path.read_bytes(),
    }


def _callback_check_diagnose_does_not_parse_unused_rows_counted(
    original, /, values, prefix
):
    assert prefix != "desired.row."
    return original(values, prefix)


@pytest.mark.parametrize(
    "branch",
    [
        "empty",
        "missing-resource",
        "missing-producer",
        "wrong-property",
        "stack",
        "context",
    ],
)
def check_diagnose_does_not_parse_unused_rows(tmp_path, monkeypatch, branch):
    values = reference_values(count=1)
    if branch == "empty":
        values = {}
    elif branch == "missing-resource":
        values["desired.reference.r000.producerLogicalId"] = "Logs_LogGroup_999"
    elif branch == "missing-producer":
        values["desired.reference.r000.producerScope"] = "dev/target/missing"
    elif branch == "wrong-property":
        values["desired.reference.r000.property"] = "Other.Name"
    elif branch == "stack":
        del values["desired.reference.r000.producerLogicalId"]
        values["desired.reference.r000.producerId"] = "001"
        values["desired.reference.r000.producerKind"] = "stack"
        values["desired.reference.r000.format"] = "name"
        values["desired.reference.r000.property"] = "name"
        del values["desired.reference.r000.resourceType"]
    elif branch == "context":
        for field in ("producerLogicalId", "resourceType", "property"):
            del values["desired.reference.r000." + field]
        values.update(
            {
                "desired.reference.r000.producerKind": "context",
                "desired.reference.r000.producerScope": "dev/target",
                "desired.reference.r000.format": "literal",
                "desired.reference.r000.contextProperty": "executionAccountId",
            }
        )
    snapshot = diagnostic_snapshot(tmp_path, values)
    snapshot = snapshot._replace(
        authoritative={**snapshot.authoritative, "desired.row.invalid": "bad"}
    )
    original = references.entries
    counted = _bind_framework_callback(
        _callback_check_diagnose_does_not_parse_unused_rows_counted, original
    )
    monkeypatch.setattr(references, "entries", counted)
    warnings, dependencies = references.diagnose(snapshot)
    assert len(warnings) == (0 if branch == "empty" else 1)
    if branch == "missing-producer":
        assert dependencies[tmp_path / "model/dev/target/missing.properties"] is None


def _callback_check_diagnose_errors_propagate_denied(
    error, original, /, values, prefix
):
    if prefix == "desired.resource.":
        raise error
    return original(values, prefix)


def check_diagnose_errors_propagate(tmp_path, monkeypatch):
    snapshot = diagnostic_snapshot(tmp_path, reference_values(count=1))
    invalid = {**snapshot.authoritative, "desired.reference.r000.occurrence": "0"}
    with pytest.raises(ValueError, match="text/occurrence"):
        references.diagnose(snapshot._replace(authoritative=invalid))
    for prefix in ("desired.resource.", "desired.row."):
        with pytest.raises(ValueError, match="invalid model entry"):
            references.diagnose(
                snapshot._replace(
                    authoritative={**snapshot.authoritative, prefix + "invalid": "bad"}
                )
            )
    original = references.entries
    error = PermissionError("parse denied")
    denied = _bind_framework_callback(
        _callback_check_diagnose_errors_propagate_denied, error, original
    )
    monkeypatch.setattr(references, "entries", denied)
    with pytest.raises(PermissionError) as caught:
        references.diagnose(snapshot)
    assert caught.value is error


def check_diagnose_fresh_inputs_in_outer_context(tmp_path):
    values = reference_values(count=2)
    with input_context():
        first = diagnostic_snapshot(tmp_path, values)
        assert len(diagnose(first)[0]) == 1
        values["observed.row.001-001.value"] = "`stale`"
        second = diagnostic_snapshot(tmp_path, values)
        assert [w["reference"] for w in diagnose(second)[0]] == ["r001"]
        del values["observed.row.001-001.value"]
        assert len(diagnose(diagnostic_snapshot(tmp_path, values))[0]) == 2
        values["observed.row.001-001.value"] = "`fixture-001`"
        assert [
            w["reference"] for w in diagnose(diagnostic_snapshot(tmp_path, values))[0]
        ] == ["r000"]
        assert (
            diagnose(first)[0]
            == diagnose(diagnostic_snapshot(tmp_path, reference_values(count=2)))[0]
        )
        producer = tmp_path / "model/dev/target/other.properties"
        values = reference_values(count=2)
        for index in range(2):
            values[f"desired.reference.r{index:03d}.producerScope"] = "dev/target/other"
        write_model(producer, reference_values(count=0))
        assert [
            w["reference"] for w in diagnose(diagnostic_snapshot(tmp_path, values))[0]
        ] == ["r000"]
        producer.unlink()
        warnings, dependencies = diagnose(diagnostic_snapshot(tmp_path, values))
        assert [w["message"] for w in warnings] == ["producer Model is absent"] * 2
        assert dependencies[producer] is None
        write_model(producer, reference_values(count=0))
        assert [
            w["reference"] for w in diagnose(diagnostic_snapshot(tmp_path, values))[0]
        ] == ["r000"]


def check_diagnose_display_name_uses_real_projection(tmp_path):
    file = logs_fixture(tmp_path)
    values = dict(load_model(file).authoritative)
    values["desired.note.001.text"] = "[fixture-001](#logs-existing)"
    write_model(file, values)
    snapshot = load_model(file, FileReads())
    view = tmp_path / "docs/designs/qa-synthetic/team-a/cloudwatch-logs.md"
    projected = reference_display(snapshot.values, view, tmp_path)
    assert not snapshot.warnings
    assert projected["desired.note.001.text"] == "[fixture-001](#logs-existing)"
    assert snapshot.authoritative == values
