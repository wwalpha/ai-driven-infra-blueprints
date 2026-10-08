#!/usr/bin/env python3
"""Small runnable checks for content-addressed results and invocation-local inputs."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

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
        first.write_text("SQS.Queue.QueueName=\n", encoding="utf-8")
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
        cache.save(key, 0)
        assert cache.load(key) is None
        old_stat = first.stat()
        first.write_text("SQS.Queue.QueueNamo=\n", encoding="utf-8")
        os.utime(first, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        assert PassCache(root, directory=directory).key("catalog") != key, "same size/mtime must not reuse stale content"
        original = digest_files(root, [first])
        missing = materials / "new.properties"
        assert digest_files(root, [first, missing]) != original
        missing.write_text("", encoding="utf-8")
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
        model.write_text("desired.value=first\n", encoding="utf-8")
        entry = ("dev", "cde", "sqs")
        before = PassCache(root, directory=directory).service_key(entry)
        (docs / "kms.md").write_text('<a id="changed"></a>\n', encoding="utf-8")
        assert PassCache(root, directory=directory).service_key(entry) != before
        part_dir = models / "sqs"
        part_dir.mkdir()
        (part_dir / "part-001.properties").write_text("desired.value=split\n", encoding="utf-8")
        model.write_text("# model-index: 1\n# part: sqs/part-001.properties\n", encoding="utf-8")
        before = PassCache(root, directory=directory).service_key(entry)
        (part_dir / "part-001.properties").write_text("desired.value=changed\n", encoding="utf-8")
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
