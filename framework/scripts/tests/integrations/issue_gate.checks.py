#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.issue_gate_fixtures import (
    Path,
    json,
    load,
    mock,
    remediation_scope,
    require_no_issues,
    require_target_no_issues,
    subprocess,
    sys,
    tempfile,
)
from support.it_case_receipt import it_case

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@it_case
def main():
    context, sync, validator, deploy = map(load, ("check-deploy-context", "sync-model", "validate-blueprint", "cloudformation-deploy"))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scope = {("dev", "cde", "ec2")}
        path = root / "issues/dev/cde/issues.md"
        path.parent.mkdir(parents=True)
        original = "# 問題一覧\n\n## dev／cde\n\n### Amazon EC2\n\n1. 不正な設定。根拠: [ec2.properties:1](../../../model/dev/cde/ec2.properties)。\n\n```text\n1. 診断のcode例\n### fake\n```\n"
        path.write_text(original)

        active = root / "tasks/example.md"
        active.parent.mkdir()
        contract = "## Task contract\n\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n\n## Validation scope\n\n- `dev/cde/ec2`\n"
        active.write_text("legacy deployment contract without service Validation scope\n")
        path.unlink()
        require_target_no_issues(root, ("dev", "cde"))  # No inventory preserves existing preflight behavior.
        path.write_text(original)
        active.write_text(contract)
        instance = validator.Validator(root, scope=None)  # --all does not broaden the task's issue scope.
        instance.task_type = "design"
        instance.check_issue_gate()
        assert instance.errors
        active.write_text(contract.replace("dev/cde/ec2", "dev/cde/s3"))
        instance = validator.Validator(root)
        instance.task_type = "design"
        instance.check_issue_gate()
        assert not instance.errors
        active.write_text(contract)
        for name in ("issues.md", "iac-issues.md"):
            report = f"issues/dev/cde/{name}"
            investigation = contract.replace('Task type: `design`', 'Task type: `migration`').split('## Modified files')[0] + ('## Modified files\n- `tasks/example.md`\n' + f'- `{report}`\n## Validation scope\n- `dev/cde/ec2`\n' +
                f"\n## Allowed paths\n\n- `tasks/example.md`\n- `{report}`\n")
            active.write_text(investigation)
            instance = validator.Validator(root)
            instance.task_type = "migration"
            instance.changed_paths = {"tasks/example.md", report}
            instance.check_issue_gate()
            assert not instance.errors  # Report saving does not require issue remediation.
            path.write_text("### Unknown service\n\n1. 調査中\n")
            instance.check_issue_gate()
            assert not instance.errors  # Unknown ownership must not prevent recording the investigation.
            path.write_text(original)
            for task_type, allowed, changed in (
                ("design", investigation, report),
                ("infrastructure", investigation, report),
                ("migration", investigation, "model/dev/cde/ec2.properties"),
                ("migration", investigation + "- `infra/**`\n", report),
                ("migration", investigation, "infra/dev/cde/ec2.yaml"),
                ("migration", investigation, f"issues/prod/cde/{name}"),
                ("migration", investigation.replace("## Validation scope", "## Missing scope"), report),
                ("migration", investigation.replace("dev/cde/ec2", "all"), report),
                ("migration", investigation.replace(report, f"issues/prod/cde/{name}"), report),
            ):
                active.write_text(allowed)
                instance = validator.Validator(root)
                instance.task_type, instance.changed_paths = task_type, {changed}
                instance.check_issue_gate()
                assert instance.errors, (task_type, allowed, changed)
        active.write_text(investigation)
        try:
            sync.sync(root, True, "dev", "cde", services=["ec2"])
        except ValueError as error:
            assert "unresolved issue blocks task" in str(error)
        else:
            raise AssertionError("model save bypassed issues")

        target = {"environment": "dev", "alias": "cde", "awsAccountId": "123456789012",
                  "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
        (root / "project.json").write_text(json.dumps({"targets": [target]}))
        backend = deploy.create_runtime(root, "dev", "cde", target)
        with mock.patch.object(context.shutil, "which", return_value="/mock/aws"), mock.patch.object(
            context.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"Account":"123456789012"}', "")
        ) as run:
            try:
                context.check_deploy_context(root, "dev", alias="cde")
            except context.DeployContextError as error:
                assert "unresolved issue" in str(error)
            else:
                raise AssertionError("deploy preflight bypassed issues")
            run.assert_not_called()
            context.check_deploy_context(root, "dev", alias="cde", read_only=True)
            run.reset_mock()
            for operation in ("create_change_set", "execute_change_set"):
                try:
                    backend.aws(operation)
                except deploy.Blocked as error:
                    assert "unresolved issue" in str(error)
                else:
                    raise AssertionError("AWS mutation bypassed issues")
                run.assert_not_called()

        active.write_text(contract)

        active.write_text(contract + "\n## Issue remediation\n\n- `dev/cde/ec2`\n")
        require_no_issues(root, scope)
        command = [sys.executable, str((Path(__file__).resolve().parents[2] / 'issue_gate.py')), "--repository-root", str(root),
                   "--environment", "dev", "--target-directory", "cde", "--service", "ec2"]
        assert subprocess.run(command, capture_output=True).returncode == 1  # A new task cannot inherit a repair waiver.
        assert subprocess.run([*command, "--task"], capture_output=True).returncode == 0
        for invalid in ("- `dev/cde/s3`", "- `all`", "- `dev/cde/ec2`\n- `dev/cde/ec2`"):
            active.write_text(contract + "\n## Issue remediation\n\n" + invalid + "\n")
            try:
                remediation_scope(root)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid remediation scope accepted")
        active.write_text(contract.replace("dev/cde/ec2", "all") + "\n## Issue remediation\n\n- `dev/cde/ec2`\n")
        try:
            remediation_scope(root)
        except ValueError:
            pass
        else:
            raise AssertionError("all-scope remediation accepted")
        active.write_text(contract)
        path.write_text("未解決issueなし\n")
        require_no_issues(root, scope)
    print("issue_gate: PASS (scope isolation, remediation, save and AWS guards)")


if __name__ == "__main__":
    main()
