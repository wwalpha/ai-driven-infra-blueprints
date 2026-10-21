"""Offline AWS CLI and SDK/mapping regressions. All network access is forbidden.

Synthetic SDK responses and test-created Models are the only regression inputs. Missing boto3 is a failure.
"""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model.files import read_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_sources import write_model

import pytest

from support.pytest_cli import run

import copy

from contextlib import ExitStack, redirect_stderr, redirect_stdout

import importlib.util

import io

import json

import os

import socket

from types import SimpleNamespace

from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import boto3

from botocore.stub import Stubber

from model.files import model_file_contents

from model.adapters import aws as m

COUNT = 0

def check(condition, message):
    global COUNT
    assert condition, message
    COUNT += 1

def expect(error_type, function):
    with pytest.raises(error_type):
        function()
    check(True, 'expected rejection')

STACK_MODEL = 'desired.stack.001.name=fixture\ndesired.stack.001.template=a.yaml\ndesired.stack.001.parameters=a.json\ndesired.stack.001.deployOrder=1\ndesired.deployment.maxConcurrentStacks=1\n'

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
    def __init__(self, root, fault=None, target=TARGET):
        session = boto3.Session(aws_access_key_id='offline', aws_secret_access_key='offline', region_name=TARGET['awsRegion'])
        super().__init__(root, target, session)
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
        self.model = SimpleNamespace(path=ctx.root / 'model' / ctx.target['environment'] / ctx.target['directory'] / (service + '.properties'), service=service, resources=[self], values={},
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
    'security-group': ('EC2.SecurityGroup', 'GroupDescription', 'fixture'),
    'sqs': ('SQS.Queue', 'MessageRetentionPeriod', 604800),
    'transit-gateway': ('EC2.TransitGatewayVpcAttachment', 'TransitGatewayId', 'fixture'),
    'vpc': ('EC2.VPC', 'CidrBlock', 'fixture'),
    'vpc-endpoint': ('EC2.VPCEndpoint', 'ServiceName', 'fixture'),
}

def acquired(value):
    # Optional array members may be absent; [MISSING] is still not an acquired value.
    return any(acquired(item) for item in value) if isinstance(value, list) else value != m.MISSING

def model_text(kind, rows, number='001', logical='fixture', anchor='fixture', metadata='', allocation=True):
    text = f"desired.resource.{number}.resourceType={kind}\ndesired.resource.{number}.logicalId={kind.replace('.', '_')}_{int(number):03d}\n" + metadata
    if allocation:
        text += 'desired.service.identity.lastAllocated=' + json.dumps({kind: int(number)}) + '\n'
    for index, (prop, value) in enumerate(rows, 1):
        text += f'desired.row.{number}-{index:03d}.property={prop}\ndesired.row.{number}-{index:03d}.value={value}\ndesired.row.{number}-{index:03d}.comment=fixture\n'
    return text

@pytest.fixture(autouse=True)
def offline_network():
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network is forbidden in offline checks")):
        yield


__all__ = ['ACCOUNT', 'COUNT', 'ExitStack', 'FakeResource', 'Offline', 'PATCHES', 'Path', 'REPRESENTATIVES', 'STACK_MODEL', 'SimpleNamespace', 'Stubber', 'TARGET', 'acquired', 'boto3', 'check', 'copy', 'expect', 'importlib', 'io', 'json', 'm', 'model_file_contents', 'model_text', 'offline_network', 'os', 'patch', 'pytest', 'read_model', 'redirect_stderr', 'redirect_stdout', 'remove_tokens', 'run', 'set_path', 'shape_value', 'socket', 'sys', 'write_model']
