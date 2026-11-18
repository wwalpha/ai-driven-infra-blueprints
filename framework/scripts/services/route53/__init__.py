"""route53 service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..import_contracts import ImportProfile, ScopedInventory, inventory_handler
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
    import_profiles={
        "Route53.RecordSet": ImportProfile(
            scoped=ScopedInventory(
                "route53",
                ("list_resource_record_sets",),
                ("list_resource_record_sets", "ResourceRecordSets[]"),
                ("HostedZoneId", "Name", "Type", "SetIdentifier"),
                inventory_handler("services.route53.inventory", "route53_records"),
                selectors=("HostedZoneId",),
                parents=("Route53.HostedZone",),
                filter_error="RecordSet filters are not supported",
            ),
            normalize_identity=inventory_handler(
                "services.route53.inventory", "identity_value"
            ),
        ),
    },
)
