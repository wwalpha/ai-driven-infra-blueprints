"""Offline security-hub adapter fixtures."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    clear_fetch,
    fixture_context,
    fixture_properties,
    fixture_resource,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class SecurityHubCalls(FakeCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        return self.call(api, operation, **inputs)

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("securityhub", "describe_hub", {}):
            raise ValueError("Security Hub request differs from fixture")
        return self.response(api, operation, deepcopy(self.payload))


def securityhub_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    payload = {
        "HubArn": "arn:aws:securityhub:ap-northeast-1:123456789012:hub/default",
        "SubscribedAt": "2026-01-01T00:00:00Z",
        "AutoEnableControls": True,
        "ControlFindingGenerator": "STANDARD_CONTROL",
    }
    cases = {
        "AutoEnableControls": ("AutoEnableControls", "typed", True),
        "ControlFindingGenerator": (
            "ControlFindingGenerator",
            "typed",
            "STANDARD_CONTROL",
        ),
    }
    ctx, fake = fixture_context(root, "security-hub", SecurityHubCalls, payload)
    record = inventory.adapter_inventory(ctx, "security-hub", ("SecurityHub.Hub",))[0]
    resource = fixture_resource(root, ctx, "security-hub", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "SecurityHub.Hub",
        cases,
        ["normal", "access-denied"],
    )
    if fake.calls != [("securityhub", "describe_hub", {})]:
        raise ValueError("Security Hub request differs from fixture")
    missing_values(ctx, fake, resource, mapping, items, payload)
    fake.error = cli.comparator().AcquisitionError(
        "securityhub.describe_hub", "AccessDenied"
    )
    clear_fetch(ctx)
    try:
        mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("API failure was changed") from error
    else:
        raise ValueError("API failure was swallowed")
    return items


CONTRACTS = (
    (("SecurityHub.Hub", "base"), securityhub_fixture, "securityhub.describe_hub", ()),
)
