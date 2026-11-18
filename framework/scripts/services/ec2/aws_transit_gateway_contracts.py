"""Offline transit-gateway adapter fixtures."""

from pathlib import Path
from typing import Any

from model.importing.adapter_contract_cases.core import (
    fixture_properties,
    missing_values,
    network_failures,
    network_resource,
)


def network_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = "EC2.TransitGatewayVpcAttachment"
    getter = mapping.properties[properties[0]].field.getter
    operation, collection, id_arg, id_prop = (
        "describe_transit_gateway_vpc_attachments",
        "TransitGatewayVpcAttachments",
        "TransitGatewayAttachmentIds",
        "TransitGatewayAttachmentId",
    )
    payload = {
        "TransitGatewayAttachmentId": "tgw-attach-12345678",
        "TransitGatewayId": "tgw-12345678",
        "VpcId": "vpc-12345678",
        "SubnetIds": ["subnet-12345678"],
    }
    cases = {
        name: (name, "typed" if name == "TransitGatewayId" else "id", value)
        for name, value in payload.items()
        if name != id_prop
    }
    cases["Id"] = (id_prop, "typed", payload[id_prop])
    filters = [
        {"Name": "vpc-id", "Values": [payload["VpcId"]]},
        {"Name": "transit-gateway-id", "Values": [payload["TransitGatewayId"]]},
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
    missing_values(ctx, fake, resource, mapping, items, payload)
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".Id")
    ]
    fake.expected_inputs = {"Filters": filters}
    network_failures(ctx, fake, resource, getter)
    return items


CONTRACTS = (
    (
        ("EC2.TransitGatewayVpcAttachment", "base"),
        network_fixture,
        "ec2.describe_transit_gateway_vpc_attachments",
        ("Id", "VpcId", "TransitGatewayId"),
    ),
)
