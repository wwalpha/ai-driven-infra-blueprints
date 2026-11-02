#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import ast
import shutil
import sys
import warnings
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as _CallbackState
from unittest import TestCase
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import import_guard
import model.importing.evidence as import_evidence
import run_it
import support.model_design_fixtures as _imports_support_model_design_fixtures
import utils.aws_mappings as _imports_utils_aws_mappings
from model.importing import evidence
from model.importing.evidence import FORMAT_FIELDS
from support import it_fixture_bundle as fixtures
from support.blueprint_loop_fixtures import (
    CLI,
    MODULE,
    SCRIPT,
    Path,
    SimpleNamespace,
    events,
    io,
    json,
    make_project_fixture,
    os,
    patch,
    pytest,
    redirect_stdout,
    subprocess,
    sys,
    tasks,
)
from support.it_workspace import populate, populate_focused
from support.pytest_cli import GroupDiagnostics, groupable, run_group, unit_commands
from support.pytest_cli import run as pytest_run
from support.validator import MODULE as validator
from support.validator import project, schema_validator, write
from utils import sealed_evidence
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.git_changes import GitWorkingPaths
from utils.script_loader import module
from validation import runner as validation_runner
from validation.project import check_validation_scope as validate_scope

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_utf8_restart():
    entrypoint = SCRIPT.read_text(encoding="utf-8").split(
        'if __name__ == "__main__":', 1
    )[1]
    for code in (0, 2, 7, 130):
        namespace = {
            **MODULE.__dict__,
            "_loop": MODULE,
            "sys": SimpleNamespace(
                flags=SimpleNamespace(utf8_mode=0),
                platform="win32",
                executable=sys.executable,
                argv=[str(SCRIPT), "--mode", "task"],
            ),
        }
        with (
            patch.object(MODULE.subprocess, "call", return_value=code) as child,
            patch.object(MODULE.signal, "signal"),
            pytest.raises(SystemExit) as result,
        ):
            exec(compile("if True:" + entrypoint, str(SCRIPT), "exec"), namespace)
        assert result.value.code == code
        assert child.call_args.args[0][:3] == [sys.executable, "-X", "utf8"]


def check_changed_paths_error(tmp_path):
    working = GitWorkingPaths(frozenset({"framework/a.py"}), frozenset(), frozenset())
    with patch.object(MODULE, "collect_working_paths", return_value=working) as collect:
        result = MODULE.changed_paths(tmp_path)
        collect.assert_called_once_with(tmp_path)
    assert isinstance(result, set) and result == working.all_paths
    result.clear()
    assert MODULE.framework_changed(set(working.all_paths))
    assert not MODULE.framework_changed({"model/dev/cde/s3.properties"})
    error = ValueError("cannot read Git paths")
    with (
        patch.object(MODULE, "collect_working_paths", side_effect=error),
        pytest.raises(ValueError) as caught,
    ):
        MODULE.changed_paths(tmp_path)
    assert caught.value is error


def check_issue_loop_has_no_git_change_checks(tmp_path):
    root = tmp_path / "repository"
    name = "tasks/issues.md"
    root.mkdir()
    tasks.start(
        root,
        name,
        "## Task contract\n- Task type: `migration`\n- Task status: `running`\n"
        "## Required changes\n- [R1] Save issue report\n## Acceptance checks\n- [R1] `exists:issues/dev/cde/issues.md`\n"
        "## Validation scope\n- `dev/cde/s3`\n## Modified files\n- `tasks/issues.md`\n"
        "- `issues/dev/cde/issues.md`\n## Allowed paths\n- `tasks/issues.md`\n- `issues/dev/cde/issues.md`\n",
    )
    with (
        patch.object(Path, "cwd", return_value=root),
        patch.object(
            MODULE,
            "changed_paths",
            side_effect=AssertionError("Issue must not discover Git changes"),
        ),
        patch.object(MODULE, "run_commands", return_value=0) as dispatch,
        patch.object(MODULE, "utf8_preflight"),
        patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ),
        patch.object(
            sys,
            "argv",
            [
                "blueprint-loop.py",
                "--mode",
                "local",
                "--task-file",
                name,
                "--log-dir",
                str(tmp_path / "logs"),
            ],
        ),
    ):
        assert CLI.main() == 0
    commands = dispatch.call_args.args[1]
    assert len(commands) == 1 and "validate-blueprint.py" in commands[0][1]


def check_process_interruption(tmp_path):
    root = tmp_path
    logs = root / "logs"
    logs.mkdir()
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, str(root / "slow.py")]
    with (
        patch.object(MODULE.subprocess, "Popen") as popen,
        redirect_stdout(io.StringIO()),
    ):
        process = popen.return_value
        process.pid = 123
        process.returncode = -9
        process.wait.side_effect = [
            KeyboardInterrupt(),
            subprocess.TimeoutExpired(command, 5),
            -9,
        ]
        assert MODULE.run_commands(root, [command, command], environment, logs) == 130
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        assert popen.call_count == 1
    history = events(logs)
    assert history[-1]["status"] == "interrupted"
    assert history[-2]["status"] == "interrupted"
    with (
        patch.object(MODULE.subprocess, "Popen", side_effect=KeyboardInterrupt()),
        redirect_stdout(io.StringIO()),
    ):
        assert MODULE.run_commands(root, [command], environment, logs) == 130
    assert events(logs)[-1]["status"] == "interrupted"

    with (
        patch.object(MODULE.subprocess, "Popen") as popen,
        redirect_stdout(io.StringIO()),
    ):
        process = Mock(pid=123, returncode=0)
        process.wait.return_value = 0
        popen.side_effect = [OSError("cannot start"), process]
        assert MODULE.run_commands(root, [command, command], environment, logs) == 1
    ended = [event for event in events(logs) if event["event"] == "step_end"]
    assert [event["status"] for event in ended] == ["error", "pass"]
    assert ended[0]["error"] == "cannot start"
    assert events(logs)[-1]["status"] == "fail"


def check_parallel_interruption(tmp_path):
    root = tmp_path
    logs = root / "logs"
    logs.mkdir()
    commands = [[sys.executable, "a.checks.py"], [sys.executable, "test_b.py"]]
    with (
        patch.object(MODULE.subprocess, "Popen") as popen,
        redirect_stdout(io.StringIO()),
    ):
        first, second = Mock(pid=1, returncode=-9), Mock(pid=2, returncode=-9)
        first.wait.side_effect = [
            KeyboardInterrupt(),
            subprocess.TimeoutExpired([], 5),
            -9,
        ]
        second.wait.return_value = -9
        popen.side_effect = [first, second]
        assert (
            MODULE.run_commands(root, commands, MODULE.utf8_environment(), logs, jobs=2)
            == 130
        )
        first.terminate.assert_called_once()
        second.terminate.assert_called_once()
        first.kill.assert_called_once()


@pytest.mark.parametrize("jobs", [0, 3, 4, True])
def check_worker_limit(tmp_path, jobs):
    with (
        patch.object(MODULE.subprocess, "Popen") as child,
        pytest.raises(ValueError, match="1 or 2"),
    ):
        MODULE.run_commands(tmp_path, [], {}, tmp_path, jobs=jobs)
    child.assert_not_called()


@pytest.mark.parametrize("changed,expected", [("dev", True), ("stg", False)])
def check_deployment_scope_decision(tmp_path, changed, expected):
    findings = Mock()
    relative = f"infra/cloudformation/parameters/{changed}/team/a.json"
    validate_scope(
        {},
        {relative},
        None,
        findings,
        tmp_path,
        None,
        {tmp_path / "infra/cloudformation/parameters/dev/team/a.json"},
    )
    findings.check.assert_called_once_with(
        expected, f"changed IaC path is outside Deployment scope: {relative}"
    )


def _command_outcome(codes, command, **kwargs):
    code = codes.pop(0)
    kwargs["stdout"].write(f"diagnostic: {command[1]}: {code}\n")
    process = Mock(pid=123, returncode=code)
    process.wait.return_value = code
    return process


def check_failed_commands_continue_and_keep_diagnostics(tmp_path):
    check = TestCase()
    commands = [
        [sys.executable, "validate-blueprint.py"],
        [sys.executable, "pytest_cli.py", "--group", "a.py"],
        [sys.executable, "pytest_cli.py", "--group", "b.py"],
        ["git", "diff", "--check"],
    ]
    with (
        patch.object(
            MODULE.subprocess,
            "Popen",
            side_effect=_bind_framework_callback(_command_outcome, [1, 1, 0, 0]),
        ) as child,
        redirect_stdout(io.StringIO()) as output,
    ):
        check.assertEqual(
            MODULE.run_commands(
                tmp_path, commands, MODULE.utf8_environment(), tmp_path, jobs=2
            ),
            1,
        )
    check.assertEqual(child.call_count, len(commands))
    check.assertEqual(
        [row["returncode"] for row in events(tmp_path) if row["event"] == "step_end"],
        [1, 1, 0, 0],
    )
    check.assertEqual(
        events(tmp_path)[-1]["failed_steps"], ["validate-blueprint.py", "pytest_cli.py"]
    )
    check.assertIn("diagnostic: pytest_cli.py: 1", output.getvalue())
    check.assertNotIn(tasks.SELECTOR, child.call_args_list[1].kwargs["env"])


@pytest.mark.parametrize("result", [1, 130])
def check_loop_failure_suspends_only_selected(tmp_path, result):
    check = TestCase()
    root = tmp_path / "repository"
    root.mkdir()
    selected, other = "tasks/selected.md", "tasks/other.md"
    for name in (selected, other):
        tasks.start(
            root,
            name,
            f"## Task contract\n- Task type: `governance`\n- Task status: `running`\n## Required changes\n- [R1] Synthetic task\n## Acceptance checks\n- [R1] `exists:{name}`\n## Validation scope\n- `framework`\n## Modified files\n- `{name}`\n## Allowed paths\n- `{name}`\n",
        )
    before = (root / other).read_bytes()
    with (
        patch.object(Path, "cwd", return_value=root),
        patch.object(MODULE, "active_scope", return_value={"framework"}),
        patch.object(MODULE, "changed_paths", return_value=set()),
        patch.object(MODULE, "run_commands", return_value=result),
        patch.object(
            MODULE, "failure_reason", return_value="synthetic validator failure"
        ),
        patch.object(MODULE, "utf8_preflight"),
        patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ),
        patch.object(
            sys,
            "argv",
            [
                str(SCRIPT),
                "--mode",
                "task",
                "--task-file",
                selected,
                "--log-dir",
                str(tmp_path / "logs"),
            ],
        ),
    ):
        check.assertEqual(CLI.main(), result)
    check.assertEqual(
        tasks.status((root / selected).read_text(encoding="utf-8")), "suspend"
    )
    check.assertEqual((root / other).read_bytes(), before)


