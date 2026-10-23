#!/usr/bin/env python3
"""Offline integration through the official IT runner."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import subprocess
from contextlib import contextmanager

import import_guard
import pytest
from support.import_model_fixtures import fixture as import_fixture
from support.import_model_fixtures import (
    logs_edit,
    m,
    review_fixture,
)
from support.model_v2_fixtures import import_publication_case
from support.repository_fixtures import fixture as repository_fixture
from support.repository_fixtures import git, start

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

def fixture(root):
    path = import_fixture(root)
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Import seed')
    return path

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


def _git_publication_workspace_begin(root, relative):
    git(root, 'add', 'model', 'project.json')
    git(root, 'commit', '-qm', 'synthetic properties Import')
    return start(root, files=(relative.as_posix(),))


def _git_publication_workspace_advance(target):
    git(target, 'commit', '--allow-empty', '-qm', 'changed HEAD')


@contextmanager
def git_publication_workspace():
    with repository_fixture() as root:
        begin = _git_publication_workspace_begin
        advance = _git_publication_workspace_advance
        yield root, begin, advance


@pytest.mark.parametrize('failure', ['head', 'subprocess', 'source-crash', 'receipt-crash', 'display-crash'])
def check_properties_import_git_boundary(monkeypatch, failure):
    import_publication_case(monkeypatch, failure, workspace=git_publication_workspace)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
