"""Offline cloudwatch-logs adapter fixtures."""

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
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class LogsCalls(FakeCalls):
    def __init__(self, ctx: Any, payload: dict[str, Any]) -> None:
        super().__init__(ctx, payload)
        self.duplicate = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation) != ("logs", "describe_log_groups") or inputs not in (
            {},
            {"logGroupNamePrefix": "fixture"},
        ):
            raise ValueError("Log group selector differs from fixture")
        records = [deepcopy(self.payload)] * (2 if self.duplicate else 1)
        return self.response(api, operation, {"logGroups": records})


def logs_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    payload = {
        "logGroupName": "fixture",
        "logGroupClass": "STANDARD",
        "retentionInDays": 30,
        "deletionProtectionEnabled": True,
        "kmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
    }
    cases = {
        "LogGroupName": ("logGroupName", "typed", "fixture"),
        "LogGroupClass": ("logGroupClass", "typed", "STANDARD"),
        "RetentionInDays": ("retentionInDays", "typed", 30),
        "DeletionProtectionEnabled": ("deletionProtectionEnabled", "typed", True),
        "KmsKeyId": ("kmsKeyId", "kms", payload["kmsKeyId"]),
    }
    ctx, fake = fixture_context(root, "cloudwatch-logs", LogsCalls, payload)
    record = inventory.adapter_inventory(ctx, "cloudwatch-logs", ("Logs.LogGroup",))[0]
    resource = fixture_resource(root, ctx, "cloudwatch-logs", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "Logs.LogGroup",
        cases,
        ["normal", "missing-selector", "access-denied", "ambiguous"],
    )
    if fake.calls != [
        ("logs", "describe_log_groups", {"logGroupNamePrefix": "fixture"})
    ]:
        raise ValueError("Log group request differs from fixture")
    missing_values(
        ctx, fake, resource, mapping, items, payload, required=("logGroupName",)
    )
    fake.duplicate = True
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resource, "base")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Duplicate log groups were accepted")
    fake.duplicate = False
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "logs.describe_log_groups",
        "LogGroupName",
    )
    return items


CONTRACTS = (
    (
        ("Logs.LogGroup", "base"),
        logs_fixture,
        "logs.describe_log_groups",
        ("LogGroupName",),
    ),
)
