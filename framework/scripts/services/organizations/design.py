"""Fixed organizations design definitions; no display-engine dependencies."""

POLICY_FORMATS = {
    "Organizations.Policy.Content": "settings",
}

POLICY_TYPE_PROPERTY = "Type"
SERVICE_CONTROL_POLICY = "SERVICE_CONTROL_POLICY"


REVIEW_PATTERN_CONDITIONS = {
    "Organizations.Policy": (
        POLICY_TYPE_PROPERTY,
        SERVICE_CONTROL_POLICY,
        "Policy Type is required to determine mandatory pattern applicability",
    )
}
