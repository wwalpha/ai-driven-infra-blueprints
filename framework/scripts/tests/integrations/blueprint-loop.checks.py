#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import run_it
from support.blueprint_loop_fixtures import (
    MODULE,
    SCRIPT,
    Path,
    events,
    io,
    json,
    make_loop_fixture,
    make_service_loop_fixture,
    os,
    redirect_stdout,
    run,
    subprocess,
    sys,
)
from support.pytest_cli import groupable, unit_commands

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_running_and_interruption(tmp_path):
    root = tmp_path
    script = root / "slow.py"
    script.write_text(
        "import time\nprint('before wait', flush=True)\ntime.sleep(0.15)\n",
        encoding="utf-8",
    )
    logs = root / "logs"
    logs.mkdir()
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, str(script)]
    with redirect_stdout(io.StringIO()) as output:
        assert (
            MODULE.run_commands(
                root, [command], environment, logs, heartbeat_seconds=0.03
            )
            == 0
        )
    history = events(logs)
    assert history[0]["jobs"] == 1 and history[0]["python_version"] == sys.version
    assert history[0]["hash_seed"] == environment.get("PYTHONHASHSEED")
    assert (
        next(event for event in history if event["event"] == "step_start")["command"]
        == command
    )
    assert any(event["event"] == "heartbeat" for event in history)
    assert "RUNNING slow.py" in output.getvalue()
    assert "before wait" in (logs / "01-slow.py.log").read_text(encoding="utf-8")
    assert history[-1]["status"] == "pass"
    assert history[-1]["duration_seconds"] >= 0.15
    running = next(event for event in history if event["event"] == "step_running")
    assert running["pid"] > 0


