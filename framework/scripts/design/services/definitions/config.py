"""Fixed config design definitions; no display-engine dependencies."""


RESOURCE_REFERENCE_PROPERTIES = {
    'Config.ConfigurationRecorder.RoleARN': ('IAM.Role', 'RoleName'),
}

RESOURCE_ANCHOR_KINDS = {
    "Config.ConfigurationRecorder": "configuration-recorder",
    "Config.DeliveryChannel": "delivery-channel",
}
