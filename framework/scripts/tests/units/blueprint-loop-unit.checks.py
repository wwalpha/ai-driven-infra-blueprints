#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import shutil
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as _CallbackState
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import import_guard
import run_it
import support.model_design_fixtures as _imports_support_model_design_fixtures
import utils.aws_mappings as _imports_utils_aws_mappings
import yaml
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
from support.pytest_cli import run as pytest_run
from support.validator import MODULE as validator
from support.validator import project, schema_validator, write
from utils import sealed_evidence
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.git_changes import GitWorkingPaths
from validation import runner as validation_runner

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_utf8_restart():
    entrypoint = SCRIPT.read_text(encoding="utf-8").split(
        'if __name__ == "__main__":', 1
    )[1]
    for code in (0, 2, 7, 130):
        namespace = {
            **MODULE.__dict__,
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


def check_ci_workflow(tmp_path):
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

    workflow = yaml.safe_load(
        (SCRIPT.parents[2] / ".github/workflows/framework-it.yml").read_text()
    )
    events = workflow[True]  # PyYAML's YAML 1.1 resolver reads the key 'on' as True.
    assert set(events) == {"pull_request", "push", "workflow_dispatch"}
    assert events["pull_request"] is None and events["push"] == {
        "branches": ["main", "master"]
    }
    step = workflow["jobs"]["framework-it"]["steps"][-1]
    assert (
        step["run"]
        == 'python -B framework/scripts/tests/run_it.py --baseline-root "$IT_BASELINE"'
    )
    assert set(step["env"]) == {"IT_BASELINE"}

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


def check_it_reachability(tmp_path):
    tests = tmp_path / "framework/scripts/tests"
    (tests / "integrations").mkdir(parents=True)
    suite = tests / "integrations/receipt.checks.py"
    suite.write_text("""import pytest
from support.pytest_cli import run
@pytest.mark.parametrize('value', [False, True])
def check_body(value):
    assert type(value) is bool

def check_not_called():
    raise AssertionError('must be detected as unreachable')

if __name__ == '__main__':
    raise SystemExit(run(__file__, ['check_body']))
""")
    (tests / "pytest.ini").write_text(
        "[pytest]\npython_functions = check_*\naddopts = --import-mode=importlib -p no:cacheprovider\n"
    )
    receipt = tmp_path / "receipt.json"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(run_it.__file__)),
            "--suite",
            str(suite),
            "--tests",
            str(tests),
            "--receipt",
            str(receipt),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(receipt.read_text())
    cases = {("integrations/receipt.checks.py", "check_body"): ("pytest", 2)}
    assert not run_it.reachability(cases, [data])
    assert len(data["passed"]) == 2
    assert "calls" not in data
    helper = ("integrations/helper.py", "check_helper")
    with_helper = {**data, "completed": {"::".join(helper): 1}}
    assert run_it.reachability(cases, [with_helper])
    assert not run_it.reachability(
        cases, [with_helper], {**cases, helper: ("direct", 1)}
    )
    assert run_it.reachability(
        cases, [{**with_helper, "passed": []}], {**cases, helper: ("direct", 1)}
    )
    assert run_it.reachability(cases, [{**data, "passed": data["passed"][:1]}])
    assert run_it.reachability(cases, [{**data, "passed": [data["passed"][0]] * 2}])
    cases[("integrations/receipt.checks.py", "check_not_called")] = ("direct", 1)
    assert "verification did not complete" in run_it.reachability(cases, [data])[0]
    cases[("integrations/receipt.checks.py", "check_body")] = ("pytest", 3)
    assert (
        "expected 3, collected 2, passed body 2"
        in run_it.reachability(cases, [data])[0]
    )
    assert run_it.reachability(cases, [{**data, "passed": []}])

    output = tmp_path / "receipts"
    output.mkdir()
    rows, receipts = run_it.execute_suites(tests, output, io.StringIO())
    assert [row["code"] for row in rows] == [0]
    assert not run_it.reachability(
        {("integrations/receipt.checks.py", "check_body"): ("pytest", 2)}, receipts
    )
    assert run_it.reachability(
        cases, receipts
    )  # Full execution still detects an unreachable registered body.
    assert all(receipt["metrics"].get("subprocess.git", 0) == 0 for receipt in receipts)

    suite.write_text(
        f"import sys\nsys.path.insert(0, {str(Path(run_it.__file__).parent.parent)!r})\n"
        + """from support.it_case_receipt import it_case, module_complete
from unittest.mock import patch
from utils.input_cache import input_scope
import inspect
@it_case
@input_scope
@patch.object(inspect, 'ismodule', return_value=True)
def check_direct(mock, value=3):
    assert inspect.ismodule(None)
    return value
@it_case
def check_failure():
    raise ValueError('expected')
assert str(inspect.signature(check_direct)) == '(mock, value=3)'
assert check_direct.__name__ == 'check_direct'
assert check_direct() == check_direct() == 3
try:
    check_failure()
except ValueError:
    pass
module_complete(__file__)
"""
    )
    command = [
        sys.executable,
        "-B",
        str(Path(run_it.__file__)),
        "--suite",
        str(suite),
        "--tests",
        str(tests),
        "--receipt",
        str(receipt),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(receipt.read_text())
    direct = ("integrations/receipt.checks.py", "check_direct")
    module = ("integrations/receipt.checks.py", "__module__")
    cases = {direct: ("direct", 1), module: ("module", 1)}
    assert data["completed"] == {"::".join(direct): 2, "::".join(module): 1}
    assert not run_it.reachability(cases, [data])
    assert run_it.reachability(
        {**cases, (direct[0], "check_failure"): ("direct", 1)}, [data]
    )
    assert run_it.reachability(cases, [{**data, "completed": {"::".join(direct): 2}}])
    for invalid in (
        None,
        {},
        {**data, "completed": []},
        {**data, "metrics": {"bad": False}},
    ):
        assert run_it.reachability(cases, [invalid])
    assert run_it.reachability(cases, [])
    suite.write_text(
        suite.read_text().replace(
            "module_complete(__file__)", "raise RuntimeError('before completion')"
        )
    )
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert run_it.reachability(cases, [json.loads(receipt.read_text())])


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
    result = subprocess.run(
        [sys.executable, "-O", run_it.__file__], capture_output=True, text=True
    )
    assert (
        result.returncode != 0 and "Focused checks require assertions" in result.stderr
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
                    subprocess.run(["git", "init", "-q", str(cases["a"])], check=True)
                    subprocess.run(["git", "add", "."], cwd=cases["a"], check=True)
                    tracked = subprocess.run(
                        ["git", "ls-files", "--stage"],
                        cwd=cases["a"],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout
                    assert not any(
                        line.endswith("\tframework") for line in tracked.splitlines()
                    )
                    assert "framework/rules/task-contract.md" not in tracked
                    assert "\tmodel/value.txt" in tracked
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
    cases, errors = run_it.inventory(Path(run_it.__file__).parent)
    assert not errors, errors
    assert cases[
        ("integrations/design_layout.checks.py", "check_config_firehose_references")
    ] == ("pytest", 1)
    assert cases[
        ("integrations/sync-model.checks.py", "check_incoming_reference_models")
    ] == ("pytest", 1)
    assert cases[
        ("integrations/model-validation-reuse.checks.py", "check_sync_mapping_lifetime")
    ] == ("pytest", 4)
    row = "| `origin` | `check_one` | IT | [case](integrations/example.py) | direct / 1 |\n"
    (tmp_path / "CASES.md").write_text(row + row)
    with pytest.raises(ValueError, match="duplicate"):
        run_it.registered_cases(tmp_path)
    assert run_it.reachability({}, [])
    folder = tmp_path / "integrations"
    folder.mkdir()
    entry = folder / "example.checks.py"
    row = row.replace("example.py", "example.checks.py")
    (tmp_path / "CASES.md").write_text(row)
    entry.write_text("def check_one():\n    pass\n")
    assert any("decorator" in error for error in run_it.inventory(tmp_path)[1])
    entry.write_text(
        "from support.it_case_receipt import it_case\n@it_case\ndef check_one():\n    pass\n"
    )
    assert not run_it.inventory(tmp_path)[1]
    entry.write_text("pass\n")
    assert any("missing IT case" in error for error in run_it.inventory(tmp_path)[1])
    (folder / "unregistered.checks.py").write_text("pass\n")
    assert any(
        "unregistered IT suite" in error for error in run_it.inventory(tmp_path)[1]
    )
    (folder / "unregistered.checks.py").unlink()
    (tmp_path / "CASES.md").write_text(
        row.replace("check_one", "__module__").replace("direct /", "module /")
    )
    entry.write_text(
        "from support.it_case_receipt import module_complete\nmodule_complete(__file__)\n"
    )
    assert not run_it.inventory(tmp_path)[1]
    entry.write_text(entry.read_text() + "assert True\n")
    assert any("terminal module" in error for error in run_it.inventory(tmp_path)[1])


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
        "if not __debug__:\n    raise SystemExit('Focused checks require assertions; run without -O')\nfrom support.it_case_receipt import it_case\n@it_case\ndef check_one():\n    assert True\n"
    )
    (tmp_path / "CASES.md").write_text(
        "| `origin` | `check_one` | IT | [case](integrations/example.checks.py) | direct / 1 |\n"
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
    # Old baseline may have neither ledger nor markers; only process results are comparable.
    (tmp_path / "CASES.md").unlink()
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
    import_guard.discard_import_proof(root, selected)


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


if __name__ == "__main__":
    raise SystemExit(pytest_run(__file__))
