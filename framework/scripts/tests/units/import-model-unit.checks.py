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
        assert acquire.call_args.kwargs == {'no_profile': True, 'resource_types': None}
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


from support.import_model_fixtures import operation_fixture, operation_candidate, operation_contract


@pytest.mark.parametrize('action', ['import-merge', 'import-delete'])
def check_model_operation_preserves_consumers(tmp_path, action):
    from import_promotion import verify_model_operation
    from task_contract import model_operation
    from model_templates import load_expansion
    before, after = tmp_path / 'before', tmp_path / 'after'
    operation_fixture(before)
    sources = operation_candidate(before, after, action)
    verify_model_operation(before, after, model_operation(operation_contract(action)), sources)
    dev = 'model/dev/cde/vpc.properties'
    assert load_expansion(before / dev).values == load_expansion(after / dev).values
    stg = load_expansion(after / 'model/stg/cde/vpc.properties').values
    assert 'desired.resource.009.resourceType' not in stg
    assert stg['desired.resource.001.resourceMode'] == 'IMPORT'
    assert stg['observed.row.001-001.value'] == ('vpc-source' if action == 'import-merge' else 'vpc-stg')
    assert not (after / '.blueprint').exists()


@pytest.mark.parametrize('change', ['cidr', 'observation', 'mode', 'row-id', 'dev', 'binding', 'missing-row', 'extra-delete', 'reference'])
def check_model_operation_rejects_unproved_changes(tmp_path, change):
    from import_promotion import verify_model_operation
    from task_contract import model_operation
    before, after = tmp_path / 'before', tmp_path / 'after'
    operation_fixture(before)
    sources = operation_candidate(before, after)
    directory = after / 'model/parameters/stg/cde/vpc'
    if change in {'cidr', 'mode', 'dev'}:
        file = directory / 'parameters.yaml' if change != 'dev' else after / 'model/parameters/dev/cde/vpc/parameters.yaml'
        text = file.read_text()
        file.write_text(text.replace('10.9.0.0/16', '10.8.0.0/16') if change == 'cidr' else text.replace('IMPORT', 'CREATE') if change == 'mode' else text.replace('10.1.0.0/16', '10.2.0.0/16'))
    elif change == 'observation':
        file = directory / 'observed.json'
        file.write_text(file.read_text().replace('vpc-source', 'fabricated'))
    elif change in {'row-id', 'binding', 'extra-delete'}:
        file = directory / 'bindings.json'
        data = json.loads(file.read_text())
        if change == 'row-id':
            data['instances']['main-vpc']['rows']['cidr'] = '001-099'
        elif change == 'binding':
            data['instances']['main-vpc']['parameters']['Anchor'] = 'new-anchor'
        else:
            del data['instances']['service']
        file.write_text(json.dumps(data))
    else:
        file = after / 'model/templates/cde/vpc.properties.tpl'
        text = file.read_text()
        text = text.replace('desired.row.cidr.property=EC2.VPC.CidrBlock', 'desired.row.cidr.property=EC2.VPC.Other', 1) if change == 'missing-row' else text.replace('display.service.title=', 'desired.note.001.text=[009](#vpc-imported)\ndisplay.service.title=')
        file.write_text(text)
    with pytest.raises(ValueError):
        verify_model_operation(before, after, model_operation(operation_contract()), sources)


@pytest.mark.parametrize('change', ['cross-env', 'same-id', 'missing-target', 'normal-task', 'aws', 'create-source', 'create-destination', 'wrong-source'])
def check_model_operation_contract_scope(tmp_path, change):
    from task_contract import model_operation
    from import_promotion import verify_model_operation
    text = operation_contract()
    if change == 'cross-env':
        text = text.replace('stg/cde/vpc/001', 'dev/cde/vpc/001')
    elif change == 'same-id':
        text = text.replace('stg/cde/vpc/001', 'stg/cde/vpc/009')
    elif change == 'missing-target':
        text = text[:text.index('- Destination resource:')]
    elif change == 'normal-task':
        text = text.replace('- Workflow: `update`', '- Workflow: `ordinary`')
    elif change == 'aws':
        text = text.replace('`forbidden`', '`allowed`')
    else:
        before, after = tmp_path / 'before', tmp_path / 'after'
        operation_fixture(before)
        if change in {'create-source', 'create-destination'}:
            file = before / 'model/parameters/stg/cde/vpc/parameters.yaml'
            file.write_text(file.read_text().replace('IMPORT', 'CREATE', 1) if change == 'create-destination' else file.read_text().replace('IMPORT', 'CREATE'))
        action = 'import-merge' if change == 'create-destination' else 'import-delete'
        sources = operation_candidate(before, after, action)
        with pytest.raises(ValueError):
            verify_model_operation(before, after, model_operation(operation_contract(action, source='stg/cde/vpc/' + ('001' if change == 'wrong-source' else '009'))), sources)
        return
    with pytest.raises(ValueError):
        model_operation(text)


def check_model_operation_row_correspondence():
    from import_promotion import operation_rows
    values = resource()
    values.update({'desired.row.001-010.property': 'EC2.VPC.Tags[].Key', 'desired.row.001-010.value': '`A`',
                   'desired.row.001-011.property': 'EC2.VPC.Tags[].Value', 'desired.row.001-011.value': '`one`',
                   'desired.row.001-020.property': 'EC2.VPC.Tags[].Key', 'desired.row.001-020.value': '`B`',
                   'desired.row.001-021.property': 'EC2.VPC.Tags[].Value', 'desired.row.001-021.value': '`two`'})
    rows = operation_rows(values, '001')
    assert rows['EC2.VPC.Tags[1].Value'][0] == '001-011'
    assert rows['EC2.VPC.Tags[2].Key'][0] == '001-020'
    values['desired.row.001-030.property'] = 'EC2.VPC.CidrBlock'
    values['desired.row.001-030.value'] = '`10.3.0.0/16`'
    with pytest.raises(ValueError, match='ambiguous'):
        operation_rows(values, '001')



