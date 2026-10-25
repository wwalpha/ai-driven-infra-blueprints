"""Reference failure categories and service isolation use authored offline Models."""

import copy
import json
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import sync_runtime
from issues.artifact import validation_status
from issues.runner import reference_issues, scan
from model.core import (
    FrameworkUnsupportedError,
    ModelNeedsFixError,
    ReferenceResolutionError,
    require_reference_diagnostics,
    resource_index,
)
from model.identity import Resolver
from model.projection import generated_document, reference_resolver
from model.reference_nodes import parse
from model.reference_values import reference_value
from model.sources import load_model
from model.validation import check_model_inputs as model_inputs
from model.validation import validate_json_settings
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from utils.aws_mappings import mapping_alias
from utils.cloudformation.inputs import Blocked
from utils.script_loader import module
from validation.findings import Findings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture
def models(tmp_path):
    with (
        mapping_alias(FRAMEWORK, tmp_path),
        patch("socket.socket", side_effect=AssertionError("network forbidden")),
    ):
        project(tmp_path)
        config = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
        config["projectName"] = "synthetic"
        config["targets"].sort(
            key=lambda target: (target["environment"], target["alias"])
        )
        (tmp_path / "project.json").write_text(
            json.dumps(config) + "\n", encoding="utf-8"
        )
        producer, key = resource(
            tmp_path,
            "kms",
            "KMS.Key",
            number="004",
            attribute="KeyId",
            observed="PENDING_DEPLOY",
        )
        consumer, role = resource(
            tmp_path, "iam", "IAM.Role", number="070", attribute="RoleName"
        )
        role["desired.resource.070.resourceMode"] = "IMPORT"
        role.pop("desired.resource.070.cfn-logicalId")
        role["desired.row.070-001.value"] = "`synthetic-role`"
        document = {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": "kms:Decrypt", "Resource": "*"}
                for _ in range(7)
            ],
        }
        document["Statement"][6]["Resource"] = reference("KMS_Key_004")
        role.update(
            {
                "desired.row.070-002.property": "IAM.Role.Policies[].PolicyName",
                "desired.row.070-002.value": "`synthetic-policy`",
                "desired.row.070-002.comment": "合成",
                "desired.row.070-003.property": "IAM.Role.Policies[].PolicyDocument",
                "desired.row.070-003.value": "[Policy](iam/iam-role-070-synthetic-policy.json)",
                "desired.row.070-003.comment": "合成",
                "desired.row.070-003.document": json.dumps(document),
            }
        )
        role.update(
            {
                "desired.row.070-004.property": "IAM.Role.AssumeRolePolicyDocument",
                "desired.row.070-004.value": "[Trust](iam/iam-role-070-trust-policy.json)",
                "desired.row.070-004.comment": "合成",
                "desired.row.070-004.document": json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Action": "sts:AssumeRole",
                                "Principal": {"Service": "lambda.amazonaws.com"},
                            }
                        ],
                    }
                ),
            }
        )
        save(consumer, role)
        yield producer, key, consumer, role, document


def materialize(consumer, role, document):
    return generated_document(
        document,
        consumer.root,
        resolver=reference_resolver(role, consumer, consumer.root),
        scope=consumer,
        logical_id="IAM_Role_070",
        property_name="IAM.Role.Policies[].PolicyDocument",
        model_key="desired.row.070-003.document",
    )


