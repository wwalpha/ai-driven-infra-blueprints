#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from unittest.mock import Mock

from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aws_mapping_compare import value as mapping_value
from model.importing import adapter_contracts, cli, inventory
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
                    raw = (
                        "`"
                        + json.dumps(
                            {
                                "$modelRef": {
                                    "logicalId": kind.replace(".", "_") + "_001",
                                    "attribute": "Name",
                                }
                            }
                        )
                        + "`"
                    )
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


class SchedulerClient:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get_schedule(self, **inputs):
        self.calls.append(inputs)
        if self.error:
            raise ClientError(
                {"Error": {"Code": self.error, "Message": "fixture"}}, "GetSchedule"
            )
        return copy.deepcopy(self.payload)


@it_case
def check_scheduler_compare():
    kind = "Scheduler.Schedule"
    target = {
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "environment": "dev",
        "directory": "fixture",
    }
    rows = {
        "Name": "job",
        "GroupName": "custom",
        "Target.RetryPolicy.MaximumEventAgeInSeconds": 3600,
        "Target.RetryPolicy.MaximumRetryAttempts": 3,
        "StartDate": "2026-01-01T09:00:00+09:00",
        "Target.Input": "sensitive-demo-value",
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
            ),
            encoding="utf-8",
        )
        path = root / "model/dev/fixture/eventbridge.properties"
        values = {
            "desired.service.eventbridge.serviceId": "eventbridge",
            "desired.service.eventbridge.ownedCatalogResourceTypes": kind,
            "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
            "desired.resource.001.resourceType": kind,
            "desired.resource.001.resourceMode": "IMPORT",
            "desired.resource.001.logicalId": "Scheduler_Schedule_001",
        }
        for index, (name, value) in enumerate(rows.items(), 1):
            values.update(
                {
                    f"desired.row.001-{index:03}.property": kind + "." + name,
                    f"desired.row.001-{index:03}.value": "`" + str(value) + "`",
                    f"desired.row.001-{index:03}.comment": "fixture",
                }
            )
        write_model(path, values)
        payload = {
            "Name": "job",
            "GroupName": "custom",
            "StartDate": "2026-01-01T00:00:00Z",
            "Target": {
                "Input": "different-sensitive-value",
                "RetryPolicy": {
                    "MaximumEventAgeInSeconds": 3600,
                    "MaximumRetryAttempts": 3,
                },
            },
        }
        client = SchedulerClient(payload)
        ctx = m.Context(
            root,
            target,
            session=SimpleNamespace(client=Mock(return_value=client)),
            services=["eventbridge"],
        )
        ctx.catalog = m.DesignSchemaCatalog(ROOT)
        ctx.verified = True
        results = m.compare_resource(ctx, ctx.model(path).resources[0])
        by_key = {item["propertiesKey"]: item for item in results}
        assert (
            by_key[kind + ".Target.RetryPolicy.MaximumEventAgeInSeconds"]["status"]
            == "match"
        )
        assert (
            by_key[kind + ".Target.RetryPolicy.MaximumRetryAttempts"]["status"]
            == "match"
        )
        assert by_key[kind + ".StartDate"]["status"] == "match"
        assert by_key[kind + ".Target.Input"]["status"] == "difference"
        assert "sensitive-demo-value" not in str(
            results
        ) and "different-sensitive-value" not in str(results)
        assert client.calls == [{"Name": "job", "GroupName": "custom"}]
        assert "sensitive-demo-value" not in str(ctx.trace)
        for retry, expected in [
            (
                {"MaximumEventAgeInSeconds": 7200, "MaximumRetryAttempts": 5},
                ("difference", "difference"),
            ),
            (
                {"MaximumEventAgeInSeconds": 3600, "MaximumRetryAttempts": 0},
                ("match", "difference"),
            ),
            (None, ("difference", "difference")),
        ]:
            changed = copy.deepcopy(payload)
            if retry is None:
                del changed["Target"]["RetryPolicy"]
            else:
                changed["Target"]["RetryPolicy"] = retry
            client = SchedulerClient(changed)
            ctx = m.Context(
                root,
                target,
                session=SimpleNamespace(client=Mock(return_value=client)),
                services=["eventbridge"],
            )
            ctx.catalog = m.DesignSchemaCatalog(ROOT)
            ctx.verified = True
            outcomes = {
                item["propertiesKey"]: item
                for item in m.compare_resource(ctx, ctx.model(path).resources[0])
            }
            keys = [
                kind + ".Target.RetryPolicy.MaximumEventAgeInSeconds",
                kind + ".Target.RetryPolicy.MaximumRetryAttempts",
            ]
            assert tuple(outcomes[key]["status"] for key in keys) == expected
            assert len(client.calls) == 1
        values["desired.row.001-004.value"] = "`0`"
        write_model(path, values)
        changed = copy.deepcopy(payload)
        changed["Target"]["RetryPolicy"]["MaximumRetryAttempts"] = 0
        client = SchedulerClient(changed)
        ctx = m.Context(
            root,
            target,
            session=SimpleNamespace(client=Mock(return_value=client)),
            services=["eventbridge"],
        )
        ctx.catalog = m.DesignSchemaCatalog(ROOT)
        ctx.verified = True
        result = {
            item["propertiesKey"]: item
            for item in m.compare_resource(ctx, ctx.model(path).resources[0])
        }
        assert (
            result[kind + ".Target.RetryPolicy.MaximumRetryAttempts"]["status"]
            == "match"
        )
        for code, status in [
            ("ResourceNotFoundException", "resource_missing"),
            ("AccessDeniedException", "acquisition_failed"),
        ]:
            client = SchedulerClient({}, error=code)
            ctx = m.Context(
                root,
                target,
                session=SimpleNamespace(client=Mock(return_value=client)),
                services=["eventbridge"],
            )
            ctx.catalog = m.DesignSchemaCatalog(ROOT)
            ctx.verified = True
            failures = m.compare_resource(ctx, ctx.model(path).resources[0])
            assert len(failures) == 1 and failures[0]["status"] == status
            assert len(client.calls) == 1
        import_ctx, _ = adapter_contracts.fixture_context(
            ROOT, "eventbridge", adapter_contracts.DirectCalls, {}
        )
        import_ctx.pages = Mock(
            return_value={
                "ResourceDescriptions": [
                    {
                        "Identifier": "job",
                        "Properties": json.dumps(
                            {"Name": "job", "GroupName": "custom"}
                        ),
                    }
                ]
            }
        )
        import_ctx.call = Mock(return_value=payload)
        records = inventory.inventory_for(import_ctx).inventory("eventbridge", kind)
        normalized = cli.normalize_records(import_ctx, "eventbridge", records)
        import_ctx.call.assert_called_once_with(
            "scheduler", "get_schedule", Name="job", GroupName="custom"
        )
        assert (
            normalized[0]["properties"][
                kind + ".Target.RetryPolicy.MaximumRetryAttempts"
            ]["value"]
            == 3
        )


