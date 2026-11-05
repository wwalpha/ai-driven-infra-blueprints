"""Offline ec2 adapter fixtures."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    fixture_context,
    fixture_properties,
    fixture_resource,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls


class InstanceCalls(DirectCalls):
    missing_volume = False
    volume_error = False
    volume = {
        "VolumeId": "vol-12345678",
        "Size": 30,
        "Encrypted": True,
        "KmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
        "VolumeType": "gp3",
    }

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if api != "ec2":
            raise ValueError("Instance API differs")
        if operation == "describe_volumes" and inputs == {
            "VolumeIds": ["vol-12345678"]
        }:
            if self.volume_error:
                raise cli.comparator().AcquisitionError(
                    "ec2.describe_volumes", "AccessDenied"
                )
            return self.response(
                api,
                operation,
                {"Volumes": [] if self.missing_volume else [deepcopy(self.volume)]},
            )
        allowed = [
            {"InstanceIds": ["i-12345678"]},
            {
                "Filters": [
                    {"Name": "tag:Name", "Values": ["fixture"]},
                    {"Name": "subnet-id", "Values": ["subnet-12345678"]},
                    {
                        "Name": "instance-state-name",
                        "Values": ["pending", "running", "stopping", "stopped"],
                    },
                ]
            },
        ]
        if operation != "describe_instances" or inputs not in allowed:
            raise ValueError("Instance selector or lifecycle scope differs")
        return self.response(
            api,
            operation,
            {
                "Reservations": [
                    {
                        "Instances": [deepcopy(self.payload)]
                        * (2 if self.duplicate else 1)
                    }
                ]
            },
        )


def instance_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    payload = {
        "InstanceId": "i-12345678",
        "ImageId": "ami-12345678",
        "InstanceType": "t3.micro",
        "SubnetId": "subnet-12345678",
        "Placement": {"AvailabilityZone": "ap-northeast-1a"},
        "IamInstanceProfile": {
            "Arn": "arn:aws:iam::123456789012:instance-profile/fixture"
        },
        "SecurityGroups": [{"GroupId": "sg-12345678"}],
        "Tags": [{"Key": "Name", "Value": "fixture"}],
        "BlockDeviceMappings": [
            {
                "DeviceName": "/dev/xvda",
                "Ebs": {"VolumeId": "vol-12345678", "DeleteOnTermination": True},
            }
        ],
    }
    ctx, fake = fixture_context(root, "ec2", InstanceCalls, payload)
    fake.typename, fake.identifier, fake.cloud_properties = (
        "AWS::EC2::Instance",
        "i-12345678",
        {"InstanceId": "i-12345678"},
    )
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("ec2")
    record = source.cloud_record(
        "ec2",
        "EC2.Instance",
        {
            "Identifier": fake.identifier,
            "Properties": json.dumps(fake.cloud_properties),
        },
        source.schema("EC2.Instance"),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "ec2", record)
    getter = mapping.properties[properties[0]].field.getter
    cases = {
        name: (name, "id" if name == "SubnetId" else "typed", payload[name])
        for name in ("InstanceId", "ImageId", "InstanceType", "SubnetId")
    }
    cases.update(
        {
            "IamInstanceProfile": (
                "IamInstanceProfile.Arn",
                "arn",
                payload["IamInstanceProfile"]["Arn"],
            ),
            "SecurityGroupIds": ("SecurityGroups[].GroupId", "id", ["sg-12345678"]),
            "Tags[].Key": ("Tags[].Key", "typed", ["Name"]),
            "Tags[].Value": ("Tags[].Value", "typed", ["fixture"]),
            "BlockDeviceMappings[].DeviceName": (
                "BlockDeviceMappings[].DeviceName",
                "typed",
                ["/dev/xvda"],
            ),
            "BlockDeviceMappings[].Ebs.DeleteOnTermination": (
                "BlockDeviceMappings[].Ebs.DeleteOnTermination",
                "typed",
                [True],
            ),
        }
    )
    for name, value in fake.volume.items():
        if name != "VolumeId":
            path = "BlockDeviceMappings[].Ebs." + (
                "VolumeSize" if name == "Size" else name
            )
            cases[path] = (path, "kms" if name == "KmsKeyId" else "typed", [value])
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "EC2.Instance",
        cases,
        [
            "id-selector",
            "name-tag-selector",
            "subnet-scope",
            "ambiguous",
            "access-denied",
            "missing-selector",
        ],
    )
    if getter == "volumes":
        for mode in ("missing-volume", "volume-error"):
            fake.missing_volume, fake.volume_error = (
                mode == "missing-volume",
                mode == "volume-error",
            )
            try:
                resource.module.fetch(ctx, resource, getter)
            except cli.comparator().AcquisitionError as error:
                if error.code != (
                    "AttachedVolumeMissing" if fake.missing_volume else "AccessDenied"
                ):
                    raise ValueError("Volume failure classification differs") from error
            else:
                raise ValueError("Failed volume acquisition was accepted")
        fake.missing_volume = fake.volume_error = False
        for entries in ([], [{"DeviceName": "/dev/sdb"}]):
            fake.payload = {**payload, "BlockDeviceMappings": entries}
            if (
                resource.module.fetch(ctx, resource, getter)["BlockDeviceMappings"]
                != entries
            ):
                raise ValueError("Non-EBS/no-volume mappings were changed")
        fake.payload = payload
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].extend(
                    [
                        "ebs-volume",
                        "non-ebs",
                        "no-volumes",
                        "attached-volume-missing",
                        "volume-access-denied",
                    ]
                )
    else:
        missing_values(ctx, fake, resource, mapping, items, payload)
    resource.rows[:] = [
        row
        for row in resource.rows
        if not row[1]["property"].endswith(".InstanceId")
        and ".Tags[]" not in row[1]["property"]
    ]
    resource.rows.extend(
        [
            (
                "fixture-tag-key",
                {"property": "EC2.Instance.Tags[].Key", "value": "`Name`"},
            ),
            (
                "fixture-tag-value",
                {"property": "EC2.Instance.Tags[].Value", "value": "`fixture`"},
            ),
        ]
    )
    if not resource.rows_for("SubnetId"):
        resource.rows.append(
            (
                "fixture-subnet",
                {"property": "EC2.Instance.SubnetId", "value": "`subnet-12345678`"},
            )
        )
    resource.module.fetch(ctx, resource, getter)
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous instances were accepted")
    fake.duplicate = False
    fake.error = cli.comparator().AcquisitionError(
        "ec2.describe_instances", "AccessDenied"
    )
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("Instance API failure was swallowed")
    fake.error = None
    resource.rows[:] = []
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing instance identity was accepted")
    return items


CONTRACTS = (
    (
        ("EC2.Instance", "base"),
        instance_fixture,
        "ec2.describe_instances",
        ("InstanceId", "Tags", "SubnetId"),
    ),
    (
        ("EC2.Instance", "volumes"),
        instance_fixture,
        "ec2.describe_volumes",
        ("InstanceId", "Tags", "SubnetId"),
        ("ec2.describe_instances",),
    ),
)
