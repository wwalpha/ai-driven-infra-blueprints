"""Offline data-firehose adapter fixtures."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    clear_fetch,
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls


class FirehoseCalls(DirectCalls):
    mode = "normal"

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("firehose", "list_delivery_streams", {}):
            raise ValueError("Firehose inventory scope differs")
        return self.response(
            api,
            operation,
            {"DeliveryStreamNames": ["fixture"], "HasMoreDeliveryStreams": False},
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation) != (
            "firehose",
            "describe_delivery_stream",
        ) or inputs not in (
            {"DeliveryStreamName": "fixture"},
            {
                "DeliveryStreamName": "fixture",
                "ExclusiveStartDestinationId": "destination-1",
            },
        ):
            raise ValueError("Firehose name or continuation differs")
        result = deepcopy(self.payload)
        if self.mode == "legacy":
            dest = result["Destinations"][0]
            body = dest.pop("ExtendedS3DestinationDescription")
            body.pop("ErrorOutputPrefix")
            dest["S3DestinationDescription"] = body
        elif self.mode == "multiple":
            result["Destinations"] *= 2
        elif self.mode in {"empty", "missing-continuation"}:
            result["Destinations"] = []
            result["HasMoreDestinations"] = self.mode == "missing-continuation"
        elif self.mode in {"pagination", "repeat"}:
            result["HasMoreDestinations"] = (
                self.mode == "repeat" or "ExclusiveStartDestinationId" not in inputs
            )
            if self.mode == "pagination" and "ExclusiveStartDestinationId" in inputs:
                result["Destinations"] = []
        return self.response(api, operation, {"DeliveryStreamDescription": result})


def firehose_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    dest = {
        "RoleARN": "arn:aws:iam::123456789012:role/fixture",
        "BucketARN": "arn:aws:s3:::fixture-bucket",
        "Prefix": "incoming/",
        "ErrorOutputPrefix": "errors/",
        "BufferingHints": {"IntervalInSeconds": 300, "SizeInMBs": 5},
        "CompressionFormat": "GZIP",
        "EncryptionConfiguration": {"NoEncryptionConfig": "NoEncryption"},
        "CloudWatchLoggingOptions": {
            "Enabled": True,
            "LogGroupName": "fixture",
            "LogStreamName": "delivery",
        },
    }
    payload = {
        "DeliveryStreamName": "fixture",
        "DeliveryStreamARN": "arn:aws:firehose:ap-northeast-1:123456789012:deliverystream/fixture",
        "DeliveryStreamStatus": "ACTIVE",
        "DeliveryStreamType": "DirectPut",
        "VersionId": "1",
        "HasMoreDestinations": False,
        "Destinations": [
            {"DestinationId": "destination-1", "ExtendedS3DestinationDescription": dest}
        ],
        "DeliveryStreamEncryptionConfiguration": {"KeyType": "AWS_OWNED_CMK"},
    }
    ctx, fake = fixture_context(root, "data-firehose", FirehoseCalls, payload)
    record = inventory.adapter_inventory(
        ctx, "data-firehose", ("KinesisFirehose.DeliveryStream",)
    )[0]
    resource = fixture_resource(root, ctx, "data-firehose", record)
    getter = mapping.properties[properties[0]].field.getter
    cases = {
        "DeliveryStreamName": ("DeliveryStreamName", "typed", "fixture"),
        "DeliveryStreamType": ("DeliveryStreamType", "typed", "DirectPut"),
        "DeliveryStreamEncryptionConfigurationInput.KeyType": (
            "DeliveryStreamEncryptionConfiguration.KeyType",
            "typed",
            "AWS_OWNED_CMK",
        ),
    }
    for name in (
        "RoleARN",
        "BucketARN",
        "Prefix",
        "ErrorOutputPrefix",
        "CompressionFormat",
    ):
        cases["S3DestinationConfiguration." + name] = (
            name,
            "arn" if name.endswith("ARN") else "typed",
            dest[name],
        )
    for group in ("BufferingHints", "CloudWatchLoggingOptions"):
        for name, value in dest[group].items():
            path = group + "." + name
            cases["S3DestinationConfiguration." + path] = (
                path,
                "name" if name == "LogGroupName" else "typed",
                value,
            )
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "KinesisFirehose.DeliveryStream",
        cases,
        ["normal", "access-denied", "missing-selector"],
    )
    if getter == "destination":
        for mode in ("legacy", "pagination"):
            fake.mode = mode
            clear_fetch(ctx)
            result = resource.module.fetch(ctx, resource, getter)
            if (
                result.get("BucketARN") != dest["BucketARN"]
                or result.get("Prefix") != "incoming/"
            ):
                raise ValueError("Firehose destination variant differs")
        for mode in ("multiple", "empty", "missing-continuation", "repeat"):
            fake.mode = mode
            try:
                resource.module.fetch(ctx, resource, getter)
            except (cli.comparator().Unresolved, cli.comparator().AcquisitionError):
                pass
            else:
                raise ValueError("Invalid destination selection was accepted: " + mode)
        fake.mode = "normal"
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].extend(
                    [
                        "extended-s3",
                        "legacy-s3",
                        "pagination",
                        "ambiguous",
                        "empty",
                        "missing-continuation",
                        "repeated-continuation",
                    ]
                )
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "firehose.describe_delivery_stream",
        "DeliveryStreamName",
    )
    return items


CONTRACTS = (
    (
        ("KinesisFirehose.DeliveryStream", "base"),
        firehose_fixture,
        "firehose.describe_delivery_stream",
        ("DeliveryStreamName",),
    ),
    (
        ("KinesisFirehose.DeliveryStream", "destination"),
        firehose_fixture,
        "firehose.describe_delivery_stream",
        ("DeliveryStreamName",),
    ),
)
