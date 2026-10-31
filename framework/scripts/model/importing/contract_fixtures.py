"""Shared offline SDK shape responses for adapter contract evidence."""

import copy
from datetime import datetime, timezone
from functools import lru_cache, partial

from botocore import xform_name
from botocore.exceptions import ClientError, ParamValidationError
from botocore.session import Session as ModelSession
from botocore.validate import validate_parameters

from model.adapters import aws as m

ACCOUNT = "123456789012"
TARGET = {
    "awsAccountId": ACCOUNT,
    "awsRegion": "ap-northeast-1",
    "environment": "dev",
    "directory": ACCOUNT,
    "iacEngine": "cloudformation",
}


class InvalidFixture(ValueError):
    """The offline fixture violates its SDK response contract."""


def shape_value(shape, depth=0, seen=()):
    """SDK-schema synthetic values, independent of comparator field mappings."""
    terminal = depth > 10 or shape.name in seen
    seen = (*seen, shape.name)
    kind = shape.type_name
    if kind == "structure":
        return {
            name: shape_value(child, depth + 1, seen)
            for name, child in shape.members.items()
            if not terminal or name in shape.required_members
        }
    if kind == "list":
        return (
            [
                shape_value(shape.member, depth + 1, seen)
                for _ in range(max(1, shape.metadata.get("min", 1)))
            ]
            if not terminal
            else []
        )
    if kind == "map":
        return (
            {
                shape_value(shape.key, depth + 1, seen): shape_value(
                    shape.value, depth + 1, seen
                )
            }
            if not terminal
            else {}
        )
    if kind == "boolean":
        return True
    if kind in {"integer", "long"}:
        return max(1, shape.metadata.get("min", 1))
    if kind in {"float", "double"}:
        return max(1.0, shape.metadata.get("min", 1.0))
    if kind == "timestamp":
        return datetime(2026, 1, 1, tzinfo=timezone.utc)
    if kind == "blob":
        return b"fixture"
    return (
        shape.enum[0]
        if shape.enum
        else "fixture" + "x" * max(0, shape.metadata.get("min", 0) - 7)
    )


def remove_tokens(value):
    if isinstance(value, dict):
        return {
            key: remove_tokens(item)
            for key, item in value.items()
            if key
            not in {
                "NextToken",
                "nextToken",
                "NextMarker",
                "Marker",
                "NextRecordName",
                "NextRecordType",
                "NextRecordIdentifier",
                "ContinuationToken",
                "NextContinuationToken",
                "nextMarker",
            }
        }
    if isinstance(value, list):
        return [remove_tokens(item) for item in value]
    return value


def set_path(tree, path, value):
    parts = path.split(".")
    node = tree
    for part in parts[:-1]:
        node = node[part][0] if isinstance(node.get(part), list) else node[part]
    node[parts[-1]] = value


