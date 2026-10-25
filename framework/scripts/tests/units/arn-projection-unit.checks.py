"""ARN projection combinations live here; callers test wiring and evidence only."""
import copy
import json
import sys
from functools import partial
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.arn_projection import project as project_arn
from model.identity import COUNTERS
from support.model_reference_fixtures import (
    FRAMEWORK,
    comparison,
    project,
    resource,
    save,
)
from utils.aws_mappings import mapping_alias
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference
from utils.reference_contracts import KMS_FORMS

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

PREFIX = 'arn:aws:kms:ap-northeast-1:123456789012:'
KEY_ID = '12345678-1234-1234-1234-123456789012'


def cached_stack(inputs, unit):
    return inputs.root / 'synthetic.yaml', inputs.stack_inputs[unit['name']]


def reference(identity='002', attribute='AliasArn'):
    return ResourceReference({'$resource': ['kms', identity], '$attribute': attribute})


def construction(source=None, *, prefix=PREFIX, suffix='', operation='Sub'):
    source = reference(attribute='AliasName') if source is None else source
    if operation == 'Sub':
        return Expression('Sub', [prefix + '${R}' + suffix, {'R': source}])
    return Expression('Join', ['', [prefix, source, suffix]])


@pytest.fixture
def inputs(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path), patch('socket.socket', side_effect=AssertionError('network forbidden')):
        _, values, _, _ = project(tmp_path)
        for identity in ('002', '003'):
            scope, alias = resource(tmp_path, 'kms', 'KMS.Alias', number=identity, attribute='AliasName')
            alias[f'desired.row.{identity}-001.value'] = '`alias/fixture`'
            values.update(alias)
        values[COUNTERS] = json.dumps({'KMS.Key': 1, 'KMS.Alias': 3})
        save(scope, values)
        result = comparison(tmp_path)
        result.stack = partial(cached_stack, result)
        result.stack_inputs['producer'][0]['Resources'].update({
            'Resource002': {'Type': 'AWS::KMS::Alias', 'Properties': {'AliasName': 'alias/fixture'}},
            'Resource003': {'Type': 'AWS::KMS::Alias', 'Properties': {'AliasName': 'alias/fixture'}}})
        yield result


@pytest.mark.parametrize('identity,source,projected,tail', [
    ('002', 'AliasName', 'AliasArn', ''), ('001', 'KeyId', 'Arn', 'key/')])
@pytest.mark.parametrize('operation', ['Sub', 'Join', 'nested'])
def test_projection_and_symbolic_comparison(inputs, identity, source, projected, tail, operation):
    value = construction(reference(identity, source), prefix=PREFIX + tail,
                         operation='Join' if operation == 'Join' else 'Sub')
    if operation == 'nested':
        value = Expression('Join', ['', [Expression('Sub', ['${R}', {'R': value}])]])
    before = copy.deepcopy(value)
    expected = reference(identity, projected)
    assert inputs.project_arn(value) == expected
    decision = inputs.reference_decision(expected, value, 'Logs.LogGroup', 'KmsKeyId')
    assert decision.equal is True and decision.diagnostics[0]['current_aws_verified'] is False
    assert decision.diagnostics[0]['evidence_type'] == 'logical_reference'
    assert value == before
    if source == 'KeyId':
        assert inputs.reference_decision(PREFIX + 'key/' + KEY_ID, value, 'Logs.LogGroup', 'KmsKeyId').equal is None


@pytest.mark.parametrize('prop', list(KMS_FORMS))
def test_projection_only_uses_registered_receiving_forms(inputs, prop):
    kind, path = '.'.join(prop.split('.')[:2]), '.'.join(prop.split('.')[2:])
    decision = inputs.reference_decision(reference(), construction(), kind, path)
    assert decision.equal is ('AliasArn' in KMS_FORMS[prop])
    with patch.object(inputs, 'project_arn', side_effect=AssertionError('unregistered receiving property')):
        assert inputs.reference_decision(reference(), construction(), 'Glue.Job', 'DefaultArguments').equal is True


@pytest.mark.parametrize('prefix,suffix', [
    ('extra/' + PREFIX, ''), (PREFIX, '/extra'), (PREFIX, ':'),
    (PREFIX.replace('arn:aws:', 'arn:aws-cn:'), ''),
    (PREFIX.replace('ap-northeast-1', 'us-east-1'), ''),
    (PREFIX.replace('123456789012', '999999999999'), '')])
def test_unproven_shape_or_scope_never_falls_back(inputs, prefix, suffix):
    value = construction(prefix=prefix, suffix=suffix)
    assert inputs.project_arn(value) is None
    for left, right in [(reference(), value), (value, copy.deepcopy(value))]:
        assert inputs.reference_decision(left, right, 'Logs.LogGroup', 'KmsKeyId').equal is None
    assert inputs.reference_decision(prefix + 'alias/fixture' + suffix, value, 'Logs.LogGroup', 'KmsKeyId').equal is not True


def test_different_producers_with_equal_names_cannot_match(inputs):
    value = construction(reference('003', 'AliasName'))
    decision = inputs.reference_decision(reference(), value, 'Logs.LogGroup', 'KmsKeyId')
    assert decision.equal is False
    assert 'different KMS ARN Producer' in decision.diagnostics[0]['reason']
    other = construction()
    assert inputs.reference_decision(other, value, 'Logs.LogGroup', 'KmsKeyId').equal is False


