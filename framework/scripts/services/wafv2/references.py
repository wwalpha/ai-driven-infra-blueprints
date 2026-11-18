"""WAFv2 reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "WAFv2.LoggingConfiguration": "ResourceArn",
        "WAFv2.IPSet": "Ref",
        "WAFv2.RuleGroup": "Ref",
        "WAFv2.WebACL": "Ref",
        "WAFv2.WebACLAssociation": "Ref",
    },
    arn_attributes={
        "WAFv2.LoggingConfiguration": "ResourceArn",
    },
)
