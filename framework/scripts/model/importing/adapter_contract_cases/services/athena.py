"""Offline athena adapter fixtures."""

from pathlib import Path
from typing import Any

from model.importing.adapter_contract_cases.core import (
    ACCOUNT,
    direct_properties,
    direct_resource,
    failure_branches,
)


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api, operation, selector, argument, envelope = (
        "athena",
        "get_work_group",
        "Name",
        "WorkGroup",
        "WorkGroup",
    )
    cloud = {"Name": "fixture"}
    payload = {
        "Name": "fixture",
        "State": "ENABLED",
        "Description": "fixture workgroup",
        "Configuration": {
            "EnforceWorkGroupConfiguration": True,
            "EngineVersion": {"SelectedEngineVersion": "Athena engine version 3"},
            "PublishCloudWatchMetricsEnabled": True,
            "RequesterPaysEnabled": False,
            "ResultConfiguration": {
                "OutputLocation": "s3://fixture-results/",
                "ExpectedBucketOwner": ACCOUNT,
                "EncryptionConfiguration": {
                    "EncryptionOption": "SSE_KMS",
                    "KmsKey": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                },
            },
        },
    }
    cases = {
        "Name": ("Name", "typed", "fixture"),
        "Description": ("Description", "typed", "fixture workgroup"),
        "State": ("State", "typed", "ENABLED"),
        "WorkGroupConfiguration.EnforceWorkGroupConfiguration": (
            "Configuration.EnforceWorkGroupConfiguration",
            "typed",
            True,
        ),
        "WorkGroupConfiguration.EngineVersion.SelectedEngineVersion": (
            "Configuration.EngineVersion.SelectedEngineVersion",
            "typed",
            "Athena engine version 3",
        ),
        "WorkGroupConfiguration.PublishCloudWatchMetricsEnabled": (
            "Configuration.PublishCloudWatchMetricsEnabled",
            "typed",
            True,
        ),
        "WorkGroupConfiguration.RequesterPaysEnabled": (
            "Configuration.RequesterPaysEnabled",
            "typed",
            False,
        ),
        "WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.EncryptionOption": (
            "Configuration.ResultConfiguration.EncryptionConfiguration.EncryptionOption",
            "typed",
            "SSE_KMS",
        ),
        "WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey": (
            "Configuration.ResultConfiguration.EncryptionConfiguration.KmsKey",
            "kms",
            payload["Configuration"]["ResultConfiguration"]["EncryptionConfiguration"][
                "KmsKey"
            ],
        ),
        "WorkGroupConfiguration.ResultConfiguration.ExpectedBucketOwner": (
            "Configuration.ResultConfiguration.ExpectedBucketOwner",
            "typed",
            ACCOUNT,
        ),
        "WorkGroupConfiguration.ResultConfiguration.OutputLocation": (
            "Configuration.ResultConfiguration.OutputLocation",
            "typed",
            "s3://fixture-results/",
        ),
    }
    ctx, fake, resource = direct_resource(
        root,
        mapping,
        kind,
        api,
        operation,
        {argument: "fixture"},
        envelope,
        cloud,
        payload,
    )
    items = direct_properties(
        ctx,
        fake,
        resource,
        mapping,
        properties,
        kind,
        cases,
        payload,
        (
            "Name",
            "repositoryName",
            "InstanceProfileName",
            "RoleName",
            "UserName",
            "Roles",
        ),
    )
    if not fake.calls:
        return items
    failure_branches(
        ctx, fake, resource, mapping, properties[0], api + "." + operation, selector
    )
    return items


CONTRACTS = (
    (("Athena.WorkGroup", "base"), direct_fixture, "athena.get_work_group", ("Name",)),
)
