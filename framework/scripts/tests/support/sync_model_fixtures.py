"""Focused self-checks for generated service models."""

from __future__ import annotations

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json

import pytest
import support.it_workspace as workspace
import task_contract_core as tasks
from model.files import load_model
from support.model_sources import write_model
from support.validator import load
from utils.aws_mappings import mapping_alias

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPT = Path(__file__).resolve().parents[2] / "sync-model.py"

MODULE = load("sync-model")


def build_generated_policy(root, definitions_root=None):
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "test",
                "targets": [
                    {
                        "environment": "dev",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    model = root / "model/dev/123456789012/iam.properties"
    values = {
        "desired.service.iam.serviceId": "iam",
        "desired.service.iam.ownedCatalogResourceTypes": "IAM.Role",
        "display.service.title": "# IAM 詳細設計",
        "desired.resource.001.resourceType": "IAM.Role",
        "desired.resource.001.logicalId": "IAM_Role_001",
        "desired.resource.001.anchor": "resource-IAM_Role_001",
        "desired.service.identity.lastAllocated": '{"IAM.Role":1}',
        "desired.resource.001.cfn-logicalId": "cfn-stack-app-dev-iam-AppRole",
        "display.resource.001.comment": "アプリケーションの実行権限",
        "desired.row.001-001.property": "IAM.Role.RoleName",
        "desired.row.001-001.value": "`app-dev-role`",
        "desired.row.001-001.comment": "権限を識別する名前",
        "desired.row.001-002.property": "IAM.Role.AssumeRolePolicyDocument",
        "desired.row.001-002.value": "[信頼ポリシー](iam/iam-role-001-trust-policy.json)",
        "desired.row.001-002.comment": "引受元に許可する権限",
        "desired.row.001-002.document": json.dumps(
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
    write_model(model, values)
    stacks = {
        "desired.deployment.maxConcurrentStacks": "1",
        "desired.stack.001.name": "cfn-stack-app-dev-iam",
        "desired.stack.001.placementName": "cfn-stack-app-dev-iam",
        "desired.stack.001.template": "iam.yaml",
        "desired.stack.001.parameters": "iam.json",
        "desired.stack.001.deployOrder": "10",
        "display.stack.001.comment": "合成Stack",
    }
    write_model(model.with_name("cloudformation-stacks.properties"), stacks)
    if (
        MODULE.sync(
            root,
            True,
            "dev",
            "123456789012",
            ["iam"],
            definitions_root=definitions_root,
        )
        != 0
    ):
        raise RuntimeError("generated_policy fixture initialization failed")
    return values


def _callback_generated_policy_register(model, root, /, outputs):
    name = "tasks/generated-policy.md"
    files = [root / name, *load_model(model).files, *outputs]
    listed = "\n".join(f"- `{file.relative_to(root).as_posix()}`" for file in files)
    tasks.start(
        root,
        name,
        "# Test\n## Task contract\n- Task type: `design`\n"
        "- Task status: `running`\n## Validation scope\n- `dev/123456789012/iam`\n"
        f"## Modified files\n{listed}\n## Allowed paths\n{listed}\n",
    )
    return {tasks.SELECTOR: name}


@pytest.fixture
def generated_policy(tmp_path, shared_framework):
    root = workspace.populate("generated_policy", tmp_path)
    model = root / "model/dev/123456789012/iam.properties"
    values = json.loads((root / "fixture-values.json").read_text(encoding="utf-8"))
    (root / "fixture-values.json").unlink()
    design = root / "docs/designs/dev/123456789012/iam.md"
    artifact = design.with_suffix("") / "iam-role-001-trust-policy.json"

    register = _bind_framework_callback(
        _callback_generated_policy_register, model, root
    )

    with mapping_alias(shared_framework.parent, root):
        yield root, model, values, design, artifact, register
