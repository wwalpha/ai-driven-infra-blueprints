"""PLAINTEXT reference policy and ordinary Issue publication; synthetic inputs only."""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import validation.design_tables as design_tables
from design.catalog import DesignSchemaCatalog
from design.document import model_reference_tables
from design.services.codebuild import codebuild_display_row, codebuild_formal_rows
from issues.artifact import scan_exit_code, validate_artifact
from issues.cli import main as issues_main
from issues.publication import save_scan
from issues.runner import codebuild_plaintext_diagnostics, scan
from model.core import entries
from model.display import display_rows
from model.render import generate_markdown, markdown_for
from model.validation import (
    check_model_inputs as _check_model_inputs,
)
from model.validation import (
    codebuild_reference_errors,
)
from support.issues_scan_fixtures import fixture, task, write
from support.model_sources import write_model
from support.pytest_cli import run
from utils.aws_mappings import mapping_alias
from utils.reference_contracts import reference_error
from validation.runner import Validator

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

FRAMEWORK = Path(__file__).resolve().parents[4]
PREFIX = "CodeBuild.Project.Environment.EnvironmentVariables"
REASON = "PLAINTEXTではResource linkは禁止"
NODE = {"$modelRef": {"logicalId": "S3_Bucket_001", "attribute": "Arn"}}


def values_for(variables, mode="CREATE", indexed=False):
    values = {
        "display.service.title": "# CodeBuild 詳細設計",
        "desired.service.codebuild.serviceId": "codebuild",
        "desired.service.codebuild.ownedCatalogResourceTypes": "CodeBuild.Project",
        "desired.service.identity.lastAllocated": '{"CodeBuild.Project":1}',
        "desired.resource.001.resourceType": "CodeBuild.Project",
        "desired.resource.001.resourceMode": mode,
        "desired.resource.001.logicalId": "CodeBuild_Project_001",
        "desired.resource.001.anchor": "project",
        "display.resource.001.comment": "合成 Project",
        "display.resource.001.label": "project",
    }
    rows = [
        ("Name", "`project`"),
        ("Artifacts.Type", "`NO_ARTIFACTS`"),
        ("Environment.Type", "`LINUX_CONTAINER`"),
        ("Environment.ComputeType", "`BUILD_GENERAL1_SMALL`"),
        ("Environment.Image", "`image`"),
        ("ServiceRole", "[role](iam.md#role)"),
        ("Source.Type", "`NO_SOURCE`"),
    ]
    for number, (name, variable_type, value) in enumerate(variables, 1):
        prefix = f"Environment.EnvironmentVariables[{number if indexed else ''}]."
        rows.extend(
            (prefix + field, raw)
            for field, raw in (
                ("Name", f"`{name}`"),
                ("Type", f"`{variable_type}`"),
                ("Value", value),
            )
        )
    for number, (prop, value) in enumerate(rows, 1):
        prefix = f"desired.row.001-{number:03d}."
        values.update(
            {
                prefix + "property": "CodeBuild.Project." + prop,
                prefix + "value": value,
                prefix + "comment": "合成設定",
            }
        )
    return values


