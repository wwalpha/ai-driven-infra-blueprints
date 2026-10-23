#!/usr/bin/env python3
"""Offline integration through the official IT runner."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import socket
import subprocess
from contextlib import contextmanager

import import_guard
import pytest
import worktree_task as wt
from model.adapters.task import source_write_context
from model.sources import load_model
from support.import_model_fixtures import fixture as import_fixture
from support.import_model_fixtures import (
    logs_edit,
    m,
    operation_contract,
    operation_fixture,
    review_fixture,
)
from support.model_v2_fixtures import import_contract, import_publication_case
from support.worktree_task_fixtures import fixture as worktree_fixture
from support.worktree_task_fixtures import git, start

from model import prepare_edit, publish_edit

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('live network forbidden')))


def source_files(root):
    return {p.relative_to(root): p.read_bytes() for p in (root / 'model').rglob('*') if p.is_file()}





def fixture(root):
    path = import_fixture(root)
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Import seed')
    return path






def _publication_workspace_begin(root, relative):
    git(root, 'add', 'model', 'project.json')
    git(root, 'commit', '-qm', 'synthetic properties Import')
    return start(root, files=(relative.as_posix(),))


def _publication_workspace_advance(target):
    git(target, 'commit', '--allow-empty', '-qm', 'changed HEAD')


@contextmanager
def publication_workspace():
    with worktree_fixture() as root:
        begin = _publication_workspace_begin
        advance = _publication_workspace_advance
        yield root, begin, advance


@pytest.mark.parametrize('failure', ['head', 'subprocess', 'source-crash', 'receipt-crash', 'display-crash'])
def check_properties_import_worktree_boundary(monkeypatch, failure):
    import_publication_case(monkeypatch, failure, workspace=publication_workspace)

def check_cli_preflight(tmp_path):
    for args in [[], ['--environment', 'dev'], ['--service', 'vpc'], ['--environment', 'dev', '--service', 'vpc']]:
        command = [sys.executable, '-B', str(m.ROOT / 'framework/scripts/model/cli.py'), 'import', *args]
        assert subprocess.run(command, capture_output=True).returncode == 2
    assert not any(hasattr(m, name) for name in ('refresh', 'snapshot_values', 'snapshot_sources', 'promoted_sources'))


def check_cross_process_evidence(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    scripts = m.ROOT / 'framework/scripts'
    setup = f"import sys; sys.path[:0] = [{str(scripts)!r}, {str(scripts / 'tests')!r}]; from pathlib import Path; from support.import_model_fixtures import m, aws; "
    acquire_code = setup + f"import json; print(json.dumps(m.acquire(Path({str(root)!r}), 'dev', 'cloudwatch-logs', 'cde', cli_runner=aws(changed=True), resource_types=['Logs.LogGroup'])))"
    completed = subprocess.run([sys.executable, '-B', '-c', acquire_code], capture_output=True, text=True, encoding='utf-8', check=True)
    acquired = json.loads(completed.stdout)
    logs_edit(root, acquired)
    review_fixture(root, acquired)
    # Run the real CLI parser/entrypoint in an unpatched child, with no Host adapter.
    command = [sys.executable, '-B', str(scripts / 'model/cli.py'), 'import', 'publish', '--repository-root', str(root),
               '--environment', 'dev', '--service', 'cloudwatch-logs', '--target', 'cde',
               '--evidence', acquired['evidence']]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=True)
    report = json.loads(result.stdout)
    assert report['model'] == 'reflected' and report['markdown'] == 'generated'
    assert import_guard.read_proof(root)['complete']
    # The ignored completion receipt contains hashes, not captured configuration values.
    assert '"retentionInDays"' not in import_guard.proof_path(root).read_text(encoding='utf-8')


def _callback_check_import_managed_contract_boundaries_workspace_invalidate(boundary, root, /, target):
    path = wt.state_path(root, 'example')
    state = json.loads(path.read_text())
    if boundary == 'base':
        state['start'] = git(target, 'commit-tree', 'HEAD^{tree}', '-m', 'unrelated baseline')
    else:
        state['worktree'] = str(root)
    wt.save(path, state)


def _callback_check_import_managed_contract_boundaries_workspace_reviewed(review, root, /, *args, **kwargs):
    result = review(*args, **kwargs)
    other, state = start(root, task_id='other', files=('model/qa-synthetic/team-a/cloudwatch-logs.properties',))
    name = state['task_file']
    (other / name).write_text(import_contract(name, 'model/qa-synthetic/team-a/cloudwatch-logs.properties'))
    original = source_files(other)
    with pytest.raises(ValueError, match='original external evidence|another Task|another.*scope|acquisition'):
        m.publish_acquisition(other, 'qa-synthetic', 'cloudwatch-logs', args[3], 'team-a')
    assert source_files(other) == original and not import_guard.proof_path(other).exists()
    return result


def _callback_check_import_managed_contract_boundaries_workspace(boundary, monkeypatch, /):
    with publication_workspace() as (root, begin, advance):
        invalidate = _bind_framework_callback(_callback_check_import_managed_contract_boundaries_workspace_invalidate, boundary, root)
        if boundary == 'other-worktree':
            review = m.review_acquisition
            reviewed = _bind_framework_callback(_callback_check_import_managed_contract_boundaries_workspace_reviewed, review, root)
            monkeypatch.setattr(m, 'review_acquisition', reviewed)
        yield root, begin, invalidate


@pytest.mark.parametrize('boundary', ['task', 'post-task', 'base', 'owner', 'other-worktree'])
def check_import_managed_contract_boundaries(monkeypatch, boundary):
    if boundary in {'task', 'post-task'}:
        import_publication_case(monkeypatch, boundary, workspace=publication_workspace)
        return
    workspace = (contextmanager)(_bind_framework_callback(_callback_check_import_managed_contract_boundaries_workspace, boundary, monkeypatch))
    import_publication_case(monkeypatch, 'none' if boundary == 'other-worktree' else 'head', workspace=workspace)


@pytest.mark.parametrize('boundary', ['none', 'head', 'task', 'owner'])
def check_model_source_context_worktree_boundary(monkeypatch, boundary):

    with worktree_fixture() as root:
        operation_fixture(root)
        git(root, 'add', 'model', 'project.json')
        git(root, 'commit', '-qm', 'Model context baseline')
        relative = 'model/stg/cde/vpc.properties'
        target, state = start(root, files=(relative,))
        name = state['task_file']
        task = target / name
        text = operation_contract() + '\n## Validation scope\n- `stg/cde/vpc`\n'
        for heading in ('Modified files', 'Allowed paths'):
            text += '\n## ' + heading + '\n- `' + name + '`\n- `' + relative + '`\n'
        task.write_text(text)
        path = target / relative
        original = path.read_bytes()
        with source_write_context(target, name) as context:
            model = load_model(path, context.snapshot)
            candidate = original.decode('utf-8') + '# intermediate save\n'
            plan = prepare_edit(model, {path: candidate}, context)
            if boundary == 'head':
                git(target, 'commit', '--allow-empty', '-qm', 'changed Task head')
            elif boundary == 'task':
                task.write_text(text + '\n## Notes\nconcurrent contract edit\n')
            elif boundary == 'owner':
                invalid = dict(state, worktree=str(root))
                wt.save(wt.state_path(root, 'example'), invalid)
            if boundary == 'none':
                assert publish_edit(plan, context) == (path,)
                assert path.read_text() == candidate
            else:
                with pytest.raises(ValueError, match='changed|lifecycle|mismatch'):
                    publish_edit(plan, context)
                assert path.read_bytes() == original
        assert (root / relative).read_bytes() == original


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
