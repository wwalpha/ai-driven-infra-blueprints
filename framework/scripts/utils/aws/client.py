"""Connection-context Session/client reuse, configuration, and structured API failures."""

import hashlib
import os
import threading
import time

from utils.aws_sdk import aws_runtime
from utils.cloudformation.inputs import Blocked

_lock = threading.RLock()
_sessions = {}
_clients = {}
API_BUDGET_SECONDS = 60


def connection_context(profile, region, account, authentication=None):
    if authentication is None:
        routes = tuple((name, os.environ.get(name)) for name in (
            'AWS_CONFIG_FILE', 'AWS_SHARED_CREDENTIALS_FILE', 'AWS_DEFAULT_PROFILE', 'AWS_PROFILE', 'AWS_ROLE_ARN',
            'AWS_WEB_IDENTITY_TOKEN_FILE', 'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI',
            'AWS_CONTAINER_CREDENTIALS_FULL_URI'))
        # Distinguish rotating explicit credentials without retaining their material in a key.
        identity = hashlib.sha256('\0'.join(os.environ.get(k, '') for k in (
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN')).encode()).hexdigest()
        authentication = ('profile' if profile else 'default-chain', routes, identity)
    return profile, region, account, authentication


def client(context, service):
    with _lock:
        if (isinstance(context[3], tuple) and context[3][:1] in (('profile',), ('default-chain',))
                and connection_context(*context[:3]) != context):
            raise Blocked('AWS authentication context changed; recreate the connection context')
        key = (context, service)
        if key not in _clients:
            Config = aws_runtime().sdk_config
            if context not in _sessions:
                _sessions[context] = aws_runtime().connection_session(context[0], context[1])
            # Session client construction is not thread-safe even across different services.
            created = _sessions[context].client(service, config=Config(
                retries={'mode': 'standard', 'total_max_attempts': 2},
                connect_timeout=5, read_timeout=20, max_pool_connections=20))
            _clients[key] = created
        return _clients[key]


class AwsError(Blocked):
    def __init__(self, service, operation, code, status=None, *, stack_absent=False, current_missing=False):
        self.code, self.http_status = code, status
        self.stack_absent, self.current_missing = stack_absent, current_missing
        super().__init__(f'{service}.{operation} failed ({code})' + ('; stack does not exist' if stack_absent else ''))


def request(context, service, operation, arguments, *, deadline=None):
    """One request, with no application guards and no secret-bearing error text."""
    BotoCoreError = aws_runtime().BotoCoreError
    ClientError = aws_runtime().ClientError
    deadline = time.monotonic() + API_BUDGET_SECONDS if deadline is None else deadline
    if time.monotonic() >= deadline:
        raise AwsError(service, operation, 'OperationDeadlineExceeded')
    try:
        response = getattr(client(context, service), operation)(**arguments)
    except ClientError as error:
        details = error.response.get('Error', {})
        code = details.get('Code', 'Unknown')
        status = error.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        message = details.get('Message', '').lower()
        # ValidationException/ResourceNotFound alone never proves a Stack is absent.
        absent = (service == 'cloudformation' and operation == 'describe_stacks'
                  and code == 'ValidationError' and 'stack' in message and 'does not exist' in message)
        missing = (service == 'secretsmanager' and operation == 'get_secret_value'
                   and code == 'ResourceNotFoundException' and 'awscurrent' in message
                   and any(word in message for word in ('not found', "can't find", 'cannot find', 'not exist', 'missing')))
        raise AwsError(service, operation, code, status, stack_absent=absent, current_missing=missing) from None
    except BotoCoreError as error:
        raise AwsError(service, operation, type(error).__name__) from None
    # A received success is authoritative, especially after a mutation. Continuations
    # have their own deadline; socket timeouts do not cancel an entire SDK operation.
    return response


def pages(context, service, operation, field, arguments):
    """Return only a complete inventory; invalid/repeated continuation tokens fail closed."""
    deadline = time.monotonic() + API_BUDGET_SECONDS
    result, items, seen, token = {}, [], set(), None
    while True:
        response = request(context, service, operation, arguments | ({'NextToken': token} if token else {}), deadline=deadline)
        values = response.get(field, [])
        if not isinstance(values, list):
            raise AwsError(service, operation, 'InvalidPage')
        items.extend(values)
        if not result:
            result = {key: value for key, value in response.items() if key not in {field, 'NextToken', 'ResponseMetadata'}}
        elif any(response.get(key) != result.get(key) for key in ('StackId', 'ChangeSetId', 'Status', 'ExecutionStatus', 'ARN') if key in result):
            raise AwsError(service, operation, 'PageIdentityChanged')
        token = response.get('NextToken')
        if token is None:
            return result | {field: items}
        if not isinstance(token, str) or not token or token in seen:
            raise AwsError(service, operation, 'InvalidContinuationToken')
        seen.add(token)
