"""Offline fixed identity allocation checks; no project or AWS inputs."""

import json
import sys
import tempfile
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import model.projection as _imports_model_projection
import model.render as _imports_model_render
import model.sources as _imports_model_sources
import model.sources as sources
import utils.json_format as _imports_utils_json_format
import validation.design_links as _imports_validation_design_links
from model.adapters.aws import Resource
from model.core import entries
from model.format import serialize
from model.identity import (
    COUNTERS,
    Resolver,
    allocate,
    parse_reference,
    preserve_allocation,
    resource_index,
)
from model.projection import document_references, execution_document
from model.sources import Scope
from model.validation import validate_resource_identities
from utils.aws_mappings import mapping_alias
from validation.findings import Findings

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

_CALLBACK_DEFAULT = object()



def rejects(function):
    try:
        function()
    except (ValueError, KeyError):
        return
    raise AssertionError('invalid identity accepted')


def main():
    values = {COUNTERS: '{"EC2.VPC":999}'}
    for i in range(500):
        values[f'desired.resource.{i:03d}.resourceType'] = 'EC2.VPC'
    assigned = allocate(values, [f'{i:03d}' for i in range(500)])
    assert len(resource_index(assigned)) == 500
    assert assigned['desired.resource.000.logicalId'] == 'EC2_VPC_1000'
    assert assigned['desired.resource.499.logicalId'] == 'EC2_VPC_1499'
    preserve_allocation({COUNTERS: '{"EC2.VPC":999}'}, assigned)
    deleted = {key: value for key, value in assigned.items() if not key.startswith('desired.resource.499.')}
    preserve_allocation(assigned, deleted)
    deleted['desired.resource.500.resourceType'] = 'EC2.VPC'
    added = allocate(deleted, ['500'])
    assert added['desired.resource.500.logicalId'] == 'EC2_VPC_1500'
    preserve_allocation(assigned, added)
    rejects(lambda: allocate(assigned, ['000']))
    rejects(lambda: resource_index({**assigned, 'desired.resource.001.logicalId': 'EC2_VPC_1000'}))
    rejects(lambda: resource_index({**assigned, COUNTERS: '{}'}))
    rejects(lambda: preserve_allocation(assigned, {**assigned, 'desired.resource.000.logicalId': 'EC2_VPC_2000'}))
    for invalid in ['resource://dev/../vpc/EC2_VPC_001', 'resource://dev/cde/vpc/EC2_VPC_001#x', 'https://dev/cde/vpc/EC2_VPC_001']:
        rejects(lambda *, invalid=invalid: parse_reference(invalid, Scope(Path('/synthetic'), 'test', 'team', 'vpc')))
    assert parse_reference('[vpc](#anchor)', Scope(Path('/synthetic'), 'test', 'team', 'vpc')) == ('test', 'team', 'vpc', 'anchor')
    print('fixed identity allocation: PASS')


