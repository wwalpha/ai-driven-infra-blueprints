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
from model.core import entries
from model.format import parse, serialize
from model.operations import operation_values
from model.sources import json_text, load_model
from support.import_model_fixtures import (ACCOUNT, TARGET, SERVICES, SUBNETS, VPC_ID, AwsCli,
    aws, correspondence, exclusions, fixture, logs_edit, m, publish_fixture, review_fixture, snapshot, resource_values, stage)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('live network forbidden')))


def prepare(tmp_path, service='cloudwatch-logs', changed=True, dry_run=False):
    root = tmp_path / 'case'
    fixture(root, service, register=not dry_run)
    cli = aws(service, changed=changed)
    acquisition = m.acquire(root, 'dev', service, TARGET, dry_run, cli)
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



def check_cli_preflight(tmp_path):
    for args in [[], ['--environment', 'dev'], ['--service', 'vpc'], ['--environment', 'dev', '--service', 'vpc']]:
        command = [sys.executable, '-B', str(m.ROOT / 'framework/scripts/model/cli.py'), 'import', *args]
        assert subprocess.run(command, capture_output=True).returncode == 2
    assert not any(hasattr(m, name) for name in ('refresh', 'snapshot_values', 'snapshot_sources', 'promoted_sources'))



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
    assert all(after.authoritative[key] == value for key, value in before.authoritative.items())
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
        acquired = m.acquire(root, 'dev', service, TARGET, True, cli)
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
        subprocess.run(['git', 'add', 'model'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'unobserved fixture'], cwd=root, check=True)
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
    values['desired.resource.009.anchor'] = values['desired.resource.009.logicalId'] = 'vpc-' + name
    values['desired.row.009-001.value'] = '[009](#vpc-' + name + ')'
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
    assert all(current.authoritative[k] == v for k, v in original.authoritative.items())
    assert current.authoritative['observed.row.009-001.value'] == identity
    assert current.authoritative['desired.row.009-001.value'] == '[009](#vpc-' + name + ')'
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
    subprocess.run(['git', 'add', 'model'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'external reference fixture'], cwd=root, check=True)
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
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
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
    acquired = m.acquire(root, 'dev', service, TARGET, cli_runner=aws(service, changed=True))
    values = dict(load_model(path).authoritative)
    original = dict(values)
    for key, value in operation_values(original, '001').items():
        values[key.replace('.001', '.009', 1)] = value
    values['desired.resource.009.logicalId'] = values['desired.resource.009.anchor'] = 'added'
    if service == 'cloudwatch-logs':
        values['desired.row.009-001.value'] = '`managed-new`' if scenario == 'new' else '`fixture-001`'
        values['desired.row.009-002.value'] = '`90`'
    else:
        values['desired.row.009-001.value'] = '[009](#added)'
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
        assert all(load_model(path).authoritative[key] == value for key, value in original.items())
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
        m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
    assert not cli.calls and source_files(root) == before
    import_guard.require_import_changes(root)



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
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
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
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=aws(changed=True))
    logs_edit(root, acquired)
    new_consumer = root / 'model/dev/cde/new-consumer.properties'
    new_consumer.write_text(serialize({}), encoding='utf-8')
    before = snapshot(root)
    with pytest.raises(ValueError, match='changed|no acquired change plan'):
        publish_fixture(root, acquired)
    assert snapshot(root) == before
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
    assert 'desired.resource.003.resourceType=Logs.LogGroup' in current
    assert 'desired.row.003-002.value=`90`' in current
    assert next(iter(files.values())) == current



def check_reflection_validation_boundary(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    with patch('import_guard.changes', side_effect=AssertionError('no whole Git Model comparison')), \
         patch('model.validation.validate_required_properties', side_effect=AssertionError('no whole design validation')), \
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
    # Run the real CLI parser/entrypoint in an unpatched child, with no Host adapter.
    command = [sys.executable, '-B', str(scripts / 'model/cli.py'), 'import', 'publish', '--repository-root', str(root),
               '--environment', 'dev', '--service', 'cloudwatch-logs', '--target', 'cde',
               '--evidence', acquired['evidence']]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=True)
    report = json.loads(result.stdout)
    assert report['model'] == 'reflected' and report['markdown'] == 'generated'
    assert import_guard.read_proof(root)['complete']
    # The ignored completion receipt contains hashes, not captured configuration values.
    assert '"retentionInDays"' not in import_guard.proof_path(root).read_text(encoding='utf-8')


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
    with patch.object(m, 'view_plan', side_effect=ValueError('synthetic display failure')):
        with pytest.raises(ValueError, match='synthetic display failure'):
            publish_fixture(root, acquired)
    assert source_files(root) == before and evidence.is_file()
    actual = m._publish_transaction
    def fail_display(root, output, *args, **kwargs):
        if any(p.is_relative_to(root / 'docs/designs') for p in output):
            raise OSError('synthetic display I/O failure')
        return actual(root, output, *args, **kwargs)
    with patch.object(m, '_publish_transaction', side_effect=fail_display):
        result = publish_fixture(root, acquired)
    assert result['model'] == 'reflected' and result['markdown'] == 'failed' and result['status'] == 'display-failed'
    assert evidence.is_file()
    before = source_files(root)
    with patch.object(m, 'import_context', side_effect=AssertionError('recovery must not acquire')):
        assert m.recover_display(root, 'dev', 'cloudwatch-logs', TARGET)['status'] == 'complete'
    assert source_files(root) == before and import_guard.read_proof(root)['markdown'] == 'generated'
    assert not (root / '.blueprint').exists()




