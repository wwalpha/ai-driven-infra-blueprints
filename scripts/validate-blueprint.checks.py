#!/usr/bin/env python3
"""Focused self-checks for IAM policy artifact naming."""

from __future__ import annotations

import importlib.util
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
    print("validate-blueprint: PASS (5 focused checks)")


if __name__ == "__main__":
    main()
