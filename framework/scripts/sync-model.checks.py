#!/usr/bin/env python3
"""Focused self-checks for generated service models."""

from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import io
import json
import shutil
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from design_catalog import property_paths_with_parents


SCRIPT = Path(__file__).with_name("sync-model.py")
SPEC = importlib.util.spec_from_file_location("sync_model", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def check_failure_counts() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(SCRIPT.parents[1], root / "framework")
        models = root / "model/dev/non-cde"
        docs = root / "docs/designs/dev/non-cde"
        models.mkdir(parents=True)
        docs.mkdir(parents=True)
        for number in range(17):
            (models / f"service-{number:02d}.properties").write_text("fixture.value=test\n")
            (docs / f"service-{number:02d}.md").write_text("generated\n")

        def render(path, values, stage):
            if int(path.stem.removeprefix("service-")) < 9:
                raise ValueError("fixture render failure")
            return "generated\n"

        # Five rejected references produce five diagnostics for one failed service.
        broken = {f"reference-{number}": docs / "service-09.md" for number in range(5)}
        for extra_inputs in (False, True):
            if extra_inputs:
                (models / "invalid.properties").write_text("invalid properties\n")
                (docs / "orphan.md").write_text("saved Markdown\n")
            for write in (False, True):
                with patch.object(MODULE, "validate_required_properties"), \
                     patch.object(MODULE, "markdown_for", side_effect=render), \
                     patch.object(MODULE, "rendered_design", return_value="generated\n"), \
                     patch.object(MODULE, "validate_views"), \
                     patch.object(MODULE, "broken_design_links", side_effect=[{}, broken, {}]), \
                     redirect_stdout(io.StringIO()):
                    try:
                        MODULE.sync(root, write, "dev", "non-cde")
                    except ValueError as error:
                        failed, diagnostics = (12, 16) if extra_inputs else (10, 14)
                        assert str(error).splitlines()[0] == f"7 services succeeded; {failed} services failed; {diagnostics} diagnostics", error
                        assert len(str(error).splitlines()) == diagnostics + 1, error
                        assert str(error).count("candidate breaks saved reference") == 5, error
                        if extra_inputs:
                            assert "invalid or duplicate model property" in str(error), error
                            assert "authoritative model missing" in str(error), error
                    else:
                        raise AssertionError("partial generation failure accepted")
    print("Failure counts: PASS (17 models, 7 successes, 10 failed services, 14 diagnostics, invalid/missing models, read/write)")


def check_required_preflight() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(SCRIPT.parents[1], root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
        model = root / "model/dev/123456789012/quicksight.properties"
        model.parent.mkdir(parents=True)
        values = {
            "desired.service.quicksight.serviceId": "quicksight",
            "desired.service.quicksight.ownedCatalogResourceTypes": "QuickSight.DataSource",
            "desired.resource.001.resourceType": "QuickSight.DataSource",
            "desired.resource.001.logicalId": "AthenaSource",
            "desired.resource.001.anchor": "quicksight-qs-app-dev-athena",
            "display.service.title": "# QuickSight 詳細設計",
            "display.resource.001.comment": "分析用データソース",
            "desired.row.001-001.property": "QuickSight.DataSource.Name",
            "desired.row.001-001.value": "`qs-app-dev-athena`",
            "desired.row.001-001.comment": "データソースの名前",
            "desired.row.001-002.property": "QuickSight.DataSource.Credentials.KeyPairCredentials",
            "desired.row.001-002.value": "[設定](quicksight/credentials.json)",
            "desired.row.001-002.document": '{"KeyPairUsername":"test","PrivateKey":"test"}',
            "desired.row.001-002.comment": "接続の認証設定",
        }
        source = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
        model.write_text(source)
        design = root / "docs/designs/dev/123456789012/quicksight.md"
        artifact = design.with_suffix("") / "credentials.json"
        for existing in (False, True):
            if existing:
                artifact.parent.mkdir(parents=True)
                design.write_text("existing Markdown\n")
                artifact.write_text("existing JSON\n")
            for write in (False, True):
                # Neither the renderer nor artifact writer may run for this service.
                with patch.object(MODULE, "markdown_for", side_effect=AssertionError("rendered before preflight")), \
                     patch.object(MODULE, "save_files", side_effect=AssertionError("wrote before preflight")):
                    try:
                        MODULE.sync(root, write, "dev", "123456789012")
                    except ValueError as error:
                        assert "AthenaSource: required provider schema property missing: QuickSight.DataSource.Type" in str(error)
                    else:
                        raise AssertionError("incomplete model accepted")
                assert model.read_text() == source
                assert design.exists() == existing and artifact.exists() == existing
                if existing:
                    assert design.read_text() == "existing Markdown\n"
                    assert artifact.read_text() == "existing JSON\n"
        try:
            MODULE.markdown_for(design, values, root)
        except ValueError as error:
            assert "QuickSight.DataSource.Type" in str(error)
        else:
            raise AssertionError("direct renderer accepted missing Type")
        complete = values | {
            "desired.row.001-003.property": "QuickSight.DataSource.Type",
            "desired.row.001-003.value": "`ATHENA`",
            "desired.row.001-003.comment": "データソースの接続方式",
        }
        MODULE.validate_required_properties(complete, root)
        for empty in ("", "``", '`""`', "`UNSET`"):
            try:
                MODULE.validate_required_properties(complete | {"desired.row.001-003.value": empty}, root)
            except ValueError as error:
                assert "QuickSight.DataSource.Type" in str(error)
            else:
                raise AssertionError("empty required value accepted")
        grouped = complete | {
            "desired.resource.001.resourceType": "S3.Bucket",
            "desired.row.001-001.property": "S3.Bucket.BucketName",
            "desired.row.001-002.property": "S3.BucketPolicy.PolicyDocument",
            "desired.row.001-002.value": "",
        }
        try:
            MODULE.validate_required_properties(grouped, root)
        except ValueError as error:
            assert "S3.BucketPolicy.PolicyDocument" in str(error)
            assert "S3.BucketPolicy.Bucket" not in str(error)
        else:
            raise AssertionError("empty grouped required value accepted")
        # An unrelated valid service still saves while the incomplete one fails.
        stack = model.with_name("cloudformation-stacks.properties")
        stack.write_text("desired.stack.001.name=cfn-stack-app-dev-general-01\n"
                         "desired.stack.001.template=app.yaml\n"
                         "desired.stack.001.parameters=app.json\n"
                         "desired.stack.001.deployOrder=10\n"
                         "display.stack.001.comment=アプリケーションのstack\n")
        with redirect_stdout(io.StringIO()):
            try:
                MODULE.sync(root, True, "dev", "123456789012")
            except ValueError as error:
                assert "1 services succeeded; 1 services failed; 1 diagnostics" in str(error), error
            else:
                raise AssertionError("partial failure accepted")
        assert design.with_name("cloudformation-stacks.md").is_file()
        assert design.read_text() == "existing Markdown\n" and artifact.read_text() == "existing JSON\n"
    print("Required-property preflight: PASS (new/existing, read/write, direct renderer, partial success)")


def check_required_property_parents() -> None:
    paths = {"ConnectionInput.PhysicalConnectionRequirements.SubnetId", "Rules[].Target.Name", "ConnectionInputName"}
    assert property_paths_with_parents(paths) == {
        *paths, "ConnectionInput", "ConnectionInput.PhysicalConnectionRequirements", "Rules", "Rules[]", "Rules[].Target",
    }
    assert "ConnectionInput" not in property_paths_with_parents({"ConnectionInputName"})
    assert not property_paths_with_parents(set())
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(SCRIPT.parents[1], root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
        model = root / "model/dev/123456789012/glue.properties"
        model.parent.mkdir(parents=True)
        values = {
            "desired.service.glue.serviceId": "glue",
            "desired.service.glue.ownedCatalogResourceTypes": "Glue.Connection",
            "desired.resource.001.resourceType": "Glue.Connection",
            "desired.resource.001.logicalId": "Connection",
            "desired.resource.001.anchor": "glue-sample",
            "display.service.title": "# AWS Glue 詳細設計",
            "display.resource.001.comment": "データ取得に使用する接続",
        }
        for number, (field, value) in enumerate((
            ("ConnectionInput.Name", "`sample`"),
            ("Name", "[Connection](#glue-sample)"),
            ("CatalogId", "`123456789012`"),
            ("ConnectionInput.ConnectionType", "`JDBC`"),
            ("ConnectionInput.PhysicalConnectionRequirements.AvailabilityZone", "`ap-northeast-1a`"),
            ("ConnectionInput.ValidateCredentials", "`true`"),
        ), 1):
            key = f"001-{number:03d}"
            comment = "一意に識別するID" if field == "Name" else "接続の設定"
            values.update({f"desired.row.{key}.property": "Glue.Connection." + field,
                           f"desired.row.{key}.value": value, f"desired.row.{key}.comment": comment})
        values.update({"observed.row.001-002.property": "Glue.Connection.Name",
                       "observed.row.001-002.value": "`sample`", "observed.row.001-002.comment": "一意に識別するID"})
        source = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
        model.write_text(source)
        design = root / "docs/designs/dev/123456789012/glue.md"
        MODULE.validate_required_properties(values, root)
        assert MODULE.sync(root, True, "dev", "123456789012") == 0
        assert model.read_text() == source
        assert "| ConnectionInput |" not in design.read_text()  # Presence is inferred without inventing a row.

        def design_errors(content):
            design.write_text(content)
            validator = MODULE.view_validator(root, root)
            validator.check_design_tables({design: ("glue", ("Glue.Connection",))}, *validator.catalog_design_properties())
            return validator.errors

        original = design.read_text()
        assert not design_errors(original), design_errors(original)
        for missing in ("ConnectionInput", "CatalogId"):
            removed = {key.rsplit(".", 1)[0] for key, value in values.items()
                       if key.endswith(".property") and (value == f"Glue.Connection.{missing}" or value.startswith(f"Glue.Connection.{missing}."))}
            incomplete = {key: value for key, value in values.items() if key.rsplit(".", 1)[0] not in removed}
            try:
                MODULE.validate_required_properties(incomplete, root)
            except ValueError as error:
                assert f"required provider schema property missing: Glue.Connection.{missing}" in str(error)
            else:
                raise AssertionError("missing required property accepted")
            content = "\n".join(line for line in original.splitlines()
                                if f" | {missing} |" not in line and f" | {missing}." not in line) + "\n"
            assert any(f"Glue.Connection.{missing}" in error and "required provider schema property missing" in error for error in design_errors(content))
        assert any("provider schema violation" in error for error in design_errors(original.replace("`true`", "`not-a-boolean`")))
    print("Required-property parents: PASS (Glue generation, design validation and true missing inputs)")


def main() -> None:
    check_failure_counts()
    check_required_preflight()
    check_required_property_parents()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        materials = root / "framework" / "materials" / "aws"
        materials.mkdir(parents=True)
        (materials / "EC2_VPC.properties").write_text(
            "EC2.VPC.VpcId=IDENTIFIER_OUTPUT\n", encoding="utf-8"
        )
        (materials / "EC2_Subnet.properties").write_text(
            "EC2.Subnet.SubnetId=IDENTIFIER_OUTPUT\nEC2.Subnet.VpcId=\n", encoding="utf-8"
        )
        (materials / "S3_Bucket.properties").write_text(
            "S3.Bucket.BucketName=\n"
            "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[]"
            ".ServerSideEncryptionByDefault.KMSMasterKeyID=\n"
            "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[]"
            ".ServerSideEncryptionByDefault.SSEAlgorithm=\n"
            "S3.Bucket.VersioningConfiguration.Status=\n",
            encoding="utf-8",
        )
        (materials / "S3_BucketPolicy.properties").write_text(
            "S3.BucketPolicy.Bucket=\nS3.BucketPolicy.PolicyDocument=\n",
            encoding="utf-8",
        )
        (materials / "KMS_Alias.properties").write_text(
            "KMS.Alias.AliasName=\nKMS.Alias.TargetKeyId=\n", encoding="utf-8"
        )
        design = root / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
        artifact = design.parent / "vpc" / "vpc01-policy.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text(
            '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
            encoding="utf-8",
        )
        design.write_text(
            """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`

## リソース詳細

<a id="vpc-vpc-app-dev"></a>

### EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | PENDING_DEPLOY | VPCを一意に識別するID |
| 2 | CidrBlock | 10.1.0.0/16 | VPCで使用するIPv4アドレス範囲 |
| 3 | Name | vpc-app-dev | VPCを識別するNameタグの値 |
| 4 | PolicyDocument | [policy](vpc/vpc01-policy.json) | VPCに適用するpolicy文書 |

<a id="vpc-sbnt-app-dev-private-01"></a>

### EC2.Subnet: sbnt-app-dev-private-01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | SubnetId | PENDING_DEPLOY | Subnetを一意に識別するID |
| 2 | VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
| 3 | Name | sbnt-app-dev-private-01 | Subnetを識別するNameタグの値 |
""",
            encoding="utf-8",
        )
        model = MODULE.model_for(design, root)
        assert "desired.service.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet" in model
        assert "desired.resource.001.logicalId=vpc-app-dev" in model
        assert "desired.row.001-001.value=[vpc-app-dev](#vpc-vpc-app-dev)" in model
        assert "observed.row.001-001.value=PENDING_DEPLOY" in model
        assert "desired.row.001-002.value=10.1.0.0/16" in model
        assert "desired.row.001-003.property=EC2.VPC.Name" in model
        assert "desired.row.001-004.artifactSha256=" in model
        assert "desired.row.002-001.value=[sbnt-app-dev-private-01](#vpc-sbnt-app-dev-private-01)" in model
        assert "observed.row.002-001.value=PENDING_DEPLOY" in model
        assert "desired.row.002-002.value=[vpc-app-dev](#vpc-vpc-app-dev)" in model
        assert "desired.row.002-003.property=EC2.Subnet.Name" in model
        assert model == MODULE.model_for(design, root)

        s3_design = design.with_name("s3.md")
        s3_artifact = s3_design.parent / "s3" / "app-data-bucket-policy.json"
        s3_artifact.parent.mkdir(parents=True)
        s3_artifact.write_text(
            '{"Version":"2012-10-17","Statement":[]}\n', encoding="utf-8"
        )
        kms_design = design.with_name("kms.md")
        kms_design.write_text(
            """# AWS KMS 詳細設計

- Design service ID: `kms`
- Owned catalog resource types: `KMS.Key`, `KMS.Alias`

## リソース詳細

<a id="kms-appdatakey"></a>

### KMS.Key: AppDataKey

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | 1234abcd-12ab-34cd-56ef-1234567890ab | KMS keyを識別するID |
| 2 | KMS.Alias.AliasName | alias/app-data | <a id="kms-appdatakeyalias"></a><!-- logical-id: AppDataKeyAlias --> application data用keyを識別するalias |
""",
            encoding="utf-8",
        )
        s3_design.write_text(
            """# Amazon S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`, `S3.BucketPolicy`

## リソース一覧

### S3.Bucket

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |

## リソース詳細

<a id="s3-app-dev-data-123456789012"></a>

### S3.Bucket: app-dev-data-123456789012

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | app-dev-data-123456789012 | application dataを格納するbucketの名前 |
| 2 | Region | us-east-1 | bucketを配置するAWS region |
| 3 | BucketEncryption[].KMSMasterKeyID | [alias/app-data](kms.md#kms-appdatakeyalias) | 新規objectのdefault暗号化に使用するKMS key alias |
| 4 | BucketEncryption[].SSEAlgorithm | aws:kms | 暗号化方式 |
| 5 | VersioningConfiguration.Status | Enabled | objectのversion保持状態 |
| 6 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |
""",
            encoding="utf-8",
        )
        s3_model = MODULE.model_for(s3_design, root)
        assert "desired.resource.001.resourceType=S3.Bucket" in s3_model
        assert "desired.resource.001.logicalId=app-dev-data-123456789012" in s3_model
        assert "desired.resource.002." not in s3_model
        assert "desired.row.001-001.property=S3.Bucket.BucketName" in s3_model
        assert "desired.row.001-002.property=S3.Bucket.Region" in s3_model
        assert "desired.row.001-002.value=us-east-1" in s3_model
        assert "desired.row.001-003.value=[alias/app-data](kms.md#kms-appdatakeyalias)" in s3_model
        assert "desired.row.001-003.property=S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID" in s3_model
        assert "desired.row.001-004.property=S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm" in s3_model
        assert "observed.row.001-003" not in s3_model
        assert "S3.BucketPolicy.Bucket" not in s3_model
        assert "desired.row.001-006.property=S3.BucketPolicy.PolicyDocument" in s3_model
        assert "desired.row.001-006.artifactSha256=" in s3_model
        assert "リソース一覧" not in s3_model
        assert "リソース詳細" not in s3_model
        assert "BucketName | Region" not in s3_model
        original_digest = MODULE.json_sha256(artifact)
        artifact.write_text(
            '{\r\n  "Action": [\r\n    "s3:GetObject"\r\n  ],\r\n'
            '  "Version": "2012-10-17"\r\n}',
            encoding="utf-8",
            newline="",
        )
        assert MODULE.json_sha256(artifact) == original_digest
        artifact.write_text(
            '{"Version":"2012-10-17","Action":["s3:PutObject"]}\n',
            encoding="utf-8",
        )
        assert MODULE.json_sha256(artifact) != original_digest
        artifact.write_text(
            '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
            encoding="utf-8",
        )
        design.write_text(
            design.read_text(encoding="utf-8")
            .replace("VpcId | PENDING_DEPLOY", "VpcId | vpc-0123456789abcdef0")
            .replace("[PENDING_DEPLOY](#vpc-vpc-app-dev)", "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)")
            .replace("SubnetId | PENDING_DEPLOY", "SubnetId | subnet-0123456789abcdef0"),
            encoding="utf-8",
        )
        deployed = MODULE.model_for(design, root)
        assert "observed.row.001-001.value=vpc-0123456789abcdef0" in deployed
        assert "observed.row.002-001.value=subnet-0123456789abcdef0" in deployed
        assert "observed.row.002-002.value=vpc-0123456789abcdef0" in deployed
        with redirect_stdout(io.StringIO()):
            try:
                MODULE.sync(root, True)
            except ValueError as error:
                assert "authoritative model missing" in str(error)
            else:
                raise AssertionError("Markdown must not overwrite authoritative model values")
            assert not (root / "model").exists()

        alias_design = root / "docs" / "designs" / "dev" / "cde" / "vpc.md"
        alias_design.parent.mkdir(parents=True)
        alias_artifact = alias_design.parent / "vpc" / "vpc01-policy.json"
        alias_artifact.parent.mkdir(parents=True)
        alias_artifact.write_text(
            '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
            encoding="utf-8",
        )
        alias_design.write_text(
            design.read_text(encoding="utf-8").replace(
                "vpc-0123456789abcdef0", "vpc-11111111111111111"
            ),
            encoding="utf-8",
        )
        with redirect_stdout(io.StringIO()):
            try:
                MODULE.sync(root, True, "dev", "cde")
            except ValueError as error:
                assert "authoritative model missing" in str(error)
            else:
                raise AssertionError("missing model was silently imported")
        assert not (root / "model" / "dev" / "cde" / "vpc.properties").exists()
        assert MODULE.selected(alias_design, root / "docs" / "designs", "dev", "cde")
        assert not MODULE.selected(alias_design, root / "docs" / "designs", "dev", "123456789012")
        stacks = design.with_name("cloudformation-stacks.md")
        stacks.write_text(
            """# CloudFormation stack 詳細設計

## Deployment設定
| Property | Value |
| --- | ---: |
| MaxConcurrentStacks | 2 |

## Stack一覧
| No. | DeployOrder | StackName | Template | Parameters | Comment |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 10 | stack-job-01 | job.yaml | job-01.json | 日次jobを配置するstack |
| 2 | 10 | stack-job-02 | job.yaml | job-02.json | 月次jobを配置するstack |
""",
            encoding="utf-8",
        )
        stack_model = MODULE.model_for(stacks, root)
        assert "desired.stack.001.template=job.yaml" in stack_model
        assert "desired.stack.002.template=job.yaml" in stack_model
        assert "desired.stack.002.parameters=job-02.json" in stack_model
        assert "日次jobを配置するstack" not in stack_model and ".comment=" not in stack_model
        assert "desired.deployment.maxConcurrentStacks=2" in stack_model
        assert "desired.stack.002.deployOrder=10" in stack_model
        assert "dependsOn" not in stack_model and ".resource." not in stack_model
        with redirect_stdout(io.StringIO()):
            try:
                MODULE.sync(root, True, "dev", "123456789012")
            except ValueError as error:
                assert "authoritative model missing" in str(error)
            else:
                raise AssertionError("stack Markdown was silently imported")
    print("sync-model: PASS (39 focused checks)")


if __name__ == "__main__":
    main()
