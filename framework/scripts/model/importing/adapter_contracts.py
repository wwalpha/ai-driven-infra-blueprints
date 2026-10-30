"""Executable, in-process Import adapter evidence; no AWS calls or saved receipts."""

import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aws_mapping_catalog import project
from aws_mapping_compare import value as mapping_value
from botocore.validate import ParamValidator
from utils.aws_sdk import aws_runtime

from model.importing import cli, inventory, limitations
from model.importing.contract_fixtures import InvalidFixture, SchemaOffline
from model.importing.discovery import ADAPTER_INVENTORIES, resolve

ACCOUNT = "123456789012"
TARGET = {
    "awsAccountId": ACCOUNT,
    "awsRegion": "ap-northeast-1",
    "environment": "dev",
    "directory": "contract",
}


class UnverifiedFixture(ValueError):
    """The fixture does not establish the requested evidence."""


def fixture_context(root: Path, service: str, calls: type, payload: Any):
    ctx = cli.import_context(root, TARGET, service=service, no_profile=True)
    ctx.verified = True
    fake = calls(ctx, payload)
    ctx.pages, ctx.call = fake.pages, fake.call
    return ctx, fake


def fixture_resource(root: Path, ctx: Any, service: str, record: Any, number="fixture"):
    _, mapped = inventory.inventory_for(ctx).mapping(service)
    model = SimpleNamespace(
        ctx=ctx,
        path=root / "model/dev/contract" / (service + ".properties"),
        service=service,
        values={},
        resources=[],
    )
    return cli.selector_resource(model, number, record, mapped)


def clear_fetch(ctx: Any) -> None:
    ctx.fetch_cache.clear()
    ctx._flights.clear()


def import_normalize(
    ctx: Any, kind: str, key: str, raw: Any, norm: str = "typed"
) -> None:
    raw = cli.normalize_import_value(ctx, raw, norm)
    shape = "projection" if cli.array_paths(key) else "leaf"
    path = cli.schema_property(kind, key)
    extracted = cli.normalize(path, raw, shape)
    if any(
        item == cli.comparator().MISSING or cli.unsafe(item)
        for item in extracted.values
    ):
        raise UnverifiedFixture("Fixture contains sensitive or unresolved values")
    errors = cli.validation_errors(ctx.catalog, kind, path, extracted)
    if errors:
        raise UnverifiedFixture(
            "Fixture value is invalid for the Model: " + "; ".join(errors)
        )


def fixture_properties(
    ctx: Any,
    resource: Any,
    mapping: Any,
    properties: list[str],
    kind: str,
    expected: dict[str, Any],
    branches: list[str],
    *,
    model_failure_is_broken: bool = False,
) -> dict[str, Any]:
    items = {}
    for key in properties:
        name = key.removeprefix(kind + ".")
        prop = mapping.properties[key]
        case = expected.get(name)
        if cli.sensitive(resource, key) or (
            prop.source != "aws" and limitations.contract(ctx.root, key, "unobservable")
        ):
            items[key] = {
                "status": "unverified",
                "reason": "Sensitive or explicitly unobservable Property",
            }
            continue
        if (
            case is None
            or prop.transform != "identity"
            or (prop.field.path, prop.field.norm) != case[:2]
        ):
            items[key] = {
                "status": "unverified",
                "reason": "No executable property/branch fixture",
            }
            continue
        _, raw = mapping_value(ctx, resource, mapping, prop, key)
        actual = (
            raw
            if prop.field.norm == "kms"
            else cli.comparator().normalize(ctx, raw, prop.field.norm)
        )
        if actual != case[2]:
            items[key] = {
                "status": "broken",
                "reason": "Adapter result differs from fixture",
            }
            continue
        try:
            import_normalize(ctx, kind, key, raw, prop.field.norm)
        except UnverifiedFixture as error:
            if not model_failure_is_broken:
                raise InvalidFixture(str(error)) from error
            items[key] = {
                "status": "broken",
                "reason": "SDK attribute is rejected by Import Model validation: "
                + str(error),
            }
            continue
        items[key] = {
            "status": "verified",
            "reason": "Offline fixture only; AWS retrieval remains unverified",
            "branches": list(branches),
        }
    return items


def failure_branches(
    ctx: Any,
    fake: Any,
    resource: Any,
    mapping: Any,
    sample: str,
    api: str,
    selector: str,
) -> None:
    clear_fetch(ctx)
    fake.error = cli.comparator().AcquisitionError(api, "AccessDenied")
    try:
        mapping_value(ctx, resource, mapping, mapping.properties[sample], sample)
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("API failure was changed") from error
    else:
        raise ValueError("API failure was swallowed")
    fake.error = None
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith("." + selector)
    ]
    clear_fetch(ctx)
    try:
        mapping_value(ctx, resource, mapping, mapping.properties[sample], sample)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing selector was accepted")


def missing_values(
    ctx: Any,
    fake: Any,
    resource: Any,
    mapping: Any,
    items: dict[str, Any],
    payload: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> None:
    for key, evidence in items.items():
        if evidence["status"] != "verified":
            continue
        prop = mapping.properties[key]
        field = prop.field.path.split(".", 1)[0].removesuffix("[]")
        if field in required:
            continue
        fake.payload = {name: value for name, value in payload.items() if name != field}
        clear_fetch(ctx)
        _, raw = mapping_value(ctx, resource, mapping, prop, key)
        actual = cli.comparator().normalize(ctx, raw, prop.field.norm)
        if actual not in (cli.comparator().MISSING, []):
            evidence.update(status="broken", reason="Missing value was not preserved")
        elif "missing-value" not in evidence["branches"]:
            evidence["branches"].append("missing-value")
    fake.payload = payload
    clear_fetch(ctx)


def contracts(mapping: Any, kind: str) -> dict[str, list[str]]:
    """Discover included adapter/SDK getters and their actual mapped properties."""
    result: dict[str, list[str]] = {}
    for key, prop in sorted(mapping.properties.items()):
        definition = mapping.getters.get(prop.field.getter, {})
        if (
            key.startswith(kind + ".")
            and prop.include
            and prop.source == "aws"
            and (not definition or definition.get("kind") in {"adapter", "sdk"})
        ):
            result.setdefault(prop.field.getter, []).append(key)
    return result


def schema_context(root: Path, service: str, fault: str | None = None) -> Any:
    ctx = SchemaOffline(root, target=TARGET, fault=fault)
    ctx.import_mode = True
    ctx.services = (service,)
    ctx.allowed = set(
        cli.import_context(root, TARGET, service=service, no_profile=True).allowed
    )
    ctx.verified = True
    return ctx


def shared_failure_branches(
    root: Path, mapping: Any, record: Any, sample: str
) -> list[str]:
    branches = []
    ctx = schema_context(root, mapping.service, fault="failed")
    resource = fixture_resource(root, ctx, mapping.service, record)
    try:
        mapping_value(ctx, resource, mapping, mapping.properties[sample], sample)
    except cli.comparator().AcquisitionError as error:
        if error.code == "AccessDeniedException":
            branches.append("access-denied")
    except InvalidFixture:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        cli.comparator().Unresolved,
    ):
        pass
    ctx = schema_context(root, mapping.service)
    resource = fixture_resource(root, ctx, mapping.service, record)
    resource.rows.clear()
    try:
        mapping_value(ctx, resource, mapping, mapping.properties[sample], sample)
    except cli.comparator().Unresolved:
        branches.append("all-selectors-missing")
    except InvalidFixture:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        cli.comparator().AcquisitionError,
    ):
        pass
    return branches


def shared_fixture_evidence(
    root: Path, mapping: Any, kind: str, getter: str, properties: list[str]
) -> dict[str, Any]:
    """Exercise shared SDK-shaped inventory without claiming untested branches."""
    ctx = schema_context(root, mapping.service)
    try:
        records = inventory.adapter_inventory(ctx, mapping.service, (kind,))
        if ctx.fixture_error is not None:
            raise ctx.fixture_error
        if not records:
            raise UnverifiedFixture("Shared SDK fixture produced no inventory record")
        record = records[0]
        resource = fixture_resource(root, ctx, mapping.service, record)
    except InvalidFixture:
        raise
    except (
        UnverifiedFixture,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        cli.comparator().Unresolved,
        cli.comparator().AcquisitionError,
    ) as error:
        if ctx.fixture_error is not None:
            raise ctx.fixture_error from error
        return {
            key: {
                "status": "unverified",
                "reason": "Shared inventory fixture cannot establish selectors: "
                + str(error),
            }
            for key in properties
        }
    branches = shared_failure_branches(root, mapping, record, properties[0])
    result = {}
    for key in properties:
        prop = mapping.properties[key]
        if cli.sensitive(resource, key) or limitations.contract(
            root, key, "unobservable"
        ):
            result[key] = {
                "status": "unverified",
                "reason": "Sensitive or explicitly unobservable Property",
            }
            continue
        try:
            _, raw = mapping_value(ctx, resource, mapping, prop, key)
            expected = project(prop, record.get("getters", {}).get(getter, {}))
            if expected == cli.comparator().MISSING or raw != expected:
                raise UnverifiedFixture(
                    "Independent inventory value unavailable or differs"
                )
            import_normalize(ctx, kind, key, raw, prop.field.norm)
        except InvalidFixture:
            raise
        except (
            UnverifiedFixture,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            cli.comparator().Unresolved,
            cli.comparator().AcquisitionError,
        ) as error:
            result[key] = {
                "status": "unverified",
                "reason": "Shared normal fixture cannot prove Property: " + str(error),
            }
        else:
            result[key] = {
                "status": "unverified",
                "reason": "SDK-shaped synthetic branches executed; conditional branches lack fixture evidence",
                "branches": ["normal", *branches],
            }
    return result


class FakeCalls:
    def __init__(self, ctx: Any, payload: dict[str, Any]) -> None:
        self.ctx = ctx
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.sdk = aws_runtime().sdk_session()
        self.error: Exception | None = None

    def request(self, api: str, operation: str, inputs: dict[str, Any]) -> None:
        if (api, operation) not in self.ctx.allowed or not operation.startswith(
            ("list_", "get_", "describe_", "batch_get_")
        ):
            raise ValueError("Operation is outside the read-only allowlist")
        model = self.sdk.get_service_model(api)
        name = aws_runtime().operation_name(model, operation)
        if name is None:
            raise ValueError("Unknown SDK operation")
        shape = model.operation_model(name).input_shape
        if shape is None and inputs:
            raise ValueError("Operation accepts no input parameters")
        errors = ParamValidator().validate(inputs, shape) if shape else None
        if errors and errors.has_errors():
            raise ValueError(errors.generate_report())
        self.calls.append((api, operation, inputs))

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "quicksight",
            "list_namespaces",
            {"AwsAccountId": ACCOUNT},
        ):
            return self.response(api, operation, {"Namespaces": [{"Name": "default"}]})
        if (api, operation, inputs) == (
            "quicksight",
            "list_groups",
            {"AwsAccountId": ACCOUNT, "Namespace": "default"},
        ):
            return self.response(
                api, operation, {"GroupList": [{"GroupName": "group"}]}
            )
        if (api, operation, inputs) != (
            "quicksight",
            "list_vpc_connections",
            {"AwsAccountId": ACCOUNT},
        ):
            raise ValueError("Unexpected inventory request or scope")
        return self.response(
            api,
            operation,
            {"VPCConnectionSummaries": [{"VPCConnectionId": "connection"}]},
        )

    def response(
        self, api: str, operation: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        model = self.sdk.get_service_model(api)
        name = aws_runtime().operation_name(model, operation)
        shape = model.operation_model(name).output_shape
        if shape is None and payload:
            raise InvalidFixture("Operation has no SDK output shape")
        errors = ParamValidator().validate(payload, shape) if shape else None
        if errors and errors.has_errors():
            raise InvalidFixture(
                "Invalid fixture response: " + errors.generate_report()
            )
        return payload

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) == (
            "quicksight",
            "describe_group",
            {"AwsAccountId": ACCOUNT, "Namespace": "default", "GroupName": "group"},
        ):
            return self.response(api, operation, {"Group": deepcopy(self.payload)})
        if (api, operation, inputs) != (
            "quicksight",
            "describe_vpc_connection",
            {"AwsAccountId": ACCOUNT, "VPCConnectionId": "connection"},
        ):
            raise ValueError("Unexpected adapter request or scope")
        return self.response(api, operation, {"VPCConnection": deepcopy(self.payload)})


class Route53Calls(FakeCalls):
    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "route53",
            "list_resource_record_sets",
            {"HostedZoneId": "Z1"},
        ):
            raise InvalidFixture("Unexpected Route53 fixture request")
        return self.response(
            api,
            operation,
            {
                "ResourceRecordSets": deepcopy(self.payload),
                "IsTruncated": False,
                "MaxItems": "100",
            },
        )


class DataZoneCalls(FakeCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == ("datazone", "list_domains", {}):
            return self.response(
                api,
                operation,
                {
                    "items": [
                        {
                            "id": "dzd_domain",
                            "name": "dzd_domain",
                            "arn": "arn:aws:datazone:ap-northeast-1:123456789012:domain/dzd_domain",
                            "managedAccountId": ACCOUNT,
                            "status": "AVAILABLE",
                            "createdAt": datetime(2026, 1, 1, tzinfo=timezone.utc),
                        }
                    ]
                },
            )
        if (api, operation, inputs) == (
            "datazone",
            "list_projects",
            {"domainIdentifier": "dzd_domain"},
        ):
            return self.response(
                api,
                operation,
                {
                    "items": [
                        {
                            "domainId": "dzd_domain",
                            "id": "project",
                            "name": "project",
                            "createdBy": "fixture",
                        }
                    ]
                },
            )
        raise InvalidFixture("Unexpected DataZone inventory request")

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "datazone",
            "get_project",
            {"domainIdentifier": "dzd_domain", "identifier": "project"},
        ):
            raise ValueError("DataZone selector differs from fixture")
        return self.response(
            api,
            operation,
            {
                "domainId": "dzd_domain",
                "id": "project",
                "name": "project",
                "createdBy": "fixture",
            },
        )


class LakeFormationCalls(FakeCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) != ("lakeformation", "list_resources", {}):
            raise InvalidFixture("Unexpected Lake Formation inventory request")
        return self.response(
            api,
            operation,
            {"ResourceInfoList": [{"ResourceArn": "arn:aws:s3:::fixture"}]},
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "lakeformation",
            "describe_resource",
            {"ResourceArn": "arn:aws:s3:::fixture"},
        ):
            raise ValueError("Lake Formation selector differs from fixture")
        return self.response(api, operation, {"ResourceInfo": deepcopy(self.payload)})


class LogsCalls(FakeCalls):
    def __init__(self, ctx: Any, payload: dict[str, Any]) -> None:
        super().__init__(ctx, payload)
        self.duplicate = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation) != ("logs", "describe_log_groups") or inputs not in (
            {},
            {"logGroupNamePrefix": "fixture"},
        ):
            raise ValueError("Log group selector differs from fixture")
        records = [deepcopy(self.payload)] * (2 if self.duplicate else 1)
        return self.response(api, operation, {"logGroups": records})


