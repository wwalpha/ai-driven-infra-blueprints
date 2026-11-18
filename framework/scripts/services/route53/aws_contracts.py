"""Offline route53 adapter fixtures."""

import json
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
    import_normalize,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls, FakeCalls
from model.importing.contract_fixtures import (
    InvalidFixture,
)


class Route53Calls(FakeCalls):
    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "route53",
            "list_resource_record_sets",
            {"HostedZoneId": "Z1"},
        ):
            raise InvalidFixture("Unexpected Route53 fixture request")
        return self.response(
            api,
            operation,
            {
                "ResourceRecordSets": deepcopy(self.payload),
                "IsTruncated": False,
                "MaxItems": "100",
            },
        )


class HostedZoneCalls(DirectCalls):
    zone_id = "Z123456789"
    wrong_vpc = False
    vpcs = [{"VPCId": "vpc-12345678", "VPCRegion": "ap-northeast-1"}]

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("route53", "list_hosted_zones", {}):
            raise ValueError("Hosted zone list scope differs")
        return self.response(
            api,
            operation,
            {
                "HostedZones": [deepcopy(self.payload)] * (2 if self.duplicate else 1),
                "Marker": "",
                "MaxItems": "100",
                "IsTruncated": False,
            },
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        if api == "cloudcontrol":
            return super().call(api, operation, **inputs)
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation) != ("route53", "get_hosted_zone") or inputs not in (
            {"Id": self.zone_id},
            {"Id": "/hostedzone/" + self.zone_id},
        ):
            raise ValueError("Hosted zone ID differs")
        return self.response(
            api,
            operation,
            {
                "HostedZone": deepcopy(self.payload),
                "VPCs": [{"VPCId": "vpc-87654321", "VPCRegion": "ap-northeast-1"}]
                if self.wrong_vpc
                else deepcopy(self.vpcs),
            },
        )


def hosted_zone_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    payload = {
        "Id": "/hostedzone/" + HostedZoneCalls.zone_id,
        "Name": "Example.COM.",
        "CallerReference": "fixture",
        "Config": {"Comment": "fixture zone", "PrivateZone": True},
    }
    ctx, fake = fixture_context(root, "route53", HostedZoneCalls, payload)
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("route53")
    fake.typename, fake.identifier, fake.cloud_properties = (
        "AWS::Route53::HostedZone",
        fake.zone_id,
        {"Id": fake.zone_id, "Name": "Example.COM."},
    )
    record = source.cloud_record(
        "route53",
        "Route53.HostedZone",
        {"Identifier": fake.zone_id, "Properties": json.dumps(fake.cloud_properties)},
        source.schema("Route53.HostedZone"),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "route53", record)
    getter = mapping.properties[properties[0]].field.getter
    cases = {
        "Id": ("Id", "typed", fake.zone_id),
        "Name": ("Name", "dns", "example.com"),
        "HostedZoneConfig.Comment": ("Config.Comment", "typed", "fixture zone"),
        "VPCs[].VPCId": ("VPCs[].VPCId", "id", ["vpc-12345678"]),
        "VPCs[].VPCRegion": ("VPCs[].VPCRegion", "typed", ["ap-northeast-1"]),
    }
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "Route53.HostedZone",
        cases,
        [
            "id-selector",
            "name-selector",
            "vpc-membership",
            "ambiguous",
            "access-denied",
            "missing-selector",
        ],
    )
    fake.payload = {**payload, "Config": {"PrivateZone": True}}
    if (
        getter == "zone"
        and resource.module.fetch(ctx, resource, getter)
        .get("Config", {})
        .get("Comment")
        is not None
    ):
        raise ValueError("Missing zone comment was lost")
    fake.payload = payload
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".Id")
    ]
    resource.module.fetch(ctx, resource, getter)
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous hosted zones were accepted")
    fake.duplicate = False
    resource.rows.append(
        (
            "fixture-vpc",
            {"property": "Route53.HostedZone.VPCs[].VPCId", "value": "`vpc-12345678`"},
        )
    )
    resource.module.fetch(ctx, resource, getter)
    fake.wrong_vpc = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("Unmatched zone VPC membership was accepted")
    fake.wrong_vpc = False
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "route53.get_hosted_zone", "Name"
    )
    return items


