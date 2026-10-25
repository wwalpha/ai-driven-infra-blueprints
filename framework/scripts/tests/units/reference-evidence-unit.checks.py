"""Offline reference proof through the shared evaluator and comparison pipeline."""
import copy
import json
import sys
from functools import partial
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from comparison import Comparison
from comparison.reference_evidence import Evidence
from comparison.resource import inactive_evidence, inline_owner
from comparison.services.iam import managed_policy_roles
from comparison.values import PreparedValue, compare_values
from design.catalog import DesignSchemaCatalog
from issues.materials import naming_materials
from model.references import declarations
from model.sources import ModelSnapshot, Scope
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import put_row
from utils.iac_values import (
    Expression,
    ResourceReference,
    same,
    unordered_same,
)
from utils.source_reads import FileReads

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

ROOT = Path(__file__).resolve().parents[4]
VPC = 'vpc-0123456789abcdef0'
KEY_ID = '12345678-1234-1234-1234-123456789012'
KEY_ARN = 'arn:aws:kms:ap-northeast-1:123456789012:key/' + KEY_ID
ATHENA_KMS = 'WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey'
KMS_RECEIVERS = [
    ('Athena.WorkGroup', ATHENA_KMS), ('Lambda.Function', 'KmsKeyArn'),
    ('Logs.LogGroup', 'KmsKeyId'),
    ('S3.Bucket', 'BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID'),
]


def stack_input(comparison, unit):
    return ROOT / 'infra/cloudformation/templates/team' / (unit['name'] + '.yaml'), comparison.stack_inputs[unit['name']]


def fixture():
    comparison = Comparison.__new__(Comparison)
    comparison.root, comparison.environment, comparison.directory = ROOT, 'fixture', 'team'
    comparison.target = {'iacEngine': 'cloudformation', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1'}
    comparison.catalog = DesignSchemaCatalog(ROOT)
    comparison.local_comparison = comparison.reference_models_loaded = True
    comparison.models, comparison.resources, comparison.rows = {}, {}, {}
    comparison.symbols, comparison.reference_formats, comparison.model_references = {}, {}, {}
    comparison.exports, comparison.export_failures, comparison.export_provenance = None, [], {}
    comparison._index = None
    comparison.sensitive_values, comparison.inputs, comparison.model_observations = set(), set(), set()
    comparison.read_hashes, comparison.model_reads = {}, FileReads()
    comparison.services, comparison.load_errors, comparison.warnings = [], [], []
    comparison.reference_unavailable, comparison.results, comparison.display_differences = {}, [], {}
    comparison.template_locations = {}
    pseudo = {'AWS::Partition': 'aws', 'AWS::Region': 'ap-northeast-1', 'AWS::AccountId': '123456789012'}
    comparison.stack_inputs = {name: ({'Resources': {}, 'Outputs': {}}, {}, pseudo)
                               for name in ('producer', 'consumer')}
    comparison.templates = lambda: [(name, {'name': name, 'template': name + '.yaml', 'parameters': name + '.json'}) for name in comparison.stack_inputs]
    comparison.stack = partial(stack_input, comparison)
    return comparison


def resource(comparison, service, identity, kind, logical, rows, *, properties=None, stack='producer'):
    metadata = {'resourceType': kind, 'logicalId': kind.replace('.', '_') + '_' + identity, 'anchor': logical.lower(),
                'cfn-logicalId': stack + '-' + logical, 'resourceMode': 'CREATE'}
    comparison.resources.setdefault(service, {})[identity] = metadata
    if service not in comparison.models:
        authority = {f'desired.service.{service}.serviceId': service}
        comparison.models[service] = ModelSnapshot(Scope(ROOT, 'fixture', 'team', service), authority, {}, {}, {}, {}, {}, ())
    snapshot = comparison.models[service]
    counters = json.loads(snapshot.authoritative.get('desired.service.identity.lastAllocated', '{}'))
    counters[kind] = max(counters.get(kind, 0), int(identity))
    snapshot.authoritative['desired.service.identity.lastAllocated'] = json.dumps(counters)
    snapshot.authoritative.update({f'desired.resource.{identity}.{key}': value for key, value in metadata.items()})
    parsed = []
    for number, (prop, value, observed) in enumerate(rows, 1):
        rid = identity + '-' + f'{number:03}'
        row = {'property': kind + '.' + prop, 'value': '`' + value + '`'}
        parsed.append((rid, row))
        snapshot.authoritative.update({f'desired.row.{rid}.{key}': value for key, value in row.items()})
        if observed is not None:
            snapshot.authoritative[f'observed.row.{rid}.value'] = '`' + observed + '`'
    comparison.rows.setdefault(service, {})[identity] = parsed
    snapshot.values.update(snapshot.authoritative)
    comparison.stack_inputs[stack][0]['Resources'][logical] = {
        'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': properties or {}}
    comparison._index = None
    return parsed


def vpc(comparison, identity='001', logical='Vpc', observed=VPC):
    return resource(comparison, 'vpc', identity, 'EC2.VPC', logical, [('VpcId', 'PENDING_DEPLOY', observed)])


def exported(comparison, expression, name='shared', stack='producer'):
    comparison.stack_inputs[stack][0]['Outputs'][name] = {'Value': expression, 'Export': {'Name': name}}
    return comparison.evaluate('consumer', {'Fn::ImportValue': name})


def declaration(comparison, key, text, *, service='consumer', producer='vpc', logical='Vpc',
                kind='EC2.VPC', prop='EC2.VPC.VpcId', mode='identifier', pointer=None, occurrence='1', name='ref', target='team'):
    matches = [item['logicalId'] for item in comparison.resources.get(producer, {}).values()
               if item['cfn-logicalId'].endswith('-' + logical)]
    logical = matches[0] if len(matches) == 1 else logical
    spec = dict(consumerKey=key, text=text, occurrence=occurrence, producerKind='resource',
                producerScope='fixture/' + target + '/' + producer, producerLogicalId=logical,
                resourceType=kind, format=mode, property=prop, labelPolicy='none')
    if pointer is not None:
        spec['pointer'] = pointer
    comparison.models[service].authoritative.update({f'desired.reference.{name}.{field}': value for field, value in spec.items()})


def consumer(comparison, value=VPC):
    return resource(comparison, 'consumer', '010', 'EC2.Subnet', 'Consumer', [('VpcId', value, None)],
                    properties={'VpcId': {'Fn::ImportValue': 'shared'}}, stack='consumer')[0]


def policy_reference(comparison, left, right, path):
    return comparison.reference_decision(left, right, 'IAM.Role', path)


def prepared(comparison, row):
    rid, value = row
    return comparison.prepare_value('consumer', value, value['property'].rsplit('.', 1)[0], row_id=rid, stack='consumer')


@pytest.fixture(autouse=True)
def offline():
    with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
         patch('comparison.inputs.load_model', side_effect=AssertionError('synthetic snapshots must be reused')):
        yield


@pytest.mark.parametrize('kind,output,attribute,fixed,receiving,path,properties', [
    ('EC2.VPC', 'VpcId', 'VpcId', VPC, 'EC2.Subnet', 'VpcId', {}),
    ('EC2.Subnet', 'SubnetId', 'SubnetId', 'subnet-0123456789abcdef0', 'EC2.Instance', 'SubnetId', {}),
    ('EC2.SecurityGroup', 'Id', 'GroupId', 'sg-0123456789abcdef0', 'EC2.Instance', 'SecurityGroupIds[]', {'VpcId': VPC}),
])
def test_recorded_ref_export_import(kind, output, attribute, fixed, receiving, path, properties):
    comparison = fixture()
    resource(comparison, 'network', '001', kind, 'Network', [(output, 'PENDING_DEPLOY', fixed)], properties=properties)
    actual = exported(comparison, {'Ref': 'Network'})
    before = copy.deepcopy(comparison.models['network'].authoritative)
    decision = comparison.reference_decision(fixed, actual, receiving, path)
    assert actual['$attribute'] == attribute
    assert decision.equal is None and not decision.equivalent
    detail = decision.diagnostics[0]
    assert detail['evidence_type'] == 'recorded_observed' and detail['current_aws_verified'] is False
    assert detail['exports'] == [{'export_name': 'shared', 'export_stack': 'producer'}]
    assert detail['producers'] == [{'producer': 'network/001', 'attribute': attribute}]
    assert comparison.models['network'].authoritative == before


@pytest.mark.parametrize('attribute,fixed', [('BucketName', 'fixture-bucket'), ('Arn', 'arn:aws:s3:::fixture-bucket')])
def test_concrete_name_and_getatt_arn(attribute, fixed):
    comparison = fixture()
    resource(comparison, 's3', '001', 'S3.Bucket', 'Bucket', [('BucketName', 'fixture-bucket', None)],
             properties={'BucketName': 'fixture-bucket'})
    expression = {'Ref': 'Bucket'} if attribute == 'BucketName' else {'Fn::GetAtt': ['Bucket', attribute]}
    actual = exported(comparison, expression)
    decision = comparison.reference_decision(fixed, actual, 'IAM.Role', 'Policies[].PolicyDocument.Statement[].Resource')
    assert decision.equal is True and decision.diagnostics[0]['evidence_type'] == 'local_evaluation'
    assert comparison.reference_decision(fixed + '-different', actual, 'IAM.Role', '').equal is False


def test_declared_scalar_and_no_reparsing_or_snapshot_reload():
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    declaration(comparison, 'desired.row.010-001.value', VPC)
    with patch('comparison.model_reference.declarations', wraps=declarations) as parse:
        first = prepared(comparison, row).require_value()
        second = prepared(comparison, row).require_value()
        assert parse.call_count == 1
    assert isinstance(first, ResourceReference) and first == second
    actual = exported(comparison, {'Ref': 'Vpc'})
    assert comparison.reference_decision(first, actual, 'EC2.Subnet', 'VpcId').equal is True
    assert comparison.reference_decision(first, VPC, 'EC2.Subnet', 'VpcId').equal is None
    assert comparison.reference_decision(first, 'vpc-different', 'EC2.Subnet', 'VpcId').equal is None


def test_declared_name_checks_producer_model_and_return_attribute_mapping():
    comparison = fixture()
    resource(comparison, 'repository', '001', 'CodeCommit.Repository', 'Repository', [('RepositoryName', 'fixture-name', None)],
             properties={'RepositoryName': 'fixture-name'})
    row = consumer(comparison, 'fixture-name')
    declaration(comparison, 'desired.row.010-001.value', 'fixture-name', producer='repository', logical='Repository',
                kind='CodeCommit.Repository', prop='CodeCommit.Repository.RepositoryName', mode='name')
    desired = prepared(comparison, row).require_value()
    assert desired['$attribute'] == 'Name'
    actual = exported(comparison, {'Fn::GetAtt': ['Repository', 'Name']})
    assert comparison.reference_decision(desired, actual, 'IAM.Role', '').equal is True
    comparison.rows['repository']['001'][0][1]['value'] = '`different-model-name`'
    assert comparison.reference_decision(desired, actual, 'IAM.Role', '').equal is None
    assert comparison.reference_decision(desired, 'fixture-name', 'IAM.Role', '').equal is None


def test_json_pointer_multiple_references_preserves_siblings_and_order():
    comparison = fixture()
    vpc(comparison)
    other = 'vpc-0fedcba9876543210'
    vpc(comparison, '002', 'OtherVpc', other)
    row = resource(comparison, 'consumer', '010', 'IAM.Role', 'Consumer', [('AssumeRolePolicyDocument', 'unused', None)], stack='consumer')[0]
    body = {'a/b~c': [VPC, other], 'unrelated': VPC}
    row[1]['document'] = json.dumps(body)
    comparison.models['consumer'].authoritative['desired.row.010-001.document'] = row[1]['document']
    for index, text in enumerate((VPC, other)):
        declaration(comparison, 'desired.row.010-001.document', text, pointer='/a~1b~0c/' + str(index),
                    logical='Vpc' if index == 0 else 'OtherVpc', name='ref' + str(index))
    desired = prepared(comparison, row).require_value()
    assert desired['unrelated'] == VPC
    assert [item['$resource'][1] for item in desired['a/b~c']] == ['001', '002']
    actual = {'a/b~c': [exported(comparison, {'Ref': 'Vpc'}), comparison.evaluate('producer', {'Ref': 'OtherVpc'})], 'unrelated': VPC}
    callback = partial(policy_reference, comparison)
    assert compare_values(desired, actual, 'AssumeRolePolicyDocument', exact=True, reference=callback).equal is True
    actual['a/b~c'].reverse()
    assert compare_values(desired, actual, 'AssumeRolePolicyDocument', exact=True, reference=callback).equal is False


@pytest.mark.parametrize('expression', [
    {'Fn::Sub': 'arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:vpc/${Vpc}'},
    {'Fn::Join': ['', ['arn:aws:ec2:ap-northeast-1:123456789012:vpc/', {'Ref': 'Vpc'}]]},
])
def test_composite_arn_requires_all_literal_affixes(expression):
    comparison = fixture()
    vpc(comparison)
    actual = exported(comparison, expression)
    fixed = 'arn:aws:ec2:ap-northeast-1:123456789012:vpc/' + VPC
    assert comparison.reference_decision(fixed, actual, 'IAM.Role', '').equal is None
    assert comparison.reference_decision(fixed.replace('123456789012', '999999999999'), actual, 'IAM.Role', '').equal is None
    comparison.models['vpc'].authoritative['observed.row.001-001.value'] = '`PENDING_DEPLOY`'
    assert comparison.reference_decision(fixed, actual, 'IAM.Role', '').equal is None


@pytest.mark.parametrize('observed,reason', [(None, 'identifier_unobserved'), ('PENDING_DEPLOY', 'identifier_unobserved'),
                                           ('vpc-0fedcba9876543210', 'recorded_identifier_mismatch')])
def test_missing_pending_and_conflicting_observations(observed, reason):
    comparison = fixture()
    vpc(comparison, observed=observed)
    actual = exported(comparison, {'Ref': 'Vpc'})
    decision = comparison.reference_decision(VPC, actual, 'EC2.Subnet', 'VpcId')
    assert decision.equal is None and reason in decision.diagnostics[0]['reason']
    row = consumer(comparison)
    declaration(comparison, 'desired.row.010-001.value', VPC)
    desired = prepared(comparison, row).require_value()
    decision = comparison.reference_decision(desired, actual, 'EC2.Subnet', 'VpcId')
    assert decision.equal is None and reason in decision.diagnostics[0]['reason']


@pytest.mark.parametrize('change', ['resource', 'attribute', 'type', 'cross-target', 'logical-id', 'duplicate', 'partial', 'occurrence'])
def test_declared_reference_negative_cases(change):
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    kwargs = {}
    if change == 'type':
        kwargs['kind'] = 'EC2.Subnet'
    if change == 'cross-target':
        kwargs['target'] = 'other-team'
    if change == 'logical-id':
        kwargs['logical'] = 'OldVpc'
    if change == 'occurrence':
        kwargs['occurrence'] = '2'
    if change == 'partial':
        kwargs['text'] = 'vpc-'
    declaration(comparison, 'desired.row.010-001.value', **({'text': VPC} | kwargs))
    if change == 'duplicate':
        declaration(comparison, 'desired.row.010-001.value', VPC, name='duplicate')
    selected = prepared(comparison, row)
    if change not in {'resource', 'attribute'}:
        assert isinstance(selected.error, Blocked)
        return
    desired = selected.require_value()
    if change == 'resource':
        vpc(comparison, '002', 'OtherVpc')
        actual = exported(comparison, {'Ref': 'OtherVpc'})
        assert comparison.reference_decision(desired, actual, 'EC2.Subnet', 'VpcId').equal is False
    else:
        actual = ResourceReference({'$resource': ['vpc', '001'], '$attribute': 'Arn'})
        assert comparison.reference_decision(desired, actual, 'EC2.Subnet', 'VpcId').equal is False


def test_declared_security_group_uses_existing_ref_output_mapping():
    comparison = fixture()
    fixed = 'sg-0123456789abcdef0'
    resource(comparison, 'security-group', '001', 'EC2.SecurityGroup', 'Group', [('Id', 'PENDING_DEPLOY', fixed)], properties={'VpcId': VPC})
    row = consumer(comparison, fixed)
    declaration(comparison, 'desired.row.010-001.value', fixed, producer='security-group', logical='Group',
                kind='EC2.SecurityGroup', prop='EC2.SecurityGroup.Id')
    desired = prepared(comparison, row).require_value()
    actual = exported(comparison, {'Ref': 'Group'})
    assert desired['$attribute'] == 'Id' and actual['$attribute'] == 'GroupId'
    assert comparison.reference_decision(desired, actual, 'EC2.Instance', 'SecurityGroupIds[]').equal is True


def test_same_producer_different_identifier_form_is_not_equated():
    comparison = fixture()
    resource(comparison, 'repository', '001', 'CodeCommit.Repository', 'Repository', [('RepositoryName', 'fixture-name', None)],
             properties={'RepositoryName': 'fixture-name'})
    row = consumer(comparison, 'fixture-name')
    declaration(comparison, 'desired.row.010-001.value', 'fixture-name', producer='repository', logical='Repository',
                kind='CodeCommit.Repository', prop='CodeCommit.Repository.RepositoryName', mode='name')
    desired = prepared(comparison, row).require_value()
    actual = exported(comparison, {'Ref': 'Repository'})
    assert comparison.reference_decision(desired, actual, 'IAM.Role', '').equal is None


def test_pointer_mismatch_is_not_silently_applied():
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    row[1]['document'] = json.dumps({'ids': [VPC]})
    comparison.models['consumer'].authoritative['desired.row.010-001.document'] = row[1]['document']
    declaration(comparison, 'desired.row.010-001.document', VPC, pointer='/ids/1')
    assert isinstance(prepared(comparison, row).error, Blocked)


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'cycle'])
def test_export_resolution_failures_remain_blocked(fault):
    comparison = fixture()
    vpc(comparison)
    if fault == 'duplicate':
        comparison.stack_inputs['other'] = ({'Resources': {}, 'Outputs': {'Duplicate': {'Value': 'value', 'Export': {'Name': 'shared'}}}}, {}, {})
        comparison.stack_inputs['producer'][0]['Outputs']['Value'] = {'Value': {'Ref': 'Vpc'}, 'Export': {'Name': 'shared'}}
    elif fault == 'cycle':
        comparison.stack_inputs['other'] = ({'Resources': {}, 'Outputs': {'Other': {'Value': {'Fn::ImportValue': 'shared'}, 'Export': {'Name': 'other'}}}}, {}, {})
        comparison.stack_inputs['producer'][0]['Outputs']['Value'] = {'Value': {'Fn::ImportValue': 'other'}, 'Export': {'Name': 'shared'}}
    with pytest.raises(Blocked):
        comparison.evaluate('consumer', {'Fn::ImportValue': 'shared'})


