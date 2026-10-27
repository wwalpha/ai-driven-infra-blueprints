"""Static Logs comparison methods; container rules include their recursive contents."""

from dataclasses import replace

from utils.reference_contracts import KMS_FORMS

from ..methods import REFERENCE, properties
from .kms import compare_forms

RULES = {
    "Logs.LogGroup": properties(
        objects="""
            DataProtectionPolicy
            ResourcePolicyDocument
            Tags[]
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

_path = "KmsKeyId"
RULES["Logs.LogGroup"][_path] = replace(
    REFERENCE, forms=KMS_FORMS["Logs.LogGroup." + _path], form_compare=compare_forms
)
