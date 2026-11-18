"""Offline guardduty adapter fixtures."""

import json
from pathlib import Path
from typing import Any

from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    fixture_context,
    fixture_properties,
    fixture_resource,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls


class GuardDutyCalls(DirectCalls):
    empty = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        detector = self.operation == "get_detector"
        if (api, operation, inputs) != (
            "guardduty",
            "list_detectors" if detector else "list_malware_protection_plans",
            {},
        ):
            raise ValueError("GuardDuty inventory scope differs")
        values = (
            [self.identifier]
            if detector
            else [{"MalwareProtectionPlanId": self.identifier}]
        )
        return self.response(
            api,
            operation,
            {
                "DetectorIds" if detector else "MalwareProtectionPlans": []
                if self.empty
                else values * (2 if self.duplicate else 1)
            },
        )


def guardduty_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    detector = kind == "GuardDuty.Detector"
    ident = "12345678123412341234123456789012"
    getter, operation, argument, selector = (
        ("detector", "get_detector", "DetectorId", "Id")
        if detector
        else (
            "plan",
            "get_malware_protection_plan",
            "MalwareProtectionPlanId",
            "MalwareProtectionPlanId",
        )
    )
    if detector:
        payload = {
            "CreatedAt": "2026-01-01T00:00:00Z",
            "UpdatedAt": "2026-01-01T00:00:00Z",
            "ServiceRole": "arn:aws:iam::123456789012:role/fixture",
            "Status": "ENABLED",
            "FindingPublishingFrequency": "SIX_HOURS",
            "Features": [{"Name": "S3_DATA_EVENTS", "Status": "ENABLED"}],
            "DataSources": {
                "S3Logs": {"Status": "ENABLED"},
                "Kubernetes": {"AuditLogs": {"Status": "ENABLED"}},
                "MalwareProtection": {
                    "ScanEc2InstanceWithFindings": {"EbsVolumes": {"Status": "ENABLED"}}
                },
            },
        }
        cases = {
            "Id": ("DetectorId", "typed", ident),
            "Enable": ("Enabled", "typed", True),
            "FindingPublishingFrequency": (
                "FindingPublishingFrequency",
                "typed",
                "SIX_HOURS",
            ),
            "Features[].Name": ("Features[].Name", "typed", ["S3_DATA_EVENTS"]),
            "Features[].Status": ("Features[].Status", "typed", ["ENABLED"]),
        }
        for name in (
            "DataSources.S3Logs.Enable",
            "DataSources.Kubernetes.AuditLogs.Enable",
            "DataSources.MalwareProtection.ScanEc2InstanceWithFindings.EbsVolumes",
        ):
            cases[name] = (name, "typed", True)
    else:
        payload = {
            "Role": "arn:aws:iam::123456789012:role/fixture",
            "ProtectedResource": {
                "S3Bucket": {
                    "BucketName": "fixture-bucket",
                    "ObjectPrefixes": ["incoming/"],
                }
            },
            "Actions": {"Tagging": {"Status": "ENABLED"}},
        }
        cases = {
            "MalwareProtectionPlanId": ("MalwareProtectionPlanId", "typed", ident),
            "Role": ("Role", "arn", payload["Role"]),
            "ProtectedResource.S3Bucket.BucketName": (
                "ProtectedResource.S3Bucket.BucketName",
                "name",
                "fixture-bucket",
            ),
            "ProtectedResource.S3Bucket.ObjectPrefixes[]": (
                "ProtectedResource.S3Bucket.ObjectPrefixes[]",
                "typed",
                ["incoming/"],
            ),
            "Actions.Tagging.Status": ("Actions.Tagging.Status", "typed", "ENABLED"),
        }
    if detector:
        payload["DataSources"].update(
            {
                name: {"Status": "ENABLED"}
                for name in ("CloudTrail", "DNSLogs", "FlowLogs")
            }
        )
    ctx, fake = fixture_context(root, "guardduty", GuardDutyCalls, payload)
    fake.api, fake.operation, fake.inputs, fake.envelope = (
        "guardduty",
        operation,
        {argument: ident},
        "$",
    )
    fake.typename, fake.identifier, fake.cloud_properties = (
        "AWS::" + kind.replace(".", "::"),
        ident,
        {selector: ident, **({} if detector else payload)},
    )
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("guardduty")
    record = source.cloud_record(
        "guardduty",
        kind,
        {"Identifier": ident, "Properties": json.dumps(fake.cloud_properties)},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "guardduty", record)
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        [
            "id-selector",
            "inventory-selector",
            "ambiguous",
            "absent-resource",
            "access-denied",
        ],
    )
    if detector:
        fake.payload = {
            **payload,
            "Status": "DISABLED",
            "DataSources": {
                "S3Logs": {"Status": "DISABLED"},
                "Kubernetes": {"AuditLogs": {"Status": "DISABLED"}},
                "MalwareProtection": {
                    "ScanEc2InstanceWithFindings": {
                        "EbsVolumes": {"Status": "DISABLED"}
                    }
                },
            },
        }
        fake.payload["DataSources"].update(
            {
                name: {"Status": "DISABLED"}
                for name in ("CloudTrail", "DNSLogs", "FlowLogs")
            }
        )
        response = resource.module.fetch(ctx, resource, getter)
        for path in (
            "Enabled",
            "DataSources.S3Logs.Enable",
            "DataSources.Kubernetes.AuditLogs.Enable",
            "DataSources.MalwareProtection.ScanEc2InstanceWithFindings.EbsVolumes",
        ):
            if cli.comparator().select(response, path) is not False:
                raise ValueError("Disabled GuardDuty status was not false")
        fake.payload = payload
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("disabled-status")
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith("." + selector)
    ]
    resource.module.fetch(ctx, resource, getter)
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous GuardDuty resources were accepted")
    fake.duplicate = False
    fake.empty = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("Absent GuardDuty resource was accepted")
    fake.empty = False
    fake.error = cli.comparator().AcquisitionError(
        "guardduty." + operation, "AccessDenied"
    )
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("GuardDuty failure was swallowed")
    return items


CONTRACTS = (
    (
        ("GuardDuty.Detector", "detector"),
        guardduty_fixture,
        "guardduty.get_detector",
        ("Id",),
        ("guardduty.list_detectors",),
    ),
    (
        ("GuardDuty.MalwareProtectionPlan", "plan"),
        guardduty_fixture,
        "guardduty.get_malware_protection_plan",
        ("MalwareProtectionPlanId", "ProtectedResource.S3Bucket.BucketName"),
        ("guardduty.list_malware_protection_plans",),
    ),
)
