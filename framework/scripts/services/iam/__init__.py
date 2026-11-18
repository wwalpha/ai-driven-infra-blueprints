"""IAM service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "iam",
    (
        "IAM.InstanceProfile",
        "IAM.ManagedPolicy",
        "IAM.Role",
        "IAM.User",
    ),
    REFERENCES,
    design=design,
    aws_adapters={"iam": "aws"},
)
