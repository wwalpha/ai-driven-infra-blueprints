"""DynamoDB service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "dynamodb",
    (
        "DynamoDB.GlobalTable",
        "DynamoDB.Table",
    ),
    REFERENCES,
    design=design,
)