def check_glue_catalog_compare():
    kind = "Glue.Catalog"
    permissions = [
        {
            "Principal": {"DataLakePrincipalIdentifier": "principal"},
            "Permissions": ["CREATE_TABLE", "ALTER"],
        }
    ]
    names = (
        "FederatedCatalog.Identifier",
        "CreateDatabaseDefaultPermissions",
        "CreateTableDefaultPermissions",
    )
    payload = {
        "Name": "catalog",
        "FederatedCatalog": {
            "Identifier": "remote-id",
            "ConnectionName": "different-connection",
        },
        names[1]: permissions,
        names[2]: permissions,
    }
    target = {
        "awsAccountId": "123456789012",
        "awsExecutionAccountId": "999999999999",
        "awsRegion": "ap-northeast-1",
        "environment": "dev",
        "directory": "fixture",
    }
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        for direct in (True, False):
            for scenario in ("match", "difference", "empty", "missing", "error"):
                actual = copy.deepcopy(payload)
                if scenario == "difference":
                    actual["FederatedCatalog"]["Identifier"] = "other-id"
                    actual[names[1]][0]["Permissions"] = ["ALTER"]
                    actual[names[2]][0]["Principal"]["DataLakePrincipalIdentifier"] = (
                        "other"
                    )
                elif scenario == "empty":
                    actual[names[1]] = actual[names[2]] = []
                elif scenario == "missing":
                    actual.pop(names[1])
                    actual.pop(names[2])
                    actual["FederatedCatalog"].pop("Identifier")
                client = Mock()
                client.can_paginate.return_value = False
                client.get_catalog.return_value = {"Catalog": actual}
                client.get_catalogs.return_value = {
                    "CatalogList": [{"Name": "other"}, actual]
                }
                if scenario == "error":
                    error = ClientError(
                        {
                            "Error": {
                                "Code": "AccessDeniedException",
                                "Message": "denied",
                            }
                        },
                        "GetCatalog",
                    )
                    (
                        client.get_catalog if direct else client.get_catalogs
                    ).side_effect = error
                ctx = m.Context(
                    root,
                    target,
                    session=SimpleNamespace(client=Mock(return_value=client)),
                    services=["glue"],
                )
                ctx.verified = True
                model = SimpleNamespace(
                    ctx=ctx,
                    service="glue",
                    values={},
                    locations={},
                    path=root / "model/dev/fixture/glue.properties",
                )
                values = ["remote-id", permissions, permissions]
                if scenario in ("empty", "missing"):
                    values[1:] = [[], []]
                rows = [
                    (
                        f"001-{index:03}",
                        {
                            "property": kind + "." + name,
                            "value": "`"
                            + (json.dumps(value) if isinstance(value, list) else value)
                            + "`",
                        },
                    )
                    for index, (name, value) in enumerate(
                        zip(names, values, strict=True), 1
                    )
                ]
                rows.append(
                    (
                        "001-004",
                        {
                            "property": kind
                            + "."
                            + ("CatalogId" if direct else "Name"),
                            "value": "`"
                            + ("catalog-id" if direct else "catalog")
                            + "`",
                        },
                    )
                )
                resource = m.Resource(
                    model,
                    "001",
                    {"resourceType": kind, "logicalId": "Glue_Catalog_001"},
                    rows,
                )
                results = m.compare_resource(ctx, resource)
                if scenario == "error":
                    assert (
                        len(results) == 1
                        and results[0]["status"] == "acquisition_failed"
                    ), results
                    assert set(results[0]["affectedKeys"]) >= {
                        kind + "." + name for name in names
                    }
                else:
                    found = {item["propertiesKey"]: item for item in results}
                    expected = {
                        "match": "match",
                        "difference": "difference",
                        "empty": "match",
                        "missing": "difference",
                    }[scenario]
                    assert all(
                        found[kind + "." + name]["status"] == expected for name in names
                    ), results
                    if scenario == "match":
                        assert found[kind + "." + names[1]]["awsValue"] == permissions
                assert all(item["api"].startswith("glue.") for item in ctx.trace)
                if direct:
                    client.get_catalog.assert_called_once_with(CatalogId="catalog-id")
                    client.get_catalogs.assert_not_called()
                else:
                    client.get_catalogs.assert_called_once_with(
                        ParentCatalogId="999999999999"
                    )
                    client.get_catalog.assert_not_called()



