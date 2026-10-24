"""Fixed iam design definitions; no display-engine dependencies."""


POLICY_FORMATS = {
    'IAM.ManagedPolicy.PolicyDocument': 'statement',
    'IAM.Role.AssumeRolePolicyDocument': 'statement',
    'IAM.Role.Policies[].PolicyDocument': 'statement',
    'IAM.User.Policies[].PolicyDocument': 'statement',
}


IAM_START = "<!-- iam-policy-tables:start -->"

IAM_END = "<!-- iam-policy-tables:end -->"

INLINE_POLICY_DOCUMENTS = {
    "IAM.Role.Policies[].PolicyDocument",
    "IAM.User.Policies[].PolicyDocument",
}
