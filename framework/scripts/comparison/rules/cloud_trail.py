"""Static CloudTrail comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "CloudTrail.Trail": properties(
        objects="""
            AdvancedEventSelectors[]
            AdvancedEventSelectors[].FieldSelectors[]
            EventSelectors[]
            EventSelectors[].DataResources[]
            InsightSelectors[]
            Tags[]
        """,
        ordered="""
            AdvancedEventSelectors
            AdvancedEventSelectors[].FieldSelectors
            AdvancedEventSelectors[].FieldSelectors[].EndsWith
            AdvancedEventSelectors[].FieldSelectors[].Equals
            AdvancedEventSelectors[].FieldSelectors[].NotEndsWith
            AdvancedEventSelectors[].FieldSelectors[].NotEquals
            AdvancedEventSelectors[].FieldSelectors[].NotStartsWith
            AdvancedEventSelectors[].FieldSelectors[].StartsWith
            EventSelectors
            EventSelectors[].DataResources
            EventSelectors[].DataResources[].Values
            EventSelectors[].ExcludeManagementEventSources
            InsightSelectors
            InsightSelectors[].EventCategories
        """,
        references="""
            KMSKeyId
            S3BucketName
        """,
        scalars="""
            AdvancedEventSelectors[].FieldSelectors[].Field
            AdvancedEventSelectors[].Name
            CloudWatchLogsLogGroupArn
            CloudWatchLogsRoleArn
            EnableLogFileValidation
            EventSelectors[].DataResources[].Type
            EventSelectors[].IncludeManagementEvents
            EventSelectors[].ReadWriteType
            IncludeGlobalServiceEvents
            InsightSelectors[].InsightType
            IsLogging
            IsMultiRegionTrail
            IsOrganizationTrail
            S3KeyPrefix
            SnsTopicName
            Tags[].Key
            Tags[].Value
            TrailName
        """,
        tags="""
            Tags
        """,
    ),
}
