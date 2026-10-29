"""Deploy mutation checks and timing."""

import re

from task_contract_core import task_reads
from utils.aws import cloudformation, kms, s3, secretsmanager, sts

MUTATIONS = {
    "create_change_set",
    "execute_change_set",
    "put_object",
    "delete_stack",
    "put_secret_value",
    "update_secret_version_stage",
}
SERVICES = {
    "cloudformation": cloudformation,
    "s3": s3,
    "kms": kms,
    "secretsmanager": secretsmanager,
    "sts": sts,
}


def call(runtime, service, operation, arguments):
    if operation in MUTATIONS:
        with task_reads(runtime.root, live=True):
            runtime.guard()
    with runtime.timing.phase(
        "awsApi", service=service, operation=operation.replace("_", "-")
    ):
        return getattr(SERVICES[service], operation)(runtime.connection, **arguments)


def secret_value_missing(reason):
    if reason == "SECRET_CURRENT_VALUE_MISSING":
        return True
    text = (reason or "").lower()
    if any(
        word in text
        for word in ("accessdenied", "access denied", "kms", "decrypt", "timeout")
    ):
        return False
    subject = r"(?:secret value|secret version|initial secret version|secretstring|secretbinary|awscurrent)"
    missing = r"(?:can't find|cannot find|not found|does not exist|not exist|missing|not registered|no )"
    return bool(
        re.search(subject + r".*" + missing + "|" + missing + r".*" + subject, text)
    )
