#!/usr/bin/env python3
"""Check grouped identities, references and catalog display coverage end to end."""

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

from design_layout import LAYOUTS, expanded_design, expanded_display_rows, layout_errors
from policy_tables import resources_in


REPOSITORY = Path(__file__).resolve().parents[2]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_script("validate-blueprint")
MODEL = load_script("sync-model")
KMS = """# KMS 詳細設計

- Design service ID: `kms`
- Owned catalog resource types: `KMS.Key`, `KMS.Alias`

## リソース一覧

### KMS.Key

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [KeyOne](#kms-keyone) | データの暗号化に使うkey |
| 2 | [KeyTwo](#kms-keytwo) | データの暗号化に使うkey |

## リソース詳細

<a id="kms-keyone"></a>

### KMS.Key: KeyOne

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | `1234abcd-12ab-34cd-56ef-1234567890ab` | KMS keyを識別するID |
| 2 | EnableKeyRotation | `true` | key materialの自動rotationを有効にする設定 |
| 3 | KMS.Alias.AliasName | `alias/one` | <a id="kms-aliasone"></a><!-- logical-id: AliasOne --> KMS keyを識別するalias |
| 4 | KMS.Alias.AliasName | `alias/two` | <a id="kms-aliastwo"></a><!-- logical-id: AliasTwo --> KMS keyを識別するalias |

<a id="kms-keytwo"></a>

### KMS.Key: KeyTwo

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | `PENDING_DEPLOY` | KMS keyを識別するID |
| 2 | KMS.Alias.AliasName | `alias/three` | <a id="kms-aliasthree"></a><!-- logical-id: AliasThree --> KMS keyを識別するalias |
"""
S3 = """# S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`

## リソース一覧

### S3.Bucket

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-data](#s3-app-data) | アプリケーションのデータを保管するbucket |

## リソース詳細

<a id="s3-app-data"></a>

### S3.Bucket: app-data

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | `app-data` | bucketの名前 |
| 2 | Region | `us-east-1` | bucketを配置するregion |
| 3 | BucketEncryption[].KMSMasterKeyID | [alias/two](kms.md#kms-aliastwo) | 暗号化に使用するKMS alias |
| 4 | BucketEncryption[].SSEAlgorithm | `aws:kms` | 暗号化方式 |
"""
CODEBUILD = """# CodeBuild 詳細設計

- Design service ID: `codebuild`
- Owned catalog resource types: `CodeBuild.Project`

## リソース詳細

<a id="codebuild-buildproject"></a>

### CodeBuild.Project: BuildProject

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `build-project` | projectの名前 |
| 2 | Id | `PENDING_DEPLOY` | projectのID |
| 3 | Artifacts.Type | `NO_ARTIFACTS` | artifactの種類 |
| 4 | Environment.ComputeType | `BUILD_GENERAL1_SMALL` | 実行環境の容量 |
| 5 | Environment.Variables.FIRST | `PLAINTEXT:hello:world` | 環境変数の値 |
| 6 | Environment.Variables.SECOND | `PARAMETER_STORE:/app/token` | 環境変数の参照先 |
| 7 | Environment.Image | `aws/codebuild/standard:7.0` | 実行環境のimage |
| 8 | Environment.Type | `LINUX_CONTAINER` | 実行環境の種類 |
| 9 | ServiceRole | `role-name` | 使用するrole |
| 10 | Source.Type | `NO_SOURCE` | sourceの種類 |
"""
GUARDDUTY = """# GuardDuty 詳細設計

- Design service ID: `guardduty`
- Owned catalog resource types: `GuardDuty.Detector`

## リソース詳細

<a id="guardduty-main"></a>

### GuardDuty.Detector: Main

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | `PENDING_DEPLOY` | detectorのID |
| 2 | Enable | `true` | detectorを有効化する設定 |
| 3 | Features.S3_DATA_EVENTS | `ENABLED` | S3の監視 |
| 4 | Features.EKS_AUDIT_LOGS | `DISABLED` | EKSの監視 |
"""


