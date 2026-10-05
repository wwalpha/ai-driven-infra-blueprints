#!/usr/bin/env python3
"""Focused self-checks for task completion and IAM artifact naming."""

from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import json
import re
import shlex
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
        root / "docs" / "designs" / "stg" / "123456789012" / "iam.md",
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


def check_idle_without_active_task() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)

        validator = MODULE.Validator(root)
        validator.check_task_scope()
        validator.check_tasks()
        assert not validator.errors, validator.errors

        (root / "tasks").mkdir()
        (root / "tasks" / "active.md").write_text("# completed\n", encoding="utf-8")
        subprocess.run(["git", "add", "tasks/active.md"], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=validator",
                "-c",
                "user.email=validator@example.invalid",
                "commit",
                "-qm",
                "active-task",
            ],
            cwd=root,
            check=True,
        )
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        validator.check_task_type_requirements()
        validator.check_acceptance_checks()
        assert not validator.errors, validator.errors
        assert not validator.task_type
        (root / "tasks" / "active.md").unlink()
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        validator.check_tasks()
        assert not validator.errors, validator.errors

        (root / "README.md").write_text("changed\n", encoding="utf-8")
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert any("active task prompt missing" in error for error in validator.errors)


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
                    "awsProfile": "dev-cde",
                    "awsExecutionAccountId": "999999999999",
                    "awsAccountId": "123456789012",
                    "awsRegion": "ap-northeast-1",
                    "iacEngine": "cloudformation",
                },
                {
                    "environment": "dev",
                    "alias": "non-cde",
                    "awsProfile": "dev-non-cde",
                    "awsAccountId": "123456789012",
                    "awsRegion": "ap-northeast-1",
                    "iacEngine": "cloudformation",
                },
                {
                    "environment": "sandbox",
                    "awsAccountId": "210987654321",
                    "awsRegion": "eusc-de-east-1",
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
        assert validator.accounts[("sandbox", "210987654321")]["account"] == "210987654321"

        # Each environment/alias may have its own suffix; paths and account identity stay intact.
        suffix_targets = [{**target, "suffix": suffix} for target, suffix in
                          zip(topology["targets"], ("blue", "green-01", "sandbox-token"))]
        for targets in (suffix_targets, [suffix_targets[0], *topology["targets"][1:]]):
            (root / "project.json").write_text(json.dumps({**topology, "targets": targets}) + "\n", encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.check_project_topology()
            assert not validator.errors, validator.errors
            assert set(validator.accounts) == {("dev", "cde"), ("dev", "non-cde"), ("sandbox", "210987654321")}
        (root / "project.json").write_text(json.dumps({**topology, "suffix": {"dev": "blue"}}) + "\n", encoding="utf-8")
        validator = MODULE.Validator(root)
        validator.check_project_topology()
        assert any("must contain only projectName and targets" in error for error in validator.errors), validator.errors

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
            (
                [{**topology["targets"][0], "awsRegion": "Tokyo"}, *topology["targets"][1:]],
                "invalid AWS region ID",
            ),
            (
                [{**topology["targets"][0], "awsRegion": "ap--1"}, *topology["targets"][1:]],
                "invalid AWS region ID",
            ),
            (
                [{**topology["targets"][0], "awsRegion": ""}, *topology["targets"][1:]],
                "AWS region is required",
            ),
        ]
        for invalid in (None, 123, {}, [], "", "UNSET", "Blue", " padded ", "blue\n", "blue\0",
                        "-blue", "blue-", "blue--green", "ｂｌｕｅ"):
            invalid_targets.append((
                [{**topology["targets"][0], "suffix": invalid}, *topology["targets"][1:]],
                "values must be strings" if not isinstance(invalid, str) else "invalid naming suffix",
            ))
        for invalid in (None, 123, "", " ", " padded ", "UNSET", "bad\nprofile", "bad\0profile"):
            invalid_targets.append((
                [{**topology["targets"][0], "awsProfile": invalid}, *topology["targets"][1:]],
                "values must be strings" if not isinstance(invalid, str) else "invalid AWS profile",
            ))
        for invalid in (None, 123456789012, "", "UNSET", "123", "1234567890123", " 123456789012", "123456789012\n", "１２３４５６７８９０１２"):
            invalid_targets.append((
                [{**topology["targets"][0], "awsExecutionAccountId": invalid}, *topology["targets"][1:]],
                "values must be strings" if not isinstance(invalid, str) else "invalid AWS execution account",
            ))
        invalid_targets.append((
            [topology["targets"][0],
             {**topology["targets"][1], "awsAccountId": "210987654321",
              "awsExecutionAccountId": "999999999999", "iacEngine": "terraform"}],
            "same environment/AWS execution account must use one IaC engine",
        ))
        invalid_targets.append((
            [{**topology["targets"][0], "profile": "unsupported"}, *topology["targets"][1:]],
            "optional alias/awsProfile/awsExecutionAccountId/suffix only",
        ))
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
        design = root / "docs" / "designs" / "stg" / "123456789012" / "logs.md"
        design.parent.mkdir(parents=True)
        invalid = """# CloudWatch Logs

- Design service ID: `logs`
- Owned catalog resource types: `Logs.LogGroup`

## リソース詳細

<a id="logs-vpcflowloggroup01"></a>
### Logs.LogGroup: VPCFLOWLOGGROUP01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KmsKeyId | `not-used` | ログ暗号化に使用するKMSキーのARN |
| 2 | Encryption | `AWS-managed standard encryption` | ログの暗号化方式 |
"""
        design.write_text(invalid, encoding="utf-8")
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.DesignSchemaCatalog(repository)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))}, catalog_types, property_owners, identifier_outputs
        )
        assert any("provider schema violation" in error for error in validator.errors)
        assert any("not selected by design catalog" in error for error in validator.errors)

        design.write_text(
            invalid.replace(
                "| 1 | KmsKeyId | `not-used` | ログ暗号化に使用するKMSキーのARN |\n"
                "| 2 | Encryption | `AWS-managed standard encryption` | ログの暗号化方式 |",
                "| 1 | LogGroupClass | `STANDARD` | ロググループの保存クラス |\n"
                "| 2 | KmsKeyId | [LOGKEY01](kms.md#kms-logkey01) | ログ暗号化に使用するKMSキーのARN |\n"
                "| 3 | Tags[].Key | `Name` | ロググループを識別するNameタグのキー |\n"
                "| 4 | Tags[].Value | `cwlogs-app-stg-flow-logs` | ロググループを識別するNameタグの値 |",
            ),
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.DesignSchemaCatalog(repository)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))}, catalog_types, property_owners, identifier_outputs
        )
        assert not validator.errors, validator.errors