class QuickSightSourceCalls(FakeCalls):
    empty = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) != (
            "quicksight",
            "list_data_sources",
            {"AwsAccountId": ACCOUNT},
        ):
            raise ValueError("QuickSight inventory request differs from fixture")
        return self.response(
            api,
            operation,
            {
                "DataSources": [
                    {"DataSourceId": "athena-id"},
                    {"DataSourceId": "snowflake-id"},
                ]
            },
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (
            api != "quicksight"
            or inputs.get("AwsAccountId") != ACCOUNT
            or inputs.get("DataSourceId") not in self.payload
        ):
            raise ValueError("QuickSight data source selector differs from fixture")
        if operation == "describe_data_source":
            return self.response(
                api,
                operation,
                {"DataSource": deepcopy(self.payload[inputs["DataSourceId"]])},
            )
        if operation == "describe_data_source_permissions":
            permissions = (
                None
                if self.empty
                else [
                    {
                        "Principal": "arn:aws:quicksight:ap-northeast-1:123456789012:group/default/fixture",
                        "Actions": ["quicksight:DescribeDataSource"],
                    }
                ]
            )
            return self.response(
                api,
                operation,
                {} if permissions is None else {"Permissions": permissions},
            )
        raise ValueError("QuickSight operation differs from fixture")


def quicksight_source_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "QuickSight.DataSource"
    getter = mapping.properties[properties[0]].field.getter
    payload = {
        "athena-id": {
            "DataSourceId": "athena-id",
            "Name": "athena-source",
            "Type": "ATHENA",
            "DataSourceParameters": {
                "AthenaParameters": {
                    "WorkGroup": "primary",
                    "RoleArn": "arn:aws:iam::123456789012:role/fixture",
                }
            },
            "SslProperties": {"DisableSsl": False},
        },
        "snowflake-id": {
            "DataSourceId": "snowflake-id",
            "Name": "snowflake-source",
            "Type": "SNOWFLAKE",
            "DataSourceParameters": {
                "SnowflakeParameters": {
                    "Host": "example.snowflakecomputing.com",
                    "Database": "DATA",
                    "Warehouse": "COMPUTE",
                    "AuthenticationType": "PASSWORD",
                }
            },
            "VpcConnectionProperties": {
                "VpcConnectionArn": "arn:aws:quicksight:ap-northeast-1:123456789012:vpcConnection/fixture"
            },
            "SslProperties": {"DisableSsl": False},
        },
    }
    cases = {
        "Name": ("Name", "typed", "athena-source", 0),
        "Type": ("Type", "typed", "ATHENA", 0),
        "DataSourceId": ("DataSourceId", "typed", "athena-id", 0),
        "DataSourceParameters.AthenaParameters.WorkGroup": (
            "DataSourceParameters.AthenaParameters.WorkGroup",
            "typed",
            "primary",
            0,
        ),
        "DataSourceParameters.AthenaParameters.RoleArn": (
            "DataSourceParameters.AthenaParameters.RoleArn",
            "arn",
            "arn:aws:iam::123456789012:role/fixture",
            0,
        ),
        "DataSourceParameters.SnowflakeParameters.AuthenticationType": (
            "DataSourceParameters.SnowflakeParameters.AuthenticationType",
            "typed",
            "PASSWORD",
            1,
        ),
        "DataSourceParameters.SnowflakeParameters.Database": (
            "DataSourceParameters.SnowflakeParameters.Database",
            "typed",
            "DATA",
            1,
        ),
        "DataSourceParameters.SnowflakeParameters.Host": (
            "DataSourceParameters.SnowflakeParameters.Host",
            "typed",
            "example.snowflakecomputing.com",
            1,
        ),
        "DataSourceParameters.SnowflakeParameters.Warehouse": (
            "DataSourceParameters.SnowflakeParameters.Warehouse",
            "typed",
            "COMPUTE",
            1,
        ),
        "SslProperties.DisableSsl": ("SslProperties.DisableSsl", "typed", False, 0),
        "VpcConnectionProperties.VpcConnectionArn": (
            "VpcConnectionProperties.VpcConnectionArn",
            "arn",
            "arn:aws:quicksight:ap-northeast-1:123456789012:vpcConnection/fixture",
            1,
        ),
        "Permissions[].Principal": (
            "Permissions[].Principal",
            "typed",
            ["arn:aws:quicksight:ap-northeast-1:123456789012:group/default/fixture"],
            0,
        ),
        "Permissions[].Actions": (
            "Permissions[].Actions",
            "typed",
            [["quicksight:DescribeDataSource"]],
            0,
        ),
    }
    ctx, fake = fixture_context(root, "quicksight", QuickSightSourceCalls, payload)
    records = inventory.adapter_inventory(ctx, "quicksight", (kind,))
    if len(records) != 2:
        raise InvalidFixture("QuickSight data source inventory differs from fixture")
    resources = [
        fixture_resource(root, ctx, "quicksight", record, "fixture-" + str(index))
        for index, record in enumerate(records)
    ]
    items = {}
    for index, resource in enumerate(resources):
        selected = [
            key
            for key in properties
            if key.removeprefix(kind + ".") in cases
            and cases[key.removeprefix(kind + ".")][3] == index
        ]
        expected = {key: value[:3] for key, value in cases.items() if value[3] == index}
        items.update(
            fixture_properties(
                ctx,
                resource,
                mapping,
                selected,
                kind,
                expected,
                [
                    "normal",
                    "missing-selector",
                    "access-denied",
                    "account-mismatch",
                    "athena-or-snowflake",
                ],
            )
        )
    for key in properties:
        if key not in items:
            items[key] = {
                "status": "unverified",
                "reason": "Sensitive or explicitly unobservable Property"
                if cli.sensitive(resources[0], key)
                else "No executable property/branch fixture",
            }
    if getter == "permissions":
        fake.empty = True
        clear_fetch(ctx)
        for key, item in items.items():
            if item["status"] != "verified":
                continue
            _, raw = mapping_value(
                ctx, resources[0], mapping, mapping.properties[key], key
            )
            if raw not in (cli.comparator().MISSING, []):
                item.update(
                    status="broken", reason="Missing permissions were not preserved"
                )
            else:
                item["branches"].append("missing-permissions")
        fake.empty = False
    else:
        for key, item in items.items():
            if item["status"] != "verified":
                continue
            name = key.removeprefix(kind + ".")
            if ".AthenaParameters." not in name and ".SnowflakeParameters." not in name:
                continue
            opposite = 1 - cases[name][3]
            _, raw = mapping_value(
                ctx, resources[opposite], mapping, mapping.properties[key], key
            )
            if raw != cli.comparator().MISSING:
                item.update(
                    status="broken",
                    reason="Different source type did not preserve missing value",
                )
            else:
                item["branches"].append("other-source-type-missing")
    failure_branches(
        ctx,
        fake,
        resources[0],
        mapping,
        properties[0],
        "quicksight.describe_data_source_permissions"
        if getter == "permissions"
        else "quicksight.describe_data_source",
        "DataSourceId",
    )
    ctx.target["awsAccountId"] = "999999999999"
    try:
        resources[1].module.fetch(ctx, resources[1], getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("QuickSight data source account mismatch was accepted")
    return items


class SecurityHubCalls(FakeCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        return self.call(api, operation, **inputs)

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("securityhub", "describe_hub", {}):
            raise ValueError("Security Hub request differs from fixture")
        return self.response(api, operation, deepcopy(self.payload))


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
    ctx.target["awsExecutionAccountId"] = "999999999999"
    if (
        resource.module.fetch(ctx, resource, "session").get("AwsAccountId")
        != "999999999999"
    ):
        raise ValueError("Macie session execution account was not preserved")
    ctx.target.pop("awsExecutionAccountId")
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


class KMSCalls(FakeCalls):
    key_id = "12345678-1234-1234-1234-123456789012"
    aliases = ("alias/fixture",)
    conflicting = False
    duplicate = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("kms", "list_aliases", {}):
            raise ValueError("KMS alias request differs from fixture")
        entries = [
            {"AliasName": name, "TargetKeyId": self.key_id} for name in self.aliases
        ]
        return self.response(
            api, operation, {"Aliases": entries * (2 if self.duplicate else 1)}
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::KMS::Key", "Identifier": self.key_id},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": self.key_id,
                        "Properties": json.dumps({"KeyId": self.key_id}),
                    }
                },
            )
        if api != "kms" or inputs.get("KeyId") not in (self.key_id, *self.aliases):
            raise ValueError("KMS key selector differs from fixture")
        if operation == "describe_key" and set(inputs) == {"KeyId"}:
            metadata = deepcopy(self.payload)
            if self.conflicting and inputs["KeyId"] == "alias/other":
                metadata["KeyId"] = "87654321-4321-4321-4321-210987654321"
            return self.response(api, operation, {"KeyMetadata": metadata})
        if operation == "get_key_rotation_status" and inputs == {"KeyId": self.key_id}:
            return self.response(
                api,
                operation,
                {"KeyRotationEnabled": True, "RotationPeriodInDays": 365},
            )
        if operation == "get_key_policy" and inputs == {
            "KeyId": self.key_id,
            "PolicyName": "default",
        }:
            return self.response(
                api,
                operation,
                {"Policy": json.dumps({"Version": "2012-10-17", "Statement": []})},
            )
        raise ValueError("Unexpected KMS operation or policy name")


def kms_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    getter = mapping.properties[properties[0]].field.getter
    payload = {
        "KeyId": KMSCalls.key_id,
        "Description": "fixture key",
        "Enabled": True,
        "KeySpec": "SYMMETRIC_DEFAULT",
        "KeyUsage": "ENCRYPT_DECRYPT",
        "MultiRegion": False,
        "Origin": "AWS_KMS",
    }
    ctx, fake = fixture_context(root, "kms", KMSCalls, payload)
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("kms")
    record = source.cloud_record(
        "kms",
        "KMS.Key",
        {"Identifier": fake.key_id, "Properties": json.dumps({"KeyId": fake.key_id})},
        source.schema("KMS.Key"),
        mapping,
        mapped,
    )
    key = fixture_resource(root, ctx, "kms", record, "key")
    key.model._anchor_resources = {"key": [("key", {"anchor": "key"})]}
    ctx.models[key.model.path.resolve()] = key.model
    aliases = []
    for number, name in enumerate(("alias/fixture", "alias/other")):
        alias = cli.selector_resource(
            key.model,
            "alias" + str(number),
            {"kind": "KMS.Alias", "getters": {"alias": {"AliasName": name}}},
            mapped,
        )
        alias.spec["parentReference"] = "[key](#key)"
        aliases.append(alias)
    key.model.resources = [key, *aliases[:1]]
    resource = aliases[0] if kind == "KMS.Alias" else key
    cases = {name: (name, "typed", value) for name, value in payload.items()}
    cases.update(
        {
            "AliasName": ("AliasName", "typed", "alias/fixture"),
            "EnableKeyRotation": ("KeyRotationEnabled", "typed", True),
            "RotationPeriodInDays": ("RotationPeriodInDays", "typed", 365),
            "KeyPolicy": (
                "Policy",
                "policy",
                {"Version": "2012-10-17", "Statement": []},
            ),
        }
    )
    items = fixture_properties(
        ctx, resource, mapping, properties, kind, cases, ["normal", "access-denied"]
    )
    if kind == "KMS.Key" and getter == "base":
        missing_values(
            ctx, fake, resource, mapping, items, payload, required=("KeyId",)
        )
    clear_fetch(ctx)
    fake.error = cli.comparator().AcquisitionError("kms", "AccessDenied")
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("KMS API failure was swallowed")
    fake.error = None
    if kind == "KMS.Alias":
        fake.aliases = ()
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().AcquisitionError:
            pass
        else:
            raise ValueError("Absent alias was accepted")
        fake.aliases = ("alias/fixture",)
        fake.duplicate = True
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Ambiguous alias was accepted")
        fake.duplicate = False
        fake.payload = {**payload, "KeyId": "87654321-4321-4321-4321-210987654321"}
        clear_fetch(ctx)
        if (
            resource.module.fetch(ctx, resource, getter).get("ParentMismatch")
            is not True
        ):
            raise ValueError("Alias parent mismatch was lost")
        branches = ["missing-alias", "ambiguous-alias", "parent-mismatch"]
    else:
        key.rows[:] = []
        for key_property in properties:
            clear_fetch(ctx)
            _, raw = mapping_value(
                ctx, resource, mapping, mapping.properties[key_property], key_property
            )
            if (
                cli.comparator().normalize(
                    ctx, raw, mapping.properties[key_property].field.norm
                )
                != cases[key_property.removeprefix(kind + ".")][2]
            ):
                raise ValueError("Alias-resolved key value differs")
        key.model.resources = [key]
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Missing key and aliases were accepted")
        key.model.resources = [key, *aliases]
        fake.aliases = ("alias/fixture", "alias/other")
        fake.conflicting = True
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Conflicting aliases were accepted")
        fake.conflicting = False
        resource.module.fetch(ctx, resource, getter)
        branches = [
            "alias-selector",
            "missing-selector",
            "conflicting-aliases",
            "multiple-aliases-one-key",
        ]
    for item in items.values():
        if item["status"] == "verified":
            item["branches"].extend(branches)
    return items


class DirectCalls(FakeCalls):
    api = ""
    operation = ""
    inputs: dict[str, Any] = {}
    envelope = ""
    typename = ""
    cloud_properties: dict[str, Any] = {}
    identifier = ""
    duplicate = False

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

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": self.typename, "Identifier": self.identifier},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": self.identifier,
                        "Properties": json.dumps(self.cloud_properties),
                    }
                },
            )
        if (api, operation, inputs) != (self.api, self.operation, self.inputs):
            raise ValueError(
                "SDK request differs from fixture: " + api + "." + operation
            )
        body = (
            deepcopy(self.payload)
            if self.envelope == "$"
            else {self.envelope: deepcopy(self.payload)}
        )
        return self.response(api, operation, body)


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
        resource.spec["parentReference"] = "[parent](#parent)"
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
            except cli.comparator().AcquisitionError:
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
            "AvailabilityZone": (
                "Placement.AvailabilityZone",
                "typed",
                "ap-northeast-1a",
            ),
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


class FirehoseCalls(DirectCalls):
    mode = "normal"

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("firehose", "list_delivery_streams", {}):
            raise ValueError("Firehose inventory scope differs")
        return self.response(
            api,
            operation,
            {"DeliveryStreamNames": ["fixture"], "HasMoreDeliveryStreams": False},
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation) != (
            "firehose",
            "describe_delivery_stream",
        ) or inputs not in (
            {"DeliveryStreamName": "fixture"},
            {
                "DeliveryStreamName": "fixture",
                "ExclusiveStartDestinationId": "destination-1",
            },
        ):
            raise ValueError("Firehose name or continuation differs")
        result = deepcopy(self.payload)
        if self.mode == "legacy":
            dest = result["Destinations"][0]
            body = dest.pop("ExtendedS3DestinationDescription")
            body.pop("ErrorOutputPrefix")
            dest["S3DestinationDescription"] = body
        elif self.mode == "multiple":
            result["Destinations"] *= 2
        elif self.mode in {"empty", "missing-continuation"}:
            result["Destinations"] = []
            result["HasMoreDestinations"] = self.mode == "missing-continuation"
        elif self.mode in {"pagination", "repeat"}:
            result["HasMoreDestinations"] = (
                self.mode == "repeat" or "ExclusiveStartDestinationId" not in inputs
            )
            if self.mode == "pagination" and "ExclusiveStartDestinationId" in inputs:
                result["Destinations"] = []
        return self.response(api, operation, {"DeliveryStreamDescription": result})


def firehose_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    dest = {
        "RoleARN": "arn:aws:iam::123456789012:role/fixture",
        "BucketARN": "arn:aws:s3:::fixture-bucket",
        "Prefix": "incoming/",
        "ErrorOutputPrefix": "errors/",
        "BufferingHints": {"IntervalInSeconds": 300, "SizeInMBs": 5},
        "CompressionFormat": "GZIP",
        "EncryptionConfiguration": {"NoEncryptionConfig": "NoEncryption"},
        "CloudWatchLoggingOptions": {
            "Enabled": True,
            "LogGroupName": "fixture",
            "LogStreamName": "delivery",
        },
    }
    payload = {
        "DeliveryStreamName": "fixture",
        "DeliveryStreamARN": "arn:aws:firehose:ap-northeast-1:123456789012:deliverystream/fixture",
        "DeliveryStreamStatus": "ACTIVE",
        "DeliveryStreamType": "DirectPut",
        "VersionId": "1",
        "HasMoreDestinations": False,
        "Destinations": [
            {"DestinationId": "destination-1", "ExtendedS3DestinationDescription": dest}
        ],
        "DeliveryStreamEncryptionConfiguration": {"KeyType": "AWS_OWNED_CMK"},
    }
    ctx, fake = fixture_context(root, "data-firehose", FirehoseCalls, payload)
    record = inventory.adapter_inventory(
        ctx, "data-firehose", ("KinesisFirehose.DeliveryStream",)
    )[0]
    resource = fixture_resource(root, ctx, "data-firehose", record)
    getter = mapping.properties[properties[0]].field.getter
    cases = {
        "DeliveryStreamName": ("DeliveryStreamName", "typed", "fixture"),
        "DeliveryStreamType": ("DeliveryStreamType", "typed", "DirectPut"),
        "DeliveryStreamEncryptionConfigurationInput.KeyType": (
            "DeliveryStreamEncryptionConfiguration.KeyType",
            "typed",
            "AWS_OWNED_CMK",
        ),
    }
    for name in (
        "RoleARN",
        "BucketARN",
        "Prefix",
        "ErrorOutputPrefix",
        "CompressionFormat",
    ):
        cases["S3DestinationConfiguration." + name] = (
            name,
            "arn" if name.endswith("ARN") else "typed",
            dest[name],
        )
    for group in ("BufferingHints", "CloudWatchLoggingOptions"):
        for name, value in dest[group].items():
            path = group + "." + name
            cases["S3DestinationConfiguration." + path] = (
                path,
                "name" if name == "LogGroupName" else "typed",
                value,
            )
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "KinesisFirehose.DeliveryStream",
        cases,
        ["normal", "access-denied", "missing-selector"],
    )
    if getter == "destination":
        for mode in ("legacy", "pagination"):
            fake.mode = mode
            clear_fetch(ctx)
            result = resource.module.fetch(ctx, resource, getter)
            if (
                result.get("BucketARN") != dest["BucketARN"]
                or result.get("Prefix") != "incoming/"
            ):
                raise ValueError("Firehose destination variant differs")
        for mode in ("multiple", "empty", "missing-continuation", "repeat"):
            fake.mode = mode
            try:
                resource.module.fetch(ctx, resource, getter)
            except (cli.comparator().Unresolved, cli.comparator().AcquisitionError):
                pass
            else:
                raise ValueError("Invalid destination selection was accepted: " + mode)
        fake.mode = "normal"
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].extend(
                    [
                        "extended-s3",
                        "legacy-s3",
                        "pagination",
                        "ambiguous",
                        "empty",
                        "missing-continuation",
                        "repeated-continuation",
                    ]
                )
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "firehose.describe_delivery_stream",
        "DeliveryStreamName",
    )
    return items


