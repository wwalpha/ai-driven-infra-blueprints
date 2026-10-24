"""Offline ARN projection from the identifiers actually saved by the catalogs."""

import copy
import json
import os
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from design.catalog import DesignSchemaCatalog
from design.policy_tables import Policy, validate_policy_document
from generation_inputs import GenerationInputs
from json_intrinsics import project_document
from model.format import serialize
from model.identity import COUNTERS
from model.operations import prepare_edit, publish_edit, validate_candidates
from model.projection import execution_document, json_sha256, reference_display
from model.render import generate_files
from model.sources import Scope, SourceWriteContext, load_model, runtime_values
from model.validation import validate_json_settings
from sync_runtime import generate_views
from utils.aws_mappings import mapping_alias
from utils.cloudformation.format import decode_file as decode
from utils.cloudformation.inputs import resolve_value
from utils.json_format import document_sha256, validate_aws_document

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

FRAMEWORK = Path(__file__).resolve().parents[4]
KEY = '12345678-1234-1234-1234-123456789abc'
BUCKET = 'confirmed-bucket.example'


def fixture(root, region='ap-northeast-1', execution='222222222222'):
    producer = {'environment': 'prod', 'alias': 'producer', 'awsAccountId': '111111111111',
                'awsRegion': region, 'iacEngine': 'cloudformation'}
    if execution is not None:
        producer['awsExecutionAccountId'] = execution
    project = {'targets': [producer, {'environment': 'dev', 'alias': 'consumer',
        'awsAccountId': '333333333333', 'awsRegion': 'us-west-2', 'iacEngine': 'cloudformation'}]}
    (root / 'project.json').write_text(json.dumps(project), encoding='utf-8')
    document = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
        'Action': ['kms:Decrypt', 's3:ListBucket'], 'Resource': '*'}]}
    scope = Scope(root, 'dev', 'consumer', 'iam')
    policy = {COUNTERS: '{"IAM.ManagedPolicy":1}',
        'desired.service.iam.serviceId': 'iam',
        'desired.service.iam.ownedCatalogResourceTypes': 'IAM.ManagedPolicy',
        'display.service.title': '# 合成ポリシー',
        'desired.resource.009.resourceType': 'IAM.ManagedPolicy',
        'desired.resource.009.logicalId': 'IAM_ManagedPolicy_001',
        'desired.resource.009.resourceMode': 'IMPORT',
        'desired.resource.009.anchor': 'saved-policy',
        'display.resource.009.comment': '合成',
        'desired.row.009-001.property': 'IAM.ManagedPolicy.ManagedPolicyName',
        'desired.row.009-001.value': '`confirmed-policy`',
        'desired.row.009-001.comment': '合成',
        'desired.row.009-002.property': 'IAM.ManagedPolicy.PolicyDocument',
        'desired.row.009-002.value': '[Policy](iam/policy.json)',
        'desired.row.009-002.comment': '合成JSON参照',
        'desired.row.009-002.document': json.dumps(document)}
    save(scope, policy)
    return scope, policy, document


def save(scope, values):
    scope.path.parent.mkdir(parents=True, exist_ok=True)
    scope.path.write_text(serialize(values), encoding='utf-8')





