@pytest.mark.parametrize('expression', [{'Fn::Sub': '${Missing}'}, {'Fn::Future': 'value'}])
def test_unresolved_intrinsics_never_match(expression):
    comparison = fixture()
    with pytest.raises(Blocked):
        comparison.evaluate('consumer', expression)
    assert comparison.reference_decision('value', Expression('Unverified', [expression]), 'IAM.Role', '').equal is None


@pytest.mark.parametrize('fault', ['condition', 'transform', 'duplicate-producer', 'type'])
def test_recorded_value_cannot_bypass_current_correspondence(fault):
    comparison = fixture()
    vpc(comparison)
    actual = exported(comparison, {'Ref': 'Vpc'})
    document = comparison.stack_inputs['producer'][0]
    if fault == 'condition':
        document['Conditions'] = {'No': {'Fn::Equals': ['yes', 'no']}}
        document['Resources']['Vpc']['Condition'] = 'No'
    elif fault == 'transform':
        document['Transform'] = 'Unresolved'
    elif fault == 'duplicate-producer':
        vpc(comparison, '002', 'OtherVpc')
        comparison.models['vpc'].values['desired.resource.002.cfn-logicalId'] = 'producer-Vpc'
        comparison._index = None
    else:
        document['Resources']['Vpc']['Type'] = 'AWS::EC2::Subnet'
    comparison.symbols.clear()
    assert comparison.reference_decision(VPC, actual, 'EC2.Subnet', 'VpcId').equal is None


def test_kms_link_contract_and_id_arn_separation():
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', '12345678-1234-1234-1234-123456789012')])
    key = comparison.evaluate('producer', {'Ref': 'Key'})
    arn = exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    desired = comparison.desired_reference('kms', '[key](kms.md#key)', 'Athena.WorkGroup',
        'WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey')
    field = 'WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey'
    assert comparison.reference_decision(desired, arn, 'Athena.WorkGroup', field).equal is True
    assert comparison.reference_decision(key, arn, 'Athena.WorkGroup', field).equal is False
    assert comparison.reference_decision('arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012',
                                         key, 'Athena.WorkGroup', field).equal is False


@pytest.mark.parametrize('kind,path', KMS_RECEIVERS)
@pytest.mark.parametrize('key_id', [KEY_ID, 'mrk-' + 'a' * 32])
@pytest.mark.parametrize('expression', [
    {'Fn::GetAtt': ['Key', 'Arn']},
    {'Fn::Sub': '${Key.Arn}'},
    {'Fn::Join': ['', [{'Fn::GetAtt': ['Key', 'Arn']}]]},
    {'Fn::Sub': 'arn:${AWS::Partition}:kms:${AWS::Region}:${AWS::AccountId}:key/${Key}'},
    {'Fn::Join': ['', ['arn:aws:kms:ap-northeast-1:123456789012:key/', {'Ref': 'Key'}]]},
])
def test_kms_recorded_arn_export_import(kind, path, key_id, expression):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', key_id)])
    before = copy.deepcopy(comparison.models['kms'].authoritative)
    actual = exported(comparison, expression)
    decision = comparison.reference_decision(KEY_ARN.replace(KEY_ID, key_id), actual, kind, path)
    assert decision.equal is None and not decision.equivalent, decision
    detail = decision.diagnostics[0]
    assert detail['evidence_type'] == 'recorded_observed' and detail['current_aws_verified'] is False
    assert detail['exports'] == [{'export_name': 'shared', 'export_stack': 'producer'}]
    if expression == {'Fn::GetAtt': ['Key', 'Arn']}:
        assert detail['producers'] == [dict(producer='kms/001', attribute='Arn',
            source_property='KMS.Key.KeyId', evidence_type='recorded_observed',
            derived_format='KeyArn', current_aws_verified=False)]
    assert comparison.models['kms'].authoritative == before


@pytest.mark.parametrize('observed', [None, '', 'PENDING_DEPLOY', 'UNSET', 'TODO', 'TBD', '未確定',
                                     'invalid', KEY_ID + '-extra', KEY_ARN, '${KeyId}'])
