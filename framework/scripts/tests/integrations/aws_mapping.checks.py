#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.aws_mapping_fixtures import (
    BASELINE,
    CHANNEL,
    RECORDER,
    ROOT,
    Path,
    SimpleNamespace,
    TemporaryDirectory,
    aws_mapping,
    copy,
    json,
    load_model,
    m,
    module,
    patch,
    resource_rows,
    resource_table_lines,
    socket,
    sys,
    write_model,
)
from support.it_case_receipt import it_case

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_config_compare(context, path, /, bucket):
    ctx, calls = context(bucket)
    model = ctx.model(path)
    results = [
        item
        for resource in model.resources
        for item in m.compare_resource(ctx, resource)
    ]
    for resource in model.resources:
        for _ in range(2):
            ctx.fetch(resource, "recorder" if resource.kind == RECORDER else "channel")
    assert sorted(api for api, _ in calls) == ["channel", "recorder", "role"]
    return results


def _callback_check_config_context_call(calls, /, api, result, **inputs):
    calls.append((api, inputs))
    return result


def _callback_check_config_context(
    channel, recorder, role, root, target, /, bucket="fixture-bucket"
):
    calls = []
    call = _bind_framework_callback(_callback_check_config_context_call, calls)
    clients = {
        "config": SimpleNamespace(
            describe_configuration_recorders=lambda **inputs: call(
                "recorder", {"ConfigurationRecorders": [recorder]}, **inputs
            ),
            describe_delivery_channels=lambda **inputs: call(
                "channel",
                {"DeliveryChannels": [dict(channel, s3BucketName=bucket)]},
                **inputs,
            ),
        ),
        "iam": SimpleNamespace(
            get_role=lambda **inputs: call("role", {"Role": {"Arn": role}}, **inputs)
        ),
    }
    ctx = m.Context(
        root,
        target,
        session=SimpleNamespace(client=lambda service, **kwargs: clients[service]),
        services=["config"],
    )
    ctx.verified = True
    return ctx, calls


