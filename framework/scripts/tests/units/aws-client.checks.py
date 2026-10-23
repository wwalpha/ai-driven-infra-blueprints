"""SDK initialization, context separation, pagination and secret redaction contracts."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import time
import pytest
from botocore.exceptions import ClientError
from utils.aws import client as sdk, cloudformation, secretsmanager


def check_client_concurrency(monkeypatch):
    sdk._sessions.clear(); sdk._clients.clear()
    calls, busy = [], []
    gate = Lock()
    class Session:
        def __init__(self, **kwargs):
            calls.append(('session', kwargs))
        def client(self, service, **kwargs):
            assert gate.acquire(blocking=False), 'shared Session clients constructed concurrently'
            try:
                busy.append(service); time.sleep(.005)
                calls.append(('client', service))
                return object()
            finally:
                gate.release()
    monkeypatch.setattr('boto3.Session', Session)
    a = sdk.connection_context('a', 'ap-northeast-1', '123456789012', 'profile')
    b = sdk.connection_context('b', 'ap-northeast-1', '123456789012', 'profile')
    contexts = [a] * 24 + [b] * 8
    with ThreadPoolExecutor(max_workers=12) as pool:
        clients = list(pool.map(lambda c: sdk.client(c, 's3'), contexts))
        other = list(pool.map(lambda s: sdk.client(a, s), ['kms', 'sts', 'kms', 'sts']))
    assert len({id(c) for c in clients[:24]}) == 1 and clients[0] is not clients[-1]
    assert calls.count(('client', 's3')) == 2 and len([c for c in calls if c[0] == 'session']) == 2
    assert other[0] is other[2] and other[1] is other[3]
    for changed in (('a', 'us-east-1', '123456789012', 'profile'), ('a', 'ap-northeast-1', '999999999999', 'profile'),
                    ('a', 'ap-northeast-1', '123456789012', 'web-identity')):
        assert sdk.client(changed, 's3') is not clients[0]
    sdk._sessions.clear(); sdk._clients.clear()


def check_initialization_failure(monkeypatch):
    sdk._sessions.clear(); sdk._clients.clear()
    calls = []
    def create(service, **kwargs):
        calls.append(service)
        if len(calls) == 1:
            raise RuntimeError('initialization failed')
        return object()
    monkeypatch.setattr('boto3.Session', lambda **kwargs: SimpleNamespace(client=create))
    context = ('a', 'ap-northeast-1', '123456789012', 'profile')
    with pytest.raises(RuntimeError): sdk.client(context, 's3')
    assert (context, 's3') not in sdk._clients
    assert sdk.client(context, 's3') is sdk.client(context, 's3') and len(calls) == 2
    sdk._sessions.clear(); sdk._clients.clear()


@pytest.mark.parametrize('operation,field', [('list_exports', 'Exports'), ('list_stack_resources', 'StackResourceSummaries'),
    ('describe_stack_events', 'StackEvents'), ('describe_change_set', 'Changes'), ('list_secret_version_ids', 'Versions')])
def check_complete_pages(monkeypatch, operation, field):
    requests = []
    def request(context, service, op, arguments, **kwargs):
        requests.append(dict(arguments))
        return {field: [{'page': len(requests)}]} | ({'NextToken': 'next'} if len(requests) == 1 else {})
    monkeypatch.setattr(sdk, 'request', request)
    service = secretsmanager if field == 'Versions' else cloudformation
    response = getattr(service, operation)(('context',), StackName='stack')
    assert response[field] == [{'page': 1}, {'page': 2}] and requests[1]['NextToken'] == 'next'
    monkeypatch.setattr(sdk, 'request', lambda *a, **k: {field: [1], 'NextToken': 'repeated'})
    with pytest.raises(sdk.AwsError, match='InvalidContinuationToken'):
        getattr(service, operation)(('context',))


def check_structured_errors_and_secrets(monkeypatch):
    context = ('a', 'ap-northeast-1', '123456789012', 'profile')
    def error(code, message, status=400):
        def request(**kwargs):
            raise ClientError({'Error': {'Code': code, 'Message': message}, 'ResponseMetadata': {'HTTPStatusCode': status}}, 'test')
        return request
    for code, status in [('AccessDenied', 403), ('ExpiredToken', 403), ('ValidationError', 400)]:
        monkeypatch.setattr(sdk, 'client', lambda *a: SimpleNamespace(describe_stacks=error(code, 'private data', status)))
        with pytest.raises(sdk.AwsError) as caught: sdk.request(context, 'cloudformation', 'describe_stacks', {})
        assert caught.value.code == code and not caught.value.stack_absent and 'private data' not in str(caught.value)
    monkeypatch.setattr(sdk, 'client', lambda *a: SimpleNamespace(describe_stacks=error('ValidationError', 'Stack with id x does not exist')))
    with pytest.raises(sdk.AwsError) as caught: sdk.request(context, 'cloudformation', 'describe_stacks', {})
    assert caught.value.stack_absent
    monkeypatch.setattr(secretsmanager, 'request', lambda *a, **k: {'ARN': 'arn', 'VersionId': 'v', 'VersionStages': ['AWSCURRENT'], 'SecretString': 'DO_NOT_RETURN', 'SecretBinary': b'secret'})
    response = secretsmanager.get_secret_value(context, SecretId='arn')
    assert response == {'ARN': 'arn', 'VersionId': 'v', 'VersionStages': ['AWSCURRENT'], 'HasValue': True}





def check_failed_continuation_returns_no_inventory(monkeypatch):
    replies = [{'Changes':[{'Action':'Add'}],'NextToken':'second'}, RuntimeError('second page failed')]
    def request(*args, **kwargs):
        result = replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(sdk,'request',request)
    with pytest.raises(RuntimeError,match='second page failed'):
        cloudformation.describe_change_set(('context',),ChangeSetName='change')
    monkeypatch.setattr(sdk,'request',lambda *a,**k:{'Changes':[],'NextToken':123})
    with pytest.raises(sdk.AwsError,match='InvalidContinuationToken'):
        cloudformation.describe_change_set(('context',),ChangeSetName='change')





def check_effective_default_profile(tmp_path, monkeypatch):
    """Use the actual SDK provider chain with private, synthetic config files."""
    config = tmp_path / 'config'
    credentials = tmp_path / 'credentials'
    config.write_text('[profile one]\nregion = us-east-1\n[profile two]\nregion = us-east-1\n')
    credentials.write_text('[one]\naws_access_key_id = synthetic-one\naws_secret_access_key = synthetic-secret-one\n[two]\naws_access_key_id = synthetic-two\naws_secret_access_key = synthetic-secret-two\n')
    for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('AWS_CONFIG_FILE', str(config))
    monkeypatch.setenv('AWS_SHARED_CREDENTIALS_FILE', str(credentials))
    monkeypatch.setenv('AWS_EC2_METADATA_DISABLED', 'true')
    monkeypatch.setattr('socket.socket.connect', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr('socket.socket.connect_ex', lambda *a, **k: pytest.fail('network forbidden'))
    sdk._sessions.clear(); sdk._clients.clear()
    try:
        monkeypatch.setenv('AWS_DEFAULT_PROFILE', 'one')
        first = sdk.connection_context(None, 'us-east-1', '123456789012')
        a = sdk.client(first, 'sts')
        assert a is sdk.client(sdk.connection_context(None, 'us-east-1', '123456789012'), 'sts')
        assert a._request_signer._credentials.access_key == 'synthetic-one'
        monkeypatch.setenv('AWS_DEFAULT_PROFILE', 'two')
        second = sdk.connection_context(None, 'us-east-1', '123456789012')
        b = sdk.client(second, 'sts')
        assert b is not a
        with pytest.raises(RuntimeError, match='authentication context changed'):
            sdk.client(first, 's3')
        assert b._request_signer._credentials.access_key == 'synthetic-two'
        # An explicit profile overrides both environment profile selectors.
        explicit = sdk.connection_context('one', 'us-east-1', '123456789012')
        assert sdk.client(explicit, 'sts')._request_signer._credentials.access_key == 'synthetic-one'
        from deploy.controller import create_runtime
        target = {'awsProfile': 'one', 'awsRegion': 'us-east-1', 'awsAccountId': '123456789012'}
        assert create_runtime(tmp_path, 'dev', 'test', target).profile == 'one'
        with pytest.raises(RuntimeError, match='profile does not match'):
            create_runtime(tmp_path, 'dev', 'test', target, 'two')
    finally:
        sdk._clients.clear(); sdk._sessions.clear()


def check_sdk_arguments_and_pages(tmp_path, monkeypatch):
    import boto3
    from botocore.stub import Stubber
    session = boto3.Session(aws_access_key_id='synthetic', aws_secret_access_key='synthetic', region_name='us-east-1')
    cfn = session.client('cloudformation')
    monkeypatch.setattr(sdk, 'client', lambda context, service: cfn)
    monkeypatch.setattr('socket.socket.connect', lambda *a, **k: pytest.fail('network forbidden'))
    with Stubber(cfn) as stub:
        stub.add_response('validate_template', {'Parameters': []}, {'TemplateBody': 'Resources: {}'})
        assert cloudformation.validate_template(('offline',), TemplateBody='Resources: {}') == {'Parameters': []}
        export = {'Name': 'Required', 'Value': 'first', 'ExportingStackId': 'stack'}
        stub.add_response('list_exports', {'Exports': [export], 'NextToken': 'next'}, {})
        stub.add_response('list_exports', {'Exports': []}, {'NextToken': 'next'})
        assert cloudformation.list_exports(('offline',))['Exports'] == [export]
        stub.assert_no_pending_responses()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
