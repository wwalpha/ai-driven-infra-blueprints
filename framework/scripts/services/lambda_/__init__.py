"""Lambda service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.lambda_.display").EXTENSION


def load_function_display() -> DisplayExtension:
    return import_module("services.lambda_.display").FUNCTION_DISPLAY


DECLARATION = ServiceDeclaration(
    "lambda",
    (
        "Lambda.EventInvokeConfig",
        "Lambda.EventSourceMapping",
        "Lambda.Function",
        "Lambda.Permission",
    ),
    REFERENCES,
    design=design,
    displays={
        "Lambda.Permission": load_display,
        "Lambda.Function": load_function_display,
    },
    package="lambda_",
    aws_adapters={"lambda": "aws"},
)
