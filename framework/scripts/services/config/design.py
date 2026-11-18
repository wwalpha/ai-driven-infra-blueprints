"""Fixed config design definitions; no display-engine dependencies."""

ROLE_ARN = "Config.ConfigurationRecorder.RoleARN"

IMPORT_PENDING_PROPERTIES = {ROLE_ARN}

RESOURCE_REFERENCE_PROPERTIES = {
    ROLE_ARN: ("IAM.Role", "RoleName"),
}

RESOURCE_ANCHOR_KINDS = {
    "Config.ConfigurationRecorder": "configuration-recorder",
    "Config.DeliveryChannel": "delivery-channel",
}

NAMING_EXEMPT_PROPERTIES = {
    "Config.ConfigurationRecorder.Name",
    "Config.DeliveryChannel.Name",
}