class GroupedCalls(DirectCalls):
    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        if self.operation != "get_policy" or api == "cloudcontrol":
            return super().call(api, operation, **inputs)
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "lambda",
            "get_policy",
            {"FunctionName": "fixture"},
        ):
            raise ValueError("Permission parent selector differs")
        return self.response(api, operation, {"Policy": json.dumps(self.payload)})


def grouped_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    permission = mapping.service == "lambda"
    kind, parent_kind, parent_prop, child_prop, getter = (
        (
            "Lambda.Permission",
            "Lambda.Function",
            "FunctionName",
            "FunctionName",
            "permission",
        )
        if permission
        else (
            "SecretsManager.RotationSchedule",
            "SecretsManager.Secret",
            "Name",
            "SecretId",
            "rotation",
        )
    )
    source_arn = "arn:aws:s3:::fixture-bucket"
    statement = {
        "Sid": "fixture-permission",
        "Action": "lambda:InvokeFunction",
        "Principal": {"Service": "s3.amazonaws.com"},
        "Condition": {
            "ArnLike": {"AWS:SourceArn": source_arn},
            "StringEquals": {"AWS:SourceAccount": ACCOUNT},
        },
    }
    if permission:
        payload = {"Version": "2012-10-17", "Statement": [statement]}
        cases = {
            "Id": ("Sid", "typed", "fixture-permission"),
            "Action": ("Action", "typed", "lambda:InvokeFunction"),
            "FunctionName": ("FunctionName", "name", "fixture"),
            "Principal": ("Principal", "typed", "s3.amazonaws.com"),
            "SourceArn": ("SourceArn", "arn", source_arn),
            "SourceAccount": ("SourceAccount", "typed", ACCOUNT),
        }
    else:
        payload = {
            "Name": "fixture",
            "RotationRules": {"AutomaticallyAfterDays": 30, "Duration": "2h"},
            "ExternalSecretRotationMetadata": [
                {"Key": "fixture-key", "Value": "fixture-value"}
            ],
            "ExternalSecretRotationRoleArn": "arn:aws:iam::123456789012:role/fixture",
        }
        cases = {
            "SecretId": ("Name", "name", "fixture"),
            "RotationRules.AutomaticallyAfterDays": (
                "RotationRules.AutomaticallyAfterDays",
                "typed",
                30,
            ),
            "RotationRules.Duration": ("RotationRules.Duration", "typed", "2h"),
            "ExternalSecretRotationMetadata[].Key": (
                "ExternalSecretRotationMetadata[].Key",
                "typed",
                ["fixture-key"],
            ),
            "ExternalSecretRotationMetadata[].Value": (
                "ExternalSecretRotationMetadata[].Value",
                "typed",
                ["fixture-value"],
            ),
            "ExternalSecretRotationRoleArn": (
                "ExternalSecretRotationRoleArn",
                "arn",
                payload["ExternalSecretRotationRoleArn"],
            ),
        }
    ctx, fake = fixture_context(root, mapping.service, GroupedCalls, payload)
    fake.api, fake.operation, fake.inputs, fake.envelope = (
        ("lambda", "get_policy", {"FunctionName": "fixture"}, "$")
        if permission
        else ("secretsmanager", "describe_secret", {"SecretId": "fixture"}, "$")
    )
    fake.typename, fake.identifier, fake.cloud_properties = (
        "AWS::" + kind.replace(".", "::"),
        "fixture-permission" if permission else "fixture-rotation",
        {
            "Id": "fixture-permission" if permission else "fixture-rotation",
            child_prop: "fixture",
        },
    )
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping(mapping.service)
    record = source.cloud_record(
        mapping.service,
        kind,
        {
            "Identifier": fake.identifier,
            "Properties": json.dumps(fake.cloud_properties),
        },
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, mapping.service, record, "child")
    parent = cli.selector_resource(
        resource.model,
        "parent",
        {
            "kind": parent_kind,
            "getters": {},
            "seedProperties": {parent_kind + "." + parent_prop: "fixture"},
        },
        mapped,
    )
    resource.spec["parentReference"] = "[parent](#parent)"
    resource.model._anchor_resources = {"parent": [("parent", {"anchor": "parent"})]}
    resource.model.resources = [parent, resource]
    ctx.models[resource.model.path.resolve()] = resource.model
    if permission:
        resource.rows.extend(
            (
                "fixture-" + name,
                {"property": kind + "." + name, "value": cli.model_literal(case[2])},
            )
            for name, case in cases.items()
            if not resource.rows_for(name)
        )
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["parent-selector", "parent-mismatch", "missing-selector", "access-denied"],
    )
    if permission:
        resource.rows[:] = [
            row for row in resource.rows if not row[1]["property"].endswith(".Id")
        ]
        for principal in ("s3.amazonaws.com", {"Service": "s3.amazonaws.com"}):
            for condition in ("ArnLike", "ArnEquals"):
                fake.payload = {
                    "Statement": [
                        {
                            **statement,
                            "Principal": principal,
                            "Condition": {
                                condition: {"AWS:SourceArn": source_arn},
                                "StringEquals": {"AWS:SourceAccount": ACCOUNT},
                            },
                        }
                    ]
                }
                clear_fetch(ctx)
                if (
                    resource.module.fetch(ctx, resource, getter)["Principal"]
                    != "s3.amazonaws.com"
                ):
                    raise ValueError(
                        "Permission principal/condition projection differs"
                    )
        fake.payload = {"Statement": [statement, statement]}
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Ambiguous permissions were accepted")
        fake.payload = payload
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].extend(
                    [
                        "sid-selector",
                        "property-selector",
                        "string-principal",
                        "object-principal",
                        "arn-like",
                        "arn-equals",
                        "ambiguous",
                    ]
                )
    else:
        missing_values(ctx, fake, resource, mapping, items, payload, required=("Name",))
    saved_rows = deepcopy(resource.rows)
    resource.rows[:] = [
        row
        for row in resource.rows
        if not row[1]["property"].endswith("." + child_prop)
    ]
    resource.rows.append(
        ("fixture-mismatch", {"property": kind + "." + child_prop, "value": "`other`"})
    )
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Grouped resource parent mismatch was accepted")
    resource.rows[:] = saved_rows
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        fake.api + "." + fake.operation,
        child_prop,
    )
    return items


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


class MacieJobCalls(DirectCalls):
    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        expected = {
            "filterCriteria": {
                "includes": [{"key": "NAME", "comparator": "EQ", "values": ["fixture"]}]
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


class HostedZoneCalls(DirectCalls):
    zone_id = "Z123456789"
    wrong_vpc = False
    vpcs = [{"VPCId": "vpc-12345678", "VPCRegion": "ap-northeast-1"}]

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("route53", "list_hosted_zones", {}):
            raise ValueError("Hosted zone list scope differs")
        return self.response(
            api,
            operation,
            {
                "HostedZones": [deepcopy(self.payload)] * (2 if self.duplicate else 1),
                "Marker": "",
                "MaxItems": "100",
                "IsTruncated": False,
            },
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        if api == "cloudcontrol":
            return super().call(api, operation, **inputs)
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation) != ("route53", "get_hosted_zone") or inputs not in (
            {"Id": self.zone_id},
            {"Id": "/hostedzone/" + self.zone_id},
        ):
            raise ValueError("Hosted zone ID differs")
        return self.response(
            api,
            operation,
            {
                "HostedZone": deepcopy(self.payload),
                "VPCs": [{"VPCId": "vpc-87654321", "VPCRegion": "ap-northeast-1"}]
                if self.wrong_vpc
                else deepcopy(self.vpcs),
            },
        )


def hosted_zone_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    payload = {
        "Id": "/hostedzone/" + HostedZoneCalls.zone_id,
        "Name": "Example.COM.",
        "CallerReference": "fixture",
        "Config": {"Comment": "fixture zone", "PrivateZone": True},
    }
    ctx, fake = fixture_context(root, "route53", HostedZoneCalls, payload)
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("route53")
    fake.typename, fake.identifier, fake.cloud_properties = (
        "AWS::Route53::HostedZone",
        fake.zone_id,
        {"Id": fake.zone_id, "Name": "Example.COM."},
    )
    record = source.cloud_record(
        "route53",
        "Route53.HostedZone",
        {"Identifier": fake.zone_id, "Properties": json.dumps(fake.cloud_properties)},
        source.schema("Route53.HostedZone"),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "route53", record)
    getter = mapping.properties[properties[0]].field.getter
    cases = {
        "Id": ("Id", "typed", fake.zone_id),
        "Name": ("Name", "dns", "example.com"),
        "HostedZoneConfig.Comment": ("Config.Comment", "typed", "fixture zone"),
        "VPCs[].VPCId": ("VPCs[].VPCId", "id", ["vpc-12345678"]),
        "VPCs[].VPCRegion": ("VPCs[].VPCRegion", "typed", ["ap-northeast-1"]),
    }
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "Route53.HostedZone",
        cases,
        [
            "id-selector",
            "name-selector",
            "vpc-membership",
            "ambiguous",
            "access-denied",
            "missing-selector",
        ],
    )
    fake.payload = {**payload, "Config": {"PrivateZone": True}}
    if (
        getter == "zone"
        and resource.module.fetch(ctx, resource, getter)
        .get("Config", {})
        .get("Comment")
        is not None
    ):
        raise ValueError("Missing zone comment was lost")
    fake.payload = payload
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".Id")
    ]
    resource.module.fetch(ctx, resource, getter)
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous hosted zones were accepted")
    fake.duplicate = False
    resource.rows.append(
        (
            "fixture-vpc",
            {"property": "Route53.HostedZone.VPCs[].VPCId", "value": "`vpc-12345678`"},
        )
    )
    resource.module.fetch(ctx, resource, getter)
    fake.wrong_vpc = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("Unmatched zone VPC membership was accepted")
    fake.wrong_vpc = False
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "route53.get_hosted_zone", "Name"
    )
    return items


class EC2NetworkCalls(DirectCalls):
    expected_inputs: dict[str, Any] | None = None
    collection = ""

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation) != ("ec2", self.operation) or (
            self.expected_inputs is not None and inputs != self.expected_inputs
        ):
            raise ValueError("EC2 selector or scope differs from fixture")
        return self.response(
            api,
            operation,
            {self.collection: [deepcopy(self.payload)] * (2 if self.duplicate else 1)},
        )


def ec2_network_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    getter = mapping.properties[properties[0]].field.getter
    tags = [{"Key": "Name", "Value": "fixture"}]
    if kind == "EC2.FlowLog":
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
            {"Name": "tag:Name", "Values": ["fixture"]},
            {"Name": "resource-id", "Values": ["vpc-12345678"]},
        ]
    elif kind == "EC2.TransitGatewayVpcAttachment":
        operation, collection, id_arg, id_prop = (
            "describe_transit_gateway_vpc_attachments",
            "TransitGatewayVpcAttachments",
            "TransitGatewayAttachmentIds",
            "TransitGatewayAttachmentId",
        )
        payload = {
            "TransitGatewayAttachmentId": "tgw-attach-12345678",
            "TransitGatewayId": "tgw-12345678",
            "VpcId": "vpc-12345678",
            "SubnetIds": ["subnet-12345678"],
        }
        cases = {
            name: (name, "typed" if name == "TransitGatewayId" else "id", value)
            for name, value in payload.items()
            if name != id_prop
        }
        cases["Id"] = (id_prop, "typed", payload[id_prop])
        filters = [
            {"Name": "vpc-id", "Values": [payload["VpcId"]]},
            {"Name": "transit-gateway-id", "Values": [payload["TransitGatewayId"]]},
        ]
    else:
        operation, collection, id_arg, id_prop = (
            "describe_vpc_endpoints",
            "VpcEndpoints",
            "VpcEndpointIds",
            "VpcEndpointId",
        )
        payload = {
            "VpcEndpointId": "vpce-12345678",
            "VpcId": "vpc-12345678",
            "ServiceName": "com.amazonaws.ap-northeast-1.s3",
            "VpcEndpointType": "Interface",
            "PrivateDnsEnabled": False,
            "DnsOptions": {"PrivateDnsOnlyForInboundResolverEndpoint": False},
            "IpAddressType": "ipv4",
            "PolicyDocument": json.dumps({"Version": "2012-10-17", "Statement": []}),
            "SubnetIds": ["subnet-12345678"],
            "RouteTableIds": ["rtb-12345678"],
            "Groups": [{"GroupId": "sg-12345678"}],
            "Tags": tags,
        }
        cases = {
            name: (
                name,
                "id" if name in {"VpcId", "SubnetIds", "RouteTableIds"} else "typed",
                value,
            )
            for name, value in payload.items()
            if name not in {id_prop, "PolicyDocument", "Groups", "Tags", "DnsOptions"}
        }
        cases.update(
            {
                "Id": (id_prop, "typed", payload[id_prop]),
                "PolicyDocument": (
                    "PolicyDocument",
                    "policy",
                    {"Version": "2012-10-17", "Statement": []},
                ),
                "SecurityGroupIds": ("Groups[].GroupId", "id", ["sg-12345678"]),
                "DnsOptions.PrivateDnsOnlyForInboundResolverEndpoint": (
                    "DnsOptions.PrivateDnsOnlyForInboundResolverEndpoint",
                    "typed",
                    "AllResolvers",
                ),
                "Tags[].Key": ("Tags[].Key", "typed", ["Name"]),
                "Tags[].Value": ("Tags[].Value", "typed", ["fixture"]),
            }
        )
        filters = [
            {"Name": "tag:Name", "Values": ["fixture"]},
            {"Name": "vpc-id", "Values": [payload["VpcId"]]},
            {"Name": "service-name", "Values": [payload["ServiceName"]]},
        ]
    ctx, fake = fixture_context(root, mapping.service, EC2NetworkCalls, payload)
    fake.api, fake.operation, fake.collection = "ec2", operation, collection
    if kind in ADAPTER_INVENTORIES:
        record = inventory.adapter_inventory(ctx, mapping.service, (kind,))[0]
    else:
        source = inventory.inventory_for(ctx)
        _, mapped = source.mapping(mapping.service)
        fake.typename, fake.identifier, fake.cloud_properties = (
            "AWS::EC2::VPCEndpoint",
            payload[id_prop],
            {"Id": payload[id_prop]},
        )
        record = source.cloud_record(
            mapping.service,
            kind,
            {
                "Identifier": fake.identifier,
                "Properties": json.dumps(fake.cloud_properties),
            },
            source.schema(kind),
            mapping,
            mapped,
        )
    resource = fixture_resource(root, ctx, mapping.service, record)
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
    if kind == "EC2.VPCEndpoint":
        fake.payload = {
            **payload,
            "DnsOptions": {"PrivateDnsOnlyForInboundResolverEndpoint": True},
        }
        clear_fetch(ctx)
        response = resource.module.fetch(ctx, resource, getter)
        if (
            response["DnsOptions"]["PrivateDnsOnlyForInboundResolverEndpoint"]
            != "OnlyInboundResolver"
        ):
            raise ValueError("Inbound-only DNS projection differs")
        fake.payload = payload
        clear_fetch(ctx)
    if kind == "EC2.FlowLog" and getter == "resource_type":
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
    if kind == "EC2.VPCEndpoint":
        resource.rows[:] = [
            row for row in resource.rows if ".Tags[]" not in row[1]["property"]
        ]
        resource.rows.extend(
            [
                (
                    "fixture-name-key",
                    {"property": kind + ".Tags[].Key", "value": "`Name`"},
                ),
                (
                    "fixture-name-value",
                    {"property": kind + ".Tags[].Value", "value": "`fixture`"},
                ),
            ]
        )
        for name in ("VpcId", "ServiceName"):
            if not resource.rows_for(name):
                resource.rows.append(
                    (
                        "fixture-" + name,
                        {
                            "property": kind + "." + name,
                            "value": cli.model_literal(payload[name]),
                        },
                    )
                )
    fake.expected_inputs = {"Filter" if kind == "EC2.FlowLog" else "Filters": filters}
    resource.module.fetch(ctx, resource, getter)
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous network resources were accepted")
    fake.duplicate = False
    clear_fetch(ctx)
    fake.error = cli.comparator().AcquisitionError("ec2." + operation, "AccessDenied")
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("Network API failure was swallowed")
    fake.error = None
    resource.rows[:] = []
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing network selectors were accepted")
    return items


