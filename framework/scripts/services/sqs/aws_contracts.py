"""Offline sqs adapter fixtures."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from contracts.target import AWS_ACCOUNT_ID_KEY
from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    ACCOUNT,
    clear_fetch,
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class SQSCalls(FakeCalls):
    failure_operation = ""
    url = "https://sqs.ap-northeast-1.amazonaws.com/123456789012/fixture"

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::SQS::Queue", "Identifier": self.url},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": self.url,
                        "Properties": json.dumps(
                            {"QueueName": "fixture", "QueueUrl": self.url}
                        ),
                    }
                },
            )
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) == (
            "sqs",
            "get_queue_url",
            {"QueueName": "fixture", "QueueOwnerAWSAccountId": ACCOUNT},
        ):
            return self.response(api, operation, {"QueueUrl": self.url})
        if (api, operation, inputs) == (
            "sqs",
            "get_queue_attributes",
            {"QueueUrl": self.url, "AttributeNames": ["All"]},
        ):
            return self.response(api, operation, {"Attributes": deepcopy(self.payload)})
        raise ValueError("SQS request differs from fixture")


class SQSPolicyCalls(FakeCalls):
    url = "https://sqs.ap-northeast-1.amazonaws.com/123456789012/fixture"
    second_url = "https://sqs.ap-northeast-1.amazonaws.com/123456789012/second"
    missing = False
    different = False

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::SQS::Queue", "Identifier": self.url},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": self.url,
                        "Properties": json.dumps(
                            {"QueueName": "fixture", "QueueUrl": self.url}
                        ),
                    }
                },
            )
        if self.error:
            raise self.error
        if (
            api != "sqs"
            or operation != "get_queue_attributes"
            or inputs.get("AttributeNames") != ["Policy"]
            or inputs.get("QueueUrl") not in {self.url, self.second_url}
        ):
            raise ValueError("SQS policy request differs from fixture")
        if self.missing:
            return self.response(api, operation, {})
        document = {"Version": "2012-10-17", "Statement": []}
        if self.different and inputs["QueueUrl"] == self.second_url:
            document["Statement"] = [
                {
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "sqs:SendMessage",
                    "Resource": "*",
                }
            ]
        return self.response(
            api, operation, {"Attributes": {"Policy": json.dumps(document)}}
        )


def sqs_policy_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "SQS.QueuePolicy"
    ctx, fake = fixture_context(root, "sqs", SQSPolicyCalls, {})
    source = inventory.inventory_for(ctx)
    queue_mapping, mapped = source.mapping("sqs")
    cloud = {"QueueName": "fixture", "QueueUrl": fake.url}
    parent = source.cloud_record(
        "sqs",
        "SQS.Queue",
        {"Identifier": fake.url, "Properties": json.dumps(cloud)},
        source.schema("SQS.Queue"),
        queue_mapping,
        mapped,
    )
    records = inventory.sdk_inventory.collect(ctx, kind, parents=[parent])
    if len(records) != 1 or records[0].get("structureStatus") != "unresolved":
        raise ValueError("SQS original grouping was not left unresolved")
    resource = fixture_resource(root, ctx, "sqs", records[0])
    policy = {"Version": "2012-10-17", "Statement": []}
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        {"PolicyDocument": ("Policy", "policy", policy)},
        [
            "normal",
            "missing-selector",
            "access-denied",
            "missing-policy",
            "different-policies",
            "account-mismatch",
        ],
    )
    fake.missing = True
    clear_fetch(ctx)
    try:
        mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing SQS policy was accepted")
    fake.missing = False
    resource.rows.append(
        (
            "fixture-999",
            {
                "property": "SQS.QueuePolicy.Queues[]",
                "value": cli.model_literal([fake.second_url]),
                "valueShape": "projection",
            },
        )
    )
    fake.different = True
    clear_fetch(ctx)
    try:
        mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Different SQS policies were accepted as one group")
    fake.different = False
    resource.rows[:] = [row for row in resource.rows if row[0] != "fixture-999"]
    ctx.target[AWS_ACCOUNT_ID_KEY] = "999999999999"
    try:
        inventory.sdk_inventory.collect(ctx, kind, parents=[parent])
    except ValueError as error:
        if "scope" not in str(error):
            raise
    else:
        raise ValueError("SQS queue account mismatch was accepted")
    ctx.target[AWS_ACCOUNT_ID_KEY] = ACCOUNT
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "sqs.get_queue_attributes",
        "Queues[]",
    )
    return items


def sqs_queue_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "SQS.Queue"
    payload = {"FifoQueue": "false", "MessageRetentionPeriod": "604800"}
    cases = {
        "QueueUrl": ("QueueUrl", "typed", SQSCalls.url),
        "FifoQueue": ("Attributes.FifoQueue", "boolean", False),
        "MessageRetentionPeriod": (
            "Attributes.MessageRetentionPeriod",
            "number",
            604800,
        ),
    }
    ctx, fake = fixture_context(root, "sqs", SQSCalls, payload)
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("sqs")
    cloud = {"QueueName": "fixture", "QueueUrl": fake.url}
    record = source.cloud_record(
        "sqs",
        kind,
        {"Identifier": fake.url, "Properties": json.dumps(cloud)},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "sqs", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied", "detail-access-denied"],
        model_failure_is_broken=True,
    )
    if fake.calls != [
        (
            "sqs",
            "get_queue_url",
            {"QueueName": "fixture", "QueueOwnerAWSAccountId": ACCOUNT},
        ),
        (
            "sqs",
            "get_queue_attributes",
            {"QueueUrl": fake.url, "AttributeNames": ["All"]},
        ),
    ]:
        raise ValueError("SQS requests differ from fixture")
    for key, item in items.items():
        if item["status"] != "verified" or key.endswith(".QueueUrl"):
            continue
        field = mapping.properties[key].field.path.removeprefix("Attributes.")
        fake.payload = {name: value for name, value in payload.items() if name != field}
        clear_fetch(ctx)
        _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
        if raw != cli.comparator().MISSING:
            item.update(
                status="broken", reason="Missing SQS attribute was not preserved"
            )
        else:
            item["branches"].append("missing-value")
    fake.payload = payload
    fake.failure_operation = "get_queue_attributes"
    fake.error = cli.comparator().AcquisitionError(
        "sqs.get_queue_attributes", "AccessDenied"
    )
    clear_fetch(ctx)
    try:
        mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("SQS attribute failure was changed") from error
    else:
        raise ValueError("SQS attribute failure was swallowed")
    fake.error, fake.failure_operation = None, ""
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "sqs.get_queue_url", "QueueName"
    )
    return items


CONTRACTS = (
    (
        ("SQS.Queue", "queue"),
        sqs_queue_fixture,
        "sqs.get_queue_url",
        ("QueueName",),
        ("sqs.get_queue_attributes",),
    ),
    (
        ("SQS.QueuePolicy", "policy"),
        sqs_policy_fixture,
        "sqs.get_queue_attributes",
        ("Queues[]",),
    ),
)
