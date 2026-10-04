#!/usr/bin/env python3
"""Offline AWS SDK/mapping regressions. All network access is forbidden.

Consumer models are read only for inventory/coverage; synthetic SDK responses and
test-created models are the only regression fixtures. Missing boto3 is a failure.
"""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import boto3
from botocore.stub import Stubber
from model_files import model_file_contents

spec = importlib.util.spec_from_file_location('model_aws_compare', Path(__file__).with_name('check-model-aws.py'))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
COUNT = 0


def check(condition, message):
    global COUNT
    assert condition, message
    COUNT += 1


def expect(error_type, function):
    try:
        function()
    except error_type:
        check(True, 'expected rejection')
    else:
        raise AssertionError('expected ' + error_type.__name__)


ACCOUNT = '123456789012'
TARGET = {'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1', 'environment': 'dev', 'directory': ACCOUNT,
          'iacEngine': 'cloudformation'}


def shape_value(shape, depth=0, seen=()):
    """SDK-schema synthetic values, independent of comparator field mappings."""
    terminal = depth > 10 or shape.name in seen
    seen = (*seen, shape.name)
    kind = shape.type_name
    if kind == 'structure':
        return {name: shape_value(child, depth + 1, seen) for name, child in shape.members.items()
                if not terminal or name in shape.required_members}
    if kind == 'list':
        return [shape_value(shape.member, depth + 1, seen) for _ in range(max(1, shape.metadata.get('min', 1)))] if not terminal else []
    if kind == 'map':
        return {shape_value(shape.key, depth + 1, seen): shape_value(shape.value, depth + 1, seen)} if not terminal else {}
    if kind == 'boolean':
        return True
    if kind in {'integer', 'long'}:
        return max(1, shape.metadata.get('min', 1))
    if kind in {'float', 'double'}:
        return max(1.0, shape.metadata.get('min', 1.0))
    if kind == 'timestamp':
        from datetime import datetime, timezone
        return datetime(2026, 1, 1, tzinfo=timezone.utc)
    if kind == 'blob':
        return b'fixture'
    return shape.enum[0] if shape.enum else 'fixture' + 'x' * max(0, shape.metadata.get('min', 0) - 7)


def remove_tokens(value):
    if isinstance(value, dict):
        return {key: remove_tokens(item) for key, item in value.items() if key not in
                {'NextToken', 'nextToken', 'NextMarker', 'Marker', 'NextRecordName', 'NextRecordType',
                 'NextRecordIdentifier', 'ContinuationToken', 'NextContinuationToken', 'nextMarker'}}
    if isinstance(value, list):
        return [remove_tokens(item) for item in value]
    return value


def set_path(tree, path, value):
    parts = path.split('.')
    node = tree
    for part in parts[:-1]:
        node = node[part][0] if isinstance(node.get(part), list) else node[part]
    node[parts[-1]] = value


PATCHES = {
    ('sts', 'get_caller_identity'): {'Account': ACCOUNT, 'Arn': 'arn:aws:iam::' + ACCOUNT + ':user/offline'},
    ('logs', 'describe_log_groups'): {'logGroups.logGroupName': 'fixture'},
    ('codecommit', 'get_repository'): {'repositoryMetadata.repositoryName': 'fixture'},
    ('codebuild', 'batch_get_projects'): {'projects.name': 'fixture'},
    ('codepipeline', 'get_pipeline'): {'pipeline.name': 'fixture'},
    ('config', 'describe_configuration_recorders'): {'ConfigurationRecorders.name': 'fixture'},
    ('config', 'describe_delivery_channels'): {'DeliveryChannels.name': 'fixture'},
    ('s3', 'list_buckets'): {'Buckets.Name': 'fixture', 'Buckets.BucketArn': 'arn:aws:s3:::fixture'},
    ('s3', 'get_object_lock_configuration'): {'ObjectLockConfiguration.ObjectLockEnabled': 'Enabled'},
    ('kms', 'list_aliases'): {'Aliases.AliasName': 'fixture', 'Aliases.TargetKeyId': 'fixture'},
    ('kms', 'describe_key'): {'KeyMetadata.KeyId': 'fixture'},
    ('glue', 'get_catalogs'): {'CatalogList.Name': 'fixture'},
    ('iam', 'list_policies'): {'Policies.PolicyName': 'fixture', 'Policies.DefaultVersionId': 'v1'},
    ('iam', 'get_role'): {'Role.RoleName': 'fixture', 'Role.AssumeRolePolicyDocument': '{"Version":"2012-10-17","Statement":[]}'},
    ('iam', 'get_role_policy'): {'PolicyDocument': '{"Version":"2012-10-17","Statement":[]}'},
    ('iam', 'get_user_policy'): {'PolicyDocument': '{"Version":"2012-10-17","Statement":[]}'},
    ('iam', 'get_policy_version'): {'PolicyVersion.Document': '{"Version":"2012-10-17","Statement":[]}'},
    ('kms', 'get_key_policy'): {'Policy': '{"Version":"2012-10-17","Statement":[]}'},
    ('events', 'describe_rule'): {'Name': 'fixture', 'EventPattern': '{"source":["fixture"]}'},
    ('guardduty', 'get_detector'): {'Status': 'ENABLED'},
    ('guardduty', 'get_malware_protection_plan'): {'ProtectedResource.S3Bucket.BucketName': 'fixture'},
    ('route53', 'list_hosted_zones'): {'HostedZones.Name': 'fixture.', 'HostedZones.Id': 'fixture', 'IsTruncated': False},
    ('route53', 'get_hosted_zone'): {'HostedZone.Id': 'fixture', 'HostedZone.Name': 'fixture.', 'VPCs.VPCId': 'fixture'},
    ('route53', 'list_resource_record_sets'): {'ResourceRecordSets.Name': 'fixture.', 'ResourceRecordSets.Type': 'A', 'IsTruncated': False},
    ('macie2', 'list_classification_jobs'): {'items.name': 'fixture'},
    ('lambda', 'get_policy'): {'Policy': '{"Version":"2012-10-17","Statement":[{"Sid":"fixture","Action":"lambda:InvokeFunction","Principal":{"Service":"s3.amazonaws.com"},"Condition":{"ArnLike":{"AWS:SourceArn":"fixture"},"StringEquals":{"AWS:SourceAccount":"123456789012"}}}]}'},
    ('ec2', 'describe_security_group_rules'): {'SecurityGroupRules.GroupId': 'fixture', 'SecurityGroupRules.IsEgress': False},
    ('sqs', 'get_queue_attributes'): {'Attributes': {'QueueArn': 'arn:aws:sqs:ap-northeast-1:' + ACCOUNT + ':fixture', 'FifoQueue': 'false', 'MessageRetentionPeriod': '604800', 'Policy': '{"Version":"2012-10-17","Statement":[]}' }},
    ('s3', 'get_bucket_policy'): {'Policy': '{"Version":"2012-10-17","Statement":[]}'},
    ('ec2', 'describe_flow_logs'): {'FlowLogs.ResourceId': 'vpc-fixture'},
    ('ec2', 'describe_route_tables'): {'RouteTables.Associations.SubnetId': 'fixture', 'RouteTables.Associations.AssociationState.State': 'associated'},
    ('ec2', 'describe_volumes'): {'Volumes.VolumeId': 'fixture'},
    ('ec2', 'describe_vpcs'): {'Vpcs.Tags.Key': 'Name'},
    ('ec2', 'describe_subnets'): {'Subnets.Tags.Key': 'Name'},
    ('ec2', 'describe_route_tables'): {'RouteTables.Associations.SubnetId': 'fixture', 'RouteTables.Associations.AssociationState.State': 'associated', 'RouteTables.Tags.Key': 'Name'},
    ('ec2', 'describe_flow_logs'): {'FlowLogs.ResourceId': 'vpc-fixture', 'FlowLogs.Tags.Key': 'Name'},
    ('cloudformation', 'describe_stacks'): {'Stacks.StackName': 'fixture', 'Stacks.StackStatus': 'CREATE_COMPLETE'},
    ('cloudformation', 'list_exports'): {'Exports.Name': 'fixture-export', 'Exports.Value': 'confirmed-export-value'},
}


