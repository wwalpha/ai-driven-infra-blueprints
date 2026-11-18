"""SageMaker service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "sagemaker",
    (
        "SageMaker.Domain",
        "SageMaker.Space",
        "SageMaker.UserProfile",
    ),
    REFERENCES,
)
