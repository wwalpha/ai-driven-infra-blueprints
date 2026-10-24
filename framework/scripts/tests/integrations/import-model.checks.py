#!/usr/bin/env python3
"""Offline acquire/edit/publish integration. Run through tests/run_it.py in CI."""

import sys
from collections import Counter
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import socket
import subprocess
from unittest.mock import patch

import import_guard
import model.importing.scope as _imports_model_importing_scope
import model.sources
import pytest
import support.import_model_fixtures as _imports_support_import_model_fixtures
import sync_files
import sync_runtime
from import_guard import digest
from model.core import entries, properties
from model.format import parse, serialize
from model.identity import COUNTERS, allocate
from model.importing import repository
from model.importing.scope import read_context
from model.operations import operation_values
from model.sources import json_text, load_model
from support.import_model_fixtures import (
    ACCOUNT,
    SERVICES,
    SUBNETS,
    TARGET,
    VPC_ID,
    AwsCli,
    CloudControlCli,
    aws,
    correspondence,
    exclusions,
    fixture,
    logs_edit,
    m,
    project_fixture,
    publish_fixture,
    resource_values,
    review_fixture,
    snapshot,
    stage,
)
from support.import_repository_fixtures import checkpoint, repositories, state
from support.model_sources import write_model
from support.model_v2_fixtures import import_publication_case
from task_contract_core import selected_task, start
from utils import sealed_evidence

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def _callback_offline_without_git(popen, /, command, *args, **kwargs):
    assert Path(command[0]).stem != 'git', 'Import IT must not start Git'
    return popen(command, *args, **kwargs)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('live network forbidden')))
    popen = subprocess.Popen
    without_git = _bind_framework_callback(_callback_offline_without_git, popen)
    monkeypatch.setattr(subprocess, 'Popen', without_git)
    with repositories(monkeypatch):
        yield
    assert 'support.worktree_task_fixtures' not in sys.modules


def prepare(tmp_path, service='cloudwatch-logs', changed=True, dry_run=False):
    root = tmp_path / 'case'
    fixture(root, service, register=not dry_run)
    cli = aws(service, changed=changed)
    acquisition = m.acquire(root, 'dev', service, TARGET, dry_run, cli, resource_types=['Logs.LogGroup'] if service == 'cloudwatch-logs' else None)
    return root, acquisition, cli


def input_file(root, service='cloudwatch-logs', env='dev'):
    return root / 'model' / env / TARGET / (service + '.properties')


def source_files(root):
    return {p.relative_to(root): p.read_bytes() for p in (root / 'model').rglob('*') if p.is_file()}


def promote_logs(root, acquisition):
    files = logs_edit(root, acquisition)
    relative = next(iter(files))
    values = parse(files[relative]).values
    values['desired.row.003-004.value'] = '`INFREQUENT_ACCESS`'
    files[relative] = serialize(values)
    selected = [correspondence(acquisition, 'managed-new')]
    stage(root, acquisition, files, selected, exclusions(acquisition, selected))
    return files


def check_logs_roundtrip(tmp_path):
    root, acquired, cli = prepare(tmp_path)
    path = root / 'model/dev/cde/cloudwatch-logs.properties'
    before = load_model(path)
    files = logs_edit(root, acquired)
    result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['markdown'] == 'generated' and result['status'] == 'complete'
    assert cli.calls == [('sts', 'get-caller-identity', {}), ('logs', 'describe-log-groups', {})]
    assert not (root / '.blueprint').exists()
    after = load_model(path)
    assert after.authoritative['desired.row.003-002.value'] == '`90`'
    assert after.authoritative['desired.row.003-001.value'] == '`managed-new`'
    display = (root / 'docs/designs/dev/cde/cloudwatch-logs.md').read_text()
    assert '| LogGroupName | `managed-new` |' in display and '``managed-new``' not in display
    assert all(after.authoritative[key] == value for key, value in before.authoritative.items() if key != 'desired.service.identity.lastAllocated')
    assert len(files) == 1
    calls = list(cli.calls)
    assert m.recover_display(root, 'dev', 'cloudwatch-logs', TARGET)['status'] == 'complete'
    assert cli.calls == calls
    import_guard.require_import_changes(root)


def check_config_sources(tmp_path):
    root, acquired, _ = prepare(tmp_path, 'config', changed=False)
    path = root / 'model/dev/cde/config.properties'
    before = path.read_bytes()
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
    result = publish_fixture(root, acquired, 'config')
    assert result['model'] == 'unchanged' and path.read_bytes() == before
    values = load_model(path).values
    assert 'AWSServiceRoleForConfig' in values['desired.row.001-007.value']
    arn = 'arn:aws:iam::' + ACCOUNT + ':role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig'
    values = values | {'desired.row.001-007.value': arn}
    document = root / 'docs/designs/dev/cde/config.md'
    output = sync_runtime.generate_files(document, values, root)[document]
    assert '| RoleARN | ' + arn + ' |' in output and '| RoleName | ' + arn + ' |' not in output


def check_vpc_eight_instances(tmp_path):
    root = tmp_path / 'case'
    path = fixture(root, 'vpc')
    before = source_files(root)
    acquired = m.acquire(root, 'dev', 'vpc', TARGET, cli_runner=aws('vpc', noise=True))
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
    result = publish_fixture(root, acquired, 'vpc')
    assert result['model'] == 'unchanged' and source_files(root) == before
    values = load_model(path).authoritative
    assert len(entries(values, 'desired.resource.')) == 8
    assert {values[f'desired.row.{rid:03d}-004.value'].strip('`') for rid in range(2, 9)} == {name for name, _, _ in SUBNETS}
    assert len(exclusions(acquired, [])) == 10


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
        acquired = m.acquire(root, 'dev', service, TARGET, True, cli, resource_types=['Logs.LogGroup'] if service == 'cloudwatch-logs' else None)
        assert acquired['records'] and acquired['sts'] == {'account': ACCOUNT, 'verified': True}
        assert cli.calls[0] == ('sts', 'get-caller-identity', {})
        assert all('properties' in record and 'getters' not in record for record in acquired['records'])
        import_guard.discard_acquisition(root, acquired['evidence'])