@it_case
def check_config():
    mapping = aws_mapping.registry(ROOT, "config")
    _ = mapping.fields
    role = "arn:aws:iam::123456789012:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig"
    recorder = {
        "name": "recorder-fixture",
        "roleARN": role,
        "recordingGroup": {
            "allSupported": False,
            "includeGlobalResourceTypes": True,
            "resourceTypes": ["AWS::S3::Bucket", "AWS::EC2::VPC"],
            "exclusionByResourceTypes": {"resourceTypes": []},
            "recordingStrategy": {"useOnly": "ALL_SUPPORTED_RESOURCE_TYPES"},
        },
        "recordingMode": {
            "recordingFrequency": "CONTINUOUS",
            "recordingModeOverrides": [
                {
                    "description": "first",
                    "recordingFrequency": "DAILY",
                    "resourceTypes": ["AWS::EC2::VPC"],
                },
                {
                    "description": "second",
                    "recordingFrequency": "CONTINUOUS",
                    "resourceTypes": ["AWS::S3::Bucket"],
                },
            ],
        },
    }
    channel = {
        "name": "channel-fixture",
        "s3BucketName": "fixture-bucket",
        "s3KeyPrefix": "config/",
        "configSnapshotDeliveryProperties": {"deliveryFrequency": "TwentyFour_Hours"},
        "s3KmsKeyArn": "arn:aws:kms:ap-northeast-1:123456789012:key/fixture",
        "snsTopicARN": "arn:aws:sns:ap-northeast-1:123456789012:fixture",
    }
    target = {
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "environment": "dev",
        "directory": "fixture",
    }
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "project.json").write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "environment": "dev",
                            "alias": "fixture",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        bucket_value = "`fixture-bucket`"
        values = {
            "desired.service.config.serviceId": "config",
            "desired.service.config.ownedCatalogResourceTypes": RECORDER
            + ","
            + CHANNEL,
            "display.service.title": "# Config 詳細設計",
            "desired.service.identity.lastAllocated": json.dumps(
                {RECORDER: 1, CHANNEL: 1}
            ),
        }
        for number, kind, payload in [
            ("001", RECORDER, recorder),
            ("002", CHANNEL, channel),
        ]:
            _ = "config-fixture-" + number
            values.update(
                {
                    f"desired.resource.{number}.{key}": value
                    for key, value in {
                        "resourceType": kind,
                        "resourceMode": "IMPORT",
                        "logicalId": kind.replace(".", "_") + "_001",
                    }.items()
                }
            )
            for index, (prop, (path, _norm, default)) in enumerate(
                BASELINE[kind].items(), 1
            ):
                value = m.select(payload, path)
                value = default if value == m.MISSING else value
                raw = (
                    "`" + (value if isinstance(value, str) else json.dumps(value)) + "`"
                )
                if prop == "RoleARN":
                    raw = "`AWSServiceRoleForConfig`"
                elif prop == "S3BucketName":
                    raw = bucket_value
                elif prop == "Id":
                    raw = f"[resource](#resource-{kind.replace('.', '_')}_001)"
                    values[f"observed.row.{number}-{index:03}.value"] = payload["name"]
                values.update(
                    {
                        f"desired.row.{number}-{index:03}.{key}": val
                        for key, val in {
                            "property": kind + "." + prop,
                            "value": raw,
                            "comment": "fixture",
                        }.items()
                    }
                )
        path = root / "model/dev/fixture/config.properties"
        write_model(path, values)

        context = _bind_framework_callback(
            _callback_check_config_context, channel, recorder, role, root, target
        )

        compare = _bind_framework_callback(
            _callback_check_config_compare, context, path
        )

        match, difference = compare("fixture-bucket"), compare("different-bucket")
        assert (
            len(match) == 11 and sum(item["status"] == "match" for item in match) == 10
        )
        assert sum(item["status"] == "identifier" for item in match) == 1
        assert [
            item["propertiesKey"]
            for item in difference
            if item["status"] == "difference"
        ] == [CHANNEL + ".S3BucketName"]
        importer = module("model/importing/cli.py", "model.importing.cli")
        records = [
            {"kind": kind, "identity": payload["name"], "getters": {getter: payload}}
            for kind, getter, payload in [
                (RECORDER, "recorder", recorder),
                (CHANNEL, "channel", channel),
            ]
        ]
        ctx, _ = context()
        model = ctx.model(path)
        normalized = importer.normalize_records(ctx, "config", copy.deepcopy(records))
        captured = {record["kind"]: record["properties"] for record in normalized}
        assert captured[CHANNEL][CHANNEL + ".S3BucketName"]["value"] == "fixture-bucket"
        assert captured[RECORDER][RECORDER + ".RoleARN"]["value"] == role, (
            "acquisition retains the ARN instead of reducing it to a name"
        )
        assert all(
            item["status"] == "captured"
            for record in normalized
            for item in record["properties"].values()
        )
        assert load_model(path).values == model.values
        tables = []
        for resource in model.resources:
            rows = resource_rows(model.values, resource.number, resource.kind, ROOT)
            table = resource_table_lines(resource.spec, "fixture", rows, [], ROOT)
            tables.extend(["### " + resource.kind + ": fixture", *table])
        markdown = "\n".join(["## リソース詳細", *tables])
        assert "| RoleName |" in markdown and "| RoleARN |" not in markdown
        assert "| S3BucketName | `fixture-bucket` |" in markdown
        assert (
            "S3KeyPrefix" not in markdown
            and "ConfigSnapshotDeliveryProperties" not in markdown
        )
        document = root / "docs/designs/dev/fixture/config.md"
        document.parent.mkdir(parents=True)
        document.write_text(markdown, encoding="utf-8")


def main():
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("network forbidden")
    ):
        check_config()
    print(
        "AWS Mapping checks: PASS (Config explicit values, Compare, IMPORT and display 18/18; no AWS connection)"
    )


if __name__ == "__main__":
    main()