def test_kms_arn_requires_recorded_key_id(observed):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', KEY_ARN, observed)])
    actual = exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    decision = comparison.reference_decision(KEY_ARN, actual, 'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is None, decision
    assert any(word in decision.diagnostics[0]['reason'] for word in ('unobserved', 'format_unproven'))


def test_kms_arn_identifier_evidence_comes_from_observation_only():
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', KEY_ID, None)],
             properties={'KeyId': KEY_ID})
    actual = exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    decision = comparison.reference_decision(KEY_ARN, actual, 'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is None and 'identifier_unobserved' in decision.diagnostics[0]['reason']


@pytest.mark.parametrize('field,value', [
    ('AWS::Partition', None), ('AWS::Region', None), ('AWS::AccountId', None),
    ('AWS::Partition', 'UNSET'), ('AWS::Region', '${Region}'), ('AWS::AccountId', '123'),
    ('AWS::Partition', 'aws-cn'), ('AWS::Region', 'us-east-1'), ('AWS::AccountId', '999999999999'),
])
def test_kms_arn_uses_only_producer_context(field, value):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    pseudo = dict(comparison.stack_inputs['producer'][2])
    pseudo[field] = value
    document, parameters, _ = comparison.stack_inputs['producer']
    comparison.stack_inputs['producer'] = document, parameters, pseudo
    with pytest.raises(Blocked, match='confirmed|handoff matches=0'):
        exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    actual = comparison.evaluate('producer', {'Fn::GetAtt': ['Key', 'Arn']})
    decision = comparison.reference_decision(KEY_ARN, actual, 'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is None, decision
    assert decision.diagnostics[0]['current_aws_verified'] is False
    if value in {'aws-cn', 'us-east-1', '999999999999'}:
        assert decision.diagnostics[0]['reason'].startswith('recorded_identifier_mismatch')
        assert comparison.reference_decision(KEY_ARN.replace(
            {'AWS::Partition': 'aws', 'AWS::Region': 'ap-northeast-1', 'AWS::AccountId': '123456789012'}[field],
            value, 1), actual, 'Athena.WorkGroup', ATHENA_KMS).equal is None


def test_kms_conflicting_recorded_identifier_is_uncompared():
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    actual = exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    decision = comparison.reference_decision(KEY_ARN.replace(KEY_ID, 'mrk-' + 'b' * 32), actual,
                                             'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is None and decision.diagnostics[0]['reason'].startswith('recorded_identifier_mismatch')


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'type', 'condition', 'transform', 'import',
                                  'duplicate-row', 'missing-stack', 'replacement'])
def test_kms_recorded_arn_preserves_correspondence_and_handoff(fault):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    actual = exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    document = comparison.stack_inputs['producer'][0]
    if fault == 'missing':
        del document['Resources']['Key']
    elif fault == 'duplicate':
        resource(comparison, 'kms', '002', 'KMS.Key', 'Other', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
        comparison.models['kms'].values['desired.resource.002.cfn-logicalId'] = 'producer-Key'
    elif fault == 'type':
        document['Resources']['Key']['Type'] = 'AWS::KMS::Alias'
    elif fault == 'condition':
        document['Conditions'] = {'No': {'Fn::Equals': ['yes', 'no']}}
        document['Resources']['Key']['Condition'] = 'No'
    elif fault == 'transform':
        document['Transform'] = 'Unresolved'
    elif fault == 'import':
        comparison.resources['kms']['001']['resourceMode'] = 'IMPORT'
    elif fault == 'duplicate-row':
        comparison.rows['kms']['001'].append(('001-002', dict(comparison.rows['kms']['001'][0][1])))
    elif fault == 'missing-stack':
        comparison.templates = lambda: []
    else:
        comparison.resources['kms']['001']['cfn-logicalId'] = 'producer-Replacement'
    comparison.symbols.clear()
    comparison._index = None
    decision = comparison.reference_decision(KEY_ARN, actual, 'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is None, decision


@pytest.mark.parametrize('actual', [
    {'Ref': 'Key'},
    {'Fn::Sub': '${Key}'},
    {'Fn::Sub': 'arn:${AWS::Partition}:kms:${AWS::Region}:${AWS::AccountId}:alias/fixture'},
    {'Fn::Join': ['', ['arn:aws:kms:ap-northeast-1:123456789012:alias/fixture']]},
])
def test_kms_expression_cannot_bypass_allowed_forms(actual):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    decision = comparison.reference_decision(KEY_ARN, exported(comparison, actual), 'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is False, decision
    assert 'KMS format' in decision.diagnostics[0]['reason']


@pytest.mark.parametrize('actual', ['literal', 'ref', 'expression'])
def test_kms_declared_literal_cannot_bypass_allowed_forms(actual):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    row = consumer(comparison, KEY_ID)
    declaration(comparison, 'desired.row.010-001.value', KEY_ID, producer='kms', logical='Key',
                kind='KMS.Key', prop='KMS.Key.KeyId')
    desired = prepared(comparison, row).require_value()
    value = KEY_ID if actual == 'literal' else exported(comparison,
        {'Ref': 'Key'} if actual == 'ref' else {'Fn::Sub': '${Key}'})
    decision = comparison.reference_decision(desired, value, 'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is False, decision


@pytest.mark.parametrize('kind,path', [('Glue.SecurityConfiguration', 'EncryptionConfiguration.S3Encryptions[].KmsKeyArn'),
                                       ('CodePipeline.Pipeline', 'ArtifactStore.EncryptionKey.Id')])
def test_key_arn_does_not_override_alias_only_service_contract(kind, path):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    decision = comparison.reference_decision(KEY_ARN, exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']}), kind, path)
    assert decision.equal is False and decision.diagnostics[0]['allowed_forms'] == ['AliasArn']


@pytest.mark.parametrize('kind,path,allowed', [
    ('Athena.WorkGroup', ATHENA_KMS, {'KeyArn'}),
    ('Logs.LogGroup', 'KmsKeyId', {'KeyArn', 'AliasArn'}),
    ('Glue.SecurityConfiguration', 'EncryptionConfiguration.S3Encryptions[].KmsKeyArn', {'AliasArn'}),
    ('CodePipeline.Pipeline', 'ArtifactStore.EncryptionKey.Id', {'AliasArn'}),
])
@pytest.mark.parametrize('model_form', ['KeyId', 'KeyArn', 'AliasName', 'AliasArn'])
@pytest.mark.parametrize('iac_form', ['KeyId', 'KeyArn', 'AliasName', 'AliasArn'])
def test_kms_existing_service_form_matrix(kind, path, allowed, model_form, iac_form):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    resource(comparison, 'kms', '002', 'KMS.Alias', 'Alias', [('AliasName', 'alias/fixture', None)],
             properties={'AliasName': 'alias/fixture', 'TargetKeyId': {'Ref': 'Key'}})
    forms = {form: ResourceReference({'$resource': ['kms', identity], '$attribute': attribute})
             for form, identity, attribute in [('KeyId', '001', 'KeyId'), ('KeyArn', '001', 'Arn'),
                 ('AliasName', '002', 'AliasName'), ('AliasArn', '002', 'AliasArn')]}
    decision = comparison.reference_decision(forms[model_form], forms[iac_form], kind, path)
    assert decision.equal is (model_form == iac_form and model_form in allowed), decision


def test_kms_unresolved_expressions_do_not_gain_symbolic_equality():
    comparison = fixture()
    expression = Expression('Sub', ['${Unknown}', {}])
    assert comparison.reference_decision(expression, expression, 'Athena.WorkGroup', ATHENA_KMS).equal is None
    assert comparison.reference_decision(KEY_ARN, Expression('Future', []), 'Athena.WorkGroup', ATHENA_KMS).equal is None


def test_kms_derived_producer_diagnostics_are_unique():
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    actual = exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    proof = Evidence(comparison)
    assert proof.resolve(actual) == proof.resolve(actual) == KEY_ARN
    assert len(proof.producers) == 1


@pytest.mark.parametrize('kind,path', KMS_RECEIVERS)
def test_kms_runner_reports_uncompared_with_recorded_proof(kind, path):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    properties = {}
    put_row(properties, path, {'Fn::ImportValue': 'shared'})
    resource(comparison, 'consumer', '010', kind, 'Consumer', [(path, KEY_ARN, None)],
             properties=properties, stack='consumer')
    exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    comparison.services = ['consumer']
    document = comparison.stack_inputs['consumer'][0]
    results = comparison.compare_rows('consumer', '010', comparison.resources['consumer']['010'],
        'consumer', 'Consumer', ROOT / 'synthetic.yaml', document['Resources']['Consumer'], document).records
    assert [item['category'] for item in results] == ['uncompared'], results
    assert results[0]['reference_diagnostics'][0]['evidence_type'] == 'recorded_observed'


def test_alias_arn_sub_import_ref_pipeline_preserves_export_evidence():
    comparison = fixture()
    resource(comparison, 'kms', '002', 'KMS.Alias', 'Alias', [('AliasName', 'alias/fixture', None)],
             properties={'AliasName': 'alias/fixture'})
    comparison.stack_inputs['producer'][0]['Outputs']['AliasName'] = {
        'Value': {'Ref': 'Alias'}, 'Export': {'Name': {'Fn::Sub': 'KmsLogKeyAliasName${Suffix}'}}}
    comparison.stack_inputs['producer'][1]['Suffix'] = 'Fixture'
    comparison.stack_inputs['consumer'][1]['Suffix'] = 'Fixture'
    expression = {'Fn::Sub': [
        'arn:${AWS::Partition}:kms:${AWS::Region}:${AWS::AccountId}:${KmsAliasName}',
        {'KmsAliasName': {'Fn::ImportValue': {'Fn::Sub': 'KmsLogKeyAliasName${Suffix}'}}}]}
    resource(comparison, 'logs', '010', 'Logs.LogGroup', 'Log',
             [('KmsKeyId', '[Alias](kms.md#alias)', None)],
             properties={'KmsKeyId': expression}, stack='consumer')
    before = copy.deepcopy(comparison.models['kms'].authoritative)
    document = comparison.stack_inputs['consumer'][0]
    batch = comparison.compare_rows('logs', '010', comparison.resources['logs']['010'],
        'consumer', 'Log', ROOT / 'synthetic.yaml', document['Resources']['Log'], document)
    assert batch.failure is None
    assert [item['category'] for item in batch.records] == ['matched'], batch.records
    detail = batch.records[0]['reference_diagnostics'][0]
    assert detail['exports'] == [{'export_name': 'KmsLogKeyAliasNameFixture', 'export_stack': 'producer'}]
    assert detail['evidence_type'] == 'logical_reference' and detail['current_aws_verified'] is False
    assert comparison.models['kms'].authoritative == before


def test_export_chain_retains_each_handoff():
    comparison = fixture()
    vpc(comparison)
    exported(comparison, {'Ref': 'Vpc'}, name='base')
    comparison.stack_inputs['relay'] = ({'Resources': {}, 'Outputs': {
        'Relay': {'Value': {'Fn::ImportValue': 'base'}, 'Export': {'Name': 'shared'}}}}, {}, dict(comparison.stack_inputs['producer'][2]))
    comparison.exports = None
    actual = comparison.evaluate('consumer', {'Fn::ImportValue': 'shared'})
    decision = comparison.reference_decision(VPC, actual, 'EC2.Subnet', 'VpcId')
    assert decision.equal is None and not decision.equivalent
    assert decision.diagnostics[0]['exports'] == [
        {'export_name': 'shared', 'export_stack': 'relay'}, {'export_name': 'base', 'export_stack': 'producer'}]


def test_runner_keeps_recorded_evidence_and_does_not_write_authority():
    comparison = fixture()
    vpc(comparison)
    consumer(comparison)
    declaration(comparison, 'desired.row.010-001.value', VPC)
    exported(comparison, {'Ref': 'Vpc'})
    comparison.services = ['consumer']
    before = {service: copy.deepcopy(model.authoritative) for service, model in comparison.models.items()}
    document = comparison.stack_inputs['consumer'][0]
    results = comparison.compare_rows('consumer', '010', comparison.resources['consumer']['010'],
        'consumer', 'Consumer', ROOT / 'synthetic.yaml', document['Resources']['Consumer'], document).records
    assert [item['category'] for item in results] == ['matched'], results
    assert results[0]['reference_diagnostics'][0]['evidence_type'] == 'logical_reference'
    assert {service: model.authoritative for service, model in comparison.models.items()} == before


RECEIVERS = [('s3', 'S3.Bucket', 'BucketName', 'CloudTrail.Trail', 'S3BucketName'),
 ('s3', 'S3.Bucket', 'BucketName', 'CodePipeline.Pipeline', 'ArtifactStore.Location'),
 ('s3', 'S3.Bucket', 'BucketName', 'Lambda.Function', 'Code.S3Bucket'),
 ('cloudwatch-logs',
  'Logs.LogGroup',
  'LogGroupName',
  'CodeBuild.Project',
  'LogsConfig.CloudWatchLogs.GroupName'),
 ('cloudwatch-logs', 'Logs.LogGroup', 'LogGroupName', 'Lambda.Function', 'LoggingConfig.LogGroup'),
 ('cloudwatch-logs', 'Logs.LogGroup', 'LogGroupName', 'EC2.FlowLog', 'LogGroupName'),
 ('vpc', 'EC2.VPC', 'VpcId', 'CodeBuild.Project', 'VpcConfig.VpcId'),
 ('vpc', 'EC2.VPC', 'VpcId', 'EC2.Subnet', 'VpcId'),
 ('vpc', 'EC2.VPC', 'VpcId', 'EC2.SecurityGroup', 'VpcId'),
 ('vpc', 'EC2.VPC', 'VpcId', 'EC2.RouteTable', 'VpcId'),
 ('vpc', 'EC2.VPC', 'VpcId', 'EC2.VPCEndpoint', 'VpcId'),
 ('vpc', 'EC2.VPC', 'VpcId', 'Route53.HostedZone', 'VPCs[].VPCId'),
 ('vpc', 'EC2.Subnet', 'SubnetId', 'EC2.Instance', 'SubnetId'),
 ('vpc', 'EC2.Subnet', 'SubnetId', 'CodeBuild.Project', 'VpcConfig.Subnets[]'),
 ('vpc', 'EC2.Subnet', 'SubnetId', 'Lambda.Function', 'VpcConfig.SubnetIds[]'),
 ('vpc', 'EC2.Subnet', 'SubnetId', 'EC2.VPCEndpoint', 'SubnetIds[]'),
 ('vpc',
  'EC2.Subnet',
  'SubnetId',
  'Glue.Connection',
  'ConnectionInput.PhysicalConnectionRequirements.SubnetId'),
 ('vpc', 'EC2.Subnet', 'SubnetId', 'MWAA.Environment', 'NetworkConfiguration.SubnetIds[]'),
 ('vpc', 'EC2.Subnet', 'SubnetId', 'QuickSight.VPCConnection', 'SubnetIds[]'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'CodeBuild.Project', 'VpcConfig.SecurityGroupIds[]'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'EC2.Instance', 'SecurityGroupIds[]'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'EC2.SecurityGroupIngress', 'GroupId'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'EC2.SecurityGroupIngress', 'SourceSecurityGroupId'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'EC2.SecurityGroupEgress', 'GroupId'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'EC2.SecurityGroupEgress', 'DestinationSecurityGroupId'),
 ('security-group',
  'EC2.SecurityGroup',
  'GroupId',
  'EC2.SecurityGroup',
  'SecurityGroupEgress[].DestinationSecurityGroupId'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'EC2.VPCEndpoint', 'SecurityGroupIds[]'),
 ('security-group',
  'EC2.SecurityGroup',
  'GroupId',
  'Glue.Connection',
  'ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList[]'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'Lambda.Function', 'VpcConfig.SecurityGroupIds[]'),
 ('security-group',
  'EC2.SecurityGroup',
  'GroupId',
  'MWAA.Environment',
  'NetworkConfiguration.SecurityGroupIds[]'),
 ('security-group', 'EC2.SecurityGroup', 'GroupId', 'QuickSight.VPCConnection', 'SecurityGroupIds[]'),
 ('vpc', 'EC2.RouteTable', 'RouteTableId', 'EC2.SubnetRouteTableAssociation', 'RouteTableId'),
 ('vpc', 'EC2.RouteTable', 'RouteTableId', 'EC2.VPCEndpoint', 'RouteTableIds[]'),
 ('iam', 'IAM.Role', 'RoleName', 'Glue.Job', 'Role'),
 ('iam', 'IAM.Role', 'RoleName', 'IAM.InstanceProfile', 'Roles[]'),
 ('iam', 'IAM.InstanceProfile', 'InstanceProfileName', 'EC2.Instance', 'IamInstanceProfile'),
 ('glue', 'Glue.SecurityConfiguration', 'Name', 'Glue.Job', 'SecurityConfiguration'),
 ('lambda', 'Lambda.Function', 'FunctionName', 'Lambda.Permission', 'FunctionName'),
 ('route53', 'Route53.HostedZone', 'Id', 'Route53.RecordSet', 'HostedZoneId'),
 ('secrets-manager', 'SecretsManager.Secret', 'Id', 'SecretsManager.RotationSchedule', 'SecretId'),
 ('sqs', 'SQS.Queue', 'QueueUrl', 'SQS.QueuePolicy', 'Queues[]'),
 ('kms', 'KMS.Alias', 'AliasName', 'CodeCommit.Repository', 'KmsKeyId'),
 ('kms', 'KMS.Alias', 'AliasName', 'EC2.Instance', 'BlockDeviceMappings[].Ebs.KmsKeyId'),
 ('kms', 'KMS.Alias', 'AliasName', 'MWAA.Environment', 'KmsKey'),
 ('kms', 'KMS.Alias', 'AliasName', 'SecretsManager.Secret', 'KmsKeyId'),
 ('kms', 'KMS.Key', 'KeyId', 'KMS.Alias', 'TargetKeyId')]


def setting(comparison, kind, prop, desired, actual, *, service='consumer'):
    """One setting, in-memory snapshots; never scan, lint or generate project files."""
    resource(comparison, service, '090', kind, 'Receiver',
                   [(prop, desired if isinstance(desired, str) else json.dumps(desired), None)], stack='producer')
    document = comparison.stack_inputs['producer'][0]
    properties = {}
    put_row(properties, prop, actual)
    definition = document['Resources']['Receiver']
    definition['Properties'] = properties
    result = comparison.compare_rows(service, '090', comparison.resources[service]['090'],
        'producer', 'Receiver', ROOT / 'synthetic.yaml', definition, document)
    assert result.failure is None, result.failure
    return result.records


@pytest.mark.parametrize('service,producer,attribute,kind,path', RECEIVERS)
def test_receiver_contracts(service, producer, attribute, kind, path):
    comparison = fixture()
    resource(comparison, service, '001', producer, 'Producer', [],
             properties={'VpcId': VPC} if producer == 'EC2.SecurityGroup' else {})
    resource(comparison, service, '002', producer, 'OtherProducer', [],
             properties={'VpcId': VPC} if producer == 'EC2.SecurityGroup' else {})
    link = '[label](' + service + '.md#producer)'
    desired = comparison.desired_reference(service, link, kind, path)
    assert desired == ResourceReference({'$resource': [service, '001'], '$attribute': attribute})
    assert comparison.reference_same(desired, comparison.evaluate('producer', {'Ref': 'Producer'}), kind, path) is True
    assert comparison.reference_same(desired, ResourceReference(dict(desired, **{'$resource': [service, '002']})), kind, path) is False
    for bad_link, requested in ((link, 'Unknown'), (link.replace('#producer', '#missing'), None)):
        with pytest.raises(Blocked):
            comparison.desired_reference(service, bad_link, kind, path, requested)
    resource(comparison, 'wrong', '001', 'IAM.Role' if producer != 'IAM.Role' else 'SecretsManager.Secret', 'Wrong', [])
    with pytest.raises(Blocked):
        comparison.desired_reference(service, '[wrong](wrong.md#wrong)', kind, path)
    comparison.reference_anchor_indexes[service] = {'producer': [('001', dict(comparison.resources[service]['001'], resourceMode='IMPORT'))]}
    with pytest.raises(Blocked, match='IMPORT'):
        comparison.desired_reference(service, link, kind, path)


@pytest.mark.parametrize('expression,expected', [
    ('fixture', 'matched'), ({'Ref': 'Name'}, 'matched'), ({'Fn::Sub': '${Name}'}, 'matched'),
    ({'Fn::Join': ['-', ['fix', 'ture']]}, 'difference'),
    ({'Fn::If': ['Active', {'Ref': 'Name'}, 'inactive']}, 'matched'),
    ({'Fn::FindInMap': ['Names', 'dev', 'Connection']}, 'matched'),
    ({'Fn::Select': [0, {'Fn::Split': [',', 'fixture,other']}]}, 'matched'),
    ('different', 'difference'), ({'Ref': 'Missing'}, 'uncompared'),
    ({'Ref': 'Connection'}, 'uncompared'), ({'Fn::Sub': '${Connection}'}, 'uncompared'),
    ({'Ref': 'OtherConnection'}, 'uncompared'), ('UNSET', 'uncompared'), (None, 'uncompared'),
])
def test_glue_connection_name(expression, expected):
    comparison = fixture()
    resource(comparison, 'glue', '001', 'Glue.Connection', 'Connection', [],
             properties={'ConnectionInput': {'Name': expression}} if expression is not None else {'Name': 'fixture'})
    resource(comparison, 'glue', '002', 'Glue.Connection', 'OtherConnection', [],
             properties={'ConnectionInput': {'Name': {'Ref': 'Connection'}}})
    document, parameters, _ = comparison.stack_inputs['producer']
    parameters['Name'] = 'fixture'
    document['Conditions'] = {'Active': {'Fn::Equals': [1, 1]}}
    document['Mappings'] = {'Names': {'dev': {'Connection': 'fixture'}}}
    records = setting(comparison, 'Glue.Job', 'Connections',
        {'Connections': ['[connection](glue.md#connection)']}, {'Connections': ['fixture']})
    record = records[0]
    assert record['category'] == expected, record
    if expected == 'matched':
        assert comparison.reference_literal(comparison.evaluate('producer', {'Fn::Sub': 'prefix-${Connection}'})) == 'prefix-fixture'
        assert comparison.reference_literal(comparison.evaluate('producer', {'Fn::Sub': '${Connection.Name}'})) == 'fixture'
    if expression is None:
        assert record['reference_diagnostics'][0]['reason'] == 'identifier_unobserved: missing or ambiguous identifier Property'
    if expression == {'Ref': 'Connection'}:
        with pytest.raises(Blocked, match='cyclic resource substitution'):
            comparison.evaluate('producer', {'Fn::Sub': '${Connection}'})


@pytest.mark.parametrize('kind,ref_attribute,attribute,invalid', [
    ('Glue.Connection', 'Name', 'Name', 'Arn'),
    ('SecretsManager.Secret', 'Id', 'Id', 'Arn'),
    ('IAM.ManagedPolicy', 'PolicyArn', 'PolicyArn', 'Arn'),
    ('CodeCommit.Repository', 'RepositoryId', 'Name', 'Unknown'),
    ('QuickSight.VPCConnection', None, 'Arn', 'VPCConnectionId'),
])
def test_formal_return_attributes(kind, ref_attribute, attribute, invalid):
    comparison = fixture()
    resource(comparison, 'producer', '001', kind, 'Producer', [])
    symbol = comparison.evaluate('producer', {'Fn::GetAtt': ['Producer', attribute]})
    assert symbol['$attribute'] == attribute
    if ref_attribute:
        assert comparison.evaluate('producer', {'Ref': 'Producer'})['$attribute'] == ref_attribute
    else:
        with pytest.raises(Blocked):
            comparison.evaluate('producer', {'Ref': 'Producer'})
    with pytest.raises((Blocked, KeyError)):
        comparison.evaluate('producer', {'Fn::GetAtt': ['Producer', invalid]})


@pytest.mark.parametrize('actual,expected', [('same', 'matched'), ('other', 'difference'), ('wrong-attribute', 'uncompared')])
def test_glue_secret_identity(actual, expected):
    comparison = fixture()
    for identity, logical in [('001', 'Secret'), ('002', 'OtherSecret')]:
        resource(comparison, 'secrets-manager', identity, 'SecretsManager.Secret', logical, [], properties={'Name': 'same-name'})
    value = {'Fn::GetAtt': ['Secret', 'Arn']} if actual == 'wrong-attribute' else {'Ref': 'OtherSecret' if actual == 'other' else 'Secret'}
    records = setting(comparison, 'Glue.Connection', 'ConnectionInput.AuthenticationConfiguration.SecretArn',
        '[secret](secrets-manager.md#secret)', value)
    assert records[0]['category'] == expected, records


@pytest.mark.parametrize('bad', [None, 'Category', 'Owner', 'Provider', 'Version', 'target'])
def test_action_context_requires_own_codecommit_contract(bad):
    comparison = fixture()
    resource(comparison, 'codecommit', '001', 'CodeCommit.Repository', 'Repository', [])
    resource(comparison, 'lambda', '001', 'Lambda.Function', 'Function', [])
    action = dict(Category='Source', Owner='AWS', Provider='CodeCommit', Version='1')
    link = '[repo](codecommit.md#repository)'
    path = 'Stages[].Actions[].Configuration.RepositoryName'
    if bad == 'target':
        link = '[function](lambda.md#function)'
    elif bad:
        action[bad] = 'wrong'
    if bad is None:
        assert comparison.desired_reference('codecommit', link, 'CodePipeline.Pipeline', path,
            context={'ActionTypeId': action})['$attribute'] == 'Name'
    else:
        with pytest.raises(Blocked):
            comparison.desired_reference('codecommit', link, 'CodePipeline.Pipeline', path, context={'ActionTypeId': action})
        if bad != 'target':
            action.pop(bad)
            with pytest.raises(Blocked):
                comparison.desired_reference('codecommit', link, 'CodePipeline.Pipeline', path, context={'ActionTypeId': action})


@pytest.mark.parametrize('fault', ['partition', 'region', 'account', 'version', 'alias', 'type', 'name',
                                  'other-resource', 'attribute', 'missing-name', 'invalid-name', 'mapping', 'condition'])
def test_eventbridge_literal_requires_exact_lambda_identity(fault):
    comparison = fixture()
    resource(comparison, 'lambda', '001', 'Lambda.Function', 'Function', [], properties={'FunctionName': 'fixture'})
    resource(comparison, 'lambda', '002', 'Lambda.Function', 'Other', [], properties={'FunctionName': 'fixture'})
    function = comparison.evaluate('producer', {'Fn::GetAtt': ['Function', 'Arn']})
    arn = 'arn:aws:lambda:ap-northeast-1:123456789012:function:fixture'
    assert comparison.reference_same(function, arn, 'Events.Rule', '') is True
    replacements = {'partition': ('arn:aws:', 'arn:aws-cn:'), 'region': ('ap-northeast-1', 'us-east-1'),
        'account': ('123456789012', '999999999999'), 'type': (':function:', ':layer:'), 'name': ('fixture', 'other')}
    expected = False
    actual = arn
    definition = comparison.stack_inputs['producer'][0]['Resources']['Function']
    if fault in replacements:
        actual = arn.replace(*replacements[fault])
    elif fault in {'version', 'alias'}:
        actual += ':1' if fault == 'version' else ':alias'
    elif fault == 'other-resource':
        actual = ResourceReference(dict(function, **{'$resource': ['lambda', '002']}))
    elif fault == 'attribute':
        actual = ResourceReference(dict(function, **{'$attribute': 'FunctionName'}))
    else:
        expected = None
        if fault == 'mapping':
            comparison.resources['lambda']['001']['cfn-logicalId'] = 'producer-Missing'
        elif fault == 'condition':
            definition['Condition'] = 'Off'
            comparison.stack_inputs['producer'][0]['Conditions'] = {'Off': {'Fn::Equals': [1, 2]}}
        else:
            definition['Properties'] = {} if fault == 'missing-name' else {'FunctionName': 'function:alias'}
        comparison.symbols.clear()
    assert comparison.reference_same(function, actual, 'Events.Rule', '') is expected
    assert comparison.redacted(arn) == '<masked ARN/secret>'


@pytest.mark.parametrize('fault', [None, 'other-stack', 'attribute', 'delimiter', 'invalid', 'missing', 'index', 'literal', 'sub'])
def test_symbolic_setting_classification(fault):
    comparison = fixture()
    resource(comparison, 'cloudwatch-logs', '001', 'Logs.LogGroup', 'Log', [])
    expression = {'Fn::Select': [0, {'Fn::Split': [':*', {'Fn::GetAtt': ['Log', 'Arn'] }]}]}
    desired = comparison.evaluate('producer', expression)
    actual = expression
    expected = 'matched'
    if fault == 'other-stack':
        resource(comparison, 'cloudwatch-logs', '002', 'Logs.LogGroup', 'OtherLog', [], stack='consumer')
        actual = {'Fn::Select': [0, {'Fn::Split': [':*', {'Fn::GetAtt': ['OtherLog', 'Arn']}]}]}
        expected = 'uncompared'
    elif fault == 'attribute':
        desired = comparison.evaluate('producer', {'Fn::GetAtt': ['Log', 'Arn']})
        expected = 'uncompared'
    elif fault == 'delimiter':
        actual = {'Fn::Select': [0, {'Fn::Split': [',', {'Fn::GetAtt': ['Log', 'Arn']}]}]}
        expected = 'uncompared'
    elif fault == 'invalid':
        actual, expected = {'Fn::Split': [',', 42]}, 'error'
    elif fault == 'missing':
        actual, expected = {'Fn::GetAtt': ['Missing', 'Arn']}, 'uncompared'
    elif fault == 'index':
        actual, expected = {'Fn::Select': [1, expression['Fn::Select'][1]]}, 'uncompared'
    elif fault == 'literal':
        desired, actual = 'a:b', {'Fn::Join': ['-', ['a', 'b']]}
        expected = 'difference'
    elif fault == 'sub':
        actual = {'Fn::Sub': ['${Arn}-${!literal}', {'Arn': expression}]}
        desired = comparison.evaluate('producer', actual)
    # Receiver and Log share a stack; only the desired value is pre-bound for this boundary test.
    with patch.object(comparison, 'prepare_value', return_value=PreparedValue(desired, [])):
        records = setting(comparison, 'Logs.LogGroup', 'LogGroupName', 'unused', actual)
    assert records[0]['category'] == expected, records


@pytest.mark.parametrize('fault', [None, 'id', 'unknown', 'intrinsic', 'nested-sub'])
def test_model_policy_links_bind_but_raw_intrinsics_do_not(fault):
    comparison = fixture()
    resource(comparison, 'cloudwatch-logs', '001', 'Logs.LogGroup', 'Log', [])
    link = '[log](cloudwatch-logs.md#log)'
    model = {'Fn::Join': ['', [{'Fn::Select': [0, {'Fn::Split': [':*', link]}]}, ':stream']]}
    actual = {'Fn::Join': ['', [{'Fn::Select': [0, {'Fn::Split': [':*', {'Fn::GetAtt': ['Log', 'Arn']}]}]}, ':stream']]}
    if fault == 'id':
        model = {'Fn::Sub': '${Log.Arn}'}
    elif fault == 'intrinsic':
        model = actual
    elif fault == 'unknown':
        model = {'Fn::Join': ['', [link.replace('#log', '#missing'), ':stream']]}
    elif fault == 'nested-sub':
        model = {'Fn::Sub': ['${Arn}:stream', {'Arn': {'Fn::Select': [0, {'Fn::Split': [':*', link]}]}}]}
    if fault == 'intrinsic':
        pending = comparison.prepare_value('consumer', {'property': 'IAM.ManagedPolicy.PolicyDocument',
            'value': '', 'document': json.dumps({'Statement': [{'Resource': model}]})}, 'IAM.ManagedPolicy')
        assert pending.warnings and pending.require_value()['Statement'][0]['Resource'].operation == 'Unverified'
        return
    records = setting(comparison, 'IAM.ManagedPolicy', 'PolicyDocument', {'Statement': [{'Resource': model}]},
                      {'Statement': [{'Resource': actual}]})
    assert records[0]['category'] == ('matched' if fault in {None, 'nested-sub'} else 'uncompared'), records


@pytest.mark.parametrize('fault', [None, 'off', 'missing', 'unknown'])
def test_managed_policy_attachment_edges(fault):
    comparison = fixture()
    resource(comparison, 'iam', '001', 'IAM.ManagedPolicy', 'Policy', [])
    resource(comparison, 'iam', '002', 'IAM.Role', 'Role', [], properties={'ManagedPolicyArns': [{'Ref': 'Policy'}]})
    document = comparison.stack_inputs['producer'][0]
    role = document['Resources']['Role']
    if fault == 'off':
        role['Condition'] = 'Off'
        document['Conditions'] = {'Off': {'Fn::Equals': [1, 2]}}
    elif fault == 'missing':
        role['Properties']['ManagedPolicyArns'] = []
    elif fault == 'unknown':
        role['Properties']['ManagedPolicyArns'] = [{'Ref': 'Missing'}]
    callback = partial(managed_policy_roles, stack_inputs=comparison.stack_inputs, evaluate=comparison.evaluate,
                       reference_same=comparison.reference_same, symbol=comparison.symbol)
    if fault == 'unknown':
        with pytest.raises(Blocked):
            callback('iam', '001', 'producer', [])
    else:
        result = callback('iam', '001', 'producer', [{'Ref': 'Role'}] if fault is None else [])
        assert len(result) == int(fault is None)


@pytest.mark.parametrize('fault', [None, 'missing', 'ambiguous', 'other-parent', 'unresolved'])
def test_inline_policy_ownership(fault):
    child = {'Type': 'AWS::S3::BucketPolicy', 'Properties': {'Bucket': {'Ref': 'Bucket'}, 'PolicyDocument': {}}}
    document = {'Resources': {'Policy': child}}
    if fault == 'missing':
        document['Resources'].clear()
    elif fault == 'ambiguous':
        document['Resources']['Other'] = copy.deepcopy(child)
    elif fault == 'other-parent':
        child['Properties']['Bucket'] = {'Ref': 'Other'}
    elif fault == 'unresolved':
        child['Properties']['Bucket'] = 'literal'
    selected, failure = inline_owner('S3.Bucket', 'S3.BucketPolicy', 'Bucket', {}, document, {}, {}, 'AWS::S3::BucketPolicy')
    assert selected is child if fault is None else selected is None
    if fault:
        assert failure[0] == ('difference' if fault in {'missing', 'other-parent'} else 'uncompared')


@pytest.mark.parametrize('fault', [None, 'account', 'namespace', 'group', 'region', 'partition', 'sub', 'join', 'unresolved',
    'unset', 'invalid-account', 'link-name', 'missing-account', 'missing-namespace', 'missing-group', 'duplicate',
    'missing-anchor', 'cross-target', 'attribute', 'deploy', 'terraform', 'no-partition', 'actions-order', 'actions-duplicate', 'actions-value', 'indexed', 'observed'])
def test_quicksight_api_group_principal(fault):
    comparison = fixture()
    comparison.partition = 'aws'
    rows = resource(comparison, 'quicksight', '001', 'QuickSight.Group', 'Group',
        [('AwsAccountId', '210987654321', None), ('Namespace', 'default', None), ('GroupName', 'analysts', None)])
    metadata = comparison.resources['quicksight']['001']
    metadata.pop('cfn-logicalId')
    metadata['resourceMode'] = 'IMPORT'
    comparison.models['quicksight'].values['desired.resource.001.resourceMode'] = 'IMPORT'
    comparison.models['quicksight'].authoritative['desired.resource.001.resourceMode'] = 'IMPORT'
    comparison.models['quicksight'].authoritative.pop('desired.resource.001.cfn-logicalId')
    comparison.models['quicksight'].values.pop('desired.resource.001.cfn-logicalId')
    link = '[display label](quicksight.md#group)'
    arn = 'arn:aws:quicksight:ap-northeast-1:210987654321:group/default/analysts'
    actions = ['quicksight:DescribeDataSource', 'quicksight:PassDataSource']
    actual = arn
    expected = 'matched'
    replacements = {'account': ('210987654321', '123456789012'), 'namespace': ('/default/', '/other/'),
        'group': ('/analysts', '/other'), 'region': ('ap-northeast-1', 'us-east-1'), 'partition': ('arn:aws:', 'arn:aws-cn:')}
    if fault in replacements:
        actual, expected = arn.replace(*replacements[fault]), 'difference'
    elif fault == 'sub':
        actual = {'Fn::Sub': 'arn:${AWS::Partition}:quicksight:${AWS::Region}:210987654321:group/default/analysts'}
    elif fault == 'join':
        actual = {'Fn::Join': ['', ['arn:', {'Ref': 'AWS::Partition'}, ':quicksight:', {'Ref': 'AWS::Region'}, ':210987654321:group/default/analysts']]}
    elif fault == 'unresolved':
        actual, expected = {'Fn::Sub': '${Missing}'}, 'uncompared'
    elif fault in {'unset', 'invalid-account', 'link-name'}:
        index, value = {'unset': (2, 'UNSET'), 'invalid-account': (0, 'invalid'), 'link-name': (2, link)}[fault]
        rows[index][1]['value'] = value
        expected = 'uncompared'
    elif fault and fault.startswith('missing-') and fault != 'missing-anchor':
        rows.pop({'missing-account': 0, 'missing-namespace': 1, 'missing-group': 2}[fault])
        expected = 'uncompared'
    elif fault == 'duplicate':
        rows.append(('001-004', dict(rows[-1][1])))
        expected = 'uncompared'
    elif fault == 'missing-anchor':
        link = link.replace('#group', '#missing')
        expected = 'uncompared'
    elif fault == 'observed':
        rows.append(('001-004', dict(property='QuickSight.Group.Arn', value=link)))
        comparison.models['quicksight'].authoritative['observed.row.001-004.value'] = 'PENDING_DEPLOY'
    elif fault in {'cross-target', 'attribute', 'deploy', 'terraform', 'no-partition'}:
        if fault == 'cross-target':
            link = link.replace('quicksight.md', '../other/quicksight.md')
        elif fault == 'deploy':
            comparison.local_comparison = False
        elif fault == 'terraform':
            comparison.target['iacEngine'] = 'terraform'
        elif fault == 'no-partition':
            comparison.partition = None
        with patch('comparison.inputs._imports_model_identity.Resolver'), pytest.raises(Blocked):
            comparison.desired_reference('quicksight', link, 'QuickSight.DataSource', 'Permissions[].Principal',
                                         'GroupName' if fault == 'attribute' else None)
        return
    actual_actions = actions[::-1] if fault == 'actions-order' else actions + actions[:1] if fault == 'actions-duplicate' else ['quicksight:UpdateDataSource'] if fault == 'actions-value' else actions
    if fault in {'actions-order', 'actions-duplicate', 'actions-value'}:
        expected = 'difference'
    desired = [{'Principal': link, 'Actions': actions}]
    records = setting(comparison, 'QuickSight.DataSource', 'Permissions', desired,
                      [{'Principal': actual, 'Actions': actual_actions}], service='quicksight')
    if fault == 'indexed':
        current = comparison.rows['quicksight']['090']
        current[:] = [('090-001', dict(property='QuickSight.DataSource.Permissions[1].Principal', value=link)),
                     ('090-002', dict(property='QuickSight.DataSource.Permissions[1].Actions', value=json.dumps(actions)))]
        document = comparison.stack_inputs['producer'][0]
        records = comparison.compare_rows('quicksight', '090', comparison.resources['quicksight']['090'],
            'producer', 'Receiver', ROOT / 'synthetic.yaml', document['Resources']['Receiver'], document).records
    assert records[0]['category'] == expected, records
    if fault is None:
        symbol = comparison.desired_reference('quicksight', link, 'QuickSight.DataSource', 'Permissions[].Principal')
        assert comparison.reference_literal(symbol) == arn
        with pytest.raises(Blocked, match='IMPORT'):
            comparison.reference('quicksight', link, 'Arn')


@pytest.mark.parametrize('prop,context,producer,expected', [
    ('ResourceId', {'ResourceType': 'VPC'}, 'Vpc', True),
    ('ResourceId', {}, 'Vpc', False), ('ResourceId', {'ResourceType': 'Subnet'}, 'Vpc', False),
    ('ResourceId', {'ResourceType': 'UNSET'}, 'Vpc', False),
    ('ResourceId', {'ResourceType': 'VPC'}, 'Subnet', False),
])
def test_flowlog_resource_type_context(prop, context, producer, expected):
    comparison = fixture()
    resource(comparison, 'vpc', '001', 'EC2.VPC', 'Vpc', [])
    resource(comparison, 'vpc', '002', 'EC2.Subnet', 'Subnet', [])
    link = '[producer](vpc.md#' + producer.lower() + ')'
    if expected:
        assert comparison.desired_reference('vpc', link, 'EC2.FlowLog', prop, context=context)['$attribute'] == 'VpcId'
    else:
        with pytest.raises(Blocked):
            comparison.desired_reference('vpc', link, 'EC2.FlowLog', prop, context=context)


@pytest.mark.parametrize('value', [None, {'Ref': 'AWS::NoValue'}, {'Fn::If': ['Active', {'Ref': 'AWS::NoValue'}, {'Ref': 'Vpc'}]},
                                   {'Ref': 'Role'}, {'Ref': 'Group'}, 'UNSET'])
def test_security_group_ref_requires_vpc(value):
    comparison = fixture()
    resource(comparison, 'vpc', '001', 'EC2.VPC', 'Vpc', [])
    resource(comparison, 'iam', '001', 'IAM.Role', 'Role', [])
    resource(comparison, 'security-group', '001', 'EC2.SecurityGroup', 'Group', [], properties={'VpcId': value})
    comparison.stack_inputs['producer'][0]['Conditions'] = {'Active': {'Fn::Equals': [1, 1]}}
    with pytest.raises(Blocked):
        comparison.evaluate('producer', {'Ref': 'Group'})
    assert comparison.evaluate('producer', {'Fn::GetAtt': ['Group', 'GroupId']})['$attribute'] == 'GroupId'


@pytest.mark.parametrize('fault', ['move', 'duplicate', 'parent', 'type', 'invalid'])
def test_cloudtrail_membership_comparison(fault):
    comparison = fixture()
    expected = [{'IncludeManagementEvents': True, 'DataResources': [
        {'Type': 'AWS::S3::Object', 'Values': ['a', 'a']}]},
        {'IncludeManagementEvents': False, 'DataResources': [{'Type': 'AWS::S3::Object', 'Values': ['b']}]}]
    actual = copy.deepcopy(expected)
    if fault == 'move':
        actual[0]['DataResources'].append(actual[1]['DataResources'].pop())
    elif fault == 'duplicate':
        actual[0]['DataResources'][0]['Values'].pop()
    elif fault == 'parent':
        actual.append({'IncludeManagementEvents': False})
    elif fault == 'type':
        actual[1]['DataResources'][0]['Type'] = 'AWS::Lambda::Function'
    if fault != 'invalid':
        records = setting(comparison, 'CloudTrail.Trail', 'EventSelectors', expected, actual)
        assert records[0]['category'] == 'difference', records
    else:
        resource(comparison, 'cloudtrail', '001', 'CloudTrail.Trail', 'Trail', [
            ('EventSelectors[].DataResources[].Values', '["a"]', None), ('IsLogging', 'true', None)])
        document = comparison.stack_inputs['producer'][0]
        definition = document['Resources']['Trail']
        definition['Properties'] = dict(IsLogging=False, EventSelectors=actual)
        records = comparison.compare_rows('cloudtrail', '001', comparison.resources['cloudtrail']['001'],
            'producer', 'Trail', ROOT / 'synthetic.yaml', definition, document).records
        assert any(item['category'] == 'uncompared' and 'membership unresolved' in item['reason'] for item in records), records
        assert any(item['property'].endswith('.IsLogging') and item['category'] == 'difference' for item in records), records


@pytest.mark.parametrize('fault', ['missing', 'output', 'conditional-output', 'export-name', 'sub-cycle', 'ref-cycle'])
def test_export_isolation_and_substitution_failures(fault):
    comparison = fixture()
    resource(comparison, 's3', '001', 'S3.Bucket', 'Bucket', [], properties={'BucketName': 'fixture'})
    document = comparison.stack_inputs['producer'][0]
    if fault == 'missing':
        comparison.templates = lambda: [('missing', {'name': 'missing'}), ('producer', {'name': 'producer'})]
        comparison.stack = Mock(side_effect=[Blocked('missing'), (ROOT / 'synthetic.yaml', comparison.stack_inputs['producer'])])
    elif fault == 'output':
        document['Outputs']['Broken'] = {'Value': 'x', 'Export': {'Name': {'Ref': 'Bucket'}}}
    elif fault == 'conditional-output':
        document['Conditions'] = {'Off': {'Fn::Equals': [1, 2]}}
        document['Outputs']['Hidden'] = {'Value': 'value', 'Condition': 'Off', 'Export': {'Name': 'hidden'}}
    elif fault == 'export-name':
        document['Outputs']['Broken'] = {'Value': 'x', 'Export': {'Name': {'Fn::Sub': '${Bucket}'}}}
    else:
        document['Resources']['Bucket']['Properties']['BucketName'] = {'Fn::Sub': '${Bucket}'} if fault == 'sub-cycle' else {'Ref': 'Bucket'}
        with pytest.raises(Blocked, match='cyclic'):
            comparison.evaluate('producer', {'Fn::Sub': '${Bucket}'})
        return
    if fault != 'conditional-output':
        # An unreadable stack or Export name cannot prove uniqueness, even with a candidate.
        with pytest.raises(Blocked, match='search incomplete'):
            exported(comparison, {'Fn::GetAtt': ['Bucket', 'Arn']})
        with patch.object(comparison, 'templates', side_effect=AssertionError('repeated export search')):
            with pytest.raises(Blocked, match='search incomplete'):
                comparison.evaluate('consumer', {'Fn::ImportValue': 'shared'})
        return
    assert exported(comparison, {'Fn::GetAtt': ['Bucket', 'Arn']})['$resource'] == ['s3', '001']
    with patch.object(comparison, 'templates', side_effect=AssertionError('repeated export search')):
        assert comparison.evaluate('consumer', {'Fn::ImportValue': 'shared'})['$attribute'] == 'Arn'
        with pytest.raises(Blocked):
            comparison.evaluate('consumer', {'Fn::ImportValue': 'hidden'})


@pytest.mark.parametrize('field,context', [('UnknownPolicyArns[]', {}), ('ManagedPolicyArns', {}), ('Description[]', {}),
    ('Tags[].Value', {}), ('ArnLikeNames[]', {}), ('Groups[]', {}),
    ('Environment.EnvironmentVariables[].Value', {}), ('ResourceRecords[]', {})])
def test_unknown_reference_property_never_infers_from_name(field, context):
    comparison = fixture()
    resource(comparison, 'iam', '001', 'IAM.ManagedPolicy', 'Policy', [])
    kind = 'CodeBuild.Project' if field.startswith('Environment') else 'Route53.RecordSet' if field.startswith('ResourceRecords') else 'IAM.User' if field == 'Groups[]' else 'IAM.Role'
    with pytest.raises(Blocked):
        comparison.desired_reference('iam', '[policy](iam.md#policy)', kind, field, context=context)


@pytest.mark.parametrize('mode', ['implicit', 'missing', 'wrong', 'plaintext'])
def test_codebuild_secret_context(mode):
    comparison = fixture()
    resource(comparison, 'secrets-manager', '001', 'SecretsManager.Secret', 'Secret', [], properties={'Name': 'app/secret'})
    link = '[secret](secrets-manager.md#secret)'
    if mode == 'implicit':
        context = {'Type': 'SECRETS_MANAGER' if mode == 'implicit' else 'PLAINTEXT'}
        symbol = comparison.desired_reference('secrets-manager', link, 'CodeBuild.Project', 'Environment.EnvironmentVariables[].Value', context=context)
        desired = {'Name': 'SECRET', 'Type': context['Type'], 'Value': symbol}
        callback = partial(reference_for, comparison, 'CodeBuild.Project')
        assert same(desired, dict(desired, Value='app/secret'), path='Environment.EnvironmentVariables[]', reference=callback) is (mode == 'implicit')
        assert same(desired, dict(desired, Value='app/secret:key:AWSPREVIOUS'), path='Environment.EnvironmentVariables[]', reference=callback) is False
    else:
        with pytest.raises(Blocked):
            comparison.desired_reference('secrets-manager', link, 'CodeBuild.Project', 'Environment.EnvironmentVariables[].Value', context={} if mode == 'missing' else {'Type': 'PLAINTEXT' if mode == 'plaintext' else 'PARAMETER_STORE'})


@pytest.mark.parametrize('case,expected', [('reverse', True), ('duplicate', False), ('missing', False), ('value', False), ('unrelated', False), ('unknown', None), ('known-difference', False)])
def test_policy_statement_bijection(case, expected):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [])
    first = {'Sid': 'One', 'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': '*'}
    second = dict(first, Sid='Two', Action='s3:PutObject')
    left, right = [first, second], [second, first]
    path = 'Policies[].PolicyDocument.Statement'
    if case == 'duplicate':
        left = [first, first]
    elif case == 'missing':
        left = [first]
    elif case == 'value':
        right = [second, dict(first, Effect='Deny')]
    elif case == 'unrelated':
        path = 'Unrelated'
    elif case in {'unknown', 'known-difference'}:
        left = [dict(first, Resource=comparison.evaluate('producer', {'Fn::GetAtt': ['Key', 'Arn']})), second]
        if case == 'known-difference':
            right = [dict(second, Effect='Deny'), first]
    assert same(left, right, path=path, reference=partial(reference_for, comparison, 'IAM.Role')) is expected


def test_unordered_augmenting_paths():
    pairs = {(1, 3): True, (1, 4): True, (2, 3): True}
    assert unordered_same([1, 2], [3, 4], reference=lambda a, b, p: pairs.get((a, b), False)) is True
    assert unordered_same([1, 2], [3, 4], reference=lambda a, b, p: None) is None


def reference_for(comparison, kind, left, right, path):
    return comparison.reference_same(left, right, kind, path)


@pytest.mark.parametrize('actual', [{'EnvironmentVariables': []}, None])
def test_incomplete_codebuild_missing_structure(actual):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Alias', 'Alias', [])
    rows = [('Environment.EnvironmentVariables[1].Name', 'RELEASE_BUCKET_KMS_KEY_ID', None),
            ('Environment.EnvironmentVariables[1].Type', 'PLAINTEXT', None),
            ('Environment.EnvironmentVariables[1].Value', '[alias](kms.md#alias)', None)]
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build', rows,
             properties={} if actual is None else {'Environment': actual})
    document = comparison.stack_inputs['producer'][0]
    result = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert result.failure is None
    differences = [item for item in result.records if item['category'] == 'difference']
    assert len(differences) == 1, result.records
    unresolved = [item for item in result.records if item['category'] == 'uncompared']
    assert len(unresolved) == 1 and 'explicit attribute' in unresolved[0]['reason'], result.records
    assert not any(item['category'] in {'error', 'matched'} for item in result.records)
    shown = json.dumps(result.display_differences)
    assert 'RELEASE_BUCKET_KMS_KEY_ID' in shown and 'Environment' in shown


@pytest.mark.parametrize('deferred', [False, True])
def test_nested_diagnostics_retain_format_and_failures(deferred):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [])
    properties = {'ResultConfiguration': {'EncryptionConfiguration': {'KmsKey': {'Ref': 'Key'}}}}
    rows = [(ATHENA_KMS, '[key](kms.md#key)', None), ('WorkGroupConfiguration.EnforceWorkGroupConfiguration', 'true', None)]
    if deferred:
        rows += [('WorkGroupConfiguration.ExecutionRole', '[private](kms.md#private-missing)', None),
                 ('WorkGroupConfiguration.ResultConfiguration.ExpectedBucketOwner', '[missing](kms.md#missing)', None)]
    resource(comparison, 'athena', '001', 'Athena.WorkGroup', 'WorkGroup', rows,
             properties={'WorkGroupConfiguration': dict(properties, EnforceWorkGroupConfiguration=True)})
    comparison.sensitive_values.add('private')
    document = comparison.stack_inputs['producer'][0]
    result = comparison.compare_rows('athena', '001', comparison.resources['athena']['001'],
        'producer', 'WorkGroup', ROOT / 'synthetic.yaml', document['Resources']['WorkGroup'], document).records
    record = next(item for item in result if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')
    if deferred:
        assert record['category'] == 'difference' and len(record['deferred_children']) == 2
        assert {child['property'] for child in record['deferred_children']} == {
            'Athena.WorkGroup.WorkGroupConfiguration.ExecutionRole',
            'Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.ExpectedBucketOwner'}
        assert all(child['reason'] for child in record['deferred_children'])
        assert {child['category'] for child in record['deferred_children']} == {'uncompared'}
        assert 'private' not in json.dumps(result)
    assert record['category'] == 'difference', result
    diagnostic = record['reference_diagnostics'][0]
    assert diagnostic['path'] == 'Athena.WorkGroup.' + ATHENA_KMS
    assert diagnostic['identity'] == 'same' and diagnostic['allowed_forms'] == ['KeyArn']
    assert diagnostic['model']['$attribute'] == 'Arn' and diagnostic['iac']['$attribute'] == 'KeyId'
    assert len(record.get('deferred_children', [])) == (2 if deferred else 0)
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('scenario', [
    'same', 'siblings', 'null', 'false', 'empty-string', 'empty-array',
    'no-value', 'condition-unknown', 'condition-present', 'condition-absent',
    'value-null', 'value-false', 'value-empty-string', 'value-empty-array',
])
def test_incomplete_setting_presence_and_siblings(scenario):
    comparison = fixture()
    comparison.stack_inputs['producer'][2]['AWS::NoValue'] = {'$noValue': True}
    resource(comparison, 'kms', '001', 'KMS.Alias', 'Alias', [])
    prefix = 'Environment.EnvironmentVariables[1].'
    rows = [(prefix + 'Name', 'RELEASE_BUCKET_KMS_KEY_ID', None),
            (prefix + 'Type', 'PLAINTEXT', None), (prefix + 'Value', '[alias](kms.md#alias)', None)]
    variable = {'Name': 'RELEASE_BUCKET_KMS_KEY_ID', 'Type': 'PLAINTEXT', 'Value': 'unknown'}
    environment = {'EnvironmentVariables': [variable], 'Extra': 'allowed'}
    if scenario == 'siblings':
        variable['Type'] = 'PARAMETER_STORE'
        rows += [('Environment.Image', 'image', None),
                 ('Environment.EnvironmentVariables[2].Name', 'SECOND', None)]
    empty_values = {'null': None, 'false': False, 'empty-string': '', 'empty-array': []}
    if scenario in empty_values:
        environment = empty_values[scenario]
    if scenario.startswith('value-'):
        variable['Value'] = empty_values[scenario.removeprefix('value-')]
    if scenario == 'no-value':
        environment = {'Ref': 'AWS::NoValue'}
    if scenario.startswith('condition-'):
        environment = {'Fn::If': ['Present', environment, {'Ref': 'AWS::NoValue'}]}
        if scenario != 'condition-unknown':
            comparison.stack_inputs['producer'][0]['Conditions'] = {'Present': scenario == 'condition-present'}
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build', rows,
             properties={'Environment': environment})
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert batch.failure is None
    differences = [item for item in batch.records if item['category'] == 'difference']
    expected = scenario in {*empty_values, 'siblings', 'no-value', 'condition-absent'}
    assert len(differences) == int(expected), batch.records
    assert not any(item['category'] in {'matched', 'error'} for item in batch.records), batch.records
    children = [item for item in batch.records if item['property'].endswith('[1].Value')]
    assert len(children) == 1 and children[0]['category'] == 'uncompared'
    assert 'explicit attribute' in children[0]['reason'] and children[0]['iac']['path'] == 'synthetic.yaml'
    if scenario == 'siblings':
        fields = next(iter(batch.display_differences.values()))
        paths = {field['path'] for field in fields}
        assert paths == {'Image', 'EnvironmentVariables[0].Type', 'EnvironmentVariables[1]'}, fields
        assert any('SECOND' in field['model'] for field in fields)
    elif scenario in empty_values:
        assert differences[0]['reason'] == 'value mismatch'
        assert differences[0]['actual'] == empty_values[scenario]
        assert next(iter(batch.display_differences.values()))[0]['iac'] != '欠落'
    elif scenario in {'no-value', 'condition-absent'}:
        assert differences[0]['reason'] == 'property omitted by AWS::NoValue'
        assert differences[0]['actual'] is None
        assert next(iter(batch.display_differences.values()))[0]['iac'] == '欠落'
    elif scenario == 'condition-unknown':
        assert any(item['property'] == 'CodeBuild.Project.Environment' and item['category'] == 'uncompared'
                   for item in batch.records)


@pytest.mark.parametrize('present', [False, True])
def test_all_children_failed_preserve_parent_and_categories(present):
    comparison = fixture()
    rows = [('Environment.Image', '[missing](kms.md#missing)', None),
            ('Environment.PrivilegedMode', 'invalid-json', None)]
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build', rows,
             properties={'Environment': {'Image': 'image', 'PrivilegedMode': False}} if present else {})
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert batch.failure is None
    assert sorted(item['category'] for item in batch.records) == (
        ['error', 'uncompared'] if present else ['difference', 'error', 'uncompared']), batch.records
    if not present:
        parent = next(item for item in batch.records if item['category'] == 'difference')
        assert parent['property'] == 'CodeBuild.Project.Environment' and parent['reason'] == 'property missing'
        assert {item['category'] for item in parent['deferred_children']} == {'error', 'uncompared'}


@pytest.mark.parametrize('document_row', [False, True])
@pytest.mark.parametrize('scenario', ['missing-element', 'missing-field', 'same', 'mismatch'])
def test_incomplete_json_preserves_declared_children(document_row, scenario):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Alias', 'Alias', [])
    desired = {'EnvironmentVariables': [dict(Name='RELEASE_BUCKET_KMS_KEY_ID', Type='PLAINTEXT',
                                           Value='[alias](kms.md#alias)')]}
    actual = copy.deepcopy(desired)
    actual['EnvironmentVariables'][0]['Value'] = 'unproven-value'
    if scenario == 'missing-element':
        actual['EnvironmentVariables'] = []
    elif scenario == 'missing-field':
        del actual['EnvironmentVariables'][0]['Type']
    elif scenario == 'mismatch':
        actual['EnvironmentVariables'][0]['Type'] = 'PARAMETER_STORE'
    rows = resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build',
                    [('Environment', json.dumps(desired), None)], properties={'Environment': actual})
    if document_row:
        rows[0][1]['document'] = json.dumps(desired)
    prepared = comparison.prepare_value('codebuild', rows[0][1], 'CodeBuild.Project', stack='producer')
    with pytest.raises(Blocked, match='explicit attribute'):
        prepared.require_value()
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert batch.failure is None
    assert sorted(item['category'] for item in batch.records) == (
        ['uncompared'] if scenario == 'same' else ['difference', 'uncompared']), batch.records
    unresolved = next(item for item in batch.records if item['category'] == 'uncompared')
    assert unresolved['property'].endswith('EnvironmentVariables[].Value')
    assert unresolved['model']['pointer'] == '/EnvironmentVariables/0/Value'
    assert 'explicit attribute' in unresolved['reason']


def fail_image_preparation(error, original, service, row, kind, **kwargs):
    if row['property'].endswith('.Image'):
        raise error('synthetic preparation failure')
    return original(service, row, kind, **kwargs)


@pytest.mark.parametrize('error', [ValueError, TypeError, OSError, ImportError, IndexError])
def test_preparation_error_retains_confirmed_difference(error):
    comparison = fixture()
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build',
             [('Environment.Image', 'image', None), ('Environment.Type', 'LINUX_CONTAINER', None)],
             properties={'Environment': {}})
    comparison.prepare_value = partial(fail_image_preparation, error, comparison.prepare_value)
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert batch.failure is None
    assert sorted(item['category'] for item in batch.records) == ['difference', 'error'], batch.records
    assert any(item['reason'] == 'synthetic preparation failure' for item in batch.records)


