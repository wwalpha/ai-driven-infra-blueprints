"""Logs service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..import_contracts import ImportProfile
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.logs.display").EXTENSION


DECLARATION = ServiceDeclaration(
    "logs",
    (
        "Logs.LogGroup",
        "Logs.MetricFilter",
        "Logs.ResourcePolicy",
        "Logs.SubscriptionFilter",
    ),
    REFERENCES,
    design=design,
    displays={"Logs.LogGroup": load_display},
    aws_adapters={"cloudwatch-logs": "aws"},
    import_profiles={
        "Logs.LogGroup": ImportProfile(
            adapter=("logs", "describe_log_groups", "logGroups")
        ),
    },
)