@pytest.mark.parametrize(
    "fault,code",
    [
        ("syntax", "MODEL_REF_INVALID_SYNTAX"),
        ("missing", "MODEL_REF_TARGET_MISSING"),
        ("ambiguous", "MODEL_REF_TARGET_AMBIGUOUS"),
        ("attribute", "MODEL_REF_INVALID_ATTRIBUTE"),
        ("pending-import", "MODEL_REF_INVALID_PENDING_STATE"),
        ("pending-desired", "MODEL_REF_INVALID_PENDING_STATE"),
    ],
)
def test_invalid_reference_has_origin_code_and_position(models, fault, code):
    producer, key, consumer, role, document = models
    node = document["Statement"][6]["Resource"]
    if fault == "syntax":
        node["$modelRef"].pop("attribute")
    elif fault == "missing":
        node["$modelRef"]["logicalId"] = "KMS_Key_999"
    elif fault == "ambiguous":
        resource(consumer.root, "duplicate", "KMS.Key", number="004")
    elif fault == "attribute":
        node["$modelRef"]["attribute"] = "RoleName"
    else:
        if fault == "pending-import":
            key["desired.resource.004.resourceMode"] = "IMPORT"
            key.pop("desired.resource.004.cfn-logicalId")
        else:
            key["desired.row.004-001.value"] = "`PENDING_DEPLOY`"
        save(producer, key)
    with pytest.raises(ModelNeedsFixError) as caught:
        materialize(consumer, role, document)
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic["category"] == "MODEL_NEEDS_FIX" and diagnostic["code"] == code
    assert (
        diagnostic["status"] == "FAIL"
        and diagnostic["pointer"] == "/Statement/6/Resource"
    )
    assert diagnostic["resourceLogicalId"] == "IAM_Role_070" and diagnostic[
        "model"
    ] == str(consumer.path)
    assert (
        diagnostic["modelKey"] == "desired.row.070-003.document"
        and diagnostic["action"]
    )
    assert not isinstance(caught.value, ReferenceResolutionError)


def test_duplicate_local_logical_id_is_model_error(models):
    _, _, _, role, _ = models
    role.update(
        {
            "desired.resource.071.resourceType": "IAM.Role",
            "desired.resource.071.logicalId": "IAM_Role_070",
        }
    )
    with pytest.raises(ModelNeedsFixError) as caught:
        resource_index(role)
    assert caught.value.diagnostic["code"] == "MODEL_REF_TARGET_AMBIGUOUS"


def test_proven_type_mismatch_and_framework_gap_are_distinct(models):
    _, _, consumer, _, _ = models
    resolver = Resolver(consumer.root)
    with pytest.raises(ModelNeedsFixError) as caught:
        reference_value(
            resolver,
            consumer,
            parse(reference("KMS_Key_004")),
            field="Lambda.Function.Role",
        )
    assert caught.value.diagnostic["code"] == "MODEL_REF_TYPE_MISMATCH"
    with pytest.raises(FrameworkUnsupportedError) as caught:
        resolver.validate_attribute("Future.Resource", "Arn")
    assert caught.value.diagnostic["category"] == "FRAMEWORK_UNSUPPORTED"
    findings = Findings(consumer.root)
    findings.warn(caught.value)
    assert findings.processing_errors and not reference_issues(
        findings, SimpleNamespace(root=consumer.root), ["iam"]
    )


def test_observed_identity_conflict_is_proven(models):
    _, _, consumer, _, _ = models
    producer, bucket = resource(
        consumer.root,
        "s3",
        "S3.Bucket",
        attribute="BucketName",
        observed="confirmed-bucket",
    )
    bucket.update(
        {
            "desired.row.001-001.value": "`desired-bucket`",
            "desired.row.001-002.property": "S3.Bucket.Arn",
            "desired.row.001-002.value": "[self](#saved-001)",
            "desired.row.001-002.comment": "合成",
            "observed.row.001-002.value": "`arn:aws:s3:::other-bucket`",
        }
    )
    save(producer, bucket)
    with pytest.raises(ModelNeedsFixError) as caught:
        reference_value(
            Resolver(consumer.root), consumer, parse(reference("S3_Bucket_001"))
        )
    assert caught.value.diagnostic["code"] == "MODEL_REF_VALUE_CONFLICT"


def test_pending_and_every_invalid_sibling_are_collected(models):
    _, _, consumer, role, document = models
    document["Statement"][0]["Resource"] = {"$modelRef": {}}
    document["Statement"][1]["Resource"] = reference("KMS_Key_999")
    with pytest.raises(ModelNeedsFixError) as caught:
        materialize(consumer, role, document)
    diagnostics = caught.value.diagnostics
    assert {d["category"] for d in diagnostics} == {
        "MODEL_NEEDS_FIX",
        "REFERENCE_PENDING_DEPLOY",
    }
    assert {d["pointer"] for d in diagnostics} == {
        "/Statement/0/Resource",
        "/Statement/1/Resource",
        "/Statement/6/Resource",
    }
    findings = Findings(consumer.root)
    result = findings.evaluate(
        "projection", None, partial(materialize, consumer, role, document)
    )
    assert result.status == "FAIL" and result.errors and result.warnings
    assert len(findings.reference_errors) == 2 and len(findings.unverified) == 1


