"""CertificateManager reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "CertificateManager.Certificate": "CertificateArn",
    },
    arn_attributes={
        "CertificateManager.Certificate": "CertificateArn",
    },
)
