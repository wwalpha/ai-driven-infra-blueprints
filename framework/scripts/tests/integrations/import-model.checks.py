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
    aws, correspondence, exclusions, fixture, logs_edit, m, publish_fixture, review_fixture, snapshot, spec, stage)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import import_approval
    # Exercise existing transactions below the unavailable trust boundary, never prove Human approval.
    monkeypatch.setattr(import_approval, 'require_human_approval', lambda: None)
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
    from model_templates import load_expansion
    path = root / 'model/dev/cde/cloudwatch-logs.properties'
    display = load_for_edit(path, display=True)
    normal = load_expansion(path)
    assert after.values['desired.row.003-001.value'] == 'managed-new'
    assert display.values['desired.row.003-001.value'] == normal.values['desired.row.003-001.value'] == '`managed-new`'
    assert '| LogGroupName | `managed-new` |' in (root / 'docs/designs/dev/cde/cloudwatch-logs.md').read_text()
    assert '``managed-new``' not in (root / 'docs/designs/dev/cde/cloudwatch-logs.md').read_text()

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
    values = load_for_edit(root / 'model/dev/cde/config.properties', display=True).values
    arn = 'arn:aws:iam::' + ACCOUNT + ':role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig'
    values = values | {'desired.resource.001.resourceMode': 'IMPORT', 'desired.row.001-007.value': arn}
    document = root / 'docs/designs/dev/cde/config.md'
    output = sync_runtime.generate_files(document, values, root)[document]
    assert '| RoleARN | ' + arn + ' |' in output
    assert '| RoleName | ' + arn + ' |' not in output



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
    identity_warnings = [w for w in result['warnings'] if 'existingResources' in w]
    assert bool(identity_warnings) == unknown, result['warnings']
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
        acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, cli)
        assert acquired['status'] == 'incomplete'
        assert acquired['inventory']['Logs.LogGroup'] == {'status': 'failed', 'reason': 'InvalidInventoryResponse'}
        assert acquired['records'] == []
        import_guard.discard_acquisition(root, acquired['evidence'])


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
    review_fixture(root, acquired)
    publish_code = setup + f"import json; print(json.dumps(m.publish_acquisition(Path({str(root)!r}), 'dev', 'cloudwatch-logs', Path({acquired['evidence']!r}), 'cde')))"
    rejected = subprocess.run([sys.executable, '-B', '-c', publish_code], capture_output=True, text=True, encoding='utf-8')
    assert rejected.returncode != 0 and 'Human approval unavailable' in rejected.stderr
    assert Path(acquired['evidence']).is_file()
    # Explicit synthetic seam for legacy cross-process receipt/rollback coverage only.
    publish_code = setup + 'import import_approval; import_approval.require_human_approval = lambda: None; ' + publish_code[len(setup):]
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
    evidence = Path(acquired['evidence'])
    path = root / 'model/dev/cde/cloudwatch-logs.properties'
    proposed = load_for_edit(path, m.candidate_sources(root, evidence.parent / 'candidates', ('dev', TARGET, 'cloudwatch-logs')))
    (evidence.parent / 'review-input.json').write_text(json_text({
        'proposedValues': proposed.values, 'risks': {r['record']: [] for r in acquired['records']}}))
    reviewed = m.review_acquisition(root, 'dev', 'cloudwatch-logs', evidence, TARGET, True)
    assert reviewed['model'] == 'unchanged' and snapshot(root) == before
    assert len(reviewed['review']['dispositions']) == len(acquired['records'])
    result = publish_fixture(root, acquired, dry_run=True)
    assert result['status'] == 'dry-run' and 'RetentionDays: 90' in result['diff']
    assert snapshot(root) == before and Path(acquired['evidence']).is_file()
    assert not (root / 'tasks').exists() and not (root / '.blueprint/import').exists()
    second = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, aws(changed=True))
    logs_edit(root, second, 91)
    with pytest.raises(ValueError):
        publish_fixture(root, second, dry_run=True)
    assert Path(second['evidence']).is_file()


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
    before = source_files(root)
    with patch.object(sync_runtime, 'generate_files', side_effect=ValueError('synthetic display failure')):
        with pytest.raises(ValueError, match='synthetic display failure'):
            publish_fixture(root, acquired)
    assert source_files(root) == before and evidence.is_file()
    publish = m.publish
    def fail_display(root, output, **kwargs):
        if any(p.is_relative_to(root / 'docs/designs') for p in output):
            raise OSError('synthetic display I/O failure')
        return publish(root, output, **kwargs)
    with patch.object(m, 'publish', side_effect=fail_display):
        result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['markdown'] == 'failed' and result['status'] == 'display-failed'
    assert evidence.is_file()
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
        import import_sources
        original = import_sources.candidate_sources
        def race(*args, **kwargs):
            output = original(*args, **kwargs)
            file = root / 'model/parameters/dev/cde/vpc/parameters.yaml'
            file.write_text(file.read_text() + '# concurrent human input\n')
            return output
        monkeypatch.setattr(import_sources, 'candidate_sources', race)
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