def check_description_design_constraints() -> None:
    repository = SCRIPT.parents[2]
    catalog = MODULE.Validator(repository).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "docs/designs/dev/123456789012"
        target.mkdir(parents=True)
        iam = target / "iam.md"
        sg = target / "security-group.md"
        iam_text = """# IAM 詳細設計

- Design service ID: `iam`
- Owned catalog resource types: `IAM.Role`

## リソース一覧

### IAM.Role

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-role](#iam-app-role) | アプリケーションの権限 |

## リソース詳細

<!-- resource-logical-id: RoleOne -->
<a id="iam-app-role"></a>
### IAM.Role: app-role

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RoleName | `app-role` | ロール名 |
| 2 | AssumeRolePolicyDocument | [Trust](iam/role-one-trust-policy.json) | 信頼ポリシー |
| 3 | Description | `Application role` | 用途の説明 |
"""
        sg_text = """# Security Group 詳細設計

- Design service ID: `security-group`
- Owned catalog resource types: `EC2.SecurityGroup`

## リソース一覧

### EC2.SecurityGroup

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-sg](#security-group-app-sg) | アプリケーションの通信制御 |

## リソース詳細

<!-- resource-logical-id: GroupOne -->
<a id="security-group-app-sg"></a>
### EC2.SecurityGroup: app-sg

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | `PENDING_DEPLOY` | 一意に識別するID |
| 2 | GroupDescription | `Application access` | 用途の説明 |
| 3 | GroupName | `app-sg` | 名前 |
| 4 | VpcId | [PENDING_DEPLOY](vpc.md#vpc-app-vpc) | 所属するVPCのID |
"""
        metadata = {iam: ("iam", ("IAM.Role",)), sg: ("security-group", ("EC2.SecurityGroup",))}

        def validate(role_text=iam_text, group_text=sg_text):
            iam.write_text(role_text, encoding="utf-8")
            sg.write_text(group_text, encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.schema_catalog = MODULE.DesignSchemaCatalog(repository)
            validator.check_design_tables(metadata, *catalog, paths=[iam, sg])
            validator.check_design_overviews(paths=[iam, sg])
            return validator

        # Both Japanese overview Comments and Source / Comments remain valid.
        assert not validate().errors, validate().errors
        for resource, prop, filename, role_text, group_text in (
            ("RoleOne", "IAM.Role.Description", "iam.md", iam_text.replace("Application role", "日本語の説明"), sg_text),
            ("GroupOne", "EC2.SecurityGroup.GroupDescription", "security-group.md", iam_text, sg_text.replace("Application access", "日本語の説明")),
            ("GroupOne", "EC2.SecurityGroup.GroupDescription", "security-group.md", iam_text, sg_text.replace("Application access", "Why?")),
        ):
            errors = validate(role_text, group_text).errors
            assert len(errors) == 1, errors
            assert all(text in errors[0] for text in (filename, resource, prop, "must match")), errors

        # Existing validators collect independent property and dependency failures.
        validator = validate(iam_text.replace("Application role", "日本語"), sg_text.replace("Application access", "日本語"))
        validator.check_design_links(catalog[2], paths=[iam, sg])
        assert any("RoleOne: IAM.Role.Description" in error for error in validator.errors)
        assert any("GroupOne: EC2.SecurityGroup.GroupDescription" in error for error in validator.errors)
        assert any("broken design link" in error and "vpc.md" in error for error in validator.errors)
        assert any("broken design link" in error and "trust-policy.json" in error for error in validator.errors)
        assert iam.read_text(encoding="utf-8") == iam_text.replace("Application role", "日本語")
        assert sg.read_text(encoding="utf-8") == sg_text.replace("Application access", "日本語")


def check_implementation_preflight_prompt() -> None:
    text = (SCRIPT.parents[2] / "framework/prompts/codex/03_implement.md").read_text(encoding="utf-8")
    preflight = text.split("## Read-only implementation preflight\n", 1)[1].split("\n## ", 1)[0]
    assert text.index("## Read-only implementation preflight") < text.index("## Create active task contract") < text.index("## Implement and validate")
    for required in (
        "active contract作成・IaC生成より前", "AWS API、IaC生成、deployは実行しない",
        "model_design.validate_required_properties", "DesignSchemaCatalog.literal_errors",
        "必要な依存先のproperties", "正本stack登録", "template・parameterの対応", "dependency cycle",
        "対象file | resource（logical ID）/stack | property/parameter | 不足・違反理由",
        "一回でまとめて提示", "最初の不足だけで報告を終えない", "不足があれば実装せず",
        "追加承認を要求せず", "変更scopeや全service検証へ自動拡張しない",
        "日本語の表示用Comment", "不正値を自動翻訳・置換しない", "別taskを自動作成・実行しない",
    ):
        assert required in preflight, required
    reading = text.split("## Read before changing files\n", 1)[1].split("\n## ", 1)[0]
    for required in (
        "設計inputはauthoritative model propertiesだけ", "propertiesとgenerated Markdownの事前二重比較をAgentへ要求しない",
        "本文はImplement開始時・IaC生成時・参照解決時に読まず", "Markdown／JSONの生成・保存とlocal loopの整合性検証は既存どおり維持",
        "scope selectorとして扱う", "本文を読まず", "path／file stem", "対応するmodelを一意に特定できない場合は推測せず停止",
        "python framework/scripts/model_files.py model/<environment>/<target-directory>/<service>.properties --resource <resource-selector>",
        "resource number", "logical ID、anchorの完全一致", "単一fileと分割入口index", "同じgroupの親・子・兄弟、service metadata／notes",
        "service全体のscopeならservice properties全体", "対象accountの承認済み設計すべて", "target全Markdownをfallbackとして読むことは禁止",
        "desired value、resource、reference、stack assignment、human decision", "design taskが必要として停止",
    ):
        assert required in reading, required
    assert not any(line.startswith("5. 対象の`docs/designs/") for line in reading.splitlines())
    assert "生成設計" not in preflight and "model生成一致検証" not in preflight
    units = text.split("## Resolve implementation units\n", 1)[1].split("\n## ", 1)[0]
    for required in ("cloudformation-stacks.properties`だけを読む", "desired.stack.*.name", "`.template`", "`.parameters`", "`.deployOrder`",
                     "desired.deployment.maxConcurrentStacks", "実効値は既存契約どおり1", "Implement inputとして読まない"):
        assert required in units, required
    implementation = text.split("## Implement and validate\n", 1)[1].split("\n## ", 1)[0]
    for required in ("authoritative model propertiesだけ", "`desired.row.*`", "`.document`", "desired.resource.*.anchor", "desired.resource.*.logicalId",
                     "producer model properties", "parentReference", "generated Markdown本文を読まない", "physical IDをIaCへ直書きしない"):
        assert required in implementation, required
    finish = text.split("## Verify and finish\n", 1)[1]
    for required in ("blueprint-loop.py --mode task", "read-onlyの`sync-model.py`", "不一致ならFAIL", "check_design_tables",
                     "check_design_links", "check_stack_designs", "validationを省略・弱体化せず"):
        assert required in finish and required not in preflight, required


def check_update_flow_prompt() -> None:
    text = (SCRIPT.parents[2] / "framework/prompts/codex/05_update.md").read_text(encoding="utf-8")

    def validate(prompt):
        # Check instruction/engine boundaries and executable examples, not a full prose snapshot.
        sections = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", prompt, re.M | re.S))

        def engine(body, heading):
            return body.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0]

        def commands(body):
            return [[token.strip("[]") for token in shlex.split(line)] for line in re.findall(
                r"(?:^|`)(python\s+framework/scripts/[^`\n]+)", body, re.M)]

        reading = sections["Read before changing files"]
        for token in ("authoritative model properties", "desired.row.*.document", "inputとして読まない",
                      "--resource <resource-selector>", "parentReference", "path／file stem", "必要なpart"):
            assert token in reading, token
        instructions = [line for line in reading.splitlines() if re.match(r"\d+\. ", line)]
        assert instructions and not any(re.search(
            r"docs/designs/|cloudformation-stacks\.md|0[34]_(?:implement|deploy)\.md", line
        ) for line in instructions), "generated artifacts/full prompts returned to the input list"
        scope = sections["Resolve target and scope from repository state"]
        assert "cloudformation-stacks.properties`だけ" in scope
        assert "cloudformation-stacks.md" not in scope, "duplicate stack scope input"
        for token in ("desired.stack.*.name", ".template", ".parameters", ".deployOrder",
                      "desired.deployment.maxConcurrentStacks", "workspace", "backend", "variable input"):
            assert token in scope, token
        issue = commands(sections["Unresolved issue gate"])
        assert len(issue) == 1 and issue[0][1].endswith("/issue_gate.py")
        assert issue[0].count("--service") == 2, "repeatable services must share one process example"
        assert "--task" in sections["Unresolved issue gate"]

        deploy = sections["Preflight and deploy"]
        dependency = engine(deploy, "CloudFormation read-only dependency check")
        for token in ("--read-only", "describe-stacks", "list-exports", "ExportingStackId",
                      "NOT_STARTED", "--pause-after-group", "通常のCloudFormation updateでは実行しない"):
            assert token in dependency, token
        cfn = engine(deploy, "CloudFormation controller")
        cfn_commands = commands(cfn)
        assert len(cfn_commands) == 1 and cfn_commands[0][1].endswith("/cloudformation-deploy.py")
        for option in ("--environment", "--alias", "--stack", "--state", "--profile"):
            assert option in cfn_commands[0], option
        for token in ("最終preflight責任者", "account", "region", "issue gate", "immutable input",
                      "cfn-lint", "validate-template", "MaxConcurrentStacks", "COMPLETE", "--resume"):
            assert token in cfn, token
        terraform = engine(deploy, "Terraform preflight and apply")
        tf_commands = commands(terraform)
        assert len(tf_commands) == 2 and all(c[1].endswith("/check-deploy-context.py") for c in tf_commands)
        assert "--alias" in tf_commands[0] and "--aws-account-id" in tf_commands[1]
        assert commands(deploy) == cfn_commands + tf_commands, "standalone normal CFn preflight was added"
        for token in ("terraform fmt -check", "terraform validate", "terraform plan -out=",
                      "terraform apply", "保存済みplan binary", "partial apply", "AWS_PROFILE"):
            assert token in terraform, token

        post = sections["Post-deployment model sync"]
        cfn_post = engine(post, "CloudFormation")
        assert not commands(cfn_post), "Agent must not run a second CFn observed/sync process"
        for token in ("controller所有", "cloudformation_observed.py", "IDENTIFIER_OUTPUT",
                      "PhysicalResourceId", "全参照元", "再実行しない", "AMBIGUOUS_OBSERVED_MAPPING"):
            assert token in cfn_post, token
        assert all("再実行しない" in line for line in cfn_post.splitlines() if "--write" in line)
        tf_post = engine(post, "Terraform")
        for token in ("Terraform output", "state", "non-sensitive", "IDENTIFIER_OUTPUT", "全参照元",
                      "PENDING_DEPLOY", "sync-model.py --write"):
            assert token in tf_post, token
        approval = sections["Confirm unapproved delete/replacement"]
        for token in ("未実行", "human確認待ち", "--approve-change-set", "CREATE_COMPLETE/AVAILABLE",
                      "fingerprint", "一部だけの承認では実行しない", "以前の承認を流用しない"):
            assert token in approval, token
        finish = sections["Verify and finish"]
        loop = commands(finish)
        assert len(loop) == 1 and loop[0][1].endswith("/blueprint-loop.py")
        assert loop[0][loop[0].index("--mode") + 1] == "task"
        assert "--task-file" in loop[0] and "--all" not in loop[0]
        for token in ("Validation scope", "Acceptance checks", "read-only", "不一致ならFAIL",
                      "validation cache", "service parallelism", "framework全回帰を追加しない"):
            assert token in finish, token

    validate(text)
    # Prohibitions alone must not hide contradictory executable/read instructions.
    regressions = [
        text.replace("6. Design scopeの正本", "6. 対象の`docs/designs/<environment>/<target-directory>/*.md`と関連JSON artifact\n7. Design scopeの正本", 1),
        text.replace("cloudformation-stacks.properties`だけ", "cloudformation-stacks.properties`と`cloudformation-stacks.md`", 1),
        text.replace("### CloudFormation controller\n", "### CloudFormation controller\n\npython framework/scripts/check-deploy-context.py --environment <environment> --alias <alias>\n", 1),
        text.replace("### CloudFormation\n", "### CloudFormation\n\npython framework/scripts/sync-model.py --write --service <service-id>\n", 1),
        text.replace("python framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-name>.md", "最終validationを省略する", 1),
    ]
    for index, regression in enumerate(regressions, 1):
        assert regression != text
        try:
            validate(regression)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"Update prompt regression {index} was accepted")


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

