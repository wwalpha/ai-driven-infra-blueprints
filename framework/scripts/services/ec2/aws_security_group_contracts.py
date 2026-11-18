"""Offline security-group adapter fixtures."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    bind_fixture_parent,
    clear_fetch,
    fixture_context,
    fixture_properties,
    fixture_resource,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls


class SecurityGroupCalls(DirectCalls):
    group: dict[str, Any] = {}
    expected_rules: dict[str, Any] = {}
    wrong_group = False
    wrong_direction = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if api != "ec2":
            raise ValueError("Security group API differs")
        if operation == "describe_security_groups":
            if inputs not in (
                {"GroupIds": ["sg-12345678"]},
                {
                    "Filters": [
                        {"Name": "group-name", "Values": ["fixture"]},
                        {"Name": "vpc-id", "Values": ["vpc-12345678"]},
                    ]
                },
            ):
                raise ValueError("Security group name/VPC scope differs")
            return self.response(
                api,
                operation,
                {
                    "SecurityGroups": [deepcopy(self.group)]
                    * (2 if self.duplicate else 1)
                },
            )
        if (
            operation != "describe_security_group_rules"
            or inputs != self.expected_rules
        ):
            raise ValueError("Rule ID/group scope differs")
        rule = deepcopy(self.payload)
        if self.wrong_group:
            rule["GroupId"] = "sg-87654321"
        if self.wrong_direction:
            rule["IsEgress"] = not rule["IsEgress"]
        return self.response(
            api,
            operation,
            {"SecurityGroupRules": [rule] * (2 if self.duplicate else 1)},
        )


def security_group_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    grouped = kind != "EC2.SecurityGroup"
    group = {
        "GroupId": "sg-12345678",
        "GroupName": "fixture",
        "Description": "fixture group",
        "VpcId": "vpc-12345678",
        "Tags": [{"Key": "Name", "Value": "fixture"}],
    }
    permission = {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443}
    rule = {
        "SecurityGroupRuleId": "sgr-12345678",
        "GroupId": group["GroupId"],
        "IsEgress": kind.endswith("Egress"),
        "IpProtocol": "tcp",
        "FromPort": 443,
        "ToPort": 443,
        "Description": "fixture rule",
    }
    ctx, fake = fixture_context(root, "security-group", SecurityGroupCalls, rule)
    fake.group = group
    fake.typename, fake.identifier, fake.cloud_properties = (
        "AWS::" + kind.replace(".", "::"),
        rule["SecurityGroupRuleId"] if grouped else group["GroupId"],
        {
            "Id": rule["SecurityGroupRuleId"] if grouped else group["GroupId"],
            "GroupId": group["GroupId"],
            "GroupName": "fixture",
            "VpcId": group["VpcId"],
        },
    )
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("security-group")
    record = source.cloud_record(
        "security-group",
        kind,
        {
            "Identifier": fake.identifier,
            "Properties": json.dumps(fake.cloud_properties),
        },
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "security-group", record)
    if grouped:
        parent = cli.selector_resource(
            resource.model,
            "parent",
            {"kind": "EC2.SecurityGroup", "getters": {"group": group}},
            mapped,
        )
        bind_fixture_parent(resource, parent, "GroupId")
        resource.model._anchor_resources = {
            "parent": [("parent", {"anchor": "parent"})]
        }
        resource.model.resources = [parent, resource]
        ctx.models[resource.model.path.resolve()] = resource.model
    items = {}
    for reference in (False, True):
        clear_fetch(ctx)
        if grouped:
            fake.payload = {
                **rule,
                **(
                    {"ReferencedGroupInfo": {"GroupId": "sg-87654321"}}
                    if reference
                    else {"CidrIpv4": "10.0.0.0/24"}
                ),
            }
            fake.expected_rules = {
                "SecurityGroupRuleIds": [rule["SecurityGroupRuleId"]]
            }
            cases = {
                "Id": ("SecurityGroupRuleId", "typed", rule["SecurityGroupRuleId"]),
                "Description": ("Description", "typed", "fixture rule"),
                "FromPort": ("FromPort", "typed", 443),
                "ToPort": ("ToPort", "typed", 443),
                "IpProtocol": ("IpProtocol", "protocol", "tcp"),
            }
            name = (
                "DestinationSecurityGroupId"
                if rule["IsEgress"]
                else "SourceSecurityGroupId"
            )
            cases[name if reference else "CidrIp"] = (
                "ReferencedGroupInfo.GroupId" if reference else "CidrIpv4",
                "id" if reference else "typed",
                "sg-87654321" if reference else "10.0.0.0/24",
            )
        else:
            entry = {
                **permission,
                **(
                    {
                        "UserIdGroupPairs": [
                            {"GroupId": "sg-87654321", "Description": "fixture rule"}
                        ]
                    }
                    if reference
                    else {
                        "IpRanges": [
                            {"CidrIp": "10.0.0.0/24", "Description": "fixture rule"}
                        ]
                    }
                ),
            }
            fake.group = {
                **group,
                "IpPermissions": [entry],
                "IpPermissionsEgress": [entry],
            }
            cases = {
                "Id": ("GroupId", "typed", group["GroupId"]),
                "GroupName": ("GroupName", "typed", "fixture"),
                "GroupDescription": ("Description", "typed", "fixture group"),
                "VpcId": ("VpcId", "id", group["VpcId"]),
                "Tags[].Key": ("Tags[].Key", "typed", ["Name"]),
                "Tags[].Value": ("Tags[].Value", "typed", ["fixture"]),
            }
            for direction in ("SecurityGroupIngress", "SecurityGroupEgress"):
                for name, value in {
                    "Description": "fixture rule",
                    "FromPort": 443,
                    "ToPort": 443,
                    "IpProtocol": "tcp",
                }.items():
                    path = direction + "[]." + name
                    cases[path] = (
                        path,
                        "protocol" if name == "IpProtocol" else "typed",
                        [value],
                    )
                name = (
                    (
                        "DestinationSecurityGroupId"
                        if direction.endswith("Egress")
                        else "SourceSecurityGroupId"
                    )
                    if reference
                    else "CidrIp"
                )
                path = direction + "[]." + name
                cases[path] = (
                    path,
                    "id" if reference else "typed",
                    ["sg-87654321" if reference else "10.0.0.0/24"],
                )
        result = fixture_properties(
            ctx,
            resource,
            mapping,
            properties,
            kind,
            cases,
            [
                "security-group-reference" if reference else "ipv4-cidr",
                "id-selector",
                "property-selector",
                "ambiguous",
                "access-denied",
            ],
        )
        for key, item in result.items():
            if key not in items or item["status"] == "verified":
                items[key] = item
        saved_rows = deepcopy(resource.rows)
        resource.rows[:] = []
        if grouped:
            fake.expected_rules = {
                "Filters": [{"Name": "group-id", "Values": [group["GroupId"]]}]
            }
            for name, case in cases.items():
                if name != "Id":
                    resource.rows.append(
                        (
                            "fixture-" + name,
                            {
                                "property": kind + "." + name,
                                "value": cli.model_literal(case[2]),
                            },
                        )
                    )
        else:
            resource.rows.extend(
                [
                    (
                        "fixture-group",
                        {"property": kind + ".GroupName", "value": "`fixture`"},
                    ),
                    (
                        "fixture-vpc",
                        {"property": kind + ".VpcId", "value": "`vpc-12345678`"},
                    ),
                ]
            )
        resource.module.fetch(ctx, resource, "rule" if grouped else "group")
        resource.rows[:] = saved_rows
    getter = "rule" if grouped else "group"
    if grouped:
        fake.expected_rules = {"SecurityGroupRuleIds": [rule["SecurityGroupRuleId"]]}
        for mismatch in ("wrong_group", "wrong_direction"):
            setattr(fake, mismatch, True)
            try:
                resource.module.fetch(ctx, resource, getter)
            except (cli.comparator().AcquisitionError, cli.comparator().Unresolved):
                pass
            else:
                raise ValueError("Rule parent/direction mismatch was accepted")
            setattr(fake, mismatch, False)
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous security group selection was accepted")
    fake.duplicate = False
    fake.error = cli.comparator().AcquisitionError("ec2", "AccessDenied")
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("Security group failure was swallowed")
    fake.error = None
    if grouped:
        resource.spec.pop("parentReference")
    else:
        resource.rows[:] = []
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing security group selector was accepted")
    return items


CONTRACTS = (
    (
        ("EC2.SecurityGroup", "group"),
        security_group_fixture,
        "ec2.describe_security_groups",
        ("Id", "GroupName", "VpcId"),
    ),
    (
        ("EC2.SecurityGroupIngress", "rule"),
        security_group_fixture,
        "ec2.describe_security_group_rules",
        ("Id", "parent", "properties"),
        ("ec2.describe_security_groups",),
    ),
    (
        ("EC2.SecurityGroupEgress", "rule"),
        security_group_fixture,
        "ec2.describe_security_group_rules",
        ("Id", "parent", "properties"),
        ("ec2.describe_security_groups",),
    ),
)
