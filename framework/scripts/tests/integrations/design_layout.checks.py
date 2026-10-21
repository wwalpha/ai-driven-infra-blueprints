#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from support.validator import diagnostics

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.design_layout_fixtures import *

from support.it_workspace import copy_framework

def check_secret_rotation_display(tmp_path, catalog) -> None:
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
| 2 | SecretsManager.RotationSchedule.RotateImmediatelyOnUpdate | `false` | <a id="secretsmanager-app-dev-key_rotate"></a><!-- logical-id: AppKeyRotation --> app-dev-key_rotate：更新直後のrotation実行設定 |
| 3 | SecretsManager.RotationSchedule.RotationRules.AutomaticallyAfterDays | `30` | rotationの間隔日数 |
| 4 | SecretsManager.RotationSchedule.SecretId | [app-dev-key](#secretsmanager-app-dev-key) | 対象secretのID |

<!-- resource-logical-id: AppToken -->
<a id="secretsmanager-app-dev-token"></a>

### SecretsManager.Secret: app-dev-token

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `app-dev-token` | secretの名前 |
"""
    root = tmp_path
    path = root / "docs/designs/dev/123456789012/secretsmanager.md"
    path.parent.mkdir(parents=True)

    def errors(content):
        path.write_text(content, encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
        validator.check_design_tables({path: ("secretsmanager", ("SecretsManager.Secret", "SecretsManager.RotationSchedule"))}, *catalog)
        validator.check_design_overviews()
        return diagnostics(validator)

    assert not errors(text), errors(text)
    model = """# Synthetic authoritative Model fixture.
desired.service.identity.lastAllocated={"SecretsManager.Secret":2,"SecretsManager.RotationSchedule":1}
desired.service.secretsmanager.serviceId=secretsmanager
desired.service.secretsmanager.ownedCatalogResourceTypes=SecretsManager.Secret,SecretsManager.RotationSchedule
desired.resource.001.resourceType=SecretsManager.Secret
desired.resource.001.logicalId=SecretsManager_Secret_001
desired.resource.001.cfn-logicalId=fixture-AppKey
desired.row.001-001.property=SecretsManager.Secret.Name
desired.row.001-001.value=`app-dev-key`
desired.row.001-001.comment=secretの名前
desired.resource.002.resourceType=SecretsManager.RotationSchedule
desired.resource.002.logicalId=SecretsManager_RotationSchedule_001
desired.resource.002.cfn-logicalId=fixture-AppKeyRotation
desired.resource.002.parentProperty=SecretsManager.RotationSchedule.SecretId
desired.resource.002.parentReference=resource://dev/123456789012/secretsmanager/SecretsManager_Secret_001
desired.row.002-001.property=SecretsManager.RotationSchedule.RotateImmediatelyOnUpdate
desired.row.002-001.value=`false`
desired.row.002-001.comment=更新直後のrotation実行設定
desired.row.002-002.property=SecretsManager.RotationSchedule.RotationRules.AutomaticallyAfterDays
desired.row.002-002.value=`30`
desired.row.002-002.comment=rotationの間隔日数
desired.row.002-003.property=SecretsManager.RotationSchedule.SecretId
desired.row.002-003.value=resource://dev/123456789012/secretsmanager/SecretsManager_Secret_001
desired.row.002-003.comment=対象secretのID
desired.resource.003.resourceType=SecretsManager.Secret
desired.resource.003.logicalId=SecretsManager_Secret_002
desired.resource.003.cfn-logicalId=fixture-AppToken
desired.row.003-001.property=SecretsManager.Secret.Name
desired.row.003-001.value=`app-dev-token`
desired.row.003-001.comment=secretの名前
"""
    assert "desired.resource.004" not in model
    assert "desired.row.002-001.property=SecretsManager.RotationSchedule.RotateImmediatelyOnUpdate" in model
    assert "desired.row.002-002.value=`30`" in model
    assert "desired.row.002-003.value=resource://dev/123456789012/secretsmanager/SecretsManager_Secret_001" in model
    assert "observed.row.002-003" not in model
    values = model_core.properties(model)
    values.update({'display.service.title': '# Secrets Manager 詳細設計',
                   'display.resource.001.comment': '定期更新する連携用key',
                   'display.resource.003.comment': '連携用token',
                   'display.resource.002.label': 'app-dev-key_rotate'})
    rendered = model_design.markdown_for(path, values, REPOSITORY)
    assert rendered == text
    assert not errors(rendered), errors(rendered)
    assert rendered == text
    csv_values = {}
    for key, value in values.items():
        row = re.fullmatch(r"((?:desired|observed)\.row\.002-)([0-9]{3})(\..+)", key)
        if row and int(row.group(2)) >= 1:
            key = row.group(1) + f"{int(row.group(2)) + 1:03d}" + row.group(3)
        csv_values[key] = value
    csv_values.update({
        "desired.row.002-001.property": "SecretsManager.RotationSchedule.HostedRotationLambda.VpcSubnetIds",
        "desired.row.002-001.value": "`subnet-00000000000000001,  subnet-00000000000000002`",
        "desired.row.002-001.comment": "rotation Lambdaの配置先Subnet",
    })
    csv_view = model_design.markdown_for(path, csv_values, REPOSITORY)
    assert not errors(csv_view), errors(csv_view)
    assert model_design.markdown_for(path, csv_values, REPOSITORY) == csv_view
    assert "HostedRotationLambda.VpcSubnetIds[1]" in csv_view and "HostedRotationLambda.VpcSubnetIds[2]" in csv_view
    for invalid, message in (
        (text.replace("### SecretsManager.Secret: app-dev-key", "### SecretsManager.RotationSchedule: app-dev-key"), "independent heading"),
        (text.replace("### SecretsManager.Secret: app-dev-key", "### S3.Bucket: app-dev-key"), "wrong parent"),
        (text.replace("[app-dev-key](#secretsmanager-app-dev-key)", "[app-dev-token](#secretsmanager-app-dev-token)"), "must reference enclosing"),
        (text.replace("RotationRules.AutomaticallyAfterDays", "RotateImmediatelyOnUpdate"), "duplicate property"),
        (text.replace("`30`", "`invalid`"), "provider schema violation"),
        (text.replace("### SecretsManager.Secret\n", "### SecretsManager.RotationSchedule\n"), "resource overview types"),
    ):
        failures = errors(invalid)
        assert any(message in error for error in failures), (message, failures)


def check_codebuild_variable_display(tmp_path, catalog) -> None:
    codebuild = CODEBUILD.replace('| 6 | Environment.Variables.SECOND | `cde` | 環境変数の値 |', '| 6 | Environment.Variables.SECOND | [venus-dev-snowflake-cicd-keypair-cde](secretsmanager.md#secretsmanager-snowflakekey) | <!-- codebuild-variable-type: SECRETS_MANAGER --> 環境変数の参照先 |')
    root = tmp_path
    path = root / "docs/designs/dev/123456789012/codebuild.md"
    path.parent.mkdir(parents=True)
    secret = path.with_name("secretsmanager.md")
    secret.write_text("""# Secrets Manager 詳細設計
<a id="secretsmanager-snowflakekey"></a>
### SecretsManager.Secret: SnowflakeKey
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `venus-dev-snowflake-cicd-keypair-cde` | secretの名前 |
""", encoding="utf-8")

    def errors(content: str) -> list[str]:
        path.write_text(content, encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
        validator.check_design_tables({path: ("codebuild", ("CodeBuild.Project",))}, *catalog)
        validator.check_design_links(catalog[2])
        return diagnostics(validator)

    assert not errors(codebuild), errors(codebuild)
    model = "\n".join(expanded_display_rows(codebuild.splitlines()))
    assert "| CodeBuild.Project.Environment.EnvironmentVariables[].Name | `FIRST` |" in model
    assert "| CodeBuild.Project.Environment.EnvironmentVariables[].Type | `PLAINTEXT` |" in model
    assert "| CodeBuild.Project.Environment.EnvironmentVariables[].Value | `hello:world` |" in model
    assert "| CodeBuild.Project.Environment.EnvironmentVariables[].Name | `SECOND` |" in model
    assert "| CodeBuild.Project.Environment.EnvironmentVariables[].Type | `SECRETS_MANAGER` |" in model
    secret_link = "[venus-dev-snowflake-cicd-keypair-cde](secretsmanager.md#secretsmanager-snowflakekey)"
    assert f"| CodeBuild.Project.Environment.EnvironmentVariables[].Value | {secret_link} |" in model
    assert "codebuild-variable-type" not in model
    assert "Environment.Variables." not in model
    short = codebuild
    assert "| Artifacts.Type |" in short
    assert not errors(short), errors(short)
    assert "\n".join(expanded_display_rows(path.read_text().splitlines())) == model
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
    assert "[venus-dev-snowflake-cicd-keypair-cde:private-key:AWSCURRENT](secretsmanager.md#secretsmanager-snowflakekey)" in "\n".join(expanded_display_rows(path.read_text().splitlines()))
    literal_link = codebuild.replace("SECRETS_MANAGER -->", "PLAINTEXT -->")
    assert not errors(literal_link), errors(literal_link)
    assert "| CodeBuild.Project.Environment.EnvironmentVariables[].Type | `PLAINTEXT` |" in "\n".join(expanded_display_rows(path.read_text().splitlines()))
    parameter_link = codebuild.replace("SECRETS_MANAGER -->", "PARAMETER_STORE -->")
    expanded = "\n".join(expanded_display_rows(parameter_link.splitlines()))
    assert "| CodeBuild.Project.Environment.EnvironmentVariables[].Type | `PARAMETER_STORE` |" in expanded
    other_target = path.parent.parent / "987654321098"
    other_target.mkdir()
    shutil.copy(secret, other_target / secret.name)
    assert errors(codebuild.replace("(secretsmanager.md#", "(../987654321098/secretsmanager.md#"))
    secret.write_text(secret.read_text(encoding="utf-8").replace("SecretsManager.Secret:", "S3.Bucket:"), encoding="utf-8")
    assert errors(codebuild)


def check_codebuild_vpc_display(tmp_path, catalog) -> None:
    vpc_rows = """| 11 | VpcConfig.Subnets[1] | [subnet-00000000000000001](vpc.md#vpc-sbnt-one) | 1つ目のprivate subnet |
| 12 | VpcConfig.Subnets[2] | [subnet-00000000000000002](vpc.md#vpc-sbnt-two) | 2つ目のprivate subnet |
| 13 | VpcConfig.SecurityGroupIds[1] | [PENDING_DEPLOY](security-group.md#security-group-codebuild-sg) | buildに適用するSecurity Group |
"""
    design_text = CODEBUILD + vpc_rows
    root = tmp_path
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

    def errors(content: str) -> list[str]:
        path.write_text(content, encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
        validator.design_files = lambda: [path]
        validator.check_design_tables({path: ("codebuild", ("CodeBuild.Project",))}, *catalog)
        validator.design_files = lambda: sorted(design.glob("*.md"))
        validator.check_design_links(catalog[2])
        return diagnostics(validator)

    assert not errors(design_text), errors(design_text)
    model = "\n".join(expanded_display_rows(design_text.splitlines()))
    assert model.count("| CodeBuild.Project.VpcConfig.Subnets |") == 2
    assert "[subnet-00000000000000001](vpc.md#vpc-sbnt-one)" in model
    assert "[subnet-00000000000000002](vpc.md#vpc-sbnt-two)" in model
    assert "| CodeBuild.Project.VpcConfig.SecurityGroupIds |" in model
    assert "[PENDING_DEPLOY](security-group.md#security-group-codebuild-sg)" in model
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


@pytest.mark.parametrize("prop", sorted(SUBNET_LIST_PROPERTIES))
def check_subnet_list_links(prop, tmp_path, catalog):
    root = tmp_path
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
    outputs = catalog[2]
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
                    ["2", "SecretsManager.RotationSchedule.SecretId", "[key](#secretsmanager-key)",
                     '<a id="secretsmanager-key-rotation"></a><!-- logical-id: KeyRotation --> key-rotation：対象secret'],
                    ["4", kind + "." + shown[0][1], shown[0][2], shown[0][3]],
                ]),
            ]) + "\n"
        return "\n".join(["# Subnet参照の設計", "", "<a id=\"owner\"></a>", f"### {kind}: owner", *row_table(shown)]) + "\n"

    def errors(value):
        path.write_text(content(value), encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.design_files = lambda: [path]
        validator.check_design_links(outputs)
        return diagnostics(validator)

    assert not errors("[subnet-00000000000000001](vpc.md#subnet-a)"), (prop, errors("[subnet-00000000000000001](vpc.md#subnet-a)"))
    assert errors("[subnet-00000000000000001](../987654321098/vpc.md#subnet-a)"), prop
    vpc.write_text(subnet.replace("EC2.Subnet:", "EC2.VPC:"), encoding="utf-8")
    assert errors("[subnet-00000000000000001](vpc.md#subnet-a)"), prop
    vpc.write_text(subnet, encoding="utf-8")
    if prop == max(SUBNET_LIST_PROPERTIES):
        print("Subnet list links: PASS (15 properties, same-target Subnet type, grouped RotationSchedule)")


def check_guardduty_feature_display(tmp_path, catalog) -> None:
    root = tmp_path
    path = root / "docs/designs/dev/123456789012/guardduty.md"
    path.parent.mkdir(parents=True)

    def errors(content: str) -> list[str]:
        path.write_text(content, encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
        validator.check_design_tables({path: ("guardduty", ("GuardDuty.Detector",))}, *catalog)
        return diagnostics(validator)

    assert not errors(GUARDDUTY), errors(GUARDDUTY)
    model = "\n".join(expanded_display_rows(GUARDDUTY.splitlines()))
    assert "| GuardDuty.Detector.Features[].Name | `S3_DATA_EVENTS` |" in model
    assert "| GuardDuty.Detector.Features[].Status | `ENABLED` |" in model
    assert "| GuardDuty.Detector.Features[].Name | `EKS_AUDIT_LOGS` |" in model
    assert "Features.S3_DATA_EVENTS" not in model
    short = GUARDDUTY.replace("| GuardDuty.Detector.", "| ")
    assert not errors(short), errors(short)
    assert "\n".join(expanded_display_rows(path.read_text().splitlines())) == model
    assert errors(GUARDDUTY.replace("Features.EKS_AUDIT_LOGS", "Features.S3_DATA_EVENTS"))
    assert errors(GUARDDUTY.replace("`ENABLED`", "`INVALID`"))
    assert errors(GUARDDUTY.replace("Features.S3_DATA_EVENTS | `ENABLED`", "Features[].Name | `S3_DATA_EVENTS`"))


def check_cloudtrail_data_resources(tmp_path, catalog) -> None:
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
    root = tmp_path
    design = root / "docs/designs/dev/123456789012"
    design.mkdir(parents=True)
    path = design / "cloudtrail.md"
    path.write_text(trail, encoding="utf-8")
    (design / "s3.md").write_text(s3, encoding="utf-8")
    (design / "lambda.md").write_text(lambda_design, encoding="utf-8")
    model = "\n".join(expanded_display_rows(trail.splitlines()))
    assert "| CloudTrail.Trail.EventSelectors[].DataResources[].Type | `AWS::S3::Object` |" in model
    assert "| CloudTrail.Trail.EventSelectors[].DataResources[].Values | [data-bucket](s3.md#s3-data-bucket) |" in model
    assert "| CloudTrail.Trail.EventSelectors[].DataResources[].Type | `AWS::Lambda::Function` |" in model
    assert "DataResources[1]" not in model

    def errors(content: str) -> list[str]:
        path.write_text(content, encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
        validator.check_design_tables({path: ("cloudtrail", ("CloudTrail.Trail",))}, *catalog)
        validator.check_design_links(catalog[2])
        return diagnostics(validator)

    assert not errors(trail), errors(trail)
    all_buckets = trail.replace(
        "[data-bucket](s3.md#s3-data-bucket) | S3 object",
        "`All current and future S3 buckets` | S3 object",
    )
    assert not errors(all_buckets), errors(all_buckets)
    original = path.read_bytes()
    all_model = "\n".join(expanded_display_rows(path.read_text().splitlines()))
    assert path.read_bytes() == original
    assert all_model == model.replace(
        "[data-bucket](s3.md#s3-data-bucket)",
        '`["arn:aws:s3"]`', 1,
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


def check_codepipeline_display(tmp_path, catalog) -> None:
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
    root = tmp_path
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
        return diagnostics(validator)

    assert not errors(pipeline), errors(pipeline)
    original = path.read_bytes()
    model = "\n".join(expanded_display_rows(path.read_text().splitlines()))
    assert path.read_bytes() == original
    assert '"PollForSourceChanges":"false"' in model
    assert '"ProjectName":"[build](codebuild.md#codebuild-build)"' in model
    assert model.count("| CodePipeline.Pipeline.Stages[].Actions[].Configuration |") == 3
    assert "Stages[1]" not in model and "Actions[2]" not in model
    assert "RepositoryId" not in "\n".join(expanded_display_rows(repo_path.read_text().splitlines()))
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
    with pytest.raises(ValueError) as error:
        "\n".join(expanded_display_rows(repo_path.read_text().splitlines()))
    assert "must not be displayed" in str(error.value)


def check_config_firehose_references(tmp_path, catalog) -> None:
    from design_layout import is_import_pending_reference
    assert is_import_pending_reference("Config.ConfigurationRecorder.RoleARN", "Pending")
    assert not is_import_pending_reference("Config.ConfigurationRecorder.RoleARN", "`Pending`")
    assert not is_import_pending_reference("Config.DeliveryChannel.S3BucketName", "Pending")
    assert is_import_pending_reference("KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN", "Pending")
    assert not is_import_pending_reference("KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN", "Pending")
    assert not is_import_pending_reference("KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN", "`arn:aws:s3:::dummy`")
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
    directory = tmp_path / "case-0"
    directory.mkdir()
    root = directory
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
        return diagnostics(validator)

    assert not errors(), errors()
    model = "\n".join(expanded_display_rows(config.splitlines()))
    assert f"| Config.ConfigurationRecorder.RoleARN | {role_link} |" in model
    assert "Config.ConfigurationRecorder.RoleName" not in model
    kdf_model = "\n".join(expanded_display_rows(firehose.splitlines()))
    assert "[1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone)" in kdf_model
    assert "[app-data](s3.md#s3-app-data)" in kdf_model
    assert role_link in kdf_model
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
    assert "[PENDING_DEPLOY](kms.md#kms-keytwo)" in "\n".join(expanded_display_rows(pending.splitlines()))

    (target / "iam.md").unlink()
    for role in ("AWSServiceRoleForConfig", "`AWSServiceRoleForConfig`", "`AWSServiceCustom`"):
        service_config = config.replace(role_link, role)
        service_firehose = firehose.replace(role_link, role)
        assert not errors(service_config, service_firehose), errors(service_config, service_firehose)
        service_model = "\n".join(expanded_display_rows(service_config.splitlines()))
        assert f"| Config.ConfigurationRecorder.RoleARN | {role} |" in service_model
        assert "Config.ConfigurationRecorder.RoleName" not in service_model
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

    directory = tmp_path / "case-1"
    directory.mkdir()
    root = directory
    copy_framework(root / 'framework')
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
        "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation",
    }]}) + "\n", encoding="utf-8")
    path = root / "docs/designs/dev/123456789012/config.md"
    path.parent.mkdir(parents=True)
    source = design("config", "Config.ConfigurationRecorder", [
        ("Id", "`PENDING_DEPLOY`"), ("RoleName", "`AWSServiceRoleForConfig`"),
    ]).replace('<a id="config-resource">', '<!-- resource-logical-id: ConfigRecorder -->\n<a id="config-configuration-recorder-recorder">').replace("ConfigurationRecorder: Resource", "ConfigurationRecorder: recorder")
    path.write_text(source, encoding="utf-8")
    values = model_core.properties("""# Synthetic authoritative Model fixture.
desired.service.config.serviceId=config
desired.service.config.ownedCatalogResourceTypes=Config.ConfigurationRecorder
desired.resource.001.resourceType=Config.ConfigurationRecorder
desired.resource.001.logicalId=Config_ConfigurationRecorder_001
desired.resource.001.cfn-logicalId=ConfigRecorder
desired.service.identity.lastAllocated={"Config.ConfigurationRecorder":1}
desired.row.001-001.property=Config.ConfigurationRecorder.Id
desired.row.001-001.value=resource://dev/123456789012/config/Config_ConfigurationRecorder_001
desired.row.001-001.comment=設定する属性
observed.row.001-001.property=Config.ConfigurationRecorder.Id
observed.row.001-001.value=`PENDING_DEPLOY`
observed.row.001-001.comment=設定する属性
desired.row.001-002.property=Config.ConfigurationRecorder.RoleARN
desired.row.001-002.value=`AWSServiceRoleForConfig`
desired.row.001-002.comment=設定する属性
""")
    values.update({"display.service.title": "# Config 詳細設計", "display.resource.001.label": "recorder", "display.resource.001.comment": "AWSリソースの設定を記録するrecorder"})
    model_path = root / "model/dev/123456789012/config.properties"
    model_path.parent.mkdir(parents=True)
    write_model(model_path, "".join(f"{key}={value}\n" for key, value in values.items()))
    path.unlink()
    assert sync_runtime.sync(root, True, "dev", "123456789012") == 0
    assert "| RoleName | `AWSServiceRoleForConfig` |" in path.read_text(encoding="utf-8")
    assert sync_runtime.sync(root, False, "dev", "123456789012") == 0


def check_resource_name_headings(tmp_path) -> None:
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
    root = tmp_path
    path = root / "docs/designs/dev/123456789012/scheduler.md"
    path.parent.mkdir(parents=True)
    metadata = {path: ("scheduler", ("Scheduler.Schedule",))}
    (root / "framework/rules").mkdir(parents=True)
    shutil.copyfile(REPOSITORY / "framework/rules/aws-resource-naming.md", root / "framework/rules/aws-resource-naming.md")
    copy_framework(root / 'framework/rules/aws-resource-naming', relative='rules/aws-resource-naming')

    def errors(markdown):
        path.write_text(markdown, encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.check_resource_names(metadata)
        validator.check_design_overviews()
        validator.check_design_links({})
        return diagnostics(validator)

    assert not errors(text), errors(text)
    identities = resource_logical_ids(text.splitlines())
    assert identities == {("Scheduler.Schedule", name): logical_id}
    assert f'<a id="{anchor}"></a>' in text
    assert len(expanded_design(text.splitlines())[1]) == 0
    assert model_projection.linked_resource(path, f"[{name}](#{anchor})") == ("Scheduler.Schedule", logical_id)
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
    children = expanded_design(named_kms.splitlines())[1]
    assert resource_logical_ids(named_kms.splitlines())[('KMS.Key', 'one')] == 'KeyOne'
    assert children['kms-alias-one']['parentLogicalId'] == 'KeyOne'
    assert children['kms-alias-one']['parentAnchor'] == 'kms-one'
    assert model_projection.linked_resource(path, "[PENDING_DEPLOY](kms.md#kms-one)") == ("KMS.Key", "KeyOne")

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
    assert resource_logical_ids(sg_text.splitlines())[("EC2.SecurityGroup", group_name)] == "TransferSecurityGroup"

    assert resource_logical_ids(text.splitlines()) == {("Scheduler.Schedule", name): logical_id}


def check_quicksight_group_principal_reference(tmp_path) -> None:
    source_property = "QuickSight.DataSource.Permissions[].Principal"
    assert source_property in RESOURCE_REFERENCE_PROPERTIES
    assert RESOURCE_REFERENCE_PROPERTIES[source_property] == ("QuickSight.Group", "GroupName")
    assert "QuickSight.Group.Arn" in HIDDEN_PROPERTIES

    root = tmp_path
    target = root / "docs/designs/dev/123456789012/quicksight.md"
    target.parent.mkdir(parents=True)
    text = """# QuickSight 詳細設計

- Design service ID: `quicksight`
- Owned catalog resource types: `QuickSight.Group`, `QuickSight.DataSource`

## リソース詳細

<!-- resource-logical-id: ReaderGroup -->
<a id="quicksight-reader-group"></a>

### QuickSight.Group: reader-group

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | GroupName | `reader-group` | group name |

<!-- resource-logical-id: Source -->
<a id="quicksight-source"></a>

### QuickSight.DataSource: source

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Permissions[].Principal | [reader-group](#quicksight-reader-group) | 権限を付与するgroup |
"""
    target.write_text(text, encoding="utf-8")

    def errors(design_text: str) -> list[str]:
        target.write_text(design_text, encoding="utf-8")
        validator = VALIDATOR.Validator(root)
        validator.check_design_links({"QuickSight.Group": {"QuickSight.Group.PrincipalId"}}, [target])
        return diagnostics(validator)

    assert not errors(text), errors(text)
    assert errors(text.replace("[reader-group](#quicksight-reader-group)", "[wrong](#quicksight-reader-group)"))
    assert errors(text.replace("[reader-group](#quicksight-reader-group)", "[reader-group](#quicksight-source)"))


def check_workflow(tmp_path, catalog) -> None:
    for kind in LAYOUTS:
        assert formal_property(kind + ".Name", "S3.Bucket") == kind + ".Name"
        assert formal_property(kind + "Extra.Name", "S3.Bucket") == "S3.Bucket." + kind + "Extra.Name"
    assert formal_property("BucketName", "S3.Bucket") == "S3.Bucket.BucketName"
    assert formal_property("BucketName", "") == "BucketName"
    assert not layout_errors(REPOSITORY)
    policy_rows = [
        '<a id="iam-role"></a>', '### IAM.Role: Role',
        '| No. | Property | Value | Source / Comment |',
        '| ---: | --- | --- | --- |',
        '| 1 | RoleName | `role` | roleの名前 |',
        '| 2 | AssumeRolePolicyDocument | [trust](trust.json) | 信頼policy |',
    ]
    assert resources_in(policy_rows)[0].policies[0].property_name == "IAM.Role.AssumeRolePolicyDocument"
    root = tmp_path
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
        return diagnostics(validator)

    assert not errors(), errors()
    original = kms.read_bytes()
    lines, children = expanded_design(KMS.splitlines())
    assert kms.read_bytes() == original
    assert children['kms-aliasone']['resourceType'] == 'KMS.Alias'
    assert children['kms-aliasone']['logicalId'] == 'AliasOne'
    assert children['kms-aliastwo']['logicalId'] == 'AliasTwo'
    assert children['kms-aliastwo']['parentProperty'] == 'KMS.Alias.TargetKeyId'
    assert children['kms-aliastwo']['parentLogicalId'] == 'KeyOne'
    assert children['kms-aliasthree']['parentLogicalId'] == 'KeyTwo'
    model = "\n".join(lines)
    assert '| KMS.Alias.AliasName | `alias/two` |' in model
    assert '| KMS.Key.KeyId | `1234abcd-12ab-34cd-56ef-1234567890ab` |' in model
    assert '| KMS.Key.KeyId | `PENDING_DEPLOY` |' in model
    assert model_projection.linked_resource(s3, "[alias/two](kms.md#kms-aliastwo)") == ("KMS.Alias", "AliasTwo")
    s3_model = "\n".join(expanded_display_rows(S3.splitlines()))
    assert "| S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID | [alias/two](kms.md#kms-aliastwo) |" in s3_model
    assert "| S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm | `aws:kms` |" in s3_model
    short_s3 = S3.replace("| S3.Bucket.", "| ")
    assert not errors(KMS, short_s3), errors(KMS, short_s3)
    assert "\n".join(expanded_display_rows(s3.read_text().splitlines())) == s3_model
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
    shortened_model = "\n".join(expanded_display_rows(s3.read_text().splitlines()))
    assert "| S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled | `true` |" in shortened_model
    assert "| S3.Bucket.LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NoncurrentDays | `30` |" in shortened_model
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
    moved_children = expanded_design(kms.read_text().splitlines())[1]
    assert moved_children['kms-aliastwo']['logicalId'] == 'AliasTwo'
    assert moved_children['kms-aliastwo']['parentLogicalId'] == 'KeyTwo'
    assert moved_children['kms-aliastwo']['parentAnchor'] == 'kms-keytwo'

    # A new catalog type cannot silently inherit an independent display decision.
    copy_framework(root / 'framework/materials/aws', relative='materials/aws')
    copy_framework(root / 'framework/materials/api', relative='materials/api')
    layout_path = root / "framework/rules/resource-layout.json"
    layout_path.parent.mkdir(parents=True)
    layout_path.write_text(json.dumps(LAYOUTS), encoding="utf-8")
    assert not layout_errors(root)
    (root / "framework/materials/aws/Example_Child.properties").write_text("Example.Child.Name=\n", encoding="utf-8")
    assert any("unclassified=['Example.Child']" in error for error in layout_errors(root))
    broken = {**LAYOUTS, "Example.Child": "independent", "KMS.Alias": {**LAYOUTS["KMS.Alias"], "parentProperty": "Missing"}}
    layout_path.write_text(json.dumps(broken), encoding="utf-8")
    assert any("parent property is absent" in error for error in layout_errors(root))


def main():
    return run(__file__, message='design-layout: PASS (grouped identities, QuickSight Group Principal reference, parent changes, invalid designs, catalog coverage)')


if __name__ == "__main__":
    raise SystemExit(main())