## リソース詳細

<a id="vpc-vpc-app-dev"></a>

### EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | vpc-app-dev | VPCを識別するNameタグの値 |
| 2 | VpcId | PENDING_DEPLOY | VPCを一意に識別するID |

<a id="vpc-sbnt-app-dev-private-01"></a>

### EC2.Subnet: sbnt-app-dev-private-01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | sbnt-app-dev-private-01 | Subnetを識別するNameタグの値 |
| 2 | SubnetId | PENDING_DEPLOY | Subnetを一意に識別するID |
| 3 | VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
""",
            encoding="utf-8",
        )
        metadata = {design: ("vpc", ("EC2.VPC", "EC2.Subnet"))}
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.DesignSchemaCatalog(repository)
        validator.check_design_tables(metadata, catalog_types, property_owners, identifier_outputs)
        validator.check_design_links(identifier_outputs)
        assert not validator.errors, validator.errors

        design.write_text(
            design.read_text(encoding="utf-8")
            .replace("VpcId | PENDING_DEPLOY", "VpcId | vpc-0123456789abcdef0")
            .replace("[PENDING_DEPLOY](#vpc-vpc-app-dev)", "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)")
            .replace("SubnetId | PENDING_DEPLOY", "SubnetId | subnet-0123456789abcdef0"),
            encoding="utf-8",
        )
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.DesignSchemaCatalog(repository)
        validator.check_design_tables(metadata, catalog_types, property_owners, identifier_outputs)
        validator.check_design_links(identifier_outputs)
        assert not validator.errors, validator.errors

        deployed = design.read_text(encoding="utf-8")
        design.write_text(
            deployed.replace("vpc-0123456789abcdef0", "vpc-app-dev"), encoding="utf-8"
        )
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.DesignSchemaCatalog(repository)
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


def check_array_source_role_links() -> None:
    from array_display import indexed_rows

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/iam.md"
        path.parent.mkdir(parents=True)
        role = """<a id="iam-role"></a>
### IAM.Role: Role

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RoleName | `app-role` | Role name |

