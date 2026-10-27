"""Static SQS comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "SQS.Queue": properties(
        objects="""
            RedriveAllowPolicy
            RedrivePolicy
            Tags[]
        """,
        scalars="""
            ContentBasedDeduplication
            DeduplicationScope
            DelaySeconds
            FifoQueue
            FifoThroughputLimit
            KmsDataKeyReusePeriodSeconds
            KmsMasterKeyId
            MaximumMessageSize
            MessageRetentionPeriod
            QueueName
            ReceiveMessageWaitTimeSeconds
            SqsManagedSseEnabled
            Tags[].Key
            Tags[].Value
            VisibilityTimeout
        """,
        tags="""
            Tags
        """,
    ),
    "SQS.QueuePolicy": properties(
        objects="""
            PolicyDocument
        """,
        ordered="""
            Queues
        """,
        references="""
            Queues[]
        """,
    ),
}