def check_index_conflict_stops_snapshot(tmp_path):
    source = tmp_path / "source-index"
    source.write_bytes(b"synthetic index")
    directory = tmp_path / "private"
    directory.mkdir()
    failure = subprocess.CalledProcessError(
        1, ["git", "write-tree"], stderr="unmerged index"
    )
    with (
        patch.object(
            MODULE.subprocess,
            "run",
            side_effect=[subprocess.CompletedProcess([], 0, str(source), ""), failure],
        ) as git,
        pytest.raises(subprocess.CalledProcessError) as caught,
    ):
        MODULE.index_tree(tmp_path, directory)
    TestCase().assertIs(caught.value, failure)
    TestCase().assertIn("write-tree", git.call_args.args[0])


def check_fixture_independence(tmp_path):
    before = dict(os.environ), Path.cwd()
    with project() as first, project() as second:
        assert first != second
        write(first / "日本語.txt", "独立fixture")
        a, b = schema_validator(first), schema_validator(second)
        assert type(a) is type(b) is validator.Validator
        a.errors.append("local state")
        assert not b.errors and a.schema_catalog is not b.schema_catalog
    assert before == (dict(os.environ), Path.cwd())
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "framework").mkdir(parents=True)
    for name in ("AGENTS.md", "README.md"):
        (source / name).write_text("framework input", encoding="utf-8")
    for name in (
        "issues/dev/other/issues.md",
        "model/dev/other/ec2.properties",
        "docs/designs/dev/other/ec2.md",
        "tasks/example.md",
        "project.json",
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid consumer input", encoding="utf-8")
    make_project_fixture(source, target)


def check_regression_discovery(tmp_path):
    with (
        patch.object(MODULE, "definition_root", return_value=tmp_path),
        pytest.raises(ValueError, match="no framework regression checks discovered"),
    ):
        MODULE.select_checks(tmp_path)
    root = Path(__file__).resolve().parents[4]
    all_checks = {p.name for p in MODULE.select_checks(root)[0]}
    assert all_checks == {
        p.name for p in (root / "framework/scripts/tests/units").rglob("*.checks.py")
    } | {"test_issues_iac.py"}
    assert "service-parameter-inputs.checks.py" not in all_checks
    assert "git-changes-unit.checks.py" in all_checks
    assert all(
        p.is_relative_to(root / "framework/scripts/tests/units")
        for p in MODULE.select_checks(root)[0]
    )


@pytest.mark.parametrize("entry", ["run(__file__)", "main()"])
def check_pytest_group_selection(tmp_path, entry):
    check = TestCase()
    paths = []
    for name in ("a-unit.checks.py", "b-unit.checks.py", "c-unit.checks.py"):
        path = tmp_path / name
        path.write_text(
            "from support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
            "def check_ok(): pass\n"
            "def main(): return run(__file__, message='done')\n"
            f"if __name__ == '__main__': raise SystemExit({entry})\n",
            encoding="utf-8",
        )
        paths.append(path)
    direct = tmp_path / "direct.checks.py"
    direct.write_text("print('direct assertion')\n", encoding="utf-8")
    paths.append(direct)
    commands = unit_commands(paths)
    check.assertEqual(len(commands), 3)
    check.assertEqual(commands[-1], [sys.executable, str(direct)])
    check.assertCountEqual(
        [path for command in commands[:2] for path in command[3:]],
        [str(path) for path in paths[:-1]],
    )
    check.assertTrue(
        all(MODULE._run_commands_regression(command) for command in commands)
    )
    check.assertFalse(MODULE._run_commands_regression(["git"]))
    with patch("support.pytest_cli.pytest.main", return_value=1) as execute:
        check.assertEqual(run_group(paths[:-1]), 1)
        check.assertEqual(
            execute.call_args.args[0][:-1], [str(path) for path in paths[:-1]]
        )
    for invalid in ([], [paths[0], paths[0]], [direct]):
        with pytest.raises(ValueError, match="unique compatible suites"):
            run_group(invalid)
    direct.write_text(
        paths[0]
        .read_text(encoding="utf-8")
        .replace("run(__file__", "run(__file__, ['check_ok']"),
        encoding="utf-8",
    )
    check.assertFalse(groupable(direct))
    direct.write_text(
        "from support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
        "class Shared: values = []\n"
        "def check_ok(): Shared.values.append(1)\n"
        "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    check.assertFalse(groupable(direct))
    for mutation in (
        "external.value = 1",
        "external.cache.clear()",
        "alias = external.cache; alias['value'] = 1",
        "setattr(external, 'value', 1)",
        "globals().update(value=1)",
        "sys.path_importer_cache.clear()",
        "module = acquire(); module.value = 1",
        "alias = sys.modules; alias['synthetic'] = 1",
        "__builtins__['__import__']('warnings').filterwarnings('ignore')",
    ):
        direct.write_text(
            "import external, sys\nfrom support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
            "def check_ok():\n    " + mutation + "\n"
            "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
            encoding="utf-8",
        )
        check.assertFalse(groupable(direct))
    for content, expected in (
        ("import external\ndef check_ok(): external.calculate()\n", True),
        (
            "import warnings\ndef check_ok(): change = warnings.filterwarnings; change('ignore')\n",
            False,
        ),
    ):
        direct.write_text(
            "from support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
            + content
            + "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
            encoding="utf-8",
        )
        check.assertEqual(groupable(direct), expected)
        direct.write_text(
            direct.read_text(encoding="utf-8").replace(
                "PYTEST_GROUP_SAFE = True\n", ""
            ),
            encoding="utf-8",
        )
        check.assertFalse(groupable(direct))
    for marker in ("skip", "skipif", "xfail"):
        direct.write_text(
            "import pytest\nfrom support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
            f"@pytest.mark.{marker}(True, reason='platform contract')\n"
            "def check_ok(): pass\n"
            "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
            encoding="utf-8",
        )
        check.assertFalse(groupable(direct))


@pytest.mark.parametrize(
    "fault", [None, "missing", "duplicate", "unknown", "skip", "fail", "xfail", "unrun"]
)
def check_pytest_group_completeness(tmp_path, fault):
    check = TestCase()
    path = tmp_path / "a-unit.checks.py"
    path.write_text("def check_ok(value): pass\n", encoding="utf-8")
    plugin = GroupDiagnostics([path])
    plugin.pytest_sessionstart(None)
    items = [
        SimpleNamespace(
            path=path,
            nodeid=f"a-unit.checks.py::check_ok[{value}]",
            originalname="check_ok",
        )
        for value in (1, 2)
    ]
    for item in items:
        plugin.pytest_itemcollected(item)
    if fault == "missing":
        items = items[:1]
    elif fault == "duplicate":
        items.append(items[0])
    elif fault == "unknown":
        items.append(
            SimpleNamespace(
                path=tmp_path / "unknown.py",
                nodeid="unknown.py::check",
                originalname="check",
            )
        )
    plugin.pytest_collection_finish(SimpleNamespace(items=items))
    for item in items:
        report = SimpleNamespace(
            nodeid=item.nodeid,
            when="call",
            passed=True,
            failed=False,
            skipped=False,
            longrepr="fault diagnostic",
        )
        if fault in ("skip", "fail"):
            report.passed = False
            report.skipped, report.failed = fault == "skip", fault == "fail"
        if fault == "xfail":
            report.wasxfail = "unexpected xpass"
        if fault != "unrun":
            plugin.pytest_runtest_logreport(report)
    session = SimpleNamespace(exitstatus=0)
    plugin.pytest_sessionfinish(session, 0)
    check.assertEqual(session.exitstatus, 0 if fault is None else 1)
    session.exitstatus = 2
    plugin.pytest_sessionfinish(session, 2)
    check.assertEqual(session.exitstatus, 2)


def check_group_subprocess_isolation_and_collection(tmp_path):
    check = TestCase()
    tests = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(tests))
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\npython_files = *-unit.checks.py\npython_functions = check_*\naddopts = --import-mode=importlib\n",
        encoding="utf-8",
    )
    first = tmp_path / "first-unit.checks.py"
    second = tmp_path / "second-unit.checks.py"
    first.write_text(
        "import importlib\nfrom support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
        "def check_mutation():\n"
        "    module = importlib.import_module('sys')\n"
        "    module.modules['synthetic_leak'] = 'value'\n"
        "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    second.write_text(
        "import sys\nfrom support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
        "def check_clean():\n"
        "    if 'synthetic_leak' in sys.modules: raise ValueError('leaked')\n"
        "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    for path in (first, second):
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        check.assertEqual(result.returncode, 0, result.stderr)
    check.assertFalse(groupable(first))
    safe = tmp_path / "safe-unit.checks.py"
    safe.write_text(
        "from support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\ndef check_ok(): pass\nif __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    check.assertTrue(groupable(safe))
    commands = unit_commands([first, second, safe])
    check.assertIn([sys.executable, str(first)], commands)
    for command in commands:
        result = subprocess.run(
            command, cwd=tmp_path, env=env, capture_output=True, text=True
        )
        check.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    first.write_text(
        "import pytest\nfrom support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
        "@pytest.mark.parametrize('value', [1, 2])\n"
        "def check_parameter(value): pass\n"
        "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(tests / "support/pytest_cli.py"),
        "--group",
        str(first),
        str(safe),
    ]
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True
    )
    check.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    (tmp_path / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    items[:] = [item for item in items if item.nodeid != 'first-unit.checks.py::check_parameter[2]']\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True
    )
    check.assertNotEqual(result.returncode, 0)
    check.assertIn("first-unit.checks.py::check_parameter[2]", result.stderr)


@pytest.mark.parametrize(
    "imports,mutation",
    [
        (
            "import warnings",
            "warnings.filterwarnings('ignore', message='synthetic-isolation')",
        ),
        (
            "import warnings as alias",
            "alias.filterwarnings('ignore', message='synthetic-isolation')",
        ),
        (
            "from warnings import filterwarnings",
            "filterwarnings('ignore', message='synthetic-isolation')",
        ),
        (
            "import importlib",
            "importlib.import_module('warnings').filterwarnings('ignore', message='synthetic-isolation')",
        ),
        (
            "from synthetic_external import change as unknown",
            "unknown()",
        ),
    ],
)
def check_group_unknown_external_calls_are_isolated(tmp_path, imports, mutation):
    check = TestCase()
    tests = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(tests))
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\npython_files = *-unit.checks.py\npython_functions = check_*\naddopts = --import-mode=importlib\n",
        encoding="utf-8",
    )
    (tmp_path / "synthetic_external.py").write_text(
        "import warnings\ndef change(): warnings.filterwarnings('ignore', message='synthetic-isolation')\n",
        encoding="utf-8",
    )
    unsafe = tmp_path / "unsafe-unit.checks.py"
    unsafe.write_text(
        imports
        + "\nfrom support.pytest_cli import run\n"
        + ("" if "synthetic_external" in imports else "PYTEST_GROUP_SAFE = True\n")
        + "def check_mutation():\n    "
        + mutation
        + "\n"
        "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    safe = tmp_path / "safe-unit.checks.py"
    safe.write_text(
        "import warnings\nfrom support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\n"
        "def check_clean():\n"
        "    if any('synthetic-isolation' in str(item[1]) for item in warnings.filters): raise ValueError('leaked')\n"
        "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    other = tmp_path / "other-unit.checks.py"
    other.write_text(
        "from support.pytest_cli import run\nPYTEST_GROUP_SAFE = True\ndef check_ok(): pass\nif __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    check.assertFalse(groupable(unsafe))
    check.assertTrue(groupable(safe))
    check.assertTrue(groupable(other))
    for path in (unsafe, safe):
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        check.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    commands = unit_commands([unsafe, safe, other])
    check.assertIn([sys.executable, str(unsafe)], commands)
    group = [
        sys.executable,
        str(tests / "support/pytest_cli.py"),
        "--group",
        str(safe),
        str(other),
    ]
    for command in ([sys.executable, str(unsafe)], group):
        result = subprocess.run(
            command, cwd=tmp_path, env=env, capture_output=True, text=True
        )
        check.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@pytest.mark.parametrize("leak", [False, True])
def check_group_process_state_restoration(tmp_path, leak):
    check = TestCase()
    configuration = module("tests/conftest.py", "blueprint_group_fixture_checks")
    request = SimpleNamespace(
        config=SimpleNamespace(blueprint_ut_group=True),
        node=SimpleNamespace(nodeid="synthetic::case"),
    )
    key = "BLUEPRINT_GROUP_ISOLATION_CHECK"
    environment, paths, arguments, cwd = (
        dict(os.environ),
        sys.path[:],
        sys.argv[:],
        Path.cwd(),
    )
    environment_object = os.environ
    warning_filters = warnings.filters[:]
    original = GroupDiagnostics.pytest_collectreport
    fixture = configuration.process_state.__wrapped__(request)
    next(fixture)
    try:
        os.environ[key] = "case-local"
        warnings.simplefilter("ignore", category=DeprecationWarning)
        sys.path.append("case-local")
        sys.argv.append("case-local")
        os.chdir(tmp_path)
        if leak:
            os.__dict__["environ"] = {key: "replacement"}
            sys.path = ["replacement"]
            sys.argv = ["replacement"]
            patch.object(GroupDiagnostics, "pytest_collectreport", Mock()).start()
        with pytest.raises(pytest.fail.Exception if leak else StopIteration):
            next(fixture)
    finally:
        fixture.close()
    check.assertIs(os.environ, environment_object)
    check.assertEqual(dict(os.environ), environment)
    check.assertEqual(sys.path, paths)
    check.assertEqual(sys.argv, arguments)
    check.assertEqual(Path.cwd(), cwd)
    check.assertEqual(warnings.filters, warning_filters)
    check.assertIs(GroupDiagnostics.pytest_collectreport, original)


@pytest.mark.parametrize("scope", [set(), {"dev/cde/ec2"}, None])
@pytest.mark.parametrize(
    "paths",
    [
        set(),
        {"framework/scripts/tests/units/a.checks.py"},
        {
            "framework/scripts/import_guard.py",
            "framework/scripts/sync-model.py",
            "framework/scripts/validation/runner.py",
            "framework/scripts/unregistered.py",
        },
        {"model/dev/cde/ec2.properties"},
        {"infra/dev/cde/ec2.yaml"},
    ],
)
def check_unit_dispatch(tmp_path, scope, paths):
    root = tmp_path / "repository"
    scripts = root / "framework/scripts"
    for relative in (
        "tests/units/a.checks.py",
        "tests/units/test_extra.py",
        "tests/integrations/only.checks.py",
    ):
        path = scripts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Selection fixture; never executed\n", encoding="utf-8")
    runner = scripts / "blueprint-loop.py"
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(Path, "cwd", return_value=root),
        patch.object(
            MODULE,
            "active_scope",
            side_effect=lambda root, all_: None if all_ else scope,
        ),
        patch.object(MODULE, "changed_paths", return_value=paths) as changes,
        patch.object(MODULE, "select_checks", wraps=MODULE.select_checks) as selection,
        patch.object(MODULE._imports_validation_runner, "run_validation") as validate,
        patch.object(MODULE, "authorize_full_regression") as authorize,
        patch.object(MODULE, "run_commands", return_value=0) as dispatch,
        patch.object(MODULE, "utf8_preflight"),
        patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ),
        patch.object(MODULE, "staged_snapshot", return_value=0) as staged,
        redirect_stdout(io.StringIO()),
    ):
        for args in (
            ["--mode", "full"],
            ["--mode", "task"],
            ["--mode", "local"],
            ["--mode", "task", "--all"],
            ["--mode", "task", "--fresh", "--profile", "--validation-jobs", "1"],
        ):
            saved_logs = {
                path: path.read_bytes() for path in (tmp_path / "logs").rglob("*.jsonl")
            }
            authorize.reset_mock()
            selection.reset_mock()
            with patch.object(
                sys, "argv", [str(runner), *args, "--log-dir", str(tmp_path / "logs")]
            ):
                assert CLI.main() == 0
            assert all(
                path.read_bytes() == content for path, content in saved_logs.items()
            )
            commands = dispatch.call_args.args[1]
            full = "full" in args or "--all" in args
            assert [Path(command[1]).name for command in commands[1:-2]] == (
                ["a.checks.py", "test_extra.py"] if full else []
            )
            assert all("integrations" not in command[1] for command in commands)
            assert ("--repository-wide-iac" in commands[0]) == full
            assert ("--all" in commands[0]) == ("--all" in args or scope is None)
            if args == ["--mode", "full"]:
                assert "--fresh" in commands[0]
                assert ("--contract-scope" in commands[0]) == (scope is not None)
            if full:
                authorize.assert_called_once_with(root)
            else:
                authorize.assert_not_called()
                selection.assert_not_called()
            assert ",cr-at-eol" in commands[-2][2]
            assert commands[-2][-1] == "--check" and "--cached" in commands[-1]
            dispatch.call_args.kwargs["validation_call"]()
            options = validate.call_args.args[1]
            assert options.fresh == (full or "--fresh" in args)
            if "--validation-jobs" in args:
                assert options.jobs == 1
            if "--profile" in args:
                assert list((tmp_path / "logs").glob("*/validate-blueprint.prof"))
            assert options.repository_wide_iac == full
            assert options.all == ("--all" in args or scope is None)
            assert options.contract_scope == (
                args[1] in {"task", "full"}
                and scope is not None
                and "--all" not in args
            )
        changes.return_value = set()
        with patch.object(
            sys,
            "argv",
            [str(runner), "--mode", "task", "--log-dir", str(tmp_path / "logs")],
        ):
            assert CLI.main() == 0
        assert (
            len(dispatch.call_args.args[1]) == 3
        )  # No forced UT for non-regression scope.
        dispatch.reset_mock()
        authorize.reset_mock()
        with patch.object(
            sys,
            "argv",
            [
                str(runner),
                "--mode",
                "full",
                "--staged",
                "--base",
                "HEAD",
                "--log-dir",
                str(tmp_path / "logs"),
            ],
        ):
            assert CLI.main() == 0
        staged.assert_called_once()
        dispatch.assert_not_called()
        authorize.assert_not_called()  # The pinned snapshot performs its own authorization.


def _check_ci_workflow_invalid_receipts(command, **kwargs):
    path = Path(command[-1])
    if path.name.startswith("a."):
        path.write_text("{broken")
    elif path.name.startswith("b."):
        path.write_text("{}")
    return subprocess.CompletedProcess(command, 0)


def _callback_check_ci_workflow_execute(
    _state_check_ci_workflow_316, /, command, **kwargs
):
    code = _state_check_ci_workflow_316.codes.pop(0)
    if isinstance(code, OSError):
        raise code
    Path(command[-1]).write_text(
        json.dumps(
            {
                "version": 1,
                "suite": "integrations/"
                + Path(command[command.index("--suite") + 1]).name,
                "completed": {},
                "collected": [],
                "passed": [],
                "metrics": {},
            }
        )
    )
    return subprocess.CompletedProcess(command, code)


def check_run_it_dispatch(tmp_path):
    _state_check_ci_workflow_316 = _CallbackState()
    tests = tmp_path / "framework/scripts/tests"
    (tests / "integrations").mkdir(parents=True)
    for name in ("a", "b", "c"):
        (tests / "integrations" / (name + ".checks.py")).write_text("assert True\n")
    output = tmp_path / "receipts"
    output.mkdir()
    for _state_check_ci_workflow_316.codes in (
        [0, 0, 0],
        [1, OSError("injected spawn failure"), 0],
    ):
        execute = _bind_framework_callback(
            _callback_check_ci_workflow_execute, _state_check_ci_workflow_316
        )
        summary = io.StringIO()
        with patch.object(run_it.subprocess, "run", side_effect=execute) as launch:
            rows, _ = run_it.execute_suites(tests, output, summary)
        assert len(rows) == launch.call_count == 3
        assert rows[-1]["code"] == 0
        assert "Suites: 3" in summary.getvalue()
        assert all(
            call.args[0][:4] == [sys.executable, "-B", "-X", "utf8"]
            for call in launch.call_args_list
        )
        for path in output.iterdir():
            path.unlink()
    assert [row["code"] for row in rows] == [1, 1, 0]

    invalid_receipts = _check_ci_workflow_invalid_receipts
    with patch.object(run_it.subprocess, "run", side_effect=invalid_receipts):
        rows, receipts = run_it.execute_suites(tests, output, io.StringIO())
    assert all(row["code"] != 0 for row in rows) and not receipts

    for unit_status, it_status in ((0, 0), (1, 0), (0, 1)):
        outcome = {"reachability_errors": [], "suites": [{"code": it_status}]}
        with (
            patch.object(sys, "argv", ["run_it.py"]),
            patch.object(MODULE, "authorize_full_regression") as authorize,
            patch.object(
                MODULE, "select_checks", return_value=([SCRIPT], "all requested")
            ) as discover,
            patch.object(
                MODULE, "run_commands", return_value=unit_status
            ) as unit_dispatch,
            patch.object(run_it, "run_all", return_value=outcome) as it_dispatch,
        ):
            assert run_it.main() == int(bool(unit_status or it_status))
        authorize.assert_called_once_with(run_it.TESTS.parents[2])
        assert discover.call_args.args == (run_it.TESTS.parents[2],)
        assert unit_dispatch.call_args.args[1] == [[sys.executable, str(SCRIPT)]]
        assert unit_dispatch.call_args.kwargs["jobs"] == 2
        it_dispatch.assert_called_once()
        assert it_dispatch.call_args.args[0] == run_it.TESTS
        assert it_dispatch.call_args.kwargs == {}

    with (
        patch.object(sys, "argv", ["run_it.py"]),
        patch.object(
            MODULE, "authorize_full_regression", side_effect=ValueError("locked")
        ),
        patch.object(MODULE, "run_commands") as unit_dispatch,
        patch.object(run_it, "run_all") as it_dispatch,
        pytest.raises(ValueError, match="locked"),
    ):
        run_it.main()
    unit_dispatch.assert_not_called()
    it_dispatch.assert_not_called()


@pytest.mark.parametrize("unit_status", [0, 1])
def check_ut_only_never_reaches_it(unit_status, capsys):
    with (
        patch.object(sys, "argv", ["run_it.py", "--ut-only"]),
        patch.object(MODULE, "authorize_full_regression") as authorize,
        patch.object(MODULE, "select_checks", return_value=([SCRIPT], "all requested")),
        patch.object(MODULE, "run_commands", return_value=unit_status) as units,
        patch.object(run_it, "run_all") as integrations,
        patch.object(run_it, "compare_revisions") as compare,
        patch.object(run_it, "inventory") as inventory,
    ):
        assert run_it.main() == unit_status
    authorize.assert_called_once_with(run_it.TESTS.parents[2])
    assert units.call_args.args[1] == [[sys.executable, str(SCRIPT)]]
    assert units.call_args.kwargs["jobs"] == 2
    integrations.assert_not_called()
    compare.assert_not_called()
    inventory.assert_not_called()
    assert "1 UT suites" in capsys.readouterr().out


@pytest.mark.parametrize(
    "option,value",
    [
        ("--baseline-root", "old"),
        ("--compare-root", "old"),
        ("--suite", "example.checks.py"),
        ("--receipt", "receipt.json"),
        ("--case-id", "case"),
        ("--baseline", None),
    ],
)
def check_ut_only_rejects_it_options(option, value):
    arguments = ["run_it.py", "--ut-only", option, *([value] if value else [])]
    with (
        patch.object(sys, "argv", arguments),
        patch.object(MODULE, "run_commands") as units,
        patch.object(run_it, "run_all") as integrations,
        pytest.raises(SystemExit) as error,
    ):
        run_it.main()
    assert error.value.code == 2
    units.assert_not_called()
    integrations.assert_not_called()


def _write_it_receipt(data, command, **kwargs):
    Path(command[command.index("--receipt") + 1]).write_text(
        json.dumps(data), encoding="utf-8"
    )
    return subprocess.CompletedProcess(command, 0)


def check_it_reachability(tmp_path):
    check = TestCase()
    tests = tmp_path / "framework/scripts/tests"
    (tests / "integrations").mkdir(parents=True)
    suite = tests / "integrations/receipt.checks.py"
    suite.write_text(
        "# Synthetic child; subprocess boundary is mocked\n", encoding="utf-8"
    )
    nodes = [
        f"integrations/receipt.checks.py::check_body[{value}]"
        for value in (False, True)
    ]
    plugin = run_it.PytestReceipt(tests)
    plugin.pytest_configure(SimpleNamespace(rootpath=tests))
    plugin.pytest_collection_finish(
        SimpleNamespace(items=[SimpleNamespace(nodeid=node) for node in nodes])
    )
    for node in nodes:
        plugin.pytest_runtest_logreport(
            SimpleNamespace(nodeid=node, when="setup", passed=True)
        )
        plugin.pytest_runtest_logreport(
            SimpleNamespace(nodeid=node, when="call", passed=True)
        )
    data = dict(
        version=1,
        suite="integrations/receipt.checks.py",
        collected=plugin.collected,
        passed=plugin.passed,
        completed={},
        metrics={},
    )
    cases = {("integrations/receipt.checks.py", "check_body"): "pytest"}
    check.assertEqual(run_it.reachability(cases, [data]), [])
    helper = ("integrations/helper.py", "check_helper")
    with_helper = {**data, "completed": {"::".join(helper): 1}}
    check.assertTrue(run_it.reachability(cases, [with_helper]))
    check.assertEqual(
        run_it.reachability(cases, [with_helper], {**cases, helper: "direct"}), []
    )
    for invalid in (
        None,
        {},
        {**data, "completed": []},
        {**data, "metrics": {"bad": False}},
        {**data, "passed": []},
        {**data, "passed": nodes[:1]},
        {**data, "passed": [nodes[0]] * 2},
    ):
        check.assertTrue(run_it.reachability(cases, [invalid]))
    check.assertTrue(run_it.reachability(cases, []))
    for mode in ("pytest", "direct"):
        check.assertTrue(
            run_it.reachability(
                {**cases, (data["suite"], "check_not_called"): mode}, [data]
            )
        )
    output = tmp_path / "receipts"
    output.mkdir()
    with patch.object(
        run_it.subprocess,
        "run",
        side_effect=_bind_framework_callback(_write_it_receipt, data),
    ) as child:
        rows, receipts = run_it.execute_suites(tests, output, io.StringIO())
    check.assertEqual([row["code"] for row in rows], [0])
    check.assertEqual(run_it.reachability(cases, receipts), [])
    check.assertIn("--suite", child.call_args.args[0])


def check_it_assertion_guards(tmp_path):
    run_it.check_assertion_guards(Path(run_it.__file__).parent)
    guard = "if not __debug__:\n raise SystemExit('Focused checks require assertions; run without -O')\n"
    source = tmp_path / "bootstrap.checks.py"
    source.write_text(
        "import sys\nsys.path.insert(0, 'tests')\n" + guard, encoding="utf-8"
    )
    run_it.check_assertion_guards(tmp_path)
    source.write_text(
        "import sys\nsys.path.insert(1, 'tests')\n" + guard, encoding="utf-8"
    )
    with pytest.raises(ValueError, match="code before assertion guard"):
        run_it.check_assertion_guards(tmp_path)
    source.write_text("print('unsafe')\n" + guard, encoding="utf-8")
    with pytest.raises(ValueError, match="code before assertion guard"):
        run_it.check_assertion_guards(tmp_path)
    source.unlink()
    source = Path(run_it.__file__).read_text()
    assert "setprofile" not in source and "settrace" not in source
    path = tmp_path / "sample.checks.py"
    guard = "if not __debug__:\n    raise SystemExit('Focused checks require assertions; run without -O')\n"
    path.write_text(guard + "assert False\n")
    run_it.check_assertion_guards(tmp_path)
    for invalid in (
        "assert False\n",
        "print(1)\n" + guard,
        guard.replace("raise SystemExit", "print"),
    ):
        path.write_text(invalid)
        with pytest.raises(ValueError):
            run_it.check_assertion_guards(tmp_path)
    tree = ast.parse(source)
    guard_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.If) and ast.unparse(node.test) == "not __debug__"
    )
    with pytest.raises(SystemExit, match="Focused checks require assertions"):
        exec(
            compile(
                ast.Module(body=[guard_node], type_ignores=[]),
                run_it.__file__,
                "exec",
                optimize=1,
            ),
            {},
        )


