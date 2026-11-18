"""FMS service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "fms",
    ("FMS.Policy",),
    REFERENCES,
)
