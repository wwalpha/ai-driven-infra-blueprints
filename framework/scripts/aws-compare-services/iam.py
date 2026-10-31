"""iam: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import AcquisitionError, one

APIS = {
    ("iam", "list_attached_user_policies"),
    ("iam", "list_role_policies"),
    ("iam", "get_user_policy"),
    ("iam", "list_attached_role_policies"),
    ("iam", "get_policy_version"),
    ("iam", "list_entities_for_policy"),
    ("iam", "list_policies"),
    ("iam", "get_instance_profile"),
    ("iam", "get_role_policy"),
    ("iam", "list_user_policies"),
    ("iam", "get_user"),
    ("iam", "get_role"),
}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind == "IAM.InstanceProfile":
        return ctx.call(
            "iam",
            "get_instance_profile",
            InstanceProfileName=r.value("InstanceProfileName"),
        )["InstanceProfile"]
    if r.kind == "IAM.ManagedPolicy":
        record = one(
            [
                v
                for v in ctx.pages("iam", "list_policies", Scope="Local").get(
                    "Policies", []
                )
                if v["PolicyName"] == r.value("ManagedPolicyName")
            ],
            "iam.list_policies",
        )
        if getter == "document":
            return ctx.call(
                "iam",
                "get_policy_version",
                PolicyArn=record["Arn"],
                VersionId=record["DefaultVersionId"],
            )["PolicyVersion"]
        if getter == "entities":
            return {
                "Roles": [
                    v["RoleName"]
                    for v in ctx.pages(
                        "iam",
                        "list_entities_for_policy",
                        PolicyArn=record["Arn"],
                        EntityFilter="Role",
                    ).get("PolicyRoles", [])
                ]
            }
        return record
    kind = "role" if r.kind == "IAM.Role" else "user"
    argument = "RoleName" if kind == "role" else "UserName"
    name = r.value(argument)
    if getter == "attached":
        result = ctx.pages(
            "iam", "list_attached_" + kind + "_policies", **{argument: name}
        )
        return {"Arns": [v["PolicyArn"] for v in result.get("AttachedPolicies", [])]}
    if getter == "inline":
        operation = "list_" + kind + "_policies"
        inputs = {argument: name}
        names = ctx.pages("iam", operation, **inputs).get("PolicyNames", [])
        if kind == "role" and not getattr(ctx, "import_mode", False):
            confirmed = ctx.fresh_pages("iam", operation, **inputs).get("PolicyNames", [])
            if set(names) != set(confirmed):
                raise AcquisitionError("iam." + operation, "InlinePolicyListChanged")
        policies = []
        for p in names:
            try:
                document = ctx.call(
                    "iam", "get_" + kind + "_policy", **inputs, PolicyName=p
                )["PolicyDocument"]
            except AcquisitionError as error:
                if kind != "role" or error.code != "NoSuchEntity" or getattr(ctx, "import_mode", False):
                    raise
                ctx.fresh_pages("iam", operation, **inputs)
                raise AcquisitionError(error.api, error.code, request=error.request) from error
            policies.append({"PolicyName": p, "PolicyDocument": document})
        return {"Policies": policies}
    return ctx.call("iam", "get_" + kind, **{argument: name})[
        "Role" if kind == "role" else "User"
    ]
