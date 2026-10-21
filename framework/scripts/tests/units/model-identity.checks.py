"""Offline fixed identity allocation checks; no project or AWS inputs."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from model.identity import COUNTERS, allocate, resource_index, preserve_allocation, parse_reference


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
        rejects(lambda: parse_reference(invalid))
    assert parse_reference('resource://test/team/vpc/EC2_VPC_001') == ('test', 'team', 'vpc', 'EC2_VPC_001')
    print('fixed identity allocation: PASS')


def check_snapshots():
    import json
    import tempfile
    from unittest.mock import patch
    from model.format import serialize
    from model.identity import Resolver
    from model.sources import load_model
    import model.sources as sources
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
            after = {key: value for key, value in values.items() if not key.endswith(('.logicalId', '.anchor'))}
            after = allocate(after, [f'{i:03d}' for i in range(500)])
            after['desired.row.000-001.value'] = 'resource://' + scope + '/EC2_VPC_001'
            for root, data in [(old, after), (new, after)]:
                path = root / 'model' / (scope + '.properties')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(serialize(data), encoding='utf-8')
        resolver = Resolver(new)
        with patch.object(sources, '_read_model', wraps=sources._read_model) as read:
            for i in range(500):
                snapshot, number, resource = resolver.resolve('resource://qa/one/vpc/EC2_VPC_' + f'{i + 1:03d}')
                assert number == f'{i:03d}'
            assert read.call_count == 1, read.call_count
        assert resolver.resolve('resource://qa/two/vpc/EC2_VPC_001')[0].scope.target == 'two'
        assert resolver.resolve('resource://live/one/vpc/EC2_VPC_001')[0].scope.environment == 'live'
        rejects(lambda: resolver.resolve('resource://unknown/one/vpc/EC2_VPC_001'))
        print('baseline preservation and 500 indexed resolutions: PASS')


if __name__ == '__main__':
    main()
    check_snapshots()


def check_cfn_and_outputs():
    import json
    import tempfile
    from model.format import serialize
    from model.projection import execution_document, reference_display, resource_display_rows
    from model.validation import validate_resource_identities
    from model.core import entries
    from model.sources import Scope
    from utils.aws_mappings import mapping_alias
    framework = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory() as directory:
        before, after = Path(directory).resolve() / 'before', Path(directory).resolve() / 'after'
        old = {'desired.resource.007.resourceType': 'EC2.VPC', 'desired.resource.007.logicalId': 'ExistingVpc',
               'desired.resource.007.anchor': 'network', 'desired.resource.007.resourceMode': 'CREATE'}
        new = allocate({key: value for key, value in old.items() if not key.endswith(('.logicalId', '.anchor'))}, ['007'])
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
                      'desired.row.007-001.comment': 'literal stays literal',
                      'desired.row.007-002.property': 'S3.Bucket.Arn',
                      'desired.row.007-002.value': 'resource://qa/team/s3/S3_Bucket_001',
                      'desired.row.007-002.comment': 'confirmed output',
                      'observed.row.007-002.value': '`arn:aws:s3:::physical-bucket`'}
            bucket = allocate(bucket, ['007'])
            path = after / 'model/qa/team/s3.properties'
            path.write_text(serialize(bucket))
            uri = 'resource://qa/team/s3/S3_Bucket_001'
            document = {'Statement': [{'Resource': {'$resource': uri, '$attribute': 'Arn'}, 'Effect': 'Allow'}]}
            result = execution_document(document, after)
            assert result['Statement'][0]['Resource'] == 'arn:aws:s3:::physical-bucket'
            assert 'resource://' not in json.dumps(result)
            assert document['Statement'][0]['Resource']['$resource'] == uri
            assert execution_document(uri, after, property_name='CloudTrail.Trail.S3BucketName') == 'physical-bucket'
            rejects(lambda: execution_document({'Statement': [{'Resource': uri}]}, after))
            displayed = reference_display(bucket, after / 'docs/designs/qa/team/s3.md', after, definitions_root=framework)
            assert displayed['desired.resource.007.anchor'] == 'resource-S3_Bucket_001'
            assert '#resource-S3_Bucket_001)' in displayed['desired.row.007-002.value']
            assert bucket['desired.row.007-001.value'] == '`physical-bucket`'
            assert 'desired.resource.007.anchor' not in bucket
            renamed = {**bucket, 'desired.row.007-001.value': '`renamed-bucket`'}
            renamed_display = reference_display(renamed, after / 'docs/designs/qa/team/s3.md', after, definitions_root=framework)
            assert '[renamed-bucket](#resource-S3_Bucket_001)' in renamed_display['desired.row.007-002.value']
            from model.render import generate_files
            from model.sources import runtime_values
            policy = allocate({
                'desired.service.iam.serviceId': 'iam',
                'desired.service.iam.ownedCatalogResourceTypes': 'IAM.ManagedPolicy',
                'display.service.title': '# Policies',
                'desired.resource.009.resourceType': 'IAM.ManagedPolicy',
                'desired.resource.009.resourceMode': 'IMPORT',
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
            from unittest.mock import patch
            import model.render as renderer
            original_markdown = renderer.generate_markdown
            with patch.object(renderer, 'generate_markdown',
                              lambda path, values, root: original_markdown(path, values, framework)):
                files = generate_files(design, runtime_values(policy), after)
            assert json.loads(files[design.with_suffix('') / 'policy.json']) == result
            assert 'resource://' not in files[design]
            assert '<a id="resource-IAM_ManagedPolicy_001"></a>' in files[design]
            assert json.loads(policy['desired.row.009-002.document']) == document
    from model.adapters.aws import Resource
    from types import SimpleNamespace
    target = SimpleNamespace(kind='S3.Bucket',
        ctx=SimpleNamespace(require_resource_scope=lambda resource: None),
        rows_for=lambda prop: [('007-001', {'value': '`physical-bucket`'})],
        value=lambda prop: 'physical-bucket', identity=lambda mode: 'resolved-' + mode)
    consumer = object.__new__(Resource)
    consumer.reference = lambda uri: target
    assert consumer.resolve_json({'$resource': uri, '$attribute': 'Arn'}) == 'resolved-arn'
    assert consumer.resolve_json({'$resource': uri, '$attribute': 'BucketName'}) == 'physical-bucket'
    print('CFn correspondence and output projections: PASS')


if __name__ == '__main__':
    check_cfn_and_outputs()