class Offline(m.Context):
    def __init__(self, root, fault=None):
        session = boto3.Session(aws_access_key_id='offline', aws_secret_access_key='offline', region_name=TARGET['awsRegion'])
        super().__init__(root, TARGET, session)
        self.stubbers, self.fault = {}, fault
        self.request_count = 0

    def client(self, service):
        client = super().client(service)
        if service not in self.stubbers:
            self.stubbers[service] = Stubber(client)
            self.stubbers[service].activate()
        return client

    def queue(self, service, operation, inputs):
        client = self.client(service)
        stub = self.stubbers[service]
        fault = self.fault.get((service, operation)) if isinstance(self.fault, dict) else self.fault
        if fault:
            stub.add_client_error(operation, service_error_code='ResourceNotFoundException' if fault == 'missing' else 'AccessDeniedException', expected_params=inputs)
        else:
            response = remove_tokens(shape_value(client.meta.service_model.operation_model(client.meta.method_to_api_mapping[operation]).output_shape))
            for name in ('IsTruncated', 'HasMoreResults', 'HasMoreDestinations'):
                if name in response:
                    response[name] = False
            if operation == 'describe_delivery_stream':
                response['DeliveryStreamDescription']['HasMoreDestinations'] = False
            for path, value in PATCHES.get((service, operation), {}).items():
                set_path(response, path, copy.deepcopy(value))
            if operation == 'describe_security_group_rules' and self.egress:
                response['SecurityGroupRules'][0]['IsEgress'] = True
            stub.add_response(operation, response, expected_params=inputs)
        self.request_count += 1

    def call(self, service, operation, **inputs):
        if (service, operation) not in self.allowed or (not self.verified and service != 'sts'):
            return super().call(service, operation, **inputs)
        key = (service, operation, m.stable(inputs))
        if key not in self.cache:
            self.queue(service, operation, inputs)
        return super().call(service, operation, **inputs)

    def pages(self, service, operation, **inputs):
        client = self.client(service)
        key = (service, operation, 'pages', m.stable(inputs))
        if key not in self.cache and client.can_paginate(operation):
            self.queue(service, operation, inputs)
        return super().pages(service, operation, **inputs)

    def finish(self):
        for stub in self.stubbers.values():
            stub.assert_no_pending_responses()


class FakeResource:
    def __init__(self, ctx, service, kind, prop=None, desired='fixture'):
        self.ctx, self.kind, self.number = ctx, kind, '001'
        self.module = m.service_module(service)
        self.spec = {'resourceType': kind, 'logicalId': 'fixture', 'anchor': 'fixture'}
        self.rows = [('001-001', {'property': prop, 'value': '`fixture`', 'comment': 'fixture'})] if prop else []
        self.desired = desired
        self.model = SimpleNamespace(path=Path('/offline/' + service + '.properties'), resources=[self], values={},
                                     locations={'desired.row.001-001.value': {'file': '/offline/fixture.properties', 'line': 1}})
        self.egress = kind.endswith('Egress')
        ctx.egress = self.egress

    def value(self, prop, norm='typed'):
        return {'AwsAccountId': ACCOUNT, 'CatalogId': ACCOUNT, 'Type': 'A', 'Action': 'lambda:InvokeFunction',
                'Principal': 's3.amazonaws.com', 'SourceAccount': ACCOUNT}.get(prop, 'fixture')

    def current(self, prop):
        return 'fixture'

    def rows_for(self, prop):
        if prop == 'Queues[]':
            return [('001-001', {'property': self.kind + '.Queues[]', 'value': 'fixture'})]
        return []

    def optional(self, prop, default=None, norm='typed'):
        return default

    def parent(self):
        return self

    def identity(self, mode='id'):
        return 'fixture'

    def parse(self, row, norm='typed'):
        return 'fixture' if row['property'].endswith('Queues[]') else self.desired


