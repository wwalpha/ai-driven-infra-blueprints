#!/usr/bin/env python3
"""Managed authority and invalidation with synthetic metadata; no Git or AWS calls."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

import json
import os
from unittest.mock import patch
import pytest
from support.pytest_cli import run
from support.worktree_task_fixtures import contract
import task_contract as tasks
import worktree_task as wt

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.fixture
def managed(tmp_path, monkeypatch):
    primary = tmp_path / 'repository'
    root = primary / '.worktrees' / 'example'
    root.mkdir(parents=True)
    common = primary / '.git'
    gitdir = common / 'worktrees' / 'example'
    gitdir.mkdir(parents=True)
    (root / '.git').write_text(f'gitdir: {gitdir}\n')
    (gitdir / 'HEAD').write_text('ref: refs/heads/codex/worktree/example\n')
    identity = tasks.directory_identity(gitdir)
    state = dict(task_id='example', branch='codex/worktree/example', worktree=str(root),
                 primary=str(primary), task_file='tasks/example.md', identity=identity,
                 base='main', start='a' * 40, tip='a' * 40, commit=None, verified=False, merged=None)
    metadata = wt.state_path(primary, 'example')
    metadata.parent.mkdir(parents=True)
    wt.save(metadata, state)
    monkeypatch.delenv(tasks.SELECTOR, raising=False)
    monkeypatch.setattr(tasks, '_managed_cache', None)
    monkeypatch.setattr(tasks, 'worktree_identity', lambda path: identity if path == root else tasks.directory_identity(path))
    monkeypatch.setattr(wt, 'repository', lambda where: (where, common, primary))
    monkeypatch.setattr(wt, 'worktrees', lambda where: [dict(worktree=str(root), branch='refs/heads/' + state['branch'])])
    monkeypatch.setattr(wt, 'idle_git', lambda where: None)
    monkeypatch.setattr(wt, 'output', lambda where, *args: str(gitdir))
    with patch.object(tasks.subprocess, 'run', side_effect=AssertionError('UT must not spawn Git')):
        yield root, state, metadata, gitdir


def register(managed):
    root, state, _, _ = managed
    tasks.start(root, state['task_file'], contract('example', ['file.txt', 'nested/second.txt']))
    return root, state['task_file']


def check_managed_lifecycle_and_hot_path(managed):
    with patch.object(tasks, 'reservations', side_effect=AssertionError('managed conflict calculation')):
        root = managed[0]
        assert tasks.task_path(root) == root / 'tasks/active.md'
        tasks.require_writable(root, [root / 'file.txt'])
        assert list(tasks.reserved_batches(root, {'free': [root / 'file.txt']})) == ['free']
        root, name = register(managed)
        tasks.require_writable(root, [root / 'file.txt'], name)
        with patch.object(tasks, 'contracts', side_effect=AssertionError('hot contract scan')), \
                patch.object(wt, 'managed_state', side_effect=AssertionError('hot lifecycle/Git validation')), \
                patch.object(tasks.time, 'sleep', side_effect=AssertionError('managed wait')):
            for index in range(20):
                tasks.require_writable(root, [root / 'file.txt'], name)
                tasks.atomic_files({root / 'file.txt': f'publication {index}\n'}, staging_directory=root)
            tasks.require_writable(root, [root / 'file.txt'], name)
            assert tasks.task_path(root) == root / name
            assert list(tasks.reserved_batches(root, {'atomic': [root / 'file.txt', root / 'nested/second.txt']}, task_file=name)) == ['atomic']
            assert tasks.wait_deferred(root, name) == set()
        assert tasks.task_changes(root, {'file.txt'}, name) == {'file.txt'}
        with pytest.raises(ValueError, match='no task reservation'):
            tasks.task_changes(root, {'outside.txt'}, name)
        from model_templates import publish
        before = (root / 'file.txt').read_bytes()
        text = (root / name).read_text()
        def change_scope():
            (root / name).write_text(text.replace('`framework`', '`dev/team/iam`'))
        with pytest.raises(ValueError, match='authority changed'):
            publish(root, {root / 'file.txt': 'changed'}, verify=change_scope)
        assert (root / 'file.txt').read_bytes() == before
        (root / name).write_text(text)
        tasks.suspend(root, name, 'unit check: file.txt')
        with pytest.raises(ValueError, match='suspend'):
            tasks.require_writable(root, [root / 'file.txt'], name)
        tasks.resume(root, name)
        tasks.refresh(root, name)
        tasks.require_writable(root, [root / 'file.txt'], name)
        tasks.complete(root, name)
        with pytest.raises(ValueError, match='completed'):
            tasks.require_writable(root, [root / 'file.txt'], name)
        assert wt.integration_task(root, managed[1]).active == {name, 'file.txt', 'nested/second.txt'}
        from validation.task import TaskValidation
        from types import SimpleNamespace
        errors = []
        findings = SimpleNamespace(check=lambda valid, message: errors.append(message) if not valid else None,
                                   relative=lambda path: path.relative_to(root).as_posix())
        with patch.object(tasks, 'contracts', side_effect=AssertionError('cached validation contract scan')):
            TaskValidation(root, findings).check_tasks()
            assert wt.integration_task(root, managed[1]).state == 'completed'
        assert not errors


@pytest.mark.parametrize('change', ['status', 'allowed', 'scope', 'replace', 'second-task', 'foreign-owner', 'metadata', 'HEAD', 'removed-metadata'])
def check_external_changes_invalidate(managed, change):
    root, name = register(managed)
    tasks.require_writable(root, [root / 'file.txt'], name)
    path = root / name
    if change == 'status':
        path.write_text(tasks.set_status(path.read_text(), 'completed'))
    elif change == 'allowed':
        text = path.read_text().replace('## Allowed paths\n- `tasks/example.md`\n- `file.txt`', '## Allowed paths\n- `tasks/example.md`')
        path.write_text(text)
    elif change == 'scope':
        path.write_text(path.read_text().replace('file.txt', 'new-file.txt'))
    elif change == 'replace':
        # Same-size replacement with restored mtime still changes inode/ctime.
        before = path.stat()
        replacement = path.with_suffix('.replacement')
        replacement.write_text(path.read_text().replace('file.txt', 'gone.txt'))
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(path)
    elif change == 'second-task':
        (root / 'tasks/other.md').write_text(contract('other', ['file.txt']))
    elif change == 'foreign-owner':
        path.write_text(path.read_text().replace(managed[1]['identity'], 'b' * 64))
    elif change == 'metadata':
        state = dict(managed[1], task_file='tasks/wrong.md')
        wt.save(managed[2], state)
    elif change == 'HEAD':
        (managed[3] / 'HEAD').write_text('ref: refs/heads/switched\n')
    else:
        managed[2].unlink()
    with pytest.raises(ValueError):
        tasks.require_writable(root, [root / 'file.txt'], name)


def check_scope_expansion_requires_refresh(managed):
    root, name = register(managed)
    path = root / name
    text = path.read_text()
    for heading in ('Modified files', 'Allowed paths'):
        text = text.replace(f'## {heading}\n', f'## {heading}\n- `new.txt`\n')
    path.write_text(text)
    with pytest.raises(ValueError, match='explicit refresh'):
        tasks.require_writable(root, [root / 'new.txt'], name)
    with pytest.raises(ValueError, match='explicit refresh'):
        list(tasks.reserved_batches(root, {'atomic': [root / 'file.txt', root / 'new.txt']}, task_file=name))
    with patch.object(tasks, 'reservations', side_effect=AssertionError('refresh must not calculate conflicts')):
        tasks.refresh(root, name)
        tasks.require_writable(root, [root / 'new.txt'], name)


def check_path_and_selection_guards(managed):
    root, name = register(managed)
    for relative in ('outside.txt', '../escape', '.git/config'):
        with pytest.raises(ValueError):
            tasks.require_writable(root, [root / relative], name)
    with pytest.raises(ValueError, match='task_file'):
        tasks.require_writable(root, [root / 'file.txt'], 'tasks/other.md')
    outside = root.parent / 'outside'
    outside.mkdir()
    (root / 'nested').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlinks'):
        tasks.require_writable(root, [root / 'nested/second.txt'], name)


@pytest.mark.parametrize('field', ['task_id', 'task_file', 'branch', 'worktree', 'identity', 'primary'])
def check_metadata_mismatch(managed, field):
    root, name = register(managed)
    record = json.loads(managed[2].read_text())
    record[field] = 'wrong'
    wt.save(managed[2], record)
    with pytest.raises(ValueError):
        tasks.require_writable(root, [root / 'file.txt'], name)


def check_contract_free_and_normal_reservations(tmp_path, monkeypatch):
    monkeypatch.delenv(tasks.SELECTOR, raising=False)
    tasks.require_writable(tmp_path, [tmp_path / 'free.txt'])
    first, second = 'tasks/first.md', 'tasks/second.md'
    tasks.start(tmp_path, first, contract('first', ['file.txt']))
    tasks.start(tmp_path, second, contract('second', ['file.txt', 'second.txt']))
    with pytest.raises(tasks.DeferredWrite):
        tasks.require_writable(tmp_path, [tmp_path / 'file.txt'], second)
    tasks.require_writable(tmp_path, [tmp_path / 'second.txt'], second)
    tasks.complete(tmp_path, first)
    tasks.refresh(tmp_path, second)
    tasks.require_writable(tmp_path, [tmp_path / 'file.txt'], second)


import import_scope
from validation_cache import input_scope


def selection_contract(name, allowed='output.txt', workflow=''):
    return (f'## Task contract\n- Task type: `migration`\n- Task status: `running`\n{workflow}'
            '## Validation scope\n- `dev/team/iam`\n'
            f'## Modified files\n- `{name}`\n- `output.txt`\n'
            f'## Allowed paths\n- `{name}`\n- `{allowed}`\n')


@pytest.mark.parametrize('allowed,accepted', [('output.txt', True), ('*.txt', True), ('out*', True), ('other.txt', False)])
def check_allowed_paths(tmp_path, allowed, accepted):
    name = 'tasks/test.md'
    records = {name: selection_contract(name, allowed)}
    if accepted:
        assert tasks.reservations(tmp_path, records)[name].active == {name, 'output.txt'}
        if allowed == 'output.txt':
            with patch.object(tasks, 'matches', side_effect=AssertionError('exact matches need no pattern scan')):
                tasks.reservations(tmp_path, records)
    else:
        with pytest.raises(ValueError, match='outside Allowed paths'):
            tasks.reservations(tmp_path, records)
    external = tmp_path / 'external'
    external.write_text('safe')
    (tmp_path / 'output.txt').symlink_to(external)
    with pytest.raises(ValueError, match='symlinks'):
        tasks.reservations(tmp_path, records)


def check_live_selection(tmp_path):
    (tmp_path / 'tasks').mkdir()
    one, two = 'tasks/one.md', 'tasks/two.md'
    original = selection_contract(one)
    (tmp_path / one).write_text(original)
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'tasks').mkdir()
    (other / one).write_text(selection_contract(one, workflow='- Workflow: `import`\n'))

    @input_scope
    def exercise():
        with patch.dict(os.environ, {tasks.SELECTOR: one}):
            assert import_scope.selected(tmp_path) is None
            assert import_scope.selected(tmp_path) is None  # cached negative parsing result
            from validation_cache import memo_table
            assert (import_scope._selection.__wrapped__, (tmp_path, one, original)) in memo_table()
            assert import_scope.selected(other) == ('dev', 'team', 'iam')
            stat = (tmp_path / one).stat()
            (tmp_path / one).write_text(selection_contract(one, workflow='- Workflow: `import`\n'))
            os.utime(tmp_path / one, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            assert import_scope.selected(tmp_path) == ('dev', 'team', 'iam')
            (tmp_path / one).write_text(original)
            assert import_scope.selected(tmp_path) is None
            (tmp_path / two).write_text(selection_contract(two, workflow='- Workflow: `import`\n- IMPORT target: `stg/team/config`\n'))
            with patch.dict(os.environ, {tasks.SELECTOR: two}):
                assert import_scope.selected(tmp_path) == ('stg', 'team', 'config')
            assert import_scope.selected(tmp_path) is None
            with import_scope.restrict(('dev', 'team', 'vpc')):
                assert import_scope.selected(tmp_path) == ('dev', 'team', 'vpc')
            assert import_scope.selected(tmp_path) is None
            (tmp_path / two).unlink()
            (tmp_path / one).write_text(selection_contract(one, 'denied'))
            with pytest.raises(ValueError, match='outside Allowed paths'):
                import_scope.selected(tmp_path)
            (tmp_path / one).write_text(original)
            (tmp_path / 'external').write_text('safe')
            (tmp_path / 'output.txt').symlink_to(tmp_path / 'external')
            assert import_scope.selected(tmp_path) is None
            with pytest.raises(ValueError, match='symlinks'):
                tasks.require_writable(tmp_path, [tmp_path / 'output.txt'])
            (tmp_path / 'output.txt').unlink()
            (tmp_path / one).write_text(original.replace('`running`', '`suspend`')+'## Suspension reason\nExplicit test stop\n')
            with pytest.raises(ValueError, match='suspend task'):
                import_scope.selected(tmp_path)
    exercise()



def ordinary_scale(root):
    """43 independent synthetic contracts, exactly 2,361 requested paths."""
    (root / 'tasks').mkdir()
    outputs = [root / f'output/{index}.txt' for index in range(10)]
    total = 0
    for index in range(43):
        task_id = f'owner-{index}'
        name = f'tasks/{task_id}.md'
        count = 55 if index < 42 else 51
        files = [file.relative_to(root).as_posix() for file in outputs] if index == 0 else []
        files += [f'past/{index}/{item}.txt' for item in range(count - 1 - len(files))]
        text = tasks.bind_worktree(root, contract(task_id, files))
        text += '\n## Active files\n' + ''.join(f'- `{file}`\n' for file in [name, *files]) + '\n## Deferred files\n'
        (root / name).write_text(text, encoding='utf-8')
        total += len(files) + 1
    assert total == 2361
    return 'tasks/owner-0.md', outputs


@pytest.mark.parametrize('imported', [False, True])
def check_scale_reads_do_not_reserve(tmp_path, monkeypatch, imported):
    from types import SimpleNamespace
    from support.model_sources import write_model
    from model_files import load_model
    from validation.design_links import check_design_links
    name, _ = ordinary_scale(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, name)
    text = (tmp_path / name).read_text().replace('- `framework`', '- `dev/team/iam`')
    if imported:
        text = text.replace('## Task contract\n', '## Task contract\n- Workflow: `import`\n- IMPORT target: `dev/team/iam`\n')
    (tmp_path / name).write_text(text)
    values = {'desired.service.iam.serviceId': 'iam', 'desired.service.iam.ownedCatalogResourceTypes': 'IAM.Role',
              'display.service.title': '# IAM 詳細設計'}
    model = write_model(tmp_path / 'model/dev/team/iam.properties', values)
    document = tmp_path / 'docs/designs/dev/team/iam.md'
    document.parent.mkdir(parents=True)
    document.write_text('# IAM 詳細設計\n<a id="target"></a>\n' + '[target](#target)\n' * 2550)
    errors, checks = [], []
    findings = SimpleNamespace(relative=lambda path: path.relative_to(tmp_path).as_posix(),
                               check=lambda valid, message: (checks.append(valid), errors.append(message) if not valid else None))

    @input_scope
    def read():
        assert tasks.task_path(tmp_path) == tmp_path / name
        assert import_scope.selected(tmp_path) == (('dev', 'team', 'iam') if imported else None)
        assert load_model(model).values == values
        check_design_links({}, [document], design_sources={document: values}, findings=findings,
                           root=tmp_path, scope={('dev', 'team', 'iam')})

    with patch.object(tasks, 'reservations', side_effect=AssertionError('read must not scan reservations')), \
            patch.object(tasks, 'registration_lock', side_effect=AssertionError('read must not hold registration lock')), \
            patch.object(tasks, 'safe_path', wraps=tasks.safe_path) as paths:
        read()
        assert paths.call_count == 0
    assert not errors, errors
    assert len(checks) >= 2550


def check_registration_and_publication_counts(tmp_path, monkeypatch):
    from model_templates import publish
    name, outputs = ordinary_scale(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, name)
    with patch.object(tasks, 'reservations', wraps=tasks.reservations) as scans:
        tasks.start(tmp_path, 'tasks/new.md', contract('new', ['new.txt']))
        assert scans.call_count == 1
    with patch.object(tasks, 'reservations', wraps=tasks.reservations) as scans, \
            patch.object(tasks, 'safe_path', wraps=tasks.safe_path) as paths:
        for _ in tasks.reserved_batches(tmp_path, {'all': outputs}):
            tasks.require_writable(tmp_path, outputs)
            publish(tmp_path, {file: 'batch' for file in outputs})
        assert scans.call_count == 1
        assert {call.args[1] for call in paths.call_args_list} == {file.relative_to(tmp_path).as_posix() for file in outputs}
        scans.reset_mock()
        for file in tasks.reserved_batches(tmp_path, {file: [file] for file in outputs}):
            tasks.require_writable(tmp_path, [file])
            publish(tmp_path, {file: 'single'})
        assert scans.call_count == 10
        scans.reset_mock()
        for _ in tasks.reserved_batches(tmp_path, {'unchanged': []}):
            tasks.require_writable(tmp_path, [])
        assert scans.call_count == 0
    assert all(file.read_text() == 'single' for file in outputs)


def check_explicit_validation_keeps_contract_checks(tmp_path, monkeypatch):
    name, outputs = ordinary_scale(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, name)
    old = tmp_path / 'tasks/owner-1.md'
    old.write_text(tasks.set_status(old.read_text(), 'completed'))
    past = tmp_path / 'past/1/0.txt'
    past.parent.mkdir(parents=True)
    past.symlink_to(tmp_path / 'unrelated')
    # Historical paths are not a write destination; explicit validation still checks them.
    tasks.require_writable(tmp_path, outputs)
    for validate in (lambda: tasks.authorizations(tmp_path),
                     lambda: tasks.task_changes(tmp_path, set(), name)):
        with pytest.raises(ValueError, match='symlinks'):
            validate()
        with tasks.writable_batch(tmp_path, outputs):
            with pytest.raises(ValueError, match='symlinks'):
                validate()


@pytest.mark.parametrize('change', ['status', 'allowed', 'scope', 'identity', 'conflict'])
def check_publication_rejects_changed_authority(tmp_path, monkeypatch, change):
    from model_templates import publish
    name = 'tasks/owner.md'
    file = tmp_path / 'file.txt'
    file.write_text('original')
    tasks.start(tmp_path, name, contract('owner', ['file.txt']))
    monkeypatch.setenv(tasks.SELECTOR, name)
    with tasks.writable_batch(tmp_path, [file]):
        own = tmp_path / name
        text = own.read_text()
        if change == 'status':
            own.write_text(tasks.set_status(text, 'completed'))
        elif change == 'allowed':
            own.write_text(text.replace('## Allowed paths\n- `tasks/owner.md`\n- `file.txt`', '## Allowed paths\n- `tasks/owner.md`'))
        elif change == 'scope':
            own.write_text(text.replace('- `framework`', '- `dev/team/iam`'))
        elif change == 'identity':
            own.write_text(text.replace(tasks.worktree_identity(tmp_path), 'f' * 64))
        else:
            (tmp_path / 'tasks/other.md').write_text(contract('other', ['file.txt']))
        with pytest.raises(ValueError):
            publish(tmp_path, {file: 'denied'})
        assert file.read_text() == 'original'
        # This is fixture restoration, not an authorization refresh.
        own.write_text(text)
        if change == 'conflict':
            (tmp_path / 'tasks/other.md').unlink()
    # A conflict introduced after registration is also detected on a new transaction.
    (tmp_path / 'tasks/other.md').write_text(contract('other', ['file.txt']))
    with pytest.raises(tasks.DeferredWrite):
        publish(tmp_path, {file: 'denied'})
    assert file.read_text() == 'original'


def check_authority_change_rolls_back_publication(tmp_path, monkeypatch):
    from model_templates import publish
    name = 'tasks/owner.md'
    file = tmp_path / 'file.txt'
    file.write_text('original')
    tasks.start(tmp_path, name, contract('owner', ['file.txt']))
    monkeypatch.setenv(tasks.SELECTOR, name)
    def changed():
        own = tmp_path / name
        own.write_text(own.read_text().replace('- `framework`', '- `dev/team/iam`'))
    with pytest.raises(ValueError, match='authority changed'):
        publish(tmp_path, {file: 'candidate'}, verify=changed)
    assert file.read_text() == 'original'
    assert 'dev/team/iam' in (tmp_path / name).read_text(), 'rollback must not undo an external contract edit'


def check_registration_excluded_through_publication(tmp_path, monkeypatch):
    from model_templates import publish
    name = 'tasks/owner.md'
    file = tmp_path / 'file.txt'
    tasks.start(tmp_path, name, contract('owner', ['file.txt']))
    monkeypatch.setenv(tasks.SELECTOR, name)
    with tasks.writable_batch(tmp_path, [file]):
        with pytest.raises(tasks.RegistrationBusy):
            tasks.start(tmp_path, 'tasks/other.md', contract('other', ['file.txt']))
        assert not (tmp_path / 'tasks/other.md').exists()
        publish(tmp_path, {file: 'saved'})
    tasks.start(tmp_path, 'tasks/other.md', contract('other', ['file.txt']))
    assert tasks.reservations(tmp_path, tasks.contracts(tmp_path))['tasks/other.md'].deferred == {'file.txt': (name,)}



def check_scope_change_during_planning_and_wait(tmp_path, monkeypatch):
    name = 'tasks/owner.md'
    file = tmp_path / 'file.txt'
    tasks.start(tmp_path, name, contract('owner', ['file.txt']))
    monkeypatch.setenv(tasks.SELECTOR, name)
    expected = tasks.task_revision(tmp_path)
    own = tmp_path / name
    own.write_text(own.read_text().replace('- `framework`', '- `dev/team/iam`'))
    with pytest.raises(ValueError, match='scope changed'):
        list(tasks.reserved_batches(tmp_path, {'file': [file]}, expected_task=expected))
    other = 'tasks/waiter.md'
    tasks.start(tmp_path, other, contract('waiter', ['file.txt']))
    def changed(seconds):
        # The worker must not retain either mutex while waiting.
        from model_templates import publication_lock
        with publication_lock(tmp_path), tasks.registration_lock(tmp_path):
            waiting = tmp_path / other
            waiting.write_text(waiting.read_text().replace('- `framework`', '- `stg/team/iam`'))
        tasks.complete(tmp_path, name)
    with pytest.raises(ValueError, match='scope changed'):
        list(tasks.reserved_batches(tmp_path, {'file': [file]}, changed, other))
    assert not file.exists()


@pytest.mark.parametrize('explicit_status', [False, True])
def check_legacy_publication_preserves_contract(tmp_path, monkeypatch, explicit_status):
    from model_templates import publish
    name = 'tasks/active.md'
    text = contract('active', ['file.txt'])
    if not explicit_status:
        text = text.replace('- Task status: `running`\n', '')
    own = tmp_path / name
    own.parent.mkdir()
    own.write_text(text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    assert tasks.task_path(tmp_path) == own
    with tasks.writable_batch(tmp_path, [tmp_path / 'file.txt']):
        publish(tmp_path, {tmp_path / 'file.txt': 'saved'})
    assert own.read_text() == text
    assert (tmp_path / 'file.txt').read_text() == 'saved'


def check_source_guard_precedes_registration_lock(tmp_path, monkeypatch):
    from model_templates import publish
    import import_guard
    name = 'tasks/owner.md'
    source = tmp_path / 'model/parameters/dev/team/iam/parameters.yaml'
    tasks.start(tmp_path, name, contract('owner', [source.relative_to(tmp_path).as_posix()]))
    monkeypatch.setenv(tasks.SELECTOR, name)
    def guard(*args, **kwargs):
        # Ordinary IMPORT protection may expand Models; it must not hold registration.
        with tasks.registration_lock(tmp_path):
            own = tmp_path / name
            own.write_text(own.read_text().replace('- `framework`', '- `dev/team/iam`'))
    with patch.object(import_guard, 'require_import_changes', guard):
        with pytest.raises(ValueError, match='scope changed'):
            publish(tmp_path, {source: 'instances: {}\n'})
    assert not source.exists()



if __name__ == '__main__':
    raise SystemExit(run(__file__))
