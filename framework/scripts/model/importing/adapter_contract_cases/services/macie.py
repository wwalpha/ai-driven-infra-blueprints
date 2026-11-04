"""Offline macie adapter fixtures."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from contracts.target import AWS_EXECUTION_ACCOUNT_ID_KEY
from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    ACCOUNT,
    clear_fetch,
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls, FakeCalls


class MacieSessionCalls(FakeCalls):
    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::Macie::Session", "Identifier": ACCOUNT},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": ACCOUNT,
                        "Properties": json.dumps({"AwsAccountId": ACCOUNT}),
                    }
                },
            )
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("macie2", "get_macie_session", {}):
            raise ValueError("Macie session request differs from fixture")
        return self.response(api, operation, deepcopy(self.payload))


def macie_session_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "Macie.Session"
    payload = {"status": "ENABLED", "findingPublishingFrequency": "FIFTEEN_MINUTES"}
    cases = {
        "Status": ("status", "typed", "ENABLED"),
        "FindingPublishingFrequency": (
            "findingPublishingFrequency",
            "typed",
            "FIFTEEN_MINUTES",
        ),
    }
    ctx, fake = fixture_context(root, "macie", MacieSessionCalls, payload)
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("macie")
    record = source.cloud_record(
        "macie",
        kind,
        {"Identifier": ACCOUNT, "Properties": json.dumps({"AwsAccountId": ACCOUNT})},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "macie", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "access-denied", "execution-account"],
    )
    if fake.calls != [("macie2", "get_macie_session", {})]:
        raise ValueError("Macie session request differs from fixture")
    missing_values(ctx, fake, resource, mapping, items, payload)
    ctx.target[AWS_EXECUTION_ACCOUNT_ID_KEY] = "999999999999"
    if (
        resource.module.fetch(ctx, resource, "session").get("AwsAccountId")
        != "999999999999"
    ):
        raise ValueError("Macie session execution account was not preserved")
    ctx.target.pop(AWS_EXECUTION_ACCOUNT_ID_KEY)
    fake.error = cli.comparator().AcquisitionError(
        "macie2.get_macie_session", "AccessDenied"
    )
    clear_fetch(ctx)
    try:
        mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("Macie session failure was changed") from error
    else:
        raise ValueError("Macie session failure was swallowed")
    return items


class MacieJobCalls(DirectCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        expected = {
            "filterCriteria": {
                "includes": [{"key": "name", "comparator": "EQ", "values": ["fixture"]}]
            }
        }
        if (api, operation) != ("macie2", "list_classification_jobs") or inputs not in (
            {},
            expected,
        ):
            raise ValueError("Classification job selector differs")
        return self.response(
            api,
            operation,
            {
                "items": [{"jobId": self.payload["jobId"], "name": "fixture"}]
                * (2 if self.duplicate else 1)
            },
        )


def macie_job_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    payload = {
        "jobId": "12345678123412341234123456789012",
        "name": "fixture",
        "jobType": "SCHEDULED",
        "initialRun": True,
        "managedDataIdentifierIds": ["fixture"],
        "managedDataIdentifierSelector": "ALL",
        "samplingPercentage": 50,
        "s3JobDefinition": {
            "bucketDefinitions": [{"accountId": ACCOUNT, "buckets": ["fixture-bucket"]}]
        },
        "scheduleFrequency": {"dailySchedule": {}},
    }
    ctx, fake = fixture_context(root, "macie", MacieJobCalls, payload)
    fake.api, fake.operation, fake.envelope, fake.inputs = (
        "macie2",
        "describe_classification_job",
        "$",
        {"jobId": payload["jobId"]},
    )
    record = inventory.adapter_inventory(ctx, "macie", ("Macie.ClassificationJob",))[0]
    resource = fixture_resource(root, ctx, "macie", record)
    cases = {
        name: (
            name,
            "set"
            if name == "managedDataIdentifierIds"
            else "json"
            if name == "s3JobDefinition"
            else "typed",
            value,
        )
        for name, value in payload.items()
    }
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "Macie.ClassificationJob",
        cases,
        [
            "id-selector",
            "name-selector",
            "ambiguous",
            "missing-selector",
            "access-denied",
        ],
    )
    missing_values(ctx, fake, resource, mapping, items, payload)
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".jobId")
    ]
    resource.module.fetch(ctx, resource, "job")
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, "job")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous classification jobs were accepted")
    fake.duplicate = False
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "macie2.describe_classification_job",
        "name",
    )
    return items


CONTRACTS = (
    (
        ("Macie.ClassificationJob", "job"),
        macie_job_fixture,
        "macie2.describe_classification_job",
        ("jobId", "name"),
        ("macie2.list_classification_jobs",),
    ),
    (
        ("Macie.Session", "session"),
        macie_session_fixture,
        "macie2.get_macie_session",
        (),
    ),
)