def test_naming_materials_mode_and_root_targets():
    comparison = fixture()
    comparison.services = ['vpc', 'codebuild', 'codepipeline', 'glue', 'kms']
    for identity, mode, rows in [('001', 'CREATE', []), ('002', 'IMPORT', []), ('003', 'CREATE', [('Name', 'bad_pattern_value', None)])]:
        parsed = resource(comparison, 'vpc', identity, 'EC2.VPC', 'Vpc' + identity, rows)
        comparison.resources['vpc'][identity]['resourceMode'] = mode
        for _, row in parsed:
            row['comment'] = 'component evidence unconfirmed'
    specs = [('codebuild', 'CodeBuild.Project', ['Environment.EnvironmentVariables[].Name', 'Artifacts.Name']),
             ('codepipeline', 'CodePipeline.Pipeline', ['Stages[].Name', 'Stages[].Actions[].Name']),
             ('glue', 'Glue.Job', ['Command.Name'])]
    for service, kind, nested in specs:
        rows = resource(comparison, service, '001', kind, service.title(), [('Name', 'invalid_root_name', None), *[(prop, 'nested', None) for prop in nested]])
        for _, row in rows:
            row['comment'] = 'fixture name'
    alias_rows = resource(comparison, 'kms', '001', 'KMS.Alias', 'Alias', [('AliasName', 'alias/HumanActual', None)])
    comparison.resources['kms']['001']['resourceMode'] = 'IMPORT'
    alias_rows[0][1]['comment'] = 'human exception'
    material, _ = naming_materials(comparison)
    names = material['names']
    assert next(item for item in names if item['service'] == 'vpc' and item['resource'] == '001')['required_missing']
    assert not next(item for item in names if item['service'] == 'vpc' and item['resource'] == '002')['required_missing']
    selected = next(item for item in names if item['service'] == 'vpc' and item['resource'] == '003')
    assert selected['pattern_review'] == 'required' and selected['value'] == '`bad_pattern_value`'
    assert '推測しない' in material['review_policy']
    alias = next(item for item in names if item['service'] == 'kms')
    assert alias['resourceMode'] == 'IMPORT' and alias['value'] == '`alias/HumanActual`' and not alias['required_missing']
    assert {(item['service'], item['property']) for item in names if item['service'] not in {'vpc', 'kms'}} == {
        ('codebuild', 'Name'), ('codepipeline', 'Name'), ('glue', 'Name')}


