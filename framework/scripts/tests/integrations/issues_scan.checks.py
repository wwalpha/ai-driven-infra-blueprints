#!/usr/bin/env python3
"""Seven real Issues boundaries; branch matrices live in the existing unit suites."""

import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from comparison import Comparison
from issue_gate import issue_errors
from issues.aggregate import aggregate, iac_dataset, iac_summary
from issues.artifact import detail_payload, summary
from issues.records import identifier
from issues.reports import iac_report
from support.issues_scan_fixtures import (
    ROOT,
    compare,
    fixture,
    mutate_template,
    review_for,
    save,
    save_scan,
    scan,
    task,
    write,
)
from support.issues_scan_fixtures import (
    protected_sources as protected_sources,
)
from support.issues_scan_fixtures import pytestmark as pytestmark
from support.model_sources import allocate_fixture as allocate
from support.model_sources import write_model
from support.pytest_cli import run

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_scan_publish_mismatch(tmp_path):
    root = tmp_path / 'project'
    _, template = fixture(root, services=['s3'])
    template['Resources']['Bucket']['Properties']['BucketName'] = 'changed-bucket'
    mutate_template(root, template)
    with patch('socket.socket', side_effect=AssertionError('network forbidden')):
        artifact = json.loads(json.dumps(scan(root, 'dev', '123456789012', ['s3'], fresh=True, jobs=1)))
    mismatch = next(item for item in artifact['iac'] if item['reason'] == 'value mismatch')
    assert artifact['version'] == 2 and artifact['checks'] > 0
    assert artifact['cfn_lint']['status'] == 'checked'
    assert len(artifact['cfn_lint']['jobs']) == 1 and artifact['cfn_lint']['jobs'][0]['completed']
    assert artifact['metrics']['template_decodes'] == 1
    assert not artifact['ordinary'] and not artifact['processing_errors']
    assert {item['service'] for item in artifact['naming']['names']} == {'s3'}
    with task(root, ['s3']):
        contract = (root / 'tasks/save.md').read_bytes()
        with patch.object(Comparison, 'run', side_effect=AssertionError('save must not compare')), \
             patch('issues.cfn_lint.run_lint', side_effect=AssertionError('save must not lint')), \
             patch('issues.aggregate.iac_dataset', side_effect=AssertionError('save must not aggregate')):
            paths = save_scan(root, artifact, review_for(artifact))
        assert all(path.is_file() for path in paths)
        assert (root / 'tasks/save.md').read_bytes() == contract
        before = {path: path.read_bytes() for path in paths}
        template_path = root / 'infra/cloudformation/templates/shared.yaml'
        template_path.write_bytes(template_path.read_bytes() + b'\n')
        with pytest.raises(ValueError, match='stale scan'):
            save_scan(root, artifact, review_for(artifact))
        assert {path: path.read_bytes() for path in paths} == before
    report = paths[1].read_text(encoding='utf-8')
    assert 'changed-bucket' in report and 'bucket-app-dev-data1' in report
    assert '<!-- iac-report-data:' not in report
    group = next(group for group in artifact['iac_issues'] if group['category'] == '要判断')
    assert detail_payload(artifact, 'iac', issue_id=group['id'])['items'][0]['value_differences'] == artifact['iac_display'][identifier(mismatch)]
    assert summary(artifact)['iac_differences'] == 1
    assert not issue_errors(root, {('dev', '123456789012', 's3')})


def fail_second_report(state, original, source, destination):
    if Path(destination).name == 'iac-issues.md' and not state.failed:
        state.failed = True
        original(source, destination)
        raise OSError('fixture publication failure')
    return original(source, destination)


