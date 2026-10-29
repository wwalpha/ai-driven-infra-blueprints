"""Connection-context Session/client reuse, configuration, and structured API failures."""

import hashlib
import os
import random
import re
import subprocess
import threading
import time
from functools import partial

from utils.aws_sdk import aws_runtime
from utils.cloudformation.inputs import Blocked

_lock = threading.RLock()
_sessions = {}
_clients = {}
API_BUDGET_SECONDS = 60
READ_RATES = {
    "describe_stacks": 5,
    "describe_stack_events": 5,
    "get_template": 5,
    "list_exports": 5,
    "list_imports": 1,
}
_rate_locks, _rate_next = {}, {}
THROTTLING = {
    "Throttling",
    "ThrottlingException",
    "RequestLimitExceeded",
    "TooManyRequestsException",
}


def read_api(account, region, operation, send, *, deadline=None):
    """One-attempt transports only; pace every page/retry across profiles and Threads."""
    deadline = time.monotonic() + API_BUDGET_SECONDS if deadline is None else deadline
    key = account, region, operation
    with _lock:
        gate = _rate_locks.setdefault(key, threading.Lock())
    for attempt in range(5):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not gate.acquire(timeout=remaining):
            raise AwsError("cloudformation", operation, "OperationDeadlineExceeded")
        try:
            delay = max(0, _rate_next.get(key, 0) - time.monotonic())
            if time.monotonic() + delay >= deadline:
                raise AwsError("cloudformation", operation, "OperationDeadlineExceeded")
            if delay:
                time.sleep(delay)
            if time.monotonic() >= deadline:
                raise AwsError("cloudformation", operation, "OperationDeadlineExceeded")
            try:
                return send()
            finally:
                # Keep the slot through transport completion so delayed sends cannot bunch up.
                _rate_next[key] = time.monotonic() + 1 / READ_RATES[operation]
        except Exception as error:
            code = (
                error.code
                if isinstance(error, AwsError)
                else getattr(error, "response", {}).get("Error", {}).get("Code")
            )
            if isinstance(error, subprocess.CalledProcessError):
                match = re.search(r"\(([^)]+)\) when calling", error.stderr or "")
                code = match[1] if match else None
            if code not in THROTTLING or attempt == 4:
                raise
        finally:
            gate.release()
        delay = random.uniform(0.5, 1.0) * 2**attempt
        if time.monotonic() + delay >= deadline:
            raise AwsError("cloudformation", operation, "OperationDeadlineExceeded")
        time.sleep(delay)


def connection_context(profile, region, account, authentication=None):
    if authentication is None:
        routes = tuple(
            (name, os.environ.get(name))
            for name in (
                "AWS_CONFIG_FILE",
                "AWS_SHARED_CREDENTIALS_FILE",
                "AWS_DEFAULT_PROFILE",
                "AWS_PROFILE",
                "AWS_ROLE_ARN",
                "AWS_WEB_IDENTITY_TOKEN_FILE",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                "AWS_CONTAINER_CREDENTIALS_FULL_URI",
            )
        )
        # Distinguish rotating explicit credentials without retaining their material in a key.
        identity = hashlib.sha256(
            "\0".join(
                os.environ.get(k, "")
                for k in (
                    "AWS_ACCESS_KEY_ID",
                    "AWS_SECRET_ACCESS_KEY",
                    "AWS_SESSION_TOKEN",
                )
            ).encode()
        ).hexdigest()
        authentication = ("profile" if profile else "default-chain", routes, identity)
    return profile, region, account, authentication


def client(context, service, *, read=False):
    with _lock:
        if (
            isinstance(context[3], tuple)
            and context[3][:1] in (("profile",), ("default-chain",))
            and connection_context(*context[:3]) != context
        ):
            raise Blocked(
                "AWS authentication context changed; recreate the connection context"
            )
        key = (context, service, read)
        if key not in _clients:
            Config = aws_runtime().sdk_config
            if context not in _sessions:
                _sessions[context] = aws_runtime().connection_session(
                    context[0], context[1]
                )
            # Session client construction is not thread-safe even across different services.
            created = _sessions[context].client(
                service,
                config=Config(
                    retries={
                        "mode": "standard",
                        "total_max_attempts": 1 if read else 2,
                    },
                    connect_timeout=5,
                    read_timeout=20,
                    max_pool_connections=20,
                ),
            )
            _clients[key] = created
        return _clients[key]


