"""Offline quicksight adapter fixtures."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
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
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls
from model.importing.contract_fixtures import (
    InvalidFixture,
)
from model.importing.discovery import resolve


class QuickSightCalls(FakeCalls):
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
                    "invalid-account",
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
    for _, row in resources[1].rows:
        if row["property"].endswith(".AwsAccountId"):
            row["value"] = "`invalid`"
    try:
        resources[1].module.fetch(ctx, resources[1], getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Invalid QuickSight data source account was accepted")
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
        QuickSightCalls,
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
    for _, row in resource.rows:
        if row["property"].endswith(".AwsAccountId"):
            row["value"] = "`invalid`"
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resource, "vpc")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Invalid account was accepted")


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
    ctx, fake = fixture_context(root, "quicksight", QuickSightCalls, payload)
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
            "invalid-account",
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


def group_namespace_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    payload = {
        "GroupName": "group",
        "Arn": f"arn:aws:quicksight:ap-northeast-1:{ACCOUNT}:group/default/group",
    }
    ctx, fake = fixture_context(root, "quicksight", QuickSightCalls, payload)
    record = inventory.sdk_inventory.collect(ctx, "QuickSight.Group")[0]
    resource = fixture_resource(root, ctx, "quicksight", record)
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        "QuickSight.Group",
        {
            "Namespace": ("Namespace", "typed", "default"),
            "AwsAccountId": ("AwsAccountId", "typed", ACCOUNT),
        },
        ["normal"],
    )
    fake.payload = {"GroupName": "group"}
    clear_fetch(ctx)
    try:
        resource.module.fetch(ctx, resource, "group-namespace")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Missing Group ARN was accepted")
    for item in items.values():
        if item["status"] == "verified":
            item["branches"].append("missing-arn")
    return items


def group_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    expected = {
        "GroupName": "group",
        "Description": "fixture",
        "PrincipalId": "principal",
    }
    payload = dict(
        expected, Arn=f"arn:aws:quicksight:ap-northeast-1:{ACCOUNT}:group/default/group"
    )
    ctx, fake = fixture_context(root, "quicksight", QuickSightCalls, payload)
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
    missing_values(
        ctx, fake, resource, mapping, items, payload, required=("GroupName",)
    )
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "quicksight.describe_group",
        "Namespace",
    )
    for _, row in resource.rows:
        if row["property"].endswith(".AwsAccountId"):
            row["value"] = "`invalid`"
    try:
        resource.module.fetch_sdk(ctx, resource, "describe_group")
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Invalid account was accepted")
    for evidence in items.values():
        if evidence["status"] == "verified":
            evidence["branches"].extend(["access-denied", "invalid-account"])
    return items


CONTRACTS = (
    (
        ("QuickSight.Group", "sdk-quicksight-group"),
        group_fixture,
        "quicksight.describe_group",
        ("AwsAccountId", "Namespace", "GroupName"),
    ),
    (
        ("QuickSight.Group", "group-namespace"),
        group_namespace_fixture,
        "quicksight.describe_group",
        ("AwsAccountId", "Namespace", "GroupName"),
    ),
    (
        ("QuickSight.DataSource", "base"),
        quicksight_source_fixture,
        "quicksight.describe_data_source",
        ("AwsAccountId", "DataSourceId"),
    ),
    (
        ("QuickSight.DataSource", "permissions"),
        quicksight_source_fixture,
        "quicksight.describe_data_source_permissions",
        ("AwsAccountId", "DataSourceId"),
    ),
    (
        ("QuickSight.VPCConnection", "vpc"),
        vpc_properties_fixture,
        "quicksight.describe_vpc_connection",
        ("AwsAccountId", "VPCConnectionId"),
    ),
)