@pytest.mark.parametrize('failure', ['none', 'rollback', 'race', 'wrong-target', 'ordinary', 'ordinary-delete'])
def check_model_only_publication(tmp_path, monkeypatch, failure):
    from support.import_model_fixtures import operation_fixture, operation_candidate, operation_contract
    from support.worktree_task_fixtures import fixture, git, start
    from model import prepare_edit, publish_edit
    from model.adapters.task import source_write_context, edit_write_context
    from model.operations import verify_model_operation
    from task_contract import model_operation, status
    action = 'import-delete' if failure == 'ordinary-delete' else 'import-merge'
    with fixture() as root:
        operation_fixture(root)
        sources = operation_candidate(root, tmp_path / 'edited', action)
        candidate = {name: (tmp_path / 'edited' / name).read_text() for name in sources}
        git(root, 'add', 'model', 'project.json'); git(root, 'commit', '-qm', 'synthetic operation')
        target, state = start(root, files=tuple(sorted(sources)))
        name = state['task_file']
        contract = operation_contract(destination='stg/cde/vpc/008' if failure == 'wrong-target' else 'stg/cde/vpc/001')
        if failure in {'ordinary', 'ordinary-delete'}:
            contract = '## Task contract\n- Task type: `design`\n- Task status: `running`\n'
        contract += '\n## Required changes\n- [R1] Synthetic source candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n'
        for heading in ('Modified files', 'Allowed paths'):
            contract += '\n## ' + heading + '\n' + ''.join('- `' + item + '`\n' for item in sorted(sources | {name}))
        contract += '\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n'
        (target / name).write_text(contract)
        before = source_files(target)
        path = target / 'model/stg/cde/vpc.properties'
        if failure == 'rollback':
            def fail_save(output):
                path.write_text('partial interrupted source')
                raise OSError('injected source publication failure')
            monkeypatch.setattr(sync_files, 'save_files', fail_save)
        authority = edit_write_context(target, {('stg', TARGET, 'vpc')}, name) if failure in {'ordinary', 'ordinary-delete'} else source_write_context(target, name)
        with authority as context:
            snapshot = load_model(path, context.snapshot)
            output = {target / relative: text for relative, text in candidate.items()}
            def save():
                plan = prepare_edit(snapshot, output, context)
                if failure == 'race':
                    path.write_bytes(path.read_bytes() + b'# concurrent human input\n')
                return publish_edit(plan, context)
            if failure != 'none':
                with pytest.raises((ValueError, OSError)):
                    save()
                if failure == 'race':
                    assert path.read_bytes() == before[path.relative_to(target)] + b'# concurrent human input\n'
                else:
                    assert source_files(target) == before
            else:
                assert set(save()) == set(output)
                assert load_model(path).authoritative['observed.row.001-001.value'] == 'vpc-source'
                verify_model_operation(root, target, model_operation(contract), sources)
                assert status((target / name).read_text()) == 'running'
        assert source_files(root) == before




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
    assert sealed['version'] == 3 and not import_guard.acquisition_complete(sealed)
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
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
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
    count = len(cli.calls)
    with patch.object(m, 'import_context', side_effect=AssertionError('publish cannot acquire')):
        review_fixture(root, acquired, dry_run=True)
        result = m.publish_acquisition(root, 'dev', 'datazone', acquired['evidence'], ACCOUNT, True)
    assert result['status'] == 'dry-run' and source_files(root) == before and len(cli.calls) == count


