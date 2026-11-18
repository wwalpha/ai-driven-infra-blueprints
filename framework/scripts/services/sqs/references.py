"""SQS reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    return_attribute_properties={
        ("SQS.Queue", "QueueName"): "QueueName",
    },
    ref_attributes={
        "SQS.Queue": "QueueUrl",
    },
    getatt_attributes={
        "SQS.Queue": {"QueueName"},
    },
    reference_properties={
        "SQS.Queue.RedrivePolicy.deadLetterTargetArn": ("SQS.Queue", "Arn"),
        "SQS.QueuePolicy.Queues[]": ("SQS.Queue", "QueueUrl"),
    },
    arn_shapes={
        "SQS.Queue": (
            "QueueName",
            "arn:{partition}:sqs:{region}:{account}:{id}",
            {"id": r"(?=.{1,80}$)[A-Za-z0-9_-]+(?:\.fifo)?"},
        ),
    },
    special_properties={
        "SQS.QueuePolicy.PolicyDocument.Statement"
        + statement
        + ".Condition.ArnEquals.aws:SourceArn"
        + values: ("Events.Rule", "Arn")
        for statement in ("", "[]")
        for values in ("", "[]")
    },
)
