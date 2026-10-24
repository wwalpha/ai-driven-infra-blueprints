#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from contextlib import nullcontext
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import import_guard
import issue_gate
import pytest
import sync_runtime
import task_contract as tasks
from issues.publication import save
from support.import_model_fixtures import operation_contract
from support.issue_gate_fixtures import (
    Path,
    issue_errors,
    json,
    mock,
    require_no_issues,
    subprocess,
    sys,
)
from utils.script_loader import module
from validation.findings import Findings
from validation.task import TaskValidation
from validation_scope import active_scope

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def _callback_check_report_commit_independence_git(tmp_path, /, *args):
    return subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                           *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize('kind', ['reports', 'migration', 'design'])
def check_report_commit_independence(tmp_path, monkeypatch, kind):
    name = 'tasks/investigation.md'
    reports = {'issues/dev/cde/issues.md', 'issues/dev/cde/iac-issues.md'}
    permitted = reports | {name}
    text = ('## Task contract\n- Task type: `' + ('design' if kind == 'design' else 'migration') +
            '`\n- Task status: `running`\n## Validation scope\n- `dev/cde/s3`\n'
            '## Required changes\n- [R1] Save reports\n## Acceptance checks\n' +
            ''.join(f'- [R1] `exists:{path}`\n' for path in sorted(reports)) +
            '## Modified files\n' + ''.join(f'- `{path}`\n' for path in sorted(permitted)) +
            '## Allowed paths\n' + ''.join(f'- `{path}`\n' for path in sorted(permitted)))
    if kind == 'migration':
        text += '- `infra/**`\n'  # An ordinary migration must retain its Git baseline.
    git = _bind_framework_callback(_callback_check_report_commit_independence_git, tmp_path)
    git('init', '--quiet', '--initial-branch=master')
    for path in reports | {'outside.txt'}:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text('')
    git('add', '.')
    git('commit', '--quiet', '-m', 'initial')
    baseline = git('rev-parse', 'HEAD')
    tasks.start(tmp_path, name, text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    findings = Findings(tmp_path)
    task = TaskValidation(tmp_path, findings)
    with mock.patch('model.importing.repository.task_start_commit', return_value=baseline) as start:
        task.fix_baseline()
        assert start.call_count == (0 if kind == 'reports' else 1)
        git('commit', '--quiet', '--allow-empty', '-m', 'advance HEAD')
        if kind == 'reports':
            save(tmp_path, 'dev', 'cde', ['s3'], iac=[])
        else:
            for path in reports:
                (tmp_path / path).write_text('ordinary Task change')
        task.check_task_scope()
        assert not findings.errors, findings.errors
        (tmp_path / 'committed.txt').write_text('unrelated committed input')
        git('add', 'committed.txt')
        git('commit', '--quiet', '-m', 'unrelated change')
        assert git('rev-parse', 'HEAD') != baseline
        task.check_task_scope()
    assert active_scope(tmp_path) == {('dev', 'cde', 's3')}
    assert (tmp_path / name).read_text() == text  # No suspension or replacement Task.
    if kind != 'reports':
        assert any('outside task scope: committed.txt' in error for error in findings.errors)
        assert 'committed.txt' in task.changed_paths and task.baseline == baseline
        return
    assert not findings.errors, findings.errors
    assert task.changed_paths == permitted and task.scope_paths == permitted
    task.check_issue_gate()
    task.check_acceptance_checks({})
    assert not findings.errors, findings.errors
    # Preserve independent index changes, including a file restored only in the worktree.
    git('add', 'issues/dev/cde/issues.md')
    (tmp_path / 'issues/dev/cde/issues.md').write_text('')
    assert task.final_paths() == permitted
    for state in ('unstaged', 'staged', 'untracked'):
        outside = tmp_path / ('untracked.txt' if state == 'untracked' else 'outside.txt')
        outside.write_text(state)
        if state == 'staged':
            git('add', 'outside.txt')
            outside.write_text('')
        blocked = TaskValidation(tmp_path, Findings(tmp_path))
        blocked.check_task_scope()
        assert any(f'outside task scope: {outside.name}' in error for error in blocked.findings.errors)
    (tmp_path / 'outside.txt').write_text('')
    git('add', 'outside.txt')
    (tmp_path / 'untracked.txt').unlink()
    task.check_task_scope()
    assert not findings.errors, findings.errors
    with mock.patch('model.importing.repository.task_start_commit', side_effect=AssertionError('report completion used a baseline')):
        tasks.complete(tmp_path, name)
    assert tasks.status((tmp_path / name).read_text()) == 'completed'


@pytest.fixture
def deletion_gate(tmp_path, monkeypatch):
    name = 'tasks/deletion.md'
    text = (operation_contract('import-delete') +
            '## Validation scope\n- `stg/cde/vpc`\n' +
            f'## Modified files\n- `{name}`\n## Allowed paths\n- `{name}`\n')
    tasks.start(tmp_path, name, text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    issues = tmp_path / 'issues/stg/cde/issues.md'
    issues.parent.mkdir(parents=True)
    issues.write_text('### vpc\n1. 既存のIssue\n', encoding='utf-8')
    return tmp_path / name, text, issues, {('stg', 'cde', 'vpc')}


def check_deletion_gate_and_task_validation(deletion_gate):
    path, text, issues, scope = deletion_gate
    root = path.parent.parent
    original = issues.read_bytes()
    for content in (original.decode('utf-8'), '### unknown service\n1. 既存のIssue\n'):
        issues.write_text(content, encoding='utf-8')
        assert issue_errors(root, scope), 'inventory analysis must still report unresolved issues'
        require_no_issues(root, scope)
        findings = Findings(root)
        task = TaskValidation(root, findings)
        task.task_type = 'design'
        task.check_issue_gate()
        assert not findings.errors
    issues.write_bytes(original)
    assert path.read_text() == text and issues.read_bytes() == original


@pytest.mark.parametrize('kind', ['merge', 'update', 'deploy', 'completed', 'missing'])
def check_ordinary_issue_gate_restored(deletion_gate, kind):
    path, text, issues, scope = deletion_gate
    if kind == 'merge':
        text = text.replace('`import-delete`', '`import-merge`').replace(
            '## Model delete sources\n- `stg/cde/vpc/009`',
            '## Model merge pairs\n- ' + json.dumps({'source': 'stg/cde/vpc/009', 'destination': 'stg/cde/vpc/001'}))
    elif kind in {'update', 'deploy'}:
        text = text.replace('- Model operation: `import-delete`\n', '').replace('## Model delete sources\n- `stg/cde/vpc/009`\n', '')
        if kind == 'deploy':
            text = text.replace('- Task type: `design`', '- Task type: `infrastructure`\n- Infrastructure phase: `deploy`')
    elif kind == 'completed':
        text = tasks.set_status(text, 'completed')
    else:
        path.unlink()
    if kind != 'missing':
        path.write_text(text)
    with pytest.raises(ValueError):
        require_no_issues(path.parent.parent, scope)


@pytest.mark.parametrize('old,new', [
    ('`design`', '`infrastructure`'), ('`update`', '`import`'),
    ('- `stg/cde/vpc/009`', '- `009`'),
    ('- AWS API execution: `forbidden`', '- AWS API execution: `allowed`'),
    ('- deploy/apply: `forbidden`', '- deploy/apply: `allowed`'),
    ('`import-delete`', '`unknown`'), ('## Modified files', '## Missing files'),
    ('- `stg/cde/vpc`', '- `stg/cde/ec2`'), ('- `stg/cde/vpc`', '- `all`'),
])
def check_deletion_contract_fail_closed(deletion_gate, old, new):
    path, text, issues, scope = deletion_gate
    path.write_text(text.replace(old, new))
    with pytest.raises(ValueError):
        require_no_issues(path.parent.parent, scope)


@pytest.mark.parametrize('scope,target', [(None, None), ({('dev', 'cde', 'vpc')}, None),
    ({('stg', 'cde', 'vpc'), ('stg', 'cde', 'ec2')}, None),
    ({('stg', 'cde', 'vpc')}, ('dev', 'cde'))])
def check_deletion_scope_fail_closed(deletion_gate, scope, target):
    path, text, issues, _ = deletion_gate
    with pytest.raises(ValueError, match='matching service Validation scope'):
        require_no_issues(path.parent.parent, scope, target=target)


def check_deletion_task_selection(deletion_gate):
    path, text, issues, scope = deletion_gate
    root = path.parent.parent
    other = 'tasks/ordinary.md'
    tasks.start(root, other, text.replace('tasks/deletion.md', other).replace(
        '- Model operation: `import-delete`\n', '').replace('## Model delete sources\n- `stg/cde/vpc/009`\n', ''))
    with tasks.selected_task(root, other), pytest.raises(ValueError, match='unresolved issue'):
        require_no_issues(root, scope)


def check_remediation_still_requires_explicit_scope(deletion_gate):
    path, text, issues, scope = deletion_gate
    root = path.parent.parent
    ordinary = text.replace('- Model operation: `import-delete`\n', '').replace('## Model delete sources\n- `stg/cde/vpc/009`\n', '')
    path.write_text(ordinary + '## Issue remediation\n- `stg/cde/vpc`\n')
    require_no_issues(root, scope)
    assert issue_errors(root, scope)
    path.write_text(ordinary + '## Issue remediation\n- `stg/cde/ec2`\n')
    with pytest.raises(ValueError, match='within explicit service Validation scope'):
        require_no_issues(root, scope)


@pytest.mark.parametrize('use_task', [False, True])
def check_deletion_cli_requires_task_opt_in(deletion_gate, use_task):
    path, text, issues, scope = deletion_gate
    args = ['issue_gate.py', '--repository-root', str(path.parent.parent), '--environment', 'stg',
            '--target-directory', 'cde', '--service', 'vpc'] + (['--task'] if use_task else [])
    with mock.patch.object(sys, 'argv', args):
        assert issue_gate.main() == (0 if use_task else 1)


@pytest.mark.parametrize('deletion', [False, True])
def check_resume_issue_gate(deletion_gate, deletion):
    path, text, issues, scope = deletion_gate
    root, name = path.parent.parent, path.relative_to(path.parent.parent).as_posix()
    if not deletion:
        text = text.replace('`import-delete`', '`import-merge`').replace(
            '## Model delete sources\n- `stg/cde/vpc/009`',
            '## Model merge pairs\n- ' + json.dumps({'source': 'stg/cde/vpc/009', 'destination': 'stg/cde/vpc/001'}))
        path.write_text(text)
    tasks.suspend(root, name, 'explicit test stop')
    if deletion:
        tasks.resume(root, name)
        assert tasks.status(path.read_text()) == 'running'
    else:
        with pytest.raises(ValueError, match='unresolved issue'):
            tasks.resume(root, name)
        assert tasks.status(path.read_text()) == 'suspend'


@pytest.mark.parametrize('entrypoint', ['cli', 'runtime'])
def check_generation_uses_deletion_gate(deletion_gate, entrypoint):

    path, text, issues, scope = deletion_gate
    root = path.parent.parent
    runner = module('sync-model.py', 'issue_gate_sync_cli')
    with mock.patch.object(import_guard, 'require_import_changes'), \
         mock.patch.object(sync_runtime, 'run_generation', return_value=0) as generate, \
         mock.patch.object(runner, 'run_generation', generate), \
         mock.patch.object(runner, 'generation_context', return_value=nullcontext()):
        if entrypoint == 'cli':
            assert runner.run(['--write', '--scope', 'stg/cde/vpc'], repository_root=root)[0] == 0
        else:
            assert sync_runtime._sync(root, True, 'stg', 'cde', ['vpc']) == 0
        assert generate.call_args.args[:2] == (root, scope)
        generate.side_effect = ValueError('new candidate validation error')
        if entrypoint == 'cli':
            code, diagnostic = runner.run(['--write', '--scope', 'stg/cde/vpc'], repository_root=root)
            assert code == 1 and 'new candidate validation error' in diagnostic
        else:
            with pytest.raises(ValueError, match='new candidate validation error'):
                sync_runtime._sync(root, True, 'stg', 'cde', ['vpc'])


def check_inventory_parser(tmp_path):
    root = tmp_path
    scope = {("dev", "cde", "ec2")}
    scope = {("dev", "cde", "ec2")}
    assert not issue_errors(root, scope)
    path = root / "issues/dev/cde/issues.md"
    path.parent.mkdir(parents=True)
    original = "# 問題一覧\n\n## dev／cde\n\n### Amazon EC2\n\n1. 不正な設定。根拠: [ec2.properties:1](../../../model/dev/cde/ec2.properties)。\n\n```text\n1. 診断のcode例\n### fake\n```\n"
    path.write_text(original)
    assert len(issue_errors(root, scope)) == 1
    assert not issue_errors(root, {("prod", "cde", "ec2")})
    assert not issue_errors(root, {("dev", "non-cde", "ec2")})
    assert not issue_errors(root, {("dev", "cde", "s3")})
    assert not issue_errors(root, set())
    assert issue_errors(root, None)
    path.write_text("### Amazon EC2\n<!-- issue-service: ec2 -->\n\n1. 設定不足\n\n2. 参照不足\n")
    assert len(issue_errors(root, scope)) == 2
    path.write_text("### ec2\n\n1. 設定不足。参照先: [s3](../../../docs/designs/dev/cde/s3.md)。\n")
    assert issue_errors(root, scope)
    assert not issue_errors(root, {("dev", "cde", "s3")})  # Explicit ownership wins over references.
    path.write_text("### Unknown service\n\n1. 設定不足\n")
    assert "ambiguous" in issue_errors(root, {("dev", "cde", "s3")})[0]
    assert issue_errors(root, scope, remediation=scope)  # Unknown ownership cannot be waived.
    path.write_text("設定不足\n")
    assert issue_errors(root, scope)
    path.write_text("# 問題一覧\n\n未解決issueなし\n")
    assert not issue_errors(root, scope)
    path.write_text("")
    assert not issue_errors(root, scope)
    (path.parent / "diff.md").write_text("### ec2\n\n1. 環境間の差分\n")
    assert not issue_errors(root, scope)  # Differences never enter the unresolved issue inventory.
    for contents in ("### ec2\n1. 差分\n", "invalid inventory; 999 differences", ""):
        (path.parent / "iac-issues.md").write_text(contents)
        assert not issue_errors(root, scope)
    path.write_text(original)
    assert issue_errors(root, scope)


    assert not issue_errors(root, {("dev", "cde", "s3")})






if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