def check_save_scope_and_rollback(tmp_path):
    root = tmp_path / 'project'
    record = dict(category='difference', service='s3', resource='001', property='S3.Bucket.Setting',
                  reason='value mismatch', stack='stack1', desired=1, actual=2)
    with task(root, ['s3', 'sqs']):
        outputs = save(root, 'dev', '123456789012', ['s3', 'sqs'],
            additions=[{'service': 'sqs', 'message': 'human確認: unresolved queue issue'}],
            iac=[record, dict(record, service='sqs')])
    with task(root, ['s3']):
        save(root, 'dev', '123456789012', ['s3'], iac=[record])
        report = outputs[1].read_text(encoding='utf-8')
        assert 'sqs / 001' not in report and '対象外Serviceは今回未検証' in report
        assert issue_errors(root, {('dev', '123456789012', 'sqs')})
        assert not issue_errors(root, {('dev', '123456789012', 's3')})
        before = {path: path.read_bytes() for path in outputs}
        state = SimpleNamespace(failed=False)
        with patch('utils.file_operations.os.replace', side_effect=partial(fail_second_report, state, os.replace)):
            with pytest.raises(OSError, match='publication failure'):
                save(root, 'dev', '123456789012', ['s3'], additions=[{'service': 's3', 'message': 'new issue'}], iac=[])
        assert state.failed and {path: path.read_bytes() for path in outputs} == before
        assert set(outputs[0].parent.iterdir()) == set(outputs)
    assert 'human確認: unresolved queue issue' in outputs[0].read_text(encoding='utf-8')


def check_cli_save_results(tmp_path):
    root = tmp_path / 'project'
    for service in ('s3', 'sqs'):
        result_file = tmp_path / (service + '.json')
        write(result_file, json.dumps({'issues': [{'service': service, 'message': 'cli-' + service}]}))
        with task(root, [service], name='save-' + service):
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'framework/scripts/issues_scan.py'),
                '--repository-root', str(root), '--task-file', 'tasks/save-' + service + '.md',
                'save-results', '--environment', 'dev', '--target-directory', '123456789012',
                '--service', service, '--results', str(result_file)], capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr + result.stdout
            assert '`running`' in (root / ('tasks/save-' + service + '.md')).read_text(encoding='utf-8')
    report = (root / 'issues/dev/123456789012/issues.md').read_text(encoding='utf-8')
    assert 'cli-s3' in report and 'cli-sqs' in report


def check_detail_cli(tmp_path):
    records = [dict(category='uncompared', service='s3', resource=str(i), property='Setting',
        reason='Export unresolved', cause={'kind': 'import-unresolved', 'export': 'shared', 'relationship': 'import'}) for i in range(3)]
    artifact = dict(version=2, environment='dev', target='team', services=['s3'],
                    **aggregate(records, 'dev', 'team', ['s3']))
    file = tmp_path / 'artifact.json'
    write(file, json.dumps(artifact))
    group = artifact['iac_issues'][0]
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'framework/scripts/issues_scan.py'), 'detail',
        '--artifact', str(file), '--section', 'iac', '--issue-id', group['id'], '--offset', '1', '--limit', '1'],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == detail_payload(artifact, 'iac', offset=1, limit=1, issue_id=group['id'])


def check_cloudtrail_comparison(tmp_path):
    root = tmp_path / 'project'
    _, template = fixture(root, services=[])
    kind = 'CloudTrail.Trail'
    model = {'desired.service.cloudtrail.serviceId': 'cloudtrail',
             'desired.resource.001.resourceType': kind,
             'desired.resource.001.cfn-logicalId': 'cfn-stack-app-dev-data1-Trail'}
    model.update(allocate(model, ['001']))
    fields = [('IsLogging', '`true`'), ('EventSelectors[].IncludeManagementEvents', '`false`'),
              ('EventSelectors[].DataResources[].Type', '`AWS::S3::Object`'),
              ('EventSelectors[].DataResources[].Values', '`["arn:aws:s3:::fixture/","arn:aws:s3:::fixture/"]`')]
    for number, (prop, value) in enumerate(fields, 1):
        model.update({f'desired.row.001-{number:03d}.property': kind + '.' + prop,
                      f'desired.row.001-{number:03d}.value': value})
    write_model(root / 'model/dev/123456789012/cloudtrail.properties', model)
    template['Resources'] = {'Trail': {'Type': 'AWS::CloudTrail::Trail', 'Properties': {'IsLogging': True,
        'EventSelectors': [{'IncludeManagementEvents': False, 'DataResources': [
            {'Type': 'AWS::S3::Object', 'Values': ['arn:aws:s3:::fixture/', 'arn:aws:s3:::fixture/']}]}]}}}
    mutate_template(root, template)
    _, records = compare(root, ['cloudtrail'])
    assert len(records) == 2 and all(item['category'] == 'matched' for item in records), records
    assert {item['property'] for item in records} == {kind + '.IsLogging', kind + '.EventSelectors'}


