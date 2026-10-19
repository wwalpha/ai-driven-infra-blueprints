#!/usr/bin/env python3
"""Acquisition/source validation units; all Models and AWS facts below are synthetic."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import import_guard
from import_sources import (candidate_sources, parameter_edit, preserve_bindings,
                            property_values, selection_records, verify_values, typed_equal)
from import_promotion import changed_properties, property_value, preserve_consumers
from model_templates import Definition, Expansion
from model_parameter_inputs import check_value as validate_value, schema, yaml_read
from script_loader import module

m = module('import-model.py', 'import_model_cli')


def schema_for(prop):
    return {'type': 'boolean' if prop.endswith('EnableDnsSupport') else 'integer' if prop.endswith('RetentionInDays') else 'string'}


def resource(number='001', kind='EC2.VPC', identity='vpc-confirmed', cidr='10.10.0.0/23', mode='IMPORT'):
    values = {f'desired.resource.{number}.resourceType': kind,
              f'desired.resource.{number}.resourceMode': mode,
              f'desired.resource.{number}.anchor': 'vpc-main' if number == '001' else 'vpc-extra',
              f'desired.resource.{number}.logicalId': 'MainVpc' if number == '001' else 'ExtraVpc'}
    for n, (prop, value) in enumerate([('VpcId', '[MainVpc](#vpc-main)' if number == '001' else '[ExtraVpc](#vpc-extra)'), ('CidrBlock', '`' + cidr + '`'), ('Name', '`main-vpc`')], 1):
        key = f'desired.row.{number}-{n:03d}.'
        values.update({key + 'property': kind + '.' + prop, key + 'value': value, key + 'comment': '合成入力'})
    if identity:
        values[f'observed.row.{number}-001.value'] = '`' + identity + '`'
    return values


def record(identity='vpc-confirmed', cidr='10.11.0.0/23', record_id='record-1'):
    return {'record': record_id, 'kind': 'EC2.VPC', 'identity': identity, 'identityProperty': 'EC2.VPC.VpcId',
            'properties': {key: {'status': 'captured', 'value': value} for key, value in
                           [('EC2.VPC.VpcId', identity), ('EC2.VPC.CidrBlock', cidr), ('EC2.VPC.Name', 'main-vpc')]}}


def selection(record_id='record-1', rid='001', action='add', basis=()):
    return {'resources': [{'record': record_id, 'resource': rid, 'action': action,
                            'reason': '合成projectで管理範囲を確認したfixture', 'basis': list(basis)}],
            'excluded': [], 'unreflected': []}


def expansion(values):
    return Expansion(values, {}, {})


def definition(expression='`false`', declarations=None):
    return Definition(declarations or {}, {'vpc'}, {'dns': 'vpc'},
                      {'desired.row.dns.value': expression}, {}, set(), {}, {}, {})


def check_null_parameter():
    validate_value(schema({'type': 'null', 'description': 'null', 'required': True, 'format': 'literal'}), None, 'null')
    assert m.model_literal(None) == '`null`'


@pytest.mark.parametrize('value', [False, 0, 'false', '001', None, ['one', 'two'], {'Enabled': False, 'Count': 2}])
def check_yaml_edits(value):
    original = '# keep header\ninstances:\n  main-vpc:\n    parameters:\n      CidrBlock: "10.10.0.0/23" # keep CIDR\n      # keep comment\n      Setting: old\n\n'
    wanted = yaml_read(original)
    wanted['instances']['main-vpc']['parameters']['Setting'] = value
    wanted['instances']['new-subnet'] = {'parameters': {'CidrBlock': '10.10.2.0/26', 'Enabled': True}}
    actual = parameter_edit(original, wanted)
    assert yaml_read(actual) == wanted
    assert '# keep header\n' in actual and '# keep comment\n' in actual
    assert 'CidrBlock: "10.10.0.0/23" # keep CIDR' in actual
    assert '  new-subnet:\n    parameters:\n      CidrBlock: 10.10.2.0/26' in actual
    assert parameter_edit(actual, wanted) == actual
    assert ': {' not in actual


def check_yaml_empty_and_order():
    original = 'instances: {}\n'
    wanted = {'instances': {'main': {'parameters': {'Text': 'true', 'Enabled': False}}}}
    actual = parameter_edit(original, wanted)
    assert yaml_read(actual) == wanted and '  main:\n' in actual
    original = '# unchanged\ninstances:\n  main:\n    parameters:\n      B: 2\n      A: 1\n'
    assert parameter_edit(original, yaml_read(original)) == original


@pytest.mark.parametrize('alias', [False, True])
def check_physical_identity_wins_over_mutable_settings(alias):
    old = resource()
    captured = record()
    captured['properties']['EC2.VPC.Name']['value'] = 'renamed-vpc'
    if alias:
        old['desired.row.001-001.property'] = 'EC2.VPC.Id'
        captured['identityProperties'] = ['EC2.VPC.VpcId', 'EC2.VPC.Id']
    new = {**old, **resource('009')}
    with pytest.raises(ValueError, match='duplicate identity'):
        selection_records(selection(rid='009'), [captured], old, new, schema_for)
    picked = {'resources': [], 'excluded': [{'record': captured['record'], 'reason': 'already registered physical ID'}], 'unreflected': []}
    assert selection_records(picked, [captured], old, old, schema_for) == {}
    assert verify_values(expansion(old), expansion(old), {}, schema_for) == []


@pytest.mark.parametrize('key,value', [
    ('desired.row.001-002.value', '`10.11.0.0/23`'),
    ('desired.resource.001.anchor', 'renamed'),
    ('desired.resource.001.logicalId', 'Renamed'),
    ('desired.resource.001.resourceMode', 'CREATE'),
    ('desired.row.001-001.value', '`vpc-confirmed`'),
    ('observed.row.001-001.value', '`vpc-invented`'),
    ('desired.row.001-002.property', 'EC2.VPC.Name'),
    ('desired.row.001-003.value', '`renamed-vpc`'),
    ('desired.row.001-003.comment', 'changed'),
    ('desired.row.001-003.document', '{}'),
    ('observed.row.001-002.value', '`10.11.0.0/23`'),
    ('desired.row.001-004.value', '`true`'),
])
def check_invalid_candidates(key, value):
    old = resource()
    new = {**old, key: value}
    with pytest.raises(ValueError, match='preserved|existing resource'):
        verify_values(expansion(old), expansion(new), {'001': record()}, schema_for)


def check_unacquired_and_create_protection():
    old = resource(mode='CREATE')
    new = {**old, **resource('009', identity='vpc-new', cidr='10.11.0.0/23')}
    unavailable = record('vpc-new')
    unavailable['properties']['EC2.VPC.CidrBlock'] = {'status': 'missing'}
    with pytest.raises(ValueError, match='unacquired'):
        verify_values(expansion(old), expansion(new), {'009': unavailable}, schema_for)
    with pytest.raises(ValueError, match='no selected acquisition'):
        verify_values(expansion(old), expansion(new), {}, schema_for)
    with pytest.raises(ValueError, match='CREATE'):
        selection_records(selection(), [record()], old, old, schema_for)
    with pytest.raises(ValueError, match='deleting an existing resource'):
        verify_values(expansion(old), expansion({}), {}, schema_for)


@pytest.mark.parametrize('kind,identity_prop', [('EC2.VPC', 'VpcId'), ('Logs.LogGroup', 'LogGroupName')])
@pytest.mark.parametrize('hide_observed', [False, True])
@pytest.mark.parametrize('mode', ['CREATE', 'IMPORT'])
def check_duplicate_add_uses_baseline(kind, identity_prop, hide_observed, mode):
    old = resource(kind=kind, mode=mode)
    if kind == 'Logs.LogGroup':
        old['desired.row.001-001.property'] = kind + '.' + identity_prop
        old['desired.row.001-001.value'] = '`fixture-001`'
        old.pop('observed.row.001-001.value')
    identity = 'fixture-001' if kind == 'Logs.LogGroup' else 'vpc-confirmed'
    captured = {**record(identity), 'kind': kind, 'identityProperty': kind + '.' + identity_prop}
    new = {**old, **resource('009', kind=kind)}
    if hide_observed:
        new.pop('observed.row.001-001.value', None)
        new['desired.row.001-001.value'] = '`hidden-in-candidate`'
    with pytest.raises(ValueError, match='record-1.*009.*001'):
        selection_records(selection(rid='009', action='add'), [captured], old, new, schema_for)


def check_selection_identity_duplicate():
    captured = record('vpc-new')
    duplicate = {**captured, 'record': 'record-2'}
    new = {**resource('008', identity='vpc-new'), **resource('009', identity='vpc-new')}
    picked = selection(rid='008', action='add')
    picked['resources'].extend(selection('record-2', '009', 'add')['resources'])
    with pytest.raises(ValueError, match='duplicate identity'):
        selection_records(picked, [captured, duplicate], {}, new, schema_for)


def check_existing_identity_ambiguity_is_local():
    old = {**resource(), **resource('008')}
    captured = record()
    with pytest.raises(ValueError, match='001,008'):
        selection_records(selection(rid='009'), [captured], old, {**old, **resource('009')}, schema_for)
    fresh = record('vpc-new')
    new = {**old, **resource('009', identity='vpc-new')}
    assert selection_records(selection(rid='009', action='add'), [fresh], old, new, schema_for)
    # An unrelated old resource with multiple identity rows is not a global gate.
    old.update({'desired.row.008-004.property': 'EC2.VPC.VpcId', 'desired.row.008-004.value': '`vpc-other`'})
    assert selection_records(selection(rid='009', action='add'), [fresh], old, new, schema_for)
    assert selection_records({'resources': [], 'excluded': [], 'unreflected': [{'record': captured['record'], 'reason': 'ambiguous'}]},
                             [captured], old, old, schema_for) == {}


@pytest.mark.parametrize('unknown', [None, '', 'UNSET', 'PENDING_DEPLOY'])
def check_unknown_identity_does_not_block_add(unknown):
    old = resource(identity=unknown)
    new = {**old, **resource('009')}
    warnings = []
    assert selection_records(selection(rid='009', action='add'), [record()], old, new, schema_for, warnings)
    assert warnings[0]['existingResources'] == ['001']


def check_new_resource_and_explicit_dispositions():
    old = resource()
    new = {**old, **resource('009', identity='vpc-new', cidr='10.11.0.0/23')}
    acquired = record('vpc-new')
    picked = selection(rid='009', action='add')
    chosen = selection_records(picked, [acquired], old, new, schema_for)
    assert chosen.keys() == {'009'}
    assert len(verify_values(expansion(old), expansion(new), chosen, schema_for)) == 3
    invalid = {**new, 'desired.row.009-001.value': '[MainVpc](#vpc-main)'}
    with pytest.raises(ValueError, match='own anchor'):
        verify_values(expansion(old), expansion(invalid), chosen, schema_for)
    picked['resources'][0]['action'] = 'update'
    with pytest.raises(ValueError, match='add only'):
        selection_records(picked, [acquired], old, new, schema_for)
    with pytest.raises(ValueError, match='explicit disposition'):
        selection_records({'resources': [], 'excluded': [], 'unreflected': []}, [acquired], old, old, schema_for)
    assert selection_records({'resources': [], 'excluded': [], 'unreflected': [{'record': 'record-1', 'reason': 'ownership unknown'}]},
                             [acquired], old, old, schema_for) == {}


def check_binding_identity_and_addition():
    original = {'instances': {'main-vpc': {'definition': 'Vpc', 'resources': {'vpc': '001'}, 'rows': {'cidr': '001-001'}, 'parameters': {}}}}
    candidate = copy.deepcopy(original)
    candidate['instances']['new-subnet'] = {'definition': 'Subnet', 'resources': {'subnet': '009'}, 'rows': {}, 'parameters': {}}
    preserve_bindings(original, candidate)
    for field, value in [('rows', {'cidr': '001-099'}), ('rows', {'cidr': '001-001', 'dns': '001-002'}),
                         ('resources', {'renamed': '001'}), ('parameters', {'Anchor': 'changed'}), ('definition', 'Other')]:
        candidate = copy.deepcopy(original)
        candidate['instances']['main-vpc'][field] = value
        with pytest.raises(ValueError, match='bindings'):
            preserve_bindings(original, candidate)


def check_shared_property_typed_preservation():
    old = definition()
    spec = {'type': 'boolean', 'required': True, 'description': 'DNS support'}
    new = definition('<<EnableDnsSupport>>', {'EnableDnsSupport': spec})
    assert changed_properties({'Vpc': old}, {'Vpc': new}) == {'Vpc': {'desired.row.dns.value'}}
    binding = {'resources': {'vpc': '001'}, 'rows': {'dns': '001-001'}, 'parameters': {}}
    params = {'instances': {'main': {'parameters': {'EnableDnsSupport': False}}}}
    assert property_value(old, 'desired.row.dns.value', {'instances': {}}, binding, 'main', 'stg') == '`false`'
    assert property_value(new, 'desired.row.dns.value', params, binding, 'main', 'stg') == 'false'
    params['instances']['main']['parameters']['EnableDnsSupport'] = 'false'
    with pytest.raises(ValueError, match='type'):
        property_value(new, 'desired.row.dns.value', params, binding, 'main', 'stg')


@pytest.mark.parametrize('dependency', ['value', 'optional', 'optional-json', 'choice', 'default', 'anchor', 'reference', 'owner'])
def check_other_definition_input_dependencies(tmp_path, dependency):
    from model_templates import json_text
    from support.import_model_fixtures import spec
    key = 'desired.row.dns.value'
    declaration = spec('boolean', default=False, required=False)
    original = definition('<<Shared>>', {'Shared': declaration})
    candidate = definition('<<Shared>>', {'Shared': {**declaration, 'default': True}})
    if dependency == 'value':
        original, candidate = definition('`false`'), definition('`true`')
    elif dependency == 'optional':
        original = original._replace(values={key: '`false`'}, optional={key: 'Shared'})
        candidate = candidate._replace(values={key: '`false`'}, optional={key: 'Shared'})
    elif dependency == 'optional-json':
        original = original._replace(values={key: '`{"enabled":true}`'}, optional_json={(key, '/enabled'): 'Shared'})
        candidate = candidate._replace(values={key: '`{"enabled":true}`'}, optional_json={(key, '/enabled'): 'Shared'})
    elif dependency == 'choice':
        original = original._replace(values={key: '`false`'}, choices={(key, None, 'Shared'): '`true`'})
        candidate = candidate._replace(values={key: '`false`'}, choices={(key, None, 'Shared'): '`true`'})
    elif dependency == 'anchor':
        original = definition('<<Anchor_vpc>>', {'Shared': spec(default='old', required=False)})
        candidate = definition('<<Anchor_vpc>>', {'Shared': spec(default='new', required=False)})
        original = original._replace(values={key: '<<Anchor_vpc>>', 'desired.resource.vpc.anchor': '<<Shared>>'})
        candidate = candidate._replace(values=original.values)
    elif dependency == 'reference':
        reference = spec('reference', source='template', target='001', service='vpc', resourceType='EC2.VPC')
        original = definition('<<Vpc>>', {'Vpc': reference})
        candidate = definition('<<Vpc>>', {'Vpc': {**reference, 'target': '002'}})
    elif dependency == 'owner':
        candidate = original._replace(rows={'dns': 'other'})
    path = tmp_path / 'model/dev/cde/cloudwatch-logs.properties'
    template = tmp_path / 'model/templates/cde/cloudwatch-logs.properties.tpl'
    directory = tmp_path / 'model/parameters/dev/cde/cloudwatch-logs'
    consumer = tmp_path / 'model/parameters/stg/cde/cloudwatch-logs'
    consumer.mkdir(parents=True)
    binding = {'definition': 'App', 'resources': {'vpc': '001'}, 'rows': {'dns': '001-001'}, 'parameters': {}}
    (consumer / 'parameters.yaml').write_text('instances: {}', encoding='utf-8')
    (consumer / 'bindings.json').write_text(json_text({'instances': {'app': binding}}), encoding='utf-8')
    baseline = SimpleNamespace(files={directory / 'bindings.json': json_text({'instances': {}}), directory / 'parameters.yaml': '{}'})
    with patch('import_promotion.service_source', return_value=(tmp_path, template, directory)), \
         patch('import_promotion.parse_template', side_effect=[({'App': original}, {}), ({'App': candidate}, {})]), \
         pytest.raises(ValueError, match='meaning changed|row owners'):
        preserve_consumers(path, baseline, {template: 'edited'}, {('dev', 'cde', 'cloudwatch-logs'), ('stg', 'cde', 'cloudwatch-logs')})


def check_shared_reference_is_symbolic():
    spec = {'type': 'reference', 'required': True, 'description': 'VPC', 'source': 'template', 'target': '001', 'service': 'vpc', 'resourceType': 'EC2.VPC'}
    raw = definition('<<Vpc>>', {'Vpc': spec})
    binding = {'resources': {}, 'rows': {}, 'parameters': {}}
    actual = property_value(raw, 'desired.row.dns.value', {'instances': {}}, binding, 'main', 'stg')
    assert actual.startswith('REFERENCE:') and '"target":"001"' in actual


def check_typed_property_values():
    values = resource()
    values.update({'desired.row.001-004.property': 'EC2.VPC.EnableDnsSupport', 'desired.row.001-004.value': '`false`'})
    assert property_values(values, '001', 'EC2.VPC.EnableDnsSupport', schema_for('EC2.VPC.EnableDnsSupport')) is False
    assert property_values(values, '001', 'EC2.VPC.VpcId', {'type': 'string'}) == 'vpc-confirmed'


def check_candidate_scope_and_changed_files(tmp_path):
    root, stage = tmp_path / 'repository', tmp_path / 'candidate'
    directory = root / 'model/parameters/dev/cde/vpc'
    directory.mkdir(parents=True)
    original = directory / 'parameters.yaml'
    original.write_text('instances: {}\n', encoding='utf-8')
    candidate = stage / original.relative_to(root)
    candidate.parent.mkdir(parents=True)
    candidate.write_text('instances: {}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='changed sources only'):
        candidate_sources(root, stage, ('dev', 'cde', 'vpc'))
    candidate.write_text('# added\ninstances: {}\n', encoding='utf-8')
    assert set(candidate_sources(root, stage, ('dev', 'cde', 'vpc'))) == {original}
    (stage / 'project.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='outside'):
        candidate_sources(root, stage, ('dev', 'cde', 'vpc'))


def check_sealed_evidence_tamper(tmp_path):
    file = tmp_path / 'acquisition.json'
    value = {'scope': ['dev', 'cde', 'vpc'], 'records': [record()], 'sts': {'verified': True}}
    with patch.object(import_guard, 'seal_key', return_value=b'x' * 32):
        file.write_text(import_guard.sealed(tmp_path, value), encoding='utf-8')
        assert import_guard.read_sealed(tmp_path, file) == value
        data = json.loads(file.read_text(encoding='utf-8'))
        data['payload']['records'][0]['identity'] = 'fabricated'
        file.write_text(json.dumps(data), encoding='utf-8')
        with pytest.raises(ValueError, match='modified'):
            import_guard.read_sealed(tmp_path, file)


@pytest.mark.parametrize('args', [[], ['--environment', 'dev', '--service', 'vpc'],
    ['--environment', 'dev', '--service', 'vpc', '--phase', 'publish'],
    ['--environment', 'dev', '--service', 'vpc', '--phase', 'publish', '--evidence', '/tmp/a', '--no-profile']])
def check_cli_never_falls_back(args):
    with patch.object(sys, 'argv', ['import-model', *args]), pytest.raises(SystemExit) as failure:
        m.main()
    assert failure.value.code == 2


def check_cli_phase_dispatch():
    result = {'status': 'acquired', 'markdown': 'not-run'}
    with patch.object(sys, 'argv', ['import-model', '--environment', 'dev', '--service', 'vpc', '--phase', 'acquire', '--no-profile']), \
            patch.object(m, 'acquire', return_value=result) as acquire, patch.object(m, 'publish_acquisition') as publish:
        assert m.main() == 0
        assert acquire.call_args.kwargs == {'no_profile': True}
        publish.assert_not_called()
    for result, code in [({'status': 'complete', 'markdown': 'generated'}, 0),
                         ({'status': 'incomplete', 'markdown': 'generated'}, 2),
                         ({'status': 'display-failed', 'markdown': 'failed'}, 3)]:
        with patch.object(sys, 'argv', ['import-model', '--environment', 'dev', '--service', 'vpc', '--phase', 'publish', '--evidence', '/tmp/a']), \
                patch.object(m, 'publish_acquisition', return_value=result), patch.object(m, 'acquire') as acquire:
            assert m.main() == code
            acquire.assert_not_called()


def check_native_equality_and_singleton():
    assert typed_equal({'a': False, 'b': 2}, {'b': 2, 'a': False})
    assert not typed_equal(False, 0)
    old = {'desired.resource.001.resourceType': 'SecurityHub.Hub', 'desired.resource.001.resourceMode': 'IMPORT'}
    captured = {'record': 'hub', 'kind': 'SecurityHub.Hub', 'identity': 'confirmed-hub', 'identityProperty': None, 'properties': {}}
    with pytest.raises(ValueError, match='add only'):
        selection_records(selection('hub', action='update', basis=['$scope']), [captured], old, old, schema_for)
    new = {**old, 'desired.resource.009.resourceType': 'SecurityHub.Hub', 'desired.resource.009.resourceMode': 'IMPORT'}
    assert selection_records(selection('hub', rid='009'), [captured], old, new, schema_for) == {'009': captured}


def check_adapter_inventory_normalization(tmp_path):
    from support.import_model_fixtures import SERVICES, ACCOUNT, aws
    target = {'environment': 'dev', 'directory': 'cde', 'awsAccountId': ACCOUNT,
              'awsRegion': 'ap-northeast-1', 'awsProfile': 'confirmed'}
    for service in SERVICES:
        cli = aws(service)
        ctx = m.import_context(m.ROOT, target, cli, service)
        ctx.verify()
        records = m.normalize_records(ctx, service, m.inventory(ctx, service))
        assert records and all('properties' in record and 'getters' not in record for record in records)
        assert cli.calls[0] == ('sts', 'get-caller-identity', {})
        if service == 'vpc':
            vpc = next(r for r in records if r['kind'] == 'EC2.VPC')
            assert vpc['properties']['EC2.VPC.EnableDnsSupport']['value'] is True
        if service == 'config':
            recorder = next(r for r in records if r['kind'] == 'Config.ConfigurationRecorder')
            assert recorder['properties']['Config.ConfigurationRecorder.RecordingGroup.AllSupported']['value'] is False
            assert recorder['properties']['Config.ConfigurationRecorder.RecordingGroup.ResourceTypes']['value'] == ['AWS::EC2::VPC']


def check_shared_source_preservation_boundary(tmp_path):
    from support.import_model_fixtures import build_seed, spec, SERVICES
    from model_templates import load_for_edit, json_text
    build_seed(tmp_path)
    for service in SERVICES:
        assert load_for_edit(tmp_path / 'model/dev/cde' / (service + '.properties')).values
    path = tmp_path / 'model/dev/cde/cloudwatch-logs.properties'
    before = load_for_edit(path)
    template = tmp_path / 'model/templates/cde/cloudwatch-logs.properties.tpl'
    text = template.read_text().replace('# definition: LogGroup\n',
        '# definition: LogGroup\n# parameter: LogClass ' + json_text(spec(required=False, default='STANDARD')) + '\n')
    text = text.replace('desired.row.class.value=`STANDARD`', 'desired.row.class.value=`<<LogClass>>`')
    output = {template: text}
    direct = {('dev', 'cde', 'cloudwatch-logs'), ('stg', 'cde', 'cloudwatch-logs')}
    snapshots, preserved, changed = preserve_consumers(path, before, output, direct)
    assert preserved == {('stg', 'cde', 'cloudwatch-logs')} and len(snapshots) == 2
    assert 'LogGroup' in changed and load_for_edit(path, output).values == before.values
    assert not verify_values(before, load_for_edit(path, output), {}, schema_for)
    output[template] = text.replace('"default":"STANDARD"', '"default":"INFREQUENT_ACCESS"')
    with pytest.raises(ValueError, match='meaning changed'):
        preserve_consumers(path, before, output, direct)
    stg = tmp_path / 'model/parameters/stg/cde/cloudwatch-logs/parameters.yaml'
    output[stg] = stg.read_text() + '# unchanged values still cannot be written\n'
    with pytest.raises(ValueError, match='read-only'):
        preserve_consumers(path, before, output, direct)


@pytest.mark.parametrize('action', ['update', 'add'])
@pytest.mark.parametrize('identity', ['vpc-confirmed', None])
def check_existing_resource_action_rejected(action, identity):
    old = resource(identity=identity)
    with pytest.raises(ValueError, match='add only'):
        selection_records(selection(action=action, basis=['EC2.VPC.Name', 'EC2.VPC.CidrBlock']),
                          [record()], old, old, schema_for)


def check_new_anchor_and_reference_preservation():
    old = resource()
    new = {**old, **resource('009', identity='vpc-new', cidr='10.11.0.0/23')}
    new['desired.resource.009.anchor'] = old['desired.resource.001.anchor']
    with pytest.raises(ValueError, match='new fixed anchor'):
        verify_values(expansion(old), expansion(new), {'009': record('vpc-new')}, schema_for)
    key = 'desired.row.001-001.value'
    before = Expansion(old, {key: {'references': {'Vpc': {'target': '001'}}}}, {})
    after = Expansion(old, {key: {'references': {'Vpc': {'target': '002'}}}}, {})
    with pytest.raises(ValueError, match='reference declaration'):
        verify_values(before, after, {}, schema_for)


@pytest.mark.parametrize('unknown', [False, True])
def check_authored_vpc_append_candidate(tmp_path, unknown):
    from support.import_model_fixtures import build_seed
    from model_templates import load_for_edit, json_text, parse_template
    build_seed(tmp_path)
    path = tmp_path / 'model/dev/cde/vpc.properties'
    directory = tmp_path / 'model/parameters/dev/cde/vpc'
    observed_file = directory / 'observed.json'
    observed = json.loads(observed_file.read_text())
    if unknown:
        observed['values'].pop('observed.row.001-001.value')
        observed_file.write_text(json_text(observed))
    before = load_for_edit(path)
    foreign = {p: p.read_bytes() for p in (tmp_path / 'model').rglob('*') if p.is_file()}
    template = tmp_path / 'model/templates/cde/vpc.properties.tpl'
    definitions = parse_template(template)[0]
    parameters_file, bindings_file = directory / 'parameters.yaml', directory / 'bindings.json'
    params = yaml_read(parameters_file.read_text())
    params['instances']['new-vpc'] = {'parameters': {'CidrBlock': '10.11.0.0/23'}}
    bindings = json.loads(bindings_file.read_text())
    seed = bindings['instances']['main-vpc']
    bindings['instances']['new-vpc'] = {**copy.deepcopy(seed), 'resources': {'resource': '009'},
        'rows': {local: rid.replace('001-', '009-') for local, rid in seed['rows'].items()}, 'parameters': {'Anchor': 'vpc-new'}}
    observed['values']['observed.row.009-001.value'] = 'vpc-new'
    output = {parameters_file: parameter_edit(parameters_file.read_text(), params), bindings_file: json_text(bindings), observed_file: json_text(observed)}
    after = load_for_edit(path, output)
    acquired = record('vpc-new')
    for prop in ('EC2.VPC.EnableDnsHostnames', 'EC2.VPC.EnableDnsSupport'):
        acquired['properties'][prop] = {'status': 'captured', 'value': True}
    captured_schema = lambda prop: {'type': 'boolean' if '.EnableDns' in prop else 'string'}
    warnings = []
    selected = selection_records(selection(rid='009'), [acquired], before.values, after.values, captured_schema, warnings)
    preserve_consumers(path, before, output, {('dev', 'cde', 'vpc'), ('stg', 'cde', 'vpc')})
    assert len(verify_values(before, after, selected, captured_schema)) == 5
    assert bool(warnings) == unknown
    assert all(after.values[k] == value for k, value in before.values.items())
    assert after.values['observed.row.009-001.value'] == 'vpc-new'
    assert after.values['desired.row.009-001.value'] == '[009](#vpc-new)'
    assert after.values['desired.resource.009.resourceMode'] == 'IMPORT'
    assert parse_template(template)[0] == definitions
    assert all(p.read_bytes() == data for p, data in foreign.items())


@pytest.mark.parametrize('relative', ['model/parameters/stg/cde/vpc/parameters.yaml',
    'model/parameters/stg/cde/vpc/bindings.json', 'model/parameters/stg/cde/vpc/observed.json',
    'model/parameters/dev/cde/config/parameters.yaml', 'model/templates/cde/config.properties.tpl'])
def check_foreign_candidate_scope(tmp_path, relative):
    root, directory = tmp_path / 'repository', tmp_path / 'candidate'
    root.mkdir()
    file = directory / relative
    file.parent.mkdir(parents=True)
    file.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='outside'):
        candidate_sources(root, directory, ('dev', 'cde', 'vpc'))


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
