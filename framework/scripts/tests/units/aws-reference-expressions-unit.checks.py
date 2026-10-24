"""Shared AWS reference/compound-string contracts over authored synthetic Models."""
import copy
import json
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison import expressions
from design.catalog import DesignSchemaCatalog
from model.core import entries
from model.identity import COUNTERS, Resolver
from model.reference_nodes import receiving_property
from support.model_reference_fixtures import (
    FRAMEWORK,
    comparison,
    project,
    reference,
    resource,
    save,
)
from utils.aws_mappings import mapping_alias
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference
from utils.reference_contracts import ARN_SHAPES, reference_attribute

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

CONTEXT = 'arn:aws:{service}:ap-northeast-1:123456789012:{tail}'
CASES = [
    ('S3.Bucket', {'BucketName': 'fixture-bucket'}, 'arn:aws:s3:::fixture-bucket'),
    ('Lambda.Function', {'FunctionName': 'fixture'}, CONTEXT.format(service='lambda', tail='function:fixture')),
    ('Logs.LogGroup', {'LogGroupName': '/fixture'}, CONTEXT.format(service='logs', tail='log-group:/fixture:*')),
    ('KMS.Alias', {'AliasName': 'alias/fixture'}, CONTEXT.format(service='kms', tail='alias/fixture')),
    ('Glue.Job', {'Name': 'fixture'}, CONTEXT.format(service='glue', tail='job/fixture')),
    ('Glue.Crawler', {'Name': 'fixture'}, CONTEXT.format(service='glue', tail='crawler/fixture')),
    ('Athena.WorkGroup', {'Name': 'fixture'}, CONTEXT.format(service='athena', tail='workgroup/fixture')),
    ('SQS.Queue', {'QueueName': 'fixture'}, CONTEXT.format(service='sqs', tail='fixture')),
    ('SNS.Topic', {'TopicName': 'fixture'}, CONTEXT.format(service='sns', tail='fixture')),
    ('ECR.Repository', {'RepositoryName': 'team/fixture'}, CONTEXT.format(service='ecr', tail='repository/team/fixture')),
    ('CloudWatch.Alarm', {'AlarmName': 'fixture'}, CONTEXT.format(service='cloudwatch', tail='alarm:fixture')),
    ('CodeCommit.Repository', {'RepositoryName': 'fixture'}, CONTEXT.format(service='codecommit', tail='fixture')),
    ('CodeBuild.Project', {'Name': 'fixture'}, CONTEXT.format(service='codebuild', tail='project/fixture')),
    ('CodePipeline.Pipeline', {'Name': 'fixture'}, CONTEXT.format(service='codepipeline', tail='fixture')),
    ('MWAA.Environment', {'Name': 'fixture'}, CONTEXT.format(service='airflow', tail='environment/fixture')),
    ('CloudTrail.Trail', {'TrailName': 'fixture'}, CONTEXT.format(service='cloudtrail', tail='trail/fixture')),
    ('IAM.Role', {'RoleName': 'fixture', 'Path': '/team/'}, 'arn:aws:iam::123456789012:role/team/fixture'),
    ('IAM.InstanceProfile', {'InstanceProfileName': 'fixture'}, 'arn:aws:iam::123456789012:instance-profile/fixture'),
    ('IAM.ManagedPolicy', {'ManagedPolicyName': 'fixture', 'Path': '/team/'}, 'arn:aws:iam::123456789012:policy/team/fixture'),
    ('IAM.User', {'UserName': 'fixture'}, 'arn:aws:iam::123456789012:user/fixture'),
    ('Events.EventBus', {'Name': 'fixture'}, CONTEXT.format(service='events', tail='event-bus/fixture')),
    ('Events.Rule', {'Name': 'fixture', 'EventBusName': 'custom'}, CONTEXT.format(service='events', tail='rule/custom/fixture')),
    ('DynamoDB.Table', {'TableName': 'fixture'}, CONTEXT.format(service='dynamodb', tail='table/fixture')),
    ('DynamoDB.GlobalTable', {'TableName': 'fixture'}, CONTEXT.format(service='dynamodb', tail='table/fixture')),
    ('ECS.Cluster', {'ClusterName': 'fixture'}, CONTEXT.format(service='ecs', tail='cluster/fixture')),
    ('KinesisFirehose.DeliveryStream', {'DeliveryStreamName': 'fixture'}, CONTEXT.format(service='firehose', tail='deliverystream/fixture')),
    ('RDS.DBCluster', {'DBClusterIdentifier': 'fixture'}, CONTEXT.format(service='rds', tail='cluster:fixture')),
    ('RDS.DBInstance', {'DBInstanceIdentifier': 'fixture'}, CONTEXT.format(service='rds', tail='db:fixture')),
    ('RDS.DBClusterParameterGroup', {'DBClusterParameterGroupName': 'fixture'}, CONTEXT.format(service='rds', tail='cluster-pg:fixture')),
    ('RDS.DBParameterGroup', {'DBParameterGroupName': 'fixture'}, CONTEXT.format(service='rds', tail='pg:fixture')),
    ('RDS.DBSubnetGroup', {'DBSubnetGroupName': 'fixture'}, CONTEXT.format(service='rds', tail='subgrp:fixture')),
    ('RDS.OptionGroup', {'OptionGroupName': 'fixture'}, CONTEXT.format(service='rds', tail='og:fixture')),
    ('SageMaker.Space', {'DomainId': 'd-fixture', 'SpaceName': 'fixture'}, CONTEXT.format(service='sagemaker', tail='space/d-fixture/fixture')),
    ('SageMaker.UserProfile', {'DomainId': 'd-fixture', 'UserProfileName': 'fixture'}, CONTEXT.format(service='sagemaker', tail='user-profile/d-fixture/fixture')),
    ('CloudWatch.Dashboard', {'DashboardName': 'fixture'}, 'arn:aws:cloudwatch::123456789012:dashboard/fixture'),
    ('CloudFront.Function', {'Name': 'fixture'}, 'arn:aws:cloudfront::123456789012:function/fixture'),
    ('ECS.CapacityProvider', {'Name': 'fixture'}, CONTEXT.format(service='ecs', tail='capacity-provider/fixture')),
    ('Scheduler.Schedule', {'Name': 'fixture'}, CONTEXT.format(service='scheduler', tail='schedule/default/fixture')),
    ('SecurityHub.Hub', {}, CONTEXT.format(service='securityhub', tail='hub/default')),
    ('Glue.Catalog', {'Name': 'fixture'}, CONTEXT.format(service='glue', tail='catalog/fixture')),
    ('NetworkFirewall.Firewall', {'FirewallName': 'fixture'}, CONTEXT.format(service='network-firewall', tail='firewall/fixture')),
    ('NetworkFirewall.FirewallPolicy', {'FirewallPolicyName': 'fixture'}, CONTEXT.format(service='network-firewall', tail='firewall-policy/fixture')),
    ('Glue.Connection', {'CatalogId': '123456789012', 'ConnectionInput': {'Name': 'fixture'}}, CONTEXT.format(service='glue', tail='connection/fixture')),
    ('Glue.Database', {'CatalogId': '123456789012', 'DatabaseInput': {'Name': 'fixture'}}, CONTEXT.format(service='glue', tail='database/fixture')),
    ('Glue.Table', {'CatalogId': '123456789012', 'DatabaseName': 'db', 'TableInput': {'Name': 'fixture'}}, CONTEXT.format(service='glue', tail='table/db/fixture')),
    ('QuickSight.Analysis', {'AwsAccountId': '123456789012', 'AnalysisId': 'fixture'}, CONTEXT.format(service='quicksight', tail='analysis/fixture')),
    ('QuickSight.Dashboard', {'AwsAccountId': '123456789012', 'DashboardId': 'fixture'}, CONTEXT.format(service='quicksight', tail='dashboard/fixture')),
    ('QuickSight.DataSet', {'AwsAccountId': '123456789012', 'DataSetId': 'fixture'}, CONTEXT.format(service='quicksight', tail='dataset/fixture')),
    ('QuickSight.DataSource', {'AwsAccountId': '123456789012', 'DataSourceId': 'fixture'}, CONTEXT.format(service='quicksight', tail='datasource/fixture')),
    ('QuickSight.VPCConnection', {'AwsAccountId': '123456789012', 'VPCConnectionId': 'fixture'}, CONTEXT.format(service='quicksight', tail='vpcConnection/fixture')),

]


