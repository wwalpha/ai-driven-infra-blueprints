#!/usr/bin/env python3
"""Offline Mapping and Config regressions with synthetic Config data."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from dataclasses import FrozenInstanceError, astuple
import hashlib
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import copy
import json
import socket

import aws_mapping
from model_display import display_rows
from model_core import entries
from model_files import load_model
from model_design import resource_table_lines
from model_references import resource_rows
from model_templates import expand
from script_loader import module
from support.model_sources import write_model
from validation_cache import input_scope

ROOT = Path(__file__).resolve().parents[4]
m = module('check-model-aws.py', 'model_aws_compare')
RECORDER = 'Config.ConfigurationRecorder'
CHANNEL = 'Config.DeliveryChannel'

# P0 fixture is independent of Registry and contains no consumer values.
BASELINE = {
    RECORDER: {
        'Id': ('name', 'typed', m.MISSING),
        'Name': ('name', 'typed', m.MISSING),
        'RecordingGroup.AllSupported': ('recordingGroup.allSupported', 'typed', m.MISSING),
        'RecordingGroup.ExclusionByResourceTypes.ResourceTypes': ('recordingGroup.exclusionByResourceTypes.resourceTypes', 'set', []),
        'RecordingGroup.IncludeGlobalResourceTypes': ('recordingGroup.includeGlobalResourceTypes', 'typed', m.MISSING),
        'RecordingGroup.RecordingStrategy.UseOnly': ('recordingGroup.recordingStrategy.useOnly', 'typed', m.MISSING),
        'RecordingGroup.ResourceTypes': ('recordingGroup.resourceTypes', 'set', []),
        'RecordingMode.RecordingFrequency': ('recordingMode.recordingFrequency', 'typed', m.MISSING),
        'RoleARN': ('roleARN', 'iam_role', m.MISSING),
    },
    CHANNEL: {'Name': ('name', 'typed', m.MISSING), 'S3BucketName': ('s3BucketName', 'name', m.MISSING)},
}


@input_scope
def check_v3_registry():
    types, supported, identities, getters, apis = set(), set(), 0, 0, []
    properties, definitions, metadata = {}, {}, {}
    paths = sorted((ROOT / 'framework/mappings/aws').glob('*.yaml'))
    assert len(paths) == 50
    for path in paths:
        document = aws_mapping.yaml_read(path.read_text(encoding='utf-8'))
        assert type(document['version']) is int and document['version'] == 3
        mapping = aws_mapping.registry(ROOT, path.stem)
        assert mapping.resource_types == document['resourceTypes'].keys()
        assert not types & mapping.resource_types
        types.update(mapping.resource_types)
        properties[path.stem] = {r: v['properties'] for r, v in document['resourceTypes'].items()}
        definitions[path.stem] = document['getters']
        adapter_getters = {name: tuple(value['resources']) for name, value in mapping.getters.items() if value['kind'] == 'adapter'}
        assert mapping.adapter_resource_types == {r for resources in adapter_getters.values() for r in resources}
        if path.stem not in m.SERVICES:
            assert not mapping.adapter_resource_types and not mapping.identities
            continue
        adapter = m.service_module(path.stem)
        assert all(not hasattr(adapter, name) for name in ('RESOURCE_TYPES', 'IDENTITIES', 'GETTERS'))
        metadata[path.stem] = {'RESOURCE_TYPES': sorted(mapping.adapter_resource_types),
                                'IDENTITIES': {r: astuple(value) for r, value in mapping.identities.items()},
                                'GETTERS': adapter_getters, 'APIS': sorted(adapter.APIS)}
        supported.update(mapping.adapter_resource_types)
        identities += len(mapping.identities)
        getters += len(adapter_getters)
        apis.extend(adapter.APIS)
    assert (len(types), len(supported), identities, getters, len(apis), len(set(apis))) == (178, 52, 50, 63, 79, 78)
    assert not (ROOT / 'framework/mappings/aws/cloudformation-stacks.yaml').exists()
    stack = m.service_module('cloudformation-stacks')
    assert stack.STACK_TYPE == 'CloudFormation.Stack'
    assert all(not hasattr(stack, name) for name in ('RESOURCE_TYPES', 'IDENTITIES', 'GETTERS'))
    metadata['cloudformation-stacks'] = {'RESOURCE_TYPES': ('CloudFormation.Stack',),
                                         'IDENTITIES': {}, 'APIS': sorted(stack.APIS)}
    # Keep the original P0 hash by serializing YAML metadata in its historical shape.
    for values, expected in [(properties, '011c38a46feabd4a28eb4619a3963a3c145f207266dfd757f4a0bbc25a02a463'),
                             (definitions, '345c0f5691eeaf636a27f902e04831de58cd96f5506d1936c67f43edb156944b'),
                             (metadata, '6ddf2190bf6c29c9615b5fad44deb27f8b33007f9fd8b4596be89630da10869b')]:
        assert hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest() == expected
    print('YAML v3/P0 baseline: PASS (50 files, 178 types, 52 adapter types, 50 identities, 63 getters; properties/native getters/metadata/API sets unchanged)')


def check_registry_cache():
    @input_scope
    def cached():
        first = aws_mapping.registry(ROOT, 'config')
        assert aws_mapping.registry(ROOT, 'config') is first
        assert first.identities[RECORDER] == aws_mapping.Identity('recorder', 'name', None, 'Name')
        for mutate in (lambda: setattr(first.identities[RECORDER], 'id_path', 'other'),
                       lambda: first.identities.__setitem__(RECORDER, None),
                       lambda: first.getters['recorder'].__setitem__('resources', ())):
            try:
                mutate()
            except (FrozenInstanceError, AttributeError):
                pass
            else:
                raise AssertionError('mutable Registry definition')
        assert isinstance(first.getters['recorder']['resources'], tuple)
        return first
    with patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as read:
        first = cached()
        assert read.call_count == 1
        assert cached() is not first
        assert read.call_count == 2, 'cache must not survive input scopes'


def check_baseline():
    expected = {kind + '.' + prop: m.Field('recorder' if kind == RECORDER else 'channel', path, norm, default)
                for kind, props in BASELINE.items() for prop, (path, norm, default) in props.items()}
    assert dict(aws_mapping.Registry(ROOT, 'config').fields) == expected
    @input_scope
    def cached():
        first = aws_mapping.registry(ROOT, 'config')
        assert aws_mapping.registry(ROOT, 'config') is first
    cached()
    for kind, props in BASELINE.items():
        rows = [[f'001-{i:03}', kind + '.' + prop, '`fixture`', ''] for i, prop in enumerate(props, 1)]
        shown = display_rows(kind, rows)
        assert [row[1] for row in shown] == ['RoleName' if prop == 'RoleARN' else prop for prop in props]
        assert [row[0] for row in shown] == [row[0] for row in rows]
    assert m.normalize(None, False, 'typed') is False
    assert m.normalize(None, [], 'set') == []
    assert m.normalize(None, ['b', 'a'], 'set') == ['a', 'b']
    assert m.normalize(None, 'bucket-fixture', 'name') == 'bucket-fixture'


def check_config():
    mapping = aws_mapping.registry(ROOT, 'config')
    original_fields = mapping.fields
    role = 'arn:aws:iam::123456789012:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig'
    recorder = {
        'name': 'recorder-fixture', 'roleARN': role,
        'recordingGroup': {'allSupported': False, 'includeGlobalResourceTypes': True,
                           'resourceTypes': ['AWS::S3::Bucket', 'AWS::EC2::VPC'],
                           'exclusionByResourceTypes': {'resourceTypes': []},
                           'recordingStrategy': {'useOnly': 'ALL_SUPPORTED_RESOURCE_TYPES'}},
        'recordingMode': {'recordingFrequency': 'CONTINUOUS', 'recordingModeOverrides': [
            {'description': 'first', 'recordingFrequency': 'DAILY', 'resourceTypes': ['AWS::EC2::VPC']},
            {'description': 'second', 'recordingFrequency': 'CONTINUOUS', 'resourceTypes': ['AWS::S3::Bucket']}]},
    }
    channel = {'name': 'channel-fixture', 's3BucketName': 'fixture-bucket', 's3KeyPrefix': 'config/',
               'configSnapshotDeliveryProperties': {'deliveryFrequency': 'TwentyFour_Hours'},
               's3KmsKeyArn': 'arn:aws:kms:ap-northeast-1:123456789012:key/fixture',
               'snsTopicARN': 'arn:aws:sns:ap-northeast-1:123456789012:fixture'}
    target = {'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1',
              'environment': 'dev', 'directory': 'fixture'}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        # Exercise the existing variable expander, independent of consumer templates.
        schema = 'framework/materials/cloudformation-schema/ap-northeast-1/'
        index = json.loads((ROOT / schema / 'index.json').read_text(encoding='utf-8'))['resourceTypes']
        for relative in ['framework/mappings/aws/config.yaml', schema + 'index.json',
                *[schema + index['AWS::' + kind.replace('.', '::')] for kind in (RECORDER, CHANNEL)], *[
                'framework/materials/aws/' + kind.replace('.', '_') + '.properties' for kind in (RECORDER, CHANNEL)]]:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / relative).read_bytes())
        template = root / 'variable.properties.tpl'
        template.write_text('\n'.join([
            '# model-template: 1', '# definition: channel',
            '# parameter: DeliveryBucketName {"type":"string","description":"Config delivery bucket","required":true}',
            '# resource: channel', '# row: bucket channel',
            'desired.resource.channel.resourceType=' + CHANNEL,
            'desired.resource.channel.anchor=config-delivery-channel-fixture',
            'desired.row.bucket.property=' + CHANNEL + '.S3BucketName',
            'desired.row.bucket.value=`<<DeliveryBucketName>>`',
            'desired.row.bucket.comment=fixture', '# end-definition', '']), encoding='utf-8')
        expanded, _, _ = expand(template, {'instances': {'fixture': {'parameters': {
            'DeliveryBucketName': 'fixture-bucket'}}}}, {'version': 1, 'values': {}}, {'instances': {'fixture': {
                'definition': 'channel', 'resources': {'channel': '002'}, 'rows': {'bucket': '002-002'},
                'parameters': {}}}})
        bucket_value = expanded['desired.row.002-002.value']
        assert bucket_value == '`fixture-bucket`'
        values = {'desired.service.config.serviceId': 'config',
                  'desired.service.config.ownedCatalogResourceTypes': RECORDER + ',' + CHANNEL,
                  'display.service.title': '# Config 詳細設計'}
        for number, kind, payload in [('001', RECORDER, recorder), ('002', CHANNEL, channel)]:
            anchor = 'config-fixture-' + number
            values.update({f'desired.resource.{number}.{key}': value for key, value in {
                'resourceType': kind, 'resourceMode': 'IMPORT', 'logicalId': 'Fixture' + number, 'anchor': anchor}.items()})
            for index, (prop, (path, norm, default)) in enumerate(BASELINE[kind].items(), 1):
                value = m.select(payload, path)
                value = default if value == m.MISSING else value
                raw = '`' + (value if isinstance(value, str) else json.dumps(value)) + '`'
                if prop == 'RoleARN':
                    raw = '`AWSServiceRoleForConfig`'
                elif prop == 'S3BucketName':
                    raw = bucket_value
                elif prop == 'Id':
                    raw = f'[Fixture{number}](#{anchor})'
                    values[f'observed.row.{number}-{index:03}.value'] = payload['name']
                values.update({f'desired.row.{number}-{index:03}.{key}': val for key, val in {
                    'property': kind + '.' + prop, 'value': raw, 'comment': 'fixture'}.items()})
        path = root / 'model/dev/fixture/config.properties'
        write_model(path, values)

        def context(bucket='fixture-bucket'):
            calls = []
            def call(api, result, **inputs):
                calls.append((api, inputs))
                return result
            clients = {
                'config': SimpleNamespace(
                    describe_configuration_recorders=lambda **inputs: call('recorder', {'ConfigurationRecorders': [recorder]}, **inputs),
                    describe_delivery_channels=lambda **inputs: call('channel', {'DeliveryChannels': [dict(channel, s3BucketName=bucket)]}, **inputs)),
                'iam': SimpleNamespace(get_role=lambda **inputs: call('role', {'Role': {'Arn': role}}, **inputs)),
            }
            ctx = m.Context(root, target, session=SimpleNamespace(client=lambda service, **kwargs: clients[service]), services=['config'])
            ctx.verified = True
            return ctx, calls

        def compare(bucket):
            ctx, calls = context(bucket)
            model = ctx.model(path)
            results = [item for resource in model.resources for item in m.compare_resource(ctx, resource)]
            for resource in model.resources:
                for _ in range(2):
                    ctx.fetch(resource, 'recorder' if resource.kind == RECORDER else 'channel')
            assert sorted(api for api, _ in calls) == ['channel', 'recorder', 'role']
            return results

        match, difference = compare('fixture-bucket'), compare('different-bucket')
        assert len(match) == 11 and sum(item['status'] == 'match' for item in match) == 10
        assert sum(item['status'] == 'identifier' for item in match) == 1
        assert [item['propertiesKey'] for item in difference if item['status'] == 'difference'] == [CHANNEL + '.S3BucketName']
        importer = module('import-model.py', 'aws_mapping_config_import')
        records = [{'kind': kind, 'identity': payload['name'], 'getters': {getter: payload}}
                   for kind, getter, payload in [(RECORDER, 'recorder', recorder), (CHANNEL, 'channel', channel)]]
        ctx, _ = context()
        model = ctx.model(path)
        imported = importer.snapshot_values(ctx, model, copy.deepcopy(records), {})
        imported_values, _, unreflected, _ = imported
        assert not unreflected
        assert set(dict(entries(imported_values, 'desired.row.'))) == set(dict(entries(model.values, 'desired.row.')))
        assert dict(entries(imported_values, 'desired.resource.')) == dict(entries(model.values, 'desired.resource.'))
        assert imported_values['desired.row.002-002.value'] == bucket_value
        assert imported_values['desired.row.001-009.value'] == '`' + role + '`', 'IMPORT retains the acquired ARN instead of reducing it to a name'
        assert load_model(path).values == model.values
        tables = []
        for resource in model.resources:
            rows = resource_rows(model.values, resource.number, resource.kind, ROOT)
            table = resource_table_lines(resource.spec, 'fixture', rows, [], ROOT)
            tables.extend(['### ' + resource.kind + ': fixture', *table])
        markdown = '\n'.join(['## リソース詳細', *tables])
        assert '| RoleName |' in markdown and '| RoleARN |' not in markdown
        assert '| S3BucketName | `fixture-bucket` |' in markdown
        assert 'S3KeyPrefix' not in markdown and 'ConfigSnapshotDeliveryProperties' not in markdown
        document = root / 'docs/designs/dev/fixture/config.md'
        document.parent.mkdir(parents=True)
        document.write_text(markdown, encoding='utf-8')
        catalog = root / 'framework/materials/aws'
        catalog.mkdir(parents=True, exist_ok=True)
        for kind in (RECORDER, CHANNEL):
            name = kind.replace('.', '_') + '.properties'
            (catalog / name).write_bytes((ROOT / 'framework/materials/aws' / name).read_bytes())
        # Read every catalog leaf, including excluded fields; preserve SDK types/array grouping.
        payloads = {'recorder': recorder, 'channel': channel}
        extracted = {key: m.select(payloads[prop.field.getter], prop.field.path)
                     for key, prop in mapping.properties.items()}
        assert extracted[CHANNEL + '.S3KeyPrefix'] == 'config/'
        assert extracted[CHANNEL + '.ConfigSnapshotDeliveryProperties.DeliveryFrequency'] == 'TwentyFour_Hours'
        assert extracted[RECORDER + '.RecordingGroup.AllSupported'] is False
        assert extracted[RECORDER + '.RecordingMode.RecordingModeOverrides[].ResourceTypes'] == [['AWS::EC2::VPC'], ['AWS::S3::Bucket']]
        assert m.select({}, mapping.properties[CHANNEL + '.S3KeyPrefix'].field.path) == m.MISSING
        assert m.select({'s3KeyPrefix': None}, 's3KeyPrefix') is None
        assert m.select({'s3KeyPrefix': ''}, 's3KeyPrefix') == ''
        shown = [prop.name for key, prop in mapping.properties.items() if key.startswith(CHANNEL + '.') and prop.show]
        assert shown == ['Name', 'S3BucketName']
        assert mapping.properties[RECORDER + '.RoleARN'].name == 'RoleName'
        assert all(not prop.show and not prop.include for key, prop in mapping.properties.items() if key not in original_fields)


def main():
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        check_v3_registry()
        check_registry_cache()
        check_baseline()
        check_config()
    print('AWS Mapping checks: PASS (Config values, variables, Compare, IMPORT and display 18/18; no AWS connection)')


if __name__ == '__main__':
    main()