@pytest.mark.parametrize('shape', ['optional', 'choice', 'optional-json', 'document', 'untransferred'])
def check_model_operation_shape_preservation(tmp_path, shape):
    from support.import_model_fixtures import spec
    from import_promotion import verify_model_operation
    from task_contract import model_operation
    from model_templates import json_text, load_expansion
    before, after = tmp_path / 'before', tmp_path / 'after'
    operation_fixture(before)
    template = before / 'model/templates/cde/vpc.properties.tpl'
    text = template.read_text()
    if shape in {'optional-json', 'document', 'untransferred'}:
        for definition, value in [('Vpc', '{"Version":"2012-10-17","Statement":[]}'),
                                  ('ImportedVpc', '{"Version":"2012-10-17","Statement":[{"Effect":"Allow"}]}')]:
            start = text.index('# definition: ' + definition + '\n')
            end = text.index('# end-definition', start)
            text = text[:end] + ('# row: document resource\ndesired.row.document.property=EC2.VPC.Document\n'
                'desired.row.document.value=[JSON](vpc/' + definition + '.json)\ndesired.row.document.document=' + value + '\n'
                'desired.row.document.comment=構造比較の合成入力\n') + text[end:]
        for env in ('dev', 'stg'):
            file = before / 'model/parameters' / env / 'cde/vpc/bindings.json'
            bindings = json.loads(file.read_text())
            bindings['instances']['main-vpc']['rows']['document'] = '001-010'
            if env == 'stg':
                bindings['instances']['imported-vpc']['rows']['document'] = '009-020'
            file.write_text(json.dumps(bindings))
    else:
        start = text.index('# definition: ImportedVpc\n')
        end = text.index('# end-definition', start)
        text = text[:end] + ('# row: hostnames resource\ndesired.row.hostnames.property=EC2.VPC.EnableDnsHostnames\n'
                            'desired.row.hostnames.value=`true`\ndesired.row.hostnames.comment=追加取得値\n') + text[end:]
        file = before / 'model/parameters/stg/cde/vpc/bindings.json'
        bindings = json.loads(file.read_text())
        bindings['instances']['imported-vpc']['rows']['hostnames'] = '009-050'
        file.write_text(json.dumps(bindings))
    template.write_text(text)
    sources = operation_candidate(before, after)
    template = after / template.relative_to(before)
    text = template.read_text()
    if shape != 'untransferred':
        begin = text.index('# definition: Vpc\n')
        end = text.index('# end-definition', begin)
        body = text[begin:end]
        if shape in {'optional', 'choice'}:
            body += '# parameter: HasHostnames ' + json_text(spec('boolean')) + '\n# row: hostnames resource\n'
            for field, value in [('property', 'EC2.VPC.EnableDnsHostnames'), ('value', '`true`'), ('comment', '追加取得値')]:
                body += '# optional: desired.row.hostnames.' + field + ' HasHostnames\n'
                body += 'desired.row.hostnames.' + field + '=' + value + '\n'
            selector = 'HasHostnames'
            if shape == 'choice':
                body = body.replace('desired.row.dns.value=<<DnsSupport>>', 'desired.row.dns.value=`false`\n# choice: desired.row.dns.value {"parameter":"HasHostnames","value":"<<DnsSupport>>"}')
        elif shape == 'optional-json':
            selector = 'HasStatement'
            body += '# parameter: HasStatement ' + json_text(spec('boolean')) + '\n'
            body += '# optional-json: desired.row.document.document /Statement/0 HasStatement\n'
            body = body.replace('"Statement":[]', '"Statement":[{"Effect":"Allow"}]')
        else:
            selector = 'Document'
            body += '# parameter: Document ' + json_text(spec('object')) + '\n'
            body = body.replace('desired.row.document.document={"Version":"2012-10-17","Statement":[]}', 'desired.row.document.document="<<Document>>"')
        text = text[:begin] + body + text[end:]
        template.write_text(text)
        for env in ('dev', 'stg'):
            file = after / 'model/parameters' / env / 'cde/vpc/parameters.yaml'
            parameters = yaml_read(file.read_text())
            parameters['instances']['main-vpc']['parameters'][selector] = ({'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow'}] if env == 'stg' else []} if shape == 'document' else env == 'stg')
            if shape == 'choice' and env == 'dev':
                del parameters['instances']['main-vpc']['parameters']['DnsSupport']
            file.write_text(parameter_edit(file.read_text(), parameters))
        if shape in {'optional', 'choice'}:
            file = after / 'model/parameters/stg/cde/vpc/bindings.json'
            bindings = json.loads(file.read_text())
            bindings['instances']['main-vpc']['rows']['hostnames'] = '001-090'
            file.write_text(json.dumps(bindings))
    if shape == 'untransferred':
        with pytest.raises(ValueError, match='not transferred'):
            verify_model_operation(before, after, model_operation(operation_contract()), sources)
    else:
        verify_model_operation(before, after, model_operation(operation_contract()), sources)
        assert load_expansion(before / 'model/dev/cde/vpc.properties').values == load_expansion(after / 'model/dev/cde/vpc.properties').values



