#!/usr/bin/env python3
"""Saved attribute references, reciprocal dependencies and immutable read snapshots."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import *
from validation_cache import input_scope

KINDS = {'s3': ('S3.Bucket', 'BucketName'), 'cloudtrail': ('CloudTrail.Trail', 'TrailName'),
         'lambda': ('Lambda.Function', 'FunctionName'), 'eventbridge': ('Events.Rule', 'Name')}


def prepare(root):
    setup(root, [*KINDS, 'iam'], [*(kind for kind, _ in KINDS.values()), 'IAM.Role'])


def fixture(root, service, other=None, *, derived=False):
    kind, property_name = KINDS[service]
    path = root / 'model/preview/team' / (service + '.properties')
    name = (other if derived else service) + '-original'
    values = resource('001', kind, service + '-original', [(property_name, '`' + name + '`')])
    values['desired.note.input.text'] = '`' + service + '-original`'
    if other:
        producer_kind, producer_property = KINDS[other]
        link = f'[{other}-original]({other}.md#{other}-original)'
        values['desired.note.link.text'] = link
        values['desired.row.001-002.property'] = kind + '.Tags'
        values['desired.row.001-002.value'] = '[config](' + service + '/config.json)'
        values['desired.row.001-002.comment'] = '型と配列順序を保持する合成設定'
        key = 'desired.row.001-002.document'
        values[key] = json.dumps({'name': other + '-original', 'count': 2, 'enabled': False, 'items': ['a', 'b']})
        values.update(reference('Other', 'desired.note.link.text', link, other, '001', producer_kind, mode='link', label='display-name'))
        values.update(reference('OtherName', key, other + '-original', other, '001', producer_kind,
                                prop=producer_kind + '.' + producer_property, pointer='/name'))
        if derived:
            values.update(reference('name', 'desired.row.001-001.value', other + '-original', other, '001', producer_kind,
                                    prop=producer_kind + '.' + producer_property))
    write_model(path, values)
    return path, values


def rejected_read(root, action, phrase):
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    rejected(action, phrase)
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}


@it_case
def check_pair(root, first, second):
    prepare(root)
    consumer, values = fixture(root, first, second)
    producer, original = fixture(root, second, first)
    loaded = load_model(consumer)
    assert not loaded.warnings, loaded.warnings
    assert loaded.authoritative['desired.note.link.text'] == f'[{second}-original]({second}.md#{second}-original)'
    key = 'desired.row.001-002.document'
    config = json.loads(loaded.authoritative[key])
    assert config == {'name': second + '-original', 'count': 2, 'enabled': False, 'items': ['a', 'b']}
    assert type(config['count']) is int and type(config['enabled']) is bool
    assert load_model(producer).authoritative['desired.row.001-001.value'] == '`' + second + '-original`'
    assert producer in loaded.dependencies
    digest, dependencies = design_source_digest(consumer), dependency_hashes(consumer)
    changed = {**original, 'desired.row.001-001.value': '`' + second + '-changed`'}
    write_model(producer, changed)
    assert warning(consumer, 'differs').authoritative == loaded.authoritative
    assert design_source_digest(consumer) == digest and dependency_hashes(consumer) != dependencies
    assert ('preview', 'team', first) in affected(root, [producer.relative_to(root)])
    assert trace_model(consumer, key)['references']['OtherName']['producerScope'] == 'preview/team/' + second
    write_model(producer, original)
    assert dependency_hashes(consumer) == dependencies and load_model(consumer).authoritative == loaded.authoritative
    @input_scope
    def snapshot():
        pinned = load_model(consumer)
        write_model(producer, changed)
        assert load_model(consumer) is pinned
        assert pinned.dependencies[producer] == serialize(original).encode()
        reads = FileReads()
        reads.read(producer)
        producer.write_bytes(producer.read_bytes() + b'# concurrent source\n')
        rejected_read(root, reads.verify, 'input changed')
    snapshot()
    write_model(producer, original)
    raw = producer.read_bytes()
    producer.write_bytes(raw + b'desired.row.001-001.value=duplicate\n')
    rejected_read(root, lambda: load_model(consumer), 'duplicate')
    producer.write_bytes(raw)
    rejected_read(root, lambda: serialize({**original, 'desired.row.001-001.value': 17}), 'strings')
    producer.write_text('# model-format: 99\n')
    rejected_read(root, lambda: load_model(consumer), 'unsupported Model format')
    producer.write_bytes(raw)
    # Reciprocal saved names have no evaluator and never recurse or rewrite either side.
    consumer, reciprocal = fixture(root, first, second, derived=True)
    producer, reverse = fixture(root, second, first, derived=True)
    before = {p: p.read_bytes() for p in (consumer, producer)}
    assert load_model(consumer).authoritative == reciprocal
    assert load_model(producer).authoritative == reverse
    assert before == {p: p.read_bytes() for p in (consumer, producer)}


@it_case
def check_fixed_label(root):
    prepare(root)
    consumer, values = fixture(root, 's3', 'cloudtrail')
    producer, original = fixture(root, 'cloudtrail', 's3')
    values = {key: value for key, value in values.items() if not key.startswith('desired.reference.OtherName.')}
    values['desired.note.link.text'] = '[fixed-label](cloudtrail.md#cloudtrail-original)'
    values['desired.reference.Other.text'] = values['desired.note.link.text']
    values['desired.reference.Other.labelPolicy'] = 'fixed'
    write_model(consumer, values)
    write_model(producer, {**original, 'desired.row.001-001.property': 'CloudTrail.Trail.Tags[].Value', 'desired.row.001-001.value': '[s3-original](s3.md#s3-original)'})
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    loaded = load_model(consumer)
    assert not loaded.warnings, loaded.warnings
    assert loaded.authoritative['desired.note.link.text'] == '[fixed-label](cloudtrail.md#cloudtrail-original)'
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    dependencies = dependency_hashes(consumer)
    producer.write_bytes(producer.read_bytes() + b'# annotation\n')
    assert load_model(consumer).authoritative == loaded.authoritative and dependency_hashes(consumer) != dependencies
    assert ('preview', 'team', 's3') in affected(root, [producer.relative_to(root)])
    assert trace_model(consumer, 'desired.note.link.text')['references']['Other']['labelPolicy'] == 'fixed'
    for fields, phrase in [({'labelPolicy': 'display-name'}, 'display-name label differs'),
                           ({'producerId': '999'}, 'absent or ambiguous'),
                           ({'resourceType': 'IAM.Role'}, 'Type differs')]:
        write_model(consumer, {**values, **{'desired.reference.Other.' + field: value for field, value in fields.items()}})
        warning(consumer, phrase)
    rejected_read(root, lambda: declarations({**values, 'desired.reference.Other.occurrence': '0'}), 'occurrence')


def fixture_stack(root):
    path = root / 'model/preview/team/cloudformation-stacks.properties'
    values = {'desired.stack.001.name': 'cfn-stack-app-preview-original', 'desired.stack.001.placementName': 'fixed-original',
              'desired.stack.001.template': 'network.yaml', 'desired.stack.001.parameters': 'network.json',
              'desired.stack.001.deployOrder': '10', 'display.stack.001.comment': '-original'}
    write_model(path, values)
    return path, values


@it_case
def check_stack(root):
    prepare(root)
    consumer, values = fixture(root, 's3')
    producer, original = fixture_stack(root)
    key = 'desired.row.001-002.document'
    values.update({'desired.row.001-002.property': 'S3.Bucket.PolicyDocument',
                   'desired.row.001-002.value': '[permission](s3/permission.json)', 'desired.row.001-002.comment': 'Stack参照',
                   key: json.dumps({'Resource': 'arn:aws:cloudformation:ap-northeast-1:123456789012:stack/cfn-stack-app-preview-original/*'})})
    fields = {'consumerKey': key, 'pointer': '/Resource', 'text': 'cfn-stack-app-preview-original', 'occurrence': '1',
              'producerKind': 'stack', 'producerScope': 'preview/team/cloudformation-stacks', 'producerId': '001',
              'format': 'name', 'property': 'name', 'labelPolicy': 'none'}
    values.update({'desired.reference.StackName.' + field: value for field, value in fields.items()})
    write_model(consumer, values)
    loaded = load_model(consumer)
    assert not loaded.warnings, loaded.warnings
    assert json.loads(loaded.authoritative[key])['Resource'].endswith('/cfn-stack-app-preview-original/*')
    digest, dependencies = design_source_digest(consumer), dependency_hashes(consumer)
    write_model(producer, {**original, 'desired.stack.001.name': 'cfn-stack-app-preview-changed'})
    assert warning(consumer, 'Stack name differs').authoritative == loaded.authoritative
    assert design_source_digest(consumer) == digest and dependency_hashes(consumer) != dependencies
    assert ('preview', 'team', 's3') in affected(root, [producer.relative_to(root)])
    assert trace_model(consumer, key)['references']['StackName']['producerKind'] == 'stack'
    write_model(producer, original)
    reads = FileReads()
    pinned = load_model(consumer, reads)
    write_model(producer, {**original, 'desired.stack.001.name': 'changed'})
    assert load_model(consumer, reads) is pinned and pinned.dependencies[producer] == serialize(original).encode()
    rejected_read(root, reads.verify, 'input changed')
    write_model(producer, original)
    write_model(consumer, {**values, 'desired.reference.StackName.producerId': '999'})
    warning(consumer, 'Stack is absent')
    for fields in ({'resourceType': 'IAM.Role'}, {'format': 'link'}, {'property': 'template'}):
        rejected_read(root, lambda: declarations({**values, **{'desired.reference.StackName.' + field: value for field, value in fields.items()}}), 'reference' if 'resourceType' not in fields else 'forbidden')
    write_model(consumer, values)
    producer.write_text(serialize({key: value for key, value in original.items() if key != 'desired.stack.001.placementName'}))
    rejected_read(root, lambda: load_model(consumer), 'placementName')
    write_model(producer, original)
    # A Stack name that contains a saved Resource reference remains an explicit string.
    reverse = {**original, 'desired.stack.001.name': 's3-original'}
    reverse.update(reference('bucket', 'desired.stack.001.name', 's3-original', 's3', '001', 'S3.Bucket', prop='S3.Bucket.BucketName'))
    write_model(producer, reverse)
    assert load_model(consumer).authoritative == values
    assert load_model(producer).authoritative == reverse
    producer.unlink()
    warning(consumer, 'Model is absent')


@it_case
def check_preparation_cache(root):
    prepare(root)
    from unittest.mock import patch
    import model.sources
    path = root / 'model/preview/team/iam.properties'
    values = {}
    for identity, rid in [('first', '001'), ('second', '002')]:
        values.update(resource(rid, 'IAM.Role', 'iam-' + rid, [('RoleName', '`' + identity + '`')]))
    write_model(path, values)
    original = path.read_bytes()
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    @input_scope
    def snapshot():
        with patch.object(model.sources, '_read_model', wraps=model.sources._read_model) as parsed:
            first = load_model(path)
            assert first.authoritative['desired.row.001-001.value'] == '`first`'
            path.write_bytes(original.replace(b'`second`', b'`changed`'))
            second = load_model(path)
            assert second.authoritative['desired.row.002-001.value'] == '`second`'
            assert parsed.call_count == 1 and second.dependencies[path] == original
    try:
        snapshot()
        assert load_model(path).authoritative['desired.row.002-001.value'] == '`changed`'
        path.unlink()
        rejected_read(root, lambda: load_model(path), 'iam.properties')
    finally:
        path.write_bytes(original)
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}


@it_case
def check():
    with tempfile.TemporaryDirectory() as directory:
        check_preparation_cache(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        check_stack(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        check_fixed_label(Path(directory))
    for pair in [('s3', 'cloudtrail'), ('lambda', 'eventbridge')]:
        with tempfile.TemporaryDirectory() as directory:
            check_pair(Path(directory), *pair)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        prepare(root)
        consumer, values = fixture(root, 's3', 'cloudtrail')
        producer, _ = fixture(root, 'cloudtrail')
        assert json.loads(load_model(consumer).authoritative['desired.row.001-002.document'])['name'] == 'cloudtrail-original'
        for fields, phrase in [({'producerId': '999'}, 'absent or ambiguous'), ({'resourceType': 'IAM.Role'}, 'Type differs')]:
            write_model(consumer, {**values, **{'desired.reference.Other.' + field: value for field, value in fields.items()}})
            warning(consumer, phrase)
    print('Attribute references: PASS (reciprocal saved values; exact JSON; Stack fixed placement; warnings; read-only failures; immutable snapshots/cache)')


if __name__ == '__main__':
    check()
