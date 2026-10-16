#!/usr/bin/env python3
"""IAM Action forms and proven local S3 ARN/Sub equality without weakening JSON."""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from iac_values import Expression, ResourceReference, same, selected_same
from issues_reports import identifier
from script_loader import module


def main_checks():
    fixtures = module('issues_scan.checks.py', 'policy_equivalence_fixtures')
    with tempfile.TemporaryDirectory(prefix='policy-equivalence-') as temporary:
        root = Path(temporary) / 'project'
        _, template = fixtures.fixture(root, stacks=2, services=('s3',))
        consumer, producer = 'cfn-stack-app-dev-data1', 'cfn-stack-app-dev-data2'
        arn = 'arn:aws:s3:::bucket-app-dev-data2'
        policy = {'Version': '2012-10-17', 'Statement': [
            {'Effect': 'Allow', 'Action': 's3:GetBucketLocation', 'Resource': arn},
            {'Effect': 'Allow', 'Action': 's3:ListBucket', 'Resource': arn,
             'Condition': {'StringLike': {'s3:prefix': ['results/', 'results/*']}}},
            {'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': arn + '/results/*'}]}
        values = {'desired.service.iam.serviceId': 'iam',
                  'desired.resource.001.resourceType': 'IAM.Role',
                  'desired.resource.001.cfn-logicalId': consumer + '-Role',
                  'desired.resource.001.anchor': 'role',
                  'desired.row.001-001.property': 'IAM.Role.Policies[].PolicyName',
                  'desired.row.001-001.value': '`ReadResults`',
                  'desired.row.001-002.property': 'IAM.Role.Policies[].PolicyDocument',
                  'desired.row.001-002.value': 'policy.json',
                  'desired.row.001-002.document': json.dumps(policy)}
        fixtures.write(root / 'model/dev/123456789012/iam.properties',
                       '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
        imported = {'Fn::ImportValue': 'app-dev-data2-BucketArn'}
        template['Outputs'] = {'BucketArn': {'Value': {'Fn::GetAtt': ['Bucket', 'Arn']},
                                             'Export': {'Name': {'Fn::Sub': '${Name}-BucketArn'}}}}
        actual = deepcopy(policy)
        for statement in actual['Statement']:
            statement['Action'] = [statement['Action']]
            statement['Resource'] = deepcopy(imported)
        actual['Statement'][2]['Resource'] = {'Fn::Sub': ['${BucketArn}/results/*', {'BucketArn': imported}]}
        template['Resources']['Role'] = {'Type': 'AWS::IAM::Role',
                                         'Properties': {'Policies': [{'PolicyName': 'ReadResults', 'PolicyDocument': actual}]}}
        original = deepcopy(template)

        def record(candidate):
            fixtures.mutate_template(root, candidate)
            comparison, records = fixtures.compare(root, ['iam'])
            selected = [r for r in records if r['property'] == 'IAM.Role.Policies']
            assert len(selected) == 1, records
            return comparison, selected[0]

        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison, result = record(original)
            assert result['category'] == 'matched', result
            callback = lambda a, b, path: comparison.reference_same(a, b, 'IAM.Role', path)
            action_path = 'Policies[].PolicyDocument.Statement[].Action'
            for predicate in (same, selected_same):
                assert predicate('s3:GetObject', ['s3:GetObject'], reference=callback, path=action_path)
                assert predicate(['s3:GetObject'], 's3:GetObject', reference=callback, path=action_path)
                for wrong in ([], ['s3:PutObject'], ['s3:GetObject', 's3:GetObject'], [True], [['s3:GetObject']]):
                    assert predicate('s3:GetObject', wrong, reference=callback, path=action_path) is False
                assert not predicate(['a', 'b'], ['b', 'a'], reference=callback, path=action_path)
                for field in ('Tags[].Value', 'Policies[].Action',
                              'Policies[].PolicyDocument.Statement[].Condition.Action',
                              'Policies[].PolicyDocument.Statement[].Resource'):
                    assert not predicate('same', ['same'], reference=callback, path=field)
                assert not predicate('same', ['same'])
            for kind, path in [('IAM.Role', 'AssumeRolePolicyDocument.Statement[].Action'),
                               ('IAM.ManagedPolicy', 'PolicyDocument.Statement[].Action'),
                               ('IAM.User', action_path)]:
                assert comparison.reference_same('a', ['a'], kind, path) is True
            assert comparison.reference_same('a', ['a'], 'S3.BucketPolicy', 'PolicyDocument.Statement[].Action') is NotImplemented

            reference = comparison.evaluate(consumer, imported)
            assert reference == {'$resource': ['s3', '002'], '$attribute': 'Arn'}
            assert comparison.reference_literal(reference) == arn
            sub = comparison.evaluate(consumer, actual['Statement'][2]['Resource'])
            for symbolic, text in ((reference, arn), (sub, arn + '/results/*')):
                assert same(symbolic, text, reference=callback)
                assert same(text, symbolic, reference=callback)
                for wrong in (text + '-other', text.replace('aws:', 'aws-cn:'), text.replace('data2', 'data1')):
                    assert same(symbolic, wrong, reference=callback) is False
            other = comparison.evaluate(consumer, {'Fn::GetAtt': ['Bucket', 'Arn']})
            assert same(reference, other, reference=callback) is False
            assert same(reference, dict(reference), reference=callback) is not True
            escaped = Expression('Sub', ['${BucketArn}/${!literal}/${Tail}', {'BucketArn': reference, 'Tail': 'one'}])
            assert same(escaped, arn + '/${literal}/one', reference=callback)
            for unresolved in (Expression('Sub', ['${Missing}', {}]),
                               Expression('Sub', ['${Value}', {'Value': {'$resource': ['s3', '002'], '$attribute': 'Arn'}}]),
                               Expression('Sub', ['${Value}', {'Value': Expression('Join', ['', [reference, '/*']])}]),
                               Expression('Join', ['', [reference, '/*']])):
                assert same(unresolved, arn, reference=callback) is None
            comparison.stack_inputs[producer][2]['AWS::Partition'] = 'aws-cn'
            assert same(reference, arn, reference=callback) is False
            assert same(reference, arn.replace('aws:', 'aws-cn:'), reference=callback)

            # Real setting changes still differ, and display does not repeat equivalent fields.
            for field, value in [('Action', ['s3:PutObject']), ('Effect', 'Deny')]:
                changed = deepcopy(original)
                changed['Resources']['Role']['Properties']['Policies'][0]['PolicyDocument']['Statement'][0][field] = value
                comparison, result = record(changed)
                assert result['category'] == 'difference', result
                fields = comparison.display_differences[identifier(result)]
                assert len(fields) == 1 and fields[0]['path'].endswith('.' + field), fields
            changed = deepcopy(original)
            changed['Resources']['Role']['Properties']['Policies'][0]['PolicyDocument']['Statement'][2]['Resource']['Fn::Sub'][0] = '${BucketArn}/other/*'
            comparison, result = record(changed)
            assert result['category'] == 'difference', result
            assert all('arn:aws:' not in json.dumps(field) for field in comparison.display_differences[identifier(result)])
            changed = deepcopy(original)
            changed['Resources']['Role']['Properties']['Policies'][0]['PolicyDocument']['Statement'][1]['Condition']['StringLike']['s3:prefix'] = ['other/*']
            assert record(changed)[1]['category'] == 'difference'
            changed = deepcopy(original)
            changed['Resources']['Bucket']['Properties']['BucketName'] = 'different-bucket'
            assert record(changed)[1]['category'] == 'difference'

            # No inferred names, arbitrary ARN construction or ambiguous/inactive handoffs.
            for name in (None, 'invalid/path', 'wildcard-*', {'Ref': 'Bucket'}):
                changed = deepcopy(original)
                props = changed['Resources']['Bucket']['Properties']
                if name is None:
                    del props['BucketName']
                else:
                    props['BucketName'] = name
                assert record(changed)[1]['category'] == 'uncompared'
            changed = deepcopy(original)
            changed['Resources']['Bucket']['Condition'] = 'Inactive'
            changed['Conditions']['Inactive'] = {'Fn::Equals': ['yes', 'no']}
            assert record(changed)[1]['category'] == 'uncompared'
            changed = deepcopy(original)
            changed['Outputs']['Duplicate'] = deepcopy(changed['Outputs']['BucketArn'])
            assert record(changed)[1]['category'] == 'uncompared'
            changed = deepcopy(original)
            del changed['Outputs']['BucketArn']
            assert record(changed)[1]['category'] == 'uncompared'
            s3 = root / 'model/dev/123456789012/s3.properties'
            original_model = fixtures.read_model(s3)
            fixtures.write(s3, original_model + 'desired.resource.003.resourceType=S3.Bucket\n'
                           'desired.resource.003.anchor=duplicate\n'
                           'desired.resource.003.cfn-logicalId=' + producer + '-Bucket\n')
            assert record(original)[1]['category'] == 'uncompared'
            fixtures.write(s3, original_model)
            comparison, result = record(original)
            assert result['category'] == 'matched'
            reference = comparison.evaluate(consumer, imported)
            comparison.resources['s3']['002']['resourceMode'] = 'IMPORT'
            assert comparison.reference_same(reference, arn, 'IAM.Role', '') is None
    print('Policy equivalence: PASS (IAM Action scope; S3 ARN/Sub/import; real differences; unresolved guards; report masking)')


if __name__ == '__main__':
    from test_support.model_sources import catalog_display
    with catalog_display():
        main_checks()
