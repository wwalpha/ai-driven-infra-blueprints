"""DataZone reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "DataZone.Domain": "Id",
        "DataZone.Connection": "Ref",
        "DataZone.DataSource": "Ref",
        "DataZone.Environment": "Ref",
        "DataZone.EnvironmentBlueprintConfiguration": "Ref",
        "DataZone.EnvironmentProfile": "Ref",
        "DataZone.Owner": "Ref",
        "DataZone.Project": "Ref",
        "DataZone.ProjectMembership": "Ref",
        "DataZone.ProjectProfile": "Ref",
    },
    import_properties={
        "DataZone.Connection.Props.IamProperties.RoleArn": ("IAM.Role", "Arn"),
    },
    unproven_document={
        "DataZone.Connection": ("DataZone.Connection.Props.S3Properties.S3Uri",)
    },
)
