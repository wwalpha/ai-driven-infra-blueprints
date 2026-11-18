"""SSO service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "sso",
    (
        "SSO.Assignment",
        "SSO.PermissionSet",
    ),
    REFERENCES,
    design=design,
)