def check_intermediate_model_sources(monkeypatch):
    import base64
    from support.worktree_task_fixtures import fixture, git, start
    from support.import_model_fixtures import operation_fixture, operation_contract
    from model import prepare_edit, publish_edit
    from model.adapters.task import source_write_context
    from model.sources import publication_lock
    with fixture() as root:
        operation_fixture(root)
        git(root, 'add', 'model', 'project.json'); git(root, 'commit', '-qm', 'model sources')
        relative = 'model/stg/cde/vpc.properties'
        target, state = start(root, files=(relative,))
        name = state['task_file']
        text = operation_contract() + '\n## Validation scope\n- `stg/cde/vpc`\n'
        for heading in ('Modified files', 'Allowed paths'):
            text += '\n## ' + heading + '\n- `' + name + '`\n- `' + relative + '`\n'
        (target / name).write_text(text)
        path = target / relative
        original = path.read_bytes()
        values = dict(load_model(path).authoritative)
        values['desired.row.001-002.comment'] = '中間保存は最終設計検証を実行しない'
        intermediate = serialize(values)
        with source_write_context(target, name) as context:
            publish_edit(prepare_edit(load_model(path, context.snapshot), {path: intermediate}, context), context)
        assert path.read_text() == intermediate
        with source_write_context(target, name) as context:
            plan = prepare_edit(load_model(path, context.snapshot), {path: original.decode()}, context)
            with patch.object(sync_files, 'save_files', side_effect=OSError('second leaf failed')):
                with pytest.raises(OSError, match='second leaf failed'):
                    publish_edit(plan, context)
        assert path.read_text() == intermediate
        assert (root / relative).read_bytes() == original
        with publication_lock(target) as journal:
            journal.write_text(json.dumps({'root': str(target.resolve()), 'originals': {relative: base64.b64encode(original).decode()}}))
            path.write_text('interrupted write')
        with pytest.raises(ValueError, match='recovery'):
            load_model(path)
        with source_write_context(target, name) as context:
            assert context.snapshot.read(path) == original
            assert publish_edit(prepare_edit(load_model(path, context.snapshot), {}, context), context) == ()
        assert path.read_bytes() == original



def check_batch_leaf_saves(monkeypatch):
    import tempfile
    from support.worktree_task_fixtures import fixture, git, start
    from support.import_model_fixtures import batch_operation_fixture
    from model import prepare_edit, publish_edit
    from model.adapters.task import source_write_context
    from model.operations import verify_model_operation
    from model.format import owner
    from task_contract import model_operation
    with fixture() as root, tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary) / 'candidate'
        contract, sources = batch_operation_fixture(root, candidate)
        git(root, 'add', 'model', 'project.json'); git(root, 'commit', '-qm', 'batch Model fixture')
        target, state = start(root, files=tuple(sorted(sources)))
        name = state['task_file']
        for heading in ('Modified files', 'Allowed paths'):
            contract += '\n## ' + heading + '\n' + ''.join('- `' + item + '`\n' for item in sorted(sources | {name}))
        contract += '\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n'
        (target / name).write_text(contract)
        path = target / 'model/stg/cde/vpc.properties'
        before = dict(load_model(path).authoritative)
        final = parse((candidate / 'model/stg/cde/vpc.properties').read_text()).values
        operation = model_operation(contract)
        deleted = {pair.source.rsplit('/', 1)[1] for pair in operation.pairs}
        transferred = dict(final)
        transferred.update({key: value for key, value in before.items() if owner(key, before) in {('resource', rid) for rid in deleted}})
        # Keep original Resource/Row order while retaining the pending source deletions.
        transferred = {key: transferred[key] for key in before if key in transferred}
        with source_write_context(target, name) as context:
            publish_edit(prepare_edit(load_model(path, context.snapshot), {path: serialize(transferred)}, context), context)
        for rid in deleted:
            assert f'desired.resource.{rid}.resourceType' in load_model(path).authoritative
        with source_write_context(target, name) as context:
            assert publish_edit(prepare_edit(load_model(path, context.snapshot), {}, context), context) == ()
        with source_write_context(target, name) as context:
            publish_edit(prepare_edit(load_model(path, context.snapshot), {path: serialize(final)}, context), context)
        for rid in deleted:
            assert f'desired.resource.{rid}.resourceType' not in load_model(path).authoritative
        verify_model_operation(root, target, operation, sources)
        assert git(root, 'rev-parse', 'HEAD') == state['start']