def check_snapshots():

    with tempfile.TemporaryDirectory() as directory:
        old, new = Path(directory) / 'before', Path(directory) / 'after'
        scopes = ['qa/one/vpc', 'qa/two/vpc', 'live/one/vpc']
        project = {'projectName': 'synthetic', 'targets': [
            {'environment': env, 'alias': alias, 'awsAccountId': '123456789012',
             'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}
            for env, alias in [('qa', 'one'), ('qa', 'two'), ('live', 'one')]]}
        for root in (old, new):
            root.mkdir()
            (root / 'project.json').write_text(json.dumps(project), encoding='utf-8')
        for scope in scopes:
            values = {'desired.service.vpc.serviceId': 'vpc'}
            for i in range(500):
                values.update({f'desired.resource.{i:03d}.resourceType': 'EC2.VPC',
                               f'desired.resource.{i:03d}.logicalId': 'old-' + str(i),
                               f'desired.resource.{i:03d}.anchor': 'anchor-' + str(i),
                               f'desired.resource.{i:03d}.resourceMode': 'IMPORT'})
            values.update({'desired.row.000-001.property': 'EC2.VPC.VpcId',
                           'desired.row.000-001.value': '[existing](#anchor-0)',
                           'desired.row.000-001.comment': 'unchanged',
                           'observed.row.000-001.value': '`vpc-fixed`'})
            after = {key: value for key, value in values.items() if not key.endswith('.logicalId')}
            after = allocate(after, [f'{i:03d}' for i in range(500)])
            after['desired.row.000-001.value'] = '[existing](#anchor-0)'
            for root, data in [(old, after), (new, after)]:
                path = root / 'model' / (scope + '.properties')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(serialize(data), encoding='utf-8')
        resolver = Resolver(new)
        with patch.object(sources, '_read_model', wraps=sources._read_model) as read:
            for i in range(500):
                snapshot, number, resource = resolver.resolve('[existing](#anchor-' + str(i) + ')', Scope(new, 'qa', 'one', 'vpc'))
                assert number == f'{i:03d}'
            assert read.call_count == 1, read.call_count
        assert resolver.resolve('[existing](../two/vpc.md#anchor-0)', Scope(new, 'qa', 'one', 'vpc'))[0].scope.target == 'two'
        assert resolver.resolve('[existing](../../live/one/vpc.md#anchor-0)', Scope(new, 'qa', 'one', 'vpc'))[0].scope.environment == 'live'
        rejects(lambda: resolver.resolve('[existing](../../unknown/one/vpc.md#anchor-0)', Scope(new, 'qa', 'one', 'vpc')))
        print('baseline preservation and 500 indexed resolutions: PASS')


if __name__ == '__main__':
    main()
    check_snapshots()


def check_cfn_and_outputs():

    execution_document = _imports_model_projection.execution_document
    reference_display = _imports_model_projection.reference_display
    framework = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory() as directory:
        before, after = Path(directory).resolve() / 'before', Path(directory).resolve() / 'after'
        old = {'desired.resource.007.resourceType': 'EC2.VPC', 'desired.resource.007.logicalId': 'ExistingVpc',
               'desired.resource.007.anchor': 'network', 'desired.resource.007.resourceMode': 'CREATE'}
        new = allocate({key: value for key, value in old.items() if not key.endswith('.logicalId')}, ['007'])
        new['desired.resource.007.cfn-logicalId'] = 'existing-stack-ExistingVpc'
        stacks = {'desired.stack.004.name': 'existing-stack', 'desired.stack.004.template': 'network.yaml',
                  'desired.stack.004.parameters': 'network.json', 'desired.stack.004.deployOrder': '1',
                  'desired.stack.004.placementName': 'unchanged'}
        for root, values in ((before, old), (after, new)):
            root.mkdir()
            (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'qa', 'alias': 'team',
                'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
            files = {'model/qa/team/vpc.properties': serialize(values),
                     'model/qa/team/cloudformation-stacks.properties': serialize(stacks),
                     'infra/cloudformation/templates/team/network.yaml': 'Resources:\n  ExistingVpc:\n    Type: AWS::EC2::VPC\n    Properties:\n      CidrBlock: 10.0.0.0/16\n',
                     'infra/cloudformation/parameters/qa/team/network.json': '[]'}
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
        with mapping_alias(framework, before), mapping_alias(framework, after):
            missing = {key: value for key, value in new.items() if not key.endswith('.cfn-logicalId')}
            rejects(lambda: validate_resource_identities(after / 'docs/designs/qa/team/vpc.md', missing, after, list(entries(missing, 'desired.resource.')), definitions_root=framework))
            bucket = {'desired.service.s3.serviceId': 's3', 'desired.service.s3.ownedCatalogResourceTypes': 'S3.Bucket',
                      'display.service.title': '# Buckets', 'display.resource.007.comment': 'confirmed',
                      'desired.resource.007.resourceType': 'S3.Bucket', 'desired.resource.007.resourceMode': 'IMPORT',
                      'desired.row.007-001.property': 'S3.Bucket.BucketName', 'desired.row.007-001.value': '`physical-bucket`',
                      'desired.row.007-001.comment': 'literal stays literal'}
            bucket['desired.resource.007.anchor'] = 'saved-bucket'
            bucket = allocate(bucket, ['007'])
            path = after / 'model/qa/team/s3.properties'
            path.write_text(serialize(bucket))
            uri = '[bucket](s3.md#saved-bucket)'
            document = {'Statement': [{'Resource': {'$resource': uri, '$attribute': 'Arn'}, 'Effect': 'Allow'}]}
            saved = path.read_bytes()
            result = execution_document(document, after, scope=Scope(after, 'qa', 'team', 'iam'))
            assert path.read_bytes() == saved
            assert 'arn:' not in saved.decode('utf-8')
            assert result['Statement'][0]['Resource'] == 'arn:aws:s3:::physical-bucket'
            assert 'resource://' not in json.dumps(result)
            assert document['Statement'][0]['Resource']['$resource'] == uri
            assert execution_document(uri, after, scope=Scope(after, 'qa', 'team', 'iam'), property_name='CloudTrail.Trail.S3BucketName') == 'physical-bucket'
            rejects(lambda: execution_document({'Statement': [{'Resource': uri}]}, after, scope=Scope(after, 'qa', 'team', 'iam')))
            displayed = reference_display(bucket, after / 'docs/designs/qa/team/s3.md', after, definitions_root=framework)
            assert displayed['desired.resource.007.anchor'] == 'saved-bucket'
            assert displayed == bucket
            assert bucket['desired.row.007-001.value'] == '`physical-bucket`'
            assert bucket['desired.resource.007.anchor'] == 'saved-bucket'
            renamed = {**bucket, 'desired.row.007-001.value': '`renamed-bucket`'}
            renamed_display = reference_display(renamed, after / 'docs/designs/qa/team/s3.md', after, definitions_root=framework)
            assert renamed_display == renamed
            generate_files = _imports_model_render.generate_files
            runtime_values = _imports_model_sources.runtime_values
            policy = allocate({
                'desired.service.iam.serviceId': 'iam',
                'desired.service.iam.ownedCatalogResourceTypes': 'IAM.ManagedPolicy',
                'display.service.title': '# Policies',
                'desired.resource.009.resourceType': 'IAM.ManagedPolicy',
                'desired.resource.009.resourceMode': 'IMPORT',
                'desired.resource.009.anchor': 'saved-policy',
                'display.resource.009.comment': 'policy fixture',
                'desired.row.009-001.property': 'IAM.ManagedPolicy.ManagedPolicyName',
                'desired.row.009-001.value': '`policy-fixture`',
                'desired.row.009-001.comment': 'unchanged name',
                'desired.row.009-002.property': 'IAM.ManagedPolicy.PolicyDocument',
                'desired.row.009-002.value': '[Policy](iam/policy.json)',
                'desired.row.009-002.comment': 'confirmed policy',
                'desired.row.009-002.document': json.dumps(document),
            }, ['009'])
            design = after / 'docs/designs/qa/team/iam.md'
            # Definitions are redirected using the same alias as a staged consumer.

            renderer = _imports_model_render
            original_markdown = renderer.generate_markdown
            with patch.object(renderer, 'generate_markdown',
                              lambda path, values, root: original_markdown(path, values, framework)):
                rejects(lambda: generate_files(design, runtime_values(policy), after))
                # A separate literal fixture exercises valid JSON artifact generation.
                literal_policy = {**policy, 'desired.row.009-002.document': json.dumps(result)}
                files = generate_files(design, runtime_values(literal_policy), after)
            assert json.loads(files[design.with_suffix('') / 'policy.json']) == result
            assert 'resource://' not in files[design]
            assert '<a id="saved-policy"></a>' in files[design]
            assert json.loads(policy['desired.row.009-002.document']) == document
            document_sha256 = _imports_utils_json_format.document_sha256
            display = reference_display(policy, design, after)
            assert display['desired.row.009-002.artifactSha256'] == document_sha256(result)
            assert 'artifactSha256' not in serialize(policy)
            assert path.read_bytes() == saved
            assert 'arn:' not in serialize(policy)
            check_json_references(after, framework, bucket, policy, files)


    target = SimpleNamespace(kind='S3.Bucket',
        ctx=SimpleNamespace(require_resource_scope=lambda resource: None),
        rows_for=lambda prop: [('007-001', {'value': '`physical-bucket`'})],
        value=lambda prop: 'physical-bucket', identity=lambda mode: 'resolved-' + mode)
    consumer = object.__new__(Resource)
    consumer.reference = lambda uri: target
    assert consumer.resolve_json({'$resource': uri, '$attribute': 'Arn'}) == 'resolved-arn'
    assert consumer.resolve_json({'$resource': uri, '$attribute': 'BucketName'}) == 'physical-bucket'
    print('CFn correspondence and output projections: PASS')


def _callback_check_json_references_save(producer, /, values):
    producer.write_text(serialize(values), encoding='utf-8')


def _callback_check_json_references_links_344(check_design_links, design, framework, root, _default_values, /, values=_CALLBACK_DEFAULT):
    if values is _CALLBACK_DEFAULT:
        values = _default_values
    findings = Findings(root)
    check_design_links({}, [design], design_sources={design: values}, findings=findings,
                       root=root, scope=None, definitions_root=framework)
    return findings


def _callback_check_json_references_resolve_245(root, scope, _default_value, _default_field, /, value=_CALLBACK_DEFAULT, field=_CALLBACK_DEFAULT):
    if value is _CALLBACK_DEFAULT:
        value = _default_value
    if field is _CALLBACK_DEFAULT:
        field = _default_field
    return execution_document(value, root, scope=scope, property_name=field)


def check_json_references(root, framework, bucket, policy, artifacts):
    """Independent authorities exercise semantic checks separately from artifacts."""

    check_design_links = _imports_validation_design_links.check_design_links
    scope = Scope(root, 'qa', 'team', 'iam')
    producer = root / 'model/qa/team/s3.properties'
    design = root / 'docs/designs/qa/team/iam.md'
    uri = '[bucket](s3.md#saved-bucket)'
    operand = {'$resource': uri, '$attribute': 'Arn'}
    original = producer.read_bytes()
    project = (root / 'project.json').read_bytes()

    resolve = _bind_framework_callback(_callback_check_json_references_resolve_245, root, scope, operand, None)

    save = _bind_framework_callback(_callback_check_json_references_save, producer)

    with patch('botocore.session.Session.create_client', side_effect=AssertionError('AWS forbidden')):
        assert document_references(operand, root, scope=scope) == operand
        for name in ['UPPER', 'ab', 'bad/name', 'bad*name', 'has..dots', '192.168.1.1', 'bad--x-s3',
                     'xn--reserved', 'UNSET', 'PENDING_DEPLOY', 'TBD', '${BucketName}', '[label](#saved-bucket)']:
            save({**bucket, 'desired.row.007-001.value': name})
            assert document_references(operand, root, scope=scope) == operand
            rejects(resolve)
        for value in ['', 'PENDING_DEPLOY', 'UNSET']:
            save({**bucket, 'observed.row.007-001.value': value})
            rejects(resolve)
        save({**bucket, 'desired.row.007-002.property': 'S3.Bucket.BucketName',
              'desired.row.007-002.value': 'PENDING_DEPLOY', 'desired.row.007-002.comment': 'duplicate'})
        rejects(resolve)
        save({key: value for key, value in bucket.items() if not key.startswith('desired.row.')})
        rejects(resolve)
        save(bucket)
        for attribute in ['NoSuchAttribute', 'ObjectArn']:
            rejects(lambda *, attribute=attribute: resolve({'$resource': uri, '$attribute': attribute}))
        for value in [{'$resource': '[missing](s3.md#absent)', '$attribute': 'Arn'},
                      {'$resource': '[missing](missing.md#absent)', '$attribute': 'Arn'},
                      {'$resource': uri, '$attribute': None}, {'$resource': uri, '$attribute': 1},
                      {'$resource': 1, '$attribute': 'Arn'}, {'$resource': uri, 'extra': True},
                      {'$attribute': 'Arn'}]:
            rejects(lambda *, value=value: resolve(value))
        rejects(lambda: resolve(operand, 'Lambda.Function.Role'))
        wrong_kind = allocate({**{key: value for key, value in bucket.items()
                                  if not key.endswith('.logicalId') and key != COUNTERS},
                               'desired.resource.007.resourceType': 'EC2.VPC'}, ['007'])
        save(wrong_kind)
        rejects(resolve)
        save(bucket)
        rejects(lambda: resolve({'$resource': uri, '$attribute': 'BucketName'},
                                'KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN'))
        duplicate = allocate({**bucket, 'desired.resource.008.resourceType': 'S3.Bucket',
                              'desired.resource.008.anchor': 'saved-bucket'}, ['008'])
        save(duplicate)
        rejects(resolve)
        save(bucket)
        assert resolve(uri, 'CloudTrail.Trail.S3BucketName') == 'physical-bucket'
        # The producer's target supplies context, even for a cross-target consumer.
        topology = json.loads(project)
        other = {**topology['targets'][0], 'alias': 'other', 'awsAccountId': '222222222222',
                 'awsExecutionAccountId': '333333333333', 'awsRegion': 'cn-north-1'}
        topology['targets'].append(other)
        (root / 'project.json').write_text(json.dumps(topology), encoding='utf-8')
        for region, partition in [('ap-northeast-1', 'aws'), ('cn-north-1', 'aws-cn'),
                                  ('us-gov-west-1', 'aws-us-gov')]:
            topology['targets'][0]['awsRegion'] = region
            (root / 'project.json').write_text(json.dumps(topology), encoding='utf-8')
            assert resolve() == f'arn:{partition}:s3:::physical-bucket'
        topology['targets'][0]['awsRegion'] = 'unknown-north-1'
        (root / 'project.json').write_text(json.dumps(topology), encoding='utf-8')
        rejects(resolve)
        cases = [
            ('KMS.Key', 'kms', {'KeyId': '12345678-1234-1234-1234-123456789012'},
             'kms:cn-north-1:333333333333:key/12345678-1234-1234-1234-123456789012'),
            ('KMS.Key', 'kms', {'KeyId': 'mrk-' + 'a' * 32}, 'kms:cn-north-1:333333333333:key/mrk-' + 'a' * 32),
            ('KMS.Alias', 'kms', {'AliasName': 'alias/audit'}, 'kms:cn-north-1:333333333333:alias/audit'),
            ('IAM.Role', 'iam', {'RoleName': 'audit-role', 'Path': '/service-role/'},
             'iam::333333333333:role/service-role/audit-role'),
            ('Lambda.Function', 'lambda', {'FunctionName': 'audit-function'},
             'lambda:cn-north-1:333333333333:function:audit-function'),
            ('Logs.LogGroup', 'cloudwatch-logs', {'LogGroupName': '/audit/logs'},
             'logs:cn-north-1:333333333333:log-group:/audit/logs'),
        ]
        for kind, service, fields, suffix in cases:
            values = {'desired.resource.001.resourceType': kind, 'desired.resource.001.anchor': 'producer',
                      'desired.resource.001.resourceMode': 'IMPORT'}
            for index, (attribute, raw) in enumerate(fields.items(), 1):
                prefix = f'desired.row.001-{index:03d}.'
                values.update({prefix + 'property': kind + '.' + attribute, prefix + 'value': raw,
                               prefix + 'comment': 'synthetic identifier'})
            values = allocate(values, ['001'])
            path = root / 'model/qa/other' / (service + '.properties')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialize(values), encoding='utf-8')
            ref = {'$resource': '[producer](../other/' + service + '.md#producer)', '$attribute': 'Arn'}
            assert resolve(ref) == 'arn:aws-cn:' + suffix
            assert 'arn:' not in path.read_text(encoding='utf-8')
            pending = {**values, 'observed.row.001-001.value': 'PENDING_DEPLOY'}
            path.write_text(serialize(pending), encoding='utf-8')
            assert document_references(ref, root, scope=scope) == ref
            rejects(lambda *, ref=ref: resolve(ref))
            path.write_text(serialize({**values, 'desired.row.001-001.value': 'invalid:*'}), encoding='utf-8')
            rejects(lambda *, ref=ref: resolve(ref))
        (root / 'project.json').write_bytes(project)
        for path, content in artifacts.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        bucket_design = design.with_name('s3.md')
        bucket_design.write_text('# Buckets\n\n<a id="saved-bucket"></a>\n\n### S3.Bucket: physical-bucket\n', encoding='utf-8')
        document = json.loads(policy['desired.row.009-002.document'])
        create_policy = {**policy, 'desired.resource.009.resourceMode': 'CREATE'}

        links = _bind_framework_callback(_callback_check_json_references_links_344, check_design_links, design, framework, root, create_policy)

        save({**bucket, 'desired.row.007-001.value': 'PENDING_DEPLOY'})
        # A link-only check must never call either execution projection entrypoint.
        with patch('model.projection.execution_document', side_effect=AssertionError('physical resolution forbidden')), \
             patch('model.projection.reference_display', side_effect=AssertionError('physical display forbidden')):
            valid = links()
            assert not valid.errors and not valid.warnings, (valid.errors, valid.warnings)
        rejects(lambda: resolve(document))
        bad = {**create_policy, 'desired.row.009-002.document': json.dumps(
            {'Resource': {'$resource': '[missing](s3.md#absent)', '$attribute': 'Arn'}})}
        assert links(bad).warnings
        bad = {**create_policy, 'desired.row.009-002.document': json.dumps(
            {'Resource': {'$resource': uri, '$attribute': 'Unknown'}})}
        assert links(bad).warnings
        malformed = {**create_policy, 'desired.row.009-002.document': '{"$resource":123}'}
        assert links(malformed).errors
        bucket_design.write_text('# Buckets\n', encoding='utf-8')
        assert any('missing design anchor' in warning['message'] for warning in links().warnings)
        bucket_design.unlink()
        assert any('broken design link' in warning['message'] for warning in links().warnings)
        # Other Markdown checks continue after an unresolved JSON reference.
        design.write_text(artifacts[design] + '\n[broken](iam/absent.json)\n', encoding='utf-8')
        assert any('broken design link' in error for error in links(bad).errors)
        producer.write_bytes(original)
        assert 'arn:' not in producer.read_text(encoding='utf-8')
    print('transient ARN, producer context, pending links, malformed references and no persistence: PASS')


if __name__ == '__main__':
    check_cfn_and_outputs()