@pytest.fixture
def models(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        for service in ('iam', 'kms'):
            (tmp_path / 'model/qa/team' / (service + '.properties')).unlink()
        yield tmp_path


def cached_stack(inputs, unit):
    return inputs.root / 'synthetic.yaml', inputs.stack_inputs[unit['name']]


def producer(root, kind, properties):
    scope, values = resource(root, 'producer', kind, attribute=next(iter(properties), 'Name'))
    values['desired.row.001-001.value'] = '`fixture`'
    save(scope, values)
    scope, receiver = resource(root, 'receiver', 'Glue.Job', attribute='Name')
    receiver['desired.resource.001.cfn-logicalId'] = 'consumer-Policy'
    receiver['desired.resource.001.logicalId'] = 'Glue_Job_002'
    receiver[COUNTERS] = json.dumps({'Glue.Job': 2})
    receiver['desired.row.001-001.value'] = '`receiver`'
    save(scope, receiver)
    inputs = comparison(root, ('producer', 'receiver'))
    inputs.stack = partial(cached_stack, inputs)
    inputs.stack_inputs['producer'][0]['Resources']['Resource001'] = {
        'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': copy.deepcopy(properties)}
    symbol = ResourceReference({'$resource': ['producer', '001'], '$attribute': reference_attribute(kind, 'Arn')})
    return inputs, symbol


def prepared(inputs, kind, payload):
    scope = inputs.models['receiver'].scope
    authored = dict(inputs.models['receiver'].authoritative)
    authored.update({'desired.row.001-002.property': 'Glue.Job.DefaultArguments',
                     'desired.row.001-002.value': '`' + json.dumps({'--value': payload}) + '`',
                     'desired.row.001-002.comment': '合成'})
    save(scope, authored)
    fresh = comparison(inputs.root, ('producer', 'receiver'))
    fresh.stack_inputs = inputs.stack_inputs
    fresh._templates = inputs._templates
    fresh.stack = partial(cached_stack, fresh)
    row = dict(entries(authored, 'desired.row.'))['001-002']
    return fresh.prepare_value('receiver', row, 'Glue.Job', row_id='001-002', stack='consumer')


@pytest.mark.parametrize('kind,properties,arn', CASES)
def test_proven_arns_and_both_comparison_directions(models, kind, properties, arn):
    inputs, symbol = producer(models, kind, properties)
    assert inputs.reference_literal(symbol) == arn
    resolver = Resolver(models)
    resolver.validate_attribute(kind, 'Arn')
    resolver.validate_attribute(kind, symbol['$attribute'])
    for left, right in [(symbol, arn), (arn, symbol)]:
        decision = inputs.reference_decision(left, right, 'Glue.Job', 'DefaultArguments')
        assert decision.equal is True
        assert decision.diagnostics[0]['model' if left is symbol else 'iac'] == symbol
    for different in (arn + '-other', arn.replace('arn:aws:', 'arn:aws-cn:'), arn.replace('123456789012', '999999999999'),
                      arn.replace('ap-northeast-1', 'us-east-1')):
        if different == arn:
            continue
        assert inputs.reference_same(symbol, different, 'Glue.Job', 'DefaultArguments') is False
        assert inputs.reference_same(different, symbol, 'Glue.Job', 'DefaultArguments') is False


EXPRESSION_CASES = [case for case in CASES if case[0] in {
    'S3.Bucket', 'Lambda.Function', 'IAM.Role', 'Logs.LogGroup', 'KMS.Alias', 'Glue.Job', 'Athena.WorkGroup', 'SQS.Queue'}]


@pytest.mark.parametrize('kind,properties,arn', EXPRESSION_CASES)
@pytest.mark.parametrize('operation', ['Sub', 'Join', 'nested', 'split-select'])
def test_model_nodes_before_common_intrinsic_evaluation(models, kind, properties, arn, operation):
    inputs, symbol = producer(models, kind, properties)
    node = reference(kind.replace('.', '_') + '_001', 'Arn')
    sub = {'Fn::Sub': ['pre/${Resource}/suffix', {'Resource': node}]}
    join = {'Fn::Join': ['', ['pre/', node, '/suffix']]}
    payload = {'Sub': sub, 'Join': join, 'nested': {'Fn::Join': ['', [{'Fn::Sub': ['pre/${R}', {'R': node}]}, '/suffix']]},
               'split-select': {'Fn::Select': [0, {'Fn::Split': ['|', {'Fn::Join': ['', [sub, '|other']]}]}]}}[operation]
    value = prepared(inputs, kind, payload).require_value()['--value']
    expected = 'pre/' + arn + '/suffix'
    assert inputs.reference_same(value, expected, 'Glue.Job', 'DefaultArguments') is True
    assert inputs.reference_same(expected, value, 'Glue.Job', 'DefaultArguments') is True
    equivalent = Expression('Join', ['', ['pre/', symbol, '/suffix']])
    assert inputs.reference_same(value, equivalent, 'Glue.Job', 'DefaultArguments') is True
    for wrong in (expected + 'other', expected.replace('pre/', 'other/'), expected.replace('/suffix', '/different')):
        assert inputs.reference_same(value, wrong, 'Glue.Job', 'DefaultArguments') is False


@pytest.mark.parametrize('kind,attribute', [('Glue.Job', 'Arn'), ('Athena.WorkGroup', 'Arn'), ('SNS.Topic', 'Arn'),
                                          ('KMS.Alias', 'AliasArn')])
def test_derived_model_attribute_does_not_authorize_getatt(models, kind, attribute):
    inputs, _ = producer(models, kind, {'Name': 'fixture'})
    with pytest.raises((Blocked, KeyError, ValueError)):
        inputs.evaluate('producer', {'Fn::GetAtt': ['Resource001', attribute]})


@pytest.mark.parametrize('kind,props,ref,attribute', [
    ('Glue.Job', {'Name': 'fixture'}, 'Name', None),
    ('Athena.WorkGroup', {'Name': 'fixture'}, 'Name', None),
    ('SNS.Topic', {'TopicName': 'fixture'}, 'TopicArn', 'TopicArn'),
    ('SQS.Queue', {'QueueName': 'fixture'}, 'QueueUrl', 'Arn'),
    ('CodeCommit.Repository', {'RepositoryName': 'fixture'}, 'RepositoryId', 'Name'),
    ('IAM.Role', {'RoleName': 'fixture'}, 'RoleName', 'Arn'),
    ('SecurityHub.Hub', {}, 'ARN', 'ARN'),
    ('Glue.Catalog', {'Name': 'fixture'}, 'ResourceArn', 'ResourceArn'),
    ('NetworkFirewall.Firewall', {'FirewallName': 'fixture'}, 'FirewallArn', 'FirewallArn'),
    ('NetworkFirewall.FirewallPolicy', {'FirewallPolicyName': 'fixture'}, 'FirewallPolicyArn', 'FirewallPolicyArn'),
])
def test_formal_ref_and_getatt_semantics(models, kind, props, ref, attribute):
    inputs, _ = producer(models, kind, props)
    assert inputs.evaluate('producer', {'Ref': 'Resource001'})['$attribute'] == ref
    if attribute:
        actual = inputs.evaluate('producer', {'Fn::GetAtt': ['Resource001', attribute]})
        assert actual['$attribute'] == attribute
        if ref == attribute:
            assert inputs.reference_same(inputs.evaluate('producer', {'Ref': 'Resource001'}), actual,
                                         'Glue.Job', 'DefaultArguments') is True
    if kind == 'SNS.Topic':
        assert inputs.evaluate('producer', {'Fn::GetAtt': ['Resource001', 'TopicName']})['$attribute'] == 'TopicName'


@pytest.mark.parametrize('kind,props,attribute', [
    ('KMS.Key', {}, 'Arn'), ('ECS.TaskDefinition', {'Family': 'fixture'}, 'TaskDefinitionArn'),
    ('ElasticLoadBalancingV2.LoadBalancer', {'Name': 'fixture'}, 'LoadBalancerArn'),
    ('WAFv2.WebACL', {'Name': 'fixture', 'Scope': 'REGIONAL'}, 'Arn'),
    ('SecretsManager.Secret', {'Name': 'fixture'}, 'Id'), ('DynamoDB.Table', {'TableName': 'fixture'}, 'StreamArn'),
    ('SageMaker.Domain', {'DomainName': 'fixture'}, 'DomainArn'),
    ('RDS.DBProxy', {'DBProxyName': 'fixture'}, 'DBProxyArn')])
def test_generated_ids_remain_uncompared(models, kind, props, attribute):
    inputs, symbol = producer(models, kind, props)
    symbol['$attribute'] = attribute
    for left, right in [(symbol, 'arn:aws:unproven'), ('arn:aws:unproven', symbol)]:
        assert inputs.reference_same(left, right, 'Glue.Job', 'DefaultArguments') is None
    assert inputs.reference_same(symbol, copy.deepcopy(symbol), 'Glue.Job', 'DefaultArguments') is True


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'type', 'inactive', 'unknown-condition', 'import', 'transform'])
def test_producer_proof_cannot_be_replaced_by_a_matching_name(models, fault):
    inputs, symbol = producer(models, 'Glue.Job', {'Name': 'fixture'})
    definition = inputs.stack_inputs['producer'][0]['Resources']['Resource001']
    if fault == 'missing':
        inputs.stack_inputs['producer'][0]['Resources'].clear()
    elif fault == 'duplicate':
        inputs.index()['producer', 'Resource001'].append(inputs.index()['producer', 'Resource001'][0])
    elif fault == 'type':
        definition['Type'] = 'AWS::Athena::WorkGroup'
    elif fault in {'inactive', 'unknown-condition'}:
        definition['Condition'] = 'Active'
        if fault == 'inactive':
            inputs.stack_inputs['producer'][0]['Conditions'] = {'Active': False}
    elif fault == 'import':
        inputs.resources['producer']['001']['resourceMode'] = 'IMPORT'
    else:
        inputs.stack_inputs['producer'][0]['Transform'] = 'Unproven'
    arn = CONTEXT.format(service='glue', tail='job/fixture')
    assert inputs.reference_same(symbol, arn, 'Glue.Job', 'DefaultArguments') is None
    assert inputs.reference_same(arn, symbol, 'Glue.Job', 'DefaultArguments') is None