def check_codebuild_variable_display() -> None:
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/codebuild.md"
        path.parent.mkdir(parents=True)

        def errors(content: str) -> list[str]:
            path.write_text(content, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables({path: ("codebuild", ("CodeBuild.Project",))}, *catalog)
            return validator.errors

        assert not errors(CODEBUILD), errors(CODEBUILD)
        model = MODEL.model_for(path, REPOSITORY)
        assert "desired.row.001-005.property=CodeBuild.Project.Environment.EnvironmentVariables[].Name" in model
        assert "desired.row.001-005.value=`FIRST`" in model
        assert "desired.row.001-006.property=CodeBuild.Project.Environment.EnvironmentVariables[].Type" in model
        assert "desired.row.001-007.value=`hello:world`" in model
        assert "desired.row.001-008.value=`SECOND`" in model
        assert "Environment.Variables." not in model
        short = CODEBUILD
        assert "| Artifacts.Type |" in short
        assert not errors(short), errors(short)
        assert MODEL.model_for(path, REPOSITORY) == model
        assert any("must omit heading resource type" in error for error in errors(short.replace("| 2 | Id |", "| 2 | CodeBuild.Project.Id |")))
        assert errors(short.replace("Artifacts.Type", "Artifacts.Unknown"))
        assert errors(CODEBUILD.replace("Variables.SECOND", "Variables.FIRST"))
        assert errors(CODEBUILD.replace("PLAINTEXT:hello:world", "hello"))
        assert errors(CODEBUILD.replace("Variables.FIRST | `PLAINTEXT:hello:world`", "EnvironmentVariables[].Name | `FIRST`"))


def check_guardduty_feature_display() -> None:
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/guardduty.md"
        path.parent.mkdir(parents=True)

        def errors(content: str) -> list[str]:
            path.write_text(content, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables({path: ("guardduty", ("GuardDuty.Detector",))}, *catalog)
            return validator.errors

        assert not errors(GUARDDUTY), errors(GUARDDUTY)
        model = MODEL.model_for(path, REPOSITORY)
        assert "desired.row.001-003.property=GuardDuty.Detector.Features[].Name" in model
        assert "desired.row.001-003.value=`S3_DATA_EVENTS`" in model
        assert "desired.row.001-004.property=GuardDuty.Detector.Features[].Status" in model
        assert "desired.row.001-004.value=`ENABLED`" in model
        assert "desired.row.001-005.value=`EKS_AUDIT_LOGS`" in model
        assert "Features.S3_DATA_EVENTS" not in model
        short = GUARDDUTY.replace("| GuardDuty.Detector.", "| ")
        assert not errors(short), errors(short)
        assert MODEL.model_for(path, REPOSITORY) == model
        assert errors(GUARDDUTY.replace("Features.EKS_AUDIT_LOGS", "Features.S3_DATA_EVENTS"))
        assert errors(GUARDDUTY.replace("`ENABLED`", "`INVALID`"))
        assert errors(GUARDDUTY.replace("Features.S3_DATA_EVENTS | `ENABLED`", "Features[].Name | `S3_DATA_EVENTS`"))



def check_cloudtrail_data_resources() -> None:
    trail = """# AWS CloudTrail 詳細設計

- Design service ID: `cloudtrail`
- Owned catalog resource types: `CloudTrail.Trail`

## リソース詳細

<a id="cloudtrail-trail"></a>

### CloudTrail.Trail: Trail

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | TrailName | `trail` | 証跡の名前 |
| 2 | EventSelectors.DataResources[1].S3 | [data-bucket](s3.md#s3-data-bucket) | S3 objectの記録対象 |
| 3 | EventSelectors.DataResources[2].Lambda | [function-one](lambda.md#lambda-function-one) | Lambda functionの記録対象 |
| 4 | IsLogging | `true` | event記録の有効化 |
| 5 | S3BucketName | [data-bucket](s3.md#s3-data-bucket) | ログの配信先bucket |
"""
    s3 = """# Amazon S3 詳細設計

<a id="s3-data-bucket"></a>

### S3.Bucket: data-bucket

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | `data-bucket` | bucketの名前 |
| 2 | Region | `ap-northeast-1` | bucketの配置region |
"""
    lambda_design = """# AWS Lambda 詳細設計

<a id="lambda-function-one"></a>

### Lambda.Function: function-one

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | FunctionName | `function-one` | functionの名前 |
| 2 | Role | `arn:aws:iam::123456789012:role/function-one` | 実行用role |
"""
    expanded = "\n".join(expanded_display_rows(trail.splitlines()))
    assert expanded.count("CloudTrail.Trail.EventSelectors[].DataResources[].Type") == 2
    assert "`AWS::S3::Object`" in expanded and "`AWS::Lambda::Function`" in expanded
    assert expanded.count("CloudTrail.Trail.EventSelectors[].DataResources[].Values") == 2
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        design = root / "docs/designs/dev/123456789012"
        design.mkdir(parents=True)
        path = design / "cloudtrail.md"
        path.write_text(trail, encoding="utf-8")
        (design / "s3.md").write_text(s3, encoding="utf-8")
        (design / "lambda.md").write_text(lambda_design, encoding="utf-8")
        model = MODEL.model_for(path, REPOSITORY)
        assert "desired.row.001-002.property=CloudTrail.Trail.EventSelectors[].DataResources[].Type" in model
        assert "desired.row.001-003.value=[data-bucket](s3.md#s3-data-bucket)" in model
        assert "desired.row.001-004.value=`AWS::Lambda::Function`" in model
        assert "DataResources[1]" not in model
        catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()

        def errors(content: str) -> list[str]:
            path.write_text(content, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables({path: ("cloudtrail", ("CloudTrail.Trail",))}, *catalog)
            validator.check_design_links(catalog[2])
            return validator.errors

        assert not errors(trail), errors(trail)
        for bad in (
            trail.replace("DataResources[1]", "DataResources[0]"),
            trail.replace("DataResources[2]", "DataResources[3]"),
            trail.replace("DataResources[2]", "DataResources[1]"),
            trail.replace("DataResources[1].S3", "DataResources[1].Object"),
            trail.replace("[data-bucket](s3.md#s3-data-bucket) | S3 object", "`data-bucket` | S3 object"),
            trail.replace("DataResources[1].S3", "EventSelectors[].DataResources[].Type"),
            trail.replace("[data-bucket](s3.md#s3-data-bucket) | S3 object", "[function-one](lambda.md#lambda-function-one) | S3 object"),
        ):
            assert errors(bad), bad


def main() -> None:
    assert not layout_errors(REPOSITORY)
    policy_rows = [
        '<a id="iam-role"></a>', '### IAM.Role: Role',
        '| No. | Property | Value | Source / Comment |',
        '| ---: | --- | --- | --- |',
        '| 1 | RoleName | `role` | roleの名前 |',
        '| 2 | AssumeRolePolicyDocument | [trust](trust.json) | 信頼policy |',
    ]
    assert resources_in(policy_rows)[0].policies[0].property_name == "IAM.Role.AssumeRolePolicyDocument"
    check_codebuild_variable_display()
    check_guardduty_feature_display()
    check_cloudtrail_data_resources()
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        kms = root / "docs/designs/dev/123456789012/kms.md"
        kms.parent.mkdir(parents=True)
        s3 = kms.with_name("s3.md")
        metadata = {kms: ("kms", ("KMS.Key", "KMS.Alias")), s3: ("s3", ("S3.Bucket",))}

        def errors(kms_text=KMS, s3_text=S3):
            kms.write_text(kms_text, encoding="utf-8")
            s3.write_text(s3_text, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables(metadata, *catalog)
            validator.check_design_overviews()
            validator.check_design_links(catalog[2])
            return validator.errors

        assert not errors(), errors()
        original = kms.read_bytes()
        model = MODEL.model_for(kms, REPOSITORY)
        assert kms.read_bytes() == original
        assert "desired.resource.002.resourceType=KMS.Alias" in model
        assert "desired.resource.002.logicalId=AliasOne" in model
        assert "desired.resource.003.logicalId=AliasTwo" in model
        assert "desired.resource.003.anchor=kms-aliastwo" in model
        assert "desired.resource.003.parentProperty=KMS.Alias.TargetKeyId" in model
        assert "desired.resource.003.parentReference=[KeyOne](#kms-keyone)" in model
        assert "desired.resource.005.parentReference=[KeyTwo](#kms-keytwo)" in model
        assert "desired.row.003-001.value=`alias/two`" in model
        assert "observed.row.001-001.value=`1234abcd-12ab-34cd-56ef-1234567890ab`" in model
        assert "observed.row.004-001.value=`PENDING_DEPLOY`" in model
        assert "<!--" not in model and "<a " not in model
        assert "observed.row.003" not in model
        assert MODEL.linked_resource(s3, "[alias/two](kms.md#kms-aliastwo)") == ("KMS.Alias", "AliasTwo")
        s3_model = MODEL.model_for(s3, REPOSITORY)
        assert "desired.row.001-003.property=S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID" in s3_model
        assert "desired.row.001-003.value=[alias/two](kms.md#kms-aliastwo)" in s3_model
        assert "desired.row.001-004.property=S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm" in s3_model
        assert "desired.row.001-004.value=`aws:kms`" in s3_model
        assert "observed.row.001-003" not in s3_model
        short_s3 = S3.replace("| S3.Bucket.", "| ")
        assert not errors(KMS, short_s3), errors(KMS, short_s3)
        assert MODEL.model_for(s3, REPOSITORY) == s3_model
        s3_with_shortened_properties = (
            S3.replace(
                "| 3 | BucketEncryption[].KMSMasterKeyID",
                "| 3 | BucketEncryption.BucketKeyEnabled | `true` | S3 Bucket Keyを有効化 |\n"
                "| 4 | BucketEncryption[].KMSMasterKeyID",
            )
            .replace("| 4 | BucketEncryption[].SSEAlgorithm", "| 5 | BucketEncryption[].SSEAlgorithm")
            .rstrip()
            + "\n| 6 | LifecycleConfiguration.Rules[].NoncurrentVersionExpirationDays | `30` | 旧versionの保存日数 |\n"
        )
        assert not errors(KMS, s3_with_shortened_properties), errors(KMS, s3_with_shortened_properties)
        shortened_model = MODEL.model_for(s3, REPOSITORY)
        assert "desired.row.001-003.property=S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled" in shortened_model
        assert "desired.row.001-006.property=S3.Bucket.LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NoncurrentDays" in shortened_model
        for display, formal in (
            ("BucketEncryption.BucketKeyEnabled", "BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled"),
            ("LifecycleConfiguration.Rules[].NoncurrentVersionExpirationDays", "LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NoncurrentDays"),
        ):
            assert any("formal property must use its Markdown display alias" in error for error in errors(KMS, s3_with_shortened_properties.replace(display, formal)))

        marker = '<a id="kms-aliastwo"></a><!-- logical-id: AliasTwo --> '
        bad_designs = [
            (KMS.replace(marker, ""), "requires anchor and logical ID"),
            (KMS.replace('KMS.Alias.AliasName', 'AliasName').replace(marker, ""), "full catalog name"),
            (KMS.replace('<!-- logical-id: AliasTwo -->', '<!-- logical-id: AliasOne -->'), "duplicate grouped logical ID"),
            (KMS.replace('id="kms-aliastwo"', 'id="kms-aliasone"'), "duplicate resource anchor"),
            (KMS.replace('id="kms-aliastwo"', 'id="kms-wrong"'), "logical ID/anchor"),
            (KMS.replace('`alias/three`', '`alias/two`'), "duplicate grouped identity value"),
            (KMS.replace('`alias/three`', '`bad-alias`'), "provider schema violation"),
            (KMS.replace('### KMS.Key: KeyOne', '### S3.Bucket: KeyOne'), "wrong parent"),
            (KMS.replace('| 4 | KMS.Alias.AliasName', '| 4 | KMS.Alias.TargetKeyId'), "must be omitted"),
            (KMS.replace('| 4 | KMS.Alias.AliasName', '| 4 | KMS.Key.Description'), "child identity marker"),
            (KMS.replace('### KMS.Key: KeyOne', '### KMS.Alias: KeyOne'), "independent heading"),
            (KMS.replace('| 4 | KMS.Alias.AliasName', '\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n| 4 | KMS.Alias.AliasName'), "exactly one detail table"),
        ]
        for markdown, message in bad_designs:
            failures = errors(markdown)
            assert any(message in error for error in failures), (message, failures)
        for reference in ("[alias/one](kms.md#kms-aliastwo)", "[alias/two](kms.md#kms-keyone)", "[alias/two](kms.md#kms-missing)"):
            assert errors(KMS, S3.replace("[alias/two](kms.md#kms-aliastwo)", reference))
        formal_kms = "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID"
        assert any("must omit heading resource type" in error for error in errors(KMS, S3.replace("BucketEncryption[].KMSMasterKeyID", formal_kms)))

        # Moving an identified child updates only its parent relationship, not its identity.
        alias_line = next(line for line in KMS.splitlines() if marker in line)
        moved = KMS.replace(alias_line + "\n", "").rstrip() + "\n" + alias_line.replace("| 4 |", "| 3 |") + "\n"
        assert not errors(moved), errors(moved)
        _, children = expanded_design(moved.splitlines())
        assert children["kms-aliastwo"]["parentLogicalId"] == "KeyTwo"
        assert children["kms-aliastwo"]["logicalId"] == "AliasTwo"
        moved_model = MODEL.model_for(kms, REPOSITORY)
        assert "desired.resource.005.logicalId=AliasTwo" in moved_model
        assert "desired.resource.005.parentReference=[KeyTwo](#kms-keytwo)" in moved_model

        # A new catalog type cannot silently inherit an independent display decision.
        shutil.copytree(REPOSITORY / "framework/materials/aws", root / "framework/materials/aws")
        shutil.copytree(REPOSITORY / "framework/materials/api", root / "framework/materials/api")
        layout_path = root / "framework/rules/resource-layout.json"
        layout_path.parent.mkdir(parents=True)
        layout_path.write_text(json.dumps(LAYOUTS), encoding="utf-8")
        alias_path = layout_path.with_name("display-property-aliases.json")
        shutil.copy(REPOSITORY / "framework/rules/display-property-aliases.json", alias_path)
        assert not layout_errors(root)
        alias_path.write_text(json.dumps({"S3.Bucket.BucketEncryption[].SSEAlgorithm": "S3.Bucket.Unknown"}), encoding="utf-8")
        assert any("invalid display property alias" in error for error in layout_errors(root))
        shutil.copy(REPOSITORY / "framework/rules/display-property-aliases.json", alias_path)
        (root / "framework/materials/aws/Example_Child.properties").write_text("Example.Child.Name=\n", encoding="utf-8")
        assert any("unclassified=['Example.Child']" in error for error in layout_errors(root))
        broken = {**LAYOUTS, "Example.Child": "independent", "KMS.Alias": {**LAYOUTS["KMS.Alias"], "parentProperty": "Missing"}}
        layout_path.write_text(json.dumps(broken), encoding="utf-8")
        assert any("parent property is absent" in error for error in layout_errors(root))
    print("design-layout: PASS (grouped identities, parent changes, S3 references, invalid designs, catalog coverage)")


if __name__ == "__main__":
    main()
