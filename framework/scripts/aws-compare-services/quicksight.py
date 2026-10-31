"""quicksight: selected properties -> read-only SDK responses; inputs in fetch()."""

import re
from typing import Any

from model.adapters.aws import (
    AcquisitionError,
    IdentityError,
    Unresolved,
    execution_account,
)

APIS = {
    ("quicksight", "describe_group"),
    ("quicksight", "describe_vpc_connection"),
    ("quicksight", "describe_data_source_permissions"),
    ("quicksight", "describe_data_source"),
}


def sensitive(prop):
    return False


def datasource_account(ctx, r):
    if not ctx.verified:
        raise Unresolved("QuickSight execution account is not verified")
    omitted = not r.rows_for("AwsAccountId")
    try:
        account = (
            execution_account(ctx.target)
            if omitted
            else execution_account({"awsAccountId": r.value("AwsAccountId")})
        )
    except IdentityError as error:
        raise Unresolved(str(error)) from error
    return account, omitted


def verify_owner(result, account, key="Arn"):
    arn = result.get(key)
    if arn is not None:
        parts = arn.split(":") if isinstance(arn, str) else []
        if (
            len(parts) < 6
            or parts[0] != "arn"
            or parts[2] != "quicksight"
            or parts[4] != account
        ):
            raise Unresolved(
                "QuickSight resource ARN owner conflicts with requested account"
            )


def fetch(ctx, r, getter):
    if getter == "group-namespace":
        try:
            response = ctx.fetch(
                r, "sdk-quicksight-group", {"operation": "describe_group"}
            )
        except AcquisitionError as error:
            raise Unresolved(
                "QuickSight DescribeGroup failed: " + error.code
            ) from error
        group = response.get("Group")
        arn = group.get("Arn") if isinstance(group, dict) else None
        parts = arn.split(":", 5) if isinstance(arn, str) else []
        if (
            len(parts) != 6
            or parts[0] != "arn"
            or not re.fullmatch(r"aws(?:-[a-z0-9]+)*", parts[1])
            or parts[2] != "quicksight"
        ):
            raise Unresolved("QuickSight Group ARN is missing or malformed")
        if (
            parts[3] != ctx.target["awsRegion"]
            or parts[4] != datasource_account(ctx, r)[0]
        ):
            raise Unresolved(
                "QuickSight Group ARN account or region conflicts with target"
            )
        resource = parts[5].split("/", 2)
        if (
            len(resource) != 3
            or resource[0] != "group"
            or not resource[1]
            or not resource[2]
        ):
            raise Unresolved("QuickSight Group ARN resource or namespace is malformed")
        if resource[2] != r.value("GroupName"):
            raise Unresolved("QuickSight Group ARN group name conflicts with target")
        return {"Namespace": resource[1]}
    account, omitted = datasource_account(ctx, r)
    if getter == "vpc":
        if account != execution_account(ctx.target):
            raise Unresolved(
                "QuickSight VPC connection owner differs from verified execution account"
            )
        result = ctx.call(
            "quicksight",
            "describe_vpc_connection",
            AwsAccountId=account,
            VPCConnectionId=r.value("VPCConnectionId"),
        )["VPCConnection"]
    elif getter == "permissions":
        result = ctx.call(
            "quicksight",
            "describe_data_source_permissions",
            AwsAccountId=account,
            DataSourceId=r.value("DataSourceId"),
        )
        verify_owner(result, account, "DataSourceArn")
        return result
    elif r.kind == "QuickSight.DataSource":
        result = ctx.call(
            "quicksight",
            "describe_data_source",
            AwsAccountId=account,
            DataSourceId=r.value("DataSourceId"),
        )["DataSource"]
    else:
        raise Unresolved("QuickSight resource has no matching adapter getter")
    verify_owner(result, account)
    return result if omitted else dict(result, AwsAccountId=account)


SDK_OPERATIONS = {"QuickSight.Group": "describe_group"}


def fetch_sdk(ctx: Any, r: Any, operation: str) -> dict[str, Any]:
    account, _ = datasource_account(ctx, r)
    result = ctx.call(
        "quicksight",
        operation,
        AwsAccountId=account,
        Namespace=r.value("Namespace"),
        GroupName=r.value("GroupName"),
    )
    verify_owner(result.get("Group", {}), account)
    return result
