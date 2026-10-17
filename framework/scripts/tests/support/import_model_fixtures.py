"""Offline import safety and real generator regressions; no AWS network calls."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from contextlib import redirect_stdout

import io

import hashlib

import builtins

import json

import os

import shutil

import socket

import subprocess

import tempfile

from unittest.mock import patch

from script_loader import module

from support.validator import load

m = module('import-model.py', 'import_model_cli')

from model_files import load_model

from model_parameter_inputs import parameter_text

from model_templates import json_text, load_expansion, resolve

from support.model_sources import write_model

from task_contract import start

from validation_cache import input_scope

import import_guard

import sync_runtime

ACCOUNT = '123456789012'

COUNT = 0

def check(value, message):
    global COUNT
    assert value, message
    COUNT += 1

def rejected(function, message):
    try:
        function()
    except ValueError as error:
        check(message in str(error), str(error))
    else:
        raise AssertionError('expected rejection: ' + message)

def values():
    result = {'desired.service.cloudwatch-logs.serviceId': 'cloudwatch-logs',
              'desired.service.cloudwatch-logs.ownedCatalogResourceTypes': 'Logs.LogGroup',
              'display.service.title': '# CloudWatch Logs 詳細設計'}
    for number, mode in [('001', 'IMPORT'), ('002', 'CREATE')]:
        result.update({f'desired.resource.{number}.resourceType': 'Logs.LogGroup',
                       f'desired.resource.{number}.logicalId': 'Group' + number,
                       f'desired.resource.{number}.anchor': 'cloudwatch-logs-fixture-' + number,
                       f'desired.resource.{number}.resourceMode': mode,
                       f'display.resource.{number}.comment': 'ログを保存する'})
        for index, (prop, value) in enumerate([('LogGroupName', 'fixture-' + number), ('RetentionInDays', '30'),
                                               ('DeletionProtectionEnabled', 'false'), ('LogGroupClass', 'STANDARD')], 1):
            base = f'desired.row.{number}-{index:03d}.'
            result.update({base + 'property': 'Logs.LogGroup.' + prop, base + 'value': '`' + value + '`', base + 'comment': 'ログの設定'})
    return result

def fixture(root, parameter=True):
    small_framework(root, ['cloudwatch-logs'], ['Logs.LogGroup'])
    (root / 'project.json').write_text(json_text({'projectName': 'fixture', 'targets': [{'environment': 'dev', 'awsAccountId': ACCOUNT,
        'awsProfile': 'confirmed', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n', encoding='utf-8')
    path = root / 'model/dev' / ACCOUNT / 'cloudwatch-logs.properties'
    write_model(path, values())
    template = root / 'model/templates' / ACCOUNT / 'cloudwatch-logs.properties.tpl'
    if parameter:
        text = template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n',
            '# definition: Fixture_dev\n# parameter: Days {"type":"integer","description":"保持日数","required":true}\n')
        text = text.replace('desired.row.row_001-002.value=`30`', 'desired.row.row_001-002.value=<<Days>>')
        template.write_text(text, encoding='utf-8')
        directory = root / 'model/parameters/dev' / ACCOUNT / 'cloudwatch-logs'
        (directory / 'parameters.yaml').write_text('instances:\n  fixture:\n    parameters:\n      Days: 30\n', encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], cwd=root, check=True)
    return path

def generate(root, scope, write):
    command = [sys.executable, '-B', str(m.ROOT / 'framework/scripts/sync-model.py'), '--repository-root', str(root)]
    if write:
        command.append('--write')
    for identity in sorted(scope):
        command += ['--scope', '/'.join(identity)]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise ValueError(result.stderr)

def contract(root, files, service="cloudwatch-logs", target=ACCOUNT):
    lines = ['# Import fixture', '## Task contract', '- Task type: `design`', '- Workflow: `import`', '- Task status: `running`',
             '## Goal', 'Import selected mock settings', '## Required changes', '- [R1] Refresh IMPORT and generate views',
             '## Validation scope', f'- `dev/{target}/{service}`', '## Allowed paths']
    paths = ['tasks/import-fixture.md', *sorted(files)]
    lines += ['- `' + p + '`' for p in paths]
    lines += ['## Modified files', *['- `' + p + '`' for p in paths], '## Acceptance checks',
              f'- [R1] `exists:docs/designs/dev/{target}/{service}.md`']
    source = root.parent / (root.name + '-contract.md')
    source.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    start(root, 'tasks/import-fixture.md', source.read_text(encoding='utf-8'))

def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts and not p.is_relative_to(root / '.blueprint/import')}

class AwsCli:
    def __init__(self, account=ACCOUNT, fail=None, profile='confirmed'):
        self.calls, self.account, self.fail = [], account, fail
        self.profile = profile
        self.responses = {}
        self.logs = [{'logGroupName': 'fixture-001', 'retentionInDays': 90, 'deletionProtectionEnabled': True, 'logGroupClass': 'STANDARD'},
                     {'logGroupName': 'aws-new', 'retentionInDays': 7, 'deletionProtectionEnabled': False, 'logGroupClass': 'STANDARD'},
                     {'logGroupName': 'fixture-002', 'retentionInDays': 99, 'logGroupClass': 'STANDARD'}]

    def __call__(self, command, **kwargs):
        check(('--profile' not in command if self.profile is None else
               '--profile' in command and command[command.index('--profile')+1] == self.profile),
              'configured profile only; omit --profile when unset on every CLI call')
        check(command[command.index('--region')+1] == 'ap-northeast-1', 'project.json Region on every CLI call')
        check(command[command.index('--output')+1] == 'json' and '--no-cli-pager' in command and kwargs['env']['AWS_CLI_AUTO_PROMPT']=='off', 'JSON output and no interactive prompt/pager')
        check(kwargs['timeout'] == 60 and kwargs['encoding'] == 'utf-8', 'bounded UTF-8 CLI transport')
        service, operation = command[1:3]
        inputs = json.loads(command[command.index('--cli-input-json') + 1])
        self.calls.append((service, operation, inputs))
        if self.fail:
            return subprocess.CompletedProcess(command, 1, '', self.fail)
        responses = {
            ('sts', 'get-caller-identity'): {'Account': self.account},
            ('logs', 'describe-log-groups'): {'logGroups': self.logs},
            ('configservice', 'describe-configuration-recorders'): {'ConfigurationRecorders': [{'name': 'actual-recorder', 'roleARN': 'arn:aws:iam::' + ACCOUNT + ':role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig', 'recordingGroup': {'allSupported': False, 'includeGlobalResourceTypes': True, 'resourceTypes': ['AWS::EC2::VPC']}}]},
            ('configservice', 'describe-delivery-channels'): {'DeliveryChannels': []},
            ('ec2', 'describe-vpcs'): {'Vpcs': [dict(VpcId='vpc-' + str(n) * 17, CidrBlock='10.' + str(n) + '.0.0/16', Tags=[{'Key': 'Name', 'Value': 'actual-vpc-' + str(n)}]) for n in (1, 2)]},
            ('ec2', 'describe-subnets'): {'Subnets': []},
            ('ec2', 'describe-route-tables'): {'RouteTables': []},
            ('ec2', 'describe-flow-logs'): {'FlowLogs': []},
            ('ec2', 'describe-vpc-attribute'): {('EnableDnsSupport' if inputs.get('Attribute') == 'enableDnsSupport' else 'EnableDnsHostnames'): {'Value': True}},
            ('quicksight', 'list-data-sources'): {'DataSources': [{'DataSourceId': 'actual-source'}, {'DataSourceId': 'create-source'}]},
            ('quicksight', 'list-vpc-connections'): {'VPCConnectionSummaries': []},
            ('quicksight', 'describe-data-source'): {'DataSource': {'DataSourceId': inputs.get('DataSourceId'), 'Name': inputs.get('DataSourceId'), 'Type': 'ATHENA', 'DataSourceParameters': {'AthenaParameters': {'WorkGroup': 'aws-group'}}}},
            ('quicksight', 'describe-data-source-permissions'): {'Permissions': []},
        }
        responses.update(self.responses)
        if (service, operation) not in responses:
            raise AssertionError('unmocked AWS CLI call: ' + service + '.' + operation)
        return subprocess.CompletedProcess(command, 0, json.dumps(responses[(service, operation)]), '')

def register_plan(root, plan, service='cloudwatch-logs', target=ACCOUNT):
    files = set(plan['files'])
    files |= {f'docs/designs/{identity}.md' for identity in plan['scope']}
    contract(root, files, service, target)
    text = (root / 'tasks/import-fixture.md').read_text(encoding='utf-8')
    text = text.replace(f'- `dev/{target}/{service}`', '\n'.join('- `' + identity + '`' for identity in plan['scope']))
    (root / 'tasks/import-fixture.md').write_text(text, encoding='utf-8')

def values_for_service(service, kind, fields, create_fields=None):
    data = {'desired.service.' + service + '.serviceId': service,
            'desired.service.' + service + '.ownedCatalogResourceTypes': kind,
            'display.service.title': '# ' + service + ' 詳細設計'}
    for number, properties, mode in [('001', fields, 'IMPORT'), ('002', create_fields or {}, 'CREATE')]:
        if not properties:
            continue
        data.update({f'desired.resource.{number}.resourceType': kind, f'desired.resource.{number}.logicalId': 'Fixture' + number,
                     f'desired.resource.{number}.resourceMode': mode, f'desired.resource.{number}.anchor': m.resource_anchor(service, str(properties.get('Name', properties.get('LogGroupName', kind))), kind),
                     f'display.resource.{number}.comment': '既存の設定'})
        for index, (prop, value) in enumerate(properties.items(), 1):
            key = f'desired.row.{number}-{index:03d}.'
            data.update({key + 'property': kind + '.' + prop, key + 'value': m.model_literal(value), key + 'comment': '既存の設定'})
    return data

def setup_service(root, service, kind, fields, create_fields=None, alias=None):
    fixture(root)
    small_framework(root, [service], [kind])
    if alias:
        project = json.loads((root / 'project.json').read_text(encoding='utf-8'))
        project['targets'][0]['alias'] = alias
        project['targets'].append({**project['targets'][0], 'alias': 'non-cde', 'awsAccountId': '210987654321'})
        (root / 'project.json').write_text(json_text(project) + '\n', encoding='utf-8')
    target = alias or ACCOUNT
    path = root / 'model/dev' / target / (service + '.properties')
    write_model(path, values_for_service(service, kind, fields, create_fields))
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'service'], cwd=root, check=True)
    return path

def small_framework(root, services, kinds):
    (root / ".gitignore").write_text("/.blueprint/import/\n", encoding="utf-8")
    from cloudformation_schema import REGION
    kinds = set(kinds) | {kind for service in services for kind in m.yaml_read((m.ROOT / 'framework/mappings/aws' / (service + '.yaml')).read_text(encoding='utf-8'))['resourceTypes']}
    schema = Path('framework/materials/cloudformation-schema') / REGION
    index = json.loads((m.ROOT / schema / 'index.json').read_text(encoding='utf-8'))['resourceTypes']
    paths = {schema / 'index.json', Path('framework/rules/aws-resource-naming.md')}
    for kind in kinds:
        paths |= {Path('framework/materials/aws' if (m.ROOT / 'framework/materials/aws' / (kind.replace('.', '_', 1) + '.properties')).is_file() else 'framework/materials/api') / (kind.replace('.', '_', 1) + '.properties'),
                  Path('framework/materials/api') / (kind.replace('.', '_', 1) + '.json') if 'AWS::' + kind.replace('.', '::', 1) not in index else schema / index['AWS::' + kind.replace('.', '::', 1)],
                  Path('framework/rules/aws-resource-naming') / (kind.split('.')[0] + '.md')}
    paths |= {Path('framework/mappings/aws') / (service + '.yaml') for service in services}
    for relative in paths:
        destination = root / relative; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(m.ROOT / relative, destination)
    (root / 'project.json').write_text(json_text({'projectName': 'fixture', 'targets': [{'environment': 'dev',
        'awsAccountId': ACCOUNT, 'awsProfile': 'confirmed', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n', encoding='utf-8')

import pytest

from support.pytest_cli import run

@pytest.fixture(autouse=True)
def reset_count():
    global COUNT
    COUNT = 0
    yield
    COUNT = 0


__all__ = ['ACCOUNT', 'AwsCli', 'COUNT', 'Path', 'builtins', 'check', 'contract', 'fixture', 'generate', 'hashlib', 'import_guard', 'input_scope', 'io', 'json', 'json_text', 'load', 'load_expansion', 'load_model', 'm', 'module', 'os', 'parameter_text', 'patch', 'pytest', 'redirect_stdout', 'rejected', 'register_plan', 'reset_count', 'resolve', 'run', 'setup_service', 'shutil', 'small_framework', 'snapshot', 'socket', 'start', 'subprocess', 'sync_runtime', 'sys', 'tempfile', 'values', 'values_for_service', 'write_model']
