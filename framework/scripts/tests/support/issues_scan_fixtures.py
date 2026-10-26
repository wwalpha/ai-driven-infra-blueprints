"""Isolated local-issues regressions and optional A/B/C fixture benchmark."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from unittest.mock import patch

import issues.records as _imports_issues_records
import model.format as _imports_model_format
import pytest
import sync_files as _imports_sync_files
from comparison import Comparison
from comparison.result import identifier, value_differences
from design.layout import resource_name_fields
from issues.aggregate import aggregate, iac_dataset, iac_summary
from issues.artifact import detail_payload, review_payload, summary
from issues.materials import naming_materials
from issues.publication import save_scan
from issues.reports import iac_report
from issues.runner import mechanical, scan
from model.core import entries, properties
from model.files import load_model, model_file_contents, read_model, resource_row_index
from model.render import markdown_for
from model.sources import model_parts
from model.validation import naming_target_matches, naming_targets
from support.model_sources import snapshot_model, write_fixture_files, write_model
from support.pytest_cli import run
from task_contract_core import SELECTOR
from utils.iac_values import same, selected_same, strict_json
from utils.input_cache import input_scope
from utils.script_loader import module

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


ROOT = Path(__file__).resolve().parents[4]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if (
        path.suffix == ".properties"
        and len(path.parents) > 2
        and path.parents[2].name == "model"
    ):
        values = properties(text)
        for key in list(values):
            if key.startswith("desired.row.") and key.endswith(".property"):
                values.setdefault(key.removesuffix("property") + "comment", "")
        write_model(path, values)
    else:
        write_fixture_files({path: text})


def write_report(path, markdown):
    write(path, markdown)


def render_iac(root, path, environment, directory, services, records, display=None):
    entries, actions, fields = iac_dataset(
        records, environment, directory, services, display
    )
    return iac_report(environment, directory, services, records, display), {
        "entries": entries,
        "actions": actions,
        "value_differences": fields,
    }


def fixture(root, stacks=1, services=("s3", "cloudwatch-logs", "sqs"), parts=False):
    # Only synthetic Project data is created here.
    write(
        root / "issues/dev/123456789012/human-confirmations.yaml",
        json.dumps(
            dict(version=2, environment="dev", target="123456789012", confirmations=[])
        ),
    )
    target = {
        "environment": "dev",
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "iacEngine": "cloudformation",
    }
    write(
        root / "project.json",
        json.dumps({"projectName": "fixture", "targets": [target]}) + "\n",
    )
    specs = {
        "s3": (
            "S3.Bucket",
            "Bucket",
            "BucketName",
            "bucket",
            [("VersioningConfiguration.Status", "`Enabled`")],
        ),
        "cloudwatch-logs": (
            "Logs.LogGroup",
            "Log",
            "LogGroupName",
            "cwlogs",
            [("RetentionInDays", "`7`")],
        ),
        "sqs": (
            "SQS.Queue",
            "Queue",
            "QueueName",
            "sqs",
            [("VisibilityTimeout", "`30`")],
        ),
    }
    values = {
        service: {
            f"desired.service.{service}.serviceId": service,
            f"desired.service.{service}.ownedCatalogResourceTypes": specs[service][0],
            "display.service.title": f"# {service} 詳細設計",
            "desired.note.001.text": "human確認: application=app; environment=dev; purpose=data。例外は対象resourceに明示する。",
        }
        for service in services
    }
    stackvalues = {"desired.deployment.maxConcurrentStacks": "1"}
    resources = {}
    for service in services:
        kind, logical, field, prefix, extra = specs[service]
        resources[logical] = {
            "Type": "AWS::" + kind.replace(".", "::"),
            "Properties": {field: {"Fn::Sub": prefix + "-${Name}"}},
        }
        for prop, value in extra:
            parts_path = prop.split(".")
            node = resources[logical]["Properties"]
            for piece in parts_path[:-1]:
                node = node.setdefault(piece, {})
            node[parts_path[-1]] = (
                json.loads(value.strip("`"))
                if value.strip("`").isdigit()
                else value.strip("`")
            )
        resources[logical]["Properties"]["Tags"] = [
            {"Key": "owner", "Value": "fixture"}
        ]
    # An unrelated resource must not be treated as an excess selected-service issue.
    resources["OtherService"] = {
        "Type": "AWS::EC2::VPC",
        "Properties": {"CidrBlock": "10.0.0.0/16"},
    }
    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": {
            "Name": {"Type": "String"},
            "Enabled": {"Type": "String", "Default": "yes"},
        },
        "Conditions": {"Active": {"Fn::Equals": [{"Ref": "Enabled"}, "yes"]}},
        "Resources": resources,
    }
    write(
        root / "infra/cloudformation/templates/shared.yaml",
        json.dumps(template, indent=2) + "\n",
    )
    for number in range(1, stacks + 1):
        stackname = f"cfn-stack-app-dev-data{number}"
        identity = f"{number:03d}"
        stackvalues.update(
            {
                f"desired.stack.{identity}.name": stackname,
                f"desired.stack.{identity}.template": "shared.yaml",
                f"desired.stack.{identity}.parameters": f"stack-{number}.json",
                f"desired.stack.{identity}.deployOrder": "1",
                f"display.stack.{identity}.comment": "fixture用の独立stack",
            }
        )
        write(
            root
            / f"infra/cloudformation/parameters/dev/123456789012/stack-{number}.json",
            json.dumps(
                [{"ParameterKey": "Name", "ParameterValue": f"app-dev-data{number}"}]
            )
            + "\n",
        )
        for service in services:
            kind, logical, field, prefix, extra = specs[service]
            name = f"{prefix}-app-dev-data{number}"
            values[service].update(
                {
                    f"desired.resource.{identity}.resourceType": kind,
                    f"desired.resource.{identity}.logicalId": kind.replace(".", "_")
                    + "_"
                    + identity,
                    f"desired.resource.{identity}.anchor": service + "-" + name,
                    "desired.service.identity.lastAllocated": json.dumps(
                        {kind: number}
                    ),
                    f"desired.resource.{identity}.cfn-logicalId": stackname
                    + "-"
                    + logical,
                    f"display.resource.{identity}.comment": "fixture用の設定",
                }
            )
            rows = [
                (field, "`" + name + "`"),
                *([("Region", "`ap-northeast-1`")] if service == "s3" else []),
                *extra,
                ("Tags[].Key", "`owner`"),
                ("Tags[].Value", "`fixture`"),
            ]
            if service == "sqs":
                rows.append(("QueueUrl", f"[{name}](#{service}-{name})"))
            for rownumber, (prop, value) in enumerate(rows, 1):
                rid = f"{identity}-{rownumber:03d}"
                values[service].update(
                    {
                        f"desired.row.{rid}.property": kind + "." + prop,
                        f"desired.row.{rid}.value": value,
                        f"desired.row.{rid}.comment": "fixtureの設定値",
                    }
                )
                if prop == "QueueUrl":
                    values[service].update(
                        {
                            f"observed.row.{rid}.property": kind + "." + prop,
                            f"observed.row.{rid}.value": "`PENDING_DEPLOY`",
                            f"observed.row.{rid}.comment": "fixtureの設定値",
                        }
                    )
    write(
        root / "model/dev/123456789012/cloudformation-stacks.properties",
        "\n".join(f"{key}={value}" for key, value in stackvalues.items()) + "\n",
    )
    for service, modelvalues in values.items():
        _ = "\n".join(f"{key}={value}" for key, value in modelvalues.items()) + "\n"
        path = root / f"model/dev/123456789012/{service}.properties"
        write_model(path, modelvalues)
        if parts:
            split = _imports_model_format.split
            save_files = _imports_sync_files.save_files
            save_files(split(path, load_model(path).authoritative, limit=25))
        write(
            root / f"docs/designs/dev/123456789012/{service}.md",
            markdown_for(
                root / f"docs/designs/dev/123456789012/{service}.md", modelvalues, root
            ),
        )
    write(
        root / "docs/designs/dev/123456789012/cloudformation-stacks.md",
        markdown_for(
            root / "docs/designs/dev/123456789012/cloudformation-stacks.md",
            stackvalues,
            root,
        ),
    )
    return values, template


@contextmanager
def task(root, services, name="save", allowed=None):
    reports = [
        "issues/dev/123456789012/issues.md",
        "issues/dev/123456789012/iac-issues.md",
    ]
    files = [f"tasks/{name}.md", *(allowed if allowed is not None else reports)]
    text = "# fixture task\n\n## Task contract\n\n- Task type: `migration`\n- Task status: `running`\n\n"
    text += "## Validation scope\n\n" + "".join(
        f"- `dev/123456789012/{service}`\n" for service in services
    )
    for heading in ("Allowed paths", "Modified files"):
        text += "\n## " + heading + "\n\n" + "".join(f"- `{file}`\n" for file in files)
    write(root / f"tasks/{name}.md", text)
    previous = os.environ.get(SELECTOR)
    os.environ[SELECTOR] = f"tasks/{name}.md"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(SELECTOR, None)
        else:
            os.environ[SELECTOR] = previous
        (root / f"tasks/{name}.md").unlink(missing_ok=True)


def _callback_compare_run(root, services, /):
    comparison = Comparison(root, "dev", "123456789012", services)
    return comparison, comparison.run()


def compare(root, services):
    run = (input_scope)(_bind_framework_callback(_callback_compare_run, root, services))
    return run()


def mutate_template(root, template):
    write(
        root / "infra/cloudformation/templates/shared.yaml",
        json.dumps(template, indent=2) + "\n",
    )


def expect_error(function, phrase=None):
    with pytest.raises((ValueError, OSError, RuntimeError)) as error:
        function()
    assert phrase is None or phrase in str(error.value), str(error.value)


def summary_fixture():
    identifier = _imports_issues_records.identifier
    unknown = [
        dict(
            category="difference",
            service=["s3", "iam", "glue"][i % 3],
            resource=f"u{i:04d}",
            property="Setting",
            reason="cause and repair target unknown",
            stack=None,
            desired=None,
            actual=None,
        )
        for i in range(1000)
    ]
    incomplete = [
        dict(
            category="uncompared",
            service="s3",
            resource=f"c{i:04d}",
            property="Role",
            reason="Export reference unresolved",
            stack="consumer",
            cause={
                "kind": "import-unresolved",
                "export": "shared-export",
                "relationship": "import",
            },
        )
        for i in range(1000)
    ]
    differences = [
        dict(
            category="difference",
            service="glue",
            resource=f"v{i:04d}",
            property=f"Glue.Job.Settings{i % 20}",
            reason="value mismatch",
            stack=f"stack{i % 7}",
            iac={"path": "infra/shared.yaml"},
            desired={f"field{j}": j for j in range(20)},
            actual={f"field{j}": j + 1 for j in range(20)},
        )
        for i in range(100)
    ]
    errors = [
        dict(
            category="error",
            service="iam",
            resource=f"e{i:04d}",
            property="Role",
            reason="Ref attribute resolution failed",
            stack=None,
        )
        for i in range(93)
    ]
    records = unknown + incomplete + differences + errors
    display = {
        identifier(item): value_differences(
            item["desired"], item["actual"], item["property"]
        )
        for item in differences
    }
    names = [
        dict(
            id=identifier(["name", i]),
            service="s3",
            resource=f"{i:04d}",
            property="BucketName",
            value=f"bucket-app-dev-data{i}",
            resourceMode="CREATE",
            comment="human-confirmed application=app",
            pattern_review="required",
        )
        for i in range(1000)
    ]
    judgments = [
        dict(
            id=identifier(["judgment", i]),
            kind="human-components/exceptions",
            service="s3",
            materials="Confirm application component and exception scope",
        )
        for i in range(100)
    ]
    context = dict(rules={}, target_context={}, review_policy="review all")
    artifact = dict(
        version=6,
        scan_id="a" * 32,
        naming_context=context,
        naming_context_id=identifier(context),
        environment="dev",
        target="cde",
        services=["glue", "iam", "s3"],
        target_services=["glue", "iam", "s3"],
        ordinary=[],
        naming=dict(names=names),
        judgments=judgments,
        human_confirmations=dict(
            version=2, environment="dev", target="cde", confirmations=[]
        ),
        checks=1,
        executed_at="2026-10-08T00:00:00Z",
        **aggregate(records, "dev", "cde", ["glue", "iam", "s3"], display),
    )
    return artifact


@pytest.fixture(scope="module", autouse=True)
def protected_sources():
    protected = [
        ROOT / "framework/scripts" / name
        for name in (
            "comparison/runner.py",
            "utils/comparison_rows.py",
            "utils/iac_values.py",
            "iac_evaluation.py",
            "utils/script_loader.py",
            "model/render.py",
            "design/policy_tables.py",
        )
    ]
    protected.extend((ROOT / "framework/scripts/issues").glob("*.py"))
    protected.extend((ROOT / "framework/scripts/comparison").rglob("*.py"))
    protected.append(ROOT / "framework/scripts/utils/cfn_lint.py")
    before = {path: path.read_bytes() for path in protected if path.exists()}
    yield
    assert before == {
        path: path.read_bytes() if path.exists() else None for path in before
    }, "checks changed protected source"


@pytest.fixture
def scan_project(tmp_path):
    root = tmp_path / "project"
    values, template = fixture(root, stacks=3, parts=True)
    return root, values, template


__all__ = [
    "aggregate",
    "review_for",
    "Comparison",
    "Counter",
    "Path",
    "ROOT",
    "SELECTOR",
    "argparse",
    "compare",
    "contextmanager",
    "detail_payload",
    "entries",
    "expect_error",
    "fixture",
    "hashlib",
    "iac_dataset",
    "iac_report",
    "iac_summary",
    "identifier",
    "input_scope",
    "json",
    "load_model",
    "markdown_for",
    "mechanical",
    "model_file_contents",
    "module",
    "mutate_template",
    "naming_materials",
    "naming_target_matches",
    "naming_targets",
    "os",
    "patch",
    "properties",
    "protected_sources",
    "pytest",
    "pytestmark",
    "re",
    "read_model",
    "render_iac",
    "resource_name_fields",
    "resource_row_index",
    "remove_model",
    "review_payload",
    "run",
    "same",
    "save_scan",
    "scan",
    "scan_project",
    "selected_same",
    "shutil",
    "snapshot_model",
    "statistics",
    "strict_json",
    "subprocess",
    "summary",
    "summary_fixture",
    "sys",
    "task",
    "tempfile",
    "time",
    "value_differences",
    "write",
    "write_fixture_files",
    "write_model",
    "write_report",
]


def remove_model(path):
    for source in model_parts(path):
        source.unlink()
    path.unlink(missing_ok=True)


def review_for(artifact):
    return dict(
        scan_id=artifact["scan_id"],
        reviewed_naming_context_id=artifact["naming_context_id"],
        reviewed_names=[item["id"] for item in artifact["naming"]["names"]],
        reviewed_judgments=[item["id"] for item in artifact["judgments"]],
        diagnostic_assignments={},
        issues=[],
        reviewed_confirmations=[
            item["id"] for item in artifact["human_confirmations"]["confirmations"]
        ],
        diagnostic_decisions=[
            dict(id=item["id"], outcome="issue", reason="Current diagnostic confirmed")
            for item in [
                *artifact["ordinary"],
                *(item for item in artifact["judgments"] if "message" in item),
            ]
        ],
        unverified=[],
    )


def snapshot_artifact(
    root, services=("s3",), records=(), ordinary=(), target="123456789012"
):
    """A complete synthetic Scan boundary, with no validators or real Project reads."""
    services = sorted(services)
    return dict(
        version=6,
        root=str(root),
        scan_id="a" * 32,
        naming_context_id=identifier({}),
        naming_context={},
        environment="dev",
        target=target,
        services=services,
        target_services=services,
        service_results=[
            dict(service=service, status="scanned") for service in services
        ],
        ordinary=list(ordinary),
        naming={"names": []},
        judgments=[],
        executed_at="2026-10-25T00:00:00Z",
        human_confirmations=dict(
            version=2, environment="dev", target=target, confirmations=[]
        ),
        warnings=[],
        information=[],
        unverified=[],
        processing_errors=[],
        check_results=[
            dict(
                id="check",
                check_id="mechanical.models",
                status="PASS",
                complete=True,
                scope=[f"dev/{target}/{service}" for service in services],
            )
        ],
        **aggregate(list(records), "dev", target, services),
    )


def forbid_report_text(original, path, *args, **kwargs):
    if path.name in {"issues.md", "iac-issues.md"}:
        raise AssertionError("old Markdown read")
    return original(path, *args, **kwargs)