class IAMPolicyCalls(FakeCalls):
    subject = ""
    getter = ""
    failure_operation = ""
    empty = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        subject = self.subject.lower()
        selector = self.subject + "Name"
        expected = (
            "list_attached_" + subject + "_policies"
            if self.getter == "attached"
            else "list_" + subject + "_policies"
        )
        if (api, operation, inputs) != ("iam", expected, {selector: "fixture"}):
            raise ValueError("IAM policy listing selector differs from fixture")
        if self.getter == "attached":
            values = (
                []
                if self.empty
                else [
                    {
                        "PolicyName": "fixture-policy",
                        "PolicyArn": "arn:aws:iam::123456789012:policy/fixture-policy",
                    }
                ]
            )
            return self.response(api, operation, {"AttachedPolicies": values})
        return self.response(
            api, operation, {"PolicyNames": [] if self.empty else ["fixture-policy"]}
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::IAM::" + self.subject, "Identifier": "fixture"},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": "fixture",
                        "Properties": json.dumps({self.subject + "Name": "fixture"}),
                    }
                },
            )
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        selector = self.subject + "Name"
        if (api, operation, inputs) != (
            "iam",
            "get_" + self.subject.lower() + "_policy",
            {selector: "fixture", "PolicyName": "fixture-policy"},
        ):
            raise ValueError("IAM policy detail selector differs from fixture")
        return self.response(
            api,
            operation,
            {
                selector: "fixture",
                "PolicyName": "fixture-policy",
                "PolicyDocument": json.dumps(
                    {"Version": "2012-10-17", "Statement": []}
                ),
            },
        )


class IAMManagedCalls(FakeCalls):
    failure_operation = ""
    duplicate = False
    empty_roles = False
    arn = "arn:aws:iam::123456789012:policy/fixture-policy"

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) == ("iam", "list_policies", {"Scope": "Local"}):
            policy = {
                "PolicyName": "fixture",
                "PolicyId": "ANPA12345678901234567",
                "Arn": self.arn,
                "DefaultVersionId": "v1",
                "Path": "/",
            }
            return self.response(
                api, operation, {"Policies": [policy] * (2 if self.duplicate else 1)}
            )
        if (api, operation, inputs) == (
            "iam",
            "list_entities_for_policy",
            {"PolicyArn": self.arn, "EntityFilter": "Role"},
        ):
            roles = (
                []
                if self.empty_roles
                else [{"RoleName": "fixture-role", "RoleId": "AROA12345678901234567"}]
            )
            return self.response(api, operation, {"PolicyRoles": roles})
        raise ValueError("IAM managed policy listing differs from fixture")

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::IAM::ManagedPolicy", "Identifier": self.arn},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": self.arn,
                        "Properties": json.dumps(
                            {"ManagedPolicyName": "fixture", "PolicyArn": self.arn}
                        ),
                    }
                },
            )
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) != (
            "iam",
            "get_policy_version",
            {"PolicyArn": self.arn, "VersionId": "v1"},
        ):
            raise ValueError("IAM policy version selector differs from fixture")
        return self.response(
            api,
            operation,
            {
                "PolicyVersion": {
                    "VersionId": "v1",
                    "IsDefaultVersion": True,
                    "Document": json.dumps({"Version": "2012-10-17", "Statement": []}),
                }
            },
        )


class S3ContractCalls(FakeCalls):
    operation = ""
    kind = ""
    failure_operation = ""
    duplicate = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) != ("s3", "list_buckets", {}):
            raise ValueError("S3 bucket inventory request differs from fixture")
        return self.response(
            api,
            operation,
            {
                "Buckets": [deepcopy(self.payload["bucket"])]
                * (2 if self.duplicate else 1)
            },
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::S3::" + self.kind, "Identifier": "fixture-bucket"},
        ):
            prop = "Bucket" if self.kind == "BucketPolicy" else "BucketName"
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": "fixture-bucket",
                        "Properties": json.dumps({prop: "fixture-bucket"}),
                    }
                },
            )
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) == ("sts", "get_caller_identity", {}):
            return self.response(
                api,
                operation,
                {
                    "Account": ACCOUNT,
                    "Arn": "arn:aws:iam::123456789012:user/fixture",
                    "UserId": "AIDA12345678901234567",
                },
            )
        if (api, operation, inputs) != (
            "s3",
            self.operation,
            {"Bucket": "fixture-bucket", "ExpectedBucketOwner": ACCOUNT},
        ):
            raise ValueError("S3 request differs from fixture")
        if operation == "get_bucket_location":
            location = self.payload["location"]
            return self.response(
                api,
                operation,
                {} if location is None else {"LocationConstraint": location},
            )
        return self.response(api, operation, deepcopy(self.payload))


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
    ctx.target["awsAccountId"] = "999999999999"
    try:
        inventory.sdk_inventory.collect(ctx, kind, parents=[parent])
    except ValueError as error:
        if "scope" not in str(error):
            raise
    else:
        raise ValueError("SQS queue account mismatch was accepted")
    ctx.target["awsAccountId"] = ACCOUNT
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


def s3_base_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = "S3.Bucket"
    payload = {
        "bucket": {
            "Name": "fixture-bucket",
            "BucketArn": "arn:aws:s3:::fixture-bucket",
        },
        "location": "ap-northeast-1",
    }
    ctx, fake = fixture_context(root, "s3", S3ContractCalls, payload)
    fake.operation, fake.kind = "get_bucket_location", "Bucket"
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("s3")
    record = source.cloud_record(
        "s3",
        kind,
        {
            "Identifier": "fixture-bucket",
            "Properties": json.dumps({"BucketName": "fixture-bucket"}),
        },
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "s3", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        {"BucketName": ("Name", "typed", "fixture-bucket")},
        [
            "normal",
            "missing-selector",
            "access-denied",
            "ambiguous",
            "region-default",
            "region-legacy",
            "arn-fallback",
        ],
    )
    expected = [
        ("s3", "list_buckets", {}),
        (
            "s3",
            "get_bucket_location",
            {"Bucket": "fixture-bucket", "ExpectedBucketOwner": ACCOUNT},
        ),
    ]
    if fake.calls != expected:
        raise ValueError("S3 bucket requests differ from fixture")
    for location, expected_region in ((None, "us-east-1"), ("EU", "eu-west-1")):
        fake.payload = {**payload, "location": location}
        result = resource.module.fetch(ctx, resource, "base")
        if result.get("BucketRegion") != expected_region:
            raise ValueError("S3 location normalization differs from fixture")
    fake.payload = {"bucket": {"Name": "fixture-bucket"}, "location": "ap-northeast-1"}
    result = resource.module.fetch(ctx, resource, "base")
    if result.get("BucketArn") != "arn:aws:s3:::fixture-bucket":
        raise ValueError("S3 ARN fallback differs from verified account partition")
    for operation in ("get_bucket_location", "get_caller_identity"):
        fake.error = cli.comparator().AcquisitionError(
            "s3." + operation, "AccessDenied"
        )
        fake.failure_operation = operation
        try:
            resource.module.fetch(ctx, resource, "base")
        except cli.comparator().AcquisitionError as error:
            if error.code != "AccessDenied":
                raise ValueError("S3 dependent API failure was changed") from error
        else:
            raise ValueError("S3 dependent API failure was swallowed")
    fake.error, fake.failure_operation, fake.payload = None, "", payload
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, "base")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Duplicate S3 bucket names were accepted")
    fake.duplicate = False
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "s3.list_buckets", "BucketName"
    )
    return items


def s3_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    getter = mapping.properties[properties[0]].field.getter
    configs = {
        "encryption": (
            "get_bucket_encryption",
            {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "aws:kms",
                                "KMSMasterKeyID": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                            },
                            "BucketKeyEnabled": True,
                        }
                    ]
                }
            },
            {
                "BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled": (
                    "ServerSideEncryptionConfiguration[].BucketKeyEnabled",
                    "typed",
                    [True],
                ),
                "BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID": (
                    "ServerSideEncryptionConfiguration[].ApplyServerSideEncryptionByDefault.KMSMasterKeyID",
                    "kms",
                    [
                        "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012"
                    ],
                ),
                "BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm": (
                    "ServerSideEncryptionConfiguration[].ApplyServerSideEncryptionByDefault.SSEAlgorithm",
                    "typed",
                    ["aws:kms"],
                ),
            },
            "ServerSideEncryptionConfigurationNotFoundError",
        ),
        "lifecycle": (
            "get_bucket_lifecycle_configuration",
            {
                "Rules": [
                    {
                        "ID": "expire",
                        "Status": "Enabled",
                        "Prefix": "logs/",
                        "Expiration": {"Days": 30},
                        "NoncurrentVersionExpiration": {"NoncurrentDays": 60},
                    }
                ]
            },
            {
                "LifecycleConfiguration.Rules[].ExpirationInDays": (
                    "Rules[].Expiration.Days",
                    "typed",
                    [30],
                ),
                "LifecycleConfiguration.Rules[].Id": (
                    "Rules[].ID",
                    "typed",
                    ["expire"],
                ),
                "LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NoncurrentDays": (
                    "Rules[].NoncurrentVersionExpiration.NoncurrentDays",
                    "typed",
                    [60],
                ),
                "LifecycleConfiguration.Rules[].Prefix": (
                    "Rules[].Prefix",
                    "typed",
                    ["logs/"],
                ),
                "LifecycleConfiguration.Rules[].Status": (
                    "Rules[].Status",
                    "typed",
                    ["Enabled"],
                ),
            },
            "NoSuchLifecycleConfiguration",
        ),
        "lock": (
            "get_object_lock_configuration",
            {
                "ObjectLockConfiguration": {
                    "ObjectLockEnabled": "Enabled",
                    "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 30}},
                }
            },
            {
                "ObjectLockEnabled": ("LockBoolean", "boolean", True),
                "ObjectLockConfiguration.ObjectLockEnabled": (
                    "ObjectLockConfiguration.ObjectLockEnabled",
                    "typed",
                    "Enabled",
                ),
                "ObjectLockConfiguration.Rule.DefaultRetention.Days": (
                    "ObjectLockConfiguration.Rule.DefaultRetention.Days",
                    "typed",
                    30,
                ),
                "ObjectLockConfiguration.Rule.DefaultRetention.Mode": (
                    "ObjectLockConfiguration.Rule.DefaultRetention.Mode",
                    "typed",
                    "GOVERNANCE",
                ),
            },
            "ObjectLockConfigurationNotFoundError",
        ),
        "versioning": (
            "get_bucket_versioning",
            {"Status": "Enabled"},
            {"VersioningConfiguration.Status": ("Status", "typed", "Enabled")},
            None,
        ),
        "public": (
            "get_public_access_block",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                }
            },
            {
                "PublicAccessBlockConfiguration." + name: (
                    "PublicAccessBlockConfiguration." + name,
                    "typed",
                    True,
                )
                for name in (
                    "BlockPublicAcls",
                    "BlockPublicPolicy",
                    "IgnorePublicAcls",
                    "RestrictPublicBuckets",
                )
            },
            "NoSuchPublicAccessBlockConfiguration",
        ),
        "ownership": (
            "get_bucket_ownership_controls",
            {
                "OwnershipControls": {
                    "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
                }
            },
            {
                "OwnershipControls.Rules[].ObjectOwnership": (
                    "OwnershipControls.Rules[].ObjectOwnership",
                    "typed",
                    ["BucketOwnerEnforced"],
                )
            },
            "OwnershipControlsNotFoundError",
        ),
        "policy": (
            "get_bucket_policy",
            {"Policy": json.dumps({"Version": "2012-10-17", "Statement": []})},
            {
                "PolicyDocument": (
                    "Policy",
                    "policy",
                    {"Version": "2012-10-17", "Statement": []},
                )
            },
            "NoSuchBucketPolicy",
        ),
    }
    operation, payload, cases, absent_error = configs[getter]
    ctx, fake = fixture_context(root, "s3", S3ContractCalls, payload)
    fake.operation, fake.kind = operation, kind.split(".")[1]
    prop = "Bucket" if fake.kind == "BucketPolicy" else "BucketName"
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("s3")
    cloud = {prop: "fixture-bucket"}
    record = source.cloud_record(
        "s3",
        kind,
        {"Identifier": "fixture-bucket", "Properties": json.dumps(cloud)},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "s3", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied"],
    )
    if fake.calls != [
        ("s3", operation, {"Bucket": "fixture-bucket", "ExpectedBucketOwner": ACCOUNT})
    ]:
        raise ValueError("S3 request differs from fixture")
    if getter == "lock":
        fake.payload = {"ObjectLockConfiguration": {}}
        clear_fetch(ctx)
        key = "S3.Bucket.ObjectLockEnabled"
        _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
        import_normalize(ctx, kind, key, raw, "boolean")
        if raw is not False:
            raise ValueError("Unenabled object lock was not false")
        if key in items and items[key]["status"] == "verified":
            items[key]["branches"].append("object-lock-not-enabled")
        fake.payload = payload
    if absent_error:
        fake.error = cli.comparator().AcquisitionError("s3." + operation, absent_error)
        clear_fetch(ctx)
        _, raw = mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
        if raw not in (cli.comparator().MISSING, []):
            raise ValueError("Absent S3 configuration was not preserved")
        fake.error = None
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("optional-configuration-absent")
    else:
        missing_values(ctx, fake, resource, mapping, items, payload)
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "s3." + operation, prop
    )
    return items


def iam_managed_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "IAM.ManagedPolicy"
    getter = mapping.properties[properties[0]].field.getter
    ctx, fake = fixture_context(root, "iam", IAMManagedCalls, {})
    cloud = {"ManagedPolicyName": "fixture", "PolicyArn": fake.arn}
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("iam")
    record = source.cloud_record(
        "iam",
        kind,
        {"Identifier": fake.arn, "Properties": json.dumps(cloud)},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "iam", record)
    cases = {
        "ManagedPolicyName": ("PolicyName", "typed", "fixture"),
        "PolicyDocument": (
            "Document",
            "policy",
            {"Version": "2012-10-17", "Statement": []},
        ),
        "Roles": ("Roles", "name", ["fixture-role"]),
    }
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied", "ambiguous-policy"],
    )
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Duplicate IAM managed policies were accepted")
    fake.duplicate = False
    if getter == "entities":
        fake.empty_roles = True
        clear_fetch(ctx)
        key = properties[0]
        _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
        if raw != []:
            raise ValueError("Empty IAM policy roles were not preserved")
        fake.empty_roles = False
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("empty-roles")
    if getter in {"document", "entities"}:
        fake.error = cli.comparator().AcquisitionError(
            "iam.policy-detail", "AccessDenied"
        )
        fake.failure_operation = (
            "get_policy_version" if getter == "document" else "list_entities_for_policy"
        )
        clear_fetch(ctx)
        try:
            mapping_value(
                ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
            )
        except cli.comparator().AcquisitionError as error:
            if error.code != "AccessDenied":
                raise ValueError(
                    "IAM managed policy detail failure was changed"
                ) from error
        else:
            raise ValueError("IAM managed policy detail failure was swallowed")
        fake.error, fake.failure_operation = None, ""
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("detail-access-denied")
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "iam.list_policies",
        "ManagedPolicyName",
    )
    return items


