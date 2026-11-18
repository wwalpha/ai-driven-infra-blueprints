"""Offline s3 adapter fixtures."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    ACCOUNT,
    clear_fetch,
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
    import_normalize,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class S3ContractCalls(FakeCalls):
    operation = ""
    kind = ""
    failure_operation = ""
    duplicate = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) != ("s3", "list_buckets", {}):
            raise ValueError("S3 bucket inventory request differs from fixture")
        return self.response(
            api,
            operation,
            {
                "Buckets": [deepcopy(self.payload["bucket"])]
                * (2 if self.duplicate else 1)
            },
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::S3::" + self.kind, "Identifier": "fixture-bucket"},
        ):
            prop = "Bucket" if self.kind == "BucketPolicy" else "BucketName"
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": "fixture-bucket",
                        "Properties": json.dumps({prop: "fixture-bucket"}),
                    }
                },
            )
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) == ("sts", "get_caller_identity", {}):
            return self.response(
                api,
                operation,
                {
                    "Account": ACCOUNT,
                    "Arn": "arn:aws:iam::123456789012:user/fixture",
                    "UserId": "AIDA12345678901234567",
                },
            )
        if (api, operation, inputs) != (
            "s3",
            self.operation,
            {"Bucket": "fixture-bucket", "ExpectedBucketOwner": ACCOUNT},
        ):
            raise ValueError("S3 request differs from fixture")
        if operation == "get_bucket_location":
            location = self.payload["location"]
            return self.response(
                api,
                operation,
                {} if location is None else {"LocationConstraint": location},
            )
        return self.response(api, operation, deepcopy(self.payload))


def s3_base_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = "S3.Bucket"
    payload = {
        "bucket": {
            "Name": "fixture-bucket",
            "BucketArn": "arn:aws:s3:::fixture-bucket",
        },
        "location": "ap-northeast-1",
    }
    ctx, fake = fixture_context(root, "s3", S3ContractCalls, payload)
    fake.operation, fake.kind = "get_bucket_location", "Bucket"
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("s3")
    record = source.cloud_record(
        "s3",
        kind,
        {
            "Identifier": "fixture-bucket",
            "Properties": json.dumps({"BucketName": "fixture-bucket"}),
        },
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "s3", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        {"BucketName": ("Name", "typed", "fixture-bucket")},
        [
            "normal",
            "missing-selector",
            "access-denied",
            "ambiguous",
            "region-default",
            "region-legacy",
            "arn-fallback",
        ],
    )
    expected = [
        ("s3", "list_buckets", {}),
        (
            "s3",
            "get_bucket_location",
            {"Bucket": "fixture-bucket", "ExpectedBucketOwner": ACCOUNT},
        ),
    ]
    if fake.calls != expected:
        raise ValueError("S3 bucket requests differ from fixture")
    for location, expected_region in ((None, "us-east-1"), ("EU", "eu-west-1")):
        fake.payload = {**payload, "location": location}
        result = resource.module.fetch(ctx, resource, "base")
        if result.get("BucketRegion") != expected_region:
            raise ValueError("S3 location normalization differs from fixture")
    fake.payload = {"bucket": {"Name": "fixture-bucket"}, "location": "ap-northeast-1"}
    result = resource.module.fetch(ctx, resource, "base")
    if result.get("BucketArn") != "arn:aws:s3:::fixture-bucket":
        raise ValueError("S3 ARN fallback differs from verified account partition")
    for operation in ("get_bucket_location", "get_caller_identity"):
        fake.error = cli.comparator().AcquisitionError(
            "s3." + operation, "AccessDenied"
        )
        fake.failure_operation = operation
        try:
            resource.module.fetch(ctx, resource, "base")
        except cli.comparator().AcquisitionError as error:
            if error.code != "AccessDenied":
                raise ValueError("S3 dependent API failure was changed") from error
        else:
            raise ValueError("S3 dependent API failure was swallowed")
    fake.error, fake.failure_operation, fake.payload = None, "", payload
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, "base")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Duplicate S3 bucket names were accepted")
    fake.duplicate = False
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "s3.list_buckets", "BucketName"
    )
    return items


def s3_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    getter = mapping.properties[properties[0]].field.getter
    configs = {
        "replication": (
            "get_bucket_replication",
            {
                "ReplicationConfiguration": {
                    "Role": "arn:aws:iam::123456789012:role/replication",
                    "Rules": [
                        {
                            "ID": "rule",
                            "Status": "Enabled",
                            "Priority": 1,
                            "DeleteMarkerReplication": {"Status": "Disabled"},
                            "Destination": {
                                "Account": ACCOUNT,
                                "Bucket": "arn:aws:s3:::destination",
                                "StorageClass": "STANDARD",
                                "EncryptionConfiguration": {
                                    "ReplicaKmsKeyID": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012"
                                },
                                "Metrics": {
                                    "Status": "Enabled",
                                    "EventThreshold": {"Minutes": 15},
                                },
                                "ReplicationTime": {
                                    "Status": "Enabled",
                                    "Time": {"Minutes": 15},
                                },
                            },
                            "Filter": {
                                "Prefix": "logs/",
                                "Tag": {"Key": "team", "Value": "ops"},
                                "And": {
                                    "Prefix": "logs/",
                                    "Tags": [{"Key": "env", "Value": "dev"}],
                                },
                            },
                            "SourceSelectionCriteria": {
                                "ReplicaModifications": {"Status": "Enabled"},
                                "SseKmsEncryptedObjects": {"Status": "Enabled"},
                            },
                        }
                    ],
                }
            },
            {
                "ReplicationConfiguration." + name: (
                    "ReplicationConfiguration." + name,
                    "typed",
                    value,
                )
                for name, value in {
                    "Role": "arn:aws:iam::123456789012:role/replication",
                    "Rules[].Id": ["rule"],
                    "Rules[].Status": ["Enabled"],
                    "Rules[].Priority": [1],
                    "Rules[].DeleteMarkerReplication.Status": ["Disabled"],
                    "Rules[].Destination.Account": [ACCOUNT],
                    "Rules[].Destination.Bucket": ["arn:aws:s3:::destination"],
                    "Rules[].Destination.StorageClass": ["STANDARD"],
                    "Rules[].Destination.EncryptionConfiguration.ReplicaKmsKeyID": [
                        "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012"
                    ],
                    "Rules[].Destination.Metrics.EventThreshold.Minutes": [15],
                    "Rules[].Destination.Metrics.Status": ["Enabled"],
                    "Rules[].Destination.ReplicationTime.Status": ["Enabled"],
                    "Rules[].Destination.ReplicationTime.Time.Minutes": [15],
                    "Rules[].Filter.And.Prefix": ["logs/"],
                    "Rules[].Filter.And.TagFilters[].Key": [["env"]],
                    "Rules[].Filter.And.TagFilters[].Value": [["dev"]],
                    "Rules[].Filter.Prefix": ["logs/"],
                    "Rules[].Filter.TagFilter.Key": ["team"],
                    "Rules[].Filter.TagFilter.Value": ["ops"],
                    "Rules[].SourceSelectionCriteria.ReplicaModifications.Status": [
                        "Enabled"
                    ],
                    "Rules[].SourceSelectionCriteria.SseKmsEncryptedObjects.Status": [
                        "Enabled"
                    ],
                }.items()
            },
            "ReplicationConfigurationNotFoundError",
        ),
        "encryption": (
            "get_bucket_encryption",
            {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "aws:kms",
                                "KMSMasterKeyID": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                            },
                            "BucketKeyEnabled": True,
                        }
                    ]
                }
            },
            {
                "BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled": (
                    "ServerSideEncryptionConfiguration[].BucketKeyEnabled",
                    "typed",
                    [True],
                ),
                "BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID": (
                    "ServerSideEncryptionConfiguration[].ApplyServerSideEncryptionByDefault.KMSMasterKeyID",
                    "kms",
                    [
                        "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012"
                    ],
                ),
                "BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm": (
                    "ServerSideEncryptionConfiguration[].ApplyServerSideEncryptionByDefault.SSEAlgorithm",
                    "typed",
                    ["aws:kms"],
                ),
            },
            "ServerSideEncryptionConfigurationNotFoundError",
        ),
        "lifecycle": (
            "get_bucket_lifecycle_configuration",
            {
                "Rules": [
                    {
                        "ID": "expire",
                        "Status": "Enabled",
                        "Prefix": "logs/",
                        "Expiration": {"Days": 30},
                        "NoncurrentVersionExpiration": {"NoncurrentDays": 60},
                    }
                ]
            },
            {
                "LifecycleConfiguration.Rules[].ExpirationInDays": (
                    "Rules[].Expiration.Days",
                    "typed",
                    [30],
                ),
                "LifecycleConfiguration.Rules[].Id": (
                    "Rules[].ID",
                    "typed",
                    ["expire"],
                ),
                "LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NoncurrentDays": (
                    "Rules[].NoncurrentVersionExpiration.NoncurrentDays",
                    "typed",
                    [60],
                ),
                "LifecycleConfiguration.Rules[].Prefix": (
                    "Rules[].Prefix",
                    "typed",
                    ["logs/"],
                ),
                "LifecycleConfiguration.Rules[].Status": (
                    "Rules[].Status",
                    "typed",
                    ["Enabled"],
                ),
            },
            "NoSuchLifecycleConfiguration",
        ),
        "lock": (
            "get_object_lock_configuration",
            {
                "ObjectLockConfiguration": {
                    "ObjectLockEnabled": "Enabled",
                    "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 30}},
                }
            },
            {
                "ObjectLockEnabled": ("LockBoolean", "boolean", True),
                "ObjectLockConfiguration.ObjectLockEnabled": (
                    "ObjectLockConfiguration.ObjectLockEnabled",
                    "typed",
                    "Enabled",
                ),
                "ObjectLockConfiguration.Rule.DefaultRetention.Days": (
                    "ObjectLockConfiguration.Rule.DefaultRetention.Days",
                    "typed",
                    30,
                ),
                "ObjectLockConfiguration.Rule.DefaultRetention.Mode": (
                    "ObjectLockConfiguration.Rule.DefaultRetention.Mode",
                    "typed",
                    "GOVERNANCE",
                ),
            },
            "ObjectLockConfigurationNotFoundError",
        ),
        "versioning": (
            "get_bucket_versioning",
            {"Status": "Enabled"},
            {"VersioningConfiguration.Status": ("Status", "typed", "Enabled")},
            None,
        ),
        "public": (
            "get_public_access_block",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                }
            },
            {
                "PublicAccessBlockConfiguration." + name: (
                    "PublicAccessBlockConfiguration." + name,
                    "typed",
                    True,
                )
                for name in (
                    "BlockPublicAcls",
                    "BlockPublicPolicy",
                    "IgnorePublicAcls",
                    "RestrictPublicBuckets",
                )
            },
            "NoSuchPublicAccessBlockConfiguration",
        ),
        "ownership": (
            "get_bucket_ownership_controls",
            {
                "OwnershipControls": {
                    "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
                }
            },
            {
                "OwnershipControls.Rules[].ObjectOwnership": (
                    "OwnershipControls.Rules[].ObjectOwnership",
                    "typed",
                    ["BucketOwnerEnforced"],
                )
            },
            "OwnershipControlsNotFoundError",
        ),
        "policy": (
            "get_bucket_policy",
            {"Policy": json.dumps({"Version": "2012-10-17", "Statement": []})},
            {
                "PolicyDocument": (
                    "Policy",
                    "policy",
                    {"Version": "2012-10-17", "Statement": []},
                )
            },
            "NoSuchBucketPolicy",
        ),
    }
    operation, payload, cases, absent_error = configs[getter]
    ctx, fake = fixture_context(root, "s3", S3ContractCalls, payload)
    fake.operation, fake.kind = operation, kind.split(".")[1]
    prop = "Bucket" if fake.kind == "BucketPolicy" else "BucketName"
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("s3")
    cloud = {prop: "fixture-bucket"}
    record = source.cloud_record(
        "s3",
        kind,
        {"Identifier": "fixture-bucket", "Properties": json.dumps(cloud)},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "s3", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied"],
    )
    if fake.calls != [
        ("s3", operation, {"Bucket": "fixture-bucket", "ExpectedBucketOwner": ACCOUNT})
    ]:
        raise ValueError("S3 request differs from fixture")
    if getter == "lock":
        fake.payload = {"ObjectLockConfiguration": {}}
        clear_fetch(ctx)
        key = "S3.Bucket.ObjectLockEnabled"
        _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
        import_normalize(ctx, kind, key, raw, "boolean")
        if raw is not False:
            raise ValueError("Unenabled object lock was not false")
        if key in items and items[key]["status"] == "verified":
            items[key]["branches"].append("object-lock-not-enabled")
        fake.payload = payload
    if absent_error:
        fake.error = cli.comparator().AcquisitionError("s3." + operation, absent_error)
        clear_fetch(ctx)
        _, raw = mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
        if raw not in (cli.comparator().MISSING, []):
            raise ValueError("Absent S3 configuration was not preserved")
        fake.error = None
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("optional-configuration-absent")
    else:
        missing_values(ctx, fake, resource, mapping, items, payload)
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "s3." + operation, prop
    )
    return items


CONTRACTS = (
    (
        ("S3.Bucket", "versioning"),
        s3_fixture,
        "s3.get_bucket_versioning",
        ("BucketName",),
    ),
    (
        ("S3.Bucket", "base"),
        s3_base_fixture,
        "s3.list_buckets",
        ("BucketName",),
        ("s3.get_bucket_location", "sts.get_caller_identity"),
    ),
    (
        ("S3.Bucket", "encryption"),
        s3_fixture,
        "s3.get_bucket_encryption",
        ("BucketName",),
    ),
    (
        ("S3.Bucket", "lifecycle"),
        s3_fixture,
        "s3.get_bucket_lifecycle_configuration",
        ("BucketName",),
    ),
    (
        ("S3.Bucket", "replication"),
        s3_fixture,
        "s3.get_bucket_replication",
        ("BucketName",),
    ),
    (
        ("S3.Bucket", "lock"),
        s3_fixture,
        "s3.get_object_lock_configuration",
        ("BucketName",),
    ),
    (
        ("S3.Bucket", "public"),
        s3_fixture,
        "s3.get_public_access_block",
        ("BucketName",),
    ),
    (
        ("S3.Bucket", "ownership"),
        s3_fixture,
        "s3.get_bucket_ownership_controls",
        ("BucketName",),
    ),
    (("S3.BucketPolicy", "policy"), s3_fixture, "s3.get_bucket_policy", ("Bucket",)),
)
