"""Task contracts, dispatch, boundaries and project topology."""

from __future__ import annotations
import json
import io
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch
from test_support.validator import MODULE, SCRIPT, project, git_project, commit, write


def check_task_contract() -> None:
    with git_project() as root:
        (root / "tasks").mkdir()
        governance = """# Test

## Task contract

- Task type: `governance`

## Required changes

- [R1] READMEを更新する。

## Acceptance checks

- [R1] `changed:README.md`

## Allowed paths

- `README.md`
- `tasks/active.md`
"""
        write(root / "tasks" / "active.md", governance)
        write(root / "README.md", "changed\n")
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert not validator.errors
        assert validator.requirement_ids == ["R1"]

        active = root / "tasks" / "active.md"
        write(active,
            active.read_text(encoding="utf-8").replace("- [R1] `changed:README.md`", "")
        )
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert "requirement has no Acceptance check: R1" in validator.errors

        infrastructure = governance.replace(
            "- Task type: `governance`", "- Task type: `infrastructure`\n- Infrastructure phase: `implement`"
        ).replace("READMEを更新する。", "IaCを更新する。")
        write(active, infrastructure)
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert not validator.errors, validator.errors
        assert validator.infrastructure_phase == "implement"

        write(active,
            active.read_text(encoding="utf-8").replace(
                "- Infrastructure phase: `implement`\n", ""
            )
        )
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert any("Infrastructure phase must appear exactly once" in error for error in validator.errors)


def check_idle_without_active_task() -> None:
    with git_project() as root:

        validator = MODULE.Validator(root)
        validator.check_task_scope()
        validator.check_tasks()
        assert not validator.errors, validator.errors

        (root / "tasks").mkdir()
        write(root / "tasks" / "active.md", "# completed\n")
        commit(root, ["tasks/active.md"], "active-task")
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

        write(root / "README.md", "changed\n")
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert any("active task prompt missing" in error for error in validator.errors)


def check_destroy_phase() -> None:
    with git_project() as root:
        model = root / "model/dev/123456789012/ec2.properties"
        model.parent.mkdir(parents=True)
        write(model, "desired.row.001-001.value=`fixed`\nobserved.row.001-001.value=`vpc-old`\n")
        commit(root, ["."], "baseline")
        validator = MODULE.Validator(root)
        validator.task_type = "infrastructure"
        validator.infrastructure_phase = "destroy"
        validator.changed_paths = {"model/dev/123456789012/ec2.properties", "tasks/destroy.md"}
        write(model, "desired.row.001-001.value=`fixed`\nobserved.row.001-001.value=`PENDING_DEPLOY`\n")
        validator.check_task_type_requirements()
        validator.check_task_boundary(root / "tasks/destroy.md")
        assert not validator.errors, validator.errors
        write(model, "desired.row.001-001.value=`changed`\nobserved.row.001-001.value=`PENDING_DEPLOY`\n")
        validator.check_task_type_requirements()
        assert any("must not change desired/display" in error for error in validator.errors)
        validator.changed_paths = {"infra/cloudformation/templates/a.yaml", "framework/scripts/a.py", "project.json", "tests/results/a.md"}
        validator.check_task_type_requirements()
        validator.check_task_boundary(root / "tasks/destroy.md")
        assert any("must not change IaC" in error for error in validator.errors)
        assert sum("destroy phase permits only" in error for error in validator.errors) == 4
        # Exercise run() dispatch: destroy retains common/model checks but never enters IaC.
        validator = MODULE.Validator(root)
        validator.scope = {("dev", "123456789012", "ec2")}
        validator.task_type = "infrastructure"
        validator.infrastructure_phase = "destroy"
        banned = {"check_iac_selection", "check_cloudformation_yaml_rules", "check_cloudformation_environment_parameters"}
        invoked = []
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name in ("check_structure", "check_task_scope", "check_tasks", "check_project_topology", "check_validation_scope",
                         "check_model_files", "check_issue_gate", "check_task_type_requirements", "check_initialized_paths",
                         "check_catalog", "check_resource_layout", "check_scoped_designs", "check_designs", "check_observed_values",
                         "check_acceptance_checks", *banned):
                def check(*args, name=name):
                    assert name not in banned, name
                    invoked.append(name)
                stack.enter_context(patch.object(validator, name, check))
            with redirect_stdout(io.StringIO()):
                assert validator.run() == 0
        assert {"check_task_scope", "check_scoped_designs", "check_acceptance_checks"} <= set(invoked)


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
    assert any("infrastructure deploy phase must not change IaC" in error for error in validator.errors)

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


    # Generated equality is checked separately; views need not have a Git diff.
    for changed in (
        {"model/dev/123456789012/logs.properties"},
        {"model/dev/123456789012/logs/part-001.properties"},
        {"model/dev/123456789012/logs.properties", "model/dev/123456789012/vpc.properties",
         "docs/designs/dev/123456789012/vpc.md"},
        {"docs/designs/dev/123456789012/vpc.md"},
        {"docs/designs/dev/123456789012/iam/role01-policy.json"},
        set(),
    ):
        validator = MODULE.Validator(SCRIPT.parents[2])
        validator.task_type = "design"
        validator.changed_paths = changed | {"tasks/active.md"}
        validator.check_task_type_requirements()
        assert bool(validator.errors) == (not any(path.startswith("model/") for path in changed)), validator.errors


def check_optional_alias_targets() -> None:
    with project() as root:
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
        write(root / "project.json",
            json.dumps(topology) + "\n"
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
            write(root / "project.json", json.dumps({**topology, "targets": targets}) + "\n")
            validator = MODULE.Validator(root)
            validator.check_project_topology()
            assert not validator.errors, validator.errors
            assert set(validator.accounts) == {("dev", "cde"), ("dev", "non-cde"), ("sandbox", "210987654321")}
        write(root / "project.json", json.dumps({**topology, "suffix": {"dev": "blue"}}) + "\n")
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
            write(root / "project.json",
                json.dumps({"projectName": "test", "targets": targets}) + "\n"
            )
            validator = MODULE.Validator(root)
            validator.check_project_topology()
            assert any(expected_error in error for error in validator.errors), (
                expected_error,
                validator.errors,
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