def test_arn_contract_inventory_covers_every_derivable_type():
    assert {kind for kind, _, _ in CASES} == ARN_SHAPES.keys() - {'KMS.Key'}
    catalog = DesignSchemaCatalog(FRAMEWORK)
    assert len(catalog.resource_types) == 176
    assert set(catalog.api_schemas) == {'Macie.ClassificationJob', 'QuickSight.Group'}
    assert all('AWS::' + kind.replace('.', '::') in catalog.resource_types for kind in ARN_SHAPES)


def test_kms_attributes_in_compound_strings_are_not_property_form_equivalence(models):
    inputs, arn = producer(models, 'KMS.Key', {})
    keyid = ResourceReference(dict(arn, **{'$attribute': 'KeyId'}))
    left = Expression('Join', ['', ['pre/', arn]])
    right = Expression('Sub', ['pre/${Key}', {'Key': keyid}])
    assert inputs.reference_same(left, right, 'KMS.Alias', 'TargetKeyId') is not True
    alias = ResourceReference({'$resource': ['producer', '002'], '$attribute': 'AliasArn'})
    inputs.resources['producer']['002'] = {'resourceType': 'KMS.Alias'}
    assert inputs.reference_same(arn, alias, 'Glue.Job', 'DefaultArguments') is False
    assert inputs.reference_same(left, Expression('Join', ['', ['pre/', alias]]), 'Glue.Job', 'DefaultArguments') is not True


