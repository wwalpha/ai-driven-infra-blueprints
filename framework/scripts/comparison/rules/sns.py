"""Static SNS comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "SNS.Subscription": properties(
        objects="""
            DeliveryPolicy
            FilterPolicy
            RedrivePolicy
            ReplayPolicy
        """,
        scalars="""
            Endpoint
            FilterPolicyScope
            Protocol
            RawMessageDelivery
            Region
            SubscriptionRoleArn
            TopicArn
        """,
    ),
    "SNS.Topic": properties(
        objects="""
            ArchivePolicy
            DataProtectionPolicy
            DeliveryStatusLogging[]
            Tags[]
        """,
        ordered="""
            DeliveryStatusLogging
        """,
        scalars="""
            ContentBasedDeduplication
            DeliveryStatusLogging[].FailureFeedbackRoleArn
            DeliveryStatusLogging[].Protocol
            DeliveryStatusLogging[].SuccessFeedbackRoleArn
            DeliveryStatusLogging[].SuccessFeedbackSampleRate
            DisplayName
            FifoThroughputScope
            FifoTopic
            KmsMasterKeyId
            SignatureVersion
            Tags[].Key
            Tags[].Value
            TopicName
            TracingConfig
        """,
        tags="""
            Tags
        """,
    ),
    "SNS.TopicPolicy": properties(
        objects="""
            PolicyDocument
        """,
        ordered="""
            Topics
        """,
    ),
}
