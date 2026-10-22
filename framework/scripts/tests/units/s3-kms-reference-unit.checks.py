"""S3 scalar Key/Arn intent across authority, display and local IaC comparison."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
import pytest
from model.core import entries, ReferenceResolutionError
from model.format import serialize, parse, patch as patch_model
from model.identity import COUNTERS
from model.sources import Scope, load_model, FileReads
from model.projection import scalar_reference_operand, reference_display
from model.render import generate_markdown
from model.references import incoming
from model.operations import validate_candidates
from reference_contracts import S3_KMS_MASTER_KEY_ID as PROP
from support.model_sources import write_model, catalog_display
from validation.design_links import check_design_links as validate_links
from validation.design_tables import check_design_tables as validate_tables
from validation.findings import Findings
from design_catalog import DesignSchemaCatalog
from issues_iac import Comparison

FRAMEWORK = Path(__file__).resolve().parents[4]
KEY_LINK = '[fixture-key](kms.md#key-one)'
ALIAS_LINK = '[alias/fixture-key](kms.md#alias-one)'
ROW = 'desired.row.001-003.value'


def selector(link=KEY_LINK, attribute='Arn'):
    return '`' + json.dumps({'$resource': link, '$attribute': attribute}) + '`'


def fixture(root, kms_value=None):
    (root / 'project.json').write_text(json.dumps({'projectName': 'synthetic', 'targets': [
        {'environment': 'fixture', 'alias': 'team', 'awsAccountId': '123456789012',
         'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}), encoding='utf-8')
    kms = {COUNTERS: '{"KMS.Key":2,"KMS.Alias":1}',
        'desired.service.kms.serviceId': 'kms', 'desired.service.kms.ownedCatalogResourceTypes': 'KMS.Key,KMS.Alias',
        'display.service.title': '# 合成KMS'}
    for rid, kind, logical, anchor in [('001', 'KMS.Key', 'KMS_Key_001', 'key-one'),
            ('002', 'KMS.Alias', 'KMS_Alias_001', 'alias-one'), ('003', 'KMS.Key', 'KMS_Key_002', 'key-two')]:
        kms.update({f'desired.resource.{rid}.resourceType': kind, f'desired.resource.{rid}.logicalId': logical,
                    f'desired.resource.{rid}.anchor': anchor, f'desired.resource.{rid}.resourceMode': 'IMPORT',
                    f'display.resource.{rid}.comment': '合成リソース'})
    kms.update({'desired.resource.002.parentReference': KEY_LINK,
        'desired.resource.002.parentProperty': 'KMS.Alias.TargetKeyId',
        'display.resource.003.label': 'other-key'})
    for rid, prop, value in [('001-001', 'KMS.Key.KeyId', '[key](#key-one)'),
            ('002-001', 'KMS.Alias.AliasName', '`alias/fixture-key`'),
            ('003-001', 'KMS.Key.KeyId', '[key](#key-two)')]:
        kms.update({f'desired.row.{rid}.property': prop, f'desired.row.{rid}.value': value,
                    f'desired.row.{rid}.comment': '合成設定'})
    kms['observed.row.001-001.value'] = '`12345678-1234-1234-1234-123456789abc`'
    kms['observed.row.003-001.value'] = '`87654321-1234-1234-1234-123456789abc`'
    bucket = {COUNTERS: '{"S3.Bucket":1}', 'desired.service.s3.serviceId': 's3',
        'desired.service.s3.ownedCatalogResourceTypes': 'S3.Bucket', 'display.service.title': '# 合成S3',
        'desired.resource.001.resourceType': 'S3.Bucket', 'desired.resource.001.logicalId': 'S3_Bucket_001',
        'desired.resource.001.anchor': 'bucket', 'desired.resource.001.resourceMode': 'IMPORT',
        'display.resource.001.comment': '合成バケット'}
    for rid, prop, value in [('001-001', 'S3.Bucket.BucketName', '`fixture-bucket`'),
            ('001-002', 'S3.Bucket.Region', '`ap-northeast-1`'),
            ('001-003', PROP, selector() if kms_value is None else kms_value),
            ('001-004', PROP.rsplit('.', 1)[0] + '.SSEAlgorithm', '`aws:kms`')]:
        bucket.update({f'desired.row.{rid}.property': prop, f'desired.row.{rid}.value': value,
                       f'desired.row.{rid}.comment': '合成設定'})
    for service, values in [('kms', kms), ('s3', bucket)]:
        write_model(Scope(root, 'fixture', 'team', service).path, values)
    return Scope(root, 'fixture', 'team', 's3'), bucket, kms


def designs(scope, bucket, kms):
    root = scope.root
    result = {}
    with catalog_display():
        for service, values in [('kms', kms), ('s3', bucket)]:
            path = root / 'docs/designs/fixture/team' / (service + '.md')
            path.parent.mkdir(parents=True, exist_ok=True)
            result[path] = generate_markdown(path, values, FRAMEWORK)
            path.write_text(result[path], encoding='utf-8')
    return result


@pytest.mark.parametrize('alias', [False, True])
def check_authority_display_and_references(project_workspace, alias):
    scope, bucket, kms = fixture(project_workspace, ALIAS_LINK if alias else None)
    before = {p: p.read_bytes() for p in scope.path.parent.glob('*.properties')}
    snapshot = load_model(scope)
    assert snapshot.authoritative == bucket
    # Exercise the normal lossless source patch/save/reload representation.
    scope.path.write_text(patch_model(parse(serialize(bucket)), {ROW: bucket[ROW]}), encoding='utf-8')
    assert load_model(scope, FileReads()).authoritative[ROW] == bucket[ROW]
    from model.validation import check_model_inputs
    schema = check_model_inputs(scope.path, bucket, scope.root, definitions_root=FRAMEWORK)
    assert not schema.errors, schema.errors
    uses = incoming(load_model(Scope(scope.root, 'fixture', 'team', 'kms')), '002' if alias else '001')
    assert any(consumer == scope and usage.consumer_key == ROW and
               usage.pointer == (None if alias else '/$resource') for consumer, usage in uses)
    validate_candidates(scope.root, {'model/fixture/team/s3.properties'}, {}, {('fixture', 'team', 's3')})
    with patch('botocore.session.Session.create_client', side_effect=AssertionError('AWS forbidden')):
        files = designs(scope, bucket, kms)
        displayed = reference_display(bucket, scope.path, scope.root, definitions_root=FRAMEWORK)
    view = scope.root / 'docs/designs/fixture/team/s3.md'
    expected = ALIAS_LINK if alias else KEY_LINK
    assert expected in files[view] and '$resource' not in files[view]
    assert displayed[ROW] == expected and bucket[ROW] == snapshot.authoritative[ROW]
    findings = Findings(scope.root)
    validate_links({}, [view], design_sources={view: bucket}, findings=findings,
                       root=scope.root, scope=None, definitions_root=FRAMEWORK)
    assert not findings.errors and not findings.warnings, (findings.errors, findings.warnings)
    from model.importing.references import Resolver as ImportResolver
    imported = ImportResolver(scope.root, 'fixture', 'team', definitions_root=FRAMEWORK)
    imported.verify_resource(bucket, '001', scope=scope, observed_only=True)
    assert not imported.warnings, imported.warnings
    if not alias:
        contracts = {'KMS.Key': ('Arn',)}
        imported._verify(PROP, KEY_LINK,
            'arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789abc', contracts=contracts)
        with pytest.raises(ReferenceResolutionError):
            imported._verify(PROP, KEY_LINK, '12345678-1234-1234-1234-123456789abc', contracts=contracts)
    catalog = DesignSchemaCatalog(FRAMEWORK)
    with catalog_display():
        validate_tables({view: ('s3', ('S3.Bucket',))}, {'S3.Bucket'},
            {row['property']: {'S3.Bucket'} for _, row in entries(bucket, 'desired.row.')}, {}, [view],
            design_sources={view: bucket}, findings=findings, markdown_design_artifacts=set(),
            markdown_iam_policy_artifacts=set(), root=scope.root, schema_catalog=catalog,
            scope=None, definitions_root=FRAMEWORK)
    assert not findings.errors and not findings.warnings, (findings.errors, findings.warnings)
    assert all(p.read_bytes() == raw and b'arn:' not in raw for p, raw in before.items())
    from sync_runtime import _compare_generation
    from types import SimpleNamespace
    plan = SimpleNamespace(root=scope.root, read_inputs=before, expected_outputs={view: {view: files[view]}}, failures=[], saved={})
    _compare_generation(plan)
    assert not plan.failures and view in plan.saved
    if not alias:
        # A saved link to a different Key cannot satisfy the Model selector.
        view.write_text(files[view].replace(KEY_LINK, '[other-key](kms.md#key-two)'), encoding='utf-8')
        _compare_generation(plan)
        assert len(plan.failures) == 1 and 'stale or missing' in plan.failures[0]
        changed = Findings(scope.root)
        validate_links({}, [view], design_sources={view: bucket}, findings=changed,
                           root=scope.root, scope=None, definitions_root=FRAMEWORK)
        assert any('Model KMS.Key' in warning['message'] for warning in changed.warnings)


@pytest.mark.parametrize('case', ['KeyId', 'AliasName', 'AliasArn', 'Unsupported', 'missing-attribute', 'extra',
                                 'alias', 'other-type', 'missing', 'ambiguous', 'cross-target'])
def check_invalid_scalar(project_workspace, case):
    scope, bucket, kms = fixture(project_workspace)
    selected = json.loads(bucket[ROW][1:-1])
    if case in {'KeyId', 'AliasName', 'AliasArn', 'Unsupported'}:
        selected['$attribute'] = case
    elif case == 'missing-attribute':
        del selected['$attribute']
    elif case == 'extra':
        selected['extra'] = True
    elif case == 'alias':
        selected['$resource'] = ALIAS_LINK
    elif case == 'other-type':
        selected['$resource'] = '[bucket](s3.md#bucket)'
    elif case == 'missing':
        selected['$resource'] = '[missing](kms.md#missing)'
    elif case == 'ambiguous':
        kms['desired.resource.003.anchor'] = 'key-one'
        write_model(Scope(scope.root, 'fixture', 'team', 'kms').path, kms)
    else:
        project = json.loads((scope.root / 'project.json').read_text(encoding='utf-8'))
        project['targets'].append({**project['targets'][0], 'alias': 'other'})
        (scope.root / 'project.json').write_text(json.dumps(project), encoding='utf-8')
        write_model(Scope(scope.root, 'fixture', 'other', 'kms').path, kms)
        selected['$resource'] = '[key](../other/kms.md#key-one)'
    bucket[ROW] = '`' + json.dumps(selected) + '`'
    row = dict(entries(bucket, 'desired.row.'))['001-003']
    with pytest.raises(ValueError):
        scalar_reference_operand(row, scope.root, scope)
    # The ordinary save guard must reject the invalid candidate before publication.
    with pytest.raises(ValueError):
        validate_candidates(scope.root, {'model/fixture/team/s3.properties'},
                            {scope.path: serialize(bucket)}, {('fixture', 'team', 's3')})


def check_pending_key_projection(project_workspace):
    scope, bucket, kms = fixture(project_workspace)
    kms['observed.row.001-001.value'] = '`PENDING_DEPLOY`'
    write_model(Scope(scope.root, 'fixture', 'team', 'kms').path, kms)
    with patch('botocore.session.Session.create_client', side_effect=AssertionError('AWS forbidden')):
        files = designs(scope, bucket, kms)
    assert KEY_LINK in files[scope.root / 'docs/designs/fixture/team/s3.md']
    assert load_model(scope).authoritative[ROW] == selector()


@pytest.mark.parametrize('actual,expected', [
    ({'Fn::GetAtt': ['Key', 'Arn']}, 'matched'), ({'Ref': 'Key'}, 'difference'),
    ({'Fn::GetAtt': ['OtherKey', 'Arn']}, 'difference'), ({'Ref': 'Alias'}, 'difference'),
    ({'Fn::GetAtt': ['Alias', 'Arn']}, 'uncompared'),
    ({'Fn::Sub': 'arn:${AWS::Partition}:kms:${AWS::Region}:${AWS::AccountId}:${Alias}'}, 'difference'),
    ({'Fn::Sub': '${Unknown}'}, 'uncompared'),
    ('12345678-1234-1234-1234-123456789abc', 'difference'),
    ('alias/fixture-key', 'difference'),
    ('arn:aws:kms:ap-northeast-1:123456789012:alias/fixture-key', 'difference'),
    ('arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789abc', 'uncompared'),
])
def check_iac_matrix(project_workspace, actual, expected):
    scope, bucket, kms = fixture(project_workspace)
    for service, values, mappings in [('s3', bucket, {'001': 'Bucket'}),
            ('kms', kms, {'001': 'Key', '002': 'Alias', '003': 'OtherKey'})]:
        for rid, logical in mappings.items():
            values[f'desired.resource.{rid}.resourceMode'] = 'CREATE'
            values[f'desired.resource.{rid}.cfn-logicalId'] = 'fixture-' + logical
        write_model(Scope(scope.root, 'fixture', 'team', service).path, values)
    stack = {'desired.stack.001.name': 'fixture', 'desired.stack.001.placementName': 'fixture',
        'desired.stack.001.template': 'fixture.yaml', 'desired.stack.001.parameters': 'fixture.json',
        'desired.stack.001.deployOrder': '1'}
    write_model(Scope(scope.root, 'fixture', 'team', 'cloudformation-stacks').path, stack)
    template = scope.root / 'infra/cloudformation/templates/team/fixture.yaml'
    template.parent.mkdir(parents=True)
    template.write_text(json.dumps({'Resources': {
        'Key': {'Type': 'AWS::KMS::Key'}, 'OtherKey': {'Type': 'AWS::KMS::Key'},
        'Alias': {'Type': 'AWS::KMS::Alias', 'Properties': {'AliasName': 'alias/fixture-key', 'TargetKeyId': {'Ref': 'Key'}}},
        'Bucket': {'Type': 'AWS::S3::Bucket', 'Properties': {'BucketName': 'fixture-bucket',
            'BucketEncryption': {'ServerSideEncryptionConfiguration': [
                {'ServerSideEncryptionByDefault': {'SSEAlgorithm': 'aws:kms', 'KMSMasterKeyID': actual}}]}}}}}), encoding='utf-8')
    parameters = scope.root / 'infra/cloudformation/parameters/fixture/team/fixture.json'
    parameters.parent.mkdir(parents=True)
    parameters.write_text('[]', encoding='utf-8')
    comparison = Comparison(scope.root, 'fixture', 'team', ['s3'], catalog=DesignSchemaCatalog(FRAMEWORK))
    results = comparison.run()
    encryption = [item for item in results if item['property'] == 'S3.Bucket.BucketEncryption']
    assert len(encryption) == 1 and encryption[0]['category'] == expected, results
    if actual == {'Ref': 'Key'}:
        assert encryption[0]['reference_diagnostics'][0]['allowed_forms'] == ['KeyArn']
    symbol = comparison.desired_value('s3', dict(entries(bucket, 'desired.row.'))['001-003'], 'S3.Bucket')
    assert symbol['$resource'] == ['kms', '001'] and symbol['$attribute'] == 'Arn'
    assert comparison.kms_format(symbol) == 'KeyArn'
    plain = comparison.desired_value('s3', {'property': PROP, 'value': KEY_LINK}, 'S3.Bucket')
    assert plain['$attribute'] == 'KeyId'
    assert comparison.reference_same(plain, comparison.evaluate('fixture', {'Fn::GetAtt': ['Key', 'Arn']}),
                                     'S3.Bucket', PROP.removeprefix('S3.Bucket.')) is True
    alias = comparison.desired_value('s3', {'property': PROP, 'value': ALIAS_LINK}, 'S3.Bucket')
    assert comparison.reference_same(alias, comparison.evaluate('fixture', {'Ref': 'Alias'}),
                                     'S3.Bucket', PROP.removeprefix('S3.Bucket.')) is True
    assert 'arn:' not in scope.path.read_text(encoding='utf-8')


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__, message='S3 KMS scalar reference contracts: PASS'))
