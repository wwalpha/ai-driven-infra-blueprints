"""SecretsManager reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "SecretsManager.Secret": "Id",
        "SecretsManager.ResourcePolicy": "Id",
        "SecretsManager.RotationSchedule": "Id",
    },
    arn_attributes={
        "SecretsManager.Secret": "Id",
        "SecretsManager.ResourcePolicy": "Id",
        "SecretsManager.RotationSchedule": "Id",
    },
    linked_subnets={
        "SecretsManager.RotationSchedule.HostedRotationLambda.VpcSubnetIds",
    },
    reference_forms={
        "SecretsManager.Secret.KmsKeyId": {"KeyId", "Arn", "AliasName"},
        "SecretsManager.RotationSchedule.SecretId": {"Id", "Name"},
        "SecretsManager.ResourcePolicy.SecretId": {"Id", "Name"},
    },
    equivalent_forms={
        ("SecretsManager.RotationSchedule.SecretId", "SecretsManager.Secret", "Id"): {
            "Name"
        },
    },
    reference_properties={
        "SecretsManager.Secret.KmsKeyId": (("KMS.Key", "KMS.Alias"), None),
        "SecretsManager.RotationSchedule.SecretId": ("SecretsManager.Secret", "Id"),
    },
    import_properties={
        "SecretsManager.ResourcePolicy.SecretId": ("SecretsManager.Secret", "Id"),
        "SecretsManager.RotationSchedule.ExternalSecretRotationRoleArn": (
            "IAM.Role",
            "Arn",
        ),
        "SecretsManager.RotationSchedule.HostedRotationLambda.MasterSecretArn": (
            "SecretsManager.Secret",
            "Arn",
        ),
        "SecretsManager.RotationSchedule.HostedRotationLambda.SuperuserSecretArn": (
            "SecretsManager.Secret",
            "Arn",
        ),
    },
    value_identities={
        ("SecretsManager.Secret", "Name"): r"(?P<id>[^:]+)(?::[^:]*){0,3}",
        (
            "SecretsManager.Secret",
            "Id",
        ): r"(?P<id>arn:[a-z0-9-]+:secretsmanager:[a-z0-9-]+:\d{12}:secret:[^:]+)(?::[^:]*){0,3}",
    },
)