@pytest.mark.parametrize('failure', ['none', 'tamper', 'missing', 'expired', 'task', 'base', 'scope'])
def check_external_completion_proof(tmp_path, monkeypatch, failure):
    from datetime import datetime, timedelta, timezone
    root = tmp_path / 'repository'
    root.mkdir()
    monkeypatch.setattr(import_guard.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(import_guard, 'task_path', lambda root: root / 'tasks/example.md')
    monkeypatch.setattr(import_guard, 'workflow', lambda root: 'tasks/example.md')
    monkeypatch.setattr(import_guard, 'base_revision', lambda root: 'base')
    monkeypatch.setattr('import_scope.selected', lambda root: ('stg', 'cde', 'vpc'))
    proof = {'version': 3, 'task': 'tasks/example.md', 'base': 'base', 'scope': ['stg', 'cde', 'vpc'],
             'acquisition': 'receipt', 'sources': {}, 'plan': 'verified', 'complete': True,
             'model': 'unchanged', 'markdown': 'unchanged', 'ownedArtifacts': [],
             'acquiredAt': datetime.now(timezone.utc).isoformat()}
    if failure == 'expired':
        proof['acquiredAt'] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    elif failure in {'task', 'base'}:
        proof[failure] = 'wrong'
    elif failure == 'scope':
        proof['scope'] = ['dev', 'cde', 'vpc']
    file = import_guard.proof_path(root)
    assert not file.is_relative_to(root)
    import_guard.write_sealed(root, file, proof)
    if failure == 'tamper':
        file.write_text(file.read_text().replace('verified', 'fabricated'))
    elif failure == 'missing':
        file.unlink()
    if failure != 'none':
        with pytest.raises(ValueError, match='no verified'):
            import_guard.read_proof(root)
    else:
        assert import_guard.read_proof(root) == proof
        import_guard.discard_import_proof(root, 'tasks/example.md')
        assert not file.exists()
    assert not (root / '.blueprint').exists()


@pytest.mark.parametrize('mixed', [False, True])
def check_legacy_proof_migration(tmp_path, monkeypatch, mixed):
    from datetime import datetime, timezone
    root = tmp_path / 'repository'
    root.mkdir()
    monkeypatch.setattr(import_guard.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(import_guard, 'task_path', lambda root: root / 'tasks/example.md')
    monkeypatch.setattr(import_guard, 'workflow', lambda root: 'tasks/example.md')
    monkeypatch.setattr(import_guard, 'base_revision', lambda root: 'base')
    monkeypatch.setattr('import_scope.selected', lambda root: ('stg', 'cde', 'vpc'))
    proof = {'version': 3, 'task': 'tasks/example.md', 'base': 'base', 'scope': ['stg', 'cde', 'vpc'],
             'acquisition': 'receipt', 'sources': {}, 'plan': 'verified', 'complete': True,
             'model': 'unchanged', 'markdown': 'unchanged', 'ownedArtifacts': [],
             'acquiredAt': datetime.now(timezone.utc).isoformat()}
    legacy = root / '.blueprint/import/example.json'
    legacy.parent.mkdir(parents=True)
    import_guard.write_sealed(root, legacy, proof)
    other = legacy.parent / 'unowned.txt'
    if mixed:
        other.write_text('preserve')
    assert import_guard.read_proof(root) == proof
    assert not legacy.exists() and import_guard.proof_path(root).exists()
    assert (root / '.blueprint').exists() == mixed
    if mixed:
        assert other.read_text() == 'preserve'
    import_guard.discard_import_proof(root, 'tasks/example.md')


def check_snapshot_proof_resigning_and_cleanup(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    root, snapshot = tmp_path / 'repository', tmp_path / 'snapshot'
    root.mkdir(); snapshot.mkdir()
    monkeypatch.setattr(import_guard.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(import_guard, 'task_path', lambda root: root / 'tasks/example.md')
    monkeypatch.setattr(import_guard, 'workflow', lambda root: 'tasks/example.md')
    monkeypatch.setattr(import_guard, 'base_revision', lambda root: 'base')
    monkeypatch.setattr('import_scope.selected', lambda root: ('stg', 'cde', 'vpc'))
    monkeypatch.setattr(import_guard, 'require_import_changes', lambda root: None)
    proof = {'version': 3, 'task': 'tasks/example.md', 'base': 'base', 'scope': ['stg', 'cde', 'vpc'],
             'acquisition': 'receipt', 'sources': {}, 'plan': 'verified', 'complete': True,
             'model': 'unchanged', 'markdown': 'unchanged', 'ownedArtifacts': [],
             'acquiredAt': datetime.now(timezone.utc).isoformat()}
    import_guard.write_sealed(root, import_guard.proof_path(root), proof)
    import_guard.copy_import_proof(root, snapshot)
    assert import_guard.read_proof(snapshot) == proof
    assert import_guard.proof_path(root).read_bytes() != import_guard.proof_path(snapshot).read_bytes()
    import_guard.discard_import_proof(snapshot, 'tasks/example.md')
    assert not import_guard.proof_path(snapshot).exists() and import_guard.read_proof(root) == proof
    assert not (root / '.blueprint').exists() and not (snapshot / '.blueprint').exists()
    import_guard.discard_import_proof(root, 'tasks/example.md')



def generic_context(service='datazone', resources=None, **kwargs):
    from support.import_model_fixtures import CloudControlCli, ACCOUNT
    cli = CloudControlCli(resources or {}, **kwargs)
    target = {'environment': 'dev', 'directory': 'synthetic', 'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1'}
    ctx = m.import_context(m.ROOT, target, cli, service)
    ctx.verify()
    return ctx, cli


def domain(identifier='dzd-one'):
    return {'identifier': identifier, 'properties': {'Id': identifier, 'Name': 'fixture', 'DomainVersion': 'V2', 'SingleSignOn': {'Type': 'DISABLED'}}}


def check_inventory_singleflight_and_isolation():
    from concurrent.futures import ThreadPoolExecutor
    from import_inventory import ImportInventory, inventory_for
    from collections import Counter
    resources = {'DataZone.Domain': [domain(), domain('dzd-two')]}
    ctx, cli = generic_context(resources=resources)
    original = m._normalize_records
    from import_inventory import import_comparison
    with patch('import_inventory.import_comparison', wraps=import_comparison) as mapping, patch.object(m, '_normalize_records', wraps=original) as normalize:
        def acquire(_):
            assert inventory_for(ctx) is ImportInventory(ctx)
            return m.normalize_records(ctx, 'datazone', m.inventory(ctx, 'datazone', ['DataZone.Domain']))
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(acquire, range(16)))
        assert all(result == results[0] for result in results)
        assert mapping.call_count == 1 and normalize.call_count == 2
    calls = Counter((s, o, json.dumps(i, sort_keys=True)) for s, o, i in cli.calls)
    assert len(calls) == 5 and set(calls.values()) == {1}  # STS + two list pages + two detail reads.
    assert ctx.metrics['api_calls'] == 5
    assert ctx.metrics['inventory_normalize_runs'] == ctx.metrics['inventory_identity_runs'] == 2
    assert ctx.metrics['inventory_mapping_runs'] == 1
    assert inventory_for(ctx).statuses == {'DataZone.Domain': {'status': 'complete'}}
    results[0][0]['properties']['DataZone.Domain.Name']['value'] = 'mutated'
    assert acquire(0)[0]['properties']['DataZone.Domain.Name']['value'] == 'fixture'
    other, other_cli = generic_context(resources=resources)
    assert inventory_for(other) is not inventory_for(ctx)
    assert len(m.inventory(other, 'datazone', ['DataZone.Domain'])) == 2 and len(other_cli.calls) == 5
    assert results[1][0]['identityComponents'] == [{'property': 'DataZone.Domain.Id', 'value': 'dzd-one'}]


def check_context_api_singleflight_and_failures():
    from concurrent.futures import ThreadPoolExecutor
    from collections import Counter
    resources = {'DataZone.Domain': [domain()]}
    ctx, cli = generic_context(resources=resources)
    def call(_):
        return ctx.call('cloudcontrol', 'get_resource', TypeName='AWS::DataZone::Domain', Identifier='dzd-one')
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(call, range(32)))
    assert len(cli.calls) == 2
    results[0]['ResourceDescription']['Identifier'] = 'changed'
    assert call(0)['ResourceDescription']['Identifier'] == 'dzd-one'
    failed, failed_cli = generic_context(resources=resources, fail={('cloudcontrol', 'get-resource', 'dzd-one'): 'AccessDeniedException'})
    def denied(_):
        with pytest.raises(m.comparator().AcquisitionError, match='AccessDeniedException'):
            failed.call('cloudcontrol', 'get_resource', TypeName='AWS::DataZone::Domain', Identifier='dzd-one')
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(denied, range(16)))
    assert len(failed_cli.calls) == 2
    assert failed.metrics['api_calls'] == 2 and failed.metrics['cache_hits'] >= 15


def check_cloudtrail_all_model_properties():
    from import_inventory import inventory_for
    ctx, cli = generic_context('cloudtrail', {'CloudTrail.Trail': [{'identifier': 'audit', 'list': {'TrailName': 'audit'}, 'properties': {'TrailName': 'audit'}}]})
    result = m.normalize_records(ctx, 'cloudtrail', m.inventory(ctx, 'cloudtrail'))
    assert len(result) == 1 and len(result[0]['properties']) == 13
    assert all(value['status'] == 'captured' for value in result[0]['properties'].values())
    assert result[0]['properties']['CloudTrail.Trail.IsLogging']['value'] is True
    assert result[0]['properties']['CloudTrail.Trail.S3BucketName']['value'] == 'audit-bucket'
    assert result[0]['properties']['CloudTrail.Trail.KMSKeyId']['value'] == 'key-confirmed'
    assert len(cli.calls) == 5  # STS, provider discovery, three existing adapter APIs.
    assert not any(operation == 'get-resource' for _, operation, _ in cli.calls)
    assert inventory_for(ctx).statuses['CloudTrail.Trail']['status'] == 'complete'


def check_tgw_provider_and_composite_identity():
    from import_inventory import inventory_for
    resources = {
        'EC2.TransitGateway': [{'identifier': 'tgw-one', 'properties': {'Id': 'tgw-one', 'AmazonSideAsn': 64512, 'Description': 'fixture',
            'DnsSupport': 'enable', 'DefaultRouteTableAssociation': 'enable', 'DefaultRouteTablePropagation': 'enable',
            'AutoAcceptSharedAttachments': 'disable', 'VpnEcmpSupport': 'enable'}}],
        'EC2.TransitGatewayRouteTable': [{'identifier': 'tgw-rtb-one', 'properties': {'TransitGatewayRouteTableId': 'tgw-rtb-one', 'TransitGatewayId': 'tgw-one'}}],
        'EC2.TransitGatewayRoute': [{'identifier': 'opaque-route', 'properties': {'TransitGatewayRouteTableId': 'tgw-rtb-one', 'DestinationCidrBlock': '10.0.0.0/16', 'TransitGatewayAttachmentId': 'tgw-attach-one', 'Blackhole': False}}],
        'EC2.TransitGatewayRouteTableAssociation': [{'identifier': 'opaque-assoc', 'properties': {'TransitGatewayRouteTableId': 'tgw-rtb-one', 'TransitGatewayAttachmentId': 'tgw-attach-one'}}],
        'EC2.TransitGatewayRouteTablePropagation': [{'identifier': 'opaque-propagation', 'properties': {'TransitGatewayRouteTableId': 'tgw-rtb-one', 'TransitGatewayAttachmentId': 'tgw-attach-one'}}],
    }
    ctx, cli = generic_context('ec2', resources)
    result = m.normalize_records(ctx, 'ec2', m.inventory(ctx, 'ec2', list(resources)))
    assert len(result) == 5 and all(item['status'] == 'complete' for item in inventory_for(ctx).statuses.values())
    assert all(value['status'] == 'captured' for record in result for value in record['properties'].values())
    route = next(r for r in result if r['kind'] == 'EC2.TransitGatewayRoute')
    assert route['identity'] == 'opaque-route' and route['identityProperty'] is None
    assert route['identityComponents'] == [{'property': 'EC2.TransitGatewayRoute.TransitGatewayRouteTableId', 'value': 'tgw-rtb-one'},
                                          {'property': 'EC2.TransitGatewayRoute.DestinationCidrBlock', 'value': '10.0.0.0/16'}]
    lists = [inputs for _, op, inputs in cli.calls if op == 'list-resources']
    assert len(lists) == 5 and sum('ResourceModel' in inputs for inputs in lists) == 3
    assert len(cli.calls) == 11
    from aws_mapping_compare import comparison
    _, compare = comparison(m.ROOT, 'ec2')
    assert all(compare[prop].field.classification == 'supported' for record in result for prop in record['properties'])


def check_inventory_status_and_partial_retention():
    from import_inventory import inventory_for
    ctx, cli = generic_context(resources={'DataZone.Domain': [domain(), domain('dzd-two')]},
                               fail={('cloudcontrol', 'get-resource', 'dzd-two'): 'AccessDeniedException'})
    records = m.normalize_records(ctx, 'datazone', m.inventory(ctx, 'datazone', ['DataZone.Domain']))
    assert len(records) == 1 and records[0]['identity'] == 'dzd-one'
    assert inventory_for(ctx).statuses['DataZone.Domain']['status'] == 'permission_denied'
    count = len(cli.calls)
    assert len(m.inventory(ctx, 'datazone', ['DataZone.Domain'])) == 1 and len(cli.calls) == count
    evidence = {'version': 2, 'inventory': inventory_for(ctx).statuses}
    assert not import_guard.acquisition_complete(evidence)
    empty, _ = generic_context()
    assert m.inventory(empty, 'datazone', ['DataZone.Domain']) == []
    assert inventory_for(empty).statuses['DataZone.Domain']['status'] == 'empty'
    assert import_guard.acquisition_complete({'version': 2, 'inventory': inventory_for(empty).statuses})
    assert m.inventory(empty, 'datazone', ['DataZone.DataSource']) == []
    assert inventory_for(empty).statuses['DataZone.DataSource']['status'] == 'not_modelled'
    with pytest.raises(ValueError, match='owner'):
        m.inventory(empty, 'datazone', ['EC2.TransitGateway'])


def check_cloudcontrol_json_and_readonly_boundary():
    from import_inventory import properties_json, inventory_for
    for value in ('null', '[]', '{"Id":1,"Id":2}', '{"Id":NaN}', '{invalid', {}, None):
        with pytest.raises((ValueError, TypeError)):
            properties_json(value)
    from support.import_model_fixtures import CloudControlCli, ACCOUNT
    target = {'environment': 'dev', 'directory': 'synthetic', 'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1'}
    ctx = m.import_context(m.ROOT, target, CloudControlCli({}), 'datazone')
    with pytest.raises(ValueError, match='verified'):
        ctx.call('cloudcontrol', 'list_resources', TypeName='AWS::DataZone::Domain')
    ctx.verify()
    for operation in ('create_resource', 'update_resource', 'delete_resource'):
        with pytest.raises(ValueError, match='allowlist'):
            ctx.call('cloudcontrol', operation)
    with pytest.raises(ValueError, match='allowlist'):
        ctx.call('datazone', 'get_domain', identifier='unvalidated-selector')
    with pytest.raises(m.comparator().AcquisitionError, match='AccountMismatch'):
        generic_context(account='999999999999')
    with pytest.raises(ValueError, match='unimplemented service'):
        m.comparator().Context(m.ROOT, target, services=('datazone',))


def check_composite_identity_same_resource_only():
    kind = 'EC2.TransitGatewayRouteTableAssociation'
    props = [kind + '.TransitGatewayRouteTableId', kind + '.TransitGatewayAttachmentId']
    def values(rid, table, attachment):
        result = {f'desired.resource.{rid}.resourceType': kind, f'desired.resource.{rid}.resourceMode': 'IMPORT', f'desired.resource.{rid}.anchor': 'association-' + rid}
        for n, (prop, value) in enumerate(zip(props, (table, attachment)), 1):
            if value is not None:
                result[f'desired.row.{rid}-{n:03d}.property'] = prop
                result[f'desired.row.{rid}-{n:03d}.value'] = '`' + value + '`'
        return result
    captured = {'record': 'assoc', 'kind': kind, 'identity': 'opaque', 'identityProperty': None, 'identityProperties': props,
                'identityStatus': 'known', 'identityComponents': [{'property': p, 'value': v} for p, v in zip(props, ('table-a', 'attachment-b'))],
                'properties': {p: {'status': 'captured', 'value': v} for p, v in zip(props, ('table-a', 'attachment-b'))}}
    old = {**values('001', 'table-a', 'attachment-a'), **values('002', 'table-b', 'attachment-b')}
    new = {**old, **values('009', 'table-a', 'attachment-b')}
    selected = selection_records(selection('assoc', '009'), [captured], old, new, schema_for)
    assert verify_values(expansion(old), expansion(new), selected, schema_for)
    old_same = values('001', 'table-a', 'attachment-b')
    with pytest.raises(ValueError, match='duplicate identity'):
        selection_records(selection('assoc', '009'), [captured], old_same, {**old_same, **values('009', 'table-a', 'attachment-b')}, schema_for)
    partial = values('001', 'table-a', None)
    warnings = []
    selection_records(selection('assoc', '009'), [captured], partial, {**partial, **values('009', 'table-a', 'attachment-b')}, schema_for, warnings)
    assert warnings and warnings[0]['existingResources'] == ['001']
    invalid = {**new, 'desired.row.009-002.value': '`wrong`'}
    with pytest.raises(ValueError, match='differs|identity'):
        verify_values(expansion(old), expansion(invalid), selected, schema_for)



@pytest.mark.parametrize('case,expected', [('no-list', 'unsupported'), ('no-read', 'unsupported'), ('filter', 'requires_filter'), ('missing', 'failed')])
def check_inventory_capability_outcomes(case, expected):
    from import_inventory import inventory_for
    item = domain()
    if case == 'missing':
        del item['properties']['Name']
    ctx, cli = generic_context(resources={'DataZone.Domain': [item]})
    inv = inventory_for(ctx)
    def schema(kind):
        # Plain copies of the fixture schema; no static singleton mutation.
        from aws_mapping import readonly
        data = {'handlers': {'list': {}, 'read': {}}, 'primaryIdentifier': ['/properties/Id'], 'required': ['Name']}
        if case == 'no-list':
            del data['handlers']['list']
        elif case == 'no-read':
            del data['handlers']['read']
        elif case == 'filter':
            data['handlers']['list']['handlerSchema'] = {'required': ['UnboundScope']}
        return readonly(data)
    with patch.object(inv, 'schema', side_effect=schema):
        records = m.normalize_records(ctx, 'datazone', m.inventory(ctx, 'datazone', ['DataZone.Domain']))
    assert inv.statuses['DataZone.Domain']['status'] == expected
    assert len(records) == (1 if case == 'missing' else 0)
    count = len(cli.calls)
    assert len(inv.inventory('datazone', 'DataZone.Domain')) == len(records)
    assert len(cli.calls) == count


def check_fetch_singleflight_and_trace():
    from concurrent.futures import ThreadPoolExecutor
    from import_inventory import inventory_for
    ctx, cli = generic_context(resources={'DataZone.Domain': [domain()]})
    def get(context, resource, getter):
        return context.call('cloudcontrol', 'get_resource', TypeName='AWS::DataZone::Domain', Identifier='dzd-one')
    resource = SimpleNamespace(model=SimpleNamespace(path=Path('/synthetic/datazone')), number='one', module=SimpleNamespace(fetch=get))
    with patch.object(resource.module, 'fetch', wraps=get) as fetch:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: ctx.fetch(resource, 'provider'), range(16)))
        assert fetch.call_count == 1 and len(cli.calls) == 2
    assert results[0] == results[-1]
    assert ctx.fetch_trace[resource.model.path, 'one', 'provider'] == [{'api': 'cloudcontrol.get_resource', 'inputs': {'TypeName': 'AWS::DataZone::Domain', 'Identifier': 'dzd-one'}}]
    inv = inventory_for(ctx)
    inv.mapping('datazone'); inv.mapping('datazone')
    assert ctx.metrics['inventory_mapping_runs'] == 1
    record = {'kind': 'DataZone.Domain', 'identity': 'one', 'cloudProperties': {'Id': 'one'}}
    inv.identity('DataZone.Domain', record); inv.identity('DataZone.Domain', record)
    assert ctx.metrics['inventory_identity_runs'] == 1
    inv.property_schema('DataZone.Domain.Name'); inv.property_schema('DataZone.Domain.Name')
    assert ctx.metrics['inventory_property_schema_runs'] == 1
    ctx.target['awsRegion'] = 'us-east-1'
    with pytest.raises(ValueError, match='connection changed'):
        ctx.call('cloudcontrol', 'get_resource', TypeName='AWS::DataZone::Domain', Identifier='dzd-one')