def check_official_receipts_and_fixture_git(tmp_path):
    check = TestCase()
    tests = tmp_path / "framework/scripts/tests"
    integrations = tests / "integrations"
    integrations.mkdir(parents=True)
    sources = {
        "pytest.checks.py": "import pytest\nfrom unittest import TestCase\nfrom support.pytest_cli import run\n@pytest.mark.parametrize('value', [False, True])\ndef check_body(value):\n TestCase().assertIs(type(value), bool)\nif __name__ == '__main__':\n raise SystemExit(run(__file__))\n",
        "direct.checks.py": "from support.it_case_receipt import it_case, module_complete\n@it_case\ndef verify():\n return 3\nverify()\nverify()\nmodule_complete(__file__)\n",
    }
    (tests / "pytest.ini").write_text(
        "[pytest]\npython_functions = check_*\naddopts = --import-mode=importlib -p no:cacheprovider\n",
        encoding="utf-8",
    )
    receipts = []
    for name, source in sources.items():
        suite = integrations / name
        suite.write_text(source, encoding="utf-8")
        receipt = tmp_path / (name + ".json")
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                run_it.__file__,
                "--suite",
                str(suite),
                "--tests",
                str(tests),
                "--receipt",
                str(receipt),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        check.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipts.append(json.loads(receipt.read_text(encoding="utf-8")))
    discovery, errors = run_it.inventory(tests)
    check.assertEqual(errors, [])
    check.assertEqual(
        run_it.reachability(discovery.cases, receipts, owners=discovery.owners), []
    )
    root = tmp_path / "git-fixture"
    root.mkdir()
    (root / "model").mkdir()
    (root / "model/value.txt").write_text("independent Model", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    check.assertEqual(tracked.stdout.splitlines(), ["model/value.txt"])


def check_task_service_validation(tmp_path):
    root = tmp_path / "repository"
    make_service_loop_fixture(root)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "task",
            "--task-file",
            "tasks/example.md",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
        cwd=root,
        env=MODULE.utf8_environment(),
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "START validate-blueprint.py" in result.stdout
    assert "validation scope: dev/123456789012/iam" in result.stdout
    assert "START git-diff-check" in result.stdout
    assert "framework regression: skipped" in result.stdout
    assert "PASS (0 framework regression scripts)" in result.stdout


def check_parallel_and_selection(tmp_path):
    root = tmp_path
    scripts = root / "framework/scripts"
    scripts.mkdir(parents=True)
    (scripts / "tests/units").mkdir(parents=True, exist_ok=True)
    logs = root / "logs"
    logs.mkdir()
    commands = []
    for name, other, code in (("a", "b", 0), ("b", "a", 0)):
        script = scripts / f"tests/units/{name}.checks.py"
        script.write_text(
            "from pathlib import Path\nimport time\n"
            f"Path('{name}').touch()\nend=time.monotonic()+5\n"
            f"while not Path('{other}').exists() and time.monotonic()<end: time.sleep(.01)\n"
            f"assert Path('{other}').exists(), 'workers did not overlap'\n"
            f"print('diagnostic-{name}')\nraise SystemExit({code})\n",
            encoding="utf-8",
        )
        commands.append([sys.executable, str(script)])
    with redirect_stdout(io.StringIO()) as output:
        TestCase().assertEqual(
            MODULE.run_commands(
                root, commands, MODULE.utf8_environment(), logs, jobs=2
            ),
            0,
        )
    assert output.getvalue().index("diagnostic-a") < output.getvalue().index(
        "diagnostic-b"
    )
    TestCase().assertEqual(events(logs)[-1]["failed_steps"], [])


def check_group_process_connection(tmp_path):
    tests = Path(__file__).resolve().parents[1]
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\npython_files = *-unit.checks.py\npython_functions = check_*\naddopts = --import-mode=importlib -p no:cacheprovider\n",
        encoding="utf-8",
    )
    (tmp_path / "conftest.py").write_text(
        f"import importlib.util\nspec = importlib.util.spec_from_file_location('group_fixtures', {str(tests / 'conftest.py')!r})\n"
        "module = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\nprocess_state = module.process_state\n",
        encoding="utf-8",
    )
    first, second, isolated = [
        tmp_path / f"{name}-unit.checks.py" for name in ("a", "b", "isolated")
    ]
    prefix = "import os\nfrom support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
    suffix = "if __name__ == '__main__': raise SystemExit(run(__file__))\n"
    first.write_text(
        prefix
        + "def check_change():\n    assert 'GROUP_CONNECTION' not in os.environ\n    os.environ['GROUP_CONNECTION'] = 'group'\n"
        + suffix,
        encoding="utf-8",
    )
    second.write_text(
        prefix + "import pytest\n@pytest.mark.parametrize('value', [1, 2])\n"
        "def check_clean(value): assert 'GROUP_CONNECTION' not in os.environ\n"
        + suffix,
        encoding="utf-8",
    )
    isolated.write_text(
        "import os\nfrom support.pytest_cli import run\n"
        "def check_isolated():\n    assert 'GROUP_CONNECTION' not in os.environ\n"
        "    os.environ['GROUP_CONNECTION'] = 'isolated'\n"
        "if __name__ == '__main__':\n"
        "    os.environ.pop('PYTEST_ADDOPTS', None)\n"
        "    raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    assert groupable(first) and groupable(second) and not groupable(isolated)
    commands = unit_commands([first, second, isolated])
    assert commands == [
        [
            sys.executable,
            str(tests / "support/pytest_cli.py"),
            "--group",
            str(first),
            str(second),
        ],
        [sys.executable, str(isolated)],
    ]
    environment = dict(os.environ, PYTHONPATH=str(tests), PYTEST_ADDOPTS="-vv")
    environment.pop("GROUP_CONNECTION", None)
    logs = tmp_path / "logs"
    logs.mkdir()
    with redirect_stdout(io.StringIO()):
        assert (
            MODULE.run_commands(tmp_path, commands[::-1], environment, logs, jobs=1)
            == 0
        )
    history = events(logs)
    assert [
        event["returncode"] for event in history if event["event"] == "step_end"
    ] == [0, 0]
    assert history[-1]["status"] == "pass" and history[-1]["failed_steps"] == []
    group_log = (logs / "02-pytest_cli.py.log").read_text(encoding="utf-8")
    assert all(f"check_clean[{value}] PASSED" in group_log for value in (1, 2))
    assert "check_change PASSED" in group_log
    assert (logs / "01-isolated-unit.checks.py.log").is_file()


def check_staged_snapshot(tmp_path):
    root = tmp_path / "source"
    scripts = root / "checks"
    scripts.mkdir(parents=True)
    (scripts / "tests/units").mkdir(parents=True, exist_ok=True)
    make_loop_fixture(scripts)
    # These isolated runner fixtures exercise orchestration after authorization.
    (scripts / "tests/units/snapshot.checks.py").write_text(
        "print('snapshot regression assertion executed')\n", encoding="utf-8"
    )
    (root / "tasks").mkdir()
    active = root / "tasks/snapshot.md"
    contract = (
        "## Task contract\n- Task type: `governance`\n- Task status: `running`\n"
        "## Validation scope\n- `framework`\n## Modified files\n- `tasks/snapshot.md`\n"
        "- `checks/validate-blueprint.py`\n## Allowed paths\n- `tasks/snapshot.md`\n"
        "- `checks/validate-blueprint.py`\n"
    )
    MODULE.git(root, "init", "-q")
    active.write_text(contract, encoding="utf-8")
    validator = scripts / "validate-blueprint.py"
    validator.write_text("print('base')\n", encoding="utf-8")
    MODULE.git(root, "add", ".")
    MODULE.git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "base",
    )
    (root / "historical.txt").write_text("old version", encoding="utf-8")
    MODULE.git(root, "add", ".")
    MODULE.git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "history",
    )
    base = MODULE.git(root, "rev-parse", "HEAD")
    validator.write_text(
        "from pathlib import Path\nimport subprocess\n"
        "assert not Path('untracked.txt').exists()\n"
        "text=Path('tasks/snapshot.md').read_text(encoding='utf-8')\n"
        f"assert text == {contract!r}\n"
        "assert subprocess.check_output(['git','rev-list','--count','HEAD'], text=True).strip() == '1'\n"
        "paths=subprocess.check_output(['git','diff','--cached','--name-only'], text=True)\n"
        "assert 'validate-blueprint.py' in paths\nprint('日本語 snapshot')\n",
        encoding="utf-8",
    )
    MODULE.git(root, "add", ".")
    active.write_text("dirty workspace contract", encoding="utf-8")
    (root / "untracked.txt").write_text("not staged", encoding="utf-8")
    MODULE.git(root, "add", "checks/validate-blueprint.py")
    log_parent = tmp_path / "logs"
    command = [
        sys.executable,
        str(scripts / SCRIPT.name),
        "--mode",
        "task",
        "--staged",
        "--base",
        base,
        "--log-dir",
        str(log_parent),
    ]
    environment = {
        **MODULE.utf8_environment(),
        "PYTHONUTF8": "0",
        "PYTHONIOENCODING": "ascii",
    }
    index = Path(MODULE.git(root, "rev-parse", "--git-path", "index"))
    if not index.is_absolute():
        index = root / index
    saved_index = index.read_bytes()
    result = subprocess.run(
        command, cwd=root, env=environment, capture_output=True, encoding="utf-8"
    )
    assert result.returncode == 0 and "日本語 snapshot" in result.stdout, (
        result.stdout + result.stderr
    )
    assert "snapshot regression assertion executed" not in result.stdout
    assert "PASS (0 framework regression scripts)" in result.stdout
    assert index.read_bytes() == saved_index
    assert active.read_text(encoding="utf-8") == "dirty workspace contract"
    metadata = json.loads(
        next(log_parent.glob("*/snapshot.json")).read_text(encoding="utf-8")
    )
    assert metadata["base"] == base and metadata["source_unchanged"]