@pytest.mark.parametrize('region,partition,suffix', [('ap-northeast-1', 'aws', 'amazonaws.com'),
    ('cn-north-1', 'aws-cn', 'amazonaws.com.cn'), ('us-gov-west-1', 'aws-us-gov', 'amazonaws.com'),
    ('us-iso-east-1', 'aws-iso', 'c2s.ic.gov'), ('eusc-de-east-1', 'aws-eusc', 'amazonaws.eu'),
    ('ap-fake-1', None, None)])
def test_stack_partition_and_noecho(tmp_path, region, partition, suffix):
    comparison = fixture()
    comparison.root = tmp_path
    comparison.target['awsRegion'] = region
    comparison.stack_inputs = {}
    comparison.documents = {}
    comparison.metrics = dict(template_decodes=0, stack_evaluations=0)
    comparison.track = Mock()
    template = tmp_path / 'infra/cloudformation/templates/one.yaml'
    parameters = tmp_path / 'infra/cloudformation/parameters/fixture/team/one.json'
    template.parent.mkdir(parents=True)
    parameters.parent.mkdir(parents=True)
    template.write_text(json.dumps({'Resources': {}, 'Parameters': {'Sensitive': {'Type': 'String', 'NoEcho': True, 'Default': 'private'}}}), encoding='utf-8')
    parameters.write_text('[]', encoding='utf-8')
    with patch('socket.socket', side_effect=AssertionError('network forbidden')):
        Comparison.stack_input(comparison, dict(name='producer', template='one.yaml', parameters='one.json'))
    document, _, pseudo = comparison.stack_inputs['producer']
    assert pseudo.get('AWS::Partition') == partition
    assert pseudo.get('AWS::URLSuffix') == suffix
    for name, expected in [('AWS::Region', region), ('AWS::AccountId', '123456789012'),
                           ('AWS::StackName', 'producer'), ('AWS::NoValue', {'$noValue': True})]:
        assert comparison.evaluate('producer', {'Ref': name}) == expected
    assert comparison.redacted('prefix-private') == '<masked sensitive parameter>'
    expression = {'Fn::Sub': 'secretsmanager.${AWS::Region}.${AWS::URLSuffix}'}
    for name, expected in [('AWS::Partition', partition), ('AWS::URLSuffix', suffix)]:
        if expected is None:
            assert name not in pseudo
            for value in ({'Ref': name}, {'Fn::Sub': '${' + name + '}'}):
                with pytest.raises(Blocked, match='unresolved pseudo parameter'):
                    comparison.evaluate('producer', value)
        else:
            assert comparison.evaluate('producer', {'Ref': name}) == expected
    if suffix is not None:
        assert comparison.evaluate('producer', expression) == f'secretsmanager.{region}.{suffix}'
        document['Conditions'] = {'Off': {'Fn::Equals': [expression, 'other']}}
        _, evidence = inactive_evidence('producer', 'Role', {'Condition': 'Off'}, document, {}, pseudo,
            path='one.yaml', parameter_path='one.json', supplied=set(), stack_id='001', target=comparison.target,
            environment='fixture', directory='team', marks={}, source_lookup=Mock(), redact=comparison.redacted)
        assert next(item for item in evidence['inputs'] if item['name'] == 'AWS::URLSuffix') == {
            'name': 'AWS::URLSuffix', 'value': suffix,
            'source': {'kind': 'botocore-endpoints', 'region': region, 'key': 'AWS::URLSuffix'}}
    comparison.root = ROOT
    for different in (False, True):
        policy = [{'PolicyName': 'KmsPolicy', 'PolicyDocument': {'Version': '2012-10-17', 'Statement': [{
            'Effect': 'Allow', 'Action': 'kms:Decrypt', 'Resource': '*',
            'Condition': {'StringEquals': {'kms:ViaService': f'secretsmanager.{region}.{suffix}'}}}]}}]
        actual = copy.deepcopy(policy)
        actual[0]['PolicyDocument']['Statement'][0]['Condition']['StringEquals']['kms:ViaService'] = expression
        if different:
            policy[0]['PolicyDocument']['Statement'][0]['Condition']['StringEquals']['kms:ViaService'] = 'different'
        records = setting(comparison, 'IAM.Role', 'Policies', policy, actual)
        expected = 'uncompared' if suffix is None else 'difference' if different else 'matched'
        assert [item['category'] for item in records] == [expected], records