def check_partial_acquisition_cannot_complete(tmp_path):
    root = tmp_path / 'case'
    fixture(root, 'config')
    original = aws('config')
    def cli(command, **kwargs):
        if command[1:3] == ['configservice', 'describe-delivery-channels']:
            original.calls.append(('configservice', 'describe-delivery-channels', {}))
            return subprocess.CompletedProcess(command, 1, '', 'An error occurred (AccessDeniedException) when calling fixture: denied')
        return original(command, **kwargs)
    before = source_files(root)
    acquired = m.acquire(root, 'dev', 'config', TARGET, cli_runner=cli)
    assert acquired['status'] == 'incomplete' and acquired['records']
    assert acquired['inventory']['Config.DeliveryChannel']['status'] == 'permission_denied'
    sealed = import_guard.read_acquisition(root, Path(acquired['evidence']), ('dev', TARGET, 'config'), False)
    assert sealed['version'] == 2 and not import_guard.acquisition_complete(sealed)
    stage(acquired, {}, excluded=exclusions(acquired, []))
    count = len(original.calls)
    with patch.object(m, 'import_context', side_effect=AssertionError('publish cannot acquire')):
        result = publish_fixture(root, acquired, 'config')
    assert result['status'] == 'incomplete' and len(original.calls) == count
    assert source_files(root) == before and import_guard.read_proof(root)['complete'] is False


def check_generic_acquisition_roundtrip(tmp_path):
    from support.import_model_fixtures import small_framework, CloudControlCli
    from support.model_sources import write_model
    root = tmp_path / 'case'
    root.mkdir()
    small_framework(root, ['datazone'], ['DataZone.Domain'])
    path = root / 'model/dev' / ACCOUNT / 'datazone.properties'
    write_model(path, {'desired.service.datazone.serviceId': 'datazone',
                      'desired.service.datazone.ownedCatalogResourceTypes': 'DataZone.Domain',
                      'display.service.title': '# DataZone 詳細設計'})
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic DataZone'], cwd=root, check=True)
    cli = CloudControlCli({'DataZone.Domain': [{'identifier': 'dzd-fixture', 'properties': {'Id': 'dzd-fixture', 'Name': 'fixture', 'DomainVersion': 'V2', 'SingleSignOn': {'Type': 'DISABLED'}}}]})
    before = source_files(root)
    acquired = m.acquire(root, 'dev', 'datazone', ACCOUNT, True, cli, resource_types=['DataZone.Domain'])
    assert acquired['status'] == 'acquired' and len(acquired['records']) == 1
    assert acquired['records'][0]['identityComponents'] == [{'property': 'DataZone.Domain.Id', 'value': 'dzd-fixture'}]
    stage(acquired, {}, excluded=exclusions(acquired, []))
    count = len(cli.calls)
    with patch.object(m, 'import_context', side_effect=AssertionError('publish cannot acquire')):
        result = m.publish_acquisition(root, 'dev', 'datazone', acquired['evidence'], ACCOUNT, True)
    assert result['status'] == 'dry-run' and source_files(root) == before and len(cli.calls) == count


