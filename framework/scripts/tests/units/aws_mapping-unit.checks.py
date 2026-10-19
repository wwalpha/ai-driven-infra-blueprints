#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.aws_mapping_fixtures import *
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import pytest
from threading import Barrier
import aws_mapping_catalog
from utils.aws_mappings import mappings_for, owners, mapping_alias
from validation_cache import memo_table

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
        assert runtime.properties == aws_mapping.Registry(ROOT, path.stem, document, runtime_properties(ROOT, path.stem, document)).properties
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
    tgw_properties = {
        'EC2.TransitGateway': {'Id', 'AmazonSideAsn', 'Description', 'DnsSupport',
                              'DefaultRouteTableAssociation', 'DefaultRouteTablePropagation',
                              'AutoAcceptSharedAttachments', 'VpnEcmpSupport'},
        'EC2.TransitGatewayRouteTable': {'TransitGatewayRouteTableId', 'TransitGatewayId'},
        'EC2.TransitGatewayRoute': {'TransitGatewayRouteTableId', 'DestinationCidrBlock',
                                  'TransitGatewayAttachmentId', 'Blackhole'},
        'EC2.TransitGatewayRouteTableAssociation': {'TransitGatewayRouteTableId', 'TransitGatewayAttachmentId'},
        'EC2.TransitGatewayRouteTablePropagation': {'TransitGatewayRouteTableId', 'TransitGatewayAttachmentId'},
    }
    assert sum(map(len, tgw_properties.values())) == 18
    from copy import deepcopy
    baseline_properties = deepcopy(properties)
    for kind, selected in tgw_properties.items():
        actual = properties['ec2'][kind]
        assert {name for name, prop in actual.items() if prop['model']['include']} == selected, kind
        assert {name for name, prop in actual.items() if prop['display']['show']} == selected, kind
        for name in selected:
            assert actual[name]['model']['include'] is True, (kind, name)
            assert actual[name]['display']['show'] is True, (kind, name)
            # Restore only the two authorized flags in a test-local copy for the original hash.
            baseline_properties['ec2'][kind][name]['model']['include'] = False
            baseline_properties['ec2'][kind][name]['display']['show'] = False
    # Keep the original P0 hash by serializing YAML metadata in its historical shape.
    for values, expected in [(baseline_properties, '011c38a46feabd4a28eb4619a3963a3c145f207266dfd757f4a0bbc25a02a463'),
                             (definitions, '345c0f5691eeaf636a27f902e04831de58cd96f5506d1936c67f43edb156944b'),
                             (metadata, '6ddf2190bf6c29c9615b5fad44deb27f8b33007f9fd8b4596be89630da10869b')]:
        assert hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest() == expected
    print('YAML v3/P0 baseline: PASS (50 files, 178 types, 52 adapter types, 50 identities, 63 getters; 18 TGW include/show changes explicit; all other properties/native getters/metadata/API sets unchanged)')


def check_registry_cache():
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory), 'config')
        @input_scope
        def cached():
            first = aws_mapping.registry(root, 'config')
            assert aws_mapping.registry(root, 'config') is first
            assert first.identities[RECORDER] == aws_mapping.Identity('recorder', 'name', None, 'Name')
            for mutate in (lambda: setattr(first.identities[RECORDER], 'id_path', 'other'),
                           lambda: first.identities.__setitem__(RECORDER, None),
                           lambda: first.getters['recorder'].__setitem__('resources', ()),
                           lambda: setattr(first, 'service', 'other')):
                with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
                    mutate()
            assert isinstance(first.getters['recorder']['resources'], tuple)
            return first
        with patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as read, \
             patch.object(aws_mapping_catalog, 'catalog_properties', wraps=aws_mapping_catalog.catalog_properties) as compile:
            first = cached()
            assert read.call_count == compile.call_count == 1
            assert cached() is not first
            assert read.call_count == compile.call_count == 1
            assert cached().properties is first.properties


def check_baseline():
    expected = {kind + '.' + prop: m.Field('recorder' if kind == RECORDER else 'channel', path, norm, default)
                for kind, props in BASELINE.items() for prop, (path, norm, default) in props.items()}
    assert {key: replace(field, default=field.copy_default())
            for key, field in aws_mapping.registry(ROOT, 'config').fields.items()} == expected
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


