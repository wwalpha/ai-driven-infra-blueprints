"""GuardDuty service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.guardduty.display").EXTENSION


DECLARATION = ServiceDeclaration(
    "guardduty",
    (
        "GuardDuty.Detector",
        "GuardDuty.MalwareProtectionPlan",
    ),
    REFERENCES,
    design=design,
    displays={"GuardDuty.Detector": load_display},
    aws_adapters={"guardduty": "aws"},
)