PATCHES = {
    ("quicksight", "describe_group"): {
        "Group.Arn": "arn:aws:quicksight:ap-northeast-1:123456789012:group/default/fixture"
    },
    ("quicksight", "describe_data_source"): {
        "DataSource.Arn": "arn:aws:quicksight:ap-northeast-1:123456789012:datasource/fixture"
    },
    ("quicksight", "describe_data_source_permissions"): {
        "DataSourceArn": "arn:aws:quicksight:ap-northeast-1:123456789012:datasource/fixture"
    },
    ("quicksight", "describe_vpc_connection"): {
        "VPCConnection.Arn": "arn:aws:quicksight:ap-northeast-1:123456789012:vpcConnection/fixture"
    },
    ("sts", "get_caller_identity"): {
        "Account": ACCOUNT,
        "Arn": "arn:aws:iam::" + ACCOUNT + ":user/offline",
    },
    ("logs", "describe_log_groups"): {"logGroups.logGroupName": "fixture"},
    ("codecommit", "get_repository"): {"repositoryMetadata.repositoryName": "fixture"},
    ("codebuild", "batch_get_projects"): {"projects.name": "fixture"},
    ("codepipeline", "get_pipeline"): {"pipeline.name": "fixture"},
    ("config", "describe_configuration_recorders"): {
        "ConfigurationRecorders.name": "fixture"
    },
    ("config", "describe_delivery_channels"): {"DeliveryChannels.name": "fixture"},
    ("s3", "list_buckets"): {
        "Buckets.Name": "fixture",
        "Buckets.BucketArn": "arn:aws:s3:::fixture",
    },
    ("s3", "get_object_lock_configuration"): {
        "ObjectLockConfiguration.ObjectLockEnabled": "Enabled"
    },
    ("kms", "list_aliases"): {
        "Aliases.AliasName": "fixture",
        "Aliases.TargetKeyId": "fixture",
    },
    ("kms", "describe_key"): {"KeyMetadata.KeyId": "fixture"},
    ("glue", "get_catalogs"): {"CatalogList.Name": "fixture"},
    ("iam", "list_policies"): {
        "Policies.PolicyName": "fixture",
        "Policies.DefaultVersionId": "v1",
    },
    ("iam", "get_role"): {
        "Role.RoleName": "fixture",
        "Role.AssumeRolePolicyDocument": '{"Version":"2012-10-17","Statement":[]}',
    },
    ("iam", "get_role_policy"): {
        "PolicyDocument": '{"Version":"2012-10-17","Statement":[]}'
    },
    ("iam", "get_user_policy"): {
        "PolicyDocument": '{"Version":"2012-10-17","Statement":[]}'
    },
    ("iam", "get_policy_version"): {
        "PolicyVersion.Document": '{"Version":"2012-10-17","Statement":[]}'
    },
    ("kms", "get_key_policy"): {"Policy": '{"Version":"2012-10-17","Statement":[]}'},
    ("events", "describe_rule"): {
        "Name": "fixture",
        "EventPattern": '{"source":["fixture"]}',
    },
    ("guardduty", "get_detector"): {"Status": "ENABLED"},
    ("guardduty", "get_malware_protection_plan"): {
        "ProtectedResource.S3Bucket.BucketName": "fixture"
    },
    ("route53", "list_hosted_zones"): {
        "HostedZones.Name": "fixture.",
        "HostedZones.Id": "fixture",
        "IsTruncated": False,
    },
    ("route53", "get_hosted_zone"): {
        "HostedZone.Id": "fixture",
        "HostedZone.Name": "fixture.",
        "VPCs.VPCId": "fixture",
    },
    ("route53", "list_resource_record_sets"): {
        "ResourceRecordSets.Name": "fixture.",
        "ResourceRecordSets.Type": "A",
        "IsTruncated": False,
    },
    ("macie2", "list_classification_jobs"): {"items.name": "fixture"},
    ("lambda", "get_policy"): {
        "Policy": '{"Version":"2012-10-17","Statement":[{"Sid":"fixture","Action":"lambda:InvokeFunction","Principal":{"Service":"s3.amazonaws.com"},"Condition":{"ArnLike":{"AWS:SourceArn":"fixture"},"StringEquals":{"AWS:SourceAccount":"123456789012"}}}]}'
    },
    ("ec2", "describe_security_group_rules"): {
        "SecurityGroupRules.GroupId": "fixture",
        "SecurityGroupRules.IsEgress": False,
    },
    ("sqs", "get_queue_attributes"): {
        "Attributes": {
            "QueueArn": "arn:aws:sqs:ap-northeast-1:" + ACCOUNT + ":fixture",
            "FifoQueue": "false",
            "MessageRetentionPeriod": "604800",
            "Policy": '{"Version":"2012-10-17","Statement":[]}',
        }
    },
    ("s3", "get_bucket_policy"): {"Policy": '{"Version":"2012-10-17","Statement":[]}'},
    ("ec2", "describe_volumes"): {"Volumes.VolumeId": "fixture"},
    ("ec2", "describe_vpcs"): {"Vpcs.Tags.Key": "Name"},
    ("ec2", "describe_subnets"): {"Subnets.Tags.Key": "Name"},
    ("ec2", "describe_route_tables"): {
        "RouteTables.Associations.SubnetId": "fixture",
        "RouteTables.Associations.AssociationState.State": "associated",
        "RouteTables.Tags.Key": "Name",
    },
    ("ec2", "describe_flow_logs"): {
        "FlowLogs.ResourceId": "vpc-fixture",
        "FlowLogs.Tags.Key": "Name",
    },
    ("cloudformation", "describe_stacks"): {
        "Stacks.StackId": "arn:aws:cloudformation:ap-northeast-1:"
        + ACCOUNT
        + ":stack/fixture/id",
        "Stacks.StackName": "fixture",
        "Stacks.StackStatus": "CREATE_COMPLETE",
        "Stacks.Outputs.OutputKey": "FixtureExport",
        "Stacks.Outputs.OutputValue": "confirmed-export-value",
        "Stacks.Outputs.ExportName": "fixture-export",
    },
    ("cloudformation", "list_exports"): {
        "Exports.ExportingStackId": "arn:aws:cloudformation:ap-northeast-1:"
        + ACCOUNT
        + ":stack/fixture/id",
        "Exports.Name": "fixture-export",
        "Exports.Value": "confirmed-export-value",
    },
}


