"""SSO reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "SSO.Assignment": "Ref",
        "SSO.PermissionSet": "Ref",
    },
    arn_attributes={
        "SSO.PermissionSet": "PermissionSetArn",
    },
)