def check_cross_service_reference(tmp_path):
    root = tmp_path / 'project'
    values, template = fixture(root, stacks=2, services=['cloudwatch-logs'])
    model = values['cloudwatch-logs']
    model.update({'desired.row.001-010.property': 'Logs.LogGroup.KmsKeyId',
                  'desired.row.001-010.value': '[Key](kms.md#resource-KMS_Key_001)'})
    write_model(root / 'model/dev/123456789012/cloudwatch-logs.properties', model)
    kms = {'desired.service.kms.serviceId': 'kms', 'desired.resource.001.resourceType': 'KMS.Key',
           'desired.resource.001.cfn-logicalId': 'cfn-stack-app-dev-data2-Key'}
    kms.update(allocate(kms, ['001']))
    write_model(root / 'model/dev/123456789012/kms.properties', kms)
    template['Resources']['Key'] = {'Type': 'AWS::KMS::Key', 'Properties': {}}
    template['Outputs'] = {'KeyArn': {'Value': {'Fn::GetAtt': ['Key', 'Arn']},
                                    'Export': {'Name': {'Fn::Sub': '${Name}-KeyArn'}}}}
    template['Resources']['Log']['Properties']['KmsKeyId'] = {'Fn::ImportValue': 'app-dev-data2-KeyArn'}
    mutate_template(root, template)
    source = root / 'model/dev/123456789012/kms.properties'
    before = source.read_bytes()
    comparison, records = compare(root, ['cloudwatch-logs'])
    record = next(item for item in records if item['property'] == 'Logs.LogGroup.KmsKeyId')
    assert record['category'] == 'matched', records
    assert not any(item['category'] in {'difference', 'uncompared', 'error'} for item in records), records
    assert comparison.metrics['model_parses'] == 3
    assert comparison.evaluate('cfn-stack-app-dev-data1', {'Fn::ImportValue': 'app-dev-data2-KeyArn'}) == comparison.reference('cloudwatch-logs', model['desired.row.001-010.value'], 'Arn')
    assert comparison.metrics['template_decodes'] == 1 and comparison.metrics['stack_evaluations'] == 2
    assert source.read_bytes() == before


def check_condition_provenance(tmp_path):
    root = tmp_path / 'project'
    _, template = fixture(root, services=['s3'])
    template['Parameters']['Enable'] = {'Type': 'String', 'Default': 'true'}
    template['Conditions']['IsEnabled'] = {'Fn::Equals': [{'Ref': 'Enable'}, 'true']}
    template['Resources']['Bucket']['Condition'] = 'IsEnabled'
    mutate_template(root, template)
    parameters = root / 'infra/cloudformation/parameters/dev/123456789012/stack-1.json'
    write(parameters, json.dumps([{'ParameterKey': 'Name', 'ParameterValue': 'app-dev-data1'},
                                  {'ParameterKey': 'Enable', 'ParameterValue': 'false'}]))
    _, records = compare(root, ['s3'])
    assert len(records) == 1 and records[0]['category'] == 'difference', records
    record = records[0]
    cause = record['cause']
    assert cause['kind'] == 'condition-disabled' and cause['result'] is False
    assert cause['stack'] == record['stack'] == 'cfn-stack-app-dev-data1' and cause['logical'] == 'Bucket'
    assert record['iac']['line'] > 0 and record['iac']['key'] == 'Resources.Bucket.Condition'
    assert cause['inputs'] == [{'name': 'Enable', 'value': 'false', 'source': {
        'kind': 'parameter-file', 'path': parameters.relative_to(root).as_posix(), 'key': 'ParameterKey=Enable'}}]
    stats = iac_summary(records, 'dev', '123456789012', ['s3'])
    assert stats['issue_count'] == stats['proven_causes'] == 1 and stats['categories']['要判断'] == 1
    report = iac_report('dev', '123456789012', ['s3'], records)
    assert '意図的な無効化か設計との不整合か' in report and 'parameter-file' in report and 'stack-1.json' in report
    _, actions, _ = iac_dataset(records, 'dev', '123456789012', ['s3'])
    assert actions[0]['classification'] == 'ConditionによるCREATE無効化'
    artifact = dict(version=2, environment='dev', target='123456789012', services=['s3'],
                    **aggregate(records, 'dev', '123456789012', ['s3']))
    assert detail_payload(artifact, 'iac', issue_id=actions[0]['id'])['items'][0]['cause'] == cause


if __name__ == '__main__':
    raise SystemExit(run(__file__))
