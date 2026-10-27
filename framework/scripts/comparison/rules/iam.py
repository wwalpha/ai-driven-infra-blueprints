"""Static IAM comparison methods; container rules include their recursive contents."""

import re

from utils.cloudformation.inputs import Blocked, condition_active
from utils.iac_values import ResourceReference

from ..methods import Rule, properties


def managed_policy_roles(
    service, identity, stack, direct, *, stack_inputs, evaluate, reference_same, symbol
):
    """Combine direct Roles with proven same-stack active Role attachments."""
    roles = evaluate(stack, direct)
    if not isinstance(roles, list):
        raise Blocked("ManagedPolicy Roles is not a proven list")
    roles = list(roles)
    policy = ResourceReference(
        {"$resource": [service, identity], "$attribute": "PolicyArn"}
    )
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-role.html#cfn-iam-role-managedpolicyarns
    document, parameters, pseudo = stack_inputs[stack]
    for logical, definition in document.get("Resources", {}).items():
        if definition.get("Type") != "AWS::IAM::Role" or not condition_active(
            document, parameters, pseudo, definition
        ):
            continue
        attachments = evaluate(
            stack, definition.get("Properties", {}).get("ManagedPolicyArns", [])
        )
        if not isinstance(attachments, list):
            raise Blocked("role ManagedPolicyArns is not a proven list")
        matches = [
            False
            if isinstance(item, str)
            and re.fullmatch(r"arn:aws[a-z-]*:iam::aws:policy/.+", item)
            else reference_same(policy, item, "IAM.Role", "ManagedPolicyArns[]")
            for item in attachments
        ]
        if any(result is None for result in matches) and not any(
            result is True for result in matches
        ):
            raise Blocked("inverse role attachment identity is unproven")
        if any(result is True for result in matches):
            role = symbol(stack, logical)
            if not any(
                reference_same(role, item, "IAM.ManagedPolicy", "Roles[]") is True
                for item in roles
            ):
                roles.append(role)
    return roles


def roles_actual(inputs, service, identity, name, owner, key):
    return managed_policy_roles(
        service,
        identity,
        name,
        owner.get("Properties", {}).get(key, []),
        stack_inputs=inputs.stack_inputs,
        evaluate=inputs.evaluate,
        reference_same=inputs.reference_same,
        symbol=inputs.symbol,
    )


RULES = {
    "IAM.InstanceProfile": properties(
        ordered="""
            Roles
        """,
        scalars="""
            InstanceProfileName
            Path
        """,
    ),
    "IAM.ManagedPolicy": properties(
        objects="""
            PolicyDocument
        """,
        ordered="""
            Groups
            Roles
            Users
        """,
        scalars="""
            Description
            ManagedPolicyName
            Path
        """,
    ),
    "IAM.Role": properties(
        objects="""
            AssumeRolePolicyDocument
            Policies[]
            Policies[].PolicyDocument
            Tags[]
        """,
        ordered="""
            ManagedPolicyArns
        """,
        scalars="""
            Description
            MaxSessionDuration
            Path
            PermissionsBoundary
            Policies[].PolicyName
            RoleName
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "IAM.User": properties(
        objects="""
            LoginProfile
            Policies[]
            Policies[].PolicyDocument
            Tags[]
        """,
        ordered="""
            Groups
            ManagedPolicyArns
        """,
        scalars="""
            LoginProfile.Password
            LoginProfile.PasswordResetRequired
            Path
            PermissionsBoundary
            Policies[].PolicyName
            Tags[].Key
            Tags[].Value
            UserName
        """,
        tags="""
            Tags
        """,
    ),
}

# Statement object membership remains exact even for a selected policy projection.
for _kind, _path in (
    ("IAM.ManagedPolicy", "PolicyDocument"),
    ("IAM.Role", "AssumeRolePolicyDocument"),
    ("IAM.Role", "Policies[].PolicyDocument"),
    ("IAM.User", "Policies[].PolicyDocument"),
):
    RULES[_kind][_path + ".Statement"] = Rule(
        "UNORDERED", "UNORDERED", key="Sid", local=True
    )
    for _field in ("Action", "NotAction", "Resource", "NotResource"):
        RULES[_kind][_path + ".Statement[]." + _field] = Rule(
            "UNORDERED", "UNORDERED", local=True, singleton=True
        )

for _kind in ("IAM.Role", "IAM.User"):
    RULES[_kind]["Policies"] = Rule(
        "KEYED", "KEYED", key="PolicyName", keyless_unordered=True
    )

RULES["IAM.ManagedPolicy"]["Roles"] = Rule(
    "UNORDERED", "UNORDERED", actual=roles_actual, local=True
)
