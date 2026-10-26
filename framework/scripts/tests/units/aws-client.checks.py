"""SDK initialization, context separation, pagination and secret redaction contracts."""

import sys
from functools import partial as _bind_framework_callback
from functools import partialmethod as _bind_framework_method
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from support.cloudformation_destroy_fixtures import M as destroy
from utils.aws import client as sdk
from utils.aws import cloudformation, secretsmanager

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

_CALLBACK_DEFAULT = object()


def _callback_check_client_concurrency_Session___init__(self, calls, /, **kwargs):
    calls.append(("session", kwargs))


def _callback_check_client_concurrency_Session_client(
    self, busy, calls, gate, /, service, **kwargs
):
    assert kwargs["config"].retries == {"mode": "standard", "total_max_attempts": 2}
    assert gate.acquire(blocking=False), (
        "shared Session clients constructed concurrently"
    )
    try:
        busy.append(service)
        time.sleep(0.005)
        calls.append(("client", service))
        return object()
    finally:
        gate.release()


def check_client_concurrency(monkeypatch):
    sdk._sessions.clear()
    sdk._clients.clear()
    calls, busy = [], []
    gate = Lock()

    class Session:
        __init__ = _bind_framework_method(
            _callback_check_client_concurrency_Session___init__, calls
        )
        client = _bind_framework_method(
            _callback_check_client_concurrency_Session_client, busy, calls, gate
        )

    monkeypatch.setattr("boto3.Session", Session)
    a = sdk.connection_context("a", "ap-northeast-1", "123456789012", "profile")
    b = sdk.connection_context("b", "ap-northeast-1", "123456789012", "profile")
    contexts = [a] * 24 + [b] * 8
    with ThreadPoolExecutor(max_workers=12) as pool:
        clients = list(pool.map(lambda c: sdk.client(c, "s3"), contexts))
        other = list(pool.map(lambda s: sdk.client(a, s), ["kms", "sts", "kms", "sts"]))
    assert len({id(c) for c in clients[:24]}) == 1 and clients[0] is not clients[-1]
    assert (
        calls.count(("client", "s3")) == 2
        and len([c for c in calls if c[0] == "session"]) == 2
    )
    assert other[0] is other[2] and other[1] is other[3]
    for changed in (
        ("a", "us-east-1", "123456789012", "profile"),
        ("a", "ap-northeast-1", "999999999999", "profile"),
        ("a", "ap-northeast-1", "123456789012", "web-identity"),
    ):
        assert sdk.client(changed, "s3") is not clients[0]
    sdk._sessions.clear()
    sdk._clients.clear()


def _callback_check_initialization_failure_create(calls, /, service, **kwargs):
    calls.append(service)
    if len(calls) == 1:
        raise RuntimeError("initialization failed")
    return object()


def check_initialization_failure(monkeypatch):
    sdk._sessions.clear()
    sdk._clients.clear()
    calls = []
    create = _bind_framework_callback(
        _callback_check_initialization_failure_create, calls
    )
    monkeypatch.setattr(
        "boto3.Session", lambda **kwargs: SimpleNamespace(client=create)
    )
    context = ("a", "ap-northeast-1", "123456789012", "profile")
    with pytest.raises(RuntimeError):
        sdk.client(context, "s3")
    assert (context, "s3", False) not in sdk._clients
    assert sdk.client(context, "s3") is sdk.client(context, "s3") and len(calls) == 2
    sdk._sessions.clear()
    sdk._clients.clear()


def _callback_check_complete_pages_request(
    field, requests, /, context, service, op, arguments, **kwargs
):
    requests.append(dict(arguments))
    return {field: [{"page": len(requests)}]} | (
        {"NextToken": "next"} if len(requests) == 1 else {}
    )