def test_inactive_inline_policy_provenance():
    comparison = fixture()
    resource(comparison, 's3', '001', 'S3.Bucket', 'Bucket', [('BucketName', 'fixture', None)], properties={'BucketName': 'fixture'})
    comparison.rows['s3']['001'].append(('001-002', dict(property='S3.BucketPolicy.PolicyDocument', value='{}')))
    document = comparison.stack_inputs['producer'][0]
    document['Conditions'] = {'Off': {'Fn::Equals': [1, 2]}}
    document['Resources']['Policy'] = dict(Type='AWS::S3::BucketPolicy', Condition='Off', Properties={'Bucket': {'Ref': 'Bucket'}, 'PolicyDocument': {}})
    comparison.parameter_keys = Mock(return_value=(ROOT / 'parameters.json', set()))
    result = comparison.compare_rows('s3', '001', comparison.resources['s3']['001'], 'producer', 'Bucket',
        ROOT / 'synthetic.yaml', document['Resources']['Bucket'], document).records
    child = next(item for item in result if item.get('cause', {}).get('kind') == 'condition-disabled')
    assert child['property'] == 'S3.BucketPolicy' and child['cause']['logical'] == 'Policy'
    assert child['iac']['key'] == 'Resources.Policy.Condition'


@pytest.mark.parametrize('case,category', [('match', 'matched'), ('order', 'difference'), ('json', 'error')])
def test_inline_policy_document(case, category):
    comparison = fixture()
    resource(comparison, 's3', '001', 'S3.Bucket', 'Bucket', [])
    policy = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Action': ['s3:GetObject'], 'Resource': ['first', 'second']}]}
    comparison.rows['s3']['001'].append(('001-001', dict(property='S3.BucketPolicy.PolicyDocument', value='policy.json',
        document='{bad json' if case == 'json' else json.dumps(policy))))
    actual = copy.deepcopy(policy)
    if case == 'order':
        actual['Statement'][0]['Resource'].reverse()
    document = comparison.stack_inputs['producer'][0]
    document['Resources']['Policy'] = dict(Type='AWS::S3::BucketPolicy', Properties={'Bucket': {'Ref': 'Bucket'}, 'PolicyDocument': actual})
    result = comparison.compare_rows('s3', '001', comparison.resources['s3']['001'], 'producer', 'Bucket',
        ROOT / 'synthetic.yaml', document['Resources']['Bucket'], document)
    assert any(item['category'] == category for item in result.records), result


def test_grouped_parent_reference():
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [])
    resource(comparison, 'kms', '002', 'KMS.Alias', 'Alias', [('AliasName', 'alias/fixture', None)],
        properties={'AliasName': 'alias/fixture', 'TargetKeyId': {'Ref': 'Key'}})
    alias = comparison.resources['kms']['002']
    alias.update(parentReference='[key](kms.md#key)', parentProperty='KMS.Alias.TargetKeyId')
    document = comparison.stack_inputs['producer'][0]
    result = comparison.compare_rows('kms', '002', alias, 'producer', 'Alias', ROOT / 'synthetic.yaml',
        document['Resources']['Alias'], document).records
    assert any(item['property'] == 'KMS.Alias.TargetKeyId' and item['category'] == 'matched' for item in result), result


@pytest.mark.parametrize('mode,category', [('IMPORT', 'excluded'), ('terraform', 'uncompared'),
                                         ('undeclared', 'uncompared'), ('missing-template', 'difference')])
def test_run_mode_classification(tmp_path, mode, category):
    comparison = fixture()
    comparison.root = tmp_path
    comparison.services = ['s3']
    resource(comparison, 's3', '001', 'S3.Bucket', 'Bucket', [])
    if mode == 'IMPORT':
        comparison.resources['s3']['001']['resourceMode'] = 'IMPORT'
    elif mode == 'terraform':
        comparison.target['iacEngine'] = 'terraform'
    elif mode == 'undeclared':
        comparison.resources['s3']['001']['cfn-logicalId'] = 'undeclared-Bucket'
    records = comparison.run()
    assert len(records) == 1 and records[0]['category'] == category, records
    if mode == 'undeclared':
        assert 'stack is not declared' in records[0]['reason'] and 'cause' not in records[0]
    elif mode == 'missing-template':
        assert records[0]['cause']['relationship'] == 'direct' and records[0]['cause']['kind'] == 'template-missing'


@pytest.mark.parametrize('second,kind', [('same', 'template-missing'), ('other', 'import-unresolved'), ('unknown', 'import-unresolved')])
def test_import_failure_cause_requires_unique_path(second, kind):
    comparison = fixture()
    failures = [Blocked('stack input missing'), Blocked('another input missing')]
    failures[0].iac_cause = dict(kind='template-missing', path='missing.yaml', relationship='stack-input')
    if second != 'unknown':
        failures[1].iac_cause = dict(failures[0].iac_cause, path='missing.yaml' if second == 'same' else 'other.yaml')
    comparison.stack = Mock(side_effect=failures)
    with pytest.raises(Blocked) as error:
        comparison.evaluate('consumer', {'Fn::ImportValue': 'missing'})
    assert error.value.iac_cause['kind'] == kind
    assert error.value.iac_cause['relationship'] == ('export-search-incomplete' if second == 'same' else 'import')


def test_recorded_evidence_survives_nested_expression_and_reversal():
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    expression = {'Fn::Join': ['', [{'Fn::Select': [0, {'Fn::Split': ['|',
        {'Fn::Sub': ['${Arn}|unused', {'Arn': {'Fn::GetAtt': ['Key', 'Arn']}}]}]}]}, '/suffix']]}
    actual = exported(comparison, expression)
    for left, right in [(KEY_ARN + '/suffix', actual), (actual, KEY_ARN + '/suffix')]:
        decision = comparison.reference_decision(left, right, 'IAM.Role', 'Policies')
        assert decision.equal is None and not decision.equivalent, decision
        detail = decision.diagnostics[0]
        assert detail['current_aws_verified'] is False and detail['evidence_type'] == 'recorded_observed'
        assert detail['producers'][0]['producer'] == 'kms/001'
    assert comparison.reference_decision(KEY_ARN + '/other', actual, 'IAM.Role', 'Policies').equal is None



@pytest.mark.parametrize('fault', [None, 'missing', 'stale'])
def test_saved_literal_evidence_is_checked_in_both_directions(fault):
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    declaration(comparison, 'desired.row.010-001.value', VPC)
    desired = prepared(comparison, row).require_value()
    actual = exported(comparison, {'Ref': 'Vpc'})
    if fault == 'missing':
        comparison.models['vpc'].authoritative.pop('observed.row.001-001.value')
    elif fault == 'stale':
        comparison.models['vpc'].authoritative['observed.row.001-001.value'] = '`vpc-other`'
    compound = Expression('Join', ['', ['pre/', desired]])
    evaluated = Expression('Sub', ['pre/${R}', {'R': actual}])
    for left, right in [(desired, actual), (actual, desired), (desired, VPC), (VPC, desired),
                        (compound, evaluated), (evaluated, compound)]:
        assert comparison.reference_decision(left, right, 'EC2.Subnet', 'VpcId').equal is (True if fault is None and not isinstance(left, str) and not isinstance(right, str) else None)



