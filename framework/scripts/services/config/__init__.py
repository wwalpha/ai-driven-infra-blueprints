"""Config service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.config.display").EXTENSION


DECLARATION = ServiceDeclaration(
    "config",
    (
        "Config.ConfigRule",
        "Config.ConfigurationRecorder",
        "Config.DeliveryChannel",
    ),
    REFERENCES,
    design=design,
    displays={"Config.ConfigurationRecorder": load_display},
    aws_adapters={"config": "aws"},
)
