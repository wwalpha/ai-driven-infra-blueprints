"""Read-only display layout metadata without Model/rendering dependencies."""

import json
import re
from pathlib import Path

from reference_contracts import LINKED_LIST_PROPERTIES as LINKED_LIST_PROPERTIES
from reference_contracts import SUBNET_LIST_PROPERTIES as SUBNET_LIST_PROPERTIES

from utils.input_cache import input_text

LAYOUT_PATH = Path(__file__).resolve().parents[2] / "rules" / "resource-layout.json"

LAYOUTS = json.loads(input_text(LAYOUT_PATH, encoding="utf-8"))

RESOURCE_PROPERTY_PREFIXES = tuple(name + "." for name in LAYOUTS)

GROUPED = {name: rule for name, rule in LAYOUTS.items() if isinstance(rule, dict)}

GROUPED_RESOURCE_TYPES = {
    rule["parent"]: {name for name, child in GROUPED.items() if child["parent"] == rule["parent"]}
    for rule in GROUPED.values()
}

IMPLICIT_GROUPED_PROPERTIES = {
    name: {rule["parentProperty"]} for name, rule in GROUPED.items()
}

DETAILS_HEADING = "## リソース詳細"

RESOURCE = re.compile(r"^### ([A-Za-z0-9]+\.[A-Za-z0-9]+): ([^<>|`\s](?:[^<>|`]*[^<>|`\s])?)$")

ANCHOR = re.compile(r'<a\s+id="([^"]+)"\s*></a>')

RESOURCE_ID = re.compile(r"^<!-- resource-logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) -->$")

CHILD = re.compile(
    r'^<a id="([A-Za-z0-9_.-]+)"></a><!-- logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) -->\s*'
)

ROTATION_SCHEDULE = "SecretsManager.RotationSchedule"

LAMBDA_PERMISSION = "Lambda.Permission"

PERMISSION_METADATA = re.compile(r'^<!-- lambda-permission: (.+?) -->\s*')

CHILD_NAME = re.compile(r'^([^<>|`\n：]+)：')

HEADER = "| No. | Property | Value | Source / Comment |"

ALIGNMENT = "| ---: | --- | --- | --- |"

CODEBUILD_VPC_PROPERTIES = {"CodeBuild.Project.VpcConfig.Subnets", "CodeBuild.Project.VpcConfig.SecurityGroupIds"}

SUBNET_LIST_SOURCE = re.compile(r'^<!-- subnet-list-source: ("(?:[^"\\]|\\.)*") --> ')

GUARDDUTY_FEATURE = "GuardDuty.Detector.Features."

GUARDDUTY_FORMAL_FEATURE = "GuardDuty.Detector.Features[]."

CLOUDTRAIL_DATA_RESOURCE = re.compile(r"^EventSelectors\.DataResources\[([1-9]\d*)\]\.(S3|Lambda)$")

CLOUDTRAIL_RESOURCE_TYPES = {"S3": "AWS::S3::Object", "Lambda": "AWS::Lambda::Function"}

CLOUDTRAIL_FORMAL_DATA_RESOURCE = "CloudTrail.Trail.EventSelectors[].DataResources[]."

STACK_DESIGN = "cloudformation-stacks.md"

STACK_HEADER = "| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |"

