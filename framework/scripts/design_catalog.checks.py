#!/usr/bin/env python3
"""Exercise Macie API designs through the existing Markdown/model validator."""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cloudformation_schema import CloudFormationSchemaCatalog
from design_catalog import MACIE_JOB, DesignSchemaCatalog, api_snapshot_errors
from macie_bucket_tables import job_bucket_tables, write_job_bucket_definitions


ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load("validate-blueprint")
MODEL = load("sync-model")
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

<!-- resource-logical-id: Session -->
<a id="macie-session"></a>

### Macie.Session: session

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | AwsAccountId | `123456789012` | Macieを使用するAWS accountのID |
| 2 | Status | `ENABLED` | Macieの有効状態 |

<!-- resource-logical-id: Job -->
<a id="macie-daily-data-scan"></a>

### Macie.ClassificationJob: daily-data-scan

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
"""
    order = [line.partition("=")[0].removeprefix(MACIE_JOB + ".") for line in (ROOT / "framework/materials/api/Macie_ClassificationJob.properties").read_text().splitlines()]
    for number, key in enumerate(sorted(values, key=lambda key: order.index(key) if key in order else len(order)), 1):
        value = values[key]
        raw = value if isinstance(value, str) else json.dumps(value)
        cell = "[対象条件](macie/job-scope.json)" if key == "s3JobDefinition" and isinstance(value, dict) and value.get("bucketDefinitions") else f"`{raw}`"
        text += f"| {number} | {key} | {cell} | Jobの{key}を設定する項目 |\n"
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


def main():
    assert not api_snapshot_errors(ROOT)
    catalog = DesignSchemaCatalog(ROOT)
    assert catalog.cloudformation_type("Macie.Session") == "AWS::Macie::Session"
    for resource_type in (MACIE_JOB, "Macie.Unknown"):
        try:
            catalog.cloudformation_type(resource_type)
        except (ValueError, KeyError):
            pass
        else:
            raise AssertionError(f"unsupported CFn type accepted: {resource_type}")
    try:
        CloudFormationSchemaCatalog(ROOT).schema(MACIE_JOB)
    except KeyError:
        pass
    else:
        raise AssertionError("API design leaked into the CFn catalog")
    command = [sys.executable, str(ROOT / "framework/scripts/design_catalog.py"), "--cloudformation-type", MACIE_JOB]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1 and "CloudFormation unsupported" in result.stdout

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        design = root / "docs/designs/dev/123456789012/macie.md"
        model = root / "model/dev/123456789012/macie.properties"
        design.parent.mkdir(parents=True)
        model.parent.mkdir(parents=True)
        schema = DesignSchemaCatalog(root)
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
        # Isolated fixture rule: production intentionally rejects the unregistered Job name.
        naming = root / "framework/rules/aws-resource-naming.md"
        naming.write_text(naming.read_text() + "\n| Fixture | Job | `Macie.ClassificationJob` | `name` | `{{purpose}}` |\n")

        def check(values=VALUES, text=None):
            artifact = design.with_suffix("") / "job-scope.json"
            if text is None and isinstance(values.get("s3JobDefinition"), dict) and values["s3JobDefinition"].get("bucketDefinitions"):
                artifact.parent.mkdir(exist_ok=True)
                artifact.write_text(json.dumps(values["s3JobDefinition"], indent=2) + "\n", encoding="utf-8")
            elif text is None and artifact.is_file():
                artifact.unlink()
            design.write_text(text if text is not None else markdown(values), encoding="utf-8")
            model.write_text(MODEL.imported_model(design, root), encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = schema
            validator.accounts = {("dev", "123456789012"): {}}
            validator.check_designs()
            return validator.errors

        assert not check(), check()
        pending = model.read_text()
        assert f"desired.resource.002.resourceType={MACIE_JOB}" in pending
        assert "desired.row.002-002.value=[Job](#macie-daily-data-scan)" in pending
        assert "observed.row.002-002.value=`PENDING_DEPLOY`" in pending
        assert "desired.row.002-004.value=" in pending
        assert "observed.row.002-004" not in pending
        assert not check({**VALUES, "jobId": "0123456789abcdef0123456789abcdef"})
        assert "observed.row.002-002.value=`0123456789abcdef0123456789abcdef`" in model.read_text()
        assert "desired.row.002-002.value=[Job](#macie-daily-data-scan)" in model.read_text()
        single = {key: value for key, value in VALUES.items() if key not in {"scheduleFrequency", "initialRun"}}
        assert not check({**single, "jobType": "ONE_TIME"})
        assert not check({**VALUES, "scheduleFrequency": {"weeklySchedule": {"dayOfWeek": "MONDAY"}}})
        assert not check({**VALUES, "scheduleFrequency": {"monthlySchedule": {"dayOfMonth": 31}}})
        assert not check({**VALUES, "managedDataIdentifierSelector": "NONE", "customDataIdentifierIds": ["custom-id"]})
        assert not check({**VALUES, "s3JobDefinition": {"bucketCriteria": {}}}), check({**VALUES, "s3JobDefinition": {"bucketCriteria": {}}})

        bad_values = [
            {key: value for key, value in VALUES.items() if key != "name"},
            {key: value for key, value in VALUES.items() if key != "scheduleFrequency"},
            {**VALUES, "jobType": "ONE_TIME"},
            {**VALUES, "jobType": "OTHER"},
            {**VALUES, "name": "x" * 501},
            {**VALUES, "name": "UNSET"},
            {**VALUES, "samplingPercentage": 101},
            {**VALUES, "samplingPercentage": True},
            {**VALUES, "initialRun": "yes"},
            {**VALUES, "scheduleFrequency": {}},
            {**VALUES, "scheduleFrequency": {"dailySchedule": {}, "weeklySchedule": {"dayOfWeek": "MONDAY"}}},
            {**VALUES, "scheduleFrequency": {"monthlySchedule": {"dayOfMonth": 32}}},
            {**VALUES, "s3JobDefinition": {}},
            {**VALUES, "s3JobDefinition": {"bucketDefinitions": [], "bucketCriteria": {}}},
            {**VALUES, "s3JobDefinition": {"bucketDefinitions": [{"accountId": "bad", "buckets": [1]}]}},
            {**VALUES, "s3JobDefinition": {"bucketDefinitions": [{"accountId": "123456789012"}]}},
            {**VALUES, "s3JobDefinition": {"bucketCriteria": {"typo": True}}},
            {**VALUES, "managedDataIdentifierSelector": "NONE"},
            {**VALUES, "managedDataIdentifierSelector": "INCLUDE"},
            {**VALUES, "managedDataIdentifierIds": ["id"]},
            {**VALUES, "tags": {"team": 3}},
            {**VALUES, "clientToken": "runtime-token"},
            {**VALUES, "jobArn": "arn:aws:macie2:ap-northeast-1:123456789012:classification-job/example"},
            {**VALUES, "jobId": "arn:aws:macie2:ap-northeast-1:123456789012:classification-job/example"},
        ]
        for values in bad_values:
            assert check(values), values
        original_row = next(line for line in markdown(VALUES).splitlines() if "| name |" in line)
        duplicate = markdown(VALUES).replace(original_row, original_row + "\n" + original_row, 1)
        assert any("duplicate API" in error for error in check(text=duplicate))
        assert any("unknown catalog" in error for error in check(text=markdown(VALUES).replace(MACIE_JOB, "Macie.Unknown")))

        # Model document owns fixed bucket mappings; rendered tables must match it.
        artifact = design.with_suffix("") / "job-scope.json"
        text = markdown(VALUES)
        assert not check(text=text), check(text=text)
        assert "desired.row.002-006.artifactSha256=" in model.read_text()
        artifact.write_text(json.dumps({"bucketDefinitions": [{"accountId": "123456789012", "buckets": ["wrong-bucket"]}]}))
        assert any("bucket mapping differs from JSON artifact" in error for error in check(text=text))
        artifact.write_text(json.dumps(VALUES["s3JobDefinition"]))
        assert any("requires a Markdown mapping table" in error for error in check(text=text.split("#### 対象S3 bucket")[0]))
        assert any("missing or duplicate Macie bucket" in error for error in check(text=text.replace("`app-data` |", "`app-data` |\n| [daily-data-scan](#macie-daily-data-scan) | `123456789012` | `app-data` |")))
        assert any("invalid Macie Job/account mapping row" in error for error in check(text=text.replace("[daily-data-scan](#macie-daily-data-scan) | `123456789012`", "[Other](#macie-other) | `123456789012`")))
        s3 = design.with_name("s3.md")
        s3.write_text('<a id="s3-app-data"></a>\n\n### S3.Bucket: app-data\n', encoding="utf-8")
        design.write_text(text.replace("`app-data` |", "[wrong](s3.md#s3-app-data) |"), encoding="utf-8")
        try:
            job_bucket_tables(design)
        except ValueError as error:
            assert "label must match its S3 Bucket" in str(error)
        else:
            raise AssertionError("wrong S3 link label accepted")
        s3.unlink()
        noncontiguous = text.replace("`app-data` |", "`app-data` |\n| [daily-data-scan](#macie-daily-data-scan) | `000000000000` | `other-bucket` |\n| [daily-data-scan](#macie-daily-data-scan) | `123456789012` | `third-bucket` |")
        assert any("account rows must be contiguous" in error for error in check(text=noncontiguous))
        assert not check()
        authoritative = model.read_text()
        doc_key = next(line.split("=", 1)[0] for line in authoritative.splitlines() if line.startswith("desired.row.") and ".document=" in line)
        definition = {**VALUES["s3JobDefinition"], "bucketDefinitions": [{"accountId": "123456789012", "buckets": ["new-bucket"]}], "scoping": {}}
        lines = [doc_key + "=" + json.dumps(definition) if line.startswith(doc_key + "=") else line for line in authoritative.splitlines()]
        model.write_text("\n".join(lines) + "\n")
        assert MODEL.sync(root, True, "dev", "123456789012") == 0
        assert json.loads(artifact.read_text())["bucketDefinitions"][0]["buckets"] == ["new-bucket"]
        assert "scoping" in json.loads(artifact.read_text())
        assert "`new-bucket`" in design.read_text()
        artifact.write_text(json.dumps({"bucketCriteria": {}}))
        try:
            write_job_bucket_definitions(design)
        except ValueError as error:
            assert "conflicts with bucketCriteria" in str(error)
        else:
            raise AssertionError("bucketCriteria accepted with a fixed bucket table")
        artifact.write_text('{"unknown":true}')
        assert any("API schema violation" in error for error in check(text=text))
        artifact.unlink()
        assert not check()
        model.write_text(model.read_text() + "desired.extra=stale\n")
        validator = VALIDATOR.Validator(root)
        validator.check_generated_service_models()
        assert validator.errors
        snapshot = root / "framework/materials/api/Macie_ClassificationJob.json"
        snapshot.write_text(snapshot.read_text() + "\n")
        assert api_snapshot_errors(root)
    print("design-catalog: PASS (Macie designs, constraints, model, CFn boundary, snapshot integrity)")


if __name__ == "__main__":
    main()