def iam_policy_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    subject = kind.split(".")[1]
    getter = mapping.properties[properties[0]].field.getter
    ctx, fake = fixture_context(root, "iam", IAMPolicyCalls, {})
    fake.subject, fake.getter = subject, getter
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("iam")
    cloud = {subject + "Name": "fixture"}
    record = source.cloud_record(
        "iam",
        kind,
        {"Identifier": "fixture", "Properties": json.dumps(cloud)},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "iam", record)
    policy = {"Version": "2012-10-17", "Statement": []}
    cases = (
        {
            "ManagedPolicyArns": (
                "Arns",
                "arn",
                ["arn:aws:iam::123456789012:policy/fixture-policy"],
            )
        }
        if getter == "attached"
        else {
            "Policies[].PolicyName": (
                "Policies[].PolicyName",
                "typed",
                ["fixture-policy"],
            ),
            "Policies[].PolicyDocument": (
                "Policies[].PolicyDocument",
                "policy",
                [policy],
            ),
        }
    )
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied", "empty"],
    )
    fake.empty = True
    clear_fetch(ctx)
    for key, item in items.items():
        if item["status"] != "verified":
            continue
        _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
        if raw != []:
            item.update(
                status="broken", reason="Empty IAM policy list was not preserved"
            )
    fake.empty = False
    if getter == "inline":
        fake.error = cli.comparator().AcquisitionError("iam.get_policy", "AccessDenied")
        fake.failure_operation = "get_" + subject.lower() + "_policy"
        clear_fetch(ctx)
        try:
            mapping_value(
                ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
            )
        except cli.comparator().AcquisitionError as error:
            if error.code != "AccessDenied":
                raise ValueError("IAM policy detail failure was changed") from error
        else:
            raise ValueError("IAM policy detail failure was swallowed")
        fake.error, fake.failure_operation = None, ""
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("detail-access-denied")
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "iam.policy-list", subject + "Name"
    )
    return items


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    extra_inputs = {}
    if kind == "CloudTrail.Trail":
        getter = mapping.properties[properties[0]].field.getter
        service, api, selector = "cloudtrail", "cloudtrail", "TrailName"
        cloud = {"TrailName": "fixture"}
        operation, argument, envelope = {
            "base": ("get_trail", "Name", "Trail"),
            "status": ("get_trail_status", "Name", "$"),
            "selectors": ("get_event_selectors", "TrailName", "$"),
        }[getter]
        if getter == "base":
            payload = {
                "Name": "fixture",
                "S3BucketName": "fixture-trail-logs",
                "IncludeGlobalServiceEvents": True,
                "IsMultiRegionTrail": False,
                "LogFileValidationEnabled": True,
                "CloudWatchLogsLogGroupArn": "arn:aws:logs:ap-northeast-1:123456789012:log-group:fixture",
                "CloudWatchLogsRoleArn": "arn:aws:iam::123456789012:role/fixture",
                "KmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
            }
            cases = {
                "TrailName": ("Name", "typed", "fixture"),
                "S3BucketName": ("S3BucketName", "name", "fixture-trail-logs"),
                "IncludeGlobalServiceEvents": (
                    "IncludeGlobalServiceEvents",
                    "typed",
                    True,
                ),
                "IsMultiRegionTrail": ("IsMultiRegionTrail", "typed", False),
                "EnableLogFileValidation": ("LogFileValidationEnabled", "typed", True),
                "CloudWatchLogsLogGroupArn": (
                    "CloudWatchLogsLogGroupArn",
                    "log_group_arn",
                    payload["CloudWatchLogsLogGroupArn"],
                ),
                "CloudWatchLogsRoleArn": (
                    "CloudWatchLogsRoleArn",
                    "arn",
                    payload["CloudWatchLogsRoleArn"],
                ),
                "KMSKeyId": ("KmsKeyId", "kms", payload["KmsKeyId"]),
            }
        elif getter == "status":
            payload = {"IsLogging": True}
            cases = {"IsLogging": ("IsLogging", "typed", True)}
        else:
            payload = {
                "EventSelectors": [
                    {
                        "ReadWriteType": "All",
                        "IncludeManagementEvents": True,
                        "DataResources": [
                            {
                                "Type": "AWS::S3::Object",
                                "Values": ["arn:aws:s3:::fixture/"],
                            }
                        ],
                    }
                ]
            }
            cases = {
                "EventSelectors[].ReadWriteType": (
                    "EventSelectors[].ReadWriteType",
                    "typed",
                    ["All"],
                ),
                "EventSelectors[].IncludeManagementEvents": (
                    "EventSelectors[].IncludeManagementEvents",
                    "typed",
                    [True],
                ),
                "EventSelectors[].DataResources[].Type": (
                    "EventSelectors[].DataResources[].Type",
                    "typed",
                    [["AWS::S3::Object"]],
                ),
                "EventSelectors[].DataResources[].Values": (
                    "EventSelectors[].DataResources[].Values",
                    "arn",
                    [[["arn:aws:s3:::fixture/"]]],
                ),
            }
    elif kind in {"Glue.Job", "Glue.SecurityConfiguration"}:
        service, api, selector = "glue", "glue", "Name"
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
        service, api, operation, selector, argument, envelope = (
            "glue",
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
            "FederatedCatalog": {"ConnectionName": "fixture-connection"},
        }
        cases = {
            "CatalogId": ("CatalogId", "typed", "fixture"),
            "Name": ("Name", "typed", "fixture"),
            "FederatedCatalog.ConnectionName": (
                "FederatedCatalog.ConnectionName",
                "typed",
                "fixture-connection",
            ),
        }
    elif kind in {"Glue.Connection", "Glue.Database", "Glue.Table"}:
        service, api = "glue", "glue"
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
    elif kind == "CodePipeline.Pipeline":
        service, api, operation, selector, argument, envelope = (
            "codepipeline",
            "codepipeline",
            "get_pipeline",
            "Name",
            "name",
            "pipeline",
        )
        cloud = {"Name": "fixture"}
        key = "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012"
        payload = {
            "name": "fixture",
            "roleArn": "arn:aws:iam::123456789012:role/fixture",
            "artifactStore": {
                "type": "S3",
                "location": "fixture-artifacts",
                "encryptionKey": {"id": key, "type": "KMS"},
            },
            "executionMode": "SUPERSEDED",
            "pipelineType": "V2",
            "variables": [{"name": "fixture-variable"}],
            "stages": [
                {
                    "name": "Source",
                    "actions": [
                        {
                            "name": "Source",
                            "actionTypeId": {
                                "category": "Source",
                                "owner": "AWS",
                                "provider": "CodeCommit",
                                "version": "1",
                            },
                            "runOrder": 1,
                            "configuration": {"RepositoryName": "fixture"},
                            "inputArtifacts": [{"name": "input"}],
                            "outputArtifacts": [{"name": "output"}],
                            "environmentVariables": [
                                {
                                    "name": "FIXTURE",
                                    "type": "PLAINTEXT",
                                    "value": "fixture",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        cases = {
            "Name": ("name", "typed", "fixture"),
            "RoleArn": ("roleArn", "arn", payload["roleArn"]),
            "ArtifactStore.Type": ("artifactStore.type", "typed", "S3"),
            "ArtifactStore.Location": (
                "artifactStore.location",
                "name",
                "fixture-artifacts",
            ),
            "ArtifactStore.EncryptionKey.Id": (
                "artifactStore.encryptionKey.id",
                "kms",
                key,
            ),
            "ArtifactStore.EncryptionKey.Type": (
                "artifactStore.encryptionKey.type",
                "typed",
                "KMS",
            ),
            "ExecutionMode": ("executionMode", "typed", "SUPERSEDED"),
            "PipelineType": ("pipelineType", "typed", "V2"),
            "Stages[].Name": ("stages[].name", "typed", ["Source"]),
            "Variables[].Name": ("variables[].name", "typed", ["fixture-variable"]),
        }
        for name, value in {
            "Category": "Source",
            "Owner": "AWS",
            "Provider": "CodeCommit",
            "Version": "1",
        }.items():
            cases["Stages[].Actions[].ActionTypeId." + name] = (
                "stages[].actions[].actionTypeId." + name[0].lower() + name[1:],
                "string" if name == "Version" else "typed",
                [[value]],
            )
        cases.update(
            {
                "Stages[].Actions[].Name": (
                    "stages[].actions[].name",
                    "typed",
                    [["Source"]],
                ),
                "Stages[].Actions[].RunOrder": (
                    "stages[].actions[].runOrder",
                    "typed",
                    [[1]],
                ),
                "Stages[].Actions[].InputArtifacts[].Name": (
                    "stages[].actions[].inputArtifacts[].name",
                    "typed",
                    [[["input"]]],
                ),
                "Stages[].Actions[].OutputArtifacts[].Name": (
                    "stages[].actions[].outputArtifacts[].name",
                    "typed",
                    [[["output"]]],
                ),
                "Stages[].Actions[].EnvironmentVariables[].Name": (
                    "stages[].actions[].environmentVariables[].name",
                    "typed",
                    [[["FIXTURE"]]],
                ),
                "Stages[].Actions[].EnvironmentVariables[].Type": (
                    "stages[].actions[].environmentVariables[].type",
                    "typed",
                    [[["PLAINTEXT"]]],
                ),
            }
        )
    elif kind == "Athena.WorkGroup":
        service, api, operation, selector, argument, envelope = (
            "athena",
            "athena",
            "get_work_group",
            "Name",
            "WorkGroup",
            "WorkGroup",
        )
        cloud = {"Name": "fixture"}
        payload = {
            "Name": "fixture",
            "State": "ENABLED",
            "Description": "fixture workgroup",
            "Configuration": {
                "EnforceWorkGroupConfiguration": True,
                "EngineVersion": {"SelectedEngineVersion": "Athena engine version 3"},
                "PublishCloudWatchMetricsEnabled": True,
                "RequesterPaysEnabled": False,
                "ResultConfiguration": {
                    "OutputLocation": "s3://fixture-results/",
                    "ExpectedBucketOwner": ACCOUNT,
                    "EncryptionConfiguration": {
                        "EncryptionOption": "SSE_KMS",
                        "KmsKey": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                    },
                },
            },
        }
        cases = {
            "Name": ("Name", "typed", "fixture"),
            "Description": ("Description", "typed", "fixture workgroup"),
            "State": ("State", "typed", "ENABLED"),
            "WorkGroupConfiguration.EnforceWorkGroupConfiguration": (
                "Configuration.EnforceWorkGroupConfiguration",
                "typed",
                True,
            ),
            "WorkGroupConfiguration.EngineVersion.SelectedEngineVersion": (
                "Configuration.EngineVersion.SelectedEngineVersion",
                "typed",
                "Athena engine version 3",
            ),
            "WorkGroupConfiguration.PublishCloudWatchMetricsEnabled": (
                "Configuration.PublishCloudWatchMetricsEnabled",
                "typed",
                True,
            ),
            "WorkGroupConfiguration.RequesterPaysEnabled": (
                "Configuration.RequesterPaysEnabled",
                "typed",
                False,
            ),
            "WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.EncryptionOption": (
                "Configuration.ResultConfiguration.EncryptionConfiguration.EncryptionOption",
                "typed",
                "SSE_KMS",
            ),
            "WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey": (
                "Configuration.ResultConfiguration.EncryptionConfiguration.KmsKey",
                "kms",
                payload["Configuration"]["ResultConfiguration"][
                    "EncryptionConfiguration"
                ]["KmsKey"],
            ),
            "WorkGroupConfiguration.ResultConfiguration.ExpectedBucketOwner": (
                "Configuration.ResultConfiguration.ExpectedBucketOwner",
                "typed",
                ACCOUNT,
            ),
            "WorkGroupConfiguration.ResultConfiguration.OutputLocation": (
                "Configuration.ResultConfiguration.OutputLocation",
                "typed",
                "s3://fixture-results/",
            ),
        }
    elif kind == "SecretsManager.Secret":
        service, api, operation, selector, argument, envelope = (
            "secrets-manager",
            "secretsmanager",
            "describe_secret",
            "Name",
            "SecretId",
            "$",
        )
        cloud = {
            "Name": "fixture",
            "Id": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:fixture-AbCdEf",
        }
        payload = {
            "ARN": cloud["Id"],
            "Name": "fixture",
            "Type": "fixture-partner",
            "Description": "fixture secret metadata",
            "KmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
        }
        cases = {
            "Name": ("Name", "typed", "fixture"),
            "Type": ("Type", "typed", "fixture-partner"),
            "Description": ("Description", "typed", "fixture secret metadata"),
            "KmsKeyId": ("KmsKeyId", "kms", payload["KmsKeyId"]),
        }
    elif kind in {"IAM.InstanceProfile", "IAM.Role", "IAM.User"}:
        service, api = "iam", "iam"
        item = kind.split(".")[1]
        selector = {
            "InstanceProfile": "InstanceProfileName",
            "Role": "RoleName",
            "User": "UserName",
        }[item]
        operation = {
            "InstanceProfile": "get_instance_profile",
            "Role": "get_role",
            "User": "get_user",
        }[item]
        argument, envelope = selector, item
        cloud = {selector: "fixture"}
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if item == "InstanceProfile":
            role = {
                "Path": "/",
                "RoleName": "fixture-role",
                "RoleId": "AROA12345678901234567",
                "Arn": "arn:aws:iam::123456789012:role/fixture-role",
                "CreateDate": stamp,
            }
            payload = {
                "Path": "/",
                "InstanceProfileName": "fixture",
                "InstanceProfileId": "AIPA12345678901234567",
                "Arn": "arn:aws:iam::123456789012:instance-profile/fixture",
                "CreateDate": stamp,
                "Roles": [role],
            }
            cases = {
                "InstanceProfileName": ("InstanceProfileName", "typed", "fixture"),
                "Roles": ("Roles[].RoleName", "name", ["fixture-role"]),
            }
        elif item == "Role":
            policy = {"Version": "2012-10-17", "Statement": []}
            payload = {
                "Path": "/",
                "RoleName": "fixture",
                "RoleId": "AROA12345678901234567",
                "Arn": "arn:aws:iam::123456789012:role/fixture",
                "CreateDate": stamp,
                "Description": "fixture role",
                "AssumeRolePolicyDocument": json.dumps(policy),
            }
            cases = {
                "RoleName": ("RoleName", "typed", "fixture"),
                "Description": ("Description", "typed", "fixture role"),
                "AssumeRolePolicyDocument": (
                    "AssumeRolePolicyDocument",
                    "policy",
                    policy,
                ),
            }
        else:
            payload = {
                "Path": "/",
                "UserName": "fixture",
                "UserId": "AIDA12345678901234567",
                "Arn": "arn:aws:iam::123456789012:user/fixture",
                "CreateDate": stamp,
            }
            cases = {"UserName": ("UserName", "typed", "fixture")}
    elif kind == "Events.Rule":
        service, api, selector, envelope = "eventbridge", "events", "Name", "$"
        getter = mapping.properties[properties[0]].field.getter
        operation = "describe_rule" if getter == "base" else "list_targets_by_rule"
        argument = "Name" if getter == "base" else "Rule"
        cloud = {
            "Name": "fixture",
            "Arn": "arn:aws:events:ap-northeast-1:123456789012:rule/fixture",
        }
        if getter == "base":
            payload = {
                "Name": "fixture",
                "State": "ENABLED",
                "EventBusName": "default",
                "EventPattern": '{"source":["fixture.event"]}',
            }
            cases = {
                "Name": ("Name", "typed", "fixture"),
                "State": ("State", "typed", "ENABLED"),
                "EventBusName": ("EventBusName", "typed", "default"),
                "EventPattern": ("EventPattern", "json", {"source": ["fixture.event"]}),
            }
        else:
            payload = {
                "Targets": [
                    {
                        "Id": "target",
                        "Arn": "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture",
                        "DeadLetterConfig": {
                            "Arn": "arn:aws:sqs:ap-northeast-1:123456789012:fixture"
                        },
                        "RetryPolicy": {
                            "MaximumEventAgeInSeconds": 3600,
                            "MaximumRetryAttempts": 3,
                        },
                    }
                ]
            }
            cases = {
                "Targets[].Id": ("Targets[].Id", "typed", ["target"]),
                "Targets[].Arn": (
                    "Targets[].Arn",
                    "arn",
                    ["arn:aws:lambda:ap-northeast-1:123456789012:function:fixture"],
                ),
                "Targets[].DeadLetterConfig.Arn": (
                    "Targets[].DeadLetterConfig.Arn",
                    "arn",
                    ["arn:aws:sqs:ap-northeast-1:123456789012:fixture"],
                ),
                "Targets[].RetryPolicy.MaximumEventAgeInSeconds": (
                    "Targets[].RetryPolicy.MaximumEventAgeInSeconds",
                    "typed",
                    [3600],
                ),
                "Targets[].RetryPolicy.MaximumRetryAttempts": (
                    "Targets[].RetryPolicy.MaximumRetryAttempts",
                    "typed",
                    [3],
                ),
            }
    elif kind == "Scheduler.Schedule":
        service, api, operation, selector, argument, envelope = (
            "eventbridge",
            "scheduler",
            "get_schedule",
            "Name",
            "Name",
            "$",
        )
        cloud = {"Name": "fixture"}
        payload = {
            "Name": "fixture",
            "State": "ENABLED",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "ScheduleExpression": "rate(1 hour)",
            "ScheduleExpressionTimezone": "UTC",
            "Target": {
                "Arn": "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture",
                "RoleArn": "arn:aws:iam::123456789012:role/fixture",
            },
        }
        cases = {
            "Name": ("Name", "typed", "fixture"),
            "State": ("State", "typed", "ENABLED"),
            "FlexibleTimeWindow.Mode": ("FlexibleTimeWindow.Mode", "typed", "OFF"),
            "ScheduleExpression": ("ScheduleExpression", "typed", "rate(1 hour)"),
            "ScheduleExpressionTimezone": (
                "ScheduleExpressionTimezone",
                "typed",
                "UTC",
            ),
            "Target.Arn": ("Target.Arn", "arn", payload["Target"]["Arn"]),
            "Target.RoleArn": ("Target.RoleArn", "arn", payload["Target"]["RoleArn"]),
        }
    elif kind == "Lambda.Function":
        service, api, operation, selector, argument, envelope = (
            "lambda",
            "lambda",
            "get_function_recursion_config"
            if properties[0].endswith(".RecursiveLoop")
            else "get_function",
            "FunctionName",
            "FunctionName",
            "$",
        )
        cloud = {"FunctionName": "fixture"}
        if operation == "get_function_recursion_config":
            payload = {"RecursiveLoop": "Allow"}
            cases = {"RecursiveLoop": ("RecursiveLoop", "typed", "Allow")}
        else:
            payload = {
                "Configuration": {
                    "FunctionName": "fixture",
                    "Architectures": ["x86_64"],
                    "EphemeralStorage": {"Size": 512},
                    "Handler": "handler.main",
                    "LoggingConfig": {
                        "LogFormat": "JSON",
                        "LogGroup": "/aws/lambda/fixture",
                    },
                    "MemorySize": 128,
                    "PackageType": "Zip",
                    "Role": "arn:aws:iam::123456789012:role/fixture",
                    "Runtime": "python3.12",
                    "Timeout": 30,
                    "TracingConfig": {"Mode": "Active"},
                    "VpcConfig": {
                        "Ipv6AllowedForDualStack": False,
                        "SecurityGroupIds": ["sg-12345678"],
                        "SubnetIds": ["subnet-12345678", "subnet-87654321"],
                    },
                },
                "Code": {
                    "ResolvedS3Object": {
                        "S3Bucket": "fixture-code",
                        "S3Key": "handler.zip",
                    }
                },
                "Concurrency": {"ReservedConcurrentExecutions": 5},
            }
            cases = {
                name: (
                    "Configuration." + name,
                    "arn" if name == "Role" else "typed",
                    value,
                )
                for name, value in payload["Configuration"].items()
                if name
                not in {
                    "EphemeralStorage",
                    "LoggingConfig",
                    "TracingConfig",
                    "VpcConfig",
                }
            }
            for section in (
                "EphemeralStorage",
                "LoggingConfig",
                "TracingConfig",
                "VpcConfig",
            ):
                for name, value in payload["Configuration"][section].items():
                    key = section + "." + name
                    cases[key] = (
                        "Configuration." + key,
                        "id"
                        if name in {"SecurityGroupIds", "SubnetIds"}
                        else "name"
                        if name == "LogGroup"
                        else "typed",
                        value,
                    )
            cases.update(
                {
                    "Code.S3Bucket": (
                        "Code.ResolvedS3Object.S3Bucket",
                        "name",
                        "fixture-code",
                    ),
                    "Code.S3Key": (
                        "Code.ResolvedS3Object.S3Key",
                        "typed",
                        "handler.zip",
                    ),
                    "ReservedConcurrentExecutions": (
                        "Concurrency.ReservedConcurrentExecutions",
                        "typed",
                        5,
                    ),
                }
            )
    elif kind == "MWAA.Environment":
        service, api, operation, selector, argument, envelope = (
            "mwaa",
            "mwaa",
            "get_environment",
            "Name",
            "Name",
            "Environment",
        )
        cloud = {"Name": "fixture"}
        payload = {
            "Name": "fixture",
            "AirflowVersion": "2.10.3",
            "DagS3Path": "dags",
            "EndpointManagement": "SERVICE",
            "EnvironmentClass": "mw1.small",
            "ExecutionRoleArn": "arn:aws:iam::123456789012:role/fixture",
            "KmsKey": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
            "LoggingConfiguration": {
                name: {"Enabled": True, "LogLevel": "INFO"}
                for name in (
                    "DagProcessingLogs",
                    "SchedulerLogs",
                    "TaskLogs",
                    "WebserverLogs",
                    "WorkerLogs",
                )
            },
            "MaxWebservers": 2,
            "MaxWorkers": 3,
            "MinWebservers": 1,
            "MinWorkers": 1,
            "NetworkConfiguration": {
                "SecurityGroupIds": ["sg-12345678"],
                "SubnetIds": ["subnet-12345678", "subnet-87654321"],
            },
            "RequirementsS3Path": "requirements.txt",
            "Schedulers": 2,
            "SourceBucketArn": "arn:aws:s3:::fixture-bucket",
            "WebserverAccessMode": "PRIVATE_ONLY",
        }
        cases = {
            name: (
                name,
                "kms"
                if name == "KmsKey"
                else "arn"
                if name.endswith("Arn")
                else "typed",
                value,
            )
            for name, value in payload.items()
            if name not in {"LoggingConfiguration", "NetworkConfiguration"}
        }
        for name, values in payload["LoggingConfiguration"].items():
            for field, value in values.items():
                path = "LoggingConfiguration." + name + "." + field
                cases[path] = (path, "typed", value)
        for name, value in payload["NetworkConfiguration"].items():
            path = "NetworkConfiguration." + name
            cases[path] = (path, "id", value)
    else:
        service, api, operation, selector, argument, envelope = (
            "codecommit",
            "codecommit",
            "get_repository",
            "RepositoryName",
            "repositoryName",
            "repositoryMetadata",
        )
        cloud = {"RepositoryName": "fixture", "RepositoryId": "fixture-id"}
        payload = {
            "repositoryName": "fixture",
            "repositoryId": "fixture-id",
            "repositoryDescription": "fixture repository",
            "kmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
        }
        cases = {
            "RepositoryName": ("repositoryName", "typed", "fixture"),
            "RepositoryDescription": (
                "repositoryDescription",
                "typed",
                "fixture repository",
            ),
            "KmsKeyId": ("kmsKeyId", "kms", payload["kmsKeyId"]),
        }
    ctx, fake = fixture_context(root, service, DirectCalls, payload)
    fake.api, fake.operation, fake.inputs, fake.envelope = (
        api,
        operation,
        {
            argument: "fixture",
            **extra_inputs,
            **({"EventBusName": "default"} if kind == "Events.Rule" else {}),
        },
        envelope,
    )
    fake.typename, fake.cloud_properties, fake.identifier = (
        "AWS::" + kind.replace(".", "::"),
        cloud,
        "fixture-id"
        if service == "codecommit"
        else cloud.get("Arn", cloud.get("Id", "fixture")),
    )
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping(service)
    record = (
        inventory.sdk_inventory.record(
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
        if kind == "Glue.Table"
        else source.cloud_record(
            service,
            kind,
            {"Identifier": fake.identifier, "Properties": json.dumps(cloud)},
            source.schema(kind),
            mapping,
            mapped,
        )
    )
    resource = fixture_resource(root, ctx, service, record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied"],
    )
    if not fake.calls:
        return items
    if fake.calls != [(api, operation, fake.inputs)]:
        raise ValueError("SDK request differs from fixture: " + str(fake.calls))
    missing_values(
        ctx,
        fake,
        resource,
        mapping,
        items,
        payload,
        required=("name", "roleArn", "stages")
        if kind == "CodePipeline.Pipeline"
        else ("Name", "repositoryName", "FlexibleTimeWindow", "Target")
        if kind == "Scheduler.Schedule"
        else (
            "Name",
            "repositoryName",
            "InstanceProfileName",
            "RoleName",
            "UserName",
            "Roles",
        ),
    )
    if kind == "Events.Rule":
        resource.rows.append(
            (
                "fixture-999",
                {"property": "Events.Rule.EventBusName", "value": "`custom-bus`"},
            )
        )
        fake.inputs = {argument: "fixture", "EventBusName": "custom-bus"}
        if getter == "base":
            fake.payload = {**payload, "EventBusName": "custom-bus"}
        fake.calls.clear()
        response = resource.module.fetch(ctx, resource, getter)
        if fake.calls != [(api, operation, fake.inputs)]:
            raise ValueError("Explicit event bus request differs from fixture")
        if getter == "base" and response.get("EventBusName") != "custom-bus":
            raise ValueError("Explicit event bus response differs from fixture")
        resource.rows[:] = [row for row in resource.rows if row[0] != "fixture-999"]
        fake.inputs = {argument: "fixture", "EventBusName": "default"}
        fake.payload = payload
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("explicit-event-bus")
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


def securityhub_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    payload = {
        "HubArn": "arn:aws:securityhub:ap-northeast-1:123456789012:hub/default",
        "SubscribedAt": "2026-01-01T00:00:00Z",
        "AutoEnableControls": True,
        "ControlFindingGenerator": "STANDARD_CONTROL",
    }
    cases = {
        "AutoEnableControls": ("AutoEnableControls", "typed", True),
        "ControlFindingGenerator": (
            "ControlFindingGenerator",
            "typed",
            "STANDARD_CONTROL",
        ),
    }
    ctx, fake = fixture_context(root, "security-hub", SecurityHubCalls, payload)
    record = inventory.adapter_inventory(ctx, "security-hub", ("SecurityHub.Hub",))[0]
    resource = fixture_resource(root, ctx, "security-hub", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "SecurityHub.Hub",
        cases,
        ["normal", "access-denied"],
    )
    if fake.calls != [("securityhub", "describe_hub", {})]:
        raise ValueError("Security Hub request differs from fixture")
    missing_values(ctx, fake, resource, mapping, items, payload)
    fake.error = cli.comparator().AcquisitionError(
        "securityhub.describe_hub", "AccessDenied"
    )
    clear_fetch(ctx)
    try:
        mapping_value(
            ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
        )
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("API failure was changed") from error
    else:
        raise ValueError("API failure was swallowed")
    return items


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


class CodeBuildCalls(FakeCalls):
    duplicate = False
    empty = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("codebuild", "list_projects", {}):
            raise ValueError("CodeBuild inventory request differs from fixture")
        return self.response(api, operation, {"projects": ["fixture"]})

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != (
            "codebuild",
            "batch_get_projects",
            {"names": ["fixture"]},
        ):
            raise ValueError("CodeBuild project selector differs from fixture")
        projects = (
            []
            if self.empty
            else [deepcopy(self.payload)] * (2 if self.duplicate else 1)
        )
        return self.response(api, operation, {"projects": projects})


def codebuild_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "CodeBuild.Project"
    payload = {
        "name": "fixture",
        "source": {
            "type": "CODECOMMIT",
            "location": "https://git-codecommit.ap-northeast-1.amazonaws.com/v1/repos/fixture",
        },
        "artifacts": {"type": "NO_ARTIFACTS"},
        "cache": {"type": "NO_CACHE"},
        "concurrentBuildLimit": 5,
        "environment": {
            "computeType": "BUILD_GENERAL1_SMALL",
            "image": "aws/codebuild/standard:7.0",
            "imagePullCredentialsType": "CODEBUILD",
            "privilegedMode": False,
            "type": "LINUX_CONTAINER",
            "environmentVariables": [
                {"name": "CONFIG", "value": "example", "type": "PLAINTEXT"}
            ],
        },
        "logsConfig": {
            "cloudWatchLogs": {
                "groupName": "/aws/codebuild/fixture",
                "status": "ENABLED",
            },
            "s3Logs": {"status": "DISABLED"},
        },
        "queuedTimeoutInMinutes": 60,
        "serviceRole": "arn:aws:iam::123456789012:role/fixture",
        "timeoutInMinutes": 30,
        "vpcConfig": {
            "vpcId": "vpc-12345678",
            "subnets": ["subnet-12345678", "subnet-87654321"],
            "securityGroupIds": ["sg-12345678"],
        },
    }
    cases = {
        "Name": ("name", "typed", "fixture"),
        "Id": ("name", "typed", "fixture"),
        "Artifacts.Type": ("artifacts.type", "typed", "NO_ARTIFACTS"),
        "Cache.Type": ("cache.type", "typed", "NO_CACHE"),
        "ConcurrentBuildLimit": ("concurrentBuildLimit", "typed", 5),
        "Environment.ComputeType": (
            "environment.computeType",
            "typed",
            "BUILD_GENERAL1_SMALL",
        ),
        "Environment.EnvironmentVariables[].Name": (
            "environment.environmentVariables[].name",
            "typed",
            ["CONFIG"],
        ),
        "Environment.EnvironmentVariables[].Type": (
            "environment.environmentVariables[].type",
            "typed",
            ["PLAINTEXT"],
        ),
        "Environment.Image": (
            "environment.image",
            "typed",
            "aws/codebuild/standard:7.0",
        ),
        "Environment.ImagePullCredentialsType": (
            "environment.imagePullCredentialsType",
            "typed",
            "CODEBUILD",
        ),
        "Environment.PrivilegedMode": ("environment.privilegedMode", "typed", False),
        "Environment.Type": ("environment.type", "typed", "LINUX_CONTAINER"),
        "LogsConfig.CloudWatchLogs.GroupName": (
            "logsConfig.cloudWatchLogs.groupName",
            "typed",
            "/aws/codebuild/fixture",
        ),
        "LogsConfig.CloudWatchLogs.Status": (
            "logsConfig.cloudWatchLogs.status",
            "typed",
            "ENABLED",
        ),
        "LogsConfig.S3Logs.Status": ("logsConfig.s3Logs.status", "typed", "DISABLED"),
        "QueuedTimeoutInMinutes": ("queuedTimeoutInMinutes", "typed", 60),
        "ServiceRole": ("serviceRole", "arn", payload["serviceRole"]),
        "Source.Type": ("source.type", "typed", "CODECOMMIT"),
        "TimeoutInMinutes": ("timeoutInMinutes", "typed", 30),
        "VpcConfig.SecurityGroupIds": (
            "vpcConfig.securityGroupIds",
            "id",
            ["sg-12345678"],
        ),
        "VpcConfig.Subnets": (
            "vpcConfig.subnets",
            "id",
            ["subnet-12345678", "subnet-87654321"],
        ),
        "VpcConfig.VpcId": ("vpcConfig.vpcId", "id", "vpc-12345678"),
    }
    ctx, fake = fixture_context(root, "codebuild", CodeBuildCalls, payload)
    record = inventory.adapter_inventory(ctx, "codebuild", (kind,))[0]
    resource = fixture_resource(root, ctx, "codebuild", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied", "missing-project", "ambiguous"],
    )
    if fake.calls != [("codebuild", "batch_get_projects", {"names": ["fixture"]})]:
        raise ValueError("CodeBuild request differs from fixture")
    missing_values(
        ctx,
        fake,
        resource,
        mapping,
        items,
        payload,
        required=("name", "source", "artifacts", "environment", "serviceRole"),
    )
    for mode in ("empty", "duplicate"):
        setattr(fake, mode, True)
        clear_fetch(ctx)
        try:
            mapping_value(
                ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
            )
        except (
            cli.comparator().AcquisitionError,
            cli.comparator().Unresolved,
        ) as error:
            if mode == "empty" and (
                not isinstance(error, cli.comparator().AcquisitionError)
                or error.status != "resource_missing"
            ):
                raise ValueError(
                    "Missing CodeBuild project failure was changed"
                ) from error
            if mode == "duplicate" and not isinstance(
                error, cli.comparator().Unresolved
            ):
                raise ValueError(
                    "Ambiguous CodeBuild project failure was changed"
                ) from error
        else:
            raise ValueError("Missing or ambiguous CodeBuild project was accepted")
        setattr(fake, mode, False)
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "codebuild.batch_get_projects",
        "Name",
    )
    return items


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


def logs_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    payload = {
        "logGroupName": "fixture",
        "logGroupClass": "STANDARD",
        "retentionInDays": 30,
        "deletionProtectionEnabled": True,
        "kmsKeyId": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
    }
    cases = {
        "LogGroupName": ("logGroupName", "typed", "fixture"),
        "LogGroupClass": ("logGroupClass", "typed", "STANDARD"),
        "RetentionInDays": ("retentionInDays", "typed", 30),
        "DeletionProtectionEnabled": ("deletionProtectionEnabled", "typed", True),
        "KmsKeyId": ("kmsKeyId", "kms", payload["kmsKeyId"]),
    }
    ctx, fake = fixture_context(root, "cloudwatch-logs", LogsCalls, payload)
    record = inventory.adapter_inventory(ctx, "cloudwatch-logs", ("Logs.LogGroup",))[0]
    resource = fixture_resource(root, ctx, "cloudwatch-logs", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "Logs.LogGroup",
        cases,
        ["normal", "missing-selector", "access-denied", "ambiguous"],
    )
    if fake.calls != [
        ("logs", "describe_log_groups", {"logGroupNamePrefix": "fixture"})
    ]:
        raise ValueError("Log group request differs from fixture")
    missing_values(
        ctx, fake, resource, mapping, items, payload, required=("logGroupName",)
    )
    fake.duplicate = True
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resource, "base")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Duplicate log groups were accepted")
    fake.duplicate = False
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "logs.describe_log_groups",
        "LogGroupName",
    )
    return items


def lakeformation_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    expected = {
        "ResourceArn": "arn:aws:s3:::fixture",
        "RoleArn": "arn:aws:iam::123456789012:role/fixture",
        "WithFederation": True,
        "HybridAccessEnabled": False,
    }
    ctx, fake = fixture_context(root, "lake-formation", LakeFormationCalls, expected)
    record = inventory.sdk_inventory.collect(ctx, "LakeFormation.Resource")[0]
    resource = fixture_resource(root, ctx, "lake-formation", record)
    cases = {
        name: (name, "arn" if name.endswith("Arn") else "typed", value)
        for name, value in expected.items()
    }
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "LakeFormation.Resource",
        cases,
        ["normal", "missing-selector", "access-denied"],
    )
    missing_values(
        ctx, fake, resource, mapping, items, expected, required=("ResourceArn",)
    )
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "lakeformation.describe_resource",
        "ResourceArn",
    )
    return items


def datazone_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    ctx, fake = fixture_context(root, "datazone", DataZoneCalls, {})
    record = inventory.sdk_inventory.collect(ctx, "DataZone.Project")[0]
    resource = fixture_resource(root, ctx, "datazone", record)
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "DataZone.Project",
        {"DomainIdentifier": ("domainId", "typed", "dzd_domain")},
        ["normal", "missing-selector", "access-denied"],
    )
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "datazone.get_project",
        "DomainIdentifier",
    )
    ctx.target["awsAccountId"] = "999999999999"
    try:
        inventory.sdk_inventory.collect(ctx, "DataZone.Project")
    except ValueError as error:
        if "scope mismatch" not in str(error):
            raise
    else:
        raise ValueError("DataZone domain scope mismatch was accepted")
    for evidence in items.values():
        if evidence["status"] == "verified":
            evidence["branches"].append("account-mismatch")
    return items


def route53_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    cases = [
        {
            "Name": "example.com.",
            "Type": "A",
            "TTL": 60,
            "ResourceRecords": [{"Value": "192.0.2.1"}],
        },
        {
            "Name": "weighted.example.com.",
            "Type": "A",
            "SetIdentifier": "blue",
            "Weight": 1,
            "TTL": 60,
            "ResourceRecords": [{"Value": "192.0.2.2"}],
        },
        {
            "Name": "weighted.example.com.",
            "Type": "A",
            "SetIdentifier": "green",
            "Weight": 2,
            "TTL": 60,
            "ResourceRecords": [{"Value": "192.0.2.3"}],
        },
        {
            "Name": "alias.example.com.",
            "Type": "A",
            "AliasTarget": {
                "DNSName": "target.example.com.",
                "HostedZoneId": "Z2",
                "EvaluateTargetHealth": False,
            },
        },
    ]
    expected = {
        "Name": ("Name", "dns", 0, "example.com"),
        "AliasTarget.DNSName": ("AliasTarget.DNSName", "dns", 3, "target.example.com"),
        "AliasTarget.EvaluateTargetHealth": (
            "AliasTarget.EvaluateTargetHealth",
            "typed",
            3,
            False,
        ),
        "AliasTarget.HostedZoneId": ("AliasTarget.HostedZoneId", "typed", 3, "Z2"),
        "ResourceRecords": ("ResourceRecords[].Value", "set", 0, ["192.0.2.1"]),
        "SetIdentifier": ("SetIdentifier", "typed", 1, "blue"),
        "TTL": ("TTL", "typed", 0, "60"),
        "Type": ("Type", "typed", 0, "A"),
    }
    ctx, fake = fixture_context(root, "route53", Route53Calls, cases)
    records = inventory.sdk_inventory.collect(
        ctx,
        "Route53.RecordSet",
        parents=[
            {
                "kind": "Route53.HostedZone",
                "identity": "Z1",
                "cloudProperties": {"Id": "Z1"},
            }
        ],
    )
    resources = [
        fixture_resource(root, ctx, "route53", record, "fixture-" + str(index))
        for index, record in enumerate(records)
    ]
    items = {}
    for key in properties:
        name = key.removeprefix("Route53.RecordSet.")
        prop = mapping.properties[key]
        case = expected.get(name)
        if (
            case is None
            or prop.transform != "identity"
            or (prop.field.path, prop.field.norm) != case[:2]
        ):
            items[key] = {
                "status": "unverified",
                "reason": "No executable property/branch fixture",
            }
            continue
        _, raw = mapping_value(ctx, resources[case[2]], mapping, prop, key)
        import_normalize(ctx, "Route53.RecordSet", key, raw)
        actual = cli.comparator().normalize(ctx, raw, prop.field.norm)
        items[key] = (
            {
                "status": "verified",
                "reason": "Offline simple, weighted and alias responses only; AWS retrieval remains unverified",
                "branches": [
                    "normal",
                    "missing-selector",
                    "ambiguous-routing",
                    "access-denied",
                ],
            }
            if actual == case[3]
            else {"status": "broken", "reason": "Adapter result differs from fixture"}
        )
        if name not in {"Name", "Type"}:
            missing_index = (
                0 if name.startswith("AliasTarget.") or name == "SetIdentifier" else 3
            )
            _, absent = mapping_value(ctx, resources[missing_index], mapping, prop, key)
            normalized = cli.comparator().normalize(ctx, absent, prop.field.norm)
            if normalized not in (cli.comparator().MISSING, []):
                items[key] = {
                    "status": "broken",
                    "reason": "Missing value was not preserved",
                }
            elif items[key]["status"] == "verified":
                items[key]["branches"].append("missing-value")
    resource = resources[1]
    resource.rows[:] = [
        row
        for row in resource.rows
        if not row[1]["property"].endswith(".SetIdentifier")
    ]
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resource, "record")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Ambiguous routing identifier was accepted")
    resource = resources[0]
    resource.rows[:] = [
        row for row in resource.rows if not row[1]["property"].endswith(".HostedZoneId")
    ]
    try:
        resource.module.fetch(ctx, resource, "record")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing hosted zone selector was accepted")
    fake.error = cli.comparator().AcquisitionError(
        "route53.list_resource_record_sets", "AccessDenied"
    )
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resources[3], "record")
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("API failure was changed") from error
    else:
        raise ValueError("API failure was swallowed")
    return items


