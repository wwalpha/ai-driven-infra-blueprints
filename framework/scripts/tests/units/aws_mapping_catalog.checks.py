#!/usr/bin/env python3
"""Offline coverage, provenance and projection checks; no consumer fixture copies."""

import os
import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import copy
import socket
from collections import Counter
from dataclasses import replace
from importlib import import_module
from unittest.mock import patch

import aws_mapping_catalog as catalog
import yaml
from aws_mapping import registry as mapping_registry
from aws_mapping_catalog import catalog_properties, project
from aws_mapping_display import MODEL_ONLY, display_name, formal_name
from botocore.session import get_session
from design.catalog import design_material_files
from utils.aws_mappings import owners
from utils.aws_sdk import Sdk, aws_runtime
from utils.input_cache import input_scope
from utils.script_loader import module

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

ROOT = Path(__file__).resolve().parents[4]
m = module('model/adapters/aws.py', 'model.adapters.aws')


@input_scope
def coverage():
    catalog = {line.partition('=')[0] for p in design_material_files(ROOT)
               for line in p.read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#')}
    properties, types, sources, summaries = {}, set(), Counter(), []
    expected_owners = {}
    for path in sorted((ROOT / 'framework/mappings/aws').glob('*.yaml')):
        registry = mapping_registry(ROOT, path.stem)
        document = yaml.safe_load(path.read_text(encoding='utf-8'))
        for kind in document['resourceTypes']:
            assert kind not in expected_owners, 'duplicate ownership'
            expected_owners[kind] = path.stem
        declared = {kind + '.' + prop: definition
                    for kind, resource in document['resourceTypes'].items()
                    for prop, definition in resource['properties'].items()}
        assert set(registry.fields) == {key for key, item in declared.items() if item['model']['include']}
        assert not properties.keys() & registry.properties.keys(), 'duplicate mapping ownership'
        properties.update(registry.properties)
        kinds = {'.'.join(k.split('.')[:2]) for k in registry.properties}
        assert not types & kinds, 'resource type split across files'
        types |= kinds
        count = Counter(p.source for p in registry.properties.values())
        sources.update(count)
        summaries.append((path.stem, len(kinds), len(registry.properties), len(registry.fields), dict(count)))
        for key, prop in registry.properties.items():
            kind = '.'.join(key.split('.')[:2])
            # Flags belong to Mapping; optional captures need no pre-existing Model row.
            assert prop.include is declared[key]['model']['include'], 'include mismatch: ' + key
            assert prop.show is declared[key]['display']['show'], 'show mismatch: ' + key
            assert prop.name == declared[key]['display']['name'], 'display name mismatch: ' + key
            assert formal_name(display_name(key, kind, ROOT), kind, ROOT) == key, 'display roundtrip: ' + key
            if prop.source != 'aws':
                assert prop.field.classification != 'supported' and prop.constraint
    assert dict(owners(ROOT)) == expected_owners, 'ownership index missing/extra/wrong owner'
    assert properties.keys() == catalog, 'missing/extra catalog mapping'
    model_only = {key for service in m.SERVICES
                  for key in getattr(m.service_module(service), 'MODEL_FIELDS', {})}
    assert model_only == MODEL_ONLY, 'adapter/display Model-only mismatch'
    assert not model_only & catalog, 'Model-only property declared in catalog'
    assert all(not hasattr(m.service_module(service), 'FIELDS') for service in m.SERVICES)
    print(f'Catalog coverage: PASS ({len(types)} resource types / {len(properties)} properties; missing/extra/duplicates 0; include {sum(p.include for p in properties.values())}; Model-only {len(model_only)}; old definitions 0)')
    print('Sources:', dict(sources))
    for summary in summaries:
        print('Service:', *summary)


def _callback_initialization_checks_next_scope(document, sdk, /):
    catalog.catalog_properties(ROOT, 'sns', document, sdk=sdk)


def _callback_initialization_checks_reuse(_state_initialization_checks_88, document, sdk, /):
    catalog.catalog_properties(ROOT, 'sns', document, sdk=sdk)
    catalog.catalog_properties(ROOT / '.', 'sns', document, sdk=sdk)
    assert _state_initialization_checks_88.sessions.call_count == 1
    session = sdk.session()
    with patch.object(session, 'get_service_model', wraps=session.get_service_model) as models:
        sdk.service_model('sqs')
        sdk.service_model('sqs')
        assert models.call_count == 1
    # A new instance explicitly captures replacement factory/settings.
    with patch('botocore.session.get_session', wraps=get_session) as replacement:
        catalog.catalog_properties(ROOT, 'sns', document, sdk=Sdk(replacement))
        assert replacement.call_count == 1
    with patch.dict(os.environ, {'AWS_DATA_PATH': '/nonexistent-offline-sdk-data'}):
        separate = Sdk(_state_initialization_checks_88.sessions)
        catalog.catalog_properties(ROOT, 'sns', document, sdk=separate)
        assert separate.data_path == '/nonexistent-offline-sdk-data'
        assert sdk.session().get_config_variable('data_path') == sdk.data_path
        assert _state_initialization_checks_88.sessions.call_count == 2


def initialization_checks():
    assert aws_runtime() is aws_runtime() is import_module('utils.aws_sdk_runtime')
    assert 'aws_sdk_runtime' not in sys.modules

    _state_initialization_checks_88 = _CallbackState()
    adapter = yaml.safe_load((ROOT / 'framework/mappings/aws/config.yaml').read_text(encoding='utf-8'))
    document = yaml.safe_load((ROOT / 'framework/mappings/aws/sns.yaml').read_text(encoding='utf-8'))
    with patch('botocore.session.get_session', wraps=get_session) as _state_initialization_checks_88.sessions:
        sdk = Sdk(_state_initialization_checks_88.sessions)
        catalog.catalog_properties(ROOT, 'config', adapter, sdk=sdk)
        assert _state_initialization_checks_88.sessions.call_count == 0, 'adapter-only Mapping needs no SDK session'

        reuse = (input_scope)(_bind_framework_callback(_callback_initialization_checks_reuse, _state_initialization_checks_88, document, sdk))
        reuse()
        next_scope = (input_scope)(_bind_framework_callback(_callback_initialization_checks_next_scope, document, sdk))
        next_scope()
        assert _state_initialization_checks_88.sessions.call_count == 2, 'new input scopes reuse the same SDK definitions'
    with patch('botocore.session.get_session', wraps=get_session) as _state_initialization_checks_88.sessions:
        assert Sdk(_state_initialization_checks_88.sessions).session() is not Sdk(_state_initialization_checks_88.sessions).session()
        assert _state_initialization_checks_88.sessions.call_count == 2
    print('Mapping initialization: PASS (adapter 0; cross-scope reuse; explicit factory/data/instance isolation)')


@input_scope
def schema_checks():
    document = yaml.safe_load((ROOT / 'framework/mappings/aws/sns.yaml').read_text(encoding='utf-8'))
    root = ROOT
    native = copy.deepcopy(document)
    native['resourceTypes']['SNS.Topic']['identity'] = {'getter': 'provider-sns-topic', 'idPath': 'TopicArn',
                                                      'arnPath': 'TopicArn', 'nameProperty': 'TopicName'}
    native['resourceTypes']['SNS.TopicPolicy']['identity'] = {'getter': 'sdk-sns-topicpolicy', 'idPath': 'Attributes',
                                                            'arnPath': None, 'nameProperty': None}
    for resource, key, value in [('SNS.Topic', 'getter', 'sdk-sns-topicpolicy'),
                                 ('SNS.Topic', 'idPath', 'Unknown'),
                                 ('SNS.Topic', 'nameProperty', 'Unknown'),
                                 ('SNS.TopicPolicy', 'idPath', 'attributes')]:
        candidate = copy.deepcopy(native)
        candidate['resourceTypes'][resource]['identity'][key] = value
        try:
            catalog_properties(root, 'sns', candidate)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid native identity accepted')
    prop = 'provider-sns-topic'
    mutations = [
        lambda d: d.update(service='other'),
        lambda d: d.update(version=True),
        lambda d: d.update(extra=True),
        lambda d: d['getters'][prop].update(operation='delete_resource'),
        lambda d: d['getters'][prop].update(result='ResourceDescription.Unknown'),
        lambda d: d['getters'][prop].update(identifier=['/properties/Unknown']),
        lambda d: d['resourceTypes']['SNS.Topic']['properties'].pop('TopicName'),
        lambda d: d['resourceTypes']['SNS.Topic']['properties']['TopicName']['aws'].update(path='Unknown'),
        lambda d: d['resourceTypes']['SNS.Topic']['properties']['TopicName']['aws'].update(getter='missing'),
        lambda d: d['resourceTypes']['SNS.Topic']['properties']['TopicName']['aws'].update(normalize='unknown'),
        lambda d: d['resourceTypes']['SNS.Topic']['properties']['TopicName']['aws'].update(transform='guess'),
        lambda d: d['resourceTypes']['SNS.Topic']['properties']['TopicName']['aws'].update(transform='present'),
        lambda d: d['resourceTypes']['SNS.Topic']['properties']['TopicName']['access'].append('write-only'),
        lambda d: d['resourceTypes']['SNS.Topic']['properties']['TopicName']['model'].update(include='false'),
        lambda d: d['resourceTypes']['SNS.Topic']['properties']['TopicName']['display'].update(show=True),
        lambda d: d['resourceTypes']['SNS.TopicPolicy']['properties']['PolicyDocument']['aws'].update(path='Attributes.policy'),
        lambda d: d['resourceTypes']['SNS.TopicPolicy']['properties']['Id']['source'].update(kind='aws'),
        lambda d: d['resourceTypes']['SNS.TopicPolicy']['properties']['Id']['source'].update(constraint='unimplemented'),
        lambda d: d['getters'].update(unused=copy.deepcopy(d['getters'][prop])),
    ]
    for mutate in mutations:
        candidate = copy.deepcopy(document)
        mutate(candidate)
        try:
            catalog_properties(root, 'sns', candidate)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid v3 Mapping accepted: ' + repr(candidate))
    candidate = copy.deepcopy(document)
    item = candidate['resourceTypes']['SNS.Topic']['properties']['TopicName']
    del item['aws']
    item['source'] = {'kind': 'model', 'location': 'desired row SNS.Topic.TopicName', 'classification': 'local_metadata', 'constraint': 'Do not replace an available AWS source.'}
    try:
        catalog_properties(root, 'sns', candidate)
    except ValueError:
        pass
    else:
        raise AssertionError('unsupported non-AWS fallback accepted')
    original = yaml.safe_load((ROOT / 'framework/mappings/aws/s3.yaml').read_text(encoding='utf-8'))
    invalid = [
        lambda d: d.update(version=2),
        lambda d: d['getters']['base'].update(adapter='s3'),
        lambda d: d['getters']['base'].update(apis=[]),
        lambda d: d['getters']['base'].update(resources=['S3.Unknown']),
        lambda d: d['getters']['base'].update(resources=['S3.Bucket', 'S3.Bucket']),
        lambda d: d['getters']['base'].update(resources=[{}]),
        lambda d: d['getters']['base'].update(resources='S3.Bucket'),
        lambda d: d['resourceTypes']['S3.Bucket'].update(identity=None),
        lambda d: d['resourceTypes']['S3.Bucket']['identity'].pop('idPath'),
        lambda d: d['resourceTypes']['S3.Bucket']['identity'].update(extra='Name'),
        lambda d: d['resourceTypes']['S3.Bucket']['identity'].update(getter='unknown'),
        lambda d: d['resourceTypes']['S3.Bucket']['identity'].update(getter='policy'),
        lambda d: d['resourceTypes']['S3.Bucket']['identity'].update(idPath=None),
        lambda d: d['resourceTypes']['S3.Bucket']['identity'].update(idPath='Name..Id'),
        lambda d: d['resourceTypes']['S3.Bucket']['identity'].update(arnPath=[]),
        lambda d: d['resourceTypes']['S3.Bucket']['identity'].update(nameProperty='Unknown'),
    ]
    for mutate in invalid:
        candidate = copy.deepcopy(original)
        mutate(candidate)
        try:
            catalog_properties(ROOT, 's3', candidate)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid adapter getter/identity accepted')
    for change in ('getter', 'default', 'source', 'transform'):
        candidate = copy.deepcopy(original)
        item = candidate['resourceTypes']['S3.Bucket']['properties']['ObjectLockEnabled']
        if change == 'getter':
            candidate['getters']['lock']['name'] = 'base'
        elif change == 'default':
            item['aws']['default'] = 0  # False and integer zero must not compare as equal defaults.
        elif change == 'transform':
            item['aws']['transform'] = 'unique'
        else:
            del item['aws']
            item['source'] = {'kind': 'model', 'location': 'desired row', 'classification': 'local_metadata', 'constraint': 'Cannot replace an available AWS value.'}
        try:
            catalog_properties(ROOT, 's3', candidate)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid Mapping accepted: ' + change)
    candidate = copy.deepcopy(original)
    candidate['resourceTypes']['S3.Bucket']['properties']['ObjectLockEnabled']['aws']['default'] = True
    assert catalog_properties(ROOT, 's3', candidate)['S3.Bucket.ObjectLockEnabled'].field.default is True
    candidate = copy.deepcopy(original)
    getter = candidate['getters'].pop('lock')
    candidate['getters']['unknown'] = getter
    candidate['resourceTypes']['S3.Bucket']['properties']['ObjectLockEnabled']['aws']['getter'] = 'unknown'
    try:
        catalog_properties(ROOT, 's3', candidate)
    except ValueError as error:
        assert 'unknown getter' in str(error)
    else:
        raise AssertionError('undeclared acquisition getter accepted')
    print('Mapping schema: PASS (provider capability/identity, API casing, provenance, types, flags, negative definitions)')


@input_scope
def projections():
    webhook = mapping_registry(ROOT, 'codebuild').properties['CodeBuild.Project.Triggers.Webhook']
    assert project(webhook, {}) is False
    assert project(webhook, {'webhook': None}) is False
    assert project(webhook, {'webhook': {'url': 'fixture'}}) is True
    account = mapping_registry(ROOT, 'datazone').properties['DataZone.Connection.AwsLocation.AwsAccountId']
    assert project(account, {'physicalEndpoints': [{'awsLocation': {'awsAccountId': 'fixture'}}]}) == 'fixture'
    assert project(account, {'physicalEndpoints': []}) == m.MISSING
    assert project(account, {'physicalEndpoints': [{'awsLocation': {'awsAccountId': 'fixture'}}, {}]}) == m.MISSING
    try:
        project(account, {'physicalEndpoints': [{'awsLocation': {'awsAccountId': 'first'}}, {'awsLocation': {'awsAccountId': 'second'}}]})
    except m.Unresolved:
        pass
    else:
        raise AssertionError('ambiguous endpoint values silently selected')
    assert project(replace(account, transform='identity', field=m.Field('fixture', 'rows[].items[].value')), {'rows': [{'items': [{'value': 0}, {'value': False}]}, {'items': [{'value': None}]}]}) == [[0, False], [None]]
    s3 = mapping_registry(ROOT, 's3')
    response = {'ServerSideEncryptionConfiguration': [{'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': 'aws:kms', 'KMSMasterKeyID': 'fixture-key'}, 'BucketKeyEnabled': False}]}
    prefix = 'S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.'
    assert project(s3.properties[prefix + 'SSEAlgorithm'], response) == ['aws:kms']
    assert project(s3.properties[prefix + 'KMSMasterKeyID'], response) == ['fixture-key']
    assert project(s3.properties['S3.Bucket.LifecycleConfiguration.Rules[].Id'], {'Rules': [{'ID': 'fixture-rule'}]}) == ['fixture-rule']
    print('Mapping projections: PASS (S3 API names, webhook presence, non-ambiguous endpoints, nested array association)')


if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        initialization_checks()
        schema_checks()
        projections()
        coverage()
