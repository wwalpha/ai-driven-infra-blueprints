#!/usr/bin/env python3
"""Offline TrailName selection, policy links and producer dependency regression."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

import json
from support.model_sources import write_model, write_fixture_files
import tempfile

import model_templates as t
from model_files import load_model
from support.model_sources import write_fixture_files as save_files


@it_case
def check(root):
    producer = root / 'model/preview/team/cloudtrail.properties'
    original = ('desired.resource.017.resourceType=CloudTrail.Trail\n'
        'desired.resource.017.anchor=cloudtrail-audit\n'
        'desired.row.017-001.property=CloudTrail.Trail.TrailName\n'
        'desired.row.017-001.value=`audit-preview`\n'
        'desired.row.017-002.property=CloudTrail.Trail.S3BucketName\n'
        'desired.row.017-002.value=`audit-bucket`\n'
        'desired.row.017-003.property=CloudTrail.Trail.Tags[].Name\n'
        'desired.row.017-003.value=`unrelated-tag`\n')
    template = root / 'model/templates/team/s3.properties.tpl'
    ref = {'service': 'cloudtrail', 'resource': '017', 'resourceType': 'CloudTrail.Trail'}
    write_fixture_files({producer: original, template: '\n'.join([
        '# model-template: 1', '# definition: Bucket',
        '# reference: Trail ' + t.json_text(ref),
        '# reference: TrailName ' + t.json_text({**ref, 'format': 'name'}),
        '# resource: bucket', '# row: policy bucket', '# row: name bucket',
        'desired.resource.bucket.resourceType=S3.Bucket',
        'desired.resource.bucket.anchor=s3-<<Id_bucket>>',
        'desired.row.name.property=S3.Bucket.BucketName',
        'desired.row.name.value=`<<TrailName>>-archive`',
        'desired.row.policy.property=S3.BucketPolicy.PolicyDocument',
        'desired.row.policy.value=[policy](s3/policy.json)',
        'desired.row.policy.document=' + t.json_text({'Statement': [
            {'Condition': {'StringEquals': {'aws:SourceArn': '<<Trail>>'}}},
            {'Condition': {'NumericLessThan': {'s3:TlsVersion': 1.2}}}]}),
        '# end-definition', ''])})
    bindings = {'instances': {'audit': {'definition': 'Bucket', 'resources': {'bucket': '003'},
        'rows': {'name': '003-001', 'policy': '003-002'}, 'parameters': {}, 'labels': {}}}}
    human, observed = {'instances': {}}, {'version': 1, 'values': {}}
    values, _, files = t.expand(template, human, observed, bindings, 'preview')
    key = 'desired.row.003-002.document'
    assert json.loads(values[key])['Statement'][0]['Condition']['StringEquals']['aws:SourceArn'] == '[audit-preview](cloudtrail.md#cloudtrail-audit)'
    assert json.loads(values[key])['Statement'][1]['Condition']['NumericLessThan']['s3:TlsVersion'] == 1.2
    assert values['desired.row.003-001.value'] == '`audit-preview-archive`'
    assert set(load_model(producer).files) <= set(files)
    bindings['instances']['audit']['labels']['Trail'] = 'existing-label'
    assert 'existing-label' in t.expand(template, human, observed, bindings, 'preview')[0][key]
    bindings['instances']['audit']['labels'].clear()
    path = root / 'model/preview/team/s3.properties'
    directory = root / 'model/parameters/preview/team/s3'
    write_fixture_files({path: ''.join(k + '=' + v + '\n' for k, v in values.items()),

        directory / 'parameters.yaml': 'instances: {}\n',
        directory / 'bindings.json': t.json_text(bindings), directory / 'observed.json': t.json_text(observed)})
    assert set(load_model(producer).files) <= set(t.source_inputs(path))
    assert t.affected(root, [producer.relative_to(root)]) == {('preview', 'team', 'cloudtrail'), ('preview', 'team', 's3')}
    digest = t.design_source_digest(path)
    for updated in [original + '# annotation\n', original.replace('audit-preview', 'audit-next')]:
        write_model(producer, updated)
        assert t.design_source_digest(path) != digest
        assert load_model(path).values['desired.row.003-001.value'] == ('`audit-next-archive`' if 'audit-next' in updated else '`audit-preview-archive`')
    for bad, phrase in [(original.replace('resourceType=CloudTrail.Trail', 'resourceType=S3.Bucket'), 'type-mismatched'),
        (original.replace('017', '018'), 'type-mismatched'),
        (original.replace('CloudTrail.Trail.TrailName', 'CloudTrail.Trail.Description'), 'exactly one name'),
        (original.replace('`audit-preview`', '``'), 'exactly one name'),
        (original + 'desired.row.017-004.property=CloudTrail.Trail.TrailName\ndesired.row.017-004.value=`duplicate`\n', 'exactly one name')]:
        write_model(producer, bad)
        try:
            load_model(path)
        except ValueError as error:
            assert phrase in str(error), str(error)
        else:
            raise AssertionError('invalid Trail reference accepted: ' + phrase)
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    try:
        load_model(path)
    except (FileNotFoundError,ValueError) as error:
        assert "missing" in str(error)
    else:
        raise AssertionError('missing producer accepted')
    print('CloudTrail references: PASS (TrailName; policy/labels; types; producer hash/impact; rejection)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
