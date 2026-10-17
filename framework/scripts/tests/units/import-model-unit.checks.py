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
from import_sources import (candidate_sources, equivalent, parameter_edit, preserve_bindings,
                            property_values, selection_records, verify_values, typed_equal)
from import_promotion import changed_properties, property_value
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


def selection(record_id='record-1', rid='001', action='update', basis=()):
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
    assert not equivalent(None, 'value') and equivalent(None, None)


def check_physical_identity_wins_over_mutable_settings():
    old = resource()
    new = {**old, 'desired.row.001-002.value': '`10.11.0.0/23`'}
    chosen = selection_records(selection(), [record()], old, new, schema_for)
    changes = verify_values(expansion(old), expansion(new), chosen, schema_for)
    assert changes == [{'resource': '001', 'record': 'record-1', 'property': 'EC2.VPC.CidrBlock'}]
    assert not verify_values(expansion(old), expansion(old), chosen, schema_for)


@pytest.mark.parametrize('mutation, message', [
    (lambda new: new.update({'desired.row.001-002.value': '`10.99.0.0/23`'}), 'differs from the acquired'),
    (lambda new: new.update({'desired.resource.001.anchor': 'renamed'}), 'identity'),
    (lambda new: new.update({'desired.resource.001.logicalId': 'Renamed'}), 'identity'),
    (lambda new: new.update({'desired.resource.001.resourceMode': 'CREATE'}), 'identity'),
    (lambda new: new.update({'desired.row.001-001.value': '`vpc-confirmed`'}), 'logical references'),
    (lambda new: new.update({'observed.row.001-001.value': '`vpc-invented`'}), 'observation differs'),
    (lambda new: new.pop('desired.row.001-002.property'), 'Property changed'),
])
def check_invalid_candidates(mutation, message):
    old = resource()
    new = dict(old)
    mutation(new)
    with pytest.raises((ValueError, KeyError), match=message):
        verify_values(expansion(old), expansion(new), {'001': record()}, schema_for)


def check_unacquired_and_create_protection():
    old = resource()
    new = {**old, 'desired.row.001-002.value': '`10.11.0.0/23`'}
    unavailable = record()
    unavailable['properties']['EC2.VPC.CidrBlock'] = {'status': 'missing'}
    with pytest.raises(ValueError, match='unacquired'):
        verify_values(expansion(old), expansion(new), {'001': unavailable}, schema_for)
    with pytest.raises(ValueError, match='no selected acquisition'):
        verify_values(expansion(old), expansion(new), {}, schema_for)
    with pytest.raises(ValueError, match='CREATE'):
        selection_records(selection(), [record()], resource(mode='CREATE'), resource(mode='CREATE'), schema_for)
    with pytest.raises(ValueError, match='deleting an existing resource'):
        verify_values(expansion(old), expansion({}), {}, schema_for)


def check_correspondence_without_id_requires_multiple_unique_facts():
    old = resource(identity=None)
    captured = record(cidr='10.10.0.0/23')
    with pytest.raises(ValueError, match='multiple facts'):
        selection_records(selection(basis=['EC2.VPC.Name']), [captured], old, old, schema_for)
    picked = selection(basis=['EC2.VPC.Name', 'EC2.VPC.CidrBlock'])
    assert selection_records(picked, [captured], old, old, schema_for)['001'] == captured
    duplicate = record('vpc-other', '10.10.0.0/23', 'record-2')
    picked['excluded'] = [{'record': 'record-2', 'reason': 'out of scope'}]
    with pytest.raises(ValueError, match='ambiguous'):
        selection_records(picked, [captured, duplicate], old, old, schema_for)
    with pytest.raises(ValueError, match='physical identity'):
        selection_records(selection(), [record('vpc-other')], resource(), resource(), schema_for)


def check_subnet_parent_is_required():
    old = resource(kind='EC2.Subnet', identity=None)
    captured = record()
    captured.update(kind='EC2.Subnet', identityProperty='EC2.Subnet.SubnetId')
    captured['properties'] = {k.replace('EC2.VPC.', 'EC2.Subnet.'): v for k, v in captured['properties'].items()}
    with pytest.raises(ValueError, match='parent VPC'):
        selection_records(selection(basis=['EC2.Subnet.Name', 'EC2.Subnet.CidrBlock']), [captured], old, old, schema_for)


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
    with pytest.raises(ValueError, match='action'):
        selection_records(picked, [acquired], old, new, schema_for)
    with pytest.raises(ValueError, match='explicit disposition'):
        selection_records({'resources': [], 'excluded': [], 'unreflected': []}, [acquired], old, old, schema_for)
    assert selection_records({'resources': [], 'excluded': [], 'unreflected': [{'record': 'record-1', 'reason': 'ownership unknown'}]},
                             [acquired], old, old, schema_for) == {}


