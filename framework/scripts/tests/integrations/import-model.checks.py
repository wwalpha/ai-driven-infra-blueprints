#!/usr/bin/env python3
"""Offline acquire/edit/publish integration. Run through tests/run_it.py in CI."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import json
import socket
import subprocess
from unittest.mock import patch

import pytest
import import_guard
import sync_files
import sync_runtime
from import_sources import parameter_edit
from model_core import entries
from model_parameter_inputs import yaml_read
from model_templates import json_text, load_for_edit
from support.import_model_fixtures import (ACCOUNT, TARGET, SERVICES, SUBNETS, VPC_ID, AwsCli,
    aws, correspondence, exclusions, fixture, logs_edit, m, publish_fixture, snapshot, spec, stage)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', 'tasks/import-fixture.md')
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('live network forbidden')))


def prepare(tmp_path, service='cloudwatch-logs', changed=True, dry_run=False):
    root = tmp_path / 'case'
    fixture(root, service, register=not dry_run)
    cli = aws(service, changed=changed)
    acquisition = m.acquire(root, 'dev', service, TARGET, dry_run, cli)
    return root, acquisition, cli


def input_file(root, service='cloudwatch-logs', env='dev', name='parameters.yaml'):
    return root / 'model/parameters' / env / TARGET / service / name


def source_files(root):
    return {p.relative_to(root): p.read_bytes() for p in (root / 'model').rglob('*') if p.is_file()}


def promote_logs(root, acquisition):
    files = logs_edit(root, acquisition)
    template = root / 'model/templates/cde/cloudwatch-logs.properties.tpl'
    text = template.read_text(encoding='utf-8').replace('# definition: LogGroup\n',
        '# definition: LogGroup\n# parameter: LogClass ' + json_text(spec(required=False, default='STANDARD')) + '\n')
    files[template.relative_to(root).as_posix()] = text.replace('desired.row.class.value=`STANDARD`', 'desired.row.class.value=`<<LogClass>>`')
    path = input_file(root).relative_to(root).as_posix()
    params = yaml_read(files[path])
    params['instances']['managed-log']['parameters']['LogClass'] = 'INFREQUENT_ACCESS'
    files[path] = parameter_edit(files[path], params)
    selected = [correspondence(acquisition, 'managed-new')]
    stage(acquisition, files, selected, exclusions(acquisition, selected))
    return files


def check_cli_preflight(tmp_path):
    for args in [[], ['--environment', 'dev'], ['--service', 'vpc'], ['--environment', 'dev', '--service', 'vpc']]:
        command = [sys.executable, '-B', str(m.ROOT / 'framework/scripts/import-model.py'), *args]
        assert subprocess.run(command, capture_output=True).returncode == 2
    assert not any(hasattr(m, name) for name in ('refresh', 'snapshot_values', 'snapshot_sources', 'promoted_sources'))


def check_logs_roundtrip(tmp_path):
    root, acquired, cli = prepare(tmp_path)
    before = load_for_edit(root / 'model/dev/cde/cloudwatch-logs.properties')
    files = logs_edit(root, acquired)
    result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['markdown'] == 'generated' and result['status'] == 'complete'
    assert cli.calls == [('sts', 'get-caller-identity', {}), ('logs', 'describe-log-groups', {})]
    assert not (root / '.blueprint').exists()
    after = load_for_edit(root / 'model/dev/cde/cloudwatch-logs.properties')
    assert after.values['desired.row.003-002.value'] == '90'
    assert all(after.values[k] == v for k, v in before.values.items())
    assert {k: v for k, v in before.values.items() if '.002' in k} == {k: v for k, v in after.values.items() if '.002' in k}
    assert len(files) == 2 and not Path(acquired['evidence']).parent.exists()
    import_guard.require_import_changes(root)


def check_config_sources(tmp_path):
    root, acquired, _ = prepare(tmp_path, 'config', changed=False)
    stage(acquired, {}, excluded=exclusions(acquired, []))
    result = publish_fixture(root, acquired, 'config')
    assert result['model'] == 'unchanged'
    assert 'AWSServiceRoleForConfig' in load_for_edit(root / 'model/dev/cde/config.properties').values['desired.row.001-007.value']
    assert result['unreflected'] == []


def check_vpc_eight_instances(tmp_path):
    root = tmp_path / 'case'
    path = fixture(root, 'vpc')
    before = source_files(root)
    acquired = m.acquire(root, 'dev', 'vpc', TARGET, cli_runner=aws('vpc', noise=True))
    stage(acquired, {}, excluded=exclusions(acquired, []))
    result = publish_fixture(root, acquired, 'vpc')
    assert result['model'] == 'unchanged' and source_files(root) == before
    bindings = json.loads(input_file(root, 'vpc', name='bindings.json').read_text(encoding='utf-8'))
    assert set(bindings['instances']) == {'service', 'main-vpc', *(name for name, _, _ in SUBNETS)}
    assert len(entries(load_for_edit(path).values, 'desired.resource.')) == 8
    assert result['resources']['excluded'] == 10


def check_quicksight_normalization(tmp_path):
    root, acquired, cli = prepare(tmp_path, 'quicksight', changed=False)
    assert all(r['kind'] == 'QuickSight.DataSource' for r in acquired['records'])
    for record in acquired['records']:
        assert record['properties']['QuickSight.DataSource.Name']['value'] == record['identity']
        assert 'getters' not in record
    assert all(inputs.get('AwsAccountId') == ACCOUNT for service, _, inputs in cli.calls if service == 'quicksight')
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_registry_services(tmp_path):
    # Acquisition/normalization once per adapter; do not duplicate seven publish E2Es.
    root = tmp_path / 'case'
    fixture(root, register=False)
    for service in SERVICES:
        cli = aws(service)
        acquired = m.acquire(root, 'dev', service, TARGET, True, cli)
        assert acquired['records'] and acquired['sts'] == {'account': ACCOUNT, 'verified': True}
        assert cli.calls[0] == ('sts', 'get-caller-identity', {})
        assert all('properties' in record and 'getters' not in record for record in acquired['records'])
        import_guard.discard_acquisition(root, acquired['evidence'])


@pytest.mark.parametrize('kind,unknown', [('subnet', False), ('vpc', False), ('vpc', True)])
def check_managed_resource_addition(tmp_path, kind, unknown):
    root = tmp_path / 'case'
    path = fixture(root, 'vpc')
    observed_file = input_file(root, 'vpc', name='observed.json')
    observed = json.loads(observed_file.read_text(encoding='utf-8'))
    if unknown:
        observed['values'].pop('observed.row.001-001.value')
        observed_file.write_text(json_text(observed), encoding='utf-8')
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'unobserved fixture'], cwd=root, check=True)
    original = load_for_edit(path)
    foreign = {p: p.read_bytes() for p in (root / 'model/parameters').rglob('*') if p.is_file() and not p.is_relative_to(observed_file.parent)}
    old_bindings = json.loads(input_file(root, 'vpc', name='bindings.json').read_text(encoding='utf-8'))
    cli = aws('vpc', changed=True)
    if kind == 'subnet':
        instance, seed_name, identity = 'audit-private-1a', 'dat-private-1a', 'subnet-managed-new'
        cli.responses['ec2', 'describe-subnets']['Subnets'].append({'SubnetId': identity, 'VpcId': VPC_ID,
            'CidrBlock': '10.11.0.0/26', 'AvailabilityZone': 'ap-northeast-1a', 'MapPublicIpOnLaunch': False,
            'Tags': [{'Key': 'Name', 'Value': instance}]})
        settings = {'CidrBlock': '10.11.0.0/26', 'SubnetName': instance}
    else:
        instance, seed_name, identity = 'new-vpc', 'main-vpc', 'vpc-managed-new'
        cli.responses['ec2', 'describe-vpcs']['Vpcs'].append({'VpcId': identity, 'CidrBlock': '10.11.0.0/23',
            'Tags': [{'Key': 'Name', 'Value': 'main-vpc'}]})
        settings = {'CidrBlock': '10.11.0.0/23'}
    acquired = m.acquire(root, 'dev', 'vpc', TARGET, cli_runner=cli)
    parameters_file = input_file(root, 'vpc')
    params = yaml_read(parameters_file.read_text(encoding='utf-8'))
    params['instances'][instance] = {'parameters': settings}
    bindings = copy.deepcopy(old_bindings)
    seed = bindings['instances'][seed_name]
    bindings['instances'][instance] = {'definition': seed['definition'], 'resources': {'resource': '009'},
        'rows': {local: '009-' + rid.rsplit('-', 1)[1] for local, rid in seed['rows'].items()}, 'parameters': {'Anchor': 'vpc-' + instance}}
    observed['values']['observed.row.009-001.value'] = identity
    if kind == 'subnet':
        observed['values']['observed.row.009-002.value'] = VPC_ID
    selected = [correspondence(acquired, identity, '009')]
    stage(acquired, {parameters_file.relative_to(root).as_posix(): parameter_edit(parameters_file.read_text(encoding='utf-8'), params),
                    input_file(root, 'vpc', name='bindings.json').relative_to(root).as_posix(): json.dumps(bindings, indent=2) + '\n',
                    observed_file.relative_to(root).as_posix(): json.dumps(observed, indent=2) + '\n'}, selected, exclusions(acquired, selected))
    result = publish_fixture(root, acquired, 'vpc')
    assert result['status'] == 'complete' and result['model'] == 'reflected' and result['markdown'] == 'generated'
    assert result['resources']['added'] == 1 and 'updated' not in result['resources']
    assert bool(result['warnings']) == unknown
    current = load_for_edit(path)
    assert len(entries(current.values, 'desired.resource.')) == 9
    assert all(current.values[k] == v for k, v in original.values.items())
    assert current.values['observed.row.009-001.value'] == identity
    assert current.values['desired.row.009-001.value'] == '[009](#vpc-' + instance + ')'
    if kind == 'subnet':
        assert current.values['desired.row.009-002.value'] == '[001](#vpc-main)'
    saved = json.loads(input_file(root, 'vpc', name='bindings.json').read_text(encoding='utf-8'))
    assert all(saved['instances'][name] == item for name, item in old_bindings['instances'].items())
    assert all(p.read_bytes() == data for p, data in foreign.items())


@pytest.mark.parametrize('action', ['update', 'add'])
def check_existing_resource_selection_rejected(tmp_path, action):
    root, acquired, _ = prepare(tmp_path)
    selected = [correspondence(acquired, 'fixture-001', '001', action)]
    stage(acquired, {}, selected, exclusions(acquired, selected))
    before = snapshot(root)
    with pytest.raises(ValueError, match='add only'):
        publish_fixture(root, acquired)
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_optional_profile(tmp_path):
    root = tmp_path / 'case'
    fixture(root, register=False)
    target = json.loads((root / 'project.json').read_text(encoding='utf-8'))
    target['targets'][0].pop('awsProfile')
    (root / 'project.json').write_text(json_text(target), encoding='utf-8')
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, aws(profile=None))
    assert acquired['connection']['awsProfile'] is None
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_explicit_no_profile(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    cli = aws(profile=None)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli, no_profile=True)
    assert acquired['connection']['awsProfile'] is None
    assert cli.calls[0][0] == 'sts'
    logs_edit(root, acquired)
    assert publish_fixture(root, acquired)['model'] == 'reflected'


def check_single_acquisition(tmp_path):
    root, acquired, cli = prepare(tmp_path)
    logs_edit(root, acquired)
    with patch.object(m, 'import_context', side_effect=AssertionError('publish must not reacquire')):
        result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and len(cli.calls) == 2


def check_source_race(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    source = input_file(root)
    source.write_text(source.read_text(encoding='utf-8') + '# concurrent edit\n', encoding='utf-8')
    before = snapshot(root)
    with pytest.raises(ValueError, match='sources changed'):
        publish_fixture(root, acquired)
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_create_definition_reuse(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    before = json.loads(input_file(root, name='bindings.json').read_text())
    logs_edit(root, acquired)
    publish_fixture(root, acquired)
    after = json.loads(input_file(root, name='bindings.json').read_text())
    assert all(after['instances'][k] == v for k, v in before['instances'].items())
    assert after['instances']['managed-log']['definition'] == before['instances']['application-log']['definition']
    assert 'Import_' not in (root / 'model/templates/cde/cloudwatch-logs.properties.tpl').read_text(encoding='utf-8')


def check_cli_faults(tmp_path):
    root = tmp_path / 'case'
    fixture(root, register=False)
    for cli, code in [(AwsCli(account='999999999999'), 'AccountMismatch'),
                      (AwsCli(fail='An error occurred (AccessDenied) when calling STS: PRIVATE-CREDENTIAL'), 'AccessDenied')]:
        before = snapshot(root)
        with pytest.raises(m.comparator().AcquisitionError, match=code):
            m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, cli)
        assert snapshot(root) == before and len(cli.calls) == 1
    for payload in ({}, {'logGroups': None}, {'logGroups': 'invalid'}):
        cli = aws()
        cli.responses['logs', 'describe-log-groups'] = payload
        with pytest.raises(m.comparator().AcquisitionError, match='InvalidInventoryResponse'):
            m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, cli)


def check_inventory_parent_references(tmp_path):
    root, acquired, _ = prepare(tmp_path, 'vpc', changed=False)
    records = {r['identity']: r for r in acquired['records']}
    assert len(records) == 8
    assert all(records['subnet-' + str(n).zfill(17)]['properties']['EC2.Subnet.VpcId']['value'] == VPC_ID for n in range(2, 9))
    assert records[VPC_ID]['properties']['EC2.VPC.EnableDnsSupport']['value'] is True
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_exact_scope(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    stage(acquired, {'model/parameters/stg/cde/cloudwatch-logs/observed.json': '{"version":1,"values":{}}'})
    with pytest.raises(ValueError, match='outside'):
        publish_fixture(root, acquired)
    with pytest.raises(ValueError, match='scope'):
        m.publish_acquisition(root, 'dev', 'vpc', acquired['evidence'], TARGET)
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_external_reference_preservation(tmp_path):
    root = tmp_path / 'case'
    fixture(root, 'config')
    template = root / 'model/templates/cde/config.properties.tpl'
    text = template.read_text(encoding='utf-8').replace('`AWSServiceRoleForConfig`', '[role](iam.md#not-locally-resolved)')
    template.write_text(text, encoding='utf-8')
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'external reference fixture'], cwd=root, check=True)
    acquired = m.acquire(root, 'dev', 'config', TARGET, cli_runner=aws('config'))
    role = next(r for r in acquired['records'] if r['kind'] == 'Config.ConfigurationRecorder')['properties']['Config.ConfigurationRecorder.RoleARN']['value']
    stage(acquired, {'model/parameters/dev/cde/config/observed.json': json_text({'version': 1, 'values': {'observed.row.001-007.value': role}})}, excluded=exclusions(acquired, []))
    before = snapshot(root)
    with pytest.raises(ValueError, match='existing resource'):
        publish_fixture(root, acquired, 'config')
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])
    assert '[role](iam.md#not-locally-resolved)' in template.read_text(encoding='utf-8')
    assert not any('iam' == r['kind'] for r in acquired['records'])


def check_mapping_preservation(tmp_path):
    root, acquired, _ = prepare(tmp_path, 'config', changed=False)
    captured = next(r for r in acquired['records'] if r['kind'] == 'Config.ConfigurationRecorder')['properties']
    assert captured['Config.ConfigurationRecorder.RecordingGroup.AllSupported']['value'] is False
    assert captured['Config.ConfigurationRecorder.RecordingGroup.ResourceTypes']['value'] == ['AWS::EC2::VPC']
    assert 'Config.ConfigurationRecorder.RecordingMode.RecordingModeOverrides[].Description' not in captured
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_shared_property_and_bindings(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    cli = aws(changed=True)
    cli.logs[-1]['logGroupClass'] = 'INFREQUENT_ACCESS'
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
    stg_path = root / 'model/stg/cde/cloudwatch-logs.properties'
    from import_scope import read_consumers
    with read_consumers({('dev', TARGET, 'cloudwatch-logs'), ('stg', TARGET, 'cloudwatch-logs')}):
        stg_before = load_for_edit(stg_path).values
    foreign = {p: p.read_bytes() for p in (root / 'model/parameters/stg').rglob('*') if p.is_file()}
    promote_logs(root, acquired)
    result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['preservedConsumers'] == ['stg/cde/cloudwatch-logs']
    assert load_for_edit(stg_path).values == stg_before
    assert all(p.read_bytes() == data for p, data in foreign.items())
    assert not (root / 'docs/designs/stg').exists()
    assert not any('/stg/' in p for p in result['files'])


@pytest.mark.parametrize('relative', ['model/parameters/stg/cde/cloudwatch-logs/parameters.yaml',
    'model/parameters/stg/cde/cloudwatch-logs/bindings.json', 'model/parameters/stg/cde/cloudwatch-logs/observed.json',
    'model/parameters/dev/cde/vpc/parameters.yaml', 'model/templates/cde/vpc.properties.tpl'])
def check_foreign_source_writes_rejected(tmp_path, relative):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    source = root / relative
    text = source.read_text() if source.exists() else '{"version":1,"values":{}}'
    destination = Path(acquired['candidates']) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text + '\n')
    before = snapshot(root)
    with patch.object(m, 'publish', side_effect=AssertionError('must reject before saving')), pytest.raises(ValueError, match='outside'):
        publish_fixture(root, acquired)
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])


@pytest.mark.parametrize('service,scenario', [('cloudwatch-logs', 'duplicate'), ('cloudwatch-logs', 'new'),
                                               ('vpc', 'duplicate'), ('vpc', 'hide-observed')])
def check_add_identity_boundary(tmp_path, service, scenario):
    root = tmp_path / 'case'
    fixture(root, service)
    cli = aws(service, changed=True)
    acquired = m.acquire(root, 'dev', service, TARGET, cli_runner=cli)
    params_file, bindings_file = input_file(root, service), input_file(root, service, name='bindings.json')
    params = yaml_read(params_file.read_text(encoding='utf-8'))
    bindings = json.loads(bindings_file.read_text(encoding='utf-8'))
    instance = 'application-log' if service == 'cloudwatch-logs' else 'main-vpc'
    params['instances']['added'] = copy.deepcopy(params['instances'][instance])
    if service == 'cloudwatch-logs':
        params['instances']['added']['parameters'].update(LogGroupName='managed-new' if scenario == 'new' else 'fixture-001', RetentionDays=90)
    else:
        params['instances']['added']['parameters']['CidrBlock'] = '10.11.0.0/23'
    seed = bindings['instances'][instance]
    bindings['instances']['added'] = {**copy.deepcopy(seed), 'resources': {'resource': '009'},
        'rows': {local: number.replace('001-', '009-') for local, number in seed['rows'].items()}, 'parameters': {'Anchor': 'added'}}
    files = {params_file.relative_to(root).as_posix(): parameter_edit(params_file.read_text(encoding='utf-8'), params),
             bindings_file.relative_to(root).as_posix(): json_text(bindings)}
    if service == 'vpc':
        path = input_file(root, service, name='observed.json')
        observed = json.loads(path.read_text(encoding='utf-8'))
        observed['values']['observed.row.009-001.value'] = VPC_ID
        if scenario == 'hide-observed':
            observed['values'].pop('observed.row.001-001.value')
        files[path.relative_to(root).as_posix()] = json_text(observed)
    identity = 'managed-new' if scenario == 'new' else 'fixture-001' if service == 'cloudwatch-logs' else VPC_ID
    selected = [correspondence(acquired, identity, '009', 'add')]
    stage(acquired, files, selected, exclusions(acquired, selected))
    before = snapshot(root)
    if scenario == 'new':
        result = publish_fixture(root, acquired, service)
        assert result['status'] == 'complete' and result['resources']['added'] == 1
        assert 'added' in json.loads(bindings_file.read_text(encoding='utf-8'))['instances']
    else:
        with patch.object(m, 'record_import', side_effect=AssertionError('must reject before recording')), \
             patch.object(m, 'publish', side_effect=AssertionError('must reject before saving')), \
             patch.object(sync_runtime, 'view_plan', side_effect=AssertionError('must reject before display')), \
             pytest.raises(ValueError, match='009.*001'):
            publish_fixture(root, acquired, service)
        assert snapshot(root) == before
        assert not (Path(acquired['evidence']).parent / 'publication.json').exists()
        import_guard.discard_acquisition(root, acquired['evidence'])


def check_unacquired_property_rejection(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired, days=91)
    before = snapshot(root)
    with pytest.raises(ValueError, match='differs from the acquired'):
        publish_fixture(root, acquired)
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_repeat_without_reformat(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    publish_fixture(root, acquired)
    before = source_files(root)
    second = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=aws(changed=True))
    stage(second, {}, excluded=exclusions(second, []))
    result = publish_fixture(root, second)
    assert result['model'] == 'unchanged' and result['markdown'] == 'unchanged' and result['files'] == []
    assert source_files(root) == before


def check_fixed_identity_rejection(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    path = input_file(root, name='bindings.json')
    value = json.loads(path.read_text(encoding='utf-8'))
    value['instances']['application-log']['resources']['resource'] = '099'
    staged = Path(acquired['candidates']) / path.relative_to(root)
    staged.write_text(json_text(value), encoding='utf-8')
    with pytest.raises(ValueError):
        publish_fixture(root, acquired)
    assert json.loads(path.read_text(encoding='utf-8'))['instances']['application-log']['resources']['resource'] == '001'
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_empty_inventory_preserves_sources(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    cli = aws()
    cli.logs = []
    before = source_files(root)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
    assert acquired['records'] == []
    stage(acquired, {})
    result = publish_fixture(root, acquired)
    assert result['model'] == 'unchanged' and source_files(root) == before


def check_partial_reflection(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    files = logs_edit(root, acquired)
    selected = [correspondence(acquired, 'managed-new')]
    unresolved = next(r for r in acquired['records'] if r['identity'] == 'fixture-002')
    stage(acquired, files, selected, excluded=[item for item in exclusions(acquired, selected) if item['record'] != unresolved['record']], pending=[{'record': unresolved['record'], 'reason': 'ownership not confirmed'}])
    result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['status'] == 'incomplete' and result['unreflected']
    with pytest.raises(ValueError, match='incomplete'):
        import_guard.require_import_changes(root)


def check_native_types_preserved(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    files = logs_edit(root, acquired)
    path = next(iter(files))
    stage(acquired, {path: files[path].replace('RetentionDays: 90', 'RetentionDays: "90"')},
          [correspondence(acquired, 'managed-new')], exclusions(acquired, [correspondence(acquired, 'managed-new')]))
    with pytest.raises(ValueError, match='type'):
        publish_fixture(root, acquired)
    assert yaml_read(input_file(root).read_text(encoding='utf-8'))['instances']['application-log']['parameters']['RetentionDays'] == 30
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_consumer_set_race(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    cli = aws(changed=True)
    cli.logs[-1]['logGroupClass'] = 'INFREQUENT_ACCESS'
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
    promote_logs(root, acquired)
    new_consumer = root / 'model/parameters/prod/cde/cloudwatch-logs'
    new_consumer.mkdir(parents=True)
    with pytest.raises(ValueError, match='consumers changed'):
        publish_fixture(root, acquired)
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_source_transaction_rollback(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    cli = aws(changed=True)
    cli.logs[-1]['logGroupClass'] = 'INFREQUENT_ACCESS'
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
    promote_logs(root, acquired)
    original = source_files(root)
    real_save = sync_files.save_files
    def fail_after_first(output):
        selected = list(output.items())
        if any(path.is_relative_to(root / 'model') for path, _ in selected):
            path, text = selected[0]
            path.write_text(text, encoding='utf-8')
            raise OSError('synthetic interrupted source transaction')
        return real_save(output)
    with patch.object(sync_files, 'save_files', side_effect=fail_after_first), pytest.raises(OSError, match='synthetic'):
        publish_fixture(root, acquired)
    assert source_files(root) == original and not import_guard.proof_path(root).exists()
    assert publish_fixture(root, acquired)['model'] == 'reflected'


def check_yaml_candidate_edit(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    original = input_file(root).read_text(encoding='utf-8')
    files = logs_edit(root, acquired)
    publish_fixture(root, acquired)
    current = input_file(root).read_text(encoding='utf-8')
    assert current.startswith(original)
    assert 'managed-log:' in current and 'RetentionDays: 90' in current
    assert next(iter(files.values())) == current


def check_reflection_validation_boundary(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    with patch('import_guard.changes', side_effect=AssertionError('no whole Git Model comparison')), \
         patch('model_templates.load_expansion', side_effect=AssertionError('no design/reference validation')), \
         patch.object(m.comparator(), 'compare_resource', side_effect=AssertionError('no AWS comparison phase')):
        result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['designValidation'] == 'not-run'


def check_cross_process_evidence(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    scripts = m.ROOT / 'framework/scripts'
    setup = f"import sys; sys.path[:0] = [{str(scripts)!r}, {str(scripts / 'tests')!r}]; from pathlib import Path; from support.import_model_fixtures import m, aws; "
    acquire_code = setup + f"import json; print(json.dumps(m.acquire(Path({str(root)!r}), 'dev', 'cloudwatch-logs', 'cde', cli_runner=aws(changed=True))))"
    completed = subprocess.run([sys.executable, '-B', '-c', acquire_code], capture_output=True, text=True, encoding='utf-8', check=True)
    acquired = json.loads(completed.stdout)
    logs_edit(root, acquired)
    publish_code = setup + f"import json; print(json.dumps(m.publish_acquisition(Path({str(root)!r}), 'dev', 'cloudwatch-logs', Path({acquired['evidence']!r}), 'cde')))"
    result = subprocess.run([sys.executable, '-B', '-c', publish_code], capture_output=True, text=True, encoding='utf-8', check=True)
    report = json.loads(result.stdout)
    assert report['model'] == 'reflected' and report['markdown'] == 'generated'
    assert import_guard.read_proof(root)['complete']
    # The ignored completion receipt contains hashes, not captured configuration values.
    assert '"retentionInDays"' not in import_guard.proof_path(root).read_text(encoding='utf-8')


def check_dry_run_cleanup(tmp_path):
    root, acquired, _ = prepare(tmp_path, dry_run=True)
    before = snapshot(root)
    logs_edit(root, acquired)
    result = publish_fixture(root, acquired, dry_run=True)
    assert result['status'] == 'dry-run' and 'RetentionDays: 90' in result['diff']
    assert snapshot(root) == before and not Path(acquired['evidence']).parent.exists()
    assert not (root / 'tasks').exists() and not (root / '.blueprint/import').exists()
    second = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, aws(changed=True))
    logs_edit(root, second, 91)
    with pytest.raises(ValueError):
        publish_fixture(root, second, dry_run=True)
    assert not Path(second['evidence']).parent.exists()


def check_evidence_and_display_recovery(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    evidence = Path(acquired['evidence'])
    original = evidence.read_text(encoding='utf-8')
    envelope = json.loads(original)
    envelope['payload']['records'][0]['identity'] = 'fabricated'
    evidence.write_text(json_text(envelope), encoding='utf-8')
    with pytest.raises(ValueError, match='modified'):
        publish_fixture(root, acquired)
    evidence.write_text(original, encoding='utf-8')
    with patch.object(sync_runtime, 'generate_files', side_effect=ValueError('synthetic display failure')):
        result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['markdown'] == 'failed' and result['status'] == 'display-failed'
    before = source_files(root)
    with patch.object(m, 'import_context', side_effect=AssertionError('recovery must not acquire')):
        assert sync_runtime.sync(root, True, 'dev', TARGET, ['cloudwatch-logs']) == 0
    assert source_files(root) == before and import_guard.read_proof(root)['markdown'] == 'generated'
    assert not (root / '.blueprint').exists()



@pytest.mark.parametrize('failure', ['none', 'rollback', 'race', 'wrong-target', 'ordinary', 'ordinary-delete'])
def check_model_only_publication(tmp_path, monkeypatch, failure):
    from support.import_model_fixtures import operation_fixture, operation_candidate, operation_contract
    from model_templates import publish_edit, load_expansion
    from task_contract import start, complete
    from utils.aws_mappings import mapping_alias
    root, candidate, edited = tmp_path / 'repository', tmp_path / 'candidates', tmp_path / 'edited'
    operation_fixture(root)
    sources = operation_candidate(root, edited, 'import-delete' if failure == 'ordinary-delete' else 'import-merge')
    for name in sources:
        file = candidate / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes((edited / name).read_bytes())
    (root / '.gitignore').write_text('tasks/**\n')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'baseline'], cwd=root, check=True)
    selected = 'tasks/import-fixture.md'
    text = operation_contract(destination='stg/cde/vpc/008' if failure == 'wrong-target' else 'stg/cde/vpc/001')
    if failure in {'ordinary', 'ordinary-delete'}:
        text = '## Task contract\n- Task type: `design`\n- Task status: `running`\n'
    files = sources | {selected}
    for heading in ('Modified files', 'Allowed paths'):
        text += '\n## ' + heading + '\n' + ''.join('- `' + name + '`\n' for name in sorted(files))
    text += '\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n'
    start(root, selected, text)
    before = source_files(root)
    if failure == 'rollback':
        real_save = sync_files.save_files
        def fail_save(output):
            real_save(dict(list(output.items())[:1]))
            raise OSError('injected source publication failure')
        monkeypatch.setattr(sync_files, 'save_files', fail_save)
    elif failure == 'race':
        import import_promotion
        original = import_promotion.verify_model_operation
        def race(*args):
            original(*args)
            file = root / 'model/parameters/dev/cde/vpc/parameters.yaml'
            file.write_text(file.read_text() + '# concurrent human input\n')
        monkeypatch.setattr(import_promotion, 'verify_model_operation', race)
    with mapping_alias(m.ROOT, root):
        if failure != 'none':
            with pytest.raises((ValueError, OSError)):
                publish_edit(root, candidate)
            if failure != 'race':
                assert source_files(root) == before
            else:
                actual = source_files(root)
                altered = Path('model/parameters/dev/cde/vpc/parameters.yaml')
                assert actual.pop(altered) is not None
                assert actual == {k: v for k, v in before.items() if k != altered}
            return
        assert set(publish_edit(root, candidate)) == sources
        import_guard.require_import_changes(root)
        assert load_expansion(root / 'model/stg/cde/vpc.properties').values['observed.row.001-001.value'] == 'vpc-source'
        complete(root, selected)
        import_guard.require_import_changes(root)
    assert not (root / '.blueprint').exists()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
