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

import model.projection as projection
import pytest
import sync_runtime
from design.policy_tables import rendered_design
from issues.artifact import validation_status
from issues.reports import issue_content, ordinary_report
from issues.runner import reference_issues, scan
from model.core import (
    FrameworkUnsupportedError,
    ModelNeedsFixError,
    ReferenceResolutionError,
    SnapshotValues,
    require_reference_diagnostics,
    resource_index,
)
from model.identity import Resolver
from model.projection import generated_document, reference_display, reference_resolver
from model.reference_nodes import parse
from model.reference_values import reference_value
from model.render import generate_files, generate_markdown
from model.sources import load_model
from model.validations.full_inputs import check_model_inputs as model_inputs
from model.validations.json_settings import validate_json_settings
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from sync_files import save_files
from utils.aws_mappings import mapping_alias
from utils.cloudformation.inputs import Blocked
from utils.input_cache import input_context
from utils.script_loader import module
from validation import design
from validation.findings import Findings
from validation.runner import Validator

from model import change_plan, sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture(params=["CREATE", "IMPORT"])
def models(tmp_path, request):
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
        human = tmp_path / "issues/qa/team/human-confirmations.yaml"
        human.parent.mkdir(parents=True)
        human.write_text(
            json.dumps(
                dict(version=2, environment="qa", target="team", confirmations=[])
            )
            + "\n",
            encoding="utf-8",
        )
        producer, key = resource(
            tmp_path,
            "kms",
            "KMS.Key",
            number="004",
            attribute="KeyId",
            observed="PENDING_DEPLOY",
        )
        key["desired.resource.004.resourceMode"] = request.param
        if request.param == "IMPORT":
            key.pop("desired.resource.004.cfn-logicalId")
        save(producer, key)
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
                "desired.row.070-003.property": "IAM.Role.Policies[].PolicyName",
                "desired.row.070-003.value": "`synthetic-policy`",
                "desired.row.070-003.comment": "合成",
                "desired.row.070-004.property": "IAM.Role.Policies[].PolicyDocument",
                "desired.row.070-004.value": "[Policy](iam/iam-role-070-synthetic-policy.json)",
                "desired.row.070-004.comment": "合成",
                "desired.row.070-004.document": json.dumps(document),
            }
        )
        role.update(
            {
                "desired.row.070-002.property": "IAM.Role.AssumeRolePolicyDocument",
                "desired.row.070-002.value": "[Trust](iam/iam-role-070-trust-policy.json)",
                "desired.row.070-002.comment": "合成",
                "desired.row.070-002.document": json.dumps(
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


def materialize(consumer, role, document, *, warnings=None):
    return generated_document(
        document,
        consumer.root,
        resolver=reference_resolver(role, consumer, consumer.root),
        scope=consumer,
        logical_id="IAM_Role_070",
        property_name="IAM.Role.Policies[].PolicyDocument",
        model_key="desired.row.070-004.document",
        warnings=warnings,
    )


def _interrupt_required(validator):
    assert validator.findings.status in {"PASS", "FAIL"}
    raise KeyboardInterrupt("required handler interrupted")


@pytest.mark.parametrize(
    "fault", [None, "target", "attribute", "type", "stale", "iac", "interrupt"]
)
def test_pending_model_only_validation_and_final_acceptance(models, fault):
    _, _, consumer, role, document = models
    root = consumer.root
    before = sources.raw_model(consumer.path)
    view = root / "docs/designs/qa/team/iam.md"
    document["Statement"][6]["Action"] = "kms:Encrypt"
    role["desired.row.070-004.document"] = json.dumps(document)
    save(consumer, role)
    outputs = generate_files(view, role, root)
    save_files(outputs)
    assert (
        "PENDING_DEPLOY"
        in outputs[view.with_suffix("") / "iam-role-070-synthetic-policy.json"]
    )
    if fault in {"target", "attribute"}:
        document["Statement"][6]["Resource"] = reference(
            "KMS_Key_999" if fault == "target" else "KMS_Key_004",
            "Arn" if fault == "target" else "RoleName",
        )
        role["desired.row.070-004.document"] = json.dumps(document)
    elif fault == "type":
        role.update(
            {
                "desired.row.070-005.property": "IAM.Role.MaxSessionDuration",
                "desired.row.070-005.value": "invalid-number",
                "desired.row.070-005.comment": "合成",
            }
        )
    elif fault == "stale":
        artifact = view.with_suffix("") / "iam-role-070-synthetic-policy.json"
        artifact.write_text("{}\n", encoding="utf-8")
    save(consumer, role)
    after = sources.raw_model(consumer.path)
    scope = {("qa", "team", "iam")}
    plan = change_plan.ChangePlan(
        changes={next(iter(scope)): change_plan.compare(before, after)},
        views=scope,
        reads=sources.FileReads(),
    )
    validator = Validator(root, scope, model_validation="change", workers=1)
    validator.task_type = "design"
    validator.change_plan = plan
    validator.acceptance_checks = [
        ("R1", "check", "framework.generated-service-model"),
        ("R1", "check", "framework.policy-tables"),
    ]
    with patch.object(
        design, "check_policy_view_integrity", wraps=design.check_policy_view_integrity
    ) as policy:
        validator.findings.evaluate(
            "validation.changed-model", scope, validator.check_changed_designs
        )
        if fault == "interrupt":
            validator.findings.evaluate(
                "validation.required", scope, partial(_interrupt_required, validator)
            )
        if fault == "iac":
            template = root / "infra/cloudformation/templates/role.yaml"
            parameters = root / "infra/cloudformation/parameters/qa/team/role.json"
            template.parent.mkdir(parents=True, exist_ok=True)
            parameters.parent.mkdir(parents=True, exist_ok=True)
            template.write_text(
                "Parameters:\n  Environment:\n    Type: String\nResources:\n  Role:\n    Type: AWS::IAM::Role\n    Properties:\n      RoleName: !Ref Environment\n",
                encoding="utf-8",
            )
            parameters.write_text(
                '[{"ParameterKey":"Environment","ParameterValue":"wrong"}]\n',
                encoding="utf-8",
            )
            validator.iac_paths = {template, parameters}
            validator.findings.evaluate(
                "iac.environment",
                scope,
                partial(
                    validator.check_cloudformation_environment_parameters,
                    stack_definitions={
                        view.with_name("cloudformation-stacks.md"): [
                            {"template": "role.yaml", "parameters": "role.json"}
                        ]
                    },
                ),
            )
        validator.check_acceptance_checks()
    assert validator.report() == int(fault is not None)
    assert validator.findings.status == ("PASS" if fault is None else "FAIL")
    if fault is None:
        assert policy.call_count > 0
        assert validator.acceptance_results == [
            "R1:check:framework.generated-service-model",
            "R1:check:framework.policy-tables",
        ]
        result = validator.findings.get_result(
            "framework.generated-service-model", scope
        )
        assert result.status == "PASS" and result.metadata["complete"]
        assert any(
            w.get("category") == "REFERENCE_PENDING_DEPLOY" for w in validator.warnings
        )
    else:
        assert all(f["reason"].strip() for f in validator.findings.failures())


@pytest.mark.parametrize("preregistered", [False, True])
@pytest.mark.parametrize("pending", [False, True])
def test_real_scoped_policy_aggregation(models, preregistered, pending):
    producer, key, consumer, role, _ = models
    if not pending:
        key["observed.row.004-001.value"] = "`12345678-1234-1234-1234-123456789abc`"
        save(producer, key)
    view = consumer.root / "docs/designs/qa/team/iam.md"
    save_files(generate_files(view, role, consumer.root))
    validator = Validator(consumer.root, {("qa", "team", "iam")}, workers=1)
    validator.check_project_topology()
    if preregistered:
        validator.findings.result("framework.policy-tables", validator.scope)
    validator.check_scoped_designs()
    assert not validator.errors, validator.errors
    assert validator.findings.status == "PASS", validator.findings.failures()
    for check_id in ("framework.generated-service-model", "framework.policy-tables"):
        result = validator.findings.get_result(check_id, validator.scope)
        assert result.status == "PASS" and result.metadata["complete"]
    assert validator.report() == 0


@pytest.mark.parametrize(
    "fault,code",
    [
        ("syntax", "MODEL_REF_INVALID_SYNTAX"),
        ("missing", "MODEL_REF_TARGET_MISSING"),
        ("ambiguous", "MODEL_REF_TARGET_AMBIGUOUS"),
        ("attribute", "MODEL_REF_INVALID_ATTRIBUTE"),
        ("pending-desired", "MODEL_REF_INVALID_PENDING_STATE"),
        ("invalid-arn", "MODEL_REF_INVALID_VALUE"),
        ("local-ambiguous", "MODEL_REF_TARGET_AMBIGUOUS"),
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
    elif fault == "invalid-arn":
        key.update(
            {
                "observed.row.004-001.value": "`12345678-1234-1234-1234-123456789abc`",
                "desired.row.004-002.property": "KMS.Key.Arn",
                "desired.row.004-002.value": "`"
                + json.dumps(reference("KMS_Key_004", "Arn"))
                + "`",
                "desired.row.004-002.comment": "合成",
                "observed.row.004-002.value": "`invalid-arn`",
            }
        )
        save(producer, key)
    elif fault == "local-ambiguous":
        key.update(
            {
                "desired.resource.005.resourceType": "KMS.Key",
                "desired.resource.005.logicalId": "KMS_Key_004",
            }
        )
        save(producer, key)
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
        diagnostic["modelKey"] == "desired.row.070-004.document"
        and diagnostic["action"]
    )
    assert not isinstance(caught.value, ReferenceResolutionError)
    findings = Findings(consumer.root)
    findings.warn(caught.value)
    comparison = SimpleNamespace(
        root=consumer.root,
        environment=consumer.environment,
        directory=consumer.target,
        redacted=lambda value: value,
    )
    issues = reference_issues(findings, comparison, ["iam", "kms", "duplicate"])
    assert all(
        item["resource"] is None and item["property"] is None
        for item in issues
        if item["service"] != "iam"
    )
    original = copy.deepcopy(issues)
    report_path = consumer.root / "issues/qa/team/issues.md"
    for issue in issues:
        content = issue_content(consumer.root, report_path, issue)
        expected = f"model/qa/team/{issue['service']}.properties"
        assert f"根拠: [{expected}]" in content
        assert issue["diagnostic"]["model"] == str(consumer.path)
        assert f"<!-- issue-id: {issue['id']} -->" in content
    assert issues == original
    unknown = copy.deepcopy(issues[0])
    unknown["ownership"]["owner"] = None
    unknown["diagnostic"]["fixModels"] = [str(producer.path)]
    assert "根拠:" not in issue_content(consumer.root, report_path, unknown)
    unknown["ownership"] = copy.deepcopy(issues[0]["ownership"])
    owned_model = next(
        model
        for model in diagnostic.get("fixModels", [str(consumer.path)])
        if Path(model).stem == issues[0]["service"]
    )
    link = consumer.root / "model/qa/team/alias.properties"
    link.symlink_to(owned_model)
    for candidates in (
        [owned_model, owned_model],
        [str(link)],
        [str(consumer.root.parent / "outside.properties")],
        [str(consumer.root / "model/qa/team/../team" / Path(owned_model).name)],
    ):
        unknown["diagnostic"]["fixModels"] = candidates
        assert "根拠:" not in issue_content(consumer.root, report_path, unknown)
    owners = {issue["service"] for issue in issues}
    if fault == "ambiguous":
        assert owners == {"kms", "duplicate"}
        assert set(diagnostic["fixModels"]) == {
            str(producer.path),
            str(producer.path.with_name("duplicate.properties")),
        }
    elif fault in {
        "pending-desired",
        "invalid-arn",
        "local-ambiguous",
    }:
        assert owners == {"kms"} and diagnostic["producerModel"] == str(producer.path)
        assert diagnostic["fixModels"] == [str(producer.path)]
        if fault == "local-ambiguous":
            assert diagnostic["resourceIds"] == ["004", "005"]
            assert diagnostic["producerModelKey"] == "desired.resource.005.logicalId"
    else:
        assert owners == {"iam"}
        if fault == "attribute":
            assert diagnostic["producerModel"] == str(producer.path)


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
    findings = Findings(consumer.root)
    findings.warn(caught.value)
    comparison = SimpleNamespace(
        root=consumer.root,
        environment=consumer.environment,
        directory=consumer.target,
        redacted=lambda value: value,
    )
    assert reference_issues(findings, comparison, ["iam", "kms"])[0]["service"] == "iam"
    with pytest.raises(FrameworkUnsupportedError) as caught:
        resolver.validate_attribute("Future.Resource", "Arn")
    assert caught.value.diagnostic["category"] == "FRAMEWORK_UNSUPPORTED"
    findings = Findings(consumer.root)
    findings.warn(caught.value)
    assert findings.processing_errors and not reference_issues(
        findings,
        SimpleNamespace(
            root=consumer.root,
            environment=consumer.environment,
            directory=consumer.target,
            redacted=lambda value: value,
        ),
        ["iam"],
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
            "desired.row.001-002.value": "`"
            + json.dumps(reference("S3_Bucket_001", "Arn"))
            + "`",
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
    findings = Findings(consumer.root)
    findings.warn(caught.value)
    comparison = SimpleNamespace(
        root=consumer.root,
        environment=consumer.environment,
        directory=consumer.target,
        redacted=lambda value: value,
    )
    assert reference_issues(findings, comparison, ["iam", "s3"])[0]["service"] == "s3"


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
    assert len(findings.reference_errors) == 2 and not findings.unverified


def test_pending_resolves_without_altering_authority(models):
    producer, key, consumer, role, document = models
    original = copy.deepcopy(document)
    warnings = []
    pending = materialize(consumer, role, document, warnings=warnings)
    assert pending["Statement"][6]["Resource"] == "PENDING_DEPLOY"
    diagnostic = warnings[0]
    assert (
        diagnostic["category"] == "REFERENCE_PENDING_DEPLOY"
        and diagnostic["status"] == "WARNING"
    )
    assert (
        diagnostic["targetLogicalId"] == "KMS_Key_004"
        and diagnostic["attribute"] == "Arn"
    )
    key["observed.row.004-001.value"] = "`12345678-1234-1234-1234-123456789abc`"
    save(producer, key)
    producer_view = consumer.root / "docs/designs/qa/team/kms.md"
    producer_view.parent.mkdir(parents=True, exist_ok=True)
    producer_view.write_text(
        generate_markdown(producer_view, load_model(producer).values, FRAMEWORK),
        encoding="utf-8",
    )
    result = materialize(consumer, role, document)
    assert (
        result["Statement"][6]["Resource"]
        == "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789abc"
    )
    assert document == original and "$modelRef" in role["desired.row.070-004.document"]
    plan = sync_runtime.prepare_generation(
        consumer.root,
        {("qa", "team", "iam")},
        write=False,
        definitions_root=FRAMEWORK,
        strict=True,
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
    role["desired.row.070-004.document"] = json.dumps(document)
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
    comparison = SimpleNamespace(
        root=consumer.root,
        environment=consumer.environment,
        directory=consumer.target,
        redacted=lambda value: value,
    )
    first = reference_issues(findings, comparison, ["iam"])
    assert len(first) == 1 and first[0]["severity"] == "ERROR"
    assert first[0]["diagnostic"]["code"] == "MODEL_REF_TARGET_MISSING"
    assert (first[0]["resource"], first[0]["property"], first[0]["rule"]) == (
        "070",
        "IAM.Role.Policies[].PolicyDocument",
        "MODEL_REF_TARGET_MISSING",
    )
    assert first[0]["message"] == findings.reference_errors[0]["message"]
    assert first[0]["diagnostic"] == findings.reference_errors[0]
    report = ordinary_report(
        consumer.root,
        dict(
            environment=consumer.environment,
            target=consumer.target,
            services=["iam"],
            executed_at="2026-10-27T00:00:00Z",
            ordinary=first,
            unverified=[],
            processing_errors=[],
            warnings=[],
        ),
    )
    assert first[0]["message"] in report and '{"code"' not in report
    assert "070 / IAM.Role.Policies[].PolicyDocument" in report
    assert (
        "[model/qa/team/iam.properties](../../../model/qa/team/iam.properties)"
        in report
    )
    assert f"<!-- issue-id: {first[0]['id']} -->" in report
    findings.reference_errors[0]["message"] = "reworded explanation"
    assert reference_issues(findings, comparison, ["iam"])[0]["id"] == first[0]["id"]
    assert (
        validation_status(dict(ordinary=first, overview={"records": {"error": 0}}))
        == "FAIL"
    )
    assert load_model(consumer).warnings[0]["category"] == "MODEL_NEEDS_FIX"


@pytest.mark.parametrize("state", ["pending", "invalid", "mixed"])
def test_generation_keeps_failed_service_and_saves_healthy_service(models, state):
    _, _, consumer, role, document = models
    invalid = state != "pending"
    if state == "invalid":
        document["Statement"][6]["Resource"] = "*"
    if invalid:
        document["Statement"][0]["Resource"] = reference("KMS_Key_999")
        role["desired.row.070-004.document"] = json.dumps(document)
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
            "model.validations.full_inputs.check_model_inputs",
            return_value=SimpleNamespace(
                errors=(), warnings=(), diagnostics=[], unverified=()
            ),
        ),
        patch.object(sync_runtime, "markdown_for", return_value="# Generated\n"),
    ):
        generated = sync_runtime.generate_views(
            stage,
            root,
            {bad: load_model(consumer).values, good: load_model(good_scope).values},
            failures,
            warnings=warnings,
            unavailable=unavailable,
        )
    assert set(generated) == ({good} if invalid else {good, bad})
    assert bool(failures) == invalid
    assert not unavailable
    assert {path: path.read_bytes() for path in original} == original
    if invalid:
        assert (stage / artifact.relative_to(root)).read_bytes() == original[artifact]
    else:
        assert (
            json.loads((stage / artifact.relative_to(root)).read_bytes())["Statement"][
                6
            ]["Resource"]
            == "PENDING_DEPLOY"
        )
    sync_runtime.save_files(
        {
            root / path.relative_to(stage): path.read_text(encoding="utf-8")
            for paths in generated.values()
            for path in paths
        }
    )
    assert good.read_text(encoding="utf-8") == "# Generated\n"
    if invalid:
        assert artifact.read_bytes() == original[artifact]
        assert bad.read_bytes() == original[bad]
    else:
        assert (
            json.loads(artifact.read_bytes())["Statement"][6]["Resource"]
            == "PENDING_DEPLOY"
        )
        assert bad.read_text(encoding="utf-8") == "# Generated\n"
    plan = SimpleNamespace(
        root=root,
        generated_scope={("qa", "team", path.stem) for path in generated},
        generated=generated,
        failure_records=failures,
        failures=[d.message for d in failures],
        unavailable=unavailable,
        reference_warnings=warnings,
        warnings={},
        saved={path: True for path in generated},
        model_paths=[consumer.path, good_scope.path],
        markdown_paths=[bad, good],
        baseline_links={},
    )
    metadata = sync_runtime.generation_metadata(plan)
    assert metadata["status"] == ("FAIL" if invalid else "PASS")
    assert metadata["complete"] == (not invalid)
    assert not metadata["unavailable_services"]
    assert not metadata["unverified"]
    assert metadata["warnings"] == warnings
    if invalid:
        with pytest.raises(ValueError):
            sync_runtime.report_generation(plan)
    else:
        sync_runtime.report_generation(plan)


def test_conflicting_design_documents_fail_before_saving(models):
    producer, key, consumer, role, _ = models
    key["observed.row.004-001.value"] = "`12345678-1234-1234-1234-123456789abc`"
    save(producer, key)
    role["desired.row.070-002.value"] = role["desired.row.070-004.value"]
    save(consumer, role)
    path = consumer.root / "docs/designs/qa/team/iam.md"
    artifact = path.with_suffix("") / "iam-role-070-synthetic-policy.json"
    artifact.parent.mkdir(parents=True)
    path.write_text("# Retained\n", encoding="utf-8")
    artifact.write_text('{"retained":true}\n', encoding="utf-8")
    before = {p: p.read_bytes() for p in (path, artifact, consumer.path)}
    values = load_model(consumer).values
    with pytest.raises(ValueError, match="conflicting authoritative JSON"):
        generate_files(path, values, consumer.root)
    failures = []
    assert not sync_runtime.generate_views(
        consumer.root / "conflict-stage", consumer.root, {path: values}, failures
    )
    assert (
        len(failures) == 1 and "conflicting authoritative JSON" in failures[0].message
    )
    assert {p: p.read_bytes() for p in before} == before


def test_pending_policy_display_keeps_resolved_positions(models):
    _, _, consumer, role, document = models
    document["Statement"][0]["Resource"] = "arn:aws:s3:::confirmed-bucket"
    role["desired.row.070-004.document"] = json.dumps(document)
    save(consumer, role)
    original = consumer.path.read_bytes()
    displayed = reference_display(
        load_model(consumer).values, consumer.path, consumer.root
    )
    projected = json.loads(displayed["desired.row.070-004.document"])
    assert projected["Statement"][0]["Resource"] == "arn:aws:s3:::confirmed-bucket"
    assert projected["Statement"][6]["Resource"] == document["Statement"][6]["Resource"]
    assert displayed["desired.row.070-004.value"] == role["desired.row.070-004.value"]
    assert "desired.row.070-004.artifactSha256" not in displayed
    path = consumer.root / "docs/designs/qa/team/iam.md"
    path.parent.mkdir(parents=True)
    trust = path.with_suffix("") / "iam-role-070-trust-policy.json"
    trust.parent.mkdir()
    trust.write_text(role["desired.row.070-002.document"], encoding="utf-8")
    artifact = trust.with_name("iam-role-070-synthetic-policy.json")
    artifact.write_text(json.dumps(document), encoding="utf-8")
    markdown = generate_markdown(path, load_model(consumer).values, FRAMEWORK)
    path.write_text(markdown, encoding="utf-8")
    assert "confirmed-bucket" in markdown and "](kms.md#saved-004)" in markdown
    assert "iam/iam-role-070-synthetic-policy.json" in markdown
    assert "iam/iam-role-070-trust-policy.json" in markdown
    assert "pending_deploy" not in markdown
    assert rendered_design(path, definitions_root=FRAMEWORK) == markdown
    assert consumer.path.read_bytes() == original
    assert (
        materialize(consumer, role, document)["Statement"][6]["Resource"]
        == "PENDING_DEPLOY"
    )
    failures, unavailable = [], {}
    strict = sync_runtime.generate_views(
        consumer.root / "strict-stage",
        consumer.root,
        {path: load_model(consumer).values},
        failures,
        unavailable=unavailable,
        strict=True,
    )
    assert path in strict and not failures and not unavailable
    # A display marker alone never authorizes a missing JSON exception.
    document["Statement"][6]["Resource"] = "*"
    role["desired.row.070-004.document"] = json.dumps(document)
    save(consumer, role)
    assert rendered_design(path, definitions_root=FRAMEWORK) != markdown


def test_real_input_validation_does_not_invent_pending_errors(models):
    _, _, consumer, role, _ = models
    findings = model_inputs(
        consumer.path, role, consumer.root, definitions_root=FRAMEWORK
    )
    assert not findings.errors, findings.errors
    assert findings.status == "PASS" and not findings.unverified
    assert findings.result("model.json-settings", None).status == "PASS"


@pytest.mark.parametrize("field", ["value", "document"])
def test_input_and_generation_share_reference_evaluation(models, field):
    _, _, consumer, role, document = models
    model_key = f"desired.row.070-004.{field}"
    if field == "value":
        role.pop("desired.row.070-004.document")
        role[model_key] = "`" + json.dumps(document) + "`"
    role = SnapshotValues(role)
    with (
        input_context(read_only=True),
        patch.object(
            projection, "reference_value", wraps=projection.reference_value
        ) as evaluate,
    ):
        checked = []
        validate_json_settings(role, consumer.path, warnings=checked)
        assert evaluate.call_count == 1
        generated = []
        projected = generated_document(
            document,
            consumer.root,
            resolver=reference_resolver(role, consumer, consumer.root),
            scope=consumer,
            logical_id="IAM_Role_070",
            property_name="IAM.Role.Policies[].PolicyDocument",
            model_key=model_key,
            context=projection.reference_context_for(
                role,
                "070-004",
                {"property": "IAM.Role.Policies[].PolicyDocument"},
                document,
                "",
                consumer.root,
            ),
            warnings=generated,
        )
        assert projected["Statement"][6]["Resource"] == "PENDING_DEPLOY"
        assert evaluate.call_count == 1
    assert checked == generated
    assert checked[0]["modelKey"] == model_key
    assert checked[0]["pointer"] == "/Statement/6/Resource"


def test_reference_wait_findings_are_not_pass(models):
    _, _, consumer, role, document = models
    findings = Findings(consumer.root)
    _, diagnostics = projection.document_references(
        document,
        resolver=reference_resolver(role, consumer, consumer.root),
        scope=consumer,
    )
    result = findings.evaluate(
        "projection",
        None,
        partial(require_reference_diagnostics, diagnostics),
        isolate=True,
    )
    assert result.status == "FAIL" and not result.errors and result.warnings
    assert not findings.reference_errors and not findings.processing_errors
    with pytest.raises(ReferenceResolutionError):
        require_reference_diagnostics(list(result.warnings))


@pytest.mark.parametrize("state", ["pending", "mixed", "producer-invalid"])
def test_real_generation_and_issues_scan_keep_reference_categories(models, state):
    producer, key, consumer, role, document = models
    invalid = state != "pending"
    if state == "mixed":
        document["Statement"][0]["Resource"] = reference("KMS_Key_999")
        role["desired.row.070-004.document"] = json.dumps(document)
        save(consumer, role)
    elif state == "producer-invalid":
        key.update(
            {
                "observed.row.004-001.value": "`12345678-1234-1234-1234-123456789abc`",
                "desired.row.004-002.property": "KMS.Key.Arn",
                "desired.row.004-002.value": "`"
                + json.dumps(reference("KMS_Key_004", "Arn"))
                + "`",
                "desired.row.004-002.comment": "合成",
                "observed.row.004-002.value": "`invalid-arn`",
            }
        )
        save(producer, key)
    plan = sync_runtime.prepare_generation(
        consumer.root, {("qa", "team", "iam")}, write=False, definitions_root=FRAMEWORK
    )
    try:
        assert bool(plan.failures) == invalid, plan.failures
        assert not plan.unavailable
        assert bool(plan.generated) == (not invalid)
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
        patch("issues.inputs.Comparison.run", return_value=[]),
        patch("issues.cfn_lint.run_lint", return_value=lint),
    ):
        artifact = scan(consumer.root, "qa", "team", ["iam"], jobs=1)
    assert artifact["version"] == 6
    classified = [
        record
        for record in artifact["ordinary"]
        if record.get("diagnostic", {}).get("category") == "MODEL_NEEDS_FIX"
    ]
    assert len(classified) == int(state == "mixed"), artifact["ordinary"]
    if state == "producer-invalid":
        assert any(
            item.get("diagnostic", {}).get("code") == "MODEL_REF_INVALID_VALUE"
            and item["ownership"]["owner"][2] == "kms"
            for item in artifact["information"]
        )
    if classified:
        assert classified[0]["service"] == (
            "kms" if state == "producer-invalid" else "iam"
        )
    assert any(
        w.get("category") == "REFERENCE_PENDING_DEPLOY" for w in artifact["warnings"]
    ) == (state != "producer-invalid")
    assert not any(
        record.get("code") == "MODEL_REF_TARGET_MISSING"
        for record in artifact["processing_errors"]
    )
    assert not any(
        "MODEL_REF_TARGET_MISSING" in record["message"] and "diagnostic" not in record
        for record in artifact["ordinary"]
    )
    validator = Validator(consumer.root, {("qa", "team", "iam")}, workers=1)
    validator.check_scoped_designs()
    assert len(validator.findings.reference_errors) == int(invalid), (
        validator.findings.reference_errors
    )
    assert len(
        [
            w
            for w in validator.warnings
            if w.get("category") == "REFERENCE_PENDING_DEPLOY"
        ]
    ) == int(state != "producer-invalid"), validator.warnings
    assert (
        len(
            [
                item
                for item in validator.findings.unverified
                if item.get("category") == "REFERENCE_PENDING_DEPLOY"
            ]
        )
        == 0
    )
    assert len(validator.findings.reference_error_positions) == int(invalid)


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
    assert code == 0 and "View generation: PENDING_DEPLOY" in output
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
        findings,
        SimpleNamespace(
            root=consumer.root,
            environment=consumer.environment,
            directory=consumer.target,
            redacted=lambda value: value,
        ),
        ["iam"],
    )
    findings = Findings(consumer.root)
    findings.warn(
        ModelNeedsFixError(
            "violation location is unknown",
            model=str(consumer.path),
            producerModel=str(consumer.path.with_name("kms.properties")),
        )
    )
    findings.warn(
        ModelNeedsFixError(
            "another violation location is unknown",
            model=str(consumer.path),
            producerModel=str(consumer.path.with_name("kms.properties")),
        )
    )
    assert (
        len(findings.reference_errors) == 2
        and len(
            reference_issues(
                findings,
                SimpleNamespace(
                    root=consumer.root,
                    environment=consumer.environment,
                    directory=consumer.target,
                    redacted=lambda value: value,
                ),
                ["iam", "kms"],
            )
        )
        == 2
    )


def test_invalid_source_identity_is_structured_without_duplicate_failure(models):
    producer, key, consumer, role, _ = models
    key["observed.row.004-001.value"] = "`12345678-1234-1234-1234-123456789abc`"
    save(producer, key)
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
    comparison = SimpleNamespace(
        root=consumer.root,
        environment=consumer.environment,
        directory=consumer.target,
        redacted=lambda value: value,
    )
    assert len(reference_issues(findings, comparison, ["iam"])) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