def vpc_fixture(root: Path, mapping: Any, prop: Any) -> None:
    """Execute the real inventory, selector builder, adapter and mapped projection."""
    if (prop.field.getter, prop.field.path, prop.field.norm) != (
        "vpc",
        "DnsResolvers",
        "typed",
    ):
        raise ValueError("Fixture does not match the current Mapping")
    definition = mapping.getters.get("vpc", {})
    if definition.get(
        "kind"
    ) != "adapter" or "QuickSight.VPCConnection" not in definition.get("resources", ()):
        raise ValueError("VPC adapter registration is invalid")
    expected = ["10.0.0.2", "10.0.0.3"]
    ctx, fake = fixture_context(
        root,
        "quicksight",
        FakeCalls,
        {"VPCConnectionId": "connection", "DnsResolvers": expected},
    )
    plan = resolve(mapping, mapping.properties, "QuickSight.VPCConnection")
    if plan.mode != "adapter":
        raise ValueError("Unexpected discovery plan")
    record = inventory.adapter_inventory(
        ctx, "quicksight", ("QuickSight.VPCConnection",)
    )[0]
    resource = fixture_resource(root, ctx, "quicksight", record)
    for value in (expected, [], None):
        fake.payload = {"VPCConnectionId": "connection"}
        if value is not None:
            fake.payload["DnsResolvers"] = value
        clear_fetch(ctx)
        fake.calls.clear()
        _, raw = mapping_value(
            ctx, resource, mapping, prop, "QuickSight.VPCConnection.DnsResolvers"
        )
        actual = cli.comparator().normalize(ctx, raw, prop.field.norm)
        if actual != (
            cli.comparator().MISSING if value is None else value
        ) or fake.calls != [
            (
                "quicksight",
                "describe_vpc_connection",
                {"AwsAccountId": ACCOUNT, "VPCConnectionId": "connection"},
            )
        ]:
            raise ValueError("Adapter result or request differs from fixture")
        if value is not None:
            extracted = cli.normalize("DnsResolvers", actual, "leaf")
            if cli.validation_errors(
                ctx.catalog,
                "QuickSight.VPCConnection",
                "DnsResolvers",
                extracted,
            ):
                raise ValueError("Normalized DNS resolver value is invalid")
    ctx.fetch_cache.clear()
    ctx._flights.clear()
    fake.error = cli.comparator().AcquisitionError(
        "quicksight.describe_vpc_connection", "AccessDenied"
    )
    try:
        mapping_value(
            ctx, resource, mapping, prop, "QuickSight.VPCConnection.DnsResolvers"
        )
    except cli.comparator().AcquisitionError as error:
        if error.code != "AccessDenied":
            raise ValueError("API failure was changed") from error
    else:
        raise ValueError("API failure was swallowed")
    fake.error = None
    resource.rows[:] = [
        row
        for row in resource.rows
        if not row[1]["property"].endswith(".VPCConnectionId")
    ]
    clear_fetch(ctx)
    try:
        mapping_value(
            ctx, resource, mapping, prop, "QuickSight.VPCConnection.DnsResolvers"
        )
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing selector was accepted")
    resource.rows.append(
        (
            "fixture-999",
            {
                "property": "QuickSight.VPCConnection.VPCConnectionId",
                "value": "`connection`",
            },
        )
    )
    ctx.target["awsAccountId"] = "999999999999"
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resource, "vpc")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Account scope mismatch was accepted")