def check_tgw_compare_provider_evaluation():
    from aws_mapping_compare import comparison, value
    kind = 'EC2.TransitGatewayRouteTableAssociation'
    identifier = 'table-one|attachment-one'
    payload = {'TransitGatewayRouteTableId': 'table-one', 'TransitGatewayAttachmentId': 'attachment-one'}
    ctx, cli = generic_context('ec2', {kind: [{'identifier': identifier, 'properties': payload}]})
    ctx.import_mode = False  # Exercise the unchanged Compare service gate plus the explicit TGW capability.
    model = SimpleNamespace(ctx=ctx, path=Path('/synthetic/ec2'), service='ec2', values={})
    rows = [(str(i), {'property': kind + '.' + prop, 'value': '`' + actual + '`'}) for i, (prop, actual) in enumerate(payload.items())]
    resource = m.comparator().Resource(model, '001', {'resourceType': kind}, rows)
    mapping, mapped = comparison(m.ROOT, 'ec2')
    for prop, expected in payload.items():
        key = kind + '.' + prop
        assert value(ctx, resource, mapping, mapped[key], key)[1] == expected
    assert resource.identity() == identifier
    assert len(cli.calls) == 2 and cli.calls[-1][2]['Identifier'] == identifier
    gateway, gateway_cli = generic_context('ec2', {'EC2.TransitGateway': [{'identifier': 'tgw-one', 'properties': {'Id': 'tgw-one'}}]})
    gateway.import_mode = False
    model = SimpleNamespace(ctx=gateway, path=Path('/synthetic/ec2'), service='ec2', values={'observed.row.001-001.value': '`tgw-one`'})
    resource = m.comparator().Resource(model, '001', {'resourceType': 'EC2.TransitGateway', 'anchor': 'gateway'}, [('001-001', {'property': 'EC2.TransitGateway.Id', 'value': '[Gateway](#gateway)'})])
    assert resource.identity() == 'tgw-one' and len(gateway_cli.calls) == 2
    model.values.clear()
    with pytest.raises(m.comparator().Unresolved, match='observation'):
        resource.identity()


