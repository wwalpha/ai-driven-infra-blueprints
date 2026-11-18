"""Fixed iam design definitions; no display-engine dependencies."""

import re

POLICY_FORMATS = {
    "IAM.ManagedPolicy.PolicyDocument": "statement",
    "IAM.Role.AssumeRolePolicyDocument": "statement",
    "IAM.Role.Policies[].PolicyDocument": "statement",
    "IAM.User.Policies[].PolicyDocument": "statement",
}


IAM_START = "<!-- iam-policy-tables:start -->"

IAM_END = "<!-- iam-policy-tables:end -->"

INLINE_POLICY_DOCUMENTS = {
    "IAM.Role.Policies[].PolicyDocument",
    "IAM.User.Policies[].PolicyDocument",
}

COLLAPSED_POLICY_DOCUMENTS = set(POLICY_FORMATS)

ADDITIONAL_RESOURCE_NAME_FIELDS = {"IAM.ManagedPolicy": ("PolicyName",)}
REQUIRED_IMPORT_NAME_TYPES = {"IAM.Role"}


NAMING_EXEMPT_PROPERTIES = {
    "IAM.ManagedPolicy.ManagedPolicyName",
    "IAM.User.UserName",
    "IAM.InstanceProfile.InstanceProfileName",
}
CONFIRMED_NAME_FIELDS = {"IAM.Role": "RoleName"}
JSON_LINK_IN_COMMENT = COLLAPSED_POLICY_DOCUMENTS
REVIEW_POLICY_JSON = COLLAPSED_POLICY_DOCUMENTS


def check_iam_role_suffix(role_name: str, expected_suffix: str | None) -> list[str]:
    """RoleName の末尾が対象ターゲットの suffix と一致するか検証する。"""
    ending = "Role" + ("-" + expected_suffix if expected_suffix is not None else "")
    # purpose と suffix の境界は PascalCase と固定の Role で判別する。
    if re.fullmatch(r".+-[A-Z][A-Za-z0-9]*" + re.escape(ending), role_name):
        return []
    return [
        f"IAM.Role.RoleName suffix mismatch: actual={role_name!r}, "
        f"expected suffix={expected_suffix!r}; expected ending={ending!r}"
    ]


NAMING_SUFFIX_CHECKS = {"IAM.Role": check_iam_role_suffix}
