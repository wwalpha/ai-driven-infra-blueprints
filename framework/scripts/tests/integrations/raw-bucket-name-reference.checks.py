#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.raw_bucket_name_reference_fixtures import *

@it_case
def check(root):
    setup(root, ['s3', 'macie', 'athena', 'kms'], ['S3.Bucket', 'Macie.ClassificationJob', 'Athena.WorkGroup', 'KMS.Key'])
    producer = root / 'model/preview/team/s3.properties'
    original = resource('017', 'S3.Bucket', 's3-raw-name', [('BucketName', '`app-preview-RAW-one`')])
    write_model(producer, original)
    path = producer.with_name('macie.properties')
    values = {}
    for rid in ('003', '088'):
        key = f'desired.row.{rid}-001.document'
        linkkey = f'desired.row.{rid}-002.value'
        document = {'bucketDefinitions': [{'accountId': '111111111111', 'buckets': ['app-preview-RAW-one', 'fixed-second']}],
                    'scoping': {'includes': {'and': [{'simpleScopeTerm': {'comparator': 'EQ', 'key': 'OBJECT_EXTENSION', 'values': ['csv']}}]}}}
        values.update(resource(rid, 'Macie.ClassificationJob', 'macie-' + rid, [
            ('S3JobDefinition', f'[json](macie/job-{rid}.json)'), ('Name', '[PENDING_DEPLOY](s3.md#s3-raw-name)')]))
        values[key] = json.dumps(document)
        values.update(reference('bucket-' + rid, key, 'app-preview-RAW-one', 's3', '017', 'S3.Bucket', prop='S3.Bucket.BucketName', pointer='/bucketDefinitions/0/buckets/0'))
        values.update(reference('link-' + rid, linkkey, values[linkkey], 's3', '017', 'S3.Bucket', mode='link', label='fixed'))
    write_model(path, values)
    key = 'desired.row.003-001.document'
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    doc = json.loads(snapshot.authoritative[key])
    assert doc['bucketDefinitions'][0]['buckets'] == ['app-preview-RAW-one', 'fixed-second']
    assert doc['bucketDefinitions'][0]['accountId'] == '111111111111'
    assert snapshot.authoritative['desired.row.003-002.value'] == '[PENDING_DEPLOY](s3.md#s3-raw-name)'
    assert producer in source_inputs(path)
    assert affected(root, [producer.relative_to(root)]) == {('preview', 'team', 's3'), ('preview', 'team', 'macie')}
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    producer.write_text(producer.read_text() + '# annotation\n')
    assert design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    assert load_model(path).authoritative == snapshot.authoritative
    changed = {**original, 'desired.row.017-001.value': '`app-preview-RAW-two`'}
    write_model(producer, changed)
    assert warning(path, 'differs from saved text').authoritative == snapshot.authoritative
    assert design_source_digest(path) == digest
    for bad, phrase in [
        ({**original, 'desired.resource.017.resourceType': 'IAM.Role'}, 'Type differs'),
        ({key.replace('.017', '.018', 1): value for key, value in original.items()}, 'absent or ambiguous'),
        ({**original, 'desired.row.017-001.property': 'S3.Bucket.Description'}, 'Property is absent'),
        ({**original, 'desired.row.017-001.value': '``'}, 'differs from saved text'),
        ({**original, 'desired.row.017-002.property': 'S3.Bucket.BucketName', 'desired.row.017-002.value': '`duplicate`', 'desired.row.017-002.comment': '重複'}, 'Property is absent or ambiguous')]:
        write_model(producer, bad)
        assert warning(path, phrase).authoritative == snapshot.authoritative
    write_model(producer, original)
    invalid = dict(values)
    invalid['desired.reference.bucket-003.labelPolicy'] = 'fixed'
    rejected(lambda: declarations(invalid), 'non-link')
    producer.unlink()
    assert warning(path, 'Model is absent').authoritative == snapshot.authoritative
    athena = producer.with_name('athena.properties')
    write_model(athena, resource('017', 'Athena.WorkGroup', 'athena-raw-name', [('Name', '`app-preview-RAW-one`')]))
    explicit = dict(values)
    for rid in ('003', '088'):
        prefix = 'desired.reference.bucket-' + rid + '.'
        explicit.update({prefix + 'producerScope': 'preview/team/athena', prefix + 'resourceType': 'Athena.WorkGroup', prefix + 'property': 'Athena.WorkGroup.Name'})
    write_model(path, explicit)
    assert json.loads(load_model(path).authoritative[key])['bucketDefinitions'][0]['buckets'][0] == 'app-preview-RAW-one'
    write_model(athena, resource('017', 'KMS.Key', 'athena-raw-name', [('Description', '`app-preview-RAW-one`')]))
    assert warning(path, 'Type differs').authoritative == explicit
    print('Raw BucketName: PASS (explicit JSON values/order; links/labels; dependency hashes; warning preservation; metadata rejection)')


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())