def check_it_focused_fixture_isolation(tmp_path):
    seed = tmp_path / "seed"
    authored = {
        "project.json": "{}",
        "model/dev/cde/cloudwatch-logs.properties": "# model-format: 2\n",
        "model/dev/cde/cloudwatch-logs/part-001.properties": "selected part",
        "model/stg/cde/cloudwatch-logs.properties": "other environment",
        "model/dev/cde/vpc.properties": "other service",
        "model/dev/cde/config.properties": "config",
    }
    for relative, raw in authored.items():
        path = seed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
    fixtures.protect(seed, True)
    before = fixtures.fingerprint(seed)
    try:
        with patch.object(fixtures, "source", return_value=seed) as source:
            full, first, second, config = (
                tmp_path / name for name in ("full", "first", "second", "config")
            )
            populate("import_sources", full)
            selected = [
                "project.json",
                "model/dev/cde/cloudwatch-logs.properties",
                "model/dev/cde/cloudwatch-logs",
            ]
            for root in (first, second):
                populate_focused("import_sources", root, selected)
                files = {
                    p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
                    for p in root.rglob("*")
                    if p.is_file()
                }
                assert files == {
                    name: raw
                    for name, raw in authored.items()
                    if name == "project.json"
                    or name.startswith("model/dev/cde/cloudwatch-logs")
                }
                assert all(p.stat().st_mode & 0o200 for p in root.rglob("*"))
                assert all(
                    not p.is_symlink() and p.stat().st_nlink == 1
                    for p in root.rglob("*")
                    if p.is_file()
                )
            populate_focused(
                "import_sources",
                config,
                ["project.json", "model/dev/cde/config.properties"],
            )
            assert {
                p.relative_to(config).as_posix()
                for p in config.rglob("*")
                if p.is_file()
            } == {"project.json", "model/dev/cde/config.properties"}
            assert {
                p.relative_to(full).as_posix() for p in full.rglob("*") if p.is_file()
            } == set(authored)
            (first / "model/dev/cde/cloudwatch-logs/part-001.properties").write_text(
                "changed"
            )
            assert (
                second / "model/dev/cde/cloudwatch-logs/part-001.properties"
            ).read_text() == "selected part"
            assert fixtures.fingerprint(seed) == before
            assert all(
                call.args == ("import_sources",) for call in source.call_args_list
            )
    finally:
        fixtures.protect(seed, False)


