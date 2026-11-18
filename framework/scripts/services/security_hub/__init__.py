"""security-hub service registration."""

from ..import_contracts import ImportProfile
from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "security-hub",
    (
        "SecurityHub.FindingAggregator",
        "SecurityHub.Hub",
    ),
    REFERENCES,
    package="security_hub",
    aws_adapters={"security-hub": "aws"},
    import_profiles={
        "SecurityHub.Hub": ImportProfile(adapter=("securityhub", "describe_hub", None)),
    },
)
