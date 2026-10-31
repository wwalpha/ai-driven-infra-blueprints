"""quicksight: selected properties -> read-only SDK responses; inputs in fetch()."""

from typing import Any

from model.adapters.aws import Unresolved

APIS = {
    ("quicksight", "describe_group"),
    ("quicksight", "describe_vpc_connection"),
    ("quicksight", "describe_data_source_permissions"),
    ("quicksight", "describe_data_source"),
}


def sensitive(prop):
    return False


def datasource_account(ctx, r):
    omitted = not r.rows_for("AwsAccountId")
    if omitted:
        account = ctx.target["awsAccountId"]
        if (
            not ctx.verified
            or ctx.target.get("awsExecutionAccountId", account) != account
        ):
            raise Unresolved("QuickSight execution account conflicts with target")
    else:
        account = r.value("AwsAccountId")
    if account != ctx.target["awsAccountId"]:
        raise Unresolved("QuickSight AwsAccountId conflicts with target")
    return account, omitted


def fetch(ctx, r, getter):
    if r.kind == "QuickSight.DataSource":
        account, omitted = datasource_account(ctx, r)
    else:
        account = r.value("AwsAccountId")
        omitted = False
        if account != ctx.target["awsAccountId"]:
            raise Unresolved("QuickSight AwsAccountId conflicts with target")
    if getter == "vpc":
        result = ctx.call(
            "quicksight",
            "describe_vpc_connection",
            AwsAccountId=account,
            VPCConnectionId=r.value("VPCConnectionId"),
        )["VPCConnection"]
    elif getter == "permissions":
        return ctx.call(
            "quicksight",
            "describe_data_source_permissions",
            AwsAccountId=account,
            DataSourceId=r.value("DataSourceId"),
        )
    elif r.kind == "QuickSight.DataSource":
        result = ctx.call(
            "quicksight",
            "describe_data_source",
            AwsAccountId=account,
            DataSourceId=r.value("DataSourceId"),
        )["DataSource"]
    else:
        raise Unresolved("QuickSight resource has no matching adapter getter")
    return result if omitted else dict(result, AwsAccountId=account)


SDK_OPERATIONS = {"QuickSight.Group": "describe_group"}


def fetch_sdk(ctx: Any, r: Any, operation: str) -> dict[str, Any]:
    account = r.value("AwsAccountId")
    if account != ctx.target.get("awsExecutionAccountId", ctx.target["awsAccountId"]):
        raise Unresolved("QuickSight group account conflicts with target")
    return ctx.call(
        "quicksight",
        operation,
        AwsAccountId=account,
        Namespace=r.value("Namespace"),
        GroupName=r.value("GroupName"),
    )
