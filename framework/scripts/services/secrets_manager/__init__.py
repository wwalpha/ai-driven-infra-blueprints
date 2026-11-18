"""SecretsManager service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.secrets_manager.display").EXTENSION


def load_secret_display() -> DisplayExtension:
    return import_module("services.secrets_manager.display").SECRET_DISPLAY


DECLARATION = ServiceDeclaration(
    "secrets-manager",
    (
        "SecretsManager.ResourcePolicy",
        "SecretsManager.RotationSchedule",
        "SecretsManager.Secret",
    ),
    REFERENCES,
    design=design,
    displays={
        "SecretsManager.RotationSchedule": load_display,
        "SecretsManager.Secret": load_secret_display,
    },
    package="secrets_manager",
    aws_adapters={"secrets-manager": "aws"},
)
