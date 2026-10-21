#!/usr/bin/env python3
"""Explicit saved references: fixed identity, dependencies and semantic warnings."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
import pytest
from support.it_case_receipt import it_case, module_complete
from support.producer_identifier_reference_fixtures import *

@it_case
def check(root):
    setup(root, ['lambda', 'cloudtrail'], ['Lambda.Function', 'CloudTrail.Trail'])
    producer = root / 'model/preview/team/lambda.properties'
    original = resource('052', 'Lambda.Function', 'lambda-app-preview-one', [
        ('FunctionName', '`app-preview-one`'), ('Description', '`CloudTrail data event function`')])
    write_model(producer, original)
    path = producer.with_name('cloudtrail.properties')
    values = {}
    for rid, label, policy in [('021', 'app-preview-one', 'display-name'), ('083', 'PENDING_DEPLOY', 'fixed')]:
        key = f'desired.row.{rid}-001.value'
        link = f'[{label}](lambda.md#lambda-app-preview-one)'
        values.update(resource(rid, 'CloudTrail.Trail', 'cloudtrail-' + rid, [('EventSelectors[].DataResources[].Values', link)]))
        values.update(reference('function-' + rid, key, link, 'lambda', '052', 'Lambda.Function', mode='link', label=policy))
    values['desired.note.producerName.text'] = 'app-preview-one'
    values.update(reference('producer-name', 'desired.note.producerName.text', 'app-preview-one', 'lambda', '052', 'Lambda.Function', prop='Lambda.Function.FunctionName'))
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert snapshot.authoritative['desired.row.021-001.value'] == '[app-preview-one](lambda.md#lambda-app-preview-one)'
    assert snapshot.authoritative['desired.row.083-001.value'] == '[PENDING_DEPLOY](lambda.md#lambda-app-preview-one)'
    assert producer in source_inputs(path)
    assert affected(root, [producer.relative_to(root)]) == {('preview', 'team', 'lambda'), ('preview', 'team', 'cloudtrail')}
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    producer.write_text(producer.read_text() + '# producer annotation\n')
    assert design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    assert load_model(path).authoritative == snapshot.authoritative
    renamed = {key: value.replace('preview-one', 'preview-two') for key, value in original.items()}
    write_model(producer, renamed)
    assert warning(path, 'differs from saved text').authoritative == snapshot.authoritative
    write_model(producer, {key.replace('.052', '.053', 1): value for key, value in original.items()})
    assert not load_model(path).warnings
    write_model(producer, original)
    for bad, phrase in [
        ({**original, 'desired.resource.052.resourceType': 'S3.Bucket'}, 'Type differs'),
        ({**original, 'desired.row.052-001.property': 'Lambda.Function.Description'}, 'Property is absent'),
        ({**original, 'desired.row.052-001.value': '``'}, 'differs from saved text'),
        ({**original, 'desired.row.052-004.property': 'Lambda.Function.FunctionName', 'desired.row.052-004.value': '`duplicate`', 'desired.row.052-004.comment': '重複'}, 'Property is absent or ambiguous')]:
        write_model(producer, bad)
        if any(key in original and key.endswith('.resourceType') and original[key] != value for key, value in bad.items()):
            with pytest.raises(ValueError, match='ResourceType prefix'):
                load_model(path)
        else:
            assert warning(path, phrase).authoritative == snapshot.authoritative
    write_model(producer, original)
    bad = {**values, 'desired.reference.function-021.occurrence': '0'}
    rejected(lambda: declarations(bad), 'occurrence')
    producer.unlink()
    assert warning(path, 'Model is absent').authoritative == snapshot.authoritative
    print('Lambda Function references: PASS (FunctionName; fixed labels; type/identity warnings; dependency snapshots)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
