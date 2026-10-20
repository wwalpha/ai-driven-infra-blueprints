#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.validation_cache_fixtures import *

def check_cache_inputs(tmp_path):
    root = tmp_path
    with tempfile.TemporaryDirectory() as directory:
        materials = root / "framework/materials/aws"
        materials.mkdir(parents=True)
        first = materials / "SQS_Queue.properties"
        (first).write_text("SQS.Queue.QueueName=\n", encoding="utf-8")
        cache = PassCache(root, directory=directory)
        key = cache.key("catalog")
        assert cache.load(key) is None
        cache.save(key, 17)
        assert cache.load(key) == 17
        assert PassCache(root, fresh=True, directory=directory).load(key) is None
        record = Path(directory) / f"{key}.json"
        for corrupted in ('{', 'null', '[]', '{"version":1,"checks":true}'):
            record.write_text(corrupted, encoding="utf-8")
            assert cache.load(key) is None
        bytecode = root/"framework/scripts/__pycache__/fixture.cpython.pyc"
        bytecode.parent.mkdir(parents=True,exist_ok=True);bytecode.write_bytes(b"generated cache")
        assert PassCache(root,directory=directory).key("catalog")==key
        bytecode.write_bytes(b"regenerated cache")
        assert PassCache(root,directory=directory).key("catalog")==key
        cache.save(key, 0)
        assert cache.load(key) is None
        old_stat = first.stat()
        (first).write_text("SQS.Queue.QueueNamo=\n", encoding="utf-8")
        os.utime(first, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        assert PassCache(root, directory=directory).key("catalog") != key, "same size/mtime must not reuse stale content"
        for relative in ("README.md", ".agents/skills/worktree/SKILL.md", "framework/rules/task-contract.md"):
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
        original = digest_files(root, [first])
        missing = materials / "new.properties"
        assert digest_files(root, [first, missing]) != original
        (missing).write_text("", encoding="utf-8")
        assert digest_files(root, [first, missing]) != original
        missing.unlink()

        @input_scope
        def read_inputs(values):
            assert design_material_files(root) is design_material_files(root)
            extracted = entries(values, "desired.row.")
            extracted[0][1]["value"] = "caller mutation"
            return entries(values, "desired.row.")
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



def check_retained_common_key(tmp_path):
    from sync_runtime import GenerationInputs
    root = tmp_path/'project'
    root.mkdir()
    definitions = tmp_path/'definitions'
    rule = definitions/'.agents/skills/task/SKILL.md'
    rule.parent.mkdir(parents=True)
    rule.write_bytes(b'original rules')
    (definitions/'AGENTS.md').write_bytes(b'original agents')
    path = root/'framework/catalog.json'
    path.parent.mkdir()
    path.write_bytes(b'{}\n')
    snapshot = GenerationInputs(root, definitions)
    cache = PassCache(root, definitions_root=definitions)
    retained = cache.common_key(snapshot=snapshot)
    assert retained == cache.common_key()
    unrelated = root/'tests/results/unrelated.log'
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b'unrelated')
    assert unrelated not in snapshot.contents
    assert cache.common_key() == retained
    snapshot.verify()
    from validation_cache import recording_inputs, input_bytes
    assert snapshot.contents[rule] == b'original rules'
    assert snapshot.contents[definitions/'AGENTS.md'] == b'original agents'
    rule.write_bytes(b'changed rules')
    with recording_inputs(snapshot):
        assert input_bytes(rule) == b'original rules'
    assert cache.common_key() != retained
    rule.write_bytes(b'original rules')
    path.write_bytes(b'[]\n')
    assert cache.common_key(snapshot=snapshot) == retained
    assert cache.common_key() != retained
    try:
        snapshot.verify()
    except ValueError as error:
        assert 'framework/catalog.json' in str(error)
    else:
        raise AssertionError('changed common inputs accepted')

    # Contract reuse belongs only to a read-only invocation, never to authority saves.
    from unittest.mock import patch
    import task_contract as tasks
    import import_scope
    from validation_cache import input_context, memoized
    project = tmp_path/'contracts'
    (project/'tasks').mkdir(parents=True)
    def contract(name, service):
        return f'''## Task contract
- Task type: `migration`
- Task status: `running`
- Workflow: `import`
- IMPORT target: `dev/cde/{service}`
## Modified files
- `tasks/{name}.md`
## Allowed paths
- `tasks/{name}.md`
## Validation scope
- `dev/cde/{service}`
'''
    first = project/'tasks/first.md'
    second = project/'tasks/second.md'
    original = contract('first', 'sqs')
    first.write_text(original)
    second.write_text(contract('second', 's3'))
    @import_scope.scoped_read
    @memoized
    def read(path, context=None):
        return object()
    with tasks.selected_task(project, 'tasks/first.md'), input_context():
        with patch.object(tasks, '_contracts', wraps=tasks._contracts) as scans, \
                patch.object(tasks, '_select_contract', wraps=tasks._select_contract) as selections:
            with tasks.contract_reads(project):
                for _ in range(1000):
                    assert import_scope.selected(project) == ('dev', 'cde', 'sqs')
                assert scans.call_count == 1
                assert selections.call_count == 1
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


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