@pytest.mark.parametrize('field,replacement', [('AWS::Partition', 'aws-cn'), ('AWS::AccountId', '999999999999'),
                                             ('AWS::Region', 'us-east-1'), ('AWS::Partition', None)])
def test_cached_exports_are_bound_to_the_consumer_scope(field, replacement):
    comparison = fixture()
    vpc(comparison)
    original = exported(comparison, {'Ref': 'Vpc'})
    assert comparison.reference_same(VPC, original, 'EC2.Subnet', 'VpcId') is None
    document, parameters, pseudo = comparison.stack_inputs['consumer']
    comparison.stack_inputs['consumer'] = document, parameters, dict(pseudo, **{field: replacement})
    with pytest.raises(Blocked, match='handoff matches=0|confirmed'):
        comparison.evaluate('consumer', {'Fn::ImportValue': 'shared'})



@pytest.mark.parametrize('kind,attribute,identifier,properties,arn', [
    ('EC2.VPC', 'VpcId', VPC, {}, 'arn:aws:ec2:ap-northeast-1:123456789012:vpc/' + VPC),
    ('EC2.EIP', 'AllocationId', 'eipalloc-0123456789abcdef0', {}, 'arn:aws:ec2:ap-northeast-1:123456789012:elastic-ip/eipalloc-0123456789abcdef0'),
    ('CloudFront.Distribution', 'Id', 'E123ABC', {}, 'arn:aws:cloudfront::123456789012:distribution/E123ABC'),
    ('SSM.MaintenanceWindow', 'WindowId', 'mw-0123456789abcdef0', {}, 'arn:aws:ssm:ap-northeast-1:123456789012:maintenancewindow/mw-0123456789abcdef0'),
    ('SSM.MaintenanceWindowTarget', 'WindowTargetId', KEY_ID, {}, 'arn:aws:ssm:ap-northeast-1:123456789012:windowtarget/' + KEY_ID),
    ('ApiGateway.Authorizer', 'AuthorizerId', 'abc123', {'RestApiId': 'def456'}, 'arn:aws:apigateway:ap-northeast-1::/restapis/def456/authorizers/abc123'),
    ('Route53.HostedZone', 'Id', 'Z123XYZ', {}, 'arn:aws:route53:::hostedzone/Z123XYZ'),
])
@pytest.mark.parametrize('fault', [None, 'missing', 'import', 'inactive'])
def test_shared_recorded_arn_proof(kind, attribute, identifier, properties, arn, fault):
    comparison = fixture()
    resource(comparison, 'producer', '001', kind, 'Resource', [(attribute, 'PENDING_DEPLOY', identifier)],
             properties=dict(properties, **{attribute: 'forged-template-id'}))
    symbol = ResourceReference({'$resource': ['producer', '001'], '$attribute': 'Arn'})
    if fault == 'missing':
        comparison.models['producer'].authoritative.pop('observed.row.001-001.value')
    elif fault == 'import':
        comparison.resources['producer']['001']['resourceMode'] = 'IMPORT'
    elif fault == 'inactive':
        comparison.stack_inputs['producer'][0]['Conditions'] = {'Off': False}
        comparison.stack_inputs['producer'][0]['Resources']['Resource']['Condition'] = 'Off'
    for left, right in [(symbol, arn), (arn, symbol)]:
        decision = comparison.reference_decision(left, right, 'IAM.Role', 'Policies[].PolicyDocument.Statement[].Resource')
        assert decision.equal is None and not decision.equivalent, decision
        if fault is None:
            assert decision.diagnostics[0]['evidence_type'] == 'recorded_observed'
            assert decision.diagnostics[0]['current_aws_verified'] is False
    if fault is None:
        for different in (arn + '-other', arn.replace('arn:aws:', 'arn:aws-cn:'), arn.replace('123456789012', '999999999999')):
            if different != arn:
                assert comparison.reference_same(symbol, different, 'IAM.Role', '') is None



if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))


@pytest.mark.parametrize('function', ['select', 'if', 'join'])
@pytest.mark.parametrize('known_difference', [False, True])
@pytest.mark.parametrize('model_unresolved', [False, True])
def test_iac_partial_errors_preserve_known_fields(function, known_difference, model_unresolved):
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Alias', 'Alias', [])
    broken = {'select': {'Fn::Select': [2, ['only']]}, 'if': {'Fn::If': ['InvalidCondition']},
              'join': {'Fn::Join': ['', [None]]}}[function]
    rows = [('Environment.Image', 'GOOD_IMAGE', None),
            ('Environment.EnvironmentVariables[1].Name', 'RELEASE_BUCKET_KMS_KEY_ID', None),
            ('Environment.EnvironmentVariables[1].Type', 'PLAINTEXT', None),
            ('Environment.EnvironmentVariables[1].Value', '[alias](kms.md#alias)' if model_unresolved else 'known', None)]
    actual = dict(Image='WRONG_IMAGE' if known_difference else 'GOOD_IMAGE', EnvironmentVariables=[dict(
        Name='RELEASE_BUCKET_KMS_KEY_ID', Type='PARAMETER_STORE' if known_difference else 'PLAINTEXT', Value=broken)])
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build', rows, properties={'Environment': actual})
    comparison.template_locations[id(actual['EnvironmentVariables'][0])] = {'Value': 23}
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    categories = [item['category'] for item in batch.records]
    assert categories.count('difference') == int(known_difference), batch.records
    assert categories.count('error') == 1 and categories.count('uncompared') == int(model_unresolved), batch.records
    assert 'matched' not in categories and batch.failure is None
    error = next(item for item in batch.records if item['category'] == 'error')
    assert error['property'] == 'CodeBuild.Project.Environment#/EnvironmentVariables/0/Value'
    assert error['iac'] == {'path': 'synthetic.yaml', 'line': 23, 'pointer': '/EnvironmentVariables/0/Value'}
    if known_difference:
        assert {item['path'] for item in next(iter(batch.display_differences.values()))} == {
            'Image', 'EnvironmentVariables[0].Type'}
    if model_unresolved:
        unresolved = next(item for item in batch.records if item['category'] == 'uncompared')
        assert 'explicit attribute' in unresolved['reason']


@pytest.mark.parametrize('exact', [False, True])
@pytest.mark.parametrize('different', [False, True])
def test_iac_partial_selective_extra_fields(exact, different):
    comparison = fixture()
    rows = [('Environment', json.dumps({'Image': 'MODEL_IMAGE'}), None)] if exact else [('Environment.Image', 'MODEL_IMAGE', None)]
    actual = {'Image': 'OTHER_IMAGE' if different else 'MODEL_IMAGE',
              'AdditionalField': {'Fn::If': ['InvalidCondition', 'A', 'B']}}
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build', rows, properties={'Environment': actual})
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    differences = [item for item in batch.records if item['category'] == 'difference']
    assert len(differences) == int(different), batch.records
    assert not any(item['category'] == 'error' for item in batch.records)
    if not exact:
        assert [item['category'] for item in batch.records] == ['difference' if different else 'matched']
    if different:
        assert 'Image' in {item['path'] for item in next(iter(batch.display_differences.values()))}


@pytest.mark.parametrize('scenario', ['field', 'element', 'unknown-presence', 'key', 'no-value',
                                      'null', 'false', 'empty-string', 'empty-array'])
def test_iac_partial_array_presence(scenario):
    comparison = fixture()
    comparison.stack_inputs['producer'][2]['AWS::NoValue'] = {'$noValue': True}
    broken = {'Fn::Select': [2, ['only']]}
    first = dict(Name='FIRST', Type='PLAINTEXT', Value='known')
    desired = {'Image': 'GOOD_IMAGE', 'EnvironmentVariables': [first]}
    actual = copy.deepcopy(desired)
    actual['EnvironmentVariables'][0]['Type'] = 'PARAMETER_STORE'
    if scenario == 'field':
        actual['EnvironmentVariables'][0]['Value'] = broken
    elif scenario in {'element', 'unknown-presence'}:
        desired['EnvironmentVariables'].append(dict(Name='SECOND', Value='value'))
        actual['EnvironmentVariables'].append(broken if scenario == 'element' else
            {'Fn::If': ['Unknown', dict(Name='SECOND', Value='value'), {'Ref': 'AWS::NoValue'}]})
    elif scenario == 'key':
        desired = {'Tags': [{'Key': 'Known', 'Value': 'one'}, {'Key': 'Missing', 'Value': 'two'}]}
        actual = {'Tags': [{'Key': 'Known', 'Value': 'wrong'}, {'Key': broken, 'Value': 'two'}]}
    elif scenario == 'no-value':
        actual['EnvironmentVariables'].insert(0, {'Fn::If': ['Absent', broken, {'Ref': 'AWS::NoValue'}]})
        comparison.stack_inputs['producer'][0]['Conditions'] = {'Absent': False}
        actual['EnvironmentVariables'][1]['Value'] = broken
    else:
        value = {'null': None, 'false': False, 'empty-string': '', 'empty-array': []}[scenario]
        desired['EnvironmentVariables'].append(value)
        actual['EnvironmentVariables'].append(value)
        actual['EnvironmentVariables'][0]['Value'] = broken
    key = 'Tags' if scenario == 'key' else 'Environment'
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build',
        [(key, json.dumps(desired[key] if key == 'Tags' else desired), None)],
        properties=actual if key == 'Tags' else {'Environment': actual})
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert batch.failure is None and sum(item['category'] == 'difference' for item in batch.records) == 1, batch.records
    assert any(item['category'] == ('uncompared' if scenario == 'unknown-presence' else 'error') for item in batch.records)
    fields = next(iter(batch.display_differences.values()))
    assert len(fields) == 1 and fields[0]['path'].endswith('.Type' if scenario != 'key' else '.Value'), fields
    assert fields[0]['iac'] != '欠落'


@pytest.mark.parametrize('case', ['missing', 'same', 'wrong', 'duplicate', 'omitted', 'condition-child'])
def test_iac_partial_keyed_and_conditional_membership(case):
    comparison = fixture()
    comparison.stack_inputs['producer'][2]['AWS::NoValue'] = {'$noValue': True}
    unknown = {'Fn::If': ['Unknown', 'key', {'Ref': 'AWS::NoValue'}]}
    actual = [{'Key': 'Known', 'Value': 'wrong' if case == 'wrong' else 'one'}, {'Key': unknown, 'Value': 'two'}]
    if case == 'duplicate':
        actual.insert(0, {'Key': 'Known', 'Value': 'one'})
    elif case == 'omitted':
        actual[1]['Key'] = {'Ref': 'AWS::NoValue'}
    elif case == 'condition-child':
        comparison.stack_inputs['producer'][0]['Conditions'] = {'Active': True}
        actual[0]['Value'] = {'Fn::Select': [3, ['only']]}
        actual = {'Fn::If': ['Active', actual, {'Ref': 'AWS::NoValue'}]}
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build',
        [('Tags[1].Key', 'Known', None), ('Tags[1].Value', 'one', None),
         ('Tags[2].Key', 'Missing', None), ('Tags[2].Value', 'two', None)] +
        ([('Tags[3].Key', 'Third', None), ('Tags[3].Value', 'three', None)] if case == 'missing' else []),
        properties={'Tags': actual})
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert batch.failure is None
    differences = [item for item in batch.records if item['category'] == 'difference']
    assert len(differences) == int(case in {'wrong', 'missing', 'duplicate', 'omitted'}), batch.records
    if case == 'wrong':
        assert [item['path'] for item in next(iter(batch.display_differences.values()))] == ['Tags[Key=Known].Value']
    if case == 'condition-child':
        assert any(item['category'] == 'error' and '/Fn::If/1/0/Value' in item['property'] for item in batch.records)
        assert not any(item['category'] == 'matched' for item in batch.records)


@pytest.mark.parametrize('unordered', [False, True])
@pytest.mark.parametrize('desired,actual,expected', [
    (['a'], ['a', 'unknown'], None),
    (['a', 'a'], ['a', 'unknown'], None),
    (['a', 'a', 'a'], ['a', 'unknown'], False),
    ([], ['a', 'unknown'], False),
    (['b'], ['a', 'unknown'], False),
    (['a', 'b'], ['unknown', 'a', 'b'], None),
])
def test_iac_partial_array_cardinality(unordered, desired, actual, expected):
    comparison = fixture()
    actual = [Expression('Unverified', []) if item == 'unknown' else item for item in actual]
    callback = partial(reference_for, comparison, 'IAM.Role')
    if unordered:
        assert unordered_same(desired, actual, reference=callback) is expected
    else:
        assert same(desired, actual, reference=callback) is expected


def test_iac_partial_error_keeps_reference_diagnostics():
    comparison = fixture()
    vpc(comparison, observed=None)
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build',
        [('VpcConfig.VpcId', '[vpc](vpc.md#vpc)', None), ('VpcConfig.Subnets', '["subnet"]', None)],
        properties={'VpcConfig': {'VpcId': 'vpc-unproven', 'Subnets': {'Fn::Select': [2, ['only']]}}})
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert batch.failure is None
    assert sorted(item['category'] for item in batch.records) == ['error', 'uncompared'], batch.records
    unresolved = next(item for item in batch.records if item['category'] == 'uncompared')
    assert unresolved['reference_diagnostics'] and not batch.display_differences


@pytest.mark.parametrize('different', [False, True])
def test_iac_partial_error_and_unknown_condition(different):
    comparison = fixture()
    resource(comparison, 'codebuild', '001', 'CodeBuild.Project', 'Build',
        [('Environment.Image', 'image', None), ('Environment.PrivilegedMode', 'false', None),
         ('Environment.Type', 'LINUX_CONTAINER', None)], properties={'Environment': {
             'Image': 'wrong' if different else 'image',
             'PrivilegedMode': {'Fn::If': ['Unknown', True, False]},
             'Type': {'Fn::Select': [2, ['only']]}}})
    document = comparison.stack_inputs['producer'][0]
    batch = comparison.compare_rows('codebuild', '001', comparison.resources['codebuild']['001'],
        'producer', 'Build', ROOT / 'synthetic.yaml', document['Resources']['Build'], document)
    assert batch.failure is None
    assert sorted(item['category'] for item in batch.records) == sorted(
        ['error', 'uncompared'] + (['difference'] if different else [])), batch.records
    assert any('Condition' in item['message'] for item in batch.warnings)
    if different:
        assert [item['path'] for item in next(iter(batch.display_differences.values()))] == ['Image']


QUEUE_ARN = 'arn:aws:sqs:ap-northeast-1:123456789012:fixture-dlq'
RULE_ARN = 'arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule'


def sqs_policy_fixture():
    comparison = fixture()
    resource(comparison, 'sqs', '001', 'SQS.Queue', 'Queue', [('QueueName', 'fixture-dlq', None)],
             properties={'QueueName': 'fixture-dlq'})
    resource(comparison, 'eventbridge', '001', 'Events.Rule', 'Rule', [('Name', 'fixture-rule', None)],
             properties={'Name': 'fixture-rule', 'EventBusName': 'default'})
    desired = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
        'Principal': {'Service': 'events.amazonaws.com'}, 'Action': 'sqs:SendMessage',
        'Resource': QUEUE_ARN, 'Condition': {'ArnEquals': {'aws:SourceArn': RULE_ARN}}}]}
    actual = copy.deepcopy(desired)
    actual['Statement'][0]['Resource'] = {'Fn::GetAtt': ['Queue', 'Arn']}
    actual['Statement'][0]['Condition']['ArnEquals']['aws:SourceArn'] = {'Fn::GetAtt': ['Rule', 'Arn']}
    return comparison, desired, actual


def test_sqs_policy_named_arn_match():
    comparison, desired, actual = sqs_policy_fixture()
    before = copy.deepcopy(comparison.models['sqs'].authoritative)
    records = setting(comparison, 'SQS.QueuePolicy', 'PolicyDocument', desired, actual)
    assert [record['category'] for record in records] == ['matched'], records
    assert comparison.models['sqs'].authoritative == before


