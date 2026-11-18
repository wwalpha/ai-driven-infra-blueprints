"""LakeFormation service registration."""

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
)