@lru_cache(maxsize=None)
def service_model(service):
    """Share immutable SDK schemas only; never share acquisition/target state."""
    return ModelSession().get_service_model(service)


def operation_model(model, operation):
    names = {xform_name(name): name for name in model.operation_names}
    return model.operation_model(names[operation])


def sdk_response(model, service, operation, egress=False):
    response = remove_tokens(
        shape_value(operation_model(model, operation).output_shape)
    )
    for name in ("IsTruncated", "HasMoreResults", "HasMoreDestinations"):
        if name in response:
            response[name] = False
    if operation == "describe_delivery_stream":
        response["DeliveryStreamDescription"]["HasMoreDestinations"] = False
    for path, value in PATCHES.get((service, operation), {}).items():
        set_path(response, path, copy.deepcopy(value))
    if (service, operation) == ("codebuild", "batch_get_projects"):
        response.pop("projectsNotFound", None)
    if operation == "describe_security_group_rules" and egress:
        response["SecurityGroupRules"][0]["IsEgress"] = True
    return response


class SchemaClient:
    def __init__(self, context, service):
        self.context, self.service = context, service
        self.model = service_model(service)

    def __getattr__(self, operation):
        operation_model(
            self.model, operation
        )  # Unknown API names fail before invocation.
        return partial(self.request, operation)

    def can_paginate(self, operation):
        operation_model(self.model, operation)
        # SDK paginator behavior belongs to the retained Stubber IT.
        return False

    def request(self, operation, **inputs):
        model = operation_model(self.model, operation)
        try:
            if model.input_shape is not None:
                validate_parameters(inputs, model.input_shape)
            elif inputs:
                raise ValueError("operation has no inputs")
        except (ValueError, TypeError, ParamValidationError) as error:
            self.context.fixture_error = InvalidFixture(
                f"Invalid fixture request for {self.service}.{operation}: {error}"
            )
            raise self.context.fixture_error from error
        self.context.request_count += 1
        fault = self.context.fault
        fault = (
            fault.get((self.service, operation)) if isinstance(fault, dict) else fault
        )
        if fault:
            raise ClientError(
                {
                    "Error": {
                        "Code": "ResourceNotFoundException"
                        if fault == "missing"
                        else "AccessDeniedException",
                        "Message": "synthetic failure",
                    }
                },
                model.name,
            )
        try:
            response = sdk_response(
                self.model, self.service, operation, self.context.egress
            )
            validate_parameters(response, model.output_shape)
        except Exception as error:
            self.context.fixture_error = InvalidFixture(
                f"Invalid fixture response for {self.service}.{operation}: {error}"
            )
            raise self.context.fixture_error from error
        return response


class SchemaOffline(m.Context):
    """Real Context/adapter/cache; schema transport without boto3 or credentials."""

    def __init__(self, root, fault=None, target=TARGET):
        super().__init__(root, target, session=self)
        self.fault, self.request_count, self.egress = fault, 0, False
        self.fixture_error = None

    def _call(self, service, operation, **inputs):
        try:
            return super()._call(service, operation, **inputs)
        finally:
            if self.fixture_error is not None:
                raise self.fixture_error

    def client(self, service, **options):
        if service not in self.clients:
            self.clients[service] = SchemaClient(self, service)
        return self.clients[service]
