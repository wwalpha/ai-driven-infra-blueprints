"""Static S3 comparison methods; container rules include their recursive contents."""

from dataclasses import replace

from comparison.contracts import ResourceContract, compare_producer_forms
from comparison.methods import OBJECT, properties
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference

from .references import SSE_KMS_KEY_CONDITIONS


def key_id_from_arn_selection(inputs, value):
    if (
        isinstance(value, Expression)
        and value.operation == "Select"
        and len(value.operands) == 2
        and str(value.operands[0]) == "1"
        and isinstance(split := value.operands[1], Expression)
        and split.operation == "Split"
        and len(split.operands) == 2
        and split.operands[0] == "/"
        and isinstance(source := split.operands[1], ResourceReference)
        and source["$attribute"] == "Arn"
        and not hasattr(source, "saved_literal")
    ):
        try:
            if inputs.resource_type(source) != "KMS.Key":
                return value
            inputs.producer_scope(source)
        except (Blocked, KeyError, ValueError, TypeError):
            return value
        # A KMS key ARN has a single slash followed by the formal KeyId.
        return ResourceReference(dict(source, **{"$attribute": "KeyId"}))
    return value


def compare_key_condition(inputs, left, right, path, *, export_origins):
    left, right = (key_id_from_arn_selection(inputs, value) for value in (left, right))
    if not any(
        isinstance(value, ResourceReference)
        and value["$attribute"] == "KeyId"
        and not hasattr(value, "saved_literal")
        for value in (left, right)
    ) or any(
        hasattr(value, "saved_literal")
        or isinstance(value, (dict, list))
        and not isinstance(value, ResourceReference)
        for value in (left, right)
    ):
        return NotImplemented
    outcome = compare_producer_forms(
        "KMS.Key",
        left,
        right,
        {"KeyArn", "KeyId"},
        resolve_literal=inputs.reference_literal,
        format_of=inputs.kms_format,
        project_arn=inputs.project_arn,
    )
    if outcome.equal is NotImplemented:
        return NotImplemented
    return outcome.equal, outcome.message or "KMS condition compares exact key forms"


