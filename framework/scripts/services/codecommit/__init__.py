"""CodeCommit service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "codecommit",
    ("CodeCommit.Repository",),
    REFERENCES,
    design=design,
    aws_adapters={"codecommit": "aws"},
)
