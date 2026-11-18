"""Offline vpc adapter fixtures."""

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
    missing_values,
    network_failures,
    network_resource,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class SubnetCalls(FakeCalls):
    def __init__(self, ctx: Any, payload: dict[str, Any]) -> None:
        super().__init__(ctx, payload)
        self.duplicate = False
        self.route_table = "RouteTableId" in payload

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        route_table = self.route_table
        op = "describe_route_tables" if route_table else "describe_subnets"
        collection = "RouteTables" if route_table else "Subnets"
        id_arg = "RouteTableIds" if route_table else "SubnetIds"
        id_value = "rtb-123" if route_table else "subnet-123"
        allowed = [
            {},
            {id_arg: [id_value]},
            {"Filters": [{"Name": "tag:Name", "Values": ["fixture"]}]},
            {
                "Filters": [
                    {"Name": "tag:Name", "Values": ["fixture"]},
                    {"Name": "vpc-id", "Values": ["vpc-123"]},
                ]
            },
        ]
        if (api, operation) != ("ec2", op) or inputs not in allowed:
            raise ValueError("Network selector differs from fixture")
        return self.response(
            api,
            operation,
            {collection: [deepcopy(self.payload)] * (2 if self.duplicate else 1)},
        )


class AssociationCalls(SubnetCalls):
    state = "associated"

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        if operation != "describe_route_tables":
            return super().pages(api, operation, **inputs)
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if api != "ec2" or inputs not in (
            {},
            {"Filters": [{"Name": "association.subnet-id", "Values": ["subnet-123"]}]},
        ):
            raise ValueError("Association subnet scope differs")
        record = {
            "RouteTableId": "rtb-12345678",
            "Associations": [
                {
                    "RouteTableAssociationId": "rtbassoc-12345678",
                    "SubnetId": "subnet-123",
                    "AssociationState": {"State": self.state},
                }
            ],
        }
        return self.response(
            api, operation, {"RouteTables": [record] * (2 if self.duplicate else 1)}
        )


def association_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    payload = {
        "SubnetId": "subnet-123",
        "VpcId": "vpc-123",
        "Tags": [{"Key": "Name", "Value": "fixture"}],
    }
    ctx, fake = fixture_context(root, "vpc", AssociationCalls, payload)
    record = inventory.inventory_for(ctx).discover("vpc", ("EC2.Subnet",))[0]
    resource = fixture_resource(root, ctx, "vpc", record)
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "EC2.SubnetRouteTableAssociation",
        {"RouteTableId": ("RouteTableId", "id", "rtb-12345678")},
        [
            "subnet-identity",
            "associated",
            "disassociating",
            "ambiguous",
            "access-denied",
            "missing-selector",
        ],
    )
    for state in ("associating", "disassociating", "disassociated", "failed"):
        fake.state = state
        try:
            resource.module.fetch(ctx, resource, "association")
        except cli.comparator().AcquisitionError:
            pass
        else:
            raise ValueError("Unconfirmed association state was accepted")
    fake.state = "associated"
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, "association")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous route associations were accepted")
    fake.duplicate = False
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".SubnetId")
    ]
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "ec2.describe_route_tables", "Name"
    )
    return items


