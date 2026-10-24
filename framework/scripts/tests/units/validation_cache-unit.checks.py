#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import task_contract_core as tasks
from model.importing import scope as import_scope
from support.pytest_cli import run
from support.validation_cache_fixtures import (
    PassCache,
    Path,
    design_material_files,
    entries,
    input_scope,
    os,
    sys,
    tempfile,
)
from utils.input_cache import input_context, memoized

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def _callback_check_cache_inputs_read_inputs(root, /, values):
    assert design_material_files(root) is design_material_files(root)
    extracted = entries(values, "desired.row.")
    extracted[0][1]["value"] = "caller mutation"
    return entries(values, "desired.row.")


def check_cache_inputs(tmp_path):
    root = tmp_path
    with tempfile.TemporaryDirectory() as directory:
        cache = PassCache(root, directory=directory)
        key = cache.key("catalog")
        assert cache.load(key) is None
        cache.save(key, 17)
        assert cache.load(key) == 17
        assert PassCache(root, fresh=True, directory=directory).load(key) is None
        bytecode = root/"__pycache__/fixture.cpython.pyc"
        bytecode.parent.mkdir(parents=True,exist_ok=True)
        bytecode.write_bytes(b"generated cache")
        assert PassCache(root,directory=directory).key("catalog")==key
        bytecode.write_bytes(b"regenerated cache")
        assert PassCache(root,directory=directory).key("catalog")==key
        cache.save(key, 0)
        assert cache.load(key) == 17
        for relative in ("README.md", "AGENTS.md", "project.json", ".agents/project/SKILL.md"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            before = PassCache(root, directory=directory).key("catalog")
            path.write_text("entry\n", encoding="utf-8")
            added = PassCache(root, directory=directory).key("catalog")
            assert added != before
            path.write_text("change\n", encoding="utf-8")
            assert PassCache(root, directory=directory).key("catalog") != added
            path.unlink()
            assert PassCache(root, directory=directory).key("catalog") == before
        read_inputs = (input_scope)(_bind_framework_callback(_callback_check_cache_inputs_read_inputs, root))
        values = {"desired.row.001-001.value": "first"}
        assert read_inputs(values)[0][1]["value"] == "first"
        values["desired.row.001-001.value"] = "second"
        assert read_inputs(values)[0][1]["value"] == "second", "later invocations must see edits"



def check_cache_location(tmp_path):
    root = tmp_path
    try:
        PassCache(root, directory=root / "cache")
    except ValueError:
        pass
    else:
        raise AssertionError("cache directory inside repository accepted")


def _project_rglob(path, pattern):
    assert path.name == '.agents', f'unexpected Framework scan: {path}'
    return iter(())


def check_cache_lifetime(tmp_path):
    root, definitions, directory = tmp_path / 'repo', tmp_path / 'definitions', tmp_path / 'cache'
    root.mkdir()
    source = root / 'source.txt'
    source.write_bytes(b'fixed input')
    directory.mkdir()
    cache = PassCache(root, directory=directory, definitions_root=definitions)
    with patch.object(Path, 'rglob', _project_rglob), input_context():
        key = cache.key('catalog')
        cache.save(key, 17)
        assert PassCache(root, directory=directory, definitions_root=definitions).load(key) == 17
        assert PassCache(root, fresh=True, directory=directory, definitions_root=definitions).load(key) is None
    with patch.object(Path, 'rglob', _project_rglob), input_context():
        assert cache.load(cache.key('catalog')) is None
        assert PassCache(root, directory=directory, definitions_root=definitions).load(key) is None
    with pytest.raises(ValueError, match='symlink inputs'):
        (root / 'README.md').symlink_to(source)
        PassCache(root, directory=directory).common_key()


def _check_retained_common_key_contract(name, service):
    return f'## Task contract\n- Task type: `migration`\n- Task status: `running`\n- Workflow: `import`\n- IMPORT target: `dev/cde/{service}`\n## Modified files\n- `tasks/{name}.md`\n## Allowed paths\n- `tasks/{name}.md`\n## Validation scope\n- `dev/cde/{service}`\n'


def _callback_check_retained_common_key_read(project, read_cached, /, path):
    import_scope.require_readable(project, path)
    return read_cached(path, import_scope.read_context(project))


def _callback_check_retained_common_key_read_cached(path, context):
    return object()


def check_retained_common_key(tmp_path):
    # Contract reuse belongs only to a read-only invocation, never to authority saves.

    project = tmp_path/'contracts'
    (project/'tasks').mkdir(parents=True)
    contract = _check_retained_common_key_contract
    first = project/'tasks/first.md'
    second = project/'tasks/second.md'
    original = contract('first', 'sqs')
    first.write_text(original)
    second.write_text(contract('second', 's3'))
    read_cached = (memoized)(_callback_check_retained_common_key_read_cached)
    read = _bind_framework_callback(_callback_check_retained_common_key_read, project, read_cached)
    with tasks.selected_task(project, 'tasks/first.md'), input_context():
        with patch.object(tasks, '_catalog', wraps=tasks._catalog) as scans, \
                patch.object(tasks, '_read_task', wraps=tasks._read_task) as selections:
            with tasks.contract_reads(project):
                for _ in range(1000):
                    assert import_scope.selected(project) == ('dev', 'cde', 'sqs')
                assert scans.call_count == 1
                assert selections.call_count == 2
                with tasks.selected_task(project, 'tasks/second.md'):
                    assert import_scope.selected(project) == ('dev', 'cde', 's3')
                assert import_scope.selected(project) == ('dev', 'cde', 'sqs')
                with import_scope.read_consumers({('dev', 'cde', 'sqs')}):
                    path = project/'model/dev/cde/sqs.properties'
                    before = import_scope.read_context(project)
                    cached = read(path)
                    with import_scope.reference_reader(path):
                        assert import_scope.read_context(project)[2] == path.absolute()
                        assert read(path) is not cached
                    assert import_scope.read_context(project) == before
                    assert read(path) is cached
                with import_scope.read_consumers({('dev', 'cde', 'sqs'), ('dev', 'cde', 'iam')}):
                    assert read(path) is not cached
                with tasks.selected_task(project, 'tasks/second.md'):
                    try:
                        read(path)
                    except ValueError as error:
                        assert 'outside selected' in str(error)
                    else:
                        raise AssertionError('cached result bypassed Task read permission')
                    with import_scope.reference_reader(path):
                        assert read(path) is not cached
                assert read(path) is cached
            assert scans.call_count == 2
        for change in ('content', 'line-endings', 'addition', 'deletion', 'selector'):
            try:
                with tasks.contract_reads(project):
                    assert import_scope.selected(project) == ('dev', 'cde', 'sqs')
                    if change == 'content':
                        first.write_text(contract('first', 'iam'))
                    elif change == 'line-endings':
                        first.write_bytes(original.replace('\n', '\r\n').encode('utf-8'))
                    elif change == 'addition':
                        (project/'tasks/third.md').write_text(contract('third', 'iam'))
                    elif change == 'deletion':
                        second.unlink()
                    else:
                        with patch.dict(os.environ, {tasks.SELECTOR: 'tasks/second.md'}):
                            tasks.verify_contract_reads(project)
            except ValueError as error:
                assert 'changed during validation' in str(error)
            else:
                raise AssertionError(f'contract {change} was not detected')
            finally:
                first.write_text(original)
                second.write_text(contract('second', 's3'))
                (project/'tasks/third.md').unlink(missing_ok=True)
        first.write_text(contract('first', 'iam'))
        with tasks.contract_reads(project):
            assert import_scope.selected(project) == ('dev', 'cde', 'iam')
        first.write_text(original)
        assert tasks.contracts(project)['tasks/first.md'] == original




@pytest.mark.parametrize('relative', ['model/dev/team/iam.properties', 'docs/designs/dev/team/iam.md',
                                       'docs/designs/dev/team/iam/policy.json',
                                       'docs/designs/dev/team/iam/extra.json', 'model/dev/team/iam/extra.properties'])
def check_service_cache_invalidation(tmp_path, relative):
    root, directory = tmp_path / 'repo', tmp_path / 'cache'
    design = root / 'docs/designs/dev/team/iam.md'
    source = root / 'model/dev/team/iam.properties'
    artifact = design.with_suffix('') / 'policy.json'
    source.parent.mkdir(parents=True)
    artifact.parent.mkdir(parents=True)
    (root / 'project.json').write_text('{"targets":[{"environment":"dev","alias":"team",'
                                       '"awsAccountId":"123456789012","awsRegion":"ap-northeast-1","iacEngine":"cloudformation"}]}\n')
    source.write_text('# model-format: 2\ndesired.service.iam.serviceId=iam\n'
                      'desired.service.iam.ownedCatalogResourceTypes=IAM.Role\ndesired.note.001.text=original\n')
    design.write_text('# Policy\n[policy](iam/policy.json)\n')
    artifact.write_text('{}\n')
    cache = PassCache(root, directory=directory)
    entry = ('dev', 'team', 'iam')
    target = root / relative
    original = target.read_bytes() if target.exists() else None
    with input_context():
        key = cache.service_key(entry)
        cache.save(key, 17)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((original or b'') + b'\n')
        changed = cache.service_key(entry)
        assert changed != key and cache.load(changed) is None
    if original is not None:
        target.unlink()
        with input_context(), pytest.raises(ValueError):
            cache.service_key(entry)


if __name__ == '__main__':
    raise SystemExit(run(__file__))
