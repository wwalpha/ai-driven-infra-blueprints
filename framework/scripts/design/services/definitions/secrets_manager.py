"""Fixed secrets_manager design definitions; no display-engine dependencies."""


HIDDEN_PROPERTIES = {'SecretsManager.Secret.Id', 'SecretsManager.RotationSchedule.Id'}

POLICY_FORMATS = {
    'SecretsManager.ResourcePolicy.ResourcePolicy': 'statement',
}

ROTATION_SCHEDULE = "SecretsManager.RotationSchedule"
