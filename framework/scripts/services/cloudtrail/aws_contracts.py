"""Offline cloudtrail adapter fixtures."""

from pathlib import Path
from typing import Any

from model.importing.adapter_contract_cases.core import (
    direct_properties,
    direct_resource,
    failure_branches,
)


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    getter = mapping.properties[properties[0]].field.getter
    api, selector = "cloudtrail", "TrailName"
    cloud = {"TrailName": "fixture"}
    operation, argument, envelope = {
        "base": ("get_trail", "Name", "Trail"),
        "status": ("get_trail_status", "Name", "$"),
        "selectors": ("get_event_selectors", "TrailName", "$"),
    }[getter]
    if getter == "base":
        payload = {
            "Name": "fixture",
            "S3BucketName": "fixture-trail-logs",
            "IncludeGlobalServiceEvents": True,
            "IsMultiRegionTrail": False,
            "LogFileValidationEnabled": True,
            "CloudWatchLogsLogGroupArn": "arn:aws:logs:ap-northeast-1:123456789012:log-group:fixture",
            "CloudWatchLogsRoleArn": "arn:aws:iam::123456789012:role/fixture",
            "KmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
        }
        cases = {
            "TrailName": ("Name", "typed", "fixture"),
            "S3BucketName": ("S3BucketName", "name", "fixture-trail-logs"),
            "IncludeGlobalServiceEvents": (
                "IncludeGlobalServiceEvents",
                "typed",
                True,
            ),
            "IsMultiRegionTrail": ("IsMultiRegionTrail", "typed", False),
            "EnableLogFileValidation": ("LogFileValidationEnabled", "typed", True),
            "CloudWatchLogsLogGroupArn": (
                "CloudWatchLogsLogGroupArn",
                "log_group_arn",
                payload["CloudWatchLogsLogGroupArn"],
            ),
            "CloudWatchLogsRoleArn": (
                "CloudWatchLogsRoleArn",
                "arn",
                payload["CloudWatchLogsRoleArn"],
            ),
            "KMSKeyId": ("KmsKeyId", "kms", payload["KmsKeyId"]),
        }
    elif getter == "status":
        payload = {"IsLogging": True}
        cases = {"IsLogging": ("IsLogging", "typed", True)}
    else:
        payload = {
            "EventSelectors": [
                {
                    "ReadWriteType": "All",
                    "IncludeManagementEvents": True,
                    "DataResources": [
                        {
                            "Type": "AWS::S3::Object",
                            "Values": ["arn:aws:s3:::fixture/"],
                        }
                    ],
                }
            ]
        }
        cases = {
            "EventSelectors[].ReadWriteType": (
                "EventSelectors[].ReadWriteType",
                "typed",
                ["All"],
            ),
            "EventSelectors[].IncludeManagementEvents": (
                "EventSelectors[].IncludeManagementEvents",
                "typed",
                [True],
            ),
            "EventSelectors[].DataResources[].Type": (
                "EventSelectors[].DataResources[].Type",
                "typed",
                [["AWS::S3::Object"]],
            ),
            "EventSelectors[].DataResources[].Values": (
                "EventSelectors[].DataResources[].Values",
                "arn",
                [[["arn:aws:s3:::fixture/"]]],
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
    (
        ("CloudTrail.Trail", "base"),
        direct_fixture,
        "cloudtrail.get_trail",
        ("TrailName",),
    ),
    (
        ("CloudTrail.Trail", "status"),
        direct_fixture,
        "cloudtrail.get_trail_status",
        ("TrailName",),
    ),
    (
        ("CloudTrail.Trail", "selectors"),
        direct_fixture,
        "cloudtrail.get_event_selectors",
        ("TrailName",),
    ),
)