@pytest.mark.parametrize('payload', [
    {'Fn::Join': ['', 'invalid']}, {'Fn::Join': [1, []]}, {'Fn::Sub': '${Missing'},
    {'Fn::Sub': '${}'}, {'Fn::Sub': [2, {}]}, {'Fn::Select': [-1, []]},
    {'Fn::Split': ['', 'invalid']}, {'Fn::Sub': 'ok', 'extra': 'invalid'},
])
def test_invalid_intrinsics_cannot_match(models, payload):
    inputs, _ = producer(models, 'Glue.Job', {'Name': 'fixture'})
    with pytest.raises((ValueError, Blocked)):
        inputs.evaluate('producer', payload)
    value = prepared(inputs, 'Glue.Job', payload)
    assert value.error is not None or value.failures or isinstance(value.value['--value'], Expression)


def test_unresolved_nodes_keep_their_pointer_and_context(models):
    inputs, _ = producer(models, 'Glue.Job', {'Name': 'fixture'})
    payload = {'Fn::Join': ['', [reference('Glue_Job_999', 'Arn'), '/key']]}
    value = prepared(inputs, 'Glue.Job', payload).require_value()['--value']
    assert inputs.reference_same(value, 'literal', 'Glue.Job', 'DefaultArguments') is None
    assert inputs.reference_same(value, copy.deepcopy(value), 'Glue.Job', 'DefaultArguments') is None
    assert receiving_property('Lambda.Function.Role', '/Fn::Sub/1/Role') == 'Lambda.Function.Role'
    assert receiving_property('CodeBuild.Project.Environment', '/EnvironmentVariables/0/Value/Fn::Join/1/0') == (
        'CodeBuild.Project.Environment.EnvironmentVariables[].Value')


