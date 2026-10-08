"""Responsibility boundaries: dispatch, mutable gates, callbacks and import safety."""
from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from test_support.validator import MODULE, SCRIPT, project, write, load
from validation_cache import PassCache


def check_dispatch():
    common = ['check_structure', 'check_task_scope', 'check_tasks', 'check_project_topology',
              'check_validation_scope', 'check_model_files', 'check_issue_gate',
              'check_initialized_paths', 'check_catalog', 'check_resource_layout']
    cases = [
        (None, '', '', False, ['check_designs', 'check_observed_values', 'check_iac_selection',
                             'check_cloudformation_yaml_rules', 'check_cloudformation_environment_parameters',
                             'check_scenarios', 'check_results', 'check_scenario_changes']),
        (set(), 'governance', '', False, ['check_scoped_designs', 'check_iac_selection']),
        ({('dev', 'target', 'ec2')}, 'design', '', True, ['check_iac_selection']),
        (set(), 'infrastructure', 'implement', False, ['check_scoped_designs', 'check_iac_selection',
                'check_cloudformation_yaml_rules', 'check_cloudformation_environment_parameters']),
        (set(), 'infrastructure', 'destroy', False, ['check_scoped_designs']),
        (set(), 'scenario-test', '', False, ['check_scoped_designs', 'check_iac_selection',
                                           'check_scenarios', 'check_results', 'check_scenario_changes']),
    ]
    methods = set(common + ['check_task_type_requirements', 'check_acceptance_checks'])
    methods.update(name for *_, tail in cases for name in tail)
    with project() as root:
        for scope, task_type, phase, failed, tail in cases:
            validator = MODULE.Validator(root, scope)
            invoked = []
            def run_check(name):
                invoked.append(name)
                if name == 'check_task_scope':
                    validator.task_type, validator.infrastructure_phase = task_type, phase
                if failed and name == 'check_model_files':
                    validator.check(False, 'prior model error')
            with ExitStack() as stack, redirect_stdout(io.StringIO()):
                for name in methods:
                    stack.enter_context(patch.object(validator, name, lambda name=name: run_check(name)))
                assert validator.run() == int(failed)
            assert invoked == common + tail + ['check_acceptance_checks'], invoked


def check_boundaries():
    with project() as root:
        path = root / 'own.yaml'
        first, second = MODULE.Validator(root, set()), MODULE.Validator(root, set())
        first.check_file(False, path, 'unresolved')
        first.file_gate_paths = set()
        first.check_file(False, path, 'outside')
        first.check(False, 'global')
        first.file_gate_paths.add('own.yaml')
        first.check_file(False, path, 'inside')
        first.repository_wide_gate = True
        first.file_gate_paths.clear()
        first.check_file(False, path, 'wide')
        assert first.errors == ['unresolved', 'global', 'inside', 'wide']
        assert first.non_blocking_findings == ['outside'] and first.checks == 5
        assert first.errors is first.findings.errors
        first.errors = list(first.errors)
        assert first.errors is first.findings.errors
        assert not second.errors and second.checks == 0 and second.file_gate_paths is None
        first.task.changed_paths.add('own.yaml')
        assert first.changed_paths == {'own.yaml'} and not second.changed_paths
        first.acceptance_checks = [('R1', 'check', 'framework.resource-layout'),
                                   ('R2', 'check', 'unknown'), ('R3', 'changed', 'pending.md')]
        first.deferred_files = {'pending.md'}
        with patch.object(first, 'check_resource_layout', side_effect=lambda: first.check(False, 'handler failed')) as handler:
            first.check_acceptance_checks()
            handler.assert_called_once_with()
        assert first.errors[-2:] == ['handler failed', 'unknown registered Acceptance check: R2: unknown']
        assert not first.acceptance_results and first.deferred_acceptance == ['R3:changed:pending.md']
        # A failed read keeps Project's already-determined mode and propagates failure.
        write(root / 'project.json', '{}\n')
        with patch.object(Path, 'read_text', side_effect=OSError('cannot read')) as read:
            try:
                second.check_project_topology()
            except OSError as error:
                assert str(error) == 'cannot read' and not second.template_mode
            else:
                raise AssertionError('read failure was hidden')
            read.assert_called_once_with(encoding='utf-8')
        scope = {('dev', 'target', 'ec2')}
        first.schema_catalog = MODULE.DesignSchemaCatalog(SCRIPT.parents[2])
        with patch.object(first, 'check_design_service_ownership') as ownership, \
             patch.object(first, 'check_stack_designs') as stacks, \
             patch.object(MODULE.Validator, 'check_designs', side_effect=RuntimeError('child failed')) as child:
            first.scope, first.model_check = scope, lambda selected: []
            try:
                first.check_scoped_designs()
            except RuntimeError as error:
                assert str(error) == 'child failed'
            else:
                raise AssertionError('child failure was hidden')
            ownership.assert_called_once()
            stacks.assert_called_once()
            child.assert_called_once_with()


def check_module_inputs():
    names = ('findings', 'scenario', 'cloudformation', 'design', 'design_tables', 'design_links',
             'project', 'task', 'framework_contracts')
    with project() as root, project() as runtime:
        for base in (root, runtime):
            directory = base / 'framework/scripts/validation'
            directory.mkdir(parents=True)
            for name in names:
                write(directory / f'{name}.py', 'original\n')
        with patch('validation_cache.__file__', str(runtime / 'framework/scripts/validation_cache.py')):
            cache = PassCache(root)
            before = cache.common_key()
            for base in (root, runtime):
                for name in names:
                    path = base / f'framework/scripts/validation/{name}.py'
                    write(path, 'changed\n')
                    assert cache.common_key() != before, (base, name)
                    write(path, 'original\n')
                    assert cache.common_key() == before
    loop = load('blueprint-loop')
    all_checks = sorted((SCRIPT.parent).glob('*.checks.py'))
    for name in names:
        selected, _ = loop.select_checks(SCRIPT.parents[2], {f'framework/scripts/validation/{name}.py'}, True)
        assert selected == all_checks, name
    command = '''from pathlib import Path
from unittest.mock import patch
import importlib
with patch.object(Path, 'rglob', side_effect=AssertionError('repository scan')), \\
     patch.object(Path, 'glob', side_effect=AssertionError('repository scan')), \\
     patch.object(Path, 'iterdir', side_effect=AssertionError('repository scan')), \\
     patch('subprocess.run', side_effect=AssertionError('process launched')):
    for name in %r:
        importlib.import_module('validation.' + name)
''' % (names,)
    completed = subprocess.run([sys.executable, '-B', '-c', command], cwd=SCRIPT.parent,
                               env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True)
    assert completed.returncode == 0 and not completed.stdout and not completed.stderr, completed.stderr
