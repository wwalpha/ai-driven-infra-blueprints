"""Athena reference label projection."""

import re

from ..contracts import DisplayExtension
from ..registry import REGISTRY


def reference_label(property_path, producer_type, attribute, name, displayed, /):
    if (
        property_path
        == "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey"
        and producer_type == "KMS.Key"
        and isinstance(displayed, str)
    ):
        form = REGISTRY.arn(producer_type).forms["Arn"]
        if match := re.fullmatch(form[1], displayed):
            return match["id"]
    return name


EXTENSION = DisplayExtension(reference_label=reference_label)
