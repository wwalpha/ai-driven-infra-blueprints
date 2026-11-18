"""SQS service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "sqs",
    (
        "SQS.Queue",
        "SQS.QueuePolicy",
    ),
    REFERENCES,
    design=design,
    aws_adapters={"sqs": "aws"},
)
