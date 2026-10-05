#!/usr/bin/env python3
"""Check grouped identities, references and catalog display coverage end to end."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import json
import re
import shutil
import tempfile
from pathlib import Path

from design_layout import DISPLAY_PROPERTY_ALIASES, LAYOUTS, expanded_design, expanded_display_rows, formal_property, layout_errors, resource_anchor, resource_display_name, resource_logical_ids
from policy_tables import resources_in
from model_design import pipeline_rows, display_rows, row_table
from design_layout import SUBNET_LIST_PROPERTIES


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
| 5 | Environment.Variables.FIRST | `hello:world` | 環境変数の値 |
| 6 | Environment.Variables.SECOND | `cde` | 環境変数の値 |
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


def check_secret_rotation_display() -> None:
    text = """# Secrets Manager 詳細設計

- Design service ID: `secretsmanager`
- Owned catalog resource types: `SecretsManager.Secret`, `SecretsManager.RotationSchedule`

## リソース一覧

### SecretsManager.Secret

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-key](#secretsmanager-app-dev-key) | 定期更新する連携用key |
| 2 | [app-dev-token](#secretsmanager-app-dev-token) | 連携用token |

## リソース詳細

<!-- resource-logical-id: AppKey -->
<a id="secretsmanager-app-dev-key"></a>

### SecretsManager.Secret: app-dev-key

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `app-dev-key` | secretの名前 |
| 2 | Id | `PENDING_DEPLOY` | secretのID |
| 3 | SecretsManager.RotationSchedule.Id | `PENDING_DEPLOY` | <a id="secretsmanager-app-dev-key_rotate"></a><!-- logical-id: AppKeyRotation --> app-dev-key_rotate：rotationのID |
| 4 | SecretsManager.RotationSchedule.RotateImmediatelyOnUpdate | `false` | 更新直後のrotation実行設定 |
| 5 | SecretsManager.RotationSchedule.RotationRules.AutomaticallyAfterDays | `30` | rotationの間隔日数 |
| 6 | SecretsManager.RotationSchedule.SecretId | [PENDING_DEPLOY](#secretsmanager-app-dev-key) | 対象secretのID |

<!-- resource-logical-id: AppToken -->
<a id="secretsmanager-app-dev-token"></a>

### SecretsManager.Secret: app-dev-token

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `app-dev-token` | secretの名前 |
| 2 | Id | `PENDING_DEPLOY` | secretのID |
"""
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/secretsmanager.md"
        path.parent.mkdir(parents=True)

        def errors(content):
            path.write_text(content, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables({path: ("secretsmanager", ("SecretsManager.Secret", "SecretsManager.RotationSchedule"))}, *catalog)
            validator.check_design_overviews()
            return validator.errors

        assert not errors(text), errors(text)
        model = MODEL.model_for(path, REPOSITORY)
        assert "desired.resource.004" not in model
        assert "desired.row.002-002.property=SecretsManager.RotationSchedule.RotateImmediatelyOnUpdate" in model
        assert "desired.row.002-003.value=`30`" in model
        assert "desired.row.002-004.value=[AppKey](#secretsmanager-app-dev-key)" in model
        assert "observed.row.002-004.value=PENDING_DEPLOY" in model
        values = MODEL.properties(MODEL.imported_model(path, REPOSITORY))
        rendered = MODEL.markdown_for(path, values, REPOSITORY)
        assert rendered == text
        assert not errors(rendered), errors(rendered)
        assert MODEL.model_for(path, REPOSITORY) == model
        csv_values = {}
        for key, value in values.items():
            row = re.fullmatch(r"((?:desired|observed)\.row\.002-)([0-9]{3})(\..+)", key)
            if row and int(row.group(2)) >= 2:
                key = row.group(1) + f"{int(row.group(2)) + 1:03d}" + row.group(3)
            csv_values[key] = value
        csv_values.update({
            "desired.row.002-002.property": "SecretsManager.RotationSchedule.HostedRotationLambda.VpcSubnetIds",
            "desired.row.002-002.value": "`subnet-00000000000000001,  subnet-00000000000000002`",
            "desired.row.002-002.comment": "rotation Lambdaの配置先Subnet",
        })
        csv_view = MODEL.markdown_for(path, csv_values, REPOSITORY)
        assert not errors(csv_view), errors(csv_view)
        assert MODEL.properties(MODEL.model_for(path, REPOSITORY)) == {
            key: value for key, value in csv_values.items() if not key.startswith("display.")
        }
        assert "HostedRotationLambda.VpcSubnetIds[1]" in csv_view and "HostedRotationLambda.VpcSubnetIds[2]" in csv_view
        for invalid, message in (
            (text.replace("### SecretsManager.Secret: app-dev-key", "### SecretsManager.RotationSchedule: app-dev-key"), "independent heading"),
            (text.replace("### SecretsManager.Secret: app-dev-key", "### S3.Bucket: app-dev-key"), "wrong parent"),
            (text.replace("[PENDING_DEPLOY](#secretsmanager-app-dev-key)", "[PENDING_DEPLOY](#secretsmanager-app-dev-token)"), "must reference enclosing"),
            (text.replace("RotationRules.AutomaticallyAfterDays", "RotateImmediatelyOnUpdate"), "duplicate property"),
            (text.replace("`30`", "`invalid`"), "provider schema violation"),
            (text.replace("### SecretsManager.Secret\n", "### SecretsManager.RotationSchedule\n"), "resource overview types"),
        ):
            failures = errors(invalid)
            assert any(message in error for error in failures), (message, failures)


def check_codebuild_variable_display() -> None:
    codebuild = CODEBUILD.replace('| 6 | Environment.Variables.SECOND | `cde` | 環境変数の値 |', '| 6 | Environment.Variables.SECOND | [venus-dev-snowflake-cicd-keypair-cde](secretsmanager.md#secretsmanager-snowflakekey) | <!-- codebuild-variable-type: SECRETS_MANAGER --> 環境変数の参照先 |')
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/codebuild.md"
        path.parent.mkdir(parents=True)
        secret = path.with_name("secretsmanager.md")
        secret.write_text("""# Secrets Manager 詳細設計
<a id="secretsmanager-snowflakekey"></a>
### SecretsManager.Secret: SnowflakeKey
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `venus-dev-snowflake-cicd-keypair-cde` | secretの名前 |
| 2 | Id | `PENDING_DEPLOY` | secretのID |
""", encoding="utf-8")

        def errors(content: str) -> list[str]:
            path.write_text(content, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables({path: ("codebuild", ("CodeBuild.Project",))}, *catalog)
            validator.check_design_links(catalog[2])
            return validator.errors

        assert not errors(codebuild), errors(codebuild)
        model = MODEL.model_for(path, REPOSITORY)
        assert "desired.row.001-005.property=CodeBuild.Project.Environment.EnvironmentVariables[].Name" in model
        assert "desired.row.001-005.value=`FIRST`" in model
        assert "desired.row.001-006.property=CodeBuild.Project.Environment.EnvironmentVariables[].Type" in model
        assert "desired.row.001-007.value=`hello:world`" in model
        assert "desired.row.001-008.value=`SECOND`" in model
        assert "desired.row.001-006.value=`PLAINTEXT`" in model
        assert "desired.row.001-009.value=`SECRETS_MANAGER`" in model
        secret_link = "[venus-dev-snowflake-cicd-keypair-cde](secretsmanager.md#secretsmanager-snowflakekey)"
        assert f"desired.row.001-010.value={secret_link}" in model
        assert "observed.row.001-010" not in model
        assert "codebuild-variable-type" not in model
        assert "Environment.Variables." not in model
        short = codebuild
        assert "| Artifacts.Type |" in short
        assert not errors(short), errors(short)
        assert MODEL.model_for(path, REPOSITORY) == model
        assert any("must omit heading resource type" in error for error in errors(short.replace("| 2 | Id |", "| 2 | CodeBuild.Project.Id |")))
        assert errors(short.replace("Artifacts.Type", "Artifacts.Unknown"))
        assert errors(codebuild.replace("Variables.SECOND", "Variables.FIRST"))
        assert not errors(codebuild.replace("hello:world", "cde"))
        assert errors(codebuild.replace("Variables.FIRST | `hello:world`", "EnvironmentVariables[].Name | `FIRST`"))
        for bad in (
            codebuild.replace("`hello:world`", "`PLAINTEXT:cde`"),
            codebuild.replace("<!-- codebuild-variable-type: SECRETS_MANAGER --> ", ""),
            codebuild.replace("SECRETS_MANAGER -->", "UNKNOWN -->"),
            codebuild.replace("SECRETS_MANAGER -->", "PARAMETER_STORE -->"),
            codebuild.replace(secret_link, "`venus-dev-snowflake-cicd-keypair-cde`"),
            codebuild.replace(secret_link, f"`{secret_link}`"),
            codebuild.replace(secret_link, "[secret](secretsmanager.md)"),
            codebuild.replace("#secretsmanager-snowflakekey", "#missing"),
            codebuild.replace("(secretsmanager.md#", "(missing.md#"),
            codebuild.replace("[venus-dev-snowflake-cicd-keypair-cde]", "[wrong-name]"),
        ):
            assert errors(bad), bad
        selector = codebuild.replace("[venus-dev-snowflake-cicd-keypair-cde]", "[venus-dev-snowflake-cicd-keypair-cde:private-key:AWSCURRENT]")
        assert not errors(selector), errors(selector)
        assert "[venus-dev-snowflake-cicd-keypair-cde:private-key:AWSCURRENT](secretsmanager.md#secretsmanager-snowflakekey)" in MODEL.model_for(path, REPOSITORY)
        literal_link = codebuild.replace("SECRETS_MANAGER -->", "PLAINTEXT -->")
        assert not errors(literal_link), errors(literal_link)
        assert "desired.row.001-009.value=`PLAINTEXT`" in MODEL.model_for(path, REPOSITORY)
        parameter_link = codebuild.replace("SECRETS_MANAGER -->", "PARAMETER_STORE -->")
        expanded = "\n".join(expanded_display_rows(parameter_link.splitlines()))
        assert "| CodeBuild.Project.Environment.EnvironmentVariables[].Type | `PARAMETER_STORE` |" in expanded
        other_target = path.parent.parent / "987654321098"
        other_target.mkdir()
        shutil.copy(secret, other_target / secret.name)
        assert errors(codebuild.replace("(secretsmanager.md#", "(../987654321098/secretsmanager.md#"))
        secret.write_text(secret.read_text(encoding="utf-8").replace("SecretsManager.Secret:", "S3.Bucket:"), encoding="utf-8")
        assert errors(codebuild)


def check_codebuild_vpc_display() -> None:
    vpc_rows = """| 11 | VpcConfig.Subnets[1] | [subnet-00000000000000001](vpc.md#vpc-sbnt-one) | 1つ目のprivate subnet |
| 12 | VpcConfig.Subnets[2] | [subnet-00000000000000002](vpc.md#vpc-sbnt-two) | 2つ目のprivate subnet |
| 13 | VpcConfig.SecurityGroupIds[1] | [PENDING_DEPLOY](security-group.md#security-group-codebuild-sg) | buildに適用するSecurity Group |
"""
    design_text = CODEBUILD + vpc_rows
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        design = root / "docs/designs/dev/123456789012"
        design.mkdir(parents=True)
        path = design / "codebuild.md"
        (design / "vpc.md").write_text("""# VPC 詳細設計

<a id="vpc-main"></a>
### EC2.VPC: main
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | `vpc-00000000000000001` | VPCのID |

<a id="vpc-sbnt-one"></a>
### EC2.Subnet: sbnt-one
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `sbnt-one` | subnetのName |
| 2 | SubnetId | `subnet-00000000000000001` | subnetのID |

<a id="vpc-sbnt-two"></a>
### EC2.Subnet: sbnt-two
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `sbnt-two` | subnetのName |
| 2 | SubnetId | `subnet-00000000000000002` | subnetのID |
""", encoding="utf-8")
        (design / "security-group.md").write_text("""# Security Group 詳細設計

## リソース一覧

### EC2.SecurityGroup

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [CodeBuildSG](#security-group-codebuild-sg) | buildの通信を制御するSecurity Group |

## リソース詳細

<a id="security-group-codebuild-sg"></a>
### EC2.SecurityGroup: CodeBuildSG
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | `PENDING_DEPLOY` | Security GroupのID |
| 2 | GroupDescription | `Build access` | 用途の説明 |
| 3 | VpcId | [vpc-00000000000000001](vpc.md#vpc-main) | 所属するVPC |
""", encoding="utf-8")
        catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()

        def errors(content: str) -> list[str]:
            path.write_text(content, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.design_files = lambda: [path]
            validator.check_design_tables({path: ("codebuild", ("CodeBuild.Project",))}, *catalog)
            validator.design_files = lambda: sorted(design.glob("*.md"))
            validator.check_design_links(catalog[2])
            return validator.errors

        assert not errors(design_text), errors(design_text)
        model = MODEL.model_for(path, REPOSITORY)
        assert model.count("property=CodeBuild.Project.VpcConfig.Subnets") == 4  # desired and observed, twice each
        assert "desired.row.001-015.property=CodeBuild.Project.VpcConfig.Subnets" in model
        assert "desired.row.001-015.value=[sbnt-one](vpc.md#vpc-sbnt-one)" in model
        assert "observed.row.001-015.value=subnet-00000000000000001" in model
        assert "desired.row.001-017.property=CodeBuild.Project.VpcConfig.SecurityGroupIds" in model
        assert "desired.row.001-017.value=[CodeBuildSG](security-group.md#security-group-codebuild-sg)" in model
        assert "observed.row.001-017.value=PENDING_DEPLOY" in model
        assert "VpcConfig.Subnets[1]" not in model
        for bad in (
            design_text.replace("Subnets[1]", "Subnets[0]"),
            design_text.replace("Subnets[2]", "Subnets[3]"),
            design_text.replace("Subnets[2]", "Subnets[1]"),
            design_text.replace("SecurityGroupIds[1]", "SecurityGroupIds[2]"),
            design_text.replace("VpcConfig.Subnets[1]", "VpcConfig.Subnets"),
            design_text.replace("[subnet-00000000000000001](vpc.md#vpc-sbnt-one)", "`[subnet-00000000000000001](vpc.md#vpc-sbnt-one)`"),
            design_text.replace("[subnet-00000000000000001](vpc.md#vpc-sbnt-one)", '`["[subnet-00000000000000001](vpc.md#vpc-sbnt-one)"]`'),
            design_text.replace("[subnet-00000000000000001](vpc.md#vpc-sbnt-one)", "[PENDING_DEPLOY](security-group.md#security-group-codebuild-sg)"),
        ):
            assert errors(bad), bad


def check_subnet_list_links() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        design = root / "docs/designs/dev/123456789012"
        design.mkdir(parents=True)
        vpc = design / "vpc.md"
        subnet = """# VPC 詳細設計

<a id="subnet-a"></a>
### EC2.Subnet: subnet-a
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | SubnetId | `subnet-00000000000000001` | SubnetのID |
"""
        vpc.write_text(subnet, encoding="utf-8")
        other = design.parent / "987654321098"
        other.mkdir()
        (other / "vpc.md").write_text(subnet, encoding="utf-8")
        outputs = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()[2]
        for prop in sorted(SUBNET_LIST_PROPERTIES):
            kind = ".".join(prop.split(".")[:2])
            path = design / (kind.split(".")[0].lower() + ".md")

            def content(value):
                shown = display_rows(kind, [["1", prop, value, "配置先Subnet"]])
                if kind == "SecretsManager.RotationSchedule":
                    return "\n".join([
                        "# Secrets Manager 詳細設計", "- Design service ID: `secretsmanager`",
                        '<a id="secretsmanager-key"></a>', "### SecretsManager.Secret: key",
                        *row_table([
                            ["1", "Name", "`key`", "secretの名称"],
                            ["2", "Id", "`PENDING_DEPLOY`", "secretのID"],
                            ["2", "SecretsManager.RotationSchedule.Id", "`PENDING_DEPLOY`",
                             '<a id="secretsmanager-key-rotation"></a><!-- logical-id: KeyRotation --> key-rotation：rotationのID'],
                            ["3", "SecretsManager.RotationSchedule.SecretId", "[PENDING_DEPLOY](#secretsmanager-key)", "対象secret"],
                            ["4", kind + "." + shown[0][1], shown[0][2], shown[0][3]],
                        ]),
                    ]) + "\n"
                return "\n".join(["# Subnet参照の設計", "", "<a id=\"owner\"></a>", f"### {kind}: owner", *row_table(shown)]) + "\n"

            def errors(value):
                path.write_text(content(value), encoding="utf-8")
                validator = VALIDATOR.Validator(root)
                validator.design_files = lambda: [path]
                validator.check_design_links(outputs)
                return validator.errors

            assert not errors("[subnet-00000000000000001](vpc.md#subnet-a)"), (prop, errors("[subnet-00000000000000001](vpc.md#subnet-a)"))
            assert errors("[subnet-00000000000000001](../987654321098/vpc.md#subnet-a)"), prop
            vpc.write_text(subnet.replace("EC2.Subnet:", "EC2.VPC:"), encoding="utf-8")
            assert errors("[subnet-00000000000000001](vpc.md#subnet-a)"), prop
            vpc.write_text(subnet, encoding="utf-8")
    print("Subnet list links: PASS (15 properties, same-target Subnet type, grouped RotationSchedule)")


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
        all_buckets = trail.replace(
            "[data-bucket](s3.md#s3-data-bucket) | S3 object",
            "`All current and future S3 buckets` | S3 object",
        )
        assert not errors(all_buckets), errors(all_buckets)
        original = path.read_bytes()
        all_model = MODEL.model_for(path, REPOSITORY)
        assert path.read_bytes() == original
        assert all_model == model.replace(
            "desired.row.001-003.value=[data-bucket](s3.md#s3-data-bucket)",
            'desired.row.001-003.value=`["arn:aws:s3"]`',
        )
        assert "All current and future S3 buckets" not in all_model
        for bad_value in (
            "All current and future S3 buckets",
            "`All current and future S3 bucket`",
            "`arn:aws:s3`",
            '`["arn:aws:s3"]`',
            '`[data-bucket](s3.md#s3-data-bucket)`',
        ):
            assert errors(all_buckets.replace("`All current and future S3 buckets`", bad_value)), bad_value
        assert errors(trail.replace(
            "[function-one](lambda.md#lambda-function-one)",
            "`All current and future S3 buckets`",
        ))
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


def check_codepipeline_display() -> None:
    def design(service: str, resource_type: str, logical_id: str, rows: list[tuple[str, str]]) -> str:
        return "\n".join([
            f"# {service} 詳細設計", f"- Design service ID: `{service}`",
            f"- Owned catalog resource types: `{resource_type}`", "## リソース詳細",
            f'<a id="{service}-{logical_id.lower()}"></a>', f"### {resource_type}: {logical_id}",
            "| No. | Property | Value | Source / Comment |", "| ---: | --- | --- | --- |",
            *(f"| {n} | {prop} | {value} | 設定する属性 |" for n, (prop, value) in enumerate(rows, 1)),
        ]) + "\n"

    rows = [
        ("Name", "`pipeline`"),
        ("RoleArn", "[role](iam.md#iam-role)"),
        ("Stages[1].Actions.ActionTypeId.Provider", "`CodeCommit`"),
        ("Stages[1].Actions.Configuration.BranchName", "`dev`"),
        ("Stages[1].Actions.Configuration.PollForSourceChanges", "`false`"),
        ("Stages[1].Actions.Configuration.RepositoryName", "[repo](codecommit.md#codecommit-repo)"),
        ("Stages[1].Actions.Name", "`Source`"),
        ("Stages[1].Name", "`Source`"),
        ("Stages[2].Actions[1].ActionTypeId.Provider", "`CodeBuild`"),
        ("Stages[2].Actions[1].Configuration.ProjectName", "[build](codebuild.md#codebuild-build)"),
        ("Stages[2].Actions[1].Name", "`Build`"),
        ("Stages[2].Actions[2].ActionTypeId.Provider", "`CodeBuild`"),
        ("Stages[2].Actions[2].Configuration.ProjectName", "[build](codebuild.md#codebuild-build)"),
        ("Stages[2].Actions[2].Name", "`Test`"),
        ("Stages[2].Name", "`BuildAndTest`"),
    ]
    pipeline = design("codepipeline", "CodePipeline.Pipeline", "Pipeline", rows)
    repository = design("codecommit", "CodeCommit.Repository", "Repo", [("RepositoryName", "`repo`")])
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    assert not catalog[2].get("CodeCommit.Repository")
    assert not MODEL.identifier_outputs(REPOSITORY).get("CodeCommit.Repository")
    expanded = "\n".join(expanded_display_rows(pipeline.splitlines()))
    assert expanded.count("CodePipeline.Pipeline.Stages[].Actions[].Configuration |") == 3
    assert '`{"BranchName":"dev","PollForSourceChanges":"false","RepositoryName":"[repo](codecommit.md#codecommit-repo)"}`' in expanded
    assert "Stages[1]" not in expanded and "Actions[2]" not in expanded
    formal_rows = [
        [cells[0], cells[1].removeprefix("CodePipeline.Pipeline."), *cells[2:]]
        for line in expanded.splitlines()
        if len(cells := [cell.strip() for cell in line.strip("|").split("|")]) == 4 and cells[0].isdigit()
    ]
    assert [(row[1], row[2]) for row in pipeline_rows(formal_rows)] == rows
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "docs/designs/dev/123456789012"
        target.mkdir(parents=True)
        path = target / "codepipeline.md"
        repo_path = target / "codecommit.md"
        repo_path.write_text(repository, encoding="utf-8")
        (target / "codebuild.md").write_text(design("codebuild", "CodeBuild.Project", "Build", [
            ("Name", "`build`"), ("Id", "`PENDING_DEPLOY`"), ("ServiceRole", "[role](iam.md#iam-role)"),
        ]), encoding="utf-8")
        (target / "iam").mkdir()
        (target / "iam/role-trust-policy.json").write_text('{"Version":"2012-10-17","Statement":[]}', encoding="utf-8")
        (target / "iam.md").write_text(design("iam", "IAM.Role", "Role", [
            ("RoleName", "`role`"), ("AssumeRolePolicyDocument", "[trust](iam/role-trust-policy.json)"),
        ]), encoding="utf-8")

        def errors(content: str) -> list[str]:
            path.write_text(content, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables({path: ("codepipeline", ("CodePipeline.Pipeline",)), repo_path: ("codecommit", ("CodeCommit.Repository",))}, *catalog)
            validator.check_design_links(catalog[2])
            return validator.errors

        assert not errors(pipeline), errors(pipeline)
        original = path.read_bytes()
        model = MODEL.model_for(path, REPOSITORY)
        assert path.read_bytes() == original
        assert '"PollForSourceChanges":"false"' in model
        assert '"ProjectName":"[build](codebuild.md#codebuild-build)"' in model
        assert model.count(".property=CodePipeline.Pipeline.Stages[].Actions[].Configuration") == 3
        assert "Stages[1]" not in model and "Actions[2]" not in model
        assert "RepositoryId" not in MODEL.model_for(repo_path, REPOSITORY)
        assert "observed." not in model
        for bad in (
            pipeline.replace("Stages[1]", "Stages[]"),
            pipeline.replace("Stages[1]", "Stages[0]"),
            pipeline.replace("Stages[2]", "Stages[3]"),
            pipeline.replace("Stages[2]", "Stages[1]"),
            pipeline.replace("Stages[1].Actions.", "Stages[1].Actions[1]."),
            pipeline.replace("Stages[1].Actions.", "Stages[1].Actions[]."),
            pipeline.replace("Actions[2]", "Actions[3]"),
            pipeline.replace("Actions[2]", "Actions[1]"),
            pipeline.replace("Actions[1]", "Actions"),
            pipeline.replace("Configuration.BranchName", "Configuration"),
            pipeline.replace("Configuration.PollForSourceChanges", "Configuration.BranchName"),
            pipeline.replace("`dev`", '`{"Fn::ImportValue":"branch-export"}`'),
            pipeline.replace("`dev`", "`!ImportValue branch-export`"),
            pipeline.replace("[build](codebuild.md#codebuild-build)", '`{"Fn::ImportValue":"CdeDevApplicationBuildProjectName"}`'),
            pipeline.replace("[build](codebuild.md#codebuild-build)", "`build`"),
            pipeline.replace("[build](codebuild.md#codebuild-build)", "[repo](codecommit.md#codecommit-repo)"),
            pipeline.replace("[build](codebuild.md#codebuild-build)", "[wrong](codebuild.md#codebuild-build)"),
            pipeline.replace("[build](codebuild.md#codebuild-build)", "[build](codebuild.md#codebuild-missing)"),
            pipeline.replace("[build](codebuild.md#codebuild-build)", "`[build](codebuild.md#codebuild-build)`"),
            pipeline.replace("[repo](codecommit.md#codecommit-repo)", "[wrong](codecommit.md#codecommit-repo)"),
        ):
            assert errors(bad), bad
        for duplicate in (("Stages[1].Name", "`DuplicateStage`"), ("Stages[2].Actions[2].Name", "`DuplicateAction`")):
            assert errors(design("codepipeline", "CodePipeline.Pipeline", "Pipeline", [*rows, duplicate]))
        reordered = rows.copy()
        reordered[4], reordered[6] = reordered[6], reordered[4]
        assert errors(design("codepipeline", "CodePipeline.Pipeline", "Pipeline", reordered))
        (target.parent / "other").mkdir()
        shutil.copy(target / "codebuild.md", target.parent / "other/codebuild.md")
        assert errors(pipeline.replace("codebuild.md#", "../other/codebuild.md#"))
        repo_path.write_text(repository.replace("| 1 | RepositoryName", "| 1 | RepositoryId | `PENDING_DEPLOY` | 一意に識別するID |\n| 2 | RepositoryName"), encoding="utf-8")
        assert errors(pipeline)
        try:
            MODEL.model_for(repo_path, REPOSITORY)
        except ValueError as error:
            assert "must not be displayed" in str(error)
        else:
            raise AssertionError("RepositoryId display was accepted")


def check_config_firehose_references() -> None:
    def design(service, kind, rows):
        return "\n".join([
            f"# {service} 詳細設計", f"- Design service ID: `{service}`",
            f"- Owned catalog resource types: `{kind}`", "## リソース詳細",
            f'<a id="{service}-resource"></a>', f"### {kind}: Resource",
            "| No. | Property | Value | Source / Comment |", "| ---: | --- | --- | --- |",
            *(f"| {n} | {prop} | {value} | 設定する属性 |" for n, (prop, value) in enumerate(rows, 1)),
        ]) + "\n"

    role_link = "[config-role](iam.md#iam-resource)"
    config = design("config", "Config.ConfigurationRecorder", [
        ("Name", "`recorder`"), ("Id", "`PENDING_DEPLOY`"), ("RoleName", role_link),
    ])
    firehose = design("kdf", "KinesisFirehose.DeliveryStream", [
        ("DeliveryStreamName", "`delivery`"),
        ("DeliveryStreamEncryptionConfigurationInput.KeyARN", "[1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone)"),
        ("DeliveryStreamEncryptionConfigurationInput.KeyType", "`CUSTOMER_MANAGED_CMK`"),
        ("S3DestinationConfiguration.BucketARN", "[app-data](s3.md#s3-app-data)"),
        ("S3DestinationConfiguration.RoleARN", role_link),
    ])
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "docs/designs/dev/123456789012"
        target.mkdir(parents=True)
        (target / "kms.md").write_text(KMS, encoding="utf-8")
        (target / "s3.md").write_text(S3, encoding="utf-8")
        (target / "iam").mkdir()
        (target / "iam/resource-trust-policy.json").write_text('{"Statement":[]}', encoding="utf-8")
        (target / "iam.md").write_text(design("iam", "IAM.Role", [
            ("RoleName", "`config-role`"),
            ("AssumeRolePolicyDocument", "[trust](iam/resource-trust-policy.json)"),
        ]), encoding="utf-8")
        config_path, kdf_path = target / "config.md", target / "kdf.md"

        def errors(config_text=config, kdf_text=firehose):
            config_path.write_text(config_text, encoding="utf-8")
            kdf_path.write_text(kdf_text, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables({}, *catalog)
            validator.check_design_links(catalog[2])
            return validator.errors

        assert not errors(), errors()
        model = MODEL.model_for(config_path, REPOSITORY)
        assert "desired.row.001-003.property=Config.ConfigurationRecorder.RoleARN" in model
        assert f"desired.row.001-003.value={role_link}" in model
        assert "Config.ConfigurationRecorder.RoleName" not in model
        assert "observed.row.001-003" not in model
        kdf_model = MODEL.model_for(kdf_path, REPOSITORY)
        assert "desired.row.001-002.value=[KeyOne](kms.md#kms-keyone)" in kdf_model
        assert "observed.row.001-002.value=1234abcd-12ab-34cd-56ef-1234567890ab" in kdf_model
        assert "desired.row.001-004.value=[app-data](s3.md#s3-app-data)" in kdf_model
        assert f"desired.row.001-005.value={role_link}" in kdf_model
        assert "arn:aws" not in model + kdf_model
        for bad in (
            config.replace("RoleName |", "RoleARN |"),
            config.replace(role_link, "`config-role`"),
            config.replace(role_link, "[wrong](iam.md#iam-resource)"),
            config.replace(role_link, "[alias/two](kms.md#kms-aliastwo)"),
            config.replace(role_link, "[config-role](iam.md#iam-missing)"),
        ):
            assert errors(config_text=bad), bad
        for link in (
            "[1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone)",
            "[app-data](s3.md#s3-app-data)", role_link,
        ):
            for replacement in ("`!ImportValue resource-export`", "`arn:aws:s3:::app-data`", "[wrong](s3.md#s3-app-data)", "[alias/two](kms.md#kms-aliastwo)", "`" + link + "`"):
                assert errors(kdf_text=firehose.replace(link, replacement)), replacement
        other_target = target.with_name("987654321098")
        other_target.mkdir()
        (other_target / "kms.md").write_text(KMS, encoding="utf-8")
        assert errors(kdf_text=firehose.replace("(kms.md#kms-keyone)", "(../987654321098/kms.md#kms-keyone)"))
        pending = firehose.replace("1234abcd-12ab-34cd-56ef-1234567890ab", "PENDING_DEPLOY").replace("kms-keyone", "kms-keytwo")
        assert not errors(kdf_text=pending), errors(kdf_text=pending)
        assert "observed.row.001-002.value=PENDING_DEPLOY" in MODEL.model_for(kdf_path, REPOSITORY)

        (target / "iam.md").unlink()
        for role in ("AWSServiceRoleForConfig", "`AWSServiceRoleForConfig`", "`AWSServiceCustom`"):
            service_config = config.replace(role_link, role)
            service_firehose = firehose.replace(role_link, role)
            assert not errors(service_config, service_firehose), errors(service_config, service_firehose)
            service_model = MODEL.model_for(config_path, REPOSITORY)
            assert f"desired.row.001-003.value={role}" in service_model
            assert "desired.row.001-003.property=Config.ConfigurationRecorder.RoleARN" in service_model
            assert "observed.row.001-003" not in service_model
        for role in (
            "`config-role`", "`AWSService`", "`AWSServiceRoleForConfig/path`",
            "`arn:aws:iam::123456789012:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig`",
            "`AWSServiceRoleForConfig", "awsServiceRoleForConfig", "AWSService" + "x" * 55,
        ):
            assert errors(config.replace(role_link, role), service_firehose), role
            assert errors(service_config, firehose.replace(role_link, role)), role
        assert errors(config, service_firehose)  # Missing IAM links still fail.
        for prop, link in (
            ("KeyARN", "[1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone)"),
            ("BucketARN", "[app-data](s3.md#s3-app-data)"),
        ):
            assert errors(service_config, service_firehose.replace(link, "`AWSServiceRoleForConfig`")), prop

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(REPOSITORY / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation",
        }]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/config.md"
        path.parent.mkdir(parents=True)
        source = design("config", "Config.ConfigurationRecorder", [
            ("Id", "`PENDING_DEPLOY`"), ("RoleName", "`AWSServiceRoleForConfig`"),
        ]).replace('<a id="config-resource">', '<!-- resource-logical-id: ConfigRecorder -->\n<a id="config-configuration-recorder-recorder">').replace("ConfigurationRecorder: Resource", "ConfigurationRecorder: recorder")
        path.write_text(source, encoding="utf-8")
        values = MODEL.properties(MODEL.model_for(path, REPOSITORY))
        values.update({"display.service.title": "# Config 詳細設計", "display.resource.001.label": "recorder", "display.resource.001.comment": "AWSリソースの設定を記録するrecorder"})
        model_path = root / "model/dev/123456789012/config.properties"
        model_path.parent.mkdir(parents=True)
        model_path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
        path.unlink()
        assert MODEL.sync(root, True, "dev", "123456789012") == 0
        assert "| RoleName | `AWSServiceRoleForConfig` |" in path.read_text(encoding="utf-8")
        assert not path.with_name("iam.md").exists()
        assert MODEL.sync(root, False, "dev", "123456789012") == 0


def check_resource_name_headings() -> None:
    name = "ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455"
    logical_id = "CoreSystemNightlyProcessingCompletedDetect0200To0455Schedule"
    anchor = resource_anchor("scheduler", name)
    marker = f"<!-- resource-logical-id: {logical_id} -->"
    text = f"""# Scheduler 詳細設計

- Design service ID: `scheduler`
- Owned catalog resource types: `Scheduler.Schedule`

## リソース一覧

### Scheduler.Schedule

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [{name}](#{anchor}) | 夜間処理の完了を5分間隔で検知するschedule |

## リソース詳細

{marker}
<a id="{anchor}"></a>

### Scheduler.Schedule: {name}

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `{name}` | scheduleの名前 |
"""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/scheduler.md"
        path.parent.mkdir(parents=True)
        metadata = {path: ("scheduler", ("Scheduler.Schedule",))}
        (root / "framework/rules").mkdir(parents=True)
        shutil.copyfile(REPOSITORY / "framework/rules/aws-resource-naming.md", root / "framework/rules/aws-resource-naming.md")
        shutil.copytree(REPOSITORY / "framework/rules/aws-resource-naming", root / "framework/rules/aws-resource-naming")

        def errors(markdown):
            path.write_text(markdown, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.check_resource_names(metadata)
            validator.check_design_overviews()
            validator.check_design_links({})
            return validator.errors

        assert not errors(text), errors(text)
        model = MODEL.model_for(path, REPOSITORY)
        assert f"desired.resource.001.logicalId={logical_id}" in model
        assert f"desired.resource.001.anchor={anchor}" in model
        assert "resource-logical-id" not in model and "desired.note" not in model
        assert MODEL.linked_resource(path, f"[{name}](#{anchor})") == ("Scheduler.Schedule", logical_id)
        for invalid, message in (
            (text.replace(f"### Scheduler.Schedule: {name}", f"### Scheduler.Schedule: {logical_id}"), "heading must display resource name"),
            (text.replace(f"[{name}]", f"[{logical_id}]"), "must not display internal logical ID"),
            (text.replace(f"| `{name}` |", "| `PENDING_DEPLOY` |"), "display name must be confirmed"),
            (text.replace(anchor, "scheduler-internal-id"), "anchor must use display name"),
            (text.replace(marker, "<!-- resource-logical-id: -->"), "invalid resource identity"),
            (text + "\n" + marker, "invalid resource identity"),
        ):
            failures = errors(invalid)
            assert any(message in failure for failure in failures), (message, failures)
        assert not errors(text), errors(text)

        # A named parent keeps its hidden ID when children are expanded.
        named_kms = KMS.replace('<a id="kms-keyone"></a>', '<!-- resource-logical-id: KeyOne -->\n<a id="kms-one"></a>').replace('### KMS.Key: KeyOne', '### KMS.Key: one').replace('(#kms-keyone)', '(#kms-one)').replace('[KeyOne]', '[one]')
        named_kms = named_kms.replace('<a id="kms-keytwo"></a>', '<!-- resource-logical-id: KeyTwo -->\n<a id="kms-three"></a>').replace('### KMS.Key: KeyTwo', '### KMS.Key: three').replace('(#kms-keytwo)', '(#kms-three)').replace('[KeyTwo]', '[three]')
        for word in ("one", "two", "three"):
            named_kms = named_kms.replace("kms-alias" + word, "kms-alias-" + word)
        kms = path.with_name("kms.md")
        kms.write_text(named_kms, encoding="utf-8")
        model = MODEL.model_for(kms, REPOSITORY)
        assert "desired.resource.001.logicalId=KeyOne" in model
        assert "parentReference=[KeyOne](#kms-one)" in model
        assert "desired.row.001-001.value=[KeyOne](#kms-one)" in model
        assert MODEL.linked_resource(path, "[PENDING_DEPLOY](kms.md#kms-one)") == ("KMS.Key", "KeyOne")

        group_name = "transfer service access"
        sg_anchor = resource_anchor("security-group", group_name)
        sg_text = text.replace("scheduler", "security-group").replace("Scheduler.Schedule", "EC2.SecurityGroup").replace(logical_id, "TransferSecurityGroup").replace(name, group_name)
        sg_text = sg_text.replace("security-group-" + group_name, sg_anchor)
        sg_text = sg_text.replace(f"| 1 | Name | `{group_name}` | scheduleの名前 |", "| 1 | Id | `PENDING_DEPLOY` | SGのID |\n| 2 | GroupDescription | `transfer service access` | 通信の用途 |\n| 3 | VpcId | `vpc-123` | 所属VPCのID |")
        sg = path.with_name("security-group.md")
        sg.write_text(sg_text, encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.check_resource_names({sg: ("security-group", ("EC2.SecurityGroup",)), kms: ("kms", ("KMS.Key", "KMS.Alias")), **metadata})
        assert not validator.errors, validator.errors
        assert "desired.resource.001.logicalId=TransferSecurityGroup" in MODEL.model_for(sg, REPOSITORY)

    assert resource_display_name("IAM.Role", [["1", "RoleName", "`role-app-dev`", "名前"]]) == "role-app-dev"
    assert resource_display_name("KMS.Key", [["1", "KMS.Alias.AliasName", "`alias/app`", "名前"]]) == "app"
    assert resource_display_name("Scheduler.Schedule", [["1", "GroupName", "`default`", "group"]]) is None
    assert resource_display_name("EC2.SecurityGroup", [["1", "EC2.SecurityGroup.Tags[].Key", '"Name"', "タグ"], ["2", "EC2.SecurityGroup.Tags[].Value", '"sg-app-dev"', "タグ"]]) == "sg-app-dev"
    assert resource_anchor("secretsmanager", "app/dev/key") == "secretsmanager-app-dev-key"
    assert resource_logical_ids(text.splitlines()) == {("Scheduler.Schedule", name): logical_id}


def main() -> None:
    for kind in LAYOUTS:
        assert formal_property(kind + ".Name", "S3.Bucket") == kind + ".Name"
        assert formal_property(kind + "Extra.Name", "S3.Bucket") == "S3.Bucket." + kind + "Extra.Name"
    for alias in DISPLAY_PROPERTY_ALIASES:
        assert formal_property(alias, "S3.Bucket") == alias
    assert formal_property("BucketName", "S3.Bucket") == "S3.Bucket.BucketName"
    assert formal_property("BucketName", "") == "BucketName"
    check_resource_name_headings()
    assert not layout_errors(REPOSITORY)
    policy_rows = [
        '<a id="iam-role"></a>', '### IAM.Role: Role',
        '| No. | Property | Value | Source / Comment |',
        '| ---: | --- | --- | --- |',
        '| 1 | RoleName | `role` | roleの名前 |',
        '| 2 | AssumeRolePolicyDocument | [trust](trust.json) | 信頼policy |',
    ]
    assert resources_in(policy_rows)[0].policies[0].property_name == "IAM.Role.AssumeRolePolicyDocument"
    check_secret_rotation_display()
    check_codebuild_variable_display()
    check_codebuild_vpc_display()
    check_subnet_list_links()
    check_guardduty_feature_display()
    check_cloudtrail_data_resources()
    check_codepipeline_display()
    check_config_firehose_references()
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
