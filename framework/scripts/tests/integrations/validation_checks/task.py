"""Task contracts, dispatch, boundaries and project topology."""


from __future__ import annotations

import io
import os
from contextlib import ExitStack, redirect_stdout
from functools import partial as _bind_framework_callback
from unittest.mock import patch

import support.model_sources as _imports_support_model_sources
from support.it_case_receipt import it_case
from support.validator import MODULE, commit, git_project
from support.validator import project as project
from support.validator import write as write

_CALLBACK_DEFAULT = object()



@it_case
def check_task_contract() -> None:
    with git_project() as root:
        (root / "tasks").mkdir()
        governance = """# Test

## Task contract

- Task type: `governance`
- Task status: `running`
## Modified files
- `tasks/example.md`
- `README.md`

## Required changes

- [R1] READMEを更新する。

## Acceptance checks

- [R1] `changed:README.md`

## Allowed paths

- `README.md`
- `tasks/example.md`
"""
        write(root / "tasks" / "example.md", governance)
        write(root / "README.md", "changed\n")
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert not validator.errors
        assert validator.requirement_ids == ["R1"]

        active = root / "tasks" / "example.md"
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


@it_case
def check_idle_without_active_task() -> None:
    with git_project() as root:

        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert not validator.errors, validator.errors

        (root / "tasks").mkdir()
        write(root / "tasks" / "example.md", "## Task contract\n- Task type: `governance`\n- Task status: `completed`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n")
        commit(root, ["tasks/example.md"], "active-task")
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        validator.check_task_type_requirements()
        validator.check_acceptance_checks()
        assert not validator.errors, validator.errors
        assert not validator.task_type
        (root / "tasks" / "example.md").unlink()
        commit(root, ["tasks/example.md"], "remove-completed-task")
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert not validator.errors, validator.errors

        write(root / "README.md", "changed\n")
        validator = MODULE.Validator(root)
        validator.check_task_scope()
        assert any("selected task contract missing" in error for error in validator.errors)


def _callback_check_destroy_phase_check_150(banned, invoked, _default_name, /, *args, name=_CALLBACK_DEFAULT):
    if name is _CALLBACK_DEFAULT:
        name = _default_name
    assert name not in banned, name
    invoked.append(name)


