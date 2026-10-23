#!/usr/bin/env python3
"""Detect direct, indirect, mocked and renamed lifecycle regressions."""
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from run_it import registered_cases
from support.worktree_test_policy import (
    audit,
    forbidden_process,
    ordinary_suite,
    violations,
)
from validation.loop import select_checks

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_repository_policy():
    assert violations(Path(__file__).resolve().parents[1]) == []


@pytest.mark.parametrize('source', [
    'import worktree_task',
    "state = {'task_file': 'tasks/example.md', 'worktree': '/tmp/fixture', 'merged': None}",
    'from support.worktree_task_fixtures import fixture',
    "from unittest.mock import patch\npatch('worktree_state.load')",
    "import importlib\nimportlib.import_module('support.worktree_task_fixtures')",
])
def check_direct_and_indirect(tmp_path, source):
    (tmp_path / 'support').mkdir()
    (tmp_path / 'support/helper.py').write_text(source)
    (tmp_path / 'business.py').write_text('from support.helper import fixture')
    errors = violations(tmp_path)
    assert any('business.py: Worktree dependency through support.helper' in error for error in errors)
    assert any('support/helper.py: Worktree dependency' in error for error in errors)


def check_filename_grants_no_authority(tmp_path):
    (tmp_path / 'worktree-renamed.checks.py').write_text('import worktree_task\ndef check_business(): pass')
    assert violations(tmp_path)


def check_runtime_guard(tmp_path):
    with ordinary_suite(tmp_path / 'business.py', tmp_path):
        for command in (['git', 'worktree', 'add', 'candidate'], ['python3', 'worktree_task.py', 'finalize']):
            with pytest.raises(AssertionError, match='lifecycle subprocess'):
                audit('subprocess.Popen', ('unused', command, None, None))
        with pytest.raises(AssertionError, match='lifecycle storage'):
            audit('open', (str(tmp_path / '.worktrees/.blueprint/state.json'), 'w', 1))
        for command in (['git', 'init'], ['git', 'commit', '-m', 'fixture'], ['git', 'diff'], ['git', 'worktree', 'list']):
            assert not forbidden_process(command)
            audit('subprocess.Popen', ('unused', command, None, None))
        audit('open', (str(tmp_path / 'model.properties'), 'w', 1))
        with ThreadPoolExecutor(max_workers=1) as pool:
            attempted = pool.submit(subprocess.run, ['git', 'worktree', 'add', str(tmp_path / 'candidate')], cwd=tmp_path, capture_output=True)
            with pytest.raises(AssertionError, match='lifecycle subprocess'):
                attempted.result()
        assert not (tmp_path / 'candidate').exists()




@pytest.mark.parametrize('fixture,expected', [
    ('worktree_task_fixtures', {'worktree_task.checks.py', 'worktree_python.checks.py', 'import-worktree-contract.checks.py', 'worktree-deploy-repair.checks.py', 'worktree-model-operation.checks.py'}),
    ('worktree_deploy_fixtures', {'worktree-deploy-repair.checks.py'}),
    ('deploy_repair_fixtures', {'deploy-controller.checks.py', 'worktree-deploy-repair.checks.py'}),
    ('resource_delete_fixtures', {'worktree-model-operation.checks.py'}),
])
def check_fixture_selection(fixture, expected):
    root = Path(__file__).resolve().parents[4]
    cases = registered_cases(root / 'framework/scripts/tests')
    selected, _ = select_checks(root, {'framework/scripts/tests/support/' + fixture + '.py'}, True, integration_cases=cases)
    assert {Path(path).name for path, _ in selected} == expected


def check_new_shared_fixture_mappings():
    root = Path(__file__).resolve().parents[4]
    cases = registered_cases(root / 'framework/scripts/tests')
    for relative in ('support/publication_fixtures.py', 'support/repository_fixtures.py', 'support/worktree_test_policy.py', 'pytest.ini'):
        path = 'framework/scripts/tests/' + relative
        assert select_checks(root, {path}, True)[0]
        assert select_checks(root, {path}, True, integration_cases=cases)[0]

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
