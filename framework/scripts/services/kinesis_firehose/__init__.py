"""KinesisFirehose service registration."""

from ..import_contracts import Detail, ImportProfile
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "data-firehose",
    ("KinesisFirehose.DeliveryStream",),
    REFERENCES,
    design=design,
    package="kinesis_firehose",
    aws_adapters={"data-firehose": "aws"},
    import_profiles={
        "KinesisFirehose.DeliveryStream": ImportProfile(
            adapter=("firehose", "list_delivery_streams", "DeliveryStreamNames"),
            detail=Detail(
                "describe_delivery_stream",
                "DeliveryStreamName",
                "DeliveryStreamDescription",
                list_returns_selector=True,
            ),
        ),
    },
)
