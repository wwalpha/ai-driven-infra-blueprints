"""Fixed sqs design definitions; no display-engine dependencies."""

POLICY_FORMATS = {
    "SQS.QueuePolicy.PolicyDocument": "statement",
    "SQS.Queue.RedriveAllowPolicy": "settings",
    "SQS.Queue.RedrivePolicy": "settings",
}
