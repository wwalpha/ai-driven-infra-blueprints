#!/usr/bin/env python3
"""Environment properties, fixed references and derived fields over synthetic sources."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
import io
import json
from contextlib import redirect_stdout
import pytest
from support.model_parameter_inputs_fixtures import fixture, root
from support.model_sources import write_model
from support.import_model_fixtures import service_values, resource_values, reference_fields
from model.sources import FileReads, load_model, list_models, design_source_digest
from model.operations import CandidateReads
from model.format import serialize
from model.references import usages, incoming
from model.files import trace_model
from model.projection import document_sha256
import sync_runtime


def check_human(root):
    environments, paths = fixture(root)
    before = {env: load_model(path) for env, path in paths.items()}
    original = {p: p.read_bytes() for p in (root / 'model').rglob('*') if p.is_file()}
    for env in environments:
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, env, 'team', services=['vpc']) == 0
    views = {p: p.read_bytes() for p in (root / 'docs/designs').rglob('*') if p.is_file()}
    for env in environments:
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, env, 'team', services=['vpc']) == 0
            assert sync_runtime.sync(root, False, env, 'team', services=['vpc']) == 0
    assert all(p.read_bytes() == raw for p, raw in {**original, **views}.items())
    snapshot = before['preview']
    values = dict(snapshot.authoritative)
    values['desired.row.017-002.value'] = '`10.11.0.0/23`'
    after = load_model(snapshot.scope, CandidateReads(FileReads(), {paths['preview']: serialize(values)}))
    assert {key for key in snapshot.authoritative if snapshot.authoritative[key] != after.authoritative[key]} == {'desired.row.017-002.value'}
    assert load_model(paths['prod']).authoritative == before['prod'].authoritative
    for field in ('logicalId', 'anchor', 'resourceMode', 'resourceType'):
        assert after.authoritative['desired.resource.017.' + field] == snapshot.authoritative['desired.resource.017.' + field]
    key = 'desired.row.017-001.value'
    trace = trace_model(paths['preview'], key)
    assert trace['file'] == str(paths['preview']) and trace['value'] == snapshot.authoritative[key]
    assert root / 'project.json' in snapshot.dependencies
    assert not (root / 'model/templates').exists() and not (root / 'model/parameters').exists()
    assert all(p.read_bytes() == raw for p, raw in original.items())


def check_declared_instance_inputs(root):
    # The retired Definition/default grammar has no normal-reader fallback.
    environments, paths = fixture(root)
    scopes = list_models(root)
    assert len(scopes) == 2 and {scope.target for scope in scopes} == {'team'}
    assert not (root / 'model/preview/other').exists()
    for identity in ('service', 'Legal_42-name'):
        values = service_values('explicit', ['Example.Resource'])
        values.update(resource_values(identity, 'Example.Resource', 'explicit-' + identity, 'CREATE', [
            ('Value', '`{"enabled":true,"fixed":"fixed","optional":3,"sequence":[3,1,2],"empty":null}`')]))
        path = root / 'model/preview/team/explicit.properties'
        write_model(path, values)
        snapshot = load_model(path)
        key = 'desired.row.' + identity + '-001.value'
        native = json.loads(snapshot.authoritative[key][1:-1])
        assert native == {'enabled': True, 'fixed': 'fixed', 'optional': 3, 'sequence': [3, 1, 2], 'empty': None}
        assert type(native['enabled']) is bool and type(native['optional']) is int
        saved = path.read_bytes()
        assert load_model(path).authoritative == snapshot.authoritative and path.read_bytes() == saved
        for field in ('property', 'value', 'comment'):
            changed = {k: v for k, v in values.items() if k != 'desired.row.' + identity + '-001.' + field}
            with pytest.raises(ValueError, match='Row requires'):
                load_model(path, CandidateReads(FileReads(), {path: serialize(changed)}))
        with pytest.raises(ValueError, match='unknown Model field'):
            load_model(path, CandidateReads(FileReads(), {path: serialize({**values, 'desired.resource.' + identity + '.definition': 'old'})}))
    legacy = root / 'model/parameters'
    legacy.mkdir()
    with pytest.raises(ValueError, match='explicit migration'):
        load_model(paths['preview'])


def check_kms_alias(root):
    fixture(root)
    producer = root / 'model/preview/team/kms.properties'
    values = service_values('kms', ['KMS.Key', 'KMS.Alias'])
    values.update(resource_values('011', 'KMS.Key', 'kms-material-key', 'CREATE', [('KeyId', 'resource://preview/team/kms/KMS_Key_011')]))
    values.update(resource_values('012', 'KMS.Alias', 'kms-alias-app-preview-material-one', 'CREATE', [
        ('AliasName', '`alias/app-preview-material-one`'), ('TargetKeyId', 'resource://preview/team/kms/KMS_Key_011')]))
    values['desired.resource.012.parentProperty'] = 'KMS.Alias.TargetKeyId'
    values['desired.resource.012.parentReference'] = 'resource://preview/team/kms/KMS_Key_011'
    values['desired.service.identity.lastAllocated'] = json.dumps({'KMS.Key': 11, 'KMS.Alias': 12})
    write_model(producer, values)
    path = producer.with_name('codecommit.properties')
    link = 'resource://preview/team/kms/KMS_Alias_012'
    consumer = service_values('codecommit', ['CodeCommit.Repository'])
    consumer.update(resource_values('021', 'CodeCommit.Repository', 'codecommit-repository', 'CREATE', [
        ('KmsKeyId', link), ('RepositoryDescription', 'alias/app-preview-material-one')]))
    consumer.update(reference_fields('link', 'desired.row.021-001.value', link, 'preview/team/kms/012', kind='KMS.Alias', mode='link'))
    consumer['desired.reference.link.labelPolicy'] = 'display-name'
    consumer.update(reference_fields('raw-name', 'desired.row.021-002.value', 'alias/app-preview-material-one',
        'preview/team/kms/012', kind='KMS.Alias', prop='KMS.Alias.AliasName'))
    write_model(path, consumer)
    before = load_model(path)
    assert not before.warnings and producer in before.dependencies
    assert before.authoritative['desired.row.021-001.value'] == link
    # A Key's grouped display must never satisfy a raw Key Property reference using its child's name.
    invalid = {**consumer, 'desired.reference.raw-name.producerLogicalId': 'KMS_Key_011', 'desired.reference.raw-name.resourceType': 'KMS.Key',
               'desired.reference.raw-name.property': 'KMS.Key.KeyId'}
    assert load_model(path, CandidateReads(FileReads(), {path: serialize(invalid)})).warnings
    saved, digest = path.read_bytes(), design_source_digest(path)
    for changed in (producer.read_text().replace('material-one', 'material-two'),
                    producer.read_text().replace('KMS.Alias', 'KMS.Key'),
                    producer.read_text().replace('KMS.Alias.AliasName', 'KMS.Alias.Other')):
        after = load_model(path, CandidateReads(FileReads(), {producer: changed}))
        assert after.authoritative == before.authoritative and after.warnings
    missing = load_model(path, CandidateReads(FileReads(), {producer: None}))
    assert missing.warnings and missing.dependencies[producer] is None
    with pytest.raises(ValueError):
        load_model(path, CandidateReads(FileReads(), {producer: '# model-format: 2\ninvalid\n'}))
    assert path.read_bytes() == saved and design_source_digest(path) == digest


def check_external_instances(root):
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': env, 'alias': 'team', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1',
         'iacEngine': 'cloudformation'} for env in ('dev', 'stg')]}))
    consumers = {}
    for env, rid in [('dev', '017'), ('stg', '083')]:
        name, kind = 'secret-' + env, 'SecretsManager.Secret'
        producer = root / 'model' / env / 'team/secrets-manager.properties'
        values = service_values('secrets-manager', [kind])
        values.update(resource_values(rid, kind, 'secret-' + rid, 'CREATE', [('Name', '`' + name + '`')]))
        write_model(producer, values)
        consumer = service_values('quicksight', ['QuickSight.DataSource'])
        consumer.update(resource_values('001', 'QuickSight.DataSource', 'quicksight-source', 'CREATE', [
            ('Name', '`' + name + '`'), ('Credentials.CredentialPair.Password', '`{{resolve:secretsmanager:' + name + ':SecretString:token}}`')]))
        for identity, key in [('name', 'desired.row.001-001.value'), ('password', 'desired.row.001-002.value')]:
            consumer.update(reference_fields(identity, key, name, env + '/team/secrets-manager/' + rid, kind=kind, prop=kind + '.Name'))
        path = producer.with_name('quicksight.properties')
        write_model(path, consumer)
        snapshot = load_model(path)
        assert not snapshot.warnings and producer in snapshot.dependencies
        assert len(incoming(load_model(producer), rid)) == 2
        assert snapshot.authoritative['desired.reference.name.producerLogicalId'] == 'SecretsManager_Secret_' + rid
        consumers[env] = (path, snapshot, producer)
    path, before, producer = consumers['dev']
    changed = producer.read_text().replace('secret-dev', 'secret-dev-updated')
    after = load_model(path, CandidateReads(FileReads(), {producer: changed}))
    assert after.authoritative == before.authoritative and after.warnings
    assert load_model(consumers['stg'][0]).authoritative == consumers['stg'][1].authoritative
    for field, raw in [('producerLogicalId', 'SecretsManager_Secret_999'), ('resourceType', 'Glue.SecurityConfiguration')]:
        candidate = {**before.authoritative, 'desired.reference.name.' + field: raw}
        model = load_model(path, CandidateReads(FileReads(), {path: serialize(candidate)}))
        assert model.warnings and model.authoritative['desired.row.001-001.value'] == '`secret-dev`'
    for field, raw in [('instance', 'old-selector'), ('producerScope', '../escape')]:
        with pytest.raises(ValueError):
            load_model(path, CandidateReads(FileReads(), {path: serialize({**before.authoritative, 'desired.reference.name.' + field: raw})}))


def check_service_contracts():
    from integrations.service_contracts import check
    check()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__, message='Explicit environment properties: PASS'))
