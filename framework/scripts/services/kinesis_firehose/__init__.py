"""KinesisFirehose service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "data-firehose",
    ("KinesisFirehose.DeliveryStream",),
    REFERENCES,
    design=design,
    package="kinesis_firehose",
    aws_adapters={"data-firehose": "aws"},
)
