"""Offline ARN projection from the identifiers actually saved by the catalogs."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import pytest
from model.core import ReferenceResolutionError
from model.format import serialize
from model.identity import COUNTERS, Resolver
from model.projection import execution_document, reference_display
from model.sources import Scope, load_model, runtime_values
from utils.json_format import document_sha256

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
    models = {}
    for service, kind, attribute, identifier, anchor in [
            ('kms', 'KMS.Key', 'KeyId', KEY, 'saved-key'),
            ('s3', 'S3.Bucket', 'BucketName', BUCKET, 'saved-bucket')]:
        values = {COUNTERS: json.dumps({kind: 1}),
            f'desired.service.{service}.serviceId': service,
            f'desired.service.{service}.ownedCatalogResourceTypes': kind,
            'desired.resource.001.resourceType': kind,
            'desired.resource.001.logicalId': kind.replace('.', '_') + '_001',
            'desired.resource.001.resourceMode': 'IMPORT',
            'desired.resource.001.anchor': anchor,
            'desired.row.001-001.property': kind + '.' + attribute,
            'desired.row.001-001.value': '`' + identifier + '`',
            'desired.row.001-001.comment': '確定済み合成識別子'}
        save(Scope(root, 'prod', 'producer', service), values)
        models[service] = values
    document = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
        'Action': ['kms:Decrypt', 's3:ListBucket'],
        'Resource': [operand('kms'), operand('s3'), operand('kms')]}]}
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
    return scope, models, policy, document


def save(scope, values):
    scope.path.parent.mkdir(parents=True, exist_ok=True)
    scope.path.write_text(serialize(values), encoding='utf-8')


def operand(service, attribute='Arn'):
    anchor = 'saved-key' if service == 'kms' else 'saved-bucket'
    return {'$resource': f'[saved](../../prod/producer/{service}.md#{anchor})', '$attribute': attribute}


@pytest.mark.parametrize('region,partition', [
    ('ap-northeast-1', 'aws'), ('us-gov-west-1', 'aws-us-gov'), ('cn-north-1', 'aws-cn')])
@pytest.mark.parametrize('key', [KEY, 'mrk-' + 'a1' * 16])
@pytest.mark.parametrize('execution,account', [('222222222222', '222222222222'), (None, '111111111111')])
def check_confirmed_identifiers(tmp_path, region, partition, key, execution, account):
    scope, models, policy, document = fixture(tmp_path, region, execution)
    models['kms']['desired.row.001-001.value'] = '`' + key + '`'
    save(Scope(tmp_path, 'prod', 'producer', 'kms'), models['kms'])
    originals = {p: p.read_bytes() for p in tmp_path.rglob('*.properties')}
    original_policy = copy.deepcopy(policy)
    expected = copy.deepcopy(document)
    expected['Statement'][0]['Resource'] = [f'arn:{partition}:kms:{region}:{account}:key/{key}',
                                           f'arn:{partition}:s3:::{BUCKET}',
                                           f'arn:{partition}:kms:{region}:{account}:key/{key}']
    resolver = Resolver(tmp_path)
    with patch('botocore.session.Session.create_client', side_effect=AssertionError('AWS client forbidden')):
        assert execution_document(document, tmp_path, scope=scope, resolver=resolver) == expected
        assert execution_document(operand('kms', 'KeyId'), tmp_path, scope=scope) == key
        assert execution_document(operand('s3')['$resource'], tmp_path, scope=scope,
                                  property_name='CloudTrail.Trail.S3BucketName') == BUCKET
        assert execution_document(operand('kms')['$resource'], tmp_path, scope=scope,
                                  property_name='Lambda.Function.KmsKeyArn') == expected['Statement'][0]['Resource'][0]
        projected = reference_display(runtime_values(policy), scope.path, tmp_path)
    assert json.loads(projected['desired.row.009-002.document']) == expected
    assert projected['desired.row.009-002.artifactSha256'] == document_sha256(expected)
    assert len(resolver.models) == 2
    assert tmp_path / 'project.json' in resolver.reads.contents
    resolver.reads.verify()
    assert policy == original_policy
    assert {p: p.read_bytes() for p in tmp_path.rglob('*.properties')} == originals
    assert not any('.Arn=' in raw.decode('utf-8') for raw in originals.values())


def check_generation_and_snapshot_boundary(tmp_path):
    root, stage = tmp_path / 'root', tmp_path / 'stage'
    root.mkdir()
    stage.mkdir()
    scope, models, policy, document = fixture(root)
    # Confirmed observations remain usable; unresolved saved links are not identifiers.
    for service, identifier in [('kms', KEY), ('s3', BUCKET)]:
        anchor = 'saved-key' if service == 'kms' else 'saved-bucket'
        models[service]['desired.row.001-001.value'] = f'[saved]({service}.md#{anchor})'
        models[service]['observed.row.001-001.value'] = '`' + identifier + '`'
        save(Scope(root, 'prod', 'producer', service), models[service])
    originals = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    expected = execution_document(document, root, scope=scope)
    from model.render import generate_files
    import model.render as renderer
    from utils.aws_mappings import mapping_alias
    from sync_runtime import generate_views
    design = root / 'docs/designs/dev/consumer/iam.md'
    original_markdown = renderer.generate_markdown
    shutil.copytree(root / 'model', stage / 'model')
    shutil.copyfile(root / 'project.json', stage / 'project.json')
    with mapping_alias(FRAMEWORK, root), mapping_alias(FRAMEWORK, stage):
        with patch.object(renderer, 'generate_markdown',
                          lambda path, values, root: original_markdown(path, values, FRAMEWORK)):
            with pytest.raises(ValueError, match='JSON setting contains'):
                generate_files(design, runtime_values(policy), root)
            literal_policy = {**policy, 'desired.row.009-002.document': json.dumps(expected)}
            files = generate_files(design, runtime_values(literal_policy), root)
        assert json.loads(files[design.with_suffix('') / 'policy.json']) == expected
        assert '<a id="saved-policy"></a>' in files[design]
        failures, warnings, unavailable = [], [], {}
        generated = generate_views(stage, root, {design: runtime_values(policy)}, failures,
                                   definitions_root=FRAMEWORK, warnings=warnings, unavailable=unavailable)
        assert failures and any('JSON setting contains' in error for error in failures), failures
        assert design not in generated
        assert not (stage / 'docs/designs/dev/consumer/iam/policy.json').exists()
    assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file()} == originals
    resolver = Resolver(root)
    assert execution_document(document, root, scope=scope, resolver=resolver) == expected
    topology = json.loads((root / 'project.json').read_text(encoding='utf-8'))
    topology['targets'][0]['awsRegion'] = 'us-west-2'
    (root / 'project.json').write_text(json.dumps(topology), encoding='utf-8')
    with pytest.raises(ValueError, match='input changed'):
        resolver.reads.verify()


@pytest.mark.parametrize('service,value', [
    ('kms', None), ('kms', ''), ('kms', 'PENDING_DEPLOY'), ('kms', 'UNSET'),
    ('kms', '[missing](kms.md#missing)'), ('kms', 'KMS_Key_001'), ('kms', 'key-label'),
    ('kms', 'alias/confirmed'), ('kms', 'arn:aws:kms:ap-northeast-1:111111111111:alias/confirmed'),
    ('kms', KEY + 'x'), ('kms', 'mrk-' + 'a' * 31), ('kms', 'mrk-' + 'g' * 32),
    ('kms', '${KeyId}'), ('kms', '{{resolve:ssm:key}}'),
    ('s3', None), ('s3', ''), ('s3', 'PENDING_DEPLOY'), ('s3', 'UNSET'),
    ('s3', '[missing](s3.md#missing)'), ('s3', 'Uppercase'), ('s3', 'bucket_name'),
    ('s3', 'ab'), ('s3', 'a' * 64), ('s3', 'bucket/object'), ('s3', 'bucket..name'),
    ('s3', '192.168.1.1'), ('s3', 'xn--bucket'), ('s3', 'sthree-bucket'), ('s3', 'amzn-s3-demo-bucket'),
    ('s3', 'bucket-s3alias'), ('s3', 'bucket--ol-s3'), ('s3', 'bucket.mrap'),
    ('s3', 'bucket--x-s3'), ('s3', 'bucket--table-s3'), ('s3', '${BucketName}')])
def check_invalid_identifiers(tmp_path, service, value):
    scope, models, _, _ = fixture(tmp_path)
    values = models[service]
    if value is None:
        values = {k: v for k, v in values.items() if not k.startswith('desired.row.')}
    else:
        values['desired.row.001-001.value'] = value
    save(Scope(tmp_path, 'prod', 'producer', service), values)
    with pytest.raises(ReferenceResolutionError, match='confirmed|valid'):
        execution_document(operand(service), tmp_path, scope=scope)


@pytest.mark.parametrize('service', ['kms', 's3'])
@pytest.mark.parametrize('other', ['same', 'different', 'UNSET'])
def check_ambiguous_identifiers(tmp_path, service, other):
    scope, models, _, _ = fixture(tmp_path)
    values = models[service]
    for key, value in list(values.items()):
        if key.startswith('desired.row.001-001.'):
            values[key.replace('001-001', '001-002')] = value
    if other != 'same':
        values['desired.row.001-002.value'] = 'another-bucket' if other == 'different' else other
    save(Scope(tmp_path, 'prod', 'producer', service), values)
    with pytest.raises(ReferenceResolutionError, match='one confirmed'):
        execution_document(operand(service), tmp_path, scope=scope)


def check_duplicate_bucket_resource(tmp_path):
    scope, models, _, _ = fixture(tmp_path)
    values = models['s3']
    for key, value in list(values.items()):
        if key.startswith(('desired.resource.001.', 'desired.row.001-')):
            values[key.replace('.001', '.002')] = value.replace('S3_Bucket_001', 'S3_Bucket_002').replace('saved-bucket', 'other-bucket')
    values[COUNTERS] = '{"S3.Bucket":2}'
    save(Scope(tmp_path, 'prod', 'producer', 's3'), values)
    with pytest.raises(ReferenceResolutionError, match='unique BucketName'):
        execution_document(operand('s3'), tmp_path, scope=scope)


@pytest.mark.parametrize('service', ['kms', 's3'])
@pytest.mark.parametrize('case', ['pending', 'invalid', 'missing-link', 'literal-desired', 'missing-producer'])
def check_unconfirmed_observations(tmp_path, service, case):
    scope, models, _, _ = fixture(tmp_path)
    producer = Scope(tmp_path, 'prod', 'producer', service)
    values = models[service]
    anchor = 'saved-key' if service == 'kms' else 'saved-bucket'
    values['desired.row.001-001.value'] = f'[saved]({service}.md#{anchor})'
    values['observed.row.001-001.value'] = KEY if service == 'kms' else BUCKET
    if case in ('pending', 'invalid'):
        values['observed.row.001-001.value'] = 'PENDING_DEPLOY' if case == 'pending' else 'bad/id'
    elif case == 'missing-link':
        values['desired.row.001-001.value'] = f'[missing]({service}.md#missing)'
    elif case == 'literal-desired':
        values['desired.row.001-001.value'] = '`' + values['observed.row.001-001.value'] + '`'
    save(producer, values)
    if case == 'missing-producer':
        producer.path.unlink()
    with pytest.raises(ReferenceResolutionError):
        execution_document(operand(service), tmp_path, scope=scope)


@pytest.mark.parametrize('field,value', [
    ('awsRegion', None), ('awsRegion', ''), ('awsRegion', 'UNSET'),
    ('awsRegion', 'unknown-zone-1'), ('awsRegion', 'us-fictional-1'),
    ('awsAccountId', None), ('awsAccountId', 'UNSET'), ('awsAccountId', '123'),
    ('awsExecutionAccountId', 'UNSET'), ('awsExecutionAccountId', '')])
@pytest.mark.parametrize('service', ['kms', 's3'])
def check_unconfirmed_target(tmp_path, field, value, service):
    scope, _, _, _ = fixture(tmp_path)
    topology = json.loads((tmp_path / 'project.json').read_text(encoding='utf-8'))
    if value is None:
        topology['targets'][0].pop(field)
    else:
        topology['targets'][0][field] = value
    (tmp_path / 'project.json').write_text(json.dumps(topology), encoding='utf-8')
    with pytest.raises(ValueError, match='region|Region|account|partition'):
        execution_document(operand(service), tmp_path, scope=scope)


@pytest.mark.parametrize('case', ['missing', 'ambiguous-anchor', 'attribute', 'object', 'alias', 'other-type'])
def check_unsupported_references(tmp_path, case):
    scope, models, _, _ = fixture(tmp_path)
    selected = operand('kms')
    if case == 'missing':
        selected['$resource'] = selected['$resource'].replace('#saved-key', '#absent')
    elif case == 'ambiguous-anchor':
        models['kms'].update({'desired.resource.002.resourceType': 'KMS.Key',
            'desired.resource.002.logicalId': 'KMS_Key_002', 'desired.resource.002.anchor': 'saved-key',
            COUNTERS: '{"KMS.Key":2}'})
    elif case in ('attribute', 'object'):
        selected = operand('s3', 'Unsupported' if case == 'attribute' else 'ObjectArn')
    else:
        kind = 'KMS.Alias' if case == 'alias' else 'EC2.VPC'
        models['kms']['desired.resource.001.resourceType'] = kind
        models['kms']['desired.resource.001.logicalId'] = kind.replace('.', '_') + '_001'
        models['kms'][COUNTERS] = json.dumps({kind: 1})
    save(Scope(tmp_path, 'prod', 'producer', 'kms'), models['kms'])
    with pytest.raises(ReferenceResolutionError):
        execution_document(selected, tmp_path, scope=scope)



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
    from model.projection import json_sha256
    from utils.json_format import validate_aws_document
    scope, _, policy, _ = fixture(tmp_path)
    document = {'Statement': [{'Effect': 'Allow', 'Action': '*', 'Resource': [expression]}]}
    key = 'desired.row.009-002.document'
    policy[key] = json.dumps(document)
    original = copy.deepcopy(document)
    from json_intrinsics import project_document
    from model.validation import validate_json_settings
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
    from model.render import generate_files
    from sync_runtime import generate_views
    from utils.aws_mappings import mapping_alias
    root, stage = tmp_path / 'root', tmp_path / 'stage'
    root.mkdir()
    stage.mkdir()
    scope, _, policy, _ = fixture(root)
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
    from utils.cloudformation_format import decode_file as decode
    from cloudformation_inputs import resolve_value
    document = {'Nested': [{'Enabled': True, 'Count': 2, 'Nothing': None}],
                'PolicyVariable': '${aws:username}', 'Url': 'https://example.com',
                'EncodedSettings': '{"rules":[{"name":"keep"}]}'}
    assert execution_document(document, tmp_path) == document
    with patch('model.projection.document_references', return_value={'Ref': 'AWS::Region'}):
        warnings = []
        assert execution_document(document, tmp_path, warnings=warnings) == {'Ref': 'AWS::Region'}
        assert warnings
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
    from model.render import generate_files
    from model.operations import prepare_edit, publish_edit, validate_candidates
    from model.sources import SourceWriteContext
    from generation_inputs import GenerationInputs
    from types import SimpleNamespace
    from sync_runtime import generate_views
    from utils.aws_mappings import mapping_alias
    from utils.json_format import validate_aws_document
    root, stage = tmp_path / 'root', tmp_path / 'stage'
    root.mkdir(); stage.mkdir()
    scope, _, policy, _ = fixture(root)
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
    from model.validation import validate_json_settings
    scope, _, policy, _ = fixture(tmp_path)
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
    from design_catalog import DesignSchemaCatalog
    catalog = DesignSchemaCatalog(FRAMEWORK)
    for document in ({'Ref': 'Missing'}, {'bucketDefinitions': {'Ref': 'Missing'}},
                     {'bucketDefinitions': [{'accountId': '111111111111', 'buckets': {'Ref': 'Missing'}}]}):
        assert not catalog.literal_errors('Macie.ClassificationJob', 's3JobDefinition', json.dumps(document))
    assert catalog.literal_errors('Macie.ClassificationJob', 's3JobDefinition',
        json.dumps({'bucketDefinitions': [{'accountId': 'invalid', 'buckets': {'Ref': 'Missing'}}]}))
    with pytest.raises(ValueError):
        catalog.literal_errors('Macie.ClassificationJob', 's3JobDefinition', '{"Ref":1}')


def check_pending_policy_siblings(tmp_path):
    from policy_tables import Policy, validate_policy_document
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
