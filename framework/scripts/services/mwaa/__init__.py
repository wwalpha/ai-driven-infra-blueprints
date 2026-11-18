"""MWAA service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "mwaa",
    ("MWAA.Environment",),
    REFERENCES,
    aws_adapters={"mwaa": "aws"},
)
