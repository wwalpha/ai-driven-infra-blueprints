#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.validation_cache_fixtures import *

import model_templates as templates
from model_files import load_model
from support.model_sources import write_fixture_files

@it_case
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


@it_case
def check_producer_inputs():
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as directory:
        root = Path(temporary).resolve()
        paths = {}
        for environment in ('preview', 'release'):
            for service, kind in (('lambda', 'Lambda.Function'), ('eventbridge', 'Events.Rule'),
                                  ('cloudtrail', 'CloudTrail.Trail'), ('sqs', 'SQS.Queue')):
                path = root/'model'/environment/'team'/(service+'.properties')
                reference = service in ('eventbridge', 'cloudtrail')
                write_model(path, (
                    '# reference: Function {"service":"lambda","resource":"001","resourceType":"Lambda.Function"}\n'
                    if reference else '') +
                    f'desired.resource.001.resourceType={kind}\n'
                    f'desired.resource.001.anchor={service}-fixture\n'
                    'desired.row.001-001.property='+kind+'.'+
                    ('FunctionName' if service == 'lambda' else 'Name')+'\n'
                    'desired.row.001-001.value=`fixture`\n'+
                    ('desired.note.target.text=<<Function>>\n'
                     'desired.note.target.document={"Target":"<<Function>>","Enabled":false,"Count":1,"Order":["b","a"]}\n'
                     if reference else ''))
                write_fixture_files({
                    root/'docs/designs'/environment/'team'/(service+'.md'): 'fixture\n',
                    root/'model/parameters'/environment/'team'/service/'observed.json':
                        templates.json_text({'version': 1, 'values': {}}),
                })
                paths[environment, 'team', service] = path
        template = root/'model/templates/team/lambda.properties.tpl'
        part = template.parent/'lambda.properties/part-001.properties'
        part.parent.mkdir()
        part.write_bytes(template.read_bytes())
        template.write_text('# model-index: 1\n# part: lambda.properties/part-001.properties\n')
        cache = PassCache(root, directory=directory)
        before = {entry: cache.service_key(entry) for entry in paths}
        values = {entry: load_model(path).values for entry, path in paths.items()}
        digests = {entry: templates.design_source_digest(path) for entry, path in paths.items()}
        producer = paths['preview', 'team', 'lambda']
        inputs = templates.source_inputs(producer)
        assert part in inputs
        assert inputs <= templates.source_inputs(paths['preview', 'team', 'eventbridge'])
        for source in sorted(inputs):
            original = source.read_bytes()
            try:
                # Byte changes must invalidate dependencies even when resolved values stay equal.
                source.write_bytes(original+b'\n')
                shared = source.is_relative_to(root/'model/templates')
                for entry, path in paths.items():
                    changed = entry[2] != 'sqs' and (shared or entry[0] == 'preview')
                    assert (cache.service_key(entry) != before[entry]) == changed, (source, entry)
                    assert (templates.design_source_digest(path) != digests[entry]) == changed, (source, entry)
                    assert load_model(path).values == values[entry], (source, entry)
            finally:
                source.write_bytes(original)
        assert {entry: cache.service_key(entry) for entry in paths} == before


if __name__ == "__main__":
    main()
    check_producer_inputs()

