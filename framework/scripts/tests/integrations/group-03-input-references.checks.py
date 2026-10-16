#!/usr/bin/env python3
"""Offline unnamed Key and InstanceProfile references, dependencies and rejection."""

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


def check(root, service, kind, name_property):
    producer = root / 'model/preview/team' / (service + '.properties')
    original = '\n'.join([
        'desired.service.' + service + '.serviceId=' + service,
        'desired.resource.052.resourceType=' + kind,
        'desired.resource.052.anchor=' + service + '-app-preview-one',
        'desired.row.052-001.property=' + (name_property or 'KMS.Key.Description'),
        'desired.row.052-001.value=`app-preview-one`',
    ]) + '\n'
    if name_property:
        original += ('desired.row.052-002.property=IAM.InstanceProfile.Roles\n'
                     'desired.row.052-002.value=[app-role](#iam-app-role)\n'
                     'desired.resource.075.resourceType=IAM.Role\n'
                     'desired.resource.075.anchor=iam-app-role\n'
                     'desired.row.075-001.property=IAM.Role.RoleName\n'
                     'desired.row.075-001.value=`app-role`\n')
    template = root / 'model/templates/team/ec2.properties.tpl'
    write_fixture_files({producer: original, template: '\n'.join([
        '# model-template: 1', '# definition: Instance',
        '# reference: Producer ' + t.json_text({'service': service, 'resource': '052', 'resourceType': kind}),
        '# resource: instance', '# row: producer instance',
        'desired.resource.instance.resourceType=EC2.Instance',
        'desired.resource.instance.anchor=ec2-<<Id_instance>>',
        'desired.row.producer.property=' + ('EC2.Instance.IamInstanceProfile' if name_property else 'EC2.Instance.BlockDeviceMappings[].Ebs.KmsKeyId'),
        'desired.row.producer.value=<<Producer>>', '# end-definition',
    ]) + '\n'})
    bindings = {'instances': {name: {
        'definition': 'Instance', 'resources': {'instance': rid},
        'rows': {'producer': rid + '-001'}, 'parameters': {}, 'labels': labels,
    } for name, rid, labels in [
        ('default-label', '021', {}), ('existing-label', '083', {'Producer': 'original-label'})]}}
    human, observed = {'instances': {}}, {'version': 1, 'values': {}}
    values, _, files = t.expand(template, human, observed, bindings, 'preview')
    key, retained = 'desired.row.021-001.value', 'desired.row.083-001.value'
    label = 'app-preview-one' if name_property else '052'
    assert values[key] == '[' + label + '](' + service + '.md#' + service + '-app-preview-one)'
    assert values[retained] == '[original-label](' + service + '.md#' + service + '-app-preview-one)'
    assert set(load_model(producer).files) <= set(files)
    path = root / 'model/preview/team/ec2.properties'
    directory = root / 'model/parameters/preview/team/ec2'
    binding_path = directory / 'bindings.json'
    write_fixture_files({path: ''.join(k + '=' + v + '\n' for k, v in values.items()),

        directory / 'parameters.yaml': 'instances: {}\n', binding_path: t.json_text(bindings),
        directory / 'observed.json': t.json_text(observed)})
    assert set(load_model(producer).files) | {binding_path} <= t.source_inputs(path)
    assert t.affected(root, [producer.relative_to(root)]) == {('preview', 'team', service), ('preview', 'team', 'ec2')}
    assert t.affected(root, [binding_path.relative_to(root)]) == {('preview', 'team', 'ec2')}
    digest = t.design_source_digest(path)
    write_model(producer, original + '# producer annotation\n')
    assert t.design_source_digest(path) != digest and load_model(path).values == values
    write_model(producer, original.replace('preview-one', 'preview-two'))
    expanded = load_model(path).values
    assert t.design_source_digest(path) != digest
    assert expanded[key] == '[' + ('app-preview-two' if name_property else '052') + '](' + service + '.md#' + service + '-app-preview-two)'
    assert expanded[retained] == '[original-label](' + service + '.md#' + service + '-app-preview-two)'
    write_model(producer, original)
    invalid = copy.deepcopy(bindings)
    invalid['instances']['existing-label']['labels']['Producer'] = 'changed-label'
    binding_path.write_text(t.json_text(invalid), encoding='utf-8')
    assert t.design_source_digest(path) != digest and load_model(path).values[retained].startswith('[changed-label]')
    binding_path.write_text(t.json_text(bindings), encoding='utf-8')
    for bad, phrase in [
        (original.replace('resourceType=' + kind, 'resourceType=S3.Bucket'), 'type-mismatched'),
        (original.replace('052', '053'), 'type-mismatched'),
    ]:
        write_model(producer, bad)
        rejected(lambda: load_model(path), phrase)
    if name_property:
        for bad in [original.replace(name_property, 'IAM.InstanceProfile.Path'),
                    original.replace('`app-preview-one`', '``'),
                    original + 'desired.row.052-003.property=' + name_property + '\n'
                               'desired.row.052-003.value=`duplicate`\n']:
            write_model(producer, bad)
            rejected(lambda: load_model(path), 'exactly one name')
    write_model(producer, original)
    invalid['instances']['existing-label']['labels']['Producer'] = '[broken]'
    rejected(lambda: t.expand(template, human, observed, invalid, 'preview'), 'invalid reference label')
    if kind == 'KMS.Key':
        fixed = template.read_text(encoding='utf-8')
        template.write_text(fixed.replace(
            '# reference: Producer ' + t.json_text({'service': service, 'resource': '052', 'resourceType': kind}),
            '# parameter: Producer ' + t.json_text({'type': 'reference', 'description': '選択する暗号化キー',
                'required': True, 'service': service, 'resourceType': kind})), encoding='utf-8')
        selected = {'instances': {name: {'parameters': {'Producer': '052'}} for name in bindings['instances']}}
        assert t.expand(template, selected, observed, bindings, 'preview')[0] == values
        for target in ['missing', 'app-preview-one']:
            bad = copy.deepcopy(selected)
            bad['instances']['default-label']['parameters']['Producer'] = target
            rejected(lambda: t.expand(template, bad, observed, bindings, 'preview'), 'type-mismatched')
        write_model(producer, original.replace('resourceType=KMS.Key', 'resourceType=KMS.Alias'))
        rejected(lambda: t.expand(template, selected, observed, bindings, 'preview'), 'type-mismatched')
        write_model(producer, original)
        template.write_text(fixed, encoding='utf-8')
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    rejected(lambda: load_model(path), 'missing')


if __name__ == '__main__':
    for service, kind, name in [('iam', 'IAM.InstanceProfile', 'IAM.InstanceProfile.InstanceProfileName'), ('kms', 'KMS.Key', None)]:
        with tempfile.TemporaryDirectory() as directory:
            check(Path(directory).resolve(), service, kind, name)
    print('Group 03 references: PASS (InstanceProfileName; unnamed Key; labels; types; producer/bindings hash/impact; rejection)')
