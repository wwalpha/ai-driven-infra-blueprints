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

from import_references import Resolver
from import_sources import verify_values, property_values
from import_scope import restrict, read_consumers, new_references
from model_templates import Expansion, load_for_edit, json_text
from model_core import entries, literal
from reference_contracts import contract
from support.model_sources import write_model
from validation_cache import input_context

ROOT = Path(__file__).resolve().parents[4]


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
    write_model(path, {**(previous or {}), **values(kind, attributes, rid, mode, anchor)})
    return service, path


CASES = [
    ('CloudTrail.Trail.S3BucketName', 'S3.Bucket', {'BucketName': 'audit-bucket'}, 'audit-bucket'),
    ('KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN', 'S3.Bucket', {'BucketName': 'audit-bucket'}, 'arn:aws:s3:::audit-bucket'),
    ('EC2.SecurityGroup.VpcId', 'EC2.VPC', {'VpcId': 'vpc-confirmed'}, 'vpc-confirmed'),
    ('CodeBuild.Project.VpcConfig.Subnets[]', 'EC2.Subnet', {'SubnetId': 'subnet-confirmed'}, 'subnet-confirmed'),
    ('Lambda.Function.VpcConfig.SecurityGroupIds[]', 'EC2.SecurityGroup', {'GroupId': 'sg-confirmed'}, 'sg-confirmed'),
    ('Glue.Job.Role', 'IAM.Role', {'RoleName': 'glue-role'}, 'glue-role'),
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
            with pytest.raises(ValueError, match='requires a reference link'):
                resolver.verify(prop, '`' + raw + '`', raw)
        else:
            resolver.verify(prop, '`' + raw + '`', raw)
            with pytest.raises(ValueError, match='differs from acquired'):
                resolver.verify(prop, '[label](s3.md#producer)', raw)


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
    with pytest.raises(ValueError, match='differs from acquired'):
        resolver.verify('EC2.SecurityGroup.VpcId', '[wrong](vpc.md#other)', 'vpc-confirmed')
    with pytest.raises(ValueError, match='differs from acquired'):
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
    with pytest.raises(ValueError, match='differs from acquired physical reference'):
        verify_values(before, Expansion(wrong, {}, {}), {'009': record}, lambda _: {'type': 'string'}, resolver)
    assert property_values(new, '009', prop, {'type': 'string'}) == record['properties'][prop]['value']


def check_observed_and_reused_index(tmp_path):
    import model_templates
    observed = values('EC2.VPC', {'VpcId': 'PENDING_DEPLOY'})
    observed['desired.row.001-001.value'] = '[Producer](#producer)'
    observed['observed.row.001-001.value'] = 'vpc-confirmed'
    write_model(tmp_path / 'model/dev/cde/vpc.properties', observed)
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    with input_context(), patch.object(model_templates, 'parse_template', wraps=model_templates.parse_template) as parse:
        for _ in range(20):
            assert resolver.match('EC2.SecurityGroup.VpcId', 'vpc-confirmed')
        assert parse.call_count == 1
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
        with pytest.raises(ValueError, match='differs from acquired'):
            resolver.verify(prop, reference, 'PENDING_DEPLOY', require_links=False)
    for wrong in ('[missing](vpc.md#absent)', '[foreign](../other/vpc.md#producer)',
                  '[wrong type](subnet.md#producer)'):
        with pytest.raises(ValueError, match='differs from acquired'):
            resolver.verify(prop, wrong, 'PENDING_DEPLOY', require_links=False)
    with pytest.raises(ValueError, match='differs from acquired'):
        resolver.verify(prop, reference, 'PENDING_DEPLOY')
    with pytest.raises(ValueError, match='no physical identification contract'):
        resolver.verify('Unknown.Resource.Value', reference, 'PENDING_DEPLOY', require_links=False)


def check_append_only_and_later_import(tmp_path):
    prop = 'CloudTrail.Trail.S3BucketName'
    old = values('CloudTrail.Trail', {'S3BucketName': 'audit-bucket'})
    expansion = Expansion(old, {}, {})
    producer(tmp_path, 'S3.Bucket', {'BucketName': 'audit-bucket'})
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    assert verify_values(expansion, expansion, {}, lambda _: {'type': 'string'}, resolver) == []
    changed = {**old, 'desired.row.001-001.value': '[audit-bucket](s3.md#producer)'}
    with pytest.raises(ValueError, match='existing expanded value'):
        verify_values(expansion, Expansion(changed, {}, {}), {}, lambda _: {'type': 'string'}, resolver)
    assert old['desired.row.001-001.value'] == '`audit-bucket`'



def check_selected_new_import_can_resolve_only_its_declared_producer(tmp_path):
    producer(tmp_path, 'EC2.Subnet', {'SubnetId': 'subnet-confirmed', 'Name': 'private-subnet'})
    path = tmp_path / 'model/dev/cde/codebuild.properties'
    write_model(path, {'desired.service.codebuild.serviceId': 'codebuild'})
    before = load_for_edit(path)
    producer_before = producer_snapshot(tmp_path, 'vpc')
    template = tmp_path / 'model/templates/cde/codebuild.properties.tpl'
    directory = tmp_path / 'model/parameters/dev/cde/codebuild'
    declaration = {'type': 'reference', 'description': '参照Subnet', 'required': True, 'service': 'vpc', 'resourceType': 'EC2.Subnet'}
    block = ['# definition: Project', '# parameter: Subnet ' + json_text(declaration),
        '# resource: project', '# row: subnet project',
        'desired.resource.project.resourceType=CodeBuild.Project',
        'desired.resource.project.anchor=codebuild-new', 'desired.resource.project.resourceMode=IMPORT',
        'desired.row.subnet.property=CodeBuild.Project.VpcConfig.Subnets',
        'desired.row.subnet.value=<<Subnet>>', 'desired.row.subnet.comment=参照Subnet', '# end-definition', '']
    binding = json.loads((directory / 'bindings.json').read_text())
    binding['instances']['new-project'] = {'definition': 'Project', 'resources': {'project': '009'},
        'rows': {'subnet': '009-001'}, 'parameters': {}}
    output = {template: template.read_text() + '\n'.join(block),
        directory / 'parameters.yaml': 'instances:\n  new-project:\n    parameters:\n      Subnet: "001"\n',
        directory / 'bindings.json': json_text(binding),
        directory / 'observed.json': json_text({'version': 1, 'values': {'observed.row.009-001.value': 'subnet-confirmed'}})}
    with restrict(('dev', 'cde', 'codebuild')), read_consumers({('dev', 'cde', 'codebuild')}):
        assert load_for_edit(path, output).values['desired.row.009-001.value'] == '<<Subnet>>'
        with new_references(before, {'009': {}}):
            candidate = load_for_edit(path, output)
        assert candidate.values['desired.row.009-001.value'] == '[private-subnet](vpc.md#producer)'

        choice = dict(output)
        text = choice[template].replace('# resource: project',
            '# parameter: UseLink ' + json_text({'type': 'boolean', 'description': '参照の選択', 'required': True}) + '\n'
            + '# parameter: LiteralSubnet ' + json_text({'type': 'string', 'description': 'Subnet実値', 'required': True, 'format': 'literal'}) + '\n'
            + '# choice: desired.row.subnet.value ' + json_text({'parameter': 'UseLink', 'value': '<<Subnet>>'}) + '\n# resource: project')
        choice[template] = text.replace('desired.row.subnet.value=<<Subnet>>', 'desired.row.subnet.value=<<LiteralSubnet>>')
        choice.pop(directory / 'observed.json')
        choice[directory / 'parameters.yaml'] = 'instances:\n  new-project:\n    parameters:\n      UseLink: false\n      LiteralSubnet: subnet-external\n'
        with new_references(before, {'009': {}}):
            assert load_for_edit(path, choice).values['desired.row.009-001.value'] == 'subnet-external'
            assert load_for_edit(path, choice, display=True).values['desired.row.009-001.value'] == '`subnet-external`'
        choice[directory / 'parameters.yaml'] = 'instances:\n  new-project:\n    parameters:\n      UseLink: true\n      Subnet: "001"\n'
        choice[directory / 'observed.json'] = output[directory / 'observed.json']
        with new_references(before, {'009': {}}):
            assert load_for_edit(path, choice).values['desired.row.009-001.value'] == '[private-subnet](vpc.md#producer)'
        with pytest.raises(ValueError, match='selected new Resource IDs'):
            with new_references(candidate, {'009': {}}):
                pass
    assert producer_snapshot(tmp_path, 'vpc') == producer_before


def producer_snapshot(root, service):
    return {p: p.read_bytes() for p in (root / 'model/parameters/dev/cde' / service).iterdir()}


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
    from model_display import display_rows
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
    from model_design import generate_markdown
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


def check_role_arn_requires_account_and_explicit_path(tmp_path):
    prop = 'Lambda.Function.Role'
    producer(tmp_path, 'IAM.Role', {'RoleName': 'runner', 'Path': '/service-role/'})
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    assert resolver.match(prop, 'arn:aws:iam::123456789012:role/service-role/runner')
    assert resolver.match(prop, 'arn:aws:iam::123456789012:role/runner') is None
    assert resolver.match(prop, 'arn:aws:iam::999999999999:role/service-role/runner') is None



@pytest.mark.parametrize('wrong', [False, True])
def check_design_link_validation_uses_physical_identity(tmp_path, wrong):
    from types import SimpleNamespace
    from model_design import generate_markdown
    from model_projection import identifier_outputs
    from design_document import DesignIndex
    from validation.design_links import check_design_links
    source = values('KinesisFirehose.DeliveryStream', {'DeliveryStreamName': 'audit', 'S3DestinationConfiguration.BucketARN': 'unused'}, rid='009', anchor='data-firehose-audit')
    source.update({'desired.service.data-firehose.serviceId': 'data-firehose',
        'desired.service.data-firehose.ownedCatalogResourceTypes': 'KinesisFirehose.DeliveryStream',
        'display.service.title': '# Firehose', 'display.resource.009.comment': '合成入力',
        'desired.row.009-002.value': '[audit-bucket](s3.md#producer)',
        'observed.row.009-002.value': '`arn:aws:s3:::audit-bucket`'})
    bucket = values('S3.Bucket', {'BucketName': 'other-bucket' if wrong else 'audit-bucket'})
    bucket.update({'desired.service.s3.serviceId': 's3', 'desired.service.s3.ownedCatalogResourceTypes': 'S3.Bucket',
                   'display.service.title': '# S3', 'display.resource.001.comment': '合成入力'})
    write_model(tmp_path / 'model/dev/cde/s3.properties', bucket)
    write_model(tmp_path / 'model/dev/cde/data-firehose.properties', source)
    document = tmp_path / 'docs/designs/dev/cde/data-firehose.md'
    document.parent.mkdir(parents=True)
    document.write_text(generate_markdown(document, source, ROOT))
    (document.parent / 's3.md').write_text(generate_markdown(document.parent / 's3.md', bucket, ROOT))
    errors = []
    findings = SimpleNamespace(check=lambda condition, message: errors.append(message) if not condition else None,
                               relative=lambda path: str(path.relative_to(tmp_path)), canonical_root=tmp_path)
    check_design_links(identifier_outputs(ROOT), [document], design_index=DesignIndex(ROOT), design_sources={document: source},
                       findings=findings, root=tmp_path, scope=None, definitions_root=ROOT)
    physical_errors = [error for error in errors if 'physical reference' in error]
    assert bool(physical_errors) == wrong, errors
    if not wrong:
        assert not errors, errors


def check_unknown_link_like_aws_data_is_not_inferred(tmp_path):
    resolver = Resolver(tmp_path, 'dev', 'cde', definitions_root=ROOT)
    raw = '[a literal AWS string](foreign.md#something)'
    resolver.verify('Custom.Resource.Configuration.Text', raw, raw)
    assert resolver.metrics['referenceModelReads'] == 0
    with pytest.raises(ValueError, match='no physical identification contract'):
        resolver.verify('Custom.Resource.Configuration.Text', raw, 'actual-id')


def check_packed_variable_roundtrip_and_tamper():
    from model_display import display_rows
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
    from model_design import generate_markdown
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
    from model_display import display_rows
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
    with pytest.raises(ValueError, match='requires a reference link'):
        resolver.verify_resource(source, '009')
    # Old literals remain untouched when a producer is imported later.
    resolver.verify_resource(source, '009', require_links=False)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
