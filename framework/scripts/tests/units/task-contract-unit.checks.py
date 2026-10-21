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
from model.importing import scope as import_scope
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
            empty = tmp_path / 'stage-without-contracts'
            empty.mkdir()
            assert import_scope.selected(empty) is None
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
                from model.sources import edit_base, FileReads
                with pytest.raises(ValueError, match='outside selected'):
                    edit_base(tmp_path / 'model/dev/team/config.properties', FileReads())
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
            assert import_scope.selected(tmp_path) is None  # Scope reads do not resume execution.
            with pytest.raises(ValueError, match='suspend task'):
                tasks.task_path(tmp_path)
    exercise()



def generation_plan(root, output):
    """Unit candidate fixture; real Model/view preparation is exercised by IT."""
    from types import SimpleNamespace
    from generation_inputs import GenerationInputs
    snapshot = GenerationInputs(root)
    for path in output:
        snapshot.read(path)
    return SimpleNamespace(root=root, stage=root, snapshot=snapshot, expected_outputs={next(iter(output)): output},
                           saved={}, failures=[], generated={})


@pytest.mark.parametrize('change', ['scope', 'completed', 'suspend'])
def check_task_change_rolls_back_publication(tmp_path, monkeypatch, change):
    from sync_runtime import publish_generation
    name = 'tasks/owner.md'
    file = tmp_path / 'file.txt'
    file.write_text('original')
    tasks.start(tmp_path, name, contract('owner', ['file.txt']))
    monkeypatch.setenv(tasks.SELECTOR, name)
    plan = generation_plan(tmp_path, {file: 'candidate'})
    own = tmp_path / name
    text = own.read_text()
    own.write_text(text.replace('- `framework`', '- `dev/team/iam`') if change == 'scope' else
                   text.replace('`running`', f'`{change}`') +
                   ('## Suspension reason\nExplicit test stop\n' if change == 'suspend' else ''))
    with pytest.raises(ValueError, match='inputs changed'):
        publish_generation(plan)
    assert file.read_text() == 'original'
    assert ('dev/team/iam' if change == 'scope' else f'`{change}`') in own.read_text()




@pytest.mark.parametrize('state', ['running', 'completed', 'suspend'])
def check_publication_preserves_contract(tmp_path, monkeypatch, state):
    from sync_runtime import publish_generation
    name = 'tasks/example.md'
    text = contract('example', ['file.txt'])
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
        with pytest.raises(ValueError, match='task cannot write|suspend task'):
            publish_generation(generation_plan(tmp_path, {file: 'saved', new: 'new'}))
        assert file.read_text() == 'original' and not new.exists() and obsolete.read_text() == 'keep'
    else:
        assert tasks.task_path(tmp_path) == own
        publish_generation(generation_plan(tmp_path, {file: 'saved'}))
        assert file.read_text() == 'saved'
    assert own.read_text() == text
    monkeypatch.delenv(tasks.SELECTOR)
    standalone = tmp_path / 'standalone'
    standalone.mkdir()
    publish_generation(generation_plan(standalone, {standalone / 'file.txt': 'without contract'}))
    assert (standalone / 'file.txt').read_text() == 'without contract'




def check_source_guard_keeps_plan_consistency(tmp_path, monkeypatch):
    from sync_runtime import publish_generation
    name = 'tasks/owner.md'
    source = tmp_path / 'model/dev/team/iam.properties'
    tasks.start(tmp_path, name, contract('owner', [source.relative_to(tmp_path).as_posix()]))
    monkeypatch.setenv(tasks.SELECTOR, name)
    plan = generation_plan(tmp_path, {source: '# model-format: 2\n'})
    own = tmp_path / name
    own.write_text(own.read_text().replace('- `framework`', '- `dev/team/iam`'))
    with pytest.raises(ValueError, match='inputs changed'):
        publish_generation(plan)
    assert not source.exists()




def check_scope_change_during_planning(tmp_path, monkeypatch):
    from sync_runtime import publish_generation
    name = 'tasks/example.md'
    tasks.start(tmp_path, name, contract('example', ['file.txt']))
    monkeypatch.setenv(tasks.SELECTOR, name)
    plan = generation_plan(tmp_path, {tmp_path / 'file.txt': 'candidate'})
    own = tmp_path / name
    own.write_text(own.read_text().replace('- `framework`', '- `dev/team/iam`'))
    with pytest.raises(ValueError, match='inputs changed'):
        publish_generation(plan)
    assert not (tmp_path / 'file.txt').exists()
    own.write_text(own.read_text().replace('`running`', '`completed`'))
    assert tasks.task_path(tmp_path) == own
    expected = tasks.task_revision(tmp_path)
    assert expected[1] == own.read_text()
    with pytest.raises(ValueError, match='completed task cannot write'):
        publish_generation(generation_plan(tmp_path, {tmp_path / 'file.txt': 'candidate'}))
    assert not (tmp_path / 'file.txt').exists()



