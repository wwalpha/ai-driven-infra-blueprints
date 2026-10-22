"""Deploy runtime target/authentication checks, independent of read-only context CLIs."""
from project_targets import load_target, DeployContextError
from utils.aws.client import connection_context
from utils.aws.sts import get_caller_identity
from issue_gate import require_target_no_issues


def check_deploy_context(root, environment, account_id=None, alias=None, profile=None):
    target = load_target(root, environment, account_id, alias)
    require_target_no_issues(root, (environment, alias or target['awsAccountId']))
    configured = target.get('awsProfile')
    if configured and profile is not None and profile != configured:
        raise DeployContextError('explicit AWS profile does not match target awsProfile')
    expected = target.get('awsExecutionAccountId', target['awsAccountId'])
    context = connection_context(configured or profile, target['awsRegion'], expected)
    caller = get_caller_identity(context).get('Account')
    if caller != expected:
        raise DeployContextError(f'AWS account mismatch: expected {expected}, actual {caller or "unknown"}')
    return target
