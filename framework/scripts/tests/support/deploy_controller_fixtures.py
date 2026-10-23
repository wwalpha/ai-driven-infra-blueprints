"""Private Project data and operation-specific SDK replies for the real controller.

Only JSON AWS state and session files survive a child process. Framework definitions
are read from the installed source; no Framework copy or controller substitution.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from functools import partial
from functools import partial as _bind_framework_callback
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sysconfig
import urllib.parse as _imports_urllib_parse
import venv

import cloudformation_inputs as _imports_cloudformation_inputs
import generation_inputs as _imports_generation_inputs
import model.format as _imports_model_format
import sync_files as _imports_sync_files
import sync_runtime
import worktree_task as wt
from botocore.exceptions import ClientError, ReadTimeoutError
from cloudformation_inputs import condition_active
from deploy.controller import main
from model.files import read_model
from support.fixture_cases import load_case, materialize_files
from support.model_sources import allocate_fixture, write_model
from support.worktree_task_fixtures import cli as worktree_cli
from task_contract_core import selected_task, start
from utils.cloudformation_format import decode

SCRIPTS = Path(__file__).resolve().parents[2]



ACCOUNT = '123456789012'
REGION = 'ap-northeast-1'


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, text=True).stdout


def seed(root, state_path, case='orders', *, same_group=False, generated_artifacts=False):
    fixture = load_case('deploy_controller', 'orders' if case in {'remove', 'multi-observed'} else case)
    if same_group:
        fixture['data']['same_group'] = True
    root.mkdir()
    materialize_files(root, fixture['files'])
    if case in {'remove', 'multi-observed'}:
        template = root / 'infra/cloudformation/templates/first.yaml'
        document, errors = decode(template.read_text())
        assert not errors
        if case == 'remove':
            for logical in ('Subnet', 'Association'):
                document['Resources'].pop(logical)
            fixture['data']['ec2']['observed.row.002-001.value'] = '`subnet-before`'
        else:
            document['Resources']['VpcFirst'] = {'Type': 'AWS::EC2::VPC', 'Properties': {'CidrBlock': '10.1.0.0/16'}}
            values = fixture['data']['ec2']
            values.update({key.replace('.001.', '.003.').replace('.001-', '.003-'): value
                           for key, value in list(values.items()) if key.startswith(('desired.resource.001.', 'desired.row.001-'))})
            values.update({'desired.resource.003.cfn-logicalId': 'cfn-stack-app-dev-first-VpcFirst',
                'desired.row.003-001.value': '[vpc](#resource-EC2_VPC_002)',
                'desired.row.003-002.value': '`10.1.0.0/16`', 'desired.row.003-003.value': '`app-dev-observed-vpc`'})
            if generated_artifacts:
                fixture['data']['s3'].update({
                    'desired.row.001-004.property': 'S3.Bucket.Tags[].Key', 'desired.row.001-004.value': '`Network`',
                    'desired.row.001-004.comment': '合成参照',
                    'desired.row.001-005.property': 'S3.Bucket.Tags[].Value',
                    'desired.row.001-005.value': '[vpc](ec2.md#resource-EC2_VPC_002)',
                    'desired.row.001-005.comment': '合成参照'})
        template.write_text(json.dumps(document))
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
    if fixture['data'].get('shared_template'):
        first = root / 'infra/cloudformation/templates/first.yaml'
        text = first.read_text().replace('Conditions:\n',
            "Conditions:\n  First: !Equals [!Ref Instance, first]\n  Second: !Equals [!Ref Instance, second]\n")
        text = text.replace('    Type:', '    Condition: First\n    Type:').replace('  OtherBucket:\n    Condition: First', '  OtherBucket:')
        first.write_text('Parameters: {Instance: {Type: String}}\n' + text +
            '\n  Vpc:\n    Type: AWS::EC2::VPC\n    Condition: Second\n    Properties: {CidrBlock: 10.2.0.0/16}\n')
        for instance in ('first','second'):
            (root / f'infra/cloudformation/parameters/dev/{ACCOUNT}/{instance}.json').write_text(
                json.dumps([{'ParameterKey':'Instance','ParameterValue':instance}]))
    if fixture['data'].get('dns_series'):
        fixture['data']['ec2'].update({'desired.row.001-004.property': 'EC2.VPC.EnableDnsSupport',
            'desired.row.001-004.value': '`true`', 'desired.row.001-004.comment': 'DNS利用'})
    services = ['s3', 'ec2'] + (['secretsmanager', 'quicksight'] if fixture['data'].get('bootstrap') else [])
    model = root / 'model/dev' / ACCOUNT
    stack_values = {'desired.deployment.maxConcurrentStacks': '2'}
    for number, name in enumerate(('cfn-stack-app-dev-first', 'cfn-stack-app-dev-second'), 1):
        for key, value in {'name': name, 'template': ('first' if number == 1 else 'second') + '.yaml',
                           'parameters': ('first' if number == 1 else 'second') + '.json',
                           'deployOrder': '10' if number == 1 or fixture['data'].get('same_group') else '20'}.items():
            stack_values[f'desired.stack.{number:03}.{key}'] = value
        if fixture['data'].get('shared_template'):
            stack_values[f'desired.stack.{number:03}.template'] = 'first.yaml'
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
        identities = ['001', '002', '003'] if service == 'ec2' and case == 'multi-observed' else ['001', '002'] if service in ('s3', 'ec2') else ['001']
        values.update(allocate_fixture(values, identities))
        values[f'desired.service.{service}.serviceId'] = service
        values[f'desired.service.{service}.ownedCatalogResourceTypes'] = ','.join(sorted({v for k, v in values.items() if k.endswith('.resourceType')} |
            {'.'.join(v.split('.')[:2]) for k, v in values.items() if k.startswith('desired.row.') and k.endswith('.property')}))
        values['display.service.title'] = '# 合成詳細設計'
        for identity in identities:
            values[f'display.resource.{identity}.comment'] = '合成resource'
        source = model / (service + '.properties')
        write_model(source, values)
        if service == 'ec2' and case == 'multi-observed':
            split = _imports_model_format.split
            save_files = _imports_sync_files.save_files
            save_files(split(source, values, limit=1))

    # This is fixture initialization through real generation; publication is tested by the controller.
    task = root / 'tasks/deploy.md'
    files = {task.relative_to(root).as_posix()}
    files.update(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
    for service in [*services, 'cloudformation-stacks']:
        files.add(f'docs/designs/dev/{ACCOUNT}/{service}.md')
    files.add(f'docs/designs/dev/{ACCOUNT}/s3/s3-bucket-001-bucket-policy.json')
    listed = ''.join('- `' + value + '`\n' for value in sorted(files))
    contract = ('## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n'
        '- Infrastructure phase: `deploy`\n- AWS API execution: `allowed`\n- Deploy/apply: `allowed`\n'
        f'- Target environment: `dev`\n- Target AWS account: `{ACCOUNT}`\n'
        '- Deployment scope: `cfn-stack-app-dev-first`, `cfn-stack-app-dev-second`\n- Authorized delete/replacement: `none`\n'
        f'- Runtime recovery: `allowed`\n- External IaC repair: `allowed`\n- Deploy repair session: `{state_path}`\n'
        '## Required changes\n- [R1] Synthetic deployment\n## Acceptance checks\n- [R1] `exists:project.json`\n'
        '## Validation scope\n' + ''.join(f'- `dev/{ACCOUNT}/{s}`\n' for s in [*services, 'cloudformation-stacks']) +
        '## Modified files\n' + listed + '## Allowed paths\n' + listed)
    start(root, 'tasks/deploy.md', contract)
    with selected_task(root, 'tasks/deploy.md'):
        assert sync_runtime.sync(root, True, 'dev', ACCOUNT, services=[*services, 'cloudformation-stacks']) == 0
    ignore = root / '.gitignore'
    ignore.write_text('tasks/**\n/.worktrees/\n__pycache__/\n')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.name', 'Offline Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'Synthetic inputs')
    # Provision only the interpreter offline; dependencies come from this fixed test runtime.

    directory = root / '.worktrees/.blueprint/python-env'
    venv.EnvBuilder(with_pip=False).create(directory)
    version = f'python{sys.version_info.major}.{sys.version_info.minor}'
    packages = directory / 'lib' / version / 'site-packages'
    (packages / 'fixture-runtime.pth').write_text(sysconfig.get_path('purelib') + '\n')
    for marker in ('.blueprint-owner', '.blueprint-ready'):
        (directory / marker).write_text(str(directory))
    saved_contract = '\n'.join(line for line in task.read_text().splitlines() if not line.startswith('- `infra/')) + '\n'
    # Retain master's lifecycle fixture; finish its provisioning through real setup.
    state = worktree_cli(root, 'create', task_id='deploy')
    state = wt.setup(root, 'deploy')
    target = Path(state['worktree'])
    start(target, state['task_file'], saved_contract)
    return target


def aws_state(path, **knobs):
    stacks = {}
    if knobs.get('remove'):
        name = 'cfn-stack-app-dev-first'
        stacks[name] = {'status': 'UPDATE_COMPLETE', 'id': f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{name}/fixture'}
    path.write_text(json.dumps({'stacks': stacks, 'changes': {}, 'calls': [], 'objects': {}, 'versions': {}, 'knobs': knobs}))


def _callback_clients_client(operations, request, /, context, service):
    return SimpleNamespace(**{op: partial(request, service, op) for op in operations[service]})


def _callback_clients_request_persist(aws_path, state, /):
    aws_path.write_text(json.dumps(state))


def _callback_clients_request_active(name, /, definition, change):
    return condition_active(change['document'], {p['ParameterKey']:p['ParameterValue'] for p in change.get('parameters', [])},
        {'AWS::AccountId':ACCOUNT, 'AWS::Region':REGION, 'AWS::StackName':name}, definition)


def _callback_clients_request_error(operation, persist, /, code, message='', status=400):
    persist()
    raise ClientError({'Error': {'Code': code, 'Message': message},
                       'ResponseMetadata': {'HTTPStatusCode': status}}, operation)


def _callback_clients_request(aws_path, gate, root, secret, state_path, /, service, operation, **arguments):
    with gate:
        state = json.loads(aws_path.read_text())
        knobs = state['knobs']
        public = {k: v for k, v in arguments.items() if k not in {'Body', 'SecretString', 'TemplateBody'}}
        state['calls'].append([service, operation, public])
        persist = _bind_framework_callback(_callback_clients_request_persist, aws_path, state)
        error = _bind_framework_callback(_callback_clients_request_error, operation, persist)
        name = arguments.get('StackName', '')
        name = name.split(':stack/')[-1].split('/')[0]
        stack_id = state['stacks'].get(name, {}).get('id') or state['changes'].get(name, {}).get('stackId') or f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{name}/fixture'
        active = _bind_framework_callback(_callback_clients_request_active, name)
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
                if knobs.get('input_stage') == 'validate_template':
                    document, errors = decode(arguments.get('TemplateBody', ''))
                    if document.get('Resources', {}).get('Vpc', {}).get('Properties', {}).get('CidrBlock') == '10.2.0.0/16':
                        error('ValidationError', 'synthetic invalid property; private details omitted')
                result = {'Parameters': []}
            elif operation == 'describe_stacks':
                if stack is None:
                    error('ValidationError', 'Stack with id fixture does not exist')
                result = {'Stacks': [{'StackId': stack_id, 'StackName': name, 'StackStatus': stack['status'],
                    **({'Outputs': [{'OutputKey': 'SecretId', 'OutputValue': secret}]} if knobs.get('bootstrap') and name == 'cfn-stack-app-dev-first' else {})}]}
            elif operation == 'create_change_set':
                if knobs.get('input_stage') == 'create_change_set' and name == 'cfn-stack-app-dev-second':
                    document, errors = decode(arguments.get('TemplateBody', ''))
                    if document['Resources']['Vpc']['Properties']['CidrBlock'] == '10.2.0.0/16':
                        error('ValidationError', 'synthetic invalid property; private details omitted')
                if arguments.get('ChangeSetType') == 'CREATE':
                    stack_id = f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{name}/' + arguments['ChangeSetName']
                if name == 'cfn-stack-app-dev-second' and not knobs.get('same_group'):
                    saved = json.loads(state_path.read_text())
                    assert saved['states']['cfn-stack-app-dev-first']['observedSynced']
                    expected = ('subnet-before' if knobs.get('policy') == 'Retain' or knobs.get('delete_proof') == 'skipped'
                                else 'PENDING_DEPLOY') if knobs.get('remove') else 'subnet-fixture'
                    assert expected in read_model(root / f'model/dev/{ACCOUNT}/ec2.properties')
                if knobs.get('delivery'):
                    saved = json.loads(state_path.read_text())
                    assert all(saved['states'][n].get('delivery', {}).get('objects') for n in ('cfn-stack-app-dev-first', 'cfn-stack-app-dev-second'))
                if 'TemplateBody' in arguments:
                    document, errors = decode(arguments['TemplateBody'])
                else:
                    unquote = _imports_urllib_parse.unquote
                    urlsplit = _imports_urllib_parse.urlsplit
                    key = unquote(urlsplit(arguments['TemplateURL']).path.lstrip('/').partition('/')[2])
                    document, errors = decode(base64.b64decode(state['objects'][key]['data']).decode())
                assert not errors
                change = f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:changeSet/{arguments["ChangeSetName"]}/fixture'
                state['changes'][name] = {'id': change, 'alias': arguments['ChangeSetName'], 'document': document,
                                           'executed': False, 'stackId': stack_id, 'parameters': arguments.get('Parameters', [])}
                if knobs.get('input_stage') == 'changeset_review' and name == 'cfn-stack-app-dev-second' and document['Resources']['Vpc']['Properties']['CidrBlock'] == '10.2.0.0/16':
                    state['changes'][name]['failedReview'] = True
                    state['stacks'][name] = {'status':'REVIEW_IN_PROGRESS', 'id':stack_id}
                result = {'Id': change, 'StackId': stack_id}
            elif operation == 'describe_change_set':
                change = state['changes'][name]
                assert arguments['ChangeSetName'] in (change['id'], change['alias'])
                changes = [{'ResourceChange': {'Action': 'Modify' if knobs.get('approval') and name == 'cfn-stack-app-dev-first' else 'Add',
                    'Replacement': 'True' if knobs.get('approval') and name == 'cfn-stack-app-dev-first' else 'False',
                    'LogicalResourceId': logical, 'ResourceType': definition['Type']}}
                    for logical, definition in change['document']['Resources'].items() if active(definition, change)]
                if knobs.get('remove') and name == 'cfn-stack-app-dev-first':
                    for change_entry in changes:
                        change_entry['ResourceChange'].update(Action='Modify', Replacement='False')
                    changes.append({'ResourceChange': {'Action': 'Remove', 'LogicalResourceId': 'Subnet',
                        'ResourceType': 'AWS::EC2::Subnet', 'PhysicalResourceId': 'subnet-before',
                        'PolicyAction': knobs.get('policy', 'Delete')}})
                result = {'ChangeSetId': change['id'], 'StackId': change['stackId'], 'Status': 'CREATE_COMPLETE',
                          'ExecutionStatus': 'EXECUTE_COMPLETE' if change['executed'] else 'AVAILABLE', 'Changes': changes}
                if change.get('failedReview'):
                    result.update(Status='FAILED', ExecutionStatus='UNAVAILABLE', StatusReason='provider input invalid (HandlerErrorCode: InvalidRequest)')
            elif operation == 'execute_change_set':
                change = state['changes'][name]
                assert not change['executed'], 'duplicate Execute'
                assert arguments['ChangeSetName'] == change['id']
                change.update(executed=True, token=arguments['ClientRequestToken'])
                properties = change['document'].get('Resources', {}).get('Vpc', {}).get('Properties', {})
                if isinstance(properties.get('CidrBlock'), dict):
                    resolve_value = _imports_cloudformation_inputs.resolve_value
                    properties = {**properties, 'CidrBlock': resolve_value(properties['CidrBlock'],
                        {p['ParameterKey']:p['ParameterValue'] for p in change.get('parameters', [])}, {})}
                cidr_failure = (knobs.get('repair') and properties.get('CidrBlock') != '10.0.0.0/16') or knobs.get('repeat_cidr')
                dns_failure = knobs.get('followup_dns') and properties.get('EnableDnsSupport') is not True
                failed = name == 'cfn-stack-app-dev-second' and (knobs.get('bootstrap') and not any('AWSCURRENT' in v for v in state['versions'].values())
                    or cidr_failure or dns_failure)
                change['failureProperty'] = 'EnableDnsSupport' if dns_failure and not cidr_failure else 'CidrBlock'
                state['stacks'][name] = {'status': 'ROLLBACK_COMPLETE' if failed else 'UPDATE_COMPLETE' if knobs.get('remove') and name == 'cfn-stack-app-dev-first' else 'CREATE_COMPLETE', 'id': stack_id}
                change['failed'] = failed
                if knobs.pop('edit_input', False):
                    template = root / 'infra/cloudformation/templates/second.yaml'
                    template.write_text(template.read_text() + '# concurrent edit\n')
                if knobs.pop('crash_execute', False):
                    persist()
                    os._exit(73)
                if knobs.pop('lost_response', False):
                    persist()
                    raise ReadTimeoutError(endpoint_url='https://offline.invalid')
                result = {}
            elif operation == 'describe_stack_events':
                change = state['changes'].get(name)
                failed = change and change.get('failed')
                events = [] if not change or not change['executed'] else [{
                    'StackId': stack_id, 'ResourceType': 'AWS::CloudFormation::Stack',
                    'ClientRequestToken': change['token'], 'ResourceStatus': state['stacks'][name]['status']}]
                if change and change['executed'] and not failed:
                    events.extend({'StackId': stack_id, 'ClientRequestToken': change['token'], 'ResourceStatus': 'CREATE_COMPLETE',
                        'LogicalResourceId': logical, 'ResourceType': definition['Type']} for logical, definition in change['document']['Resources'].items()
                        if active(definition, change))
                if knobs.get('remove') and change and change['executed'] and name == 'cfn-stack-app-dev-first':
                    proof = knobs.get('delete_proof', 'complete')
                    event = {'StackId': stack_id, 'ClientRequestToken': change['token'],
                        'LogicalResourceId': 'Subnet', 'PhysicalResourceId': 'subnet-before',
                        'ResourceType': 'AWS::EC2::Subnet', 'ResourceStatus': 'DELETE_SKIPPED' if proof == 'skipped' else 'DELETE_COMPLETE'}
                    for key, mismatch in [('ClientRequestToken', 'token'), ('StackId', 'stack'), ('PhysicalResourceId', 'physical')]:
                        if proof == mismatch:
                            event[key] = 'unrelated'
                    if proof != 'missing':
                        events.append(event)
                if failed:
                    events.append({'StackId': stack_id, 'ClientRequestToken': change['token'], 'ResourceStatus': 'CREATE_FAILED',
                        'LogicalResourceId': 'Consumer' if knobs.get('bootstrap') else 'Vpc',
                        'ResourceType': 'AWS::QuickSight::DataSource' if knobs.get('bootstrap') else 'AWS::EC2::VPC',
                        'ResourceStatusReason': 'AWSCURRENT secret value not found' if knobs.get('bootstrap') else 'invalid ' + change.get('failureProperty', 'CidrBlock')})
                if name == 'cfn-stack-app-dev-second' and events and knobs.pop('defer_peer', False):
                    events[0]['ResourceStatus'] = 'UPDATE_IN_PROGRESS'
                result = {'StackEvents': events}
            elif operation == 'list_stack_resources':
                document = state['changes'].get(name, {}).get('document', {})
                result = {'StackResourceSummaries': [{'LogicalResourceId': logical, 'ResourceType': definition['Type'],
                    'PhysicalResourceId': secret if logical == 'Secret' else 'app-dev-bucket' if logical == 'Bucket' else 'vpc-first-fixture' if logical == 'VpcFirst' else 'vpc-fixture' if definition['Type'] == 'AWS::EC2::VPC' else 'subnet-fixture' if logical == 'Subnet' else 'integrated-child',
                    'ResourceStatus': 'CREATE_COMPLETE'} for logical, definition in document.get('Resources', {}).items()
                    if active(definition, state['changes'][name])]}
                if stack and stack['status'] in {'ROLLBACK_COMPLETE', 'REVIEW_IN_PROGRESS'}:
                    result = {'StackResourceSummaries': []}
                if knobs.get('remove') and name == 'cfn-stack-app-dev-first' and not state['changes'].get(name, {}).get('executed'):
                    result['StackResourceSummaries'].append({'LogicalResourceId': 'Subnet', 'ResourceType': 'AWS::EC2::Subnet',
                        'PhysicalResourceId': 'subnet-before', 'ResourceStatus': 'CREATE_COMPLETE'})
            elif operation == 'delete_stack':
                assert stack and (stack['status'] == 'ROLLBACK_COMPLETE' or
                    stack['status'] == 'REVIEW_IN_PROGRESS' and state['changes'][name].get('failedReview') and not state['changes'][name]['executed'])
                state['stacks'].pop(name)
                if knobs.pop('crash_cleanup', False):
                    persist()
                    os._exit(74)
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
                if not current:
                    error('ResourceNotFoundException', 'AWSCURRENT not found')
                assert len(current) == 1
                result = {'ARN': secret, 'VersionId': current[0], 'VersionStages': versions[current[0]], 'SecretString': 'synthetic'}
            elif operation == 'put_secret_value':
                token = arguments['ClientRequestToken']
                assert token not in versions
                assert arguments['VersionStages'] == ['BLUEPRINT_BOOTSTRAP_' + token]
                versions[token] = arguments['VersionStages']
                if knobs.pop('crash_bootstrap', False):
                    persist()
                    os._exit(75)
                result = {'ARN': secret, 'VersionId': token, 'VersionStages': versions[token]}
            elif operation == 'update_secret_version_stage':
                assert 'RemoveFromVersionId' not in arguments
                assert not any('AWSCURRENT' in v for v in versions.values())
                versions[arguments['MoveToVersionId']].append('AWSCURRENT')
                result = {'ARN': secret}
            else:
                raise AssertionError((service, operation))
        elif service == 's3':
            assert arguments['ExpectedBucketOwner'] == ACCOUNT
            if operation == 'head_bucket':
                result = {}
            elif operation == 'get_bucket_location':
                result = {'LocationConstraint': REGION}
            elif operation == 'get_bucket_encryption':
                result = {'ServerSideEncryptionConfiguration': {'Rules': [{'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]}}
            elif operation == 'get_bucket_policy':
                error('NoSuchBucketPolicy', status=404)
            elif operation == 'put_object':
                if knobs.get('delivery_fail'):
                    error('AccessDenied', status=403)
                assert arguments['IfNoneMatch'] == '*'
                key = arguments['Key']
                if key in state['objects']:
                    error('PreconditionFailed', status=412)
                data = arguments['Body'].read()
                checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
                assert checksum == arguments['ChecksumSHA256']
                state['objects'][key] = {'data': base64.b64encode(data).decode(), 'ChecksumSHA256': checksum,
                    'ContentLength': len(data), 'VersionId': 'v1', 'ServerSideEncryption': 'AES256'}
                result = {'VersionId': 'v1'}
            elif operation == 'head_object':
                if arguments['Key'] not in state['objects']:
                    error('NotFound', status=404)
                result = {k: v for k, v in state['objects'][arguments['Key']].items() if k != 'data'}
            else:
                raise AssertionError((service, operation))
        else:
            raise AssertionError((service, operation))
        assert result is not None, (service, operation)
        persist()
        return result


def clients(root, state_path, aws_path):
    """A finite set of SDK operations; unexpected calls have no network fallback."""
    gate = RLock()
    secret = f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:app-dev-secret-abcdef'

    request = _bind_framework_callback(_callback_clients_request, aws_path, gate, root, secret, state_path)

    operations = {'sts': ['get_caller_identity'], 'cloudformation': ['validate_template', 'describe_stacks',
        'create_change_set', 'describe_change_set', 'execute_change_set', 'describe_stack_events',
        'list_stack_resources', 'delete_stack', 'get_template', 'list_exports'],
        'secretsmanager': ['describe_secret', 'list_secret_version_ids', 'get_secret_value', 'put_secret_value', 'update_secret_version_stage'], 's3': ['head_bucket', 'get_bucket_location', 'get_bucket_encryption',
        'get_bucket_policy', 'put_object', 'head_object']}
    client = _bind_framework_callback(_callback_clients_client, operations, request)
    return client


def _callback_invoke_write(fail_observed, fault, journal, original_write, root, state_path, /, path, text, *args, **kwargs):
    model_output = path.is_relative_to(root / 'model') and path.suffix == '.properties' and 'observed.row.' in text
    if (fail_observed or fault == 'model-io') and model_output:
        raise OSError('injected observed I/O failure')
    if fault == 'design-io' and path.is_relative_to(root / 'docs/designs'):
        raise OSError('injected design I/O failure')
    if fault == 'generation-io' and path.suffix == '.md' and not path.is_relative_to(root) and state_path.is_file():
        if json.loads(state_path.read_text()).get('pendingObserved', {}).get('stage') == 'MODEL_PUBLISHED':
            raise OSError('injected staged generation I/O failure')
    if path == state_path.with_suffix('.json.tmp'):
        saved = json.loads(text)
        if fault == 'plan-save' and saved.get('pendingObserved'):
            raise OSError('injected observed plan I/O failure')
        if fault == 'design-committed' and saved['states']['cfn-stack-app-dev-first'].get('observedSynced'):
            os._exit(78)
    result = original_write(path, text, *args, **kwargs)
    if fault == 'model-partial' and model_output:
        assert journal.is_file()
        os._exit(76)
    if fault == 'design-partial' and path.is_relative_to(root / 'docs/designs'):
        assert journal.is_file()
        os._exit(79)
    return result


def _callback_invoke_unlink(fault, journal, original_unlink, /, path, *args, **kwargs):
    model_commit = (fault == 'model-committed' and path == journal and path.is_file()
                    and all(p.startswith('model/') for p in json.loads(path.read_text())['originals']))
    result = original_unlink(path, *args, **kwargs)
    if model_commit:
        os._exit(77)
    return result


def _callback_invoke_replace(aws_path, original_replace, state_path, /, path, target):
    if Path(target) == state_path:
        candidate = json.loads(path.read_text())
        data = json.loads(aws_path.read_text())
        if candidate.get('inputRevision') == 1:
            for knob, code in (('crash_accept_before', 77), ('crash_accept_after', 78)):
                if data['knobs'].pop(knob, False):
                    aws_path.write_text(json.dumps(data))
                    if knob.endswith('after'):
                        original_replace(path, target)
                    os._exit(code)
    return original_replace(path, target)


def _callback_invoke_seal(original_seal, original_write, root, /, snapshot):
    original_seal(snapshot)
    path = root / f'docs/designs/dev/{ACCOUNT}/ec2.md'
    original_write(path, path.read_text() + '\nexternal during generation\n')


def invoke(root, state_path, aws_path, options=(), fail_observed=False, fault=None):
    original_write, original_replace = Path.write_text, Path.replace
    original_unlink = Path.unlink
    journal = Path(tempfile.gettempdir()) / 'blueprint-model-publication' / (hashlib.sha256(str(root).encode()).hexdigest() + '.json')
    write = _bind_framework_callback(_callback_invoke_write, fail_observed, fault, journal, original_write, root, state_path)
    unlink = _bind_framework_callback(_callback_invoke_unlink, fault, journal, original_unlink)
    replace = _bind_framework_callback(_callback_invoke_replace, aws_path, original_replace, state_path)
    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, 'replace', replace))
        stack.enter_context(patch('utils.aws.client.client', clients(root, state_path, aws_path)))
        stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('network forbidden')))
        stack.enter_context(patch('socket.socket.connect_ex', side_effect=AssertionError('network forbidden')))
        if fail_observed or fault:
            stack.enter_context(patch.object(Path, 'write_text', write))
            stack.enter_context(patch.object(Path, 'unlink', unlink))
        if fault == 'design-race':
            GenerationInputs = _imports_generation_inputs.GenerationInputs
            original_seal = GenerationInputs.seal
            seal = _bind_framework_callback(_callback_invoke_seal, original_seal, original_write, root)
            stack.enter_context(patch.object(GenerationInputs, 'seal', seal))
        return main(['--environment', 'dev', '--aws-account-id', ACCOUNT, '--stack', 'cfn-stack-app-dev-first', '--stack', 'cfn-stack-app-dev-second',
            '--state', str(state_path), '--timing-log', str(state_path.with_suffix('.timing.jsonl')), *options])


def child_environment():
    return {**{k: v for k, v in os.environ.items() if k not in {'AWS_PROFILE', 'AWS_DEFAULT_PROFILE', 'BLUEPRINT_OBSERVED_FAULT'}},
        'PYTHONPATH': os.pathsep.join([str(SCRIPTS), str(Path(__file__).resolve().parents[2] / 'tests')]),
        'BLUEPRINT_TASK_FILE': 'tasks/deploy.md', 'AWS_EC2_METADATA_DISABLED': 'true',
        'AWS_CONFIG_FILE': os.devnull, 'AWS_SHARED_CREDENTIALS_FILE': os.devnull,
        'AWS_ACCESS_KEY_ID': 'synthetic', 'AWS_SECRET_ACCESS_KEY': 'synthetic'}


if __name__ == '__main__':
    root, state_path, aws_path = map(lambda arg: Path(arg).resolve(), sys.argv[1:4])
    os.chdir(root)
    raise SystemExit(invoke(root, state_path, aws_path, sys.argv[4:], fault=os.environ.get('BLUEPRINT_OBSERVED_FAULT')))
