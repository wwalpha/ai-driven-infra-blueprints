#!/usr/bin/env python3
"""Parent deletion transactions use synthetic sources; no consumer checkout or AWS."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import shutil
from contextlib import nullcontext
from unittest.mock import patch

import pytest
import task_contract_core as tasks
import worktree_state as ws
import worktree_task as wt
from import_guard import require_import_changes
from issue_gate import task_issue_errors
from model.adapters.task import source_write_context
from model.core import entries
from model.format import owner, serialize
from model.operations import prepare_edit, publish_edit, verify_model_operation
from model.sources import load_model, scope_for
from support.import_model_fixtures import (
    dependency_contract,
    dependency_fixture,
    dependency_refactor,
    operation_contract,
    reference_fields,
    resource_values,
    service_values,
)
from support.model_sources import write_model
from support.worktree_task_fixtures import fixture as git_fixture
from support.worktree_task_fixtures import git
from utils.aws_mappings import mapping_alias

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def contract(sources, references=(), detaches=()):
    text = operation_contract('import-delete').split('## Model merge pairs')[0].split('## Model delete sources')[0]
    if detaches:
        text += '- Model refactor: `value-preserving`\n'
    text += '## Model delete sources\n' + ''.join('- `' + source + '`\n' for source in sources)
    for heading, records in [('Model reference changes', references), ('Model dependency detach', detaches)]:
        if records:
            text += '## ' + heading + '\n' + ''.join('- ' + json.dumps(record) + '\n' for record in records)
    return text


def fixture(root, multiple=False):
    root.mkdir(parents=True, exist_ok=True)
    services = ['service-a', 'service-b'] if multiple else ['service-a']
    count = 5 if multiple else 10
    sources = []
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': env, 'alias': 'cde', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1',
         'iacEngine': 'cloudformation'} for env in ('dev', 'stg')]}))
    for service in services:
        for env in ('dev', 'stg'):
            values = service_values(service, ['Example.Resource'])
            for index in range(1, count + 2):
                rid = f'{index:03d}'
                values.update(resource_values(rid, 'Example.Resource', 'resource-' + rid, 'IMPORT', [('Name', env + '-' + rid)]))
                values[f'observed.row.{rid}-001.value'] = 'observed-' + rid
                if env == 'stg' and index <= count:
                    sources.append('stg/cde/' + service + '/' + rid)
            write_model(root / 'model' / env / 'cde' / (service + '.properties'), values)
    return sources


def deletion(root, address):
    env, target, service, rid = address.split('/')
    file = root / 'model' / env / target / (service + '.properties')
    values = dict(load_model(file).authoritative)
    return {file: serialize({key: value for key, value in values.items() if owner(key, values) != ('resource', rid)})}


def write_candidate(context, changes):
    scope = scope_for(next(iter(changes)))
    return publish_edit(prepare_edit(load_model(scope, context.snapshot), changes, context), context)


def save(changes):
    for path, text in changes.items():
        path.write_text(text, encoding='utf-8')


def changed(before, after):
    return {path.relative_to(after).as_posix() for path in after.rglob('*') if path.is_file()
            and (not (before / path.relative_to(after)).exists() or path.read_bytes() != (before / path.relative_to(after)).read_bytes())}


@pytest.mark.parametrize('multiple', [False, True])
def check_ten_deletions(tmp_path, multiple):
    before, after = tmp_path / 'before', tmp_path / 'after'
    sources = fixture(before, multiple)
    shutil.copytree(before, after)
    operation = tasks.model_operation(contract(sources))
    assert len(operation.delete_sources) == 10
    for address in sources:
        save(deletion(after, address))
    verify_model_operation(before, after, operation, changed(before, after))
    assert (before / 'model/dev').exists()
    for source_scope in operation.source_scopes:
        env, target, service = source_scope
        current = load_model(after / 'model' / env / target / (service + '.properties'))
        assert len(entries(current.authoritative, 'desired.resource.')) == 1
        assert current.authoritative['desired.service.' + service + '.serviceId'] == service


@pytest.mark.parametrize('bad', ['duplicate', 'empty', 'cross-target', 'merge', 'reference-unrelated', 'detach-unrelated'])
def check_contract_rejects_unscoped_deletion(bad):
    sources = ['stg/cde/service-a/001', 'stg/cde/service-b/002']
    text = contract(sources)
    if bad == 'duplicate':
        text += '- `' + sources[0] + '`\n'
    elif bad == 'empty':
        text = contract([])
    elif bad == 'cross-target':
        text = text.replace('stg/cde/service-b', 'dev/cde/service-b')
    elif bad == 'merge':
        text = text.replace('import-delete', 'import-merge')
    elif bad == 'reference-unrelated':
        text = contract(sources, [{'consumer': 'stg/cde/service-c/003', 'field': 'value', 'property': 'Example.Resource.Name',
                                   'source': 'stg/cde/service-a/099', 'destination': 'stg/cde/service-a/004'}])
    elif bad == 'detach-unrelated':
        text = contract(sources, detaches=[{'consumer': 'stg/cde/service-c/003', 'producer': 'stg/cde/service-a/099', 'key': 'desired.row.003-001.value'}])
    with pytest.raises(ValueError):
        tasks.model_operation(text)


def check_deletion_and_detach_normalization():
    old = tasks.model_operation(operation_contract('import-delete'))
    new = tasks.model_operation(contract(['stg/cde/vpc/009']))
    assert old == new and old.delete_sources == ('stg/cde/vpc/009',)
    text = dependency_contract().replace('## Model dependency detach', '- Model operation: `import-delete`\n## Model delete sources\n- `stg/cde/service-a/001`\n## Model dependency detach')
    operation = tasks.model_operation(text)
    assert operation.detaches == tasks.model_refactor(text)
    assert operation.scopes == {('stg', 'cde', 'service-a'), ('stg', 'cde', 'service-b')}


@pytest.mark.parametrize('mutation', ['missing', 'extra-delete', 'setting', 'identity', 'observation', 'shared-consumer'])
def check_final_rejects_unrequested_changes(tmp_path, mutation):
    before, after = tmp_path / 'before', tmp_path / 'after'
    sources = fixture(before)
    shutil.copytree(before, after)
    for source in sources:
        if mutation == 'missing' and source == sources[-1]:
            continue
        save(deletion(after, source))
    if mutation == 'extra-delete':
        save(deletion(after, 'stg/cde/service-a/011'))
    elif mutation != 'missing':
        file = after / ('model/dev/cde/service-a.properties' if mutation == 'shared-consumer' else 'model/stg/cde/service-a.properties')
        values = dict(load_model(file).authoritative)
        field = 'desired.row.011-001.value' if mutation in {'setting', 'shared-consumer'} else 'desired.resource.011.anchor' if mutation == 'identity' else 'observed.row.011-001.value'
        values[field] = 'changed'
        write_model(file, values)
    with pytest.raises(ValueError):
        verify_model_operation(before, after, tasks.model_operation(contract(sources)), changed(before, after))


def check_related_detach_and_two_consumers(tmp_path):
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    file = before / 'model/stg/cde/service-b.properties'
    values = dict(load_model(file).authoritative)
    values.update(resource_values('004', 'ServiceB.Resource', 'second', 'IMPORT', [('Name', 'same-name-stg')]))
    values.update(reference_fields('second', 'desired.row.004-001.value', 'same-name-stg', 'stg/cde/service-a/001'))
    write_model(file, values)
    dependency_refactor(before, after)
    file = after / file.relative_to(before)
    values = {key: value for key, value in load_model(file).authoritative.items() if not key.startswith('desired.reference.second.')}
    write_model(file, values)
    save(deletion(after, 'stg/cde/service-a/001'))
    detaches = [{'consumer': 'stg/cde/service-b/' + rid, 'producer': 'stg/cde/service-a/001', 'key': 'desired.row.' + rid + '-001.value'} for rid in ('002', '004')]
    operation = tasks.model_operation(contract(['stg/cde/service-a/001'], detaches=detaches))
    verify_model_operation(before, after, operation, changed(before, after))
    file = after / 'model/dev/cde/service-b.properties'
    values = dict(load_model(file).authoritative)
    values['desired.row.002-001.value'] = 'unrelated'
    write_model(file, values)
    with pytest.raises(ValueError):
        verify_model_operation(before, after, operation, changed(before, after))


def check_remaining_reference_is_warning(tmp_path):
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    shutil.copytree(before, after)
    save(deletion(after, 'stg/cde/service-a/001'))
    warnings = verify_model_operation(before, after, tasks.model_operation(contract(['stg/cde/service-a/001'])), changed(before, after))
    assert any(item['code'] == 'reference.mismatch' and 'absent' in item['message'] for item in warnings)


def _callback_check_fifth_save_failure_retains_first_four_fail_partial_write(original_write, path, /, destination, content, *args, **kwargs):
    if destination == path:
        raise OSError('injected fifth leaf write failure')
    return original_write(destination, content, *args, **kwargs)


@pytest.mark.parametrize('failure', ['syntax', 'io'])
def check_fifth_save_failure_retains_first_four(tmp_path, failure):
    sources = fixture(tmp_path, True)
    name = 'tasks/parent.md'
    paths = sorted({path.relative_to(tmp_path).as_posix() for source in sources for path in deletion(tmp_path, source)})
    listed = '\n'.join('- `' + path + '`' for path in [name, *paths])
    text = contract(sources) + '## Validation scope\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n## Modified files\n' + listed + '\n## Allowed paths\n' + listed + '\n'
    tasks.start(tmp_path, name, text)
    state = {'task_file': name, 'worktree': str(tmp_path), 'merged': None}
    with patch.object(ws, 'load', return_value=(tmp_path, None, None, state)), patch.object(ws, 'task_worktree', return_value=tmp_path), \
         patch.object(wt, 'finalize', side_effect=AssertionError('leaf cannot finalize')), \
         patch('model.operations.verify_model_operation', side_effect=AssertionError('leaf must not run final validation')), \
         patch.object(ws, 'output', return_value='synthetic-head'):
        for source in sources[:4]:
            with source_write_context(tmp_path, name) as context:
                write_candidate(context, deletion(tmp_path, source))
        saved = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
        with source_write_context(tmp_path, name) as context:
            edits = deletion(tmp_path, sources[4])
            path = next(iter(edits))
            if failure == 'syntax':
                edits[path] = '# model-format: 2\ninvalid\n'
                with pytest.raises(ValueError):
                    write_candidate(context, edits)
            else:
                original_write = Path.write_text
                fail_partial_write = _bind_framework_callback(_callback_check_fifth_save_failure_retains_first_four_fail_partial_write, original_write, path)
                with patch.object(Path, 'write_text', fail_partial_write), pytest.raises(OSError, match='fifth leaf'):
                    write_candidate(context, edits)
        assert all(path.read_bytes() == content for path, content in saved.items())
        assert tasks.status((tmp_path / name).read_text()) == 'running'
        # Resume the same parent; each next save sees the preceding successful sources.
        for source in sources[4:]:
            with source_write_context(tmp_path, name) as context:
                write_candidate(context, deletion(tmp_path, source))


def check_finalize_rejects_incomplete_leaves(tmp_path):
    sources = fixture(tmp_path)
    name = 'tasks/parent.md'
    (tmp_path / 'tasks').mkdir()
    (tmp_path / name).write_text(contract(sources) + '## Validation scope\n- `stg/cde/service-a`\n' +
        f'## Modified files\n- `{name}`\n## Allowed paths\n- `{name}`\n')
    state = {'task_file': name, 'python_setup': {'status': 'ready'}, 'merged': None}
    with patch.object(wt, 'load', return_value=(tmp_path, None, tmp_path / 'state.json', state)), \
         patch.object(wt, 'lifecycle_lock', return_value=nullcontext()), patch.object(wt, 'task_worktree', return_value=tmp_path), \
         patch.object(wt, '_prepare_commit', side_effect=AssertionError('incomplete leaves cannot commit')):
        with pytest.raises(wt.Blocked, match='leaves incomplete'):
            wt.prepare_integration(tmp_path, 'parent')


def check_related_retarget(tmp_path):
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    shutil.copytree(before, after)
    file = after / 'model/stg/cde/service-b.properties'
    values = dict(load_model(file).authoritative)
    values['desired.reference.origin.producerLogicalId'] = 'ServiceA_Resource_003'
    write_model(file, values)
    save(deletion(after, 'stg/cde/service-a/001'))
    references = [{'consumer': 'stg/cde/service-b/002', 'field': 'value', 'property': 'ServiceB.Resource.Name',
                   'source': 'stg/cde/service-a/001', 'destination': 'stg/cde/service-a/003'}]
    operation = tasks.model_operation(contract(['stg/cde/service-a/001'], references))
    verify_model_operation(before, after, operation, changed(before, after))
    with pytest.raises(ValueError, match='scope|undeclared'):
        verify_model_operation(before, after, tasks.model_operation(contract(['stg/cde/service-a/001'])), changed(before, after))


def check_delete_issue_exception_is_service_scoped(tmp_path):
    sources = fixture(tmp_path, True)
    name = 'tasks/parent.md'
    text = contract(sources) + ('## Validation scope\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n- `stg/cde/service-c`\n'
        '## Modified files\n- `' + name + '`\n## Allowed paths\n- `' + name + '`\n')
    tasks.start(tmp_path, name, text)
    issues = tmp_path / 'issues/stg/cde/issues.md'
    issues.parent.mkdir(parents=True)
    issues.write_text('### service-a\n1. Existing failure\n### service-b\n2. Existing failure\n### service-c\n3. Ordinary failure\n')
    selected = {('stg', 'cde', 'service-a'), ('stg', 'cde', 'service-b')}
    assert task_issue_errors(tmp_path, selected, task_file=name) == []
    errors = task_issue_errors(tmp_path, selected | {('stg', 'cde', 'service-c')}, task_file=name)
    assert len(errors) == 1 and 'service-c' in errors[0]


def _callback_check_one_parent_merge_and_failed_candidate_repair_final_check(name, /, repository, options, *, final_candidate):
    try:
        with tasks.selected_task(repository, name):
            require_import_changes(repository, final_candidate=final_candidate)
    except ValueError:
        return 1
    return 0


@pytest.mark.parametrize('repair', [False, True])
def check_one_parent_merge_and_failed_candidate_repair(repair):
    with git_fixture() as root:
        sources = fixture(root, True)
        git(root, 'add', 'model', 'project.json')
        git(root, 'commit', '-qm', 'synthetic sources')
        with patch.object(wt.python_env, 'setup', return_value={'status': 'ready'}):
            state = wt.create(root, 'parent')
        target = Path(state['worktree'])
        name = state['task_file']
        paths = sorted({path.relative_to(target).as_posix() for source in sources for path in deletion(target, source)})
        listed = '\n'.join('- `' + path + '`' for path in [name, *paths])
        text = contract(sources) + ('## Validation scope\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n'
            '## Modified files\n' + listed + '\n## Allowed paths\n' + listed + '\n')
        tasks.start(target, name, text)
        for source in sources:
            with source_write_context(target, name) as context:
                write_candidate(context, deletion(target, source))
        final_check = _bind_framework_callback(_callback_check_one_parent_merge_and_failed_candidate_repair_final_check, name)
        original_git = wt.git
        with mapping_alias(Path(__file__).resolve().parents[4], target), patch.object(wt, 'git', wraps=original_git) as calls, patch('validation.loop.run_loop', side_effect=final_check) as validation:
            first_head = None
            if repair:
                path = target / 'model/stg/cde/service-a.properties'
                original = path.read_text()
                values = dict(load_model(path).authoritative)
                values['observed.row.006-001.value'] = 'unauthorized'
                write_model(path, values)
                candidate = wt.prepare_integration(target, 'parent')
                result = wt.validate_final_candidate(candidate)
                assert result.returncode == 1
                with pytest.raises(wt.Blocked, match='no merge'):
                    wt.merge_validated_candidate(result)
                first_head = git(target, 'rev-parse', 'HEAD')
                assert git(root, 'rev-parse', 'HEAD') == candidate.base_commit
                assert target.is_dir()
                path.write_text(original)
            wt._integrate_model(target, 'parent')
            assert sum(call.args[1:2] == ('merge',) for call in calls.call_args_list) == 1
            expected = 1
            if repair:
                expected = 2
                assert git(target, 'rev-parse', 'HEAD^') == first_head
            assert validation.call_count == expected
            assert tasks.status((target / name).read_text()) == 'completed'
            assert git(root, 'rev-parse', 'HEAD') == git(target, 'rev-parse', 'HEAD')
        wt.cleanup(root, 'parent')
        assert not target.exists()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
