"""Athena service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.athena.display").EXTENSION


DECLARATION = ServiceDeclaration(
    "athena",
    ("Athena.WorkGroup",),
    REFERENCES,
    displays={"Athena.WorkGroup": load_display},
    aws_adapters={"athena": "aws"},
)