@pytest.mark.parametrize('expression', [
    {'Fn::Sub': 'arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/stg-vpc-01/*'},
    {'Fn::ImportValue': 'UnknownExport'}, {'Fn::GetAtt': ['Unknown', 'Arn']},
    {'Fn::Join': ['', ['arn:', {'Ref': 'Unknown'}]]}, {'Ref': 'AWS::Region'},
    {'Fn::If': ['Condition', '*', 'arn:unknown']}, {'Fn::Select': [0, ['*']]},
    {'Fn::Unknown': 'future'}, '${AWS::Region}', '${AWS::AccountId}',
    '{{resolve:ssm:unacquired}}', '{"Fn::Sub":"${AWS::Region}"}',
    '{"Fn::ImportValue":"UnknownExport"}', '{"Fn::GetAtt":["Unknown","Arn"]}',
    'Fn::Sub: literal-looking-expression',
])
def check_standalone_expressions(tmp_path, expression):
    scope, policy, _ = fixture(tmp_path)
    document = {'Statement': [{'Effect': 'Allow', 'Action': '*', 'Resource': [expression]}]}
    key = 'desired.row.009-002.document'
    policy[key] = json.dumps(document)
    original = copy.deepcopy(document)
    warnings = []
    pending = isinstance(expression, dict) and 'Fn::Select' not in expression or isinstance(expression, str) and expression.startswith('{"')
    if pending or isinstance(expression, dict):
        projected = execution_document(document, tmp_path, scope=scope, logical_id='IAM_ManagedPolicy_001',
            property_name='IAM.ManagedPolicy.PolicyDocument', warnings=warnings)
        expected = copy.deepcopy(document)
        if expression == {'Fn::Select': [0, ['*']]}:
            expected['Statement'][0]['Resource'] = ['*']
        assert projected == expected
        assert bool(warnings) == bool(pending)
        for warning in warnings:
            assert warning['severity'] == 'WARNING'
            assert warning['property'] == 'IAM.ManagedPolicy.PolicyDocument'
            assert warning['pointer'].startswith('/Statement/0/Resource/0')
            assert warning['function'] in warning['message']
            assert 'unresolved/unverified' in warning['message']
        assert reference_display(runtime_values(policy), scope.path, tmp_path)[key] == json.dumps(expected, ensure_ascii=False)
        validate_json_settings(policy, scope.path)
    else:
        with pytest.raises(ValueError):
            execution_document(document, tmp_path, scope=scope)
    escaped = []
    if pending:
        project_document({'a/b~': [expression]}, warnings=escaped)
        assert escaped[0]['pointer'] == '/a~1b~0/0'
    artifact = tmp_path / 'policy.json'
    artifact.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError, match='CloudFormation'):
        json_sha256(artifact)
    with pytest.raises(ValueError, match='/a~1b~0/0'):
        validate_aws_document({'a/b~': [expression]})
    assert document == original


def check_standalone_generation(tmp_path):
    root, stage = tmp_path / 'root', tmp_path / 'stage'
    root.mkdir()
    stage.mkdir()
    scope, policy, _ = fixture(root)
    good = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
        'Action': ['s3:GetObject'], 'Resource': ['arn:aws:s3:::bucket/${aws:username}'],
        'Condition': {'StringEquals': {'s3:prefix': '${aws:PrincipalTag/team}'}}}]}
    policy['desired.row.009-002.document'] = json.dumps(good)
    design = root / 'docs/designs/dev/consumer/iam.md'
    artifact = design.with_suffix('') / 'policy.json'
    with mapping_alias(FRAMEWORK, root):
        files = generate_files(design, runtime_values(policy), root)
        displayed = reference_display(runtime_values(policy), scope.path, root)
        assert json.loads(files[artifact]) == good
        assert displayed['desired.row.009-002.artifactSha256'] == document_sha256(good)
        assert '${aws:username}' in files[design]
        # A valid first artifact must not be saved when a later document is rejected.
        for key, value in list(policy.items()):
            if key.startswith(('desired.resource.009.', 'display.resource.009.', 'desired.row.009-')):
                policy[key.replace('.009', '.010', 1)] = value
        policy[COUNTERS] = '{"IAM.ManagedPolicy":2}'
        policy['desired.resource.010.logicalId'] = 'IAM_ManagedPolicy_002'
        policy['desired.resource.010.anchor'] = 'second-policy'
        policy['desired.row.010-001.value'] = '`second-policy`'
        policy['desired.row.010-002.value'] = '[Policy](iam/second.json)'
        policy['desired.row.010-002.document'] = json.dumps({'Statement': [
            {'Effect': 'Allow', 'Action': '*', 'Resource': [{'Fn::GetAtt': ['Invalid']}]}]})
        save(scope, policy)
        artifact.parent.mkdir(parents=True)
        artifact.write_text('existing artifact\n', encoding='utf-8')
        design.write_text('existing design\n', encoding='utf-8')
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        with pytest.raises(ValueError, match='Fn::GetAtt'):
            generate_files(design, runtime_values(policy), root)
        failures = []
        generated = generate_views(stage, root, {design: runtime_values(policy)}, failures,
                                   definitions_root=FRAMEWORK)
        assert not generated and any('Fn::GetAtt' in error for error in failures), failures
        assert (stage / artifact.relative_to(root)).read_bytes() == before[artifact]
        assert not (stage / artifact.with_name('second.json').relative_to(root)).exists()
        assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file()} == before