@pytest.mark.parametrize(
    "operation,field",
    [
        ("list_exports", "Exports"),
        ("list_imports", "Imports"),
        ("list_stack_resources", "StackResourceSummaries"),
        ("describe_stack_events", "StackEvents"),
        ("describe_change_set", "Changes"),
        ("list_secret_version_ids", "Versions"),
    ],
)
def check_complete_pages(monkeypatch, operation, field):
    requests = []
    request = _bind_framework_callback(
        _callback_check_complete_pages_request, field, requests
    )
    monkeypatch.setattr(sdk, "request", request)
    service = secretsmanager if field == "Versions" else cloudformation
    response = getattr(service, operation)(("context",), StackName="stack")
    assert (
        response[field] == [{"page": 1}, {"page": 2}]
        and requests[1]["NextToken"] == "next"
    )
    monkeypatch.setattr(
        sdk, "request", lambda *a, **k: {field: [1], "NextToken": "repeated"}
    )
    with pytest.raises(sdk.AwsError, match="InvalidContinuationToken"):
        getattr(service, operation)(("context",))


def _callback_check_structured_errors_and_secrets_error_request(
    code, message, status, /, **kwargs
):
    raise ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "test",
    )


def _callback_check_structured_errors_and_secrets_error_114(
    _default_status, /, code, message, status=_CALLBACK_DEFAULT
):
    if status is _CALLBACK_DEFAULT:
        status = _default_status
    request = _bind_framework_callback(
        _callback_check_structured_errors_and_secrets_error_request,
        code,
        message,
        status,
    )
    return request


def check_structured_errors_and_secrets(monkeypatch):
    context = ("a", "ap-northeast-1", "123456789012", "profile")
    error = _bind_framework_callback(
        _callback_check_structured_errors_and_secrets_error_114, 400
    )
    for code, status in [
        ("AccessDenied", 403),
        ("ExpiredToken", 403),
        ("ValidationError", 400),
    ]:
        monkeypatch.setattr(
            sdk,
            "client",
            lambda *a, code=code, status=status, **kw: SimpleNamespace(
                describe_stacks=error(code, "private data", status)
            ),
        )
        with pytest.raises(sdk.AwsError) as caught:
            sdk.request(context, "cloudformation", "describe_stacks", {})
        assert (
            caught.value.code == code
            and not caught.value.stack_absent
            and "private data" not in str(caught.value)
        )
    monkeypatch.setattr(
        sdk,
        "client",
        lambda *a, **kw: SimpleNamespace(
            describe_stacks=error("ValidationError", "Stack with id x does not exist")
        ),
    )
    with pytest.raises(sdk.AwsError) as caught:
        sdk.request(context, "cloudformation", "describe_stacks", {})
    assert caught.value.stack_absent
    monkeypatch.setattr(
        secretsmanager,
        "request",
        lambda *a, **k: {
            "ARN": "arn",
            "VersionId": "v",
            "VersionStages": ["AWSCURRENT"],
            "SecretString": "DO_NOT_RETURN",
            "SecretBinary": b"secret",
        },
    )
    response = secretsmanager.get_secret_value(context, SecretId="arn")
    assert response == {
        "ARN": "arn",
        "VersionId": "v",
        "VersionStages": ["AWSCURRENT"],
        "HasValue": True,
    }


def _callback_check_failed_continuation_returns_no_inventory_request(
    replies, /, *args, **kwargs
):
    result = replies.pop(0)
    if isinstance(result, Exception):
        raise result
    return result


def check_failed_continuation_returns_no_inventory(monkeypatch):
    replies = [
        {"Changes": [{"Action": "Add"}], "NextToken": "second"},
        RuntimeError("second page failed"),
    ]
    request = _bind_framework_callback(
        _callback_check_failed_continuation_returns_no_inventory_request, replies
    )
    monkeypatch.setattr(sdk, "request", request)
    with pytest.raises(RuntimeError, match="second page failed"):
        cloudformation.describe_change_set(("context",), ChangeSetName="change")
    monkeypatch.setattr(
        sdk, "request", lambda *a, **k: {"Changes": [], "NextToken": 123}
    )
    with pytest.raises(sdk.AwsError, match="InvalidContinuationToken"):
        cloudformation.describe_change_set(("context",), ChangeSetName="change")


