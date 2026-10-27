"""Static Config comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "Config.ConfigRule": properties(
        objects="""
            EvaluationModes[]
            InputParameters
            Scope
            Source
            Source.CustomPolicyDetails
            Source.SourceDetails[]
        """,
        ordered="""
            EvaluationModes
            Scope.ComplianceResourceTypes
            Source.SourceDetails
        """,
        scalars="""
            ConfigRuleName
            Description
            EvaluationModes[].Mode
            MaximumExecutionFrequency
            Scope.ComplianceResourceId
            Scope.TagKey
            Scope.TagValue
            Source.CustomPolicyDetails.EnableDebugLogDelivery
            Source.CustomPolicyDetails.PolicyRuntime
            Source.CustomPolicyDetails.PolicyText
            Source.Owner
            Source.SourceDetails[].EventSource
            Source.SourceDetails[].MaximumExecutionFrequency
            Source.SourceDetails[].MessageType
            Source.SourceIdentifier
        """,
    ),
    "Config.ConfigurationRecorder": properties(
        objects="""
            RecordingGroup
            RecordingGroup.ExclusionByResourceTypes
            RecordingGroup.RecordingStrategy
            RecordingMode
            RecordingMode.RecordingModeOverrides[]
        """,
        ordered="""
            RecordingGroup.ExclusionByResourceTypes.ResourceTypes
            RecordingGroup.ResourceTypes
            RecordingMode.RecordingModeOverrides
            RecordingMode.RecordingModeOverrides[].ResourceTypes
        """,
        scalars="""
            Name
            RecordingGroup.AllSupported
            RecordingGroup.IncludeGlobalResourceTypes
            RecordingGroup.RecordingStrategy.UseOnly
            RecordingMode.RecordingFrequency
            RecordingMode.RecordingModeOverrides[].Description
            RecordingMode.RecordingModeOverrides[].RecordingFrequency
            RoleARN
        """,
    ),
    "Config.DeliveryChannel": properties(
        objects="""
            ConfigSnapshotDeliveryProperties
        """,
        scalars="""
            ConfigSnapshotDeliveryProperties.DeliveryFrequency
            Name
            S3BucketName
            S3KeyPrefix
            S3KmsKeyArn
            SnsTopicARN
        """,
    ),
}