REPRESENTATIVES = {
    'athena': ('Athena.WorkGroup', 'Description', 'fixture'),
    'cloudtrail': ('CloudTrail.Trail', 'TrailName', 'fixture'),
    'cloudwatch-logs': ('Logs.LogGroup', 'LogGroupName', 'fixture'),
    'codebuild': ('CodeBuild.Project', 'Name', 'fixture'),
    'codecommit': ('CodeCommit.Repository', 'RepositoryName', 'fixture'),
    'codepipeline': ('CodePipeline.Pipeline', 'Name', 'fixture'),
    'config': ('Config.ConfigurationRecorder', 'Name', 'fixture'),
    'data-firehose': ('KinesisFirehose.DeliveryStream', 'DeliveryStreamName', 'fixture'),
    'ec2': ('EC2.Instance', 'InstanceType', 'a1.medium'),
    'eventbridge': ('Events.Rule', 'Name', 'fixture'),
    'glue': ('Glue.Job', 'Name', 'fixture'),
    'guardduty': ('GuardDuty.Detector', 'FindingPublishingFrequency', 'FIFTEEN_MINUTES'),
    'iam': ('IAM.Role', 'RoleName', 'fixture'),
    'kms': ('KMS.Key', 'Description', 'fixture'),
    'lambda': ('Lambda.Function', 'FunctionName', 'fixture'),
    'macie': ('Macie.ClassificationJob', 'name', 'fixture'),
    'mwaa': ('MWAA.Environment', 'Name', 'fixture'),
    'quicksight': ('QuickSight.DataSource', 'Name', 'fixture'),
    'route53': ('Route53.HostedZone', 'Name', 'fixture'),
    's3': ('S3.Bucket', 'BucketName', 'fixture'),
    'secrets-manager': ('SecretsManager.Secret', 'Name', 'fixture'),
    'security-hub': ('SecurityHub.Hub', 'AutoEnableControls', True),
    'security_group': ('EC2.SecurityGroup', 'GroupDescription', 'fixture'),
    'sqs': ('SQS.Queue', 'MessageRetentionPeriod', 604800),
    'transit-gateway': ('EC2.TransitGatewayVpcAttachment', 'TransitGatewayId', 'fixture'),
    'vpc': ('EC2.VPC', 'CidrBlock', 'fixture'),
    'vpc-endpoint': ('EC2.VPCEndpoint', 'ServiceName', 'fixture'),
}


def service_checks(root):
    # Every supported field is extracted from a real botocore-validated SDK
    # response after executing the service's fetch adapter. These are not stubs
    # that simply echo comparator mappings. Unknown SDK paths fail here.
    type_count, field_count = 0, 0
    for service in m.SERVICES:
        module = m.service_module(service)
        if service == 'cloudformation-stacks':
            continue
        for kind in module.RESOURCE_TYPES:
            relevant = {prop: field for prop, field in module.FIELDS.items() if prop.startswith(kind + '.') and field.classification == 'supported'}
            if not relevant:  # Inline types still must have their actual getter exercised below.
                raise AssertionError('resource type without acquisition: ' + kind)
            owner = {'S3.BucketPolicy': 'S3.Bucket', 'EC2.SubnetRouteTableAssociation': 'EC2.Subnet'}.get(kind, kind)
            ctx = Offline(root)
            ctx.egress = False
            ctx.verify()
            resource = FakeResource(ctx, service, owner)
            for prop, field in relevant.items():
                value = m.select(ctx.fetch(resource, field.getter), field.path)
                check(value != m.MISSING, 'unreadable mapping ' + prop + ' -> ' + field.path)
                field_count += 1
            ctx.finish()
            type_count += 1
        kind, prop, expected = REPRESENTATIVES[service]
        for state in ('match', 'difference', 'missing', 'failed'):
            ctx = Offline(root)
            ctx.egress = False
            ctx.verified = True
            ctx.fault = state if state in {'missing', 'failed'} else None
            different = not expected if type(expected) is bool else expected + 1 if type(expected) is int else 'deliberately different'
            resource = FakeResource(ctx, service, kind, kind + '.' + prop, expected if state != 'difference' else different)
            results = m.compare_resource(ctx, resource)
            wanted = {'missing': 'resource_missing', 'failed': 'acquisition_failed'}.get(state, state)
            check(any(item['status'] == wanted for item in results), service + ': ' + state + ': ' + repr(results))
            ctx.finish()
    print(f'Service acquisition/field extraction: {type_count} resource types, {field_count} supported mappings, 27 × 4 comparison cases')


def model_text(kind, rows, number='001', logical='fixture', anchor='fixture', metadata=''):
    text = f'desired.resource.{number}.resourceType={kind}\ndesired.resource.{number}.logicalId={logical}\ndesired.resource.{number}.anchor={anchor}\n' + metadata
    for index, (prop, value) in enumerate(rows, 1):
        text += f'desired.row.{number}-{index:03d}.property={prop}\ndesired.row.{number}-{index:03d}.value={value}\ndesired.row.{number}-{index:03d}.comment=fixture\n'
    return text


