#!/usr/bin/env python3
"""Offline Lambda Function reference, label, dependency and rejection regression."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

import copy
from support.model_sources import write_model, write_fixture_files
import tempfile

import model_templates as t
from model_files import load_model
from support.model_sources import write_fixture_files as save_files


def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError) as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid reference accepted: ' + phrase)


@it_case
def check(root):
    producer = root / 'model/preview/team/lambda.properties'
    original = '\n'.join([
        'desired.service.lambda.serviceId=lambda',
        'desired.resource.052.resourceType=Lambda.Function',
        'desired.resource.052.resourceMode=IMPORT',
        'desired.resource.052.anchor=lambda-app-preview-one',
        'desired.row.052-001.property=Lambda.Function.FunctionName',
        'desired.row.052-001.value=`app-preview-one`',
        'desired.row.052-002.property=Lambda.Function.Description',
        'desired.row.052-002.value=`CloudTrail data event function`',
    ]) + '\n'
    template = root / 'model/templates/team/cloudtrail.properties.tpl'
    write_fixture_files({producer: original, template: '\n'.join([
            '# model-template: 1', '# definition: Connection',
            '# reference: Function ' + t.json_text({
                'service': 'lambda', 'resource': '052', 'resourceType': 'Lambda.Function'}),
            '# resource: connection', '# row: groups connection',
            'desired.resource.connection.resourceType=CloudTrail.Trail',
            'desired.resource.connection.anchor=cloudtrail-<<Id_connection>>',
            'desired.row.groups.property=CloudTrail.Trail.EventSelectors[].DataResources[].Values',
            'desired.row.groups.value=<<Function>>', '# end-definition',
        ]) + '\n'})
    bindings = {'instances': {name: {
        'definition': 'Connection', 'resources': {'connection': rid},
        'rows': {'groups': rid + '-001'}, 'parameters': {}, 'labels': labels,
    } for name, rid, labels in [
        ('default-label', '021', {}), ('existing-label', '083', {'Function': 'PENDING_DEPLOY'})]}}
    human, observed = {'instances': {}}, {'version': 1, 'values': {}}
    values, _, files = t.expand(template, human, observed, bindings, 'preview')
    key, retained = 'desired.row.021-001.value', 'desired.row.083-001.value'
    assert values[key] == '[app-preview-one](lambda.md#lambda-app-preview-one)'
    assert values[retained] == '[PENDING_DEPLOY](lambda.md#lambda-app-preview-one)'
    assert set(load_model(producer).files) <= set(files)
    path = root / 'model/preview/team/cloudtrail.properties'
    directory = root / 'model/parameters/preview/team/cloudtrail'
    write_fixture_files({path: ''.join(k + '=' + v + '\n' for k, v in values.items()),

        directory / 'parameters.yaml': 'instances: {}\n',
        directory / 'bindings.json': t.json_text(bindings),
        directory / 'observed.json': t.json_text(observed)})
    assert set(load_model(producer).files) <= set(t.source_inputs(path))
    assert t.affected(root, [producer.relative_to(root)]) == {
        ('preview', 'team', 'lambda'), ('preview', 'team', 'cloudtrail')}
    digest = t.design_source_digest(path)
    write_model(producer, original + '# producer annotation\n')
    assert t.design_source_digest(path) != digest
    assert load_model(path).values == values
    write_model(producer, original.replace('preview-one', 'preview-two'))
    assert t.design_source_digest(path) != digest
    expanded = load_model(path).values
    assert expanded[key] == '[app-preview-two](lambda.md#lambda-app-preview-two)'
    assert expanded[retained] == '[PENDING_DEPLOY](lambda.md#lambda-app-preview-two)'
    write_model(producer, original)
    for bad, phrase in [
        (original.replace('resourceType=Lambda.Function', 'resourceType=S3.Bucket'), 'type-mismatched'),
        (original.replace('052', '053'), 'type-mismatched'),
        (original.replace('Lambda.Function.FunctionName', 'Lambda.Function.Description'), 'exactly one name'),
        (original.replace('`app-preview-one`', '``'), 'exactly one name'),
        (original + 'desired.row.052-004.property=Lambda.Function.FunctionName\n'
                    'desired.row.052-004.value=`duplicate`\n', 'exactly one name'),
    ]:
        write_model(producer, bad)
        rejected(lambda: load_model(path), phrase)
    write_model(producer, original)
    invalid = copy.deepcopy(bindings)
    invalid['instances']['existing-label']['labels']['Function'] = '[broken]'
    rejected(lambda: t.expand(template, human, observed, invalid, 'preview'), 'invalid reference label')
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    rejected(lambda: load_model(path), 'missing')
    print('Lambda Function references: PASS (FunctionName; labels; types; producer hash/impact; rejection)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