def _callback_check_it_fixture_isolation_build(generations, /, root, name):
    generations.append(name)
    (root / name).mkdir()
    (root / name / "value.txt").write_text(name)


def check_it_fixture_isolation(tmp_path):
    generations = []
    build = _bind_framework_callback(
        _callback_check_it_fixture_isolation_build, generations
    )
    with patch.object(fixtures, "build", side_effect=build):
        with (
            fixtures.bundle() as root,
            patch.dict(os.environ, {fixtures.ENV: str(root)}),
        ):
            before = fixtures.fingerprint(root)
            for number, names in enumerate(
                (fixtures.NAMES, tuple(reversed(fixtures.NAMES)))
            ):
                for name in names:
                    seed = fixtures.source(name)
                    assert not seed.stat().st_mode & 0o222
                    assert not (seed / "value.txt").stat().st_mode & 0o222
                    first = populate(name, tmp_path / str(number) / name / "first")
                    second = populate(name, tmp_path / str(number) / name / "second")
                    (first / "value.txt").write_text("changed")
                    (first / "new.txt").write_text("local")
                    assert (second / "value.txt").read_text() == name
                    assert set(p.name for p in second.iterdir()) == {"value.txt"}
            model_design_root = _imports_support_model_design_fixtures.root
            shared = fixtures.REPOSITORY / "framework"
            with (
                patch(
                    "support.it_workspace.populate",
                    side_effect=AssertionError("case copy"),
                ),
                patch("shutil.copytree", side_effect=AssertionError("framework copy")),
            ):
                for order in (("a", "b"), ("b", "a")):
                    cases = {}
                    for name in order:
                        directory = tmp_path / "".join(order) / name
                        directory.mkdir(parents=True)
                        case = model_design_root.__wrapped__(directory)
                        assert case == directory.resolve()
                        definition_root = _imports_utils_aws_mappings.definition_root
                        assert not (case / "framework").exists()
                        assert definition_root(case) / "framework" == shared
                        assert not (case / "model").exists()
                        (case / "model").mkdir()
                        (case / "model/value.txt").write_text(name)
                        cases[name] = case
                        assert fixtures.fingerprint(root) == before
                    (cases["a"] / "model/value.txt").write_text("changed")
                    assert (cases["b"] / "model/value.txt").read_text() == "b"
            assert fixtures.fingerprint(root) == before
        assert generations == list(fixtures.NAMES)
    assert not root.exists()
    with (
        patch.object(fixtures, "build", side_effect=build),
        pytest.raises(RuntimeError, match="modified"),
    ):
        with fixtures.bundle() as root:
            victim = root / fixtures.NAMES[0] / "value.txt"
            victim.chmod(0o600)
            victim.write_text("corrupt")
    assert not root.exists()


