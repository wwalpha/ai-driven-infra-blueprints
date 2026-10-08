"""Deployment input selection and task file gating."""

from __future__ import annotations
import json
import io
import os
from pathlib import Path
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch
from test_support.validator import MODULE, project, git_project, commit, write


def check_deployment_iac_scope():
    from deploy_preparation import task_deployment_input_paths
    from model_design import markdown_for
    import task_contract as tasks
    import os
    with git_project() as root, patch.dict(os.environ, {}, clear=True):
        (root / "framework/rules").mkdir(parents=True)
        write(root / "framework/rules/aws-resource-naming.md",
            "| CloudFormation | Stack | `CloudFormation.Stack` | StackName | `.*` |\n")
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
                    assert not validator.errors, validator.errors
                    assert not validator.changed_paths  # Other running task owns the invalid bytes.
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
    print("Deployment IaC scope: PASS (A/B dev ignores other-task invalid stg; stg/full fail; shared template and own out-of-scope IaC fail)")


def check_task_file_gating() -> None:
    import task_contract as tasks
    import worktree_task as wt

    # Keep real task attribution, CF scans, Acceptance and run()/exit reporting.
    # Other catalog/design checks have independent regression fixtures.
    unrelated_checks = (
        "check_structure", "check_project_topology", "check_validation_scope", "check_model_files",
        "check_issue_gate", "check_initialized_paths", "check_catalog", "check_resource_layout",
        "check_scoped_designs", "check_designs", "check_observed_values", "check_iac_selection",
        "check_scenarios", "check_results", "check_scenario_changes",
    )
    own = "infra/cloudformation/templates/non-cde/snowflake.yaml"
    names = {"cde/secrets-manager.yaml": 60, "non-cde/codepipeline.yaml": 11,
             "non-cde/glue-inbound-18.yaml": 9, "non-cde/kms.yaml": 2}
    planned = "infra/cloudformation/templates/non-cde/kms.yaml"

    def contract(name, files):
        listed = "\n".join(f"- `{path}`" for path in [name, *files])
        return f"""# Task
## Task contract
- Task type: `infrastructure`
- Task status: `running`
- Infrastructure phase: `implement`
## Validation scope
- `dev/non-cde/snowflake`
## Required changes
- [R1] Change own template
## Acceptance checks
- [R1] `changed:{files[0]}`
## Modified files
{listed}
## Allowed paths
{listed}
"""

    with project() as primary, patch.dict(os.environ, {}, clear=True):
        wt.git(primary, "init", "-q", "-b", "main")
        wt.git(primary, "config", "user.name", "Fixture")
        wt.git(primary, "config", "user.email", "fixture@example.invalid")
        wt.git(primary, "config", "commit.gpgsign", "false")
        write(primary / ".gitignore", "tasks/**\n/.worktrees/\n")
        template = primary / own
        template.parent.mkdir(parents=True)
        write(template, "Resources: {}\n")
        for name, count in names.items():
            path = primary / "infra/cloudformation/templates" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            write(path, "Metadata:\n  Entries:\n" + "    - Fn::Sub: invalid\n" * count)
        wt.git(primary, "add", ".")
        wt.git(primary, "commit", "-qm", "baseline")
        state = wt.create(primary, "file-gate")
        root, selected = Path(state["worktree"]), state["task_file"]
        tasks.start(root, selected, contract(selected, [own, planned]))
        os.environ[tasks.SELECTOR] = selected

        def validate(*, all_files=False, wide_iac=False, no_changes=False):
            validator = MODULE.Validator(root, None if all_files else set(), repository_wide_gate=wide_iac)
            output = io.StringIO()
            with ExitStack() as stack, redirect_stdout(output):
                for name in unrelated_checks:
                    stack.enter_context(patch.object(validator, name))
                if no_changes:
                    original = validator.check_task_scope
                    def idle_scope():
                        original()
                        validator.changed_paths.clear()
                    stack.enter_context(patch.object(validator, "check_task_scope", idle_scope))
                result = validator.run()
            return validator, result, output.getvalue()

        # Case 1: existing 82 errors are still scanned, counted and printed.
        write(root / own, "Resources: {}\n# current task\n")
        clean, result, output = validate()
        assert result == 0 and not clean.errors and len(clean.non_blocking_findings) == 82, output
        assert "validation: PASS" in output and "Non-blocking findings: 82" in output
        assert all(name in output for name in names), output
        assert planned not in clean.file_gate_paths, "planned-but-unchanged file entered managed gate"

        # Case 2: only the own file's new finding blocks.
        write(root / own, "Metadata:\n  Fn::Sub: invalid\n")
        invalid, result, output = validate()
        assert result == 1 and len(invalid.errors) == 1 and len(invalid.non_blocking_findings) == 82, output
        assert own in invalid.errors[0] and "Blocking errors: 1" in output

        # Case 3: both explicit all and full/framework repository-wide IaC gate everything.
        for kwargs in ({"all_files": True}, {"wide_iac": True}):
            wide, result, output = validate(**kwargs)
            assert result == 1 and len(wide.errors) == 83 and not wide.non_blocking_findings, output
            assert wide.checks == invalid.checks, "file gating changed scan/check count"

        # Case 5: working diff disappears, but the pinned task diff/gate survives.
        wt.git(root, "add", own)
        wt.git(root, "commit", "-qm", "task fixture")
        assert not wt.paths(root, "diff", "--name-only", "-z")
        committed, result, output = validate()
        assert result == 1 and committed.file_gate_paths == invalid.file_gate_paths, output
        assert committed.changed_paths == invalid.changed_paths and len(committed.errors) == 1, output
        assert len(committed.non_blocking_findings) == 82
        write(root / own, "Resources: {}\n# committed valid\n")
        wt.git(root, "add", own)
        wt.git(root, "commit", "-qm", "valid task fixture")
        committed_valid, result, output = validate()
        assert result == 0 and own in committed_valid.file_gate_paths, output

        # Case 4: an actual required Acceptance input outside the changed files still blocks.
        text = (root / selected).read_text(encoding="utf-8")
        write(root / selected, text.replace(f"changed:{own}", "exists:missing-required-input"))
        for no_changes in (False, True):
            global_failure, result, output = validate(no_changes=no_changes)
            assert result == 1 and any("required path missing" in error for error in global_failure.errors), output
            assert len(global_failure.non_blocking_findings) == 82
        write(root / selected, text)

        # Case 6: another worktree and another same-checkout task supply no current-task changes.
        other = wt.create(primary, "other-gate")
        other_root = Path(other["worktree"])
        tasks.start(other_root, other["task_file"], contract(other["task_file"], [own]))
        write(other_root / own, "Metadata:\n  Fn::Sub: foreign\n")
        foreign = root / other["task_file"]
        foreign.write_bytes((other_root / other["task_file"]).read_bytes())
        sibling_path = "infra/cloudformation/templates/non-cde/codepipeline.yaml"
        sibling = "tasks/sibling.md"
        tasks.start(root, sibling, contract(sibling, [sibling_path]))
        with (root / sibling_path).open("a", encoding="utf-8") as stream:
            stream.write("# sibling task\n")
        isolated, result, output = validate()
        assert result == 0 and isolated.file_gate_paths == committed_valid.file_gate_paths, output
        assert sibling_path not in isolated.changed_paths and other["task_file"] not in isolated.changed_paths
        assert len(isolated.non_blocking_findings) == 82

        # Legacy/non-managed contracts keep acquired file authority even after committing.
        with patch.dict(os.environ, {tasks.SELECTOR: selected}):
            legacy = MODULE.Validator(root, set())
            with patch.object(wt, "committed_task_paths", return_value=None):
                legacy.check_task_scope()
            assert own in legacy.file_gate_paths and sibling_path not in legacy.file_gate_paths
            legacy.check_file(False, root / own, "committed own error")
            assert legacy.errors == ["committed own error"]

        # Environment/template and parameter JSON findings share the same gate abstraction.
        params = root / "infra/cloudformation/parameters/dev/non-cde/unrelated.json"
        params.parent.mkdir(parents=True)
        write(params, "invalid JSON")
        isolated.check_cloudformation_environment_parameters()
        assert any("invalid CloudFormation parameter JSON" in item for item in isolated.non_blocking_findings)
        isolated.file_gate_paths.add(params.relative_to(root).as_posix())
        isolated.check_cloudformation_environment_parameters()
        assert any("invalid CloudFormation parameter JSON" in item for item in isolated.errors)
        unresolved = MODULE.Validator(root, set())
        unresolved.check_file(False, root / own, "unresolved authority")
        assert unresolved.errors == ["unresolved authority"]
        # Process/rule integrity uses unchanged check(), even with an empty file gate.
        isolated.file_gate_paths.clear()
        isolated.check(False, "global process failure")
        assert "global process failure" in isolated.errors
    print("Task file gating: PASS (6 cases; unrelated CloudFormation errors detected: 82; blocking errors from those files: 0)")

