"""S3 scalar Key/Arn intent across authority, display and local IaC comparison."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import model.validations.full_inputs as _model_validation_full_inputs
from comparison import Comparison
from design.catalog import DesignSchemaCatalog
from design.document import DesignIndex
from design.services import kms
from generation_inputs import GenerationInputs
from model.core import ModelNeedsFixError, entries
from model.format import parse, serialize
from model.format import patch as patch_model
from model.identity import COUNTERS, Resolver
from model.importing.references import Resolver as ImportResolver
from model.operations import validate_candidates
from model.projection import (
    document_references,
    generated_document,
    reference_display,
    reference_resolver,
)
from model.reference_nodes import parse as parse_reference
from model.reference_presentation import Position, Presentation
from model.reference_values import reference_value
from model.references import diagnose, incoming, kms_observation
from model.render import generate_markdown
from model.sources import Scope, load_model
from support.model_reference_fixtures import reference
from support.model_sources import catalog_display, write_model
from sync_runtime import _compare_generation
from utils.reference_contracts import S3_KMS_MASTER_KEY_ID as PROP
from utils.reference_contracts import contract
from utils.source_reads import FileReads
from validation.design_links import check_design_links as validate_links
from validation.design_tables import check_design_tables as validate_tables
from validation.diagnostics import ArtifactReferences
from validation.findings import Findings

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

FRAMEWORK = Path(__file__).resolve().parents[4]
KEY_LINK = "[fixture-key](kms.md#key-one)"
ALIAS_LINK = (
    "[arn:aws:kms:ap-northeast-1:123456789012:alias/fixture-key](kms.md#alias-one)"
)
ROW = "desired.row.001-003.value"


def fixture(root):
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "synthetic",
                "targets": [
                    {
                        "environment": "fixture",
                        "alias": "team",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    kms = {
        COUNTERS: '{"KMS.Key":2,"KMS.Alias":1}',
        "desired.service.kms.serviceId": "kms",
        "desired.service.kms.ownedCatalogResourceTypes": "KMS.Key,KMS.Alias",
        "display.service.title": "# 合成KMS",
    }
    for rid, kind, logical, anchor in [
        ("001", "KMS.Key", "KMS_Key_001", "key-one"),
        ("002", "KMS.Alias", "KMS_Alias_001", "alias-one"),
        ("003", "KMS.Key", "KMS_Key_002", "key-two"),
    ]:
        kms.update(
            {
                f"desired.resource.{rid}.resourceType": kind,
                f"desired.resource.{rid}.logicalId": logical,
                f"desired.resource.{rid}.anchor": anchor,
                f"desired.resource.{rid}.resourceMode": "IMPORT",
                f"display.resource.{rid}.comment": "合成リソース",
            }
        )
    kms.update(
        {
            "desired.resource.002.parentReference": "`"
            + json.dumps(reference("KMS_Key_001", "KeyId"))
            + "`",
            "desired.resource.002.parentProperty": "KMS.Alias.TargetKeyId",
            "display.resource.003.label": "other-key",
        }
    )
    for rid, prop, value in [
        (
            "001-001",
            "KMS.Key.KeyId",
            "`" + json.dumps(reference("KMS_Key_001", "KeyId")) + "`",
        ),
        ("002-001", "KMS.Alias.AliasName", "`alias/fixture-key`"),
        (
            "003-001",
            "KMS.Key.KeyId",
            "`" + json.dumps(reference("KMS_Key_002", "KeyId")) + "`",
        ),
    ]:
        kms.update(
            {
                f"desired.row.{rid}.property": prop,
                f"desired.row.{rid}.value": value,
                f"desired.row.{rid}.comment": "合成設定",
            }
        )
    kms["observed.row.001-001.value"] = "`12345678-1234-1234-1234-123456789abc`"
    kms["observed.row.003-001.value"] = "`87654321-1234-1234-1234-123456789abc`"
    bucket = {
        COUNTERS: '{"S3.Bucket":1}',
        "desired.service.s3.serviceId": "s3",
        "desired.service.s3.ownedCatalogResourceTypes": "S3.Bucket",
        "display.service.title": "# 合成S3",
        "desired.resource.001.resourceType": "S3.Bucket",
        "desired.resource.001.logicalId": "S3_Bucket_001",
        "desired.resource.001.anchor": "bucket",
        "desired.resource.001.resourceMode": "IMPORT",
        "display.resource.001.comment": "合成バケット",
    }
    for rid, prop, value in [
        ("001-001", "S3.Bucket.BucketName", "`fixture-bucket`"),
        ("001-002", "S3.Bucket.Region", "`ap-northeast-1`"),
        ("001-003", PROP, "`" + json.dumps(reference("KMS_Alias_001", "Arn")) + "`"),
        ("001-004", PROP.rsplit(".", 1)[0] + ".SSEAlgorithm", "`aws:kms`"),
    ]:
        bucket.update(
            {
                f"desired.row.{rid}.property": prop,
                f"desired.row.{rid}.value": value,
                f"desired.row.{rid}.comment": "合成設定",
            }
        )
    for service, values in [("kms", kms), ("s3", bucket)]:
        write_model(Scope(root, "fixture", "team", service).path, values)
    return Scope(root, "fixture", "team", "s3"), bucket, kms


def designs(scope, bucket, kms):
    root = scope.root
    result = {}
    with catalog_display():
        for service, values in [("kms", kms), ("s3", bucket)]:
            path = root / "docs/designs/fixture/team" / (service + ".md")
            path.parent.mkdir(parents=True, exist_ok=True)
            result[path] = generate_markdown(path, values, FRAMEWORK)
            path.write_text(result[path], encoding="utf-8")
    return result


def check_authority_display_and_references(project_workspace):
    scope, bucket, kms = fixture(project_workspace)
    before = {p: p.read_bytes() for p in scope.path.parent.glob("*.properties")}
    snapshot = load_model(scope)
    assert snapshot.authoritative == bucket
    # Exercise the normal lossless source patch/save/reload representation.
    scope.path.write_text(
        patch_model(parse(serialize(bucket)), {ROW: bucket[ROW]}), encoding="utf-8"
    )
    assert load_model(scope, FileReads()).authoritative[ROW] == bucket[ROW]
    check_model_inputs = _model_validation_full_inputs.check_model_inputs
    schema = check_model_inputs(
        scope.path, bucket, scope.root, definitions_root=FRAMEWORK
    )
    assert not schema.errors, schema.errors
    dependency_index.rebuild(scope.root)
    uses = incoming(load_model(Scope(scope.root, "fixture", "team", "kms")), "002")
    assert any(
        consumer == scope and usage.consumer_key == ROW and usage.pointer == ""
        for consumer, usage in uses
    )
    validate_candidates(
        scope.root,
        {"model/fixture/team/s3.properties"},
        {
            scope.path: serialize(
                {**bucket, ROW: "`" + json.dumps(reference("KMS_Key_001", "Arn")) + "`"}
            )
        },
        {("fixture", "team", "s3")},
    )
    with patch(
        "botocore.session.Session.create_client",
        side_effect=AssertionError("AWS forbidden"),
    ):
        displayed = reference_display(bucket, scope.path, scope.root)
        files = designs(scope, bucket, kms)
    view = scope.root / "docs/designs/fixture/team/s3.md"
    expected = "[未観測](kms.md#alias-one)"
    assert expected in files[view] and "$resource" not in files[view]
    TestCase().assertNotIn("$modelRef", displayed[ROW])
    TestCase().assertEqual(bucket[ROW], snapshot.authoritative[ROW])
    findings = Findings(scope.root)
    validate_links(
        {},
        [view],
        design_sources={view: bucket},
        findings=findings,
        root=scope.root,
        scope=None,
        definitions_root=FRAMEWORK,
    )
    assert not findings.errors and not findings.warnings, (
        findings.errors,
        findings.warnings,
    )
    imported = ImportResolver(scope.root, "fixture", "team", definitions_root=FRAMEWORK)
    imported.verify_resource(bucket, "001", scope=scope, observed_only=True)
    assert not imported.warnings, imported.warnings
    catalog = DesignSchemaCatalog(FRAMEWORK)
    with catalog_display():
        validate_tables(
            {view: ("s3", ("S3.Bucket",))},
            {"S3.Bucket"},
            {
                row["property"]: {"S3.Bucket"}
                for _, row in entries(bucket, "desired.row.")
            },
            {},
            [view],
            design_sources={view: bucket},
            findings=findings,
            markdown_design_artifacts=ArtifactReferences(),
            markdown_iam_policy_artifacts=set(),
            root=scope.root,
            schema_catalog=catalog,
            scope=None,
            definitions_root=FRAMEWORK,
        )
    assert not findings.errors and not findings.warnings, (
        findings.errors,
        findings.warnings,
    )
    assert all(
        p.read_bytes() == raw and b"arn:" not in raw for p, raw in before.items()
    )

    plan = SimpleNamespace(
        root=scope.root,
        snapshot=GenerationInputs(scope.root, read_only=True),
        expected_outputs={view: {view: files[view]}},
        failure_records=[],
        saved={},
    )
    _compare_generation(plan)
    assert not plan.failure_records and view in plan.saved


def check_iac_matrix(project_workspace):
    actual = {"Ref": "Alias"}
    scope, bucket, kms = fixture(project_workspace)
    for service, values, mappings in [
        ("s3", bucket, {"001": "Bucket"}),
        ("kms", kms, {"001": "Key", "002": "Alias", "003": "OtherKey"}),
    ]:
        for rid, logical in mappings.items():
            values[f"desired.resource.{rid}.resourceMode"] = "CREATE"
            values[f"desired.resource.{rid}.cfn-logicalId"] = "fixture-" + logical
        write_model(Scope(scope.root, "fixture", "team", service).path, values)
    stack = {
        "desired.stack.001.name": "fixture",
        "desired.stack.001.placementName": "fixture",
        "desired.stack.001.template": "fixture.yaml",
        "desired.stack.001.parameters": "fixture.json",
        "desired.stack.001.deployOrder": "1",
    }
    write_model(
        Scope(scope.root, "fixture", "team", "cloudformation-stacks").path, stack
    )
    template = scope.root / "infra/cloudformation/templates/team/fixture.yaml"
    template.parent.mkdir(parents=True)
    template.write_text(
        json.dumps(
            {
                "Resources": {
                    "Key": {"Type": "AWS::KMS::Key"},
                    "OtherKey": {"Type": "AWS::KMS::Key"},
                    "Alias": {
                        "Type": "AWS::KMS::Alias",
                        "Properties": {
                            "AliasName": "alias/fixture-key",
                            "TargetKeyId": {"Ref": "Key"},
                        },
                    },
                    "Bucket": {
                        "Type": "AWS::S3::Bucket",
                        "Properties": {
                            "BucketName": "fixture-bucket",
                            "BucketEncryption": {
                                "ServerSideEncryptionConfiguration": [
                                    {
                                        "ServerSideEncryptionByDefault": {
                                            "SSEAlgorithm": "aws:kms",
                                            "KMSMasterKeyID": actual,
                                        }
                                    }
                                ]
                            },
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    parameters = (
        scope.root / "infra/cloudformation/parameters/fixture/team/fixture.json"
    )
    parameters.parent.mkdir(parents=True)
    parameters.write_text("[]", encoding="utf-8")
    comparison = Comparison(
        scope.root, "fixture", "team", ["s3"], catalog=DesignSchemaCatalog(FRAMEWORK)
    )
    results = comparison.run()
    encryption = [
        item for item in results if item["property"] == "S3.Bucket.BucketEncryption"
    ]
    assert len(encryption) == 1 and encryption[0]["category"] == "matched", results

    bucket[ROW] = json.dumps(
        {"$modelRef": {"logicalId": "KMS_Alias_001", "attribute": "AliasName"}}
    )
    write_model(scope.path, bucket)
    comparison = Comparison(
        scope.root, "fixture", "team", ["s3"], catalog=DesignSchemaCatalog(FRAMEWORK)
    )
    results = comparison.run()
    encryption = [
        item for item in results if item["property"] == "S3.Bucket.BucketEncryption"
    ]
    assert len(encryption) == 1 and encryption[0]["category"] == "matched", results
    plain = comparison.desired_reference(
        "s3",
        reference("KMS_Key_001", "KeyId"),
        "S3.Bucket",
        PROP.removeprefix("S3.Bucket."),
        attribute="KeyId",
    )
    assert plain["$attribute"] == "KeyId"
    assert (
        comparison.reference_same(
            plain,
            comparison.evaluate("fixture", {"Fn::GetAtt": ["Key", "Arn"]}),
            "S3.Bucket",
            PROP.removeprefix("S3.Bucket."),
        )
        is True
    )
    alias = comparison.desired_reference(
        "s3",
        reference("KMS_Alias_001", "AliasName"),
        "S3.Bucket",
        PROP.removeprefix("S3.Bucket."),
        attribute="AliasName",
    )
    assert (
        comparison.reference_same(
            alias,
            comparison.evaluate("fixture", {"Ref": "Alias"}),
            "S3.Bucket",
            PROP.removeprefix("S3.Bucket."),
        )
        is True
    )
    assert "arn:" not in scope.path.read_text(encoding="utf-8")


def check_bucket_policy_kms_condition_contract():
    base = "S3.BucketPolicy.PolicyDocument.Statement"
    case = TestCase()
    for statement in ("", "[]"):
        for values in ("", "[]"):
            field = (
                base
                + statement
                + ".Condition.StringNotEquals.s3:x-amz-server-side-encryption-aws-kms-key-id"
                + values
            )
            case.assertEqual(contract(field), {"KMS.Key": ("Arn",)})
    case.assertEqual(
        contract(
            base
            + ".Condition.StringEquals.s3:x-amz-server-side-encryption-aws-kms-key-id"
        ),
        {},
    )


def check_bucket_policy_kms_reference_types(project_workspace):
    scope, _, _ = fixture(project_workspace)
    resolver = Resolver(scope.root)
    case = TestCase()
    field = (
        "S3.BucketPolicy.PolicyDocument.Statement[].Condition.StringNotEquals."
        "s3:x-amz-server-side-encryption-aws-kms-key-id"
    )
    resolver.validate_attribute("KMS.Key", "Arn", field=field)
    with case.assertRaises(ModelNeedsFixError):
        resolver.validate_attribute("KMS.Key", "KeyId", field=field)
    with case.assertRaises(ModelNeedsFixError):
        resolver.validate_attribute("S3.Bucket", "Arn", field=field)
    with case.assertRaises(ModelNeedsFixError):
        resolver.validate_attribute("KMS.Key", "Missing", field=field)


def check_kms_consumers_obey_attribute_contracts(project_workspace):
    scope, _, _ = fixture(project_workspace)
    resolver = Resolver(scope.root)
    case = TestCase()
    fields = (
        "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey",
        "MWAA.Environment.KmsKey",
        PROP,
    )
    for field in fields:
        resolver.validate_attribute("KMS.Key", "Arn", field=field)
        with case.assertRaises(ModelNeedsFixError):
            resolver.validate_attribute("S3.Bucket", "Arn", field=field)
    with case.assertRaises(ModelNeedsFixError):
        resolver.validate_attribute("KMS.Key", "KeyId", field=fields[0])
    for field in fields[1:]:
        resolver.validate_attribute("KMS.Key", "KeyId", field=field)


def logs_fixture(root, observed, logical="KMS_Alias_001", attribute="Arn"):
    scope, _, kms = fixture(root)
    logs = {
        COUNTERS: '{"Logs.LogGroup":1}',
        "desired.service.cloudwatch-logs.serviceId": "cloudwatch-logs",
        "desired.service.cloudwatch-logs.ownedCatalogResourceTypes": "Logs.LogGroup",
        "display.service.title": "# 合成ログ",
        "desired.resource.001.resourceType": "Logs.LogGroup",
        "desired.resource.001.logicalId": "Logs_LogGroup_001",
        "desired.resource.001.anchor": "log-group",
        "desired.resource.001.resourceMode": "IMPORT",
        "display.resource.001.comment": "合成ログ",
        "desired.row.001-001.property": "Logs.LogGroup.LogGroupName",
        "desired.row.001-001.value": "`fixture-logs`",
        "desired.row.001-001.comment": "名前",
        "desired.row.001-002.property": "Logs.LogGroup.KmsKeyId",
        "desired.row.001-002.value": "`"
        + json.dumps(reference(logical, attribute))
        + "`",
        "desired.row.001-002.comment": "暗号化キー",
    }
    if observed is not None:
        logs["observed.row.001-002.value"] = "`" + observed + "`"
    logs_scope = Scope(root, "fixture", "team", "cloudwatch-logs")
    write_model(logs_scope.path, logs)
    dependency_index.rebuild(root)
    return logs_scope, logs, kms


@pytest.mark.parametrize(
    "observed,label,warning",
    [
        (
            "12345678-1234-1234-1234-123456789abc",
            "12345678-1234-1234-1234-123456789abc",
            None,
        ),
        (
            "87654321-1234-1234-1234-123456789abc",
            "87654321-1234-1234-1234-123456789abc",
            "reference.mismatch",
        ),
        ("PENDING_DEPLOY", "PENDING_DEPLOY", None),
        (None, "未観測", None),
    ],
)
def check_logs_observed_kms_key_id_label(project_workspace, observed, label, warning):
    scope, logs, _ = logs_fixture(project_workspace, observed)
    path = scope.root / "docs/designs/fixture/team/cloudwatch-logs.md"
    presentation = Presentation(logs, path, scope.root)
    link = presentation.references[Position("001-002", "value", "")].link
    assert link == f"[{label}](kms.md#alias-one)"
    diagnostics, _ = diagnose(load_model(scope))
    relevant = [
        d for d in diagnostics if d.get("consumerKey") == "desired.row.001-002.value"
    ]
    assert [d["code"] for d in relevant] == ([warning] if warning else [])


def check_logs_kms_key_identity_unproven(project_workspace):
    observed = "12345678-1234-1234-1234-123456789abc"
    scope, logs, kms = logs_fixture(project_workspace, observed)
    kms.pop("observed.row.001-001.value")
    write_model(Scope(scope.root, "fixture", "team", "kms").path, kms)
    path = scope.root / "docs/designs/fixture/team/cloudwatch-logs.md"
    link = (
        Presentation(logs, path, scope.root)
        .references[Position("001-002", "value", "")]
        .link
    )
    assert link == f"[未確認: {observed}](kms.md#alias-one)"
    diagnostics, _ = diagnose(load_model(scope))
    assert any(
        d["code"] == "reference.unresolved"
        and d.get("consumerKey") == "desired.row.001-002.value"
        for d in diagnostics
    )


@pytest.mark.parametrize(
    "logical,anchor", [("KMS_Key_001", "key-one"), ("KMS_Alias_001", "alias-one")]
)
def check_logs_kms_key_reference_roundtrip(project_workspace, logical, anchor):
    observed = "12345678-1234-1234-1234-123456789abc"
    scope, logs, _ = logs_fixture(project_workspace, observed, logical, "Arn")
    original = {p: p.read_bytes() for p in scope.path.parent.glob("*.properties")}
    path = scope.root / "docs/designs/fixture/team/cloudwatch-logs.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with catalog_display():
        markdown = generate_markdown(path, logs, FRAMEWORK)
        assert f"[{observed}](kms.md#{anchor})" in markdown
        restored = DesignIndex(FRAMEWORK).get(path, text=markdown, values=logs)
        assert "Logs.LogGroup.KmsKeyId" in "\n".join(restored.raw.display_lines)
        assert (
            generate_markdown(path, load_model(scope).authoritative, FRAMEWORK)
            == markdown
        )
    assert {
        p: p.read_bytes() for p in scope.path.parent.glob("*.properties")
    } == original
    node = parse_reference(reference(logical, "Arn"))
    resolver = reference_resolver(logs, scope, scope.root)
    execution = generated_document(
        reference(logical, "Arn"),
        scope.root,
        resolver=resolver,
        scope=scope,
        property_name="Logs.LogGroup.KmsKeyId",
    )
    assert execution.startswith("arn:aws:kms:")
    assert (
        observed not in execution
        if logical == "KMS_Alias_001"
        else observed in execution
    )
    assert (
        reference_value(resolver, scope, node, field="Logs.LogGroup.KmsKeyId").value
        == execution
    )
    assert (
        Presentation(logs, path, scope.root)
        .references[Position("001-002", "value", "")]
        .link
        == f"[{observed}](kms.md#{anchor})"
    )


def check_kms_alias_name_and_multiple_aliases(project_workspace):
    scope, bucket, kms = fixture(project_workspace)
    bucket[ROW] = "`" + json.dumps(reference("KMS_Alias_001", "AliasName")) + "`"
    bucket["observed.row.001-003.value"] = "`12345678-1234-1234-1234-123456789abc`"
    path = scope.root / "docs/designs/fixture/team/s3.md"
    assert (
        Presentation(bucket, path, scope.root)
        .references[Position("001-003", "value", "")]
        .link
        == "[alias/fixture-key](kms.md#alias-one)"
    )
    kms[COUNTERS] = '{"KMS.Key":2,"KMS.Alias":2}'
    for key, value in list(kms.items()):
        if key.startswith("desired.resource.002."):
            kms[key.replace(".002.", ".004.")] = value
    kms["desired.resource.004.logicalId"] = "KMS_Alias_002"
    kms["desired.resource.004.anchor"] = "alias-two"
    kms["desired.row.004-001.property"] = "KMS.Alias.AliasName"
    kms["desired.row.004-001.value"] = "`alias/second-key`"
    kms["desired.row.004-001.comment"] = "別名"
    write_model(Scope(scope.root, "fixture", "team", "kms").path, kms)
    logs_scope, logs, _ = logs_fixture(
        project_workspace,
        "12345678-1234-1234-1234-123456789abc",
        "KMS_Alias_002",
    )
    write_model(Scope(logs_scope.root, "fixture", "team", "kms").path, kms)
    dependency_index.rebuild(logs_scope.root)
    path = logs_scope.root / "docs/designs/fixture/team/cloudwatch-logs.md"
    assert (
        Presentation(logs, path, logs_scope.root)
        .references[Position("001-002", "value", "")]
        .link
        == "[12345678-1234-1234-1234-123456789abc](kms.md#alias-two)"
    )


@pytest.mark.parametrize(
    "state,observed,expected",
    [
        ("match", "key-id", "key-id"),
        ("mismatch", "key-id", "key-id"),
        ("unproven", "key-id", "未確認: key-id"),
        ("pending", "PENDING_DEPLOY", "PENDING_DEPLOY"),
        ("unobserved", None, "未観測"),
    ],
)
def check_kms_service_reference_label(state, observed, expected):
    position = Position("001-002", "value", "")
    values = {"desired.row.001-002.value": "`" + json.dumps(reference()) + "`"}
    with patch.object(
        kms.references, "kms_observation", return_value=(state, observed)
    ):
        assert (
            kms.reference_label(
                values,
                position,
                object(),
                None,
                None,
                {"resourceType": "KMS.Key"},
                "Arn",
                "key-name",
                "resolved-arn",
            )
            == expected
        )


def check_kms_observation_not_applied_inside_document(project_workspace):
    scope, logs, _ = logs_fixture(
        project_workspace, "12345678-1234-1234-1234-123456789abc"
    )
    path = scope.root / "docs/designs/fixture/team/cloudwatch-logs.md"
    resolver = Presentation(logs, path, scope.root).resolver
    node = parse_reference(reference("KMS_Alias_001", "Arn"), "/0")
    assert kms_observation(logs, "001-002", node, scope, resolver) is None


def check_kms_alias_missing_parent_is_unproven(project_workspace):
    observed = "12345678-1234-1234-1234-123456789abc"
    scope, logs, kms = logs_fixture(project_workspace, observed)
    del kms["desired.resource.002.parentReference"]
    write_model(Scope(scope.root, "fixture", "team", "kms").path, kms)
    path = scope.root / "docs/designs/fixture/team/cloudwatch-logs.md"
    assert (
        Presentation(logs, path, scope.root)
        .references[Position("001-002", "value", "")]
        .link
        == f"[未確認: {observed}](kms.md#alias-one)"
    )
    diagnostics, _ = diagnose(load_model(scope))
    assert any(d["code"] == "reference.unresolved" for d in diagnostics)


@pytest.mark.parametrize("fault", ["target", "attribute", "anchor"])
def check_logs_invalid_kms_reference_remains_invalid(project_workspace, fault):
    logical = "KMS_Missing_001" if fault == "target" else "KMS_Alias_001"
    attribute = "Missing" if fault == "attribute" else "Arn"
    scope, logs, kms = logs_fixture(
        project_workspace, "12345678-1234-1234-1234-123456789abc", logical, attribute
    )
    if fault == "anchor":
        kms["desired.resource.002.anchor"] = "invalid anchor"
        write_model(Scope(scope.root, "fixture", "team", "kms").path, kms)
    path = scope.root / "docs/designs/fixture/team/cloudwatch-logs.md"
    presentation = Presentation(logs, path, scope.root)
    assert presentation.references[Position("001-002", "value", "")].link is None
    if fault != "anchor":
        _, diagnostics = document_references(
            reference(logical, attribute),
            resolver=presentation.resolver,
            scope=scope,
            property_name="Logs.LogGroup.KmsKeyId",
        )
        assert diagnostics


def check_alias_execution_projection_stays_arn(project_workspace):
    scope, logs, _ = logs_fixture(
        project_workspace, "12345678-1234-1234-1234-123456789abc"
    )
    resolver = reference_resolver(logs, scope, scope.root)
    raw = reference("KMS_Alias_001", "Arn")
    expected = reference_value(
        resolver, scope, parse_reference(raw), field="Logs.LogGroup.KmsKeyId"
    ).value
    actual = generated_document(
        raw,
        scope.root,
        resolver=resolver,
        scope=scope,
        property_name="Logs.LogGroup.KmsKeyId",
    )
    assert actual == expected and actual.startswith("arn:") and "fixture-key" in actual


def check_kms_self_identifier_is_plain_text(project_workspace):
    scope, _, kms = fixture(project_workspace)
    path = scope.root / "docs/designs/fixture/team/kms.md"
    with catalog_display():
        markdown = generate_markdown(path, kms, FRAMEWORK)
    observed = "12345678-1234-1234-1234-123456789abc"
    assert "`" + observed + "`" in markdown
    assert "[" + observed + "](#key-one)" not in markdown


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__, message="S3 KMS scalar reference contracts: PASS"))