def check_it_inventory(tmp_path):
    discovery, errors = run_it.inventory(Path(run_it.__file__).parent)
    assert not errors, errors
    assert (
        discovery.cases[
            ("integrations/design_layout.checks.py", "check_config_firehose_references")
        ]
        == "pytest"
    )
    assert (
        discovery.cases[
            (
                "integrations/model-validation-reuse.checks.py",
                "check_sync_mapping_lifetime",
            )
        ]
        == "pytest"
    )
    assert run_it.reachability({}, [])
    assert run_it.inventory(tmp_path)[1]


def _check_it_run_lifecycle_build(root, name):
    assert "BLUEPRINT_TASK_FILE" not in os.environ
    (root / name).mkdir()
    (root / name / "seed").write_text(name)
    sys.audit("blueprint.it_fixture.generated", name)


def _callback_check_it_run_lifecycle_execute(*args):
    assert "BLUEPRINT_TASK_FILE" not in os.environ
    assert os.environ[fixtures.ENV]
    assert os.environ["BLUEPRINT_VALIDATION_CACHE_DIR"] != "previous-cache"
    return [{"suite": "example", "code": 0}], [
        {
            "version": 1,
            "suite": "integrations/example.checks.py",
            "completed": {"integrations/example.checks.py::check_one": 1},
            "collected": [],
            "passed": [],
            "metrics": {},
        }
    ]


def check_it_run_lifecycle(tmp_path):
    (tmp_path / "integrations").mkdir()
    (tmp_path / "integrations/example.checks.py").write_text(
        "if not __debug__:\n    raise SystemExit('Focused checks require assertions; run without -O')\nfrom support.it_case_receipt import it_case\n@it_case\ndef check_one():\n    assert True\ncheck_one()\n"
    )
    build = _check_it_run_lifecycle_build
    execute = _callback_check_it_run_lifecycle_execute
    with (
        patch.dict(
            os.environ,
            {
                fixtures.ENV: "previous-bundle",
                "BLUEPRINT_VALIDATION_CACHE_DIR": "previous-cache",
                "BLUEPRINT_TASK_FILE": "tasks/parent.md",
            },
        ),
        patch.object(fixtures, "build", side_effect=build),
        patch.object(run_it, "execute_suites", side_effect=execute),
    ):
        result = run_it.run_all(tmp_path, io.StringIO())
        assert result["bundle_initializations"] == 1
        assert result["seed_generations"] == dict.fromkeys(fixtures.NAMES, 1)
        assert not result["reachability_errors"]
        assert os.environ[fixtures.ENV] == "previous-bundle"
        assert os.environ["BLUEPRINT_VALIDATION_CACHE_DIR"] == "previous-cache"
        assert os.environ["BLUEPRINT_TASK_FILE"] == "tasks/parent.md"
        with (
            patch.object(fixtures, "build", side_effect=ValueError("fixture failed")),
            pytest.raises(ValueError, match="fixture failed"),
        ):
            run_it.run_all(tmp_path, io.StringIO())
        assert os.environ["BLUEPRINT_TASK_FILE"] == "tasks/parent.md"
    assert result["selection"] == "full"
    # Old baseline may lack markers; only process results are comparable.
    with patch.object(
        run_it, "execute_suites", return_value=([{"suite": "old", "code": 7}], [])
    ):
        result = run_it.run_all(tmp_path, io.StringIO(), baseline=True)
    assert result["reachability"] == "not verified (baseline)"
    assert (
        result["bundle_initializations"] is None and result["seed_generations"] is None
    )
    assert result["suites"][0]["code"] == 7


@pytest.mark.parametrize("write", [False, True])
def check_write_validator_stops_followups(tmp_path, write):
    logs = tmp_path / "logs"
    logs.mkdir()
    commands = [
        [sys.executable, "validate-blueprint.py"],
        [sys.executable, "a.checks.py"],
        ["git", "diff", "--check"],
    ]
    with (
        patch.object(MODULE.subprocess, "Popen") as popen,
        redirect_stdout(io.StringIO()),
    ):
        popen.return_value.wait.return_value = 1
        popen.return_value.pid = 123
        assert (
            MODULE.run_commands(
                tmp_path,
                commands,
                MODULE.utf8_environment(),
                logs,
                stop_after_validator_failure=write,
            )
            == 1
        )
        assert popen.call_count == (1 if write else 3)
    history = events(logs)
    assert history[-1]["status"] == "fail"
    assert any(row["event"] == "steps_skipped" for row in history) == write


def check_staged_write_rejected():
    with (
        patch.object(
            sys,
            "argv",
            [str(SCRIPT), "--mode", "task", "--write", "--staged", "--base", "HEAD"],
        ),
        pytest.raises(SystemExit) as error,
    ):
        CLI.main()
    assert error.value.code == 2


def check_regression_authorization(tmp_path):
    root = tmp_path / "repository"
    scripts = root / "framework/scripts"
    scripts.mkdir(parents=True)
    (scripts / "tests/units").mkdir(parents=True, exist_ok=True)
    runner = scripts / SCRIPT.name
    runner.write_text("# fixture\n", encoding="utf-8")
    (scripts / "tests/units/a.checks.py").write_text("# fixture\n", encoding="utf-8")
    with (
        patch.object(Path, "cwd", return_value=root),
        patch.object(MODULE, "active_scope", return_value={"framework"}),
        patch.object(MODULE, "changed_paths", return_value=set()) as changed,
        patch.object(
            MODULE,
            "authorize_full_regression",
            side_effect=ValueError("fixture locked"),
        ) as authorize,
        patch.object(MODULE, "run_commands", return_value=0) as run,
        patch.object(MODULE, "utf8_preflight"),
        redirect_stdout(io.StringIO()),
        patch.object(sys, "stderr", io.StringIO()),
    ):
        logs = tmp_path / "logs"
        for mode, paths, extra in (("full", set(), []), ("local", set(), ["--all"])):
            changed.return_value = paths
            with patch.object(
                sys,
                "argv",
                [str(runner), "--mode", mode, "--log-dir", str(logs), *extra],
            ):
                assert CLI.main() == 2
            run.assert_not_called()
        authorize.side_effect = KeyboardInterrupt()
        with patch.object(
            sys, "argv", [str(runner), "--mode", "full", "--log-dir", str(logs)]
        ):
            assert CLI.main() == 130
        run.assert_not_called()


def _callback_check_startup_diagnostics_run(
    fail, phase, real_run, /, command, *args, **kwargs
):
    if command[:3] == ["git", "config", "--get"]:
        if phase in {"git", "unexpected"}:
            fail()
        if phase == "git-exit":
            return subprocess.CompletedProcess(command, 7, "", "fixture git error")
    if phase == "utf8" and "-c" in command:
        fail()
    if "-c" in command:
        Path(command[-1]).write_text("日本語", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "日本語", "")
    return subprocess.CompletedProcess(command, 0, "", "")


def _callback_check_startup_diagnostics_fail(
    _state_check_startup_diagnostics_591, phase, /
):
    pass
    _state_check_startup_diagnostics_591.injected = True
    if phase == "unexpected":
        raise RuntimeError("unexpected fixture failure")
    error = OSError(22, "Invalid argument", "日本語-input")
    error.winerror = 87
    raise error


def _callback_check_startup_diagnostics_read(
    _state_check_startup_diagnostics_591,
    fail,
    logs,
    phase,
    real_read,
    root,
    selected,
    /,
    path,
    *args,
    **kwargs,
):
    if (
        phase == "contract"
        and path == root / selected
        and logs.exists()
        and not _state_check_startup_diagnostics_591.injected
    ):
        fail()
    return real_read(path, *args, **kwargs)


def _callback_check_startup_diagnostics_open_file(
    _state_check_startup_diagnostics_591,
    fail,
    phase,
    real_open,
    /,
    path,
    *args,
    **kwargs,
):
    if (
        not _state_check_startup_diagnostics_591.injected
        and phase == "timing"
        and path.name == "timing.jsonl"
        or phase == "diagnostic-open"
        and path.name == "startup.jsonl"
    ):
        fail()
    return real_open(path, *args, **kwargs)


class Console(io.StringIO):
    banner = False

    def __init__(self, phase, fail):
        super().__init__()
        self.phase = phase
        self.fail = fail

    def write(self, text):
        if "Local loop logs:" in text:
            self.banner = True
        if self.phase == "print" or self.phase == "banner-print" and self.banner:
            self.fail()
        return super().write(text)

    def flush(self):
        if self.phase == "flush" or self.phase == "banner-flush" and self.banner:
            self.fail()
        return super().flush()


