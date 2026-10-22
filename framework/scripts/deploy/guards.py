"""Deploy mutation checks and timing; transport owns no Task or Issue decisions."""
import re
from cloudformation_inputs import Blocked
from issue_gate import require_target_no_issues
from utils.aws import cloudformation, s3, kms, secretsmanager, sts

MUTATIONS = {'create_change_set', 'execute_change_set', 'put_object', 'delete_stack',
             'put_secret_value', 'update_secret_version_stage'}
SERVICES = {'cloudformation': cloudformation, 's3': s3, 'kms': kms,
            'secretsmanager': secretsmanager, 'sts': sts}


def call(runtime, service, operation, arguments):
    if operation in MUTATIONS:
        runtime.guard()
        try:
            require_target_no_issues(runtime.root, (runtime.environment, runtime.directory))
        except (OSError, ValueError) as error:
            raise Blocked(str(error)) from error
    with runtime.timing.phase('awsApi', service=service, operation=operation.replace('_', '-')):
        return getattr(SERVICES[service], operation)(runtime.connection, **arguments)


def secret_value_missing(reason):
    if reason == 'SECRET_CURRENT_VALUE_MISSING':
        return True
    text = (reason or '').lower()
    if any(word in text for word in ('accessdenied', 'access denied', 'kms', 'decrypt', 'timeout')):
        return False
    subject = r'(?:secret value|secret version|initial secret version|secretstring|secretbinary|awscurrent)'
    missing = r"(?:can't find|cannot find|not found|does not exist|not exist|missing|not registered|no )"
    return bool(re.search(subject + r'.*' + missing + '|' + missing + r'.*' + subject, text))
