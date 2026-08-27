#!/usr/bin/env python3
"""Focused self-checks for task completion and IAM artifact naming."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate-blueprint.py")
SPEC = importlib.util.spec_from_file_location("validate_blueprint", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def errors_for(rows: list[list[str]]) -> list[str]:
    root = SCRIPT.parents[2]
    validator = MODULE.Validator(root)
    validator.check_markdown_iam_policy_artifacts(
        root / "docs" / "designs" / "staging" / "123456789012" / "iam.md",
        "VPCFLOWLOGROLE01",
        rows,
    )
    return validator.errors


def check_task_contract() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "tasks").mkdir()
        (root / "tasks" / "active.md").write_text(
            """# Test

## Task contract

- Task type: `governance`

## Required changes

- [R1] READMEを更新する。

## Acceptance checks

- [R1] `changed:README.md`

## Allowed paths

- `README.md`
- `tasks/active.md`
""",
            encoding="utf-8",
        )
        (root / "README.md").write_text("changed\n", encoding="utf-8")
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert not validator.errors
        assert validator.requirement_ids == ["R1"]

        active = root / "tasks" / "active.md"
        active.write_text(
            active.read_text(encoding="utf-8").replace("- [R1] `changed:README.md`", ""),
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert "requirement has no Acceptance check: R1" in validator.errors

        active.write_text(
            """# Test

## Task contract

- Task type: `infrastructure`
- Infrastructure phase: `implement`

## Required changes

- [R1] IaCを更新する。

## Acceptance checks

- [R1] `changed:README.md`

## Allowed paths

- `README.md`
- `tasks/active.md`
""",
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert not validator.errors, validator.errors
        assert validator.infrastructure_phase == "implement"

        active.write_text(
            active.read_text(encoding="utf-8").replace(
                "- Infrastructure phase: `implement`\n", ""
            ),
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert any("Infrastructure phase must appear exactly once" in error for error in validator.errors)


def check_task_type_dispatch() -> None:
    valid = {
        "initialization": {"project.json"},
        "design": {"docs/designs/dev/123456789012/vpc.md", "model/dev/123456789012/vpc.properties"},
        "infrastructure": {"infra/cloudformation/templates/vpc.yaml"},
        "scenario-test": {"tests/scenarios/vpc/scenario.md", "tests/results/vpc/dev/123456789012/result.md"},
        "governance": {"README.md"},
        "catalog-maintenance": {"framework/materials/aws/EC2_VPC.properties", "framework/materials/catalog.sha256"},
        "migration": {"project.json"},
    }
    for task_type, changed in valid.items():
        validator = MODULE.Validator(SCRIPT.parents[2])
        validator.task_type = task_type
        validator.infrastructure_phase = "implement" if task_type == "infrastructure" else ""
        validator.changed_paths = changed | {"tasks/active.md"}
        validator.check_task_type_requirements()
        assert not validator.errors, (task_type, validator.errors)

    validator = MODULE.Validator(SCRIPT.parents[2])
    validator.task_type = "infrastructure"
    validator.infrastructure_phase = "deploy"
    validator.changed_paths = {"tasks/active.md"}
    validator.check_task_type_requirements()
    assert not validator.errors, validator.errors

    validator.changed_paths.add("infra/cloudformation/templates/vpc.yaml")
    validator.check_task_type_requirements()
    assert "infrastructure deploy phase must not change IaC" in validator.errors

    validator = MODULE.Validator(SCRIPT.parents[2])
    validator.task_type = "infrastructure"
    validator.infrastructure_phase = "update"
    validator.changed_paths = {
        "docs/designs/dev/123456789012/vpc.md",
        "model/dev/123456789012/vpc.properties",
        "infra/cloudformation/templates/vpc.yaml",
        "tasks/active.md",
    }
    validator.check_task_type_requirements()
    assert not validator.errors, validator.errors

    validator = MODULE.Validator(SCRIPT.parents[2])
    validator.task_type = "design"
    validator.changed_paths = {
        "docs/designs/dev/123456789012/iam/role01-policy.json",
        "model/dev/123456789012/iam.properties",
        "tasks/active.md",
    }
    validator.check_task_type_requirements()
    assert not validator.errors, validator.errors


def check_model_task_boundaries() -> None:
    prompt = SCRIPT.parents[2] / "tasks" / "active.md"
    for task_type, changed in {
        "design": {"docs/designs/dev/123456789012/vpc.md", "model/dev/123456789012/vpc.properties"},
        "infrastructure": {
            "infra/cloudformation/templates/vpc.yaml",
            "docs/designs/dev/123456789012/vpc.md",
            "model/dev/123456789012/vpc.properties",
        },
    }.items():
        validator = MODULE.Validator(SCRIPT.parents[2])
        validator.task_type = task_type
        validator.changed_paths = changed | {"tasks/active.md"}
        validator.check_task_boundary(prompt)
        assert not validator.errors, (task_type, validator.errors)


def check_schema_backed_design_rows() -> None:
    repository = SCRIPT.parents[2]
    _, property_owners = MODULE.Validator(repository).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        design = root / "docs" / "designs" / "staging" / "123456789012" / "logs.md"
        design.parent.mkdir(parents=True)
        invalid = """# CloudWatch Logs