def check_batch_operation_contract():
    import json
    from dataclasses import FrozenInstanceError
    base = ('## Task contract\n- Task type: `design`\n- Workflow: `update`\n'
            '- Model operation: `import-merge`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n')
    pairs = [{'source': 'test/primary/network/' + left, 'destination': 'test/primary/network/' + right}
             for left, right in [('022', '009'), ('023', '010'), ('024', '011'), ('025', '012'), ('028', '013')]]
    pair_text = '## Model merge pairs\n' + ''.join('- ' + json.dumps(pair) + '\n' for pair in pairs)
    reference = {'consumer': 'test/primary/subnet/020', 'field': 'document', 'property': 'EC2.Subnet.Policy',
                 'pointer': '/Statement/0/Resource', **pairs[0]}
    ref_text = '## Model reference changes\n- ' + json.dumps(reference) + '\n'
    operation = tasks.model_operation(base + pair_text + ref_text)
    assert operation.scope == ('test', 'primary', 'network') and len(operation.pairs) == 5
    assert operation.references[0].pointer == '/Statement/0/Resource'
    with pytest.raises(FrozenInstanceError):
        operation.action = 'import-delete'
    deletion = base.replace('import-merge', 'import-delete') + '## Model delete sources\n- `' + pairs[0]['source'] + '`\n'
    assert tasks.model_operation(deletion).delete_sources == (pairs[0]['source'],)
    malformed = [
        base + '## Model merge pairs\n',
        base + pair_text + pair_text,
        pair_text,
        base + pair_text + 'trailing junk\n',
        base + pair_text.replace('"022"', '"009"') + ref_text + ref_text,
        base + pair_text.replace('network/023', 'network/009'),
        base + pair_text.replace('network/023', 'network/022'),
        base + pair_text.replace('network/010', 'network/009'),
        base + pair_text.replace('"source":', '"source": null, "source":', 1),
        base + pair_text.replace('"source":', '"extra": NaN, "source":', 1),
        base + pair_text + ref_text.replace('/Statement/0/Resource', ''),
        base + pair_text + ref_text.replace('/Statement/0/Resource', '/bad~2'),
        base + pair_text + ref_text.replace('subnet/020', 'network/022'),
        deletion + '## Model reference changes\n',
        base.replace('- Model operation:', '- Model operation :') + pair_text,
    ]
    for text in malformed:
        with pytest.raises(ValueError):
            tasks.model_operation(text)
    assert tasks.model_operation('## Goal\nFree prose with Model merge pairs is unrestricted.\n') is None


def check_dependency_detach_contract():
    from support.import_model_fixtures import dependency_contract
    text = dependency_contract()
    parsed = tasks.model_refactor(text)
    assert len(parsed) == 1 and parsed[0].key == 'desired.row.002-001.value'
    assert tasks.final_model_task(text) and tasks.model_operation(text) is None
    assert tasks.model_refactor('## Task contract\n- Task type: `design`\n') is None
    for bad in [text.replace('forbidden', 'allowed', 1), text.replace('design', 'infrastructure'),
                text.replace('value-preserving', 'automatic'), text.replace('Model refactor:', 'Model refactor :'),
                text.replace('service-a/001', 'service-a/999/001'), text.replace('002-001', '003-001'),
                text + text[text.index('## Model dependency detach'):],
                text.replace('"key":', '"key": null, "key":'),
                text.replace('"key":', '"unknown": NaN, "key":'),
                text.replace('"key":', '"pointer": "/bad~2", "key":'),
                text.replace('## Model dependency detach', '## Model dependency detach extra'),
                text.replace('## Model dependency detach', '- Model operation: `import-merge`\n## Model dependency detach'),
                text.split('## Model dependency detach')[0] + '## Model dependency detach\n',
                text + 'unconsumed junk\n']:
        with pytest.raises(ValueError):
            tasks.model_refactor(bad)


if __name__ == '__main__':
    raise SystemExit(run(__file__))
