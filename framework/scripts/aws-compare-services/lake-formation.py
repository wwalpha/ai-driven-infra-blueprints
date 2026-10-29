"""Lake Formation registered-resource reads."""

APIS = {("lakeformation", "describe_resource")}
SDK_OPERATIONS = {"LakeFormation.Resource": "describe_resource"}


def sensitive(prop):
    return False


def fetch(ctx, resource, getter):
    raise ValueError("Lake Formation has no adapter getter")


def fetch_sdk(ctx, resource, operation):
    return ctx.call(
        "lakeformation", operation, ResourceArn=resource.value("ResourceArn", "arn")
    )