class ReplicationClient:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error
        self.replication_calls = []

    def list_buckets(self, **inputs):
        return {
            "Buckets": [
                {"Name": "fixture-bucket", "BucketArn": "arn:aws:s3:::fixture-bucket"}
            ]
        }

    def get_bucket_location(self, **inputs):
        return {"LocationConstraint": "ap-northeast-1"}

    def get_bucket_replication(self, **inputs):
        self.replication_calls.append(inputs)
        if self.error:
            raise ClientError(
                {"Error": {"Code": self.error, "Message": "fixture"}},
                "GetBucketReplication",
            )
        return copy.deepcopy(self.payload)


class ReplicationImportCalls:
    def __init__(self, payload, error):
        self.payload = payload
        self.error = error
        self.replication_calls = []

    def pages(self, service, operation, **inputs):
        if (service, operation) == ("cloudcontrol", "list_resources"):
            return {
                "ResourceDescriptions": [
                    {
                        "Identifier": "fixture-bucket",
                        "Properties": json.dumps({"BucketName": "fixture-bucket"}),
                    }
                ]
            }
        if (service, operation) == ("s3", "list_buckets"):
            return {
                "Buckets": [
                    {
                        "Name": "fixture-bucket",
                        "BucketArn": "arn:aws:s3:::fixture-bucket",
                    }
                ]
            }
        raise AssertionError((service, operation))

    def call(self, service, operation, **inputs):
        if (service, operation) == ("cloudcontrol", "get_resource"):
            return {
                "ResourceDescription": {
                    "Identifier": "fixture-bucket",
                    "Properties": json.dumps({"BucketName": "fixture-bucket"}),
                }
            }
        if (service, operation) == ("s3", "get_bucket_location"):
            return {"LocationConstraint": "ap-northeast-1"}
        if (service, operation) == ("s3", "get_bucket_replication"):
            self.replication_calls.append(inputs)
            if self.error:
                raise m.AcquisitionError("s3.get_bucket_replication", self.error)
            return copy.deepcopy(self.payload)
        raise m.AcquisitionError(service + "." + operation, "AccessDenied")