@pytest.mark.parametrize(
    "phase",
    [
        "contract",
        "git",
        "git-exit",
        "utf8",
        "print",
        "flush",
        "banner-print",
        "banner-flush",
        "timing",
        "diagnostic-open",
        "unexpected",
    ],
)
def check_startup_diagnostics(tmp_path, phase):
    _state_check_startup_diagnostics_591 = _CallbackState()
    root = tmp_path / "repository"
    scripts = root / "framework/scripts"
    scripts.mkdir(parents=True)
    (scripts / "tests/units").mkdir(parents=True, exist_ok=True)
    runner = scripts / SCRIPT.name
    runner.write_text("# fixture\n", encoding="utf-8")
    selected, other = "tasks/first.md", "tasks/other.md"
    for name in (selected, other):
        tasks.start(
            root,
            name,
            f"## Task contract\n- Task type: `governance`\n- Task status: `running`\n"
            f"## Required changes\n- [R1] Diagnose startup\n## Acceptance checks\n- [R1] `exists:{name}`\n"
            f"## Validation scope\n- `framework`\n## Modified files\n- `{name}`\n"
            f"## Allowed paths\n- `{name}`\n",
        )
    untouched = (root / other).read_bytes()
    logs = tmp_path / "日本語 logs"
    real_read, real_open, real_run = Path.read_bytes, Path.open, subprocess.run
    _state_check_startup_diagnostics_591.injected = False

    fail = _bind_framework_callback(
        _callback_check_startup_diagnostics_fail,
        _state_check_startup_diagnostics_591,
        phase,
    )

    read = _bind_framework_callback(
        _callback_check_startup_diagnostics_read,
        _state_check_startup_diagnostics_591,
        fail,
        logs,
        phase,
        real_read,
        root,
        selected,
    )

    open_file = _bind_framework_callback(
        _callback_check_startup_diagnostics_open_file,
        _state_check_startup_diagnostics_591,
        fail,
        phase,
        real_open,
    )

    run = _bind_framework_callback(
        _callback_check_startup_diagnostics_run, fail, phase, real_run
    )

    expected = {
        "contract": ("task.contract.read", "pathlib.Path.read_bytes"),
        "git": ("git.config", "subprocess.run"),
        "git-exit": ("git.config", "subprocess.run"),
        "utf8": ("utf8.subprocess", "subprocess.run"),
        "print": ("stdout.print", "builtins.print"),
        "flush": ("stdout.flush", "sys.stdout.flush"),
        "banner-print": ("stdout.print", "builtins.print"),
        "banner-flush": ("stdout.flush", "sys.stdout.flush"),
        "timing": ("timing.open", "pathlib.Path.open"),
        "diagnostic-open": ("diagnostics.start", "pathlib.Path.open"),
        "unexpected": ("git.config", "subprocess.run"),
    }
    with (
        patch.object(Path, "cwd", return_value=root),
        patch.object(MODULE, "active_scope", return_value={"framework"}),
        patch.object(MODULE, "changed_paths", return_value=set()),
        patch.object(Path, "read_bytes", read),
        patch.object(Path, "open", open_file),
        patch.object(MODULE.subprocess, "run", side_effect=run),
        patch.object(sys, "stdout", Console(phase, fail)),
        patch.object(sys, "stderr", Console(phase, fail)),
        patch.object(
            sys,
            "argv",
            [
                str(runner),
                "--mode",
                "task",
                "--task-file",
                selected,
                "--log-dir",
                str(logs),
            ],
        ),
        patch.dict(os.environ, {tasks.SELECTOR: selected}),
    ):
        assert CLI.main() == 2
    (directory,) = logs.iterdir()
    details = json.loads((directory / "startup-error.json").read_text(encoding="utf-8"))
    assert (details["step"], details["api"]) == expected[phase], details
    assert details["cwd"] == str(root)
    assert details["location"]["line"] > 0 and details["location"]["filename"]
    assert "Traceback (most recent call last)" in details["traceback"]
    assert str(Path(MODULE.__file__)) in details["traceback"]
    if phase not in {"git-exit", "unexpected"}:
        assert details["errno"] == 22 and details["winerror"] == 87
        assert details["filename"] == "日本語-input"
    if phase in {"git", "git-exit", "unexpected"}:
        assert details["command"] == ["git", "config", "--get", "core.whitespace"]
    if phase == "git-exit":
        assert details["returncode"] == 7
    if phase == "utf8":
        assert details["command"][:3] == [sys.executable, "-X", "utf8"]
    if phase != "diagnostic-open":
        history = [
            json.loads(line)
            for line in (directory / "startup.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert history[-1]["event"] == "error"
    text = (root / selected).read_text(encoding="utf-8")
    assert (
        tasks.status(text) == "suspend"
        and str(directory / "startup-error.json") in text
    )
    assert (root / other).read_bytes() == untouched


def _snapshot_evidence_git(source, root, *args, **kwargs):
    if args[0] == "init":
        (root / ".git").mkdir()
    elif args[0] == "read-tree":
        shutil.copytree(source, root, dirs_exist_ok=True)
    return "synthetic-revision"


def _snapshot_evidence_pack(command, **kwargs):
    assert command[:2] in (["git", "pack-objects"], ["git", "index-pack"])
    return SimpleNamespace(returncode=0)


@pytest.mark.parametrize("result", [0, 1])
def check_import_snapshot_evidence(tmp_path, monkeypatch, result):
    root = tmp_path / "source"
    scripts = root / "framework/scripts"
    scripts.mkdir(parents=True)
    (root / "tasks").mkdir()
    selected = "tasks/snapshot.md"
    (root / selected).write_text(
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `import`\n## Modified files\n- `tasks/snapshot.md`\n## Allowed paths\n- `tasks/snapshot.md`\n"
    )
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", selected)
    monkeypatch.setattr(import_guard.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(import_guard, "require_import_changes", lambda root: None)
    monkeypatch.setattr(
        evidence,
        "read_proof",
        lambda root: sealed_evidence.read_sealed(root, import_guard.proof_path(root)),
    )
    # Authorization is covered by Import IT; this fixture runs the real staged copy/finally boundary.
    (scripts / "blueprint-loop.py").write_text(
        "raise SystemExit(" + str(result) + ")\n"
    )
    monkeypatch.setattr(
        MODULE, "git", _bind_framework_callback(_snapshot_evidence_git, root)
    )
    monkeypatch.setattr(MODULE, "index_tree", lambda *args: "synthetic-tree")
    monkeypatch.setattr(MODULE.subprocess, "run", _snapshot_evidence_pack)
    proof = {
        "version": 6,
        **FORMAT_FIELDS,
        "task": selected,
        "acquiredAt": datetime.now(timezone.utc).isoformat(),
    }
    sealed_evidence.write_sealed(root, import_guard.proof_path(root), proof)
    saved = import_guard.proof_path(root).read_bytes()
    directory = tmp_path / "logs"
    directory.mkdir()
    args = SimpleNamespace(
        base="HEAD",
        mode="task",
        jobs=1,
        validation_jobs=1,
        fresh=False,
        all=False,
        profile=False,
    )
    with patch.object(MODULE.subprocess, "Popen") as child:
        child.return_value.wait.return_value = result
        assert (
            MODULE.staged_snapshot(root, args, directory, MODULE.utf8_environment())
            == result
        )
        child.assert_called_once()
    snapshot = directory / "repository"
    assert not sealed_evidence.evidence_store(snapshot, create=False).exists()
    assert import_guard.proof_path(root).read_bytes() == saved
    assert not (root / ".blueprint").exists() and not (snapshot / ".blueprint").exists()
    import_evidence.discard_import_proof(root, selected)


@pytest.mark.parametrize("change", ["head", "index", "lock", "windows"])
@pytest.mark.parametrize("issue_only", [False, True])
def check_snapshot_guards(tmp_path, monkeypatch, change, issue_only):
    root = tmp_path / "source"
    root.mkdir()
    selected = "tasks/snapshot.md"
    (root / "tasks").mkdir()
    (root / selected).write_text(
        "## Task contract\n- Task type: `governance`\n- Task status: `running`\n## Modified files\n- `tasks/snapshot.md`\n## Allowed paths\n- `tasks/snapshot.md`\n"
    )
    if issue_only:
        (root / selected).write_text(
            "## Task contract\n- Task type: `migration`\n- Task status: `running`\n"
            "## Validation scope\n- `dev/cde/s3`\n## Modified files\n- `tasks/snapshot.md`\n"
            "## Allowed paths\n- `tasks/snapshot.md`\n- `issues/dev/cde/issues.md`\n"
        )
    monkeypatch.setenv(tasks.SELECTOR, selected)
    directory = tmp_path / "logs"
    directory.mkdir()
    lock = root / ".lock"
    lock.write_bytes(b"original")
    args = SimpleNamespace(
        base="HEAD",
        mode="task",
        jobs=1,
        validation_jobs=1,
        fresh=False,
        all=False,
        profile=False,
    )
    git_call = _bind_framework_callback(_snapshot_guard_git, root, change)
    with (
        patch.object(MODULE, "git", side_effect=git_call),
        patch.object(
            MODULE,
            "index_tree",
            side_effect=["tree", "changed" if change == "index" else "tree"],
        ),
        patch.object(MODULE.subprocess, "run", side_effect=_snapshot_evidence_pack),
        patch.object(MODULE.subprocess, "Popen") as child,
    ):
        child.return_value.wait.side_effect = _bind_framework_callback(
            _snapshot_guard_wait, lock, change
        )
        if change == "windows":
            with (
                patch.object(
                    MODULE, "os", SimpleNamespace(name="nt", environ=os.environ)
                ),
                pytest.raises(ValueError, match="current runner and regression guard"),
            ):
                MODULE.staged_snapshot(root, args, directory, {})
            child.assert_not_called()
        else:
            assert MODULE.staged_snapshot(root, args, directory, {}) == (
                0 if issue_only else 1
            )
            metadata = json.loads((directory / "snapshot.json").read_text())
            assert (
                ("source_unchanged" not in metadata)
                if issue_only
                else metadata["source_unchanged"] is False
            )


def _snapshot_guard_git(source, change, root, *args, **kwargs):
    if args == ("rev-parse", "HEAD"):
        return (
            "changed" if change == "head" and (root / "finished").exists() else "head"
        )
    return _snapshot_evidence_git(source, root, *args, **kwargs)


def _snapshot_guard_wait(lock, change):
    if change == "lock":
        lock.write_bytes(b"finished")
    elif change == "head":
        lock.with_name("finished").touch()
    return 0


def check_log_directory_rejected(tmp_path):
    with (
        patch.object(Path, "cwd", return_value=tmp_path),
        patch.object(MODULE, "active_scope", return_value={"framework"}),
        patch.object(MODULE, "changed_paths", return_value=set()),
        patch.object(MODULE, "run_commands") as dispatch,
        patch.object(
            sys,
            "argv",
            [str(SCRIPT), "--mode", "task", "--log-dir", str(tmp_path / "logs")],
        ),
    ):
        with pytest.raises(ValueError, match="outside the repository"):
            CLI.main()
    dispatch.assert_not_called()


def issues_save_contract(root):
    name = "tasks/issues-save.md"
    reports = ["issues/dev/cde/" + file for file in ("issues.md", "iac-issues.md")]
    paths = "".join(f"- `{path}`\n" for path in [name, *reports])
    text = (
        "## Task contract\n- Task type: `migration`\n- Task status: `running`\n"
        "## Goal\nSave reviewed issues.\n"
        "## Validation scope\n- `dev/cde/s3`\n"
        "## Required changes\n- [R1] Save both reports.\n"
        "## Acceptance checks\n"
        + "".join(f"- [R1] `exists:{path}`\n" for path in reports)
        + "## Allowed paths\n"
        + paths
        + "## Modified files\n"
        + paths
    )
    tasks.start(root, name, text)
    for path in reports:
        write(root / path, "# Issues\nModel violation remains recorded.\n")
    return name


def issue_validation_options(name):
    return SimpleNamespace(
        task_file=name,
        write=False,
        all=False,
        fresh=False,
        jobs=1,
        repository_wide_iac=False,
        contract_scope=False,
    )


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "missing-report",
        "acceptance",
        "required",
        "modified",
        "allowed",
        "status",
        "symlink",
        "access",
    ],
)
def check_issue_save_validator_contract_only(tmp_path, invalid):
    name = issues_save_contract(tmp_path)
    contract = tmp_path / name
    if invalid == "missing-report":
        (tmp_path / "issues/dev/cde/iac-issues.md").unlink()
    elif invalid == "acceptance":
        contract.write_text(
            contract.read_text().replace(
                "- [R1] `exists:issues/dev/cde/iac-issues.md`\n", ""
            ),
            encoding="utf-8",
        )
    elif invalid == "required":
        contract.write_text(
            contract.read_text().replace("[R1] Save both reports.", "invalid"),
            encoding="utf-8",
        )
    elif invalid in {"modified", "allowed"}:
        heading = "## Modified files" if invalid == "modified" else "## Allowed paths"
        text = contract.read_text()
        before, after = text.split(heading)
        after = after.replace("- `issues/dev/cde/iac-issues.md`\n", "")
        contract.write_text(before + heading + after, encoding="utf-8")
    elif invalid == "symlink":
        report = tmp_path / "issues/dev/cde/iac-issues.md"
        report.unlink()
        report.symlink_to(tmp_path / "issues/dev/cde/issues.md")
    elif invalid == "access":
        (tmp_path / "issues/dev/cde/iac-issues.md").write_bytes(b"invalid UTF-8: \xff")
    elif invalid == "status":
        contract.write_text(
            contract.read_text().replace("`running`", "`completed`"), encoding="utf-8"
        )
    with ExitStack() as stack:
        for method in (
            "check_structure",
            "check_validation_scope",
            "check_model_files",
            "check_scoped_designs",
            "check_iac_selection",
            "check_catalog",
        ):
            stack.enter_context(
                patch.object(
                    validation_runner.Validator,
                    method,
                    side_effect=AssertionError("ordinary validation must not run"),
                )
            )
        stack.enter_context(
            patch.object(
                validation_runner._imports_deploy_inputs,
                "task_deployment_input_paths",
                side_effect=AssertionError("IaC discovery must not run"),
            )
        )
        stack.enter_context(
            patch.object(
                validation_runner._dependency_validation_task,
                "collect_working_paths",
                side_effect=AssertionError("Git discovery must not run"),
            )
        )
        try:
            result = validation_runner.run_validation(
                tmp_path,
                issue_validation_options(name),
                issues_save=True,
            )
        except ValueError:
            assert invalid in {"allowed", "modified", "symlink"}
        else:
            assert result.findings.status == ("PASS" if invalid is None else "FAIL"), (
                result.errors
            )


@pytest.mark.parametrize(
    "mode,write,all_,staged,expected",
    [
        ("local", False, False, False, True),
        ("task", False, False, False, False),
        ("full", False, False, False, False),
        ("local", True, False, False, False),
        ("local", False, True, False, False),
        ("local", False, False, True, False),
    ],
)
def check_issue_save_loop_option(tmp_path, mode, write, all_, staged, expected):
    name = issues_save_contract(tmp_path)
    args = SimpleNamespace(
        mode=mode,
        write=write,
        all=all_,
        staged=staged,
        fresh=False,
        validation_jobs=1,
        profile=False,
    )
    validation = Mock()
    with tasks.selected_task(tmp_path, name):
        MODULE._callback__run_loop_validation_call(
            args,
            tmp_path,
            None,
            all_,
            tmp_path,
            validation,
            {("dev", "cde", "s3")},
            name,
        )
    assert validation.call_args.kwargs["issues_save"] is expected


def check_issue_save_loop_runs_contract_validator(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    name = issues_save_contract(root)
    # Deliberately invalid authority: saving its diagnosis must still pass.
    write(root / "model/dev/cde/s3.properties", "invalid Model")
    with (
        patch.object(Path, "cwd", return_value=root),
        patch.object(
            MODULE, "changed_paths", side_effect=AssertionError("Git changes forbidden")
        ),
        patch.object(MODULE, "utf8_preflight"),
        patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ),
        patch.object(
            sys,
            "argv",
            [
                "blueprint-loop.py",
                "--mode",
                "local",
                "--task-file",
                name,
                "--log-dir",
                str(tmp_path / "logs"),
            ],
        ),
    ):
        assert CLI.main() == 0


def check_ordinary_validator_keeps_full_path(tmp_path):
    name = issues_save_contract(tmp_path)
    with patch.object(validation_runner.Validator, "_run", return_value=0) as ordinary:
        result = validation_runner.run_validation(
            tmp_path, issue_validation_options(name)
        )
    ordinary.assert_called_once()
    assert not result.issues_save


def check_parallel_repair_receipts():
    receipts = [
        {
            "version": 1,
            "suite": run_it.REPAIR_SUITE,
            "completed": {},
            "collected": [case],
            "passed": [case],
            "metrics": {"subprocess.Popen": 1},
        }
        for case in run_it.REPAIR_CASES
    ]
    combined = run_it.repair_receipt(receipts)
    assert combined["collected"] == combined["passed"] == list(run_it.REPAIR_CASES)
    TestCase().assertEqual(
        combined["metrics"], {"subprocess.Popen": len(run_it.REPAIR_CASES)}
    )
    cases = run_it.inventory(Path(run_it.__file__).parent)[0].cases
    selected = {
        key: value for key, value in cases.items() if key[0] == run_it.REPAIR_SUITE
    }
    assert not run_it.reachability(selected, [combined], cases)
    with pytest.raises(ValueError, match="missing"):
        run_it.repair_receipt(receipts[:-1])
    duplicate = [{**receipts[0], "passed": []}]
    with pytest.raises(ValueError, match="incorrect"):
        run_it.repair_receipt(duplicate)
    invalid = [{**receipts[0], "suite": "other"}]
    with pytest.raises(ValueError, match="suite"):
        run_it.repair_receipt(invalid)
    checkpoint = [
        {
            "version": 1,
            "suite": run_it.CHECKPOINT_SUITE,
            "completed": {},
            "collected": [case],
            "passed": [case],
            "metrics": {},
        }
        for case in run_it.CHECKPOINT_CASES
    ]
    combined = run_it.repair_receipt(
        checkpoint, run_it.CHECKPOINT_SUITE, run_it.CHECKPOINT_CASES
    )
    if combined["passed"] != list(run_it.CHECKPOINT_CASES):
        raise ValueError("checkpoint case receipts were not aggregated")
    with pytest.raises(ValueError, match="missing"):
        run_it.repair_receipt(
            checkpoint[:-1], run_it.CHECKPOINT_SUITE, run_it.CHECKPOINT_CASES
        )


def check_parallel_repair_selection(tmp_path):
    plugin = run_it.PytestReceipt(tmp_path, "unknown")
    plugin.rootpath = tmp_path
    items = [SimpleNamespace(nodeid=case) for case in run_it.CHECKPOINT_CASES]
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    with pytest.raises(ValueError, match="unknown"):
        plugin.pytest_collection_modifyitems(None, config, items)
    plugin.case_id = run_it.CHECKPOINT_CASES[1]
    plugin.pytest_collection_modifyitems(None, config, items)
    assert [item.nodeid for item in items] == [plugin.case_id]
    assert len(config.hook.pytest_deselected.call_args.kwargs["items"]) == 1
    with pytest.raises(ValueError, match="collection mismatch"):
        plugin.pytest_collection_modifyitems(None, config, items)


def _callback_parallel_receipt(state, command, **kwargs):
    receipt = Path(command[command.index("--receipt") + 1])
    case = command[command.index("--case-id") + 1]
    if state.mode == "fresh":
        receipt.write_text(
            json.dumps(
                {
                    "version": 1,
                    "suite": state.suite,
                    "completed": {},
                    "collected": [case],
                    "passed": [case],
                    "metrics": {},
                }
            ),
            encoding="utf-8",
        )
    elif state.mode == "corrupt":
        receipt.write_text("{", encoding="utf-8")
    return state.processes.pop(0)


def _callback_checkpoint_wait(state, **kwargs):
    state.running -= 1
    return 0


def _callback_checkpoint_bounded_launch(state, command, **kwargs):
    state.running += 1
    if state.running > 2:
        raise ValueError("checkpoint exceeded two concurrent children")
    return _callback_parallel_receipt(state, command, **kwargs)


def check_checkpoint_keeps_two_process_limit(tmp_path):
    tests = Path(run_it.__file__).parent
    suite = run_it.CHECKPOINT_SUITE
    cases = tuple(suite + f"::check_case_{number}" for number in range(4))
    processes = [Mock() for _ in cases]
    state = _CallbackState(
        mode="fresh", suite=suite, processes=processes.copy(), running=0
    )
    for process in processes:
        process.poll.return_value = 0
        process.wait.side_effect = _bind_framework_callback(
            _callback_checkpoint_wait, state
        )
    launch = _bind_framework_callback(_callback_checkpoint_bounded_launch, state)
    logs = tmp_path / "logs"
    logs.mkdir()
    with (
        patch.dict(run_it.PARALLEL_CASES, {suite: cases}),
        patch.object(
            run_it,
            "inventory",
            return_value=(
                SimpleNamespace(
                    cases={(suite, case.split("::")[1]): "pytest" for case in cases}
                ),
                [],
            ),
        ),
        patch.object(run_it.subprocess, "Popen", side_effect=launch),
        patch.object(run_it.tempfile, "mkdtemp", return_value=str(logs)),
    ):
        run_it.run_parallel_repair(tests / suite, tests, tmp_path)
    if sorted(path.name for path in logs.glob("case-*.log")) != [
        f"case-{index}.log" for index in range(len(cases))
    ]:
        raise ValueError("checkpoint case logs were not retained")


@pytest.mark.parametrize("suite", [run_it.REPAIR_SUITE, run_it.CHECKPOINT_SUITE])
@pytest.mark.parametrize("mode", ["stale", "fresh", "corrupt"])
def check_parallel_repair_receipt_freshness(tmp_path, mode, suite):
    tests = Path(run_it.__file__).parent
    cases = run_it.PARALLEL_CASES[suite]
    for index, case in enumerate(cases):
        (tmp_path / f"repair-{index}.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "suite": suite,
                    "completed": {},
                    "collected": [case],
                    "passed": [case],
                    "metrics": {},
                }
            ),
            encoding="utf-8",
        )
    processes = [Mock() for _ in cases]
    for process in processes:
        process.wait.return_value = 0
        process.poll.return_value = 0
    state = _CallbackState(mode=mode, suite=suite, processes=processes)
    launch = _bind_framework_callback(_callback_parallel_receipt, state)
    with patch.object(run_it.subprocess, "Popen", side_effect=launch):
        if mode == "fresh":
            result = run_it.run_parallel_repair(tests / state.suite, tests, tmp_path)
            assert result["passed"] == list(cases)
        else:
            with pytest.raises(ValueError, match="missing/invalid receipt"):
                run_it.run_parallel_repair(tests / state.suite, tests, tmp_path)


