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
    for name in ("iac_evaluation", "script_loader"):
        assert selected(f"framework/scripts/{name}.py") == (comparison - {'check-model-aws-unit.checks.py'})
    for name in ("__init__", "scheduler", "guards", "delivery", "s3_delivery", "observed", "controller", "inputs", "change_sets", "repair", "secret_bootstrap", "session"):
        assert selected(f"framework/scripts/deploy/{name}.py") == {'cloudformation-deploy-unit.checks.py', 'deploy_preparation-unit.checks.py', 'model_files-unit.checks.py',
            'deploy-sdk.checks.py', 'deploy-runtime-unit.checks.py', 'deploy-observed-unit.checks.py'}
    for name in ('client', 'cloudformation', 's3', 'kms', 'sts', 'secretsmanager'):
        assert selected(f'framework/scripts/utils/aws/{name}.py') == selected('framework/scripts/deploy/controller.py') | {'aws-client.checks.py'}
    for name in ('__init__','cli','runner','inputs','integrity','materials','records','aggregate','artifact','reports','publication','cfn_lint'):
        expected = (comparison - {'check-model-aws-unit.checks.py'}) | {'test_issues_iac.py','issues-lint-unit.checks.py'}
        if name in {'materials', 'reports'}:
            expected.add('model-reference-warnings-unit.checks.py')
        if name in {'publication', 'reports'}:
            expected.add('issue_gate-unit.checks.py')
        checks, reason = MODULE.select_checks(root, {f'framework/scripts/issues/{name}.py'}, True)
        assert expected <= {p.name for p in checks}
        assert reason.startswith('affected:')
        assert all('/units/' in p.as_posix() for p in checks)
    expected_comparison = (comparison - {'check-model-aws-unit.checks.py'}) | {
        'test_issues_iac.py', 'issues-lint-unit.checks.py', 's3-kms-reference-unit.checks.py',
        'security_group_tables-unit.checks.py', 'deploy-runtime-unit.checks.py'}
    for path in ('comparison/runner.py', 'comparison/inputs.py', 'comparison/references.py',
                 'comparison/services/s3.py', 'comparison/services/kms.py', 'comparison/services/security_group.py'):
        checks, reason = MODULE.select_checks(root, {'framework/scripts/' + path}, True)
        assert {p.name for p in checks} == expected_comparison
        assert reason.startswith('affected:')
        assert all('/units/' in p.as_posix() for p in checks)
    assert selected('framework/scripts/utils/cfn_lint.py') == selected('framework/scripts/issues/cfn_lint.py')
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
                 "docs/designs/dev/other/ec2.md", "tasks/example.md", "project.json"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid consumer input", encoding="utf-8")
    make_project_fixture(source, target)


def check_regression_discovery(tmp_path):
    with patch.object(MODULE, "definition_root", return_value=tmp_path), \
         pytest.raises(ValueError, match="no framework regression checks discovered"):
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
         patch.object(Path, "cwd", return_value=root), \
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
                assert CLI.main() == 0
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
            assert CLI.main() == 0
        assert len(dispatch.call_args.args[1]) == 3  # No forced UT for non-regression scope.
        dispatch.reset_mock()
        authorize.reset_mock()
        with patch.object(sys, "argv", [str(runner), "--mode", "full", "--staged", "--base", "HEAD", "--log-dir", str(tmp_path / "logs")]):
            assert CLI.main() == 0
        staged.assert_called_once()
        dispatch.assert_not_called()
        authorize.assert_not_called()  # The pinned snapshot performs its own authorization.


