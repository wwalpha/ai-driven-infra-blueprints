#!/usr/bin/env python3
"""Typed EventBridge producer names, dependency tracking and strict rejection."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
from support.model_sources import write_model, write_fixture_files
import tempfile

import model_templates as t
from model_files import load_model
from support.model_sources import write_fixture_files as save_files


def rejected(call, message):
    try:
        call()
    except (ValueError, OSError) as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError('invalid producer accepted: ' + message)


def check(root, service, kind, property_name):
    producer = root / 'model/preview/team' / (service + '.properties')
    original = '\n'.join([
        'desired.resource.052.resourceType=' + kind,
        'desired.resource.052.resourceMode=IMPORT',
        'desired.resource.052.anchor=' + service + '-original',
        'desired.row.052-001.property=' + kind + '.' + property_name,
        'desired.row.052-001.value=`Original-Case_01`',
        'desired.row.052-002.property=' + kind + '.Nested.Name',
        'desired.row.052-002.value=`unrelated-nested-name`', '',
    ])
    if service == 'lambda':
        original += '\n'.join([
            'desired.resource.053.resourceType=Lambda.Permission',
            'desired.resource.053.anchor=lambda-invoke-permission',
            'desired.resource.053.parentProperty=Lambda.Permission.FunctionName',
            'desired.resource.053.parentReference=[052](#lambda-original)',
            'desired.row.053-001.property=Lambda.Permission.FunctionName',
            'desired.row.053-001.value=[052](#lambda-original)',
            'desired.row.053-002.property=Lambda.Permission.Principal',
            'desired.row.053-002.value=`events.amazonaws.com`',
            'desired.row.053-003.property=Lambda.Permission.SourceArn',
            'desired.row.053-003.value=[rule](eventbridge.md#eventbridge-rule)', '',
        ])
    template = root / 'model/templates/team/eventbridge.properties.tpl'
    ref = {'service': service, 'resource': '052', 'resourceType': kind}
    write_fixture_files({producer: original, template: '\n'.join([
        '# model-template: 1', '# definition: Rule',
        '# reference: Link ' + t.json_text(ref),
        '# reference: Raw ' + t.json_text({**ref, 'format': 'name'}),
        '# resource: rule', '# row: name rule',
        'desired.resource.rule.resourceType=Events.Rule',
        'desired.resource.rule.anchor=eventbridge-rule',
        'desired.row.name.property=Events.Rule.Name',
        'desired.row.name.value=`rule`',
        'desired.note.link.text=<<Link>>',
        'desired.note.raw.document={"name":"<<Raw>>","count":2,"enabled":true}',
        '# end-definition', '',
    ])})
    bindings = {'instances': {'rule': {'definition': 'Rule', 'resources': {'rule': '021'},
        'rows': {'name': '021-001'}, 'parameters': {}, 'labels': {'Link': 'PENDING_DEPLOY'}}}}
    human, observed = {'instances': {}}, {'version': 1, 'values': {}}
    values, trace, files = t.expand(template, human, observed, bindings, 'preview')
    assert values['desired.note.link.text'] == '[PENDING_DEPLOY](' + service + '.md#' + service + '-original)'
    assert t.json_read(values['desired.note.raw.document']) == {'name': 'Original-Case_01', 'count': 2, 'enabled': True}
    assert trace['desired.note.raw.document']['parameters'] == ['Raw']
    assert set(load_model(producer).files) <= set(files)
    path = root / 'model/preview/team/eventbridge.properties'
    directory = root / 'model/parameters/preview/team/eventbridge'
    write_fixture_files({path: ''.join(k + '=' + v + '\n' for k, v in values.items()),

        directory / 'parameters.yaml': 'instances: {}\n', directory / 'bindings.json': t.json_text(bindings),
        directory / 'observed.json': t.json_text(observed)})
    initial = t.design_source_digest(path)
    write_model(producer, original.replace('Original-Case_01', 'Renamed'))
    assert t.design_source_digest(path) != initial
    assert t.json_read(load_model(path).values['desired.note.raw.document'])['name'] == 'Renamed'
    assert t.affected(root, [producer.relative_to(root)]) == {('preview', 'team', service), ('preview', 'team', 'eventbridge')}
    for bad, message in [
        (original.replace('resourceType=' + kind, 'resourceType=EC2.VPC'), 'type-mismatched'),
        (original.replace('052', '054'), 'type-mismatched'),
        (original.replace(kind + '.' + property_name, kind + '.Description'), 'exactly one name'),
        (original.replace('`Original-Case_01`', '``'), 'exactly one name'),
        (original + 'desired.row.052-003.property=' + kind + '.' + property_name + '\ndesired.row.052-003.value=`duplicate`\n', 'exactly one name'),
    ]:
        write_model(producer, bad)
        rejected(lambda: load_model(path), message)
    write_model(producer, original)
    invalid = copy.deepcopy(bindings)
    invalid['instances']['rule']['labels']['Raw'] = 'override'
    rejected(lambda: t.expand(template, human, observed, invalid, 'preview'), 'cannot override label')
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    rejected(lambda: load_model(path), 'missing')


if __name__ == '__main__':
    for service, kind, name in [('lambda', 'Lambda.Function', 'FunctionName'),
                               ('sqs', 'SQS.Queue', 'QueueName'), ('iam', 'IAM.User', 'UserName')]:
        with tempfile.TemporaryDirectory() as directory:
            check(Path(directory).resolve(), service, kind, name)
    print('EventBridge producer names: PASS (FunctionName/QueueName/UserName; typed links/raw JSON; labels; hash/impact/trace; strict rejection)')