def test_pending_resolves_without_altering_authority(models):
    producer, key, consumer, role, document = models
    original = copy.deepcopy(document)
    with pytest.raises(ReferenceResolutionError) as caught:
        materialize(consumer, role, document)
    diagnostic = caught.value.diagnostics[0]
    assert (
        diagnostic["category"] == "REFERENCE_PENDING_DEPLOY"
        and diagnostic["status"] == "NOT_RUN"
    )
    assert (
        diagnostic["targetLogicalId"] == "KMS_Key_004"
        and diagnostic["attribute"] == "Arn"
    )
    key["observed.row.004-001.value"] = "`12345678-1234-1234-1234-123456789abc`"
    save(producer, key)
    result = materialize(consumer, role, document)
    assert (
        result["Statement"][6]["Resource"]
        == "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789abc"
    )
    assert document == original and "$modelRef" in role["desired.row.070-003.document"]
    plan = sync_runtime.prepare_generation(
        consumer.root, {("qa", "team", "iam")}, write=False, definitions_root=FRAMEWORK
    )
    try:
        assert (
            len(plan.generated) == 1 and not plan.failures and not plan.unavailable
        ), plan.failures
        sync_runtime.validate_generation(plan, jobs=1, write=False)
        assert not plan.failures, plan.failures
        generated = next(
            path
            for paths in plan.generated.values()
            for path in paths
            if path.name == "iam-role-070-synthetic-policy.json"
        )
        assert json.loads(generated.read_text(encoding="utf-8")) == result
    finally:
        plan.close()


@pytest.mark.parametrize(
    "error",
    [
        ValueError("unknown value error"),
        KeyError("unknown key"),
        RuntimeError("unknown runtime"),
        Blocked("unknown block"),
    ],
)
def test_unknown_exceptions_never_become_reference_waits(models, error):
    _, _, consumer, _, _ = models
    resolver = Resolver(consumer.root)
    with (
        patch.object(resolver, "resolve_logical", side_effect=error),
        pytest.raises(type(error)) as caught,
    ):
        reference_value(resolver, consumer, parse(reference("KMS_Key_004")))
    assert caught.value is error


def test_issues_use_structured_codes_and_stable_identity(models):
    _, _, consumer, role, document = models
    document["Statement"][6]["Resource"] = reference("KMS_Key_999")
    role["desired.row.070-003.document"] = json.dumps(document)
    save(consumer, role)
    # Validate source references through the same Findings path used by the scan.
    findings = Findings(consumer.root)
    result = findings.evaluate(
        "model.json-settings",
        None,
        partial(validate_json_settings, role, consumer.path),
        isolate=True,
    )
    assert result.status == "FAIL" and not findings.processing_errors
    comparison = SimpleNamespace(root=consumer.root, redacted=lambda value: value)
    first = reference_issues(findings, comparison, ["iam"])
    assert len(first) == 1 and first[0]["severity"] == "ERROR"
    assert first[0]["diagnostic"]["code"] == "MODEL_REF_TARGET_MISSING"
    findings.reference_errors[0]["message"] = "reworded explanation"
    assert reference_issues(findings, comparison, ["iam"])[0]["id"] == first[0]["id"]
    assert (
        validation_status(dict(ordinary=first, overview={"records": {"error": 0}}))
        == "FAIL"
    )
    assert load_model(consumer).warnings[0]["category"] == "MODEL_NEEDS_FIX"


