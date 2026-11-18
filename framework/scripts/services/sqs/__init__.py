"""SQS service registration."""

from ..import_contracts import ImportProfile, ScopedInventory, inventory_handler
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "sqs",
    (
        "SQS.Queue",
        "SQS.QueuePolicy",
    ),
    REFERENCES,
    design=design,
    aws_adapters={"sqs": "aws"},
    import_profiles={
        "SQS.QueuePolicy": ImportProfile(
            unobservable={
                "SQS.QueuePolicy.Id": (
                    "sqs",
                    "get_queue_attributes",
                    "Id",
                    "PROVIDER_OUTPUT_NOT_OBSERVABLE",
                )
            },
            scoped=ScopedInventory(
                "sqs",
                ("get_queue_attributes",),
                ("get_queue_attributes", "Attributes"),
                ("Queues[]",),
                inventory_handler("services.sqs.inventory", "queue_policies"),
                selectors=("Queues[]",),
                parents=("SQS.Queue",),
                group_review="Original queue grouping requires explicit Human structure selection",
                grouped_identity="SQS.QueuePolicy.Queues[]",
            ),
        ),
    },
)