def check_intermediate_model_sources(monkeypatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    import base64
    from unittest.mock import patch
    from support.worktree_task_fixtures import fixture, git, start
    from support.import_model_fixtures import operation_fixture, operation_contract
    from import_guard import source_write_context
    from model_sources import read_sources, write_sources, publication_lock
    from model_templates import load_expansion
    import sync_files
    with fixture() as root:
        operation_fixture(root)
        git(root, 'add', 'model', 'project.json'); git(root, 'commit', '-qm', 'model sources')
        relative = 'model/parameters/stg/cde/vpc/parameters.yaml'
        target, state = start(root, files=(relative,))
        text = operation_contract() + '\n## Validation scope\n- `stg/cde/vpc`\n'
        for heading in ('Modified files', 'Allowed paths'):
            text += '\n## ' + heading + '\n- `' + state['task_file'] + '`\n- `' + relative + '`\n'
        (target / state['task_file']).write_text(text)
        logical = target / 'model/stg/cde/vpc.properties'
        path = target / relative
        original = path.read_bytes()
        with source_write_context(target, state['task_file']) as context:
            write_sources(context, {path: 'instances: {}\n'})
        assert read_sources(logical)[path] == 'instances: {}\n'
        try:
            load_expansion(logical)
            raise AssertionError('intermediate fixture unexpectedly expanded')
        except ValueError:
            pass
        with source_write_context(target, state['task_file']) as context:
            with patch.object(sync_files, 'save_files', side_effect=OSError('second leaf failed')):
                try:
                    write_sources(context, {path: original.decode()})
                    raise AssertionError('save failure was ignored')
                except OSError:
                    pass
        assert path.read_text() == 'instances: {}\n'
        assert (root / relative).read_bytes() == original
        with publication_lock(target) as journal:
            journal.write_text(json.dumps({'root': str(target.resolve()), 'originals': {relative: base64.b64encode(original).decode()}}))
            path.write_text('interrupted write')
        with source_write_context(target, state['task_file']) as context:
            assert context.snapshot.read(path) == original
            assert write_sources(context, {path: original.decode()}) == ()
        assert path.read_bytes() == original


def check_batch_leaf_saves(monkeypatch):
    import tempfile
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    import yaml
    from support.worktree_task_fixtures import fixture, git, start
    from support.import_model_fixtures import batch_operation_fixture
    from import_guard import source_write_context
    from model_sources import write_sources
    from model_operation_checks import verify_model_operation
    from model_templates import load_expansion
    from task_contract import model_operation
    with fixture() as root, tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary) / 'candidate'
        contract, sources = batch_operation_fixture(root, candidate)
        git(root, 'add', 'model', 'project.json'); git(root, 'commit', '-qm', 'batch Model fixture')
        target, state = start(root, files=tuple(sorted(sources)))
        for heading in ('Modified files', 'Allowed paths'):
            contract += '\n## ' + heading + '\n' + ''.join('- `' + name + '`\n' for name in sorted(sources | {state['task_file']}))
        contract += '\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n'
        (target / state['task_file']).write_text(contract)
        final = {target / name: (candidate / name).read_text() for name in sources}
        transfer = dict(final)
        directory = 'model/parameters/stg/cde/vpc/'
        operation = model_operation(contract)
        deleted = {pair.source.rsplit('/', 1)[1] for pair in operation.pairs}
        for filename, reader in [('parameters.yaml', yaml_read), ('bindings.json', json.loads), ('observed.json', json.loads)]:
            path = target / directory / filename
            before, after = reader(path.read_text()), reader(final[path])
            if filename == 'observed.json':
                after['values'].update({key: value for key, value in before['values'].items() if key.split('.')[2].rpartition('-')[0] in deleted})
            else:
                after['instances'].update({key: value for key, value in before['instances'].items() if key.startswith('imported-vpc')})
            transfer[path] = yaml.safe_dump(after) if filename.endswith('.yaml') else json.dumps(after)
        with source_write_context(target, state['task_file']) as context:
            write_sources(context, transfer)
        model = target / 'model/stg/cde/vpc.properties'
        for source in deleted:
            assert 'desired.resource.' + source + '.resourceType' in load_expansion(model).values
        with source_write_context(target, state['task_file']) as context:
            assert write_sources(context, {}) == ()  # This fixture has no declared retarget positions.
        for source in deleted:
            assert 'desired.resource.' + source + '.resourceType' in load_expansion(model).values
        with source_write_context(target, state['task_file']) as context:
            write_sources(context, final)
        for source in deleted:
            assert 'desired.resource.' + source + '.resourceType' not in load_expansion(model).values
        verify_model_operation(root, target, operation, sources)
        assert git(root, 'rev-parse', 'HEAD') == state['start']



