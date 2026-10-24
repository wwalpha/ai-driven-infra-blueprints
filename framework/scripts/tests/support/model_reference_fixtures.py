"""Small authored cross-service Model fixtures; no generated project or Git setup."""

import json
from pathlib import Path

from comparison import Comparison
from model.format import serialize
from model.identity import COUNTERS
from model.sources import Scope

FRAMEWORK = Path(__file__).resolve().parents[4]


def reference(logical='KMS_Key_001', attribute='Arn'):
    return {'$modelRef': {'logicalId': logical, 'attribute': attribute}}


def save(scope, values):
    scope.path.parent.mkdir(parents=True, exist_ok=True)
    scope.path.write_text(serialize(values), encoding='utf-8')


def resource(root, service, kind, *, target='team', attribute='Arn', observed=None, number='001'):
    scope = Scope(root, 'qa', target, service)
    logical = kind.replace('.', '_') + '_' + number
    values = {COUNTERS: json.dumps({kind: int(number)}),
              f'desired.service.{service}.serviceId': service,
              f'desired.service.{service}.ownedCatalogResourceTypes': kind,
              'display.service.title': '# 合成参照',
              f'desired.resource.{number}.resourceType': kind,
              f'desired.resource.{number}.logicalId': logical,
              f'desired.resource.{number}.anchor': 'saved-' + number,
              f'desired.resource.{number}.resourceMode': 'CREATE',
              f'desired.resource.{number}.cfn-logicalId': 'producer-Resource' + number,
              f'display.resource.{number}.comment': '合成',
              f'desired.row.{number}-001.property': kind + '.' + attribute,
              f'desired.row.{number}-001.value': '[self](#saved-' + number + ')',
              f'desired.row.{number}-001.comment': '合成'}
    if observed is not None:
        values[f'observed.row.{number}-001.value'] = '`' + observed + '`'
    save(scope, values)
    return scope, values


def project(root):
    data = {'targets': [{'environment': 'qa', 'alias': target, 'awsAccountId': '123456789012',
                       'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'} for target in ('team', 'other')]}
    (root / 'project.json').write_text(json.dumps(data), encoding='utf-8')
    producer, values = resource(root, 'kms', 'KMS.Key')
    consumer, policy = resource(root, 'iam', 'IAM.ManagedPolicy', attribute='ManagedPolicyName')
    policy.update({'desired.row.001-001.value': '`synthetic-policy`',
                   'desired.row.001-002.property': 'IAM.ManagedPolicy.PolicyDocument',
                   'desired.row.001-002.value': '[Policy](iam/policy.json)',
                   'desired.row.001-002.comment': '合成JSON',
                   'desired.row.001-002.document': json.dumps({'Version': '2012-10-17', 'Statement': [
                       {'Effect': 'Allow', 'Action': 'kms:Decrypt', 'Resource': reference()}]})})
    policy['desired.resource.001.cfn-logicalId'] = 'consumer-Policy'
    save(consumer, policy)
    return producer, values, consumer, policy


def comparison(root, services=('iam', 'kms')):
    result = Comparison(root, 'qa', 'team', services)
    result.local_comparison = True
    pseudo = {'AWS::Region': 'ap-northeast-1', 'AWS::AccountId': '123456789012', 'AWS::Partition': 'aws'}
    result.stack_inputs = {
        'producer': ({'Resources': {'Resource001': {'Type': 'AWS::KMS::Key'}},
                      'Outputs': {'Reference': {'Value': {'Fn::GetAtt': ['Resource001', 'Arn']},
                                               'Export': {'Name': 'ExampleKmsKeyArn'}}}}, {}, pseudo),
        'consumer': ({'Resources': {'Policy': {'Type': 'AWS::IAM::ManagedPolicy'}}}, {}, pseudo)}
    result._templates = [(name, {'name': name}) for name in result.stack_inputs]
    return result
