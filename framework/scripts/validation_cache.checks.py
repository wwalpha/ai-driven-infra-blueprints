#!/usr/bin/env python3
"""Small runnable checks for content-addressed results and invocation-local inputs."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from test_support.model_sources import write_model
import os
from pathlib import Path
import tempfile

from validation_cache import PassCache, digest_files, input_scope
from design_catalog import design_material_files
from model_core import entries


def main():
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as directory:
        root = Path(temporary).resolve()
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
        docs = root / "docs/designs/dev/cde"
        models = root / "model/dev/cde"
        docs.mkdir(parents=True); models.mkdir(parents=True)
        design = docs / "sqs.md"
        model = models / "sqs.properties"
        design.write_text("[Reference](kms.md#key)\n", encoding="utf-8")
        (docs / "kms.md").write_text('<a id="key"></a>\n', encoding="utf-8")
        write_model(model, "desired.value=first\n")
        entry = ("dev", "cde", "sqs")
        before = PassCache(root, directory=directory).service_key(entry)
        (docs / "kms.md").write_text('<a id="changed"></a>\n', encoding="utf-8")
        assert PassCache(root, directory=directory).service_key(entry) != before
        template = root/'model/templates/cde/sqs.properties.tpl'
        body = template.read_text()
        part_dir = template.parent/'sqs.properties'
        part_dir.mkdir()
        part = part_dir/'part-001.properties'
        part.write_text(body)
        template.write_text('# model-index: 1\n# part: sqs.properties/part-001.properties\n')
        before = PassCache(root, directory=directory).service_key(entry)
        part.write_text(body.replace('desired.value=first', 'desired.value=changed'))
        assert PassCache(root, directory=directory).service_key(entry) != before
        try:
            PassCache(root, directory=root / "cache")
        except ValueError:
            pass
        else:
            raise AssertionError("cache directory inside repository accepted")
    print("validation-cache: PASS (content, corruption, file sets, references, parts, fresh mode, input lifetime)")


if __name__ == "__main__":
    main()
