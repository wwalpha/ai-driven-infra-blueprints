"""s3: selected properties -> read-only SDK responses; inputs in fetch()."""

from copy import deepcopy

from botocore.validate import ParamValidator
from model.adapters.aws import MISSING, AcquisitionError, Field, one
from utils.aws_sdk import Sdk

APIS = {
    ("s3", "get_bucket_policy"),
    ("s3", "get_bucket_replication"),
    ("s3", "get_bucket_lifecycle_configuration"),
    ("s3", "get_bucket_encryption"),
    ("s3", "get_public_access_block"),
    ("s3", "list_buckets"),
    ("s3", "get_bucket_versioning"),
    ("s3", "get_object_lock_configuration"),
    ("s3", "get_bucket_ownership_controls"),
    ("s3", "get_bucket_location"),
}

SDK = Sdk()

MODEL_FIELDS = {"S3.Bucket.Region": Field("base", "BucketRegion", default=MISSING)}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    name = (
        r.value("Bucket", "name")
        if r.kind == "S3.BucketPolicy"
        else r.value("BucketName")
    )
    if getter == "base":
        bucket = one(
            [
                v
                for v in ctx.pages("s3", "list_buckets").get("Buckets", [])
                if v["Name"] == name
            ],
            "s3.list_buckets",
        )
        location = ctx.call(
            "s3",
            "get_bucket_location",
            Bucket=name,
            ExpectedBucketOwner=ctx.target.get(
                "awsExecutionAccountId", ctx.target["awsAccountId"]
            ),
        ).get("LocationConstraint")
        if not bucket.get("BucketArn"):
            # General-purpose bucket ARN is the documented identity format, from
            # SDK-confirmed bucket name and verified STS partition; no guessed IDs.
            partition = ctx.call("sts", "get_caller_identity")["Arn"].split(":")[1]
            bucket = dict(
                bucket, BucketArn="arn:" + partition + ":s3:::" + bucket["Name"]
            )
        bucket = dict(
            bucket,
            BucketRegion="us-east-1"
            if location is None
            else "eu-west-1"
            if location == "EU"
            else location,
        )
        return bucket
    operations = {
        "encryption": "get_bucket_encryption",
        "lifecycle": "get_bucket_lifecycle_configuration",
        "replication": "get_bucket_replication",
        "ownership": "get_bucket_ownership_controls",
        "public": "get_public_access_block",
        "versioning": "get_bucket_versioning",
        "lock": "get_object_lock_configuration",
        "policy": "get_bucket_policy",
    }
    try:
        result = ctx.call(
            "s3",
            operations[getter],
            Bucket=name,
            ExpectedBucketOwner=ctx.target.get(
                "awsExecutionAccountId", ctx.target["awsAccountId"]
            ),
        )
    except AcquisitionError as error:
        absent = {
            "ServerSideEncryptionConfigurationNotFoundError",
            "NoSuchLifecycleConfiguration",
            "OwnershipControlsNotFoundError",
            "NoSuchOwnershipControls",
            "NoSuchPublicAccessBlockConfiguration",
            "ObjectLockConfigurationNotFoundError",
            "NoSuchBucketPolicy",
        }
        if error.code in absent or (
            getter == "replication"
            and error.code == "ReplicationConfigurationNotFoundError"
        ):
            return {}
        raise
    if getter == "replication":
        return normalize_replication(result)
    if getter == "encryption":
        return {
            "ServerSideEncryptionConfiguration": result[
                "ServerSideEncryptionConfiguration"
            ]["Rules"]
        }
    if getter == "lock" and "ObjectLockConfiguration" in result:
        result = dict(result)
        result["ObjectLockConfiguration"] = dict(result["ObjectLockConfiguration"])
        result["ObjectLockConfiguration"]["ObjectLockEnabled"] = result[
            "ObjectLockConfiguration"
        ].get("ObjectLockEnabled")
        result["LockBoolean"] = (
            result["ObjectLockConfiguration"].get("ObjectLockEnabled") == "Enabled"
        )
    return result


def normalize_replication(result):
    api = "s3.get_bucket_replication"
    if not isinstance(result, dict) or not isinstance(
        result.get("ReplicationConfiguration"), dict
    ):
        raise AcquisitionError(api, "InvalidResponse")
    shape = SDK.service_model("s3").operation_model("GetBucketReplication").output_shape
    payload = {key: value for key, value in result.items() if key != "ResponseMetadata"}
    if ParamValidator().validate(payload, shape).has_errors():
        raise AcquisitionError(api, "InvalidResponse")
    result = deepcopy(result)
    config = result["ReplicationConfiguration"]
    for rule in config["Rules"]:
        if "ID" in rule:
            rule["Id"] = rule.pop("ID")
        if "Filter" in rule:
            filt = rule["Filter"]
            if "Tag" in filt:
                filt["TagFilter"] = filt.pop("Tag")
            if "And" in filt:
                conjunction = filt["And"]
                if "Tags" in conjunction:
                    conjunction["TagFilters"] = conjunction.pop("Tags")
    return result


SDK_OPERATIONS = {"S3.Bucket": "get_bucket_lifecycle_configuration"}


def fetch_sdk(ctx, r, operation):
    # Preserve the adapter's optional-configuration absence classification.
    return ctx.fetch(r, "lifecycle")