@pytest.mark.parametrize("invalid", [False, True])
def test_generation_keeps_failed_service_and_saves_healthy_service(models, invalid):
    _, _, consumer, role, document = models
    if invalid:
        document["Statement"][0]["Resource"] = reference("KMS_Key_999")
        role["desired.row.070-003.document"] = json.dumps(document)
        save(consumer, role)
    good_scope, good_values = resource(
        consumer.root, "s3", "S3.Bucket", attribute="BucketName"
    )
    good_values["desired.row.001-001.value"] = "`synthetic-bucket`"
    save(good_scope, good_values)
    root, stage = consumer.root, consumer.root / "stage"
    bad = root / "docs/designs/qa/team/iam.md"
    good = bad.with_name("s3.md")
    artifact = bad.with_suffix("") / "iam-role-070-synthetic-policy.json"
    artifact.parent.mkdir(parents=True)
    bad.write_text("# Retained\n", encoding="utf-8")
    artifact.write_text('{"retained": true}\n', encoding="utf-8")
    original = {path: path.read_bytes() for path in (bad, artifact)}
    failures, warnings, unavailable = [], [], {}
    # Service presentation is independent of the common reference transaction under test.
    with (
        patch(
            "model.validation.check_model_inputs",
            return_value=SimpleNamespace(errors=(), warnings=(), unverified=()),
        ),
        patch.object(sync_runtime, "markdown_for", return_value="# Generated\n"),
        patch.object(sync_runtime, "rendered_design", return_value="# Generated\n"),
    ):
        generated = sync_runtime.generate_views(
            stage,
            root,
            {bad: load_model(consumer).values, good: load_model(good_scope).values},
            failures,
            warnings=warnings,
            unavailable=unavailable,
        )
    assert set(generated) == {good} and len(failures) == int(invalid)
    assert bad in unavailable and not any("UNKNOWN" in str(d) for d in warnings)
    assert {path: path.read_bytes() for path in original} == original
    assert {(stage / path.relative_to(root)).read_bytes() for path in original} == set(
        original.values()
    )
    # The existing publisher receives only healthy candidates.
    sync_runtime.save_files(
        {
            root / path.relative_to(stage): path.read_text(encoding="utf-8")
            for paths in generated.values()
            for path in paths
        }
    )
    assert good.read_text(encoding="utf-8") == "# Generated\n"
    assert {path: path.read_bytes() for path in original} == original
    plan = SimpleNamespace(
        root=root,
        generated_scope={("qa", "team", "s3")},
        generated=generated,
        failures=failures,
        unavailable=unavailable,
        reference_warnings=warnings,
        warnings={},
        saved={good: True},
        model_paths=[consumer.path, good_scope.path],
        markdown_paths=[bad, good],
        baseline_links={},
    )
    metadata = sync_runtime.generation_metadata(plan)
    assert (
        metadata["status"] == ("FAIL" if invalid else "NOT_RUN")
        and not metadata["complete"]
    )
    with pytest.raises(
        ValueError,
        match="1 services failed; 0 services NOT_RUN"
        if invalid
        else "0 services failed; 1 services NOT_RUN",
    ):
        sync_runtime.report_generation(plan)


def test_real_input_validation_does_not_invent_pending_errors(models):
    _, _, consumer, role, _ = models
    findings = model_inputs(
        consumer.path, role, consumer.root, definitions_root=FRAMEWORK
    )
    assert not findings.errors, findings.errors


def test_reference_wait_findings_are_not_pass(models):
    _, _, consumer, role, document = models
    findings = Findings(consumer.root)
    result = findings.evaluate(
        "projection", None, partial(materialize, consumer, role, document), isolate=True
    )
    assert result.status == "NOT_RUN" and not result.errors and result.warnings
    assert not findings.reference_errors and not findings.processing_errors
    with pytest.raises(ReferenceResolutionError):
        require_reference_diagnostics(list(result.warnings))


