"""Fixed sns design definitions; no display-engine dependencies."""

POLICY_FORMATS = {
    "SNS.TopicPolicy.PolicyDocument": "statement",
    "SNS.Subscription.DeliveryPolicy": "settings",
    "SNS.Subscription.FilterPolicy": "settings",
    "SNS.Subscription.RedrivePolicy": "settings",
    "SNS.Subscription.ReplayPolicy": "settings",
    "SNS.Topic.ArchivePolicy": "settings",
    "SNS.Topic.DataProtectionPolicy": "settings",
}