class Clock:
    def __init__(self):
        self.now, self.waits = 100.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


def check_read_sdk_attempts_do_not_change_mutation_clients(monkeypatch):
    session = boto3.Session(
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
        region_name="us-east-1",
    )
    context = ("offline", "us-east-1", "123456789012", "fixture")
    monkeypatch.setattr(sdk, "_clients", {})
    monkeypatch.setattr(sdk, "_sessions", {context: session})
    read = sdk.client(context, "cloudformation", read=True)
    mutation = sdk.client(context, "cloudformation")
    assert read is not mutation
    assert read.meta.config.retries["total_max_attempts"] == 1
    assert mutation.meta.config.retries["total_max_attempts"] == 2


def check_destroy_cli_controls_every_page_and_retry(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(sdk, "time", clock)
    monkeypatch.setattr(sdk, "_rate_locks", {})
    monkeypatch.setattr(sdk, "_rate_next", {})
    monkeypatch.setattr(sdk.random, "uniform", lambda a, b: 1)
    backend = destroy.AwsBackend(
        tmp_path,
        "dev",
        "123456789012",
        {"awsAccountId": "123456789012", "awsRegion": "us-east-1"},
    )
    process = Mock(
        side_effect=[
            SimpleNamespace(
                returncode=0, stdout='{"Imports":["A"],"NextToken":"next"}', stderr=""
            ),
            SimpleNamespace(
                returncode=255,
                stdout="",
                stderr="An error occurred (Throttling) when calling the ListImports operation: slow",
            ),
            SimpleNamespace(returncode=0, stdout='{"Imports":["B"]}', stderr=""),
        ]
    )
    monkeypatch.setattr(destroy.subprocess, "run", process)
    assert backend.aws("list-imports", "--export-name", "Export") == {
        "Imports": ["A", "B"]
    }
    assert process.call_count == 3 and clock.waits == [1, 1]
    for index, call_item in enumerate(process.call_args_list):
        assert "--no-paginate" in call_item.args[0]
        assert call_item.kwargs["env"]["AWS_MAX_ATTEMPTS"] == "1"
        assert ("--next-token" in call_item.args[0]) == (index > 0)
    process.reset_mock()
    with pytest.raises(destroy.Blocked, match="outside standard destroy"):
        backend.aws("list-exports")
    process.assert_not_called()


@pytest.mark.parametrize("token", ["same", "", 123])
def check_destroy_incomplete_pagination_blocks(tmp_path, monkeypatch, token):
    clock = Clock()
    monkeypatch.setattr(sdk, "time", clock)
    monkeypatch.setattr(sdk, "_rate_locks", {})
    monkeypatch.setattr(sdk, "_rate_next", {})
    backend = destroy.AwsBackend(
        tmp_path,
        "dev",
        "123456789012",
        {"awsAccountId": "123456789012", "awsRegion": "us-east-1"},
    )
    process = Mock(
        return_value=SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"Imports": [], "NextToken": token}),
            stderr="",
        )
    )
    monkeypatch.setattr(destroy.subprocess, "run", process)
    with pytest.raises(destroy.Blocked, match="pagination"):
        backend.aws("list-imports", "--export-name", "Export")
    assert process.call_count == (2 if token == "same" else 1)


@pytest.mark.parametrize("operation", list(sdk.READ_RATES))
def check_read_rates_shared_by_eight_threads(monkeypatch, operation):
    clock, sent = Clock(), []
    monkeypatch.setattr(sdk, "time", clock)
    monkeypatch.setattr(sdk, "_rate_locks", {})
    monkeypatch.setattr(sdk, "_rate_next", {})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda _: sdk.read_api(
                    "account",
                    "region",
                    operation,
                    lambda: sent.append(clock.monotonic()),
                ),
                range(24),
            )
        )
    spacing = 1 / sdk.READ_RATES[operation]
    assert len(sent) == 24 and all(
        b - a >= spacing - 1e-9 for a, b in zip(sent, sent[1:], strict=False)
    )
    for account, region in [("other", "region"), ("account", "other")]:
        before = len(clock.waits)
        sdk.read_api(account, region, operation, lambda: None)
        assert len(clock.waits) == before