@pytest.mark.parametrize('kind,unknown', [('subnet', False), ('vpc', False), ('vpc', True)])
def check_managed_resource_addition(tmp_path, kind, unknown):
    root = tmp_path / 'case'
    path = fixture(root, 'vpc')
    if unknown:
        values = dict(load_model(path).authoritative)
        del values['observed.row.001-001.value']
        path.write_text(serialize(values), encoding='utf-8')
        checkpoint(root)
    original = load_model(path)
    foreign = {p: p.read_bytes() for p in (root / 'model').rglob('*.properties') if p != path}
    cli = aws('vpc', changed=True)
    if kind == 'subnet':
        name, identity, source = 'audit-private-1a', 'subnet-managed-new', '002'
        cli.responses['ec2', 'describe-subnets']['Subnets'].append({'SubnetId': identity, 'VpcId': VPC_ID,
            'CidrBlock': '10.11.0.0/26', 'AvailabilityZone': 'ap-northeast-1a', 'MapPublicIpOnLaunch': False,
            'Tags': [{'Key': 'Name', 'Value': name}]})
    else:
        name, identity, source = 'new-vpc', 'vpc-managed-new', '001'
        cli.responses['ec2', 'describe-vpcs']['Vpcs'].append({'VpcId': identity, 'CidrBlock': '10.11.0.0/23',
            'Tags': [{'Key': 'Name', 'Value': 'main-vpc'}]})
    acquired = m.acquire(root, 'dev', 'vpc', TARGET, cli_runner=cli)
    values = dict(original.authoritative)
    for key, value in original.authoritative.items():
        if key.startswith((f'desired.resource.{source}.', f'display.resource.{source}.', f'desired.row.{source}-', f'observed.row.{source}-')):
            values[key.replace('.' + source, '.009', 1)] = value
    del values['desired.resource.009.logicalId']
    values = allocate(values, ['009'])
    values['desired.resource.009.anchor'] = 'vpc-managed-009'
    values['desired.row.009-001.value'] = '[009](#vpc-managed-009)'
    values['observed.row.009-001.value'] = identity
    values['desired.row.009-' + ('003' if kind == 'subnet' else '002') + '.value'] = m.model_literal('10.11.0.0/26' if kind == 'subnet' else '10.11.0.0/23')
    if kind == 'subnet':
        values['desired.row.009-004.value'] = m.model_literal(name)
    selected = [correspondence(acquired, identity, '009')]
    stage(root, acquired, {path.relative_to(root).as_posix(): serialize(values)}, selected, exclusions(acquired, selected))
    result = publish_fixture(root, acquired, 'vpc')
    assert result['status'] == 'complete' and result['model'] == 'reflected' and result['markdown'] == 'generated'
    assert {change['resource'] for change in result['changes']} == {'009'}
    current = load_model(path)
    assert len(entries(current.authoritative, 'desired.resource.')) == 9
    assert all(current.authoritative[k] == v for k, v in original.authoritative.items() if k != 'desired.service.identity.lastAllocated')
    assert current.authoritative['observed.row.009-001.value'] == identity
    assert current.authoritative['desired.row.009-001.value'] == '[009](#vpc-managed-009)'
    if kind == 'subnet':
        assert current.authoritative['desired.row.009-002.value'] == '[001](#vpc-main)'
    assert all(p.read_bytes() == data for p, data in foreign.items())


@pytest.mark.parametrize('action', ['update', 'add'])
def check_existing_resource_selection_rejected(tmp_path, action):
    root, acquired, _ = prepare(tmp_path)
    selected = [correspondence(acquired, 'fixture-001', '001', action)]
    stage(root, acquired, {}, selected, exclusions(acquired, selected))
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
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, aws(profile=None), resource_types=['Logs.LogGroup'])
    assert acquired['connection']['awsProfile'] is None
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_explicit_no_profile(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    cli = aws(profile=None)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli, no_profile=True, resource_types=['Logs.LogGroup'])
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
    before = load_model(input_file(root)).authoritative
    logs_edit(root, acquired)
    publish_fixture(root, acquired)
    after = load_model(input_file(root)).authoritative
    assert operation_values(before, '002') == operation_values(after, '002')
    assert after['desired.resource.002.resourceMode'] == 'CREATE'
    assert after['desired.resource.003.resourceMode'] == 'IMPORT'
    assert not (root / 'model/templates').exists()


def check_cli_faults(tmp_path):
    root = tmp_path / 'case'
    fixture(root, register=False)
    for cli, error_type, code in [(AwsCli(account='999999999999'), m.comparator().IdentityError, 'AccountMismatch'),
                                  (AwsCli(fail='An error occurred (AccessDenied) when calling STS: PRIVATE-CREDENTIAL'), m.comparator().AcquisitionError, 'AccessDenied')]:
        before = snapshot(root)
        with pytest.raises(error_type) as caught:
            m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, cli, resource_types=['Logs.LogGroup'])
        assert caught.value.code == code
        assert snapshot(root) == before and len(cli.calls) == 1
    for payload in ({}, {'logGroups': None}, {'logGroups': 'invalid'}):
        cli = aws()
        cli.responses['logs', 'describe-log-groups'] = payload
        acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, cli, resource_types=['Logs.LogGroup'])
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
    foreign = input_file(root, env='stg')
    stage(root, acquired, {foreign.relative_to(root).as_posix(): foreign.read_text()})
    with pytest.raises(ValueError, match='outside|invalid authoritative Model path'):
        publish_fixture(root, acquired)
    with pytest.raises(ValueError, match='scope'):
        m.publish_acquisition(root, 'dev', 'vpc', acquired['evidence'], TARGET)
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_external_reference_preservation(tmp_path):
    root = tmp_path / 'case'
    path = fixture(root, 'config')
    values = dict(load_model(path).authoritative)
    values['desired.row.001-007.value'] = '[role](iam.md#not-locally-resolved)'
    path.write_text(serialize(values), encoding='utf-8')
    checkpoint(root)
    acquired = m.acquire(root, 'dev', 'config', TARGET, cli_runner=aws('config'))
    role = next(r for r in acquired['records'] if r['kind'] == 'Config.ConfigurationRecorder')['properties']['Config.ConfigurationRecorder.RoleARN']['value']
    values['observed.row.001-007.value'] = role
    stage(root, acquired, {path.relative_to(root).as_posix(): serialize(values)}, excluded=exclusions(acquired, []))
    before = snapshot(root)
    with pytest.raises(ValueError, match='unselected Resource'):
        publish_fixture(root, acquired, 'config')
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])
    assert '[role](iam.md#not-locally-resolved)' in path.read_text()
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
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli, resource_types=['Logs.LogGroup'])
    stg_path = input_file(root, env='stg')
    before = stg_path.read_bytes()
    promote_logs(root, acquired)
    result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected'
    assert stg_path.read_bytes() == before
    assert not (root / 'docs/designs/stg').exists()
    assert not any('/stg/' in str(p) for p in result.get('files', []))


