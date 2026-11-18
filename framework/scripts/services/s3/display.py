"""S3 Reference labels and property order."""

from utils.type_contracts import JsonValue

from ..contracts import DisplayExtension
from .design import REGION_PROPERTY
from .references import S3_KMS_MASTER_KEY_ID


def reference_label(
    property_path: str | None,
    producer_type: str,
    attribute: str,
    name: str,
    displayed: JsonValue,
    /,
) -> str:
    if (
        property_path == S3_KMS_MASTER_KEY_ID
        and producer_type == "KMS.Alias"
        and attribute == "Arn"
        and isinstance(displayed, str)
    ):
        return displayed.rsplit(":", 1)[-1]
    return name


def display_order(resource_type: str, order: dict[str, int | float]) -> None:
    order[REGION_PROPERTY] = order["S3.Bucket.BucketName"] + 0.5


EXTENSION = DisplayExtension(
    reference_label=reference_label, adjust_order=display_order
)