def check_standalone_and_cfn_boundaries(tmp_path):
    document = {'Nested': [{'Enabled': True, 'Count': 2, 'Nothing': None}],
                'PolicyVariable': '${aws:username}', 'Url': 'https://example.com',
                'EncodedSettings': '{"rules":[{"name":"keep"}]}'}
    assert execution_document(document, tmp_path) == document
    template_path = tmp_path / 'template.yaml'
    template_path.write_text('Value: !Sub "${AWS::Region}-${Name}"\nImport: !ImportValue Export\nAttr: !GetAtt Resource.Arn\n', encoding='utf-8')
    template, errors = decode(str(template_path))
    assert not errors
    original = copy.deepcopy(template)
    assert resolve_value(template['Value'], {'Name': 'confirmed'}, {'AWS::Region': 'ap-northeast-1'}) == 'ap-northeast-1-confirmed'
    assert resolve_value(template['Import'], {}, {}, exports={'Export': 'confirmed-export'}) == 'confirmed-export'
    warnings = []
    assert execution_document(template, tmp_path, warnings=warnings) == template
    assert {warning['function'] for warning in warnings} == {'Fn::Sub', 'Fn::ImportValue', 'Fn::GetAtt'}
    assert template == original


@pytest.mark.parametrize('expression', [
    {'Fn::Sub': '${Missing}'}, {'Fn::GetAtt': ['Missing', 'Arn']},
    {'Fn::ImportValue': 'External'}, {'Ref': 'Missing'},
    {'Fn::Join': ['', ['prefix', {'Fn::GetAtt': ['Missing', 'Arn']}]]},
    {'Fn::If': ['Pending', {'Ref': 'Missing'}, 'literal']},
    {'Fn::Split': [',', {'Ref': 'Missing'}]}, {'Fn::FindInMap': ['Map', 'Key', 'Value']},
    {'Fn::GetAZs': ''}, {'Fn::Base64': 'literal'}, {'Fn::Cidr': ['10.0.0.0/16', 2, 8]},
    {'Fn::ToJsonString': {'Key': {'Ref': 'Missing'}}}, {'Fn::Length': [1, 2]},
    {'Fn::Transform': {'Name': 'Macro', 'Parameters': {}}},
    {'Fn::UnknownFuture': {'Ref': 'Missing'}}, {'Fn::And': [True, {'Ref': 'Missing'}]},
    {'Fn::ForEach::Loop': ['Item', ['a'], {'Key': {'Ref': 'Item'}}], 'Other': 'retained'},
])
def check_pending_intrinsic_generation(tmp_path, expression):

    root, stage = tmp_path / 'root', tmp_path / 'stage'
    root.mkdir()
    stage.mkdir()
    scope, policy, _ = fixture(root)
    key = 'desired.row.009-002.document'
    policy[key] = json.dumps({'Statement': [{'Effect': 'Allow', 'Action': '*', 'Resource': [expression]}]})
    design = root / 'docs/designs/dev/consumer/iam.md'
    with patch('socket.socket', side_effect=AssertionError('network forbidden')), mapping_alias(FRAMEWORK, root), patch.dict(os.environ):
        os.environ.pop('BLUEPRINT_TASK_FILE', None)
        reads = GenerationInputs(root)
        context = SourceWriteContext._authorized(root, reads, SimpleNamespace(action='edit'),
            lambda changes: None, frozenset({scope.path}))
        plan = prepare_edit(load_model(scope.path, reads), {scope.path: serialize(policy)}, context)
        assert any(w['code'] == 'json.intrinsic.unresolved' for w in plan.candidate.warnings)
        with patch('import_guard.require_import_changes') as task_guard:
            publish_edit(plan, context)
            task_guard.assert_called_once()
        assert load_model(scope.path).authoritative[key] == policy[key]
        before = scope.path.read_bytes()
        warnings = validate_candidates(root, {scope.path.relative_to(root)}, {}, {('dev', 'consumer', 'iam')})
        assert any(w['code'] == 'json.intrinsic.unresolved' for w in warnings)
        warnings = []
        files = generate_files(design, runtime_values(policy), root, warnings=warnings)
        assert json.loads(files[design.with_suffix('') / 'policy.json']) == json.loads(policy[key])
        assert warnings and all(w['severity'] == 'WARNING' for w in warnings)
        failures, warnings, unavailable = [], [], {}
        assert generate_views(stage, root, {design: runtime_values(policy)}, failures,
            definitions_root=FRAMEWORK, warnings=warnings, unavailable=unavailable)
        assert not failures and not unavailable, (failures, unavailable)
        assert any(w['code'] == 'json.intrinsic.unresolved' for w in warnings)
        assert scope.path.read_bytes() == before
        with pytest.raises(ValueError, match='CloudFormation'):
            validate_aws_document(json.loads((stage / design.relative_to(root)).with_suffix('').joinpath('policy.json').read_text()))


