"""Guarded AWS CLI transport; no session state or Stack scheduling."""
import json
import re
import subprocess

from cloudformation_inputs import Blocked
from issue_gate import require_target_no_issues

SECRET_METADATA_QUERY = "{ARN:ARN,VersionId:VersionId,VersionStages:VersionStages,HasValue:contains(keys(@), 'SecretString') || contains(keys(@), 'SecretBinary')}"

def secret_value_missing(reason):
    """Error text selects a category only, never an identifier or a JSON key."""
    if reason == 'SECRET_CURRENT_VALUE_MISSING':
        return True
    text = (reason or '').lower()
    if any(word in text for word in ('accessdenied', 'access denied', 'kms', 'decrypt', 'timeout')):
        return False
    subject = r'(?:secret value|secret version|initial secret version|secretstring|secretbinary|awscurrent)'
    missing = r"(?:can't find|cannot find|not found|does not exist|not exist|missing|not registered|no )"
    return bool(re.search(subject + r'.*' + missing + '|' + missing + r'.*' + subject, text))


def call(root, environment, directory, target, profile, timing, guard, operation, *arguments,
        service="cloudformation"):
    if service == 'secretsmanager' and operation == 'get-secret-value' and (
            '--query' not in arguments or arguments[arguments.index('--query') + 1:] != (SECRET_METADATA_QUERY,)):
        raise Blocked('Secret value retrieval requires the controller metadata-only query')
    if operation in {"create-change-set", "execute-change-set", "put-object", "delete-stack",
                     "put-secret-value", "update-secret-version-stage"}:
        guard()
        try:
            require_target_no_issues(root, (environment, directory))
        except (OSError, ValueError) as error:
            raise Blocked(str(error)) from error
    command = ["aws", "--region", target["awsRegion"]]
    if profile:
        command += ["--profile", profile]
    with timing.phase("awsApi", service=service, operation=operation):
        try:
            result = subprocess.run(command + [service, operation, *arguments, "--output", "json", "--no-cli-pager"],
                                    capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            if service == 'secretsmanager':
                raise Blocked('Secrets Manager API transport failure') from None
            raise
        if result.returncode:
            if service == 'secretsmanager':
                code = re.search(r'\(([A-Za-z]+Exception|DecryptionFailure|EncryptionFailure)\)', result.stderr)
                error = Blocked('Secrets Manager API failed (' + (code[1] if code else 'UNKNOWN') + ')')
                error.current_missing = bool(code and code[1] == 'ResourceNotFoundException'
                                             and operation == 'get-secret-value' and secret_value_missing(result.stderr)
                                             and 'awscurrent' in result.stderr.lower())
                raise error from None
            raise Blocked(result.stderr.strip())
        try:
            return json.loads(result.stdout or "{}")
        except ValueError:
            if service == 'secretsmanager':
                raise Blocked('Secrets Manager API response invalid') from None
            raise