def check_successful_workflow(tmp_path) -> None:
    root = tmp_path / "repository"
    log_parent = tmp_path / "logs"
    scripts = root / "checks"
    scripts.mkdir(parents=True)
    (scripts / "tests/units").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    make_loop_fixture(scripts)
    (scripts / "validate-blueprint.py").write_text(
        "print('validator success')\n", encoding="utf-8"
    )
    (scripts / "tests/units/a.checks.py").write_text(
        "from unittest import TestCase; TestCase().assertTrue(__debug__)\n",
        encoding="utf-8",
    )
    (scripts / "tests/units/b.checks.py").write_text(
        "from pathlib import Path\nPath('continued').write_text('yes', encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-O",
        str(scripts / SCRIPT.name),
        "--mode",
        "local",
        "--all",
        "--jobs",
        "1",
        "--log-dir",
        str(log_parent),
    ]
    environment = {**os.environ, "PYTHONOPTIMIZE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        command, cwd=root, env=environment, capture_output=True, encoding="utf-8"
    )
    TestCase().assertEqual(result.returncode, 0, result.stdout + result.stderr)
    TestCase().assertIn("validator success", result.stdout)
    assert (root / "continued").read_text(encoding="utf-8") == "yes"
    failed_directory = next(log_parent.glob("blueprint-loop-*"))
    startup = [
        json.loads(line)
        for line in (failed_directory / "startup.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert startup[0]["event"] == "directory_created"
    assert {
        "task.contract.read",
        "git.config",
        "commands.prepare",
        "utf8.subprocess",
        "utf8.output",
        "utf8.cleanup",
        "stdout.print",
        "stdout.flush",
        "timing.open",
    } <= {event["step"] for event in startup if event["event"] == "end"}
    history = events(failed_directory)
    assert history[0]["event"] == "loop_start" and history[0]["step_count"] == 5
    ended = [event for event in history if event["event"] == "step_end"]
    TestCase().assertEqual([event["returncode"] for event in ended], [0, 0, 0, 0, 0])
    assert all(event["duration_seconds"] >= 0 for event in ended)
    TestCase().assertEqual(
        (history[-1]["event"], history[-1]["status"]), ("loop_end", "pass")
    )
    TestCase().assertEqual(history[-1]["failed_steps"], [])
    assert all("timestamp" in event for event in history)


def main():
    return run(__file__, message="blueprint-loop: PASS")


if __name__ == "__main__":
    raise SystemExit(main())
