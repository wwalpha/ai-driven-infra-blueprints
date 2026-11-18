"""eventbridge reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    return_attribute_properties={
        ("Events.Rule", "RuleName"): "Name",
    },
    ref_attributes={
        "Events.Rule": "RuleName",
        "Events.EventBus": "Name",
    },
    getatt_attributes={
        "Events.EventBus": {"Name"},
    },
    arn_shapes={
        "Events.EventBus": (
            "Name",
            "arn:{partition}:events:{region}:{account}:event-bus/{id}",
            {"id": r"[A-Za-z0-9._-]{1,256}"},
        ),
        "Events.Rule": (
            "Name",
            "arn:{partition}:events:{region}:{account}:rule/{bus}{id}",
            {"bus": r"(?:[A-Za-z0-9._-]{1,256}/)?", "id": r"[A-Za-z0-9._-]{1,64}"},
        ),
    },
    local_comparison={
        "Events.Rule.Targets[].Arn": {
            "CodePipeline.Pipeline": ("Arn",),
            "Lambda.Function": ("Arn",),
        },
        "Events.Rule.Targets[].RoleArn": {"IAM.Role": ("Arn",)},
        "Events.Rule.Targets[].DeadLetterConfig.Arn": {"SQS.Queue": ("Arn",)},
    },
    arn_components={"Events.Rule": ("EventBusName",)},
    arn_without_forms=frozenset(("Events.Rule",)),
)
