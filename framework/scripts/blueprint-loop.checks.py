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


def main() -> None:
    check_running_and_interruption()
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
        assert history[0]["event"] == "loop_start" and history[0]["step_count"] == 3
        ended = [event for event in history if event["event"] == "step_end"]
        assert [event["returncode"] for event in ended] == [1, 1, 0]
        assert all(event["duration_seconds"] >= 0 for event in ended)
        assert history[-1]["event"] == "loop_end" and history[-1]["status"] == "fail"
        assert history[-1]["failed_steps"] == ["validate-blueprint.py", "a.checks.py"]
        assert all("timestamp" in event for event in history)
        assert "AssertionError" in (failed_directory / "02-a.checks.py.log").read_text()

        (scripts / "validate-blueprint.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        (scripts / "a.checks.py").write_text("assert True\n", encoding="utf-8")
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS (2 focused check scripts)" in result.stdout
        directories = set(log_parent.glob("blueprint-loop-*"))
        assert len(directories) == 2, "each run must retain its own logs"
        assert events((directories - {failed_directory}).pop())[-1]["status"] == "pass"
        assert events(failed_directory)[-1]["status"] == "fail", "previous logs must not be overwritten"
        rejected = subprocess.run([*command[:-1], str(root / 'logs')], capture_output=True, text=True)
        assert rejected.returncode != 0 and "outside the repository" in rejected.stderr
        assert not (root / "logs").exists()

        # A normal design edit runs the validator only; changed validator code selects its own check.
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
        assert result.returncode == 0 and "PASS (0 focused check scripts)" in result.stdout, result.stdout + result.stderr
        assert not (root / "continued").exists(), "unrelated check ran for a design edit"
        (scripts / "a.py").write_text("# validator change\n")
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0 and "PASS (1 focused check scripts)" in result.stdout
        assert not (root / "continued").exists()
        active.write_text("# missing scope\n")
        before = set(log_parent.glob("blueprint-loop-*"))
        result = subprocess.run(scoped_command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode and "validation scope missing" in result.stderr
        assert set(log_parent.glob("blueprint-loop-*")) == before, "missing scope started validation"
    print("blueprint-loop: PASS")


if __name__ == "__main__":
    main()
