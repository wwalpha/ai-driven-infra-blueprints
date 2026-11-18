"""Organizations reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "Organizations.Policy": "Id",
    },
    unproven_document={"Organizations.Policy": ("Organizations.Policy.Content.",)},
)
