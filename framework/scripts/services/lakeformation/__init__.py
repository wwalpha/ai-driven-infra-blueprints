"""LakeFormation service registration."""

from ..import_contracts import ImportProfile, ScopedInventory, inventory_handler
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "lake-formation",
    (
        "LakeFormation.DataLakeSettings",
        "LakeFormation.PrincipalPermissions",
        "LakeFormation.Resource",
    ),
    REFERENCES,
    design=design,
    package="lakeformation",
    aws_adapters={"lake-formation": "aws"},
    import_profiles={
        "LakeFormation.Resource": ImportProfile(
            unobservable={
                "LakeFormation.Resource.UseServiceLinkedRole": (
                    "lakeformation",
                    "describe_resource",
                    "ResourceInfo.UseServiceLinkedRole",
                    "REQUEST_INPUT_NOT_OBSERVABLE",
                )
            },
            scoped=ScopedInventory(
                "lakeformation",
                ("list_resources", "describe_resource"),
                ("describe_resource", "ResourceInfo"),
                ("ResourceArn",),
                inventory_handler(
                    "services.lakeformation.inventory", "lakeformation_resources"
                ),
            ),
        ),
    },
)
