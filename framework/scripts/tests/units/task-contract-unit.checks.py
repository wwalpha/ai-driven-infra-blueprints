#!/usr/bin/env python3
"""Task selection, declaration checks and publication consistency with synthetic inputs."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
import os
from unittest.mock import patch
import pytest
from support.pytest_cli import run
from support.worktree_task_fixtures import contract
import task_contract as tasks
import import_scope
from validation_cache import input_scope

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


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
        tasks.validate_contract(tmp_path, name, records[name])
        if allowed == 'output.txt':
            with patch.object(tasks, 'matches', side_effect=AssertionError('exact matches need no pattern scan')):
                tasks.validate_contract(tmp_path, name, records[name])
    else:
        with pytest.raises(ValueError, match='outside Allowed paths'):
            tasks.validate_contract(tmp_path, name, records[name])
    external = tmp_path / 'external'
    external.write_text('safe')
    (tmp_path / 'output.txt').symlink_to(external)
    with pytest.raises(ValueError, match='symlinks'):
        tasks.validate_contract(tmp_path, name, records[name])



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
                tasks.safe_path(tmp_path, 'output.txt')
            (tmp_path / 'output.txt').unlink()
            (tmp_path / one).write_text(original.replace('`running`', '`suspend`')+'## Suspension reason\nExplicit test stop\n')
            with pytest.raises(ValueError, match='suspend task'):
                import_scope.selected(tmp_path)
    exercise()



@pytest.mark.parametrize('change', ['scope', 'completed', 'suspend'])
def check_task_change_rolls_back_publication(tmp_path, monkeypatch, change):
    from model_templates import publish
    name = 'tasks/owner.md'
    file = tmp_path / 'file.txt'
    file.write_text('original')
    tasks.start(tmp_path, name, contract('owner', ['file.txt']))
    monkeypatch.setenv(tasks.SELECTOR, name)
    def changed():
        own = tmp_path / name
        text = own.read_text()
        own.write_text(text.replace('- `framework`', '- `dev/team/iam`') if change == 'scope' else
                       text.replace('`running`', f'`{change}`') +
                       ('## Suspension reason\nExplicit test stop\n' if change == 'suspend' else ''))
    with pytest.raises(ValueError, match='suspend task' if change == 'suspend' else 'scope changed'):
        publish(tmp_path, {file: 'candidate'}, verify=changed)
    assert file.read_text() == 'original'
    assert ('dev/team/iam' if change == 'scope' else f'`{change}`') in (tmp_path / name).read_text(), 'rollback must not undo an external contract edit'



@pytest.mark.parametrize('state', [None, 'running', 'completed', 'suspend'])
def check_legacy_publication_preserves_contract(tmp_path, monkeypatch, state):
    from model_templates import publish
    name = 'tasks/active.md'
    text = contract('active', ['file.txt'])
    if state is None:
        text = text.replace('- Task status: `running`\n', '')
    else:
        text = text.replace('`running`', f'`{state}`')
        if state == 'suspend':
            text += '## Suspension reason\nExplicit test stop\n'
    own = tmp_path / name
    own.parent.mkdir()
    own.write_text(text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    file = tmp_path / 'file.txt'
    file.write_text('original')
    new = tmp_path / 'new.txt'
    obsolete = tmp_path / 'obsolete.txt'
    obsolete.write_text('keep')
    if state in ('completed', 'suspend'):
        if state == 'completed':
            assert tasks.task_path(tmp_path) == own
            assert tasks.task_revision(tmp_path) == (name, text)
        with pytest.raises(ValueError, match=f'{state} task'):
            publish(tmp_path, {file: 'saved', new: 'new'}, obsolete=[obsolete])
        assert file.read_text() == 'original' and not new.exists()
        assert obsolete.read_text() == 'keep'
    else:
        assert tasks.task_path(tmp_path) == own
        publish(tmp_path, {file: 'saved'})
        assert file.read_text() == 'saved'
    assert own.read_text() == text
    monkeypatch.delenv(tasks.SELECTOR)
    standalone = tmp_path / 'standalone'
    standalone.mkdir()
    publish(standalone, {standalone / 'file.txt': 'without contract'})
    assert (standalone / 'file.txt').read_text() == 'without contract'



def check_source_guard_keeps_plan_consistency(tmp_path, monkeypatch):
    from model_templates import publish
    import import_guard
    name = 'tasks/owner.md'
    source = tmp_path / 'model/parameters/dev/team/iam/parameters.yaml'
    tasks.start(tmp_path, name, contract('owner', [source.relative_to(tmp_path).as_posix()]))
    monkeypatch.setenv(tasks.SELECTOR, name)
    def guard(*args, **kwargs):
        own = tmp_path / name
        own.write_text(own.read_text().replace('- `framework`', '- `dev/team/iam`'))
    with patch.object(import_guard, 'require_import_changes', guard):
        with pytest.raises(ValueError, match='scope changed'):
            publish(tmp_path, {source: 'instances: {}\n'})
    assert not source.exists()



def check_scope_change_during_planning(tmp_path, monkeypatch):
    from model_templates import publish
    name = 'tasks/example.md'
    tasks.start(tmp_path, name, contract('example', ['file.txt']))
    monkeypatch.setenv(tasks.SELECTOR, name)
    expected = tasks.task_revision(tmp_path)
    own = tmp_path / name
    own.write_text(own.read_text().replace('- `framework`', '- `dev/team/iam`'))
    with pytest.raises(ValueError, match='scope changed'):
        publish(tmp_path, {tmp_path / 'file.txt': 'candidate'}, expected_task=expected)
    assert not (tmp_path / 'file.txt').exists()
    own.write_text(own.read_text().replace('`running`', '`completed`'))
    assert tasks.task_path(tmp_path) == own
    expected = tasks.task_revision(tmp_path)
    assert expected[1] == own.read_text()
    with pytest.raises(ValueError, match='completed task cannot write'):
        publish(tmp_path, {tmp_path / 'file.txt': 'candidate'}, expected_task=expected)
    assert not (tmp_path / 'file.txt').exists()


if __name__ == '__main__':
    raise SystemExit(run(__file__))
