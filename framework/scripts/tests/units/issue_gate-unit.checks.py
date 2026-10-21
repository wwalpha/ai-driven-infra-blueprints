#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.issue_gate_fixtures import *
import pytest
import task_contract as tasks
from support.import_model_fixtures import operation_contract


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
    from validation.findings import Findings
    from validation.task import TaskValidation
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
    import worktree_task
    path, text, issues, scope = deletion_gate
    root = path.parent.parent
    other = 'tasks/ordinary.md'
    tasks.start(root, other, text.replace('tasks/deletion.md', other).replace(
        '- Model operation: `import-delete`\n', '').replace('## Model delete sources\n- `stg/cde/vpc/009`\n', ''))
    with tasks.selected_task(root, other), pytest.raises(ValueError, match='unresolved issue'):
        require_no_issues(root, scope)
    (root / '.git').mkdir()
    with mock.patch.object(worktree_task, 'task_start_commit', side_effect=ValueError('selected task does not match managed task_file')):
        with pytest.raises(ValueError, match='managed task_file'):
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
    import issue_gate
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
    from contextlib import nullcontext
    import import_guard
    import sync_runtime
    from script_loader import module
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
