"""SSM reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "SSM.MaintenanceWindow": "WindowId",
        "SSM.MaintenanceWindowTarget": "WindowTargetId",
        "SSM.MaintenanceWindowTask": "WindowTaskId",
        "SSM.PatchBaseline": "Id",
    },
    model_attributes={"SSM.Parameter": {"Name": "Name"}},
    import_properties={
        "SSM.MaintenanceWindowTask.ServiceRoleArn": ("IAM.Role", "Arn"),
    },
    arn_shapes={
        "SSM.Association": (
            "AssociationId",
            "arn:{partition}:ssm:{region}:{account}:association/{id}",
            {"id": r"[a-f0-9-]+"},
        ),
        "SSM.MaintenanceWindow": (
            "WindowId",
            "arn:{partition}:ssm:{region}:{account}:maintenancewindow/{id}",
            {"id": r"mw-[a-f0-9]+"},
        ),
        "SSM.MaintenanceWindowTarget": (
            "WindowTargetId",
            "arn:{partition}:ssm:{region}:{account}:windowtarget/{id}",
            {"id": r"[a-f0-9-]+"},
        ),
        "SSM.MaintenanceWindowTask": (
            "WindowTaskId",
            "arn:{partition}:ssm:{region}:{account}:windowtask/{id}",
            {"id": r"[a-f0-9-]+"},
        ),
        "SSM.PatchBaseline": (
            "Id",
            "arn:{partition}:ssm:{region}:{account}:patchbaseline/{id}",
            {"id": r"pb-[a-f0-9]+"},
        ),
    },
)