def check_import_and_owners_are_lazy():
    # A fresh interpreter verifies import side effects without reloading shared state.
    import subprocess
    code = """from pathlib import Path
from unittest.mock import patch
with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected read')):
    import utils.aws_mappings
assert not utils.aws_mappings._instances
"""
    subprocess.run([sys.executable, '-c', code], cwd=ROOT / 'framework/scripts', check=True)
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory), 'config', 'iam')
        original = Path.read_text
        reads = []
        def read(path, *args, **kwargs):
            reads.append(path)
            return original(path, *args, **kwargs)
        barrier = Barrier(8)
        def obtain(_):
            barrier.wait(timeout=10)
            return mappings_for(root)
        with patch.object(Path, 'read_text', read), patch.object(aws_mapping, 'yaml_read') as parse:
            with ThreadPoolExecutor(max_workers=8) as pool:
                providers = list(pool.map(obtain, range(8)))
            assert all(provider is providers[0] for provider in providers)
            assert owners(root) is owners(root)
            assert owners(root)[RECORDER] == 'config'
            assert reads == [root / 'framework/mappings/aws/owners.json']
            parse.assert_not_called()
            with pytest.raises(KeyError):
                owners(root)['Unknown.Resource']
            with pytest.raises(TypeError):
                owners(root)[RECORDER] = 'iam'
            for service in ('unknown', '../config', None):
                with pytest.raises(ValueError, match='unknown Mapping service'):
                    providers[0].get(service)
            assert len(reads) == 1


def check_runtime_cache():
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory) / 'first', 'config', 'iam', 'sns')
        other = mapping_fixture(Path(directory) / 'second', 'config')
        original = Path.read_text
        reads = []
        def read(path, *args, **kwargs):
            if path.suffix == '.yaml':
                reads.append(path)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read), \
             patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as parse, \
             patch.object(aws_mapping_catalog, 'runtime_properties', wraps=aws_mapping_catalog.runtime_properties) as compile:
            provider = mappings_for(root)
            first = provider.get('config')
            assert provider.get(owners(root)[RECORDER]) is provider.get(owners(root)[CHANNEL]) is first
            @input_scope
            def scoped():
                assert aws_mapping.runtime_registry(root, 'config') is first
                memo_table().clear()
                assert aws_mapping.runtime_registry(root, 'config') is first
            scoped()
            scoped()
            assert parse.call_count == compile.call_count == 1
            assert mappings_for(root).get('iam').service == 'iam'
            assert mappings_for(other).get('config') is not first
            assert parse.call_count == compile.call_count == 3
            assert reads == [root / 'framework/mappings/aws/config.yaml', root / 'framework/mappings/aws/iam.yaml',
                             other / 'framework/mappings/aws/config.yaml']
            # These are static definitions: later filesystem changes cannot alter this instance.
            (root / 'framework/mappings/aws/config.yaml').write_text('invalid: [', encoding='utf-8')
            assert provider.get('config') is first
            assert parse.call_count == 3


def check_parallel_services():
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory), 'config', 'iam')
        provider = mappings_for(root)
        start, parsing = Barrier(8), Barrier(2)
        original = aws_mapping.yaml_read
        def parse(content):
            parsing.wait(timeout=10)  # Different services must not hold a common lock.
            return original(content)
        def get(number):
            start.wait(timeout=10)
            return provider.get('config' if number % 2 else 'iam')
        with patch.object(aws_mapping, 'yaml_read', side_effect=parse) as read, \
             patch.object(aws_mapping_catalog, 'runtime_properties', wraps=aws_mapping_catalog.runtime_properties) as compile:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(get, range(8)))
            assert read.call_count == compile.call_count == 2
        assert all(item is results[number % 2] for number, item in enumerate(results))


