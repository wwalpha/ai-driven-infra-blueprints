"""cloudfront service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "cloudfront",
    (
        "CloudFront.CachePolicy",
        "CloudFront.Distribution",
        "CloudFront.Function",
        "CloudFront.OriginAccessControl",
        "CloudFront.OriginRequestPolicy",
        "CloudFront.ResponseHeadersPolicy",
    ),
    REFERENCES,
)
