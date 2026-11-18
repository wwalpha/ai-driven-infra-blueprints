"""SNS reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    return_attribute_properties={
        ("SNS.Topic", "TopicName"): "TopicName",
    },
    ref_attributes={
        "SNS.Topic": "TopicArn",
        "SNS.Subscription": "Ref",
    },
    getatt_attributes={
        "SNS.Topic": {"TopicName"},
    },
    arn_attributes={
        "SNS.Topic": "TopicArn",
    },
    reference_properties={
        "SNS.Subscription.RedrivePolicy.deadLetterTargetArn": ("SQS.Queue", "Arn"),
    },
    import_properties={
        "SNS.Subscription.TopicArn": ("SNS.Topic", "Arn"),
        "SNS.Subscription.SubscriptionRoleArn": ("IAM.Role", "Arn"),
    },
    arn_shapes={
        "SNS.Topic": (
            "TopicName",
            "arn:{partition}:sns:{region}:{account}:{id}",
            {"id": r"(?=.{1,256}$)[A-Za-z0-9_-]+(?:\.fifo)?"},
        ),
    },
)
