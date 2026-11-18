"""Offline codebuild adapter fixtures."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    clear_fetch,
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class CodeBuildCalls(FakeCalls):
    duplicate = False
    empty = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("codebuild", "list_projects", {}):
            raise ValueError("CodeBuild inventory request differs from fixture")
        return self.response(api, operation, {"projects": ["fixture"]})

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "codebuild",
            "batch_get_projects",
            {"names": ["fixture"]},
        ):
            raise ValueError("CodeBuild project selector differs from fixture")
        projects = (
            []
            if self.empty
            else [deepcopy(self.payload)] * (2 if self.duplicate else 1)
        )
        return self.response(api, operation, {"projects": projects})


def codebuild_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "CodeBuild.Project"
    payload = {
        "name": "fixture",
        "source": {
            "type": "CODECOMMIT",
            "location": "https://git-codecommit.ap-northeast-1.amazonaws.com/v1/repos/fixture",
        },
        "artifacts": {"type": "NO_ARTIFACTS"},
        "cache": {"type": "NO_CACHE"},
        "concurrentBuildLimit": 5,
        "environment": {
            "computeType": "BUILD_GENERAL1_SMALL",
            "image": "aws/codebuild/standard:7.0",
            "imagePullCredentialsType": "CODEBUILD",
            "privilegedMode": False,
            "type": "LINUX_CONTAINER",
            "environmentVariables": [
                {"name": "CONFIG", "value": "example", "type": "PLAINTEXT"}
            ],
        },
        "logsConfig": {
            "cloudWatchLogs": {
                "groupName": "/aws/codebuild/fixture",
                "status": "ENABLED",
            },
            "s3Logs": {"status": "DISABLED"},
        },
        "queuedTimeoutInMinutes": 60,
        "serviceRole": "arn:aws:iam::123456789012:role/fixture",
        "timeoutInMinutes": 30,
        "vpcConfig": {
            "vpcId": "vpc-12345678",
            "subnets": ["subnet-12345678", "subnet-87654321"],
            "securityGroupIds": ["sg-12345678"],
        },
    }
    cases = {
        "Name": ("name", "typed", "fixture"),
        "Id": ("name", "typed", "fixture"),
        "Artifacts.Type": ("artifacts.type", "typed", "NO_ARTIFACTS"),
        "Cache.Type": ("cache.type", "typed", "NO_CACHE"),
        "ConcurrentBuildLimit": ("concurrentBuildLimit", "typed", 5),
        "Environment.ComputeType": (
            "environment.computeType",
            "typed",
            "BUILD_GENERAL1_SMALL",
        ),
        "Environment.EnvironmentVariables[].Name": (
            "environment.environmentVariables[].name",
            "typed",
            ["CONFIG"],
        ),
        "Environment.EnvironmentVariables[].Type": (
            "environment.environmentVariables[].type",
            "typed",
            ["PLAINTEXT"],
        ),
        "Environment.Image": (
            "environment.image",
            "typed",
            "aws/codebuild/standard:7.0",
        ),
        "Environment.ImagePullCredentialsType": (
            "environment.imagePullCredentialsType",
            "typed",
            "CODEBUILD",
        ),
        "Environment.PrivilegedMode": ("environment.privilegedMode", "typed", False),
        "Environment.Type": ("environment.type", "typed", "LINUX_CONTAINER"),
        "LogsConfig.CloudWatchLogs.GroupName": (
            "logsConfig.cloudWatchLogs.groupName",
            "typed",
            "/aws/codebuild/fixture",
        ),
        "LogsConfig.CloudWatchLogs.Status": (
            "logsConfig.cloudWatchLogs.status",
            "typed",
            "ENABLED",
        ),
        "LogsConfig.S3Logs.Status": ("logsConfig.s3Logs.status", "typed", "DISABLED"),
        "QueuedTimeoutInMinutes": ("queuedTimeoutInMinutes", "typed", 60),
        "ServiceRole": ("serviceRole", "arn", payload["serviceRole"]),
        "Source.Type": ("source.type", "typed", "CODECOMMIT"),
        "TimeoutInMinutes": ("timeoutInMinutes", "typed", 30),
        "VpcConfig.SecurityGroupIds": (
            "vpcConfig.securityGroupIds",
            "id",
            ["sg-12345678"],
        ),
        "VpcConfig.Subnets": (
            "vpcConfig.subnets",
            "id",
            ["subnet-12345678", "subnet-87654321"],
        ),
        "VpcConfig.VpcId": ("vpcConfig.vpcId", "id", "vpc-12345678"),
    }
    ctx, fake = fixture_context(root, "codebuild", CodeBuildCalls, payload)
    record = inventory.adapter_inventory(ctx, "codebuild", (kind,))[0]
    resource = fixture_resource(root, ctx, "codebuild", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied", "missing-project", "ambiguous"],
    )
    if fake.calls != [("codebuild", "batch_get_projects", {"names": ["fixture"]})]:
        raise ValueError("CodeBuild request differs from fixture")
    missing_values(
        ctx,
        fake,
        resource,
        mapping,
        items,
        payload,
        required=("name", "source", "artifacts", "environment", "serviceRole"),
    )
    for mode in ("empty", "duplicate"):
        setattr(fake, mode, True)
        clear_fetch(ctx)
        try:
            mapping_value(
                ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
            )
        except (
            cli.comparator().AcquisitionError,
            cli.comparator().Unresolved,
        ) as error:
            if mode == "empty" and (
                not isinstance(error, cli.comparator().AcquisitionError)
                or error.status != "resource_missing"
            ):
                raise ValueError(
                    "Missing CodeBuild project failure was changed"
                ) from error
            if mode == "duplicate" and not isinstance(
                error, cli.comparator().Unresolved
            ):
                raise ValueError(
                    "Ambiguous CodeBuild project failure was changed"
                ) from error
        else:
            raise ValueError("Missing or ambiguous CodeBuild project was accepted")
        setattr(fake, mode, False)
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "codebuild.batch_get_projects",
        "Name",
    )
    return items


CONTRACTS = (
    (
        ("CodeBuild.Project", "base"),
        codebuild_fixture,
        "codebuild.batch_get_projects",
        ("Name",),
    ),
)