def batch_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [TARGET]}), encoding='utf-8')
    s3 = directory / 's3.properties'
    s3_rows = [('S3.Bucket.BucketName', '`fixture`'), ('S3.Bucket.VersioningConfiguration.Status', '`Enabled`')]
    s3.write_text(model_text('S3.Bucket', s3_rows), encoding='utf-8')
    (directory / 'iam.properties').write_text(model_text('IAM.Role', [('IAM.Role.RoleName', '`fixture`')]), encoding='utf-8')
    # An unrelated entrance must never be compared or included in scoped coverage.
    (directory / 'athena.properties').write_text(model_text('Athena.WorkGroup', [('Athena.WorkGroup.Name', '`fixture`')]), encoding='utf-8')
    selected = m.targets(root, 'dev', ACCOUNT)
    base_args = ['--root', str(root), '--environment', 'dev', '--target', ACCOUNT]

    def cli(arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['check-model-aws.py', *arguments]), redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = m.main()
            except SystemExit as error:
                code = error.code
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue()

    session_class = boto3.Session
    requests = {
        'sts': [('get_caller_identity', {})],
        's3': [('list_buckets', {}), ('get_bucket_location', {'Bucket': 'fixture', 'ExpectedBucketOwner': ACCOUNT}),
               ('get_bucket_versioning', {'Bucket': 'fixture', 'ExpectedBucketOwner': ACCOUNT})],
        'iam': [('get_role', {'RoleName': 'fixture'})],
        'kms': [('describe_key', {'KeyId': 'fixture'})],
    }

    def compare(services, fault=None, direct=False, items=None):
        with ExitStack() as stack:
            api_calls, stubbers = [], []

            def session_factory(**kwargs):
                session = session_class(aws_access_key_id='offline', aws_secret_access_key='offline', region_name=kwargs['region_name'])
                real_client = session.client

                def client(service, **client_kwargs):
                    result = real_client(service, **client_kwargs)
                    stub = stack.enter_context(Stubber(result))
                    stubbers.append(stub)
                    api_calls.append((service, stack.enter_context(patch.object(result, '_make_api_call', wraps=result._make_api_call))))
                    for operation, inputs in requests[service]:
                        if service == 'kms' and fault:
                            stub.add_client_error(operation, 'NotFoundException' if fault == 'missing' else 'AccessDeniedException', expected_params=inputs)
                            continue
                        response = remove_tokens(shape_value(result.meta.service_model.operation_model(result.meta.method_to_api_mapping[operation]).output_shape))
                        for path, value in PATCHES.get((service, operation), {}).items():
                            set_path(response, path, copy.deepcopy(value))
                        if service == 's3' and operation == 'get_bucket_location':
                            response['LocationConstraint'] = TARGET['awsRegion']
                        if service == 's3' and operation == 'get_bucket_versioning':
                            response['Status'] = 'Enabled'
                        stub.add_response(operation, response, expected_params=inputs)
                    return result

                stack.enter_context(patch.object(session, 'client', side_effect=client))
                return session

            factory = stack.enter_context(patch.object(boto3, 'Session', side_effect=session_factory))
            contexts = stack.enter_context(patch.object(m, 'Context', wraps=m.Context))
            if direct:
                report = m.run(root, items if items is not None else m.inventory(root, selected, services), session_factory=factory)
                code = report['exitCode']
            else:
                code, report, _ = cli([*base_args, *(arg for service in services for arg in ('--service', service))])
            for stub in stubbers:
                stub.assert_no_pending_responses()
            target_count = len({(target['environment'], target['directory']) for target, _ in items}) if items is not None else 1
            check(factory.call_count == contexts.call_count == target_count, 'Session factory and real Context initialized once per target')
            check(sum(call.call_count for service, call in api_calls if service == 'sts') == target_count, 'STS get_caller_identity called once per target')
            expected_apis = {service: len(requests[service]) * target_count for service in {'sts', *services}}
            actual_apis = {service: sum(call.call_count for name, call in api_calls if name == service) for service, _ in api_calls}
            check(actual_apis == expected_apis, 'only selected service API requests, no extra or repeated SDK calls')
            return code, report

    single = compare(['s3'])
    check(single == compare(['s3'], direct=True), 'single-service CLI preserves existing run result exactly')
    check(single[0] == 0 and single[1]['counts'] == {'match': 2}, 'single service remains matched')
    check(single == compare(['s3', 's3']), 'duplicate CLI services do not duplicate results or API calls')
    iam = compare(['iam'])
    code, batch = compare(['s3', 'iam'])
    expected = m.summarize(iam[1]['results'] + single[1]['results'])
    check(code == 0 and batch == expected, 'batch results equal standalone results, preserving JSON and counts')
    check({item['service'] for item in batch['results']} == {'s3', 'iam'}, 'batch compares both requested services only')
    compare(['s3', 'iam'], direct=True)
    batch_items = m.inventory(root, selected, ['s3', 'iam'])
    compare(['s3', 'iam'], direct=True, items=batch_items + [(dict(target, environment='stg'), path) for target, path in batch_items])

    with patch.object(boto3, 'Session', side_effect=AssertionError('offline coverage must not create a session')) as factory:
        code, report, _ = cli([*base_args, '--service', 's3', '--service', 'iam', '--coverage'])
        check(code == 0 and report['services'] == ['iam', 's3'] and report['modelCount'] == 2, 'batch coverage selects requested services only')
        check({item['service'] for item in report['mappings']} == {'s3', 'iam'} and report['keyCount'] == 3, 'unselected service excluded from coverage mappings')
        code, duplicate, _ = cli([*base_args, '--service', 's3', '--service', 'iam', '--service', 's3', '--coverage'])
        check(code == 0 and duplicate == report, 'coverage deduplicates requested services')
        check(not factory.called, 'coverage never creates an SDK session')

    expect(ValueError, lambda: m.inventory(root, selected, ['s3', 'iam', 'kms']))
    expect(ValueError, lambda: m.inventory(root, selected, ['kms']))
    with patch.object(m, 'run') as run, patch.object(m, 'coverage') as coverage:
        for flags in ([], ['--coverage']):
            code, report, _ = cli([*base_args, '--service', 's3', '--service', 'iam', '--service', 'kms', *flags])
            check(code == 2 and report == {'status': 'incomplete', 'reason': 'service entrance models are missing for target: kms'}, 'missing batch service fails closed in existing error schema')
        check(not run.called and not coverage.called, 'missing service rejected before comparison or coverage')
    with patch.object(m, 'targets') as targets:
        for flags in ([], ['--all', '--service', 's3'], ['--all', '--environment', 'dev'],
                      ['--all', '--target', ACCOUNT], ['--environment', 'dev', '--target', ACCOUNT],
                      ['--service', 's3'], ['--environment', 'dev', '--service', 's3'],
                      ['--target', ACCOUNT, '--service', 's3']):
            code, report, error = cli(['--root', str(root), *flags])
            check(code == 2 and report is None and 'use --all alone' in error, 'invalid selector rejected: ' + repr(flags))
        check(not targets.called, 'invalid selectors rejected before inventory')
    with patch.object(m, 'run', return_value=single[1]) as run:
        code, _, _ = cli(['--root', str(root), '--all'])
        check(code == 0 and {path.stem for _, path in run.call_args.args[1]} == {'s3', 'iam', 'athena'}, 'explicit --all remains available')

    (directory / 'kms.properties').write_text(model_text('KMS.Key', [('KMS.Key.KeyId', '`fixture`'), ('KMS.Key.Description', '`fixture`')]), encoding='utf-8')
    s3_rows[1] = ('S3.Bucket.VersioningConfiguration.Status', '`Suspended`')
    s3.write_text(model_text('S3.Bucket', s3_rows), encoding='utf-8')
    for fault, wanted_code, wanted_status in ((None, 1, 'identifier'), ('missing', 1, 'resource_missing'), ('failed', 2, 'acquisition_failed')):
        code, report = compare(['s3', 'iam', 'kms'], fault=fault)
        statuses = {(item['service'], item['status']) for item in report['results']}
        check(code == wanted_code and ('s3', 'difference') in statuses and ('iam', 'match') in statuses and ('kms', wanted_status) in statuses,
              'batch exit precedence retains successful comparisons and S3 differences: ' + str(fault))
        check(set(report) == {'status', 'exitCode', 'counts', 'results'}, 'batch does not add a JSON wrapper')


