"""Deployment input selection and scope validation."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack as ExitStack
from unittest import TestCase
from unittest.mock import patch

import deploy.inputs as _imports_deploy_inputs
import model.render as _imports_model_render
import task_contract_core as _imports_task_contract
from support.it_case_receipt import it_case
from support.validator import MODULE, commit, git_project
from support.validator import project as project
from support.validator import write as write


@it_case
def check_deployment_iac_scope():
    tasks = _imports_task_contract
    task_deployment_input_paths = _imports_deploy_inputs.task_deployment_input_paths
    markdown_for = _imports_model_render.markdown_for
    with (
        git_project() as root,
        patch.dict(os.environ, {}, clear=True),
        patch("deploy.contracts.accepted_changes", return_value=set()),
    ):
        target = {
            "awsAccountId": "123456789012",
            "awsRegion": "ap-northeast-1",
            "alias": "shared",
            "iacEngine": "cloudformation",
        }
        write(
            root / "project.json",
            json.dumps(
                {
                    "projectName": "app",
                    "targets": [
                        {"environment": env, **target} for env in ("dev", "stg")
                    ],
                }
            )
            + "\n",
        )
        template = root / "infra/cloudformation/templates/shared/a.yaml"
        template.parent.mkdir(parents=True)
        write(template, "Resources: {}\n")
        parameters = {}
        for env, phase in (("dev", "deploy"), ("stg", "update")):
            model = root / f"model/{env}/shared/cloudformation-stacks.properties"
            design = root / f"docs/designs/{env}/shared/cloudformation-stacks.md"
            model.parent.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            values = {
                "desired.deployment.maxConcurrentStacks": "1",
                "desired.stack.001.name": "A",
                "desired.stack.001.template": "a.yaml",
                "desired.stack.001.parameters": "a.json",
                "desired.stack.001.deployOrder": "1",
                "display.stack.001.comment": "配置するstack",
            }
            write(
                model,
                "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
            )
            write(design, markdown_for(design, values, root))
            parameters[env] = (
                root / f"infra/cloudformation/parameters/{env}/shared/a.json"
            )
            parameters[env].parent.mkdir(parents=True)
            write(parameters[env], "[]\n")
            name = f"tasks/{env}.md"
            relative = parameters[env].relative_to(root).as_posix()
            text = f"""# Task
## Task contract
- Task type: `infrastructure`
- Task status: `running`
- Infrastructure phase: `{phase}`
- Target environment: `{env}`
- Target alias: `shared`
- Target AWS account: `123456789012`
- Deployment scope: `A`
## Validation scope
- `{env}/shared/cloudformation-stacks`
## Required changes
- [R1] 対象stackを検証する。
## Acceptance checks
- [R1] `exists:{relative}`
## Modified files
- `{name}`
- `{relative}`
## Allowed paths
- `{name}`
- `{relative}`
"""
            tasks.start(root, name, text)
        commit(root, ["."], "fixture")
        for env in ("dev", "stg"):
            with patch.dict(os.environ, {tasks.SELECTOR: f"tasks/{env}.md"}):
                paths = task_deployment_input_paths(root)
                assert paths == {template, parameters[env]}, paths
                validator = MODULE.Validator(
                    root,
                    {(env, "shared", "cloudformation-stacks")},
                    iac_paths=paths,
                    task_iac_paths=paths,
                    model_validation="change",
                )
                validator.check_task_scope()
                validator.accounts = {(env, "shared"): {"alias": "shared"}}
                validator.check_validation_scope()
                validator.check_cloudformation_yaml_rules()
                validator.check_cloudformation_environment_parameters()
                TestCase().assertFalse(validator.errors, validator.errors)
    print(
        "Deployment IaC scope: PASS (normal dev/stg input selection, shared template and validation)"
    )