@pytest.mark.parametrize("invalid", [False, True])
def test_real_generation_and_issues_v3_keep_reference_categories(models, invalid):
    _, _, consumer, role, document = models
    if invalid:
        document["Statement"][0]["Resource"] = reference("KMS_Key_999")
        role["desired.row.070-003.document"] = json.dumps(document)
        save(consumer, role)
    plan = sync_runtime.prepare_generation(
        consumer.root, {("qa", "team", "iam")}, write=False, definitions_root=FRAMEWORK
    )
    try:
        assert bool(plan.failures) == invalid, plan.failures
        assert len(plan.unavailable) == 1 and not plan.generated
        assert any(
            d.get("category") == "REFERENCE_PENDING_DEPLOY"
            for d in plan.reference_warnings
        )
    finally:
        plan.close()
    lint = dict(
        jobs=[],
        coverage=[],
        status="not_applicable",
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
        patch("issues.runner.naming_materials", return_value=({"names": []}, [])),
        patch("issues.runner.existing_materials", return_value=([], [])),
        patch("issues.inputs.Comparison.run", return_value=[]),
        patch("issues.cfn_lint.run_lint", return_value=lint),
    ):
        artifact = scan(consumer.root, "qa", "team", ["iam"], jobs=1)
    classified = [
        record
        for record in artifact["ordinary"]
        if record.get("diagnostic", {}).get("category") == "MODEL_NEEDS_FIX"
    ]
    assert len(classified) == int(invalid), artifact["ordinary"]
    assert any(
        w.get("category") == "REFERENCE_PENDING_DEPLOY" for w in artifact["warnings"]
    )
    assert not any(
        record.get("code") == "MODEL_REF_TARGET_MISSING"
        for record in artifact["processing_errors"]
    )
    assert not any(
        "MODEL_REF_TARGET_MISSING" in record["message"] and "diagnostic" not in record
        for record in artifact["ordinary"]
    )


def test_pending_cli_is_not_reported_as_generation_failure(models):
    _, _, consumer, role, document = models
    cli = module("sync-model.py", "reference_classification_sync")
    error = ReferenceResolutionError(
        "CREATE producer wait",
        category="REFERENCE_PENDING_DEPLOY",
        code="REFERENCE_PENDING_DEPLOY",
    )
    with (
        patch.object(cli, "sync", side_effect=error),
        patch.object(cli, "active_scope", return_value=None),
    ):
        code, output = cli.run(
            [], repository_root=consumer.root, definitions_root=FRAMEWORK
        )
    assert code == 2 and "Design Markdown sync: NOT_RUN" in output
    assert (
        "Design Markdown sync: FAIL" not in output
        and "REFERENCE_PENDING_DEPLOY" in output
    )


def test_pending_never_masks_invalid_desired_schema_value(models):
    _, _, consumer, _, _ = models
    producer, bucket = resource(
        consumer.root,
        "s3",
        "S3.Bucket",
        attribute="BucketName",
        observed="PENDING_DEPLOY",
    )
    bucket["desired.row.001-001.value"] = "`invalid bucket`"
    save(producer, bucket)
    with pytest.raises(ModelNeedsFixError) as caught:
        reference_value(
            Resolver(consumer.root), consumer, parse(reference("S3_Bucket_001"))
        )
    assert caught.value.diagnostic["code"] == "MODEL_REF_INVALID_VALUE"


def test_unknown_validation_exception_is_fail(models):
    _, _, consumer, _, _ = models
    findings = Findings(consumer.root)
    result = findings.evaluate(
        "unknown",
        None,
        partial(require_reference_diagnostics, [{"category": "future"}]),
        isolate=True,
    )
    assert result.status == "FAIL" and result.errors
    assert findings.processing_errors and not reference_issues(
        findings, SimpleNamespace(root=consumer.root), ["iam"]
    )


def test_invalid_source_identity_is_structured_without_duplicate_failure(models):
    _, _, consumer, role, _ = models
    role.update(
        {
            "desired.resource.071.resourceType": "IAM.Role",
            "desired.resource.071.logicalId": "IAM_Role_070",
        }
    )
    save(consumer, role)
    findings = Findings(consumer.root)
    scope = {("qa", "team", "iam")}
    result = findings.evaluate(
        "generation",
        scope,
        partial(
            sync_runtime.compare_generation,
            consumer.root,
            scope,
            jobs=1,
            definitions_root=FRAMEWORK,
            findings=findings,
        ),
    )
    assert result.status == "FAIL" and len(result.errors) == 1
    diagnostic = findings.reference_errors[0]
    assert diagnostic["code"] == "MODEL_REF_TARGET_AMBIGUOUS" and diagnostic[
        "model"
    ] == str(consumer.path)
    assert diagnostic["modelKey"] == "desired.resource.071.logicalId"
    comparison = SimpleNamespace(root=consumer.root, redacted=lambda value: value)
    assert len(reference_issues(findings, comparison, ["iam"])) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