def common_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [TARGET]}), encoding='utf-8')
    check(m.targets(root, 'dev', ACCOUNT)[0]['directory'] == ACCOUNT, 'existing target resolver')
    expect(ValueError, lambda: m.targets(root, 'dev', 'unknown'))
    text = model_text('Athena.WorkGroup', [('Athena.WorkGroup.Name', '`fixture`'), ('Athena.WorkGroup.State', '`ENABLED`')])
    path = directory / 'athena.properties'
    path.write_text(text + '\n' * 601, encoding='utf-8')
    for file, content in model_file_contents(path, path.read_text(encoding='utf-8')).items():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding='utf-8')
    ctx = Offline(root)
    ctx.egress = False
    ctx.verify()
    model = ctx.model(path)
    check(len(model.resources) == 1 and model.locations['desired.row.001-002.value']['file'].endswith('part-001.properties'), 'split model and source')
    check(all(item['status'] == 'match' for item in m.compare_resource(ctx, model.resources[0])), 'desired typed model comparison')
    check(ctx.request_count == 2, 'one shared SDK response for two selected keys')
    check(all(item['apis'] for item in m.compare_resource(ctx, model.resources[0])), 'cached responses retain API evidence')
    resource = model.resources[0]
    resource.rows.append(('001-003', {'property': 'Athena.WorkGroup.Unknown', 'value': 'false', 'comment': 'fixture'}))
    model.locations['desired.row.001-003.value'] = {'file': str(path), 'line': 1}
    check(any(item['status'] == 'unimplemented' for item in m.compare_resource(ctx, resource)), 'unknown key fail closed')
    resource.rows.pop()
    resource.rows[1][1]['value'] = 'UNSET'
    check(any(item['status'] == 'design_unresolved' for item in m.compare_resource(ctx, resource)), 'unresolved desired is not equality')
    resource.rows[1][1]['value'] = '`ENABLED`'
    failed = Offline(root, 'failed')
    failed.egress = False
    failed.verified = True
    failures = m.compare_resource(failed, failed.model(path).resources[0])
    check(len(failures) == 1 and len(failures[0]['affectedKeys']) == 2, 'one failure with affected-key scope')
    ctx.finish()
    check(m.summarize([{'status': 'match'}])['exitCode'] == 0, 'match exit')
    check(m.summarize([{'status': 'difference'}])['exitCode'] == 1, 'difference exit')
    check(m.summarize([{'status': 'difference'}, {'status': 'sdk_unavailable'}])['exitCode'] == 2, 'incomplete takes precedence')
    check(m.summarize([])['exitCode'] == 2, 'empty scan incomplete')
    expect(ValueError, lambda: ctx.call('s3', 'delete_bucket', Bucket='fixture'))
    expect(ValueError, lambda: ctx.call('secretsmanager', 'get_secret_value', SecretId='fixture'))
    unverified = Offline(root)
    expect(ValueError, lambda: unverified.call('s3', 'list_buckets'))
    bad = dict(TARGET, awsAccountId='999999999999')
    ctx2 = Offline(root)
    ctx2.target = bad
    expect(m.AcquisitionError, ctx2.verify)
    check(not ctx2.verified and set(ctx2.clients) == {'sts'}, 'account mismatch stops all service APIs')
    split = Offline(root)
    split.target = dict(TARGET, awsAccountId='999999999999', awsExecutionAccountId=ACCOUNT)
    split.verify()
    check(split.verified and split.target['awsAccountId'] == '999999999999', 'execution account verification preserves resource account')
    split_resource = split.model(path).resources[0]
    check(split_resource.resolve_json({'Fn::Sub': 'account-${AWS::AccountId}'}, None) == 'account-' + ACCOUNT,
          'live CFN pseudo account uses verified execution account')
    check(split_resource.resolve_json({'Ref': 'AWS::AccountId'}) == ACCOUNT,
          'live CFN Ref pseudo account uses verified execution account')
    split.finish()
    wrong_execution = Offline(root)
    wrong_execution.target = dict(TARGET, awsExecutionAccountId='999999999999')
    expect(m.AcquisitionError, wrong_execution.verify)
    check(not wrong_execution.verified and set(wrong_execution.clients) == {'sts'}, 'execution mismatch stops all service APIs')
    # Implicit API account contexts use execution IDs; explicit model values stay untouched.
    execution = '999999999999'
    api_ctx = SimpleNamespace(target=dict(TARGET, awsExecutionAccountId=execution))
    resource_stub = SimpleNamespace(kind='SQS.Queue', value=lambda key: 'fixture', current=lambda key: None)
    with patch.object(api_ctx, 'call', create=True, return_value={'QueueUrl': 'url'}) as call:
        m.service_module('sqs').fetch(api_ctx, resource_stub, 'base')
        check(call.call_args_list[0].kwargs['QueueOwnerAWSAccountId'] == execution, 'SQS implicit owner is execution account')
    with patch.object(api_ctx, 'call', create=True, return_value={}) as call:
        m.service_module('s3').fetch(api_ctx, resource_stub, 'versioning')
        check(call.call_args.kwargs['ExpectedBucketOwner'] == execution, 'S3 implicit owner is execution account')
        check(m.service_module('macie').fetch(api_ctx, resource_stub, 'session')['AwsAccountId'] == execution,
              'Macie session actual account is execution account')
    resource_stub.kind = 'Glue.Catalog'
    with patch.object(api_ctx, 'pages', create=True, return_value={'CatalogList': [{'Name': 'fixture'}]}) as pages:
        m.service_module('glue').fetch(api_ctx, resource_stub, 'base')
        check(pages.call_args.kwargs['ParentCatalogId'] == execution, 'Glue implicit parent catalog is execution account')
    calls = []
    expect(ValueError, lambda: m.run(root, [(dict(TARGET, awsProfile='confirmed'), path)], profile='wrong', session_factory=lambda **kw: calls.append(kw)))
    check(not calls, 'profile conflict rejected before session creation')
    def bad_factory(**kw):
        calls.append(kw)
        raise RuntimeError('secret credential failure')
    m.run(root, [(dict(TARGET, awsProfile='confirmed'), path)], session_factory=bad_factory)
    check(len(calls) == 1 and calls[0]['profile_name'] == 'confirmed', 'no profile fallback')
    # Real paginator and two STS-free, credential-free pages, including a later-page failure.
    for fail in (False, True):
        session = boto3.Session(aws_access_key_id='offline', aws_secret_access_key='offline', region_name=TARGET['awsRegion'])
        page_ctx = m.Context(root, TARGET, session)
        page_ctx.verified = True
        client = page_ctx.client('logs')
        with Stubber(client) as stub:
            stub.add_response('describe_log_groups', {'logGroups': [{'logGroupName': 'first'}], 'nextToken': 'page-2'}, {})
            if fail:
                stub.add_client_error('describe_log_groups', 'AccessDeniedException', expected_params={'nextToken': 'page-2'})
                expect(m.AcquisitionError, lambda: page_ctx.pages('logs', 'describe_log_groups'))
            else:
                stub.add_response('describe_log_groups', {'logGroups': [{'logGroupName': 'second'}]}, {'nextToken': 'page-2'})
                check(len(page_ctx.pages('logs', 'describe_log_groups')['logGroups']) == 2, 'all paginator pages')
            stub.assert_no_pending_responses()
    # Reference resolution reads the authoritative model and obtains ARN from SDK.
    role = directory / 'iam.properties'
    role.write_text(model_text('IAM.Role', [('IAM.Role.RoleName', '`fixture`')], anchor='iam-fixture'), encoding='utf-8')
    check(resource.resolve_json('[fixture](iam.md#iam-fixture)', 'arn').startswith('arn:' ) is False, 'SDK synthetic ARN used, not constructed')
    expect(m.Unresolved, lambda: resource.reference('[x](../iam.md#iam-fixture)'))
    expect(m.Unresolved, lambda: resource.reference('[x](iam.md#missing)'))
    # Ordered arrays remain ordered; tags keep Key/Value pairs together.
    tags = {'Tags': [{'Key': 'b', 'Value': '2'}, {'Key': 'a', 'Value': '1'}]}
    check(m.canonical(tags)['Tags'] == [{'Key': 'a', 'Value': '1'}, {'Key': 'b', 'Value': '2'}], 'tag association')
    check(m.canonical({'Stages': ['b', 'a']})['Stages'] == ['b', 'a'], 'stage order')
    check(m.canonical({'SubnetIds': ['b', 'a']})['SubnetIds'] == ['b', 'a'], 'placement order')
    check(m.policy({'Statement': {'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': '*'}}) == m.policy({'Statement': [{'Resource': ['*'], 'Action': ['s3:GetObject'], 'Effect': 'Allow'}]}), 'policy scalar/set/object normalization')
    check(m.policy('{"Statement":[],"Id":"keep%2Fthis"}')['Id'] == 'keep%2Fthis', 'plain JSON policy preserves percent escapes')
    check(m.normalize(ctx, 'false', 'boolean') is False and m.normalize(ctx, '60', 'number') == 60, 'typed SDK string values')
    expect(m.Unresolved, lambda: m.normalize(ctx, 'FALSE', 'boolean'))
    check(m.normalize(ctx, 'alias/fixture', 'kms') == m.normalize(ctx, 'fixture', 'kms'), 'SDK-confirmed KMS alias/key identity')
    check(resource.resolve_json({'Fn::ImportValue': 'fixture-export'}) == 'confirmed-export-value', 'SDK-confirmed export in authoritative policy')
    check(resource.resolve_json({'Fn::Sub': '${AWS::AccountId}/${AWS::Region}/${AWS::Partition}'}) == ACCOUNT + '/ap-northeast-1/aws', 'verified pseudo-parameters')
    expect(m.Unresolved, lambda: resource.resolve_json({'Fn::ImportValue': 'missing-export'}))
    sample_row = {'property': 'GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.ObjectPrefixes[]', 'value': '`["a/","b/"]`'}
    check(resource.parse(sample_row) == ['a/', 'b/'], 'terminal-array literal')
    check(resource.parse({'property': 'S3.Bucket.LifecycleConfiguration.Rules[].Prefix', 'value': '``'}) == '', 'explicit empty optional prefix')
    check(m.redacted({'password': 'never print', 'nested': {'Token': 'never print'}}) == {'password': '[REDACTED]', 'nested': {'Token': '[REDACTED]'}}, 'secret output redaction')
    ctx.finish()
    # Stack presence/state and local metadata, without templates or parameters.
    stacks = directory / 'cloudformation-stacks.properties'
    stacks.write_text('desired.stack.001.name=fixture\ndesired.stack.001.template=a.yaml\ndesired.stack.001.parameters=a.json\ndesired.stack.001.deployOrder=1\ndesired.deployment.maxConcurrentStacks=1\n', encoding='utf-8')
    for fault in (None, 'missing', 'failed'):
        stack_ctx = Offline(root, fault)
        stack_ctx.egress = False
        stack_ctx.verified = True
        results = m.service_module('cloudformation-stacks').compare(stack_ctx, stack_ctx.model(stacks))
        check(results[0]['status'] == {None: 'match', 'missing': 'resource_missing', 'failed': 'acquisition_failed'}[fault], 'stack acquisition')
        check(sum(item['status'] == 'local_metadata' for item in results) == 4, 'stack local metadata')
        stack_ctx.finish()


