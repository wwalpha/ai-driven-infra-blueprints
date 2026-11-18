"""WAFv2 service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "wafv2",
    (
        "WAFv2.IPSet",
        "WAFv2.LoggingConfiguration",
        "WAFv2.RuleGroup",
        "WAFv2.WebACL",
        "WAFv2.WebACLAssociation",
    ),
    REFERENCES,
)