class VPCCalls(FakeCalls):
    duplicate = False
    missing_attribute = False
    failure_operation = ""

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        allowed = [
            {},
            {"VpcIds": ["vpc-12345678"]},
            {"Filters": [{"Name": "tag:Name", "Values": ["fixture-vpc"]}]},
        ]
        if (api, operation) != ("ec2", "describe_vpcs") or inputs not in allowed:
            raise ValueError("VPC selector differs from fixture")
        return self.response(
            api,
            operation,
            {"Vpcs": [deepcopy(self.payload)] * (2 if self.duplicate else 1)},
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (
            (api, operation) != ("ec2", "describe_vpc_attribute")
            or inputs.get("VpcId") != "vpc-12345678"
            or inputs.get("Attribute") not in {"enableDnsHostnames", "enableDnsSupport"}
        ):
            raise ValueError("VPC attribute selector differs from fixture")
        name = (
            "EnableDnsHostnames"
            if inputs["Attribute"] == "enableDnsHostnames"
            else "EnableDnsSupport"
        )
        return self.response(
            api,
            operation,
            {}
            if self.missing_attribute
            else {name: {"Value": True}, "VpcId": "vpc-12345678"},
        )


def vpc_network_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "EC2.VPC"
    getter = mapping.properties[properties[0]].field.getter
    payload = {
        "VpcId": "vpc-12345678",
        "CidrBlock": "10.0.0.0/16",
        "Tags": [{"Key": "Name", "Value": "fixture-vpc"}],
    }
    cases = {
        "VpcId": ("VpcId", "typed", "vpc-12345678"),
        "CidrBlock": ("CidrBlock", "typed", "10.0.0.0/16"),
        "EnableDnsHostnames": ("EnableDnsHostnames.Value", "typed", True),
        "EnableDnsSupport": ("EnableDnsSupport.Value", "typed", True),
    }
    ctx, fake = fixture_context(root, "vpc", VPCCalls, payload)
    record = inventory.adapter_inventory(ctx, "vpc", (kind,))[0]
    resource = fixture_resource(root, ctx, "vpc", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        [
            "id-selector",
            "name-selector",
            "missing-selector",
            "access-denied",
            "ambiguous",
        ],
    )
    expected = [("ec2", "describe_vpcs", {"VpcIds": ["vpc-12345678"]})]
    if getter != "base":
        attribute = (
            "enableDnsHostnames" if getter == "hostnames" else "enableDnsSupport"
        )
        expected.append(
            (
                "ec2",
                "describe_vpc_attribute",
                {"VpcId": "vpc-12345678", "Attribute": attribute},
            )
        )
    if fake.calls != expected:
        raise ValueError("VPC requests differ from fixture")
    if getter == "base":
        missing_values(ctx, fake, resource, mapping, items, payload)
    else:
        fake.missing_attribute = True
        clear_fetch(ctx)
        for key, item in items.items():
            if item["status"] != "verified":
                continue
            _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
            if raw != cli.comparator().MISSING:
                item.update(
                    status="broken", reason="Missing VPC attribute was not preserved"
                )
            else:
                item["branches"].append("missing-value")
        fake.missing_attribute = False
        fake.error = cli.comparator().AcquisitionError(
            "ec2.describe_vpc_attribute", "AccessDenied"
        )
        fake.failure_operation = "describe_vpc_attribute"
        clear_fetch(ctx)
        try:
            mapping_value(
                ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
            )
        except cli.comparator().AcquisitionError as error:
            if error.code != "AccessDenied":
                raise ValueError("VPC attribute failure was changed") from error
        else:
            raise ValueError("VPC attribute failure was swallowed")
        fake.error, fake.failure_operation = None, ""
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("attribute-access-denied")
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".VpcId")
    ]
    clear_fetch(ctx)
    fake.calls.clear()
    mapping_value(
        ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
    )
    if not fake.calls or fake.calls[0] != (
        "ec2",
        "describe_vpcs",
        {"Filters": [{"Name": "tag:Name", "Values": ["fixture-vpc"]}]},
    ):
        raise ValueError("VPC name selector differs from fixture")
    fake.duplicate = True
    clear_fetch(ctx)
    try:
        mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous VPC selector was accepted")
    fake.duplicate = False
    fake.payload = {
        **payload,
        "Tags": [
            {"Key": "Name", "Value": "fixture-vpc"},
            {"Key": "Name", "Value": "other"},
        ],
    }
    try:
        resource.module.fetch(ctx, resource, "base")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous VPC name tags were accepted")
    fake.payload = {**payload, "Tags": []}
    if (
        resource.module.fetch(ctx, resource, "base")["NameTag"]
        != cli.comparator().MISSING
    ):
        raise ValueError("Absent VPC name tag was not preserved")
    fake.payload = payload
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "ec2.describe_vpcs", "Name"
    )
    return items


def subnet_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    route_table = properties[0].startswith("EC2.RouteTable.")
    kind = "EC2.RouteTable" if route_table else "EC2.Subnet"
    op = "describe_route_tables" if route_table else "describe_subnets"
    id_prop = "RouteTableId" if route_table else "SubnetId"
    id_arg = "RouteTableIds" if route_table else "SubnetIds"
    id_value = "rtb-123" if route_table else "subnet-123"
    payload = {
        id_prop: id_value,
        "VpcId": "vpc-123",
        "Tags": [{"Key": "Name", "Value": "fixture"}],
    }
    cases = {
        id_prop: (id_prop, "typed", id_value),
        "VpcId": ("VpcId", "id", "vpc-123"),
        "AvailabilityZone": ("AvailabilityZone", "typed", "ap-northeast-1a"),
        "CidrBlock": ("CidrBlock", "typed", "10.0.0.0/24"),
        "MapPublicIpOnLaunch": ("MapPublicIpOnLaunch", "typed", False),
    }
    if not route_table:
        payload.update(
            AvailabilityZone="ap-northeast-1a",
            CidrBlock="10.0.0.0/24",
            MapPublicIpOnLaunch=False,
        )
    ctx, fake = fixture_context(root, "vpc", SubnetCalls, payload)
    record = inventory.adapter_inventory(ctx, "vpc", (kind,))[0]
    resource = fixture_resource(root, ctx, "vpc", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        [
            "id-selector",
            "name-selector",
            "vpc-filter",
            "missing-selector",
            "access-denied",
            "ambiguous",
        ],
    )
    if fake.calls != [("ec2", op, {id_arg: [id_value]})]:
        raise ValueError("Subnet ID request differs from fixture")
    missing_values(ctx, fake, resource, mapping, items, payload)
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith("." + id_prop)
    ]
    fake.calls.clear()
    resource.module.fetch(ctx, resource, "base")
    if fake.calls != [
        (
            "ec2",
            op,
            {
                "Filters": [
                    {"Name": "tag:Name", "Values": ["fixture"]},
                    {"Name": "vpc-id", "Values": ["vpc-123"]},
                ]
            },
        )
    ]:
        raise ValueError("Subnet name and VPC request differs from fixture")
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".VpcId")
    ]
    fake.calls.clear()
    resource.module.fetch(ctx, resource, "base")
    if fake.calls != [
        (
            "ec2",
            op,
            {"Filters": [{"Name": "tag:Name", "Values": ["fixture"]}]},
        )
    ]:
        raise ValueError("Subnet name request differs from fixture")
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, "base")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Duplicate subnets were accepted")
    fake.duplicate = False
    fake.payload = {
        **payload,
        "Tags": [
            {"Key": "Name", "Value": "fixture"},
            {"Key": "Name", "Value": "other"},
        ],
    }
    try:
        resource.module.fetch(ctx, resource, "base")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous subnet name tags were accepted")
    fake.payload = {**payload, "Tags": []}
    if (
        resource.module.fetch(ctx, resource, "base")["NameTag"]
        != cli.comparator().MISSING
    ):
        raise ValueError("Absent subnet name tag was not preserved")
    fake.payload = payload
    failure_branches(ctx, fake, resource, mapping, properties[0], "ec2." + op, "Name")
    return items


