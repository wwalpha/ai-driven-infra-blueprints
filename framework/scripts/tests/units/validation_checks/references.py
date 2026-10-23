"""Design references, grouped resources and resource overviews."""


from __future__ import annotations

from support.validator import MODULE, SCRIPT
from support.validator import load as load
from support.validator import project as project
from support.validator import write as write


def errors_for(rows: list[list[str]]) -> list[str]:
    root = SCRIPT.parents[2]
    validator = MODULE.Validator(root)
    validator.check_markdown_iam_policy_artifacts(
        root / "docs" / "designs" / "stg" / "123456789012" / "iam.md",
        "VPCFLOWLOGROLE01",
        rows,
    )
    return validator.errors


def check_artifact_naming() -> None:
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