@pytest.mark.parametrize('relative', ['model/stg/cde/cloudwatch-logs.properties',
    'model/stg/cde/cloudwatch-logs/part-001.properties', 'model/dev/cde/vpc.properties',
    'model/dev/cde/vpc/part-001.properties', 'model/templates/cde/vpc.properties.tpl'])
def check_foreign_source_writes_rejected(tmp_path, relative):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    source = root / relative
    text = source.read_text() if source.exists() else '{"version":1,"values":{}}'
    destination = Path(acquired['candidates']) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text + '\n')
    before = snapshot(root)
    with patch.object(m, 'publish_edit', side_effect=AssertionError('must reject before saving')), pytest.raises(ValueError, match='outside|invalid authoritative Model path'):
        publish_fixture(root, acquired)
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])


@pytest.mark.parametrize('service,scenario', [('cloudwatch-logs', 'duplicate'), ('cloudwatch-logs', 'new'),
                                               ('vpc', 'duplicate'), ('vpc', 'hide-observed')])
def check_add_identity_boundary(tmp_path, service, scenario):
    root = tmp_path / 'case'
    path = fixture(root, service)
    acquired = m.acquire(root, 'dev', service, TARGET, cli_runner=aws(service, changed=True), resource_types=['Logs.LogGroup'] if service == 'cloudwatch-logs' else None)
    values = dict(load_model(path).authoritative)
    original = dict(values)
    for key, value in operation_values(original, '001').items():
        values[key.replace('.001', '.009', 1)] = value
    del values['desired.resource.009.logicalId']
    values = allocate(values, ['009'])
    values['desired.resource.009.anchor'] = 'vpc-managed-009'
    if service == 'cloudwatch-logs':
        values['desired.row.009-001.value'] = '`managed-new`' if scenario == 'new' else '`fixture-001`'
        values['desired.row.009-002.value'] = '`90`'
    else:
        values['desired.row.009-001.value'] = '[009](#vpc-managed-009)'
        values['desired.row.009-002.value'] = '`10.11.0.0/23`'
        values['observed.row.009-001.value'] = VPC_ID
        if scenario == 'hide-observed':
            del values['observed.row.001-001.value']
    identity = 'managed-new' if scenario == 'new' else 'fixture-001' if service == 'cloudwatch-logs' else VPC_ID
    selected = [correspondence(acquired, identity, '009', 'add')]
    stage(root, acquired, {path.relative_to(root).as_posix(): serialize(values)}, selected, exclusions(acquired, selected))
    before = snapshot(root)
    if scenario == 'new':
        result = publish_fixture(root, acquired, service)
        assert result['status'] == 'complete'
        assert {change['resource'] for change in result['changes']} == {'009'}
        assert all(load_model(path).authoritative[key] == value for key, value in original.items() if key != 'desired.service.identity.lastAllocated')
    else:
        with patch.object(m, 'record_import', side_effect=AssertionError('must reject before recording')), \
             patch.object(m, 'publish_edit', side_effect=AssertionError('must reject before saving')), \
             patch.object(m, 'view_plan', side_effect=AssertionError('must reject before display')), \
             pytest.raises(ValueError, match='009.*001|unselected Resource'):
            publish_fixture(root, acquired, service)
        assert snapshot(root) == before
        assert not import_guard.proof_path(root).exists()
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
    cli = aws(changed=True)
    with pytest.raises(ValueError, match='Task already published'):
        m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli, resource_types=['Logs.LogGroup'])
    assert not cli.calls and source_files(root) == before
    import_guard.require_import_changes(root)
    old_name, new_name = 'tasks/import-fixture.md', 'tasks/reimport.md'
    checkpoint(root, task=new_name)
    text = (root / old_name).read_text().replace(old_name, new_name)
    start(root, new_name, text)
    with selected_task(root, new_name):
        again = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=aws(changed=True), resource_types=['Logs.LogGroup'])
        path = input_file(root)
        selected = [correspondence(again, 'managed-new', '003', action='refresh')]
        stage(root, again, {path.relative_to(root).as_posix(): path.read_text()}, selected, exclusions(again, selected))
        assert publish_fixture(root, again)['status'] == 'complete'
        import_guard.require_import_changes(root)
    with selected_task(root, old_name):
        assert sealed_evidence.read_sealed(root, import_guard.proof_path(root))['complete']


