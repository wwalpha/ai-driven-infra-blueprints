#!/usr/bin/env python3
"""Focused self-checks for task completion and IAM artifact naming."""

from __future__ import annotations

import importlib.util
import json
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


def check_optional_alias_targets() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        topology = {
            "projectName": "test",
            "targets": [
                {
                    "environment": "dev",
                    "alias": "cde",
                    "awsAccountId": "123456789012",
                    "awsRegion": "ap-northeast-1",
                    "iacEngine": "cloudformation",
                },
                {
                    "environment": "dev",
                    "alias": "non-cde",
                    "awsAccountId": "123456789012",
                    "awsRegion": "ap-northeast-1",
                    "iacEngine": "cloudformation",
                },
                {
                    "environment": "sandbox",
                    "awsAccountId": "210987654321",
                    "awsRegion": "ap-northeast-1",
                    "iacEngine": "terraform",
                },
            ],
        }
        (root / "project.json").write_text(
            json.dumps(topology) + "\n", encoding="utf-8"
        )
        for path in (
            "docs/designs/dev/cde",
            "docs/designs/dev/non-cde",
            "docs/designs/sandbox/210987654321",
            "model/dev/cde",
            "model/dev/non-cde",
            "model/sandbox/210987654321",
            "infra/cloudformation/parameters/dev/cde",
            "infra/cloudformation/parameters/dev/non-cde",
            "infra/terraform/environments/sandbox/210987654321",
        ):
            (root / path).mkdir(parents=True)

        validator = MODULE.Validator(root)
        validator.check_project_topology()
        validator.check_initialized_paths()
        assert not validator.errors, validator.errors
        assert validator.accounts[("dev", "cde")]["account"] == "123456789012"
        assert validator.accounts[("dev", "non-cde")]["account"] == "123456789012"

        invalid_targets = [
            ([topology["targets"][0]], "single-target environment must omit alias"),
            (
                [
                    topology["targets"][0],
                    {**topology["targets"][2], "environment": "dev"},
                ],
                "multi-target environment requires alias",
            ),
            (
                [
                    topology["targets"][0],
                    {**topology["targets"][1], "iacEngine": "terraform"},
                ],
                "must use one IaC engine",
            ),
            (
                [{**topology["targets"][0], "alias": "123456789012"}],
                "invalid target alias",
            ),
        ]
        for targets, expected_error in invalid_targets:
            (root / "project.json").write_text(
                json.dumps({"projectName": "test", "targets": targets}) + "\n",
                encoding="utf-8",
            )
            validator = MODULE.Validator(root)
            validator.check_project_topology()
            assert any(expected_error in error for error in validator.errors), (
                expected_error,
                validator.errors,
            )


