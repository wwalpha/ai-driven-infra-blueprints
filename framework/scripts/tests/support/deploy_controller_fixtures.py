"""Private Project data and operation-specific SDK replies for the real controller.

Only JSON AWS state and session files survive a child process. Framework definitions
are read from the installed source; no Framework copy or controller substitution.
"""
import base64
from contextlib import ExitStack
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / 'tests')]
from support.fixture_cases import load_case, materialize_files
from support.model_sources import allocate_fixture, write_model
from support.worktree_task_fixtures import cli as worktree_cli
from model.files import read_model
from utils.cloudformation_format import decode

ACCOUNT = '123456789012'
REGION = 'ap-northeast-1'


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, text=True).stdout


def seed(root, state_path, case='orders'):
    fixture = load_case('deploy_controller', case)
    root.mkdir()
    materialize_files(root, fixture['files'])
    if fixture['data'].get('bootstrap'):
        first = root / 'infra/cloudformation/templates/first.yaml'
        document, errors = decode(first.read_text())
        assert not errors
        document['Resources']['Secret'] = {'Type': 'AWS::SecretsManager::Secret', 'Properties': {'Name': 'app-dev-secret'}}
        document['Outputs'] = {'SecretId': {'Value': {'Ref': 'Secret'}, 'Export': {'Name': 'FixtureSecret'}}}
        first.write_text(json.dumps(document))
        second = root / 'infra/cloudformation/templates/second.yaml'
        document, errors = decode(second.read_text())
        assert not errors
        document['Resources']['Consumer'] = {'Type': 'AWS::QuickSight::DataSource', 'Properties': {
            'AwsAccountId': ACCOUNT, 'DataSourceId': 'app-dev-source', 'Name': 'app-dev-source', 'Type': 'POSTGRESQL',
            'Credentials': {'CredentialPair': {key: {'Fn::Sub': ['{{resolve:secretsmanager:${Secret}:SecretString:' + key.lower() + '}}',
                {'Secret': {'Fn::ImportValue': 'FixtureSecret'}}]} for key in ('Username', 'Password')}}}}
        second.write_text(json.dumps(document))
    services = ['s3', 'ec2'] + (['secretsmanager', 'quicksight'] if fixture['data'].get('bootstrap') else [])
    model = root / 'model/dev' / ACCOUNT
    stack_values = {'desired.deployment.maxConcurrentStacks': '2'}
    for number, name in enumerate(('cfn-stack-app-dev-first', 'cfn-stack-app-dev-second'), 1):
        for key, value in {'name': name, 'template': ('first' if number == 1 else 'second') + '.yaml',
                           'parameters': ('first' if number == 1 else 'second') + '.json',
                           'deployOrder': '10' if number == 1 or fixture['data'].get('same_group') else '20'}.items():
            stack_values[f'desired.stack.{number:03}.{key}'] = value
        stack_values[f'display.stack.{number:03}.comment'] = '合成Stack'
    if fixture['data'].get('delivery'):
        stack_values.update({'desired.deployment.templateBucket': '[assets](s3.md#resource-S3_Bucket_002)',
                             'desired.deployment.templateKeyPrefix': 'templates/'})
        for name in ('first', 'second'):
            template = root / 'infra/cloudformation/templates' / (name + '.yaml')
            template.write_text(template.read_text() + 'Description: ' + 'x' * 52000 + '\n')
    write_model(model / 'cloudformation-stacks.properties', stack_values)
    for service in services:
        values = fixture['data'][service]
        values.update(allocate_fixture(values, ['001', '002'] if service in ('s3', 'ec2') else ['001']))
        values[f'desired.service.{service}.serviceId'] = service
        values[f'desired.service.{service}.ownedCatalogResourceTypes'] = ','.join(sorted({v for k, v in values.items() if k.endswith('.resourceType')} |
            {'.'.join(v.split('.')[:2]) for k, v in values.items() if k.startswith('desired.row.') and k.endswith('.property')}))
        values['display.service.title'] = '# 合成詳細設計'
        for identity in ('001', '002') if service in ('s3', 'ec2') else ('001',):
            values[f'display.resource.{identity}.comment'] = '合成resource'
        write_model(model / (service + '.properties'), values)
    import sync_runtime
    # This is fixture initialization through real generation; publication is tested by the controller.
    from task_contract import selected_task
    task = root / 'tasks/deploy.md'
    task.parent.mkdir()
    files = {task.relative_to(root).as_posix()}
    files.update(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
    for service in [*services, 'cloudformation-stacks']:
        files.add(f'docs/designs/dev/{ACCOUNT}/{service}.md')
        files.update(f'model/dev/{ACCOUNT}/{service}/part-{i:03}.properties' for i in (1, 2, 3))
    files.add(f'docs/designs/dev/{ACCOUNT}/s3/s3-bucket-001-bucket-policy.json')
    listed = ''.join('- `' + value + '`\n' for value in sorted(files))
    task.write_text('## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n'
        '- Infrastructure phase: `deploy`\n- AWS API execution: `allowed`\n- Deploy/apply: `allowed`\n'
        f'- Target environment: `dev`\n- Target AWS account: `{ACCOUNT}`\n'
        '- Deployment scope: `cfn-stack-app-dev-first`, `cfn-stack-app-dev-second`\n- Authorized delete/replacement: `none`\n'
        f'- Controlled repair: `allowed`\n- Deploy repair session: `{state_path}`\n'
        '## Required changes\n- [R1] Synthetic deployment\n## Acceptance checks\n- [R1] `exists:project.json`\n'
        '## Validation scope\n' + ''.join(f'- `dev/{ACCOUNT}/{s}`\n' for s in [*services, 'cloudformation-stacks']) +
        '## Modified files\n' + listed + '## Allowed paths\n' + listed)
    with selected_task(root, 'tasks/deploy.md'):
        assert sync_runtime.sync(root, True, 'dev', ACCOUNT, services=[*services, 'cloudformation-stacks']) == 0
    (root / '.gitignore').write_text('/.worktrees/\n', encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.name', 'Offline Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'Synthetic inputs')
    # Reuse the real lifecycle fixture; only Python installation is stubbed there.
    return Path(worktree_cli(root, 'create', task_id='deploy')['worktree'])


def aws_state(path, **knobs):
    path.write_text(json.dumps({'stacks': {}, 'changes': {}, 'calls': [], 'objects': {}, 'versions': {}, 'knobs': knobs}))


def clients(root, state_path, aws_path):
    """A finite set of SDK operations; unexpected calls have no network fallback."""
    from botocore.exceptions import ClientError, ReadTimeoutError
    gate = RLock()
    secret = f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:app-dev-secret-abcdef'

    def request(service, operation, **arguments):
        with gate:
            state = json.loads(aws_path.read_text())
            knobs = state['knobs']
            public = {k: v for k, v in arguments.items() if k not in {'Body', 'SecretString', 'TemplateBody'}}
            state['calls'].append([service, operation, public])
            def persist():
                aws_path.write_text(json.dumps(state))
            def error(code, message='', status=400):
                persist()
                raise ClientError({'Error': {'Code': code, 'Message': message},
                                   'ResponseMetadata': {'HTTPStatusCode': status}}, operation)
            name = arguments.get('StackName', '')
            name = name.split(':stack/')[-1].split('/')[0]
            stack_id = f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{name}/fixture'
            result = None
            if service == 'sts' and operation == 'get_caller_identity':
                result = {'Account': ACCOUNT, 'Arn': f'arn:aws:iam::{ACCOUNT}:user/fixture', 'UserId': 'fixture'}
            elif service == 'cloudformation':
                stack = state['stacks'].get(name)
                if operation == 'list_exports':
                    result = {'Exports': [{'Name': 'FixtureSecret', 'Value': secret, 'ExportingStackId': state['stacks']['cfn-stack-app-dev-first']['id']}]}
                elif operation == 'get_template':
                    result = {'TemplateBody': state['changes'][name]['document']}
                elif operation == 'validate_template':
                    result = {'Parameters': []}
                elif operation == 'describe_stacks':
                    if stack is None: error('ValidationError', 'Stack with id fixture does not exist')
                    result = {'Stacks': [{'StackId': stack_id, 'StackName': name, 'StackStatus': stack['status'],
                        **({'Outputs': [{'OutputKey': 'SecretId', 'OutputValue': secret}]} if knobs.get('bootstrap') and name == 'cfn-stack-app-dev-first' else {})}]}
                elif operation == 'create_change_set':
                    if name == 'cfn-stack-app-dev-second' and not knobs.get('same_group'):
                        saved = json.loads(state_path.read_text())
                        assert saved['states']['cfn-stack-app-dev-first']['observedSynced']
                        assert 'subnet-fixture' in read_model(root / f'model/dev/{ACCOUNT}/ec2.properties')
                    if knobs.get('delivery'):
                        saved = json.loads(state_path.read_text())
                        assert all(saved['states'][n].get('delivery', {}).get('objects') for n in ('cfn-stack-app-dev-first', 'cfn-stack-app-dev-second'))
                    if 'TemplateBody' in arguments:
                        document, errors = decode(arguments['TemplateBody'])
                    else:
                        from urllib.parse import urlsplit, unquote
                        key = unquote(urlsplit(arguments['TemplateURL']).path.lstrip('/').partition('/')[2])
                        document, errors = decode(base64.b64decode(state['objects'][key]['data']).decode())
                    assert not errors
                    change = f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:changeSet/{arguments["ChangeSetName"]}/fixture'
                    state['changes'][name] = {'id': change, 'alias': arguments['ChangeSetName'], 'document': document,
                                               'executed': False, 'stackId': stack_id}
                    result = {'Id': change, 'StackId': stack_id}
                elif operation == 'describe_change_set':
                    change = state['changes'][name]
                    assert arguments['ChangeSetName'] in (change['id'], change['alias'])
                    changes = [{'ResourceChange': {'Action': 'Modify' if knobs.get('approval') and name == 'cfn-stack-app-dev-first' else 'Add',
                        'Replacement': 'True' if knobs.get('approval') and name == 'cfn-stack-app-dev-first' else 'False',
                        'LogicalResourceId': logical, 'ResourceType': definition['Type']}}
                        for logical, definition in change['document']['Resources'].items() if definition.get('Condition') != 'Disabled']
                    result = {'ChangeSetId': change['id'], 'StackId': change['stackId'], 'Status': 'CREATE_COMPLETE',
                              'ExecutionStatus': 'EXECUTE_COMPLETE' if change['executed'] else 'AVAILABLE', 'Changes': changes}
                elif operation == 'execute_change_set':
                    change = state['changes'][name]
                    assert not change['executed'], 'duplicate Execute'
                    assert arguments['ChangeSetName'] == change['id']
                    change.update(executed=True, token=arguments['ClientRequestToken'])
                    failed = name == 'cfn-stack-app-dev-second' and (knobs.get('bootstrap') and not any('AWSCURRENT' in v for v in state['versions'].values())
                        or knobs.get('repair') and change['document']['Resources']['Vpc']['Properties']['CidrBlock'] != '10.0.0.0/16')
                    state['stacks'][name] = {'status': 'ROLLBACK_COMPLETE' if failed else 'CREATE_COMPLETE', 'id': stack_id}
                    change['failed'] = failed
                    if knobs.pop('edit_input', False):
                        template = root / 'infra/cloudformation/templates/second.yaml'
                        template.write_text(template.read_text() + '# concurrent edit\n')
                    if knobs.pop('crash_execute', False):
                        persist(); os._exit(73)
                    if knobs.pop('lost_response', False):
                        persist(); raise ReadTimeoutError(endpoint_url='https://offline.invalid')
                    result = {}
                elif operation == 'describe_stack_events':
                    change = state['changes'].get(name)
                    failed = change and change.get('failed')
                    events = [] if not change or not change['executed'] else [{
                        'StackId': stack_id, 'ResourceType': 'AWS::CloudFormation::Stack',
                        'ClientRequestToken': change['token'], 'ResourceStatus': 'ROLLBACK_COMPLETE' if failed else 'CREATE_COMPLETE'}]
                    if failed:
                        events.append({'StackId': stack_id, 'ClientRequestToken': change['token'], 'ResourceStatus': 'CREATE_FAILED',
                            'LogicalResourceId': 'Consumer' if knobs.get('bootstrap') else 'Vpc',
                            'ResourceType': 'AWS::QuickSight::DataSource' if knobs.get('bootstrap') else 'AWS::EC2::VPC',
                            'ResourceStatusReason': 'AWSCURRENT secret value not found' if knobs.get('bootstrap') else 'invalid CidrBlock'})
                    result = {'StackEvents': events}
                elif operation == 'list_stack_resources':
                    document = state['changes'].get(name, {}).get('document', {})
                    result = {'StackResourceSummaries': [{'LogicalResourceId': logical, 'ResourceType': definition['Type'],
                        'PhysicalResourceId': secret if logical == 'Secret' else 'app-dev-bucket' if logical == 'Bucket' else 'vpc-fixture' if logical == 'Vpc' else 'subnet-fixture' if logical == 'Subnet' else 'integrated-child',
                        'ResourceStatus': 'CREATE_COMPLETE'} for logical, definition in document.get('Resources', {}).items()
                        if definition.get('Condition') != 'Disabled']}
                    if stack and stack['status'] == 'ROLLBACK_COMPLETE':
                        result = {'StackResourceSummaries': []}
                elif operation == 'delete_stack':
                    assert stack and stack['status'] == 'ROLLBACK_COMPLETE'
                    state['stacks'].pop(name)
                    if knobs.pop('crash_cleanup', False):
                        persist(); os._exit(74)
                    result = {}
                else:
                    raise AssertionError((service, operation))
            elif service == 'secretsmanager':
                assert arguments['SecretId'] == secret
                versions = state['versions']
                if operation == 'describe_secret':
                    result = {'ARN': secret, 'Name': 'app-dev-secret', 'VersionIdsToStages': {k: v for k, v in versions.items() if v}}
                elif operation == 'list_secret_version_ids':
                    result = {'ARN': secret, 'Versions': [{'VersionId': k, 'VersionStages': v} for k, v in versions.items()]}
                elif operation == 'get_secret_value':
                    current = [k for k, v in versions.items() if 'AWSCURRENT' in v]
                    if not current: error('ResourceNotFoundException', 'AWSCURRENT not found')
                    assert len(current) == 1
                    result = {'ARN': secret, 'VersionId': current[0], 'VersionStages': versions[current[0]], 'SecretString': 'synthetic'}
                elif operation == 'put_secret_value':
                    token = arguments['ClientRequestToken']
                    assert token not in versions
                    assert arguments['VersionStages'] == ['BLUEPRINT_BOOTSTRAP_' + token]
                    versions[token] = arguments['VersionStages']
                    if knobs.pop('crash_bootstrap', False):
                        persist(); os._exit(75)
                    result = {'ARN': secret, 'VersionId': token, 'VersionStages': versions[token]}
                elif operation == 'update_secret_version_stage':
                    assert 'RemoveFromVersionId' not in arguments
                    assert not any('AWSCURRENT' in v for v in versions.values())
                    versions[arguments['MoveToVersionId']].append('AWSCURRENT')
                    result = {'ARN': secret}
                else: raise AssertionError((service, operation))
            elif service == 's3':
                assert arguments['ExpectedBucketOwner'] == ACCOUNT
                if operation == 'head_bucket': result = {}
                elif operation == 'get_bucket_location': result = {'LocationConstraint': REGION}
                elif operation == 'get_bucket_encryption':
                    result = {'ServerSideEncryptionConfiguration': {'Rules': [{'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]}}
                elif operation == 'get_bucket_policy': error('NoSuchBucketPolicy', status=404)
                elif operation == 'put_object':
                    if knobs.get('delivery_fail'): error('AccessDenied', status=403)
                    assert arguments['IfNoneMatch'] == '*'
                    key = arguments['Key']
                    if key in state['objects']: error('PreconditionFailed', status=412)
                    data = arguments['Body'].read()
                    checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
                    assert checksum == arguments['ChecksumSHA256']
                    state['objects'][key] = {'data': base64.b64encode(data).decode(), 'ChecksumSHA256': checksum,
                        'ContentLength': len(data), 'VersionId': 'v1', 'ServerSideEncryption': 'AES256'}
                    result = {'VersionId': 'v1'}
                elif operation == 'head_object':
                    if arguments['Key'] not in state['objects']: error('NotFound', status=404)
                    result = {k: v for k, v in state['objects'][arguments['Key']].items() if k != 'data'}
                else: raise AssertionError((service, operation))
            else:
                raise AssertionError((service, operation))
            assert result is not None, (service, operation)
            persist()
            return result

    operations = {'sts': ['get_caller_identity'], 'cloudformation': ['validate_template', 'describe_stacks',
        'create_change_set', 'describe_change_set', 'execute_change_set', 'describe_stack_events',
        'list_stack_resources', 'delete_stack', 'get_template', 'list_exports'],
        'secretsmanager': ['describe_secret', 'list_secret_version_ids', 'get_secret_value', 'put_secret_value', 'update_secret_version_stage'], 's3': ['head_bucket', 'get_bucket_location', 'get_bucket_encryption',
        'get_bucket_policy', 'put_object', 'head_object']}
    def client(context, service):
        return SimpleNamespace(**{op: partial(request, service, op) for op in operations[service]})
    return client


def invoke(root, state_path, aws_path, options=(), fail_observed=False):
    from deploy.controller import main
    original_write = Path.write_text
    def write(path, text, *args, **kwargs):
        if fail_observed and path == root / f'model/dev/{ACCOUNT}/ec2.properties' and 'observed.row.' in text:
            raise OSError('injected observed I/O failure')
        return original_write(path, text, *args, **kwargs)
    with ExitStack() as stack:
        stack.enter_context(patch('utils.aws.client.client', clients(root, state_path, aws_path)))
        stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('network forbidden')))
        stack.enter_context(patch('socket.socket.connect_ex', side_effect=AssertionError('network forbidden')))
        if fail_observed: stack.enter_context(patch.object(Path, 'write_text', write))
        return main(['--environment', 'dev', '--aws-account-id', ACCOUNT, '--stack', 'cfn-stack-app-dev-first', '--stack', 'cfn-stack-app-dev-second',
            '--state', str(state_path), '--timing-log', str(state_path.with_suffix('.timing.jsonl')), *options])


def child_environment():
    return {**os.environ, 'PYTHONPATH': os.pathsep.join([str(SCRIPTS), str(SCRIPTS / 'tests')]),
        'BLUEPRINT_TASK_FILE': 'tasks/deploy.md', 'AWS_EC2_METADATA_DISABLED': 'true',
        'AWS_CONFIG_FILE': os.devnull, 'AWS_SHARED_CREDENTIALS_FILE': os.devnull,
        'AWS_ACCESS_KEY_ID': 'synthetic', 'AWS_SECRET_ACCESS_KEY': 'synthetic'}


if __name__ == '__main__':
    root, state_path, aws_path = map(lambda arg: Path(arg).resolve(), sys.argv[1:4])
    os.chdir(root)
    raise SystemExit(invoke(root, state_path, aws_path, sys.argv[4:]))
