"""Offline glue adapter fixtures."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    ACCOUNT,
    clear_fetch,
    direct_properties,
    direct_resource,
    failure_branches,
)
from model.importing.adapter_contract_cases.fake_sdk import DirectCalls


class GlueCalls(DirectCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        if self.operation == "get_catalog":
            self.request(api, operation, inputs)
            if self.error:
                raise self.error
            if (api, operation, inputs) != (
                "glue",
                "get_catalogs",
                {"ParentCatalogId": ACCOUNT},
            ):
                raise ValueError("Catalog parent scope differs from fixture")
            return self.response(
                api,
                operation,
                {
                    "CatalogList": [deepcopy(self.payload)]
                    * (2 if self.duplicate else 1)
                },
            )
        return self.call(api, operation, **inputs)


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    extra_inputs = {}
    if kind in {"Glue.Job", "Glue.SecurityConfiguration"}:
        api, selector = "glue", "Name"
        cloud = {"Name": "fixture"}
        envelope = kind.split(".")[1]
        argument = "JobName" if kind == "Glue.Job" else "Name"
        operation = "get_job" if kind == "Glue.Job" else "get_security_configuration"
        if kind == "Glue.Job":
            payload = {
                "Name": "fixture",
                "Description": "fixture job",
                "Role": "arn:aws:iam::123456789012:role/fixture",
                "Command": {
                    "Name": "glueetl",
                    "PythonVersion": "3",
                    "ScriptLocation": "s3://fixture/job.py",
                },
                "Connections": {"Connections": ["fixture-connection"]},
                "DefaultArguments": {"--job-language": "python"},
                "NonOverridableArguments": {"--enable-metrics": "true"},
                "ExecutionClass": "STANDARD",
                "ExecutionProperty": {"MaxConcurrentRuns": 1},
                "GlueVersion": "4.0",
                "JobRunQueuingEnabled": False,
                "MaxRetries": 0,
                "NumberOfWorkers": 2,
                "SecurityConfiguration": "fixture-security",
                "Timeout": 60,
                "WorkerType": "G.1X",
            }
            cases = {
                name: (
                    name,
                    "json"
                    if name in {"DefaultArguments", "NonOverridableArguments"}
                    else "iam_role"
                    if name == "Role"
                    else "name"
                    if name == "SecurityConfiguration"
                    else "typed",
                    value,
                )
                for name, value in payload.items()
                if name not in {"Command", "Connections", "ExecutionProperty"}
            }
            cases.update(
                {
                    "Command.Name": ("Command.Name", "typed", "glueetl"),
                    "Command.PythonVersion": ("Command.PythonVersion", "typed", "3"),
                    "Command.ScriptLocation": (
                        "Command.ScriptLocation",
                        "typed",
                        "s3://fixture/job.py",
                    ),
                    "Connections.Connections": (
                        "Connections.Connections",
                        "name",
                        ["fixture-connection"],
                    ),
                    "ExecutionProperty.MaxConcurrentRuns": (
                        "ExecutionProperty.MaxConcurrentRuns",
                        "typed",
                        1,
                    ),
                }
            )
        else:
            key = "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012"
            payload = {
                "Name": "fixture",
                "EncryptionConfiguration": {
                    "CloudWatchEncryption": {
                        "CloudWatchEncryptionMode": "SSE-KMS",
                        "KmsKeyArn": key,
                    },
                    "S3Encryption": [{"S3EncryptionMode": "SSE-KMS", "KmsKeyArn": key}],
                },
            }
            cases = {"Name": ("Name", "typed", "fixture")}
            for name, value in payload["EncryptionConfiguration"][
                "CloudWatchEncryption"
            ].items():
                path = "EncryptionConfiguration.CloudWatchEncryption." + name
                cases[path] = (path, "kms" if name == "KmsKeyArn" else "typed", value)
            for name, value in payload["EncryptionConfiguration"]["S3Encryption"][
                0
            ].items():
                cases["EncryptionConfiguration.S3Encryptions[]." + name] = (
                    "EncryptionConfiguration.S3Encryption[]." + name,
                    "kms" if name == "KmsKeyArn" else "typed",
                    [value],
                )
    elif kind == "Glue.Catalog":
        api, operation, selector, argument, envelope = (
            "glue",
            "get_catalog",
            "Name",
            "CatalogId",
            "Catalog",
        )
        cloud = {"CatalogId": "fixture", "Name": "fixture"}
        payload = {
            "CatalogId": "fixture",
            "Name": "fixture",
            "FederatedCatalog": {
                "ConnectionName": "fixture-connection",
                "Identifier": "fixture-id",
            },
        }
        cases = {
            "CatalogId": ("CatalogId", "typed", "fixture"),
            "Name": ("Name", "typed", "fixture"),
            "FederatedCatalog.Identifier": (
                "FederatedCatalog.Identifier",
                "typed",
                "fixture-id",
            ),
            "FederatedCatalog.ConnectionName": (
                "FederatedCatalog.ConnectionName",
                "typed",
                "fixture-connection",
            ),
        }
    else:
        api = "glue"
        item = kind.split(".")[1]
        operation, argument, envelope = "get_" + item.lower(), "Name", item
        selector = item + "Input.Name"
        cloud = {"CatalogId": ACCOUNT, item + "Input": {"Name": "fixture"}}
        extra_inputs = {"CatalogId": ACCOUNT}
        payload = {"Name": "fixture"}
        cases = {selector: ("Name", "typed", "fixture")}
        if item == "Database":
            payload["Description"] = "fixture database"
            cases["DatabaseInput.Description"] = (
                "Description",
                "typed",
                "fixture database",
            )
        elif item == "Connection":
            extra_inputs["HidePassword"] = True
            payload.update(
                {
                    "ConnectionType": "JDBC",
                    "Description": "fixture connection",
                    "ConnectionProperties": {
                        "JDBC_CONNECTION_URL": "jdbc:postgresql://fixture/database"
                    },
                    "AuthenticationConfiguration": {
                        "AuthenticationType": "BASIC",
                        "SecretArn": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:fixture-AbCdEf",
                    },
                    "PhysicalConnectionRequirements": {
                        "AvailabilityZone": "ap-northeast-1a",
                        "SecurityGroupIdList": ["sg-12345678"],
                        "SubnetId": "subnet-12345678",
                    },
                }
            )
            cases["Name"] = ("Name", "name", "fixture")
            for name in ("ConnectionType", "Description", "ConnectionProperties"):
                cases["ConnectionInput." + name] = (
                    name,
                    "json" if name == "ConnectionProperties" else "typed",
                    payload[name],
                )
            for name, value in payload["AuthenticationConfiguration"].items():
                path = "AuthenticationConfiguration." + name
                cases["ConnectionInput." + path] = (
                    path,
                    "arn" if name == "SecretArn" else "typed",
                    value,
                )
            for name, value in payload["PhysicalConnectionRequirements"].items():
                path = "PhysicalConnectionRequirements." + name
                cases["ConnectionInput." + path] = (
                    path,
                    "typed" if name == "AvailabilityZone" else "id",
                    value,
                )
        else:
            cloud["DatabaseName"] = "fixture-database"
            extra_inputs["DatabaseName"] = "fixture-database"
            payload.update(
                {
                    "Parameters": {"classification": "parquet"},
                    "TableType": "EXTERNAL_TABLE",
                    "StorageDescriptor": {
                        "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                        "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                        "Location": "s3://fixture/table/",
                        "SerdeInfo": {
                            "Parameters": {"serialization.format": "1"},
                            "SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                        },
                    },
                }
            )
            for name in ("Parameters", "TableType"):
                cases["TableInput." + name] = (
                    name,
                    "json" if name == "Parameters" else "typed",
                    payload[name],
                )
            for name in ("InputFormat", "OutputFormat", "Location"):
                path = "StorageDescriptor." + name
                cases["TableInput." + path] = (
                    path,
                    "typed",
                    payload["StorageDescriptor"][name],
                )
            for name, value in payload["StorageDescriptor"]["SerdeInfo"].items():
                path = "StorageDescriptor.SerdeInfo." + name
                cases["TableInput." + path] = (
                    path,
                    "json" if name == "Parameters" else "typed",
                    value,
                )
    record = None
    if kind == "Glue.Table":
        record = inventory.sdk_inventory.record(
            kind,
            {
                "CatalogId": ACCOUNT,
                "DatabaseName": "fixture-database",
                "TableInput.Name": "fixture",
            },
            {
                "base": {
                    **payload,
                    "CatalogId": ACCOUNT,
                    "DatabaseName": "fixture-database",
                }
            },
            selectors={"CatalogId": ACCOUNT, "DatabaseName": "fixture-database"},
        )
    ctx, fake, resource = direct_resource(
        root,
        mapping,
        kind,
        api,
        operation,
        {argument: "fixture", **extra_inputs},
        envelope,
        cloud,
        payload,
        calls=GlueCalls,
        record=record,
    )
    items = direct_properties(
        ctx,
        fake,
        resource,
        mapping,
        properties,
        kind,
        cases,
        payload,
        (
            "Name",
            "repositoryName",
            "InstanceProfileName",
            "RoleName",
            "UserName",
            "Roles",
        ),
    )
    if not fake.calls:
        return items
    if kind == "Glue.Catalog":
        resource.rows[:] = [
            row
            for row in resource.rows
            if not row[1]["property"].endswith(".CatalogId")
        ]
        clear_fetch(ctx)
        for key in properties:
            _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
            if raw != cases[key.removeprefix(kind + ".")][2]:
                raise ValueError("Catalog name selector value differs")
        fake.duplicate = True
        clear_fetch(ctx)
        try:
            resource.module.fetch(ctx, resource, "base")
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Duplicate named catalogs were accepted")
        fake.duplicate = False
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].extend(
                    ["name-selector", "parent-account", "ambiguous-name"]
                )
    failure_branches(
        ctx, fake, resource, mapping, properties[0], api + "." + operation, selector
    )
    return items


CONTRACTS = (
    (("Glue.Job", "base"), direct_fixture, "glue.get_job", ("Name",)),
    (
        ("Glue.SecurityConfiguration", "base"),
        direct_fixture,
        "glue.get_security_configuration",
        ("Name",),
    ),
    (
        ("Glue.Connection", "base"),
        direct_fixture,
        "glue.get_connection",
        ("CatalogId", "ConnectionInput.Name"),
    ),
    (
        ("Glue.Catalog", "base"),
        direct_fixture,
        "glue.get_catalog",
        ("CatalogId", "Name"),
        ("glue.get_catalogs",),
    ),
    (
        ("Glue.Database", "base"),
        direct_fixture,
        "glue.get_database",
        ("CatalogId", "DatabaseInput.Name"),
    ),
    (
        ("Glue.Table", "base"),
        direct_fixture,
        "glue.get_table",
        ("CatalogId", "DatabaseName", "TableInput.Name"),
    ),
)
