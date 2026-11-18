"""Fixed secrets_manager design definitions; no display-engine dependencies."""

import re

HIDDEN_PROPERTIES = {"SecretsManager.Secret.Id", "SecretsManager.RotationSchedule.Id"}

POLICY_FORMATS = {
    "SecretsManager.ResourcePolicy.ResourcePolicy": "statement",
}

ROTATION_SCHEDULE = "SecretsManager.RotationSchedule"

ROTATION_SUBNETS = "SecretsManager.RotationSchedule.HostedRotationLambda.VpcSubnetIds"


def review_secret_name(kind: str, actual: str, same_type_count: int) -> list[str]:
    errors = []
    if (
        actual.endswith("-")
        or actual.startswith("/")
        or actual.endswith("/")
        or "//" in actual
    ):
        errors.append(
            "Secret Name must have non-empty path components and no trailing hyphen"
        )
    if not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*){2,}", actual
    ):
        errors.append(
            "Secret Name requires application/environment/purpose_path with lower-kebab-case components"
        )
    return errors


REVIEW_NAME_CHECKS = {"SecretsManager.Secret.Name": review_secret_name}
