"""Deploy runtime target/authentication checks, independent of read-only context CLIs."""

from issue_gate import require_target_no_issues
from utils.aws.client import connection_context
from utils.aws.identity import execution_account, select_profile, verify_account
from utils.aws.sts import get_caller_identity
from utils.project_targets import load_target


def check_deploy_context(root, environment, account_id=None, alias=None, profile=None):
    target = load_target(root, environment, account_id, alias)
    require_target_no_issues(root, (environment, alias or target["awsAccountId"]))
    selected = select_profile(target, profile)
    expected = execution_account(target)
    context = connection_context(selected, target["awsRegion"], expected)
    caller = get_caller_identity(context).get("Account")
    verify_account(target, caller)
    return target
