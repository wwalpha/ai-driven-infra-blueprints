"""Offline codecommit adapter fixtures."""

from pathlib import Path
from typing import Any

from model.importing.adapter_contract_cases.core import (
    direct_properties,
    direct_resource,
    failure_branches,
)


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api, operation, selector, argument, envelope = (
        "codecommit",
        "get_repository",
        "RepositoryName",
        "repositoryName",
        "repositoryMetadata",
    )
    cloud = {"RepositoryName": "fixture", "RepositoryId": "fixture-id"}
    payload = {
        "repositoryName": "fixture",
        "repositoryId": "fixture-id",
        "repositoryDescription": "fixture repository",
        "kmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
    }
    cases = {
        "RepositoryName": ("repositoryName", "typed", "fixture"),
        "RepositoryDescription": (
            "repositoryDescription",
            "typed",
            "fixture repository",
        ),
        "KmsKeyId": ("kmsKeyId", "kms", payload["kmsKeyId"]),
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
        identifier="fixture-id",
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
        ("CodeCommit.Repository", "base"),
        direct_fixture,
        "codecommit.get_repository",
        ("RepositoryName",),
    ),
)
