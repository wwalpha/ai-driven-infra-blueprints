"""security-hub service registration."""

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
)
