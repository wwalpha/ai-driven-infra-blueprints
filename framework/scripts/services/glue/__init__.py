"""glue service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display(kind: str) -> DisplayExtension:
    return import_module("services.glue.display").EXTENSIONS[kind]


DECLARATION = ServiceDeclaration(
    "glue",
    (
        "Glue.Catalog",
        "Glue.Connection",
        "Glue.Crawler",
        "Glue.Database",
        "Glue.Job",
        "Glue.SecurityConfiguration",
        "Glue.Table",
    ),
    REFERENCES,
    design=design,
    displays={"Glue.Job": partial(load_display, "Glue.Job")},
    aws_adapters={"glue": "aws"},
)