def check_legacy_adapter_api_counts():
    from support.import_model_fixtures import SERVICES, ACCOUNT, aws
    # Baseline counts are physical mock transport invocations on the identical fixture.
    expected = {'vpc': 7, 'config': 3, 'cloudwatch-logs': 2, 'data-firehose': 3, 'quicksight': 7, 'security-hub': 2, 'transit-gateway': 2}
    measured = {}
    for service in SERVICES:
        cli = aws(service)
        target = {'environment': 'dev', 'directory': 'cde', 'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1', 'awsProfile': 'confirmed'}
        ctx = m.import_context(m.ROOT, target, cli, service)
        ctx.verify()
        records = m.inventory(ctx, service)
        m.normalize_records(ctx, service, records)
        first = len(cli.calls)
        m.normalize_records(ctx, service, m.inventory(ctx, service))
        assert len(cli.calls) == first
        measured[service] = first
    assert measured == expected



@pytest.mark.parametrize('account,region', [('999999999999', 'ap-northeast-1'), ('123456789012', 'us-east-1')])
def check_acquisition_account_region_isolation(account, region):
    from support.import_model_fixtures import CloudControlCli
    from import_inventory import inventory_for
    first, _ = generic_context(resources={'DataZone.Domain': [domain()]})
    first_records = m.inventory(first, 'datazone', ['DataZone.Domain'])
    cli = CloudControlCli({'DataZone.Domain': [domain('dzd-other')]}, account=account)
    target = {'environment': 'dev', 'directory': 'synthetic', 'awsAccountId': account, 'awsRegion': region}
    second = m.import_context(m.ROOT, target, cli, 'datazone')
    second.verify()
    records = m.inventory(second, 'datazone', ['DataZone.Domain'])
    assert records[0]['identity'] == 'dzd-other' and first_records[0]['identity'] == 'dzd-one'
    assert inventory_for(second) is not inventory_for(first) and len(cli.calls) == 3
    with pytest.raises(TypeError):
        inventory_for(second).schema('DataZone.Domain')['primaryIdentifier'] = []


def check_resource_type_cli_selection():
    arguments = ['import-model', '--environment', 'dev', '--service', 'ec2', '--phase', 'acquire',
                 '--resource-type', 'EC2.TransitGateway', '--resource-type', 'EC2.TransitGatewayRouteTable']
    with patch.object(sys, 'argv', arguments), patch.object(m, 'acquire', return_value={'status': 'acquired', 'markdown': 'not-run'}) as acquire:
        assert m.main() == 0
        assert acquire.call_args.kwargs['resource_types'] == ['EC2.TransitGateway', 'EC2.TransitGatewayRouteTable']


def check_unknown_acquired_identity_rejected():
    captured = record()
    captured.update(identityStatus='unknown', identityComponents=[{'property': 'EC2.VPC.VpcId', 'value': None}])
    with pytest.raises(ValueError, match='identity is unknown'):
        selection_records(selection(), [captured], {}, resource(), schema_for)
    with pytest.raises(ValueError, match='inventory status'):
        import_guard.acquisition_complete({'version': 2, 'inventory': {}})
    with pytest.raises(ValueError, match='version'):
        import_guard.acquisition_complete({'version': 99})
    assert import_guard.acquisition_complete({'version': 1})


def check_batch_model_operation(tmp_path):
    import json
    from model_operation_checks import verify_model_operation
    from task_contract import model_operation
    from support.import_model_fixtures import batch_operation_fixture
    before, after = tmp_path / 'before', tmp_path / 'after'
    contract, sources = batch_operation_fixture(before, after)
    verify_model_operation(before, after, model_operation(contract), sources)
    observed_file = after / 'model/parameters/stg/cde/vpc/observed.json'
    observed = json.loads(observed_file.read_text())
    observed['values']['observed.row.013-001.value'] = 'not-transferred'
    observed_file.write_text(json.dumps(observed))
    with pytest.raises(ValueError, match='not transferred'):
        verify_model_operation(before, after, model_operation(contract), sources)


def check_intermediate_source_context(tmp_path, monkeypatch):
    from unittest.mock import patch
    import worktree_task
    from import_guard import source_write_context
    from model_sources import read_sources, write_sources
    from sync_runtime import GenerationInputs
    from task_contract import start
    operation_fixture(tmp_path)
    path = tmp_path / 'model/stg/cde/vpc.properties'
    raw = read_sources(path)
    inputs = tmp_path / 'model/parameters/stg/cde/vpc/parameters.yaml'
    name = 'tasks/parent.md'
    listed = '\n'.join('- `' + value + '`' for value in [name, inputs.relative_to(tmp_path).as_posix()])
    text = operation_contract() + '## Validation scope\n- `stg/cde/vpc`\n## Modified files\n' + listed + '\n## Allowed paths\n' + listed + '\n'
    start(tmp_path, name, text)
    state = {'task_file': name, 'worktree': str(tmp_path), 'merged': None}
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', 'tasks/wrong.md')
    with patch.object(worktree_task, 'load', return_value=(tmp_path, None, None, state)), \
         patch.object(worktree_task, 'task_worktree', return_value=tmp_path), \
         patch('model_templates.load_expansion', side_effect=AssertionError('raw save cannot expand')), \
         patch('model_templates.affected', side_effect=AssertionError('raw save cannot calculate expanded impact')), \
         patch.object(GenerationInputs, 'open_stage', side_effect=AssertionError('raw save cannot stage')):
        with source_write_context(tmp_path, name) as first:
            assert write_sources(first, {inputs: 'instances: {}\n'}) == (inputs,)
            with pytest.raises(ValueError, match='closed'):
                write_sources(first, {})
        assert read_sources(path)[inputs] == 'instances: {}\n'
        with source_write_context(tmp_path, name) as second:
            assert write_sources(second, {inputs: 'instances: {}\n'}) == ()
        with source_write_context(tmp_path, name) as third:
            inputs.write_text('instances: {} # outside edit\n')
            with pytest.raises(ValueError, match='inputs changed'):
                write_sources(third, {inputs: raw[inputs]})
        assert inputs.read_text() == 'instances: {} # outside edit\n'
        with source_write_context(tmp_path, name) as fourth:
            with pytest.raises(ValueError, match='unregistered'):
                write_sources(fourth, {tmp_path / 'project.json': '{}'})
        with source_write_context(tmp_path, name) as fifth:
            with pytest.raises(ValueError, match='YAML'):
                write_sources(fifth, {inputs: 'instances: [\n'})
        assert inputs.read_text() == 'instances: {} # outside edit\n'


