"""Static IAM comparison methods; container rules include their recursive contents."""

from ..methods import Rule, custom, properties
from ..services.iam import action_same, roles_actual

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
            Policies
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
            Policies
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
    RULES[_kind][_path + ".Statement"] = Rule("UNORDERED", "UNORDERED", local=True)
    RULES[_kind][_path + ".Statement[].Action"] = custom(action_same, local=True)

RULES["IAM.ManagedPolicy"]["Roles"] = Rule(
    "UNORDERED", "UNORDERED", actual=roles_actual, local=True
)
