#!/usr/bin/env python3
"""Scoped KMS forms and deterministic ARN/GetAtt comparison without AWS."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

import json
import tempfile
from unittest.mock import patch

from iac_values import Expression, same
from issues_iac import KMS_COMPARISON_FORMS
from issues_reports import iac_actions, identifier
from support.validator import load


@it_case
def main_checks():
    from support import issues_scan_fixtures as fixture
    with tempfile.TemporaryDirectory(prefix='failed-service-comparison-') as temporary:
        root = Path(temporary)
        _, template = fixture.fixture(root, services=('s3', 'sqs'))
        stack = 'cfn-stack-app-dev-data1'
        models = {}

        def resource(service, logical, kind, props, rows=()):
            values = models.setdefault(service, {f'desired.service.{service}.serviceId': service})
            values.update({f'desired.resource.{logical}.resourceType': kind,
                           f'desired.resource.{logical}.cfn-logicalId': stack + '-' + logical})
            from model.identity import allocate
            values.update(allocate(values, [logical]))
            for index, (prop, value) in enumerate(rows, 1):
                values[f'desired.row.{logical}-{index:03d}.property'] = kind + '.' + prop
                values[f'desired.row.{logical}-{index:03d}.value'] = value
            template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': props}

        resource('kms', 'Key', 'KMS.Key', {})
        resource('kms', 'Alias', 'KMS.Alias', {'AliasName': 'alias/fixture', 'TargetKeyId': {'Ref': 'Key'}})
        resource('kms', 'OtherAlias', 'KMS.Alias', {'AliasName': 'alias/other', 'TargetKeyId': {'Ref': 'Key'}})
        alias_arn = 'arn:aws:kms:ap-northeast-1:123456789012:alias/fixture'
        key_id = '12345678-1234-1234-1234-123456789012'
        key_arn = 'arn:aws:kms:ap-northeast-1:123456789012:key/' + key_id
        resource('cloudwatch-logs', 'Log', 'Logs.LogGroup', {'LogGroupName': '/fixture/log', 'KmsKeyId': alias_arn},
                 [('KmsKeyId', 'resource://dev/123456789012/kms/KMS_Alias_001')])
        resource('codebuild', 'Build', 'CodeBuild.Project', {'Name': 'fixture-build'})
        resource('eventbridge', 'Rule', 'Events.Rule', {'Name': 'fixture-rule'})
        resource('athena', 'Workgroup', 'Athena.WorkGroup', {'WorkGroupConfiguration': {'ResultConfiguration': {
            'EncryptionConfiguration': {'KmsKey': key_arn}}}},
                 [('WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey', '`' + key_arn + '`')])
        resource('codepipeline', 'Pipeline', 'CodePipeline.Pipeline', {'ArtifactStore': {'EncryptionKey': {'Id': alias_arn}}},
                 [('ArtifactStore.EncryptionKey.Id', 'resource://dev/123456789012/kms/KMS_Alias_001')])
        resource('glue', 'Security', 'Glue.SecurityConfiguration', {'EncryptionConfiguration': {
            'S3Encryptions': [{'KmsKeyArn': alias_arn}], 'CloudWatchEncryption': {'KmsKeyArn': alias_arn}}},
                 [('EncryptionConfiguration.S3Encryptions[].KmsKeyArn', 'resource://dev/123456789012/kms/KMS_Alias_001'),
                  ('EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn', 'resource://dev/123456789012/kms/KMS_Alias_001')])
        # Keep the queue from the shared fixture and give the policy an explicit mapping.
        models['sqs'] = fixture.properties(fixture.read_model(root / 'model/dev/123456789012/sqs.properties'))
        policy = {'Statement': [{'Effect': 'Allow', 'Action': 'sqs:SendMessage',
                                 'Resource': {'Fn::GetAtt': ['Queue', 'Arn']}}]}
        resource('sqs', 'QueuePolicy', 'SQS.QueuePolicy', {'PolicyDocument': policy}, [('PolicyDocument', 'policy.json')])
        models['sqs']['desired.row.QueuePolicy-001.document'] = json.dumps(policy)

        def publish():
            for service, values in models.items():
                fixture.write(root / f'model/dev/123456789012/{service}.properties', '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
            fixture.mutate_template(root, template)

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

            def athena(model, iac, category):
                models['athena'][row] = model
                kms['KmsKey'] = iac
                publish()
                current, rows = fixture.compare(root, ['athena'])
                # WorkGroupConfiguration is compared as one structured property.
                record = next(r for r in rows if r.get('property') == 'Athena.WorkGroup.WorkGroupConfiguration')
                assert record['category'] == category, record
                assert next(r for r in rows if r.get('property') == 'Athena.WorkGroup.State')['category'] == 'matched'
                if category == 'uncompared' and record.get('reference_diagnostics'):
                    assert record['reference_diagnostics'][0]['reason'], record
                return current, record

            current, _ = athena('resource://dev/123456789012/kms/KMS_Key_001', {'Fn::GetAtt': ['Key', 'Arn']}, 'matched')
            assert current.desired_reference('athena', 'resource://dev/123456789012/kms/KMS_Key_001', 'Athena.WorkGroup', path)['$attribute'] == 'Arn'
            athena('resource://dev/123456789012/kms/KMS_Key_001', {'Fn::GetAtt': ['OtherKey', 'Arn']}, 'difference')
            athena('`' + key_arn + '`', key_arn, 'matched')
            athena('`' + key_arn + '`', key_arn[:-1] + '3', 'difference')
            for invalid in (key_id, 'alias/fixture', alias_arn):
                for model, iac in ((invalid, key_arn), (key_arn, invalid), (invalid, invalid)):
                    _, record = athena('`' + model + '`', iac, 'difference')
                    diagnostic = record['reference_diagnostics'][0]
                    assert diagnostic['allowed_forms'] == ['KeyArn'] and diagnostic['reason'], diagnostic
                    assert diagnostic['format']['model'] == ('allowed' if model == key_arn else 'outside allowed forms')
                    assert diagnostic['format']['iac'] == ('allowed' if iac == key_arn else 'outside allowed forms')
            athena('resource://dev/123456789012/kms/KMS_Alias_001', {'Fn::GetAtt': ['Key', 'Arn']}, 'difference')
            athena('resource://dev/123456789012/kms/KMS_Key_001', key_arn, 'uncompared')
            athena('`' + key_arn + '`', '{{resolve:secretsmanager:key}}', 'uncompared')
            athena('resource://dev/123456789012/kms/KMS_Key_001', {'Fn::GetAtt': ['Key', 'Arn']}, 'matched')
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
            athena('resource://dev/123456789012/kms/KMS_Key_001', {'Fn::ImportValue': 'KeyArn'}, 'matched')
            athena('resource://dev/123456789012/kms/KMS_Key_001', {'Fn::ImportValue': 'OtherKeyArn'}, 'difference')
            athena('resource://dev/123456789012/kms/KMS_Key_001', {'Fn::ImportValue': 'MissingArn'}, 'uncompared')
            # Restore the single-stack inputs for the existing other-service cases.
            fixture.write(stackpath, original_stacks)
            for name in ('Key', 'OtherKey'):
                models['kms']['desired.resource.' + name + '.cfn-logicalId'] = stack + '-' + name
                template['Resources'][name] = {'Type': 'AWS::KMS::Key', 'Properties': {}}
            athena('resource://dev/123456789012/kms/KMS_Key_001', {'Fn::GetAtt': ['Key', 'Arn']}, 'matched')
            comparison, _ = fixture.compare(root, list(models))
            key = comparison.evaluate(stack, {'Ref': 'Key'})
            arn = comparison.evaluate(stack, {'Fn::GetAtt': ['Key', 'Arn']})
            alias = comparison.reference('kms', 'resource://dev/123456789012/kms/KMS_Alias_001')
            for prop, allowed in KMS_COMPARISON_FORMS.items():
                kind, path = '.'.join(prop.split('.')[:2]), '.'.join(prop.split('.')[2:])
                callback = lambda a, b, p: comparison.reference_same(a, b, kind, p)
                for form, literal in [('KeyId', key_id), ('KeyArn', key_arn), ('AliasName', 'alias/fixture'), ('AliasArn', alias_arn)]:
                    assert same(literal, literal, reference=callback, path=path) is (form in allowed), (prop, form)
                assert same(key, arn, reference=callback, path=path) is False
                assert same('not-a-key', 'not-a-key', reference=callback, path=path) is False
                assert same('{{resolve:secretsmanager:key}}', alias_arn if 'AliasArn' in allowed else key_arn,
                            reference=callback, path=path) is None
                assert same(key_arn, alias_arn, reference=callback, path=path) is False
                assert same(alias_arn, key_arn, reference=callback, path=path) is False
                if allowed <= {'KeyArn', 'AliasArn'}:
                    symbolic = comparison.desired_reference('kms', 'resource://dev/123456789012/kms/KMS_Alias_001', kind, path)
                    assert symbolic['$attribute'] == 'AliasArn'
                    assert same(symbolic, arn, reference=callback, path=path) is False
                    assert same(arn, symbolic, reference=callback, path=path) is False
                    assert same(symbolic, alias_arn, reference=callback, path=path) is ('AliasArn' in allowed)
                    assert same(alias_arn, symbolic, reference=callback, path=path) is ('AliasArn' in allowed)
                    assert same(symbolic, alias_arn.replace('123456789012', '999999999999'), reference=callback, path=path) is False
                    assert same(symbolic, alias_arn.replace('ap-northeast-1', 'us-east-1'), reference=callback, path=path) is False
                    assert same(symbolic, alias, reference=callback, path=path) is False
                    other = comparison.desired_reference('kms', 'resource://dev/123456789012/kms/KMS_Alias_002', kind, path)
                    assert same(symbolic, other, reference=callback, path=path) is False
                else:
                    assert same(arn, key_arn, reference=callback, path=path) is None
                    assert same(key, key_arn, reference=callback, path=path) is False
                    assert same(key_id, key_id[:-1] + '3', reference=callback, path=path) is False

            # Existing contracts outside this repair are deliberately unchanged.
            assert comparison.reference_same(alias, alias, 'CloudTrail.Trail', 'KMSKeyId') is True
            assert comparison.reference_same(key, arn, 'MWAA.Environment', 'KmsKey') is True
            assert comparison.reference_same(alias, alias, 'SecretsManager.Secret', 'KmsKeyId') is True
            assert comparison.reference_same(alias, alias, 'S3.Bucket', 'BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID') is True

            for logical, expected in [('Log', 'arn:aws:logs:ap-northeast-1:123456789012:log-group:/fixture/log:*'),
                                      ('Build', 'arn:aws:codebuild:ap-northeast-1:123456789012:project/fixture-build'),
                                      ('Rule', 'arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule')]:
                symbol = comparison.evaluate(stack, {'Fn::GetAtt': [logical, 'Arn']})
                callback = lambda a, b, p: comparison.reference_same(a, b, 'IAM.Role', p)
                assert same(symbol, expected, reference=callback)
                assert same(expected, symbol, reference=callback)
                assert same(symbol, expected + '-wrong', reference=callback) is False
                expression = Expression('Sub', ['${Resource}', {'Resource': symbol}])
                assert same(expression, expected, reference=callback)
            log = comparison.evaluate(stack, {'Fn::GetAtt': ['Log', 'Arn']})
            expression = Expression('Select', [0, Expression('Split', [':*', log])])
            assert comparison.reference_same(expression, 'arn:aws:logs:ap-northeast-1:123456789012:log-group:/fixture/log', 'IAM.Role', '') is True
            assert comparison.reference_same(Expression('Select', [9, Expression('Split', [':*', log])]), 'x', 'IAM.Role', '') is None
            rule = comparison.evaluate(stack, {'Fn::GetAtt': ['Rule', 'Arn']})
            comparison.stack_inputs[stack][0]['Resources']['Rule']['Properties']['EventBusName'] = 'other-bus'
            assert comparison.reference_same(rule, 'arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule', 'Lambda.Permission', 'SourceArn') is None
            comparison.stack_inputs[stack][0]['Resources']['Build']['Properties'].pop('Name')
            build = comparison.evaluate(stack, {'Fn::GetAtt': ['Build', 'Arn']})
            assert comparison.reference_same(build, 'arn:aws:codebuild:ap-northeast-1:123456789012:project/fixture-build', 'IAM.Role', '') is None
            # Neither a fake Alias GetAtt nor a generated key ARN is synthesized.
            with fixture.pytest.raises(KeyError, match='KMS.Alias.Arn'):
                comparison.evaluate(stack, {'Fn::GetAtt': ['Alias', 'Arn']})
            fixture.expect_error(lambda: comparison.reference_literal(arn), 'explicit name')

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


if __name__ == '__main__':
    from support.model_sources import catalog_display
    with catalog_display():
        main_checks()
