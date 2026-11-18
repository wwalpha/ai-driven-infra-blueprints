"""route53 service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display(kind: str) -> DisplayExtension:
    return import_module("services.route53.display").EXTENSIONS[kind]


DECLARATION = ServiceDeclaration(
    "route53",
    (
        "Route53.HostedZone",
        "Route53.RecordSet",
    ),
    REFERENCES,
    design=design,
    displays={
        "Route53.RecordSet": partial(load_display, "Route53.RecordSet"),
        "Route53.HostedZone": partial(load_display, "Route53.HostedZone"),
    },
    aws_adapters={"route53": "aws"},
)
