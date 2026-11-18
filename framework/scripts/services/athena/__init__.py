"""Athena service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "athena",
    ("Athena.WorkGroup",),
    REFERENCES,
    aws_adapters={"athena": "aws"},
)