def check_fixed_identity_rejection(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    files = logs_edit(root, acquired)
    relative = next(iter(files))
    values = parse(files[relative]).values
    values['desired.resource.001.anchor'] = 'changed-fixed-anchor'
    (Path(acquired['candidates']) / relative).write_text(serialize(values), encoding='utf-8')
    before = snapshot(root)
    with pytest.raises(ValueError):
        publish_fixture(root, acquired)
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_empty_inventory_preserves_sources(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    cli = aws()
    cli.logs = []
    before = source_files(root)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli, resource_types=['Logs.LogGroup'])
    assert acquired['records'] == []
    stage(root, acquired, {})
    result = publish_fixture(root, acquired)
    assert result['model'] == 'unchanged' and source_files(root) == before


def check_partial_reflection(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    files = logs_edit(root, acquired)
    selected = [correspondence(acquired, 'managed-new')]
    unresolved = next(r for r in acquired['records'] if r['identity'] == 'fixture-002')
    stage(root, acquired, files, selected, excluded=[item for item in exclusions(acquired, selected) if item['record'] != unresolved['record']], pending=[{'record': unresolved['record'], 'reason': 'ownership not confirmed'}])
    original = source_files(root)
    with pytest.raises(ValueError, match='all Resource selections'):
        publish_fixture(root, acquired)
    assert source_files(root) == original and Path(acquired['evidence']).exists()


def check_native_types_preserved(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    files = logs_edit(root, acquired)
    path = next(iter(files))
    selected = [correspondence(acquired, 'managed-new')]
    stage(root, acquired, {path: files[path].replace('desired.row.003-002.value=`90`', 'desired.row.003-002.value=`"90"`')},
          selected, exclusions(acquired, selected))
    before = source_files(root)
    with pytest.raises(ValueError, match='type|acquired'):
        publish_fixture(root, acquired)
    assert source_files(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])


def check_consumer_set_race(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=aws(changed=True), resource_types=['Logs.LogGroup'])
    logs_edit(root, acquired)
    new_consumer = root / 'model/dev/cde/new-consumer.properties'
    new_consumer.write_text(serialize({}), encoding='utf-8')
    before = snapshot(root)
    with pytest.raises(ValueError, match='changed|no acquired change plan|outside Modified files/Allowed paths'):
        publish_fixture(root, acquired)
    assert snapshot(root) == before
    import_guard.discard_acquisition(root, acquired['evidence'])


def _callback_check_source_transaction_rollback_fail_after_first(real_save, root, /, output):
    selected = list(output.items())
    if any(path.is_relative_to(root / 'model') for path, _ in selected):
        path, text = selected[0]
        path.write_text(text, encoding='utf-8')
        raise OSError('synthetic interrupted source transaction')
    return real_save(output)


def check_source_transaction_rollback(tmp_path):
    root = tmp_path / 'case'
    fixture(root)
    cli = aws(changed=True)
    cli.logs[-1]['logGroupClass'] = 'INFREQUENT_ACCESS'
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli, resource_types=['Logs.LogGroup'])
    promote_logs(root, acquired)
    original = source_files(root)
    real_save = sync_files.save_files
    fail_after_first = _bind_framework_callback(_callback_check_source_transaction_rollback_fail_after_first, real_save, root)
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
    assert {key: value for key, value in properties(original).items() if key != 'desired.service.identity.lastAllocated'}.items() <= properties(current).items()
    assert 'desired.resource.003.resourceType=Logs.LogGroup' in current
    assert 'desired.row.003-002.value=`90`' in current
    assert next(iter(files.values())) == current


def check_reflection_validation_boundary(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    with patch('import_guard.snapshots', side_effect=AssertionError('no whole Git Model comparison')), \
         patch('model.validation.validate_required_properties', side_effect=AssertionError('no whole design validation')), \
         patch.object(m.comparator(), 'compare_resource', side_effect=AssertionError('no AWS comparison phase')):
        result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['designValidation'] == 'not-run'


def check_dry_run_cleanup(tmp_path):
    root, acquired, _ = prepare(tmp_path, dry_run=True)
    before = snapshot(root)
    logs_edit(root, acquired)
    reviewed = review_fixture(root, acquired, dry_run=True)
    assert reviewed['model'] == 'unchanged' and snapshot(root) == before
    assert len(reviewed['review']['dispositions']) == len(acquired['records'])
    result = publish_fixture(root, acquired, dry_run=True)
    assert result['status'] == 'dry-run'
    assert any(item['key'] == 'desired.row.003-002.value' for disposition in result['review']['dispositions'] for item in disposition['changes'])
    assert snapshot(root) == before and Path(acquired['evidence']).is_file()
    assert not (root / 'tasks').exists() and not (root / '.blueprint/import').exists()
    second = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, True, aws(changed=True), resource_types=['Logs.LogGroup'])
    logs_edit(root, second, 91)
    with pytest.raises(ValueError):
        publish_fixture(root, second, dry_run=True)
    assert Path(second['evidence']).is_file()


def _callback_check_evidence_and_display_recovery_fail_display(actual, /, root, output, *args, **kwargs):
    if any(p.is_relative_to(root / 'docs/designs') for p in output):
        raise OSError('synthetic display I/O failure')
    return actual(root, output, *args, **kwargs)


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
    with patch.object(m, 'view_plan', side_effect=ValueError('synthetic display failure')):
        with pytest.raises(ValueError, match='synthetic display failure'):
            publish_fixture(root, acquired)
    assert source_files(root) == before and evidence.is_file()
    actual = m._publish_transaction
    fail_display = _bind_framework_callback(_callback_check_evidence_and_display_recovery_fail_display, actual)
    with patch.object(m, '_publish_transaction', side_effect=fail_display):
        result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['markdown'] == 'failed' and result['status'] == 'display-failed'
    assert evidence.is_file()
    before = source_files(root)
    with patch.object(m, 'import_context', side_effect=AssertionError('recovery must not acquire')):
        assert m.recover_display(root, 'dev', 'cloudwatch-logs', TARGET)['status'] == 'complete'
    assert source_files(root) == before and import_guard.read_proof(root)['markdown'] == 'generated'
    assert not (root / '.blueprint').exists()


def _callback_check_partial_acquisition_cannot_complete_cli(original, /, command, **kwargs):
    if command[1:3] == ['configservice', 'describe-delivery-channels']:
        original.calls.append(('configservice', 'describe-delivery-channels', {}))
        return subprocess.CompletedProcess(command, 1, '', 'An error occurred (AccessDeniedException) when calling fixture: denied')
    return original(command, **kwargs)


def check_partial_acquisition_cannot_complete(tmp_path):
    root = tmp_path / 'case'
    fixture(root, 'config')
    original = aws('config')
    cli = _bind_framework_callback(_callback_check_partial_acquisition_cannot_complete_cli, original)
    before = source_files(root)
    acquired = m.acquire(root, 'dev', 'config', TARGET, cli_runner=cli)
    assert acquired['status'] == 'incomplete' and acquired['records']
    assert acquired['inventory']['Config.DeliveryChannel']['status'] == 'permission_denied'
    sealed = import_guard.read_acquisition(root, Path(acquired['evidence']), ('dev', TARGET, 'config'), False)
    assert sealed['version'] == 3 and not import_guard.acquisition_complete(sealed)
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
    count = len(original.calls)
    with patch.object(m, 'import_context', side_effect=AssertionError('publish cannot acquire')):
        result = publish_fixture(root, acquired, 'config')
    assert result['status'] == 'incomplete' and len(original.calls) == count
    assert source_files(root) == before and import_guard.read_proof(root)['complete'] is False


def check_generic_acquisition_roundtrip(tmp_path):
    root = tmp_path / 'case'
    root.mkdir()
    project_fixture(root)
    path = root / 'model/dev' / ACCOUNT / 'datazone.properties'
    write_model(path, {'desired.service.datazone.serviceId': 'datazone',
                      'desired.service.datazone.ownedCatalogResourceTypes': 'DataZone.Domain',
                      'display.service.title': '# DataZone 詳細設計'})
    checkpoint(root)
    cli = CloudControlCli({'DataZone.Domain': [{'identifier': 'dzd-fixture', 'properties': {'Id': 'dzd-fixture', 'Name': 'fixture', 'DomainVersion': 'V2', 'SingleSignOn': {'Type': 'DISABLED'}}}]})
    before = source_files(root)
    acquired = m.acquire(root, 'dev', 'datazone', ACCOUNT, True, cli, resource_types=['DataZone.Domain'])
    assert acquired['status'] == 'acquired' and len(acquired['records']) == 1
    assert acquired['records'][0]['identityComponents'] == [{'property': 'DataZone.Domain.Id', 'value': 'dzd-fixture'}]
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
    count = len(cli.calls)
    with patch.object(m, 'import_context', side_effect=AssertionError('publish cannot acquire')):
        review_fixture(root, acquired, dry_run=True)
        result = m.publish_acquisition(root, 'dev', 'datazone', acquired['evidence'], ACCOUNT, True)
    assert result['status'] == 'dry-run' and source_files(root) == before and len(cli.calls) == count


def _callback_check_reference_publication_counted(original_read, reads, root, /, scope, *args, **kwargs):
    if scope.service == 's3':
        reads[read_context(root), args[0]] += 1
    return original_read(scope, *args, **kwargs)


def _callback_check_reference_publication_finish(original_finish, producer, race, /, *args, **kwargs):
    result = original_finish(*args, **kwargs)
    if race and kwargs.get('model') == 'reflected':
        producer.write_text(producer.read_text().replace('`audit-bucket`', '`audit-bucket-raced`'))
    return result


@pytest.mark.parametrize('present,race,diagnostic', [(False, False, None), (True, False, None), (True, True, None),
    (False, False, 'absent'), (True, False, 'mismatch'), (True, False, 'ambiguous'), (True, False, 'review-race')])
def check_reference_publication(tmp_path, present, race, diagnostic):

    CloudControlCli = _imports_support_import_model_fixtures.CloudControlCli
    project_fixture = _imports_support_import_model_fixtures.project_fixture
    reference_fields = _imports_support_import_model_fixtures.reference_fields
    service_values = _imports_support_import_model_fixtures.service_values
    root = tmp_path / 'reference-publication'
    root.mkdir()
    project_fixture(root)
    (root / 'project.json').write_text(json_text({'targets': [{'environment': 'dev', 'alias': TARGET,
        'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n')
    path = root / 'model/dev/cde/cloudtrail.properties'
    write_model(path, service_values('cloudtrail', ['CloudTrail.Trail']))
    producer = path.with_name('s3.properties')
    if present:
        write_model(producer, resource_values('001', 'S3.Bucket', 's3-audit-bucket', 'CREATE', [('BucketName', '`audit-bucket`')]))
    if diagnostic == 'mismatch':
        producer.write_text(producer.read_text().replace('`audit-bucket`', '`different-bucket`'))
    elif diagnostic == 'ambiguous':
        reference_reader = _imports_model_importing_scope.reference_reader
        with reference_reader(producer):
            fields = dict(load_model(producer).authoritative)
        fields.update(resource_values('002', 'S3.Bucket', 'another-bucket', 'CREATE', [('BucketName', '`audit-bucket`')]))
        write_model(producer, fields)
    checkpoint(root)
    files = {path, root / 'docs/designs/dev/cde/cloudtrail.md'}
    listed = ['- `' + p.relative_to(root).as_posix() + '`' for p in sorted(files)] + ['- `tasks/import-fixture.md`']
    text = '\n'.join(['# Reference fixture', '## Task contract', '- Task type: `design`', '- Task status: `running`',
        '- Workflow: `import`', '- IMPORT target: `dev/cde/cloudtrail`', '## Goal', 'Synthetic reference addition',
        '## Required changes', '- [R1] Add acquired resource', '## Acceptance checks', '- [R1] `exists:docs/designs/dev/cde/cloudtrail.md`',
        '## Validation scope', '- `dev/cde/cloudtrail`', '## Modified files', *listed, '## Allowed paths', *listed])
    start(root, 'tasks/import-fixture.md', text)
    cli = CloudControlCli({'CloudTrail.Trail': [{'identifier': 'audit', 'properties': {'TrailName': 'audit',
        'S3BucketName': 'audit-bucket', 'IsLogging': True,
        'EventSelectors': [{'ReadWriteType': 'All', 'IncludeManagementEvents': True,
                            'DataResources': [{'Type': 'AWS::S3::Object', 'Values': ['audit-bucket']}]}]}}]})
    foreign = {p: p.read_bytes() for p in (root / 'model').rglob('*.properties') if p != path}
    acquired = m.acquire(root, 'dev', 'cloudtrail', TARGET, cli_runner=cli, resource_types=['CloudTrail.Trail'])
    record = acquired['records'][0]
    captured = {prop: item['value'] for prop, item in record['properties'].items() if item['status'] == 'captured'}
    values = dict(load_model(path).authoritative)
    values.update(resource_values('009', 'CloudTrail.Trail', 'cloudtrail-audit', 'IMPORT',
        [(prop.removeprefix('CloudTrail.Trail.'), m.model_literal(value)) for prop, value in captured.items()]))
    values[COUNTERS] = load_model(path).authoritative.get(COUNTERS, '{}')
    del values['desired.resource.009.logicalId']
    values = allocate(values, ['009'])
    values['desired.resource.009.anchor'] = 'vpc-managed-009'
    link = '[S3_Bucket_001](s3.md#s3-audit-bucket)'
    if present or diagnostic:
        for index, (prop, actual) in enumerate(captured.items(), 1):
            key = f'desired.row.009-{index:03d}.value'
            if prop == 'CloudTrail.Trail.S3BucketName':
                values[key] = link
                values[f'observed.row.009-{index:03d}.value'] = m.model_literal(actual)
                values.update(reference_fields('bucket', key, link, 'dev/cde/s3/001', kind='S3.Bucket', mode='link', prop=None))
                values['desired.reference.bucket.labelPolicy'] = 'display-name'
            elif prop == 'CloudTrail.Trail.EventSelectors[].DataResources[].Values':
                values.update(reference_fields('nested-bucket', key, 'audit-bucket', 'dev/cde/s3/001',
                    kind='S3.Bucket', mode='name', prop='S3.Bucket.BucketName', pointer='/0/0/0'))
                assert values[key] == m.model_literal(actual)
    selected = [correspondence(acquired, record['identity'], '009')]
    stage(root, acquired, {path.relative_to(root).as_posix(): serialize(values)}, selected)
    reviewed = review_fixture(root, acquired, 'cloudtrail')['review']
    if diagnostic:
        assert reviewed['warnings'], reviewed
        assert m.review_acquisition(root, 'dev', 'cloudtrail', acquired['evidence'], TARGET)['review'] == reviewed
        if diagnostic == 'absent':
            assert any(w.get('phase') == 'after' and 'absent' in w['message'] for w in reviewed['warnings'])
            assert reviewed['referenceImpact']['inputs'][producer.relative_to(root).as_posix()] is None
        elif diagnostic in {'mismatch', 'ambiguous'}:
            assert any(w.get('phase') == 'physical' and w.get('acquiredValue') and
                w.get('consumerKey') and w.get('referenceIds') for w in reviewed['warnings'])
        else:
            producer.write_text(producer.read_text() + '# changed decision input\n')
            with pytest.raises(ValueError, match='Review changed or stale'):
                m.publish_acquisition(root, 'dev', 'cloudtrail', acquired['evidence'], TARGET)
            assert not import_guard.proof_path(root).exists()
            return
    calls = len(cli.calls)
    reads = Counter()
    original_read = model.sources._read_model
    original_finish = m.finish_import
    counted = _bind_framework_callback(_callback_check_reference_publication_counted, original_read, reads, root)
    finish = _bind_framework_callback(_callback_check_reference_publication_finish, original_finish, producer, race)
    original_sources = source_files(root)
    with patch.object(model.sources, '_read_model', counted), patch.object(m, 'finish_import', finish):
        if race:
            with pytest.raises(ValueError, match='inputs changed during publication'):
                m.publish_acquisition(root, 'dev', 'cloudtrail', acquired['evidence'], TARGET)
            changed = producer.relative_to(root)
            actual_sources = source_files(root)
            assert actual_sources.pop(changed) != original_sources[changed]
            assert actual_sources == {key: value for key, value in original_sources.items() if key != changed}
            assert not import_guard.proof_path(root).exists()
            assert not (root / 'docs/designs/dev/cde/cloudtrail.md').exists()
            assert len(cli.calls) == calls
            return
        result = m.publish_acquisition(root, 'dev', 'cloudtrail', acquired['evidence'], TARGET)
    assert result['status'] == 'complete' and result['model'] == 'reflected' and result['markdown'] == 'generated', result
    assert all(count == 1 for count in reads.values()), reads
    assert bool(reads) == present
    assert len(cli.calls) == calls
    document = root / 'docs/designs/dev/cde/cloudtrail.md'
    markdown = document.read_text()
    assert ('](s3.md#s3-audit-bucket)' if present or diagnostic else '`audit-bucket`') in markdown
    if present or diagnostic:
        saved = load_model(path).authoritative
        key = values['desired.reference.nested-bucket.consumerKey']
        assert saved[key] == values[key]
        assert saved['desired.reference.nested-bucket.format'] == 'name'
        assert saved['desired.reference.nested-bucket.pointer'] == '/0/0/0'
    assert all(p.read_bytes() == raw for p, raw in foreign.items())
    assert not (root / 'docs/designs/dev/cde/s3.md').exists()
    before_recovery = source_files(root)
    assert m.recover_display(root, 'dev', 'cloudtrail', TARGET)['status'] == 'complete'
    assert source_files(root) == before_recovery and document.read_text() == markdown


@pytest.mark.parametrize('action', ['refresh', 'replace', 'bind'])
@pytest.mark.parametrize('dry_run', [False, True])
def check_user_selected_overwrite_publication(tmp_path, action, dry_run):
    root = tmp_path / 'case'
    path = fixture(root, register=not dry_run)
    if action == 'bind':
        values = dict(load_model(path).authoritative)
        values['desired.row.001-001.value'] = 'UNSET'
        path.write_text(serialize(values), encoding='utf-8')
        checkpoint(root)
    cli = aws(changed=True)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, dry_run, cli, resource_types=['Logs.LogGroup'])
    before = load_model(path)
    original = snapshot(root)
    values = dict(before.authoritative)
    identity = 'fixture-001' if action == 'refresh' else 'managed-new'
    values.update({'desired.row.001-001.value': m.model_literal(identity), 'desired.row.001-002.value': '`90`'})
    selected = [correspondence(acquired, identity, '001', action)]
    if action in {'replace', 'bind'}:
        selected[0]['before'] = {'identity': None if action == 'bind' else 'fixture-001', 'model': digest(operation_values(before.authoritative, '001'))}
    stage(root, acquired, {path.relative_to(root).as_posix(): serialize(values)}, selected, exclusions(acquired, selected))
    result = publish_fixture(root, acquired, dry_run=dry_run)
    assert result['status'] == ('dry-run' if dry_run else 'complete')
    review = json.loads((Path(acquired['evidence']).parent / 'review.json').read_text())
    assert next(item for item in review['dispositions'] if item['record'] == selected[0]['record'])['operation'] == action
    assert cli.calls == [('sts', 'get-caller-identity', {}), ('logs', 'describe-log-groups', {})]
    assert Path(acquired['evidence']).is_file()
    if dry_run:
        assert snapshot(root) == original
        assert not (sealed_evidence.evidence_store(root) / 'import-fixture.json').exists()
    else:
        after = load_model(path)
        assert after.authoritative['desired.row.001-002.value'] == '`90`'
        assert after.authoritative['desired.row.001-001.value'] == m.model_literal(identity)
        assert operation_values(before.authoritative, '002') == operation_values(after.authoritative, '002')
        assert len(entries(after.authoritative, 'desired.resource.')) == 2
        assert all((root / rel).read_bytes() == data for rel, data in original.items() if 'stg' in rel.parts)
        import_guard.require_import_changes(root)


def _callback_check_mixed_add_refresh_single_publication_save(calls, fail, original_save, /, output):
    calls.append(set(output))
    if fail:
        file, text = next(iter(output.items()))
        file.write_text(text, encoding='utf-8')
        raise OSError('injected source publication failure')
    return original_save(output)


@pytest.mark.parametrize('fail', [False, True])
def check_mixed_add_refresh_single_publication(tmp_path, fail):
    root, acquired, cli = prepare(tmp_path)
    files = logs_edit(root, acquired)
    file = input_file(root)
    relative = file.relative_to(root).as_posix()
    values = parse(files[relative]).values
    values['desired.row.001-002.value'] = '`90`'
    files[relative] = serialize(values)
    selected = [correspondence(acquired, 'managed-new'), correspondence(acquired, 'fixture-001', '001', 'refresh')]
    stage(root, acquired, files, selected, exclusions(acquired, selected))
    before = source_files(root)
    calls = []
    original_save = sync_files.save_files
    save = _bind_framework_callback(_callback_check_mixed_add_refresh_single_publication_save, calls, fail, original_save)
    with patch.object(sync_files, 'save_files', side_effect=save):
        if fail:
            with pytest.raises(OSError, match='injected'):
                publish_fixture(root, acquired)
            assert source_files(root) == before
            assert not import_guard.proof_path(root).exists()
            import_guard.discard_acquisition(root, acquired['evidence'])
        else:
            result = publish_fixture(root, acquired)
            assert {item['resource'] for item in result['changes']} == {'001', '003'}
            values = load_model(file).authoritative
            assert values['desired.row.001-002.value'] == values['desired.row.003-002.value'] == '`90`'
    assert sum(file in output for output in calls) == 1
    assert len(cli.calls) == 2


def check_replace_warns_incoming_references(tmp_path):
    root = tmp_path / 'case'
    path = fixture(root, 'vpc')
    before = load_model(path)
    acquired = m.acquire(root, 'dev', 'vpc', TARGET, cli_runner=aws('vpc', changed=True, noise=True))
    values = dict(before.authoritative)
    values.update({'desired.row.001-002.value': '`172.16.0.0/16`', 'desired.row.001-003.value': '`unmanaged`',
                   'observed.row.001-001.value': 'vpc-00000000000000000'})
    selected = [correspondence(acquired, 'vpc-00000000000000000', '001', 'replace')]
    selected[0]['before'] = {'identity': VPC_ID, 'model': digest(operation_values(before.authoritative, '001'))}
    stage(root, acquired, {path.relative_to(root).as_posix(): serialize(values)}, selected, exclusions(acquired, selected))
    original = snapshot(root)
    _ = publish_fixture(root, acquired, 'vpc')
    reviewed = json.loads((Path(acquired['evidence']).parent / 'review.json').read_text())
    assert any(w['code'] == 'reference.replace_impact' for w in reviewed['referenceImpact']['warnings'])
    assert snapshot(root) != original
    assert load_model(path).authoritative['observed.row.001-001.value'] == 'vpc-00000000000000000'
    assert Path(acquired['evidence']).is_file()


@pytest.mark.parametrize('missing', [False, True])
@pytest.mark.parametrize('shared_template', [False, True])
def check_first_resource_uses_existing_source_format(tmp_path, missing, shared_template):
    root = tmp_path / 'case'
    path = fixture(root)
    seed = dict(load_model(path).authoritative)
    if not shared_template:
        input_file(root, env='stg').unlink()
    service = {key: value for key, value in seed.items() if key.startswith(('desired.service.', 'display.service.'))}
    if missing:
        path.unlink()
        assert not path.exists()
    else:
        path.write_text(serialize(service), encoding='utf-8')
        assert not entries(load_model(path).authoritative, 'desired.resource.')
    checkpoint(root)
    cli = aws(changed=True)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli, resource_types=['Logs.LogGroup'])
    service.update(operation_values(seed, '001'))
    del service['desired.resource.001.logicalId']
    if missing:
        service.pop('desired.service.identity.lastAllocated', None)
    service = allocate(service, ['001'])
    service['desired.row.001-002.value'] = '`90`'
    selected = [correspondence(acquired, 'fixture-001', '001')]
    stage(root, acquired, {path.relative_to(root).as_posix(): serialize(service)}, selected, exclusions(acquired, selected))
    foreign = input_file(root, env='stg')
    original = foreign.read_bytes() if foreign.is_file() else None
    result = publish_fixture(root, acquired)
    assert result['status'] == 'complete'
    assert len(entries(load_model(path).authoritative, 'desired.resource.')) == 1
    assert (foreign.read_bytes() if foreign.is_file() else None) == original
    assert len(cli.calls) == 2


def check_refresh_switches_definition_without_foreign_changes(tmp_path):
    root = tmp_path / 'case'
    file = fixture(root)
    before = source_files(root)
    values = dict(load_model(file).authoritative)
    values.update({'desired.row.001-002.value': '`90`', 'desired.row.001-004.value': '`INFREQUENT_ACCESS`'})
    cli = aws(changed=True)
    cli.logs[0]['logGroupClass'] = 'INFREQUENT_ACCESS'
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli, resource_types=['Logs.LogGroup'])
    selected = [correspondence(acquired, 'fixture-001', '001', 'refresh')]
    stage(root, acquired, {file.relative_to(root).as_posix(): serialize(values)}, selected, exclusions(acquired, selected))
    result = publish_fixture(root, acquired)
    assert result['status'] == 'complete'
    current = load_model(file).authoritative
    assert current['desired.row.001-004.value'] == '`INFREQUENT_ACCESS`'
    assert current['desired.row.002-004.value'] == '`STANDARD`'
    assert all((root / rel).read_bytes() == data for rel, data in before.items() if 'stg' in rel.parts)
    assert load_model(input_file(root, env='stg')).authoritative['desired.row.001-004.value'] == '`STANDARD`'


@pytest.mark.parametrize('tamper', ['candidate', 'sources', 'task', 'worktree', 'risk', 'legacy'])
def check_approval_bound_save_guard(tmp_path, tamper):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    publish_fixture(root, acquired)
    original = source_files(root)
    if tamper == 'candidate':
        file = input_file(root)
        raw = file.read_bytes()
        try:
            file.write_bytes(raw + b'\n# unapproved candidate bytes\n')
            with pytest.raises(ValueError, match='no verified /import evidence|differs from acquired change plan'):
                import_guard.require_import_changes(root)
        finally:
            file.write_bytes(raw)
    else:
        proof = import_guard.read_proof(root)
        if tamper == 'sources':
            name = next(iter(proof['sources']))
            proof['sources'][name] = '0' * 64
        elif tamper == 'legacy':
            proof['version'] = 3
            del proof['reviewBinding']
        else:
            proof['reviewBinding'][{'risk': 'recordsDigest'}.get(tamper, tamper)] = 'forged'
        sealed_evidence.write_sealed(root, import_guard.proof_path(root), proof)
        with pytest.raises(ValueError, match='no verified /import evidence|differs from acquired change plan'):
            import_guard.require_import_changes(root)
    assert source_files(root) == original


@pytest.mark.parametrize('failure', ['none', 'source', 'task', 'review', 'candidate', 'source-set', 'model-io', 'receipt', 'display-io', 'bind', 'replace'])
def check_properties_import_acquire_review_publish(monkeypatch, failure):
    import_publication_case(monkeypatch, failure)


@pytest.mark.parametrize('failure', [None, 'review', 'draft', 'candidate', 'acquisition', 'baseline',
                                    'approval-expired', 'source-save', 'display-save', 'task-baseline'])
def check_publication_transaction_without_host(monkeypatch, failure):
    action = {None: 'none', 'review': 'post-review', 'draft': 'post-draft', 'candidate': 'post-candidate',
              'acquisition': 'post-acquisition', 'baseline': 'post-baseline', 'approval-expired': 'post-expiry',
              'source-save': 'receipt', 'display-save': 'display-io', 'task-baseline': 'post-task'}[failure]
    import_publication_case(monkeypatch, action)


def check_saved_display_recovery_needs_no_new_approval(monkeypatch):
    import_publication_case(monkeypatch, 'display-io')


@pytest.mark.parametrize('change', ['property', 'destination', 'resource', 'selector'])
def check_candidate_review_mismatch_rejected_without_host(monkeypatch, change):
    action = {'property': 'candidate', 'destination': 'selection-target', 'resource': 'candidate-resource',
              'selector': 'candidate-reference'}[change]
    import_publication_case(monkeypatch, action)


@pytest.mark.parametrize('boundary', ['head', 'base', 'task', 'allowed', 'scope', 'target', 'unapproved-source'])
def check_gitless_guard_boundaries(tmp_path, boundary):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    review_fixture(root, acquired)
    before = source_files(root)
    task = root / 'tasks/import-fixture.md'
    if boundary == 'head':
        state(root).head = 'changed-head'
    elif boundary == 'base':
        state(root).base = 'different-start'
    elif boundary == 'task':
        task.write_text(task.read_text() + '\n## Notes\nconcurrent Task edit\n')
    elif boundary == 'allowed':
        text = task.read_text()
        prefix, allowed = text.split('## Allowed paths\n')
        allowed, rest = allowed.split('## Modified files\n')
        task.write_text(prefix + '## Allowed paths\n' + allowed.replace('- `model/dev/cde/cloudwatch-logs.properties`\n', '') + '## Modified files\n' + rest)
    elif boundary == 'scope':
        task.write_text(task.read_text().replace('- `dev/cde/cloudwatch-logs`', '- `dev/cde/vpc`'))
    elif boundary == 'target':
        task.write_text(task.read_text().replace('IMPORT target: `dev/cde/cloudwatch-logs`', 'IMPORT target: `dev/cde/vpc`'))
    if boundary == 'unapproved-source':
        assert m.publish_acquisition(root, 'dev', 'cloudwatch-logs', acquired['evidence'], TARGET)['status'] == 'complete'
        foreign = input_file(root, env='stg')
        foreign.write_bytes(foreign.read_bytes() + b'# unapproved source\n')
        saved = source_files(root)
        with pytest.raises(ValueError, match='outside Modified files/Allowed paths'):
            import_guard.require_import_changes(root)
        assert source_files(root) == saved
    else:
        with pytest.raises(ValueError, match='stale|changed|mismatched|outside|scope|target|declare'):
            m.publish_acquisition(root, 'dev', 'cloudwatch-logs', acquired['evidence'], TARGET)
        assert source_files(root) == before
        assert not (sealed_evidence.evidence_store(root) / 'import-fixture.json').exists()
    assert not (root / '.git').exists()


def check_repository_snapshot_detects_real_changes(tmp_path):
    root = tmp_path / 'case'
    path = fixture(root)
    baseline = state(root).baseline.copy()
    path.write_bytes(path.read_bytes() + b'# comment change\n')
    added = path.with_name('extra.properties')
    added.write_bytes(b'# model-format: 2\n')
    deleted = input_file(root, env='stg')
    deleted.unlink()
    task = root / 'tasks/import-fixture.md'
    task.write_text(task.read_text() + '\n# Task change\n')
    assert repository.changed_paths(root) == {p.relative_to(root).as_posix() for p in (path, added, deleted, task)}
    assert state(root).baseline == baseline


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