def check_optional_alias_contract() -> None:
    root = SCRIPT.parents[2]
    required = {
        "AGENTS.md": "target directory",
        "framework/prompts/codex/01_initialize.md": "optional `alias`",
        "framework/rules/cloudformation.md": "templates/<alias>/",
        "framework/rules/terraform.md": "modules/<alias>/",
        "framework/rules/detailed-design.md": "<target-directory>",
        "framework/rules/scenario-testing.md": "<target-directory>",
    }
    for relative, literal in required.items():
        assert literal in (root / relative).read_text(encoding="utf-8"), (
            relative,
            literal,
        )


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
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(repository).catalog_design_properties()
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
"""
        design.write_text(invalid, encoding="utf-8")
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.CloudFormationSchemaCatalog(repository)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))}, catalog_types, property_owners, identifier_outputs
        )
        assert any("provider schema violation" in error for error in validator.errors)
        assert any("not selected by framework/materials/aws" in error for error in validator.errors)

        design.write_text(
            invalid.replace(
                "| 1 | KmsKeyId | `not-used` | ログ暗号化に使用するKMSキーのARN |\n"
                "| 2 | Encryption | `AWS-managed standard encryption` | ログの暗号化方式 |",
                "| 1 | KmsKeyId | [LOGKEY01](kms.md#kms-logkey01) | ログ暗号化に使用するKMSキーのARN |\n"
                "| 2 | LogGroupClass | `STANDARD` | ロググループの保存クラス |\n"
                "| 3 | Logs.LogGroup.Tags[].Key | `Name` | ロググループを識別するNameタグのキー |\n"
                "| 4 | Logs.LogGroup.Tags[].Value | `cwlogs-app-staging-flow-logs` | ロググループを識別するNameタグの値 |",
            ),
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.CloudFormationSchemaCatalog(repository)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))}, catalog_types, property_owners, identifier_outputs
        )
        assert not validator.errors, validator.errors


def check_identifier_propagation() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(repository).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        design = root / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
        design.parent.mkdir(parents=True)
        design.write_text(
            """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`

<a id="vpc-vpc-app-dev"></a>

## EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EC2.VPC.VpcId | PENDING_DEPLOY | VPCを一意に識別するID |
| 2 | EC2.VPC.Name | vpc-app-dev | VPCを識別するNameタグの値 |

<a id="vpc-sbnt-app-dev-private-01"></a>

## EC2.Subnet: sbnt-app-dev-private-01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EC2.Subnet.SubnetId | PENDING_DEPLOY | Subnetを一意に識別するID |
| 2 | EC2.Subnet.VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
| 3 | EC2.Subnet.Name | sbnt-app-dev-private-01 | Subnetを識別するNameタグの値 |
""",
            encoding="utf-8",
        )
        metadata = {design: ("vpc", ("EC2.VPC", "EC2.Subnet"))}
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.CloudFormationSchemaCatalog(repository)
        validator.check_design_tables(metadata, catalog_types, property_owners, identifier_outputs)
        validator.check_design_links(identifier_outputs)
        assert not validator.errors, validator.errors

        design.write_text(
            design.read_text(encoding="utf-8")
            .replace("EC2.VPC.VpcId | PENDING_DEPLOY", "EC2.VPC.VpcId | vpc-0123456789abcdef0")
            .replace("[PENDING_DEPLOY](#vpc-vpc-app-dev)", "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)")
            .replace("EC2.Subnet.SubnetId | PENDING_DEPLOY", "EC2.Subnet.SubnetId | subnet-0123456789abcdef0"),
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.CloudFormationSchemaCatalog(repository)
        validator.check_design_tables(metadata, catalog_types, property_owners, identifier_outputs)
        validator.check_design_links(identifier_outputs)
        assert not validator.errors, validator.errors

        deployed = design.read_text(encoding="utf-8")
        design.write_text(
            deployed.replace("vpc-0123456789abcdef0", "vpc-app-dev"), encoding="utf-8"
        )
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.CloudFormationSchemaCatalog(repository)
        validator.check_design_tables(metadata, catalog_types, property_owners, identifier_outputs)
        assert any("must use a physical value" in error for error in validator.errors)

        design.write_text(
            deployed.replace(
                "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)", "[vpc-wrong](#vpc-vpc-app-dev)"
            ),
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.check_design_links(identifier_outputs)
        assert any("identifier reference does not match observed target" in error for error in validator.errors)


def check_name_tag_and_identifier_order_contract() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(repository).catalog_design_properties()
    assert MODULE.REQUIRED_NAME_PROPERTIES == {
        "EC2.RouteTable": "EC2.RouteTable.Name",
        "EC2.Subnet": "EC2.Subnet.Name",
        "EC2.VPC": "EC2.VPC.Name",
    }
    for resource_type, property_name in MODULE.REQUIRED_NAME_PROPERTIES.items():
        assert resource_type in property_owners[property_name]

    path = repository / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
    validator = MODULE.Validator(repository)
    validator.check_required_name_tag(
        path,
        "EC2.VPC",
        "vpc-app-dev",
        [["1", "EC2.VPC.Name", "vpc-app-dev", "Nameタグの値"]],
    )
    assert not validator.errors, validator.errors

    validator = MODULE.Validator(repository)
    validator.check_required_name_tag(
        path,
        "EC2.VPC",
        "vpc-app-dev",
        [
            ["1", "EC2.VPC.Tags[].Key", "Name", "Nameタグのキー"],
            ["2", "EC2.VPC.Tags[].Value", "vpc-app-dev", "Nameタグの値"],
        ],
    )
    assert any("one-row property" in error for error in validator.errors)

    validator = MODULE.Validator(repository)
    validator.check_required_name_tag(
        path,
        "EC2.Subnet",
        "SUBNET01",
        [["1", "EC2.Subnet.Name", "sbnt-app-dev-private-01", "Nameタグの値"]],
    )
    assert any("heading identifier must match" in error for error in validator.errors)

    validator = MODULE.Validator(repository)
    validator.check_required_name_tag(
        path,
        "EC2.Subnet",
        "PRIVATE_SUBNET_01",
        [["1", "EC2.Subnet.Name", "PRIVATE_SUBNET_01", "Nameタグの値"]],
    )
    assert any("lower-kebab-case" in error for error in validator.errors)

    validator = MODULE.Validator(repository)
    validator.check_required_name_tag(
        path,
        "ApiGatewayV2.Api",
        "API01",
        [],
    )
    assert not validator.errors, validator.errors

    validator = MODULE.Validator(repository)
    validator.check_generated_identifier(
        path,
        "EC2.EIP",
        "EIP01",
        [
            ["1", "EC2.EIP.AllocationId", "eipalloc-0123456789abcdef0", "Allocation ID"],
            ["2", "EC2.EIP.PublicIp", "192.0.2.1", "Public IP"],
        ],
        identifier_outputs,
    )
    assert not validator.errors, validator.errors

    validator = MODULE.Validator(repository)
    validator.check_generated_identifier(
        path,
        "EC2.EIP",
        "EIP01",
        [
            ["1", "EC2.EIP.PublicIp", "192.0.2.1", "Public IP"],
            ["2", "EC2.EIP.AllocationId", "eipalloc-0123456789abcdef0", "Allocation ID"],
        ],
        identifier_outputs,
    )
    assert any("must be first in catalog order" in error for error in validator.errors)


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
    check_optional_alias_targets()
    check_optional_alias_contract()
    check_model_task_boundaries()
    check_schema_backed_design_rows()
    check_identifier_propagation()
    check_name_tag_and_identifier_order_contract()
    check_design_handoff_prompt()
    print("validate-blueprint: PASS (32 focused checks)")


if __name__ == "__main__":
    main()
