"""Deployment input selection and scope validation."""


from __future__ import annotations

from support.it_case_receipt import it_case


import json
import shutil


import io


import os


from pathlib import Path


from contextlib import ExitStack, redirect_stdout


from unittest.mock import patch


from support.validator import MODULE, SCRIPT, project, git_project, commit, write


@it_case
def check_deployment_iac_scope():
    from deploy_preparation import task_deployment_input_paths
    from model.render import markdown_for
    import task_contract as tasks
    import os
    with git_project() as root, patch.dict(os.environ, {}, clear=True):
        target = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "alias": "shared", "iacEngine": "cloudformation"}
        write(root / "project.json", json.dumps({"projectName": "app", "targets": [
            {"environment": env, **target} for env in ("dev", "stg")]}) + "\n")
        template = root / "infra/cloudformation/templates/shared/a.yaml"
        template.parent.mkdir(parents=True)
        write(template, "Resources: {}\n")
        parameters = {}
        for env, phase in (("dev", "deploy"), ("stg", "update")):
            model = root / f"model/{env}/shared/cloudformation-stacks.properties"
            design = root / f"docs/designs/{env}/shared/cloudformation-stacks.md"
            model.parent.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            values = {"desired.deployment.maxConcurrentStacks": "1", "desired.stack.001.name": "A",
                      "desired.stack.001.template": "a.yaml", "desired.stack.001.parameters": "a.json",
                      "desired.stack.001.deployOrder": "1", "display.stack.001.comment": "配置するstack"}
            write(model, "\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
            write(design, markdown_for(design, values, root))
            parameters[env] = root / f"infra/cloudformation/parameters/{env}/shared/a.json"
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
        write(parameters["stg"], "invalid JSON\n")
        for env in ("dev", "stg"):
            with patch.dict(os.environ, {tasks.SELECTOR: f"tasks/{env}.md"}):
                paths = task_deployment_input_paths(root)
                assert paths == {template, parameters[env]}, paths
                validator = MODULE.Validator(root, {(env, "shared", "cloudformation-stacks")}, iac_paths=paths, task_iac_paths=paths)
                validator.check_task_scope()
                validator.accounts = {(env, "shared"): {"alias": "shared"}}
                validator.check_validation_scope()
                validator.check_cloudformation_yaml_rules()
                validator.check_cloudformation_environment_parameters()
                if env == "dev":
                    assert any("outside Deployment scope" in error for error in validator.errors), validator.errors
                    assert validator.changed_paths == {parameters["stg"].relative_to(root).as_posix()}
                else:
                    assert any("invalid CloudFormation parameter JSON" in error for error in validator.errors), validator.errors
        # The current task cannot hide its own out-of-deployment IaC behind the content filter.
        with patch.dict(os.environ, {tasks.SELECTOR: "tasks/dev.md"}):
            paths = task_deployment_input_paths(root)
            validator = MODULE.Validator(root, set(), iac_paths=paths, task_iac_paths=paths)
            validator.changed_paths = {parameters["stg"].relative_to(root).as_posix()}
            validator.check_validation_scope()
            assert any("outside Deployment scope" in error for error in validator.errors)
            write(template, "Resources:\n  Item: &InvalidAnchor {}\n")
            validator = MODULE.Validator(root, iac_paths=paths)
            validator.check_cloudformation_yaml_rules()
            assert any("anchor/alias/merge" in error for error in validator.errors)
        validator = MODULE.Validator(root)
        validator.check_cloudformation_environment_parameters()
        assert any("invalid CloudFormation parameter JSON" in error for error in validator.errors)
    print("Deployment IaC scope: PASS (A/B dev detects out-of-scope stg changes; stg/full fail; shared template and own out-of-scope IaC fail)")
