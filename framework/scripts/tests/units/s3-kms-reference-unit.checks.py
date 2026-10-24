"""S3 scalar Key/Arn intent across authority, display and local IaC comparison."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import model.validation as _imports_model_validation
from comparison import Comparison
from design_catalog import DesignSchemaCatalog
from model.core import entries
from model.format import parse, serialize
from model.format import patch as patch_model
from model.identity import COUNTERS
from model.importing.references import Resolver as ImportResolver
from model.operations import validate_candidates
from model.projection import reference_display
from model.references import incoming
from model.render import generate_markdown
from model.sources import Scope, load_model
from support.model_sources import catalog_display, write_model
from sync_runtime import _compare_generation
from utils.reference_contracts import S3_KMS_MASTER_KEY_ID as PROP
from utils.source_reads import FileReads
from validation.design_links import check_design_links as validate_links
from validation.design_tables import check_design_tables as validate_tables
from validation.findings import Findings

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

FRAMEWORK = Path(__file__).resolve().parents[4]
KEY_LINK = '[fixture-key](kms.md#key-one)'
ALIAS_LINK = '[alias/fixture-key](kms.md#alias-one)'
ROW = 'desired.row.001-003.value'




def fixture(root):
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
            ('001-003', PROP, ALIAS_LINK),
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


def check_authority_display_and_references(project_workspace):
    scope, bucket, kms = fixture(project_workspace)
    before = {p: p.read_bytes() for p in scope.path.parent.glob('*.properties')}
    snapshot = load_model(scope)
    assert snapshot.authoritative == bucket
    # Exercise the normal lossless source patch/save/reload representation.
    scope.path.write_text(patch_model(parse(serialize(bucket)), {ROW: bucket[ROW]}), encoding='utf-8')
    assert load_model(scope, FileReads()).authoritative[ROW] == bucket[ROW]
    check_model_inputs = _imports_model_validation.check_model_inputs
    schema = check_model_inputs(scope.path, bucket, scope.root, definitions_root=FRAMEWORK)
    assert not schema.errors, schema.errors
    uses = incoming(load_model(Scope(scope.root, 'fixture', 'team', 'kms')), '002')
    assert any(consumer == scope and usage.consumer_key == ROW and usage.pointer is None
               for consumer, usage in uses)
    validate_candidates(scope.root, {'model/fixture/team/s3.properties'}, {}, {('fixture', 'team', 's3')})
    with patch('botocore.session.Session.create_client', side_effect=AssertionError('AWS forbidden')):
        displayed = reference_display(bucket, scope.path, scope.root)
        files = designs(scope, displayed, kms)
    view = scope.root / 'docs/designs/fixture/team/s3.md'
    expected = ALIAS_LINK
    assert expected in files[view] and '$resource' not in files[view]
    assert displayed[ROW] == expected and bucket[ROW] == snapshot.authoritative[ROW]
    findings = Findings(scope.root)
    validate_links({}, [view], design_sources={view: bucket}, findings=findings,
                       root=scope.root, scope=None, definitions_root=FRAMEWORK)
    assert not findings.errors and not findings.warnings, (findings.errors, findings.warnings)
    imported = ImportResolver(scope.root, 'fixture', 'team', definitions_root=FRAMEWORK)
    imported.verify_resource(bucket, '001', scope=scope, observed_only=True)
    assert not imported.warnings, imported.warnings
    catalog = DesignSchemaCatalog(FRAMEWORK)
    with catalog_display():
        validate_tables({view: ('s3', ('S3.Bucket',))}, {'S3.Bucket'},
            {row['property']: {'S3.Bucket'} for _, row in entries(bucket, 'desired.row.')}, {}, [view],
            design_sources={view: bucket}, findings=findings, markdown_design_artifacts=set(),
            markdown_iam_policy_artifacts=set(), root=scope.root, schema_catalog=catalog,
            scope=None, definitions_root=FRAMEWORK)
    assert not findings.errors and not findings.warnings, (findings.errors, findings.warnings)
    assert all(p.read_bytes() == raw and b'arn:' not in raw for p, raw in before.items())

    plan = SimpleNamespace(root=scope.root, read_inputs=before, expected_outputs={view: {view: files[view]}}, failures=[], saved={})
    _compare_generation(plan)
    assert not plan.failures and view in plan.saved
def check_iac_matrix(project_workspace):
    actual = {'Ref': 'Alias'}
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
    assert len(encryption) == 1 and encryption[0]['category'] == 'matched', results
    plain = comparison.prepare_value('s3', {'property': PROP, 'value': KEY_LINK}, 'S3.Bucket').require_value()
    assert plain['$attribute'] == 'KeyId'
    assert comparison.reference_same(plain, comparison.evaluate('fixture', {'Fn::GetAtt': ['Key', 'Arn']}),
                                     'S3.Bucket', PROP.removeprefix('S3.Bucket.')) is True
    alias = comparison.prepare_value('s3', {'property': PROP, 'value': ALIAS_LINK}, 'S3.Bucket').require_value()
    assert comparison.reference_same(alias, comparison.evaluate('fixture', {'Ref': 'Alias'}),
                                     'S3.Bucket', PROP.removeprefix('S3.Bucket.')) is True
    assert 'arn:' not in scope.path.read_text(encoding='utf-8')


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__, message='S3 KMS scalar reference contracts: PASS'))