@pytest.mark.parametrize('change', ['name', 'partition', 'region', 'account', 'source'])
def test_sqs_policy_proven_difference_is_sqs_specific(change):
    comparison, desired, actual = sqs_policy_fixture()
    statement = desired['Statement'][0]
    if change == 'name':
        comparison.stack_inputs['producer'][0]['Resources']['Queue']['Properties']['QueueName'] = 'other-dlq'
    elif change == 'source':
        statement['Condition']['ArnEquals']['aws:SourceArn'] = RULE_ARN + '-other'
    else:
        old, new = {'partition': ('aws:', 'aws-cn:'), 'region': ('ap-northeast-1', 'us-east-1'),
                    'account': ('123456789012', '999999999999')}[change]
        statement['Resource'] = QUEUE_ARN.replace(old, new)
    records = setting(comparison, 'SQS.QueuePolicy', 'PolicyDocument', desired, actual)
    assert [record['category'] for record in records] == ['difference'], records
    diagnostics = records[0]['reference_diagnostics']
    queue = next(item for item in diagnostics if item['path'].endswith('.Resource'))
    rule = next(item for item in diagnostics if item['path'].endswith('aws:SourceArn'))
    assert queue['producers'] == [{'producer': 'sqs/001', 'attribute': 'Arn'}]
    assert queue['local_comparison'] == ('matched' if change == 'source' else 'difference')
    assert rule['local_comparison'] == ('difference' if change == 'source' else 'matched')
    assert queue['identity'] == 'unproven' and queue['format']['model'] == 'unproven'
    assert queue['evidence_type'] == 'local_evaluation' and queue['current_aws_verified'] is False
    assert '123456789012' not in json.dumps(records) and 'arn:aws:' not in json.dumps(records)


@pytest.mark.parametrize('name', [None, '', 'UNSET', 'PENDING_DEPLOY', 'TODO', 'invalid/path', 'invalid.name', 'wildcard-*', 'x' * 81,
                                  'x' * 76 + '.fifo', {'Ref': 'Missing'}, {'Fn::If': ['Unknown', 'one', 'two']}])
def test_sqs_unproven_names(name):
    comparison, desired, actual = sqs_policy_fixture()
    properties = comparison.stack_inputs['producer'][0]['Resources']['Queue']['Properties']
    if name is None:
        properties.clear()
    else:
        properties['QueueName'] = name
    records = setting(comparison, 'SQS.QueuePolicy', 'PolicyDocument', desired, actual)
    assert [record['category'] for record in records] == ['uncompared'], records
    queue = next(item for item in records[0]['reference_diagnostics'] if item['path'].endswith('.Resource'))
    assert queue['local_comparison'] == 'uncompared'


@pytest.mark.parametrize('name', ['a', 'x' * 80, 'x' * 75 + '.fifo'])
def test_sqs_explicit_name_boundaries(name):
    comparison, desired, actual = sqs_policy_fixture()
    comparison.stack_inputs['producer'][0]['Resources']['Queue']['Properties']['QueueName'] = name
    desired['Statement'][0]['Resource'] = QUEUE_ARN.rsplit(':', 1)[0] + ':' + name
    assert [item['category'] for item in setting(comparison, 'SQS.QueuePolicy', 'PolicyDocument', desired, actual)] == ['matched']


@pytest.mark.parametrize('field', ['Partition', 'Region', 'AccountId'])
@pytest.mark.parametrize('value', [None, '', 'UNSET', '${Unresolved}', 123, 'invalid:context'])
def test_sqs_arn_context_requires_proof(field, value):
    comparison, desired, actual = sqs_policy_fixture()
    pseudo = comparison.stack_inputs['producer'][2]
    if value is None:
        pseudo.pop('AWS::' + field)
    else:
        pseudo['AWS::' + field] = value
    reference = comparison.evaluate('producer', {'Fn::GetAtt': ['Queue', 'Arn']})
    decision = comparison.reference_decision(QUEUE_ARN, reference, 'SQS.QueuePolicy', 'PolicyDocument.Statement[].Resource')
    assert decision.equal is None and decision.diagnostics[0]['local_comparison'] == 'uncompared'
    assert field in decision.diagnostics[0]['reason']
    records = setting(comparison, 'SQS.QueuePolicy', 'PolicyDocument', desired, actual)
    assert [item['category'] for item in records] == ['uncompared'], records


@pytest.mark.parametrize('kind,field,name,logical', [
    ('Events.Rule', 'Name', 'fixture-rule', 'Rule'), ('CodeBuild.Project', 'Name', 'fixture-project', 'Build'),
    ('Logs.LogGroup', 'LogGroupName', 'fixture-log', 'Log')])
@pytest.mark.parametrize('context', ['Partition', 'Region', 'AccountId'])
def test_existing_named_arn_context_guards(kind, field, name, logical, context):
    comparison = fixture()
    resource(comparison, 'producer', '001', kind, logical, [], properties={field: name})
    reference = comparison.evaluate('producer', {'Fn::GetAtt': [logical, 'Arn']})
    assert comparison.reference_literal(reference).startswith('arn:aws:')
    comparison.stack_inputs['producer'][2].pop('AWS::' + context)
    with pytest.raises(Blocked, match=context):
        comparison.reference_literal(reference)


@pytest.mark.parametrize('fault', ['type', 'stack', 'logical', 'duplicate', 'missing', 'condition', 'inactive', 'transform', 'import'])
def test_sqs_arn_correspondence_and_mode_guards(fault):
    comparison, desired, actual = sqs_policy_fixture()
    queue = comparison.stack_inputs['producer'][0]['Resources']['Queue']
    model = comparison.resources['sqs']['001']
    if fault == 'type':
        queue['Type'] = 'AWS::SNS::Topic'
    elif fault in {'stack', 'logical'}:
        model['cfn-logicalId'] = 'other-Queue' if fault == 'stack' else 'producer-Other'
    elif fault == 'duplicate':
        resource(comparison, 'sqs', '002', 'SQS.Queue', 'Queue', [], properties={'QueueName': 'fixture-dlq'})
    elif fault == 'missing':
        comparison.resources['sqs'].clear()
        comparison.models.pop('sqs')
    elif fault in {'condition', 'inactive'}:
        queue['Condition'] = 'Unknown'
        if fault == 'inactive':
            comparison.stack_inputs['producer'][0]['Conditions'] = {'Unknown': False}
    elif fault == 'transform':
        comparison.stack_inputs['producer'][0]['Transform'] = 'Unknown'
    else:
        model['resourceMode'] = 'IMPORT'
    records = setting(comparison, 'SQS.QueuePolicy', 'PolicyDocument', desired, actual)
    assert [item['category'] for item in records] == ['uncompared'], records


def test_sqs_queue_url_is_not_getatt_arn():
    comparison, _, _ = sqs_policy_fixture()
    ref = comparison.evaluate('producer', {'Ref': 'Queue'})
    arn = comparison.evaluate('producer', {'Fn::GetAtt': ['Queue', 'Arn']})
    assert ref['$attribute'] == 'QueueUrl' and arn['$attribute'] == 'Arn'
    assert comparison.reference_decision(QUEUE_ARN, ref, 'SQS.QueuePolicy', 'PolicyDocument.Statement[].Resource').equal is None
    assert comparison.reference_decision(QUEUE_ARN, arn, 'SQS.QueuePolicy', 'Queues[]').equal is False
    with pytest.raises(Blocked):
        comparison.reference_literal(ref)
    comparison.resources['sqs']['001']['resourceMode'] = 'IMPORT'
    assert comparison.reference_decision(QUEUE_ARN, arn, 'SQS.QueuePolicy', 'PolicyDocument.Statement[].Resource').equal is None


@pytest.mark.parametrize('error', [OSError, ValueError, TypeError])
def test_sqs_reference_processing_errors_propagate(error):
    comparison, desired, actual = sqs_policy_fixture()
    reference = comparison.evaluate('producer', {'Fn::GetAtt': ['Queue', 'Arn']})
    with patch('comparison.registry.named_arn', side_effect=error('synthetic reference evaluation failure')):
        with pytest.raises(error, match='synthetic reference evaluation failure'):
            comparison.reference_decision(QUEUE_ARN, reference, 'SQS.QueuePolicy', 'PolicyDocument.Statement[].Resource')
        resource(comparison, 'consumer', '090', 'SQS.QueuePolicy', 'Receiver', [('PolicyDocument', json.dumps(desired), None)],
                 properties={'PolicyDocument': actual})
        document = comparison.stack_inputs['producer'][0]
        batch = comparison.compare_rows('consumer', '090', comparison.resources['consumer']['090'], 'producer', 'Receiver',
            ROOT / 'synthetic.yaml', document['Resources']['Receiver'], document)
        assert isinstance(batch.failure, error) and not batch.records


@pytest.mark.parametrize('declared', [False, True])
@pytest.mark.parametrize('error', [OSError, ValueError, TypeError])
def test_recorded_reference_processing_errors_are_not_missing_proof(declared, error):
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    if declared:
        declaration(comparison, 'desired.row.010-001.value', VPC)
        desired = prepared(comparison, row).require_value()
        actual = VPC
    else:
        desired = VPC
        actual = comparison.evaluate('producer', {'Ref': 'Vpc'})
    with patch('comparison.reference_evidence.catalog_outputs', side_effect=error('synthetic catalog read failure')):
        with pytest.raises(error, match='synthetic catalog read failure'):
            comparison.reference_decision(desired, actual, 'EC2.Subnet', 'VpcId')


@pytest.mark.parametrize('operation', ['Arn', 'Sub', 'Join', 'SplitSelect'])
def test_replacement_and_old_observed_cannot_prove_physical_identity(operation):
    comparison = fixture()
    resource(comparison, 'vpc', '001', 'EC2.VPC', 'Vpc', [
        ('CidrBlock', '10.0.0.0/16', None), ('VpcId', 'PENDING_DEPLOY', VPC)],
        properties={'CidrBlock': '10.99.0.0/16'})
    arn = 'arn:aws:ec2:ap-northeast-1:123456789012:vpc/' + VPC
    symbol = ResourceReference({'$resource': ['vpc', '001'], '$attribute': 'Arn'})
    value = {'Arn': symbol, 'Sub': Expression('Sub', ['${R}', {'R': symbol}]),
             'Join': Expression('Join', ['', [symbol]]),
             'SplitSelect': Expression('Select', [0, Expression('Split', ['|', symbol])])}[operation]
    for left, right in [(value, arn), (arn, value)]:
        decision = comparison.reference_decision(left, right, 'IAM.Role', 'Policies')
        assert decision.equal is None and not decision.equivalent
        assert decision.diagnostics[0]['evidence_type'] == 'recorded_observed'
        assert 'cannot prove' in decision.diagnostics[0]['reason']
    assert comparison.reference_decision(value, copy.deepcopy(value), 'IAM.Role', 'Policies').equal is True
    other = ResourceReference({'$resource': ['vpc', '001'], '$attribute': 'VpcId'})
    assert comparison.reference_decision(symbol, other, 'IAM.Role', 'Policies').equal is not True
    vpc(comparison, '002', 'OtherVpc')
    different = ResourceReference({'$resource': ['vpc', '002'], '$attribute': 'Arn'})
    assert comparison.reference_decision(symbol, different, 'IAM.Role', 'Policies').equal is False


@pytest.mark.parametrize('bus,tail', [(None, ''), ('default', ''), ('custom', 'custom/'),
    ('arn:aws:events:ap-northeast-1:123456789012:event-bus/default', ''),
    ('arn:aws:events:ap-northeast-1:123456789012:event-bus/custom', 'custom/'),
    ({'Ref': 'Bus'}, 'custom/'), ({'Fn::GetAtt': ['Bus', 'Arn']}, 'custom/'),
    ({'Fn::Sub': '${Bus.Arn}'}, 'custom/')])
def test_eventbridge_bus_name_arn_and_proven_reference(bus, tail):
    comparison = fixture()
    resource(comparison, 'events', '001', 'Events.EventBus', 'Bus', [], properties={'Name': 'custom'})
    properties = {'Name': 'fixture-rule'}
    if bus is not None:
        properties['EventBusName'] = bus
    resource(comparison, 'events', '002', 'Events.Rule', 'Rule', [], properties=properties)
    symbol = comparison.evaluate('producer', {'Fn::GetAtt': ['Rule', 'Arn']})
    arn = 'arn:aws:events:ap-northeast-1:123456789012:rule/' + tail + 'fixture-rule'
    assert comparison.reference_literal(symbol) == arn
    for left, right in [(arn, symbol), (symbol, arn)]:
        assert comparison.reference_decision(left, right, 'IAM.Role', 'Policies').equal is True


@pytest.mark.parametrize('bus', [
    'arn:aws:events:ap-northeast-1:999999999999:event-bus/custom',
    'arn:aws:events:us-east-1:123456789012:event-bus/custom',
    'arn:aws-cn:events:ap-northeast-1:123456789012:event-bus/custom',
    'arn:aws:events:ap-northeast-1:123456789012:rule/custom',
    'arn:aws:sns:ap-northeast-1:123456789012:event-bus/custom',
    'arn:aws:events:ap-northeast-1:123:event-bus/custom',
    'arn:aws:events:ap-northeast-1:123456789012:event-bus/',
    'arn:aws:events:ap-northeast-1:123456789012:event-bus/custom/suffix',
    'arn:aws:events:ap-northeast-1:123456789012:event-bus/*',
    '', 'UNSET', {'Ref': 'Missing'}, {'Fn::GetAtt': ['Bus', 'Arn']}, {'Fn::GetAtt': ['Rule', 'Arn']}])
def test_eventbridge_unproven_or_conflicting_bus_is_uncompared(bus):
    comparison = fixture()
    resource(comparison, 'events', '001', 'Events.EventBus', 'Bus', [], properties={})
    resource(comparison, 'events', '002', 'Events.Rule', 'Rule', [],
             properties={'Name': 'fixture-rule', 'EventBusName': bus})
    symbol = comparison.evaluate('producer', {'Fn::GetAtt': ['Rule', 'Arn']})
    for left, right in [(symbol, 'arn:aws:events:ap-northeast-1:123456789012:rule/custom/fixture-rule'),
                        ('arn:aws:events:ap-northeast-1:123456789012:rule/custom/fixture-rule', symbol)]:
        decision = comparison.reference_decision(left, right, 'IAM.Role', 'Policies')
        assert decision.equal is None and not decision.equivalent


@pytest.mark.parametrize('transform', ['same', 'suffix', 'select', 'delimiter'])
def test_route53_composite_export_uses_shared_nested_setting_comparison(transform):
    comparison = fixture()
    resource(comparison, 'endpoint', '001', 'EC2.VPCEndpoint', 'Endpoint', [], stack='consumer',
             properties={'VpcEndpointType': 'Interface'})
    expression = {'Fn::Select': [0, {'Fn::Split': [':', {'Fn::Select': [0,
        {'Fn::GetAtt': ['Endpoint', 'DnsEntries']}]}]}]}
    comparison.stack_inputs['consumer'][0]['Outputs']['Dns'] = {'Value': expression, 'Export': {'Name': 'EndpointDns'}}
    imported = {'Fn::ImportValue': 'EndpointDns'}
    desired = {'DNSName': imported, 'HostedZoneId': 'Z123'}
    actual = copy.deepcopy(desired)
    if transform == 'suffix':
        actual['DNSName'] = {'Fn::Join': ['', [imported, '.other']]}
    elif transform in {'select', 'delimiter'}:
        desired['DNSName'] = {'Fn::Select': [0, {'Fn::Split': ['|', imported]}]}
        actual['DNSName'] = {'Fn::Select': [1 if transform == 'select' else 0,
            {'Fn::Split': ['|' if transform == 'select' else ',', imported]}]}
    results = setting(comparison, 'Route53.RecordSet', 'AliasTarget', desired, actual)
    assert [item['category'] for item in results] == ['matched' if transform == 'same' else 'uncompared'], results
    details = results[0].get('reference_diagnostics', [])
    if transform != 'select':
        assert details and details[0]['exports'][0]['unproven'].startswith('Select bounds are unproven')