@pytest.mark.parametrize('fault', [None, 'missing', 'duplicate', 'scope', 'incomplete', 'unresolved-name'])
def test_export_evidence_composes_with_sub_and_join(models, fault):
    inputs, symbol = producer(models, 'S3.Bucket', {'BucketName': 'fixture-bucket'})
    outputs = {'Arn': {'Value': {'Fn::GetAtt': ['Resource001', 'Arn']}, 'Export': {'Name': 'BucketArn'}}}
    inputs.stack_inputs['producer'][0]['Outputs'] = {} if fault == 'missing' else outputs
    if fault == 'duplicate':
        inputs.stack_inputs['consumer'][0]['Outputs'] = copy.deepcopy(outputs)
    if fault == 'scope':
        inputs.resources['producer']['001']['cfn-logicalId'] = 'elsewhere-Resource001'
        inputs.index().pop(('producer', 'Resource001'))
    if fault == 'incomplete':
        inputs.stack_inputs['consumer'][0]['Transform'] = 'Unproven'
    if fault == 'unresolved-name':
        outputs['Unknown'] = {'Value': 'other', 'Export': {'Name': {'Fn::Sub': '${Missing}'}}}
    actual = {'Fn::Join': ['', [{'Fn::ImportValue': 'BucketArn'}, '/object']]}
    if fault:
        with pytest.raises((Blocked, ValueError)):
            inputs.evaluate('consumer', actual)
    else:
        evaluated = inputs.evaluate('consumer', actual)
        desired = Expression('Sub', ['${Bucket}/object', {'Bucket': symbol}])
        assert inputs.reference_same(desired, evaluated, 'Glue.Job', 'DefaultArguments') is True
        assert inputs.reference_same(evaluated, 'arn:aws:s3:::fixture-bucket/object', 'Glue.Job', 'DefaultArguments') is True