@pytest.mark.parametrize('present,race', [(False, False), (True, False), (True, True)])
def check_reference_publication(tmp_path, present, race):
    from support.import_model_fixtures import CloudControlCli
    from support.model_sources import write_model
    from utils.aws_mappings import mapping_alias
    from task_contract import start
    root = tmp_path / 'reference-publication'
    root.mkdir()
    (root / 'project.json').write_text(json_text({'targets': [{'environment': 'dev', 'alias': TARGET,
        'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
    path = root / 'model/dev/cde/cloudtrail.properties'
    write_model(path, {'desired.service.cloudtrail.serviceId': 'cloudtrail',
        'desired.service.cloudtrail.ownedCatalogResourceTypes': 'CloudTrail.Trail', 'display.service.title': '# CloudTrail'})
    if present:
        write_model(root / 'model/dev/cde/s3.properties', {
            'desired.resource.001.resourceType': 'S3.Bucket', 'desired.resource.001.resourceMode': 'CREATE',
            'desired.resource.001.anchor': 's3-audit-bucket',
            'desired.row.001-001.property': 'S3.Bucket.BucketName', 'desired.row.001-001.value': '`audit-bucket`',
            'desired.row.001-001.comment': '合成Bucket'})
    for args in [('init', '-q'), ('add', '.'), ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'reference fixture')]:
        subprocess.run(['git', *args], cwd=root, check=True)
    directory = root / 'model/parameters/dev/cde/cloudtrail'
    template = root / 'model/templates/cde/cloudtrail.properties.tpl'
    files = {template, directory / 'parameters.yaml', directory / 'bindings.json', directory / 'observed.json', root / 'docs/designs/dev/cde/cloudtrail.md'}
    listed = ['- `' + p.relative_to(root).as_posix() + '`' for p in sorted(files)] + ['- `tasks/import-fixture.md`']
    text = '\n'.join(['# Reference fixture', '## Task contract', '- Task type: `design`', '- Task status: `running`',
        '- Workflow: `import`', '- IMPORT target: `dev/cde/cloudtrail`', '## Goal', 'Synthetic reference addition',
        '## Required changes', '- [R1] Add acquired resource', '## Acceptance checks', '- [R1] `exists:docs/designs/dev/cde/cloudtrail.md`',
        '## Validation scope', '- `dev/cde/cloudtrail`', '## Modified files', *listed, '## Allowed paths', *listed])
    start(root, 'tasks/import-fixture.md', text)
    cli = CloudControlCli({'CloudTrail.Trail': [{'identifier': 'audit', 'properties': {'TrailName': 'audit', 'S3BucketName': 'audit-bucket', 'IsLogging': True}}]})
    foreign = {p: p.read_bytes() for p in (root / 'model').rglob('*') if p.is_file() and not p.is_relative_to(directory) and p != template}
    with mapping_alias(m.ROOT, root):
        acquired = m.acquire(root, 'dev', 'cloudtrail', TARGET, cli_runner=cli, resource_types=['CloudTrail.Trail'])
        record = acquired['records'][0]
        captured = {prop: item['value'] for prop, item in record['properties'].items() if item['status'] == 'captured'}
        before_addition = load_for_edit(path)
        block = ['# definition: AcquiredTrail', '# resource: trail']
        if present:
            block.insert(1, '# parameter: Bucket ' + json_text({'type': 'reference', 'description': '参照Bucket', 'required': True, 'service': 's3', 'resourceType': 'S3.Bucket'}))
        block += ['# row: row_' + str(i) + ' trail' for i in range(len(captured))]
        block += ['desired.resource.trail.resourceType=CloudTrail.Trail', 'desired.resource.trail.resourceMode=IMPORT', 'desired.resource.trail.anchor=cloudtrail-audit', 'display.resource.trail.comment=合成Trail']
        observed = {}
        for i, (prop, value) in enumerate(captured.items()):
            raw = m.model_literal(value)
            if present and prop == 'CloudTrail.Trail.S3BucketName':
                raw = '<<Bucket>>'
                observed['observed.row.009-' + str(i + 1).zfill(3) + '.value'] = m.model_literal(value)
            if present and prop == 'CloudTrail.Trail.EventSelectors[].DataResources[].Values':
                raw = m.model_literal([[['[audit-bucket](s3.md#s3-audit-bucket)']]])
                observed['observed.row.009-' + str(i + 1).zfill(3) + '.value'] = m.model_literal(value)
            block += ['desired.row.row_' + str(i) + '.property=' + prop, 'desired.row.row_' + str(i) + '.value=' + raw, 'desired.row.row_' + str(i) + '.comment=合成取得設定']
        block += ['# end-definition', '']
        bindings = json.loads((directory / 'bindings.json').read_text())
        bindings['instances']['audit'] = {'definition': 'AcquiredTrail', 'resources': {'trail': '009'},
            'rows': {'row_' + str(i): '009-' + str(i + 1).zfill(3) for i in range(len(captured))}, 'parameters': {}}
        output = {template.relative_to(root).as_posix(): template.read_text() + '\n'.join(block),
                  (directory / 'bindings.json').relative_to(root).as_posix(): json_text(bindings)}
        if present:
            output[(directory / 'parameters.yaml').relative_to(root).as_posix()] = 'instances:\n  audit:\n    parameters:\n      Bucket: "001"\n'
        if observed:
            output[(directory / 'observed.json').relative_to(root).as_posix()] = json_text({'version': 1, 'values': observed})
        stage(acquired, output, [{'record': record['record'], 'resource': '009', 'action': 'add', 'reason': 'Explicit synthetic management', 'basis': []}])
        review_fixture(root, acquired, 'cloudtrail')
        calls = len(cli.calls)
        import model_templates
        real_parse = model_templates.parse_template
        real_finish = m.finish_import
        original_sources = source_files(root)
        reads = []
        def counted(template, *args, **kwargs):
            if template.name == 's3.properties.tpl':
                reads.append(template)
            return real_parse(template, *args, **kwargs)
        def finish(*args, **kwargs):
            value = real_finish(*args, **kwargs)
            if race and len(args) > 1 and args[1] == 'reflected':
                bucket = root / 'model/templates/cde/s3.properties.tpl'
                bucket.write_text(bucket.read_text().replace('`audit-bucket`', '`audit-bucket-raced`'))
            return value
        with patch.object(model_templates, 'parse_template', counted), patch.object(m, 'finish_import', finish):
            if race:
                with pytest.raises(ValueError, match='inputs changed during publication'):
                    m.publish_acquisition(root, 'dev', 'cloudtrail', acquired['evidence'], TARGET)
                changed = Path('model/templates/cde/s3.properties.tpl')
                actual_sources = source_files(root)
                assert actual_sources.pop(changed) != original_sources[changed]
                assert actual_sources == {key: value for key, value in original_sources.items() if key != changed}
                assert not (root / 'docs/designs/dev/cde/cloudtrail.md').exists()
                assert len(reads) == 1 and len(cli.calls) == calls
                import_guard.discard_acquisition(root, acquired['evidence'])
                return
            result = m.publish_acquisition(root, 'dev', 'cloudtrail', acquired['evidence'], TARGET)
        assert len(reads) == int(present), reads
        assert result['status'] == 'complete' and result['model'] == 'reflected' and result['markdown'] == 'generated', result
        assert len(cli.calls) == calls
        markdown = (root / 'docs/designs/dev/cde/cloudtrail.md').read_text()
        assert ('[audit-bucket](s3.md#s3-audit-bucket)' if present else '`audit-bucket`') in markdown
        assert result['referenceMetrics']['referenceModelReads'] == int(present)
        assert all(p.read_bytes() == raw for p, raw in foreign.items())
        assert not (root / 'docs/designs/dev/cde/s3.md').exists()
        from model_design import generate_markdown
        from import_scope import new_references
        with new_references(before_addition, {'009': record}):
            saved = load_for_edit(path, display=True).values
            document = root / 'docs/designs/dev/cde/cloudtrail.md'
            assert generate_markdown(document, saved, root) == markdown
        before_recovery = source_files(root)
        assert sync_runtime.sync(root, True, 'dev', TARGET, services=['cloudtrail']) == 0
        assert source_files(root) == before_recovery
        assert document.read_text() == markdown


@pytest.mark.parametrize('action', ['refresh', 'replace'])
@pytest.mark.parametrize('dry_run', [False, True])
def check_user_selected_overwrite_publication(tmp_path, action, dry_run):
    from import_guard import digest
    from model_operation_checks import operation_values
    root, acquired, cli = prepare(tmp_path, dry_run=dry_run)
    path = root / 'model/dev/cde/cloudwatch-logs.properties'
    before = load_for_edit(path)
    original = snapshot(root)
    file = input_file(root)
    parameters = yaml_read(file.read_text())
    identity = 'fixture-001' if action == 'refresh' else 'managed-new'
    parameters['instances']['application-log']['parameters'].update(LogGroupName=identity, RetentionDays=90)
    selected = [correspondence(acquired, identity, '001', action)]
    if action == 'replace':
        selected[0]['before'] = {'identity': 'fixture-001', 'model': digest(operation_values(before.values, '001'))}
    stage(acquired, {file.relative_to(root).as_posix(): parameter_edit(file.read_text(), parameters)},
          selected, exclusions(acquired, selected))
    result = publish_fixture(root, acquired, dry_run=dry_run)
    assert result['status'] == ('dry-run' if dry_run else 'complete')
    assert result['resources']['refreshed' if action == 'refresh' else 'replaced'] == 1
    assert result['resources']['added'] == 0
    assert cli.calls == [('sts', 'get-caller-identity', {}), ('logs', 'describe-log-groups', {})]
    assert Path(acquired['evidence']).parent.exists() is dry_run
    if dry_run:
        assert snapshot(root) == original
        assert not (import_guard.evidence_store(root) / 'import-fixture.json').exists()
    else:
        after = load_for_edit(path)
        assert after.values['desired.row.001-002.value'] == '90'
        assert after.values['desired.row.001-001.value'] == identity
        assert operation_values(before.values, '002') == operation_values(after.values, '002')
        assert len(entries(after.values, 'desired.resource.')) == 2
        assert all(file.read_bytes() == data for file, data in
                   ((root / rel, data) for rel, data in original.items() if 'stg' in rel.parts))
        import_guard.require_import_changes(root)


@pytest.mark.parametrize('fail', [False, True])
def check_mixed_add_refresh_single_publication(tmp_path, fail):
    root, acquired, cli = prepare(tmp_path)
    files = logs_edit(root, acquired)
    file = input_file(root)
    relative = file.relative_to(root).as_posix()
    parameters = yaml_read(files[relative])
    parameters['instances']['application-log']['parameters']['RetentionDays'] = 90
    files[relative] = parameter_edit(files[relative], parameters)
    selected = [correspondence(acquired, 'managed-new'), correspondence(acquired, 'fixture-001', '001', 'refresh')]
    stage(acquired, files, selected, exclusions(acquired, selected))
    before = source_files(root)
    calls = []
    original_save = sync_files.save_files
    def save(output):
        calls.append(set(output))
        if fail:
            file, text = next(iter(output.items()))
            file.write_text(text, encoding='utf-8')
            raise OSError('injected source publication failure')
        return original_save(output)
    with patch.object(sync_files, 'save_files', side_effect=save):
        if fail:
            with pytest.raises(OSError, match='injected'):
                publish_fixture(root, acquired)
            assert source_files(root) == before
            import_guard.discard_acquisition(root, acquired['evidence'])
        else:
            result = publish_fixture(root, acquired)
            assert result['resources']['added'] == result['resources']['refreshed'] == 1
            values = load_for_edit(root / 'model/dev/cde/cloudwatch-logs.properties').values
            assert values['desired.row.001-002.value'] == values['desired.row.003-002.value'] == '90'
    assert sum(file in output for output in calls) == 1
    assert len(cli.calls) == 2


def check_replace_warns_incoming_references(tmp_path):
    from import_guard import digest
    from model_operation_checks import operation_values
    root = tmp_path / 'case'
    path = fixture(root, 'vpc')
    before = load_for_edit(path)
    cli = aws('vpc', changed=True, noise=True)
    acquired = m.acquire(root, 'dev', 'vpc', TARGET, cli_runner=cli)
    file = input_file(root, 'vpc')
    parameters = yaml_read(file.read_text())
    parameters['instances']['main-vpc']['parameters']['CidrBlock'] = '172.16.0.0/16'
    observed_file = file.with_name('observed.json')
    observed = json.loads(observed_file.read_text())
    observed['values']['observed.row.001-001.value'] = 'vpc-00000000000000000'
    selected = [correspondence(acquired, 'vpc-00000000000000000', '001', 'replace')]
    selected[0]['before'] = {'identity': VPC_ID, 'model': digest(operation_values(before.values, '001'))}
    stage(acquired, {file.relative_to(root).as_posix(): parameter_edit(file.read_text(), parameters),
                    observed_file.relative_to(root).as_posix(): json_text(observed)}, selected, exclusions(acquired, selected))
    original = snapshot(root)
    result = publish_fixture(root, acquired, 'vpc')
    assert any(w['code'] == 'reference.replace_impact' for w in result['warnings'])
    assert snapshot(root) != original
    assert result['status'] == 'incomplete' and Path(acquired['evidence']).is_file()


@pytest.mark.parametrize('missing', [False, True])
@pytest.mark.parametrize('shared_template', [False, True])
def check_first_resource_uses_existing_source_format(tmp_path, missing, shared_template):
    import shutil
    root = tmp_path / 'case'
    path = fixture(root)
    file = input_file(root)
    template = root / 'model/templates/cde/cloudwatch-logs.properties.tpl'
    template_text = template.read_text()
    bindings = json.loads(file.with_name('bindings.json').read_text())
    parameters = yaml_read(file.read_text())
    empty_binding = bindings['instances']['service']
    if not shared_template:
        shutil.rmtree(input_file(root, env='stg').parent)
    if missing:
        shutil.rmtree(file.parent)
        if not shared_template:
            template.unlink()
        assert load_for_edit(path) is None
    else:
        file.write_text('instances: {}\n')
        file.with_name('bindings.json').write_text(json_text({'instances': {'service': empty_binding}}))
        assert not entries(load_for_edit(path).values, 'desired.resource.')
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-qm', 'synthetic absent or empty service'], cwd=root, check=True)
    cli = aws(changed=True)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
    parameters['instances'] = {'application-log': parameters['instances']['application-log']}
    parameters['instances']['application-log']['parameters']['RetentionDays'] = 90
    bindings['instances'] = {'service': empty_binding, 'application-log': bindings['instances']['application-log']}
    files = {file.relative_to(root).as_posix(): parameter_edit('instances: {}\n', parameters),
             file.with_name('bindings.json').relative_to(root).as_posix(): json_text(bindings)}
    if not template.exists():
        files[template.relative_to(root).as_posix()] = template_text
    selected = [correspondence(acquired, 'fixture-001', '001')]
    stage(acquired, files, selected, exclusions(acquired, selected))
    result = publish_fixture(root, acquired)
    assert result['status'] == 'complete' and result['resources']['added'] == 1
    assert len(entries(load_for_edit(path).values, 'desired.resource.')) == 1
    assert len(cli.calls) == 2


def check_refresh_switches_definition_without_foreign_changes(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    before = source_files(root)
    template = root / 'model/templates/cde/cloudwatch-logs.properties.tpl'
    text = template.read_text()
    definition = text[text.index('# definition: LogGroup\n'):]
    definition = definition.replace('# definition: LogGroup\n', '# definition: AcquiredLogGroup\n')
    definition = definition.replace('desired.row.class.value=`STANDARD`', 'desired.row.class.value=`INFREQUENT_ACCESS`')
    file = input_file(root)
    parameters = yaml_read(file.read_text())
    parameters['instances']['application-log']['parameters']['RetentionDays'] = 90
    bindings_file = file.with_name('bindings.json')
    bindings = json.loads(bindings_file.read_text())
    bindings['instances']['application-log']['definition'] = 'AcquiredLogGroup'
    cli = aws(changed=True)
    cli.logs[0]['logGroupClass'] = 'INFREQUENT_ACCESS'
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
    selected = [correspondence(acquired, 'fixture-001', '001', 'refresh')]
    stage(acquired, {template.relative_to(root).as_posix(): text + '\n' + definition,
                    file.relative_to(root).as_posix(): parameter_edit(file.read_text(), parameters),
                    bindings_file.relative_to(root).as_posix(): json_text(bindings)}, selected, exclusions(acquired, selected))
    result = publish_fixture(root, acquired)
    assert result['status'] == 'complete'
    values = load_for_edit(root / 'model/dev/cde/cloudwatch-logs.properties').values
    assert values['desired.row.001-004.value'] == '`INFREQUENT_ACCESS`'
    assert values['desired.row.002-004.value'] == '`STANDARD`'
    assert all((root / rel).read_bytes() == data for rel, data in before.items() if 'stg' in rel.parts)
    from import_scope import read_consumers
    with read_consumers({('stg', TARGET, 'cloudwatch-logs')}):
        assert load_for_edit(root / 'model/stg/cde/cloudwatch-logs.properties').values['desired.row.001-004.value'] == '`STANDARD`'


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
