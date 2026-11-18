"""CloudWatch service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "cloudwatch",
    (
        "CloudWatch.Alarm",
        "CloudWatch.Dashboard",
    ),
    REFERENCES,
)
