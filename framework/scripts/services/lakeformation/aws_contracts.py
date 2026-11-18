"""Offline lake-formation adapter fixtures."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from model.importing import inventory
from model.importing.adapter_contract_cases.core import (
    ACCOUNT,
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls, FakeCalls
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


class DataLakeSettingsCalls(DirectCalls):
    api = "lakeformation"
    operation = "get_data_lake_settings"
    inputs = {"CatalogId": ACCOUNT}
    envelope = "DataLakeSettings"


def data_lake_settings_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "LakeFormation.DataLakeSettings"
    principal_id = "arn:aws:iam::123456789012:role/fixture"
    read_only_id = "arn:aws:iam::123456789012:role/fixture-read-only"
    external_account = "234567890123"
    default_principal = "IAM_ALLOWED_PRINCIPALS"
    default_permissions = {
        "Principal": {"DataLakePrincipalIdentifier": default_principal},
        "Permissions": ["ALL"],
    }
    payload = {
        "DataLakeAdmins": [{"DataLakePrincipalIdentifier": principal_id}],
        "ReadOnlyAdmins": [{"DataLakePrincipalIdentifier": read_only_id}],
        "CreateDatabaseDefaultPermissions": [default_permissions],
        "CreateTableDefaultPermissions": [default_permissions],
        "AllowExternalDataFiltering": True,
        "AllowFullTableExternalDataAccess": False,
        "ExternalDataFilteringAllowList": [
            {"DataLakePrincipalIdentifier": external_account}
        ],
        "AuthorizedSessionTagValueList": ["fixture"],
        "TrustedResourceOwners": [external_account],
        "Parameters": {"CROSS_ACCOUNT_VERSION": "3"},
    }
    ctx, fake = fixture_context(root, "lake-formation", DataLakeSettingsCalls, payload)
    resource = fixture_resource(
        root, ctx, "lake-formation", {"kind": kind, "getters": {}}
    )
    cases = {name: (name, "typed", value) for name, value in payload.items()}
    cases["Admins"] = ("DataLakeAdmins", "typed", payload["DataLakeAdmins"])
    for name, path, value in (
        ("Admins", "DataLakeAdmins", principal_id),
        ("ReadOnlyAdmins", "ReadOnlyAdmins", read_only_id),
        (
            "ExternalDataFilteringAllowList",
            "ExternalDataFilteringAllowList",
            external_account,
        ),
    ):
        leaf = "[].DataLakePrincipalIdentifier"
        cases[name + leaf] = (path + leaf, "typed", [value])
    for name in ("CreateDatabaseDefaultPermissions", "CreateTableDefaultPermissions"):
        for suffix, value in (
            ("[].Principal.DataLakePrincipalIdentifier", [default_principal]),
            ("[].Permissions", [["ALL"]]),
        ):
            path = name + suffix
            cases[path] = (path, "typed", value)
    items = fixture_properties(
        ctx, resource, mapping, properties, kind, cases, ["normal"]
    )
    missing_values(ctx, fake, resource, mapping, items, payload)
    return items


CONTRACTS = (
    (
        ("LakeFormation.DataLakeSettings", "sdk-lakeformation-datalakesettings"),
        data_lake_settings_fixture,
        "lakeformation.get_data_lake_settings",
        ("CatalogId",),
    ),
    (
        ("LakeFormation.Resource", "sdk-lakeformation-resource"),
        lakeformation_fixture,
        "lakeformation.describe_resource",
        ("ResourceArn",),
    ),
)
