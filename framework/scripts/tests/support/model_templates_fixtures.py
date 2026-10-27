"""Explicit service properties, fixed identities, scope and transaction fixtures."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch

import model.sources as _exports_model_sources
import pytest
import sync_runtime
from model.core import entries, properties
from model.files import model_file_contents, read_model, trace_model
from model.format import parse, serialize, split
from model.impact import affected, dependencies
from model.render import generate_files
from model.sources import (
    _publish_transaction,
    json_read,
    json_text,
    publication_lock,
    source_scope,
)
from support.model_sources import declare_outputs, write_model
from support.model_sources import write_fixture_files as save_files
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

# Preserve shared fixtures and compatibility exports under their historical names.
load_model = _exports_model_sources.load_model
model_parts = _exports_model_sources.model_parts


ROOT = Path(__file__).resolve().parents[4]


def rejected(function, phrase=None):
    try:
        function()
    except (ValueError, OSError, KeyError, TypeError, IndexError, Blocked) as error:
        if phrase:
            assert phrase in str(error), (phrase, error)
        return str(error)
    raise AssertionError("invalid input accepted")


def fixture(root, environments=("dev", "prod")):
    (root / "project.json").write_text(
        json_text(
            {
                "projectName": "app",
                "targets": [
                    {
                        "environment": env,
                        "alias": alias,
                        "awsAccountId": account,
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                    for env in environments
                    for alias, account in [
                        ("other", "210987654321"),
                        ("team", "123456789012"),
                    ]
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "tasks").mkdir()
    (root / "tasks/example.md").write_text(
        "## Task contract\n- Task type: `migration`\n- Task status: `running`\n## Validation scope\n"
        + "".join(
            f"- `{env}/team/{service}`\n"
            for env in environments
            for service in ("iam", "config")
        )
        + "## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n- `model/**`\n- `docs/designs/**`\n",
        encoding="utf-8",
    )


def role_model(env, count):
    result = {
        "desired.service.iam.serviceId": "iam",
        "desired.service.iam.ownedCatalogResourceTypes": "IAM.Role",
        "display.service.title": "# IAM 詳細設計",
    }
    result["desired.service.identity.lastAllocated"] = json_text({"IAM.Role": count})
    for number in range(count):
        identity = f"{11 + number * 7:03d}"
        name = f"app-{env}-role-{number + 1}"
        result.update(
            {
                f"desired.resource.{identity}.resourceType": "IAM.Role",
                f"desired.resource.{identity}.logicalId": f"IAM_Role_{number + 1:03d}",
                f"desired.resource.{identity}.anchor": "resource-"
                + (f"IAM_Role_{number + 1:03d}"),
                f"desired.resource.{identity}.resourceMode": "IMPORT",
                f"display.resource.{identity}.comment": "共通の処理権限",
                f"desired.row.{identity}-004.property": "IAM.Role.RoleName",
                f"desired.row.{identity}-004.value": "`" + name + "`",
                f"desired.row.{identity}-004.comment": "ロール名",
                f"desired.row.{identity}-008.property": "IAM.Role.AssumeRolePolicyDocument",
                f"desired.row.{identity}-008.value": f"[信頼ポリシー](iam/iam-role-{number + 1:03d}-trust-policy.json)",
                f"desired.row.{identity}-008.comment": "Lambdaによる引受けを許可",
                f"desired.row.{identity}-008.document": json_text(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "lambda.amazonaws.com"},
                                "Action": "sts:AssumeRole",
                            }
                        ],
                    }
                ),
            }
        )
    return result


def config_model():
    return {
        "desired.service.config.serviceId": "config",
        "desired.service.config.ownedCatalogResourceTypes": "Config.ConfigurationRecorder",
        "display.service.title": "# AWS Config 詳細設計",
        "desired.resource.007.resourceType": "Config.ConfigurationRecorder",
        "desired.resource.007.logicalId": "Config_ConfigurationRecorder_001",
        "desired.resource.007.anchor": "resource-Config_ConfigurationRecorder_001",
        "desired.service.identity.lastAllocated": '{"Config.ConfigurationRecorder":1}',
        "desired.resource.007.resourceMode": "IMPORT",
        "display.resource.007.comment": "構成情報を記録",
        "desired.row.007-001.property": "Config.ConfigurationRecorder.Name",
        "desired.row.007-001.value": "`default`",
        "desired.row.007-001.comment": "記録名",
        "desired.row.007-005.property": "Config.ConfigurationRecorder.RoleARN",
        "desired.row.007-005.value": "`AWSServiceRoleForConfig`",
        "desired.row.007-005.comment": "記録する権限",
        "desired.row.007-009.property": "Config.ConfigurationRecorder.Id",
        "desired.row.007-009.value": "[Config_ConfigurationRecorder_001](config.md#resource-Config_ConfigurationRecorder_001)",
        "desired.row.007-009.comment": "記録ID",
        "observed.row.007-009.value": "`default`",
    }


def write_fixture(root, env, service, values):
    path = write_model(
        root / "model" / env / "team" / (service + ".properties"), values
    )
    view = root / "docs/designs" / env / "team" / (service + ".md")
    declare_outputs(root, generate_files(view, values, root))
    with redirect_stdout(io.StringIO()):
        sync_runtime.sync(root, True, env, "team", services=[service])
    return path


def install_candidate(root, models):
    for env, values in models.items():
        write_model(root / "model" / env / "team/iam.properties", values)
        view = root / "docs/designs" / env / "team/iam.md"
        declare_outputs(root, generate_files(view, values, root))
    return root / "model" / next(iter(models)) / "team/iam.properties"


@pytest.fixture
def root(project_workspace):
    return project_workspace


__all__ = [
    "Blocked",
    "Path",
    "ROOT",
    "affected",
    "config_model",
    "copy",
    "dependencies",
    "entries",
    "fixture",
    "install_candidate",
    "io",
    "json",
    "json_text",
    "json_read",
    "load_model",
    "model_file_contents",
    "model_parts",
    "os",
    "parse",
    "patch",
    "properties",
    "publication_lock",
    "_publish_transaction",
    "pytest",
    "read_model",
    "redirect_stdout",
    "rejected",
    "role_model",
    "root",
    "run",
    "save_files",
    "serialize",
    "shutil",
    "source_scope",
    "split",
    "subprocess",
    "sync_runtime",
    "sys",
    "tempfile",
    "trace_model",
    "write_fixture",
    "write_model",
]
