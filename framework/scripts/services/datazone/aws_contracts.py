"""Offline datazone adapter fixtures."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.target import AWS_ACCOUNT_ID_KEY
from model.importing import inventory
from model.importing.adapter_contract_cases.core import (
    ACCOUNT,
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls
from model.importing.contract_fixtures import (
    InvalidFixture,
)


class DataZoneCalls(FakeCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == ("datazone", "list_domains", {}):
            return self.response(
                api,
                operation,
                {
                    "items": [
                        {
                            "id": "dzd_domain",
                            "name": "dzd_domain",
                            "arn": "arn:aws:datazone:ap-northeast-1:123456789012:domain/dzd_domain",
                            "managedAccountId": ACCOUNT,
                            "status": "AVAILABLE",
                            "createdAt": datetime(2026, 1, 1, tzinfo=timezone.utc),
                        }
                    ]
                },
            )
        if (api, operation, inputs) == (
            "datazone",
            "list_projects",
            {"domainIdentifier": "dzd_domain"},
        ):
            return self.response(
                api,
                operation,
                {
                    "items": [
                        {
                            "domainId": "dzd_domain",
                            "id": "project",
                            "name": "project",
                            "createdBy": "fixture",
                        }
                    ]
                },
            )
        raise InvalidFixture("Unexpected DataZone inventory request")

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) == (
            "datazone",
            "get_domain",
            {"identifier": "dzd_domain"},
        ):
            return self.response(
                api,
                operation,
                {
                    "id": "dzd_domain",
                    "domainExecutionRole": "arn:aws:iam::123456789012:role/fixture",
                    "status": "AVAILABLE",
                    "domainVersion": "V2",
                },
            )
        if (api, operation, inputs) != (
            "datazone",
            "get_project",
            {"domainIdentifier": "dzd_domain", "identifier": "project"},
        ):
            raise ValueError("DataZone selector differs from fixture")
        return self.response(
            api,
            operation,
            {
                "domainId": "dzd_domain",
                "id": "project",
                "name": "project",
                "createdBy": "fixture",
            },
        )


def datazone_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    ctx, fake = fixture_context(root, "datazone", DataZoneCalls, {})
    record = inventory.sdk_inventory.collect(ctx, "DataZone.Project")[0]
    resource = fixture_resource(root, ctx, "datazone", record)
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "DataZone.Project",
        {"DomainIdentifier": ("domainId", "typed", "dzd_domain")},
        ["normal", "missing-selector", "access-denied"],
    )
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "datazone.get_project",
        "DomainIdentifier",
    )
    ctx.target[AWS_ACCOUNT_ID_KEY] = "999999999999"
    try:
        inventory.sdk_inventory.collect(ctx, "DataZone.Project")
    except ValueError as error:
        if "scope mismatch" not in str(error):
            raise
    else:
        raise ValueError("DataZone domain scope mismatch was accepted")
    for evidence in items.values():
        if evidence["status"] == "verified":
            evidence["branches"].append("account-mismatch")
    return items


def datazone_domain_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    ctx, fake = fixture_context(root, "datazone", DataZoneCalls, {})
    record = {
        "kind": "DataZone.Domain",
        "getters": {},
        "selectorProperties": {"DataZone.Domain.Id": "dzd_domain"},
    }
    resource = fixture_resource(root, ctx, "datazone", record)
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "DataZone.Domain",
        {
            "Id": ("id", "typed", "dzd_domain"),
            "DomainVersion": ("domainVersion", "typed", "V2"),
        },
        ["normal", "missing-selector", "access-denied"],
    )
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "datazone.get_domain", "Id"
    )
    return items


CONTRACTS = (
    (
        ("DataZone.Project", "sdk-datazone-project"),
        datazone_fixture,
        "datazone.get_project",
        ("DomainIdentifier", "Id"),
    ),
    (
        ("DataZone.Domain", "sdk-datazone-domain"),
        datazone_domain_fixture,
        "datazone.get_domain",
        ("Id",),
    ),
)
