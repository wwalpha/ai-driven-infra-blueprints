#!/usr/bin/env python3
"""Focused check for complete diagnostics and assertion-safe execution."""

from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import os
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("blueprint-loop.py")
SPEC = importlib.util.spec_from_file_location("blueprint_loop", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def events(directory):
    return [json.loads(line) for line in (directory / "timing.jsonl").read_text(encoding="utf-8").splitlines()]


def check_running_and_interruption():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        script = root / "slow.py"
        script.write_text("import time\nprint('before wait', flush=True)\ntime.sleep(0.15)\n", encoding="utf-8")
        logs = root / "logs"
        logs.mkdir()
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, str(script)]
        with redirect_stdout(io.StringIO()) as output:
            assert MODULE.run_commands(root, [command], environment, logs, heartbeat_seconds=0.03) == 0
        history = events(logs)
        assert any(event["event"] == "heartbeat" for event in history)
        assert "RUNNING slow.py" in output.getvalue()
        assert "before wait" in (logs / "01-slow.py.log").read_text()
        assert history[-1]["status"] == "pass"
        assert history[-1]["duration_seconds"] >= 0.15
        running = next(event for event in history if event["event"] == "step_running")
        assert running["pid"] > 0

        with patch.object(MODULE.subprocess, "Popen") as popen, redirect_stdout(io.StringIO()):
            process = popen.return_value
            process.pid = 123
            process.returncode = -9
            process.wait.side_effect = [KeyboardInterrupt(), subprocess.TimeoutExpired(command, 5), -9]
            assert MODULE.run_commands(root, [command, command], environment, logs) == 130
            process.terminate.assert_called_once()
            process.kill.assert_called_once()
            assert popen.call_count == 1
        history = events(logs)
        assert history[-1]["status"] == "interrupted"
        assert history[-2]["status"] == "interrupted"
        with patch.object(MODULE.subprocess, "Popen", side_effect=KeyboardInterrupt()), redirect_stdout(io.StringIO()):
            assert MODULE.run_commands(root, [command], environment, logs) == 130
        assert events(logs)[-1]["status"] == "interrupted"

        real_popen = MODULE.subprocess.Popen
        calls = 0

        def fail_first_start(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("cannot start")
            return real_popen(*args, **kwargs)

        with patch.object(MODULE.subprocess, "Popen", side_effect=fail_first_start), redirect_stdout(io.StringIO()):
            assert MODULE.run_commands(root, [command, command], environment, logs) == 1
        ended = [event for event in events(logs) if event["event"] == "step_end"]
        assert [event["status"] for event in ended] == ["error", "pass"]
        assert ended[0]["error"] == "cannot start"
        assert events(logs)[-1]["status"] == "fail"


def check_task_service_validation():
    """Use the real validator/generator, with no framework changes in the fixture."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "repository"
        shutil.copytree(SCRIPT.parents[2], root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        scripts = root / "framework/scripts"
        (root / "project.json").write_text(json.dumps({"projectName": "app", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1",
            "iacEngine": "cloudformation"}]}) + "\n")
        (root / "infra/cloudformation/parameters/dev/123456789012").mkdir(parents=True)
        model = root / "model/dev/123456789012/logs.properties"
        model.parent.mkdir(parents=True)
        original = """desired.service.logs.serviceId=logs
desired.service.logs.ownedCatalogResourceTypes=Logs.LogGroup
desired.resource.001.resourceType=Logs.LogGroup
desired.resource.001.logicalId=FlowLogs
desired.resource.001.anchor=logs-cwlogs-app-dev-flow
desired.row.001-001.property=Logs.LogGroup.LogGroupName
desired.row.001-001.value=cwlogs-app-dev-flow
desired.row.001-001.comment=ログを保存する名前
desired.row.001-002.property=Logs.LogGroup.RetentionInDays
desired.row.001-002.value=30
desired.row.001-002.comment=ログを保持する日数
display.service.title=# CloudWatch Logs 詳細設計
display.resource.001.comment=通信ログを保存するLog Group
"""
        model.write_text(original)
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONOPTIMIZE": "0"}
        result = subprocess.run([sys.executable, str(scripts / "sync-model.py"), "--write", "--all"],
                                cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-qm", "fixture"], cwd=root, check=True)
        active = root / "tasks/active.md"
        active.write_text("""# Design fixture
## Task contract
- Task type: `design`
## Validation scope
- `all`
## Required changes
- [R1] ログの保持期間を変更する。
## Acceptance checks
- [R1] `changed:model/dev/123456789012/logs.properties`
- [R1] `changed:docs/designs/dev/123456789012/logs.md`
## Allowed paths
- `tasks/active.md`
- `model/**`
- `docs/designs/**`
""")
        design = root / "docs/designs/dev/123456789012/logs.md"
        model.write_text(original.replace("value=30", "value=14"))
        subprocess.run([sys.executable, str(scripts / "sync-model.py"), "--write", "--all"],
                       cwd=root, env=environment, check=True, capture_output=True)
        good_model, good_design = model.read_text(), design.read_text()
        command = [sys.executable, str(scripts / SCRIPT.name), "--mode", "task", "--log-dir", str(Path(temporary) / "logs")]

        def run():
            result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
            assert "START validate-blueprint.py" in result.stdout
            assert "validation scope: all" in result.stdout or result.returncode != 0
            assert "START git-diff-check" in result.stdout
            assert "framework regression: skipped" in result.stdout
            assert "START blueprint-loop.checks.py" not in result.stdout
            return result

        result = run()
        assert result.returncode == 0 and "PASS (0 framework regression scripts)" in result.stdout, result.stdout + result.stderr
        for label, model_text, design_text, diagnostic in (
            ("model/view mismatch", good_model.replace("value=14", "value=7"), good_design, "generated Markdown is stale"),
            ("missing name", good_model.replace("value=cwlogs-app-dev-flow", "value=``"), good_design, "confirmed resource display label is missing"),
            ("schema violation", good_model.replace("value=14", "value=31"), good_design.replace("14", "31"), "schema"),
            ("broken reference", good_model, good_design.replace("14", "[missing](missing.md#missing)"), "broken design link"),
        ):
            model.write_text(model_text)
            design.write_text(design_text)
            result = run()
            assert result.returncode != 0 and diagnostic in result.stdout, (label, result.stdout, result.stderr)
        model.write_text(good_model)
        design.write_text(good_design)
        # Scope=all must not couple whole-repository validation to regression.
        # A second, untouched service is still validated by the task mode.
        contract = active.read_text()
        active.write_text(contract.replace("- `all`", "- `dev/999999999999/logs`"))
        result = run()
        assert result.returncode != 0 and "validation target is not defined" in result.stdout, result.stdout
        active.write_text(contract.replace("- `all`", "- `dev/123456789012/ec2`"))
        result = run()
        assert result.returncode != 0 and "changed design path is outside validation scope" in result.stdout, result.stdout
        active.write_text(contract)
        active.write_text(active.read_text().replace("- `all`", "- `dev/123456789012/logs`"))
        (design.parent / "ec2.md").write_text("invalid unrelated service\n")
        (model.parent / "ec2.properties").write_text("invalid unrelated service\n")
        subprocess.run(["git", "add", "docs/designs/dev/123456789012/ec2.md", "model/dev/123456789012/ec2.properties"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "unrelated service"], cwd=root, check=True)
        result = run()
        assert result.returncode != 0 and "ec2" in result.stdout, result.stdout
    print("task-service-validation: PASS (valid design, mismatch, name, schema, reference, contract scope, whole repository)")


def main() -> None:
    check_running_and_interruption()
    check_task_service_validation()
    for check in SCRIPT.parent.glob("*.checks.py"):
        optimized = subprocess.run(
            [sys.executable, "-O", str(check)], capture_output=True, text=True
        )
        assert optimized.returncode != 0 and "Focused checks require assertions" in optimized.stderr, check
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repository"
        log_parent = Path(directory) / "logs"
        scripts = root / "framework" / "scripts"
        scripts.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
        shutil.copyfile(SCRIPT.with_name("validation_scope.py"), scripts / "validation_scope.py")
        (scripts / "validate-blueprint.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
        (scripts / "a.checks.py").write_text("assert False, 'assertions must run'\n", encoding="utf-8")
        (scripts / "b.checks.py").write_text(
            "from pathlib import Path\nPath('continued').write_text('yes', encoding='utf-8')\n",
            encoding="utf-8",
        )
        command = [sys.executable, "-O", str(scripts / SCRIPT.name), "--mode", "local", "--all", "--log-dir", str(log_parent)]
        environment = {**os.environ, "PYTHONOPTIMIZE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode != 0
        assert "AssertionError: assertions must run" in result.stdout
        assert "validate-blueprint.py, a.checks.py" in result.stdout
        assert (root / "continued").read_text(encoding="utf-8") == "yes"
        failed_directory = next(log_parent.glob("blueprint-loop-*"))
        history = events(failed_directory)
        assert history[0]["event"] == "loop_start" and history[0]["step_count"] == 5
        ended = [event for event in history if event["event"] == "step_end"]
        assert [event["returncode"] for event in ended] == [1, 1, 0, 0, 0]
        assert all(event["duration_seconds"] >= 0 for event in ended)
        assert history[-1]["event"] == "loop_end" and history[-1]["status"] == "fail"
        assert history[-1]["failed_steps"] == ["validate-blueprint.py", "a.checks.py"]
        assert all("timestamp" in event for event in history)
        assert "AssertionError" in (failed_directory / "02-a.checks.py.log").read_text()

        (scripts / "validate-blueprint.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        (scripts / "a.checks.py").write_text("assert True\n", encoding="utf-8")
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS (2 framework regression scripts)" in result.stdout
        directories = set(log_parent.glob("blueprint-loop-*"))
        assert len(directories) == 2, "each run must retain its own logs"
        assert events((directories - {failed_directory}).pop())[-1]["status"] == "pass"
        assert events(failed_directory)[-1]["status"] == "fail", "previous logs must not be overwritten"
        rejected = subprocess.run([*command[:-1], str(root / 'logs')], capture_output=True, text=True)
        assert rejected.returncode != 0 and "outside the repository" in rejected.stderr
        assert not (root / "logs").exists()

        # A normal design edit skips regression; any shared framework change selects all checks.
        (root / "tasks").mkdir()
        active = root / "tasks/active.md"
        active.write_text("## Validation scope\n- `dev/cde/ec2`\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], cwd=root, check=True)
        (root / "continued").unlink()
        model = root / "model/dev/cde/ec2.properties"
        model.parent.mkdir(parents=True)
        model.write_text("design change\n")
        scoped_command = [argument for argument in command if argument != "--all"]
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0 and "PASS (0 framework regression scripts)" in result.stdout, result.stdout + result.stderr
        assert not (root / "continued").exists(), "unrelated check ran for a design edit"
        full_command = scoped_command.copy()
        full_command[full_command.index("local")] = "full"
        result = subprocess.run(full_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0 and "PASS (2 framework regression scripts)" in result.stdout, result.stdout
        (root / "continued").unlink()
        for path in ("framework/scripts/a.py", "framework/rules/rule.md", "framework/materials/input.json",
                     "framework/schema/schema.json", "framework/catalog/catalog.json", "framework/prompts/prompt.md",
                     ".agents/skills/example/SKILL.md", "AGENTS.md", "README.md"):
            assert MODULE.framework_changed({path}), path
        assert not MODULE.framework_changed({"model/dev/cde/ec2.properties", "docs/designs/dev/cde/ec2.md", "tasks/active.md"})
        scoped_command[scoped_command.index("local")] = "task"
        (scripts / "a.py").write_text("# validator change\n")
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0 and "PASS (2 framework regression scripts)" in result.stdout
        assert (root / "continued").exists(), "shared change must run all regression"
        (scripts / "a.py").unlink()
        (root / "continued").unlink()
        rule = root / "framework/rules/rule.md"
        rule.parent.mkdir()
        rule.write_text("# staged rule change\n")
        subprocess.run(["git", "add", str(rule)], cwd=root, check=True)
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0 and "PASS (2 framework regression scripts)" in result.stdout, result.stdout
        assert "framework/rules/rule.md" in MODULE.changed_paths(root)
        # A move out of framework must still detect its old path, as must deletion.
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "rule"], cwd=root, check=True)
        rule.rename(root / "moved-rule.md")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        assert "framework/rules/rule.md" in MODULE.changed_paths(root)
        assert MODULE.framework_changed(MODULE.changed_paths(root))
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "failure")):
            try:
                MODULE.changed_paths(root)
            except ValueError:
                pass
            else:
                raise AssertionError("Git failure skipped framework detection")
        model.write_text(model.read_text() + "trailing whitespace  \n")
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode != 0 and "FAIL git-diff-check" in result.stdout, result.stdout
        subprocess.run(["git", "add", str(model)], cwd=root, check=True)
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode != 0 and "FAIL git-diff-check" in result.stdout, result.stdout
        active.write_text("# missing scope\n")
        before = set(log_parent.glob("blueprint-loop-*"))
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode and "validation scope missing" in result.stderr
        assert set(log_parent.glob("blueprint-loop-*")) == before, "missing scope started validation"
    print("blueprint-loop: PASS")


if __name__ == "__main__":
    main()