@pytest.mark.parametrize('field', ['value', 'document', 'parentReference', 'name', 'identifier', 'reevaluation'])
def check_explicit_reference_operation(tmp_path, field):
    import json
    import yaml
    from support.import_model_fixtures import declaration, binding, spec
    from model_operation_checks import verify_model_operation
    from task_contract import model_operation
    before, after = tmp_path / 'before', tmp_path / 'after'
    operation_fixture(before)
    external = field in {'name', 'identifier', 'reevaluation'}
    if external:
        template = before / 'model/templates/cde/vpc.properties.tpl'
        text = template.read_text()
        for definition in ('Vpc', 'ImportedVpc'):
            text = text.replace('# definition: ' + definition + '\n', '# definition: ' + definition + '\n# parameter: Name ' + json.dumps(spec(format='literal')) + '\n')
        text = text.replace('desired.row.cidr.property=', '# row: name resource\ndesired.row.name.property=EC2.VPC.Name\ndesired.row.name.value=<<Name>>\ndesired.row.name.comment=name\ndesired.row.cidr.property=')
        template.write_text(text)
        for env in ('dev', 'stg'):
            directory = before / 'model/parameters' / env / 'cde/vpc'
            bindings_file, inputs_file = directory / 'bindings.json', directory / 'parameters.yaml'
            bindings, inputs = json.loads(bindings_file.read_text()), yaml_read(inputs_file.read_text())
            for instance, rid in [('main-vpc', '001'), ('imported-vpc', '009')]:
                if instance in bindings['instances']:
                    bindings['instances'][instance]['rows']['name'] = rid + '-004'
                    inputs['instances'][instance]['parameters']['Name'] = 'source-name' if rid == '009' else 'destination-name'
            bindings_file.write_text(json.dumps(bindings)); inputs_file.write_text(yaml.safe_dump(inputs))
    fields = {'vpc': ('VpcId', '<<Vpc>>'), 'cidr': ('CidrBlock', '`10.2.0.0/24`')}
    if field == 'document':
        fields['vpc'] = ('Policy', '[JSON](vpc/policy.json)')
    lines = declaration('Subnet', 'EC2.Subnet', fields,
                        {'Vpc': spec('reference', resourceType='EC2.VPC', **({'service': 'vpc', 'format': 'identifier', 'property': 'EC2.VPC.VpcId'} if field == 'identifier' else {'service': 'vpc', 'format': 'name'} if external else {})), 'ResourceMode': spec()})
    if field == 'document':
        lines.insert(-1, 'desired.row.vpc.document={"Vpc":"<<Vpc>>","Sibling":true}')
    if field == 'parentReference':
        lines.insert(-1, 'desired.resource.resource.parentReference=<<Vpc>>')
    template = before / 'model/templates/cde/vpc.properties.tpl'
    template.write_text(template.read_text() + '\n'.join(lines) + '\n')
    directory = before / 'model/parameters/stg/cde/vpc'
    bindings_file, inputs_file = directory / 'bindings.json', directory / 'parameters.yaml'
    bindings, inputs = json.loads(bindings_file.read_text()), yaml_read(inputs_file.read_text())
    bindings['instances']['subnet'] = binding('Subnet', '020', fields, 'subnet-keep')
    inputs['instances']['subnet'] = {'parameters': {'Vpc': ('001' if field == 'reevaluation' else '009') if external else 'imported-vpc', 'ResourceMode': 'CREATE'}}
    bindings_file.write_text(json.dumps(bindings)); inputs_file.write_text(yaml.safe_dump(inputs))
    from model_reference_usage import outgoing_references
    from utils.aws_mappings import mapping_alias
    with mapping_alias(Path(__file__).resolve().parents[4], before):
        usages = outgoing_references(before, 'stg/cde/vpc/020')
    expected_source = 'stg/cde/vpc/' + ('001' if field == 'reevaluation' else '009')
    assert usages and all(item['producer'] == expected_source for item in usages)
    if field == 'identifier':
        assert any(item['format'] == 'identifier' and item['resolvedValue'] == 'vpc-source' for item in usages)
    if field == 'name':
        assert any(item['format'] == 'name' and item['resolvedValue'] == 'source-name' for item in usages)
    sources = operation_candidate(before, after)
    inputs_file = after / inputs_file.relative_to(before)
    inputs = yaml_read(inputs_file.read_text())
    inputs['instances']['subnet']['parameters']['Vpc'] = '001' if external else 'main-vpc'
    if external:
        inputs['instances']['main-vpc']['parameters']['Name'] = 'source-name'
    inputs_file.write_text(yaml.safe_dump(inputs))
    contract = operation_contract().split('- Source resource:')[0] + '## Model merge pairs\n' + '- ' + json.dumps({'source': 'stg/cde/vpc/009', 'destination': 'stg/cde/vpc/001'}) + '\n'
    reference = {'consumer': 'stg/cde/vpc/020', 'field': 'value' if external else field, 'source': 'stg/cde/vpc/001' if field == 'reevaluation' else 'stg/cde/vpc/009', 'destination': 'stg/cde/vpc/001'}
    if field != 'parentReference':
        reference['property'] = 'EC2.Subnet.Policy' if field == 'document' else 'EC2.Subnet.VpcId'
    if field == 'document':
        reference['pointer'] = '/Vpc'
    references = [reference]
    if field == 'parentReference':
        references.append({**reference, 'field': 'value', 'property': 'EC2.Subnet.VpcId'})
    contract += '## Model reference changes\n' + ''.join('- ' + json.dumps(ref) + '\n' for ref in references)
    from utils.aws_mappings import mapping_alias
    with mapping_alias(Path(__file__).resolve().parents[4], before), mapping_alias(Path(__file__).resolve().parents[4], after):
        verify_model_operation(before, after, model_operation(contract), sources)
    with mapping_alias(Path(__file__).resolve().parents[4], before), mapping_alias(Path(__file__).resolve().parents[4], after), pytest.raises(ValueError):
        verify_model_operation(before, after, model_operation(contract.split('## Model reference changes')[0]), sources)
    template = after / template.relative_to(before)
    content = template.read_text()
    template.write_text(content.replace('<<Vpc>>', '[001](#vpc-main)'))
    with mapping_alias(Path(__file__).resolve().parents[4], before), mapping_alias(Path(__file__).resolve().parents[4], after), pytest.raises(ValueError):
        verify_model_operation(before, after, model_operation(contract), sources)



def check_generic_reference_usage(tmp_path):
    from support.import_model_fixtures import dependency_fixture
    from model_reference_usage import incoming_references, outgoing_references
    dependency_fixture(tmp_path)
    snapshot = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    incoming = incoming_references(tmp_path, 'stg/cde/service-a/001')
    assert len(incoming) == 1
    record = incoming[0]
    assert record['consumer'] == 'stg/cde/service-b/002'
    assert record['key'] == 'desired.row.002-001.value' and record['property'] == 'ServiceB.Resource.Name'
    assert record['kind'] == 'typed' and record['format'] == 'name' and record['role'] == 'configuration'
    assert record['resolvedValue'] == 'same-name-stg' and record['status'] == 'resolved'
    assert record['sourceLocation']['file'] == 'model/templates/cde/service-b.properties.tpl'
    line = snapshot[tmp_path / record['sourceLocation']['file']].decode().splitlines()[record['sourceLocation']['line'] - 1]
    assert line == 'desired.row.name.value=<<Origin>>'
    assert incoming_references(tmp_path, 'stg/cde/service-a/003') == []  # Same name, different fixed ID.
    reverse = outgoing_references(tmp_path, 'stg/cde/service-a/001')
    assert len(reverse) == 1 and reverse[0]['producer'] == 'stg/cde/service-b/002'
    assert all(p.read_bytes() == data for p, data in snapshot.items())
    with pytest.raises(ValueError, match='unknown Resource'):
        incoming_references(tmp_path, 'stg/cde/service-a/999')