def route53_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    cases = [
        {
            "Name": "example.com.",
            "Type": "A",
            "TTL": 60,
            "ResourceRecords": [{"Value": "192.0.2.1"}],
        },
        {
            "Name": "weighted.example.com.",
            "Type": "A",
            "SetIdentifier": "blue",
            "Weight": 1,
            "TTL": 60,
            "ResourceRecords": [{"Value": "192.0.2.2"}],
        },
        {
            "Name": "weighted.example.com.",
            "Type": "A",
            "SetIdentifier": "green",
            "Weight": 2,
            "TTL": 60,
            "ResourceRecords": [{"Value": "192.0.2.3"}],
        },
        {
            "Name": "alias.example.com.",
            "Type": "A",
            "AliasTarget": {
                "DNSName": "target.example.com.",
                "HostedZoneId": "Z2",
                "EvaluateTargetHealth": False,
            },
        },
    ]
    expected = {
        "Name": ("Name", "dns", 0, "example.com"),
        "AliasTarget.DNSName": ("AliasTarget.DNSName", "dns", 3, "target.example.com"),
        "AliasTarget.EvaluateTargetHealth": (
            "AliasTarget.EvaluateTargetHealth",
            "typed",
            3,
            False,
        ),
        "AliasTarget.HostedZoneId": ("AliasTarget.HostedZoneId", "typed", 3, "Z2"),
        "ResourceRecords": ("ResourceRecords[].Value", "set", 0, ["192.0.2.1"]),
        "SetIdentifier": ("SetIdentifier", "typed", 1, "blue"),
        "TTL": ("TTL", "typed", 0, "60"),
        "Type": ("Type", "typed", 0, "A"),
    }
    ctx, fake = fixture_context(root, "route53", Route53Calls, cases)
    records = inventory.sdk_inventory.collect(
        ctx,
        "Route53.RecordSet",
        parents=[
            {
                "kind": "Route53.HostedZone",
                "identity": "Z1",
                "cloudProperties": {"Id": "Z1"},
            }
        ],
    )
    resources = [
        fixture_resource(root, ctx, "route53", record, "fixture-" + str(index))
        for index, record in enumerate(records)
    ]
    items = {}
    for key in properties:
        name = key.removeprefix("Route53.RecordSet.")
        prop = mapping.properties[key]
        case = expected.get(name)
        if (
            case is None
            or prop.transform != "identity"
            or (prop.field.path, prop.field.norm) != case[:2]
        ):
            items[key] = {
                "status": "unverified",
                "reason": "No executable property/branch fixture",
            }
            continue
        _, raw = mapping_value(ctx, resources[case[2]], mapping, prop, key)
        import_normalize(ctx, "Route53.RecordSet", key, raw)
        actual = cli.comparator().normalize(ctx, raw, prop.field.norm)
        items[key] = (
            {
                "status": "verified",
                "reason": "Offline simple, weighted and alias responses only; AWS retrieval remains unverified",
                "branches": [
                    "normal",
                    "missing-selector",
                    "ambiguous-routing",
                    "access-denied",
                ],
            }
            if actual == case[3]
            else {"status": "broken", "reason": "Adapter result differs from fixture"}
        )
        if name not in {"Name", "Type"}:
            missing_index = (
                0 if name.startswith("AliasTarget.") or name == "SetIdentifier" else 3
            )
            _, absent = mapping_value(ctx, resources[missing_index], mapping, prop, key)
            normalized = cli.comparator().normalize(ctx, absent, prop.field.norm)
            if normalized not in (cli.comparator().MISSING, []):
                items[key] = {
                    "status": "broken",
                    "reason": "Missing value was not preserved",
                }
            elif items[key]["status"] == "verified":
                items[key]["branches"].append("missing-value")
    resource = resources[1]
    resource.rows[:] = [
        row
        for row in resource.rows
        if not row[1]["property"].endswith(".SetIdentifier")
    ]
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resource, "record")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous routing identifier was accepted")
    resource = resources[0]
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".HostedZoneId")
    ]
    try:
        resource.module.fetch(ctx, resource, "record")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing hosted zone selector was accepted")
    fake.error = cli.comparator().AcquisitionError(
        "route53.list_resource_record_sets", "AccessDenied"
    )
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resources[3], "record")
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("API failure was changed") from error
    else:
        raise ValueError("API failure was swallowed")
    return items


CONTRACTS = (
    (
        ("Route53.HostedZone", "zone"),
        hosted_zone_fixture,
        "route53.get_hosted_zone",
        ("Id", "Name", "VPCs"),
        ("route53.list_hosted_zones",),
    ),
    (
        ("Route53.HostedZone", "vpcs"),
        hosted_zone_fixture,
        "route53.get_hosted_zone",
        ("Id", "Name", "VPCs"),
        ("route53.list_hosted_zones",),
    ),
    (
        ("Route53.RecordSet", "record"),
        route53_fixture,
        "route53.list_resource_record_sets",
        ("HostedZoneId", "Name", "Type", "SetIdentifier"),
    ),
)
