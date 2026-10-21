"""Synthetic format/discovery checks; never inspect the executing project's Models."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import json
import tempfile
import pytest
from model.format import FORMAT, INDEX, parse, patch, serialize, split
from model.sources import Scope, load_model, list_models
from model.references import declarations, diagnose


def check_scalar_spelling_and_patch():
    text = FORMAT + '\r\n# comment\r\na.value= 010 \\ " \r\nb.value=`true`\r\n'
    document = parse(text)
    assert document.values == {'a.value': ' 010 \\ " ', 'b.value': '`true`'}
    edited = patch(document, {'b.value': '`false`'})
    assert edited == text.replace('`true`', '`false`')
    for raw in ('`{{resolve:secretsmanager:secret:SecretString:token}}`', '`[Policy](iam/policy.json)`', '`[Role](iam.md#role)`'):
        assert parse(FORMAT + '\ndesired.row.007-001.value=' + raw + '\n').values['desired.row.007-001.value'] == raw
        from model.references import _json
        assert _json('desired.row.007-001.value', raw) == (raw, False)


def check_json_continuation_and_types():
    text = FORMAT + '\ndesired.row.007-003.document={\\\n  "a": [true, 10, null, "1"],\\\n  "b": "slash\\\\"} \ndesired.row.007-004.value=`[\\\n"first", "second"]`\n'
    values = parse(text).values
    assert json.loads(values['desired.row.007-003.document']) == {'a': [True, 10, None, '1'], 'b': 'slash\\'}
    assert json.loads(values['desired.row.007-004.value'][1:-1]) == ['first', 'second']


@pytest.mark.parametrize('body', [
    'a.document={"a":1,"a":2}', 'a.document={"x":NaN}', 'a.document={\\',
    'a.document={\\\n# comment\n}', 'a.document={\\ \n}',
    'a.document={"x":"broken\\\nstring"}', 'a.document={\n"a":1}',
    'a.document={"x":Infinity}', 'a.document={"x":1e999}', 'a.value=`[-1e999]`', 'a.value=`[1,]`', 'a=1\na=2'])
def check_invalid_properties(body):
    with pytest.raises(ValueError):
        parse(FORMAT + '\n' + body + '\n')


@pytest.mark.parametrize('header', ['', '# model-format: 1', '# model-format: 3', '# model-template: 1'])
def check_unsupported_version(header):
    with pytest.raises(ValueError):
        parse(header + '\na=1\n')


@pytest.mark.parametrize('version', [None, 1, 2, 3.0])
def check_deploy_rejects_legacy_session_format(version):
    from deployment.session import require_session_format
    from cloudformation_inputs import Blocked
    with pytest.raises(Blocked, match='format is incompatible'):
        require_session_format({'version': version, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1})
    require_session_format({'version': 3, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1})


def check_observed_insertion_is_local_without_reflow():
    text = FORMAT + '\r\n# original comment  \r\n' + (
        'desired.row.007-001.property=EC2.VPC.VpcId\r\n'
        'desired.row.007-001.value=[network](#network)\r\n'
        'desired.row.007-001.comment=日本語の説明\r\n'
        '# next Row must keep its exact original bytes  \r\n'
        'desired.row.007-002.property=EC2.VPC.Name\r\n'
        'desired.row.007-002.value= 010 \\ " \r\n')
    marker = 'desired.row.007-001.comment=日本語の説明\r\n'
    observed = 'observed.row.007-001.value=\r\n'
    updated = patch(parse(text), {'observed.row.007-001.value': ''})
    assert updated == text.replace(marker, marker + observed)
    assert patch(parse(updated), {'observed.row.007-001.value': None}) == text




def check_import_observation_foreign_reference_and_identity_spoof(tmp_path):
    import shutil
    from model.sources import load_model
    from model.observed import observed_outputs
    from model.format import serialize
    from support.model_v2_fixtures import format_fixture, FRAMEWORK
    scope, values = format_fixture(tmp_path)
    for name in ('materials', 'mappings', 'rules'):
        shutil.copytree(FRAMEWORK / 'framework' / name, tmp_path / 'framework' / name)
    values.update({'desired.resource.008.resourceType': 'EC2.Subnet',
                   'desired.resource.008.resourceMode': 'IMPORT', 'desired.resource.008.anchor': 'imported-subnet',
                   'desired.row.008-001.property': 'EC2.Subnet.VpcId',
                   'desired.row.008-001.value': '[Network](#network)', 'desired.row.008-001.comment': 'foreign VPC',
                   'observed.row.008-001.value': 'vpc-before',
                   'desired.row.008-002.property': 'EC2.Subnet.SubnetId',
                   'desired.row.008-002.value': '[Subnet](#imported-subnet)', 'desired.row.008-002.comment': 'own ID',
                   'observed.row.008-002.value': 'subnet-before'})
    scope.path.write_text(serialize(values))
    snapshot = load_model(scope)
    outputs = observed_outputs(scope.path, {**snapshot.values, 'observed.row.008-001.value': 'PENDING_DEPLOY'})
    assert outputs[scope.path] == patch(parse(scope.path.read_text()), {'observed.row.008-001.value': 'PENDING_DEPLOY'})
    assert 'observed.row.008-002.value=subnet-before' in outputs[scope.path]
    with pytest.raises(ValueError, match='IMPORT physical identity'):
        observed_outputs(scope.path, {**snapshot.values, 'observed.row.008-002.value': 'subnet-other'})
    # A forged foreign link cannot make a native primary identifier writable.
    values['desired.row.008-002.value'] = '[Network](#network)'
    scope.path.write_text(serialize(values))
    snapshot = load_model(scope)
    with pytest.raises(ValueError, match='IMPORT physical identity'):
        observed_outputs(scope.path, {**snapshot.values, 'observed.row.008-002.value': 'subnet-other'})


@pytest.mark.parametrize('inline', [False, True])
@pytest.mark.parametrize('existing', [None, '{"bucketDefinitions":[{"accountId":"123456789012","buckets":["stale"]}]}', 'broken JSON'])
def check_macie_renders_current_document_without_artifact_reads(tmp_path, existing, inline):
    import shutil
    from model.render import render_model
    from support.model_v2_fixtures import format_fixture, FRAMEWORK
    scope, _ = format_fixture(tmp_path, service='macie')
    for directory in ('materials', 'mappings', 'rules'):
        shutil.copytree(FRAMEWORK / 'framework' / directory, tmp_path / 'framework' / directory)
    document = {'bucketDefinitions': [{'accountId': '123456789012', 'buckets': ['current-a', 'current-b']}]}
    values = {'desired.service.macie.serviceId': 'macie',
        'desired.service.macie.ownedCatalogResourceTypes': 'Macie.ClassificationJob',
        'display.service.title': '# Fixture', 'desired.resource.007.resourceType': 'Macie.ClassificationJob',
        'desired.resource.007.logicalId': 'fixed', 'desired.resource.007.anchor': 'fixed',
        'desired.resource.007.resourceMode': 'IMPORT', 'display.resource.007.comment': 'fixture'}
    for index, (prop, value) in enumerate([('name', '`fixture-job`'), ('s3JobDefinition', '[definition](macie/definition.json)')], 1):
        values.update({f'desired.row.007-{index:03d}.property': 'Macie.ClassificationJob.' + prop,
            f'desired.row.007-{index:03d}.value': value, f'desired.row.007-{index:03d}.comment': 'fixture'})
    if inline:
        document = {'bucketCriteria': {}}
        values['desired.row.007-002.value'] = '`' + json.dumps(document) + '`'
    else:
        values['desired.row.007-002.document'] = json.dumps(document)
    scope.path.write_text(serialize(values), encoding='utf-8')
    artifact = tmp_path / 'docs/designs' / scope.environment / scope.target / 'macie/definition.json'
    if existing is not None:
        artifact.parent.mkdir(parents=True)
        artifact.write_text(existing, encoding='utf-8')
    original = scope.path.read_bytes()
    files = render_model(load_model(scope), None)
    if inline:
        assert artifact not in files
    else:
        assert json.loads(files[artifact]) == document
    markdown = files[artifact.parent.with_suffix('.md')]
    assert ('#### 対象S3 bucket' in markdown) == (not inline)
    for bucket in document.get('bucketDefinitions', [{'buckets': []}])[0]['buckets']:
        assert f'`{bucket}`' in markdown
    assert '`stale`' not in markdown
    assert scope.path.read_bytes() == original
    assert (artifact.read_text(encoding='utf-8') if artifact.exists() else None) == existing


@pytest.mark.parametrize('kind,label,rows,expected', [
    ('EC2.VPC', None, [], 'EC2.VPC'),
    ('CodeBuild.Project', 'fallback', [('CodeBuild.Project.Name', '`raw-name`')], 'raw-name'),
    ('KMS.Key', 'fallback', [], 'fallback'),
    ('EC2.SecurityGroupIngress', None, [], 'fixed'),
    ('KMS.Key', None, [('KMS.Alias.AliasName', '`alias/grouped`')], 'grouped')])
def check_shared_display_selection_and_diagnostics(tmp_path, kind, label, rows, expected):
    from model.render import display_name
    from support.model_v2_fixtures import format_fixture
    scope, _ = format_fixture(tmp_path)
    values = {'desired.resource.007.resourceType': kind, 'desired.resource.007.logicalId': 'fixed',
        'desired.resource.007.anchor': 'producer', 'desired.resource.007.resourceMode': 'IMPORT'}
    if label:
        values['display.resource.007.label'] = label
    for index, (prop, value) in enumerate(rows, 1):
        rid = '008' if prop.startswith('KMS.Alias.') else '007'
        values.update({f'desired.row.{rid}-{index:03d}.property': prop,
            f'desired.row.{rid}-{index:03d}.value': value, f'desired.row.{rid}-{index:03d}.comment': 'fixture'})
        if rid == '008':
            values.update({'desired.resource.008.resourceType': 'KMS.Alias', 'desired.resource.008.logicalId': 'alias',
                'desired.resource.008.anchor': 'alias', 'desired.resource.008.resourceMode': 'IMPORT',
                'desired.resource.008.parentReference': '[key](#producer)'})
    from model.core import entries
    resource = dict(entries(values, 'desired.resource.'))['007']
    assert display_name(values, '007', resource, [[str(i), prop, value, 'fixture'] for i, (prop, value) in enumerate(rows)], tmp_path)[0] == expected
    if kind == 'EC2.VPC':
        from model.render import resource_details
        values['desired.resource.007.anchor'] = resource['anchor'] = 'network-ec2.vpc'
        details, _ = resource_details(values, tmp_path, 'network', {kind}, [(identity, item) for identity, item in entries(values, 'desired.resource.')], {})
        assert details[0][2] == expected
    text = f'[{expected}](#{resource["anchor"]})'
    values['desired.note.001.text'] = text
    spec = {'consumerKey': 'desired.note.001.text', 'text': text, 'occurrence': '1', 'producerKind': 'resource',
        'producerScope': '/'.join((scope.environment, scope.target, scope.service)), 'producerId': '007',
        'resourceType': kind, 'format': 'link', 'labelPolicy': 'display-name'}
    values.update({'desired.reference.name.' + key: value for key, value in spec.items()})
    scope.path.write_text(serialize(values), encoding='utf-8')
    assert load_model(scope).warnings == ()



@pytest.mark.parametrize('kind,mode,multiple', [
    ('EC2.VPC', 'IMPORT', True), ('EC2.VPC', 'CREATE', False),
    ('KMS.Alias', 'IMPORT', False), ('CodeBuild.Project', 'IMPORT', False)])
def check_type_display_constraints(tmp_path, kind, mode, multiple):
    from model.render import display_name, resource_details
    from support.model_v2_fixtures import FRAMEWORK
    from model.core import entries
    values = {'desired.resource.007.resourceType': kind, 'desired.resource.007.resourceMode': mode,
        'desired.resource.007.logicalId': 'fixed', 'desired.resource.007.anchor': 'network'}
    if multiple:
        values.update({'desired.resource.008.resourceType': kind, 'desired.resource.008.logicalId': 'second'})
    resource = dict(entries(values, 'desired.resource.'))['007']
    assert display_name(values, '007', resource, [], FRAMEWORK)[0] is None
    with pytest.raises(ValueError):
        resource_details(values, FRAMEWORK, 'network', {kind}, list(entries(values, 'desired.resource.')), {})


@pytest.mark.parametrize('scope', ['dev/one', 'dev/two', 'prod/one', 'prod/two'])
@pytest.mark.parametrize('provider', ['adapter', 'sdk', 'cloudcontrol'])
def check_resource_acquisition_scope(tmp_path, monkeypatch, scope, provider):
    from types import SimpleNamespace
    from script_loader import module
    from model.importing import inventory
    from aws_mapping_compare import value as mapped_value
    from concurrent.futures import Future
    m = module('model/adapters/aws.py', 'model.adapters.aws')
    target = {'environment': 'dev', 'directory': 'one', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1'}
    calls = []
    from support.model_v2_fixtures import FRAMEWORK
    from design_catalog import DesignSchemaCatalog
    monkeypatch.setattr(m, 'DesignSchemaCatalog', lambda root: DesignSchemaCatalog(FRAMEWORK))
    ctx = m.Context(tmp_path, target)
    ctx.verified = True
    getter = {'kind': 'cloudcontrol', 'service': 'cloudcontrol', 'operation': 'get_resource',
        'resourceType': 'EC2.TransitGateway', 'identifier': ['/properties/TransitGatewayId']}
    mapping = SimpleNamespace(identities={}, getters={'provider': getter})
    monkeypatch.setattr(ctx, 'comparison', lambda service: (mapping, {}))
    monkeypatch.setattr(inventory, 'inventory_for', lambda ctx: SimpleNamespace(schema=lambda kind: {
        'primaryIdentifier': getter['identifier'], 'handlers': {'read': {}}}))
    def call(*args, **kwargs):
        calls.append(args)
        return {'ResourceDescription': {'Properties': '{"TransitGatewayId":"tgw-fixture"}'}}
    monkeypatch.setattr(ctx, 'call', call)
    def fetch(*args):
        calls.append(provider)
        return {'id': 'tgw-fixture'}
    model = SimpleNamespace(path=tmp_path / 'model' / (scope + '/ec2.properties'), ctx=ctx, service='ec2',
        values={'desired.row.007-001.property': 'EC2.TransitGateway.TransitGatewayId',
                'desired.row.007-001.value': '`tgw-fixture`'})
    resource = m.Resource(model, '007', {'resourceType': 'EC2.TransitGateway', 'anchor': 'gateway'},
        [('007-001', {'property': 'EC2.TransitGateway.TransitGatewayId', 'value': '`tgw-fixture`'})])
    resource.module = SimpleNamespace(CLOUDCONTROL_RESOURCE_TYPES={'EC2.TransitGateway'}, fetch=fetch, fetch_sdk=fetch)
    definition = {'operation': 'get_resource'} if provider == 'sdk' else None
    if provider == 'cloudcontrol':
        entries = [lambda: resource.identity(), lambda: inventory.cloudcontrol_value(ctx, resource, getter)]
    else:
        entries = [lambda: ctx.fetch(resource, 'provider', definition), lambda: ctx._fetch(resource, 'provider', definition)]
    if scope == 'dev/one':
        for acquire in entries:
            assert acquire()
        assert calls
    else:
        # Populate both caches to prove that authorization precedes every cache hit.
        cache_key = (model.path, '007', 'provider')
        ctx.fetch_cache[cache_key] = {'id': 'cached'}
        ctx.fetch_trace[cache_key] = []
        future = Future()
        future.set_result({'id': 'cached'})
        ctx._flights[('fetch', *cache_key)] = future
        prop = SimpleNamespace(field=SimpleNamespace(getter='provider'))
        if provider == 'cloudcontrol':
            entries.append(lambda: mapped_value(ctx, resource, mapping, prop, 'EC2.TransitGateway.TransitGatewayId'))
        for acquire in entries:
            with pytest.raises(m.Unresolved, match='outside authorized AWS retrieval scope'):
                acquire()
        assert calls == []


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
