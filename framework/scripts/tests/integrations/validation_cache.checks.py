#!/usr/bin/env python3
"""Raw Model/dependency bytes invalidate validation without changing saved values."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from support.it_case_receipt import it_case
from support.validation_cache_fixtures import *
from support.producer_identifier_reference_fixtures import setup, resource, reference
from model.sources import load_model, design_source_digest, source_inputs
from model.format import FORMAT, INDEX, serialize


@it_case
def main():
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as directory:
        root = Path(temporary).resolve()
        setup(root, ('sqs', 'kms'), ('SQS.Queue', 'KMS.Key'), environments=('dev',))
        docs = root / 'docs/designs/dev/team'
        docs.mkdir(parents=True)
        design, model = docs / 'sqs.md', root / 'model/dev/team/sqs.properties'
        design.write_text('[Reference](kms.md#key)\n', encoding='utf-8')
        (docs / 'kms.md').write_text('<a id="key"></a>\n', encoding='utf-8')
        write_model(model, resource('001', 'SQS.Queue', 'sqs', [('QueueName', '`first`')]))
        entry = ('dev', 'team', 'sqs')
        before = PassCache(root, directory=directory).service_key(entry)
        (docs / 'kms.md').write_text('<a id="changed"></a>\n', encoding='utf-8')
        assert PassCache(root, directory=directory).service_key(entry) != before
        body = model.read_text()
        part = model.with_suffix('') / 'part-003.properties'
        part.parent.mkdir()
        part.write_text(body)
        model.write_text(FORMAT + '\n' + INDEX + '\n# part: sqs/part-003.properties\n')
        before = PassCache(root, directory=directory).service_key(entry)
        part.write_text(body.replace('`first`', '`changed`'))
        assert PassCache(root, directory=directory).service_key(entry) != before
    print('validation-cache: PASS (references, stable part names and raw bytes)')


@it_case
def check_producer_inputs():
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as directory:
        root = Path(temporary).resolve()
        setup(root, ('lambda', 'eventbridge', 'cloudtrail', 'sqs'),
              ('Lambda.Function', 'Events.Rule', 'CloudTrail.Trail', 'SQS.Queue'), environments=('preview', 'release'))
        paths = {}
        for environment in ('preview', 'release'):
            for service, kind in (('lambda', 'Lambda.Function'), ('eventbridge', 'Events.Rule'),
                                  ('cloudtrail', 'CloudTrail.Trail'), ('sqs', 'SQS.Queue')):
                path = root / 'model' / environment / 'team' / (service + '.properties')
                prop = 'FunctionName' if service == 'lambda' else 'QueueName' if service == 'sqs' else 'Name'
                values = resource('001', kind, service + '-fixture', [(prop, '`fixture`')])
                if service in ('eventbridge', 'cloudtrail'):
                    key = 'desired.row.001-002.document'
                    text = '[Function](lambda.md#lambda-fixture)'
                    values.update({'desired.row.001-002.property': kind + '.Target',
                                   'desired.row.001-002.comment': '保存済み参照', 'desired.row.001-002.value': '`document`',
                                   key: '{"Target":"' + text + '","Enabled":false,"Count":1,"Order":["b","a"]}'})
                    values.update(reference('target', key, text, 'lambda', '001', 'Lambda.Function', mode='link',
                                            pointer='/Target', environment=environment, label='fixed'))
                write_model(path, values)
                doc = root / 'docs/designs' / environment / 'team' / (service + '.md')
                doc.parent.mkdir(parents=True, exist_ok=True)
                doc.write_text('fixture\n')
                paths[environment, 'team', service] = path
        producer = paths['preview', 'team', 'lambda']
        part = producer.with_suffix('') / 'part-001.properties'
        part.parent.mkdir()
        part.write_bytes(producer.read_bytes())
        producer.write_text(FORMAT + '\n' + INDEX + '\n# part: lambda/part-001.properties\n')
        cache = PassCache(root, directory=directory)
        before = {entry: cache.service_key(entry) for entry in paths}
        values = {entry: load_model(path).values for entry, path in paths.items()}
        digests = {entry: design_source_digest(path) for entry, path in paths.items()}
        inputs = source_inputs(producer)
        assert part in inputs
        assert inputs <= source_inputs(paths['preview', 'team', 'eventbridge'])
        for source in sorted(inputs):
            original = source.read_bytes()
            try:
                source.write_bytes(original + b'\n')
                for entry, path in paths.items():
                    changed = source == root / 'project.json' or entry[2] != 'sqs' and entry[0] == 'preview'
                    assert (cache.service_key(entry) != before[entry]) == changed, (source, entry)
                    assert design_source_digest(path) == digests[entry], (source, entry)
                    assert load_model(path).values == values[entry], (source, entry)
            finally:
                source.write_bytes(original)
        assert {entry: cache.service_key(entry) for entry in paths} == before


if __name__ == '__main__':
    main()
    check_producer_inputs()
