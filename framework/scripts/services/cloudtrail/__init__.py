"""cloudtrail service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display(kind: str) -> DisplayExtension:
    return import_module("services.cloudtrail.display").EXTENSIONS[kind]


DECLARATION = ServiceDeclaration(
    "cloudtrail",
    ("CloudTrail.Trail",),
    REFERENCES,
    design=design,
    displays={"CloudTrail.Trail": partial(load_display, "CloudTrail.Trail")},
    aws_adapters={"cloudtrail": "aws"},
)
