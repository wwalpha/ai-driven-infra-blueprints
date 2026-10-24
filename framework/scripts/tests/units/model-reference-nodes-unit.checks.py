"""Common typed Model references: pure syntax and small authored local snapshots."""

import copy
import json
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model.sources as sources
import pytest
from comparison.values import compare_values
from design.catalog import DesignSchemaCatalog
from design.policy_tables import (
    Policy,
    policy_document_lines,
    raw_policy_lines,
    validate_policy_document,
)
from json_intrinsics import project_document
from model.adapters.observed import observed_destinations, propagate_references
from model.core import entries
from model.identity import Resolver
from model.impact_graph import Graph
from model.importing.sources import has_reference
from model.operations import _compare_field, validate_candidates
from model.projection import execution_document, observed_value, reference_display
from model.reference_nodes import nodes, parse, resolve
from model.reference_nodes import project as display
from model.references import Usage, incoming, symbolic, usages
from model.sources import load_model
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
from utils.json_format import validate_aws_document

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.fixture
def models(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        yield project(tmp_path)


def check_parse():
    node = parse(reference())
    assert (node.logical_id, node.attribute, node.pointer) == ('KMS_Key_001', 'Arn', '')
    assert [item.pointer for item in nodes({'a/b': [reference()]})] == ['/a~1b/0']
    assert [item.pointer for item in nodes({'~': json.dumps(reference())})] == ['/~0']
    raw = '`' + json.dumps(reference()) + '`'
    assert has_reference(raw)
    assert observed_value('001-001', {'value': raw, 'property': 'Lambda.Function.Role'}, '`confirmed`', ()) == raw


@pytest.mark.parametrize('value', [
    {}, {'$modelRef': None}, {'$modelRef': []}, {'$modelRef': {}},
    {'$modelRef': {'logicalId': 'KMS_Key_001'}}, {'$modelRef': {'attribute': 'Arn'}},
    {'$modelRef': {'logicalId': 'KMS_Key_001', 'attribute': 'Arn', 'scope': 'qa/team'}},
    {'$modelRef': {'logicalId': 1, 'attribute': 'Arn'}}, reference(attribute=None),
    reference(attribute=''), reference(logical=''), reference(logical='../other'),
    {**reference(), 'deployed': False}, {'$modelRef': {**reference()['$modelRef'], 'physicalValue': 'x'}},
])
def check_invalid(value):
    with pytest.raises(ValueError):
        parse(value)


def check_target_index_and_cache(tmp_path, models):
    producer, _, consumer, _ = models
    resource(tmp_path, 'kms', 'KMS.Key', target='other')
    resolver = Resolver(tmp_path)
    with patch.object(sources, '_read_model', wraps=sources._read_model) as reader:
        for _ in range(10):
            result = resolve(parse(reference()), consumer, resolver)
            assert result[0].scope == producer and result[1] == '001'
        assert reader.call_count == 2
    resource(tmp_path, 'duplicate', 'KMS.Key')
    with pytest.raises(ValueError, match='ambiguous'):
        resolve(parse(reference()), consumer, Resolver(tmp_path))


def check_missing_and_attributes(tmp_path, models):
    _, _, consumer, _ = models
    resolver = Resolver(tmp_path)
    with pytest.raises(ValueError, match='absent'):
        resolve(parse(reference(logical='KMS_Key_999')), consumer, resolver)
    with pytest.raises(ValueError, match='unsupported'):
        resolve(parse(reference(attribute='RoleName')), consumer, resolver)
    with pytest.raises(ValueError, match='type differs'):
        resolve(parse(reference()), consumer, resolver, field='Lambda.Function.Role')
    with pytest.raises(ValueError, match='unsupported'):
        resolve(parse(reference(attribute='KeyId')), consumer, resolver, field='Lambda.Function.KmsKeyArn')


@pytest.mark.parametrize('kind,service,attribute,consumer_kind,property_name,expression', [
    ('KMS.Key', 'kms', 'Arn', 'IAM.ManagedPolicy', 'PolicyDocument', {'Fn::GetAtt': ['Resource001', 'Arn']}),
    ('S3.Bucket', 's3', 'Arn', 'IAM.ManagedPolicy', 'PolicyDocument', {'Fn::GetAtt': ['Resource001', 'Arn']}),
    ('EC2.VPC', 'vpc', 'VpcId', 'EC2.Subnet', 'VpcId', {'Ref': 'Resource001'}),
    ('EC2.Subnet', 'vpc', 'SubnetId', 'EC2.Instance', 'SubnetId', {'Ref': 'Resource001'}),
    ('IAM.Role', 'roles', 'Arn', 'Lambda.Function', 'Role', {'Fn::GetAtt': ['Resource001', 'Arn']}),
    ('CodeCommit.Repository', 'codecommit', 'Name', 'Lambda.Function', 'Description', {'Fn::GetAtt': ['Resource001', 'Name']}),
    ('CodeCommit.Repository', 'codecommit', 'RepositoryName', 'Lambda.Function', 'Description', {'Fn::GetAtt': ['Resource001', 'Name']}),
])
def check_cross_service_comparison(tmp_path, models, kind, service, attribute, consumer_kind, property_name, expression):
    _, _, consumer, policy = models
    resource(tmp_path, service, kind, attribute=attribute)
    # Replace the initial KMS producer if another resource owns the same CFn identity.
    if service != 'kms':
        (tmp_path / 'model/qa/team/kms.properties').unlink()
    policy['desired.row.001-002.property'] = consumer_kind + '.' + property_name
    node = reference(kind.replace('.', '_') + '_001', attribute)
    row = {'property': consumer_kind + '.' + property_name, 'value': '`' + json.dumps(node) + '`'}
    if property_name == 'PolicyDocument':
        row['document'] = json.dumps({'Statement': [{'Effect': 'Allow', 'Action': '*', 'Resource': node}]})
    if 'document' not in row:
        policy.pop('desired.row.001-002.document', None)
    policy.update({f'desired.row.001-002.{key}': value for key, value in row.items()})
    save(consumer, policy)
    inputs = comparison(tmp_path, ('iam', service))
    inputs.stack_inputs['producer'][0]['Resources']['Resource001']['Type'] = 'AWS::' + kind.replace('.', '::')
    prepared = inputs.prepare_value('iam', row, consumer_kind, stack='consumer', row_id='001-002')
    desired = prepared.require_value()
    actual = inputs.evaluate('producer', expression)
    if property_name == 'PolicyDocument':
        desired = desired['Statement'][0]['Resource']
    assert isinstance(desired, ResourceReference), desired
    assert inputs.reference_same(desired, actual, consumer_kind, property_name) is True
    assert prepared.warnings == []


@pytest.mark.parametrize('expression', [
    {'Fn::ImportValue': 'ExampleKmsKeyArn'}, {'Ref': 'Resource001'}, {'Fn::GetAtt': ['Resource001', 'Arn']},
])
def check_evaluator_normalization(tmp_path, models, expression):
    inputs = comparison(tmp_path)
    # Reuse the existing stack loader's cached-input path for export traversal.
    inputs.stack = partial(stack, inputs)
    actual = inputs.evaluate('producer' if 'Fn::ImportValue' not in expression else 'consumer', expression)
    assert actual['$resource'] == ['kms', '001']
    assert actual['$attribute'] == ('KeyId' if 'Ref' in expression else 'Arn')


def stack(inputs, unit):
    return inputs.root / (unit['name'] + '.yaml'), inputs.stack_inputs[unit['name']]


def check_no_false_matches_and_atomic_missing(tmp_path, models):
    _, _, consumer, policy = models
    inputs = comparison(tmp_path)
    row = dict(entries(policy, 'desired.row.'))['001-002']
    desired = inputs.prepare_value('iam', row, 'IAM.ManagedPolicy', stack='consumer', row_id='001-002').require_value()
    symbol = desired['Statement'][0]['Resource']
    other = ResourceReference({'$resource': ['kms', '999'], '$attribute': 'Arn'})
    assert inputs.reference_same(symbol, other, 'IAM.ManagedPolicy', 'PolicyDocument.Statement[].Resource') is False
    inputs.stack = partial(stack, inputs)
    inputs.stack_inputs['producer'][0]['Outputs'].clear()
    with pytest.raises(Blocked):
        inputs.evaluate('consumer', {'Fn::ImportValue': 'ExampleKmsKeyArn'})
    policy['desired.row.001-002.document'] = json.dumps({'Environment': {'Variables': {'KEY': reference('KMS_Key_999')}}})
    save(consumer, policy)
    inputs = comparison(tmp_path)
    row = dict(entries(policy, 'desired.row.'))['001-002']
    prepared = inputs.prepare_value('iam', row, 'IAM.ManagedPolicy', stack='consumer', row_id='001-002')
    value = prepared.require_value()
    assert isinstance(value['Environment']['Variables']['KEY'], Expression)
    result = compare_values(value, {}, 'PolicyDocument', exact=True, reference=partial(reference_decision, inputs))
    assert result.equal is False
    assert compare_values(value, copy.deepcopy(value), 'PolicyDocument', exact=True, reference=partial(reference_decision, inputs)).equal is None


def reference_decision(inputs, left, right, path):
    return inputs.reference_decision(left, right, 'IAM.ManagedPolicy', path)


@pytest.mark.parametrize('observed,expected', [(None, 'unresolved'), ('PENDING_DEPLOY', 'pending_deploy'),
    ('arn:aws:kms:ap-northeast-1:123456789012:key/confirmed', 'arn:aws:kms:ap-northeast-1:123456789012:key/confirmed')])
def check_display_and_stable_design(tmp_path, models, observed, expected):
    producer, values, consumer, policy = models
    if observed is not None:
        values['observed.row.001-001.value'] = '`' + observed + '`'
        save(producer, values)
    original = copy.deepcopy(policy)
    warnings = []
    validate_json_settings(policy, consumer.path, warnings=warnings)
    document = json.loads(policy['desired.row.001-002.document'])
    assert execution_document(document, tmp_path, scope=consumer, warnings=warnings) == document
    assert warnings == []
    displayed = reference_display(policy, consumer.path, tmp_path)
    assert json.loads(displayed['desired.row.001-002.document'])['Statement'][0]['Resource'] == expected
    assert '$modelRef' not in displayed['desired.row.001-002.document']
    assert policy == original
    with pytest.raises(ValueError, match='Model reference'):
        validate_aws_document(document)
    with pytest.raises(ValueError, match='Model reference'):
        validate_aws_document(json.dumps(document))
    broken = {'Statement': [{'Effect': 'Allow', 'Resource': {'Ref': 'Missing'}}]}
    project_document(broken, warnings=warnings)
    assert [warning['code'] for warning in warnings] == ['json.intrinsic.unresolved']


def check_every_markdown_fallback_and_schema(tmp_path, models):
    _, _, consumer, policy = models
    p = Policy('test', 'iam/policy.json', 'saved-policy', 'ポリシー', 'IAM.ManagedPolicy.PolicyDocument')
    document = json.loads(policy['desired.row.001-002.document'])
    validate_policy_document(document, p, design=True)
    for candidate in (document, {'Unknown': reference()}, {'Statement': reference()}, [reference()], json.dumps(reference())):
        for render in (policy_document_lines, raw_policy_lines):
            output = '\n'.join(render(candidate, p))
            assert '$modelRef' not in output and 'unresolved' in output
    with pytest.raises(ValueError):
        validate_policy_document(json.loads(policy['desired.row.001-002.document']), p)
    catalog = DesignSchemaCatalog(tmp_path)
    assert catalog.literal_errors('Lambda.Function', 'Role', json.dumps(reference())) == []
    assert catalog.literal_errors('Events.Rule', 'EventPattern', json.dumps(reference())) == []
    assert catalog.literal_errors('EC2.Subnet', 'MapPublicIpOnLaunch', json.dumps(reference())) == []  # Semantic type checks require producer scope.
    assert display({'deep': [reference()]}) == {'deep': ['unresolved']}


def check_dependency_graph_and_observed_views(tmp_path, models):
    producer, values, consumer, policy = models
    source = load_model(consumer)
    usage, = [item for item in usages(source) if item.attribute]
    assert (usage.producer_scope, usage.logical_id, usage.pointer) == ('qa/team/kms', 'KMS_Key_001', '/Statement/0/Resource')
    assert incoming(load_model(producer), '001')[0][0] == consumer
    graph = Graph()
    graph.include({('qa', 'team', 'kms'): load_model(producer), ('qa', 'team', 'iam'): source}, sources.FileReads())
    assert ('qa', 'team', 'iam', 'resource', 'IAM_ManagedPolicy_001') in graph.traverse({('qa', 'team', 'kms', 'resource', 'KMS_Key_001')})
    assert symbolic(source)['desired.row.001-002.document']['Statement'][0]['Resource'].format == 'model'
    changes, loaded = {producer.path: {}}, {producer.path: values}
    identifiers = {('qa', 'team', 'kms', 'KMS_Key_001'): '`confirmed`'}
    propagate_references(tmp_path, loaded, changes, identifiers)
    assert consumer.path in changes and changes[consumer.path] == {}
    destinations, views, _ = observed_destinations(tmp_path, 'qa', 'team', loaded, changes, check_scope=False)
    assert tmp_path / 'docs/designs/qa/team/iam.md' in views
    assert consumer.path not in destinations
    assert policy == load_model(consumer).authoritative


def check_retarget_keeps_attribute_and_siblings():
    key, pointer = 'desired.row.001-002.document', '/Resource'
    old = SimpleNamespace(scope=SimpleNamespace(path=Path('/before/iam.properties')),
                          authoritative={key: json.dumps({'Resource': reference(), 'keep': ['same', 1]})})
    new = SimpleNamespace(scope=SimpleNamespace(path=Path('/after/iam.properties')),
                          authoritative={key: json.dumps({'Resource': reference('KMS_Key_002'), 'keep': ['same', 1]})})
    declaration = SimpleNamespace(pointer=pointer, source='qa/team/kms/001', destination='qa/team/kms/002')
    previous = Usage(key, pointer, 0, 0, '', 'qa/team/kms', 'resource', '001', logical_id='KMS_Key_001', attribute='Arn')
    current = Usage(key, pointer, 0, 0, '', 'qa/team/kms', 'resource', '002', logical_id='KMS_Key_002', attribute='Arn')
    graph = {old.scope.path: [previous], new.scope.path: [current], 'editable_ids': {}, 'editable_text_ids': {},
             'resolved': {(old.scope.path, previous): declaration.source, (new.scope.path, current): declaration.destination},
             'addresses': {(old.scope.path, key, pointer): {declaration.source},
                           (new.scope.path, key, pointer): {declaration.destination}}}
    _compare_field(old, key, new, key, [declaration], [], graph)
    for changed in ({'Resource': reference('KMS_Key_002', 'KeyId'), 'keep': ['same', 1]},
                    {'Resource': reference('KMS_Key_002'), 'keep': ['changed', 1]}):
        new.authoritative[key] = json.dumps(changed)
        with pytest.raises(ValueError):
            _compare_field(old, key, new, key, [declaration], [], graph)


def check_deletion_rejected_and_protection_preserved(tmp_path, models):
    producer, _, consumer, policy = models
    assert incoming(load_model(producer), '001')
    producer.path.unlink()
    with pytest.raises(ValueError, match='absent'):
        validate_json_settings(policy, consumer.path)
    with pytest.raises(ValueError):
        validate_candidates(tmp_path, {consumer.path.relative_to(tmp_path)}, {}, {('qa', 'team', 'iam')})
    row = dict(entries(policy, 'desired.row.'))['001-002']
    prepared = comparison(tmp_path, ('iam',)).prepare_value('iam', row, 'IAM.ManagedPolicy', row_id='001-002')
    assert isinstance(prepared.require_value()['Statement'][0]['Resource'], Expression)


def check_import_and_receiving_forms_cannot_be_bypassed(tmp_path, models):
    producer, values, consumer, policy = models
    row = dict(entries(policy, 'desired.row.'))['001-002']
    values.pop('desired.resource.001.cfn-logicalId')
    values['desired.resource.001.resourceMode'] = 'IMPORT'
    save(producer, values)
    prepared = comparison(tmp_path).prepare_value('iam', row, 'IAM.ManagedPolicy', row_id='001-002')
    assert isinstance(prepared.require_value()['Statement'][0]['Resource'], Expression)
    values['desired.resource.001.resourceMode'] = 'CREATE'
    values['desired.resource.001.cfn-logicalId'] = 'producer-Resource001'
    save(producer, values)
    row['document'] = json.dumps({'Statement': [{'Effect': 'Allow', 'Resource': reference(attribute='KeyId')}]})
    policy['desired.row.001-002.document'] = row['document']
    save(consumer, policy)
    prepared = comparison(tmp_path).prepare_value('iam', row, 'IAM.ManagedPolicy', row_id='001-002')
    assert isinstance(prepared.require_value()['Statement'][0]['Resource'], Expression)


def check_unknown_attribute_equivalence_and_encoded_json(tmp_path, models):
    inputs = comparison(tmp_path)
    resource(tmp_path, 's3', 'S3.Bucket', attribute='BucketName')
    inputs.model('s3')
    left = ResourceReference({'$resource': ['s3', '001'], '$attribute': 'Arn'})
    right = ResourceReference({'$resource': ['s3', '001'], '$attribute': 'BucketName'})
    assert inputs.reference_same(left, right, 'IAM.ManagedPolicy', 'PolicyDocument.Resource') is None
    row = {'property': 'IAM.ManagedPolicy.PolicyDocument', 'value': '',
           'document': json.dumps({'Encoded': json.dumps(reference())})}
    prepared = inputs.prepare_value('iam', row, 'IAM.ManagedPolicy', row_id='001-002')
    assert isinstance(prepared.require_value()['Encoded'], Expression)


def check_return_attribute_mapping_and_identifier_pending(tmp_path, models):
    producer, values, consumer, policy = models
    values['desired.row.001-001.property'] = 'KMS.Key.KeyId'
    values['observed.row.001-001.value'] = '`PENDING_DEPLOY`'
    save(producer, values)
    assert 'pending_deploy' in reference_display(policy, consumer.path, tmp_path)['desired.row.001-002.document']
    # Resolver's anchor path remains usable after logical indexing populated its snapshot cache.
    resolver = Resolver(tmp_path)
    resolve(parse(reference()), consumer, resolver)
    assert resolver.resolve('[key](kms.md#saved-001)', consumer)[1] == '001'


@pytest.mark.parametrize('container', [reference(), {'Statement': reference()},
    {'Statement': [{'Effect': 'Allow', 'Condition': reference()}]}])
def check_string_reference_cannot_replace_policy_objects(container):
    policy = Policy('test', 'iam/policy.json', 'policy', 'policy', 'IAM.ManagedPolicy.PolicyDocument')
    with pytest.raises(ValueError):
        validate_policy_document(container, policy, design=True)


def check_scalar_value_and_json_are_stable(tmp_path, models):
    producer, values, consumer, policy = models
    resource(tmp_path, 'vpc', 'EC2.VPC', attribute='VpcId', observed='vpc-0123456789abcdef0')
    key = 'desired.row.001-003.value'
    policy.update({'desired.row.001-003.property': 'EC2.SecurityGroup.VpcId', key: '`' + json.dumps(reference('EC2_VPC_001', 'VpcId')) + '`',
                   'desired.row.001-003.comment': '合成'})
    save(consumer, policy)
    original = json.loads(policy['desired.row.001-002.document'])
    design_json = json.dumps(execution_document(original, tmp_path, scope=consumer), sort_keys=True)
    assert reference_display(policy, consumer.path, tmp_path)[key] == '`vpc-0123456789abcdef0`'
    values['observed.row.001-001.value'] = '`PENDING_DEPLOY`'
    save(producer, values)
    assert json.dumps(execution_document(original, tmp_path, scope=consumer), sort_keys=True) == design_json
    assert policy[key] == '`' + json.dumps(reference('EC2_VPC_001', 'VpcId')) + '`'
    # An IMPORT pending marker describes unobserved acquisition, not confirmed AWS absence.
    values['desired.resource.001.resourceMode'] = 'IMPORT'
    values.pop('desired.resource.001.cfn-logicalId')
    save(producer, values)
    assert 'unresolved' in reference_display(policy, consumer.path, tmp_path)['desired.row.001-002.document']


def check_other_target_only_never_resolves(tmp_path, models):
    _, _, consumer, _ = models
    resource(tmp_path, 'kms', 'KMS.Key', target='other', number='002')
    with pytest.raises(ValueError, match='absent'):
        resolve(parse(reference('KMS_Key_002')), consumer, Resolver(tmp_path))


def check_external_metadata_does_not_hide_missing_parent(tmp_path, models):
    _, _, consumer, policy = models
    key = 'desired.row.001-002.document'
    policy[key] = json.dumps({'Known': 'confirmed-id', 'Unknown': reference('KMS_Key_999')})
    spec = {'consumerKey': key, 'pointer': '/Known', 'text': 'confirmed-id', 'occurrence': '1',
            'producerKind': 'resource', 'producerScope': 'qa/team/kms', 'producerLogicalId': 'KMS_Key_001',
            'resourceType': 'KMS.Key', 'format': 'identifier', 'property': 'KMS.Key.KeyId', 'labelPolicy': 'none'}
    policy.update({f'desired.reference.external.{field}': value for field, value in spec.items()})
    save(consumer, policy)
    inputs = comparison(tmp_path)
    row = dict(entries(policy, 'desired.row.'))['001-002']
    value = inputs.prepare_value('iam', row, 'IAM.ManagedPolicy', row_id='001-002').require_value()
    assert isinstance(value['Known'], ResourceReference)
    assert isinstance(value['Unknown'], Expression)
    assert compare_values(value, {}, 'PolicyDocument', exact=True, reference=partial(reference_decision, inputs)).equal is False


def check_attribute_type_does_not_produce_false_match(tmp_path, models):
    _, _, consumer, policy = models
    policy.pop('desired.row.001-002.document')
    policy['desired.row.001-002.property'] = 'EC2.Subnet.MapPublicIpOnLaunch'
    policy['desired.row.001-002.value'] = '`' + json.dumps(reference()) + '`'
    save(consumer, policy)
    inputs = comparison(tmp_path)
    row = dict(entries(policy, 'desired.row.'))['001-002']
    desired = inputs.prepare_value('iam', row, 'EC2.Subnet', row_id='001-002').require_value()
    assert isinstance(desired, Expression)
    actual = inputs.evaluate('producer', {'Fn::GetAtt': ['Resource001', 'Arn']})
    assert inputs.reference_same(desired, actual, 'EC2.Subnet', 'MapPublicIpOnLaunch') is None
    with pytest.raises(ValueError, match='type'):
        validate_json_settings(policy, consumer.path)


def check_returned_array_attribute_types(tmp_path, models):
    _, _, consumer, _ = models
    resource(tmp_path, 'route53', 'Route53.HostedZone', attribute='NameServers')
    resolver = Resolver(tmp_path)
    node = parse(reference('Route53_HostedZone_001', 'NameServers'))
    assert resolve(node, consumer, resolver)[2]['resourceType'] == 'Route53.HostedZone'
    resolver.catalog.schemas['AWS::Test::Receiver'] = {'properties': {'Values': {'type': 'array'}}}
    assert resolve(node, consumer, resolver, field='Test.Receiver.Values')[3] == 'NameServers'
    with pytest.raises(ValueError, match='type'):
        resolve(node, consumer, resolver, field='Lambda.Function.Description')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