@it_case
def check_s3_replication():
    kind = "S3.Bucket"
    target = {
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "environment": "dev",
        "directory": "fixture",
    }
    payload = {
        "ReplicationConfiguration": {
            "Role": "arn:aws:iam::123456789012:role/replication",
            "Rules": [
                {
                    "ID": "first",
                    "Status": "Enabled",
                    "Priority": 1,
                    "Destination": {
                        "Bucket": "arn:aws:s3:::destination-one",
                        "StorageClass": "STANDARD",
                    },
                    "Filter": {
                        "And": {
                            "Prefix": "one/",
                            "Tags": [
                                {"Key": "a", "Value": "1"},
                                {"Key": "b", "Value": "2"},
                            ],
                        }
                    },
                },
                {
                    "ID": "second",
                    "Status": "Disabled",
                    "Priority": 2,
                    "Destination": {
                        "Bucket": "arn:aws:s3:::destination-two",
                        "StorageClass": "STANDARD_IA",
                    },
                    "Filter": {
                        "And": {
                            "Prefix": "two/",
                            "Tags": [
                                {"Key": "c", "Value": "3"},
                                {"Key": "d", "Value": "4"},
                            ],
                        }
                    },
                },
            ],
        }
    }
    prefix = "ReplicationConfiguration."
    expected = {
        "Role": payload["ReplicationConfiguration"]["Role"],
        "Rules[].Id": ["first", "second"],
        "Rules[].Status": ["Enabled", "Disabled"],
        "Rules[].Priority": [1, 2],
        "Rules[].Destination.Bucket": [
            "arn:aws:s3:::destination-one",
            "arn:aws:s3:::destination-two",
        ],
        "Rules[].Destination.StorageClass": ["STANDARD", "STANDARD_IA"],
        "Rules[].Filter.And.Prefix": ["one/", "two/"],
        "Rules[].Filter.And.TagFilters[].Key": [["a", "b"], ["c", "d"]],
        "Rules[].Filter.And.TagFilters[].Value": [["1", "2"], ["3", "4"]],
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
            ),
            encoding="utf-8",
        )
        path = root / "model/dev/fixture/s3.properties"
        values = {
            "desired.service.s3.serviceId": "s3",
            "desired.service.s3.ownedCatalogResourceTypes": kind,
            "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
            "desired.resource.001.resourceType": kind,
            "desired.resource.001.resourceMode": "IMPORT",
            "desired.resource.001.logicalId": "S3_Bucket_001",
        }
        rows = {
            "BucketName": "fixture-bucket",
            **{prefix + key: value for key, value in expected.items()},
        }
        for index, (name, value) in enumerate(rows.items(), 1):
            values[f"desired.row.001-{index:03}.property"] = kind + "." + name
            values[f"desired.row.001-{index:03}.value"] = cli.model_literal(value)
            values[f"desired.row.001-{index:03}.comment"] = "fixture"
            if "[]" in name:
                values[f"desired.row.001-{index:03}.valueShape"] = "projection"
        write_model(path, values)
        for error, changed, expected_status in [
            (None, False, "match"),
            (None, True, "difference"),
            ("ReplicationConfigurationNotFoundError", False, "difference"),
            ("AccessDenied", False, "acquisition_failed"),
            ("NoSuchBucket", False, "resource_missing"),
        ]:
            response = copy.deepcopy(payload)
            if changed:
                response["ReplicationConfiguration"]["Rules"][1]["Status"] = "Enabled"
            client = ReplicationClient(response, error)
            ctx = m.Context(
                root,
                target,
                session=SimpleNamespace(client=Mock(return_value=client)),
                services=["s3"],
            )
            ctx.catalog = m.DesignSchemaCatalog(ROOT)
            ctx.verified = True
            results = m.compare_resource(ctx, ctx.model(path).resources[0])
            if error in ("AccessDenied", "NoSuchBucket"):
                assert any(row["status"] == expected_status for row in results)
            else:
                selected = {row["propertiesKey"]: row["status"] for row in results}
                assert (
                    selected[kind + "." + prefix + "Rules[].Status"] == expected_status
                )
                if not error and not changed:
                    assert all(
                        selected[kind + "." + prefix + key] == "match"
                        for key in expected
                    )
            if not error and not changed:
                mapping, mapped = ctx.comparison("s3")
                resource = ctx.model(path).resources[0]
                properties = {
                    key: prop
                    for key, prop in mapped.items()
                    if key.startswith(kind + "." + prefix)
                }
                assert len(properties) == 21
                for key, prop in properties.items():
                    mapping_value(ctx, resource, mapping, prop, key)
            assert client.replication_calls == [
                {"Bucket": "fixture-bucket", "ExpectedBucketOwner": "123456789012"}
            ]

        for error in (None, "ReplicationConfigurationNotFoundError", "AccessDenied"):
            ctx, _ = adapter_contracts.fixture_context(
                ROOT, "s3", adapter_contracts.DirectCalls, {}
            )
            fake = ReplicationImportCalls(payload, error)
            ctx.call, ctx.pages = fake.call, fake.pages
            records = inventory.inventory_for(ctx).inventory("s3", kind)
            assert len(records) == 1 and records[0]["identity"] == "fixture-bucket"
            captured = cli.normalize_records(ctx, "s3", records)[0]["properties"]
            assert captured[kind + ".BucketName"]["value"] == "fixture-bucket"
            prop = captured[kind + "." + prefix + "Rules[].Id"]
            assert fake.replication_calls == [
                {"Bucket": "fixture-bucket", "ExpectedBucketOwner": "123456789012"}
            ]
            if error is None:
                assert prop["status"] == "captured" and prop["value"] == [
                    "first",
                    "second",
                ]
                assert captured[
                    kind + "." + prefix + "Rules[].Filter.And.TagFilters[].Value"
                ]["value"] == [["1", "2"], ["3", "4"]]
            elif error == "AccessDenied":
                assert prop["status"] == "unavailable" and prop["errorCode"] == error
            else:
                assert prop["status"] == "missing"


def main():
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("network forbidden")
    ):
        check_config()
        check_scheduler_compare()
        check_glue_catalog_compare()
        check_s3_replication()
    print(
        "AWS Mapping checks: PASS (Config explicit values, Compare, IMPORT and display 18/18; no AWS connection)"
    )


if __name__ == "__main__":
    main()