def check_runtime_full_reuse():
    with TemporaryDirectory() as directory:
        for order in ('runtime-first', 'full-first', 'parallel'):
            root = mapping_fixture(Path(directory) / order, 'sqs')
            provider = mappings_for(root)
            barrier = Barrier(8)
            def obtain(number):
                barrier.wait(timeout=10)
                return provider.get('sqs') if number % 2 else aws_mapping.registry(root, 'sqs')
            with patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as parse:
                if order == 'runtime-first':
                    runtime, full = provider.get('sqs'), aws_mapping.registry(root, 'sqs')
                elif order == 'full-first':
                    full, runtime = aws_mapping.registry(root, 'sqs'), provider.get('sqs')
                else:
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        results = list(pool.map(obtain, range(8)))
                    runtime, full = results[1], results[0]
                    assert all(results[n] is runtime for n in (1, 3, 5, 7))
                assert parse.call_count == 1
                # Full compilation retains input extraction classification; runtime retains executable fields.
                assert full.getters == runtime.getters and full.identities == runtime.identities
                key = 'SQS.Queue.QueueName'
                assert full.properties[key].field.classification == 'local_metadata'
                assert runtime.properties[key].field.classification == 'supported'
                assert provider.get('sqs') is runtime


def check_runtime_failures():
    class Cancelled(BaseException):
        pass
    with TemporaryDirectory() as directory:
        for fault in ('read', 'parse', 'runtime', 'control'):
            root = mapping_fixture(Path(directory) / fault, 'config')
            provider = mappings_for(root)
            if fault == 'parse':
                (root / 'framework/mappings/aws/config.yaml').write_text('invalid: [', encoding='utf-8')
            original = Path.read_text
            reads = []
            def read(path, *args, **kwargs):
                if path.suffix == '.yaml':
                    reads.append(path)
                    if fault == 'read':
                        raise OSError('injected read failure')
                return original(path, *args, **kwargs)
            barrier = Barrier(8)
            def obtain(_):
                barrier.wait(timeout=10)
                try:
                    provider.get('config')
                except BaseException as error:
                    return error
                raise AssertionError('failure accepted')
            runtime = aws_mapping_catalog.runtime_properties
            def compile(*args):
                if fault == 'runtime':
                    raise ValueError('injected runtime failure')
                if fault == 'control':
                    raise Cancelled('control exception')
                return runtime(*args)
            with patch.object(Path, 'read_text', read), \
                 patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as parse, \
                 patch.object(aws_mapping_catalog, 'runtime_properties', side_effect=compile) as build:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    errors = list(pool.map(obtain, range(8)))
                with pytest.raises(type(errors[0])):
                    provider.get('config')
                assert all(error is errors[0] for error in errors)
                assert len(reads) == 1
                assert parse.call_count == (0 if fault == 'read' else 1)
                assert build.call_count == (1 if fault in ('runtime', 'control') else 0)
                if fault in ('runtime', 'control'):
                    assert aws_mapping.registry(root, 'config').service == 'config'
                    assert parse.call_count == 1, 'runtime failure must retain a usable document'


def check_full_failure_isolation():
    from utils.aws_mappings import Mappings
    from utils.aws_sdk import Sdk
    from utils.aws_schemas import Schemas
    from utils.aws_catalogs import Catalogs
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory), 'sns')
        runtime_provider = mappings_for(root)
        with patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as parse:
            for target in ('sdk_shape', 'DesignSchemaCatalog'):
                # Patching validation code changes its lifetime: use fresh instances.
                provider = Mappings(root)
                sdk, schemas, catalogs = Sdk(), Schemas(root), Catalogs(root)
                with patch.object(aws_mapping_catalog, target, side_effect=ValueError('injected full failure')):
                    def failed():
                        with pytest.raises(ValueError, match='injected full failure'):
                            provider.validated('sns', sdk, schemas, catalogs, aws_mapping_catalog.catalog_properties)
                    input_scope(failed)()
                    runtime = runtime_provider.get('sns')
                    input_scope(failed)()
                    assert runtime_provider.get('sns') is runtime
                fresh = Mappings(root)
                assert fresh.validated('sns', Sdk(), Schemas(root), Catalogs(root),
                                       aws_mapping_catalog.catalog_properties).resource_types == runtime.resource_types
            assert parse.call_count == 5


