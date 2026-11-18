"""security-hub reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "SecurityHub.Hub": "ARN",
        "SecurityHub.FindingAggregator": "FindingAggregatorArn",
    },
    arn_attributes={
        "SecurityHub.Hub": "ARN",
        "SecurityHub.FindingAggregator": "FindingAggregatorArn",
    },
    arn_shapes={
        "SecurityHub.Hub": (
            {},
            "arn:{partition}:securityhub:{region}:{account}:hub/default",
            {},
        ),
    },
)
