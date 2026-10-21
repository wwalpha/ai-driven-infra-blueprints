"""Exercise Macie API designs through the existing Markdown/model validator."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model.files import read_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model

import sync_runtime

import model.projection as model_projection

import json

import os

import shutil

import subprocess

import tempfile

from support.validator import load

from array_display import indexed_rows

from model.display import row_table

from cloudformation_schema import CloudFormationSchemaCatalog, manifest_text

from design_catalog import MACIE_JOB, QUICKSIGHT_GROUP, DesignSchemaCatalog, api_snapshot_errors

from macie_bucket_tables import job_bucket_tables, write_job_bucket_definitions

ROOT = Path(__file__).resolve().parents[4]

VALIDATOR = load("validate-blueprint")

VALUES = {
    "name": "daily-data-scan",
    "jobId": "PENDING_DEPLOY",
    "jobType": "SCHEDULED",
    "s3JobDefinition": {"bucketDefinitions": [{"accountId": "123456789012", "buckets": ["app-data"]}]},
    "scheduleFrequency": {"dailySchedule": {}},
    "initialRun": False,
    "samplingPercentage": 100,
    "managedDataIdentifierSelector": "RECOMMENDED",
}

def markdown(values):
    text = """# Macie 詳細設計

- Design service ID: `macie`
- Owned catalog resource types: `Macie.Session`, `Macie.ClassificationJob`

## リソース一覧

### Macie.Session

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [session](#macie-session) | 機密データ検出を有効にするsession |

### Macie.ClassificationJob

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [daily-data-scan](#macie-daily-data-scan) | 対象データを検査するjob |

## リソース詳細

<!-- resource-logical-id: Macie_Session_001 -->
<a id="macie-session"></a>

### Macie.Session: session

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | AwsAccountId | `123456789012` | Macieを使用するAWS accountのID |
| 2 | Status | `ENABLED` | Macieの有効状態 |

<!-- resource-logical-id: Macie_ClassificationJob_001 -->
<a id="macie-daily-data-scan"></a>

### Macie.ClassificationJob: daily-data-scan

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
"""
    order = [line.partition("=")[0].removeprefix(MACIE_JOB + ".") for line in (ROOT / 'framework/materials/api/Macie_ClassificationJob.properties').read_text(encoding="utf-8").splitlines()]
    rows = []
    for number, key in enumerate(sorted(values, key=lambda key: order.index(key) if key in order else len(order)), 1):
        value = values[key]
        raw = value if isinstance(value, str) else json.dumps(value)
        cell = "[対象条件](macie/job-scope.json)" if key == "s3JobDefinition" and isinstance(value, dict) and value.get("bucketDefinitions") else f"`{raw}`"
        rows.append([str(number), key, cell, f"Jobの{key}を設定する項目"])
    text += "\n".join(row_table(indexed_rows(rows, MACIE_JOB))[2:]) + "\n"
    scope = values.get("s3JobDefinition", {})
    if isinstance(scope, dict) and scope.get("bucketDefinitions"):
        text += "\n#### 対象S3 bucket\n\n| Job | AWS account ID | Bucket |\n| --- | --- | --- |\n"
        for definition in scope["bucketDefinitions"]:
            if not isinstance(definition, dict) or not isinstance(definition.get("buckets"), list) or not isinstance(definition.get("accountId"), str):
                continue
            for bucket in definition["buckets"]:
                if isinstance(bucket, str):
                    text += f"| [daily-data-scan](#macie-daily-data-scan) | `{definition['accountId']}` | `{bucket}` |\n"
    return text.replace("| [daily-data-scan](#macie-daily-data-scan) | SCHEDULED |", f"| [daily-data-scan](#macie-daily-data-scan) | {values.get('jobType', '')} |")

def quicksight_group_markdown():
    return """# QuickSight 詳細設計

- Design service ID: `quicksight`
- Owned catalog resource types: `QuickSight.Group`

## リソース一覧

### QuickSight.Group

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [reader-group](#quicksight-reader-group) | 閲覧者group |

## リソース詳細

<!-- resource-logical-id: ReaderGroup -->
<a id="quicksight-reader-group"></a>

### QuickSight.Group: reader-group

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | AwsAccountId | `123456789012` | QuickSight accountのID |
| 2 | Namespace | `default` | groupが属するnamespace |
| 3 | GroupName | `reader-group` | group name |
| 4 | PrincipalId | `PENDING_DEPLOY` | group principal ID |
"""


__all__ = ['CloudFormationSchemaCatalog', 'DesignSchemaCatalog', 'MACIE_JOB', 'Path', 'QUICKSIGHT_GROUP', 'ROOT', 'VALIDATOR', 'VALUES', 'api_snapshot_errors', 'indexed_rows', 'job_bucket_tables', 'json', 'load', 'manifest_text', 'markdown', 'model_projection', 'os', 'quicksight_group_markdown', 'read_model', 'row_table', 'shutil', 'subprocess', 'sync_runtime', 'sys', 'tempfile', 'write_job_bucket_definitions', 'write_model']
