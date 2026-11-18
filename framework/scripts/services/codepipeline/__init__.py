"""codepipeline service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display(kind: str) -> DisplayExtension:
    return import_module("services.codepipeline.display").EXTENSIONS[kind]


DECLARATION = ServiceDeclaration(
    "codepipeline",
    ("CodePipeline.Pipeline",),
    REFERENCES,
    design=design,
    displays={"CodePipeline.Pipeline": partial(load_display, "CodePipeline.Pipeline")},
    aws_adapters={"codepipeline": "aws"},
)
