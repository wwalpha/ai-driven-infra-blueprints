#!/usr/bin/env python3
"""Parent deletion transactions use synthetic sources; no consumer checkout or AWS."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import json
import shutil
from contextlib import nullcontext
from unittest.mock import patch
import pytest
import yaml
import task_contract as tasks
import worktree_task as wt
from model_operation_checks import verify_model_operation
from model_sources import read_sources, write_sources
from import_guard import source_write_context
from support.import_model_fixtures import (metadata, declaration, binding, save_service, spec,
    operation_contract, dependency_fixture, dependency_refactor, dependency_contract)


def contract(sources, references=(), detaches=()):
    text = operation_contract('import-delete').split('- Source resource:')[0]
    if detaches:
        text += '- Model refactor: `value-preserving`\n'
    text += '## Model delete sources\n' + ''.join('- `' + source + '`\n' for source in sources)
    for heading, records in [('Model reference changes', references), ('Model dependency detach', detaches)]:
        if records:
            text += '## ' + heading + '\n' + ''.join('- ' + json.dumps(record) + '\n' for record in records)
    return text


def fixture(root, multiple=False):
    fields = {'name': ('Name', '<<Name>>')}
    empty = {'definition': 'Metadata', 'resources': {}, 'rows': {}, 'parameters': {}}
    services = ['service-a']
    count = 10
    if multiple:
        services.append('service-b')
        count = 5
    sources = []
    for service in services:
        template = ['# model-template: 1'] + metadata(service, ['Example.Resource'])
        template += declaration('Resource', 'Example.Resource', fields, {'Name': spec(), 'ResourceMode': spec()})
        for env in ('dev', 'stg'):
            parameters, bindings, observed = {'instances': {}}, {'instances': {'service': empty}}, {}
            for index in range(1, count + 2):
                rid = str(index).zfill(3)
                instance = 'resource-' + rid
                parameters['instances'][instance] = {'parameters': {'Name': env + '-' + rid, 'ResourceMode': 'IMPORT'}}
                bindings['instances'][instance] = binding('Resource', rid, fields, 'resource-' + rid)
                observed['observed.row.' + rid + '-001.value'] = 'observed-' + rid
                if env == 'stg' and index <= count:
                    sources.append('stg/cde/' + service + '/' + rid)
            save_service(root, service, template, parameters, bindings, observed, environment=env)
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': env, 'alias': 'cde', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}
        for env in ('dev', 'stg')]}))
    return sources


def deletion(root, address):
    env, target, service, rid = address.split('/')
    directory = root / 'model/parameters' / env / target / service
    files = {name: directory / name for name in ('parameters.yaml', 'bindings.json', 'observed.json')}
    bindings = json.loads(files['bindings.json'].read_text())
    parameters = yaml.safe_load(files['parameters.yaml'].read_text())
    names = [name for name, record in bindings['instances'].items() if rid in record['resources'].values()]
    for name in names:
        del bindings['instances'][name]
        parameters['instances'].pop(name, None)
    result = {files['bindings.json']: json.dumps(bindings), files['parameters.yaml']: yaml.safe_dump(parameters)}
    if files['observed.json'].exists():
        observed = json.loads(files['observed.json'].read_text())
        observed['values'] = {key: value for key, value in observed['values'].items() if not key.startswith('observed.row.' + rid + '-')}
        result[files['observed.json']] = json.dumps(observed)
    return result


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
    assert (before / 'model/parameters/dev').exists()
    for source_scope in operation.source_scopes:
        current = json.loads((after / 'model/parameters' / '/'.join(source_scope) / 'bindings.json').read_text())
        assert len(current['instances']) == 2  # Metadata plus the untouched survivor.


@pytest.mark.parametrize('bad', ['duplicate', 'empty', 'cross-target', 'legacy-mixed', 'merge', 'reference-unrelated', 'detach-unrelated'])
def check_contract_rejects_unscoped_deletion(bad):
    sources = ['stg/cde/service-a/001', 'stg/cde/service-b/002']
    text = contract(sources)
    if bad == 'duplicate':
        text += '- `' + sources[0] + '`\n'
    elif bad == 'empty':
        text = contract([])
    elif bad == 'cross-target':
        text = text.replace('stg/cde/service-b', 'dev/cde/service-b')
    elif bad == 'legacy-mixed':
        text = text.replace('## Model delete sources', '- Source resource: `' + sources[0] + '`\n## Model delete sources')
    elif bad == 'merge':
        text = text.replace('import-delete', 'import-merge')
    elif bad == 'reference-unrelated':
        text = contract(sources, [{'consumer': 'stg/cde/service-c/003', 'field': 'value', 'property': 'Example.Resource.Name',
                                   'source': 'stg/cde/service-a/099', 'destination': 'stg/cde/service-a/004'}])
    elif bad == 'detach-unrelated':
        text = contract(sources, detaches=[{'consumer': 'stg/cde/service-c/003', 'producer': 'stg/cde/service-a/099', 'key': 'desired.row.003-001.value'}])
    with pytest.raises(ValueError):
        tasks.model_operation(text)


def check_legacy_and_detach_normalization():
    old = tasks.model_operation(operation_contract('import-delete'))
    new = tasks.model_operation(contract(['stg/cde/vpc/009']))
    assert old == new and old.delete_source == 'stg/cde/vpc/009'
    text = dependency_contract().replace('## Model dependency detach', '- Model operation: `import-delete`\n- Source resource: `stg/cde/service-a/001`\n## Model dependency detach')
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
    directory = after / 'model/parameters/stg/cde/service-a'
    if mutation == 'extra-delete':
        save(deletion(after, 'stg/cde/service-a/011'))
    elif mutation in {'setting', 'shared-consumer'}:
        if mutation == 'shared-consumer':
            directory = after / 'model/parameters/dev/cde/service-a'
        path = directory / 'parameters.yaml'
        values = yaml.safe_load(path.read_text())
        values['instances']['resource-011']['parameters']['Name'] = 'changed'
        path.write_text(yaml.safe_dump(values))
    elif mutation == 'identity':
        path = directory / 'bindings.json'
        values = json.loads(path.read_text())
        values['instances']['resource-011']['parameters']['Anchor'] = 'changed'
        path.write_text(json.dumps(values))
    elif mutation == 'observation':
        path = directory / 'observed.json'
        values = json.loads(path.read_text())
        values['values']['observed.row.011-001.value'] = 'changed'
        path.write_text(json.dumps(values))
    with pytest.raises(ValueError):
        verify_model_operation(before, after, tasks.model_operation(contract(sources)), changed(before, after))


def check_related_detach_and_two_consumers(tmp_path):
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    directory = before / 'model/parameters/stg/cde/service-b'
    parameters = yaml.safe_load((directory / 'parameters.yaml').read_text())
    bindings = json.loads((directory / 'bindings.json').read_text())
    parameters['instances']['second'] = copy.deepcopy(parameters['instances']['consumer'])
    bindings['instances']['second'] = binding('Consumer', '004', {'name': ('Name', '<<Origin>>')}, 'second')
    save({directory / 'parameters.yaml': yaml.safe_dump(parameters), directory / 'bindings.json': json.dumps(bindings)})
    after.mkdir()
    dependency_refactor(before, after)
    directory = after / 'model/parameters/stg/cde/service-b'
    parameters = yaml.safe_load((directory / 'parameters.yaml').read_text())
    parameters['instances']['second'] = copy.deepcopy(parameters['instances']['consumer'])
    bindings = json.loads((directory / 'bindings.json').read_text())
    bindings['instances']['second']['definition'] = 'Detached'
    save({directory / 'parameters.yaml': yaml.safe_dump(parameters), directory / 'bindings.json': json.dumps(bindings)})
    save(deletion(after, 'stg/cde/service-a/001'))
    detaches = [{'consumer': 'stg/cde/service-b/' + rid, 'producer': 'stg/cde/service-a/001', 'key': 'desired.row.' + rid + '-001.value'} for rid in ('002', '004')]
    operation = tasks.model_operation(contract(['stg/cde/service-a/001'], detaches=detaches))
    verify_model_operation(before, after, operation, changed(before, after))
    # The shared Definition must leave the dev consumer's original reference intact.
    path = after / 'model/templates/cde/service-b.properties.tpl'
    path.write_text(path.read_text().replace('desired.row.name.value=<<Origin>>', 'desired.row.name.value=`unrelated`'))
    with pytest.raises(ValueError):
        verify_model_operation(before, after, operation, changed(before, after))


def check_remaining_reference_is_warning(tmp_path):
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    shutil.copytree(before, after)
    save(deletion(after, 'stg/cde/service-a/001'))
    warnings = verify_model_operation(before, after, tasks.model_operation(contract(['stg/cde/service-a/001'])), changed(before, after))
    assert any(item['code'] == 'reference.target_removed' for item in warnings)


@pytest.mark.parametrize('failure', ['syntax', 'io'])
def check_fifth_save_failure_retains_first_four(tmp_path, failure):
    sources = fixture(tmp_path, True)
    name = 'tasks/parent.md'
    paths = sorted({path.relative_to(tmp_path).as_posix() for source in sources for path in deletion(tmp_path, source)})
    listed = '\n'.join('- `' + path + '`' for path in [name, *paths])
    text = contract(sources) + '## Validation scope\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n## Modified files\n' + listed + '\n## Allowed paths\n' + listed + '\n'
    tasks.start(tmp_path, name, text)
    state = {'task_file': name, 'worktree': str(tmp_path), 'merged': None}
    with patch.object(wt, 'load', return_value=(tmp_path, None, None, state)), patch.object(wt, 'task_worktree', return_value=tmp_path), \
         patch.object(wt, 'finalize', side_effect=AssertionError('leaf cannot finalize')), \
         patch('model_templates.load_expansion', side_effect=AssertionError('raw leaf must not expand')):
        for source in sources[:4]:
            with source_write_context(tmp_path, name) as context:
                write_sources(context, deletion(tmp_path, source))
        saved = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
        with source_write_context(tmp_path, name) as context:
            edits = deletion(tmp_path, sources[4])
            path = next(path for path in edits if path.name == 'parameters.yaml')
            if failure == 'syntax':
                edits[path] = 'instances: [\n'
                with pytest.raises(ValueError):
                    write_sources(context, edits)
            else:
                original_write = Path.write_text
                def fail_partial_write(destination, content, *args, **kwargs):
                    if destination == path:
                        raise OSError('injected fifth leaf write failure')
                    return original_write(destination, content, *args, **kwargs)
                with patch.object(Path, 'write_text', fail_partial_write), pytest.raises(OSError, match='fifth leaf'):
                    write_sources(context, edits)
        assert all(path.read_bytes() == content for path, content in saved.items())
        assert tasks.status((tmp_path / name).read_text()) == 'running'
        # Resume the same parent; each next save sees the preceding successful sources.
        for source in sources[4:]:
            with source_write_context(tmp_path, name) as context:
                write_sources(context, deletion(tmp_path, source))


def check_finalize_rejects_incomplete_leaves(tmp_path):
    sources = fixture(tmp_path)
    name = 'tasks/parent.md'
    (tmp_path / 'tasks').mkdir()
    (tmp_path / name).write_text(contract(sources))
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
    path = after / 'model/parameters/stg/cde/service-b/parameters.yaml'
    values = yaml.safe_load(path.read_text())
    values['instances']['consumer']['parameters']['Origin'] = '003'
    path.write_text(yaml.safe_dump(values))
    save(deletion(after, 'stg/cde/service-a/001'))
    references = [{'consumer': 'stg/cde/service-b/002', 'field': 'value', 'property': 'ServiceB.Resource.Name',
                   'source': 'stg/cde/service-a/001', 'destination': 'stg/cde/service-a/003'}]
    operation = tasks.model_operation(contract(['stg/cde/service-a/001'], references))
    verify_model_operation(before, after, operation, changed(before, after))
    with pytest.raises(ValueError, match='scope|undeclared'):
        verify_model_operation(before, after, tasks.model_operation(contract(['stg/cde/service-a/001'])), changed(before, after))


def check_delete_issue_exception_is_service_scoped(tmp_path):
    from issue_gate import task_issue_errors
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


@pytest.mark.parametrize('repair', [False, True])
def check_one_parent_merge_and_failed_candidate_repair(repair):
    from support.worktree_task_fixtures import fixture as git_fixture, git
    from import_guard import require_import_changes
    from utils.aws_mappings import mapping_alias
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
                write_sources(context, deletion(target, source))
        def final_check(repository, options, *, final_candidate):
            try:
                with tasks.selected_task(repository, name):
                    require_import_changes(repository, final_candidate=final_candidate)
            except ValueError:
                return 1
            return 0
        original_git = wt.git
        with mapping_alias(Path(__file__).resolve().parents[4], target), patch.object(wt, 'git', wraps=original_git) as calls, patch('validation.loop.run_loop', side_effect=final_check) as validation:
            first_head = None
            if repair:
                path = target / 'model/parameters/stg/cde/service-a/observed.json'
                original = path.read_text()
                values = json.loads(original)
                values['values']['observed.row.006-001.value'] = 'unauthorized'
                path.write_text(json.dumps(values))
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