def association_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    # SDK responses and desired rows are authored separately. Moving a tag value
    # onto a different key must fail even when the multisets of values are equal.
    path = directory / 'ec2.properties'
    text = model_text('EC2.Instance', [('EC2.Instance.InstanceId', '[fixture](#fixture)'),
                      ('EC2.Instance.Tags[].Key', '`b`'), ('EC2.Instance.Tags[].Value', '`2`'),
                      ('EC2.Instance.Tags[].Key', '`a`'), ('EC2.Instance.Tags[].Value', '`1`')])
    text += 'observed.row.001-001.value=fixture\n'
    path.write_text(text, encoding='utf-8')
    for wrong in (False, True):
        patches = copy.deepcopy(PATCHES)
        patches[('ec2', 'describe_instances')] = {'Reservations.Instances.Tags': [{'Key': 'a', 'Value': '2' if wrong else '1'}, {'Key': 'b', 'Value': '1' if wrong else '2'}]}
        with patch.dict(PATCHES, patches, clear=True):
            ctx = Offline(root)
            ctx.egress = False
            ctx.verified = True
            values = m.compare_resource(ctx, ctx.model(path).resources[0])
            check(any(v['status'] == 'difference' for v in values) == wrong, 'tag values belong to their keys')
            ctx.finish()
    pipeline = directory / 'codepipeline.properties'
    pipeline.write_text(model_text('CodePipeline.Pipeline', [
        ('CodePipeline.Pipeline.Name', '`fixture`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category', '`Source`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].Name', '`source`'),
        ('CodePipeline.Pipeline.Stages[].Name', '`first`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category', '`Build`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].Name', '`build-a`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category', '`Build`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].Name', '`build-b`'),
        ('CodePipeline.Pipeline.Stages[].Name', '`second`'),
    ]), encoding='utf-8')
    stages = [{'name': 'first', 'actions': [{'name': 'source', 'actionTypeId': {'category': 'Source', 'owner': 'AWS', 'provider': 'CodeCommit', 'version': '1'}}]},
              {'name': 'second', 'actions': [{'name': 'build-a', 'actionTypeId': {'category': 'Build', 'owner': 'AWS', 'provider': 'CodeBuild', 'version': '1'}},
                                            {'name': 'build-b', 'actionTypeId': {'category': 'Build', 'owner': 'AWS', 'provider': 'CodeBuild', 'version': '1'}}]}]
    for reversed_order in (False, True):
        patches = copy.deepcopy(PATCHES)
        patches[('codepipeline', 'get_pipeline')]['pipeline.stages'] = list(reversed(stages)) if reversed_order else stages
        with patch.dict(PATCHES, patches, clear=True):
            ctx = Offline(root)
            ctx.verified = True
            ctx.egress = False
            values = m.compare_resource(ctx, ctx.model(pipeline).resources[0])
            check(any(v['status'] == 'difference' for v in values) == reversed_order, 'stage/action affiliation and order')
            ctx.finish()
    trail = directory / 'cloudtrail.properties'
    trail.write_text(model_text('CloudTrail.Trail', [('CloudTrail.Trail.TrailName', '`fixture`'), ('CloudTrail.Trail.IsLogging', '`true`')]), encoding='utf-8')
    ctx = Offline(root, {('cloudtrail', 'get_trail_status'): 'failed'})
    ctx.egress = False
    ctx.verified = True
    values = m.compare_resource(ctx, ctx.model(trail).resources[0])
    check({v['status'] for v in values} == {'match', 'acquisition_failed'}, 'partial acquisition preserves successful comparisons')
    ctx.finish()
    failure = next(v for v in values if v['status'] == 'acquisition_failed')
    report = m.summarize([dict(failure, environment='dev', target=ACCOUNT, service='cloudtrail'),
                          dict(failure, environment='dev', target=ACCOUNT, service='cloudtrail', resource='second')])
    check(len(report['results']) == 1 and len(report['results'][0]['affectedResources']) == 2, 'one shared failure retains all affected resources')
    imported = directory / 'mwaa.properties'
    imported.write_text(model_text('MWAA.Environment', [('MWAA.Environment.Name', '`fixture`')], metadata='desired.resource.001.resourceMode=IMPORT\n'), encoding='utf-8')
    ctx = Offline(root)
    ctx.verified = True
    ctx.egress = False
    check(m.compare_resource(ctx, ctx.model(imported).resources[0])[0]['status'] == 'match', 'IMPORT is compared')
    ctx.finish()
    # Wrong key membership is a difference despite matching AliasName.
    alias = directory / 'kms.properties'
    alias.write_text(model_text('KMS.Key', [('KMS.Key.KeyId', '[key](#key)')], number='001', anchor='key') +
                     model_text('KMS.Alias', [('KMS.Alias.AliasName', '`fixture`')], number='002', anchor='alias',
                                metadata='desired.resource.002.parentReference=[key](#key)\n') +
                     'observed.row.001-001.value=fixture\n', encoding='utf-8')
    patches = copy.deepcopy(PATCHES)
    patches[('kms', 'list_aliases')]['Aliases.TargetKeyId'] = 'different-key'
    with patch.dict(PATCHES, patches, clear=True):
        ctx = Offline(root)
        ctx.verified = True
        ctx.egress = False
        values = m.compare_resource(ctx, ctx.model(alias).resources[1])
        check(any(v['status'] == 'difference' and 'parentReference' in v['propertiesKey'] for v in values), 'KMS alias parent membership')
        ctx.finish()
    # Stack state differs without touching stack templates.
    patches = copy.deepcopy(PATCHES)
    patches[('cloudformation', 'describe_stacks')]['Stacks.StackStatus'] = 'ROLLBACK_COMPLETE'
    with patch.dict(PATCHES, patches, clear=True):
        ctx = Offline(root)
        ctx.verified = True
        ctx.egress = False
        values = m.service_module('cloudformation-stacks').compare(ctx, ctx.model(directory / 'cloudformation-stacks.properties'))
        check(values[0]['status'] == 'difference', 'stack unhealthy state')
        ctx.finish()


