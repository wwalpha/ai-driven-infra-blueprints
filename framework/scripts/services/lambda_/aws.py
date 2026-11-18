"""lambda: selected properties -> read-only SDK responses; inputs in fetch()."""

import json

from model.adapters.aws import MISSING, Unresolved, one

APIS = {
    ("lambda", "get_function_recursion_config"),
    ("lambda", "get_policy"),
    ("lambda", "get_function"),
}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind == "Lambda.Function":
        name = r.value("FunctionName")
        if getter == "recursion":
            return ctx.call(
                "lambda", "get_function_recursion_config", FunctionName=name
            )
        return ctx.call("lambda", "get_function", FunctionName=name)
    parent = r.parent()
    name = parent.value("FunctionName")
    if r.value("FunctionName", "name") != name:
        raise Unresolved("permission FunctionName does not identify its parent")
    statements = json.loads(
        ctx.call("lambda", "get_policy", FunctionName=name)["Policy"]
    ).get("Statement", [])
    current = r.current("Id")
    if current:
        statement = one(
            [v for v in statements if v.get("Sid") == current], "lambda.get_policy"
        )
    else:
        action = r.value("Action")
        principal = r.value("Principal")
        source = r.optional("SourceArn", norm="arn")
        account = r.optional("SourceAccount")
        candidates = []
        for v in statements:
            principals = v.get("Principal", {})
            principal_values = (
                [principals]
                if isinstance(principals, str)
                else list(principals.values())
            )
            condition = v.get("Condition", {})
            actual_source = condition.get(
                "ArnLike", condition.get("ArnEquals", {})
            ).get("AWS:SourceArn")
            actual_account = condition.get("StringEquals", {}).get("AWS:SourceAccount")
            if (
                v.get("Action") == action
                and principal in principal_values
                and (source is None or source == actual_source)
                and (account is None or account == actual_account)
            ):
                candidates.append(v)
        statement = one(candidates, "lambda.get_policy")
    principal = statement.get("Principal", {})
    if isinstance(principal, dict):
        principal = one(list(principal.values()), "lambda.get_policy")
    condition = statement.get("Condition", {})
    return dict(
        statement,
        FunctionName=name,
        Principal=principal,
        SourceArn=condition.get("ArnLike", condition.get("ArnEquals", {})).get(
            "AWS:SourceArn", MISSING
        ),
        SourceAccount=condition.get("StringEquals", {}).get(
            "AWS:SourceAccount", MISSING
        ),
    )


SDK_OPERATIONS = {"Lambda.Function": "get_function"}


def fetch_sdk(ctx, r, operation):
    return ctx.call("lambda", operation, FunctionName=r.value("FunctionName"))