def check_binding_identity_and_addition():
    original = {'instances': {'main-vpc': {'definition': 'Vpc', 'resources': {'vpc': '001'}, 'rows': {'cidr': '001-001'}, 'parameters': {}}}}
    candidate = copy.deepcopy(original)
    candidate['instances']['new-subnet'] = {'definition': 'Subnet', 'resources': {'subnet': '009'}, 'rows': {}, 'parameters': {}}
    preserve_bindings(original, candidate, new_instances=True)
    with pytest.raises(ValueError, match='instances'):
        preserve_bindings(original, candidate)
    candidate = copy.deepcopy(original)
    candidate['instances']['main-vpc']['rows']['cidr'] = '001-099'
    with pytest.raises(ValueError, match='Row IDs'):
        preserve_bindings(original, candidate, new_instances=True)


def check_shared_property_typed_preservation():
    old = definition()
    spec = {'type': 'boolean', 'required': True, 'description': 'DNS support'}
    new = definition('<<EnableDnsSupport>>', {'EnableDnsSupport': spec})
    assert changed_properties({'Vpc': old}, {'Vpc': new}) == {'Vpc': {'desired.row.dns.value'}}
    binding = {'resources': {'vpc': '001'}, 'rows': {'dns': '001-001'}, 'parameters': {}}
    params = {'instances': {'main': {'parameters': {'EnableDnsSupport': False}}}}
    assert equivalent(property_value(old, 'desired.row.dns.value', {'instances': {}}, binding, 'main', 'stg'),
                      property_value(new, 'desired.row.dns.value', params, binding, 'main', 'stg'))
    params['instances']['main']['parameters']['EnableDnsSupport'] = 'false'
    with pytest.raises(ValueError, match='type'):
        property_value(new, 'desired.row.dns.value', params, binding, 'main', 'stg')


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
        candidate_sources(root, stage, ('dev', 'cde', 'vpc'), {('dev', 'cde', 'vpc')})
    candidate.write_text('# added\ninstances: {}\n', encoding='utf-8')
    assert set(candidate_sources(root, stage, ('dev', 'cde', 'vpc'), {('dev', 'cde', 'vpc')})) == {original}
    (stage / 'project.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='outside'):
        candidate_sources(root, stage, ('dev', 'cde', 'vpc'), {('dev', 'cde', 'vpc')})


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
    assert not typed_equal(False, 0) and not equivalent(False, 0)
    old = {'desired.resource.001.resourceType': 'SecurityHub.Hub',
           'desired.resource.001.resourceMode': 'IMPORT'}
    captured = {'record': 'hub', 'kind': 'SecurityHub.Hub', 'identity': 'confirmed-hub',
                'identityProperty': None, 'properties': {}}
    picked = selection('hub', basis=['$scope'])
    assert selection_records(picked, [captured], old, old, schema_for) == {'001': captured}
    with pytest.raises(ValueError, match='ambiguous'):
        selection_records(picked, [captured, {**captured, 'record': 'another'}], old, old, schema_for)


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
    from import_promotion import preserve_consumers
    build_seed(tmp_path)
    for service in SERVICES:
        assert load_for_edit(tmp_path / 'model/dev/cde' / (service + '.properties')).values
    path = tmp_path / 'model/dev/cde/cloudwatch-logs.properties'
    before = load_for_edit(path)
    template = tmp_path / 'model/templates/cde/cloudwatch-logs.properties.tpl'
    text = template.read_text().replace('# definition: LogGroup\n',
        '# definition: LogGroup\n# parameter: Protection ' + json_text(spec('boolean')) + '\n')
    text = text.replace('desired.row.protected.value=`false`', 'desired.row.protected.value=<<Protection>>')
    text = text.replace('# row: protected resource', '# row: protection resource').replace('desired.row.protected.', 'desired.row.protection.')
    output = {template: text}
    direct = {('dev', 'cde', 'cloudwatch-logs'), ('stg', 'cde', 'cloudwatch-logs')}
    for environment in ('dev', 'stg'):
        directory = tmp_path / 'model/parameters' / environment / 'cde/cloudwatch-logs'
        file = directory / 'parameters.yaml'
        params = yaml_read(file.read_text())
        for instance in params['instances'].values():
            instance['parameters']['Protection'] = False
        output[file] = parameter_edit(file.read_text(), params)
        file = directory / 'bindings.json'
        bindings = json.loads(file.read_text())
        for binding in bindings['instances'].values():
            if 'protected' in binding['rows']:
                binding['rows']['protection'] = binding['rows'].pop('protected')
        output[file] = json_text(bindings)
    snapshots, preserved, changed = preserve_consumers(path, before, output, direct)
    assert preserved == {('stg', 'cde', 'cloudwatch-logs')} and len(snapshots) == 2
    assert 'LogGroup' in changed
    current = load_for_edit(path, output).values
    assert current.keys() == before.values.keys()
    assert all(equivalent(current[k], v) for k, v in before.values.items())
    stg = tmp_path / 'model/parameters/stg/cde/cloudwatch-logs/parameters.yaml'
    output[stg] = output[stg].replace('Protection: false', 'Protection: true', 1)
    with pytest.raises(ValueError, match='meaning changed'):
        preserve_consumers(path, before, output, direct)

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
