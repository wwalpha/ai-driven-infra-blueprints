"""Fixed sqs design definitions; no display-engine dependencies."""

import re

POLICY_DOCUMENT = "SQS.QueuePolicy.PolicyDocument"

POLICY_FORMATS = {
    POLICY_DOCUMENT: "statement",
    "SQS.Queue.RedriveAllowPolicy": "settings",
    "SQS.Queue.RedrivePolicy": "settings",
}

FIFO_PROPERTIES = {"SQS.Queue": ("QueueName", "FifoQueue")}


def queue_name_errors(kind: str, field: str, value: str) -> list[str]:
    if (
        kind in FIFO_PROPERTIES
        and field == FIFO_PROPERTIES[kind][0]
        and (len(value) > 80 or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.fifo)?", value))
    ):
        return ["SQS QueueName has invalid characters or exceeds 80 characters"]
    return []


COLLAPSED_POLICY_DOCUMENTS = {POLICY_DOCUMENT}


PROVIDER_NAME_CHECKS = {"SQS.Queue": queue_name_errors}
