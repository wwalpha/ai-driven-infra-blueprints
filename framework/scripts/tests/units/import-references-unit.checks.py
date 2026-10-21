#!/usr/bin/env python3
"""Exact IMPORT references use synthetic Models and immutable Framework definitions."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import json
from unittest.mock import patch
import pytest

from model.importing.references import Resolver
from model.importing.sources import verify_values, property_values
from model.importing.scope import restrict, read_consumers
from model.sources import load_model as load_for_edit, json_text
from support.model_v2_fixtures import value_snapshot as Expansion
from model.core import LINK, entries, literal
from reference_contracts import contract
from support.model_sources import write_model
from validation_cache import input_context

ROOT = Path(__file__).resolve().parents[4]


from contextlib import contextmanager, closing

@contextmanager
def warned(resolver, match):
    before = len(resolver.warnings)
    yield
    assert any(match in warning['message'] for warning in resolver.warnings[before:]), resolver.warnings[before:]


@pytest.fixture(autouse=True)
def project(tmp_path):
    (tmp_path / 'project.json').write_text(json_text({'targets': [
        {'environment': 'dev', 'alias': 'cde', 'awsAccountId': '123456789012',
         'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))


def values(kind, attributes, rid='001', mode='IMPORT', anchor='producer'):
    result = {f'desired.resource.{rid}.resourceType': kind,
              f'desired.resource.{rid}.resourceMode': mode,
              f'desired.resource.{rid}.anchor': anchor,
              f'desired.resource.{rid}.logicalId': 'Producer'}
    for n, (prop, raw) in enumerate(attributes.items(), 1):
        prefix = f'desired.row.{rid}-{n:03d}.'
        result.update({prefix + 'property': kind + '.' + prop, prefix + 'value': '`' + raw + '`', prefix + 'comment': '合成入力'})
    return result


def producer(root, kind, attributes, mode='IMPORT', env='dev', rid='001', anchor='producer', previous=None):
    from utils.aws_mappings import owners
    service = owners(ROOT)[kind]
    path = root / 'model' / env / 'cde' / (service + '.properties')
    fields = {**(previous or {}), **values(kind, attributes, rid, mode, anchor)}
    for index, raw in enumerate(attributes.values(), 1):
        if LINK.fullmatch(raw):
            fields[f'desired.row.{rid}-{index:03d}.value'] = raw
    write_model(path, fields)
    return service, path


CASES = [
    ('GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.BucketName', 'S3.Bucket', {'BucketName': 'audit-bucket'}, 'audit-bucket'),
    ('CloudTrail.Trail.S3BucketName', 'S3.Bucket', {'BucketName': 'audit-bucket'}, 'audit-bucket'),
    ('KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN', 'S3.Bucket', {'BucketName': 'audit-bucket'}, 'arn:aws:s3:::audit-bucket'),
    ('EC2.SecurityGroup.VpcId', 'EC2.VPC', {'VpcId': 'vpc-confirmed'}, 'vpc-confirmed'),
    ('EC2.TransitGatewayVpcAttachment.VpcId', 'EC2.VPC', {'VpcId': 'vpc-confirmed'}, 'vpc-confirmed'),
    ('CodeBuild.Project.VpcConfig.Subnets[]', 'EC2.Subnet', {'SubnetId': 'subnet-confirmed'}, 'subnet-confirmed'),
    ('Lambda.Function.VpcConfig.SecurityGroupIds[]', 'EC2.SecurityGroup', {'GroupId': 'sg-confirmed'}, 'sg-confirmed'),
    ('Glue.Job.Role', 'IAM.Role', {'RoleName': 'glue-role'}, 'glue-role'),
    ('GuardDuty.MalwareProtectionPlan.Role', 'IAM.Role', {'RoleName': 'scanner', 'Path': '/service-role/'}, 'arn:aws:iam::123456789012:role/service-role/scanner'),
    ('KMS.Alias.TargetKeyId', 'KMS.Key', {'KeyId': '12345678-1234-1234-1234-123456789012'}, '12345678-1234-1234-1234-123456789012'),
    ('CloudTrail.Trail.KMSKeyId', 'KMS.Alias', {'AliasName': 'alias/audit'}, 'alias/audit'),
]


@pytest.mark.parametrize('prop,kind,attrs,raw', CASES)
@pytest.mark.parametrize('mode', ['CREATE', 'IMPORT'])
@pytest.mark.parametrize('present', [False, True])
def check_exact_reference(tmp_path, prop, kind, attrs, raw, mode, present):
    if present:
        service, _ = producer(tmp_path, kind, attrs, mode)
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    with input_context(), patch('subprocess.run', side_effect=AssertionError('no AWS or other subprocess')):
        result = resolver.match(prop, raw)
        assert bool(result) == present
        if present:
            assert result['service'] == service and result['id'] == '001'
            resolver.verify(prop, '[label](' + service + '.md#producer)', raw)
            with warned(resolver, 'requires a reference link'):
                resolver.verify(prop, '`' + raw + '`', raw)
        else:
            resolver.verify(prop, '`' + raw + '`', raw)
            with warned(resolver, 'differs from acquired'):
                resolver.verify(prop, '[label](s3.md#producer)', raw)


def check_guardduty_bucket_reference_contract(tmp_path):
    prop = 'GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.BucketName'
    assert contract(prop) == {'S3.Bucket': ('BucketName',)}
    assert contract('Unknown.Resource.ProtectedResource.S3Bucket.BucketName') == {}
    first = values('S3.Bucket', {'BucketName': 'audit-bucket'})
    producer(tmp_path, 'S3.Bucket', {'BucketName': 'other-bucket'}, rid='002', anchor='other', previous=first)
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    source = values('GuardDuty.MalwareProtectionPlan', {'ProtectedResource.S3Bucket.BucketName': 'unused'}, rid='009')
    source['desired.row.009-001.value'] = '[bucket](s3.md#producer)'
    source['observed.row.009-001.value'] = 'audit-bucket'
    record = {'record': 'synthetic', 'identityProperty': None, 'identity': 'synthetic-plan',
              'properties': {prop: {'status': 'captured', 'value': 'audit-bucket'}}}
    before = Expansion({}, {}, {})
    with patch('subprocess.run', side_effect=AssertionError('no AWS or other subprocess')):
        assert verify_values(before, Expansion(source, {}, {}), {'009': record}, lambda _: {'type': 'string'}, resolver)
        resolver.verify_resource(source, '009', require_links=False, observed_only=True)
        assert not resolver.warnings
        source['desired.row.009-001.value'] = '[wrong](s3.md#other)'
        with warned(resolver, 'differs from acquired physical reference'):
            verify_values(before, Expansion(source, {}, {}), {'009': record}, lambda _: {'type': 'string'}, resolver)
        source['desired.row.009-001.value'] = '[bucket](s3.md#producer)'
        source['observed.row.009-001.value'] = 'other-bucket'
        with pytest.raises(ValueError, match='differs from the acquired Property'):
            verify_values(before, Expansion(source, {}, {}), {'009': record}, lambda _: {'type': 'string'}, resolver)
        with pytest.raises(ValueError, match='literal differs from acquired physical value'):
            resolver.verify(prop, '`other-bucket`', 'audit-bucket')


def check_no_guessed_or_foreign_identity(tmp_path):
    prop = 'EC2.SecurityGroup.VpcId'
    producer(tmp_path, 'EC2.VPC', {'VpcId': 'vpc-confirmed'}, env='stg')
    producer(tmp_path, 'EC2.VPC', {'VpcId': 'vpc-other', 'Name': 'vpc-confirmed'})
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    assert resolver.match(prop, 'vpc-confirmed') is None
    assert resolver.match('Unregistered.Resource.VpcId', 'vpc-other') is None
    assert resolver.match(prop, 'UNSET') is None
    assert resolver.match(prop, 'PENDING_DEPLOY') is None


def check_ambiguous_and_wrong_explicit_link(tmp_path):
    first = values('EC2.VPC', {'VpcId': 'vpc-confirmed'})
    producer(tmp_path, 'EC2.VPC', {'VpcId': 'vpc-confirmed'}, rid='002', anchor='other', previous=first)
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    with pytest.raises(ValueError, match='ambiguous physical reference'):
        resolver.match('EC2.SecurityGroup.VpcId', 'vpc-confirmed')
    producer(tmp_path, 'EC2.VPC', {'VpcId': 'vpc-confirmed'})
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    with warned(resolver, 'differs from acquired'):
        resolver.verify('EC2.SecurityGroup.VpcId', '[wrong](vpc.md#other)', 'vpc-confirmed')
    with warned(resolver, 'differs from acquired'):
        resolver.verify('EC2.SecurityGroup.VpcId', '[wrong](../other/vpc.md#producer)', 'vpc-confirmed')


def check_publication_mixed_array_and_physical_value(tmp_path):
    service, _ = producer(tmp_path, 'EC2.Subnet', {'SubnetId': 'subnet-confirmed'})
    prop = 'CodeBuild.Project.VpcConfig.Subnets[]'
    raw = '["[subnet](' + service + '.md#producer)","subnet-external"]'
    new = values('CodeBuild.Project', {'VpcConfig.Subnets[]': raw}, rid='009', anchor='consumer')
    new['observed.row.009-001.value'] = '["subnet-confirmed","subnet-external"]'
    after, before = Expansion(new, {}, {}), Expansion({}, {}, {})
    record = {'record': 'synthetic', 'identityProperty': None, 'identity': 'synthetic-project',
              'properties': {prop: {'status': 'captured', 'value': ['subnet-confirmed', 'subnet-external']}}}
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    assert verify_values(before, after, {'009': record}, lambda _: {'type': 'string'}, resolver)
    wrong = {**new, 'observed.row.009-001.value': '["subnet-external","subnet-external"]'}
    with pytest.raises(ValueError, match='differs from the acquired Property'):
        verify_values(before, Expansion(wrong, {}, {}), {'009': record}, lambda _: {'type': 'string'}, resolver)
    assert property_values(new, '009', prop, {'type': 'string'}) == record['properties'][prop]['value']


def check_observed_and_reused_index(tmp_path):
    import model.sources
    observed = values('EC2.VPC', {'VpcId': 'PENDING_DEPLOY'})
    observed['desired.row.001-001.value'] = '[Producer](#producer)'
    observed['observed.row.001-001.value'] = 'vpc-confirmed'
    write_model(tmp_path / 'model/dev/cde/vpc.properties', observed)
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    with input_context(), patch.object(model.sources, '_read_model', wraps=model.sources._read_model) as read:
        for _ in range(20):
            assert resolver.match('EC2.SecurityGroup.VpcId', 'vpc-confirmed')
        assert read.call_count == 1
        assert resolver.metrics['referenceModelReads'] == 1
    assert resolver.match('EC2.SecurityGroup.VpcId', 'PENDING_DEPLOY') is None


@pytest.mark.parametrize('physical', ['PENDING_DEPLOY', 'vpc-confirmed', 'UNSET'])
@pytest.mark.parametrize('local', [None, 'vpc', 'ec2'])
def check_pending_explicit_reference_after_destroy(tmp_path, physical, local):
    source = values('EC2.VPC', {'VpcId': physical})
    source['desired.row.001-001.value'] = '[Producer](#producer)'
    source['observed.row.001-001.value'] = physical
    write_model(tmp_path / 'model/dev/cde/vpc.properties', source)
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT,
                        local={local: Expansion(source, {}, {})} if local else None)
    prop = 'EC2.Subnet.VpcId'
    reference = '[Producer](' + ('' if local else 'vpc.md') + '#producer)'
    assert resolver.match(prop, 'PENDING_DEPLOY') is None
    if physical == 'PENDING_DEPLOY':
        resolver.verify(prop, reference, 'PENDING_DEPLOY', require_links=False)
    else:
        with warned(resolver, 'differs from acquired'):
            resolver.verify(prop, reference, 'PENDING_DEPLOY', require_links=False)
    for wrong in ('[missing](vpc.md#absent)', '[foreign](../other/vpc.md#producer)',
                  '[wrong type](subnet.md#producer)'):
        with warned(resolver, 'differs from acquired'):
            resolver.verify(prop, wrong, 'PENDING_DEPLOY', require_links=False)
    with warned(resolver, 'differs from acquired'):
        resolver.verify(prop, reference, 'PENDING_DEPLOY')
    with warned(resolver, 'no physical identification contract'):
        resolver.verify('Unknown.Resource.Value', reference, 'PENDING_DEPLOY', require_links=False)


def check_append_only_and_later_import(tmp_path):
    prop = 'CloudTrail.Trail.S3BucketName'
    old = values('CloudTrail.Trail', {'S3BucketName': 'audit-bucket'})
    expansion = Expansion(old, {}, {})
    producer(tmp_path, 'S3.Bucket', {'BucketName': 'audit-bucket'})
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    assert verify_values(expansion, expansion, {}, lambda _: {'type': 'string'}, resolver) == []
    changed = {**old, 'desired.row.001-001.value': '[audit-bucket](s3.md#producer)'}
    warnings = []
    with pytest.raises(ValueError, match='unselected Resource'):
        verify_values(expansion, Expansion(changed, {}, {}), {}, lambda _: {'type': 'string'}, resolver, warnings=warnings)
    assert old['desired.row.001-001.value'] == '`audit-bucket`'



def check_selected_new_import_can_resolve_only_its_declared_producer(tmp_path):
    from model.format import serialize
    from model.sources import FileReads, candidate_sources
    from model.operations import CandidateReads
    _, producer_path = producer(tmp_path, 'EC2.Subnet', {'SubnetId': 'subnet-confirmed', 'Name': 'private-subnet'})
    producer_before = producer_path.read_bytes()
    path = tmp_path / 'model/dev/cde/codebuild.properties'
    write_model(path, {'desired.service.codebuild.serviceId': 'codebuild'})
    before = load_for_edit(path)
    fields = {**before.authoritative, **values('CodeBuild.Project', {'VpcConfig.Subnets': 'unused'}, rid='009', anchor='codebuild-new')}
    fields['desired.row.009-001.value'] = '[private-subnet](vpc.md#producer)'
    fields['observed.row.009-001.value'] = 'subnet-confirmed'
    with restrict(('dev', 'cde', 'codebuild')), read_consumers({('dev', 'cde', 'codebuild')}):
        candidate = load_for_edit(path, CandidateReads(FileReads(), {path: serialize(fields)}))
        assert candidate.authoritative['desired.row.009-001.value'] == '[private-subnet](vpc.md#producer)'
        assert producer_path in candidate.dependencies
        with pytest.raises(ValueError, match='outside selected'):
            load_for_edit(producer_path)
        external = dict(fields)
        external['desired.row.009-001.value'] = 'subnet-external'
        del external['observed.row.009-001.value']
        assert load_for_edit(path, CandidateReads(FileReads(), {path: serialize(external)})).authoritative['desired.row.009-001.value'] == 'subnet-external'
        directory = tmp_path.parent / (tmp_path.name + '-candidate')
        own = directory / path.relative_to(tmp_path)
        own.parent.mkdir(parents=True)
        own.write_text(serialize(fields), encoding='utf-8')
        (directory / producer_path.relative_to(tmp_path)).write_bytes(producer_before)
        with pytest.raises(ValueError, match='outside the selected service'):
            candidate_sources(tmp_path, directory, before)
    assert producer_path.read_bytes() == producer_before


@pytest.mark.parametrize('prop,kind,attrs,raw,context', [
    ('CloudTrail.Trail.KMSKeyId', 'KMS.Key', {'KeyId': '12345678-1234-1234-1234-123456789012'},
     'arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012', {}),
    ('CloudTrail.Trail.KMSKeyId', 'KMS.Alias', {'AliasName': 'alias/audit'},
     'arn:aws:kms:ap-northeast-1:123456789012:alias/audit', {}),
    ('CodeBuild.Project.Environment.EnvironmentVariables[].Value', 'SecretsManager.Secret', {'Name': 'audit-secret'},
     'audit-secret:password:AWSCURRENT:', {'CodeBuild.Project.Environment.EnvironmentVariables[].Type': 'SECRETS_MANAGER'}),
    ('CloudTrail.Trail.EventSelectors[].DataResources[].Values', 'S3.Bucket', {'BucketName': 'audit-bucket'},
     'arn:aws:s3:::audit-bucket/prefix/', {'CloudTrail.Trail.EventSelectors[].DataResources[].Type': 'AWS::S3::Object'}),
])
def check_declared_identifier_forms(tmp_path, prop, kind, attrs, raw, context):
    producer(tmp_path, kind, attrs)
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    assert resolver.match(prop, raw, context)
    assert resolver.match(prop, raw.replace('123456789012:', '999999999999:'), context) is None if '123456789012:' in raw else True
    assert resolver.match(prop, raw.replace('arn:aws:', 'arn:aws-cn:'), context) is None if raw.startswith('arn:aws:') else True


def check_import_compact_display_and_create_guards():
    from model.display import display_rows
    from design_layout import expanded_display_rows, HEADER, ALIGNMENT
    from service_rows import codebuild_display_row, codebuild_formal_rows, CODEBUILD_FORMAL_VARIABLE
    prop = 'CodeBuild.Project.VpcConfig.Subnets'
    raw = '`["[private](vpc.md#producer)","subnet-external"]`'
    rows = [['001-001', prop, raw, '合成入力']]
    rendered = display_rows('CodeBuild.Project', rows, ROOT, mode='IMPORT')
    assert [r[2] for r in rendered] == ['[private](vpc.md#producer)', '`subnet-external`']
    lines = ['<a id="codebuild-new"></a>', '### CodeBuild.Project: audit', HEADER, ALIGNMENT]
    lines += ['| ' + ' | '.join([str(i), *row[1:]]) + ' |' for i, row in enumerate(rendered, 1)]
    restored = expanded_display_rows(lines, ROOT, modes={'codebuild-new': 'IMPORT'})
    assert any(raw in line for line in restored)
    with pytest.raises(ValueError, match='must be a resource link'):
        display_rows('CodeBuild.Project', rows, ROOT)
    variables = [['001-' + str(n), CODEBUILD_FORMAL_VARIABLE + key, '`' + value + '`', '合成入力']
                 for n, (key, value) in enumerate([('Name', 'SECRET'), ('Type', 'SECRETS_MANAGER'), ('Value', 'audit-secret:key')])]
    compact = codebuild_display_row(variables, 0, '合成入力', mode='IMPORT')
    assert 'SECRETS_MANAGER' in compact[3]
    assert codebuild_formal_rows(compact, set(), mode='IMPORT')[1][2] == '`SECRETS_MANAGER`'
    with pytest.raises(ValueError, match='require a resource link'):
        codebuild_display_row(variables, 0, '合成入力')



@pytest.mark.parametrize('kind,name,prop,desired,observed', [
    ('KinesisFirehose.DeliveryStream', 'DeliveryStreamName', 'S3DestinationConfiguration.BucketARN', '[audit-bucket](s3.md#producer)', '`arn:aws:s3:::audit-bucket`'),
    ('CloudTrail.Trail', 'TrailName', 'S3BucketName', '[audit-bucket](s3.md#producer)', '`audit-bucket`'),
    ('CodeBuild.Project', 'Name', 'VpcConfig.Subnets', '`["[private](vpc.md#producer)","subnet-external"]`', '["subnet-confirmed","subnet-external"]'),
])
def check_markdown_roundtrip_keeps_physical_values(tmp_path, kind, name, prop, desired, observed):
    from model.render import generate_markdown
    from utils.aws_mappings import owners
    service = owners(ROOT)[kind]
    source = values(kind, {name: 'audit', prop: 'unused'}, rid='009', anchor=service + '-audit')
    source.update({'desired.service.' + service + '.serviceId': service,
        'desired.service.' + service + '.ownedCatalogResourceTypes': kind,
        'display.service.title': '# 合成詳細設計', 'display.resource.009.comment': '合成設定',
        'desired.row.009-002.value': desired, 'observed.row.009-002.value': observed})
    path = tmp_path / 'docs/designs/dev/cde' / (service + '.md')
    path.parent.mkdir(parents=True)
    first = generate_markdown(path, source, ROOT)
    path.write_text(first)
    from design_layout import expanded_display_rows
    normalized = expanded_display_rows(first.splitlines(), ROOT, modes={service + '-audit': 'IMPORT'})
    expected = '[' + literal(observed) + ']' + desired[desired.index(']') + 1:] if desired.startswith('[') else desired
    assert any(expected in line for line in normalized), normalized
    assert source['desired.row.009-002.value'] == desired
    assert source['observed.row.009-002.value'] == observed
    assert path.read_text() == first


def check_mixed_literals_cannot_hide_behind_observations(tmp_path):
    producer(tmp_path, 'EC2.Subnet', {'SubnetId': 'subnet-confirmed'})
    source = values('CodeBuild.Project', {'VpcConfig.Subnets': 'unused'}, rid='009')
    source['desired.row.009-001.value'] = '`["[private](vpc.md#producer)","subnet-wrong"]`'
    source['observed.row.009-001.value'] = '["subnet-confirmed","subnet-external"]'
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    with pytest.raises(ValueError, match='literal differs'):
        resolver.verify_resource(source, '009')


@pytest.mark.parametrize('prop', ['Lambda.Function.Role', 'GuardDuty.MalwareProtectionPlan.Role'])
def check_role_arn_requires_account_and_explicit_path(tmp_path, prop):
    producer(tmp_path, 'IAM.Role', {'RoleName': 'runner', 'Path': '/service-role/'})
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    assert resolver.match(prop, 'arn:aws:iam::123456789012:role/service-role/runner')
    assert resolver.match(prop, 'arn:aws:iam::123456789012:role/runner') is None
    assert resolver.match(prop, 'arn:aws:iam::999999999999:role/service-role/runner') is None
    assert resolver.match(prop, 'arn:aws-cn:iam::123456789012:role/service-role/runner') is None
    assert resolver.match(prop, 'runner') is None


def check_guardduty_role_acquired_value_consistency(tmp_path):
    prop = 'GuardDuty.MalwareProtectionPlan.Role'
    assert contract(prop) == {'IAM.Role': ('Arn',)}
    assert contract('Unknown.Resource.Role') == {}
    service, _ = producer(tmp_path, 'IAM.Role', {'RoleName': 'scanner', 'Path': '/service-role/'})
    physical = 'arn:aws:iam::123456789012:role/service-role/scanner'
    source = values('GuardDuty.MalwareProtectionPlan', {'Role': 'unused'}, rid='002')
    source['desired.row.002-001.value'] = '[role](' + service + '.md#producer)'
    source['observed.row.002-001.value'] = physical
    record = {'record': 'synthetic', 'identityProperty': None, 'identity': 'synthetic-plan',
              'properties': {prop: {'status': 'captured', 'value': physical}}}
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    before = Expansion({}, {}, {})
    with patch('subprocess.run', side_effect=AssertionError('no AWS or other subprocess')):
        assert verify_values(before, Expansion(source, {}, {}), {'002': record}, lambda _: {'type': 'string'}, resolver)
        resolver.verify_resource(source, '002', require_links=False, observed_only=True)
        assert not resolver.warnings
        wrong = {**source, 'desired.row.002-001.value': '[wrong](s3.md#producer)'}
        with warned(resolver, 'differs from acquired physical reference'):
            verify_values(before, Expansion(wrong, {}, {}), {'002': record}, lambda _: {'type': 'string'}, resolver)
        wrong = {**source, 'observed.row.002-001.value': 'arn:aws:iam::123456789012:role/other'}
        with pytest.raises(ValueError, match='differs from the acquired Property'):
            verify_values(before, Expansion(wrong, {}, {}), {'002': record}, lambda _: {'type': 'string'}, resolver)
        with warned(resolver, 'differs from acquired physical reference'):
            resolver.verify_resource(wrong, '002', require_links=False, observed_only=True)


def check_import_reference_observation_sync_remains_guarded(tmp_path):
    from import_guard import resource_config, digest, require_import_changes
    from task_contract import start
    producer(tmp_path, 'EC2.VPC', {'VpcId': 'vpc-confirmed'})
    source = values('EC2.TransitGatewayVpcAttachment', {'VpcId': 'unused'})
    source['desired.row.001-001.value'] = '[vpc](vpc.md#producer)'
    source['observed.row.001-001.value'] = 'PENDING_DEPLOY'
    updated = {**source, 'observed.row.001-001.value': 'vpc-confirmed'}
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    with warned(resolver, 'differs from acquired physical reference'):
        resolver.verify_resource(source, '001', require_links=False, observed_only=True)
    resolver.warnings.clear()
    resolver.verify_resource(updated, '001', require_links=False, observed_only=True)
    assert not resolver.warnings
    old, new = resource_config(source, '001'), resource_config(updated, '001')
    assert old['rows'] == new['rows'] and old['resource'] == new['resource']
    assert digest(old) != digest(new)
    (tmp_path / '.git').mkdir()
    start(tmp_path, 'tasks/sync.md', '## Task contract\n- Task type: `governance`\n- Task status: `running`\n'
          '## Validation scope\n- `framework`\n## Required changes\n- [R1] Synthetic sync guard\n'
          '## Acceptance checks\n- [R1] `exists:tasks/sync.md`\n## Modified files\n- `tasks/sync.md`\n'
          '## Allowed paths\n- `tasks/sync.md`\n')
    with patch('import_guard.changes', return_value=('synthetic-base', {'dev/cde/transit-gateway/001':
              {'before': digest(old), 'after': digest(new), 'mode': 'IMPORT', 'action': 'update'}})):
        with pytest.raises(ValueError, match='require the registered design /import workflow'):
            require_import_changes(tmp_path, supplied={'model/dev/cde/transit-gateway.properties'})



@pytest.mark.parametrize('wrong', [False, True])
@pytest.mark.parametrize('observed', [False, True])
def check_design_link_validation_uses_physical_identity(tmp_path, wrong, observed):
    from types import SimpleNamespace
    from model.render import generate_markdown
    from model.projection import identifier_outputs
    from design_document import DesignIndex
    from validation.design_links import check_design_links
    source = values('KinesisFirehose.DeliveryStream', {'DeliveryStreamName': 'audit', 'S3DestinationConfiguration.BucketARN': 'unused'}, rid='009', anchor='data-firehose-audit')
    source.update({'desired.service.data-firehose.serviceId': 'data-firehose',
        'desired.service.data-firehose.ownedCatalogResourceTypes': 'KinesisFirehose.DeliveryStream',
        'display.service.title': '# Firehose', 'display.resource.009.comment': '合成入力',
        'desired.row.009-002.value': '[audit-bucket](s3.md#producer)',
        'observed.row.009-002.value': '`arn:aws:s3:::audit-bucket`'})
    if not observed:
        del source['observed.row.009-002.value']
    bucket = values('S3.Bucket', {'BucketName': 'other-bucket' if wrong else 'audit-bucket'})
    bucket.update({'desired.service.s3.serviceId': 's3', 'desired.service.s3.ownedCatalogResourceTypes': 'S3.Bucket',
                   'display.service.title': '# S3', 'display.resource.001.comment': '合成入力'})
    write_model(tmp_path / 'model/dev/cde/s3.properties', bucket)
    write_model(tmp_path / 'model/dev/cde/data-firehose.properties', source)
    document = tmp_path / 'docs/designs/dev/cde/data-firehose.md'
    document.parent.mkdir(parents=True)
    document.write_text(generate_markdown(document, source, ROOT))
    (document.parent / 's3.md').write_text(generate_markdown(document.parent / 's3.md', bucket, ROOT))
    from validation.findings import Findings
    findings = Findings(tmp_path)
    check_design_links(identifier_outputs(ROOT), [document], design_index=DesignIndex(ROOT), design_sources={document: source},
                       findings=findings, root=tmp_path, scope=None, definitions_root=ROOT)
    physical_warnings = [warning for warning in findings.warnings if 'physical reference' in warning['message']]
    assert bool(physical_warnings) == (wrong and observed), findings.warnings
    assert not findings.errors


def check_unknown_link_like_aws_data_is_not_inferred(tmp_path):
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    raw = '[a literal AWS string](foreign.md#something)'
    resolver.verify('Custom.Resource.Configuration.Text', raw, raw)
    assert resolver.metrics['referenceModelReads'] == 0
    with warned(resolver, 'no physical identification contract'):
        resolver.verify('Custom.Resource.Configuration.Text', raw, 'actual-id')


def check_packed_variable_roundtrip_and_tamper():
    from model.display import display_rows
    from design_layout import expanded_display_rows, HEADER, ALIGNMENT
    from service_rows import CODEBUILD_FORMAL_VARIABLE
    rows = [['009-' + str(i), CODEBUILD_FORMAL_VARIABLE + prop, '`' + json.dumps(value) + '`', '合成変数']
            for i, (prop, value) in enumerate([('Name', ['SECRET', 'PLAIN']), ('Type', ['SECRETS_MANAGER', 'PLAINTEXT']), ('Value', ['audit-secret:key', 'text'])])]
    rendered = display_rows('CodeBuild.Project', rows, ROOT, mode='IMPORT')
    assert '<!-- compact-source:' in rendered[0][3] and 'SECRETS_MANAGER' in rendered[0][3]
    lines = ['<a id="codebuild-audit"></a>', '### CodeBuild.Project: audit', HEADER, ALIGNMENT]
    lines += ['| ' + ' | '.join([str(i), *row[1:]]) + ' |' for i, row in enumerate(rendered, 1)]
    restored = expanded_display_rows(lines, ROOT, modes={'codebuild-audit': 'IMPORT'})
    assert all(any(row[2] in line for line in restored) for row in rows)
    changed = [line.replace('`audit-secret:key`', '`wrong-secret`') if line.startswith('| 1 |') else line for line in lines]
    with pytest.raises(ValueError, match='differs from source'):
        expanded_display_rows(changed, ROOT, modes={'codebuild-audit': 'IMPORT'})
    with pytest.raises(ValueError, match='requires IMPORT'):
        expanded_display_rows(lines, ROOT)



def check_packed_pipeline_configuration_roundtrip(tmp_path):
    from model.render import generate_markdown
    kind = 'CodePipeline.Pipeline'
    producer(tmp_path, 'CodeBuild.Project', {'Name': 'audit-build'})
    config = [[{'ProjectName': '[audit-build](codebuild.md#producer)', 'EnvironmentVariables': 'literal-json'}]]
    actual = [[{'ProjectName': 'audit-build', 'EnvironmentVariables': 'literal-json'}]]
    attrs = {'Name': 'pipeline-audit', 'Stages[].Actions[].ActionTypeId.Provider': json.dumps([['CodeBuild']]),
        'Stages[].Actions[].Configuration': json.dumps(config), 'Stages[].Actions[].Name': json.dumps([['Build']]),
        'Stages[].Name': json.dumps(['Build'])}
    source = values(kind, attrs, rid='009', anchor='codepipeline-audit')
    source.update({'desired.service.codepipeline.serviceId': 'codepipeline',
        'desired.service.codepipeline.ownedCatalogResourceTypes': kind, 'display.service.title': '# Pipeline',
        'display.resource.009.comment': '合成Pipeline', 'observed.row.009-003.value': json.dumps(actual),
        'desired.row.009-003.comment': 'ProjectName: 合成Build / EnvironmentVariables: 合成変数'})
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    resolver.verify_resource(source, '009')
    path = tmp_path / 'docs/designs/dev/cde/codepipeline.md'
    path.parent.mkdir(parents=True)
    first = generate_markdown(path, source, ROOT)
    path.write_text(first)
    assert '[audit-build](codebuild.md#producer)' in first
    from design_layout import expanded_display_rows
    normalized = expanded_display_rows(first.splitlines(), ROOT, modes={'codepipeline-audit': 'IMPORT'})
    assert any('literal-json' in line and '[audit-build](codebuild.md#producer)' in line for line in normalized)
    assert source['observed.row.009-003.value'] == json.dumps(actual)
    assert path.read_text() == first
    wrong = json.loads(json.dumps(config))
    wrong[0][0]['EnvironmentVariables'] = 'wrong'
    source['desired.row.009-003.value'] = '`' + json.dumps(wrong) + '`'
    with pytest.raises(ValueError, match='literal differs'):
        resolver.verify_resource(source, '009')



def check_native_cloudtrail_all_bucket_display():
    from model.display import display_rows
    from design_layout import expanded_display_rows, HEADER, ALIGNMENT
    prefix = 'CloudTrail.Trail.EventSelectors[].DataResources[].'
    rows = [['009-001', prefix + 'Type', '`[["AWS::S3::Object"]]`', '合成対象'],
            ['009-002', prefix + 'Values', '`[[["arn:aws:s3"]]]`', '合成対象']]
    rendered = display_rows('CloudTrail.Trail', rows, ROOT, mode='IMPORT')
    assert rendered[0][2] == '`All current and future S3 buckets`'
    lines = ['<a id="cloudtrail-audit"></a>', '### CloudTrail.Trail: audit', HEADER, ALIGNMENT]
    lines += ['| ' + ' | '.join([str(i), *row[1:]]) + ' |' for i, row in enumerate(rendered, 1)]
    restored = expanded_display_rows(lines, ROOT, modes={'cloudtrail-audit': 'IMPORT'})
    assert any(rows[1][2] in line for line in restored)



def check_native_array_literals_cannot_evade_matching_model(tmp_path):
    producer(tmp_path, 'S3.Bucket', {'BucketName': 'audit-bucket'})
    source = values('CloudTrail.Trail', {
        'EventSelectors[].DataResources[].Type': '[["AWS::S3::Object"]]',
        'EventSelectors[].DataResources[].Values': '[[["arn:aws:s3:::audit-bucket/"]]]'}, rid='009')
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    with warned(resolver, 'requires a reference link'):
        resolver.verify_resource(source, '009')
    # Old literals remain untouched when a producer is imported later.
    resolver.verify_resource(source, '009', require_links=False)


@pytest.mark.parametrize('reference', [
    '[group](cloudwatch-logs.md#producer)',
    '[missing](cloudwatch-logs.md#absent)',
    '[wrong type](s3.md#producer)',
    '[missing service](missing.md#producer)',
    '[foreign](../other/cloudwatch-logs.md#producer)',
])
def check_unobserved_link_requires_typed_target(tmp_path, reference):
    # A producer's logical identity is sufficient even without any physical identifier.
    producer(tmp_path, 'Logs.LogGroup', {'LogGroupName': '[group](#producer)'})
    producer(tmp_path, 'S3.Bucket', {'BucketName': 'audit-bucket'})
    source = values('CloudTrail.Trail', {'CloudWatchLogsLogGroupArn': 'unused'}, rid='009')
    source['desired.row.009-001.value'] = reference
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    if reference == '[group](cloudwatch-logs.md#producer)':
        with patch.object(resolver, 'match', side_effect=AssertionError('unobserved physical comparison')):
            resolver.verify_resource(source, '009', require_links=False, observed_only=True)
    else:
        with warned(resolver, 'no unique design target'):
            resolver.verify_resource(source, '009', require_links=False, observed_only=True)
    source['desired.row.009-001.property'] = 'CloudTrail.Trail.Unknown'
    with warned(resolver, 'no physical identification contract'):
        resolver.verify_resource(source, '009', require_links=False, observed_only=True)


@pytest.mark.parametrize('shape', ['scalar', 'array', 'document', 'configuration'])
def check_unobserved_structured_links_and_strict_import(tmp_path, shape):
    if shape == 'scalar':
        producer(tmp_path, 'Logs.LogGroup', {'LogGroupName': 'audit'})
        source = values('CloudTrail.Trail', {'CloudWatchLogsLogGroupArn': 'unused'}, rid='009')
        source['desired.row.009-001.value'] = '[group](cloudwatch-logs.md#producer)'
    elif shape in {'array', 'document'}:
        producer(tmp_path, 'EC2.Subnet', {'SubnetId': 'subnet-confirmed'})
        raw = ['[subnet](vpc.md#producer)', 'subnet-external']
        prop = 'VpcConfig.Subnets' if shape == 'array' else 'VpcConfig'
        source = values('CodeBuild.Project', {prop: json.dumps(raw if shape == 'array' else {'Subnets': raw})}, rid='009')
        if shape == 'document':
            source['desired.row.009-001.document'] = json.dumps({'Subnets': raw})
    else:
        producer(tmp_path, 'CodeBuild.Project', {'Name': 'audit-build'})
        source = values('CodePipeline.Pipeline', {
            'Stages[].Actions[].ActionTypeId.Provider': '[["CodeBuild"]]',
            'Stages[].Actions[].Configuration': '[[{"ProjectName":"[build](codebuild.md#producer)"}]]'}, rid='009')
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    snapshot = dict(source)
    resolver.verify_resource(source, '009', require_links=False, observed_only=True)
    assert source == snapshot
    invalid = {key: value.replace('#producer)', '#absent)') for key, value in source.items()}
    with warned(resolver, 'no unique design target'):
        resolver.verify_resource(invalid, '009', require_links=False, observed_only=True)
    for require_links in (True, False):
        with warned(resolver, 'differs from acquired physical reference'):
            resolver.verify_resource(source, '009', require_links=require_links)
    record = {'record': 'synthetic', 'identityProperty': None, 'identity': 'synthetic', 'properties': {}}
    with pytest.raises(ValueError, match='unacquired Property'):
        verify_values(Expansion({}, {}, {}), Expansion(source, {}, {}), {'009': record},
                      lambda _: {'type': 'string'}, resolver)
    for key in list(source):
        if key.startswith('desired.row.') and key.endswith('.value') and '[' in source[key]:
            source['observed.' + key.removeprefix('desired.')] = 'null'
    if shape == 'scalar':
        with warned(resolver, 'differs from acquired'):
            resolver.verify_resource(source, '009', require_links=False, observed_only=True)
    else:
        with pytest.raises(ValueError, match='structure differs|Configuration array dimensions differ'):
            resolver.verify_resource(source, '009', require_links=False, observed_only=True)


@pytest.mark.parametrize('physical', ['audit-bucket', 'wrong-bucket'])
def check_observed_comparison_in_design_and_import(tmp_path, physical):
    producer(tmp_path, 'S3.Bucket', {'BucketName': 'audit-bucket'})
    source = values('CloudTrail.Trail', {'S3BucketName': 'unused'}, rid='009')
    source['desired.row.009-001.value'] = '[bucket](s3.md#producer)'
    source['observed.row.009-001.value'] = physical
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    for kwargs in ({}, {'require_links': False}, {'require_links': False, 'observed_only': True}):
        if physical == 'audit-bucket':
            resolver.verify_resource(source, '009', **kwargs)
        else:
            with warned(resolver, 'differs from acquired physical reference'):
                resolver.verify_resource(source, '009', **kwargs)


def check_unobserved_local_and_identity_self_links(tmp_path):
    source = values('EC2.VPC', {'VpcId': 'unused'})
    source['desired.row.001-001.value'] = '[self](#producer)'
    source.update(values('EC2.Subnet', {'VpcId': 'unused'}, rid='009', anchor='consumer'))
    source['desired.row.009-001.value'] = '[vpc](#producer)'
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT, local={'vpc': Expansion(source, {}, {})})
    resolver.verify_resource(source, '001', require_links=False, observed_only=True)
    resolver.verify_resource(source, '009', require_links=False, observed_only=True)
    source['desired.row.009-001.value'] = '[absent](#missing)'
    with warned(resolver, 'no unique design target'):
        resolver.verify_resource(source, '009', require_links=False, observed_only=True)


@pytest.mark.parametrize('physical', ['PENDING_DEPLOY', 'vpc-confirmed', 'UNSET'])
def check_design_pending_observation_retains_target_guard(tmp_path, physical):
    producer(tmp_path, 'EC2.VPC', {'VpcId': physical})
    source = values('EC2.Subnet', {'VpcId': 'unused'}, rid='009')
    source['desired.row.009-001.value'] = '[vpc](vpc.md#producer)'
    source['observed.row.009-001.value'] = 'PENDING_DEPLOY'
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    if physical == 'PENDING_DEPLOY':
        resolver.verify_resource(source, '009', require_links=False, observed_only=True)
    else:
        with warned(resolver, 'differs from acquired physical reference'):
            resolver.verify_resource(source, '009', require_links=False, observed_only=True)
    with warned(resolver, 'differs from acquired physical reference'):
        resolver.verify_resource(source, '009')




def impact_fixture(root):
    producer(root, 'EC2.Subnet', {'SubnetId': 'subnet-confirmed', 'Name': 'private-subnet'})
    path = root / 'model/dev/cde/codebuild.properties'
    source = values('CodeBuild.Project', {'VpcConfig.Subnets': 'unused'}, rid='009', anchor='build')
    source.update(values('CodeBuild.Project', {'Name': 'sibling'}, rid='010', anchor='sibling'))
    source['desired.row.009-001.value'] = '[private-subnet](vpc.md#producer)'
    source['observed.row.009-001.value'] = 'subnet-confirmed'
    source['desired.row.010-001.value'] = '[build](#build)'
    for key, value in {'consumerKey': 'desired.row.009-001.value', 'text': source['desired.row.009-001.value'],
            'occurrence': '1', 'producerKind': 'resource', 'producerScope': 'dev/cde/vpc', 'producerId': '001',
            'resourceType': 'EC2.Subnet', 'format': 'link', 'labelPolicy': 'fixed'}.items():
        source['desired.reference.subnet.' + key] = value
    write_model(path, source)
    consumer = values('CodePipeline.Pipeline', {'RoleArn': 'unused'}, rid='003', anchor='pipeline')
    consumer['desired.row.003-001.value'] = '[build](codebuild.md#build)'
    write_model(root / 'model/dev/cde/codepipeline.properties', consumer)
    return path


@pytest.mark.parametrize('action', ['bind', 'replace'])
def check_saved_import_impact_analysis(tmp_path, action):
    from model.importing.cli import replacement_inputs
    from generation_inputs import GenerationInputs
    path = impact_fixture(tmp_path)
    snapshot = {p: p.read_bytes() for p in (tmp_path / 'model').rglob('*') if p.is_file()}
    with input_context(), restrict(('dev', 'cde', 'codebuild')), read_consumers({('dev', 'cde', 'codebuild')}):
        with closing(GenerationInputs(tmp_path)) as reads:
            before = load_for_edit(path, reads)
            impact = replacement_inputs(before, {'009': {'_action': action}}, reads)
            assert impact['inputs'] and impact['fileSets']
            impacts = [w for w in impact['warnings'] if w['code'] == 'reference.replace_impact']
            assert any(w['consumer'] == 'dev/cde/codebuild/010' for w in impacts)
            assert any(w['consumer'] == 'dev/cde/codepipeline/003' and w['producer'] == 'dev/cde/codebuild/009'
                       and w['consumer_key'] == 'desired.row.003-001.value' for w in impacts)
            assert load_for_edit(path, reads) is before
    assert snapshot == {p: p.read_bytes() for p in (tmp_path / 'model').rglob('*') if p.is_file()}


@pytest.mark.parametrize('permission_first', [False, True])
def check_preserved_analysis_cache_boundary(tmp_path, permission_first):
    from model.importing.scope import reference_reader
    path = impact_fixture(tmp_path)
    producer_path = path.with_name('vpc.properties')
    with input_context(), restrict(('dev', 'cde', 'codebuild')), read_consumers({('dev', 'cde', 'codebuild')}):
        before = load_for_edit(path)
        if not permission_first:
            with pytest.raises(ValueError, match='outside selected'):
                load_for_edit(producer_path)
        with reference_reader(producer_path):
            first = load_for_edit(producer_path)
            assert not first.warnings
            assert load_for_edit(producer_path) is first
        assert load_for_edit(path) is before
        assert before.authoritative['desired.row.009-001.value'] == '[private-subnet](vpc.md#producer)'
        with pytest.raises(ValueError, match='outside selected'):
            load_for_edit(producer_path)


@pytest.mark.parametrize('invalid', ['999', 'bad-id', 'wrong-type', 'undeclared'])
def check_impact_keeps_invalid_reference_diagnostics(tmp_path, invalid):
    from model.importing.cli import replacement_inputs
    from generation_inputs import GenerationInputs
    from model.format import serialize
    path = impact_fixture(tmp_path)
    fields = dict(load_for_edit(path).authoritative)
    field, value = ('consumerKey', 'desired.row.absent.value') if invalid == 'undeclared' else (
        ('resourceType', 'EC2.VPC') if invalid == 'wrong-type' else ('producerId', invalid))
    fields['desired.reference.subnet.' + field] = value
    path.write_text(serialize(fields), encoding='utf-8')
    with restrict(('dev', 'cde', 'codebuild')):
        if invalid == 'undeclared':
            with pytest.raises(ValueError, match='consumerKey|orphan row'):
                load_for_edit(path)
        else:
            with closing(GenerationInputs(tmp_path)) as reads:
                before = load_for_edit(path, reads)
                impact = replacement_inputs(before, {'009': {'_action': 'replace'}}, reads)
                assert any(w['code'] == 'reference.mismatch' for w in impact['warnings'])


def check_analysis_permission_restores_after_exception_and_foreign_scope(tmp_path):
    from model.importing.scope import reference_reader
    path = impact_fixture(tmp_path)
    producer_path = path.with_name('vpc.properties')
    with input_context(), restrict(('dev', 'cde', 'codebuild')), read_consumers({('dev', 'cde', 'codebuild')}):
        with pytest.raises(RuntimeError, match='analysis failed'):
            with reference_reader(producer_path):
                assert load_for_edit(producer_path).authoritative
                for foreign in (tmp_path / 'model/stg/cde/codebuild.properties', tmp_path / 'model/dev/other/codebuild.properties'):
                    with pytest.raises(ValueError, match='outside selected'):
                        load_for_edit(foreign)
                raise RuntimeError('analysis failed')
        with pytest.raises(ValueError, match='outside selected'):
            load_for_edit(producer_path)



@pytest.mark.parametrize('action', ['bind', 'replace'])
def check_review_runs_saved_reference_impact(tmp_path, action):
    from datetime import datetime, timezone
    from generation_inputs import GenerationInputs
    from model.importing.cli import replacement_inputs
    from model.importing.approval import build_review
    path = impact_fixture(tmp_path)
    with input_context(), closing(GenerationInputs(tmp_path)) as reads:
        before = load_for_edit(path, reads)
        impact = replacement_inputs(before, {'009': {'_action': action}}, reads)
        acquisition = {'version': 3, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1,
            'task': 'tasks/import-fixture.md', 'root': str(tmp_path), 'scope': ['dev', 'cde', 'codebuild'],
            'connection': {'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1'},
            'acquiredAt': datetime.now(timezone.utc).isoformat(), 'sources': impact['inputs'],
            'records': [], 'inventory': {'CodeBuild.Project': {'status': 'complete'}}}
        review = build_review(acquisition, {'resources': [], 'excluded': [], 'unreflected': []}, before,
            dict(before.authoritative), {}, lambda _: {'type': 'string'}, reference_impact=impact)
        assert any(w.get('consumer') == 'dev/cde/codepipeline/003' for w in review['referenceImpact']['warnings'])
        assert review['referenceImpact']['inputs'] == impact['inputs']

def check_preserved_read_does_not_authorize_writes(tmp_path):
    from model.references import incoming
    path = impact_fixture(tmp_path)
    with restrict(('dev', 'cde', 'codebuild')):
        before = load_for_edit(path)
        assert incoming(before, '009')
        fields = {**before.authoritative, 'desired.row.010-001.comment': 'changed'}
        with pytest.raises(ValueError, match='unselected Resource'):
            verify_values(before, Expansion(fields), {}, lambda _: {'type': 'string'})


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
