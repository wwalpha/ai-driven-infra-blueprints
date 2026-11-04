"""Offline lambda adapter fixtures."""

import json
from pathlib import Path
from typing import Any

from model.importing import cli
from model.importing.adapter_contract_cases.core import (
    ACCOUNT,
    clear_fetch,
    direct_properties,
    direct_resource,
    failure_branches,
    fixture_properties,
    grouped_failures,
    grouped_resource,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls


class PermissionCalls(DirectCalls):
    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        if self.operation != "get_policy" or api == "cloudcontrol":
            return super().call(api, operation, **inputs)
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "lambda",
            "get_policy",
            {"FunctionName": "fixture"},
        ):
            raise ValueError("Permission parent selector differs")
        return self.response(api, operation, {"Policy": json.dumps(self.payload)})


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api, operation, selector, argument, envelope = (
        "lambda",
        "get_function_recursion_config"
        if properties[0].endswith(".RecursiveLoop")
        else "get_function",
        "FunctionName",
        "FunctionName",
        "$",
    )
    cloud = {"FunctionName": "fixture"}
    if operation == "get_function_recursion_config":
        payload = {"RecursiveLoop": "Allow"}
        cases = {"RecursiveLoop": ("RecursiveLoop", "typed", "Allow")}
    else:
        payload = {
            "Configuration": {
                "FunctionName": "fixture",
                "Architectures": ["x86_64"],
                "EphemeralStorage": {"Size": 512},
                "Handler": "handler.main",
                "LoggingConfig": {
                    "LogFormat": "JSON",
                    "LogGroup": "/aws/lambda/fixture",
                },
                "MemorySize": 128,
                "PackageType": "Zip",
                "Role": "arn:aws:iam::123456789012:role/fixture",
                "Runtime": "python3.12",
                "Timeout": 30,
                "TracingConfig": {"Mode": "Active"},
                "VpcConfig": {
                    "Ipv6AllowedForDualStack": False,
                    "SecurityGroupIds": ["sg-12345678"],
                    "SubnetIds": ["subnet-12345678", "subnet-87654321"],
                },
            },
            "Code": {
                "ImageUri": "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/fixture:tag",
                "ResolvedS3Object": {
                    "S3Bucket": "fixture-code",
                    "S3Key": "handler.zip",
                },
            },
            "Concurrency": {"ReservedConcurrentExecutions": 5},
        }
        cases = {
            name: (
                "Configuration." + name,
                "arn" if name == "Role" else "typed",
                value,
            )
            for name, value in payload["Configuration"].items()
            if name
            not in {
                "EphemeralStorage",
                "LoggingConfig",
                "TracingConfig",
                "VpcConfig",
            }
        }
        for section in (
            "EphemeralStorage",
            "LoggingConfig",
            "TracingConfig",
            "VpcConfig",
        ):
            for name, value in payload["Configuration"][section].items():
                key = section + "." + name
                cases[key] = (
                    "Configuration." + key,
                    "id"
                    if name in {"SecurityGroupIds", "SubnetIds"}
                    else "name"
                    if name == "LogGroup"
                    else "typed",
                    value,
                )
        cases.update(
            {
                "Code.ImageUri": (
                    "Code.ImageUri",
                    "typed",
                    "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/fixture:tag",
                ),
                "Code.S3Bucket": (
                    "Code.ResolvedS3Object.S3Bucket",
                    "name",
                    "fixture-code",
                ),
                "Code.S3Key": (
                    "Code.ResolvedS3Object.S3Key",
                    "typed",
                    "handler.zip",
                ),
                "ReservedConcurrentExecutions": (
                    "Concurrency.ReservedConcurrentExecutions",
                    "typed",
                    5,
                ),
            }
        )
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


def permission_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "Lambda.Permission"
    parent_kind = "Lambda.Function"
    parent_prop = "FunctionName"
    child_prop = "FunctionName"
    getter = "permission"
    source_arn = "arn:aws:s3:::fixture-bucket"
    statement = {
        "Sid": "fixture-permission",
        "Action": "lambda:InvokeFunction",
        "Principal": {"Service": "s3.amazonaws.com"},
        "Condition": {
            "ArnLike": {"AWS:SourceArn": source_arn},
            "StringEquals": {"AWS:SourceAccount": ACCOUNT},
        },
    }
    payload = {"Version": "2012-10-17", "Statement": [statement]}
    cases = {
        "Id": ("Sid", "typed", "fixture-permission"),
        "Action": ("Action", "typed", "lambda:InvokeFunction"),
        "FunctionName": ("FunctionName", "name", "fixture"),
        "Principal": ("Principal", "typed", "s3.amazonaws.com"),
        "SourceArn": ("SourceArn", "arn", source_arn),
        "SourceAccount": ("SourceAccount", "typed", ACCOUNT),
    }
    ctx, fake, resource = grouped_resource(
        root,
        mapping,
        kind,
        parent_kind,
        parent_prop,
        child_prop,
        "lambda",
        "get_policy",
        "fixture-permission",
        payload,
        PermissionCalls,
    )
    resource.rows.extend(
        (
            "fixture-" + name,
            {"property": kind + "." + name, "value": cli.model_literal(case[2])},
        )
        for name, case in cases.items()
        if not resource.rows_for(name)
    )
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["parent-selector", "parent-mismatch", "missing-selector", "access-denied"],
    )
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".Id")
    ]
    for principal in ("s3.amazonaws.com", {"Service": "s3.amazonaws.com"}):
        for condition in ("ArnLike", "ArnEquals"):
            fake.payload = {
                "Statement": [
                    {
                        **statement,
                        "Principal": principal,
                        "Condition": {
                            condition: {"AWS:SourceArn": source_arn},
                            "StringEquals": {"AWS:SourceAccount": ACCOUNT},
                        },
                    }
                ]
            }
            clear_fetch(ctx)
            if (
                resource.module.fetch(ctx, resource, getter)["Principal"]
                != "s3.amazonaws.com"
            ):
                raise ValueError("Permission principal/condition projection differs")
    fake.payload = {"Statement": [statement, statement]}
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous permissions were accepted")
    fake.payload = payload
    for item in items.values():
        if item["status"] == "verified":
            item["branches"].extend(
                [
                    "sid-selector",
                    "property-selector",
                    "string-principal",
                    "object-principal",
                    "arn-like",
                    "arn-equals",
                    "ambiguous",
                ]
            )
    grouped_failures(
        ctx, fake, resource, mapping, properties[0], kind, getter, child_prop
    )
    return items


CONTRACTS = (
    (
        ("Lambda.Permission", "permission"),
        permission_fixture,
        "lambda.get_policy",
        ("parent", "FunctionName", "Id", "properties"),
    ),
    (
        ("Lambda.Function", "base"),
        direct_fixture,
        "lambda.get_function",
        ("FunctionName",),
    ),
    (
        ("Lambda.Function", "recursion"),
        direct_fixture,
        "lambda.get_function_recursion_config",
        ("FunctionName",),
    ),
)