def network_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = "EC2.FlowLog"
    getter = mapping.properties[properties[0]].field.getter
    tags = [{"Key": "Name", "Value": "fixture"}]
    operation, collection, id_arg, id_prop = (
        "describe_flow_logs",
        "FlowLogs",
        "FlowLogIds",
        "FlowLogId",
    )
    payload = {
        "FlowLogId": "fl-12345678",
        "ResourceId": "vpc-12345678",
        "Tags": tags,
        "DeliverLogsPermissionArn": "arn:aws:iam::123456789012:role/fixture",
        "LogDestinationType": "cloud-watch-logs",
        "LogGroupName": "fixture",
        "MaxAggregationInterval": 600,
        "TrafficType": "ALL",
    }
    cases = {
        name: (
            name,
            "arn"
            if name.endswith("Arn")
            else "name"
            if name == "LogGroupName"
            else "id"
            if name == "ResourceId"
            else "typed",
            value,
        )
        for name, value in payload.items()
        if name not in {"Tags", "FlowLogId"}
    }
    cases.update(
        {
            "Id": ("FlowLogId", "typed", payload["FlowLogId"]),
            "ResourceType": ("ResourceType", "typed", "VPC"),
        }
    )
    filters = [
        {"Name": "resource-id", "Values": ["vpc-12345678"]},
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
    if getter == "resource_type":
        for prefix, expected in (("subnet-", "Subnet"), ("eni-", "NetworkInterface")):
            fake.payload = {**payload, "ResourceId": prefix + "12345678"}
            clear_fetch(ctx)
            if resource.module.fetch(ctx, resource, getter) != {
                "ResourceType": expected
            }:
                raise ValueError("Flow log resource type differs")
        fake.payload = {**payload, "ResourceId": "unknown-12345678"}
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Unknown flow log resource type was accepted")
        fake.payload = payload
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].extend(
                    ["subnet", "network-interface", "unknown-resource-type"]
                )
    else:
        missing_values(ctx, fake, resource, mapping, items, payload)
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".Id")
    ]
    fake.expected_inputs = {"Filter": filters}
    network_failures(ctx, fake, resource, getter)
    return items


CONTRACTS = (
    (
        ("EC2.FlowLog", "base"),
        network_fixture,
        "ec2.describe_flow_logs",
        ("Id", "Name", "ResourceId"),
    ),
    (
        ("EC2.FlowLog", "resource_type"),
        network_fixture,
        "ec2.describe_flow_logs",
        ("Id", "Name", "ResourceId"),
    ),
    (
        ("EC2.SubnetRouteTableAssociation", "association"),
        association_fixture,
        "ec2.describe_route_tables",
        ("SubnetId",),
        ("ec2.describe_subnets",),
    ),
    (
        ("EC2.Subnet", "base"),
        subnet_fixture,
        "ec2.describe_subnets",
        ("SubnetId", "Name", "VpcId"),
    ),
    (
        ("EC2.RouteTable", "base"),
        subnet_fixture,
        "ec2.describe_route_tables",
        ("RouteTableId", "Name", "VpcId"),
    ),
    (("EC2.VPC", "base"), vpc_network_fixture, "ec2.describe_vpcs", ("VpcId", "Name")),
    (
        ("EC2.VPC", "hostnames"),
        vpc_network_fixture,
        "ec2.describe_vpc_attribute",
        ("VpcId", "Name"),
        ("ec2.describe_vpcs",),
    ),
    (
        ("EC2.VPC", "support"),
        vpc_network_fixture,
        "ec2.describe_vpc_attribute",
        ("VpcId", "Name"),
        ("ec2.describe_vpcs",),
    ),
)
