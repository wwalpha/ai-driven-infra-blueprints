"""Check grouped identities, references and catalog display coverage end to end."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import re
import shutil

import model.core as model_core
import model.projection as model_projection
import model.render as model_design
import pytest
import sync_runtime
from design_layout import (
    SUBNET_LIST_PROPERTIES,
    expanded_design,
    expanded_display_rows,
    formal_property,
    layout_errors,
    resource_display_name,
    resource_logical_ids,
)
from model.display import display_rows, row_table
from policy_tables import resources_in
from service_rows import pipeline_rows
from support.model_sources import write_model
from support.pytest_cli import run
from support.validator import load
from utils.layout_schema import (
    HIDDEN_PROPERTIES,
    LAYOUTS,
    RESOURCE_REFERENCE_PROPERTIES,
    resource_anchor,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")



REPOSITORY = Path(__file__).resolve().parents[4]

VALIDATOR = load("validate-blueprint")

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
| 3 | KMS.Alias.AliasName | `alias/one` | <a id="resource-AliasOne"></a><!-- logical-id: AliasOne --> KMS keyを識別するalias |
| 4 | KMS.Alias.AliasName | `alias/two` | <a id="resource-AliasTwo"></a><!-- logical-id: AliasTwo --> KMS keyを識別するalias |

<a id="kms-keytwo"></a>

### KMS.Key: KeyTwo

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | `PENDING_DEPLOY` | KMS keyを識別するID |
| 2 | KMS.Alias.AliasName | `alias/three` | <a id="resource-AliasThree"></a><!-- logical-id: AliasThree --> KMS keyを識別するalias |
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
| 3 | BucketEncryption[].KMSMasterKeyID | [alias/two](kms.md#resource-AliasTwo) | 暗号化に使用するKMS alias |
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

@pytest.fixture(scope="module")
def catalog():
    return VALIDATOR.Validator(REPOSITORY).catalog_design_properties()


__all__ = ['CODEBUILD', 'GUARDDUTY', 'HIDDEN_PROPERTIES', 'KMS', 'LAYOUTS', 'Path', 'REPOSITORY', 'RESOURCE_REFERENCE_PROPERTIES', 'S3', 'SUBNET_LIST_PROPERTIES', 'VALIDATOR', 'catalog', 'display_rows', 'expanded_design', 'expanded_display_rows', 'formal_property', 'json', 'layout_errors', 'load', 'model_core', 'model_design', 'model_projection', 'pipeline_rows', 'pytest', 'pytestmark', 're', 'resource_anchor', 'resource_display_name', 'resource_logical_ids', 'resources_in', 'row_table', 'run', 'shutil', 'sync_runtime', 'sys', 'write_model']
