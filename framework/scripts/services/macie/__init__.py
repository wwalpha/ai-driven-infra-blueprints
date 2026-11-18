"""Macie service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.macie.display").EXTENSION


DECLARATION = ServiceDeclaration(
    "macie",
    (
        "Macie.ClassificationJob",
        "Macie.Session",
    ),
    REFERENCES,
    design=design,
    displays={"Macie.ClassificationJob": load_display},
    without_comparison=("Macie.ClassificationJob",),
    aws_adapters={"macie": "aws"},
)