def vpc_properties_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    dns = mapping.properties.get("QuickSight.VPCConnection.DnsResolvers")
    if dns is None:
        raise InvalidFixture("DNS fixture Property is unavailable")
    vpc_fixture(
        root,
        mapping,
        replace(
            dns,
            field=replace(dns.field, getter="vpc", path="DnsResolvers", norm="typed"),
        ),
    )
    expected = {
        "Name": ("Name", "typed", "connection-name"),
        "DnsResolvers": ("DnsResolvers", "typed", ["10.0.0.2", "10.0.0.3"]),
        "RoleArn": ("RoleArn", "arn", "arn:aws:iam::123456789012:role/fixture"),
        "SecurityGroupIds": ("SecurityGroupIds", "id", ["sg-123"]),
        "SubnetIds": (
            "NetworkInterfaces[].SubnetId",
            "id",
            ["subnet-123", "subnet-456"],
        ),
        "VPCConnectionId": ("VPCConnectionId", "typed", "connection"),
    }
    payload = {
        "Name": "connection-name",
        "DnsResolvers": ["10.0.0.2", "10.0.0.3"],
        "RoleArn": "arn:aws:iam::123456789012:role/fixture",
        "SecurityGroupIds": ["sg-123"],
        "NetworkInterfaces": [{"SubnetId": "subnet-123"}, {"SubnetId": "subnet-456"}],
        "VPCConnectionId": "connection",
    }
    ctx, fake = fixture_context(root, "quicksight", FakeCalls, payload)
    record = inventory.adapter_inventory(
        ctx, "quicksight", ("QuickSight.VPCConnection",)
    )[0]
    resource = fixture_resource(root, ctx, "quicksight", record)
    fake.calls.clear()
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "QuickSight.VPCConnection",
        expected,
        [
            "normal",
            "missing-value",
            "access-denied",
            "missing-selector",
            "account-mismatch",
        ],
    )
    dns_evidence = items.get("QuickSight.VPCConnection.DnsResolvers")
    if dns_evidence and dns_evidence["status"] == "verified":
        dns_evidence["branches"].append("empty")
    if fake.calls != [
        (
            "quicksight",
            "describe_vpc_connection",
            {"AwsAccountId": ACCOUNT, "VPCConnectionId": "connection"},
        )
    ]:
        raise ValueError("VPC adapter request differs from fixture")
    missing_values(ctx, fake, resource, mapping, items, payload)
    return items


def group_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    expected = {
        "GroupName": "group",
        "Description": "fixture",
        "PrincipalId": "principal",
    }
    ctx, fake = fixture_context(root, "quicksight", FakeCalls, expected)
    plan = resolve(mapping, mapping.properties, "QuickSight.Group")
    if plan.mode != "scoped_sdk":
        raise ValueError("Unexpected discovery plan")
    record = inventory.sdk_inventory.collect(ctx, "QuickSight.Group")[0]
    resource = fixture_resource(root, ctx, "quicksight", record)
    fake.calls.clear()
    cases = {name: (name, "typed", value) for name, value in expected.items()}
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "QuickSight.Group",
        cases,
        ["normal", "missing-selector"],
    )
    if fake.calls != [
        (
            "quicksight",
            "describe_group",
            {"AwsAccountId": ACCOUNT, "Namespace": "default", "GroupName": "group"},
        )
    ]:
        raise ValueError("SDK adapter request differs from fixture")
    missing_values(ctx, fake, resource, mapping, items, expected)
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "quicksight.describe_group",
        "Namespace",
    )
    ctx.target["awsAccountId"] = "999999999999"
    try:
        resource.module.fetch_sdk(ctx, resource, "describe_group")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Account scope mismatch was accepted")
    for evidence in items.values():
        if evidence["status"] == "verified":
            evidence["branches"].extend(["access-denied", "account-mismatch"])
    return items


