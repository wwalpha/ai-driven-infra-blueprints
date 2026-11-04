"""Offline lake-formation adapter fixtures."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from model.importing import inventory
from model.importing.adapter_contract_cases.core import (
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls
from model.importing.contract_fixtures import (
    InvalidFixture,
)


class LakeFormationCalls(FakeCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) != ("lakeformation", "list_resources", {}):
            raise InvalidFixture("Unexpected Lake Formation inventory request")
        return self.response(
            api,
            operation,
            {"ResourceInfoList": [{"ResourceArn": "arn:aws:s3:::fixture"}]},
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "lakeformation",
            "describe_resource",
            {"ResourceArn": "arn:aws:s3:::fixture"},
        ):
            raise ValueError("Lake Formation selector differs from fixture")
        return self.response(api, operation, {"ResourceInfo": deepcopy(self.payload)})


def lakeformation_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    expected = {
        "ResourceArn": "arn:aws:s3:::fixture",
        "RoleArn": "arn:aws:iam::123456789012:role/fixture",
        "WithFederation": True,
        "HybridAccessEnabled": False,
    }
    ctx, fake = fixture_context(root, "lake-formation", LakeFormationCalls, expected)
    record = inventory.sdk_inventory.collect(ctx, "LakeFormation.Resource")[0]
    resource = fixture_resource(root, ctx, "lake-formation", record)
    cases = {
        name: (name, "arn" if name.endswith("Arn") else "typed", value)
        for name, value in expected.items()
    }
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "LakeFormation.Resource",
        cases,
        ["normal", "missing-selector", "access-denied"],
    )
    missing_values(
        ctx, fake, resource, mapping, items, expected, required=("ResourceArn",)
    )
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "lakeformation.describe_resource",
        "ResourceArn",
    )
    return items


CONTRACTS = (
    (
        ("LakeFormation.Resource", "sdk-lakeformation-resource"),
        lakeformation_fixture,
        "lakeformation.describe_resource",
        ("ResourceArn",),
    ),
)
