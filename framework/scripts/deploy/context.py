"""Deploy runtime target/authentication checks, independent of read-only context CLIs."""
from issue_gate import require_target_no_issues
from project_targets import DeployContextError, load_target
from utils.aws.client import connection_context
from utils.aws.identity import execution_account, select_profile, verify_account
from utils.aws.sts import get_caller_identity


def check_deploy_context(root, environment, account_id=None, alias=None, profile=None):
    target = load_target(root, environment, account_id, alias)
    require_target_no_issues(root, (environment, alias or target['awsAccountId']))
    try:
        selected = select_profile(target, profile)
        expected = execution_account(target)
    except ValueError as error:
        raise DeployContextError(str(error)) from error
    context = connection_context(selected, target['awsRegion'], expected)
    caller = get_caller_identity(context).get('Account')
    try:
        verify_account(target, caller)
    except ValueError as error:
        raise DeployContextError(str(error)) from error
    return target
