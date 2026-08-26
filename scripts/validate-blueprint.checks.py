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
    root = SCRIPT.parents[1]
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


def check_task_type_dispatch() -> None:
    valid = {
        "initialization": {"project.json"},
        "design": {"docs/designs/dev/123456789012/vpc.md", "llm/designs/dev/123456789012/vpc.properties"},
        "infrastructure": {"infra/cloudformation/templates/vpc.yaml"},
        "scenario-test": {"tests/scenarios/vpc/scenario.md", "tests/results/vpc/dev/123456789012/result.md"},
        "governance": {"README.md"},
        "catalog-maintenance": {"materials/aws/EC2_VPC.properties", "materials/catalog.sha256"},
        "migration": {"project.json"},
    }
    for task_type, changed in valid.items():
        validator = MODULE.Validator(SCRIPT.parents[1])
        validator.task_type = task_type
        validator.changed_paths = changed | {"tasks/active.md"}
        validator.check_task_type_requirements()
        assert not validator.errors, (task_type, validator.errors)

    validator = MODULE.Validator(SCRIPT.parents[1])
    validator.task_type = "design"
    validator.changed_paths = {
        "docs/designs/dev/123456789012/iam/role01-policy.json",
        "llm/designs/dev/123456789012/iam.properties",
        "tasks/active.md",
    }
    validator.check_task_type_requirements()
    assert not validator.errors, validator.errors


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
    check_task_contract()
    check_task_type_dispatch()
    print("validate-blueprint: PASS (9 focused checks)")


if __name__ == "__main__":
    main()