SECURITY_GROUP_TYPES = {"EC2.SecurityGroup", "EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}

RESOURCE_REFERENCE_PROPERTIES = {
    "Config.ConfigurationRecorder.RoleARN": ("IAM.Role", "RoleName"),
    "KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN": ("KMS.Key", "KeyId"),
    "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN": ("S3.Bucket", "BucketName"),
    "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN": ("IAM.Role", "RoleName"),
    # DataSource permissions resolve this Group identity link to its transient Arn output.
    "QuickSight.DataSource.Permissions[].Principal": ("QuickSight.Group", "GroupName"),
}

HIDDEN_PROPERTIES = {
    "CodeCommit.Repository.RepositoryId",
    # These Id attributes return ARNs, not persistable observed identifiers.
    "SecretsManager.Secret.Id",
    "SecretsManager.RotationSchedule.Id",
    "QuickSight.Group.Arn",
}

REQUIRED_NAME_TAG_TYPES = {"EC2.VPCEndpoint", "EC2.Instance"}


def resource_anchor(service_id: str, name: str, resource_type: str = "") -> str:
    """Use the displayed resource name as the navigation identity."""
    kind = {"Config.ConfigurationRecorder": "configuration-recorder",
            "Config.DeliveryChannel": "delivery-channel"}.get(resource_type)
    prefix = f"{service_id}-{kind}" if kind else service_id
    return prefix + "-" + re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-")


POLICY_FORMATS = {
    "ApiGateway.RestApi.Policy": "statement",
    "DynamoDB.GlobalTable.Replicas[].ReplicaStreamSpecification.ResourcePolicy.PolicyDocument": "statement",
    "DynamoDB.GlobalTable.Replicas[].ResourcePolicy.PolicyDocument": "statement",
    "DynamoDB.Table.ResourcePolicy": "wrapped-statement",
    "DynamoDB.Table.StreamSpecification.ResourcePolicy.PolicyDocument": "statement",
    "EC2.VPCEndpoint.PolicyDocument": "statement",
    "ECR.Repository.RepositoryPolicyText": "statement",
    "Events.EventBus.Policy": "statement",
    "IAM.ManagedPolicy.PolicyDocument": "statement",
    "IAM.Role.AssumeRolePolicyDocument": "statement",
    "IAM.Role.Policies[].PolicyDocument": "statement",
    "IAM.User.Policies[].PolicyDocument": "statement",
    "KMS.Key.KeyPolicy": "statement",
    "Logs.LogGroup.ResourcePolicyDocument": "statement",
    "Logs.ResourcePolicy.PolicyDocument": "statement",
    "S3.BucketPolicy.PolicyDocument": "statement",
    "SNS.TopicPolicy.PolicyDocument": "statement",
    "SQS.QueuePolicy.PolicyDocument": "statement",
    "SSO.PermissionSet.InlinePolicy": "statement",
    "SecretsManager.ResourcePolicy.ResourcePolicy": "statement",
    "ECR.Repository.LifecyclePolicy": "settings",
    "Logs.LogGroup.DataProtectionPolicy": "settings",
    "Organizations.Policy.Content": "settings",
    "SNS.Subscription.DeliveryPolicy": "settings",
    "SNS.Subscription.FilterPolicy": "settings",
    "SNS.Subscription.RedrivePolicy": "settings",
    "SNS.Subscription.ReplayPolicy": "settings",
    "SNS.Topic.ArchivePolicy": "settings",
    "SNS.Topic.DataProtectionPolicy": "settings",
    "SQS.Queue.RedriveAllowPolicy": "settings",
    "SQS.Queue.RedrivePolicy": "settings",
}

CODEBUILD_FORMAL_VARIABLE = "CodeBuild.Project.Environment.EnvironmentVariables[]."

CODEBUILD_VARIABLE = "CodeBuild.Project.Environment.Variables."
CODEBUILD_VARIABLE_TYPE = re.compile(r"^<!-- codebuild-variable-type: (PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER) -->\s*")
CODEPIPELINE_STAGE = re.compile(r"^Stages\[([1-9]\d*)\]\.(?:Actions(?:\[([1-9]\d*)\])?\.)?(.+)$")
CODEPIPELINE_CONFIGURATION = "CodePipeline.Pipeline.Stages[].Actions[].Configuration"
COMPACT_SOURCE = re.compile(r'^<!-- compact-source: (.+?) --> ')
COMPACT_FIELDS = {
    CODEBUILD_FORMAL_VARIABLE + 'Name': (('Name', 'Type', 'Value'), None),
    'CloudTrail.Trail.EventSelectors[].DataResources[].Type': (('Type', 'Values'), 'Values'),
}
PACKED_ARRAY_PREFIXES = ('CodePipeline.Pipeline.Stages[]',)
