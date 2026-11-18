"""Scheduler reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "Scheduler.Schedule": "Name",
    },
    linked_subnets={
        "Scheduler.Schedule.Target.EcsParameters.NetworkConfiguration.AwsvpcConfiguration.Subnets[]",
    },
    import_properties={
        "Scheduler.Schedule.Target.DeadLetterConfig.Arn": ("SQS.Queue", "Arn"),
        "Scheduler.Schedule.Target.RoleArn": ("IAM.Role", "Arn"),
    },
    arn_shapes={
        "Scheduler.Schedule": (
            {"Name": "id", "GroupName": "group"},
            "arn:{partition}:scheduler:{region}:{account}:schedule/{group}/{id}",
            {"id": r"[A-Za-z0-9_.-]{1,64}", "group": r"[A-Za-z0-9_.-]{1,64}"},
        ),
    },
    arn_defaults={
        ("Scheduler.Schedule", "GroupName"): "default",
    },
    local_comparison={
        "Scheduler.Schedule.Target.Arn": {"Lambda.Function": ("Arn",)},
    },
)
