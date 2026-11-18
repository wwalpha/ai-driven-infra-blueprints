"""Fixed s3 design definitions; no display-engine dependencies."""

import re

from .references import S3_KMS_MASTER_KEY_ID

POLICY_FORMATS = {
    "S3.BucketPolicy.PolicyDocument": "statement",
}

COLLAPSED_POLICY_DOCUMENTS = set(POLICY_FORMATS)
REVIEW_POLICY_JSON = {"S3.BucketPolicy.PolicyDocument"}

REGION_PROPERTY = "S3.Bucket.Region"

REQUIRED_DISPLAY_LINKS = {
    S3_KMS_MASTER_KEY_ID: "S3 KMSMasterKeyID must link to a KMS.Alias or an explicit Model KMS.Key/Arn"
}


def bucket_name_errors(kind: str, field: str, value: str) -> list[str]:
    if (kind, field) == ("S3.Bucket", "BucketName") and (
        not 3 <= len(value) <= 63
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", value)
    ):
        return ["S3 BucketName must be lowercase and 3–63 characters"]
    return []


PROVIDER_NAME_CHECKS = {"S3.Bucket": bucket_name_errors}