@pytest.mark.parametrize('present,race', [(False, False), (True, False), (True, True)])
def check_reference_publication(tmp_path, present, race):
    from collections import Counter
    from support.import_model_fixtures import CloudControlCli, small_framework, service_values, reference_fields
    from support.model_sources import write_model
    from task_contract import start
    from model.importing.scope import read_context
    import model.sources
    root = tmp_path / 'reference-publication'
    root.mkdir()
    small_framework(root, ['cloudtrail', 's3'], ['CloudTrail.Trail', 'S3.Bucket'])
    (root / 'project.json').write_text(json_text({'targets': [{'environment': 'dev', 'alias': TARGET,
        'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n')
    path = root / 'model/dev/cde/cloudtrail.properties'
    write_model(path, service_values('cloudtrail', ['CloudTrail.Trail']))
    producer = path.with_name('s3.properties')
    if present:
        write_model(producer, resource_values('001', 'S3.Bucket', 's3-audit-bucket', 'CREATE', [('BucketName', '`audit-bucket`')]))
    for args in [('init', '-q'), ('add', '.'), ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'reference fixture')]:
        subprocess.run(['git', *args], cwd=root, check=True)
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
    link = '[audit-bucket](s3.md#s3-audit-bucket)'
    if present:
        for index, (prop, actual) in enumerate(captured.items(), 1):
            key = f'desired.row.009-{index:03d}.value'
            if prop == 'CloudTrail.Trail.S3BucketName':
                values[key] = link
                values[f'observed.row.009-{index:03d}.value'] = m.model_literal(actual)
                values.update(reference_fields('bucket', key, link, 'dev/cde/s3/001', kind='S3.Bucket', mode='link', prop=None))
            elif prop == 'CloudTrail.Trail.EventSelectors[].DataResources[].Values':
                values[key] = m.model_literal([[[link]]])
                values[f'observed.row.009-{index:03d}.value'] = m.model_literal(actual)
                values.update(reference_fields('nested-bucket', key, link, 'dev/cde/s3/001', kind='S3.Bucket', mode='link', prop=None, pointer='/0/0/0'))
    for identity in ('bucket', 'nested-bucket'):
        key = 'desired.reference.' + identity + '.labelPolicy'
        if key in values:
            values[key] = 'display-name'
    selected = [correspondence(acquired, record['identity'], '009')]
    stage(root, acquired, {path.relative_to(root).as_posix(): serialize(values)}, selected)
    review_fixture(root, acquired, 'cloudtrail')
    calls = len(cli.calls)
    reads = Counter()
    original_read = model.sources._read_model
    original_finish = m.finish_import
    def counted(scope, *args, **kwargs):
        if scope.service == 's3':
            reads[read_context(root), args[0]] += 1
        return original_read(scope, *args, **kwargs)
    def finish(*args, **kwargs):
        result = original_finish(*args, **kwargs)
        if race and kwargs.get('model') == 'reflected':
            producer.write_text(producer.read_text().replace('`audit-bucket`', '`audit-bucket-raced`'))
        return result
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
    assert (link if present else '`audit-bucket`') in markdown
    assert all(p.read_bytes() == raw for p, raw in foreign.items())
    assert not (root / 'docs/designs/dev/cde/s3.md').exists()
    before_recovery = source_files(root)
    assert m.recover_display(root, 'dev', 'cloudtrail', TARGET)['status'] == 'complete'
    assert source_files(root) == before_recovery and document.read_text() == markdown



@pytest.mark.parametrize('action', ['refresh', 'replace', 'bind'])
@pytest.mark.parametrize('dry_run', [False, True])
def check_user_selected_overwrite_publication(tmp_path, action, dry_run):
    from import_guard import digest
    root = tmp_path / 'case'
    path = fixture(root, register=not dry_run)
    if action == 'bind':
        values = dict(load_model(path).authoritative)
        values['desired.row.001-001.value'] = 'UNSET'
        path.write_text(serialize(values), encoding='utf-8')
        subprocess.run(['git', 'add', 'model'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'unknown existing IMPORT identity'], cwd=root, check=True)
    cli = aws(changed=True)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, dry_run, cli)
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
        assert not (import_guard.evidence_store(root) / 'import-fixture.json').exists()
    else:
        after = load_model(path)
        assert after.authoritative['desired.row.001-002.value'] == '`90`'
        assert after.authoritative['desired.row.001-001.value'] == m.model_literal(identity)
        assert operation_values(before.authoritative, '002') == operation_values(after.authoritative, '002')
        assert len(entries(after.authoritative, 'desired.resource.')) == 2
        assert all((root / rel).read_bytes() == data for rel, data in original.items() if 'stg' in rel.parts)
        import_guard.require_import_changes(root)



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
    from import_guard import digest
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
    result = publish_fixture(root, acquired, 'vpc')
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
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic absent or empty service'], cwd=root, check=True)
    cli = aws(changed=True)
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
    service.update(operation_values(seed, '001'))
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
    acquired = m.acquire(root, 'dev', 'cloudwatch-logs', TARGET, cli_runner=cli)
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
        import_guard.write_sealed(root, import_guard.proof_path(root), proof)
        with pytest.raises(ValueError, match='no verified /import evidence|differs from acquired change plan'):
            import_guard.require_import_changes(root)
    assert source_files(root) == original



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
