"""Offline secrets-manager adapter fixtures."""

from pathlib import Path
from typing import Any

from model.importing.adapter_contract_cases.core import (
    direct_properties,
    direct_resource,
    failure_branches,
    fixture_properties,
    grouped_failures,
    grouped_resource,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api, operation, selector, argument, envelope = (
        "secretsmanager",
        "describe_secret",
        "Name",
        "SecretId",
        "$",
    )
    cloud = {
        "Name": "fixture",
        "Id": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:fixture-AbCdEf",
    }
    payload = {
        "ARN": cloud["Id"],
        "Name": "fixture",
        "Type": "fixture-partner",
        "Description": "fixture secret metadata",
        "KmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
    }
    cases = {
        "Name": ("Name", "typed", "fixture"),
        "Type": ("Type", "typed", "fixture-partner"),
        "Description": ("Description", "typed", "fixture secret metadata"),
        "KmsKeyId": ("KmsKeyId", "kms", payload["KmsKeyId"]),
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


def rotation_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = "SecretsManager.RotationSchedule"
    parent_kind = "SecretsManager.Secret"
    parent_prop = "Name"
    child_prop = "SecretId"
    getter = "rotation"
    payload = {
        "Name": "fixture",
        "RotationRules": {"AutomaticallyAfterDays": 30, "Duration": "2h"},
        "ExternalSecretRotationMetadata": [
            {"Key": "fixture-key", "Value": "fixture-value"}
        ],
        "ExternalSecretRotationRoleArn": "arn:aws:iam::123456789012:role/fixture",
    }
    cases = {
        "SecretId": ("Name", "name", "fixture"),
        "RotationRules.AutomaticallyAfterDays": (
            "RotationRules.AutomaticallyAfterDays",
            "typed",
            30,
        ),
        "RotationRules.Duration": ("RotationRules.Duration", "typed", "2h"),
        "ExternalSecretRotationMetadata[].Key": (
            "ExternalSecretRotationMetadata[].Key",
            "typed",
            ["fixture-key"],
        ),
        "ExternalSecretRotationMetadata[].Value": (
            "ExternalSecretRotationMetadata[].Value",
            "typed",
            ["fixture-value"],
        ),
        "ExternalSecretRotationRoleArn": (
            "ExternalSecretRotationRoleArn",
            "arn",
            payload["ExternalSecretRotationRoleArn"],
        ),
    }
    ctx, fake, resource = grouped_resource(
        root,
        mapping,
        kind,
        parent_kind,
        parent_prop,
        child_prop,
        "secretsmanager",
        "describe_secret",
        "fixture-rotation",
        payload,
        DirectCalls,
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
    missing_values(ctx, fake, resource, mapping, items, payload, required=("Name",))
    grouped_failures(
        ctx, fake, resource, mapping, properties[0], kind, getter, child_prop
    )
    return items


CONTRACTS = (
    (
        ("SecretsManager.RotationSchedule", "rotation"),
        rotation_fixture,
        "secretsmanager.describe_secret",
        ("parent", "SecretId"),
    ),
    (
        ("SecretsManager.Secret", "base"),
        direct_fixture,
        "secretsmanager.describe_secret",
        ("Name",),
    ),
)
