"""Macie reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "Macie.Session": "AwsAccountId",
    },
)