<a id="iam-profile"></a>
### IAM.InstanceProfile: Profile

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
"""
        def errors(label):
            rows = indexed_rows([
                ["1", "InstanceProfileName", "`app-profile`", "Profile name"],
                ["2", "Roles", f"[{label}](#iam-role)", "Selected role"],
            ], "IAM.InstanceProfile")
            content = role + "\n".join("| " + " | ".join(row) + " |" for row in rows) + "\n"
            # Hidden links must not enter reference discovery or broken-link checks.
            content += "<!--\n[hidden](missing.md#missing)\n-->\n"
            assert "<!-- array-source:" in content
            path.write_text(content, encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.check_design_links({}, paths=[path])
            return validator.errors

        assert not errors("app-role"), errors("app-role")
        assert any("IAM Role link must display RoleName" in error for error in errors("wrong-role")), errors("wrong-role")


def check_name_tag_and_identifier_order_contract() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(repository).catalog_design_properties()
    assert MODULE.REQUIRED_NAME_PROPERTIES == {
        "EC2.FlowLog": "EC2.FlowLog.Name",
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
        "EC2.FlowLog",
        "flowlog-venus-stg-non-cde",
        [["1", "EC2.FlowLog.Name", "flowlog-venus-stg-non-cde", "Nameタグの値"]],
    )
    assert not validator.errors, validator.errors

    validator = MODULE.Validator(repository)
    validator.check_required_name_tag(
        path,
        "EC2.FlowLog",
        "flowlog-venus-stg-non-cde",
        [
            ["1", "EC2.FlowLog.Tags[].Key", "Name", "Nameタグのキー"],
            ["2", "EC2.FlowLog.Tags[].Value", "flowlog-venus-stg-non-cde", "Nameタグの値"],
        ],
    )
    assert any("one-row property" in error for error in validator.errors)

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
    assert any("catalog file order" in error for error in validator.errors)


def check_cidr_pending_deploy() -> None:
    repository = SCRIPT.parents[2]
    catalog = MODULE.Validator(repository).catalog_design_properties()
    schema = MODULE.DesignSchemaCatalog(repository)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/stg/123456789012/vpc.md"
        path.parent.mkdir(parents=True)
        valid = """# VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`

## リソース一覧