def run(root: Path, mapping: Any, kind: str) -> dict[str, Any]:
    getters = contracts(mapping, kind)
    results = {}
    for getter, properties in getters.items():
        items = {}
        fixture = {
            ("SQS.Queue", "queue"): sqs_queue_fixture,
            ("KMS.Key", "base"): kms_fixture,
            ("KMS.Key", "policy"): kms_fixture,
            ("KMS.Key", "rotation"): kms_fixture,
            ("KMS.Alias", "alias"): kms_fixture,
            ("Route53.HostedZone", "zone"): hosted_zone_fixture,
            ("Route53.HostedZone", "vpcs"): hosted_zone_fixture,
            ("Macie.ClassificationJob", "job"): macie_job_fixture,
            ("GuardDuty.Detector", "detector"): guardduty_fixture,
            ("GuardDuty.MalwareProtectionPlan", "plan"): guardduty_fixture,
            ("Lambda.Permission", "permission"): grouped_fixture,
            ("SecretsManager.RotationSchedule", "rotation"): grouped_fixture,
            ("KinesisFirehose.DeliveryStream", "base"): firehose_fixture,
            ("KinesisFirehose.DeliveryStream", "destination"): firehose_fixture,
            ("EC2.Instance", "base"): instance_fixture,
            ("EC2.Instance", "volumes"): instance_fixture,
            ("EC2.SecurityGroup", "group"): security_group_fixture,
            ("EC2.SecurityGroupIngress", "rule"): security_group_fixture,
            ("EC2.SecurityGroupEgress", "rule"): security_group_fixture,
            ("EC2.FlowLog", "base"): ec2_network_fixture,
            ("EC2.FlowLog", "resource_type"): ec2_network_fixture,
            ("EC2.VPCEndpoint", "base"): ec2_network_fixture,
            ("EC2.TransitGatewayVpcAttachment", "base"): ec2_network_fixture,
            ("EC2.SubnetRouteTableAssociation", "association"): association_fixture,
            ("SQS.QueuePolicy", "policy"): sqs_policy_fixture,
            ("S3.Bucket", "versioning"): s3_fixture,
            ("S3.Bucket", "base"): s3_base_fixture,
            ("S3.Bucket", "encryption"): s3_fixture,
            ("S3.Bucket", "lifecycle"): s3_fixture,
            ("S3.Bucket", "lock"): s3_fixture,
            ("S3.Bucket", "public"): s3_fixture,
            ("S3.Bucket", "ownership"): s3_fixture,
            ("S3.BucketPolicy", "policy"): s3_fixture,
            ("Athena.WorkGroup", "base"): direct_fixture,
            ("CloudTrail.Trail", "base"): direct_fixture,
            ("CloudTrail.Trail", "status"): direct_fixture,
            ("CloudTrail.Trail", "selectors"): direct_fixture,
            ("Glue.Job", "base"): direct_fixture,
            ("Glue.SecurityConfiguration", "base"): direct_fixture,
            ("Glue.Connection", "base"): direct_fixture,
            ("Glue.Catalog", "base"): direct_fixture,
            ("Glue.Database", "base"): direct_fixture,
            ("Glue.Table", "base"): direct_fixture,
            ("CodePipeline.Pipeline", "base"): direct_fixture,
            ("CodePipeline.Pipeline", "sdk-codepipeline-pipeline"): direct_fixture,
            ("CodeCommit.Repository", "base"): direct_fixture,
            ("MWAA.Environment", "base"): direct_fixture,
            ("Lambda.Function", "base"): direct_fixture,
            ("Lambda.Function", "recursion"): direct_fixture,
            ("Scheduler.Schedule", "schedule"): direct_fixture,
            ("Events.Rule", "base"): direct_fixture,
            ("Events.Rule", "targets"): direct_fixture,
            ("IAM.InstanceProfile", "base"): direct_fixture,
            ("IAM.Role", "base"): direct_fixture,
            ("IAM.User", "base"): direct_fixture,
            ("SecretsManager.Secret", "base"): direct_fixture,
            ("IAM.Role", "attached"): iam_policy_fixture,
            ("IAM.Role", "inline"): iam_policy_fixture,
            ("IAM.User", "attached"): iam_policy_fixture,
            ("IAM.User", "inline"): iam_policy_fixture,
            ("IAM.ManagedPolicy", "base"): iam_managed_fixture,
            ("IAM.ManagedPolicy", "document"): iam_managed_fixture,
            ("IAM.ManagedPolicy", "entities"): iam_managed_fixture,
            ("Config.ConfigurationRecorder", "recorder"): config_fixture,
            ("CodeBuild.Project", "base"): codebuild_fixture,
            ("Config.DeliveryChannel", "channel"): config_fixture,
            ("DataZone.Project", "sdk-datazone-project"): datazone_fixture,
            ("EC2.Subnet", "base"): subnet_fixture,
            ("EC2.RouteTable", "base"): subnet_fixture,
            ("EC2.VPC", "base"): vpc_network_fixture,
            ("EC2.VPC", "hostnames"): vpc_network_fixture,
            ("EC2.VPC", "support"): vpc_network_fixture,
            ("Logs.LogGroup", "base"): logs_fixture,
            (
                "LakeFormation.Resource",
                "sdk-lakeformation-resource",
            ): lakeformation_fixture,
            ("QuickSight.Group", "sdk-quicksight-group"): group_fixture,
            ("QuickSight.DataSource", "base"): quicksight_source_fixture,
            ("QuickSight.DataSource", "permissions"): quicksight_source_fixture,
            ("QuickSight.VPCConnection", "vpc"): vpc_properties_fixture,
            ("Route53.RecordSet", "record"): route53_fixture,
            ("SecurityHub.Hub", "base"): securityhub_fixture,
            ("Macie.Session", "session"): macie_session_fixture,
        }.get((kind, getter))
        if fixture is not None and getter in mapping.getters:
            try:
                items = fixture(root, mapping, properties)
            except InvalidFixture:
                raise
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                cli.comparator().Unresolved,
                cli.comparator().AcquisitionError,
            ) as error:
                items = {
                    key: {"status": "broken", "reason": str(error)}
                    for key in properties
                }
        elif kind in ADAPTER_INVENTORIES and getter in mapping.getters:
            items = shared_fixture_evidence(root, mapping, kind, getter, properties)
        for key in properties:
            if key in items:
                continue
            if getter not in mapping.getters:
                items[key] = {"status": "broken", "reason": "Getter is not registered"}
            else:
                items[key] = {
                    "status": "unverified",
                    "reason": "No executable property/branch fixture",
                }
        statuses = Counter(item["status"] for item in items.values())
        evidence = {
            ("EC2.VPC", "base"): ("ec2.describe_vpcs", ["VpcId", "Name"]),
            ("EC2.VPC", "hostnames"): ("ec2.describe_vpc_attribute", ["VpcId", "Name"]),
            ("EC2.VPC", "support"): ("ec2.describe_vpc_attribute", ["VpcId", "Name"]),
            ("CodeBuild.Project", "base"): ("codebuild.batch_get_projects", ["Name"]),
            ("Macie.Session", "session"): ("macie2.get_macie_session", []),
            ("SQS.Queue", "queue"): ("sqs.get_queue_url", ["QueueName"]),
            ("SQS.QueuePolicy", "policy"): ("sqs.get_queue_attributes", ["Queues[]"]),
            ("S3.Bucket", "base"): ("s3.list_buckets", ["BucketName"]),
            ("S3.Bucket", "encryption"): ("s3.get_bucket_encryption", ["BucketName"]),
            ("S3.Bucket", "lifecycle"): (
                "s3.get_bucket_lifecycle_configuration",
                ["BucketName"],
            ),
            ("S3.Bucket", "lock"): ("s3.get_object_lock_configuration", ["BucketName"]),
            ("S3.Bucket", "ownership"): (
                "s3.get_bucket_ownership_controls",
                ["BucketName"],
            ),
            ("S3.Bucket", "public"): ("s3.get_public_access_block", ["BucketName"]),
            ("S3.Bucket", "versioning"): ("s3.get_bucket_versioning", ["BucketName"]),
            ("S3.BucketPolicy", "policy"): ("s3.get_bucket_policy", ["Bucket"]),
            ("IAM.ManagedPolicy", "base"): ("iam.list_policies", ["ManagedPolicyName"]),
            ("IAM.ManagedPolicy", "document"): (
                "iam.list_policies",
                ["ManagedPolicyName"],
            ),
            ("IAM.ManagedPolicy", "entities"): (
                "iam.list_policies",
                ["ManagedPolicyName"],
            ),
            ("IAM.Role", "attached"): ("iam.list_attached_role_policies", ["RoleName"]),
            ("IAM.Role", "inline"): ("iam.list_role_policies", ["RoleName"]),
            ("IAM.User", "attached"): ("iam.list_attached_user_policies", ["UserName"]),
            ("IAM.User", "inline"): ("iam.list_user_policies", ["UserName"]),
            ("Athena.WorkGroup", "base"): ("athena.get_work_group", ["Name"]),
            ("CodeCommit.Repository", "base"): (
                "codecommit.get_repository",
                ["RepositoryName"],
            ),
            ("MWAA.Environment", "base"): ("mwaa.get_environment", ["Name"]),
            ("Lambda.Function", "base"): ("lambda.get_function", ["FunctionName"]),
            ("Lambda.Function", "recursion"): (
                "lambda.get_function_recursion_config",
                ["FunctionName"],
            ),
            ("Scheduler.Schedule", "schedule"): ("scheduler.get_schedule", ["Name"]),
            ("Events.Rule", "base"): ("events.describe_rule", ["Name", "EventBusName"]),
            ("Events.Rule", "targets"): (
                "events.list_targets_by_rule",
                ["Name", "EventBusName"],
            ),
            ("IAM.InstanceProfile", "base"): (
                "iam.get_instance_profile",
                ["InstanceProfileName"],
            ),
            ("IAM.Role", "base"): ("iam.get_role", ["RoleName"]),
            ("IAM.User", "base"): ("iam.get_user", ["UserName"]),
            ("SecretsManager.Secret", "base"): (
                "secretsmanager.describe_secret",
                ["Name"],
            ),
            ("SecurityHub.Hub", "base"): ("securityhub.describe_hub", []),
            ("Config.ConfigurationRecorder", "recorder"): (
                "config.describe_configuration_recorders",
                ["Name"],
            ),
            ("Config.DeliveryChannel", "channel"): (
                "config.describe_delivery_channels",
                ["Name"],
            ),
            ("DataZone.Project", "sdk-datazone-project"): (
                "datazone.get_project",
                ["DomainIdentifier", "Id"],
            ),
            ("LakeFormation.Resource", "sdk-lakeformation-resource"): (
                "lakeformation.describe_resource",
                ["ResourceArn"],
            ),
            ("QuickSight.Group", "sdk-quicksight-group"): (
                "quicksight.describe_group",
                ["AwsAccountId", "Namespace", "GroupName"],
            ),
            ("QuickSight.DataSource", "base"): (
                "quicksight.describe_data_source",
                ["AwsAccountId", "DataSourceId"],
            ),
            ("QuickSight.DataSource", "permissions"): (
                "quicksight.describe_data_source_permissions",
                ["AwsAccountId", "DataSourceId"],
            ),
            ("QuickSight.VPCConnection", "vpc"): (
                "quicksight.describe_vpc_connection",
                ["AwsAccountId", "VPCConnectionId"],
            ),
            ("Route53.RecordSet", "record"): (
                "route53.list_resource_record_sets",
                ["HostedZoneId", "Name", "Type", "SetIdentifier"],
            ),
            ("Logs.LogGroup", "base"): ("logs.describe_log_groups", ["LogGroupName"]),
            ("EC2.Instance", "base"): (
                "ec2.describe_instances",
                ["InstanceId", "Tags", "SubnetId"],
            ),
            ("EC2.Instance", "volumes"): (
                "ec2.describe_volumes",
                ["InstanceId", "Tags", "SubnetId"],
            ),
            ("EC2.FlowLog", "base"): (
                "ec2.describe_flow_logs",
                ["Id", "Name", "ResourceId"],
            ),
            ("EC2.FlowLog", "resource_type"): (
                "ec2.describe_flow_logs",
                ["Id", "Name", "ResourceId"],
            ),
            ("EC2.TransitGatewayVpcAttachment", "base"): (
                "ec2.describe_transit_gateway_vpc_attachments",
                ["Id", "VpcId", "TransitGatewayId"],
            ),
            ("EC2.VPCEndpoint", "base"): (
                "ec2.describe_vpc_endpoints",
                ["Id", "Tags", "VpcId", "ServiceName"],
            ),
            ("EC2.SecurityGroup", "group"): (
                "ec2.describe_security_groups",
                ["Id", "GroupName", "VpcId"],
            ),
            ("EC2.SecurityGroupIngress", "rule"): (
                "ec2.describe_security_group_rules",
                ["Id", "parent", "properties"],
            ),
            ("EC2.SecurityGroupEgress", "rule"): (
                "ec2.describe_security_group_rules",
                ["Id", "parent", "properties"],
            ),
            ("EC2.SubnetRouteTableAssociation", "association"): (
                "ec2.describe_route_tables",
                ["SubnetId"],
            ),
            ("GuardDuty.Detector", "detector"): ("guardduty.get_detector", ["Id"]),
            ("GuardDuty.MalwareProtectionPlan", "plan"): (
                "guardduty.get_malware_protection_plan",
                ["MalwareProtectionPlanId", "ProtectedResource.S3Bucket.BucketName"],
            ),
            ("Macie.ClassificationJob", "job"): (
                "macie2.describe_classification_job",
                ["jobId", "name"],
            ),
            ("Route53.HostedZone", "zone"): (
                "route53.get_hosted_zone",
                ["Id", "Name", "VPCs"],
            ),
            ("Route53.HostedZone", "vpcs"): (
                "route53.get_hosted_zone",
                ["Id", "Name", "VPCs"],
            ),
            ("Lambda.Permission", "permission"): (
                "lambda.get_policy",
                ["parent", "FunctionName", "Id", "properties"],
            ),
            ("SecretsManager.RotationSchedule", "rotation"): (
                "secretsmanager.describe_secret",
                ["parent", "SecretId"],
            ),
            ("KinesisFirehose.DeliveryStream", "base"): (
                "firehose.describe_delivery_stream",
                ["DeliveryStreamName"],
            ),
            ("KinesisFirehose.DeliveryStream", "destination"): (
                "firehose.describe_delivery_stream",
                ["DeliveryStreamName"],
            ),
            ("KMS.Key", "base"): ("kms.describe_key", ["KeyId", "AliasName"]),
            ("KMS.Key", "rotation"): (
                "kms.get_key_rotation_status",
                ["KeyId", "AliasName"],
            ),
            ("KMS.Key", "policy"): ("kms.get_key_policy", ["KeyId", "AliasName"]),
            ("KMS.Alias", "alias"): ("kms.list_aliases", ["AliasName", "parent"]),
            ("CodePipeline.Pipeline", "base"): ("codepipeline.get_pipeline", ["Name"]),
            ("CodePipeline.Pipeline", "sdk-codepipeline-pipeline"): (
                "codepipeline.get_pipeline",
                ["Name"],
            ),
            ("CloudTrail.Trail", "base"): ("cloudtrail.get_trail", ["TrailName"]),
            ("CloudTrail.Trail", "status"): (
                "cloudtrail.get_trail_status",
                ["TrailName"],
            ),
            ("CloudTrail.Trail", "selectors"): (
                "cloudtrail.get_event_selectors",
                ["TrailName"],
            ),
            ("Glue.Job", "base"): ("glue.get_job", ["Name"]),
            ("Glue.Connection", "base"): (
                "glue.get_connection",
                ["CatalogId", "ConnectionInput.Name"],
            ),
            ("Glue.Catalog", "base"): ("glue.get_catalog", ["CatalogId", "Name"]),
            ("Glue.Database", "base"): (
                "glue.get_database",
                ["CatalogId", "DatabaseInput.Name"],
            ),
            ("Glue.Table", "base"): (
                "glue.get_table",
                ["CatalogId", "DatabaseName", "TableInput.Name"],
            ),
            ("Glue.SecurityConfiguration", "base"): (
                "glue.get_security_configuration",
                ["Name"],
            ),
            ("EC2.Subnet", "base"): (
                "ec2.describe_subnets",
                ["SubnetId", "Name", "VpcId"],
            ),
            ("EC2.RouteTable", "base"): (
                "ec2.describe_route_tables",
                ["RouteTableId", "Name", "VpcId"],
            ),
        }.get((kind, getter))
        results[getter] = {
            "status": "broken"
            if statuses["broken"]
            else "unverified"
            if statuses["unverified"]
            else "verified",
            "adapter": "framework/scripts/aws-compare-services/"
            + mapping.service
            + ".py",
            "getterKind": mapping.getters.get(getter, {}).get("kind"),
            "operation": mapping.getters.get(getter, {}).get("operation"),
            "fixtureOperation": evidence[0] if evidence else None,
            "fixtureAdditionalOperations": [
                "iam.get_" + kind.split(".")[1].lower() + "_policy"
            ]
            if kind in {"IAM.Role", "IAM.User"} and getter == "inline"
            else [
                "iam.get_policy_version"
                if getter == "document"
                else "iam.list_entities_for_policy"
            ]
            if kind == "IAM.ManagedPolicy" and getter in {"document", "entities"}
            else ["s3.get_bucket_location", "sts.get_caller_identity"]
            if kind == "S3.Bucket" and getter == "base"
            else ["sqs.get_queue_attributes"]
            if kind == "SQS.Queue" and getter == "queue"
            else ["ec2.describe_vpcs"]
            if kind == "EC2.VPC" and getter in {"hostnames", "support"}
            else ["kms.describe_key"]
            if kind in {"KMS.Key", "KMS.Alias"} and getter != "base"
            else {
                ("EC2.Instance", "volumes"): ["ec2.describe_instances"],
                ("EC2.SecurityGroupIngress", "rule"): ["ec2.describe_security_groups"],
                ("EC2.SecurityGroupEgress", "rule"): ["ec2.describe_security_groups"],
                ("EC2.SubnetRouteTableAssociation", "association"): [
                    "ec2.describe_subnets"
                ],
                ("GuardDuty.Detector", "detector"): ["guardduty.list_detectors"],
                ("GuardDuty.MalwareProtectionPlan", "plan"): [
                    "guardduty.list_malware_protection_plans"
                ],
                ("Route53.HostedZone", "zone"): ["route53.list_hosted_zones"],
                ("Route53.HostedZone", "vpcs"): ["route53.list_hosted_zones"],
                ("Macie.ClassificationJob", "job"): ["macie2.list_classification_jobs"],
                ("Glue.Catalog", "base"): ["glue.get_catalogs"],
            }.get((kind, getter), []),
            "selectors": evidence[1] if evidence else None,
            "paths": {
                key: {
                    "path": mapping.properties[key].field.path,
                    "normalize": mapping.properties[key].field.norm,
                }
                for key in properties
            },
            "properties": items,
        }
    return results