@pytest.mark.parametrize(
    "suite,limit", [(run_it.REPAIR_SUITE, 300), (run_it.CHECKPOINT_SUITE, 1800)]
)
def check_parallel_suite_shared_deadline(tmp_path, suite, limit):
    tests = Path(run_it.__file__).parent
    cases = run_it.PARALLEL_CASES[suite]
    processes = [Mock() for _ in cases]
    for process in processes:
        process.wait.return_value = 0
        process.poll.return_value = 0
    state = _CallbackState(mode="fresh", suite=suite, processes=processes.copy())
    launch = _bind_framework_callback(_callback_parallel_receipt, state)
    clock = iter([100, *range(101, 120)])
    with (
        patch.object(run_it.subprocess, "Popen", side_effect=launch),
        patch.object(run_it.time, "monotonic", side_effect=clock),
    ):
        run_it.run_parallel_repair(tests / suite, tests, tmp_path)
    waits = [
        call.kwargs["timeout"]
        for process in processes
        for call in process.wait.call_args_list
        if call.kwargs["timeout"] != 5
    ]
    assert sorted(waits, reverse=True) == list(
        range(limit - 1, limit - len(waits) - 1, -1)
    )
    if suite == run_it.REPAIR_SUITE:
        assert limit < 20 * 60


