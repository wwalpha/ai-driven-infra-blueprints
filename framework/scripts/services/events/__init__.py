"""eventbridge service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display(kind: str) -> DisplayExtension:
    return import_module("services.events.display").EXTENSIONS[kind]


DECLARATION = ServiceDeclaration(
    "eventbridge",
    (
        "Events.EventBus",
        "Events.Rule",
    ),
    REFERENCES,
    design=design,
    displays={"Events.Rule": partial(load_display, "Events.Rule")},
    package="events",
    aws_adapters={"eventbridge": "aws"},
)