def check_ci_workflow(tmp_path):
    import run_it
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
            Path(command[-1]).write_text(json.dumps({'version': 1, 'suite': 'integrations/' + Path(command[command.index('--suite') + 1]).name,
                                                   'completed': {}, 'collected': [], 'passed': [], 'metrics': {}}))
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

    def invalid_receipts(command, **kwargs):
        path = Path(command[-1])
        if path.name.startswith('a.'):
            path.write_text('{broken')
        elif path.name.startswith('b.'):
            path.write_text('{}')
        return subprocess.CompletedProcess(command, 0)
    with patch.object(run_it.subprocess, 'run', side_effect=invalid_receipts):
        rows, receipts = run_it.execute_suites(tests, output, io.StringIO())
    assert all(row['code'] != 0 for row in rows) and not receipts


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
    assert len(data['passed']) == 2
    assert 'calls' not in data
    assert run_it.reachability(cases, [{**data, 'passed': data['passed'][:1]}])
    assert run_it.reachability(cases, [{**data, 'passed': [data['passed'][0]] * 2}])
    cases[('integrations/receipt.checks.py', 'check_not_called')] = ('direct', 1)
    assert 'verification did not complete' in run_it.reachability(cases, [data])[0]
    cases[('integrations/receipt.checks.py', 'check_body')] = ('pytest', 3)
    assert 'expected 3, collected 2, passed body 2' in run_it.reachability(cases, [data])[0]
    assert run_it.reachability(cases, [{**data, 'passed': []}])

    suite.write_text(f"import sys\nsys.path.insert(0, {str(Path(run_it.__file__).parent.parent)!r})\n" + """from support.it_case_receipt import it_case, module_complete
from unittest.mock import patch
from validation_cache import input_scope
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
""")
    command = [sys.executable, '-B', str(Path(run_it.__file__)), '--suite', str(suite),
               '--tests', str(tests), '--receipt', str(receipt)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(receipt.read_text())
    direct = ('integrations/receipt.checks.py', 'check_direct')
    module = ('integrations/receipt.checks.py', '__module__')
    cases = {direct: ('direct', 1), module: ('module', 1)}
    assert data['completed'] == {'::'.join(direct): 2, '::'.join(module): 1}
    assert not run_it.reachability(cases, [data])
    assert run_it.reachability({**cases, (direct[0], 'check_failure'): ('direct', 1)}, [data])
    assert run_it.reachability(cases, [{**data, 'completed': {'::'.join(direct): 2}}])
    for invalid in (None, {}, {**data, 'completed': []}, {**data, 'metrics': {'bad': False}}):
        assert run_it.reachability(cases, [invalid])
    assert run_it.reachability(cases, [])
    suite.write_text(suite.read_text().replace('module_complete(__file__)', "raise RuntimeError('before completion')"))
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert run_it.reachability(cases, [json.loads(receipt.read_text())])


def check_it_assertion_guards(tmp_path):
    import run_it
    run_it.check_assertion_guards(Path(run_it.__file__).parent)
    source = Path(run_it.__file__).read_text()
    assert 'setprofile' not in source and 'settrace' not in source
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
            from support.model_design_fixtures import root as model_design_root
            shared = fixtures.REPOSITORY / 'framework'
            with patch('support.it_workspace.populate', side_effect=AssertionError('case copy')), \
                 patch('shutil.copytree', side_effect=AssertionError('framework copy')):
                for order in (('a', 'b'), ('b', 'a')):
                    cases = {}
                    for name in order:
                        directory = tmp_path / ''.join(order) / name
                        directory.mkdir(parents=True)
                        case = model_design_root.__wrapped__(directory)
                        assert case == directory.resolve()
                        from utils.aws_mappings import definition_root
                        assert not (case / 'framework').exists()
                        assert definition_root(case) / 'framework' == shared
                        assert not (case / 'model').exists()
                        (case / 'model').mkdir()
                        (case / 'model/value.txt').write_text(name)
                        cases[name] = case
                        assert fixtures.fingerprint(root) == before
                    (cases['a'] / 'model/value.txt').write_text('changed')
                    assert (cases['b'] / 'model/value.txt').read_text() == 'b'
                    subprocess.run(['git', 'init', '-q', str(cases['a'])], check=True)
                    subprocess.run(['git', 'add', '.'], cwd=cases['a'], check=True)
                    tracked = subprocess.run(['git', 'ls-files', '--stage'], cwd=cases['a'],
                                             check=True, capture_output=True, text=True).stdout
                    assert not any(line.endswith('\tframework') for line in tracked.splitlines())
                    assert 'framework/rules/task-contract.md' not in tracked
                    assert '\tmodel/value.txt' in tracked
            assert fixtures.fingerprint(root) == before
        assert generations == list(fixtures.NAMES)
    assert not root.exists()
    with patch.object(fixtures, 'build', side_effect=build), pytest.raises(RuntimeError, match='modified'):
        with fixtures.bundle() as root:
            victim = root / fixtures.NAMES[0] / 'value.txt'
            victim.chmod(0o600)
            victim.write_text('corrupt')
    assert not root.exists()


def check_it_inventory(tmp_path):
    import run_it
    cases, errors = run_it.inventory(Path(run_it.__file__).parent)
    assert not errors, errors
    assert cases[('integrations/design_layout.checks.py', 'check_quicksight_group_principal_reference')] == ('pytest', 1)
    assert cases[('integrations/sync-model.checks.py', 'check_incoming_reference_models')] == ('pytest', 2)
    assert cases[('integrations/model-validation-reuse.checks.py', 'check_sync_mapping_lifetime')] == ('pytest', 4)
    row = '| `origin` | `check_one` | IT | [case](integrations/example.py) | direct / 1 |\n'
    (tmp_path / 'CASES.md').write_text(row + row)
    with pytest.raises(ValueError, match='duplicate'):
        run_it.registered_cases(tmp_path)
    assert run_it.reachability({}, [])
    folder = tmp_path / 'integrations'
    folder.mkdir()
    entry = folder / 'example.checks.py'
    row = row.replace('example.py', 'example.checks.py')
    (tmp_path / 'CASES.md').write_text(row)
    entry.write_text('def check_one():\n    pass\n')
    assert any('decorator' in error for error in run_it.inventory(tmp_path)[1])
    entry.write_text('from support.it_case_receipt import it_case\n@it_case\ndef check_one():\n    pass\n')
    assert not run_it.inventory(tmp_path)[1]
    entry.write_text('pass\n')
    assert any('missing IT case' in error for error in run_it.inventory(tmp_path)[1])
    (folder / 'unregistered.checks.py').write_text('pass\n')
    assert any('unregistered IT suite' in error for error in run_it.inventory(tmp_path)[1])
    (folder / 'unregistered.checks.py').unlink()
    (tmp_path / 'CASES.md').write_text(row.replace('check_one', '__module__').replace('direct /', 'module /'))
    entry.write_text('from support.it_case_receipt import module_complete\nmodule_complete(__file__)\n')
    assert not run_it.inventory(tmp_path)[1]
    entry.write_text(entry.read_text() + 'assert True\n')
    assert any('terminal module' in error for error in run_it.inventory(tmp_path)[1])


def check_it_run_lifecycle(tmp_path):
    import run_it
    from support import it_fixture_bundle as fixtures
    (tmp_path / 'integrations').mkdir()
    (tmp_path / 'integrations/example.checks.py').write_text("if not __debug__:\n    raise SystemExit('Focused checks require assertions; run without -O')\nfrom support.it_case_receipt import it_case\n@it_case\ndef check_one():\n    assert True\n")
    (tmp_path / 'CASES.md').write_text('| `origin` | `check_one` | IT | [case](integrations/example.checks.py) | direct / 1 |\n')
    def build(root, name):
        (root / name).mkdir()
        (root / name / 'seed').write_text(name)
        sys.audit('blueprint.it_fixture.generated', name)
    def execute(*args):
        assert os.environ[fixtures.ENV]
        assert os.environ['BLUEPRINT_VALIDATION_CACHE_DIR'] != 'previous-cache'
        return [{'suite': 'example', 'code': 0}], [{'version': 1, 'suite': 'integrations/example.checks.py', 'completed': {'integrations/example.checks.py::check_one': 1}, 'collected': [], 'passed': [], 'metrics': {}}]
    with patch.dict(os.environ, {fixtures.ENV: 'previous-bundle', 'BLUEPRINT_VALIDATION_CACHE_DIR': 'previous-cache'}), \
         patch.object(fixtures, 'build', side_effect=build), patch.object(run_it, 'execute_suites', side_effect=execute):
        result = run_it.run_all(tmp_path, io.StringIO())
        assert result['bundle_initializations'] == 1
        assert result['seed_generations'] == dict.fromkeys(fixtures.NAMES, 1)
        assert not result['reachability_errors']
        assert os.environ[fixtures.ENV] == 'previous-bundle'
        assert os.environ['BLUEPRINT_VALIDATION_CACHE_DIR'] == 'previous-cache'
    # Old baseline may have neither ledger nor markers; only process results are comparable.
    (tmp_path / 'CASES.md').unlink()
    with patch.object(run_it, 'execute_suites', return_value=([{'suite': 'old', 'code': 7}], [])):
        result = run_it.run_all(tmp_path, io.StringIO(), baseline=True)
    assert result['reachability'] == 'not verified (baseline)'
    assert result['bundle_initializations'] is None and result['seed_generations'] is None
    assert result['suites'][0]['code'] == 7


@pytest.mark.parametrize('write', [False, True])
def check_write_validator_stops_followups(tmp_path, write):
    logs = tmp_path/'logs'
    logs.mkdir()
    commands = [[sys.executable, 'validate-blueprint.py'], [sys.executable, 'a.checks.py'], ['git', 'diff', '--check']]
    with patch.object(MODULE.subprocess, 'Popen') as popen, redirect_stdout(io.StringIO()):
        popen.return_value.wait.return_value = 1
        popen.return_value.pid = 123
        assert MODULE.run_commands(tmp_path, commands, MODULE.utf8_environment(), logs,
                                   stop_after_validator_failure=write) == 1
        assert popen.call_count == (1 if write else 3)
    history = events(logs)
    assert history[-1]['status'] == 'fail'
    assert any(row['event'] == 'steps_skipped' for row in history) == write


def check_staged_write_rejected():
    with patch.object(sys, 'argv', [str(SCRIPT), '--mode', 'task', '--write', '--staged', '--base', 'HEAD']), \
         pytest.raises(SystemExit) as error:
        CLI.main()
    assert error.value.code == 2


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
