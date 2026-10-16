#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.blueprint_loop_fixtures import *

def check_utf8_restart():
    entrypoint = SCRIPT.read_text(encoding="utf-8").split('if __name__ == "__main__":', 1)[1]
    for code in (0, 2, 7, 130):
        namespace = {**MODULE.__dict__, "sys": SimpleNamespace(flags=SimpleNamespace(utf8_mode=0),
                     platform="win32", executable=sys.executable, argv=[str(SCRIPT), "--mode", "task"])}
        with patch.object(MODULE.subprocess, "call", return_value=code) as child, \
             patch.object(MODULE.signal, "signal"), pytest.raises(SystemExit) as result:
            exec(compile("if True:" + entrypoint, str(SCRIPT), "exec"), namespace)
        assert result.value.code == code
        assert child.call_args.args[0][:3] == [sys.executable, "-X", "utf8"]



def check_changed_paths_error(tmp_path):
    root = tmp_path
    with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "failure")):
        with pytest.raises(ValueError):
            MODULE.changed_paths(root)



def check_process_interruption(tmp_path):
    root = tmp_path
    logs = root / 'logs'
    logs.mkdir()
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    command = [sys.executable, str(root / 'slow.py')]
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



def check_parallel_interruption(tmp_path):
    root = tmp_path
    logs = root / 'logs'
    logs.mkdir()
    commands = [[sys.executable, 'a.checks.py'], [sys.executable, 'test_b.py']]
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



def check_leaf_selection(tmp_path):
    root = tmp_path
    scripts = root / 'framework/scripts/tests/units'
    scripts.mkdir(parents=True)
    for name in ('a', 'b'):
        (scripts / (name + '.checks.py')).write_text('# selection fixture\n', encoding='utf-8')
    paths = {"framework/scripts/tests/units/a.checks.py"}
    integration = scripts.parent / "integrations/only.checks.py"
    integration.parent.mkdir()
    integration.write_text("raise AssertionError('IT must not run locally')\n", encoding="utf-8")
    assert MODULE.select_checks(root, {integration.relative_to(root).as_posix()}, True)[0] == []
    selected, reason = MODULE.select_checks(root, paths, True)
    assert [path.name for path in selected] == ["a.checks.py"]
    for unknown in ("framework/scripts/shared.py", "framework/rules/rule.md",
                    "framework/scripts/tests/integrations/deleted.checks.py", "framework/materials/catalog.sha256"):
        selected, reason = MODULE.select_checks(root, paths | {unknown}, True)
        assert len(selected) == 2 and "unknown dependency" in reason
    assert len(MODULE.select_checks(root, paths, False)[0]) == 2
    assert not MODULE.select_checks(root, {"model/dev/cde/ec2.properties"}, True)[0]



def check_dependency_selection():
    root = SCRIPT.parents[2]
    def selected(*paths, affected=True):
        return {p.name for p in MODULE.select_checks(root, set(paths), affected)[0]}
    validator = {'validation-units.checks.py'}
    shared = validator | {'blueprint-loop-unit.checks.py'}
    for category, name in (("integrations", "task"), ("units", "design"), ("units", "references"),
                           ("units", "cloudformation"), ("integrations", "scope"), ("units", "contracts")):
        assert selected(f"framework/scripts/tests/{category}/validation_checks/{name}.py") == validator, name
    leaf = "framework/scripts/tests/integrations/validation_checks/task.py"
    assert selected(leaf, "framework/scripts/blueprint-loop.py") == shared
    comparison = {'comparison_core-unit.checks.py', 'issues_scan-unit.checks.py', 'check-model-aws-unit.checks.py', 'cloudformation-deploy-unit.checks.py', 'deploy_preparation-unit.checks.py', 'model_files-unit.checks.py'}
    assert selected("framework/scripts/comparison_rows.py") == comparison
    for name in ("iac_evaluation", "script_loader", "issues_iac"):
        assert selected(f"framework/scripts/{name}.py") == (comparison - {'check-model-aws-unit.checks.py'}) | ({'test_issues_iac.py'} if name == 'issues_iac' else set())
    for name in ("__init__", "scheduler", "aws_adapter", "delivery", "change_sets", "repair", "secret_bootstrap", "session"):
        assert selected(f"framework/scripts/deployment/{name}.py") == {'cloudformation-deploy-unit.checks.py', 'deploy_preparation-unit.checks.py', 'model_files-unit.checks.py'}
    all_checks = {p.name for p in (SCRIPT.parent / "tests/units").rglob("*.checks.py")} | {"test_issues_iac.py"}
    assert selected("framework/scripts/iac_values.py") == all_checks
    for unknown in ("framework/scripts/tests/support/validation_checks/unknown.py", "framework/scripts/tests/support/unknown.py"):
        assert selected(leaf, unknown) == all_checks
    with patch.object(Path, "is_file", return_value=False):
        assert selected(leaf) == all_checks  # Known path removed/renamed without a resolvable source.
    assert selected("framework/scripts/tests/support/validator.py") == all_checks
    assert selected("framework/scripts/tests/integrations/model_design.checks.py") == all_checks
    assert selected("framework/scripts/tests/integrations/rotation_schedule.checks.py") == {'cloudformation-deploy-unit.checks.py'}
    for name in ("service_rows", "model_display", "model_projection", "model_references", "sync_runtime", "sync_views", "sync_files"):
        assert selected(f"framework/scripts/{name}.py") == all_checks
    assert selected("framework/scripts/model_core.py") == all_checks
    assert selected("framework/scripts/ec2_display.py") == all_checks
    assert selected(leaf, affected=False) == all_checks
    assert selected("framework/scripts/tests/integrations/design_layout.checks.py") == {'design_layout-unit.checks.py', 'design_document-unit.checks.py', 'validation-units.checks.py', 'sync-model-unit.checks.py', 'policy_tables-unit.checks.py'}