def cfn_identity_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    path = directory / 'vpc.properties'
    content = ''
    for index, department in enumerate(('ism', 'ced', 'sd'), 1):
        number = f'{index:03d}'
        content += model_text('EC2.VPC', [('EC2.VPC.VpcId', f'[{number}](#vpc-{department})')], number=number, anchor='vpc-' + department,
                              metadata=f'desired.resource.{number}.cfn-logicalId=cfn-stack-app-dev-{department}-DepartmentVpc\n').replace(f'desired.resource.{number}.logicalId=fixture\n', '')
        content += f'observed.row.{number}-001.value=vpc-{department}\n'
    path.write_text(content)
    ctx = Offline(root)
    resources = ctx.model(path).resources
    with patch.object(ctx, 'fetch', side_effect=lambda resource, getter: {'VpcId': 'vpc-' + ('ism', 'ced', 'sd')[int(resource.number) - 1]}):
        for index, resource in enumerate(resources):
            department = ('ism', 'ced', 'sd')[index]
            check(resource.resolve_json({'Ref': 'DepartmentVpc'}) == 'vpc-' + department, 'CFn JSON Ref respects originating stack instance')
            expect(m.Unresolved, lambda: resource.resolve_json({'Ref': 'Missing'}))
        resources[1].spec['cfn-logicalId'] = resources[0].spec['cfn-logicalId']
        expect(m.Unresolved, lambda: resources[0].resolve_json({'Ref': 'DepartmentVpc'}))
    ctx.finish()


