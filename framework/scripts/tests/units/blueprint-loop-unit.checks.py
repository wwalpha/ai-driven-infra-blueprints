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
    commands = [[sys.executable, 'a.checks.py'], [sys.executable, 'b.checks.py']]
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
    scripts = root / 'framework/scripts/tests/integrations'
    scripts.mkdir(parents=True)
    for name in ('a', 'b'):
        (scripts / (name + '.checks.py')).write_text('# selection fixture\n', encoding='utf-8')
    paths = {"framework/scripts/tests/integrations/a.checks.py"}
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
    validator = {'validate-blueprint.checks.py', 'validation-units.checks.py'}
    shared = validator | {'blueprint-loop.checks.py', 'blueprint-loop-unit.checks.py'}
    for category, name in (("integrations", "task"), ("units", "design"), ("units", "references"),
                           ("units", "cloudformation"), ("integrations", "scope"), ("units", "contracts")):
        assert selected(f"framework/scripts/tests/{category}/validation_checks/{name}.py") == validator, name
    leaf = "framework/scripts/tests/integrations/validation_checks/task.py"
    assert selected(leaf, "framework/scripts/blueprint-loop.py") == shared
    comparison = {'comparison_core.checks.py', 'issues_scan.checks.py', 'check-model-aws.checks.py', 'cloudformation-deploy.checks.py', 'deploy_preparation.checks.py', 'model_files.checks.py', 'comparison_core-unit.checks.py', 'issues_scan-unit.checks.py', 'check-model-aws-unit.checks.py', 'cloudformation-deploy-unit.checks.py', 'deploy_preparation-unit.checks.py', 'model_files-unit.checks.py'}
    assert selected("framework/scripts/comparison_rows.py") == comparison
    for name in ("iac_evaluation", "script_loader", "issues_iac"):
        assert selected(f"framework/scripts/{name}.py") == comparison - {'check-model-aws.checks.py', 'check-model-aws-unit.checks.py'}
    for name in ("__init__", "scheduler", "aws_adapter", "delivery", "change_sets", "repair", "secret_bootstrap", "session"):
        assert selected(f"framework/scripts/deployment/{name}.py") == {'cloudformation-deploy.checks.py', 'deploy_preparation.checks.py', 'model_files.checks.py', 'cloudformation-deploy-unit.checks.py', 'deploy_preparation-unit.checks.py', 'model_files-unit.checks.py'}
    all_checks = {p.name for p in (SCRIPT.parent / "tests").rglob("*.checks.py")}
    assert selected("framework/scripts/iac_values.py") == all_checks
    for unknown in ("framework/scripts/tests/support/validation_checks/unknown.py", "framework/scripts/tests/support/unknown.py"):
        assert selected(leaf, unknown) == all_checks
    with patch.object(Path, "is_file", return_value=False):
        assert selected(leaf) == all_checks  # Known path removed/renamed without a resolvable source.
    assert selected("framework/scripts/tests/support/validator.py") == all_checks
    assert selected("framework/scripts/tests/integrations/model_design.checks.py") == all_checks
    assert selected("framework/scripts/tests/integrations/rotation_schedule.checks.py") == {'rotation_schedule.checks.py', 'cloudformation-deploy.checks.py', 'cloudformation-deploy-unit.checks.py'}
    for name in ("service_rows", "model_display", "model_projection", "model_references", "sync_runtime", "sync_views", "sync_files"):
        assert selected(f"framework/scripts/{name}.py") == all_checks
    assert selected("framework/scripts/model_core.py") == all_checks
    assert selected("framework/scripts/ec2_display.py") == all_checks
    assert selected(leaf, affected=False) == all_checks
    assert selected("framework/scripts/tests/integrations/design_layout.checks.py") == {'design_layout.checks.py', 'design_document.checks.py', 'validate-blueprint.checks.py', 'sync-model.checks.py', 'policy_tables.checks.py', 'design_layout-unit.checks.py', 'design_document-unit.checks.py', 'validation-units.checks.py', 'sync-model-unit.checks.py', 'policy_tables-unit.checks.py'}



def check_fixture_independence(tmp_path):
    from support.validator import MODULE as validator, project, schema_validator, write
    before = dict(os.environ), Path.cwd()
    with project() as first, project() as second:
        assert first != second
        write(first / "日本語.txt", "独立fixture")
        assert not (second / "日本語.txt").exists()
        a, b = schema_validator(first), schema_validator(second)
        assert type(a) is type(b) is validator.Validator
        a.errors.append("local state")
        assert not b.errors and a.schema_catalog is not b.schema_catalog
    assert not first.exists() and not second.exists()
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
    assert not (target / "issues").exists()
    assert not list((target / "model").rglob("*.properties"))
    assert not (target / "project.json").exists()
    assert not (target / "tasks/active.md").exists()


def check_regression_discovery(tmp_path):
    with pytest.raises(ValueError, match="no framework regression checks discovered"):
        MODULE.select_checks(tmp_path, set())
    root = Path(__file__).resolve().parents[4]
    all_checks = {p.name for p in MODULE.select_checks(root, set())[0]}
    assert all_checks and "cloudformation-naming.checks.py" in all_checks
    assert "service-parameter-inputs.checks.py" in all_checks
    assert not any("parameter-migration" in name for name in all_checks)
    for helper, expected in (("parameter_cases", "service-parameter-inputs.checks.py"),
                             ("service_contracts", "model_parameter_inputs.checks.py")):
        selected, reason = MODULE.select_checks(root, {f"framework/scripts/tests/integrations/{helper}.py"}, True)
        assert {p.name for p in selected} == {expected, *({"model_parameter_inputs-unit.checks.py"} if helper == "service_contracts" else set())}, reason


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
