"""ECR service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "ecr",
    ("ECR.Repository",),
    REFERENCES,
    design=design,
)
