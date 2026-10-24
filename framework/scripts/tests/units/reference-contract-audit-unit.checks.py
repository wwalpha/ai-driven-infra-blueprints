"""Registered receiving contracts and typed reference regressions; synthetic inputs only."""

import copy
import json
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from design.catalog import DesignSchemaCatalog
from design.common import row_table
from design.layout import expanded_design
from model.core import entries
from model.display import display_rows, restored_reference_rows
from model.identity import Resolver
from model.projection import reference_display
from model.reference_nodes import parse, resolve
from model.validation import validate_json_settings
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
from utils.reference_contracts import (
    ARN_SHAPES,
    CONTEXT_PROPERTIES,
    GETATT_ATTRIBUTES,
    IMPORT_PROPERTIES,
    REF_ATTRIBUTES,
    contract,
    reference_attribute,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.fixture
def models(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        for service in ('iam', 'kms'):
            (tmp_path / 'model/qa/team' / (service + '.properties')).unlink()
        yield tmp_path


def prepare(root, kind, prop, payload, context=None, producer='S3.Bucket', attribute='Arn'):
    resource(root, 'producer', producer, attribute=attribute, observed='PENDING_DEPLOY')
    scope, values = resource(root, 'receiver', kind, attribute='Name')
    values['desired.resource.001.cfn-logicalId'] = 'consumer-Policy'
    values.update({'desired.row.001-002.property': kind + '.' + prop,
                   'desired.row.001-002.value': '`' + json.dumps(payload) + '`',
                   'desired.row.001-002.comment': '合成'})
    save(scope, values)
    inputs = comparison(root, ('receiver', 'producer'))
    inputs.stack = partial(cached_stack, inputs)
    row = dict(entries(values, 'desired.row.'))['001-002']
    result = inputs.prepare_value('receiver', row, kind, row_id='001-002', context=context)
    return inputs, result, scope, values


def cached_stack(inputs, unit):
    return inputs.root / (unit['name'] + '.yaml'), inputs.stack_inputs[unit['name']]


@pytest.mark.parametrize('kind,prop,payload,context,producer,attribute', [
    ('CloudTrail.Trail', 'EventSelectors', [{'DataResources': [{'Type': 'AWS::S3::Object', 'Values': [reference('Lambda_Function_001', 'Arn')]}]}], None, 'Lambda.Function', 'Arn'),
    ('CloudTrail.Trail', 'EventSelectors', [{'DataResources': [{'Values': [reference('Lambda_Function_001', 'Arn')]}]}], None, 'Lambda.Function', 'Arn'),
    ('CodeBuild.Project', 'Environment', {'EnvironmentVariables': [{'Name': 'Bad', 'Type': 'UNKNOWN', 'Value': reference('S3_Bucket_001', 'Arn')}]}, None, 'S3.Bucket', 'Arn'),
])
def test_context_never_guesses(models, kind, prop, payload, context, producer, attribute):
    _, prepared, _, _ = prepare(models, kind, prop, payload, context, producer, attribute)
    desired = prepared.require_value()
    value = desired[0]['DataResources'][0]['Values'][0] if kind == 'CloudTrail.Trail' else desired['EnvironmentVariables'][0]['Value']
    assert isinstance(value, Expression), value


def test_flowlog_nested_context(models):
    payload = {'ResourceType': 'VPC', 'ResourceId': reference('EC2_VPC_001', 'VpcId')}
    resolver = Resolver(models)
    resource(models, 'producer', 'EC2.VPC', attribute='VpcId')
    scope, _ = resource(models, 'receiver', 'EC2.FlowLog', attribute='Id')
    assert resolve(parse(payload['ResourceId']), scope, resolver, field='EC2.FlowLog.ResourceId', context=payload)[3] == 'VpcId'
    with pytest.raises(ValueError):
        resolve(parse(payload['ResourceId']), scope, resolver, field='EC2.FlowLog.ResourceId', context={'ResourceType': 'Subnet'})


STATIC = [(prop, kind, attr) for prop in IMPORT_PROPERTIES for kind, attrs in contract(prop).items() for attr in attrs]


@pytest.mark.parametrize('prop,producer,attribute', STATIC)
def test_registered_contract_route(models, prop, producer, attribute):
    consumer_kind = '.'.join(prop.split('.')[:2])
    resource(models, 'producer', producer, attribute=attribute)
    scope, authored = resource(models, 'receiver', consumer_kind, attribute='Name')
    authored['desired.resource.001.logicalId'] = consumer_kind.replace('.', '_') + '_999'
    authored['desired.service.identity.lastAllocated'] = json.dumps({consumer_kind: 999})
    resolver = Resolver(models)
    resolver.validate_attribute(producer, attribute, field=prop)
    # Whole arrays are receiving contracts for elements, never permission to replace the array by a scalar.
    schema = DesignSchemaCatalog(models)
    path = prop.removeprefix(consumer_kind + '.')
    try:
        if schema.property_schema(consumer_kind, path).get('type') == 'array':
            path += '[]'
    except KeyError:
        pass  # SecretsManager's VpcSubnetIds is a documented comma-separated string list.
    authored.update({'desired.row.001-002.property': consumer_kind + '.' + path,
                     'desired.row.001-002.value': '`' + json.dumps(reference(producer.replace('.', '_') + '_001', attribute)) + '`',
                     'desired.row.001-002.comment': 'contract'})
    save(scope, authored)
    symbol = ResourceReference({'$resource': ['producer', '001'], '$attribute': reference_attribute(producer, attribute)})
    inputs = comparison(models, ('producer', 'receiver'))
    actual = inputs.desired_reference('receiver', symbol, consumer_kind, path, symbol['$attribute'])
    assert actual == symbol
    assert inputs.reference_same(actual, copy.deepcopy(symbol), consumer_kind, path) is True
    typed = inputs.normalize_model_reference('receiver', '001-002', 'value', reference(producer.replace('.', '_') + '_001', attribute))
    assert typed == symbol, typed
    inputs.resources['producer']['002'] = dict(inputs.resources['producer']['001'])
    assert inputs.reference_same(typed, ResourceReference(dict(symbol, **{'$resource': ['producer', '002']})), consumer_kind, path) is False
    with pytest.raises(ValueError):
        resolver.validate_attribute(producer, 'UnsupportedAttribute', field=prop)
    wrong = 'KMS.Key' if producer == 'S3.Bucket' else 'S3.Bucket'
    with pytest.raises(ValueError):
        resolver.validate_attribute(wrong, 'Arn', field=prop)
    inputs.resources['producer']['001']['resourceMode'] = 'IMPORT'
    with pytest.raises(Blocked):
        inputs.desired_reference('receiver', symbol, consumer_kind, path, symbol['$attribute'])


def test_catalog_and_context_boundaries(models):
    catalog = DesignSchemaCatalog(models)
    for kind in catalog.resource_types:
        assert catalog.schema(kind)['typeName'] == kind
    assert 'AWS::SSM::Parameter' not in catalog.resource_types
    for prop, (selector, choices) in CONTEXT_PROPERTIES.items():
        assert contract(prop, {}) == {}
        for value, (producer, _) in choices.items():
            assert producer in contract(prop, {selector: value})


@pytest.mark.parametrize('kind,rows', [
    ('Glue.Job', [['001-002', 'Glue.Job.DefaultArguments', '`' + json.dumps({'--bucket': reference('S3_Bucket_001', 'BucketName'), '--ordinary': 'keep'}) + '`', 'arguments'],
                  ['001-003', 'Glue.Job.NonOverridableArguments', '`' + json.dumps({'--bucket': reference('S3_Bucket_001', 'BucketName')}) + '`', 'fixed']]),
    ('CodeBuild.Project', [['001-002', 'CodeBuild.Project.Environment.EnvironmentVariables[].Name', '`SECRET`', 'variable'],
                           ['001-003', 'CodeBuild.Project.Environment.EnvironmentVariables[].Type', '`SECRETS_MANAGER`', 'variable'],
                           ['001-004', 'CodeBuild.Project.Environment.EnvironmentVariables[].Value', '`' + json.dumps(reference('SecretsManager_Secret_001', 'Id')) + '`', 'variable']]),
    ('Lambda.Function', [['001-002', 'Lambda.Function.VpcConfig.SubnetIds', '`' + json.dumps([reference('EC2_Subnet_001', 'SubnetId'), reference('EC2_Subnet_002', 'SubnetId')]) + '`', 'subnets'],
                         ['001-003', 'Lambda.Function.VpcConfig.SecurityGroupIds', '`' + json.dumps([reference('EC2_SecurityGroup_001', 'GroupId')]) + '`', 'groups']]),
])
@pytest.mark.parametrize('observed,expected', [(None, 'unresolved'), ('PENDING_DEPLOY', 'pending_deploy'), ('confirmed-value', 'confirmed-value')])
def test_common_markdown_projection_and_restoration(models, kind, rows, observed, expected):
    resource(models, 's3', 'S3.Bucket', attribute='BucketName', observed=observed)
    resource(models, 'secret', 'SecretsManager.Secret', attribute='Id', observed=observed)
    scope, first = resource(models, 'subnet', 'EC2.Subnet', attribute='SubnetId', observed=observed)
    _, second = resource(models, 'subnet', 'EC2.Subnet', attribute='SubnetId', observed=observed, number='002')
    first.update(second)
    save(scope, first)
    resource(models, 'groups', 'EC2.SecurityGroup', attribute='GroupId', observed=observed)
    scope, values = resource(models, 'receiver', kind, attribute='FunctionName' if kind == 'Lambda.Function' else 'Name')
    values['desired.row.001-001.value'] = '`fixture`'
    for rid, prop, value, comment in rows:
        values.update({f'desired.row.{rid}.property': prop, f'desired.row.{rid}.value': value, f'desired.row.{rid}.comment': comment})
    save(scope, values)
    original = copy.deepcopy(values)
    shown = reference_display(values, scope.path, models)
    rendered = display_rows(kind, [[rid, row['property'], row['value'], row['comment']] for rid, row in entries(shown, 'desired.row.')], models)
    assert expected in str(rendered) and '$modelRef' not in str(rendered)
    document = [f'### {kind}: fixture', '', *row_table(rendered)]
    expanded, _ = expanded_design(document, root=models)
    restored = [[cell.strip() for cell in line.strip("|").split("|")] for line in expanded if line.startswith("|")][2:]
    assert [row[1:] for row in restored] == [
        [row['property'], row['value'], row['comment']] for rid, row in entries(values, 'desired.row.')]
    assert restored_reference_rows(rendered, kind, models, mode='CREATE')[0] == [
        [rid, row['property'], row['value'], row['comment']] for rid, row in entries(values, 'desired.row.')]
    assert values == original
    tampered = copy.deepcopy(rendered)
    tampered[-1][2] = '`tampered`'
    with pytest.raises(ValueError):
        expanded_design([f'### {kind}: fixture', '', *row_table(tampered)], root=models)


@pytest.mark.parametrize('suffix,equal', [('/', True), ('/prefix/', False), ('', False)])
def test_cloudtrail_object_prefix_semantics(models, suffix, equal):
    payload = [{'DataResources': [{'Type': 'AWS::S3::Object', 'Values': [reference('S3_Bucket_001', 'ObjectArn')]},
                                  {'Type': 'AWS::Lambda::Function', 'Values': [reference('Lambda_Function_001', 'Arn')]}]}]
    resource(models, 'lambda', 'Lambda.Function', attribute='Arn')
    inputs, prepared, _, _ = prepare(models, 'CloudTrail.Trail', 'EventSelectors', payload)
    desired = prepared.require_value()[0]['DataResources']
    bucket = ResourceReference({'$resource': ['producer', '001'], '$attribute': 'Arn'})
    actual = Expression('Sub', ['${Bucket}' + suffix, {'Bucket': bucket}])
    assert inputs.reference_same(desired[0]['Values'][0], actual, 'CloudTrail.Trail', 'EventSelectors[].DataResources[].Values[]') is equal
    function = ResourceReference({'$resource': ['lambda', '001'], '$attribute': 'Arn'})
    assert inputs.reference_same(desired[1]['Values'][0], function, 'CloudTrail.Trail', 'EventSelectors[].DataResources[].Values[]') is True
    assert prepared.warnings == []


@pytest.mark.parametrize('producer,attribute,consumer,prop', [
    ('SecretsManager.Secret', 'Name', 'SecretsManager.RotationSchedule', 'SecretId'),
    ('SecretsManager.Secret', 'Id', 'SecretsManager.RotationSchedule', 'SecretId'),
    ('Events.Rule', 'Name', 'Glue.Job', 'DefaultArguments'),
    ('KMS.Alias', 'Arn', 'CodePipeline.Pipeline', 'ArtifactStore.EncryptionKey.Id'),
])
def test_setting_attributes_and_consumers(models, producer, attribute, consumer, prop):
    node = reference(producer.replace('.', '_') + '_001', attribute)
    payload = {'--rule': node} if prop == 'DefaultArguments' else node
    inputs, prepared, scope, _ = prepare(models, consumer, prop, payload, producer=producer, attribute=attribute)
    desired = prepared.require_value()
    symbol = desired['--rule'] if prop == 'DefaultArguments' else desired
    assert isinstance(symbol, ResourceReference), symbol
    assert inputs.reference_same(symbol, copy.deepcopy(symbol), consumer, prop) is True
    assert prepared.warnings == []
    resolver = Resolver(models)
    with pytest.raises(ValueError):
        resolve(parse(node), scope, resolver, field='Lambda.Function.Role')
    if producer == 'Events.Rule':
        inputs.stack_inputs['producer'][0]['Resources']['Resource001'] = {
            'Type': 'AWS::Events::Rule', 'Properties': {'Name': 'synthetic-rule'}}
        # One producer mapping per stack/logical ID.
        inputs.resources['receiver']['001']['cfn-logicalId'] = 'consumer-Policy'
        actual = inputs.evaluate('producer', {'Fn::GetAtt': ['Resource001', 'RuleName']})
        assert inputs.reference_same(symbol, actual, consumer, prop) is True
        assert inputs.reference_same(symbol, 'synthetic-rule', consumer, prop) is True


@pytest.mark.parametrize('resource_type', ['VPC', 'Subnet', 'UNKNOWN', None])
def test_flowlog_comparison_and_validation(models, resource_type):
    node = reference('EC2_VPC_001', 'VpcId')
    resource(models, 'producer', 'EC2.VPC', attribute='VpcId')
    scope, authored = resource(models, 'receiver', 'EC2.FlowLog', attribute='ResourceType')
    authored['desired.row.001-001.value'] = '`' + str(resource_type) + '`'
    authored.update({'desired.row.001-002.property': 'EC2.FlowLog.ResourceId',
                     'desired.row.001-002.value': '`' + json.dumps(node) + '`', 'desired.row.001-002.comment': 'flow'})
    save(scope, authored)
    inputs = comparison(models, ('producer', 'receiver'))
    row = dict(entries(authored, 'desired.row.'))['001-002']
    desired = inputs.prepare_value('receiver', row, 'EC2.FlowLog', row_id='001-002').require_value()
    if resource_type == 'VPC':
        assert isinstance(desired, ResourceReference), desired
        validate_json_settings(authored, scope.path)
        assert inputs.reference_same(desired, ResourceReference(dict(desired)), 'EC2.FlowLog', 'ResourceId') is True
    else:
        assert isinstance(desired, Expression), desired
        with pytest.raises(ValueError):
            validate_json_settings(authored, scope.path)


@pytest.mark.parametrize('field,producer,attribute', [
    ('Lambda.Function.VpcConfig.SubnetIds', 'EC2.Subnet', 'SubnetId'),
    ('Lambda.Function.VpcConfig.SecurityGroupIds', 'EC2.SecurityGroup', 'GroupId'),
])
def test_array_elements_and_scalar_array_boundary(models, field, producer, attribute):
    node = reference(producer.replace('.', '_') + '_001', attribute)
    resource(models, 'producer', producer, attribute=attribute)
    scope, _ = resource(models, 'receiver', 'Lambda.Function', attribute='FunctionName')
    resolver = Resolver(models)
    resolve(parse(node), scope, resolver, field=field + '[]')
    with pytest.raises(ValueError, match='type'):
        resolve(parse(node), scope, resolver, field=field)
    with pytest.raises(ValueError):
        resolve(parse(reference(producer.replace('.', '_') + '_001', 'Arn')), scope, resolver, field=field + '[]')


@pytest.mark.parametrize('kind,field,value', [
    ('Glue.Job', 'Glue.Job.DefaultArguments', {'--bad': {}}),
    ('Glue.Job', 'Glue.Job.NonOverridableArguments', {'--bad': reference(attribute='')}),
    ('Lambda.Function', 'Lambda.Function.VpcConfig.SubnetIds', [{}]),
])
def test_malformed_display_objects(models, kind, field, value):
    with pytest.raises(ValueError):
        display_rows(kind, [['001-001', field, '`' + json.dumps(value) + '`', 'bad']], models)


def test_unknown_expression_operand_never_matches(models):
    inputs = comparison(models, ())
    value = Expression('Sub', ['${Unknown}/', {'Unknown': Expression('Unverified', ['missing'])}])
    assert inputs.reference_same(value, copy.deepcopy(value), 'Glue.Job', 'DefaultArguments') is None


def test_unsupported_ssm_and_name_id_equivalence(models):
    resource(models, 'producer', 'SSM.Parameter', attribute='Name')
    scope, _ = resource(models, 'receiver', 'CodeBuild.Project', attribute='Name')
    with pytest.raises(ValueError, match='Framework unsupported'):
        resolve(parse(reference('SSM_Parameter_001', 'Name')), scope, Resolver(models),
                field='CodeBuild.Project.Environment.EnvironmentVariables[].Value', context={'Type': 'PARAMETER_STORE'})
    inputs, prepared, _, _ = prepare(models, 'SecretsManager.RotationSchedule', 'SecretId',
        reference('SecretsManager_Secret_001', 'Name'), producer='SecretsManager.Secret', attribute='Name')
    symbol = prepared.require_value()
    arn = ResourceReference(dict(symbol, **{'$attribute': 'Id'}))
    assert inputs.reference_same(symbol, arn, 'SecretsManager.RotationSchedule', 'SecretId') is not True


@pytest.mark.parametrize('producer,attribute,data_type', [
    ('S3.Bucket', 'ObjectArn', 'AWS::S3::Object'),
    ('Lambda.Function', 'Arn', 'AWS::Lambda::Function'),
])
def test_cloudtrail_split_context(models, producer, attribute, data_type):
    resource(models, 'producer', producer, attribute=attribute)
    scope, authored = resource(models, 'receiver', 'CloudTrail.Trail', attribute='TrailName')
    prefix = 'CloudTrail.Trail.EventSelectors[].DataResources[].'
    authored.update({'desired.row.001-001.value': '`fixture`',
        'desired.row.001-002.property': prefix + 'Type', 'desired.row.001-002.value': '`' + data_type + '`',
        'desired.row.001-002.comment': 'type', 'desired.row.001-003.property': prefix + 'Values',
        'desired.row.001-003.value': '`' + json.dumps([reference(producer.replace('.', '_') + '_001', attribute)]) + '`',
        'desired.row.001-003.comment': 'values'})
    save(scope, authored)
    validate_json_settings(authored, scope.path)
    authored['desired.row.001-002.value'] = '`UNKNOWN`'
    with pytest.raises(ValueError, match='context'):
        validate_json_settings(authored, scope.path)


def test_codebuild_plaintext_and_missing_sibling_type(models):
    node = reference('S3_Bucket_001', 'BucketName')
    payload = {'EnvironmentVariables': [{'Name': 'Good', 'Type': 'PLAINTEXT', 'Value': node},
                                        {'Name': 'Missing', 'Value': node}]}
    _, prepared, _, _ = prepare(models, 'CodeBuild.Project', 'Environment', payload, attribute='BucketName')
    good, missing = prepared.require_value()['EnvironmentVariables']
    assert isinstance(good['Value'], ResourceReference), good
    assert isinstance(missing['Value'], Expression), missing


def test_all_aws_return_contracts_are_explicit_and_schema_supported(models):
    catalog = DesignSchemaCatalog(models)
    resolver = Resolver(models)
    for aws_kind in catalog.resource_types:
        kind = aws_kind.removeprefix('AWS::').replace('::', '.')
        schema = catalog.schema(kind)
        for pointer in schema.get('readOnlyProperties', ()):
            if '*' not in pointer:
                attribute = pointer.removeprefix('/properties/').replace('/', '.')
                resolver.validate_attribute(kind, attribute)
        for attribute in GETATT_ATTRIBUTES.get(kind, ()):
            resolver.validate_attribute(kind, attribute)
        if kind in ARN_SHAPES:
            resolver.validate_attribute(kind, 'Arn')
        if kind in REF_ATTRIBUTES:
            resolver.validate_attribute(kind, REF_ATTRIBUTES[kind])


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