@pytest.mark.parametrize("operation", list(sdk.READ_RATES))
@pytest.mark.parametrize(
    "code",
    [
        "Throttling",
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "AccessDenied",
        "ValidationError",
    ],
)
def check_reference_retry_and_non_throttling_failure(monkeypatch, operation, code):
    clock = Clock()
    monkeypatch.setattr(sdk, "time", clock)
    monkeypatch.setattr(sdk, "_rate_locks", {})
    monkeypatch.setattr(sdk, "_rate_next", {})
    monkeypatch.setattr(sdk.random, "uniform", lambda a, b: 1)
    error = ClientError({"Error": {"Code": code}}, operation)
    send = Mock(side_effect=[error, {"ok": True}])
    if code in sdk.THROTTLING:
        assert sdk.read_api("account", "region", operation, send) == {"ok": True}
        assert send.call_count == 2 and clock.waits == [1]
    else:
        with pytest.raises(ClientError):
            sdk.read_api("account", "region", operation, send)
        assert send.call_count == 1 and not clock.waits


def check_reference_attempt_limit_and_deadline(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(sdk, "time", clock)
    monkeypatch.setattr(sdk, "_rate_locks", {})
    monkeypatch.setattr(sdk, "_rate_next", {})
    monkeypatch.setattr(sdk.random, "uniform", lambda a, b: 1)
    error = sdk.AwsError("cloudformation", "list_exports", "Throttling", 400)
    send = Mock(side_effect=error)
    with pytest.raises(sdk.AwsError, match="Throttling"):
        sdk.read_api("account", "region", "list_exports", send)
    assert send.call_count == 5 and clock.waits == [1, 2, 4, 8]
    send.reset_mock()
    with pytest.raises(sdk.AwsError, match="OperationDeadlineExceeded"):
        sdk.read_api("other", "region", "list_exports", send, deadline=clock.now + 0.5)
    assert send.call_count == 1
    sdk._rate_next[("other", "region", "list_exports")] = clock.now + 10
    send.reset_mock()
    with pytest.raises(sdk.AwsError, match="OperationDeadlineExceeded"):
        sdk.read_api("other", "region", "list_exports", send, deadline=clock.now + 1)
    send.assert_not_called()


@pytest.mark.parametrize(
    "operation", ["create_change_set", "execute_change_set", "delete_stack"]
)
def check_mutations_keep_single_application_call(monkeypatch, operation):
    send = Mock(side_effect=ClientError({"Error": {"Code": "Throttling"}}, operation))
    monkeypatch.setattr(
        sdk, "client", lambda *a, **kw: SimpleNamespace(**{operation: send})
    )
    with pytest.raises(sdk.AwsError, match="Throttling"):
        sdk.request(
            ("profile", "region", "account", "auth"), "cloudformation", operation, {}
        )
    send.assert_called_once_with()


@pytest.mark.parametrize("missing_page", [0, 1])
def check_failed_changeset_missing_changes_is_not_empty(monkeypatch, missing_page):
    replies = [
        {"Status": "FAILED", "Changes": [], "NextToken": "second"},
        {"Status": "FAILED", "Changes": []},
    ]
    replies[missing_page].pop("Changes")
    monkeypatch.setattr(
        sdk,
        "request",
        _bind_framework_callback(
            _callback_check_failed_continuation_returns_no_inventory_request, replies
        ),
    )
    with pytest.raises(sdk.AwsError, match="InvalidPage"):
        cloudformation.describe_change_set(("context",), ChangeSetName="change")


def check_effective_default_profile(tmp_path, monkeypatch):
    """Use the actual SDK provider chain with private, synthetic config files."""
    config = tmp_path / "config"
    credentials = tmp_path / "credentials"
    config.write_text(
        "[profile one]\nregion = us-east-1\n[profile two]\nregion = us-east-1\n"
    )
    credentials.write_text(
        "[one]\naws_access_key_id = synthetic-one\naws_secret_access_key = synthetic-secret-one\n[two]\naws_access_key_id = synthetic-two\naws_secret_access_key = synthetic-secret-two\n"
    )
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setattr(
        "socket.socket.connect", lambda *a, **k: pytest.fail("network forbidden")
    )
    monkeypatch.setattr(
        "socket.socket.connect_ex", lambda *a, **k: pytest.fail("network forbidden")
    )
    sdk._sessions.clear()
    sdk._clients.clear()
    try:
        monkeypatch.setenv("AWS_DEFAULT_PROFILE", "one")
        first = sdk.connection_context(None, "us-east-1", "123456789012")
        a = sdk.client(first, "sts")
        assert a is sdk.client(
            sdk.connection_context(None, "us-east-1", "123456789012"), "sts"
        )
        assert a._request_signer._credentials.access_key == "synthetic-one"
        monkeypatch.setenv("AWS_DEFAULT_PROFILE", "two")
        second = sdk.connection_context(None, "us-east-1", "123456789012")
        b = sdk.client(second, "sts")
        assert b is not a
        with pytest.raises(RuntimeError, match="authentication context changed"):
            sdk.client(first, "s3")
        assert b._request_signer._credentials.access_key == "synthetic-two"
        # An explicit profile overrides both environment profile selectors.
        explicit = sdk.connection_context("one", "us-east-1", "123456789012")
        assert (
            sdk.client(explicit, "sts")._request_signer._credentials.access_key
            == "synthetic-one"
        )
    finally:
        sdk._clients.clear()
        sdk._sessions.clear()


def check_sdk_arguments_and_pages(tmp_path, monkeypatch):
    session = boto3.Session(
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
        region_name="us-east-1",
    )
    cfn = session.client("cloudformation")
    monkeypatch.setattr(sdk, "client", lambda context, service, **kw: cfn)
    sleep = Mock()
    monkeypatch.setattr(
        sdk, "time", SimpleNamespace(monotonic=lambda: 100, sleep=sleep)
    )
    monkeypatch.setattr(
        "socket.socket.connect", lambda *a, **k: pytest.fail("network forbidden")
    )
    with Stubber(cfn) as stub:
        stub.add_response(
            "validate_template", {"Parameters": []}, {"TemplateBody": "Resources: {}"}
        )
        assert cloudformation.validate_template(
            ("offline",), TemplateBody="Resources: {}"
        ) == {"Parameters": []}
        export = {"Name": "Required", "Value": "first", "ExportingStackId": "stack"}
        stub.add_response(
            "list_exports", {"Exports": [export], "NextToken": "next"}, {}
        )
        stub.add_client_error(
            "list_exports",
            service_error_code="Throttling",
            service_message="private",
            expected_params={"NextToken": "next"},
        )
        stub.add_response("list_exports", {"Exports": []}, {"NextToken": "next"})
        assert cloudformation.list_exports(
            ("offline", "us-east-1", "123456789012", "auth")
        )["Exports"] == [export]
        assert sleep.called
        stub.add_response(
            "list_imports",
            {"Imports": ["Consumer"], "NextToken": "next"},
            {"ExportName": "Required"},
        )
        stub.add_response(
            "list_imports",
            {"Imports": []},
            {"ExportName": "Required", "NextToken": "next"},
        )
        assert cloudformation.list_imports(
            ("offline", "us-east-1", "123456789012", "auth"), ExportName="Required"
        )["Imports"] == ["Consumer"]
        stub.assert_no_pending_responses()


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