def check_parallel_repair_expired_deadline(tmp_path):
    tests = Path(run_it.__file__).parent
    processes = [Mock(pid=100 + i) for i in range(len(run_it.REPAIR_CASES))]
    for process in processes:
        process.wait.return_value = 0
        process.poll.return_value = None
    state = _CallbackState(
        mode="fresh", suite=run_it.REPAIR_SUITE, processes=processes.copy()
    )
    launch = _bind_framework_callback(_callback_parallel_receipt, state)
    logs = tmp_path / "logs"
    logs.mkdir()
    with (
        patch.object(run_it.subprocess, "Popen", side_effect=launch),
        patch.object(
            run_it.time, "monotonic", side_effect=[100, 2000, 2000, 2000, 2000]
        ),
        patch.object(run_it.os, "killpg", create=True) as kill,
        patch.object(run_it.tempfile, "mkdtemp", return_value=str(logs)),
        pytest.raises(RuntimeError, match="timed out"),
    ):
        run_it.run_parallel_repair(tests / run_it.REPAIR_SUITE, tests, tmp_path)
    if os.name == "nt":
        assert all(process.terminate.called for process in processes)
    else:
        TestCase().assertEqual(kill.call_count, len(processes))
    TestCase().assertTrue(
        all(
            ((logs / f"case-{i}.log").exists() for i in range(len(run_it.REPAIR_CASES)))
        )
    )


@pytest.mark.parametrize(
    "failure", ["spawn", "exit", "interrupt", "timeout", "missing", "corrupt"]
)
def check_parallel_repair_failure_cleanup(tmp_path, failure):
    suite = run_it.CHECKPOINT_SUITE
    tests = Path(run_it.__file__).parent
    cases = run_it.PARALLEL_CASES[suite]
    processes = [Mock(pid=100 + i) for i in range(len(cases))]
    for process in processes:
        process.poll.return_value = None
        process.wait.return_value = 0
    if failure == "exit":
        processes[0].wait.side_effect = [1, 1]
    elif failure == "interrupt":
        processes[0].wait.side_effect = [KeyboardInterrupt(), 0]
    elif failure == "timeout":
        processes[0].wait.side_effect = [subprocess.TimeoutExpired("case", 1), 0]
    launched = (
        [processes[0], OSError("spawn failed")] if failure == "spawn" else processes
    )
    if failure == "corrupt":
        state = _CallbackState(mode="corrupt", suite=suite, processes=processes.copy())
        launched = _bind_framework_callback(_callback_parallel_receipt, state)
    expected = (
        KeyboardInterrupt
        if failure == "interrupt"
        else (OSError, RuntimeError, ValueError)
    )
    with (
        patch.object(run_it.subprocess, "Popen", side_effect=launched) as launch,
        patch.object(run_it.os, "killpg", create=True) as kill,
        patch.object(run_it.tempfile, "mkdtemp", return_value=str(tmp_path / "logs")),
    ):
        (tmp_path / "logs").mkdir()
        with pytest.raises(expected):
            run_it.run_parallel_repair(tests / suite, tests, tmp_path)
        count = (
            1
            if failure == "spawn"
            else 2
            if failure in ("exit", "interrupt", "timeout")
            else len(cases)
        )
        TestCase().assertEqual(launch.call_count, 2 if failure == "spawn" else count)
        if os.name == "nt":
            assert all(process.terminate.called for process in processes[:count])
        else:
            assert kill.call_count == count
        assert all(process.wait.called for process in processes[:count])
        assert all((tmp_path / "logs" / f"case-{i}.log").exists() for i in range(count))


def check_parallel_repair_dispatch(tmp_path):
    tests = tmp_path / "framework/scripts/tests"
    integrations = tests / "integrations"
    integrations.mkdir(parents=True)
    (integrations / "worktree-deploy-repair.checks.py").touch()
    (integrations / "other.checks.py").touch()
    output = tmp_path / "receipts"
    output.mkdir()
    receipt = {
        "version": 1,
        "suite": run_it.REPAIR_SUITE,
        "completed": {},
        "collected": list(run_it.REPAIR_CASES),
        "passed": list(run_it.REPAIR_CASES),
        "metrics": {},
    }
    state = _CallbackState()
    state.codes = [0, 0, 0]
    execute = _bind_framework_callback(_callback_check_ci_workflow_execute, state)
    with (
        patch.object(run_it, "run_parallel_repair", return_value=receipt) as parallel,
        patch.object(run_it.subprocess, "run", side_effect=execute) as launch,
    ):
        rows, receipts = run_it.execute_suites(tests, output, io.StringIO())
        assert all(row["code"] == 0 for row in rows)
        assert len(receipts) == 2 and parallel.call_count == launch.call_count == 1
        rows, receipts = run_it.execute_suites(
            tests, output, io.StringIO(), baseline=True
        )
        assert all(row["code"] == 0 for row in rows)
        assert parallel.call_count == 1 and launch.call_count == 3
        assert all("--baseline" in call.args[0] for call in launch.call_args_list[1:])


def check_unit_timing_parallel_receipts_and_summary(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    source_conftest = Path(run_it.__file__).parent / "conftest.py"
    (tests / "conftest.py").write_text(
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('timing_fixture', {str(source_conftest)!r})\n"
        "fixture = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(fixture)\n"
        "def pytest_configure(config):\n"
        "    config.pluginmanager.register(fixture.UnitTiming(config))\n",
        encoding="utf-8",
    )
    (tests / "pytest.ini").write_text(
        "[pytest]\npython_functions = check_* test_*\naddopts = --import-mode=importlib\n",
        encoding="utf-8",
    )
    support = str(Path(run_it.__file__).parent)
    entry = (
        "import sys\n"
        f"sys.path.insert(0, {support!r})\n"
        "from support.pytest_cli import run\n"
        "PYTEST_GROUP_SAFE = True\n"
    )
    grouped = []
    for name in ("a", "b"):
        path = tests / f"{name}.checks.py"
        path.write_text(
            entry
            + "import pytest\n"
            + "@pytest.mark.parametrize('value', [0, 1])\n"
            + "def check_case(value): assert value >= 0\n"
            + "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
            encoding="utf-8",
        )
        grouped.append(path)
    isolated = tests / "isolated.checks.py"
    isolated.write_text(
        entry
        + "import pytest\n"
        + "def check_fail(): assert False\n"
        + "def check_skip(): pytest.skip('reason')\n"
        + "if __name__ == '__main__': raise SystemExit(run(__file__))\n",
        encoding="utf-8",
    )
    direct = tests / "direct.checks.py"
    direct.write_text("assert True\n", encoding="utf-8")
    commands = unit_commands([*grouped, isolated, direct])
    environment = MODULE.utf8_environment()
    environment["BLUEPRINT_UT_TIMING_DIR"] = str(tmp_path)
    assert MODULE.run_commands(tmp_path, commands, environment, tmp_path, jobs=2) == 1
    timing = run_it.unit_timing(tmp_path, commands, 4.5)
    assert not timing["errors"]
    assert len(timing["cases"]) == 6
    assert {case["status"] for case in timing["cases"]} == {"PASS", "FAIL", "SKIP"}
    assert any("[0]" in case["nodeid"] for case in timing["cases"])
    assert all({"setup", "teardown"} <= set(case["phases"]) for case in timing["cases"])
    assert (
        next(row for row in timing["files"] if row["path"] == str(direct))["process"]
        is not None
    )
    summary = io.StringIO()
    run_it.display_unit_timing(timing, summary)
    assert "UT total wall time: 4.500s" in summary.getvalue()
    assert "Slowest UT Cases" in summary.getvalue()
    assert "All UT cases" in summary.getvalue()
    receipt = next(tmp_path.glob("pytest-*.json"))
    receipt.write_text("invalid", encoding="utf-8")
    assert run_it.unit_timing(tmp_path, commands, 4.5)["errors"]


if __name__ == "__main__":
    raise SystemExit(pytest_run(__file__))
