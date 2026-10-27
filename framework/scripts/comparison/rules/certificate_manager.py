"""Static CertificateManager comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "CertificateManager.Certificate": properties(
        objects="""
            DomainValidationOptions[]
            Tags[]
        """,
        ordered="""
            DomainValidationOptions
            SubjectAlternativeNames
        """,
        scalars="""
            CertificateAuthorityArn
            CertificateExport
            CertificateTransparencyLoggingPreference
            DomainName
            DomainValidationOptions[].DomainName
            DomainValidationOptions[].HostedZoneId
            DomainValidationOptions[].ValidationDomain
            KeyAlgorithm
            Tags[].Key
            Tags[].Value
            ValidationMethod
        """,
        tags="""
            Tags
        """,
    ),
}
