"""quicksight IMPORT acquisition."""

from typing import Any

from contracts.target import AWS_REGION_KEY
from model.importing.sdk_inventory import collection, identifier, record
from utils.aws.identity import execution_account
from utils.aws_sdk import sdk_for


def quicksight_groups(ctx: Any) -> list[dict[str, Any]]:
    account = execution_account(ctx.target)
    records = []
    namespaces = collection(
        ctx, "quicksight", "list_namespaces", "Namespaces", AwsAccountId=account
    )
    seen = set()
    for namespace in namespaces:
        name = identifier(namespace.get("Name"))
        if name in seen:
            raise ValueError("Duplicate QuickSight namespace")
        seen.add(name)
        for group in collection(
            ctx,
            "quicksight",
            "list_groups",
            "GroupList",
            AwsAccountId=account,
            Namespace=name,
        ):
            group_name = identifier(group.get("GroupName"))
            selectors = {"AwsAccountId": account, "Namespace": name}
            records.append(
                record(
                    "QuickSight.Group",
                    {**selectors, "GroupName": group_name},
                    {},  # Leave the detail getter to DescribeGroup.
                    selectors=selectors,
                )
            )
    return records


def verified_detail(
    ctx: Any, resource: Any, listed: dict[str, Any], getter: Any, response: Any
) -> bool:
    """Prove listed/requested/returned Identity; unimplemented SDK paths stay closed."""
    if (
        listed.get("kind") != "QuickSight.Group"
        or getter.get("kind") != "sdk"
        or getter.get("service") != "quicksight"
        or getter.get("operation") != "describe_group"
        or getter.get("resourceType") != "QuickSight.Group"
        or getter.get("result") != "Group"
        or not ctx.verified
        or not isinstance(response, dict)
    ):
        return False
    inputs = {
        name: resource.value(name)
        for name in ("AwsAccountId", "Namespace", "GroupName")
    }
    expected = record(
        "QuickSight.Group",
        inputs,
        {},
        selectors={name: inputs[name] for name in ("AwsAccountId", "Namespace")},
    )
    if any(
        listed.get(key) != expected[key]
        for key in (
            "identity",
            "identityStatus",
            "identityProperties",
            "identityProperty",
            "identityComponents",
            "seedProperties",
            "selectorProperties",
            "provenance",
        )
    ) or inputs["AwsAccountId"] != execution_account(ctx.target):
        return False
    trace = ctx.fetch_trace.get(
        (resource.model.path, resource.number, "sdk-quicksight-group"), ()
    )
    if {"api": "quicksight.describe_group", "inputs": inputs} not in trace:
        return False
    group = response.get("Group")
    if not isinstance(group, dict) or group.get("GroupName") != inputs["GroupName"]:
        return False
    arn = group.get("Arn")
    parts = arn.split(":", 5) if isinstance(arn, str) else []
    region = ctx.target[AWS_REGION_KEY]
    partition = sdk_for(ctx.root).session().get_partition_for_region(region)
    return parts == [
        "arn",
        partition,
        "quicksight",
        region,
        inputs["AwsAccountId"],
        "group/" + inputs["Namespace"] + "/" + inputs["GroupName"],
    ]


def permissions(ctx, record, inputs):
    return {
        "permissions": ctx.call(
            "quicksight",
            "describe_data_source_permissions",
            **inputs,
            DataSourceId=record["DataSourceId"],
        ),
    }
