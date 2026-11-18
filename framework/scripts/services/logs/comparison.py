"""Static Logs comparison methods; container rules include their recursive contents."""

from dataclasses import replace
from functools import partial

from comparison.contracts import compare_producer_forms
from comparison.methods import REFERENCE, properties

from .references import REFERENCES

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
    REFERENCE,
    forms=REFERENCES.format_limits["Logs.LogGroup." + _path],
    form_compare=partial(compare_producer_forms, "KMS.Key"),
)
