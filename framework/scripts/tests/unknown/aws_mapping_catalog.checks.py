#!/usr/bin/env python3
"""Offline coverage, provenance and projection checks; no consumer fixture copies."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from collections import Counter
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import json
import shutil
import socket
import yaml

from aws_mapping import Registry, registry as mapping_registry
from aws_mapping_catalog import project, catalog_properties
from validation_cache import input_scope
from aws_mapping_display import MODEL_ONLY, display_name, formal_name
from design_catalog import design_material_files
from script_loader import module

ROOT = Path(__file__).resolve().parents[4]
m = module('check-model-aws.py', 'model_aws_compare')


@input_scope
def coverage():
    catalog = {line.partition('=')[0] for p in design_material_files(ROOT)
               for line in p.read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#')}
    properties, types, sources, summaries = {}, set(), Counter(), []
    for path in sorted((ROOT / 'framework/mappings/aws').glob('*.yaml')):
        registry = mapping_registry(ROOT, path.stem)
        document = yaml.safe_load(path.read_text(encoding='utf-8'))
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


def initialization_checks():
    import os
    import aws_mapping_catalog as catalog
    from validation_cache import memo_table
    adapter = yaml.safe_load((ROOT / 'framework/mappings/aws/config.yaml').read_text(encoding='utf-8'))
    sdk = yaml.safe_load((ROOT / 'framework/mappings/aws/sns.yaml').read_text(encoding='utf-8'))
    factory = catalog.get_session
    with patch.object(catalog, 'get_session', wraps=factory) as sessions:
        catalog.catalog_properties(ROOT, 'config', adapter)
        assert sessions.call_count == 0, 'adapter-only Mapping needs no SDK session'

        @input_scope
        def reuse():
            catalog.catalog_properties(ROOT, 'sns', sdk)
            catalog.catalog_properties(ROOT / '.', 'sns', sdk)
            assert sessions.call_count == 1
            session = catalog._sdk_session(ROOT.resolve(), sessions, os.environ.get('AWS_DATA_PATH'))
            with patch.object(session, 'get_service_model', wraps=session.get_service_model) as models:
                memo_table().clear()
                catalog._service_model(session, 'sns')
                catalog._service_model(session, 'sns')
                assert models.call_count == 1
            # A patch and SDK data path are separate initialization inputs even inside a scope.
            with patch.object(catalog, 'get_session', wraps=factory) as replacement:
                catalog.catalog_properties(ROOT, 'sns', sdk)
                assert replacement.call_count == 1
            with patch.dict(os.environ, {'AWS_DATA_PATH': '/nonexistent-offline-sdk-data'}):
                catalog.catalog_properties(ROOT, 'sns', sdk)
                assert sessions.call_count == 2
        reuse()
        @input_scope
        def next_scope():
            catalog.catalog_properties(ROOT, 'sns', sdk)
        next_scope()
        assert sessions.call_count == 3, 'a new scope cannot inherit sessions'
    # No clients or credentials are involved in SDK model initialization.
    @input_scope
    def roots():
        with patch.object(catalog, 'get_session', side_effect=lambda: object()) as sessions:
            catalog._sdk_session(ROOT, sessions, None)
            catalog._sdk_session(ROOT / 'other', sessions, None)
            assert sessions.call_count == 2
    roots()
    print('Mapping initialization: PASS (adapter 0; same scope 1; separate roots/data/patch/scopes isolated)')


@input_scope
def schema_checks():
    document = yaml.safe_load((ROOT / 'framework/mappings/aws/sns.yaml').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='mapping-schema-') as directory:
        root = Path(directory)
        catalog = root / 'framework/materials'
        (catalog / 'aws').mkdir(parents=True)
        schemas = catalog / 'cloudformation-schema/ap-northeast-1'
        schemas.mkdir(parents=True)
        original = ROOT / 'framework/materials/cloudformation-schema/ap-northeast-1'
        shutil.copyfile(original / 'index.json', schemas / 'index.json')
        index = json.loads((original / 'index.json').read_text(encoding='utf-8'))['resourceTypes']
        for kind in document['resourceTypes']:
            shutil.copyfile(ROOT / 'framework/materials/aws' / (kind.replace('.', '_') + '.properties'), catalog / 'aws' / (kind.replace('.', '_') + '.properties'))
            filename = index['AWS::' + kind.replace('.', '::')]
            shutil.copyfile(original / filename, schemas / filename)
        target = root / 'framework/mappings/aws/sns.yaml'
        target.parent.mkdir(parents=True)

        def load(value):
            target.write_text(yaml.safe_dump(value, sort_keys=False), encoding='utf-8')
            return Registry(root, 'sns')

        assert len(load(document).properties) == sum(
            len(resource['properties']) for resource in document['resourceTypes'].values())
        candidate = copy.deepcopy(document)
        candidate['version'] = 2
        try:
            load(candidate)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid file-backed Mapping accepted')
        native = copy.deepcopy(document)
        native['resourceTypes']['SNS.Topic']['identity'] = {'getter': 'provider-sns-topic', 'idPath': 'TopicArn',
                                                          'arnPath': 'TopicArn', 'nameProperty': 'TopicName'}
        assert load(native).identities['SNS.Topic'].id_path == 'TopicArn'
        native['resourceTypes']['SNS.TopicPolicy']['identity'] = {'getter': 'sdk-sns-topicpolicy', 'idPath': 'Attributes',
                                                                'arnPath': None, 'nameProperty': None}
        assert load(native).identities['SNS.TopicPolicy'].arn_path is None
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