@pytest.mark.parametrize('field,old,new', [
    ('Partition', 'aws', 'aws-cn'), ('Region', 'ap-northeast-1', 'us-east-1'),
    ('AccountId', '123456789012', '999999999999')])
def test_projection_uses_producer_context_without_borrowing_consumer_context(inputs, field, old, new):
    document, parameters, pseudo = inputs.stack_inputs['producer']
    inputs.stack_inputs['producer'] = document, parameters, dict(pseudo, **{'AWS::' + field: new})
    assert inputs.project_arn(construction()) is None
    value = construction(prefix=PREFIX.replace(old, new, 1))
    assert inputs.project_arn(value) == reference()
    assert inputs.reference_decision(reference(), value, 'Logs.LogGroup', 'KmsKeyId').equal is True


def test_saved_reference_evidence_is_checked_before_projection(inputs):
    source = reference(attribute='AliasName')
    source.saved_literal = 'alias/fixture'
    source.saved_property = 'KMS.Alias.AliasName'
    source.declared_format = 'identifier'
    decision = inputs.reference_decision(reference(), construction(source), 'Logs.LogGroup', 'KmsKeyId')
    assert decision.equal is not True
    assert decision.diagnostics


def test_key_and_alias_arn_are_different(inputs):
    value = construction(reference('001', 'KeyId'), prefix=PREFIX + 'key/')
    assert inputs.reference_decision(reference(), value, 'Logs.LogGroup', 'KmsKeyId').equal is False


@pytest.mark.parametrize('fault', ['missing', 'import', 'stack', 'duplicate', 'type', 'transform', 'condition',
                                  'partition', 'region', 'account'])
def test_producer_scope_requires_the_owning_stack(inputs, fault):
    document, parameters, pseudo = inputs.stack_inputs['producer']
    # Consumer context remains valid and must never substitute for the Producer.
    pseudo = dict(pseudo)
    inputs.stack_inputs['producer'] = document, parameters, pseudo
    if fault in {'partition', 'region', 'account'}:
        pseudo.pop({'partition': 'AWS::Partition', 'region': 'AWS::Region', 'account': 'AWS::AccountId'}[fault])
    elif fault == 'missing':
        source = reference('999', 'AliasName')
        assert inputs.reference_decision(reference(), construction(source), 'Logs.LogGroup', 'KmsKeyId').equal is None
        return
    elif fault == 'import':
        inputs.resources['kms']['002']['resourceMode'] = 'IMPORT'
    elif fault == 'stack':
        inputs._templates = []
    elif fault == 'duplicate':
        inputs._index = dict(inputs.index())
        inputs._index['producer', 'Resource002'].append(inputs._index['producer', 'Resource003'][0])
    elif fault == 'type':
        document['Resources']['Resource002']['Type'] = 'AWS::KMS::Key'
    elif fault == 'transform':
        document['Transform'] = 'Unknown'
    else:
        document['Resources']['Resource002']['Condition'] = 'Unknown'
    assert inputs.project_arn(construction()) is None
    assert inputs.reference_decision(reference(), construction(), 'Logs.LogGroup', 'KmsKeyId').equal is None


@pytest.mark.parametrize('value', [
    Expression('Sub', ['${Unknown}', {}]), Expression('Future', []),
    Expression('Select', [0, Expression('Split', [':', reference()])]),
    construction(Expression('Unverified', [])),
    Expression('Join', ['', [PREFIX, reference(attribute='AliasName'), reference('003', 'AliasName')]]),
    Expression('Sub', [PREFIX + '${R}', {'R': reference(attribute='AliasName'), 'Other': reference('003', 'AliasName')}]),
    construction(reference(attribute='TargetKeyId'))])
def test_incomplete_or_unregistered_expressions_are_uncompared(inputs, value):
    assert inputs.project_arn(value) is None
    assert inputs.reference_decision(reference(), value, 'Logs.LogGroup', 'KmsKeyId').equal is None
    assert inputs.reference_decision(value, copy.deepcopy(value), 'Logs.LogGroup', 'KmsKeyId').equal is not True


@pytest.mark.parametrize('operation', ['direct', 'Sub', 'Join', 'literal'])
def test_existing_reference_and_literal_results(inputs, operation):
    symbol = reference()
    value = {'direct': symbol, 'Sub': Expression('Sub', ['${R}', {'R': symbol}]),
             'Join': Expression('Join', ['', [symbol]]), 'literal': PREFIX + 'alias/fixture'}[operation]
    assert inputs.reference_decision(symbol, value, 'Logs.LogGroup', 'KmsKeyId').equal is True
    assert inputs.reference_decision(PREFIX + 'alias/fixture', value, 'Logs.LogGroup', 'KmsKeyId').equal is True


def test_alias_arn_projection_does_not_authorize_getatt(inputs):
    assert inputs.project_arn(construction()) == reference()
    with pytest.raises(Blocked, match='GetAtt'):
        inputs.evaluate('producer', {'Fn::GetAtt': ['Resource002', 'AliasArn']})


def test_normalizer_reuses_a_non_kms_shape_without_enabling_a_service():
    symbol = ResourceReference({'$resource': ['bucket', '001'], '$attribute': 'BucketName'})
    value = Expression('Join', ['', ['arn:aws:s3:::', symbol]])
    result = project_arn(value, resource_type=lambda value: 'S3.Bucket', producer_scope=lambda value: {
        'partition': 'aws', 'region': 'ap-northeast-1', 'account': '123456789012'})
    assert result == ResourceReference({'$resource': ['bucket', '001'], '$attribute': 'Arn'})


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