### EC2.VPC

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [vpc-app-stg](#vpc-vpc-app-stg) | アプリケーションのネットワーク |

## リソース詳細

<a id="vpc-vpc-app-stg"></a>

### EC2.VPC: vpc-app-stg

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `vpc-app-stg` | VPCの名前 |
| 2 | VpcId | `PENDING_DEPLOY` | VPCのID |
| 3 | CidrBlock | `10.0.0.0/16` | VPCのIPv4アドレス範囲 |
"""

        def errors(text):
            path.write_text(text, encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.schema_catalog = schema
            validator.check_design_tables({path: ("vpc", ("EC2.VPC",))}, *catalog)
            validator.check_design_overviews()
            return validator.errors

        assert not errors(valid), errors(valid)
        for pending in ("PENDING_DEPLOY", "`PENDING_DEPLOY`", "[PENDING_DEPLOY](#vpc-vpc-app-stg)"):
            # Reject either table independently, not merely when both agree.
            assert any("CIDR must not use" in error for error in errors(valid.replace("`10.0.0.0/16`", pending, 1)))
            assert any("CIDR must not use" in error for error in errors(valid.replace("CidrBlock | `10.0.0.0/16`", "CidrBlock | " + pending)))
        for prop in ("EC2.Subnet.CidrBlock", "EC2.Route.CidrBlock", "EC2.Route.DestinationCidrBlock", "EC2.SecurityGroupIngress.CidrIp", "EC2.TransitGateway.TransitGatewayCidrBlocks"):
            validator = MODULE.Validator(root)
            validator.check_cidr_value(path, prop, '["10.0.0.0/16","PENDING_DEPLOY"]')
            assert validator.errors, prop
            validator = MODULE.Validator(root)
            validator.check_cidr_value(path, prop, "10.0.0.0/16")
            assert not validator.errors, prop


def check_catalog_display_order() -> None:
    from design_layout import catalog_order_errors

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        material = root / "framework/materials/aws/Example_Resource.properties"
        material.parent.mkdir(parents=True)
        lines = ["Example.Resource.Name=", "Example.Resource.Hidden=", "Example.Resource.Id=IDENTIFIER_OUTPUT", "Example.Resource.Tags[].Key=", "Example.Resource.Tags[].Value="]
        material.write_text("\n".join(lines) + "\n", encoding="utf-8")
        def rows(*properties):
            return [[str(n), "Example.Resource." + prop, "value", "属性"] for n, prop in enumerate(properties, 1)]
        selected = rows("Name", "Id", "Tags[].Key", "Tags[].Value", "Tags[].Key", "Tags[].Value")
        assert not catalog_order_errors("Example.Resource", selected, root)
        assert catalog_order_errors("Example.Resource", rows("Id", "Name"), root)
        assert catalog_order_errors("Example.Resource", rows("Tags[].Value", "Tags[].Key"), root)
        assert catalog_order_errors("Example.Resource", rows("Tags[].Key", "Name", "Tags[].Key"), root)
        material.write_text("\n".join([lines[2], *lines[:2], *lines[3:]]) + "\n", encoding="utf-8")
        assert not catalog_order_errors("Example.Resource", rows("Id", "Name"), root)
        assert catalog_order_errors("Example.Resource", rows("Name", "Id"), root)
        assert len(selected) == 6 and all("Hidden" not in row[1] for row in selected)


def check_event_rule_row_order() -> None:
    repository = SCRIPT.parents[2]
    catalog = MODULE.Validator(repository).catalog_design_properties()
    schema = MODULE.DesignSchemaCatalog(repository)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        design = root / "docs/designs/dev/123456789012/eventbridge.md"
        design.parent.mkdir(parents=True)
        header = """# EventBridge 詳細設計

- Design service ID: `eventbridge`
- Owned catalog resource types: `Events.Rule`

## リソース詳細

<a id="eventbridge-hulftretrievaldetectrule"></a>

### Events.Rule: HulftRetrievalDetectRule

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
"""
        rows = [
            ("Name", "ebr-event-venus-dev-hulft-retrieval-detect"),
            ("State", "DISABLED"),
            ("EventBusName", "default"),
            ("ScheduleExpression", "rate(5 minutes)"),
        ]

        def errors(selected):
            design.write_text(header + "".join(
                f"| {number} | {prop} | `{value}` | ルールの設定 |\n"
                for number, (prop, value) in enumerate(selected, 1)
            ), encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.schema_catalog = schema
            validator.check_design_tables({design: ("eventbridge", ("Events.Rule",))}, *catalog)
            return validator.errors

        assert not errors(rows), errors(rows)
        for selected in (rows[2:3] + rows[:2] + rows[3:], [rows[1], rows[0], *rows[2:]]):
            assert any("catalog file order" in error for error in errors(selected))
        for index in (0, 1):
            for selected in (rows[:index] + rows[index + 1:], rows + [rows[index]]):
                assert any("must appear exactly once" in error for error in errors(selected))
            for value in ("", "UNSET", "PENDING_DEPLOY"):
                selected = rows.copy()
                selected[index] = (rows[index][0], value)
                assert any("must have a confirmed value" in error for error in errors(selected))
        assert not errors([rows[0], ("State", "ENABLED"), *rows[2:]])


def check_s3_bucket_policy_grouping() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(
        repository
    ).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        design = root / "docs" / "designs" / "dev" / "123456789012" / "s3.md"
        artifact = design.parent / "s3" / "app-data-bucket-policy.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"Version":"2012-10-17","Statement":[]}\n', encoding="utf-8")
        kms_design = design.with_name("kms.md")
        kms_design.write_text(
            """# AWS KMS 詳細設計

- Design service ID: `kms`
- Owned catalog resource types: `KMS.Key`, `KMS.Alias`

## リソース詳細

<a id="kms-appdatakey"></a>

### KMS.Key: AppDataKey

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | `1234abcd-12ab-34cd-56ef-1234567890ab` | KMS keyを識別するID |
| 2 | KMS.Alias.AliasName | `alias/app-data` | <a id="kms-appdatakeyalias"></a><!-- logical-id: AppDataKeyAlias --> application data用keyを識別するalias |
""",
            encoding="utf-8",
        )
        valid = """# Amazon S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`, `S3.BucketPolicy`

## リソース詳細

<a id="s3-app-dev-data-123456789012"></a>

### S3.Bucket: app-dev-data-123456789012

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | `app-dev-data-123456789012` | application dataを格納するbucketの名前 |
| 2 | Region | `ap-northeast-1` | bucketを配置するAWS region |
| 3 | BucketEncryption[].KMSMasterKeyID | [alias/app-data](kms.md#kms-appdatakeyalias) | 新規objectのdefault暗号化に使用するKMS key alias |
| 4 | BucketEncryption[].SSEAlgorithm | `aws:kms` | 暗号化方式 |
| 5 | VersioningConfiguration.Status | `Enabled` | objectのversion保持状態 |
| 6 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |
"""
        metadata = {
            design: ("s3", ("S3.Bucket", "S3.BucketPolicy")),
            kms_design: ("kms", ("KMS.Key", "KMS.Alias")),
        }

        def errors(markdown: str) -> list[str]:
            design.write_text(markdown, encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.schema_catalog = MODULE.DesignSchemaCatalog(repository)
            validator.check_design_tables(
                metadata, catalog_types, property_owners, identifier_outputs
            )
            validator.check_design_links(identifier_outputs)
            return validator.errors

        assert not errors(valid)
        wrong_order = valid.replace(
            "| 1 | BucketName | `app-dev-data-123456789012` | application dataを格納するbucketの名前 |\n"
            "| 2 | Region | `ap-northeast-1` | bucketを配置するAWS region |",
            "| 1 | Region | `ap-northeast-1` | bucketを配置するAWS region |\n"
            "| 2 | BucketName | `app-dev-data-123456789012` | application dataを格納するbucketの名前 |",
        )
        assert any("BucketName must be the first row" in error for error in errors(wrong_order))
        other_region = valid.replace("`ap-northeast-1`", "`us-east-1`")
        assert not errors(other_region)
        unset_region = valid.replace("`ap-northeast-1`", "`UNSET`")
        assert any("must be a confirmed AWS region ID" in error for error in errors(unset_region))
        literal_alias = valid.replace(
            "[alias/app-data](kms.md#kms-appdatakeyalias)", "`alias/app-data`"
        )
        assert any("must link to a KMS.Alias" in error for error in errors(literal_alias))
        wrong_alias = valid.replace("[alias/app-data]", "[alias/other]")
        assert any("must display the referenced KMS alias" in error for error in errors(wrong_alias))
        wrong_heading = valid.replace(
            "### S3.Bucket: app-dev-data-123456789012",
            "### S3.Bucket: AppDataBucket",
        )
        assert any("heading identifier must match BucketName" in error for error in errors(wrong_heading))
        explicit_bucket = valid.replace(
            "| 6 | S3.BucketPolicy.PolicyDocument",
            "| 6 | S3.BucketPolicy.Bucket | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | bucket policyを適用するbucket |\n"
            "| 7 | S3.BucketPolicy.PolicyDocument",
        )
        assert any("S3.BucketPolicy.Bucket must be omitted" in error for error in errors(explicit_bucket))
        separate_heading = valid.replace(
            "| 6 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |",
            "\n<a id=\"s3-appdatabucketpolicy\"></a>\n\n"
            "### S3.BucketPolicy: AppDataBucketPolicy\n\n"
            "| No. | Property | Value | Source / Comment |\n"
            "| ---: | --- | --- | --- |\n"
            "| 1 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |",
        )
        assert any("must not have an independent heading" in error for error in errors(separate_heading))


def check_resource_overview() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        design = root / "docs" / "designs" / "dev" / "123456789012" / "s3.md"
        design.parent.mkdir(parents=True)
        valid = """# Amazon S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`

## リソース一覧

### S3.Bucket

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |

## リソース詳細

<a id="s3-app-dev-data-123456789012"></a>

### S3.Bucket: app-dev-data-123456789012

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | `app-dev-data-123456789012` | application dataを格納するbucketの名前 |
"""

        def errors(markdown: str) -> list[str]:
            design.write_text(markdown, encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.check_design_overviews()
            return validator.errors

        assert not errors(valid)
        assert any("resource overview numbering error" in error for error in errors(valid.replace("| 1 | [app-dev-data", "| 2 | [app-dev-data", 1)))
        assert any("Comment must describe the resource in Japanese" in error for error in errors(valid.replace("アプリケーションのデータを保管するbucket |", "resource |", 1)))
        assert any("must state a distinct purpose or role" in error for error in errors(valid.replace("アプリケーションのデータを保管するbucket |", "バケット（app-dev-data-123456789012）の設定 |", 1)))
        sg = valid.replace("S3.Bucket", "EC2.SecurityGroup").replace("app-dev-data-123456789012", "VULNERABILITYSCANCDESECURITYGROUP01")
        sg = sg.replace("アプリケーションのデータを保管するbucket |", "セキュリティグループ（VULNERABILITYSCANCDESECURITYGROUP01）の設定 |", 1)
        assert any("must state a distinct purpose or role" in error for error in errors(sg))
        assert not errors(sg.replace("セキュリティグループ（VULNERABILITYSCANCDESECURITYGROUP01）の設定 |", "脆弱性スキャン用ホストから検査対象への通信を制御する |", 1))
        assert any("resource overview must use No." in error for error in errors(valid.replace("| No. | ResourceName |", "| ResourceName |", 1)))
        extra = valid.replace("| ResourceName | Comment |", "| ResourceName | SSEAlgorithm | Comment |", 1)
        assert any("resource overview must use No." in error for error in errors(extra))
        details_heading = "## リソース詳細\n\n"
        invalid_sections = [
            (valid.replace(details_heading, "", 1), "details heading must appear exactly once"),
            (valid.replace(details_heading, details_heading * 2, 1), "details heading must appear exactly once"),
            (valid.replace(details_heading, "", 1).replace("## リソース一覧", details_heading + "## リソース一覧", 1), "details must follow the overview"),
            (valid.replace(details_heading, "", 1) + "\n" + details_heading, "details must follow the overview"),
            (valid.replace("### S3.Bucket:", "## S3.Bucket:", 1), "detail heading must use H3"),
            (valid.replace("### S3.Bucket:", "#### S3.Bucket:", 1), "detail heading must use H3"),
            (valid.replace(details_heading, "", 1).replace("### S3.Bucket:", details_heading + "### S3.Bucket:", 1), "anchors must be inside resource details"),
            (valid + "\n### 実装注記\n", "details must follow the overview"),
        ]
        for markdown, message in invalid_sections:
            failures = errors(markdown)
            assert any(message in failure for failure in failures), (message, failures)
        assert any("resource overview must use No." in error for error in errors(valid.replace("| ResourceName |", "| BucketName |", 1)))
        missing_row = valid.replace(
            "| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |\n",
            "",
        )
        assert any("must list every detail resource exactly once" in error for error in errors(missing_row))


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
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "framework/prompts/chatbot/service-design.md"
        path.parent.mkdir(parents=True)
        for original, replacement, expected in (
            ("## Naming rule preflight（設計開始gate）", "## Removed gate", "before design questions"),
            ("check-design-naming.py --resource-type", "removed-preflight", "executable naming preflight"),
            ("design契約登録前に`check-design-naming.py`", "removed-handoff", "before task registration"),
        ):
            path.write_text(prompt.replace(original, replacement), encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.check_framework_design_handoff()
            assert any(expected in error for error in validator.errors), validator.errors


def check_subnet_association_overview() -> None:
    spec = importlib.util.spec_from_file_location("sync_model", SCRIPT.with_name("sync-model.py"))
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    association_type = "EC2.SubnetRouteTableAssociation"
    metadata = (
        "# VPC 詳細設計\n\n- Design service ID: `vpc`\n"
        f"- Owned catalog resource types: `EC2.Subnet`, `EC2.RouteTable`, `{association_type}`\n\n"
    )
    subnet_header = "| No. | ResourceName | Comment |"
    subnet_rows = [f"| {number} | [subnet-{number}](#vpc-subnet-{number}) | Subnetの用途 |" for number in range(1, 4)]
    overview = "\n".join([
        "## リソース一覧", "", "### EC2.Subnet", "", subnet_header,
        "| ---: | --- | --- |", *subnet_rows, "",
        "### EC2.RouteTable", "", subnet_header, "| ---: | --- | --- |",
        "| 1 | [route](#vpc-route) | Subnetの経路を管理するtable |", "", "",
    ])
    details = "## リソース詳細\n\n"
    for number in range(1, 4):
        route_table = (
            f"| 3 | EC2.RouteTableId | [rtb-00000001](#vpc-route) | 関連付けるRoute Table |\n"
            if number < 3 else ""
        )
        details += (
            f'<a id="vpc-subnet-{number}"></a>\n\n### EC2.Subnet: subnet-{number}\n\n'
            f"{MODULE.TABLE_HEADER}\n{MODULE.TABLE_ALIGNMENT}\n"
            f"| 1 | EC2.Subnet.SubnetId | `subnet-{number:08d}` | Subnetを識別するID |\n"
            f"| 2 | EC2.Subnet.Name | `subnet-{number}` | SubnetのNameタグ |\n"
            f"{route_table}\n"
        )
    details += (
        '<a id="vpc-route"></a>\n\n### EC2.RouteTable: route\n\n'
        f"{MODULE.TABLE_HEADER}\n{MODULE.TABLE_ALIGNMENT}\n"
        "| 1 | EC2.RouteTable.RouteTableId | `rtb-00000001` | Route Tableを識別するID |\n\n"
    )
    independent = (
        f'<a id="vpc-assoc-1"></a>\n\n### {association_type}: Assoc1\n\n'
        f"{MODULE.TABLE_HEADER}\n{MODULE.TABLE_ALIGNMENT}\n"
        f"| 1 | {association_type}.Id | `rtbassoc-00000001` | 関連付けを識別するID |\n"
        f"| 2 | {association_type}.RouteTableId | [rtb-00000001](#vpc-route) | 関連付けるRoute Table |\n"
        f"| 3 | {association_type}.SubnetId | [subnet-00000001](#vpc-subnet-1) | 関連付けるSubnet |\n\n"
    )
    valid = metadata + overview + details
    legacy_overview = overview.replace("| ResourceName | Comment |", "| ResourceName | RouteTableId | Comment |", 1).replace(
        "| ---: | --- | --- |", "| ---: | --- | --- | --- |", 1
    )
    for row in subnet_rows:
        legacy_overview = legacy_overview.replace(row, row.replace("| Subnetの用途 |", "| [rtb-00000001](#vpc-route) | Subnetの用途 |"), 1)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        design = root / "docs/designs/dev/123456789012/vpc.md"
        design.parent.mkdir(parents=True)

        def errors(markdown):
            design.write_text(markdown, encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.check_design_overviews()
            return validator.errors

        assert not errors(valid), errors(valid)
        merged_model = model.model_for(design, SCRIPT.parents[2])
        # An overview edit must not change resources, references, or observed IDs.
        design.write_text(metadata + legacy_overview + details, encoding="utf-8")
        assert model.model_for(design, SCRIPT.parents[2]) == merged_model
        assert "resourceType=EC2.SubnetRouteTableAssociation" not in merged_model
        assert "desired.row.001-003.property=EC2.SubnetRouteTableAssociation.RouteTableId" in merged_model
        assert "desired.row.001-003.value=[route](#vpc-route)" in merged_model
        assert "observed.row.001-003.value=rtb-00000001" in merged_model
        assert "desired.row.002-003.property=EC2.SubnetRouteTableAssociation.RouteTableId" in merged_model
        assert "EC2.SubnetRouteTableAssociation.Id" not in merged_model
        assert "EC2.SubnetRouteTableAssociation.SubnetId" not in merged_model

        design.write_text(
            valid.replace("EC2.RouteTableId", f"{association_type}.RouteTableId"),
            encoding="utf-8",
        )
        catalog_types, property_owners, identifier_outputs = MODULE.Validator(
            SCRIPT.parents[2]
        ).catalog_design_properties()
        validator = MODULE.Validator(root)
        validator.schema_catalog = MODULE.DesignSchemaCatalog(SCRIPT.parents[2])
        validator.check_design_tables(
            {design: ("vpc", ("EC2.Subnet", "EC2.RouteTable", association_type))},
            catalog_types,
            property_owners,
            identifier_outputs,
        )
        assert any(
        "must use its Markdown display alias" in error
            for error in validator.errors
        ), validator.errors

        pending = valid
        for identifier in ("rtb-00000001", *(f"subnet-{number:08d}" for number in range(1, 4))):
            pending = pending.replace(identifier, "PENDING_DEPLOY")
        assert not errors(pending), errors(pending)

        bad_designs = [
            (valid + independent, "types must match"),
            (metadata + legacy_overview + details, "resource overview must use No."),
            (valid.replace(subnet_rows[0] + "\n", ""), "must list every detail resource exactly once"),
        ]
        for markdown, message in bad_designs:
            failures = errors(markdown)
            assert any(message in failure for failure in failures), (message, failures)


def check_cloudformation_yaml_rules() -> None:
    trust_body = """        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: ec2.amazonaws.com
            Action: sts:AssumeRole
"""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        template = root / "infra/cloudformation/templates/iam.yaml"
        template.parent.mkdir(parents=True)

        def errors(yaml: str) -> list[str]:
            template.write_text(yaml, encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.check_cloudformation_yaml_rules()
            return validator.errors

        valid = (
            "Resources:\n"
            "  RoleA:\n"
            "    Type: AWS::IAM::Role\n"
            "    Properties:\n"
            "      AssumeRolePolicyDocument:\n"
            + trust_body
            + "\n  RoleB:\n"
            "    Type: AWS::IAM::Role\n"
            "    Properties:\n"
            "      AssumeRolePolicyDocument:\n"
            + trust_body
            + "      JobId: !Select [0, !Split ['|', !Ref GlueJob]]\n"
            "      Imported: !ImportValue fixed-export\n"
            "      Description: 'Fn::Select: &shared *alias <<: is text'\n"
            "      UserData: |\n"
            "        Ref: &shared *alias <<: is text too\n"
            "      Extra: {Fn::Length: [a, b]}\n"
            "\n  Consumer:\n"
            "    Type: AWS::EC2::Instance\n"
        )
        assert not errors(valid), errors(valid)
        assert any(
            "resources must be separated by a blank line" in error
            for error in errors(valid.replace("\n  RoleB:", "  RoleB:", 1))
        )
        for bad in (
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId:\n        Fn::Select:\n          - 0\n          - Ref: GlueJob"),
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Select: [0, {Ref: GlueJob}]}"),
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {'Fn::Select': [0, !Ref GlueJob]}"),
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Join: ['-', [a, b]]}"),
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Sub: '${AWS::Region}'}"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported:\n        Fn::ImportValue: fixed-export"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported:\n        Fn::ImportValue:\n          !Sub '${NetworkStack}-SubnetID'"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported:\n        'Fn::ImportValue': !Sub '${NetworkStack}-SubnetID'"),
        ):
            assert any("must use YAML short form" in error for error in errors(bad)), errors(bad)

        block_array = valid.replace(
            "JobId: !Select [0, !Split ['|', !Ref GlueJob]]",
            "JobId: !Select\n        - 0\n        - !Split ['|', !Ref GlueJob]",
        )
        assert any("must use YAML flow form" in error for error in errors(block_array)), errors(block_array)
        join_block_array = valid.replace(
            "JobId: !Select [0, !Split ['|', !Ref GlueJob]]",
            "JobId: !Join\n        - '-'\n        - [a, b]",
        )
        assert any("must use YAML flow form" in error for error in errors(join_block_array)), errors(join_block_array)

        for forbidden in (
            valid.replace("AssumeRolePolicyDocument:\n", "AssumeRolePolicyDocument: &sharedTrustPolicy\n", 1),
            valid.replace("AssumeRolePolicyDocument:\n" + trust_body, "AssumeRolePolicyDocument: *sharedTrustPolicy\n", 1),
            valid.replace("AssumeRolePolicyDocument:\n" + trust_body, "AssumeRolePolicyDocument:\n        <<: {}\n", 1),
        ):
            assert any("anchor/alias/merge is forbidden" in error for error in errors(forbidden)), errors(forbidden)
        different = valid.replace("ec2.amazonaws.com", "lambda.amazonaws.com", 1)
        assert not errors(different), errors(different)

        consumer = "\n  Consumer:\n    Type: AWS::EC2::Instance\n"
        boundary_error = "must share the consuming resource template"
        marker = "Metadata:\n  RolePlacement: standalone\n"
        role_only = "Resources:\n  Role:\n    Type: AWS::IAM::Role\n"
        assert any("Role-only template requires" in error for error in errors(valid.replace(consumer, "")))
        assert any("Role-only template requires" in error for error in errors(role_only))
        assert not errors(marker + role_only)
        assert not errors(
            marker + role_only + "\n  Policy:\n    Type: AWS::IAM::Policy\n"
        )
        assert not errors(
            marker + role_only + "\n  Policy:\n    Type: AWS::IAM::ManagedPolicy\n"
        )
        assert any("requires a Role-only template" in error for error in errors(marker + valid))
        assert any(boundary_error in error for error in errors("Resources:\n  Logs:\n    Type: AWS::Logs::LogGroup\n"))
        assert any(boundary_error in error for error in errors(
            "Resources:\n  Role:\n    Type: AWS::IAM::Role\n\n  Logs:\n    Type: AWS::Logs::LogGroup\n"
        ))
        assert any(boundary_error in error for error in errors("Resources:\n  Filter:\n    Type: AWS::Logs::SubscriptionFilter\n"))
        assert any(boundary_error in error for error in errors(
            "Resources:\n  Role:\n    Type: AWS::IAM::Role\n\n  Profile:\n    Type: AWS::IAM::InstanceProfile\n"
        ))
        assert any(boundary_error in error for error in errors(
            "Resources:\n  Group:\n    Type: AWS::EC2::SecurityGroup\n  Ingress:\n    Type: AWS::EC2::SecurityGroupIngress\n"
        ))
        assert any(boundary_error in error for error in errors(
            "Resources:\n  Egress:\n    Type: AWS::EC2::SecurityGroupEgress\n"
        ))
        assert not errors("Resources:\n  Logs:\n    Type: AWS::Logs::LogGroup\n" + consumer)
        assert not errors("Resources:\n  Group:\n    Type: AWS::EC2::SecurityGroup\n" + consumer)


def check_cloudformation_environment_parameters() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        template = root / "infra/cloudformation/templates/role.yaml"
        parameter = root / "infra/cloudformation/parameters/dev/123456789012/role.json"
        template.parent.mkdir(parents=True)
        parameter.parent.mkdir(parents=True)
        valid_template = """Parameters:
  Environment:
    Type: String
  NamePrefix:
    Type: String
Resources:
  Role:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'
"""

        def errors(yaml: str, values: list[dict[str, str]]) -> list[str]:
            template.write_text(yaml, encoding="utf-8")
            parameter.write_text(json.dumps(values), encoding="utf-8")
            validator = MODULE.Validator(root)
            validator.check_cloudformation_environment_parameters()
            return validator.errors

        valid_values = [
            {"ParameterKey": "Environment", "ParameterValue": "dev"},
            {"ParameterKey": "NamePrefix", "ParameterValue": "app"},
        ]
        assert not errors(valid_template, valid_values)
        assert not errors(valid_template.replace("  ", "    "), valid_values)
        assert not errors(valid_template.replace("!Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'", "!Ref Environment"), valid_values)
        assert any("without Parameters.Environment" in error for error in errors(
            valid_template.replace("  Environment:\n    Type: String\n", ""), valid_values
        ))
        assert any("must equal target environment" in error for error in errors(
            valid_template, valid_values[1:]
        ))
        assert any("must equal target environment" in error for error in errors(
            valid_template, [{**valid_values[0], "ParameterValue": "prod"}, valid_values[1]]
        ))
        assert any("contains Environment component" in error for error in errors(
            valid_template, [valid_values[0], {**valid_values[1], "ParameterValue": "app-dev"}]
        ))
        assert any("contains Environment component" in error for error in errors(
            valid_template.replace("!Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'", "!Ref NamePrefix"),
            [{"ParameterKey": "NamePrefix", "ParameterValue": "app-dev-role"}],
        ))
        assert not errors(
            valid_template, [valid_values[0], {**valid_values[1], "ParameterValue": "device"}]
        )

def check_cloudformation_stack_design() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "docs" / "designs" / "dev" / "123456789012"
        target.mkdir(parents=True)
        (target / "glue.md").write_text(
            '<a id="glue-job01"></a>\n### Glue.Job: Job01\n<a id="glue-job02"></a>\n### Glue.Job: Job02\n', encoding="utf-8"
        )
        stack_file = target / "cloudformation-stacks.md"
        stack_file.write_text(
            """# CloudFormation stack 詳細設計

<!-- max-concurrent-stacks: 2 -->

## Stack一覧
| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 10 | stack-job-01 | job.yaml | job-01.json | 日次jobを配置するstack |
| 2 | 10 | stack-job-02 | job.yaml | job-02.json | 月次jobを配置するstack |
""",
            encoding="utf-8",
        )
        template = root / "infra" / "cloudformation" / "templates" / "job.yaml"
        template.parent.mkdir(parents=True)
        template.write_text(
            "Parameters:\n  Environment:\n    Type: String\nResources:\n  Job:\n    Type: AWS::Glue::Job\n    Properties:\n      Name: !Ref Environment\n",
            encoding="utf-8",
        )
        parameter_dir = root / "infra" / "cloudformation" / "parameters" / "dev" / "123456789012"
        parameter_dir.mkdir(parents=True)
        for name in ("job-01", "job-02"):
            (parameter_dir / f"{name}.json").write_text(
                '[{"ParameterKey":"Environment","ParameterValue":"dev"}]\n', encoding="utf-8"
            )

        def errors() -> list[str]:
            validator = MODULE.Validator(root)
            validator.accounts[("dev", "123456789012")] = {
                "account": "123456789012", "region": "ap-northeast-1", "alias": "", "engine": "cloudformation"
            }
            validator.check_stack_designs()
            validator.check_cloudformation_environment_parameters()
            return validator.errors

        assert not errors(), errors()
        original = stack_file.read_text(encoding="utf-8")
        for old, replacement in (("<!-- max-concurrent-stacks: 2 -->", "<!-- max-concurrent-stacks: 0 -->"),
                                 ("<!-- max-concurrent-stacks: 2 -->", "<!-- max-concurrent-stacks: -1 -->"),
                                 ("| 1 | 10 |", "| 1 | 0 |"), ("| 1 | 10 |", "| 1 | -1 |"),
                                 ("| 1 | 10 |", "| 1 | abc |")):
            stack_file.write_text(original.replace(old, replacement), encoding="utf-8")
            assert any("integer >= 1" in error for error in errors()), errors()
        stack_file.write_text(original, encoding="utf-8")
        stack_file.write_text(original.replace("| 2 | 10 | stack-job-02 | job.yaml", "| 2 | 10 | stack-job-01 | job.yaml"), encoding="utf-8")
        assert any("duplicate stack name" in error for error in errors())
        stack_file.write_text(original.replace("job-02.json", "job-01.json"), encoding="utf-8")
        assert any("parameter file belongs to multiple stacks" in error for error in errors())
        stack_file.write_text(original.replace("| job.yaml |", "| ../job.yaml |", 1), encoding="utf-8")
        assert any("invalid stack template filename" in error for error in errors())
        stack_file.write_text(original.replace("| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |", "| StackName | Template | Parameters |", 1), encoding="utf-8")
        assert any("invalid CloudFormation stack design header" in error for error in errors())
        stack_file.write_text(original.replace("| 2 | 10 | stack-job-02", "| 3 | 10 | stack-job-02"), encoding="utf-8")
        assert any("No. must be sequential" in error for error in errors())
        stack_file.write_text(original.replace("| 月次jobを配置するstack |", "| |"), encoding="utf-8")
        assert any("invalid CloudFormation stack design row" in error for error in errors())
        stack_file.write_text(original.replace("月次jobを配置するstack", "monthly job"), encoding="utf-8")
        assert any("stack Comment must describe its purpose in Japanese" in error for error in errors())
        stack_file.write_text(original, encoding="utf-8")
        (parameter_dir / "job-02.json").write_text("[]\n", encoding="utf-8")
        assert any("must equal target environment" in error for error in errors())
        (parameter_dir / "job-02.json").write_text(
            '[{"ParameterKey":"Environment","ParameterValue":"dev"}]\n', encoding="utf-8"
        )


def check_stack_mapping_targets():
    from model_design import markdown_for
    import shutil
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(SCRIPT.parents[2] / "framework", root / "framework")
        model_dir = root / "model/dev/123456789012"
        model_dir.mkdir(parents=True)
        target = root / "docs/designs/dev/123456789012"
        target.mkdir(parents=True)
        values = {"desired.stack.001.name": "cfn-stack-app-dev-ism", "desired.stack.001.template": "department.yaml",
                  "desired.stack.001.parameters": "ism.json", "desired.stack.001.deployOrder": "10", "display.stack.001.comment": "部署用リソースを配置するstack",
                  }
        source = model_dir / "cloudformation-stacks.properties"
        source.write_text("\n".join(k + "=" + v for k, v in values.items()))
        path = target / "cloudformation-stacks.md"
        path.write_text(markdown_for(path, values, root))
        model = model_dir / "ec2.properties"
        model.write_text("desired.resource.001.resourceType=EC2.VPC\ndesired.resource.001.cfn-logicalId=cfn-stack-app-dev-ism-DepartmentVpc\n")
        def errors():
            validator = MODULE.Validator(root)
            validator.accounts[("dev", "123456789012")] = {"account": "123456789012", "region": "ap-northeast-1", "alias": "", "engine": "cloudformation"}
            validator.check_stack_designs()
            return validator.errors
        assert not errors(), errors()
        model.write_text(model.read_text() + "desired.resource.001.resourceMode=IMPORT\n")
        assert any("CREATE" in error for error in errors()), errors()
        model.write_text(model.read_text().replace("cfn-stack-app-dev-ism-DepartmentVpc", "absent-DepartmentVpc").replace("desired.resource.001.resourceMode=IMPORT\n", ""))
        assert any("undeclared stack" in error for error in errors()), errors()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/iam.md"
        path.parent.mkdir(parents=True)
        path.write_text('<a id="iam-confirmed-role"></a>\n')
        model = root / "model/dev/123456789012/iam.properties"
        model.parent.mkdir(parents=True)
        model.write_text('desired.resource.007.resourceType=IAM.Role\ndesired.resource.007.anchor=iam-confirmed-role\n')
        validator = MODULE.Validator(root)
        validator.check_markdown_iam_policy_artifacts(path, "007", [["1", "AssumeRolePolicyDocument", "[Trust](iam/confirmed-role-trust-policy.json)", "信頼ポリシー"]])
        assert not validator.errors, validator.errors
    prompt = (SCRIPT.parents[2] / "framework/prompts/codex/03_implement.md").read_text()
    assert "python framework/scripts/cloudformation_observed.py --environment" in prompt
    assert "生成・変更後も" in prompt and "identifier行の不足を自動補完せず" in prompt


def check_rule_reading_contract() -> None:
    validator = MODULE.Validator(SCRIPT.parents[2])
    validator.check_framework_rule_readings()
    assert not validator.errors, validator.errors
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "README.md").write_text("reference fixture\n")
        rule = root / "framework/rules/fixture.md"
        rule.parent.mkdir(parents=True)
        rule.write_text("## Present\nrequired rule\n")
        agents = root / "AGENTS.md"
        agents.write_text("[rule](framework/rules/fixture.md#missing)\n")
        validator = MODULE.Validator(root)
        validator.check_framework_rule_readings()
        assert len(validator.errors) == 1 and "missing rule section" in validator.errors[0], validator.errors
        agents.write_text("[rule](framework/rules/fixture.md#present)\n")
        validator = MODULE.Validator(root)
        validator.check_framework_rule_readings()
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
    assert MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch("01_initialize.md")
    assert not MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch("initialize.md")
    check_rule_reading_contract()
    check_task_contract()
    check_idle_without_active_task()
    check_task_type_dispatch()
    check_optional_alias_targets()
    check_optional_alias_contract()
    check_model_task_boundaries()
    check_schema_backed_design_rows()
    check_description_design_constraints()
    check_implementation_preflight_prompt()
    check_update_flow_prompt()
    check_identifier_propagation()
    check_array_source_role_links()
    check_name_tag_and_identifier_order_contract()
    check_cidr_pending_deploy()
    check_catalog_display_order()
    check_event_rule_row_order()
    check_s3_bucket_policy_grouping()
    check_resource_overview()
    check_subnet_association_overview()
    check_cloudformation_yaml_rules()
    check_cloudformation_environment_parameters()
    check_cloudformation_stack_design()
    check_stack_mapping_targets()
    check_design_handoff_prompt()
    print("validate-blueprint: PASS (63 focused checks)")


if __name__ == "__main__":
    main()
