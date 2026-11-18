"""DataZone service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "datazone",
    (
        "DataZone.Connection",
        "DataZone.DataSource",
        "DataZone.Domain",
        "DataZone.Environment",
        "DataZone.EnvironmentBlueprintConfiguration",
        "DataZone.EnvironmentProfile",
        "DataZone.Owner",
        "DataZone.Project",
        "DataZone.ProjectMembership",
        "DataZone.ProjectProfile",
    ),
    REFERENCES,
    aws_adapters={"datazone": "aws"},
)
