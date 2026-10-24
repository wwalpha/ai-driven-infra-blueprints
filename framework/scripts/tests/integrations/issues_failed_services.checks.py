#!/usr/bin/env python3
"""Scoped KMS forms and deterministic ARN/GetAtt comparison without AWS."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import tempfile
from unittest.mock import patch

from comparison.registry import SERVICES
from issues.aggregate import aggregate, iac_actions
from issues.artifact import detail_payload, summary
from issues.records import identifier
from issues.reports import iac_report
from support import issues_scan_fixtures as fixture
from support.it_case_receipt import it_case
from support.model_sources import allocate_fixture as allocate
from support.validator import load as load

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

KMS_COMPARISON_FORMS = {key: forms for rules in set(SERVICES.values()) for key, forms in getattr(rules, "KMS_FORMS", {}).items()}


def _callback_main_checks_publish(models, root, template, /):
    for service, values in models.items():
        fixture.write(root / f'model/dev/123456789012/{service}.properties', '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
    fixture.mutate_template(root, template)


def _callback_main_checks_athena(kms, models, publish, root, row, /, model, iac, category, *, property_name='WorkGroupConfiguration'):
    models['athena'][row] = model
    kms['KmsKey'] = iac
    publish()
    current, rows = fixture.compare(root, ['athena'])
    # Incomplete references are reported on their authored leaf instead of the parent.
    record = next(r for r in rows if r.get('property') == 'Athena.WorkGroup.' + property_name)
    assert record['category'] == category, record
    assert next(r for r in rows if r.get('property') == 'Athena.WorkGroup.State')['category'] == 'matched'
    if category == 'uncompared' and record.get('reference_diagnostics'):
        assert record['reference_diagnostics'][0]['reason'], record
    return current, record


def _callback_main_checks_resource(models, stack, template, /, service, logical, kind, props, rows=()):
    values = models.setdefault(service, {f'desired.service.{service}.serviceId': service})
    values.update({f'desired.resource.{logical}.resourceType': kind,
                   f'desired.resource.{logical}.cfn-logicalId': stack + '-' + logical})
    values.update(allocate(values, [logical]))
    for index, (prop, value) in enumerate(rows, 1):
        values[f'desired.row.{logical}-{index:03d}.property'] = kind + '.' + prop
        values[f'desired.row.{logical}-{index:03d}.value'] = value
    template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': props}


def _lambda_main_checks_callback_156(comparison, /, a, b, p, *, kind):
    return comparison.reference_same(a, b, kind, p)


def _lambda_main_checks_callback_192(comparison, /, a, b, p):
    return comparison.reference_same(a, b, 'IAM.Role', p)


@it_case
def main_checks():
    with tempfile.TemporaryDirectory(prefix='failed-service-comparison-') as temporary:
        root = Path(temporary)
        _, template = fixture.fixture(root, services=('s3', 'sqs'))
        stack = 'cfn-stack-app-dev-data1'
        models = {}

        resource = _bind_framework_callback(_callback_main_checks_resource, models, stack, template)

        resource('kms', 'Key', 'KMS.Key', {})
        resource('kms', 'Alias', 'KMS.Alias', {'AliasName': 'alias/fixture', 'TargetKeyId': {'Ref': 'Key'}})
        resource('kms', 'OtherAlias', 'KMS.Alias', {'AliasName': 'alias/other', 'TargetKeyId': {'Ref': 'Key'}})
        alias_arn = 'arn:aws:kms:ap-northeast-1:123456789012:alias/fixture'
        key_id = '12345678-1234-1234-1234-123456789012'
        key_arn = 'arn:aws:kms:ap-northeast-1:123456789012:key/' + key_id
        resource('cloudwatch-logs', 'Log', 'Logs.LogGroup', {'LogGroupName': '/fixture/log', 'KmsKeyId': alias_arn},
                 [('KmsKeyId', '[KMS_Alias_001](kms.md#resource-KMS_Alias_001)')])
        resource('codebuild', 'Build', 'CodeBuild.Project', {'Name': 'fixture-build'})
        resource('eventbridge', 'Rule', 'Events.Rule', {'Name': 'fixture-rule'})
        resource('athena', 'Workgroup', 'Athena.WorkGroup', {'WorkGroupConfiguration': {'ResultConfiguration': {
            'EncryptionConfiguration': {'KmsKey': key_arn}}}},
                 [('WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey', '`' + key_arn + '`')])
        resource('codepipeline', 'Pipeline', 'CodePipeline.Pipeline', {'ArtifactStore': {'EncryptionKey': {'Id': alias_arn}}},
                 [('ArtifactStore.EncryptionKey.Id', '[KMS_Alias_001](kms.md#resource-KMS_Alias_001)')])
        resource('glue', 'Security', 'Glue.SecurityConfiguration', {'EncryptionConfiguration': {
            'S3Encryptions': [{'KmsKeyArn': alias_arn}], 'CloudWatchEncryption': {'KmsKeyArn': alias_arn}}},
                 [('EncryptionConfiguration.S3Encryptions[].KmsKeyArn', '[KMS_Alias_001](kms.md#resource-KMS_Alias_001)'),
                  ('EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn', '[KMS_Alias_001](kms.md#resource-KMS_Alias_001)')])
        # Keep the queue from the shared fixture and give the policy an explicit mapping.
        models['sqs'] = fixture.properties(fixture.read_model(root / 'model/dev/123456789012/sqs.properties'))
        policy = {'Statement': [{'Effect': 'Allow', 'Action': 'sqs:SendMessage',
                                 'Resource': {'Fn::GetAtt': ['Queue', 'Arn']}}]}
        resource('sqs', 'QueuePolicy', 'SQS.QueuePolicy', {'PolicyDocument': policy}, [('PolicyDocument', 'policy.json')])
        models['sqs']['desired.row.QueuePolicy-001.document'] = json.dumps(policy)

        publish = _bind_framework_callback(_callback_main_checks_publish, models, root, template)

        publish()
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison, records = fixture.compare(root, list(models))
            selected = [r for r in records if r['service'] in {'athena', 'cloudwatch-logs', 'codepipeline', 'glue'} or r['resource'] == 'QueuePolicy']
            assert selected and all(r['category'] == 'matched' for r in selected), selected
            # Exercise Model loading and receiving-property attribute selection, not hand-built symbols.
            path = 'WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey'
            row = 'desired.row.Workgroup-001.value'
            kms = template['Resources']['Workgroup']['Properties']['WorkGroupConfiguration']['ResultConfiguration']['EncryptionConfiguration']
            resource('kms', 'OtherKey', 'KMS.Key', {})
            template['Resources']['Workgroup']['Properties']['State'] = 'ENABLED'
            models['athena'].update({'desired.row.Workgroup-002.property': 'Athena.WorkGroup.State',
                                     'desired.row.Workgroup-002.value': '`ENABLED`'})

            athena = _bind_framework_callback(_callback_main_checks_athena, kms, models, publish, root, row)

            current, _ = athena('[KMS_Key_001](kms.md#resource-KMS_Key_001)', {'Fn::GetAtt': ['Key', 'Arn']}, 'matched')
            assert current.desired_reference('athena', '[KMS_Key_001](kms.md#resource-KMS_Key_001)', 'Athena.WorkGroup', path)['$attribute'] == 'Arn'
            athena('[KMS_Key_001](kms.md#resource-KMS_Key_001)', {'Fn::GetAtt': ['OtherKey', 'Arn']}, 'difference')
            athena('`' + key_arn + '`', key_arn, 'matched')
            athena('`' + key_arn + '`', key_arn[:-1] + '3', 'difference')
            for invalid in (key_id, 'alias/fixture', alias_arn):
                for model, iac in ((invalid, key_arn), (key_arn, invalid), (invalid, invalid)):
                    _, record = athena('`' + model + '`', iac, 'difference')
                    diagnostic = record['reference_diagnostics'][0]
                    assert diagnostic['allowed_forms'] == ['KeyArn'] and diagnostic['reason'], diagnostic
                    assert diagnostic['format']['model'] == ('allowed' if model == key_arn else 'outside allowed forms')
                    assert diagnostic['format']['iac'] == ('allowed' if iac == key_arn else 'outside allowed forms')
            _, record = athena('[KMS_Alias_001](kms.md#resource-KMS_Alias_001)', {'Fn::GetAtt': ['Key', 'Arn']}, 'uncompared', property_name=path)
            assert 'outside receiving property contract' in record['reason'], record
            athena('[KMS_Key_001](kms.md#resource-KMS_Key_001)', key_arn, 'uncompared')
            athena('`' + key_arn + '`', '{{resolve:secretsmanager:key}}', 'uncompared')
            athena('[KMS_Key_001](kms.md#resource-KMS_Key_001)', {'Fn::GetAtt': ['Key', 'Arn']}, 'matched')
            stackpath = root / 'model/dev/123456789012/cloudformation-stacks.properties'
            original_stacks = fixture.read_model(stackpath)
            fixture.write(stackpath, original_stacks + 'desired.stack.002.name=key-stack\ndesired.stack.002.template=keys.yaml\ndesired.stack.002.parameters=keys.json\ndesired.stack.002.deployOrder=1\n')
            fixture.write(root / 'infra/cloudformation/parameters/dev/123456789012/keys.json', '[]')
            fixture.write(root / 'infra/cloudformation/templates/keys.yaml', json.dumps({
                'Resources': {'Key': template['Resources']['Key'], 'OtherKey': template['Resources']['OtherKey']},
                'Outputs': {name: {'Value': {'Fn::GetAtt': [name, 'Arn']}, 'Export': {'Name': name + 'Arn'}}
                            for name in ('Key', 'OtherKey')}}))
            for name in ('Key', 'OtherKey'):
                models['kms']['desired.resource.' + name + '.cfn-logicalId'] = 'key-stack-' + name
                del template['Resources'][name]
            athena('[KMS_Key_001](kms.md#resource-KMS_Key_001)', {'Fn::ImportValue': 'KeyArn'}, 'matched')
            athena('[KMS_Key_001](kms.md#resource-KMS_Key_001)', {'Fn::ImportValue': 'OtherKeyArn'}, 'difference')
            athena('[KMS_Key_001](kms.md#resource-KMS_Key_001)', {'Fn::ImportValue': 'MissingArn'}, 'uncompared')
            # Restore the single-stack inputs for the existing other-service cases.
            fixture.write(stackpath, original_stacks)
            for name in ('Key', 'OtherKey'):
                models['kms']['desired.resource.' + name + '.cfn-logicalId'] = stack + '-' + name
                template['Resources'][name] = {'Type': 'AWS::KMS::Key', 'Properties': {}}
            athena('[KMS_Key_001](kms.md#resource-KMS_Key_001)', {'Fn::GetAtt': ['Key', 'Arn']}, 'matched')
            comparison, _ = fixture.compare(root, list(models))
            template['Resources']['Log']['Properties']['KmsKeyId'] = key_arn
            publish()
            _, records = fixture.compare(root, ['cloudwatch-logs'])
            mismatch = next(r for r in records if r['property'] == 'Logs.LogGroup.KmsKeyId')
            assert mismatch['category'] == 'difference' and mismatch['reference_diagnostics']
            action = iac_actions([{'id': identifier(mismatch), 'record': mismatch, 'retained': False}], 'dev', '123456789012')[0]
            assert action['classification'] == 'KMS指定形式違反' and action['status'] == '要対応', action

            for invalid in [('Missing', 'Arn'), ('Queue', 'MissingAttribute')]:
                policy['Statement'][0]['Resource'] = {'Fn::GetAtt': list(invalid)}
                models['sqs']['desired.row.QueuePolicy-001.document'] = json.dumps(policy)
                publish()
                _, records = fixture.compare(root, ['sqs'])
                assert any(r['resource'] == 'QueuePolicy' and r['category'] == 'uncompared' for r in records), records
            policy['Statement'][0]['Resource'] = {'Fn::GetAtt': ['Queue', 'Arn']}
            models['sqs']['desired.row.QueuePolicy-001.document'] = json.dumps(policy)
            template['Resources']['Queue']['Condition'] = 'Active'
            template['Conditions']['Active'] = {'Fn::Equals': ['no', 'yes']}
            publish()
            _, records = fixture.compare(root, ['sqs'])
            assert any(r['resource'] == 'QueuePolicy' and r['category'] == 'uncompared' for r in records), records
    print('Failed service comparison: PASS (scoped forms, alias ownership, physical uncertainty, ARN expressions, valid/invalid GetAtt, unchanged other services)')


@it_case
def check_incomplete_setting_artifact():
    with tempfile.TemporaryDirectory(prefix='incomplete-comparison-') as temporary:
        root = Path(temporary)
        _, template = fixture.fixture(root, services=('s3',))
        models = {}
        stack = 'cfn-stack-app-dev-data1'
        resource = _bind_framework_callback(_callback_main_checks_resource, models, stack, template)
        resource('kms', 'Alias', 'KMS.Alias', {'AliasName': 'alias/fixture'}, [('AliasName', '`alias/fixture`')])
        resource('codebuild', 'Build', 'CodeBuild.Project', {}, [
            ('Environment.EnvironmentVariables[1].Name', '`RELEASE_BUCKET_KMS_KEY_ID`'),
            ('Environment.EnvironmentVariables[1].Type', '`PLAINTEXT`'),
            ('Environment.EnvironmentVariables[1].Value', '[alias](kms.md#resource-KMS_Alias_001)'),
            ('Environment.EnvironmentVariables[2].Name', '`SECRET_TOKEN`'),
            ('Environment.EnvironmentVariables[2].Value', '`fixture-sensitive-value`'),
            ('Environment.PrivilegedMode', '`invalid-json`')])
        publish = _bind_framework_callback(_callback_main_checks_publish, models, root, template)
        for missing_parent in (False, True):
            template['Resources']['Build']['Properties'] = {} if missing_parent else {'Environment': {'EnvironmentVariables': []}}
            publish()
            with patch('socket.socket', side_effect=AssertionError('network forbidden')):
                comparison, records = fixture.compare(root, ['codebuild'])
            data = aggregate(records, 'dev', '123456789012', ['codebuild'], comparison.display_differences,
                             redact=comparison.redacted)
            artifact = dict(version=2, **data)
            counts = data['overview']['records']
            assert counts == dict(difference=1, uncompared=1, error=1, matched=0, excluded=0), records
            assert summary(artifact)['iac_differences'] == 1 and summary(artifact)['iac_errors'] == 1
            detail = detail_payload(artifact, 'iac')['items']
            difference = next(item for item in detail if item['category'] == 'difference')
            unresolved = next(item for item in detail if item['category'] == 'uncompared')
            assert difference['property'] == 'CodeBuild.Project.Environment'
            assert difference['model']['path'] == 'model/dev/123456789012/codebuild.properties'
            assert difference['model']['line'] > 0 and difference['iac']['line'] > 0
            assert difference['iac']['path'] == 'infra/cloudformation/templates/shared.yaml'
            assert 'explicit attribute' in unresolved['reason']
            assert unresolved['model']['line'] > 0 and unresolved['iac']['path'].endswith('shared.yaml')
            assert {child['category'] for child in difference['deferred_children']} == {'error', 'uncompared'}
            assert difference['value_differences'] and all(field['iac'] == '欠落' for field in difference['value_differences'])
            report = iac_report('dev', '123456789012', ['codebuild'], data['iac'], artifact=artifact)
            assert '差分 1件 / 未比較 1項目 / 処理エラー 1項目' in report
            assert '相違項目:' in report and 'Environment' in report and 'RELEASE_BUCKET_KMS_KEY_ID' in report
            serialized = json.dumps(artifact, ensure_ascii=False) + report
            assert 'fixture-sensitive-value' not in serialized and '$operands' not in serialized
            print('Incomplete fixture:', json.dumps(counts), difference['reason'], difference['value_differences'])


@it_case
def check_iac_partial_error_artifact():
    with tempfile.TemporaryDirectory(prefix='iac-partial-comparison-') as temporary:
        root = Path(temporary)
        _, template = fixture.fixture(root, services=('s3',))
        models = {}
        stack = 'cfn-stack-app-dev-data1'
        resource = _bind_framework_callback(_callback_main_checks_resource, models, stack, template)
        resource('kms', 'Alias', 'KMS.Alias', {'AliasName': 'alias/fixture'}, [('AliasName', '`alias/fixture`')])
        resource('codebuild', 'Build', 'CodeBuild.Project', {'Environment': {
            'Image': 'WRONG_IMAGE', 'EnvironmentVariables': [
                {'Name': 'RELEASE_BUCKET_KMS_KEY_ID', 'Type': 'PARAMETER_STORE',
                 'Value': {'Fn::Select': [2, ['only']]}},
                {'Name': 'SECRET_TOKEN', 'Value': 'fixture-sensitive-value'}]}}, [
            ('Environment.Image', '`GOOD_IMAGE`'),
            ('Environment.EnvironmentVariables[1].Name', '`RELEASE_BUCKET_KMS_KEY_ID`'),
            ('Environment.EnvironmentVariables[1].Type', '`PLAINTEXT`'),
            ('Environment.EnvironmentVariables[1].Value', '[alias](kms.md#resource-KMS_Alias_001)'),
            ('Environment.EnvironmentVariables[2].Name', '`SECRET_TOKEN`'),
            ('Environment.EnvironmentVariables[2].Value', '`fixture-sensitive-value`')])
        _callback_main_checks_publish(models, root, template)
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison, records = fixture.compare(root, ['codebuild'])
        data = aggregate(records, 'dev', '123456789012', ['codebuild'], comparison.display_differences,
                         redact=comparison.redacted)
        artifact = dict(version=2, **data)
        counts = data['overview']['records']
        detail = detail_payload(artifact, 'iac')['items']
        report = iac_report('dev', '123456789012', ['codebuild'], data['iac'], artifact=artifact)
        serialized = json.dumps(artifact, ensure_ascii=False) + report
        assert 'fixture-sensitive-value' not in serialized and '<masked>' in serialized
        print('IaC partial fixture:', json.dumps(dict(counts=counts, summary=summary(artifact), detail=detail), ensure_ascii=False))
        print(report)
        assert counts == dict(difference=1, uncompared=1, error=1, matched=0, excluded=0), records
        assert summary(artifact)['iac_differences'] == 1 and summary(artifact)['iac_errors'] == 1
        difference = next(item for item in detail if item['category'] == 'difference')
        unresolved = next(item for item in detail if item['category'] == 'uncompared')
        error = next(item for item in detail if item['category'] == 'error')
        assert {field['path'] for field in difference['value_differences']} == {
            'Image', 'EnvironmentVariables[0].Type'}
        assert 'explicit attribute' in unresolved['reason']
        assert error['property'].endswith('#/EnvironmentVariables/0/Value')
        assert error['iac']['pointer'] == '/EnvironmentVariables/0/Value'
        for item in (difference, error):
            assert item['model']['line'] > 0 and item['iac']['line'] > 0
            assert item['model']['path'] == 'model/dev/123456789012/codebuild.properties'
            assert item['iac']['path'] == 'infra/cloudformation/templates/shared.yaml'
        assert '差分 1件 / 未比較 1項目 / 処理エラー 1項目' in report
        assert '相違項目:' in report and 'Image' in report and 'EnvironmentVariables[0].Type' in report


if __name__ == '__main__':
    from support.model_sources import catalog_display
    with catalog_display():
        main_checks()
        check_incomplete_setting_artifact()
        check_iac_partial_error_artifact()
