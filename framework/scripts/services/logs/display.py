"""Logs Reference label projection."""

import re

from utils.type_contracts import JsonValue

from ..contracts import DisplayExtension
from ..registry import REGISTRY
from .references import KMS_KEY


def reference_label(
    property_path: str | None,
    producer_type: str,
    attribute: str,
    name: str,
    displayed: JsonValue,
    /,
) -> str:
    if (
        property_path == KMS_KEY
        and producer_type == "KMS.Key"
        and isinstance(displayed, str)
    ):
        form = REGISTRY.arn(producer_type).forms["Arn"]
        if match := re.fullmatch(form[1], displayed):
            return match["id"]
    return name


EXTENSION = DisplayExtension(reference_label=reference_label)
