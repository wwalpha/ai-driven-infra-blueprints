"""Static Logs comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "Logs.LogGroup": properties(
        objects="""
            DataProtectionPolicy
            ResourcePolicyDocument
            Tags[]
        """,
        references="""
            KmsKeyId
        """,
        scalars="""
            DeletionProtectionEnabled
            LogGroupClass
            LogGroupName
            RetentionInDays
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "Logs.MetricFilter": properties(
        objects="""
            MetricTransformations[]
            MetricTransformations[].Dimensions[]
        """,
        ordered="""
            MetricTransformations
            MetricTransformations[].Dimensions
        """,
        scalars="""
            FilterName
            FilterPattern
            LogGroupName
            MetricTransformations[].DefaultValue
            MetricTransformations[].Dimensions[].Key
            MetricTransformations[].Dimensions[].Value
            MetricTransformations[].MetricName
            MetricTransformations[].MetricNamespace
            MetricTransformations[].MetricValue
            MetricTransformations[].Unit
        """,
    ),
    "Logs.ResourcePolicy": properties(
        objects="""
            PolicyDocument
        """,
        scalars="""
            PolicyName
        """,
    ),
    "Logs.SubscriptionFilter": properties(
        scalars="""
            DestinationArn
            Distribution
            FilterName
            FilterPattern
            LogGroupName
            RoleArn
        """,
    ),
}
