#!/usr/bin/env python3
"""Offline account context and canonical document digest regression."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import *
from model.projection import document_sha256, json_sha256


@it_case
def check(root):
    setup(root, ['sqs'], ['SQS.QueuePolicy'])
    project = root / 'project.json'
    target = {'environment': 'preview', 'alias': 'team', 'awsAccountId': '111111111111',
              'awsExecutionAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}
    topology = {'targets': [target]}
    project.write_text(json.dumps(topology), encoding='utf-8')
    path = root / 'model/preview/team/sqs.properties'
    key = 'desired.row.007-002.'
    document = {'Statement': [{'Action': ['sqs:SendMessage', 'sqs:GetQueueUrl'],
        'Condition': {'StringEquals': {'aws:SourceAccount': '123456789012'}}, 'Enabled': True, 'Count': 2}]}
    values = {key.replace('.007-001.', '.007-002.'): value for key, value in resource('007', 'SQS.QueuePolicy', 'queue-policy',
        [('PolicyDocument', '[policy](sqs/policy.json)')]).items()}
    values[key + 'document'] = json.dumps(document)
    fields = {'consumerKey': key + 'document', 'pointer': '/Statement/0/Condition/StringEquals/aws:SourceAccount',
              'text': '123456789012', 'occurrence': '1', 'producerKind': 'context', 'producerScope': 'preview/team',
              'format': 'literal', 'labelPolicy': 'none', 'contextProperty': 'executionAccountId'}
    values.update({'desired.reference.account.' + field: value for field, value in fields.items()})
    write_model(path, values)
    model = load_model(path)
    assert not model.warnings, model.warnings
    actual = json.loads(model.authoritative[key + 'document'])
    assert actual['Statement'][0]['Condition']['StringEquals']['aws:SourceAccount'] == '123456789012'
    assert actual['Statement'][0]['Action'] == ['sqs:SendMessage', 'sqs:GetQueueUrl']
    assert actual['Statement'][0]['Enabled'] is True and type(actual['Statement'][0]['Count']) is int
    assert model.values[key + 'artifactSha256'] == document_sha256(document)
    assert key + 'artifactSha256' not in model.authoritative
    artifact = root / 'policy.json'
    artifact.write_text(json.dumps(document, indent=2) + '\n')
    assert json_sha256(artifact) == model.values[key + 'artifactSha256']
    trace = trace_model(path, key + 'document')
    assert trace['references']['account']['contextProperty'] == 'executionAccountId'
    assert trace_model(path, key + 'artifactSha256')['derivedFrom'] == key + 'document'
    assert project in source_inputs(path) and affected(root, ['project.json']) == {('preview', 'team', 'sqs')}
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    target.pop('awsExecutionAccountId')
    project.write_text(json.dumps(topology))
    changed = warning(path, 'context value differs')
    assert changed.authoritative == model.authoritative and changed.values[key + 'artifactSha256'] == model.values[key + 'artifactSha256']
    assert design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    for targets in ([], [target, target], [{**target, 'awsExecutionAccountId': 123}], [{**target, 'awsExecutionAccountId': 'bad'}]):
        project.write_text(json.dumps({'targets': targets}))
        try:
            load_model(path)
        except (ValueError, OSError):
            pass
        else:
            raise AssertionError('invalid topology accepted')
    project.write_text(json.dumps(topology))
    for fields in ({'producerId': '007'}, {'property': 'Account'}, {'contextProperty': 'awsAccountId'}):
        bad = {**values, **{'desired.reference.account.' + field: value for field, value in fields.items()}}
        rejected(lambda: declarations(bad), 'reference' if 'contextProperty' in fields else 'forbidden')
    # Values and reference text change only in an explicit candidate; hashes remain derived.
    hashes = []
    for account in ('222222222222', '333333333333'):
        candidate = dict(values)
        candidate[key + 'document'] = values[key + 'document'].replace('123456789012', account)
        candidate['desired.reference.account.text'] = account
        write_model(path, candidate)
        current = load_model(path)
        doc = json.loads(current.authoritative[key + 'document'])
        hashes.append(current.values[key + 'artifactSha256'])
        assert hashes[-1] == document_sha256(doc)
        raw = path.read_bytes()
        assert load_model(path).authoritative == current.authoritative and path.read_bytes() == raw
    assert hashes[0] != hashes[1]
    invalid = dict(candidate)
    invalid[key + 'artifactSha256'] = 'stale'
    path.write_text(serialize(invalid))
    rejected(lambda: load_model(path), 'unknown Model field')
    print('Context/document digest: PASS (project authority; explicit context meaning; types/order; derived hash; snapshot invalidation; no automatic changes)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
