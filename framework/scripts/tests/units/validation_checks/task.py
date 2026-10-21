"""Task contracts, dispatch, boundaries and project topology."""


from __future__ import annotations


import json


import io


import os


from contextlib import ExitStack, redirect_stdout


from unittest.mock import patch


from support.validator import MODULE, SCRIPT, project, git_project, commit, write


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
            "infra/210987654321/terraform/sandbox",
        ):
            (root / path).mkdir(parents=True)

        validator = MODULE.Validator(root)
        validator.check_project_topology()
        validator.check_initialized_paths()
        assert not validator.errors, validator.errors
        assert validator.accounts[("dev", "cde")]["account"] == "123456789012"
        assert validator.accounts[("dev", "non-cde")]["account"] == "123456789012"
        assert validator.accounts[("sandbox", "210987654321")]["account"] == "210987654321"

        from model.importing.scope import restrict
        cross_environment = [*topology["targets"],
                             *[{**target, "environment": "stg"} for target in topology["targets"][:2]]]
        write(root / "project.json", json.dumps({**topology, "targets": cross_environment}) + "\n")
        validator = MODULE.Validator(root)
        validator.check_project_topology()
        assert not validator.errors, validator.errors
        with restrict(("dev", "cde", "vpc")):
            validator = MODULE.Validator(root)
            validator.check_project_topology()
            assert not validator.errors, validator.errors
            assert set(validator.accounts) == {("dev", "cde")}
        duplicates = [topology["targets"][0], {**topology["targets"][1], "alias": "cde"}]
        write(root / "project.json", json.dumps({**topology, "targets": duplicates}) + "\n")
        for identity in (None, ("dev", "cde", "vpc")):
            with restrict(identity):
                validator = MODULE.Validator(root)
                validator.check_project_topology()
                assert any("duplicate target directory" in error for error in validator.errors), validator.errors

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
            ([{**topology["targets"][0], "awsAccountId": "123"}, *topology["targets"][1:]],
             "invalid AWS account"),
            ([{**topology["targets"][2], "environment": "modules"}],
             "Terraform environment conflicts with shared modules directory"),
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
        "design": {"docs/designs/dev/cde/vpc.md", "model/dev/cde/vpc.properties"},
        "infrastructure": {
            "infra/cloudformation/templates/vpc.yaml",
            "docs/designs/dev/cde/vpc.md",
            "model/dev/cde/vpc.properties",
        },
    }.items():
        validator = MODULE.Validator(SCRIPT.parents[2])
        validator.task_type = task_type
        validator.changed_paths = changed | {"tasks/active.md"}
        validator.check_task_boundary(prompt)
        assert not validator.errors, (task_type, validator.errors)

