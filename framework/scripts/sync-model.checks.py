#!/usr/bin/env python3
"""Focused self-checks for generated service models."""

from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync-model.py")
SPEC = importlib.util.spec_from_file_location("sync_model", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> None:
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
