"""quicksight: selected properties -> read-only SDK responses; inputs in fetch()."""

import re
from typing import Any

from contracts.target import AWS_ACCOUNT_ID_KEY, AWS_REGION_KEY
from model.adapters.aws import (
    AcquisitionError,
    IdentityError,
    Unresolved,
    execution_account,
)
from model.importing.limitations import sdk_response
from utils.aws_sdk import sdk_for

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
            else execution_account({AWS_ACCOUNT_ID_KEY: r.value("AwsAccountId")})
        )
    except IdentityError as error:
        raise Unresolved(str(error)) from error
    if account not in {execution_account(ctx.target), ctx.target[AWS_ACCOUNT_ID_KEY]}:
        raise Unresolved("QuickSight account is outside the configured target accounts")
    return account, omitted


def group_account(ctx, r):
    if not ctx.verified:
        raise Unresolved("QuickSight execution account is not verified")
    try:
        account = execution_account(ctx.target)
        if (
            r.rows_for("AwsAccountId")
            and execution_account({AWS_ACCOUNT_ID_KEY: r.value("AwsAccountId")})
            != account
        ):
            raise Unresolved("QuickSight Group account differs from execution account")
    except IdentityError as error:
        raise Unresolved(str(error)) from error
    return account


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
        account = group_account(ctx, r)
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
        region = ctx.target[AWS_REGION_KEY]
        partition = next(
            (
                name
                for prefix, name in (
                    ("us-gov-", "aws-us-gov"),
                    ("cn-", "aws-cn"),
                    ("us-iso-", "aws-iso"),
                    ("us-isob-", "aws-iso-b"),
                    ("eu-isoe-", "aws-iso-e"),
                    ("us-isof-", "aws-iso-f"),
                    ("eusc-", "aws-eusc"),
                )
                if region.startswith(prefix)
            ),
            "aws",
        )
        if parts[3] != region or parts[4] != account or parts[1] != partition:
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
        return {"Namespace": resource[1], "AwsAccountId": parts[4]}
    account, omitted = datasource_account(ctx, r)
    if getter == "vpc":
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
    account = group_account(ctx, r)
    result = ctx.call(
        "quicksight",
        operation,
        AwsAccountId=account,
        Namespace=r.value("Namespace"),
        GroupName=r.value("GroupName"),
    )
    getter = {"service": "quicksight", "operation": operation}
    if not sdk_response(ctx.root, getter, result) or not isinstance(
        result.get("Group"), dict
    ):
        raise Unresolved(
            "QuickSight DescribeGroup response structure or status is invalid"
        )
    group = result["Group"]
    region = ctx.target[AWS_REGION_KEY]
    partition = sdk_for(ctx.root).session().get_partition_for_region(region)
    expected_arn = (
        f"arn:{partition}:quicksight:{region}:{account}:group/"
        + r.value("Namespace")
        + "/"
        + r.value("GroupName")
    )
    if (
        group.get("GroupName") != r.value("GroupName")
        or group.get("Arn") != expected_arn
    ):
        raise Unresolved(
            "QuickSight DescribeGroup Identity conflicts with requested Group"
        )
    return result
