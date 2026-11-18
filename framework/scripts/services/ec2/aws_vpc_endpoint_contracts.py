"""Offline vpc-endpoint adapter fixtures."""

import json
from pathlib import Path
from typing import Any

from model.importing import cli
from model.importing.adapter_contract_cases.core import (
    clear_fetch,
    fixture_properties,
    missing_values,
    network_failures,
    network_resource,
)


def network_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = "EC2.VPCEndpoint"
    getter = mapping.properties[properties[0]].field.getter
    tags = [{"Key": "Name", "Value": "fixture"}]
    operation, collection, id_arg, id_prop = (
        "describe_vpc_endpoints",
        "VpcEndpoints",
        "VpcEndpointIds",
        "VpcEndpointId",
    )
    payload = {
        "VpcEndpointId": "vpce-12345678",
        "VpcId": "vpc-12345678",
        "ServiceName": "com.amazonaws.ap-northeast-1.s3",
        "VpcEndpointType": "Interface",
        "PrivateDnsEnabled": False,
        "DnsOptions": {"PrivateDnsOnlyForInboundResolverEndpoint": False},
        "IpAddressType": "ipv4",
        "PolicyDocument": json.dumps({"Version": "2012-10-17", "Statement": []}),
        "SubnetIds": ["subnet-12345678"],
        "RouteTableIds": ["rtb-12345678"],
        "Groups": [{"GroupId": "sg-12345678"}],
        "Tags": tags,
    }
    cases = {
        name: (
            name,
            "id" if name in {"VpcId", "SubnetIds", "RouteTableIds"} else "typed",
            value,
        )
        for name, value in payload.items()
        if name not in {id_prop, "PolicyDocument", "Groups", "Tags", "DnsOptions"}
    }
    cases.update(
        {
            "Id": (id_prop, "typed", payload[id_prop]),
            "PolicyDocument": (
                "PolicyDocument",
                "policy",
                {"Version": "2012-10-17", "Statement": []},
            ),
            "SecurityGroupIds": ("Groups[].GroupId", "id", ["sg-12345678"]),
            "DnsOptions.PrivateDnsOnlyForInboundResolverEndpoint": (
                "DnsOptions.PrivateDnsOnlyForInboundResolverEndpoint",
                "typed",
                "AllResolvers",
            ),
            "Tags[].Key": ("Tags[].Key", "typed", ["Name"]),
            "Tags[].Value": ("Tags[].Value", "typed", ["fixture"]),
        }
    )
    filters = [
        {"Name": "tag:Name", "Values": ["fixture"]},
        {"Name": "vpc-id", "Values": [payload["VpcId"]]},
        {"Name": "service-name", "Values": [payload["ServiceName"]]},
    ]
    ctx, fake, resource = network_resource(
        root, mapping, kind, operation, collection, payload, payload[id_prop]
    )
    fake.expected_inputs = {id_arg: [payload[id_prop]]}
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        [
            "id-selector",
            "name-or-scope-selector",
            "ambiguous",
            "access-denied",
            "missing-selector",
        ],
    )
    fake.payload = {
        **payload,
        "DnsOptions": {"PrivateDnsOnlyForInboundResolverEndpoint": True},
    }
    clear_fetch(ctx)
    response = resource.module.fetch(ctx, resource, getter)
    if (
        response["DnsOptions"]["PrivateDnsOnlyForInboundResolverEndpoint"]
        != "OnlyInboundResolver"
    ):
        raise ValueError("Inbound-only DNS projection differs")
    fake.payload = payload
    clear_fetch(ctx)
    missing_values(ctx, fake, resource, mapping, items, payload)
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".Id")
    ]
    resource.rows[:] = [
        row for row in resource.rows if ".Tags[]" not in row[1]["property"]
    ]
    resource.rows.extend(
        [
            (
                "fixture-name-key",
                {"property": kind + ".Tags[].Key", "value": "`Name`"},
            ),
            (
                "fixture-name-value",
                {"property": kind + ".Tags[].Value", "value": "`fixture`"},
            ),
        ]
    )
    for name in ("VpcId", "ServiceName"):
        if not resource.rows_for(name):
            resource.rows.append(
                (
                    "fixture-" + name,
                    {
                        "property": kind + "." + name,
                        "value": cli.model_literal(payload[name]),
                    },
                )
            )
    fake.expected_inputs = {"Filters": filters}
    network_failures(ctx, fake, resource, getter)
    return items


CONTRACTS = (
    (
        ("EC2.VPCEndpoint", "base"),
        network_fixture,
        "ec2.describe_vpc_endpoints",
        ("Id", "Tags", "VpcId", "ServiceName"),
    ),
)