class AwsError(Blocked):
    def __init__(
        self,
        service,
        operation,
        code,
        status=None,
        *,
        stack_absent=False,
        current_missing=False,
    ):
        self.code, self.http_status = code, status
        self.stack_absent, self.current_missing = stack_absent, current_missing
        super().__init__(
            f"{service}.{operation} failed ({code})"
            + ("; stack does not exist" if stack_absent else "")
        )


def empty_list_imports(service, operation, code, message, arguments):
    export = arguments.get("ExportName")
    if (
        service != "cloudformation"
        or operation != "list_imports"
        or code != "ValidationError"
        or "NextToken" in arguments
        or not isinstance(export, str)
        or not export
        or not isinstance(message, str)
    ):
        return False
    return message in (
        f"Export '{export}' is not imported by any stack",
        f"Export '{export}' is not imported by any stack.",
        f"Export {export} is not imported by any stack",
        f"Export {export} is not imported by any stack.",
    )


def request(context, service, operation, arguments, *, deadline=None):
    """One request, with no application guards and no secret-bearing error text."""
    BotoCoreError = aws_runtime().BotoCoreError
    ClientError = aws_runtime().ClientError
    deadline = time.monotonic() + API_BUDGET_SECONDS if deadline is None else deadline
    if time.monotonic() >= deadline:
        raise AwsError(service, operation, "OperationDeadlineExceeded")
    try:
        controlled = service == "cloudformation" and operation in READ_RATES
        send = partial(
            getattr(
                client(context, service, read=True)
                if controlled
                else client(context, service),
                operation,
            ),
            **arguments,
        )
        response = (
            read_api(context[2], context[1], operation, send, deadline=deadline)
            if controlled
            else send()
        )
    except ClientError as error:
        details = error.response.get("Error", {})
        code = details.get("Code", "Unknown")
        if empty_list_imports(
            service, operation, code, details.get("Message"), arguments
        ):
            return {"Imports": []}
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        raw_message = details.get("Message", "")
        message = raw_message.lower() if isinstance(raw_message, str) else ""
        # ValidationException/ResourceNotFound alone never proves a Stack is absent.
        absent = (
            service == "cloudformation"
            and operation == "describe_stacks"
            and code == "ValidationError"
            and isinstance(arguments.get("StackName"), str)
            and bool(arguments["StackName"])
            and raw_message == f"Stack with id {arguments['StackName']} does not exist"
        )
        missing = (
            service == "secretsmanager"
            and operation == "get_secret_value"
            and code == "ResourceNotFoundException"
            and "awscurrent" in message
            and any(
                word in message
                for word in (
                    "not found",
                    "can't find",
                    "cannot find",
                    "not exist",
                    "missing",
                )
            )
        )
        raise AwsError(
            service,
            operation,
            code,
            status,
            stack_absent=absent,
            current_missing=missing,
        ) from None
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
        page_arguments = arguments | ({"NextToken": token} if token else {})
        response = request(
            context, service, operation, page_arguments, deadline=deadline
        )
        values = response.get(field, [])
        if (
            service == "cloudformation"
            and operation == "list_imports"
            and "Imports" not in response
        ):
            raise AwsError(service, operation, "InvalidPage")
        if (
            service == "cloudformation"
            and operation == "describe_change_set"
            and response.get("Status") == "FAILED"
            and field not in response
        ):
            raise AwsError(service, operation, "InvalidPage")
        if not isinstance(values, list):
            raise AwsError(service, operation, "InvalidPage")
        items.extend(values)
        if not result:
            result = {
                key: value
                for key, value in response.items()
                if key not in {field, "NextToken", "ResponseMetadata"}
            }
        elif any(
            response.get(key) != result.get(key)
            for key in ("StackId", "ChangeSetId", "Status", "ExecutionStatus", "ARN")
            if key in result
        ):
            raise AwsError(service, operation, "PageIdentityChanged")
        token = response.get("NextToken")
        if token is None:
            return result | {field: items}
        if not isinstance(token, str) or not token or token in seen:
            raise AwsError(service, operation, "InvalidContinuationToken")
        seen.add(token)
