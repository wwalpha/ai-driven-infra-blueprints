#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.aws_mapping_fixtures import *

def check_payload_selection():
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
        runtime = aws_mapping.runtime_registry(ROOT, path.stem)
        from aws_mapping_catalog import runtime_properties
        assert runtime.properties == aws_mapping.Registry(ROOT, path.stem, runtime_properties).properties
        assert dict(runtime.getters) == dict(mapping.getters)
        assert runtime.identities == mapping.identities
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


def check_runtime_cache():
    import os
    from concurrent.futures import ThreadPoolExecutor
    from aws_mapping_catalog import runtime_properties

    content = (ROOT / 'framework/mappings/aws/config.yaml').read_text(encoding='utf-8')
    with TemporaryDirectory() as directory:
        roots = [Path(directory) / name for name in ('first', 'second')]
        for root in roots:
            path = root / 'framework/mappings/aws/config.yaml'
            path.parent.mkdir(parents=True)
            path.write_text(content, encoding='utf-8')
            path.with_name('iam.yaml').write_text(
                (ROOT / 'framework/mappings/aws/iam.yaml').read_text(encoding='utf-8'), encoding='utf-8')
        root = roots[0]
        path = root / 'framework/mappings/aws/config.yaml'
        with patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as read:
            first = aws_mapping.runtime_registry(root, 'config')
            again = aws_mapping.runtime_registry(root, 'config')
            assert read.call_count == 1 and first.properties == again.properties
            second = aws_mapping.runtime_registry(roots[1], 'config')
            assert read.call_count == 2 and second.root == roots[1]
            iam = aws_mapping.runtime_registry(root, 'iam')
            assert read.call_count == 3 and iam.service == 'iam' and 'IAM.Role' in iam.resource_types

            @input_scope
            def snapshot():
                pinned = aws_mapping.runtime_registry(root, 'config')
                stat = path.stat()
                path.write_text(content.replace('name: RoleName', 'name: OtherRole'), encoding='utf-8')
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                assert aws_mapping.runtime_registry(root, 'config') is pinned
                return pinned

            assert snapshot().properties[RECORDER + '.RoleARN'].name == 'RoleName'
            changed = aws_mapping.runtime_registry(root, 'config')
            assert read.call_count == 4 and changed.properties[RECORDER + '.RoleARN'].name == 'OtherRole'
            path.write_text('invalid: [', encoding='utf-8')
            for _ in range(2):
                try:
                    aws_mapping.runtime_registry(root, 'config')
                except ValueError:
                    pass
                else:
                    raise AssertionError('invalid YAML reused a Registry')
            assert read.call_count == 6, 'exceptions must not be cached'
            path.write_text(content, encoding='utf-8')
            assert aws_mapping.runtime_registry(root, 'config').properties == first.properties
            assert read.call_count == 6
            # Returned attributes and nested defaults must never mutate the private cached Registry.
            first.getters = {}
            first.service = 'changed'
            default = RECORDER + '.RecordingGroup.ResourceTypes'
            first.fields[default].default.append('changed')
            fresh = aws_mapping.runtime_registry(root, 'config')
            assert fresh.service == 'config' and fresh.getters and fresh.fields[default].default == []
            assert fresh.fields[default] is fresh.properties[default].field
            assert fresh.properties == aws_mapping.Registry(root, 'config', runtime_properties).properties
            with ThreadPoolExecutor(max_workers=4) as pool:
                registries = list(pool.map(lambda _: aws_mapping.runtime_registry(root, 'config'), range(8)))
            assert all(item.properties == fresh.properties for item in registries)
            assert len({id(item) for item in registries}) == 8
            registries[0].fields[default].default.append('thread-local')
            assert all(item.fields[default].default == [] for item in registries[1:])


def check_runtime_cache_snapshot_and_bound():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / 'framework/mappings/aws/fixture.yaml'
        path.parent.mkdir(parents=True)
        content = json.dumps({'version': 3, 'service': 'fixture', 'getters': {}, 'resourceTypes': {}})
        path.write_text(content, encoding='utf-8')
        original = aws_mapping.yaml_read

        def read(snapshot):
            path.write_text('invalid: [', encoding='utf-8')
            return original(snapshot)

        with patch.object(aws_mapping, 'yaml_read', side_effect=read):
            assert aws_mapping.runtime_registry(root, 'fixture').service == 'fixture'
        for number in range(129):
            path.write_text(content + f'\n# {number}', encoding='utf-8')
            aws_mapping.runtime_registry(root, 'fixture')
        assert aws_mapping._runtime_registry.cache_info().currsize == 128
        path.write_text(content, encoding='utf-8')
        with patch.object(aws_mapping, 'yaml_read', wraps=original) as parsed:
            aws_mapping.runtime_registry(root, 'fixture')
            assert parsed.call_count == 1, 'least recently used snapshot must be evicted'


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