@pytest.mark.parametrize('selected', [False, True])
def check_reference_active_shapes_and_documents(tmp_path, selected):
    import yaml
    from support.import_model_fixtures import dependency_fixture, spec
    from model_reference_usage import outgoing_references
    dependency_fixture(tmp_path)
    path = tmp_path / 'model/templates/cde/service-b.properties.tpl'
    text = path.read_text().replace('# definition: Consumer\n', '# definition: Consumer\n# parameter: Select ' + json.dumps(spec('boolean')) + '\n')
    text = text.replace('desired.row.name.value=<<Origin>>',
        'desired.row.name.value=same-name-stg\n# choice: desired.row.name.value {"parameter":"Select","value":"<<Origin>>"}')
    # A display link remains a distinct usage; identical ordinary text is not a reference.
    text = text.replace('display.resource.resource.comment=合成テスト用のリソース',
                        'display.resource.resource.comment=説明 [producer](./service-a.md#producer) same-name-stg')
    text += '\n# definition: Unused\n# reference: Missing {"service":"unknown","resource":"999","resourceType":"Other.Resource"}\ndesired.note.099.text=<<Missing>>\n# end-definition\n'
    path.write_text(text)
    for env in ('dev', 'stg'):
        inputs = tmp_path / 'model/parameters' / env / 'cde/service-b/parameters.yaml'
        value = yaml_read(inputs.read_text())
        value['instances']['consumer']['parameters']['Select'] = selected
        if not selected:
            del value['instances']['consumer']['parameters']['Origin']
        inputs.write_text(yaml.safe_dump(value))
    references = outgoing_references(tmp_path, 'stg/cde/service-b/002')
    assert len(references) == (2 if selected else 1)
    assert sum(item['role'] == 'display' for item in references) == 1
    if selected:
        named = next(item for item in references if item['format'] == 'name')
        assert path.read_text().splitlines()[named['sourceLocation']['line'] - 1].startswith('# choice:')
    # Document shape uses the same resolver and escaped RFC 6901 positions.
    text = path.read_text().replace('desired.row.name.comment=合成テストの取得設定',
        'desired.row.name.comment=合成テストの取得設定\ndesired.row.name.document={"a/b":["drop","<<Origin>>"],"unused":"<<Missing>>"}\n'
        '# parameter: Missing ' + json.dumps(spec('reference', service='missing', resourceType='Other.Resource')) + '\n'
        '# optional-json: desired.row.name.document /unused Keep\n'
        '# optional-json: desired.row.name.document /a~1b/0 Keep\n'
        '# choice: desired.row.name.document {"parameter":"Select","pointer":"/a~1b/1","value":"<<Origin>>"}\n'
        '# parameter: Keep ' + json.dumps(spec('boolean')))
    path.write_text(text)
    for env in ('dev', 'stg'):
        inputs = tmp_path / 'model/parameters' / env / 'cde/service-b/parameters.yaml'
        value = yaml_read(inputs.read_text())
        value['instances']['consumer']['parameters'].update(Origin='001', Keep=False)
        inputs.write_text(yaml.safe_dump(value))
    references = outgoing_references(tmp_path, 'stg/cde/service-b/002')
    document = [item for item in references if item['pointer'] is not None]
    assert len(document) == 1 and document[0]['pointer'] == '/a~1b/0'
    assert document[0]['resolvedValue'] == 'same-name-stg'
    location = path.read_text().splitlines()[document[0]['sourceLocation']['line'] - 1]
    assert location.startswith('# choice:' if selected else 'desired.row.name.document=')