@pytest.fixture
def models(tmp_path):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "projectName": "fixture",
                "targets": [
                    {
                        "environment": "dev",
                        "alias": "team",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "terraform",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with mapping_alias(FRAMEWORK, tmp_path):
        yield tmp_path


def dependency_projects(
    root, *, schema_error=False, typed=False, pending=False, target="team"
):
    if target == "team":
        project_path = root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["targets"].append(
            {**project["targets"][0], "alias": "other", "awsAccountId": "987654321098"}
        )
        project["targets"].sort(key=lambda target: target["alias"])
        project_path.write_text(json.dumps(project) + "\n", encoding="utf-8")
    values = values_for([("VALUE", "PLAINTEXT", "`literal`")])
    values.update(
        {
            "desired.row.001-900.property": "CodeBuild.Project.Id",
            "desired.row.001-900.value": "`synthetic-project-id`",
            "desired.row.001-900.comment": "合成識別子",
        }
    )
    if typed:
        role = {
            "desired.service.iam.serviceId": "iam",
            "desired.service.iam.ownedCatalogResourceTypes": "IAM.Role",
            "desired.service.identity.lastAllocated": '{"IAM.Role":1}',
            "desired.resource.001.resourceType": "IAM.Role",
            "desired.resource.001.resourceMode": "IMPORT",
            "desired.resource.001.logicalId": "IAM_Role_001",
            "desired.resource.001.anchor": "role",
            "desired.row.001-001.property": "IAM.Role.RoleName",
            "desired.row.001-001.value": "`role`",
            "desired.row.001-001.comment": "合成Role",
            "desired.row.001-002.property": "IAM.Role.Arn",
            "desired.row.001-002.value": "[role](#role)",
            "desired.row.001-002.comment": "合成ARN",
        }
        if not pending:
            role["observed.row.001-002.value"] = "`arn:aws:iam::123456789012:role/role`"
        if pending:
            role["desired.resource.001.resourceMode"] = "CREATE"
            role["observed.row.001-002.value"] = "`PENDING_DEPLOY`"
        write_model(root / "model/dev" / target / "iam.properties", role)
        values["desired.row.001-006.value"] = (
            '`{"$modelRef":{"logicalId":"IAM_Role_001","attribute":"Arn"}}`'
        )
    original = dict(values)
    for identity, name in (("002", "second"), ("003", "third")):
        for key, value in original.items():
            if key.startswith(
                ("desired.resource.001.", "display.resource.001.", "desired.row.001-")
            ):
                key = key.replace(".001.", "." + identity + ".").replace(
                    ".001-", "." + identity + "-"
                )
                values[key] = value
        values[f"desired.resource.{identity}.logicalId"] = (
            "CodeBuild_Project_" + identity
        )
        values[f"desired.resource.{identity}.anchor"] = name
        values[f"display.resource.{identity}.label"] = name
        values[f"desired.row.{identity}-001.value"] = "`" + name + "`"
    values["desired.service.identity.lastAllocated"] = '{"CodeBuild.Project":3}'
    if schema_error:
        values.update(
            {
                "desired.row.002-901.property": "CodeBuild.Project.TimeoutInMinutes",
                "desired.row.002-901.value": "`invalid`",
                "desired.row.002-901.comment": "独立した型違反",
            }
        )
    path = root / "model/dev" / target / "codebuild.properties"
    view = root / "docs/designs/dev" / target / "codebuild.md"
    write_model(path, values)
    view.parent.mkdir(parents=True, exist_ok=True)
    view.write_text(generate_markdown(view, values, FRAMEWORK), encoding="utf-8")
    dependency_index.rebuild(root)
    return path, view, values


def assert_dependency_errors(findings):
    assert any(REASON in error for error in findings.errors), findings.errors
    assert any(
        "provider schema violation" in error and "TimeoutInMinutes" in error
        for error in findings.errors
    ), findings.errors
    assert not any(
        "not selected by design catalog" in error or "identifier output row" in error
        for error in findings.errors
    ), findings.errors
    assert not findings.processing_errors, findings.processing_errors
    semantic = findings.result("design.tables.semantic", {("dev", "team", "codebuild")})
    assert semantic.status == "NOT_RUN" and not semantic.model_completion_allowed
    assert any(
        item.get("resource") == "CodeBuild_Project_001"
        for item in semantic.metadata["unverified"]
    )


def test_model_reference_failure_keeps_independent_schema_and_valid_resource(models):
    path, view, values = dependency_projects(models, schema_error=True, typed=True)
    values["desired.row.001-010.value"] = "[bucket](s3.md#bucket)"
    write_model(path, values)
    validator = Validator(
        models, {("dev", "team", "codebuild")}, definitions_root=FRAMEWORK
    )
    validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
    with patch.object(
        design_tables,
        "check_generated_identifier",
        wraps=design_tables.check_generated_identifier,
    ) as identifiers:
        result = validator.findings.evaluate(
            "design.tables",
            validator.scope,
            lambda: validator.check_design_tables(
                *validator.check_design_service_ownership([view]), paths=[view]
            ),
            isolate=True,
        )
    assert result.status == "FAIL" and not result.model_completion_allowed
    assert_dependency_errors(validator.findings)
    assert [call.args[2] for call in identifiers.call_args_list] == [
        "CodeBuild_Project_002",
        "CodeBuild_Project_003",
    ]


@pytest.mark.parametrize("raw_error", [False, True])
def test_scoped_generation_failure_keeps_saved_raw_and_schema(models, raw_error):
    path, view, values = dependency_projects(models, schema_error=True, typed=True)
    values["desired.row.001-010.value"] = "[bucket](s3.md#bucket)"
    write_model(path, values)
    if raw_error:
        view.write_text(
            view.read_text(encoding="utf-8") + "\n# 重複H1\n", encoding="utf-8"
        )
    validator = Validator(
        models, {("dev", "team", "codebuild")}, definitions_root=FRAMEWORK, workers=1
    )
    validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
    with patch.object(
        design_tables,
        "check_raw_design_tables",
        wraps=design_tables.check_raw_design_tables,
    ) as raw:
        validator.check_project_topology()
        validator.check_scoped_designs()
    assert raw.call_count == 1
    assert_dependency_errors(validator.findings)
    assert any("exactly one H1" in error for error in validator.errors) == raw_error, (
        validator.errors
    )
    service = validator.findings.result("design.service", validator.scope)
    assert service.status == "FAIL" and not service.model_completion_allowed
    generation = validator.findings.result(
        "framework.generated-service-model", validator.scope
    )
    assert generation.status == "FAIL" and not generation.model_completion_allowed
    assert (
        validator.findings.result("design.observed-values", validator.scope).status
        == "PASS"
    )


@pytest.mark.parametrize("missing", [False, True])
def test_generation_failure_unreadable_raw_is_not_run(models, missing):
    path, view, values = dependency_projects(models)
    values["desired.row.001-010.value"] = "[bucket](s3.md#bucket)"
    write_model(path, values)
    if missing:
        view.unlink()
    else:
        view.write_bytes(b"\xff")
    validator = Validator(
        models, {("dev", "team", "codebuild")}, definitions_root=FRAMEWORK, workers=1
    )
    validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
    view_errors = {}
    if not missing:
        view_errors[view] = {"message": "invalid UTF-8"}
    validator.check_scoped_designs(view_errors=view_errors)
    raw = validator.findings.result("design.tables.raw", validator.scope)
    assert raw.status == "NOT_RUN" and not raw.model_completion_allowed
    assert raw.metadata["reason"] == "view-read" and raw.metadata["message"]
    assert not validator.findings.processing_errors, (
        validator.findings.processing_errors
    )


@pytest.mark.parametrize("pending", [False, True])
def test_scoped_normal_typed_reference_checks_raw_once(models, pending):
    _, view, values = dependency_projects(models, typed=True, pending=pending)
    validator = Validator(
        models, {("dev", "team", "codebuild")}, definitions_root=FRAMEWORK, workers=1
    )
    validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
    with patch.object(
        design_tables,
        "check_raw_design_tables",
        wraps=design_tables.check_raw_design_tables,
    ) as raw:
        validator.check_project_topology()
        validator.check_scoped_designs()
    assert not validator.errors, validator.errors
    assert not validator.findings.processing_errors
    assert raw.call_count == 1
    assert model_reference_tables(
        view, view.read_text(encoding="utf-8"), tuple(values.items()), FRAMEWORK
    )
    service = validator.findings.result("design.service", validator.scope)
    assert service.model_completion_allowed, service
    if pending:
        assert service.status in {"PASS", "NOT_RUN"}
        if service.status == "NOT_RUN":
            assert service.metadata["reason"] == "reference"
    else:
        assert service.status == "PASS" and not validator.findings.unverified


def test_missing_typed_target_is_model_error_not_reference_wait(models):
    dependency_projects(models, typed=True)
    (models / "model/dev/team/iam.properties").unlink()
    validator = Validator(
        models, {("dev", "team", "codebuild")}, definitions_root=FRAMEWORK, workers=1
    )
    validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
    validator.check_project_topology()
    with patch.object(
        design_tables,
        "check_raw_design_tables",
        wraps=design_tables.check_raw_design_tables,
    ) as raw:
        validator.check_scoped_designs()
    assert any("MODEL_REF_TARGET_MISSING" in error for error in validator.errors)
    assert not validator.findings.processing_errors
    assert raw.call_count == 1
    service = validator.findings.result("design.service", validator.scope)
    assert service.status == "FAIL" and service.metadata["reason"] == "dependency"
    assert not service.model_completion_allowed
    semantic = validator.findings.result("design.tables.semantic", validator.scope)
    assert semantic.status == "NOT_RUN" and not semantic.model_completion_allowed


@pytest.mark.usefixtures("catalog_display_fixture")
def test_issues_retains_mixed_causes_and_resource_dependencies(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        fixture(tmp_path, services=("s3",))
        path, view, values = dependency_projects(
            tmp_path, schema_error=True, target="123456789012"
        )
        values["desired.row.001-010.value"] = (
            "[bucket-app-dev-data1](s3.md#s3-bucket-app-dev-data1)"
        )
        write_model(path, values)
        view.write_text(
            view.read_text(encoding="utf-8") + "\n# 重複H1\n", encoding="utf-8"
        )
        artifact = scan(tmp_path, "dev", "123456789012", ["codebuild"], jobs=1)
        validate_artifact(artifact)
        messages = [
            item["message"]
            for item in [*artifact["ordinary"], *artifact["judgments"]]
            if "message" in item
        ]
        assert any(REASON in message for message in messages), messages
        assert any(
            "TimeoutInMinutes" in message and "provider schema violation" in message
            for message in messages
        ), messages
        assert any("exactly one H1" in message for message in messages), messages
        assert not any(
            "identifier output row" in message
            or "not selected by design catalog" in message
            for message in messages
        ), messages
        # Link validation now reaches the intentionally absent external IAM View.
        assert len(artifact["processing_errors"]) == 1
        assert artifact["processing_errors"][0]["code"] == "mechanical.view_read"
        assert artifact["processing_errors"][0]["service"] == "iam"
        assert not any(
            item.get("code") == "design.tables.dependency"
            and item.get("resource")
            and item.get("checks")
            for item in artifact["unverified"]
        )
        assert any(
            item["check_id"] == "design.service" and item["status"] == "FAIL"
            for item in artifact["check_results"]
        )


def test_recovery_rejects_independent_markdown_tampering(models):
    path, view, values = dependency_projects(models, typed=True)
    values["desired.row.001-010.value"] = "[bucket](s3.md#bucket)"
    write_model(path, values)
    view.write_text(
        view.read_text(encoding="utf-8").replace("`second`", "`tampered`"),
        encoding="utf-8",
    )
    validator = Validator(
        models, {("dev", "team", "codebuild")}, definitions_root=FRAMEWORK
    )
    validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
    with patch.object(
        design_tables,
        "check_generated_identifier",
        wraps=design_tables.check_generated_identifier,
    ) as identifiers:
        validator.check_design_tables(
            *validator.check_design_service_ownership([view]), paths=[view]
        )
    assert [call.args[2] for call in identifiers.call_args_list] == [
        "CodeBuild_Project_003"
    ]
    assert any(
        d.code == "design.display.mismatch" for d in validator.findings.diagnostics
    )
    assert not validator.findings.processing_errors


@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
@pytest.mark.parametrize(
    "value,forbidden",
    [
        ("`hello:world`", False),
        ("`arn:aws:s3:::fixture`", False),
        ("`https://example.com/path#fragment`", False),
        ("[bucket](s3.md#bucket)", True),
        ("[secret](secretsmanager.md#secret)", True),
        ("[key](kms.md#key)", True),
        ("[other](vpc.md#vpc)", True),
        ("[missing](missing.md#missing)", True),
        ("`" + json.dumps(NODE) + "`", True),
    ],
)
def test_model_policy(models, mode, value, forbidden):
    path = models / "model/dev/team/codebuild.properties"
    values = values_for([("VALUE", "PLAINTEXT", value)], mode)
    write_model(path, values)
    findings = _check_model_inputs(path, values, models, definitions_root=FRAMEWORK)
    errors = [error for error in findings.errors if REASON in error]
    assert len(errors) == int(forbidden), findings.errors
    if forbidden:
        assert all(
            text in errors[0]
            for text in [
                str(path),
                "CodeBuild_Project_001",
                "Name=VALUE",
                "Type=PLAINTEXT",
                "Property=" + PREFIX,
            ]
        )
        assert not any(REASON in str(w) for w in findings.warnings)
    else:
        assert not findings.errors, findings.errors


@pytest.mark.parametrize("indexed", [False, True])
def test_exact_sibling_type_and_continuation(models, indexed):
    path = models / "model/dev/team/codebuild.properties"
    values = values_for(
        [
            ("SECRET", "SECRETS_MANAGER", "[secret](secretsmanager.md#secret)"),
            ("BAD", "PLAINTEXT", "[missing](missing.md#missing)"),
            ("TEXT", "PLAINTEXT", "`literal`"),
            ("PARAMETER", "PARAMETER_STORE", "[parameter](ssm.md#parameter)"),
            ("OTHER_BAD", "PLAINTEXT", "`" + json.dumps(NODE) + "`"),
        ],
        indexed=indexed,
    )
    values.update(
        {
            "desired.row.001-999.property": "CodeBuild.Project.TimeoutInMinutes",
            "desired.row.001-999.value": "`invalid`",
            "desired.row.001-999.comment": "不正",
        }
    )
    write_model(path, values)
    findings = _check_model_inputs(path, values, models, definitions_root=FRAMEWORK)
    errors = [error for error in findings.errors if REASON in error]
    assert len(errors) == 2, findings.errors
    assert "Name=BAD," in errors[0] and "Name=OTHER_BAD," in errors[1]
    assert any("provider schema violation" in e for e in findings.errors)


def test_prohibited_link_preserves_resource_ownership_error(models):
    path = models / "model/dev/team/codebuild.properties"
    values = values_for([("VALUE", "PLAINTEXT", "[missing](missing.md#missing)")])
    values["desired.service.codebuild.ownedCatalogResourceTypes"] = "S3.Bucket"
    write_model(path, values)
    findings = _check_model_inputs(path, values, models, definitions_root=FRAMEWORK)
    assert len(findings.errors) == 2, findings.errors
    assert sum(REASON in error for error in findings.errors) == 1
    assert any("outside service ownership" in error for error in findings.errors)


@pytest.mark.parametrize("indexed", [False, True])
def test_policy_diagnostic_identity_preserves_model_ids(models, indexed):
    values = values_for(
        [("VALUE", "PLAINTEXT", "[missing](missing.md#missing)")], indexed=indexed
    )
    path = models / "model/dev/team/codebuild.properties"
    original = next(iter(codebuild_reference_errors(path, values).values()))
    comparison = SimpleNamespace(
        root=models,
        environment="dev",
        directory="team",
        model=Mock(return_value=SimpleNamespace(values=values)),
    )
    detail = original.split("Name=", 1)[1]
    detail = re.sub(r"\[\d+\]", "[]", "Name=" + detail)
    markdown = (
        "invalid grouped design: docs/designs/dev/team/codebuild.md: "
        "Resource=CodeBuild.Project#project: " + detail
    )
    assert codebuild_plaintext_diagnostics(markdown, comparison) == [original]
    assert codebuild_plaintext_diagnostics(original, comparison) == [original]
    unrelated = "invalid resource identity: independent error\ninvalid grouped design: another error"
    assert codebuild_plaintext_diagnostics(unrelated, comparison) == [unrelated]
    other = markdown.replace("#project:", "#another:")
    assert codebuild_plaintext_diagnostics(other, comparison) != [original]


@pytest.mark.parametrize("document", [False, True])
def test_container_references_use_exact_context(models, document):
    values = values_for([])
    variables = [
        {"Name": "SECRET", "Type": "SECRETS_MANAGER", "Value": NODE},
        {"Name": "BAD", "Type": "PLAINTEXT", "Value": NODE},
        {
            "Name": "BAD_LINK",
            "Type": "PLAINTEXT",
            "Value": "[missing](missing.md#missing)",
        },
    ]
    values.update(
        {
            "desired.row.001-008.property": "CodeBuild.Project.Environment",
            "desired.row.001-008.value": "`"
            + json.dumps({"EnvironmentVariables": variables})
            + "`",
            "desired.row.001-008.comment": "合成",
        }
    )
    if document:
        values["desired.row.001-008.document"] = values[
            "desired.row.001-008.value"
        ].strip("`")
        values["desired.row.001-008.value"] = (
            "[Environment](codebuild/environment.json)"
        )
    errors = codebuild_reference_errors(
        models / "model/dev/team/codebuild.properties", values
    )
    assert len(errors) == 2
    assert (
        "Name=BAD,"
        in errors[
            "001-008",
            "document" if document else "value",
            "/EnvironmentVariables/1/Value",
        ]
    )
    assert (
        "Name=BAD_LINK,"
        in errors[
            "001-008",
            "document" if document else "value",
            "/EnvironmentVariables/2/Value",
        ]
    )


@pytest.mark.parametrize("marker", ["", "<!-- codebuild-variable-type: PLAINTEXT -->"])
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def test_markdown_rejects_plaintext_link(marker, mode):
    cells = [
        "1",
        "CodeBuild.Project.Environment.Variables.VALUE",
        "[missing](missing.md#missing)",
        marker,
    ]
    with pytest.raises(ValueError, match=REASON):
        codebuild_formal_rows(cells, set(), mode=mode)
    rows = [
        ["1", PREFIX + "[]." + field, value, "合成"]
        for field, value in (
            ("Name", "`VALUE`"),
            ("Type", "`PLAINTEXT`"),
            ("Value", cells[2]),
        )
    ]
    with pytest.raises(ValueError, match=REASON):
        codebuild_display_row(rows, 0, "合成", mode=mode)


@pytest.mark.parametrize("kind", ["PARAMETER_STORE", "SECRETS_MANAGER"])
def test_non_plaintext_round_trip(kind):
    cells = [
        "1",
        "CodeBuild.Project.Environment.Variables.VALUE",
        "[reference](service.md#resource)",
        f"<!-- codebuild-variable-type: {kind} --> 合成",
    ]
    rows = codebuild_formal_rows(cells, set())
    assert codebuild_display_row(rows, 0, "合成") == cells
    assert reference_error(PREFIX + "[].Value", {"Type": kind}) is None


@pytest.mark.parametrize(
    "unreadable_view,typed", [(False, False), (True, False), (False, True)]
)
@pytest.mark.usefixtures("catalog_display_fixture")
@pytest.mark.parametrize(
    "model_link,markdown_link,count,ownership_error",
    [
        (True, False, 1, False),
        (False, True, 1, False),
        (False, True, 2, False),
        (True, True, 1, False),
        (True, True, 2, False),
        (True, True, 1, True),
    ],
)
def test_scan_save_owns_codebuild_and_deduplicates(
    tmp_path, unreadable_view, typed, model_link, markdown_link, count, ownership_error
):
    with mapping_alias(FRAMEWORK, tmp_path):
        _, template = fixture(tmp_path, services=("s3",))
        path = tmp_path / "model/dev/123456789012/codebuild.properties"
        view = tmp_path / "docs/designs/dev/123456789012/codebuild.md"
        values = values_for(
            [
                (
                    "BUILD_BUCKET_NAME" + str(number),
                    "PLAINTEXT",
                    "`bucket-app-dev-data1`",
                )
                for number in range(count)
            ]
        )
        if typed:
            role = {
                "desired.service.iam.serviceId": "iam",
                "desired.service.iam.ownedCatalogResourceTypes": "IAM.Role",
                "desired.service.identity.lastAllocated": '{"IAM.Role":1}',
                "desired.resource.001.resourceType": "IAM.Role",
                "desired.resource.001.logicalId": "IAM_Role_001",
                "desired.resource.001.anchor": "role",
                "desired.resource.001.resourceMode": "IMPORT",
                "desired.row.001-001.property": "IAM.Role.RoleName",
                "desired.row.001-001.value": "`role`",
                "desired.row.001-001.comment": "合成Role",
            }
            write_model(path.with_name("iam.properties"), role)
            role_view = view.with_name("iam.md")
            write(
                role_view,
                generate_markdown(
                    role_view,
                    {
                        **role,
                        "display.service.title": "# 合成IAM",
                        "display.resource.001.comment": "合成Role",
                    },
                    tmp_path,
                ),
            )
            role_key = next(
                key.removesuffix("property") + "value"
                for key, value in values.items()
                if value == "CodeBuild.Project.ServiceRole"
            )
            values[role_key] = (
                '`{"$modelRef":{"logicalId":"IAM_Role_001","attribute":"Arn"}}`'
            )
        values["desired.resource.001.cfn-logicalId"] = "cfn-stack-app-dev-data1-Build"
        values.update(
            {
                "desired.row.001-900.property": "CodeBuild.Project.Id",
                "desired.row.001-900.value": "`synthetic-project-id`",
                "desired.row.001-900.comment": "合成識別子",
            }
        )
        write_model(path, values)
        write(view, markdown_for(view, values, tmp_path))
        variables = {rid: row for rid, row in entries(values, "desired.row.")}
        variable_ids = [
            rid
            for rid, row in variables.items()
            if row["property"].endswith("EnvironmentVariables[].Value")
        ]
        if markdown_link and not unreadable_view:
            write(
                view,
                view.read_text(encoding="utf-8").replace(
                    "`bucket-app-dev-data1`",
                    "[bucket-app-dev-data1](s3.md#s3-bucket-app-dev-data1)",
                ),
            )
        if model_link:
            for rid in variable_ids:
                values[f"desired.row.{rid}.value"] = (
                    "[bucket-app-dev-data1](s3.md#s3-bucket-app-dev-data1)"
                )
        if ownership_error:
            values["desired.service.codebuild.ownedCatalogResourceTypes"] = "S3.Bucket"
        write_model(path, values)
        if model_link:
            with pytest.raises(ValueError, match=REASON + "|outside service ownership"):
                markdown_for(view, values, tmp_path)
        # The same symbolic bucket is also the IaC value; equality cannot waive policy.
        template["Resources"]["Build"] = {
            "Type": "AWS::CodeBuild::Project",
            "Properties": {
                "Name": "project",
                "Artifacts": {"Type": "NO_ARTIFACTS"},
                "Environment": {
                    "Type": "LINUX_CONTAINER",
                    "ComputeType": "BUILD_GENERAL1_SMALL",
                    "Image": "image",
                    "EnvironmentVariables": [
                        {
                            "Name": "BUILD_BUCKET_NAME",
                            "Type": "PLAINTEXT",
                            "Value": {"Ref": "Bucket"},
                        }
                    ],
                },
                "ServiceRole": "role",
                "Source": {"Type": "NO_SOURCE"},
            },
        }
        write(
            tmp_path / "infra/cloudformation/templates/shared.yaml",
            json.dumps(template),
        )
        if unreadable_view:
            view.write_bytes(b"\xff")
        services = ["s3", "codebuild", "cloudformation-stacks"] + (
            ["iam"] if typed else []
        )
        previous_markers = set()
        for _iteration in range(2):
            if typed:
                artifact_path = tmp_path.parent / "scan.json"
                with patch.object(
                    sys,
                    "argv",
                    [
                        "issues",
                        "--repository-root",
                        str(tmp_path),
                        "scan",
                        "--environment",
                        "dev",
                        "--target-directory",
                        "123456789012",
                        *(
                            value
                            for service in services
                            for value in ("--service", service)
                        ),
                        "--jobs",
                        "2",
                        "--artifact",
                        str(artifact_path),
                    ],
                ):
                    status = issues_main()
                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                validate_artifact(artifact)
                assert status == scan_exit_code(artifact) != 0
            else:
                artifact = scan(tmp_path, "dev", "123456789012", services, jobs=1)
            assert any(
                item["service"] == "s3" and item["category"] == "matched"
                for item in artifact["iac"]
            )
            assert artifact["cfn_lint"]["jobs"] and all(
                job["completed"] for job in artifact["cfn_lint"]["jobs"]
            )
            assert any(
                result["scope"] == ["dev/123456789012/s3"] and result["checks"] > 0
                for result in artifact["check_results"]
            )
            if typed:
                assert any(
                    result["check_id"] == "design.service"
                    and result["scope"] == ["dev/123456789012/s3"]
                    and result["status"] == "PASS"
                    and result["complete"]
                    for result in artifact["check_results"]
                )
                links = [
                    result
                    for result in artifact["check_results"]
                    if result["check_id"] == "design.links"
                    and result["scope"] == ["dev/123456789012/codebuild"]
                ]
                if unreadable_view or markdown_link:
                    assert len(links) == 1
                    assert links[0]["status"] == "NOT_RUN" and not links[0]["complete"]
                else:
                    assert not any(result["status"] == "NOT_RUN" for result in links)
            errors = [
                item for item in artifact["ordinary"] if REASON in item["message"]
            ]
            expected = count if model_link or not unreadable_view else 0
            assert len(errors) == expected, artifact["ordinary"]
            if not expected:
                continue
            if ownership_error:
                assert any(
                    "outside service ownership" in item.get("message", "")
                    for item in [*artifact["ordinary"], *artifact["judgments"]]
                ), {
                    channel: artifact[channel]
                    for channel in ("ordinary", "judgments", "processing_errors")
                }
            else:
                assert all(
                    REASON in item["message"]
                    or item.get("diagnostic", {}).get("code")
                    == "design.display.mismatch"
                    for item in artifact["ordinary"]
                    if item["service"] == "codebuild"
                ), artifact["ordinary"]
            assert all(item["service"] == "codebuild" for item in errors)
            assert not any(
                "not selected by design catalog" in item["message"]
                or "identifier output row" in item["message"]
                for item in artifact["ordinary"]
            ), artifact["ordinary"]
            if not unreadable_view:
                dependencies = [
                    item
                    for item in artifact["unverified"]
                    if item.get("code") == "design.tables.dependency"
                ]
                if dependencies:
                    assert all(
                        item.get("resource") and item.get("checks")
                        for item in dependencies
                    )
                    assert any(
                        result["check_id"] == "design.tables.semantic"
                        and result["status"] == "NOT_RUN"
                        and not result["complete"]
                        for result in artifact["check_results"]
                    ), artifact["check_results"]
                else:
                    # A Model violation alone does not prevent valid saved-View checks.
                    assert not any(
                        item.get("code") == "mechanical.view_unverified"
                        and item.get("service") == "codebuild"
                        for item in artifact["unverified"]
                    ), artifact["unverified"]
            assert not any(
                "generated View equality" in item.get("checks", [])
                for item in artifact["unverified"]
            )
            assert any(
                result["check_id"] == "mechanical.designs"
                and result["status"] == "FAIL"
                for result in artifact["check_results"]
            ), artifact["check_results"]
            assert not any(
                REASON in str(item) for item in artifact["processing_errors"]
            ), artifact["processing_errors"]
            assert (
                typed
                or markdown_link
                or not any(
                    REASON in str(item)
                    for channel in ("warnings",)
                    for item in artifact[channel]
                )
            )
            assert not any(REASON in str(item) for item in artifact["judgments"])
            unowned = [item for item in artifact["judgments"] if "message" in item]
            diagnostics = [
                *artifact["ordinary"],
                *(
                    dict(item, service="codebuild")
                    for item in unowned
                    if item["cause_kind"] == "input_invalid"
                ),
            ]
            review = dict(
                scan_id=artifact["scan_id"],
                reviewed_naming_context_id=artifact["naming_context_id"],
                reviewed_names=[item["id"] for item in artifact["naming"]["names"]],
                reviewed_judgments=[item["id"] for item in artifact["judgments"]],
                diagnostic_assignments={
                    item["id"]: dict(
                        status="assigned",
                        service="codebuild",
                        evidence="Synthetic input Resource checked",
                    )
                    for item in unowned
                },
                issues=[],
                reviewed_confirmations=[],
                diagnostic_decisions=[
                    dict(
                        id=item["id"],
                        outcome="issue",
                        reason="Current diagnostic confirmed",
                    )
                    for item in diagnostics
                ],
                unverified=[],
            )
            with task(tmp_path, services):
                paths, snapshot, _ = save_scan(tmp_path, artifact, review)
            report = paths[0].read_text(encoding="utf-8")
            markers = set(re.findall(r"<!-- issue-id: (\S+) -->", report))
            if _iteration:
                assert markers == previous_markers
            previous_markers = markers
            assert REASON in report
            assert report.count("<!-- issue-id:") == len(diagnostics), report
            assert "### codebuild" in report


@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def test_structured_reference_display_is_rejected(mode):
    rows = [
        ["001-" + str(n), PREFIX + "[]." + field, raw, "合成"]
        for n, (field, raw) in enumerate(
            [
                ("Name", "`VALUE`"),
                ("Type", "`PLAINTEXT`"),
                ("Value", "`" + json.dumps(NODE) + "`"),
            ],
            1,
        )
    ]
    shown = display_rows("CodeBuild.Project", rows, FRAMEWORK, mode=mode)
    assert shown == [
        [rid, prop.removeprefix("CodeBuild.Project."), value, comment]
        for rid, prop, value, comment in rows
    ]
    assert "$modelRef" in shown[-1][2]
    assert REASON in str(
        codebuild_reference_errors(
            FRAMEWORK / "model/dev/team/codebuild.properties",
            values_for(
                [("VALUE", "PLAINTEXT", "`" + json.dumps(NODE) + "`")], mode=mode
            ),
        )
    )


@pytest.mark.parametrize(
    "variable_type,service,kind",
    [
        ("SECRETS_MANAGER", "secretsmanager", "SecretsManager.Secret"),
        ("PARAMETER_STORE", "ssm", "SSM.Parameter"),
    ],
)
def test_non_plaintext_model_links_pass(models, variable_type, service, kind):
    producer = {
        "desired.service." + service + ".serviceId": service,
        "desired.service." + service + ".ownedCatalogResourceTypes": kind,
        "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
        "desired.resource.001.resourceType": kind,
        "desired.resource.001.resourceMode": "IMPORT",
        "desired.resource.001.logicalId": kind.replace(".", "_") + "_001",
        "desired.resource.001.anchor": "reference",
        "desired.row.001-001.property": kind + ".Name",
        "desired.row.001-001.value": "`fixture-name`",
        "desired.row.001-001.comment": "合成",
    }
    write_model(models / f"model/dev/team/{service}.properties", producer)
    path = models / "model/dev/team/codebuild.properties"
    values = values_for(
        [("VALUE", variable_type, f"[fixture-name]({service}.md#reference)")]
    )
    write_model(path, values)
    findings = _check_model_inputs(path, values, models, definitions_root=FRAMEWORK)
    assert not findings.errors, findings.errors


if __name__ == "__main__":
    raise SystemExit(run(__file__, message="CodeBuild PLAINTEXT unit checks passed"))
