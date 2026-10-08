#!/usr/bin/env python3
"""Runnable checks for issue isolation, remediation and mutation guards."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock

from test_support.validator import load

from issue_gate import issue_errors, remediation_scope, require_no_issues, require_target_no_issues


def main():
    context, sync, validator, deploy = map(load, ("check-deploy-context", "sync-model", "validate-blueprint", "cloudformation-deploy"))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scope = {("dev", "cde", "ec2")}
        assert not issue_errors(root, scope)
        path = root / "issues/dev/cde/issues.md"
        path.parent.mkdir(parents=True)
        original = "# 問題一覧\n\n## dev／cde\n\n### Amazon EC2\n\n1. 不正な設定。根拠: [ec2.properties:1](../../../model/dev/cde/ec2.properties)。\n\n```text\n1. 診断のcode例\n### fake\n```\n"
        path.write_text(original)
        assert len(issue_errors(root, scope)) == 1
        assert not issue_errors(root, {("prod", "cde", "ec2")})
        assert not issue_errors(root, {("dev", "non-cde", "ec2")})
        assert not issue_errors(root, {("dev", "cde", "s3")})
        assert not issue_errors(root, set())
        assert issue_errors(root, None)
        path.write_text("### Amazon EC2\n<!-- issue-service: ec2 -->\n\n1. 設定不足\n\n2. 参照不足\n")
        assert len(issue_errors(root, scope)) == 2
        path.write_text("### ec2\n\n1. 設定不足。参照先: [s3](../../../docs/designs/dev/cde/s3.md)。\n")
        assert issue_errors(root, scope)
        assert not issue_errors(root, {("dev", "cde", "s3")})  # Explicit ownership wins over references.
        path.write_text("### Unknown service\n\n1. 設定不足\n")
        assert "ambiguous" in issue_errors(root, {("dev", "cde", "s3")})[0]
        assert issue_errors(root, scope, remediation=scope)  # Unknown ownership cannot be waived.
        path.write_text("設定不足\n")
        assert issue_errors(root, scope)
        path.write_text("# 問題一覧\n\n未解決issueなし\n")
        assert not issue_errors(root, scope)
        path.write_text("")
        assert not issue_errors(root, scope)
        (path.parent / "diff.md").write_text("### ec2\n\n1. 環境間の差分\n")
        assert not issue_errors(root, scope)  # Differences never enter the unresolved issue inventory.
        for contents in ("### ec2\n1. 差分\n", "invalid inventory; 999 differences", ""):
            (path.parent / "iac-issues.md").write_text(contents)
            assert not issue_errors(root, scope)
        path.write_text(original)
        assert issue_errors(root, scope)
        assert not issue_errors(root, {("dev", "cde", "s3")})

        active = root / "tasks/active.md"
        active.parent.mkdir()
        contract = "## Task contract\n\n- Task type: `design`\n\n## Validation scope\n\n- `dev/cde/ec2`\n"
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
        for name in ("issues.md", "iac-issues.md", "diff.md"):
            report = f"issues/dev/cde/{name}"
            investigation = contract.replace('Task type: `design`', 'Task type: `migration`') + (
                f"\n## Allowed paths\n\n- `tasks/active.md`\n- `{report}`\n")
            active.write_text(investigation)
            instance = validator.Validator(root)
            instance.task_type = "migration"
            instance.changed_paths = {"tasks/active.md", report}
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
        # State is neither a report output nor a save-only deletion target.
        legacy = "issues/dev/cde/iac-issues.state.json"
        active.write_text(investigation + f"- `{legacy}`\n")
        state = root / legacy
        state.write_text("{}")
        instance = validator.Validator(root)
        instance.task_type, instance.changed_paths = "migration", {legacy}
        instance.check_issue_gate()
        assert instance.errors  # Existing/created state cannot bypass the ordinary gate.
        state.unlink()
        instance = validator.Validator(root)
        instance.task_type, instance.changed_paths = "migration", {legacy}
        instance.check_issue_gate()
        assert instance.errors  # State deletion is outside the report-only exception.
        instance = validator.Validator(root)
        instance.task_type, instance.changed_paths = "migration", {"issues/dev/cde/iac-issues.md"}
        instance.check_issue_gate()
        assert instance.errors  # A nonexistent, unchanged state path is not an output authorization.
        active.write_text(investigation)
        try:
            sync.sync(root, True, "dev", "cde", services=["ec2"])
        except ValueError as error:
            assert "unresolved issue blocks task" in str(error)
        else:
            raise AssertionError("model save bypassed issues")
        assert not (root / "docs").exists()

        target = {"environment": "dev", "alias": "cde", "awsAccountId": "123456789012",
                  "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
        (root / "project.json").write_text(json.dumps({"targets": [target]}))
        backend = deploy.AwsBackend(root, "dev", "cde", target)
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
            for operation in ("create-change-set", "execute-change-set"):
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
        command = [sys.executable, str(Path(__file__).with_name("issue_gate.py")), "--repository-root", str(root),
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