- Design service ID: `logs`
- Owned catalog resource types: `Logs.LogGroup`

<a id="logs-vpcflowloggroup01"></a>
## Logs.LogGroup: VPCFLOWLOGGROUP01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KmsKeyId | `not-used` | ログ暗号化に使用するKMSキーのARN |
| 2 | Encryption | `AWS-managed standard encryption` | ログの暗号化方式 |
| 3 | Log Group ID | `PENDING_DEPLOY` | デプロイ後生成値としてロググループを識別するID |
"""
        design.write_text(invalid, encoding="utf-8")
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.CloudFormationSchemaCatalog(repository)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))}, {"Logs.LogGroup"}, property_owners
        )
        assert any("provider schema violation" in error for error in validator.errors)
        assert any("not selected by framework/materials/aws" in error for error in validator.errors)

        design.write_text(
            invalid.replace(
                "| 1 | KmsKeyId | `not-used` | ログ暗号化に使用するKMSキーのARN |\n"
                "| 2 | Encryption | `AWS-managed standard encryption` | ログの暗号化方式 |\n"
                "| 3 | Log Group ID",
                "| 1 | KmsKeyId | [LOGKEY01](kms.md#kms-logkey01) | ログ暗号化に使用するKMSキーのARN |\n"
                "| 2 | LogGroupClass | `STANDARD` | ロググループの保存クラス |\n"
                "| 3 | Log Group ID",
            ),
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.CloudFormationSchemaCatalog(repository)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))}, {"Logs.LogGroup"}, property_owners
        )
        assert not validator.errors, validator.errors


def check_design_handoff_prompt() -> None:
    validator = MODULE.Validator(SCRIPT.parents[2])
    validator.check_framework_design_handoff()
    assert not validator.errors, validator.errors
    prompt = (
        SCRIPT.parents[2] / "framework" / "prompts" / "chatbot" / "service-design.md"
    ).read_text(encoding="utf-8")
    assert "AWS::<Service>::<Resource>" in prompt
    assert "VPC固有" not in prompt
    assert "Management owner" not in prompt


def main() -> None:
    trust = ["1", "AssumeRolePolicyDocument", "[Trust](iam/vpcflowlogrole01-trust-policy.json)", "信頼ポリシー"]
    old_trust = ["1", "AssumeRolePolicyDocument", "[Trust](iam/vpcflowlogrole01-assume-role-policy-document.json)", "信頼ポリシー"]
    inline_name = ["1", "Policies[].PolicyName", "`VPCFlowLogsToCloudWatchLogs`", "ポリシー名"]
    inline = ["2", "Policies[].PolicyDocument", "[Policy](iam/vpcflowlogrole01-vpc-flow-logs-to-cloud-watch-logs.json)", "権限ポリシー"]
    old_inline = ["2", "Policies[].PolicyDocument", "[Policy](iam/vpcflowlogrole01-inline-policy-document.json)", "権限ポリシー"]
    assert not errors_for([trust])
    assert errors_for([old_trust])
    assert not errors_for([inline_name, inline])
    assert errors_for([inline_name, old_inline])
    assert MODULE.artifact_id("VPCFlowLogsToCloudWatchLogs") == "vpc-flow-logs-to-cloud-watch-logs"
    assert MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch("01_initialize.md")
    assert not MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch("initialize.md")
    check_task_contract()
    check_task_type_dispatch()
    check_model_task_boundaries()
    check_schema_backed_design_rows()
    check_design_handoff_prompt()
    print("validate-blueprint: PASS (17 focused checks)")


if __name__ == "__main__":
    main()
