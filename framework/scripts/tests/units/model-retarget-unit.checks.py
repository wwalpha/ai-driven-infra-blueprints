#!/usr/bin/env python3
"""Standalone retarget contracts and guards use only authored temporary authorities."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
import json
import shutil
from unittest.mock import patch
import pytest
import yaml
from task_contract import model_operation
from model.operations import verify_model_operation, prepare_edit, publish_edit
from support.import_model_fixtures import dependency_fixture
from model.sources import load_model
from model.format import serialize, owner
from support.model_sources import write_model

REF = {'consumer': 'stg/cde/service-b/002', 'field': 'value', 'property': 'ServiceB.Resource.Name',
       'source': 'stg/cde/service-a/001', 'destination': 'stg/cde/service-a/003'}


def contract(refs=None):
    return ('## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `update`\n'
            '- Model operation: `import-retarget`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n'
            '## Model reference changes\n' + ''.join('- ' + json.dumps(r) + '\n' for r in (refs if refs is not None else [REF])))


def fixture(tmp_path, document=False):
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    for env in ('dev', 'stg'):
        file = before / 'model' / env / 'cde/service-a.properties'
        values = dict(load_model(file).authoritative)
        write_model(file, {key: value for key, value in values.items() if not key.startswith('desired.row.001-002.')})
    if document:
        file = before / 'model/stg/cde/service-b.properties'
        values = dict(load_model(file).authoritative)
        values['desired.row.002-001.value'] = '[JSON](service-b/policy.json)'
        values['desired.row.002-001.document'] = '{"Items":["same-name-stg","keep"],"Enabled":true}'
        values['desired.reference.origin.consumerKey'] = 'desired.row.002-001.document'
        values['desired.reference.origin.pointer'] = '/Items/0'
        write_model(file, values)
    shutil.copytree(before, after)
    file = after / 'model/stg/cde/service-b.properties'
    values = dict(load_model(file).authoritative)
    values['desired.reference.origin.producerId'] = '003'
    write_model(file, values)
    return before, after, {file.relative_to(after).as_posix()}


def check_standalone_contract():
    operation = model_operation(contract())
    assert operation.action == 'import-retarget' and operation.pairs == () and operation.delete_source is None
    assert operation.references[0].consumer == REF['consumer']
    for text in [contract([]), contract([REF, REF]), contract([{**REF, 'source': REF['destination']}]),
                 contract([{**REF, 'destination': 'dev/cde/service-a/003'}]),
                 contract([{**REF, 'field': 'parentReference', 'property': None}]),
                 contract() + '## Model merge pairs\n- {"source":"stg/cde/service-a/001","destination":"stg/cde/service-a/003"}\n',
                 contract().replace('## Model reference changes', '- Source resource: `stg/cde/service-a/001`\n## Model reference changes'),
                 contract([{**REF, 'property': '*'}]), contract() + 'trailing junk\n']:
        with pytest.raises(ValueError):
            model_operation(text)


@pytest.mark.parametrize('document', [False, True])
def check_preserves_producers_and_equal_renderings(tmp_path, document):
    before, after, sources = fixture(tmp_path, document)
    refs = [{**REF, 'field': 'document', 'pointer': '/Items/0'}] if document else [REF]
    verify_model_operation(before, after, model_operation(contract(refs)), sources)
    old = load_model(before / 'model/stg/cde/service-a.properties').values
    new = load_model(after / 'model/stg/cde/service-a.properties').values
    assert old == new  # Both producers survive, despite equal name renderings.


@pytest.mark.parametrize('failure', ['mismatch', 'missing', 'no-change', 'unused', 'literal', 'order', 'sibling', 'type',
    'settings', 'observed', 'bindings', 'delete', 'transfer', 'other-env', 'unused-input', 'format', 'ambiguous', 'overlap'])
def check_rejects_unsafe_candidates(tmp_path, failure):
    document = failure in {'order', 'sibling', 'type', 'overlap'}
    before, after, sources = fixture(tmp_path, document)
    refs = [{**REF, 'field': 'document', 'pointer': '/Items/0'}] if document else [dict(REF)]
    file = after / 'model/stg/cde/service-b.properties'
    values = dict(load_model(file).authoritative)
    if failure == 'mismatch':
        refs[0]['source'] = REF['destination']
    elif failure == 'missing':
        refs[0]['destination'] = 'stg/cde/service-a/099'
    elif failure == 'no-change':
        values['desired.reference.origin.producerId'] = '001'
    elif failure == 'unused':
        refs.append({**REF, 'property': 'ServiceB.Resource.Absent'})
    elif failure == 'literal':
        values = {key: value for key, value in values.items() if not key.startswith('desired.reference.origin.')}
    elif failure in {'order', 'sibling', 'type'}:
        values['desired.row.002-001.document'] = {
            'order': '{"Items":["keep","same-name-stg"],"Enabled":true}',
            'sibling': '{"Items":["same-name-stg","changed"],"Enabled":true}',
            'type': '{"Items":["same-name-stg","keep"],"Enabled":1}'}[failure]
        if failure == 'order':
            values['desired.reference.origin.pointer'] = '/Items/1'
    elif failure == 'overlap':
        refs.append({**refs[0], 'pointer': '/Items/00'})
    elif failure == 'unused-input':
        values['desired.note.unrelated.text'] = 'changed'
    elif failure == 'format':
        values['desired.reference.origin.format'] = 'identifier'
    elif failure == 'ambiguous':
        values['desired.resource.002.anchor'] = 'changed-fixed-anchor'
    else:
        target = after / ('model/dev/cde/service-b.properties' if failure == 'other-env' else 'model/stg/cde/service-a.properties')
        other = dict(load_model(target).authoritative)
        if failure in {'settings', 'transfer'}:
            other['desired.row.001-001.value'] = 'changed' if failure == 'settings' else 'transferred'
        elif failure == 'observed':
            other['observed.row.001-001.value'] = 'fabricated'
        elif failure == 'bindings':
            other['desired.resource.003.logicalId'] = 'changed-fixed'
        elif failure == 'delete':
            other = {key: value for key, value in other.items() if owner(key, other) != ('resource', '001')}
        elif failure == 'other-env':
            other['desired.reference.origin.producerId'] = '003'
        write_model(target, other)
    write_model(file, values)
    sources |= {p.relative_to(after).as_posix() for p in after.rglob('*') if p.is_file() and
                (not (before / p.relative_to(after)).exists() or p.read_bytes() != (before / p.relative_to(after)).read_bytes())}
    if failure == 'no-change':
        assert verify_model_operation(before, after, model_operation(contract(refs)), sources)
    else:
        with pytest.raises((ValueError, KeyError)):
            verify_model_operation(before, after, model_operation(contract(refs)), sources)


@pytest.mark.parametrize('field', ['value', 'document'])
def check_json_positions(tmp_path, field):
    before, after, sources = fixture(tmp_path, True)
    if field == 'value':
        for root in (before, after):
            file = root / 'model/stg/cde/service-b.properties'
            values = dict(load_model(file).authoritative)
            values['desired.row.002-001.value'] = '`' + values.pop('desired.row.002-001.document') + '`'
            values['desired.reference.origin.consumerKey'] = 'desired.row.002-001.value'
            write_model(file, values)
    refs = [{**REF, 'field': field, 'pointer': '/Items/0'}]
    verify_model_operation(before, after, model_operation(contract(refs)), sources)
    refs[0]['pointer'] = '/Items'
    with pytest.raises(ValueError):
        verify_model_operation(before, after, model_operation(contract(refs)), sources)


def check_route_table_pair_example(tmp_path):
    from support.model_sources import write_model
    before, after = tmp_path / 'before', tmp_path / 'after'
    before.mkdir()
    (before / 'project.json').write_text(json.dumps({'targets': [{'environment': 'stg', 'alias': 'cde',
        'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
    values = {}
    for rid in ('009', '010', '022', '023'):
        values.update({f'desired.resource.{rid}.resourceType': 'EC2.RouteTable',
                       f'desired.resource.{rid}.resourceMode': 'IMPORT',
                       f'desired.resource.{rid}.anchor': 'table-' + rid,
                       f'desired.row.{rid}-001.property': 'EC2.RouteTable.RouteTableId',
                       f'desired.row.{rid}-001.value': f'[{rid}](#table-{rid})',
                       f'desired.row.{rid}-001.comment': '合成fixture',
                       f'observed.row.{rid}-001.value': '`rtb-' + rid + '`'})
    write_model(before / 'model/stg/cde/vpc.properties', values)
    endpoint = {'desired.resource.001.resourceType': 'EC2.VPCEndpoint',
                'desired.resource.001.resourceMode': 'IMPORT', 'desired.resource.001.anchor': 'endpoint'}
    for index, rid in enumerate(('009', '010'), 1):
        endpoint.update({f'desired.row.001-{index:03d}.property': f'EC2.VPCEndpoint.RouteTableIds[{index}]',
                         f'desired.row.001-{index:03d}.value': f'[{rid}](vpc.md#table-{rid})',
                         f'desired.row.001-{index:03d}.comment': '合成fixture'})
    write_model(before / 'model/stg/cde/vpc-endpoint.properties', endpoint)
    shutil.copytree(before, after)
    template = after / 'model/stg/cde/vpc-endpoint.properties'
    template.write_text(template.read_text().replace('[009](vpc.md#table-009)', '[022](vpc.md#table-022)').replace('[010](vpc.md#table-010)', '[023](vpc.md#table-023)'))
    sources = {template.relative_to(after).as_posix()}
    refs = [{'consumer': 'stg/cde/vpc-endpoint/001', 'field': 'value',
             'property': f'EC2.VPCEndpoint.RouteTableIds[{index}]',
             'source': 'stg/cde/vpc/' + source, 'destination': 'stg/cde/vpc/' + destination}
            for index, source, destination in ((1, '009', '022'), (2, '010', '023'))]
    verify_model_operation(before, after, model_operation(contract(refs)), sources)
    with pytest.raises(ValueError):
        verify_model_operation(before, after, model_operation(contract(refs[:1])), sources)


@pytest.mark.parametrize('mode', ['success', 'reuse', 'conflict', 'new-file', 'task-change', 'wrong-owner', 'invalid', 'normal-save', 'mixed-save', 'missing-scope', 'issue', 'other-issue'])
def check_guarded_save(tmp_path, monkeypatch, mode):
    import subprocess
    import worktree_task
    from utils.aws_mappings import mapping_alias
    from model.adapters.task import source_write_context, edit_write_context
    from task_contract import start, selected_task
    before, after, sources = fixture(tmp_path)
    def git(*args):
        return subprocess.run(['git', *args], cwd=before, check=True, capture_output=True, text=True).stdout.strip()
    git('init'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
    git('add', '.'); git('commit', '-m', 'synthetic baseline')
    base = git('rev-parse', 'HEAD')
    inputs = before / next(iter(sources))
    candidate = (after / next(iter(sources))).read_text()
    name = 'tasks/retarget.md'
    listing = ''.join('- `' + p + '`\n' for p in [name, *sorted(sources)])
    scopes = ['stg/cde/service-b'] if mode == 'missing-scope' else ['stg/cde/service-a', 'stg/cde/service-b']
    if mode == 'other-issue':
        scopes.append('dev/cde/service-b')
    text = contract() + '## Validation scope\n' + ''.join('- `' + s + '`\n' for s in scopes) + '## Modified files\n' + listing + '## Allowed paths\n' + listing
    start(before, name, text)
    state = {'task_file': name, 'worktree': str(after if mode == 'wrong-owner' else before), 'merged': None}
    if mode in {'issue', 'other-issue'}:
        p = before / ('issues/dev/cde/issues.md' if mode == 'other-issue' else 'issues/stg/cde/issues.md')
        p.parent.mkdir(parents=True)
        p.write_text(('### service-b\n' if mode == 'other-issue' else '### service-a\n') + '1. existing issue\n')
    with patch.object(worktree_task, 'load', return_value=(before, None, None, state)), \
         patch.object(worktree_task, 'task_worktree', return_value=before), \
         patch.object(worktree_task, 'task_start_commit', return_value=base), \
         mapping_alias(Path(__file__).resolve().parents[4], before), selected_task(before, name):
        if mode in {'wrong-owner', 'missing-scope', 'issue', 'other-issue'}:
            with pytest.raises(ValueError):
                with source_write_context(before, name):
                    pass
            return
        if mode == 'normal-save':
            with pytest.raises(ValueError, match='limited source write context'):
                with edit_write_context(before, {('stg', 'cde', 'service-b')}, name):
                    pass
            with source_write_context(before, name) as context:
                publish_edit(prepare_edit(load_model(inputs, context.snapshot), {inputs: candidate}, context), context)
            assert inputs.read_text() == candidate
            return
        if mode == 'mixed-save':
            with source_write_context(before, name) as context, pytest.raises(ValueError, match='unregistered'):
                prepare_edit(load_model(inputs, context.snapshot), {inputs: candidate, before / 'docs/designs/stg/cde/service-b.md': 'fake'}, context)
            return
        original = inputs.read_text()
        with source_write_context(before, name) as context:
            snapshot = load_model(inputs, context.snapshot)
            plan = prepare_edit(snapshot, {inputs: original if mode == 'invalid' else candidate}, context)
            if mode == 'conflict':
                inputs.write_text(original + '# concurrent edit\n')
            if mode == 'new-file':
                extra = before / 'model/stg/cde/service-b/part-001.properties'
                extra.parent.mkdir()
                extra.write_text('# model-format: 2\n')
            if mode == 'task-change':
                (before / name).write_text(text + '\n## Goal\nchanged\n')
            if mode in {'conflict', 'new-file', 'task-change'}:
                with pytest.raises(ValueError):
                    publish_edit(plan, context)
                assert inputs.read_text() == (original + '# concurrent edit\n' if mode == 'conflict' else original)
            elif mode == 'invalid':
                assert publish_edit(plan, context) == () and inputs.read_text() == original
            else:
                assert publish_edit(plan, context) == (inputs,) and inputs.read_text() == candidate
            with pytest.raises(ValueError, match='consumed'):
                publish_edit(plan, context)
        if mode == 'reuse':
            with source_write_context(before, name) as context:
                assert publish_edit(prepare_edit(load_model(inputs, context.snapshot), {inputs: candidate}, context), context) == ()


def check_final_candidate_uses_latest_base(tmp_path):
    import subprocess
    from types import SimpleNamespace
    import import_guard
    import worktree_task
    from task_contract import start, selected_task, final_model_task
    from utils.aws_mappings import mapping_alias
    before, after, sources = fixture(tmp_path)
    def git(*args):
        return subprocess.run(['git', *args], cwd=before, check=True, capture_output=True, text=True).stdout.strip()
    (before / '.gitignore').write_text('tasks/\n')
    git('init'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
    git('add', '.'); git('commit', '-m', 'creation baseline'); original_base = git('rev-parse', 'HEAD')
    producer = before / 'model/stg/cde/service-a.properties'
    producer.write_text(producer.read_text().replace('same-name-stg', 'latest-name'))
    git('add', '.'); git('commit', '-m', 'latest base settings'); latest = git('rev-parse', 'HEAD')
    relative = next(iter(sources)); (before / relative).write_bytes((after / relative).read_bytes())
    name = 'tasks/retarget.md'
    listing = ''.join('- `' + p + '`\n' for p in [name, relative])
    text = contract() + '## Validation scope\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n## Modified files\n' + listing + '## Allowed paths\n' + listing
    start(before, name, text)
    candidate = SimpleNamespace(base_commit=latest, changed_paths=frozenset(sources), scope={('stg', 'cde', 'service-a'), ('stg', 'cde', 'service-b')})
    assert final_model_task(text)
    with mapping_alias(Path(__file__).resolve().parents[4], before), selected_task(before, name), \
         patch.object(worktree_task, 'task_start_commit', return_value=original_base):
        import_guard.require_import_changes(before, final_candidate=candidate)
        candidate.base_commit = original_base
        with pytest.raises(ValueError): import_guard.require_import_changes(before, final_candidate=candidate)
        state = {'task_file': name, 'task_id': 'retarget'}
        with pytest.raises(worktree_task.Blocked, match='successful final candidate'):
            worktree_task._prepare_commit(before, before / 'unused-state.json', state, before, 'approval cannot bypass')
    assert producer.read_text().count('latest-name') == 2


@pytest.mark.parametrize('failure', ['wrong-type', 'create-producer', 'subnet', 'template-comment', 'unused-template'])
def check_additional_boundaries(tmp_path, failure):
    before, after, sources = fixture(tmp_path)
    refs = [dict(REF)]
    if failure in {'wrong-type', 'create-producer', 'subnet'}:
        for root in (before, after):
            file = root / ('model/stg/cde/service-b.properties' if failure == 'subnet' else 'model/stg/cde/service-a.properties')
            values = dict(load_model(file).authoritative)
            if failure == 'wrong-type':
                values['desired.resource.003.resourceType'] = 'Other.Resource'
            elif failure == 'create-producer':
                values['desired.resource.001.resourceMode'] = 'CREATE'
                values['desired.resource.003.resourceMode'] = 'CREATE'
            else:
                values['desired.row.002-001.property'] = 'ServiceB.Resource.SubnetId'
                refs[0]['property'] = 'ServiceB.Resource.SubnetId'
            write_model(file, values)
    elif failure == 'template-comment':
        file = after / 'model/stg/cde/service-a.properties'
        values = dict(load_model(file).authoritative)
        values['desired.row.001-001.comment'] = 'changed'
        write_model(file, values)
    else:
        for root in (before, after):
            write_model(root / 'model/stg/cde/unused.properties', {'desired.note.unused.text': 'changed' if root == after else 'unused'})
    sources |= {p.relative_to(after).as_posix() for p in after.rglob('*') if p.is_file() and
                (not (before / p.relative_to(after)).exists() or p.read_bytes() != (before / p.relative_to(after)).read_bytes())}
    if failure == 'wrong-type':
        assert verify_model_operation(before, after, model_operation(contract(refs)), sources)
    else:
        with pytest.raises(ValueError):
            verify_model_operation(before, after, model_operation(contract(refs)), sources)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
