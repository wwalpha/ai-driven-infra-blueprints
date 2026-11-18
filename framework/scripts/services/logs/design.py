"""Fixed logs design definitions; no display-engine dependencies."""

POLICY_FORMATS = {
    "Logs.LogGroup.ResourcePolicyDocument": "statement",
    "Logs.ResourcePolicy.PolicyDocument": "statement",
    "Logs.LogGroup.DataProtectionPolicy": "settings",
}
