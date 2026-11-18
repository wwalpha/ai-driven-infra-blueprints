"""LakeFormation reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "LakeFormation.PrincipalPermissions": "Ref",
    },
    import_properties={
        "LakeFormation.PrincipalPermissions.Resource.Database.Name": (
            "Glue.Database",
            "Name",
        ),
        "LakeFormation.PrincipalPermissions.Resource.Table.DatabaseName": (
            "Glue.Database",
            "Name",
        ),
        "LakeFormation.PrincipalPermissions.Resource.TableWithColumns.DatabaseName": (
            "Glue.Database",
            "Name",
        ),
        "LakeFormation.Resource.ResourceArn": (("Glue.Connection", "S3.Bucket"), "Arn"),
        "LakeFormation.Resource.RoleArn": ("IAM.Role", "Arn"),
    },
)