def check_stage_alias():
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory) / 'source', 'config')
        stage = mapping_fixture(Path(directory) / 'stage', 'config')
        provider = mappings_for(root)
        with pytest.raises(RuntimeError, match='injected'), mapping_alias(root, stage):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: mappings_for(stage).get('config'), range(4)))
            assert all(item is provider.get('config') for item in results)
            sibling = mapping_fixture(Path(str(stage) + '-prefix'), 'config')
            assert mappings_for(sibling) is not provider
            with pytest.raises(ValueError, match='already has a provider'), mapping_alias(root, stage):
                pass
            raise RuntimeError('injected')
        assert mappings_for(stage) is not provider
        with pytest.raises(ValueError, match='already has a provider'), mapping_alias(root, stage):
            pass
        second = Path(directory) / 'short-lived'
        with mapping_alias(root, second):
            assert mappings_for(second) is provider
        assert second not in __import__('utils.aws_mappings', fromlist=['_aliases'])._aliases


def check_ownership_errors():
    with TemporaryDirectory() as directory:
        for number, index in enumerate(('{}', '[]', '{"Config.ConfigurationRecorder":1}',
                '{"bad":"config"}', '{"Config.ConfigurationRecorder":"../config"}',
                '{"Config.ConfigurationRecorder":"config","Config.ConfigurationRecorder":"iam"}',
                '{"Config.ConfigurationRecorder":NaN}')):
            root = Path(directory) / str(number)
            path = root / 'framework/mappings/aws/owners.json'
            path.parent.mkdir(parents=True)
            path.write_text(index, encoding='utf-8')
            with patch.object(aws_mapping, 'yaml_read') as parse, pytest.raises(ValueError):
                mappings_for(root)
            parse.assert_not_called()
        for fault in ('missing', 'extra', 'owner'):
            root = mapping_fixture(Path(directory) / fault, 'config', 'iam')
            path = root / 'framework/mappings/aws/owners.json'
            index = json.loads(path.read_text(encoding='utf-8'))
            if fault == 'missing':
                del index[CHANNEL]
            elif fault == 'extra':
                index['Config.Unknown'] = 'config'
            else:
                index[CHANNEL] = 'iam'
            path.write_text(json.dumps(index), encoding='utf-8')
            with patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as parse:
                for _ in range(2):
                    with pytest.raises(ValueError, match='ownership index mismatch'):
                        mappings_for(root).get('config')
                assert parse.call_count == 1


def check_readonly_defaults():
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory), 'config')
        path = root / 'framework/mappings/aws/config.yaml'
        document = aws_mapping.yaml_read(path.read_text(encoding='utf-8'))
        key = RECORDER + '.RecordingGroup.ResourceTypes'
        values = [[], {'nested': [False, 0, None, {'leaf': []}]}, False, 0, None, m.MISSING]
        for number, default in enumerate(values):
            document['resourceTypes'][RECORDER]['properties']['RecordingGroup.ResourceTypes']['aws']['default'] = default
            candidate = mapping_fixture(Path(directory) / str(number), 'config')
            (candidate / 'framework/mappings/aws/config.yaml').write_text(json.dumps(document), encoding='utf-8')
            result = mappings_for(candidate).get('config')
            field = result.fields[key]
            assert field is result.properties[key].field
            assert field.copy_default() == default
            assert type(field.copy_default()) is type(default)
            assert asdict(replace(result.properties[key], field=replace(field, default=field.copy_default())))['field']['default'] == default
            with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
                result.getters['recorder']['resources'] += ('changed',)
            with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
                result.properties[key].field.default = 'changed'
            if isinstance(default, list):
                with pytest.raises(AttributeError):
                    field.default.append('changed')
                field.copy_default().append('independent')
                assert field.copy_default() == default
                assert m.normalize(None, field.copy_default(), 'set') == []
            if isinstance(default, dict):
                with pytest.raises(TypeError):
                    field.default['changed'] = True
                detached = field.copy_default()
                detached['changed'] = True
                assert field.copy_default() == default
                if 'nested' in default:
                    with pytest.raises(AttributeError):
                        field.default['nested'][3]['leaf'].append(1)
                    detached['nested'][3]['leaf'].append(1)
                    assert field.copy_default() == default
        # Field is embedded verbatim into standalone audits; it must need no repo imports.
        generator = module('model-test.py', 'model_test_generator')
        namespace = {}
        exec('from dataclasses import dataclass\n' + generator.definitions(ROOT / 'framework/scripts/check-model-aws.py', ['Field']), namespace)
        assert namespace['Field'](default={'nested': (False, 0, None)}).copy_default() == {'nested': [False, 0, None]}


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
