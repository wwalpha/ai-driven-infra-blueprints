"""Offline config adapter fixtures."""

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
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class ConfigCalls(FakeCalls):
    operation = ""
    collection = ""
    selector = ""
    duplicate = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        return self.retrieve(api, operation, inputs, {})

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        return self.retrieve(api, operation, inputs, {self.selector: ["fixture"]})

    def retrieve(
        self, api: str, operation: str, inputs: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("config", self.operation, expected):
            raise ValueError("Config selector differs from fixture")
        return self.response(
            api,
            operation,
            {self.collection: [deepcopy(self.payload)] * (2 if self.duplicate else 1)},
        )


def config_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    if kind == "Config.ConfigurationRecorder":
        operation, collection, selector = (
            "describe_configuration_recorders",
            "ConfigurationRecorders",
            "ConfigurationRecorderNames",
        )
        payload = {
            "name": "fixture",
            "roleARN": "arn:aws:iam::123456789012:role/fixture",
            "recordingGroup": {
                "allSupported": True,
                "includeGlobalResourceTypes": True,
                "resourceTypes": [],
                "exclusionByResourceTypes": {"resourceTypes": []},
                "recordingStrategy": {"useOnly": "ALL_SUPPORTED_RESOURCE_TYPES"},
            },
            "recordingMode": {"recordingFrequency": "CONTINUOUS"},
        }
        cases = {
            "Name": ("name", "typed", "fixture"),
            "Id": ("name", "typed", "fixture"),
            "RoleARN": ("roleARN", "iam_role", payload["roleARN"]),
            "RecordingGroup.AllSupported": (
                "recordingGroup.allSupported",
                "typed",
                True,
            ),
            "RecordingGroup.IncludeGlobalResourceTypes": (
                "recordingGroup.includeGlobalResourceTypes",
                "typed",
                True,
            ),
            "RecordingGroup.ResourceTypes": (
                "recordingGroup.resourceTypes",
                "set",
                [],
            ),
            "RecordingGroup.ExclusionByResourceTypes.ResourceTypes": (
                "recordingGroup.exclusionByResourceTypes.resourceTypes",
                "set",
                [],
            ),
            "RecordingGroup.RecordingStrategy.UseOnly": (
                "recordingGroup.recordingStrategy.useOnly",
                "typed",
                "ALL_SUPPORTED_RESOURCE_TYPES",
            ),
            "RecordingMode.RecordingFrequency": (
                "recordingMode.recordingFrequency",
                "typed",
                "CONTINUOUS",
            ),
        }
    else:
        operation, collection, selector = (
            "describe_delivery_channels",
            "DeliveryChannels",
            "DeliveryChannelNames",
        )
        payload = {"name": "fixture", "s3BucketName": "fixture-bucket"}
        cases = {
            "Name": ("name", "typed", "fixture"),
            "S3BucketName": ("s3BucketName", "name", "fixture-bucket"),
        }
    ctx, fake = fixture_context(root, "config", ConfigCalls, payload)
    fake.operation, fake.collection, fake.selector = operation, collection, selector
    record = inventory.adapter_inventory(ctx, "config", (kind,))[0]
    resource = fixture_resource(root, ctx, "config", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied", "ambiguous"],
    )
    if fake.calls != [("config", operation, {selector: ["fixture"]})]:
        raise ValueError("Config request differs from fixture")
    if kind == "Config.ConfigurationRecorder":
        for property_name, strategy, types in (
            (
                "RecordingGroup.ResourceTypes",
                "INCLUSION_BY_RESOURCE_TYPES",
                ["AWS::S3::Bucket"],
            ),
            (
                "RecordingGroup.ExclusionByResourceTypes.ResourceTypes",
                "EXCLUSION_BY_RESOURCE_TYPES",
                ["AWS::EC2::Instance"],
            ),
        ):
            key = kind + "." + property_name
            if key not in items or items[key]["status"] != "verified":
                continue
            group = {
                "allSupported": False,
                "includeGlobalResourceTypes": False,
                "recordingStrategy": {"useOnly": strategy},
            }
            if strategy == "INCLUSION_BY_RESOURCE_TYPES":
                group["resourceTypes"] = types
            else:
                group["exclusionByResourceTypes"] = {"resourceTypes": types}
            fake.payload = {**payload, "recordingGroup": group}
            clear_fetch(ctx)
            _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
            import_normalize(ctx, kind, key, raw)
            if cli.comparator().normalize(ctx, raw, "set") != types:
                items[key] = {
                    "status": "broken",
                    "reason": "Config recording strategy result differs from fixture",
                }
            else:
                items[key]["branches"].append(strategy)
        fake.payload = payload
        clear_fetch(ctx)
    missing_values(ctx, fake, resource, mapping, items, payload, required=("name",))
    fake.duplicate = True
    try:
        resource.module.fetch(
            ctx,
            resource,
            "recorder" if kind.endswith("ConfigurationRecorder") else "channel",
        )
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous Config inventory was accepted")
    fake.duplicate = False
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "config." + operation, "Name"
    )
    return items


CONTRACTS = (
    (
        ("Config.ConfigurationRecorder", "recorder"),
        config_fixture,
        "config.describe_configuration_recorders",
        ("Name",),
    ),
    (
        ("Config.DeliveryChannel", "channel"),
        config_fixture,
        "config.describe_delivery_channels",
        ("Name",),
    ),
)
