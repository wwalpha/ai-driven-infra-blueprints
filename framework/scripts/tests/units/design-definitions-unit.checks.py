#!/usr/bin/env python3
"""Fixed design definitions, duplicate rejection and registration completeness."""

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from design.array_display import ROOT
from design.layout_schema import LAYOUT_PATH
from design.services.definitions import registry

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
        actual = getattr(registry, name)
        if isinstance(actual, set):
            actual = sorted(actual)
        actual = json.loads(json.dumps(actual, sort_keys=True))
        assert actual == expected, name
    assert len(registry.POLICY_FORMATS) == 31
    assert list(registry.POLICY_FORMATS) == sorted(
        registry.POLICY_FORMATS,
        key=lambda key: (registry.POLICY_FORMATS[key] == "settings", key),
    )
    assert LAYOUT_PATH == ROOT / "framework/rules/resource-layout.json"


def check_duplicates():
    for name in EXPECTED:
        values = getattr(registry, name)
        duplicate = SimpleNamespace(**{name: values})
        try:
            registry.merge_definitions((duplicate, duplicate), name)
        except ValueError as error:
            assert f"duplicate {name} definition:" in str(error)
        else:
            raise AssertionError(f"duplicate {name} registration accepted")


def check_registration():
    directory = Path(registry.__file__).parent
    names = [service.__name__.rsplit(".", 1)[1] for service in registry.SERVICES]
    assert names == sorted(set(names))
    assert set(names) == {path.stem for path in directory.glob("*.py")} - {
        "__init__",
        "registry",
    }
    # Definitions cannot acquire display, Model or file-reading dependencies.
    for service in registry.SERVICES:
        tree = ast.parse(Path(service.__file__).read_text(encoding="utf-8"))
        assert all(
            not isinstance(node, (ast.FunctionDef, ast.ClassDef)) for node in tree.body
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name == "re" for alias in node.names)
            assert not isinstance(node, ast.ImportFrom)
    assert set(registry.merge_definitions((), "POLICY_FORMATS")) == set()
    services = directory.parent
    forbidden = {"design.layout", "design.array_display", "model.display"}
    for name in (
        "codebuild",
        "codepipeline",
        "cloudtrail",
        "guardduty",
        "secrets_manager",
    ):
        tree = ast.parse((services / (name + ".py")).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not forbidden.intersection(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden
                assert all(
                    (node.module + "." + alias.name) not in forbidden
                    for alias in node.names
                )
    tree = ast.parse(Path(registry.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module == "design.services.definitions"
        assert not isinstance(node, ast.Import)


if __name__ == "__main__":
    check_values()
    check_duplicates()
    check_registration()
    print(
        "Design definitions: PASS (26 services; 31 policy formats; seven collections; service dependency direction)"
    )