def test_symbolic_token_boundaries_do_not_prove_string_inequality():
    symbol = ResourceReference({'$resource': ['producer', '001'], '$attribute': 'Name'})
    assert expressions.symbolic_same(['a', symbol, 'b'], ['ab', symbol]) is None



@pytest.mark.parametrize('kind,properties,arn', CASES)
def test_missing_identity_never_uses_a_generated_name(models, kind, properties, arn):
    if not properties:
        return  # Hub ARN is fixed by context, not a generated name.
    inputs, symbol = producer(models, kind, properties)
    inputs.stack_inputs['producer'][0]['Resources']['Resource001']['Properties'].clear()
    assert inputs.reference_same(symbol, arn, 'Glue.Job', 'DefaultArguments') is None


@pytest.mark.parametrize('kind,properties', [
    ('Glue.Database', {'CatalogId': '123456789012', 'DatabaseInput': {'Name': 'one'}, 'DatabaseName': 'other'}),
    ('Glue.Table', {'CatalogId': '123456789012', 'DatabaseName': 'db', 'TableInput': {'Name': 'one'}, 'Name': 'other'}),
    ('QuickSight.Analysis', {'AwsAccountId': '999999999999', 'AnalysisId': 'fixture'}),
    ('Glue.Connection', {'CatalogId': '999999999999', 'ConnectionInput': {'Name': 'fixture'}}),
])
def test_explicit_context_and_creation_names_must_agree(models, kind, properties):
    inputs, symbol = producer(models, kind, properties)
    with pytest.raises(Blocked):
        inputs.reference_literal(symbol)


def test_import_name_cannot_depend_on_a_resource(models):
    inputs, _ = producer(models, 'S3.Bucket', {'BucketName': 'fixture-bucket'})
    with pytest.raises(Blocked):
        inputs.evaluate('consumer', {'Fn::ImportValue': {'Fn::Sub': '${Resource001}'}})


