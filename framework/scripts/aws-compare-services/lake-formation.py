"""Lake Formation registered-resource reads."""

from model.adapters.aws import AcquisitionError

APIS = {("lakeformation", "describe_resource"), ("lakeformation", "list_resources")}
SDK_OPERATIONS = {"LakeFormation.Resource": "describe_resource"}


def sensitive(prop):
    return False


def fetch(ctx, resource, getter):
    raise ValueError("Lake Formation has no adapter getter")


def fetch_sdk(ctx, resource, operation):
    arn = resource.value("ResourceArn", "arn")
    response = ctx.call("lakeformation", operation, ResourceArn=arn)
    info = response.get("ResourceInfo")
    if isinstance(info, dict) and "ResourceArn" not in info:
        try:
            listed = ctx.pages(
                "lakeformation",
                "list_resources",
                FilterConditionList=[
                    {
                        "Field": "RESOURCE_ARN",
                        "ComparisonOperator": "EQ",
                        "StringValueList": [arn],
                    }
                ],
            ).get("ResourceInfoList", [])
        except AcquisitionError as error:
            response["ListResourcesError"] = error.code
            return response
        matches = [
            item
            for item in listed
            if isinstance(item, dict) and item.get("ResourceArn") == arn
        ]
        if len(matches) == 1:
            response["ResourceInfo"] = {**matches[0], **info}
    return response
