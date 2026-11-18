"""cloudfront reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "CloudFront.CachePolicy": "Id",
        "CloudFront.Distribution": "Id",
        "CloudFront.OriginRequestPolicy": "Id",
        "CloudFront.ResponseHeadersPolicy": "Id",
    },
    arn_attributes={
        "CloudFront.Function": "FunctionARN",
    },
    import_properties={
        "CloudFront.Distribution.DistributionConfig.Logging.Bucket": (
            "S3.Bucket",
            "DomainName",
        ),
    },
    arn_shapes={
        "CloudFront.Function": (
            "Name",
            "arn:{partition}:cloudfront::{account}:function/{id}",
            {"id": r"[A-Za-z0-9_-]{1,64}"},
        ),
        "CloudFront.CachePolicy": (
            "Id",
            "arn:{partition}:cloudfront::{account}:cache-policy/{id}",
            {"id": "[A-Za-z0-9-]+"},
        ),
        "CloudFront.Distribution": (
            "Id",
            "arn:{partition}:cloudfront::{account}:distribution/{id}",
            {"id": "[A-Za-z0-9-]+"},
        ),
        "CloudFront.OriginAccessControl": (
            "Id",
            "arn:{partition}:cloudfront::{account}:origin-access-control/{id}",
            {"id": "[A-Za-z0-9-]+"},
        ),
        "CloudFront.OriginRequestPolicy": (
            "Id",
            "arn:{partition}:cloudfront::{account}:origin-request-policy/{id}",
            {"id": "[A-Za-z0-9-]+"},
        ),
        "CloudFront.ResponseHeadersPolicy": (
            "Id",
            "arn:{partition}:cloudfront::{account}:response-headers-policy/{id}",
            {"id": "[A-Za-z0-9-]+"},
        ),
    },
    model_attributes={
        "CloudFront.Function": {"FunctionMetadata.FunctionARN": "FunctionARN"}
    },
)
