#!/usr/bin/env python3
"""Offline Security Group reference, label, dependency and rejection regression."""

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


def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError) as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid reference accepted: ' + phrase)


def check(root):
    producer = root / 'model/preview/team/security-group.properties'
    original = '\n'.join([
        'desired.service.security-group.serviceId=security-group',
        'desired.resource.052.resourceType=EC2.SecurityGroup',
        'desired.resource.052.resourceMode=IMPORT',
        'desired.resource.052.anchor=security-group-app-preview-one',
        'desired.row.052-001.property=EC2.SecurityGroup.GroupName',
        'desired.row.052-001.value=`app-preview-one`',
        'desired.row.052-002.property=EC2.SecurityGroup.GroupDescription',
        'desired.row.052-002.value=`QuickSight VPC connection`',
        'desired.row.052-003.property=EC2.SecurityGroup.VpcId',
        'desired.row.052-003.value=[017](vpc.md#vpc-app-preview)',
    ]) + '\n'
    template = root / 'model/templates/team/quicksight.properties.tpl'
    write_fixture_files({producer: original, root / 'model/preview/team/vpc.properties':
        'desired.resource.017.resourceType=EC2.VPC\n'
        'desired.resource.017.anchor=vpc-app-preview\n'
        'desired.row.017-001.property=EC2.VPC.Name\n'
        'desired.row.017-001.value=`vpc-app-preview`\n',
        template: '\n'.join([
            '# model-template: 1', '# definition: Connection',
            '# reference: SecurityGroup ' + t.json_text({
                'service': 'security-group', 'resource': '052', 'resourceType': 'EC2.SecurityGroup'}),
            '# resource: connection', '# row: groups connection',
            'desired.resource.connection.resourceType=QuickSight.VPCConnection',
            'desired.resource.connection.anchor=quicksight-<<Id_connection>>',
            'desired.row.groups.property=QuickSight.VPCConnection.SecurityGroupIds',
            'desired.row.groups.value=<<SecurityGroup>>', '# end-definition',
        ]) + '\n'})
    bindings = {'instances': {name: {
        'definition': 'Connection', 'resources': {'connection': rid},
        'rows': {'groups': rid + '-001'}, 'parameters': {}, 'labels': labels,
    } for name, rid, labels in [
        ('default-label', '021', {}), ('existing-label', '083', {'SecurityGroup': 'PENDING_DEPLOY'})]}}
    human, observed = {'instances': {}}, {'version': 1, 'values': {}}
    values, _, files = t.expand(template, human, observed, bindings, 'preview')
    key, retained = 'desired.row.021-001.value', 'desired.row.083-001.value'
    assert values[key] == '[app-preview-one](security-group.md#security-group-app-preview-one)'
    assert values[retained] == '[PENDING_DEPLOY](security-group.md#security-group-app-preview-one)'
    assert set(load_model(producer).files) <= set(files)
    path = root / 'model/preview/team/quicksight.properties'
    directory = root / 'model/parameters/preview/team/quicksight'
    write_fixture_files({path: ''.join(k + '=' + v + '\n' for k, v in values.items()),

        directory / 'parameters.yaml': 'instances: {}\n',
        directory / 'bindings.json': t.json_text(bindings),
        directory / 'observed.json': t.json_text(observed)})
    assert set(load_model(producer).files) <= set(t.source_inputs(path))
    assert t.affected(root, [producer.relative_to(root)]) == {
        ('preview', 'team', 'security-group'), ('preview', 'team', 'quicksight')}
    digest = t.design_source_digest(path)
    write_model(producer, original + '# producer annotation\n')
    assert t.design_source_digest(path) != digest
    assert load_model(path).values == values
    write_model(producer, original.replace('preview-one', 'preview-two'))
    assert t.design_source_digest(path) != digest
    expanded = load_model(path).values
    assert expanded[key] == '[app-preview-two](security-group.md#security-group-app-preview-two)'
    assert expanded[retained] == '[PENDING_DEPLOY](security-group.md#security-group-app-preview-two)'
    write_model(producer, original)
    for bad, phrase in [
        (original.replace('resourceType=EC2.SecurityGroup', 'resourceType=EC2.Subnet'), 'type-mismatched'),
        (original.replace('052', '053'), 'type-mismatched'),
        (original.replace('EC2.SecurityGroup.GroupName', 'EC2.SecurityGroup.GroupDescription'), 'exactly one name'),
        (original.replace('`app-preview-one`', '``'), 'exactly one name'),
        (original + 'desired.row.052-004.property=EC2.SecurityGroup.GroupName\n'
                    'desired.row.052-004.value=`duplicate`\n', 'exactly one name'),
    ]:
        write_model(producer, bad)
        rejected(lambda: load_model(path), phrase)
    write_model(producer, original)
    invalid = copy.deepcopy(bindings)
    invalid['instances']['existing-label']['labels']['SecurityGroup'] = '[broken]'
    rejected(lambda: t.expand(template, human, observed, invalid, 'preview'), 'invalid reference label')
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    rejected(lambda: load_model(path), 'missing')
    print('Security Group references: PASS (GroupName; labels; types; producer hash/impact; rejection)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
