"""S3 service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.s3.display").EXTENSION


DECLARATION = ServiceDeclaration(
    "s3",
    (
        "S3.Bucket",
        "S3.BucketPolicy",
    ),
    REFERENCES,
    design=design,
    displays={"S3.Bucket": load_display},
    aws_adapters={"s3": "aws"},
)
