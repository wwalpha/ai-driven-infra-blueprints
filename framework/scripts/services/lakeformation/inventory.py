"""lakeformation IMPORT acquisition."""

from typing import Any

from model.importing.sdk_inventory import collection, identifier, record


def lakeformation_resources(ctx: Any) -> list[dict[str, Any]]:
    records = []
    for item in collection(ctx, "lakeformation", "list_resources", "ResourceInfoList"):
        arn = identifier(item.get("ResourceArn"))
        detail = ctx.call("lakeformation", "describe_resource", ResourceArn=arn).get(
            "ResourceInfo"
        )
        if not isinstance(detail, dict) or detail.get("ResourceArn") != arn:
            raise ValueError("Lake Formation detail identity mismatch")
        records.append(
            record(
                "LakeFormation.Resource",
                {"ResourceArn": arn},
                {"sdk-lakeformation-resource": {"ResourceInfo": detail}},
            )
        )
    return records
