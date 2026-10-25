"""Task contracts, dispatch, boundaries and project topology."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack as ExitStack
from unittest.mock import patch as patch

import model.importing.scope as _imports_model_importing_scope
import support.model_sources as _imports_support_model_sources
from support.validator import MODULE, SCRIPT
from support.validator import project as project
from support.validator import write as write
from utils.aws.identity import IdentityError


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
        write(root / "project.json", json.dumps(topology) + "\n")
        for path in (
            "docs/designs/dev/cde",
            "docs/designs/dev/non-cde",
            "docs/designs/sandbox/210987654321",
            "model/dev/cde",
            "model/dev/non-cde",
            "model/sandbox/210987654321",
            "infra/cloudformation/parameters/dev/cde",
            "infra/cloudformation/parameters/dev/non-cde",
            "infra/210987654321/terraform/sandbox",
        ):
            (root / path).mkdir(parents=True)

        validator = MODULE.Validator(root)
        validator.check_project_topology()
        validator.check_initialized_paths()
        assert not validator.errors, validator.errors
        assert validator.accounts[("dev", "cde")]["account"] == "123456789012"
        assert validator.accounts[("dev", "non-cde")]["account"] == "123456789012"
        assert (
            validator.accounts[("sandbox", "210987654321")]["account"] == "210987654321"
        )

        restrict = _imports_model_importing_scope.restrict
        cross_environment = [
            *topology["targets"],
            *[{**target, "environment": "stg"} for target in topology["targets"][:2]],
        ]
        write(
            root / "project.json",
            json.dumps({**topology, "targets": cross_environment}) + "\n",
        )
        validator = MODULE.Validator(root)
        validator.check_project_topology()
        assert not validator.errors, validator.errors
        with restrict(("dev", "cde", "vpc")):
            validator = MODULE.Validator(root)
            validator.check_project_topology()
            assert not validator.errors, validator.errors
            assert set(validator.accounts) == {("dev", "cde")}
        duplicates = [
            topology["targets"][0],
            {**topology["targets"][1], "alias": "cde"},
        ]
        write(
            root / "project.json",
            json.dumps({**topology, "targets": duplicates}) + "\n",
        )
        for identity in (None, ("dev", "cde", "vpc")):
            with restrict(identity):
                validator = MODULE.Validator(root)
                validator.check_project_topology()
                assert any(
                    "duplicate target directory" in error for error in validator.errors
                ), validator.errors

        # Each environment/alias may have its own suffix; paths and account identity stay intact.
        suffix_targets = [
            {**target, "suffix": suffix}
            for target, suffix in zip(
                topology["targets"], ("blue", "green-01", "sandbox-token"), strict=False
            )
        ]
        for targets in (suffix_targets, [suffix_targets[0], *topology["targets"][1:]]):
            write(
                root / "project.json",
                json.dumps({**topology, "targets": targets}) + "\n",
            )
            validator = MODULE.Validator(root)
            validator.check_project_topology()
            assert not validator.errors, validator.errors
            assert set(validator.accounts) == {
                ("dev", "cde"),
                ("dev", "non-cde"),
                ("sandbox", "210987654321"),
            }
        write(
            root / "project.json",
            json.dumps({**topology, "suffix": {"dev": "blue"}}) + "\n",
        )
        validator = MODULE.Validator(root)
        validator.check_project_topology()
        assert any(
            "must contain only projectName and targets" in error
            for error in validator.errors
        ), validator.errors

        with patch(
            "validation.project.select_profile",
            side_effect=IdentityError("identity rejected"),
        ) as select:
            write(root / "project.json", json.dumps(topology) + "\n")
            validator = MODULE.Validator(root)
            validator.check_project_topology()
            assert any("invalid AWS profile" in error for error in validator.errors)
            assert select.call_count == 2

        invalid_targets = [
            (
                [{**topology["targets"][2], "environment": "modules"}],
                "Terraform environment conflicts with shared modules directory",
            ),
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
                [
                    {**topology["targets"][0], "awsRegion": "Tokyo"},
                    *topology["targets"][1:],
                ],
                "invalid AWS region ID",
            ),
            (
                [
                    {**topology["targets"][0], "awsRegion": "ap--1"},
                    *topology["targets"][1:],
                ],
                "invalid AWS region ID",
            ),
            (
                [{**topology["targets"][0], "awsRegion": ""}, *topology["targets"][1:]],
                "AWS region is required",
            ),
        ]
        for invalid in (
            None,
            123,
            {},
            [],
            "",
            "UNSET",
            "Blue",
            " padded ",
            "blue\n",
            "blue\0",
            "-blue",
            "blue-",
            "blue--green",
            "ｂｌｕｅ",
        ):
            invalid_targets.append(
                (
                    [
                        {**topology["targets"][0], "suffix": invalid},
                        *topology["targets"][1:],
                    ],
                    "values must be strings"
                    if not isinstance(invalid, str)
                    else "invalid naming suffix",
                )
            )
        invalid_targets.append(
            (
                [
                    topology["targets"][0],
                    {
                        **topology["targets"][1],
                        "awsAccountId": "210987654321",
                        "awsExecutionAccountId": "999999999999",
                        "iacEngine": "terraform",
                    },
                ],
                "same environment/AWS execution account must use one IaC engine",
            )
        )
        invalid_targets.append(
            (
                [
                    {**topology["targets"][0], "profile": "unsupported"},
                    *topology["targets"][1:],
                ],
                "optional alias/awsProfile/awsExecutionAccountId/suffix only",
            )
        )
        for targets, expected_error in invalid_targets:
            write(
                root / "project.json",
                json.dumps({"projectName": "test", "targets": targets}) + "\n",
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
        "design": {"docs/designs/dev/cde/vpc.md", "model/dev/cde/vpc.properties"},
        "infrastructure": {
            "infra/cloudformation/templates/vpc.yaml",
            "docs/designs/dev/cde/vpc.md",
            "model/dev/cde/vpc.properties",
        },
    }.items():
        validator = MODULE.Validator(SCRIPT.parents[2])
        validator.task_type = task_type
        validator.changed_paths = changed | {"tasks/example.md"}
        validator.check_task_boundary(prompt)
        assert not validator.errors, (task_type, validator.errors)


def check_task_type_cases(root) -> None:
    valid = {
        "initialization": {"project.json"},
        "design": {"docs/designs/dev/cde/vpc.md", "model/dev/cde/vpc.properties"},
        "infrastructure": {"infra/cloudformation/templates/vpc.yaml"},
        "scenario-test": {
            "tests/scenarios/vpc/scenario.md",
            "tests/results/vpc/dev/123456789012/result.md",
        },
        "governance": {"README.md"},
        "catalog-maintenance": {
            "framework/materials/aws/EC2_VPC.properties",
            "framework/materials/catalog.sha256",
        },
        "migration": {"project.json"},
    }
    for task_type, changed in valid.items():
        validator = MODULE.Validator(root)
        validator.task_type = task_type
        validator.infrastructure_phase = (
            "implement" if task_type == "infrastructure" else ""
        )
        validator.changed_paths = changed | {"tasks/example.md"}
        validator.check_task_type_requirements()
        assert not validator.errors, (task_type, validator.errors)

    validator = MODULE.Validator(root)
    validator.task_type = "infrastructure"
    validator.infrastructure_phase = "deploy"
    validator.changed_paths = {"tasks/example.md"}
    validator.check_task_type_requirements()
    assert not validator.errors, validator.errors

    validator.changed_paths.add("infra/cloudformation/templates/vpc.yaml")
    validator.check_task_type_requirements()
    assert any(
        "infrastructure deploy phase must not change IaC" in error
        for error in validator.errors
    )

    validator = MODULE.Validator(root)
    validator.task_type = "infrastructure"
    validator.infrastructure_phase = "update"
    validator.changed_paths = {
        "docs/designs/dev/cde/vpc.md",
        "model/dev/cde/vpc.properties",
        "infra/cloudformation/templates/vpc.yaml",
        "tasks/example.md",
    }
    validator.check_task_type_requirements()
    assert not validator.errors, validator.errors

    validator = MODULE.Validator(root)
    validator.task_type = "design"
    validator.changed_paths = {
        "docs/designs/dev/cde/iam/role01-policy.json",
        "model/dev/cde/iam.properties",
        "tasks/example.md",
    }
    validator.check_task_type_requirements()
    assert not validator.errors, validator.errors

    # Generated equality is checked separately; views need not have a Git diff.
    for changed in (
        {"model/dev/cde/cloudwatch-logs.properties"},
        {"model/dev/cde/cloudwatch-logs/part-003.properties"},
        {
            "model/dev/cde/cloudwatch-logs.properties",
            "model/dev/cde/vpc.properties",
            "docs/designs/dev/cde/vpc.md",
        },
        {"docs/designs/dev/cde/vpc.md"},
        {"docs/designs/dev/cde/iam/role01-policy.json"},
        set(),
    ):
        validator = MODULE.Validator(root)
        validator.task_type = "design"
        validator.changed_paths = changed | {"tasks/example.md"}
        validator.check_task_type_requirements()
        assert bool(validator.errors) == (
            not any(
                path.startswith("model/") and path.endswith(".properties")
                for path in changed
            )
        ), validator.errors


def check_task_type_inputs() -> None:
    write_model = _imports_support_model_sources.write_model
    with (
        project() as root,
        patch.dict(os.environ, {"BLUEPRINT_TASK_FILE": "tasks/example.md"}),
    ):
        write(
            root / "project.json",
            __import__("json").dumps(
                {
                    "targets": [
                        {
                            "environment": "dev",
                            "alias": "cde",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        }
                    ]
                }
            )
            + "\n",
        )
        write(
            root / "tasks/example.md",
            "## Task contract\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n",
        )
        for service, kind, prop in (
            ("vpc", "EC2.VPC", "Name"),
            ("cloudwatch-logs", "Logs.LogGroup", "LogGroupName"),
        ):
            write_model(
                root / "model/dev/cde" / (service + ".properties"),
                {
                    "desired.resource.001.resourceType": kind,
                    "desired.resource.001.logicalId": kind.replace(".", "_") + "_001",
                    "desired.resource.001.anchor": "resource-"
                    + (kind.replace(".", "_") + "_001"),
                    "desired.service.identity.lastAllocated": __import__("json").dumps(
                        {kind: 1}
                    ),
                    "desired.row.001-001.property": kind + "." + prop,
                    "desired.row.001-001.value": "`fixture`",
                    "desired.row.001-001.comment": "Synthetic setting",
                },
            )
        check_task_type_cases(root)
