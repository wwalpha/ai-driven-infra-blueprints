#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.validation_cache_fixtures import *

def main():
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as directory:
        root = Path(temporary).resolve()
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
    print("validation-cache: PASS (content, corruption, file sets, references, parts, fresh mode, input lifetime)")


if __name__ == "__main__":
    main()