def fixture_coverage(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [TARGET]}))
    for service in m.SERVICES:
        module = m.service_module(service)
        if service == 'cloudformation-stacks':
            text = 'desired.stack.001.name=cfn-stack-app-dev-fixture\ndesired.stack.001.template=fixture.yaml\ndesired.stack.001.parameters=fixture.json\ndesired.stack.001.deployOrder=10\n'
        else:
            text = ''
            for index, kind in enumerate(sorted(module.RESOURCE_TYPES), 1):
                number = f'{index:03d}'
                text += model_text(kind, [(prop, '`fixture`') for prop in sorted(module.FIELDS) if prop.startswith(kind + '.')], number=number).replace(f'desired.resource.{number}.logicalId=fixture\n', '')
        (directory / (service + '.properties')).write_text(text)
    report = m.coverage(root, m.inventory(root, m.targets(root, all_targets=True)))
    check(not report['problems'], 'fixture coverage: ' + repr(report['problems']))
    check(set(report['services']) == set(m.SERVICES), 'all current services mechanically enumerated without logicalId')
    print(f"Offline model coverage: {report['modelCount']} models / {report['resourceTypeCount']} types / {report['keyCount']} keys")


def main():
    consumer = Path(os.environ['AWS_COMPARE_COVERAGE_ROOT']) if 'AWS_COMPARE_COVERAGE_ROOT' in os.environ else None
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network is forbidden in offline checks')):
        with tempfile.TemporaryDirectory(prefix='aws-compare-checks-') as tmp:
            root = Path(tmp)
            service_checks(root)
            common_checks(root)
            association_checks(root)
            batch_checks(root / 'batch')
            cfn_identity_checks(root / 'cfn-identity')
            fixture_coverage(root / 'coverage')
        # Explicit read-only consumer audit is optional; regression has no host-path dependency.
        if consumer is not None and consumer.is_dir():
            report = m.coverage(consumer, m.inventory(consumer, m.targets(consumer, all_targets=True)))
            check(not report['problems'], 'consumer coverage: ' + repr(report['problems']))
            check(set(report['services']) == set(m.SERVICES), 'all current services mechanically enumerated')
            print(f"Read-only model coverage: {report['modelCount']} models / {report['resourceTypeCount']} types / {report['keyCount']} keys")
        elif 'AWS_COMPARE_COVERAGE_ROOT' in os.environ:
            raise AssertionError('explicit coverage root is missing')
    print(f'AWS model comparison checks: PASS ({COUNT} assertions; no AWS connection)')


if __name__ == '__main__':
    main()