@pytest.mark.parametrize('expression', [
    {'Ref': 1}, {'Fn::GetAtt': ['OnlyOne']}, {'Fn::Sub': [1, {}]},
    {'Fn::Join': ['']}, {'Fn::Split': ['', 'value']}, {'Fn::Select': [-1, ['x']]},
    {'Fn::If': ['C', 'yes']}, {'Ref': 'X', 'Extra': True},
    {'Fn::Join': ['', [{'Fn::GetAtt': [1, 'Arn']}]]},
])
def check_invalid_intrinsic_structure(tmp_path, expression):
    scope, policy, _ = fixture(tmp_path)
    key = 'desired.row.009-002.document'
    policy[key] = json.dumps({'a/b~': [expression]})
    with pytest.raises(ValueError, match='JSON Pointer'):
        validate_json_settings(policy, scope.path)
    with pytest.raises(ValueError, match='JSON Pointer'):
        execution_document(json.loads(policy[key]), tmp_path)
    policy[key] = '{"invalid":'
    with pytest.raises(ValueError):
        validate_json_settings(policy, scope.path)


def check_api_json_intrinsics():
    catalog = DesignSchemaCatalog(FRAMEWORK)
    for document in ({'Ref': 'Missing'}, {'bucketDefinitions': {'Ref': 'Missing'}},
                     {'bucketDefinitions': [{'accountId': '111111111111', 'buckets': {'Ref': 'Missing'}}]}):
        assert not catalog.literal_errors('Macie.ClassificationJob', 's3JobDefinition', json.dumps(document))
    assert catalog.literal_errors('Macie.ClassificationJob', 's3JobDefinition',
        json.dumps({'bucketDefinitions': [{'accountId': 'invalid', 'buckets': {'Ref': 'Missing'}}]}))
    with pytest.raises(ValueError):
        catalog.literal_errors('Macie.ClassificationJob', 's3JobDefinition', '{"Ref":1}')


@pytest.mark.parametrize('tag', ['JobName', 'RoleName'])
def check_escaped_policy_sub_variables(tmp_path, tag):
    scope, policy, _ = fixture(tmp_path)
    text = '${BucketArn}/temp/${!aws:PrincipalTag/' + tag + '}/*'
    expression = {'Fn::Sub': [text, {'BucketArn': {
        'Fn::ImportValue': {'Fn::Sub': 'InternalProcessingBucketArn${Suffix}'}}}]}
    document = {'Version': '2012-10-17', 'Statement': [{
        'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': expression}]}
    policy['desired.row.009-002.document'] = json.dumps(document)
    validate_json_settings(policy, scope.path)
    warnings = []
    assert project_document(document, warnings=warnings) == document
    assert warnings and all(w['code'] == 'json.intrinsic.unresolved' for w in warnings)
    projected = project_document(document, evaluate=partial(resolve_value,
        parameters={'Suffix': 'Fixture'}, pseudo={},
        exports={'InternalProcessingBucketArnFixture': 'arn:aws:s3:::fixture-bucket'}))
    assert projected['Statement'][0]['Resource'] == (
        'arn:aws:s3:::fixture-bucket/temp/${aws:PrincipalTag/' + tag + '}/*')


def check_pending_policy_siblings(tmp_path):
    document = {'Statement': [{'Sid': {'Fn::Sub': '${Missing}'}, 'Effect': 'Allow',
        'Action': '*', 'Resource': [{'Ref': 'Missing'}, '*']}]}
    policy = Policy('test', 'test.json', 'test', 'policy', 'IAM.Role.Policies[].PolicyDocument')
    validate_policy_document(document, policy, design=True)
    for key, value in [('Effect', 'Invalid'), ('Resource', [{'Ref': 'Missing'}, 42]), ('Sid', 'x' * 17)]:
        invalid = copy.deepcopy(document)
        invalid['Statement'][0][key] = value
        with pytest.raises(ValueError):
            validate_policy_document(invalid, policy, design=True)
    with pytest.raises(ValueError):
        validate_policy_document(document, policy)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__, message='JSON Resource ARN projections: PASS'))
