"""Offline reference proof through the shared evaluator and comparison pipeline."""
import copy
import json
import sys
from functools import partial
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from cloudformation_inputs import Blocked
from comparison import Comparison
from comparison.reference_evidence import Evidence
from comparison.values import compare_values
from comparison_rows import put_row
from design_catalog import DesignSchemaCatalog
from iac_values import Expression, ResourceReference
from model.references import declarations
from model.sources import ModelSnapshot, Scope
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
    assert decision.equal is True
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
    assert comparison.reference_decision(first, VPC, 'EC2.Subnet', 'VpcId').equal is True
    assert comparison.reference_decision(first, 'vpc-different', 'EC2.Subnet', 'VpcId').equal is False


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
    assert comparison.reference_decision(fixed, actual, 'IAM.Role', '').equal is True
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
    assert decision.equal is True, decision
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
    actual = exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    decision = comparison.reference_decision(KEY_ARN, actual, 'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is None, decision
    assert decision.diagnostics[0]['current_aws_verified'] is False
    if value in {'aws-cn', 'us-east-1', '999999999999'}:
        assert decision.diagnostics[0]['reason'] == 'recorded_identifier_mismatch'
        assert comparison.reference_decision(KEY_ARN.replace(
            {'AWS::Partition': 'aws', 'AWS::Region': 'ap-northeast-1', 'AWS::AccountId': '123456789012'}[field],
            value, 1), actual, 'Athena.WorkGroup', ATHENA_KMS).equal is True


def test_kms_conflicting_recorded_identifier_is_uncompared():
    comparison = fixture()
    resource(comparison, 'kms', '001', 'KMS.Key', 'Key', [('KeyId', 'PENDING_DEPLOY', KEY_ID)])
    actual = exported(comparison, {'Fn::GetAtt': ['Key', 'Arn']})
    decision = comparison.reference_decision(KEY_ARN.replace(KEY_ID, 'mrk-' + 'b' * 32), actual,
                                             'Athena.WorkGroup', ATHENA_KMS)
    assert decision.equal is None and decision.diagnostics[0]['reason'] == 'recorded_identifier_mismatch'


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
def test_kms_runner_reports_matched_with_recorded_proof(kind, path):
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
    assert [item['category'] for item in results] == ['matched'], results
    assert results[0]['reference_diagnostics'][0]['evidence_type'] == 'recorded_observed'


def test_export_chain_retains_each_handoff():
    comparison = fixture()
    vpc(comparison)
    exported(comparison, {'Ref': 'Vpc'}, name='base')
    comparison.stack_inputs['relay'] = ({'Resources': {}, 'Outputs': {
        'Relay': {'Value': {'Fn::ImportValue': 'base'}, 'Export': {'Name': 'shared'}}}}, {}, {})
    comparison.exports = None
    actual = comparison.evaluate('consumer', {'Fn::ImportValue': 'shared'})
    decision = comparison.reference_decision(VPC, actual, 'EC2.Subnet', 'VpcId')
    assert decision.equal is True
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
    assert results[0]['reference_diagnostics'][0]['evidence_type'] == 'recorded_observed'
    assert {service: model.authoritative for service, model in comparison.models.items()} == before


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
