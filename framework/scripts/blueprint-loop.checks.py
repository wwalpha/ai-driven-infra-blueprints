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
        assert "before wait" in (logs / "01-slow.py.log").read_text(encoding="utf-8")
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


def make_framework_fixture(source, root):
    # Copy framework inputs only; never inherit consumer issues, models or tasks.
    shutil.copytree(source / "framework", root / "framework",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("AGENTS.md", "README.md"):
        shutil.copyfile(source / name, root / name)
    for name in ("tasks", "docs/designs", "model", "infra", "tests/scenarios", "tests/results"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "docs/system-overview.md").write_text("# Fixture\n", encoding="utf-8")


def check_task_service_validation():
    """Use the real validator/generator, with no framework changes in the fixture."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "repository"
        make_framework_fixture(SCRIPT.parents[2], root)
        scripts = root / "framework/scripts"
        (root / "project.json").write_text(json.dumps({"projectName": "app", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1",
            "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
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
        model.write_text(original, encoding="utf-8")
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONOPTIMIZE": "0"}
        result = subprocess.run([sys.executable, str(scripts / "sync-model.py"), "--write", "--all"],
                                cwd=root, env=environment, capture_output=True, encoding="utf-8")
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
- `dev/123456789012/logs`
## Required changes
- [R1] ログの保持期間を変更する。
## Acceptance checks
- [R1] `changed:model/dev/123456789012/logs.properties`
- [R1] `changed:docs/designs/dev/123456789012/logs.md`
## Allowed paths
- `tasks/active.md`
- `model/**`
- `docs/designs/**`
""", encoding="utf-8")
        design = root / "docs/designs/dev/123456789012/logs.md"
        model.write_text(original.replace("value=30", "value=14"), encoding="utf-8")
        subprocess.run([sys.executable, str(scripts / "sync-model.py"), "--write", "--all"],
                       cwd=root, env=environment, check=True, capture_output=True)
        good_model, good_design = model.read_text(encoding="utf-8"), design.read_text(encoding="utf-8")
        command = [sys.executable, str(scripts / SCRIPT.name), "--mode", "task", "--log-dir", str(Path(temporary) / "logs")]

        def run():
            result = subprocess.run(command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
            assert "START validate-blueprint.py" in result.stdout
            assert "validation scope: dev/123456789012/logs" in result.stdout or result.returncode != 0
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
            model.write_text(model_text, encoding="utf-8")
            design.write_text(design_text, encoding="utf-8")
            result = run()
            assert result.returncode != 0 and diagnostic in result.stdout, (label, result.stdout, result.stderr)
        model.write_text(good_model, encoding="utf-8")
        design.write_text(good_design, encoding="utf-8")
        # Contract scope remains enforced before design validation.
        contract = active.read_text(encoding="utf-8")
        active.write_text(contract.replace("- `dev/123456789012/logs`", "- `dev/999999999999/logs`"), encoding="utf-8")
        result = run()
        assert result.returncode != 0 and "validation target is not defined" in result.stdout, result.stdout
        active.write_text(contract.replace("- `dev/123456789012/logs`", "- `dev/123456789012/ec2`"), encoding="utf-8")
        result = run()
        assert result.returncode != 0 and "changed design path is outside validation scope" in result.stdout, result.stdout
        active.write_text(contract, encoding="utf-8")
        (design.parent / "ec2.md").write_text("invalid unrelated service\n", encoding="utf-8")
        (model.parent / "ec2.properties").write_text("invalid unrelated service\n", encoding="utf-8")
        subprocess.run(["git", "add", "docs/designs/dev/123456789012/ec2.md", "model/dev/123456789012/ec2.properties"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "unrelated service"], cwd=root, check=True)
        result = run()
        assert result.returncode == 0, result.stdout + result.stderr
        # The selected service still fails even with invalid unrelated input present.
        model.write_text(good_model.replace("value=14", "value=7"), encoding="utf-8")
        result = run()
        assert result.returncode != 0 and "generated Markdown is stale" in result.stdout, result.stdout
        model.write_text(good_model, encoding="utf-8")
        active.write_text(contract.replace("- `dev/123456789012/logs`", "- `all`"), encoding="utf-8")
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode != 0 and "ec2" in result.stdout, result.stdout
        assert "Validation: all" in result.stdout and "framework regression: skipped" in result.stdout
    print("task-service-validation: PASS (scoped design, excluded error, mismatch, name, schema, reference, contract scope, explicit all)")


def check_parallel_and_selection():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        scripts = root / "framework/scripts"
        scripts.mkdir(parents=True)
        logs = root / "logs"
        logs.mkdir()
        commands = []
        for name, other, code in (("a", "b", 1), ("b", "a", 0)):
            script = scripts / f"{name}.checks.py"
            script.write_text(
                "from pathlib import Path\nimport time\n"
                f"Path('{name}').touch()\nend=time.monotonic()+5\n"
                f"while not Path('{other}').exists() and time.monotonic()<end: time.sleep(.01)\n"
                f"assert Path('{other}').exists(), 'workers did not overlap'\n"
                f"print('diagnostic-{name}')\nraise SystemExit({code})\n", encoding="utf-8")
            commands.append([sys.executable, str(script)])
        with redirect_stdout(io.StringIO()) as output:
            assert MODULE.run_commands(root, commands, MODULE.utf8_environment(), logs, jobs=2) == 1
        assert output.getvalue().index("diagnostic-a") < output.getvalue().index("diagnostic-b")
        parallel = events(logs)[-1]["failed_steps"]
        with redirect_stdout(io.StringIO()):
            assert MODULE.run_commands(root, commands, MODULE.utf8_environment(), logs, jobs=1) == 1
        assert parallel == events(logs)[-1]["failed_steps"] == ["a.checks.py"]
        # Both children must be terminated even if the first wait is interrupted.
        with patch.object(MODULE.subprocess, "Popen") as popen, redirect_stdout(io.StringIO()):
            from unittest.mock import Mock
            first, second = Mock(pid=1, returncode=-9), Mock(pid=2, returncode=-9)
            first.wait.side_effect = [KeyboardInterrupt(), subprocess.TimeoutExpired([], 5), -9]
            second.wait.return_value = -9
            popen.side_effect = [first, second]
            assert MODULE.run_commands(root, commands, MODULE.utf8_environment(), logs, jobs=2) == 130
            first.terminate.assert_called_once()
            second.terminate.assert_called_once()
            first.kill.assert_called_once()
        paths = {"framework/scripts/a.checks.py"}
        selected, reason = MODULE.select_checks(root, paths, True)
        assert [path.name for path in selected] == ["a.checks.py"]
        for unknown in ("framework/scripts/shared.py", "framework/rules/rule.md",
                        "framework/scripts/deleted.checks.py", "framework/materials/catalog.sha256"):
            selected, reason = MODULE.select_checks(root, paths | {unknown}, True)
            assert len(selected) == 2 and "unknown dependency" in reason
        assert len(MODULE.select_checks(root, paths, False)[0]) == 2
        assert not MODULE.select_checks(root, {"model/dev/cde/ec2.properties"}, True)[0]
        MODULE.utf8_preflight(logs, MODULE.utf8_environment())
        assert not (logs / "utf8.txt").exists()


def check_fixture_independence():
    with tempfile.TemporaryDirectory() as temporary:
        source, target = Path(temporary) / "source", Path(temporary) / "target"
        (source / "framework").mkdir(parents=True)
        for name in ("AGENTS.md", "README.md"):
            (source / name).write_text("framework input", encoding="utf-8")
        for name in ("issues/dev/other/issues.md", "model/dev/other/ec2.properties",
                     "docs/designs/dev/other/ec2.md", "tasks/active.md", "project.json"):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("invalid consumer input", encoding="utf-8")
        make_framework_fixture(source, target)
        assert not (target / "issues").exists()
        assert not list((target / "model").rglob("*.properties"))
        assert not (target / "project.json").exists()
        assert not (target / "tasks/active.md").exists()


def check_staged_snapshot():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "source"
        scripts = root / "framework/scripts"
        scripts.mkdir(parents=True)
        for name in (SCRIPT.name, "validation_scope.py"):
            shutil.copyfile(SCRIPT.with_name(name), scripts / name)
        (root / "tasks").mkdir()
        active = root / "tasks/active.md"
        contract = "- Task type: `governance`\n## Validation scope\n- `framework`\n"
        active.write_text(contract, encoding="utf-8")
        validator = scripts / "validate-blueprint.py"
        validator.write_text("print('base')\n", encoding="utf-8")
        MODULE.git(root, "init", "-q")
        MODULE.git(root, "add", ".")
        MODULE.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base")
        (root / "historical.txt").write_text("old version", encoding="utf-8")
        MODULE.git(root, "add", ".")
        MODULE.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "history")
        base = MODULE.git(root, "rev-parse", "HEAD")
        validator.write_text(
            "from pathlib import Path\nimport subprocess\n"
            f"assert Path('tasks/active.md').read_text(encoding='utf-8') == {contract!r}\n"
            "assert not Path('untracked.txt').exists()\n"
            "assert subprocess.check_output(['git','rev-list','--count','HEAD'], text=True).strip() == '1'\n"
            "paths=subprocess.check_output(['git','diff','--cached','--name-only'], text=True)\n"
            "assert 'validate-blueprint.py' in paths\nprint('日本語 snapshot')\n", encoding="utf-8")
        MODULE.git(root, "add", ".")
        active.write_text("dirty workspace contract", encoding="utf-8")
        (root / "untracked.txt").write_text("not staged", encoding="utf-8")
        log_parent = Path(temporary) / "logs"
        command = [sys.executable, str(scripts / SCRIPT.name), "--mode", "task", "--staged", "--base", base,
                   "--log-dir", str(log_parent)]
        environment = {**MODULE.utf8_environment(), "PYTHONUTF8": "0", "PYTHONIOENCODING": "ascii"}
        index = Path(MODULE.git(root, "rev-parse", "--git-path", "index"))
        if not index.is_absolute():
            index = root / index
        saved_index = index.read_bytes()
        result = subprocess.run(command, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode == 0 and "日本語 snapshot" in result.stdout, result.stdout + result.stderr
        assert index.read_bytes() == saved_index
        assert active.read_text(encoding="utf-8") == "dirty workspace contract"
        metadata = json.loads(next(log_parent.glob("*/snapshot.json")).read_text(encoding="utf-8"))
        assert metadata["base"] == base and metadata["source_unchanged"]
        # A concurrent index edit cannot be reported as current validation success.
        validator.write_text(validator.read_text(encoding="utf-8") +
            f"subprocess.run(['git','add','tasks/active.md'], cwd={str(root)!r}, check=True)\n", encoding="utf-8")
        MODULE.git(root, "add", "framework/scripts/validate-blueprint.py")
        result = subprocess.run(command, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode == 1 and "snapshot is stale" in result.stdout, result.stdout + result.stderr
        rejected = subprocess.run([*command, "--affected", "--all"], capture_output=True, encoding="utf-8")
        assert rejected.returncode and "cannot narrow" in rejected.stderr
        # write-tree must reject unresolved conflicts before any validation starts.
        blob = MODULE.git(root, "rev-parse", "HEAD:tasks/active.md")
        conflict = "0 " + "0" * len(blob) + "\ttasks/active.md\n"
        conflict += "".join(f"100644 {blob} {stage}\ttasks/active.md\n" for stage in (1, 2, 3))
        subprocess.run(["git", "update-index", "--index-info"], cwd=root,
                       input=conflict, encoding="utf-8", check=True)
        result = subprocess.run(command, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode != 0 and "START validate-blueprint.py" not in result.stdout


def main() -> None:
    check_parallel_and_selection()
    check_fixture_independence()
    check_staged_snapshot()
    check_running_and_interruption()
    check_task_service_validation()
    for check in SCRIPT.parent.glob("*.checks.py"):
        optimized = subprocess.run(
            [sys.executable, "-O", str(check)], capture_output=True, encoding="utf-8"
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
        command = [sys.executable, "-O", str(scripts / SCRIPT.name), "--mode", "local", "--all", "--jobs", "1", "--log-dir", str(log_parent)]
        environment = {**os.environ, "PYTHONOPTIMIZE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
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
        assert "AssertionError" in (failed_directory / "02-a.checks.py.log").read_text(encoding="utf-8")

        (scripts / "validate-blueprint.py").write_text("import sys\nassert '--all' in sys.argv\n", encoding="utf-8")
        (scripts / "a.checks.py").write_text("assert True\n", encoding="utf-8")
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS (2 framework regression scripts)" in result.stdout
        directories = set(log_parent.glob("blueprint-loop-*"))
        assert len(directories) == 2, "each run must retain its own logs"
        assert events((directories - {failed_directory}).pop())[-1]["status"] == "pass"
        assert events(failed_directory)[-1]["status"] == "fail", "previous logs must not be overwritten"
        rejected = subprocess.run([*command[:-1], str(root / 'logs')], capture_output=True, encoding="utf-8")
        assert rejected.returncode != 0 and "outside the repository" in rejected.stderr
        assert not (root / "logs").exists()

        (scripts / "validate-blueprint.py").write_text("import sys\nassert '--all' not in sys.argv\n", encoding="utf-8")
        # A normal design edit skips regression; any shared framework change selects all checks.
        (root / "tasks").mkdir()
        active = root / "tasks/active.md"
        active.write_text("## Validation scope\n- `dev/cde/ec2`\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], cwd=root, check=True)
        (root / "continued").unlink()
        model = root / "model/dev/cde/ec2.properties"
        model.parent.mkdir(parents=True)
        model.write_text("design change\n", encoding="utf-8")
        scoped_command = [argument for argument in command if argument != "--all"]
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode == 0 and "PASS (0 framework regression scripts)" in result.stdout, result.stdout + result.stderr
        assert not (root / "continued").exists(), "unrelated check ran for a design edit"
        task_command = scoped_command.copy()
        task_command[task_command.index("local")] = "task"
        result = subprocess.run(task_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode == 0 and "Validation: active scope" in result.stdout, result.stdout
        full_command = scoped_command.copy()
        full_command[full_command.index("local")] = "full"
        result = subprocess.run(full_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode == 0 and "PASS (2 framework regression scripts)" in result.stdout, result.stdout
        (root / "continued").unlink()
        for path in ("framework/scripts/a.py", "framework/rules/rule.md", "framework/materials/input.json",
                     "framework/schema/schema.json", "framework/catalog/catalog.json", "framework/prompts/prompt.md",
                     ".agents/skills/example/SKILL.md", "AGENTS.md", "README.md"):
            assert MODULE.framework_changed({path}), path
        assert not MODULE.framework_changed({"model/dev/cde/ec2.properties", "docs/designs/dev/cde/ec2.md", "tasks/active.md"})
        scoped_command[scoped_command.index("local")] = "task"
        (scripts / "a.py").write_text("# validator change\n", encoding="utf-8")
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode == 0 and "PASS (2 framework regression scripts)" in result.stdout
        assert (root / "continued").exists(), "shared change must run all regression"
        (scripts / "a.py").unlink()
        (root / "continued").unlink()
        rule = root / "framework/rules/rule.md"
        rule.parent.mkdir()
        rule.write_text("# staged rule change\n", encoding="utf-8")
        subprocess.run(["git", "add", str(rule)], cwd=root, check=True)
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
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
        model.write_text(model.read_text(encoding="utf-8") + "trailing whitespace  \n", encoding="utf-8")
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode != 0 and "FAIL git-diff-check" in result.stdout, result.stdout
        subprocess.run(["git", "add", str(model)], cwd=root, check=True)
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode != 0 and "FAIL git-diff-check" in result.stdout, result.stdout
        active.write_text("# missing scope\n", encoding="utf-8")
        before = set(log_parent.glob("blueprint-loop-*"))
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode and "validation scope missing" in result.stderr
        assert set(log_parent.glob("blueprint-loop-*")) == before, "missing scope started validation"
        active.unlink()
        result = subprocess.run(full_command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode and "validation scope missing" in result.stderr
        assert set(log_parent.glob("blueprint-loop-*")) == before, "full mode implicitly widened missing scope"
    print("blueprint-loop: PASS")


if __name__ == "__main__":
    main()
