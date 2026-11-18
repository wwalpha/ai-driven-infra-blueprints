"""codebuild service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display(kind: str) -> DisplayExtension:
    return import_module("services.codebuild.display").EXTENSIONS[kind]


DECLARATION = ServiceDeclaration(
    "codebuild",
    ("CodeBuild.Project",),
    REFERENCES,
    design=design,
    displays={"CodeBuild.Project": partial(load_display, "CodeBuild.Project")},
    aws_adapters={"codebuild": "aws"},
)
