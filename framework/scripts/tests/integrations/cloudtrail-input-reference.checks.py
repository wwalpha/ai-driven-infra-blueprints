#!/usr/bin/env python3
"""Explicit saved references: fixed identity, dependencies and semantic warnings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import (
    Path,
    affected,
    dependency_hashes,
    design_source_digest,
    json,
    load_model,
    reference,
    resource,
    setup,
    source_inputs,
    tempfile,
    warning,
    write_model,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@it_case
def check(root):
    setup(root, ['cloudtrail', 's3'], ['CloudTrail.Trail', 'S3.Bucket'])
    producer = root / 'model/preview/team/cloudtrail.properties'
    original = resource('017', 'CloudTrail.Trail', 'cloudtrail-audit', [
        ('TrailName', '`audit-preview`'), ('S3BucketName', '`audit-bucket`'), ('Tags[].Name', '`unrelated-tag`')])
    write_model(producer, original)
    path = producer.with_name('s3.properties')
    key = 'desired.row.003-002.document'
    values = resource('003', 'S3.Bucket', 's3-003', [('BucketName', '`audit-preview-archive`'),
        ('PolicyDocument', '[policy](s3/policy.json)')])
    link = '[audit-preview](cloudtrail.md#cloudtrail-audit)'
    values[key] = json.dumps({'Statement': [
        {'Condition': {'StringEquals': {'aws:SourceArn': link}}},
        {'Condition': {'NumericLessThan': {'s3:TlsVersion': 1.2}}}]})
    values.update(reference('trail-name', 'desired.row.003-001.value', 'audit-preview', 'cloudtrail', '017', 'CloudTrail.Trail', prop='CloudTrail.Trail.TrailName'))
    values.update(reference('trail', key, link, 'cloudtrail', '017', 'CloudTrail.Trail', mode='link', pointer='/Statement/0/Condition/StringEquals/aws:SourceArn', label='display-name'))
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert json.loads(snapshot.authoritative[key])['Statement'][1]['Condition']['NumericLessThan']['s3:TlsVersion'] == 1.2
    assert snapshot.authoritative['desired.row.003-001.value'] == '`audit-preview-archive`'
    assert producer in source_inputs(path)
    assert affected(root, [producer.relative_to(root)]) == {('preview', 'team', 'cloudtrail'), ('preview', 'team', 's3')}
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    producer.write_text(producer.read_text() + '# annotation\n')
    assert dependency_hashes(path) != dependencies and design_source_digest(path) == digest
    assert load_model(path).authoritative == snapshot.authoritative
    write_model(producer, {**original, 'desired.row.017-001.value': '`audit-next`'})
    assert warning(path, 'differs').authoritative == snapshot.authoritative
    write_model(producer, {key.replace('.017', '.018', 1): value for key, value in original.items()})
    assert not load_model(path).warnings
    write_model(producer, original)
    for bad, phrase in [
        ({**original, 'desired.resource.017.resourceType': 'S3.Bucket'}, 'Type differs'),
        ({**original, 'desired.row.017-001.property': 'CloudTrail.Trail.Description'}, 'Property is absent'),
        ({**original, 'desired.row.017-001.value': '``'}, 'differs'),
        ({**original, 'desired.row.017-004.property': 'CloudTrail.Trail.TrailName', 'desired.row.017-004.value': '`duplicate`', 'desired.row.017-004.comment': '重複'}, 'Property is absent or ambiguous')]:
        write_model(producer, bad)
        if any(key in original and key.endswith('.resourceType') and original[key] != value for key, value in bad.items()):
            with pytest.raises(ValueError, match='ResourceType prefix'):
                load_model(path)
        else:
            assert warning(path, phrase).authoritative == snapshot.authoritative
    write_model(producer, original)
    explicit = dict(values)
    explicit[key] = values[key].replace('[audit-preview]', '[existing-label]')
    explicit['desired.reference.trail.text'] = '[existing-label](cloudtrail.md#cloudtrail-audit)'
    explicit['desired.reference.trail.labelPolicy'] = 'fixed'
    write_model(path, explicit)
    assert not load_model(path).warnings
    producer.unlink()
    assert warning(path, 'Model is absent').authoritative == explicit
    print('CloudTrail references: PASS (TrailName; exact JSON; fixed labels; dependency snapshots; warning preservation)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
