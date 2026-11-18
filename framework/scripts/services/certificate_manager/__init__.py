"""CertificateManager service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "certificate-manager",
    ("CertificateManager.Certificate",),
    REFERENCES,
    package="certificate_manager",
)
