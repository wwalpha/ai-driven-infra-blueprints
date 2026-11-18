"""AutoScaling reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "AutoScaling.AutoScalingGroup": "AutoScalingGroupName",
        "AutoScaling.LifecycleHook": "LifecycleHookName",
        "AutoScaling.ScalingPolicy": "Arn",
        "AutoScaling.ScheduledAction": "ScheduledActionName",
    },
    arn_attributes={
        "AutoScaling.AutoScalingGroup": "AutoScalingGroupARN",
    },
    import_properties={
        "AutoScaling.AutoScalingGroup.ServiceLinkedRoleARN": ("IAM.Role", "Arn"),
        "AutoScaling.AutoScalingGroup.LifecycleHookSpecificationList[].RoleARN": (
            "IAM.Role",
            "Arn",
        ),
        "AutoScaling.LifecycleHook.RoleARN": ("IAM.Role", "Arn"),
    },
)