@pytest.mark.parametrize('broken', ['unknown', 'cycle', 'link', 'missing-input'])
def check_reference_fail_closed(tmp_path, broken):
    import yaml
    from support.import_model_fixtures import dependency_fixture, spec
    from model_reference_usage import incoming_references
    dependency_fixture(tmp_path)
    path = tmp_path / 'model/parameters/stg/cde/service-b/parameters.yaml'
    if broken == 'unknown':
        path.write_text(path.read_text().replace("'001'", "'999'"))
    elif broken == 'missing-input':
        path.unlink()
    elif broken == 'link':
        template = tmp_path / 'model/templates/cde/service-b.properties.tpl'
        template.write_text(template.read_text().replace('合成テスト用のリソース', '[missing](service-a.md#missing)'))
    else:
        template = tmp_path / 'model/templates/cde/service-a.properties.tpl'
        text = template.read_text().replace('# parameter: Name ' + json.dumps(spec(), ensure_ascii=False, separators=(',', ':')),
            '# parameter: Name ' + json.dumps(spec('reference', service='service-b', resourceType='ServiceB.Resource', format='name')))
        template.write_text(text)
        for env in ('dev', 'stg'):
            inputs = tmp_path / 'model/parameters' / env / 'cde/service-a/parameters.yaml'
            value = yaml_read(inputs.read_text())
            for item in value['instances'].values():
                item['parameters']['Name'] = '002'
            inputs.write_text(yaml.safe_dump(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        incoming_references(tmp_path, 'stg/cde/service-a/001')


def check_value_preserving_detach_and_single_deletions(tmp_path):
    import shutil
    import yaml
    from support.import_model_fixtures import dependency_fixture, dependency_refactor, dependency_contract, operation_contract
    from task_contract import model_refactor, model_operation
    from model_operation_checks import verify_model_refactor, verify_model_operation
    from model_reference_usage import incoming_references
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    sources = dependency_refactor(before, after)
    scope = {('stg', 'cde', 'service-b'), ('dev', 'cde', 'service-b')}
    verify_model_refactor(before, after, model_refactor(dependency_contract()), sources, scope)
    assert incoming_references(after, 'stg/cde/service-a/001') == []
    assert incoming_references(after, 'dev/cde/service-a/001')
    previous = after
    for service, rid, instance in [('service-a', '001', 'producer'), ('service-b', '002', 'consumer')]:
        candidate = tmp_path / service
        shutil.copytree(previous, candidate)
        directory = candidate / 'model/parameters/stg/cde' / service
        parameters, bindings = directory / 'parameters.yaml', directory / 'bindings.json'
        inputs, bound = yaml_read(parameters.read_text()), json.loads(bindings.read_text())
        del inputs['instances'][instance]; del bound['instances'][instance]
        parameters.write_text(yaml.safe_dump(inputs)); bindings.write_text(json.dumps(bound))
        operation = model_operation(operation_contract('import-delete', source='stg/cde/' + service + '/' + rid))
        changed = {p.relative_to(candidate).as_posix() for p in (parameters, bindings)}
        verify_model_operation(previous, candidate, operation, changed)
        previous = candidate


@pytest.mark.parametrize('corrupt', ['property', 'mode', 'anchor', 'observed', 'foreign', 'identity-reference', 'scope', 'retained', 'create', 'undeclared'])
def check_refactor_rejects_changes(tmp_path, corrupt):
    import yaml
    from support.import_model_fixtures import dependency_fixture, dependency_refactor, dependency_contract
    from task_contract import model_refactor
    from model_operation_checks import verify_model_refactor
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    sources = dependency_refactor(before, after)
    scope = {('stg', 'cde', 'service-b'), ('dev', 'cde', 'service-b')}
    parameters = after / 'model/parameters/stg/cde/service-b/parameters.yaml'
    if corrupt == 'property':
        parameters.write_text(parameters.read_text().replace('same-name-stg', 'changed'))
    elif corrupt == 'mode':
        parameters.write_text(parameters.read_text().replace('IMPORT', 'CREATE'))
    elif corrupt == 'anchor':
        file = parameters.with_name('bindings.json')
        file.write_text(file.read_text().replace('"Anchor": "consumer"', '"Anchor": "changed"'))
    elif corrupt == 'observed':
        file = parameters.with_name('observed.json')
        file.write_text(json.dumps({'version': 1, 'values': {'observed.row.002-001.value': 'changed'}}))
        sources.add(file.relative_to(after).as_posix())
    elif corrupt == 'foreign':
        file = after / 'model/parameters/dev/cde/service-a/parameters.yaml'
        file.write_text(file.read_text().replace('same-name-dev', 'changed'))
    elif corrupt == 'identity-reference':
        file = after / 'model/parameters/dev/cde/service-b/parameters.yaml'
        file.write_text(file.read_text().replace("'001'", "'003'"))
    elif corrupt == 'scope':
        scope.remove(('dev', 'cde', 'service-b'))
    elif corrupt == 'retained':
        for name in ('parameters.yaml', 'bindings.json'):
            file = parameters.with_name(name)
            file.write_bytes((before / file.relative_to(after)).read_bytes())
    elif corrupt == 'create':
        file = before / parameters.relative_to(after)
        file.write_text(file.read_text().replace('IMPORT', 'CREATE'))
        parameters.write_text(parameters.read_text().replace('IMPORT', 'CREATE'))
    else:
        file = after / 'model/parameters/dev/cde/service-b/parameters.yaml'
        value = yaml_read(file.read_text())
        value['instances']['consumer']['parameters'] = {'Name': 'same-name-dev', 'ResourceMode': 'IMPORT'}
        file.write_text(yaml.safe_dump(value))
        file = file.with_name('bindings.json')
        file.write_text(file.read_text().replace('Consumer', 'Detached'))
    with pytest.raises(ValueError):
        verify_model_refactor(before, after, model_refactor(dependency_contract()), sources, scope)


def check_reference_readonly_and_bounded_expansion(tmp_path, monkeypatch):
    import hashlib
    from support.import_model_fixtures import dependency_fixture
    from model_reference_usage import incoming_references, outgoing_references
    import model_reference_usage as usage
    import model_sources
    dependency_fixture(tmp_path)
    # A broken unrelated environment cannot affect this target's read-only answer.
    foreign = tmp_path / 'model/parameters/dev/cde/service-b/parameters.yaml'
    foreign.write_text('invalid: [')
    calls = []
    load = usage.load_expansion
    def expand(path):
        calls.append(path.relative_to(tmp_path).as_posix())
        return load(path)
    monkeypatch.setattr(usage, 'load_expansion', expand)
    assert outgoing_references(tmp_path, 'stg/cde/service-b/002')
    assert calls == ['model/stg/cde/service-b.properties']
    calls.clear()
    assert incoming_references(tmp_path, 'stg/cde/service-a/001')
    assert calls == ['model/stg/cde/service-a.properties', 'model/stg/cde/service-b.properties']
    # The API refuses recovery, rather than writing a pending transaction's Model.
    temporary = tmp_path / 'temporary'
    temporary.mkdir()
    monkeypatch.setattr(model_sources.tempfile, 'gettempdir', lambda: str(temporary))
    journal = temporary / 'blueprint-model-publication' / (hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest() + '.json')
    journal.parent.mkdir()
    journal.write_text('pending recovery')
    before = {p: p.read_bytes() for p in (tmp_path / 'model').rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='read-only analysis stopped'):
        incoming_references(tmp_path, 'stg/cde/service-a/001')
    assert journal.read_text() == 'pending recovery'
    assert all(p.read_bytes() == data for p, data in before.items())


def check_reference_structural_and_remaining_delete(tmp_path):
    import shutil
    import yaml
    from support.import_model_fixtures import dependency_fixture, dependency_contract, operation_contract
    from model_reference_usage import outgoing_references
    from model_operation_checks import verify_model_refactor, verify_model_operation
    from task_contract import model_refactor, model_operation
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    template = before / 'model/templates/cde/service-a.properties.tpl'
    template.write_text(template.read_text().replace('# definition: Producer\n',
        '# definition: Producer\ndesired.resource.resource.parentReference=[other](#other-producer)\n'))
    refs = outgoing_references(before, 'stg/cde/service-a/001')
    structural = next(item for item in refs if item['role'] == 'structure')
    assert structural['producer'] == 'stg/cde/service-a/003' and structural['kind'] == 'link'
    shutil.copytree(before, after)
    file = after / template.relative_to(before)
    file.write_text(file.read_text().replace('desired.resource.resource.parentReference=[other](#other-producer)\n', ''))
    text = dependency_contract().replace('service-b/002', 'service-a/001').replace('service-a/001", "key"', 'service-a/003", "key"').replace('desired.row.002-001.value', 'desired.resource.001.parentReference')
    with pytest.raises(ValueError, match='structure changed|structural metadata'):
        verify_model_refactor(before, after, model_refactor(text), {file.relative_to(after).as_posix()}, {('stg', 'cde', 'service-a'), ('dev', 'cde', 'service-a')})
    # Existing single-delete rejects an actual surviving name reference.
    directory = after / 'model/parameters/stg/cde/service-a'
    for filename in ('parameters.yaml', 'bindings.json'):
        file = directory / filename
        payload = yaml_read(file.read_text()) if filename.endswith('.yaml') else json.loads(file.read_text())
        del payload['instances']['producer']
        file.write_text(yaml.safe_dump(payload) if filename.endswith('.yaml') else json.dumps(payload))
    with pytest.raises(ValueError):
        verify_model_operation(before, after, model_operation(operation_contract('import-delete', source='stg/cde/service-a/001')),
                               {p.relative_to(after).as_posix() for p in directory.iterdir()})


def check_dependency_json_types_and_exact_detach(tmp_path):
    import shutil
    from support.import_model_fixtures import dependency_fixture, dependency_refactor, dependency_contract
    from task_contract import model_refactor
    from model_operation_checks import verify_model_refactor
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    template = before / 'model/templates/cde/service-b.properties.tpl'
    template.write_text(template.read_text().replace('desired.row.name.comment=',
        'desired.row.name.document={"ref":"<<Origin>>","keep":"<<Origin>>","typed":1}\ndesired.row.name.comment='))
    sources = dependency_refactor(before, after)
    file = after / template.relative_to(before)
    # Retain one exact reference, detach Name and /ref only through an explicit choice of input.
    text = file.read_text().replace('# definition: Detached\n',
        '# definition: Detached\n# reference: Retained {"service":"service-a","resource":"001","resourceType":"ServiceA.Resource","format":"name"}\n')
    text = text.replace('desired.row.name.value=<<Name>>',
        'desired.row.name.value=<<Name>>\ndesired.row.name.document={"ref":"<<Name>>","keep":"<<Retained>>","typed":1}')
    file.write_text(text)
    declaration = {'consumer': 'stg/cde/service-b/002', 'producer': 'stg/cde/service-a/001', 'key': 'desired.row.002-001.document', 'pointer': '/ref'}
    contract = dependency_contract() + '- ' + json.dumps(declaration) + '\n'
    scope = {('stg', 'cde', 'service-b'), ('dev', 'cde', 'service-b')}
    verify_model_refactor(before, after, model_refactor(contract), sources, scope)
    with pytest.raises(ValueError, match='undeclared'):
        verify_model_refactor(before, after, model_refactor(dependency_contract()), sources, scope)
    file.write_text(text.replace('"typed":1}', '"typed":true}'))
    with pytest.raises(ValueError, match='value/type changed'):
        verify_model_refactor(before, after, model_refactor(contract), sources, scope)
    file.write_text(text.replace('"typed":1}', '"typed":1.0}'))
    with pytest.raises(ValueError, match='value/type changed'):
        verify_model_refactor(before, after, model_refactor(contract), sources, scope)
    # Escaped NULs in source JSON cannot impersonate in-memory reference markers.
    file.write_text(text.replace('"typed":1}', '"typed":"\\u0000reference0\\u0000"}'))
    from model_reference_usage import outgoing_references
    with pytest.raises(ValueError, match='reserved control character'):
        outgoing_references(after, 'stg/cde/service-b/002')


def check_reference_embedded_link_label(tmp_path):
    from support.import_model_fixtures import dependency_fixture
    from model_reference_usage import outgoing_references
    dependency_fixture(tmp_path)
    template = tmp_path / 'model/templates/cde/service-b.properties.tpl'
    template.write_text(template.read_text().replace('display.resource.resource.comment=合成テスト用のリソース',
        'display.resource.resource.comment=[<<Origin>>](service-a.md#other-producer)'))
    usages = outgoing_references(tmp_path, 'stg/cde/service-b/002')
    links = [item for item in usages if item['role'] == 'display']
    assert {(item['producer'], item['kind']) for item in links} == {
        ('stg/cde/service-a/001', 'typed'), ('stg/cde/service-a/003', 'link')}
    assert all(item['resolvedValue'] == '[same-name-stg](service-a.md#other-producer)' for item in links)

def check_publication_verifies_only_acquisition_selected_additions():
    from unittest.mock import Mock
    before = expansion(resource())
    after = expansion({**before.values, **resource('009', identity='vpc-new')})
    references = Mock()
    verify_values(before, after, {'009': record('vpc-new', cidr='10.10.0.0/23')}, schema_for, references)
    assert references.verify_resource.call_count == 1
    assert references.verify_resource.call_args.args[1] == '009'



def check_existing_hyphenated_fixed_id_cannot_receive_rows():
    original = resource('existing-vpc')
    addition = {'desired.row.existing-vpc-999.property': 'EC2.VPC.EnableDnsSupport',
                'desired.row.existing-vpc-999.value': '`true`', 'desired.row.existing-vpc-999.comment': '追加は禁止'}
    with pytest.raises(ValueError, match='cannot add fields, Rows or observations'):
        verify_values(expansion(original), expansion({**original, **addition}), {}, schema_for)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