def test_pseudo_parameters_and_formal_escaping(models):
    inputs, symbol = producer(models, 'Lambda.Function', {'FunctionName': 'fixture'})
    expression = inputs.evaluate('producer', {'Fn::Sub': ['${AWS::Partition}/${AWS::Region}/${AWS::AccountId}/${!Literal}/${R}', {'R': symbol}]})
    expected = 'aws/ap-northeast-1/123456789012/${Literal}/' + CONTEXT.format(service='lambda', tail='function:fixture')
    assert inputs.reference_same(expression, expected, 'Glue.Job', 'DefaultArguments') is True


@pytest.mark.parametrize('kind,properties,arn', EXPRESSION_CASES)
def test_qualifiers_keys_and_literal_affixes_remain_part_of_the_value(models, kind, properties, arn):
    inputs, symbol = producer(models, kind, properties)
    suffix = ':live' if kind == 'Lambda.Function' else ':stream' if kind == 'Logs.LogGroup' else '/objects/key'
    expression = Expression('Join', ['', ['prefix/', symbol, suffix]])
    assert inputs.reference_same(expression, 'prefix/' + arn + suffix, 'Glue.Job', 'DefaultArguments') is True
    assert inputs.reference_same(expression, 'prefix/' + arn, 'Glue.Job', 'DefaultArguments') is False
    assert inputs.reference_same(expression, 'prefix/' + arn + suffix + '-other', 'Glue.Job', 'DefaultArguments') is False


@pytest.mark.parametrize('operation', ['Sub', 'Join', 'Select', 'malformed', 'invalid-split', 'empty-select',
                                       'negative-select', 'nested-invalid-split', 'unknown-operation'])
def test_unresolved_expression_is_not_equal_to_itself(models, operation):
    inputs, _ = producer(models, 'Glue.Job', {'Name': 'fixture'})
    missing = Expression('Sub', ['${Missing}', {}])
    value = {'Sub': missing, 'Join': Expression('Join', ['', [missing, '/suffix']]),
             'Select': Expression('Select', [0, Expression('Split', ['|', missing])]),
             'malformed': Expression('Sub', ['${Missing', {}]),
             'invalid-split': Expression('Split', ['', 'literal']),
             'empty-select': Expression('Select', [0, []]),
             'negative-select': Expression('Select', [-1, ['literal']]),
             'nested-invalid-split': Expression('Select', [0, Expression('Split', ['', 'literal'])]),
             'unknown-operation': Expression('Select', [0, Expression('Future', ['literal'])])}[operation]
    assert inputs.reference_same(value, copy.deepcopy(value), 'Glue.Job', 'DefaultArguments') is None


@pytest.mark.parametrize('kind,attribute,text', [
    ('KMS.Key', 'KeyId', '1234abcd-12ab-34cd-56ef-1234567890ab'),
    ('ECS.TaskDefinition', 'TaskDefinitionArn', 'arn:aws:ecs:ap-northeast-1:123456789012:task-definition/fake:1'),
    ('ElasticLoadBalancingV2.LoadBalancer', 'LoadBalancerArn', 'arn:aws:elasticloadbalancing:ap-northeast-1:123456789012:loadbalancer/app/fake/123'),
])
def test_template_cannot_supply_aws_generated_return_values(models, kind, attribute, text):
    inputs, symbol = producer(models, kind, {attribute: text})
    symbol['$attribute'] = attribute
    assert inputs.reference_same(symbol, text, 'Glue.Job', 'DefaultArguments') is None
    expression = inputs.evaluate('producer', {'Fn::Sub': ['pre/${R}', {'R': symbol}]})
    assert inputs.reference_same(expression, 'pre/' + text, 'Glue.Job', 'DefaultArguments') is None


@pytest.mark.parametrize('kind,properties,arn', CASES)
def test_sub_arn_uses_contract_even_with_a_spoofed_template_field(models, kind, properties, arn):
    inputs, symbol = producer(models, kind, properties)
    props = inputs.stack_inputs['producer'][0]['Resources']['Resource001']['Properties']
    props[symbol['$attribute']] = 'spoofed'
    expression = inputs.evaluate('producer', {'Fn::Sub': ['pre/${R}/suffix', {'R': symbol}]})
    assert inputs.reference_same(expression, 'pre/' + arn + '/suffix', 'Glue.Job', 'DefaultArguments') is True
    assert inputs.reference_same(expression, 'pre/spoofed/suffix', 'Glue.Job', 'DefaultArguments') is False


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