def check_fixture_independence(tmp_path):
    from support.validator import MODULE as validator, project, schema_validator, write
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
    for name in ("issues/dev/other/issues.md", "model/dev/other/ec2.properties",
                 "docs/designs/dev/other/ec2.md", "tasks/active.md", "project.json"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid consumer input", encoding="utf-8")
    make_framework_fixture(source, target)


def check_regression_discovery(tmp_path):
    with pytest.raises(ValueError, match="no framework regression checks discovered"):
        MODULE.select_checks(tmp_path, set())
    root = Path(__file__).resolve().parents[4]
    all_checks = {p.name for p in MODULE.select_checks(root, set())[0]}
    assert all_checks == {p.name for p in (root / "framework/scripts/tests/units").rglob("*.checks.py")} | {"test_issues_iac.py"}
    assert "service-parameter-inputs.checks.py" not in all_checks
    assert all(p.is_relative_to(root / "framework/scripts/tests/units") for p in MODULE.select_checks(root, set())[0])
    assert not any("parameter-migration" in name for name in all_checks)
    for helper, expected in (("parameter_cases", "service-parameter-inputs.checks.py"),
                             ("service_contracts", "model_parameter_inputs.checks.py")):
        selected, reason = MODULE.select_checks(root, {f"framework/scripts/tests/integrations/{helper}.py"}, True)
        assert {p.name for p in selected} == ({"model_parameter_inputs-unit.checks.py"} if helper == "service_contracts" else set()), reason



def check_unit_dispatch(tmp_path):
    root = tmp_path / "repository"
    scripts = root / "framework/scripts"
    for relative in ("tests/units/a.checks.py", "tests/units/test_extra.py", "tests/integrations/only.checks.py"):
        path = scripts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Selection fixture; never executed\n", encoding="utf-8")
    runner = scripts / "blueprint-loop.py"
    with patch.dict(os.environ, {}, clear=True), \
         patch.object(MODULE, "__file__", str(runner)), \
         patch.object(MODULE, "active_scope", side_effect=lambda root, all_: None if all_ else {"framework"}), \
         patch.object(MODULE, "changed_paths", return_value={"README.md"}) as changes, \
         patch.object(MODULE, "authorize_full_regression") as authorize, \
         patch.object(MODULE, "run_commands", return_value=0) as dispatch, \
         patch.object(MODULE, "utf8_preflight"), \
         patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
         patch.object(MODULE, "staged_snapshot", return_value=0) as staged, redirect_stdout(io.StringIO()):
        for args in (["--mode", "full"], ["--mode", "task"], ["--mode", "local"],
                     ["--mode", "task", "--all"], ["--mode", "task", "--affected"]):
            authorize.reset_mock()
            with patch.object(sys, "argv", [str(runner), *args, "--log-dir", str(tmp_path / "logs")]):
                assert MODULE.main() == 0
            commands = dispatch.call_args.args[1]
            assert [Path(command[1]).name for command in commands[1:-2]] == ["a.checks.py", "test_extra.py"]
            assert all("integrations" not in command[1] for command in commands)
            assert "--repository-wide-iac" in commands[0]
            assert ("--all" in commands[0]) == ("--all" in args)
            if args == ["--mode", "full"]:
                assert "--fresh" in commands[0] and "--contract-scope" in commands[0]
            authorize.assert_called_once_with(root)
        changes.return_value = set()
        with patch.object(sys, "argv", [str(runner), "--mode", "task", "--log-dir", str(tmp_path / "logs")]):
            assert MODULE.main() == 0
        assert len(dispatch.call_args.args[1]) == 3  # No forced UT for non-regression scope.
        dispatch.reset_mock()
        authorize.reset_mock()
        with patch.object(sys, "argv", [str(runner), "--mode", "full", "--staged", "--base", "HEAD", "--log-dir", str(tmp_path / "logs")]):
            assert MODULE.main() == 0
        staged.assert_called_once()
        dispatch.assert_not_called()
        authorize.assert_not_called()  # The pinned snapshot performs its own authorization.


def check_ci_workflow(tmp_path):
    import yaml
    import run_it
    workflow = yaml.load((SCRIPT.parents[2] / ".github/workflows/framework-it.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert "main" in workflow["on"]["push"]["branches"]
    job = workflow["jobs"]["framework-it"]
    assert job["env"]["PYTHONOPTIMIZE"] == "0"
    assert next(step for step in job["steps"] if step.get("uses", "").startswith("actions/setup-python@"))["with"]["python-version"] == "3.12"
    assert next(step for step in job["steps"] if step.get("name") == "Install dependencies")["run"] == "python -m pip install -r framework/scripts/requirements.txt"
    assert [step['run'] for step in job['steps'] if 'run_it.py' in step.get('run', '')] == [
        'python -B framework/scripts/tests/run_it.py --baseline-root "$IT_BASELINE"']
    tests = tmp_path / 'framework/scripts/tests'
    (tests / 'integrations').mkdir(parents=True)
    for name in ('a', 'b', 'c'):
        (tests / 'integrations' / (name + '.checks.py')).write_text('assert True\n')
    output = tmp_path / 'receipts'
    output.mkdir()
    for codes in ([0, 0, 0], [1, OSError('injected spawn failure'), 0]):
        def execute(command, **kwargs):
            code = codes.pop(0)
            if isinstance(code, OSError):
                raise code
            Path(command[-1]).write_text('{}')
            return subprocess.CompletedProcess(command, code)
        summary = io.StringIO()
        with patch.object(run_it.subprocess, 'run', side_effect=execute) as launch:
            rows, _ = run_it.execute_suites(tests, output, summary)
        assert len(rows) == launch.call_count == 3
        assert rows[-1]['code'] == 0
        assert 'Suites: 3' in summary.getvalue()
        assert all(call.args[0][:4] == [sys.executable, '-B', '-X', 'utf8'] for call in launch.call_args_list)
        for path in output.iterdir():
            path.unlink()
    assert [row['code'] for row in rows] == [1, 1, 0]


def check_it_reachability(tmp_path):
    import run_it
    tests = tmp_path / 'framework/scripts/tests'
    (tests / 'integrations').mkdir(parents=True)
    suite = tests / 'integrations/receipt.checks.py'
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
    (tests / 'pytest.ini').write_text('[pytest]\npython_functions = check_*\naddopts = --import-mode=importlib -p no:cacheprovider\n')
    receipt = tmp_path / 'receipt.json'
    result = subprocess.run([sys.executable, '-B', str(Path(run_it.__file__)), '--suite', str(suite),
                             '--tests', str(tests), '--receipt', str(receipt)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(receipt.read_text())
    cases = {('integrations/receipt.checks.py', 'check_body'): ('pytest', 2)}
    assert not run_it.reachability(cases, [data])
    assert data['calls']['integrations/receipt.checks.py::check_body'] == 2
    cases[('integrations/receipt.checks.py', 'check_not_called')] = ('direct', 1)
    assert 'verification body not reached' in run_it.reachability(cases, [data])[0]
    cases[('integrations/receipt.checks.py', 'check_body')] = ('pytest', 3)
    assert 'expected 3, collected 2, passed body 2' in run_it.reachability(cases, [data])[0]
    assert run_it.reachability(cases, [{**data, 'passed': []}])


def check_it_assertion_guards(tmp_path):
    import run_it
    run_it.check_assertion_guards(Path(run_it.__file__).parent)
    path = tmp_path / 'sample.checks.py'
    guard = "if not __debug__:\n    raise SystemExit('Focused checks require assertions; run without -O')\n"
    path.write_text(guard + 'assert False\n')
    run_it.check_assertion_guards(tmp_path)
    for invalid in ('assert False\n', 'print(1)\n' + guard, guard.replace('raise SystemExit', 'print')):
        path.write_text(invalid)
        with pytest.raises(ValueError):
            run_it.check_assertion_guards(tmp_path)
    result = subprocess.run([sys.executable, '-O', run_it.__file__], capture_output=True, text=True)
    assert result.returncode != 0 and 'Focused checks require assertions' in result.stderr


def check_it_fixture_isolation(tmp_path):
    from support import it_fixture_bundle as fixtures
    from support.it_workspace import populate
    generations = []
    def build(root, name):
        generations.append(name)
        (root / name).mkdir()
        (root / name / 'value.txt').write_text(name)
    with patch.object(fixtures, 'build', side_effect=build):
        with fixtures.bundle() as root, patch.dict(os.environ, {fixtures.ENV: str(root)}):
            before = fixtures.fingerprint(root)
            for number, names in enumerate((fixtures.NAMES, tuple(reversed(fixtures.NAMES)))):
                for name in names:
                    seed = fixtures.source(name)
                    assert not seed.stat().st_mode & 0o222
                    assert not (seed / 'value.txt').stat().st_mode & 0o222
                    first = populate(name, tmp_path / str(number) / name / 'first')
                    second = populate(name, tmp_path / str(number) / name / 'second')
                    (first / 'value.txt').write_text('changed')
                    (first / 'new.txt').write_text('local')
                    assert (second / 'value.txt').read_text() == name
                    assert set(p.name for p in second.iterdir()) == {'value.txt'}
            assert fixtures.fingerprint(root) == before
        assert generations == list(fixtures.NAMES)
    assert not root.exists()
    with patch.object(fixtures, 'build', side_effect=build), pytest.raises(RuntimeError, match='modified'):
        with fixtures.bundle() as root:
            victim = root / 'framework/value.txt'
            victim.chmod(0o600)
            victim.write_text('corrupt')
    assert not root.exists()


def check_it_inventory(tmp_path):
    import run_it
    cases, errors = run_it.inventory(Path(run_it.__file__).parent)
    assert not errors, errors
    assert cases[('integrations/design_layout.checks.py', 'check_quicksight_group_principal_reference')] == ('pytest', 1)
    assert cases[('integrations/sync-model.checks.py', 'check_incoming_reference_models')] == ('pytest', 2)
    row = '| `origin` | `check_one` | IT | [case](integrations/example.py) | direct / 1 |\n'
    (tmp_path / 'CASES.md').write_text(row + row)
    with pytest.raises(ValueError, match='duplicate'):
        run_it.registered_cases(tmp_path)
    assert run_it.reachability({}, [{'collected': ['integrations/example.py::check_one']}])


def check_it_run_lifecycle(tmp_path):
    import run_it
    from support import it_fixture_bundle as fixtures
    (tmp_path / 'integrations').mkdir()
    (tmp_path / 'integrations/example.py').write_text('def check_one():\n    assert True\n')
    (tmp_path / 'CASES.md').write_text('| `origin` | `check_one` | IT | [case](integrations/example.py) | direct / 1 |\n')
    def build(root, name):
        (root / name).mkdir()
        (root / name / 'seed').write_text(name)
        sys.audit('blueprint.it_fixture.generated', name)
    def execute(*args):
        assert os.environ[fixtures.ENV]
        assert os.environ['BLUEPRINT_VALIDATION_CACHE_DIR'] != 'previous-cache'
        return [{'suite': 'example', 'code': 0}], [{'calls': {'integrations/example.py::check_one': 1}}]
    with patch.dict(os.environ, {fixtures.ENV: 'previous-bundle', 'BLUEPRINT_VALIDATION_CACHE_DIR': 'previous-cache'}), \
         patch.object(fixtures, 'build', side_effect=build), patch.object(run_it, 'execute_suites', side_effect=execute):
        result = run_it.run_all(tmp_path, io.StringIO())
        assert result['bundle_initializations'] == 1
        assert result['seed_generations'] == dict.fromkeys(fixtures.NAMES, 1)
        assert not result['reachability_errors']
        assert os.environ[fixtures.ENV] == 'previous-bundle'
        assert os.environ['BLUEPRINT_VALIDATION_CACHE_DIR'] == 'previous-cache'


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
