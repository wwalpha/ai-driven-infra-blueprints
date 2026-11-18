#!/usr/bin/env python3
"""Fixed design definitions, duplicate rejection and registration completeness."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collections.abc import Mapping, Set

from design.array_display import ROOT
from design.layout_schema import LAYOUT_PATH
from services.manifest import DECLARATIONS
from services.registry import REGISTRY

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


EXPECTED = {
    "COMPACT_FIELDS": {
        "CloudTrail.Trail.EventSelectors[].DataResources[].Type": [
            ["Type", "Values"],
            "Values",
        ],
        "CodeBuild.Project.Environment.EnvironmentVariables[].Name": [
            ["Name", "Type", "Value"],
            None,
        ],
    },
    "IMPORT_PENDING_PROPERTIES": [
        "Config.ConfigurationRecorder.RoleARN",
        "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN",
        "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN",
    ],
    "HIDDEN_PROPERTIES": [
        "CodeCommit.Repository.RepositoryId",
        "LakeFormation.DataLakeSettings.Id",
        "LakeFormation.PrincipalPermissions.PrincipalIdentifier",
        "LakeFormation.PrincipalPermissions.ResourceIdentifier",
        "LakeFormation.Resource.Id",
        "QuickSight.Group.Arn",
        "SecretsManager.RotationSchedule.Id",
        "SecretsManager.Secret.Id",
    ],
    "PACKED_ARRAY_PREFIXES": ["CodePipeline.Pipeline.Stages[]"],
    "POLICY_FORMATS": {
        "ApiGateway.RestApi.Policy": "statement",
        "DynamoDB.GlobalTable.Replicas[].ReplicaStreamSpecification.ResourcePolicy.PolicyDocument": "statement",
        "DynamoDB.GlobalTable.Replicas[].ResourcePolicy.PolicyDocument": "statement",
        "DynamoDB.Table.ResourcePolicy": "wrapped-statement",
        "DynamoDB.Table.StreamSpecification.ResourcePolicy.PolicyDocument": "statement",
        "EC2.VPCEndpoint.PolicyDocument": "statement",
        "ECR.Repository.LifecyclePolicy": "settings",
        "ECR.Repository.RepositoryPolicyText": "statement",
        "Events.EventBus.Policy": "statement",
        "IAM.ManagedPolicy.PolicyDocument": "statement",
        "IAM.Role.AssumeRolePolicyDocument": "statement",
        "IAM.Role.Policies[].PolicyDocument": "statement",
        "IAM.User.Policies[].PolicyDocument": "statement",
        "KMS.Key.KeyPolicy": "statement",
        "Logs.LogGroup.DataProtectionPolicy": "settings",
        "Logs.LogGroup.ResourcePolicyDocument": "statement",
        "Logs.ResourcePolicy.PolicyDocument": "statement",
        "Organizations.Policy.Content": "settings",
        "S3.BucketPolicy.PolicyDocument": "statement",
        "SNS.Subscription.DeliveryPolicy": "settings",
        "SNS.Subscription.FilterPolicy": "settings",
        "SNS.Subscription.RedrivePolicy": "settings",
        "SNS.Subscription.ReplayPolicy": "settings",
        "SNS.Topic.ArchivePolicy": "settings",
        "SNS.Topic.DataProtectionPolicy": "settings",
        "SNS.TopicPolicy.PolicyDocument": "statement",
        "SQS.Queue.RedriveAllowPolicy": "settings",
        "SQS.Queue.RedrivePolicy": "settings",
        "SQS.QueuePolicy.PolicyDocument": "statement",
        "SSM.ResourcePolicy.Policy": "statement",
        "SSO.PermissionSet.InlinePolicy": "statement",
        "SecretsManager.ResourcePolicy.ResourcePolicy": "statement",
    },
    "REQUIRED_NAME_TAG_TYPES": ["EC2.Instance", "EC2.VPCEndpoint"],
    "RESOURCE_REFERENCE_PROPERTIES": {
        "Config.ConfigurationRecorder.RoleARN": ["IAM.Role", "RoleName"],
        "KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN": [
            "KMS.Key",
            "KeyId",
        ],
        "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN": [
            "S3.Bucket",
            "BucketName",
        ],
        "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN": [
            "IAM.Role",
            "RoleName",
        ],
        "QuickSight.DataSource.Permissions[].Principal": [
            "QuickSight.Group",
            "GroupName",
        ],
    },
}


def check_values():
    for name, expected in EXPECTED.items():
        actual = REGISTRY.design_tables[name]
        if isinstance(actual, Set):
            actual = sorted(actual)
        elif isinstance(actual, Mapping):
            actual = dict(actual)
        actual = json.loads(json.dumps(actual, sort_keys=True))
        assert actual == expected, name
    assert len(REGISTRY.design_tables["POLICY_FORMATS"]) == 32
    assert list(REGISTRY.design_tables["POLICY_FORMATS"]) == sorted(
        REGISTRY.design_tables["POLICY_FORMATS"],
        key=lambda key: (
            REGISTRY.design_tables["POLICY_FORMATS"][key] == "settings",
            key,
        ),
    )
    assert LAYOUT_PATH == ROOT / "framework/rules/resource-layout.json"


def check_registration():
    # Every static definition key is indexed under the service and ResourceType that owns it.
    for service in DECLARATIONS:
        if service.design is None:
            continue
        for name in REGISTRY.design_tables:
            for key in getattr(service.design, name, ()):
                kind = ".".join(key.split(".")[:2])
                assert REGISTRY.owner(kind) == service.name
                assert key in REGISTRY.design(kind)[name]


if __name__ == "__main__":
    check_values()
    check_registration()
    print("Design definitions: PASS")