@it_case
def check_destroy_phase() -> None:
    with git_project() as root:
        write(root / "project.json", __import__("json").dumps({"targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
        model = root / "model/dev/123456789012/ec2.properties"
        model.parent.mkdir(parents=True)
        write(model, 'desired.resource.001.resourceType=EC2.VPC\ndesired.resource.001.logicalId=EC2_VPC_001\ndesired.resource.001.anchor=resource-EC2_VPC_001\ndesired.service.identity.lastAllocated={"EC2.VPC":1}\ndesired.row.001-001.property=EC2.VPC.VpcId\ndesired.row.001-001.comment=Physical ID\ndesired.row.001-001.value=[EC2_VPC_001](ec2.md#resource-EC2_VPC_001)\nobserved.row.001-001.value=`vpc-old`\n')
        commit(root, ["."], "baseline")
        validator = MODULE.Validator(root)
        validator.task_type = "infrastructure"
        validator.infrastructure_phase = "destroy"
        validator.changed_paths = {"model/dev/123456789012/ec2.properties", "tasks/destroy.md"}
        write(model, 'desired.resource.001.resourceType=EC2.VPC\ndesired.resource.001.logicalId=EC2_VPC_001\ndesired.resource.001.anchor=resource-EC2_VPC_001\ndesired.service.identity.lastAllocated={"EC2.VPC":1}\ndesired.row.001-001.property=EC2.VPC.VpcId\ndesired.row.001-001.comment=Physical ID\ndesired.row.001-001.value=[EC2_VPC_001](ec2.md#resource-EC2_VPC_001)\nobserved.row.001-001.value=`PENDING_DEPLOY`\n')
        validator.check_task_type_requirements()
        assert any("versioned Model baseline" in error for error in validator.errors)
        validator.errors.clear()
        validator.task.fix_baseline()
        validator.check_task_type_requirements()
        validator.check_task_boundary(root / "tasks/destroy.md")
        assert not validator.errors, validator.errors
        write(model, 'desired.resource.001.resourceType=EC2.VPC\ndesired.resource.001.logicalId=EC2_VPC_001\ndesired.resource.001.anchor=resource-EC2_VPC_001\ndesired.service.identity.lastAllocated={"EC2.VPC":1}\ndesired.row.001-001.property=EC2.VPC.VpcId\ndesired.row.001-001.comment=Physical ID\ndesired.row.001-001.value=[EC2_VPC_002](ec2.md#resource-EC2_VPC_002)\nobserved.row.001-001.value=`PENDING_DEPLOY`\n')
        validator.changed_paths = {"model/dev/123456789012/ec2.properties"}
        validator.check_task_type_requirements()
        validator.check_task_boundary(root / "tasks/destroy.md")
        assert any("destroy permits only observation patches" in error for error in validator.errors)
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
        with ExitStack() as stack:
            for name in ("check_structure", "check_task_scope", "check_project_topology", "check_validation_scope",
                         "check_model_files", "check_issue_gate", "check_task_type_requirements", "check_initialized_paths",
                         "check_catalog", "check_resource_layout", "check_scoped_designs", "check_designs", "check_observed_values",
                         "check_acceptance_checks", *banned):
                check = _bind_framework_callback(_callback_check_destroy_phase_check_150, banned, invoked, name)
                stack.enter_context(patch.object(validator, name, check))
            with redirect_stdout(io.StringIO()):
                assert validator.run() == 0
        assert {"check_task_scope", "check_scoped_designs", "check_acceptance_checks"} <= set(invoked)


@it_case
def check_task_type_dispatch() -> None:
    write_model = _imports_support_model_sources.write_model
    with project() as root, patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/example.md'}):
        write(root/'project.json', __import__('json').dumps({'targets': [{'environment': 'dev', 'alias': 'cde', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n')
        write(root/'tasks/example.md', '## Task contract\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n')
        for service, kind, prop in (('vpc', 'EC2.VPC', 'Name'), ('cloudwatch-logs', 'Logs.LogGroup', 'LogGroupName')):
            write_model(root/'model/dev/cde'/(service+'.properties'), {
                'desired.resource.001.resourceType': kind,
                'desired.resource.001.logicalId': kind.replace('.', '_') + '_001', 'desired.resource.001.anchor': 'resource-' + (kind.replace('.', '_') + '_001'),
                'desired.service.identity.lastAllocated': __import__('json').dumps({kind: 1}),
                'desired.row.001-001.property': kind+'.'+prop,
                'desired.row.001-001.value': '`fixture`', 'desired.row.001-001.comment': 'Synthetic setting',
            })
        check_task_type_cases(root)


@it_case
def check_task_type_cases(root) -> None:
    valid = {
        "initialization": {"project.json"},
        "design": {"docs/designs/dev/cde/vpc.md", "model/dev/cde/vpc.properties"},
        "infrastructure": {"infra/cloudformation/templates/vpc.yaml"},
        "scenario-test": {"tests/scenarios/vpc/scenario.md", "tests/results/vpc/dev/123456789012/result.md"},
        "governance": {"README.md"},
        "catalog-maintenance": {"framework/materials/aws/EC2_VPC.properties", "framework/materials/catalog.sha256"},
        "migration": {"project.json"},
    }
    for task_type, changed in valid.items():
        validator = MODULE.Validator(root)
        validator.task_type = task_type
        validator.infrastructure_phase = "implement" if task_type == "infrastructure" else ""
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
    assert any("infrastructure deploy phase must not change IaC" in error for error in validator.errors)

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
        {"model/dev/cde/cloudwatch-logs.properties", "model/dev/cde/vpc.properties",
         "docs/designs/dev/cde/vpc.md"},
        {"docs/designs/dev/cde/vpc.md"},
        {"docs/designs/dev/cde/iam/role01-policy.json"},
        set(),
    ):
        validator = MODULE.Validator(root)
        validator.task_type = "design"
        validator.changed_paths = changed | {"tasks/example.md"}
        validator.check_task_type_requirements()
        assert bool(validator.errors) == (not any(path.startswith("model/") and path.endswith(".properties") for path in changed)), validator.errors
