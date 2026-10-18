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


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