RULES = {
    "S3.Bucket": properties(
        resource=ResourceContract(design_only=frozenset({"Region"})),
        objects="""
            BucketEncryption
            BucketEncryption.ServerSideEncryptionConfiguration[]
            BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault
            LifecycleConfiguration
            LifecycleConfiguration.Rules[]
            LifecycleConfiguration.Rules[].AbortIncompleteMultipartUpload
            LifecycleConfiguration.Rules[].NoncurrentVersionExpiration
            LifecycleConfiguration.Rules[].NoncurrentVersionTransitions[]
            LifecycleConfiguration.Rules[].TagFilters[]
            LifecycleConfiguration.Rules[].Transitions[]
            LoggingConfiguration
            LoggingConfiguration.TargetObjectKeyFormat
            LoggingConfiguration.TargetObjectKeyFormat.PartitionedPrefix
            LoggingConfiguration.TargetObjectKeyFormat.SimplePrefix
            NotificationConfiguration
            NotificationConfiguration.EventBridgeConfiguration
            NotificationConfiguration.LambdaConfigurations[]
            NotificationConfiguration.LambdaConfigurations[].Filter
            NotificationConfiguration.LambdaConfigurations[].Filter.S3Key
            NotificationConfiguration.LambdaConfigurations[].Filter.S3Key.Rules[]
            NotificationConfiguration.QueueConfigurations[]
            NotificationConfiguration.QueueConfigurations[].Filter
            NotificationConfiguration.QueueConfigurations[].Filter.S3Key
            NotificationConfiguration.QueueConfigurations[].Filter.S3Key.Rules[]
            NotificationConfiguration.TopicConfigurations[]
            NotificationConfiguration.TopicConfigurations[].Filter
            NotificationConfiguration.TopicConfigurations[].Filter.S3Key
            NotificationConfiguration.TopicConfigurations[].Filter.S3Key.Rules[]
            ObjectLockConfiguration
            ObjectLockConfiguration.Rule
            ObjectLockConfiguration.Rule.DefaultRetention
            OwnershipControls
            OwnershipControls.Rules[]
            PublicAccessBlockConfiguration
            ReplicationConfiguration
            ReplicationConfiguration.Rules[]
            ReplicationConfiguration.Rules[].DeleteMarkerReplication
            ReplicationConfiguration.Rules[].Destination
            ReplicationConfiguration.Rules[].Destination.EncryptionConfiguration
            ReplicationConfiguration.Rules[].Destination.Metrics
            ReplicationConfiguration.Rules[].Destination.Metrics.EventThreshold
            ReplicationConfiguration.Rules[].Destination.ReplicationTime
            ReplicationConfiguration.Rules[].Destination.ReplicationTime.Time
            ReplicationConfiguration.Rules[].Filter
            ReplicationConfiguration.Rules[].Filter.And
            ReplicationConfiguration.Rules[].Filter.And.TagFilters[]
            ReplicationConfiguration.Rules[].Filter.TagFilter
            ReplicationConfiguration.Rules[].SourceSelectionCriteria
            ReplicationConfiguration.Rules[].SourceSelectionCriteria.ReplicaModifications
            ReplicationConfiguration.Rules[].SourceSelectionCriteria.SseKmsEncryptedObjects
            Tags[]
            VersioningConfiguration
        """,
        ordered="""
            BucketEncryption.ServerSideEncryptionConfiguration
            LifecycleConfiguration.Rules
            LifecycleConfiguration.Rules[].NoncurrentVersionTransitions
            LifecycleConfiguration.Rules[].TagFilters
            LifecycleConfiguration.Rules[].Transitions
            NotificationConfiguration.LambdaConfigurations
            NotificationConfiguration.LambdaConfigurations[].Filter.S3Key.Rules
            NotificationConfiguration.QueueConfigurations
            NotificationConfiguration.QueueConfigurations[].Filter.S3Key.Rules
            NotificationConfiguration.TopicConfigurations
            NotificationConfiguration.TopicConfigurations[].Filter.S3Key.Rules
            OwnershipControls.Rules
            ReplicationConfiguration.Rules
            ReplicationConfiguration.Rules[].Filter.And.TagFilters
        """,
        references="""
            BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID
        """,
        scalars="""
            BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled
            BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm
            BucketName
            LifecycleConfiguration.Rules[].AbortIncompleteMultipartUpload.DaysAfterInitiation
            LifecycleConfiguration.Rules[].ExpirationDate
            LifecycleConfiguration.Rules[].ExpirationInDays
            LifecycleConfiguration.Rules[].ExpiredObjectDeleteMarker
            LifecycleConfiguration.Rules[].Id
            LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NewerNoncurrentVersions
            LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NoncurrentDays
            LifecycleConfiguration.Rules[].NoncurrentVersionTransitions[].NewerNoncurrentVersions
            LifecycleConfiguration.Rules[].NoncurrentVersionTransitions[].StorageClass
            LifecycleConfiguration.Rules[].NoncurrentVersionTransitions[].TransitionInDays
            LifecycleConfiguration.Rules[].ObjectSizeGreaterThan
            LifecycleConfiguration.Rules[].ObjectSizeLessThan
            LifecycleConfiguration.Rules[].Prefix
            LifecycleConfiguration.Rules[].Status
            LifecycleConfiguration.Rules[].TagFilters[].Key
            LifecycleConfiguration.Rules[].TagFilters[].Value
            LifecycleConfiguration.Rules[].Transitions[].StorageClass
            LifecycleConfiguration.Rules[].Transitions[].TransitionDate
            LifecycleConfiguration.Rules[].Transitions[].TransitionInDays
            LifecycleConfiguration.TransitionDefaultMinimumObjectSize
            LoggingConfiguration.DestinationBucketName
            LoggingConfiguration.LogFilePrefix
            LoggingConfiguration.TargetObjectKeyFormat.PartitionedPrefix.PartitionDateSource
            NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled
            NotificationConfiguration.LambdaConfigurations[].Event
            NotificationConfiguration.LambdaConfigurations[].Filter.S3Key.Rules[].Name
            NotificationConfiguration.LambdaConfigurations[].Filter.S3Key.Rules[].Value
            NotificationConfiguration.LambdaConfigurations[].Function
            NotificationConfiguration.QueueConfigurations[].Event
            NotificationConfiguration.QueueConfigurations[].Filter.S3Key.Rules[].Name
            NotificationConfiguration.QueueConfigurations[].Filter.S3Key.Rules[].Value
            NotificationConfiguration.QueueConfigurations[].Queue
            NotificationConfiguration.TopicConfigurations[].Event
            NotificationConfiguration.TopicConfigurations[].Filter.S3Key.Rules[].Name
            NotificationConfiguration.TopicConfigurations[].Filter.S3Key.Rules[].Value
            NotificationConfiguration.TopicConfigurations[].Topic
            ObjectLockConfiguration.ObjectLockEnabled
            ObjectLockConfiguration.Rule.DefaultRetention.Days
            ObjectLockConfiguration.Rule.DefaultRetention.Mode
            ObjectLockConfiguration.Rule.DefaultRetention.Years
            ObjectLockEnabled
            OwnershipControls.Rules[].ObjectOwnership
            PublicAccessBlockConfiguration.BlockPublicAcls
            PublicAccessBlockConfiguration.BlockPublicPolicy
            PublicAccessBlockConfiguration.IgnorePublicAcls
            PublicAccessBlockConfiguration.RestrictPublicBuckets
            ReplicationConfiguration.Role
            ReplicationConfiguration.Rules[].DeleteMarkerReplication.Status
            ReplicationConfiguration.Rules[].Destination.Account
            ReplicationConfiguration.Rules[].Destination.Bucket
            ReplicationConfiguration.Rules[].Destination.EncryptionConfiguration.ReplicaKmsKeyID
            ReplicationConfiguration.Rules[].Destination.Metrics.EventThreshold.Minutes
            ReplicationConfiguration.Rules[].Destination.Metrics.Status
            ReplicationConfiguration.Rules[].Destination.ReplicationTime.Status
            ReplicationConfiguration.Rules[].Destination.ReplicationTime.Time.Minutes
            ReplicationConfiguration.Rules[].Destination.StorageClass
            ReplicationConfiguration.Rules[].Filter.And.Prefix
            ReplicationConfiguration.Rules[].Filter.And.TagFilters[].Key
            ReplicationConfiguration.Rules[].Filter.And.TagFilters[].Value
            ReplicationConfiguration.Rules[].Filter.Prefix
            ReplicationConfiguration.Rules[].Filter.TagFilter.Key
            ReplicationConfiguration.Rules[].Filter.TagFilter.Value
            ReplicationConfiguration.Rules[].Id
            ReplicationConfiguration.Rules[].Priority
            ReplicationConfiguration.Rules[].SourceSelectionCriteria.ReplicaModifications.Status
            ReplicationConfiguration.Rules[].SourceSelectionCriteria.SseKmsEncryptedObjects.Status
            ReplicationConfiguration.Rules[].Status
            Tags[].Key
            Tags[].Value
            VersioningConfiguration.Status
        """,
        tags="""
            Tags
        """,
    ),
    "S3.BucketPolicy": properties(
        objects="""
            PolicyDocument
        """,
        scalars="""
            Bucket
        """,
    ),
}

for _condition in SSE_KMS_KEY_CONDITIONS:
    RULES["S3.BucketPolicy"][_condition.removeprefix("S3.BucketPolicy.")] = replace(
        OBJECT, selected_decision=compare_key_condition
    )
