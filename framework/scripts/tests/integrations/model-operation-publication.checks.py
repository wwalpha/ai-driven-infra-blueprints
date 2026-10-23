#!/usr/bin/env python3
"""Offline integration through the official IT runner."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import json
import socket
import subprocess
from unittest.mock import patch
import pytest
import sync_files
from model.format import parse, serialize
from model.sources import load_model
from support.import_model_fixtures import TARGET

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('live network forbidden')))
    from support.import_repository_fixtures import repositories
    def no_subprocess(*args, **kwargs):
        raise AssertionError('Model value/save IT must not start subprocesses')
    monkeypatch.setattr(subprocess, 'Popen', no_subprocess)
    with repositories(monkeypatch):
        yield
    assert 'support.worktree_task_fixtures' not in sys.modules


def source_files(root):
    return {p.relative_to(root): p.read_bytes() for p in (root / 'model').rglob('*') if p.is_file()}

@pytest.mark.parametrize('failure', ['none', 'rollback', 'race', 'wrong-target', 'ordinary', 'ordinary-delete'])
def check_model_only_publication(tmp_path, monkeypatch, failure):
    from support.import_model_fixtures import operation_fixture, operation_candidate, operation_contract
    from support.import_repository_fixtures import fixture, start
    from model import prepare_edit, publish_edit
    from model.adapters.task import source_write_context, edit_write_context
    from model.operations import verify_model_operation
    from task_contract import model_operation, status
    action = 'import-delete' if failure == 'ordinary-delete' else 'import-merge'
    with fixture() as root:
        operation_fixture(root)
        sources = operation_candidate(root, tmp_path / 'edited', action)
        candidate = {name: (tmp_path / 'edited' / name).read_text() for name in sources}
        target, state = start(root)
        name = state['task_file']
        contract = operation_contract(destination='stg/cde/vpc/008' if failure == 'wrong-target' else 'stg/cde/vpc/001')
        if failure in {'ordinary', 'ordinary-delete'}:
            contract = '## Task contract\n- Task type: `design`\n- Task status: `running`\n'
        contract += '\n## Required changes\n- [R1] Synthetic source candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n'
        for heading in ('Modified files', 'Allowed paths'):
            contract += '\n## ' + heading + '\n' + ''.join('- `' + item + '`\n' for item in sorted(sources | {name}))
        contract += '\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n'
        (target / name).write_text(contract)
        before = source_files(target)
        path = target / 'model/stg/cde/vpc.properties'
        if failure == 'rollback':
            def fail_save(output):
                path.write_text('partial interrupted source')
                raise OSError('injected source publication failure')
            monkeypatch.setattr(sync_files, 'save_files', fail_save)
        authority = edit_write_context(target, {('stg', TARGET, 'vpc')}, name) if failure in {'ordinary', 'ordinary-delete'} else source_write_context(target, name)
        with authority as context:
            snapshot = load_model(path, context.snapshot)
            output = {target / relative: text for relative, text in candidate.items()}
            def save():
                plan = prepare_edit(snapshot, output, context)
                if failure == 'race':
                    path.write_bytes(path.read_bytes() + b'# concurrent human input\n')
                return publish_edit(plan, context)
            if failure not in {'none', 'ordinary', 'ordinary-delete'}:
                with pytest.raises((ValueError, OSError)):
                    save()
                if failure == 'race':
                    assert path.read_bytes() == before[path.relative_to(target)] + b'# concurrent human input\n'
                else:
                    assert source_files(target) == before
            else:
                assert set(save()) == set(output)
                expected_id = 'vpc-source'
                if action == 'import-delete':
                    expected_id = 'vpc-stg'
                assert load_model(path).authoritative['observed.row.001-001.value'] == expected_id
                if failure == 'none':
                    verify_model_operation(root, target, model_operation(contract), sources)
                assert status((target / name).read_text()) == 'running'
        assert source_files(root) == before


def check_intermediate_model_sources(monkeypatch):
    import base64
    from support.import_repository_fixtures import fixture, start
    from support.import_model_fixtures import operation_fixture, operation_contract
    from model import prepare_edit, publish_edit
    from model.adapters.task import source_write_context
    from model.sources import publication_lock
    with fixture() as root:
        operation_fixture(root)
        relative = 'model/stg/cde/vpc.properties'
        target, state = start(root)
        name = state['task_file']
        text = operation_contract() + '\n## Validation scope\n- `stg/cde/vpc`\n'
        for heading in ('Modified files', 'Allowed paths'):
            text += '\n## ' + heading + '\n- `' + name + '`\n- `' + relative + '`\n'
        (target / name).write_text(text)
        path = target / relative
        original = path.read_bytes()
        values = dict(load_model(path).authoritative)
        values['desired.row.001-002.comment'] = '中間保存は最終設計検証を実行しない'
        intermediate = serialize(values)
        with source_write_context(target, name) as context:
            publish_edit(prepare_edit(load_model(path, context.snapshot), {path: intermediate}, context), context)
        assert path.read_text() == intermediate
        with source_write_context(target, name) as context:
            plan = prepare_edit(load_model(path, context.snapshot), {path: original.decode()}, context)
            with patch.object(sync_files, 'save_files', side_effect=OSError('second leaf failed')):
                with pytest.raises(OSError, match='second leaf failed'):
                    publish_edit(plan, context)
        assert path.read_text() == intermediate
        assert (root / relative).read_bytes() == original
        with publication_lock(target) as journal:
            journal.write_text(json.dumps({'root': str(target.resolve()), 'originals': {relative: base64.b64encode(original).decode()}}))
            path.write_text('interrupted write')
        with pytest.raises(ValueError, match='recovery'):
            load_model(path)
        with source_write_context(target, name) as context:
            assert context.snapshot.read(path) == original
            assert publish_edit(prepare_edit(load_model(path, context.snapshot), {}, context), context) == ()
        assert path.read_bytes() == original


def check_batch_leaf_saves(monkeypatch):
    import tempfile
    from support.import_repository_fixtures import fixture, start
    from support.import_model_fixtures import batch_operation_fixture
    from model import prepare_edit, publish_edit
    from model.adapters.task import source_write_context
    from model.operations import verify_model_operation
    from model.format import owner
    from task_contract import model_operation
    with fixture() as root, tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary) / 'candidate'
        contract, sources = batch_operation_fixture(root, candidate)
        target, state = start(root)
        name = state['task_file']
        for heading in ('Modified files', 'Allowed paths'):
            contract += '\n## ' + heading + '\n' + ''.join('- `' + item + '`\n' for item in sorted(sources | {name}))
        contract += '\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n'
        (target / name).write_text(contract)
        path = target / 'model/stg/cde/vpc.properties'
        before = dict(load_model(path).authoritative)
        final = parse((candidate / 'model/stg/cde/vpc.properties').read_text()).values
        operation = model_operation(contract)
        deleted = {pair.source.rsplit('/', 1)[1] for pair in operation.pairs}
        transferred = dict(final)
        transferred.update({key: value for key, value in before.items() if owner(key, before) in {('resource', rid) for rid in deleted}})
        # Keep original Resource/Row order while retaining the pending source deletions.
        transferred = {key: transferred[key] for key in before if key in transferred}
        with source_write_context(target, name) as context:
            publish_edit(prepare_edit(load_model(path, context.snapshot), {path: serialize(transferred)}, context), context)
        for rid in deleted:
            assert f'desired.resource.{rid}.resourceType' in load_model(path).authoritative
        with source_write_context(target, name) as context:
            assert publish_edit(prepare_edit(load_model(path, context.snapshot), {}, context), context) == ()
        with source_write_context(target, name) as context:
            publish_edit(prepare_edit(load_model(path, context.snapshot), {path: serialize(final)}, context), context)
        for rid in deleted:
            assert f'desired.resource.{rid}.resourceType' not in load_model(path).authoritative
        verify_model_operation(root, target, operation, sources)
        from model.importing.repository import working_revision
        assert working_revision(root) == state['start']


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
