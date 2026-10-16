#!/usr/bin/env python3
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
    return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}


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


def reserve(root, plan, service='cloudwatch-logs', target=ACCOUNT):
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


def check_cli_preflight():
    from types import SimpleNamespace
    from aws_mapping_compare import comparison
    context = SimpleNamespace(root=m.ROOT, comparison=lambda service: comparison(m.ROOT, service))
    resource = SimpleNamespace(kind='Config.ConfigurationRecorder', ctx=context,
        model=SimpleNamespace(ctx=context, service='config'), module=m.comparator().service_module('config'),
        current=lambda prop: {'Id': 'existing-recorder', 'Name': 'renamed-recorder'}.get(prop))
    check(m.old_identity(resource) == 'existing-recorder', 'physical identifier precedes a changed desired Name')
    for args in [[], ['--environment', 'dev'], ['--service', 'config']]:
        result = subprocess.run([sys.executable, '-B', str(m.ROOT / 'framework/scripts/import-model.py'), *args], capture_output=True)
        check(result.returncode == 2, 'environment and service mandatory')
    for result, code in [({'status': 'complete', 'markdown': 'generated'}, 0),
                         ({'status': 'incomplete', 'markdown': 'generated'}, 2),
                         ({'status': 'display-failed', 'markdown': 'failed'}, 3)]:
        with patch.object(m, 'refresh', return_value=result), patch.object(m, 'print_report'), \
                patch.object(sys, 'argv', ['import-model', '--environment', 'dev', '--service', 'config']):
            check(m.main() == code, 'CLI distinguishes acquisition/reflection and display states')



def check_logs_roundtrip():
    from import_guard import require_import_changes
    with tempfile.TemporaryDirectory() as tmp, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        root = Path(tmp) / 'logs'; root.mkdir()
        path = fixture(root)
        template = m.service_source(path)[1]
        text = template.read_text(encoding='utf-8').replace('# model-template: 1\n', '# model-template: 1\n# input: CreateDays {"type":"integer","description":"CREATE保持日数","required":true,"source":"service"}\n').replace('desired.row.row_002-002.value=`30`', 'desired.row.row_002-002.value=<<CreateDays>>')
        template.write_text(text, encoding='utf-8')
        parameters = m.service_source(path)[2] / 'parameters.yaml'
        parameters.write_text('parameters:\n  CreateDays: 30\n' + parameters.read_text(encoding='utf-8'), encoding='utf-8')
        subprocess.run(['git','add','.'],cwd=root,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','create input'],cwd=root,check=True)
        before = snapshot(root)
        cli = AwsCli()
        with patch.object(m.comparator(), 'compare_resource', side_effect=AssertionError('Model comparison forbidden')), patch.object(sync_runtime, 'generate_files', side_effect=AssertionError('dry-run generation forbidden')):
            plan = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=cli)
        check(snapshot(root) == before, 'dry-run changes no source/view/Task/evidence files')
        check(cli.calls[0] == ('sts', 'get-caller-identity', {}), 'STS runs before resource calls')
        check([inputs for service, _, inputs in cli.calls if service == 'logs'] == [{}], 'AWS listing does not filter by Model names')
        check(plan['resources'] == {'import': 2, 'create': 1}, 'all AWS resources imported; CREATE skipped')
        reserve(root, plan)
        original = load_model(path).values
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}), patch.object(m.comparator(), 'compare_resource', side_effect=AssertionError('no comparison')):
            with patch.object(subprocess, 'run', wraps=subprocess.run) as commands, patch.object(sync_runtime, 'generate_files', wraps=sync_runtime.generate_files) as generations:
                result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=AwsCli())
            check(generations.call_count == 1, 'changed import generates the final candidate exactly once')
            check(not any('sync-model.py' in str(call.args[0]) for call in commands.call_args_list), 'normal import starts no sync subprocess')
            check(sum(call.args[0][:2] == ['git', 'archive'] for call in commands.call_args_list) == 0,
                  'normal import never expands a Git baseline')
            check(result['status'] == 'complete' and result['markdown'] == 'generated', 'normal import generates and verifies views')
            current = load_model(path).values
            check(import_guard.resource_config(original, '002') == import_guard.resource_config(current, '002'), 'CREATE configuration preserved exactly')
            expansion = load_expansion(path)
            check('CreateDays' in expansion.provenance['desired.row.002-002.value']['inputs'], 'CREATE parameter source retained')
            check(m.comparator().literal(current['desired.row.001-002.value']) == '90', 'AWS values overwrite old settings')
            check(len(m.entries(current, 'desired.resource.')) == 3, 'new AWS resource added')
            require_import_changes(root)
            after = snapshot(root)
            second = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=AwsCli())
            check(snapshot(root) == after and second['files'] == [], 'same AWS inventory does not cause unnecessary rewrites')
            parameters = m.service_source(path)[2] / 'parameters.yaml'
            with import_guard.baseline_scope():
                require_import_changes(root)
                proof_file = import_guard.proof_path(root)
                proof_text = proof_file.read_text(encoding='utf-8')
                proof = json.loads(proof_text)
                proof['base'] = '0' * 40
                proof_file.write_text(json_text(proof), encoding='utf-8')
                rejected(lambda: require_import_changes(root), 'verified /import evidence')
                proof_file.write_text(proof_text, encoding='utf-8')
                for invalid in ({'complete': False}, {'model': 'pending'}, {'acquisition': ''}):
                    proof_file.write_text(json_text({**json.loads(proof_text), **invalid}), encoding='utf-8')
                    try:
                        task_contract_complete = __import__('task_contract').complete
                        task_contract_complete(root, 'tasks/import-fixture.md')
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('incomplete evidence cannot complete import')
                proof_file.write_text(proof_text, encoding='utf-8')
                original_parameters = parameters.read_text(encoding='utf-8')
                parameters.write_text(original_parameters.replace('CreateDays: 30', 'CreateDays: 31'), encoding='utf-8')
                rejected(lambda: require_import_changes(root), 'differs from acquired change plan')
                parameters.write_text(original_parameters.replace('90', '91'), encoding='utf-8')
                rejected(lambda: require_import_changes(root), 'differs from acquired change plan')
        # Account/auth failure stops before any resource read and does not fall back.
        for cli, code in [(AwsCli(account='999999999999'), 'AccountMismatch'), (AwsCli(fail='An error occurred (AccessDenied) when calling GetCallerIdentity: SECRET-CREDENTIAL'), 'AccessDenied')]:
            try:
                m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=cli)
            except m.comparator().AcquisitionError as error:
                check(error.code == code and 'SECRET' not in str(error), 'safe failure code')
                check(len(cli.calls) == 1, 'failed STS has no fallback/resource calls')
            else:
                raise AssertionError('must stop on failed identity')
        project = json.loads((root / 'project.json').read_text(encoding='utf-8'))
        project['targets'][0]['awsExecutionAccountId'] = '999999999999'
        (root / 'project.json').write_text(json_text(project) + '\n', encoding='utf-8')
        check(m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=AwsCli(account='999999999999'))['status'] == 'dry-run', 'execution Account override')
        project['targets'].append({**project['targets'][0], 'alias': 'other'})
        (root / 'project.json').write_text(json_text(project) + '\n', encoding='utf-8')
        write_model(root / 'model/dev/other/cloudwatch-logs.properties', values())
        rejected(lambda: m.target_for(root, 'dev', 'cloudwatch-logs'), 'target is required')
        rejected(lambda: m.target_for(root, 'missing', 'cloudwatch-logs'), 'environment is not registered')
        project['targets'] = project['targets'][:1]
        for invalid in [None, False, 1, '', ' UNSET', 'UNSET', ' confirmed', 'confirmed ', 'confirmed\n', 'confirmed\r', 'confirmed\0']:
            target = dict(project['targets'][0]); target['awsProfile'] = invalid
            rejected(lambda: m.import_context(root, target, AwsCli()), 'project.json awsProfile')
        rejected(lambda: m.import_context(root, {**project['targets'][0], 'awsRegion': 'UNSET'}, AwsCli()), 'RegionMismatch')
        ctx = m.import_context(root, project['targets'][0], AwsCli(), 'vpc')
        rejected(lambda: ctx.call('ec2', 'describe_vpcs'), 'not been verified')
        rejected(lambda: ctx.call('ec2', 'create_vpc', CidrBlock='10.0.0.0/16'), 'read-only allowlist')


def check_config_snapshot():
    from import_guard import require_import_changes
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'config'; root.mkdir()
        path = setup_service(root, 'config', 'Config.ConfigurationRecorder', {'Name': 'wrong-model-name', 'RecordingGroup.AllSupported': True}, alias='cde')
        plan = m.refresh(root, 'dev', 'config', 'cde', True, AwsCli())
        reserve(root, plan, 'config', 'cde')
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            result = m.refresh(root, 'dev', 'config', 'cde', cli_runner=AwsCli())
            check(result['status'] == 'complete', 'Config snapshot succeeds independent of wrong old name')
            current = load_model(path).values
            names = [row['value'] for _, row in m.entries(current, 'desired.row.') if row['property'].endswith('.Name')]
            check(names == ['`actual-recorder`'], 'AWS identity replaces stale resource; old resource removed')
            check(any(m.comparator().literal(row['value']) == 'false' for _, row in m.entries(current, 'desired.row.')), 'typed Boolean preserved')
            check(any('AWS::EC2::VPC' in row['value'] for _, row in m.entries(current, 'desired.row.')), 'array preserved')


def check_vpc_snapshot():
    from import_guard import require_import_changes
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'vpc'; root.mkdir()
        path = setup_service(root, 'vpc', 'EC2.VPC', {'CidrBlock': 'wrong-old-value', 'Name': 'does-not-exist', 'EnableDnsSupport': False, 'EnableDnsHostnames': False})
        cli = AwsCli()
        plan = m.refresh(root, 'dev', 'vpc', dry_run=True, cli_runner=cli)
        check(plan['resources']['import'] == 2, 'both AWS VPCs imported regardless of Model')
        check(all(inputs == {} for service, operation, inputs in cli.calls if operation in {'describe-vpcs', 'describe-subnets', 'describe-route-tables', 'describe-flow-logs'}), 'VPC service enumeration uses no Model filter')
        reserve(root, plan, 'vpc')
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            result = m.refresh(root, 'dev', 'vpc', cli_runner=AwsCli())
            check(result['status'] == 'complete', 'VPC snapshot generates valid Markdown')
            current = load_model(path).values
            check(len(m.entries(current, 'desired.resource.')) == 2 and 'desired.resource.001.anchor' not in current, 'old VPC removed and two actual VPCs stored')
            check(any(row['value'] == '`10.1.0.0/16`' for _, row in m.entries(current, 'desired.row.')), 'actual CIDR stored')
            check(any(k.startswith('observed.row.') and 'vpc-111' in v for k, v in current.items()), 'non-ARN identifiers observed')


def check_quicksight_snapshot():
    from import_guard import require_import_changes
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'quicksight'; root.mkdir()
        path = setup_service(root, 'quicksight', 'QuickSight.DataSource', {'DataSourceId': 'old-source', 'Name': 'old-source', 'Type': 'ATHENA', 'AwsAccountId': ACCOUNT}, {'DataSourceId': 'create-source', 'Name': 'create-source', 'Type': 'ATHENA', 'AwsAccountId': ACCOUNT})
        old = load_model(path).values
        plan = m.refresh(root, 'dev', 'quicksight', dry_run=True, cli_runner=AwsCli())
        reserve(root, plan, 'quicksight')
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            result = m.refresh(root, 'dev', 'quicksight', cli_runner=AwsCli())
            check(result['status'] == 'incomplete' and len(result['unreflected']) == 3 and
                  all(row['reason'] == 'sensitive Property' for row in result['unreflected']),
                  'Mapping-included QuickSight credentials remain explicitly sensitive and incomplete')
            current = load_model(path).values
            check(import_guard.resource_config(old, '002') == import_guard.resource_config(current, '002'), 'QuickSight CREATE protected')
            check(any('aws-group' in row['value'] for _, row in m.entries(current, 'desired.row.')), 'QuickSight actual settings overwrite')
        report = dict(result); stream = io.StringIO()
        with redirect_stdout(stream): m.print_report(report)
        check('| Resource | Property | AWS |' in stream.getvalue() and '| Model |' not in stream.getvalue(), 'snapshot report has no Model comparison')





@input_scope
def check_registry_consumers():
    # Reuse the offline CLI fixtures for exact Registry/Inventory and source-plan coverage.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'registry'; root.mkdir()
        fixture(root)
        target = m.target_for(root, 'dev', 'cloudwatch-logs')
        rejected(lambda: m.inventory(m.import_context(root, target, AwsCli(), 'cloudformation-stacks'),
                                     'cloudformation-stacks'), 'IMPORT inventory is unimplemented for: CloudFormation.Stack')
        supported = {'cloudwatch-logs', 'config', 'data-firehose', 'quicksight',
                     'security-hub', 'transit-gateway', 'vpc'}
        for service in m.comparator().SERVICES:
            if service != 'cloudformation-stacks':
                mapping_file = root / 'framework/mappings/aws' / (service + '.yaml')
                shutil.copyfile(m.ROOT / mapping_file.relative_to(root), mapping_file)
            if service == 'cloudformation-stacks':
                continue
            mapping, _ = m.comparison(root, service)
            adapter = m.comparator().service_module(service)
            expected_allowed = {('sts', 'get_caller_identity')} | adapter.APIS
            ctx = m.import_context(root, target, AwsCli(), service)
            check(ctx.allowed == expected_allowed, service + ': API allowlist remains Python APIS')
            if service not in supported:
                rejected(lambda: m.inventory(ctx, service), 'IMPORT inventory is unimplemented for:')
                check(ctx.allowed == expected_allowed and not ctx.trace, service + ': unsupported inventory grants/calls no API')
                continue
            def acquire():
                cli = AwsCli()
                cli.responses.update({
                    ('firehose', 'list-delivery-streams'): {'DeliveryStreamNames': ['fixture']},
                    ('firehose', 'describe-delivery-stream'): {'DeliveryStreamDescription': {'DeliveryStreamName': 'fixture'}},
                    ('securityhub', 'describe-hub'): {'HubArn': 'arn:aws:securityhub:ap-northeast-1:' + ACCOUNT + ':hub/default'},
                    ('ec2', 'describe-transit-gateway-vpc-attachments'): {'TransitGatewayVpcAttachments': [{'TransitGatewayAttachmentId': 'tgw-attach-fixture'}]},
                })
                ctx = m.import_context(root, target, cli, service)
                ctx.verify()
                records = m.inventory(ctx, service)
                inventory_apis = {tuple(m.INVENTORY[kind][:2]) for kind in mapping.adapter_resource_types if kind in m.INVENTORY}
                check(ctx.allowed == expected_allowed | inventory_apis, service + ': only existing Inventory APIs added')
                return records, cli.calls, ctx.allowed
            records, _, _ = acquire()
            check(all(record['kind'] in mapping.adapter_resource_types for record in records), service + ': Inventory stays within Adapter types')
        # Capture both the dry-run report and exact variable/reference update plan.
        captured = []
        original = m.snapshot_sources
        def capture(*args):
            result = original(*args)
            captured.append({file.relative_to(args[0].parents[3]): content for file, content in result.items()})
            return result
        m.comparison(m.ROOT, 'cloudwatch-logs')
        with patch.object(m, 'snapshot_sources', side_effect=capture):
            baseline = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=AwsCli())
            actual = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=AwsCli())
        check(actual == baseline and captured[0] == captured[1], 'Registry-only IMPORT plan preserves every Model variable/reference and CREATE value')


def check_main_vpc_slot():
    from import_scope import restrict
    for count, observed in [(1, 'PENDING_DEPLOY'), (2, 'PENDING_DEPLOY'), (2, 'vpc-' + '2' * 17)]:
        with tempfile.TemporaryDirectory() as temporary, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            root = Path(temporary).resolve()
            fixture(root)
            small_framework(root, ['vpc', 'iam'], ['EC2.VPC', 'IAM.Role'])
            path = root / 'model/dev' / ACCOUNT / 'vpc.properties'
            vpc = values_for_service('vpc', 'EC2.VPC', {'Name': 'vpc-fixture-dev', 'VpcId': 'unused', 'CidrBlock': '10.0.0.0/16'})
            vpc['desired.service.vpc.ownedCatalogResourceTypes'] += ',EC2.FlowLog'
            vpc['desired.row.001-002.value'] = '[Fixture001](#vpc-vpc-fixture-dev)'
            vpc['observed.row.001-002.value'] = '`' + observed + '`'
            write_model(path, vpc)
            template, directory = m.service_source(path)[1:]
            main_text = template.read_text(encoding='utf-8').replace('Fixture_dev', 'MainVpc')
            main_binding = json.loads((directory / 'bindings.json').read_text(encoding='utf-8'))['instances']['fixture']
            main_binding['definition'] = 'MainVpc'
            fields = {'Name': 'flowlog-fixture-dev', 'Id': 'PENDING_DEPLOY',
                      'DeliverLogsPermissionArn': '[SavedRole](iam.md#iam-savedrole)',
                      'LogDestinationType': 'cloud-watch-logs', 'LogGroupName': '[SavedLogs](cloudwatch-logs.md#cloudwatch-logs-savedlogs)',
                      'MaxAggregationInterval': 60, 'ResourceId': '[Fixture001](#vpc-vpc-fixture-dev)',
                      'ResourceType': 'VPC', 'TrafficType': 'ALL'}
            flow = values_for_service('vpc', 'EC2.FlowLog', fields)
            flow = {key.replace('.001.', '.014.').replace('.001-', '.014-'): value
                    for key, value in flow.items() if not key.startswith(('desired.service.', 'display.service.'))}
            flow.pop('desired.resource.014.resourceMode')
            flow['desired.resource.014.logicalId'] = 'Fixture014'
            flow['desired.row.014-002.value'] = '[Fixture014](#vpc-flowlog-fixture-dev)'
            flow['observed.row.014-002.value'] = '`PENDING_DEPLOY`'
            flow['observed.row.014-007.value'] = 'PENDING_DEPLOY'
            write_model(path, flow)
            flow_text = template.read_text(encoding='utf-8').replace('# model-template: 1\n', '').replace('Fixture_dev', 'FlowLog')
            flow_text = flow_text.replace('# definition: FlowLog\n', '# definition: FlowLog\n' +
                '# reference: Resource {"instance":"main-vpc","resourceType":"EC2.VPC"}\n' +
                '# reference: Role {"service":"iam","resource":"001","resourceType":"IAM.Role"}\n' +
                '# reference: Logs {"service":"cloudwatch-logs","resource":"001","resourceType":"Logs.LogGroup"}\n')
            for value, variable in [(fields['ResourceId'], 'Resource'), (fields['DeliverLogsPermissionArn'], 'Role'), (fields['LogGroupName'], 'Logs')]:
                flow_text = flow_text.replace('`' + value + '`', '<<' + variable + '>>')
            flow_binding = json.loads((directory / 'bindings.json').read_text(encoding='utf-8'))['instances']['fixture']
            flow_binding.update(definition='FlowLog', labels={'Resource': 'Fixture001'})
            subnet, subnet_text = {}, ''
            bindings = {'main-vpc': main_binding, 'flow-log': flow_binding}
            if observed != 'PENDING_DEPLOY':
                subnet = values_for_service('vpc', 'EC2.Subnet', {'Name': 'sbnt-fixture-dev', 'SubnetId': 'unused',
                    'VpcId': fields['ResourceId'], 'CidrBlock': '10.2.1.0/24'})
                subnet = {key.replace('.001.', '.002.').replace('.001-', '.002-'): value
                          for key, value in subnet.items() if not key.startswith(('desired.service.', 'display.service.'))}
                subnet['desired.resource.002.logicalId'] = 'Fixture002'
                subnet['desired.row.002-002.value'] = '[Fixture002](#vpc-sbnt-fixture-dev)'
                subnet['observed.row.002-002.value'] = '`subnet-' + '3' * 17 + '`'
                subnet['observed.row.002-003.value'] = observed
                write_model(path, subnet)
                subnet_text = template.read_text(encoding='utf-8').replace('# model-template: 1\n', '').replace('Fixture_dev', 'Subnet')
                subnet_text = subnet_text.replace('# definition: Subnet\n', '# definition: Subnet\n' +
                    '# reference: Vpc {"instance":"main-vpc","resourceType":"EC2.VPC"}\n').replace('`' + fields['ResourceId'] + '`', '<<Vpc>>')
                bindings['subnet'] = json.loads((directory / 'bindings.json').read_text(encoding='utf-8'))['instances']['fixture']
                bindings['subnet'].update(definition='Subnet', labels={'Vpc': 'Fixture001'})
            template.write_text(main_text + flow_text + subnet_text, encoding='utf-8')
            (directory / 'bindings.json').write_text(json_text({'instances': bindings}), encoding='utf-8')
            observations = {key: value for source in (vpc, flow, subnet) for key, value in source.items() if key.startswith('observed.')}
            (directory / 'observed.json').write_text(json_text({'version': 1, 'values': observations}), encoding='utf-8')
            for service, kind, properties in [('iam', 'IAM.Role', {'RoleName': 'SavedRole'}),
                                              ('cloudwatch-logs', 'Logs.LogGroup', {'LogGroupName': 'SavedLogs'})]:
                write_model(root / 'model/dev' / ACCOUNT / (service + '.properties'), values_for_service(service, kind, properties))
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'main-vpc slot'], cwd=root, check=True)
            previous = load_expansion(path)
            baseline = import_guard.resource_config(previous.values, '014', path)
            before = snapshot(root)
            vpcs = [{'VpcId': 'vpc-' + str(n) * 17, 'CidrBlock': '10.' + str(n) + '.0.0/16',
                     'Tags': [{'Key': 'Name', 'Value': 'actual-vpc-' + str(n)}]} for n in range(1, count + 1)]
            def cli(order):
                result = AwsCli()
                result.responses[('ec2', 'describe-vpcs')] = {'Vpcs': order}
                if subnet:
                    result.responses[('ec2', 'describe-subnets')] = {'Subnets': [{'SubnetId': 'subnet-' + '3' * 17,
                        'VpcId': observed, 'CidrBlock': '10.2.1.0/24', 'AvailabilityZone': 'ap-northeast-1a',
                        'MapPublicIpOnLaunch': False, 'Tags': [{'Key': 'Name', 'Value': 'actual-subnet'}]}]}
                return result
            plan = m.refresh(root, 'dev', 'vpc', dry_run=True, cli_runner=cli(list(reversed(vpcs))))
            check(snapshot(root) == before, 'main-vpc preview saves no files or logs')
            reserve(root, plan, 'vpc')
            with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
                result = m.refresh(root, 'dev', 'vpc', cli_runner=cli(list(reversed(vpcs))))
                check(result['status'] == 'complete' and result['markdown'] == 'generated', 'main-vpc candidate publishes and matches generated views')
                current = load_expansion(path)
                binding = json.loads((directory / 'bindings.json').read_text(encoding='utf-8'))['instances']
                check(binding['main-vpc']['resources'] == main_binding['resources'] and binding['main-vpc']['rows']['row_001-002'] == '001-002',
                      'main-vpc instance, resource ID and existing Row ID are retained')
                check(current.values['desired.resource.001.logicalId'] == previous.values['desired.resource.001.logicalId'] and
                      current.values['desired.resource.001.anchor'] == previous.values['desired.resource.001.anchor'], 'main-vpc logicalId and anchor are retained')
                check(m.comparator().literal(current.values['observed.row.001-002.value']) == vpcs[0]['VpcId'] and
                      current.values['desired.row.001-003.value'] == '`10.1.0.0/16`', 'lowest VPC ID overwrites main-vpc regardless of old physical ID or API order')
                check(len(m.entries(current.values, 'desired.resource.')) == count + 1 + bool(subnet) and len(binding) == count + 1 + bool(subnet),
                      'subsequent VPCs become separate instances alongside unchanged Flow Log')
                if subnet:
                    added = next(spec for rid, spec in m.entries(current.values, 'desired.resource.') if rid != '001' and spec['resourceType'] == 'EC2.VPC')
                    check(current.values['desired.row.002-003.value'] == previous.values['desired.row.002-003.value'] and
                          m.comparator().literal(current.values['observed.row.002-003.value']) == observed,
                          'Subnet logical reference remains while actual second-VPC identity is observed separately')
                    validator = module('validate-blueprint.py', 'import_reference_validator').Validator(root, {('dev', ACCOUNT, 'vpc')})
                    validator.check_design_links({'EC2.VPC': {'EC2.VPC.VpcId'}, 'EC2.Subnet': {'EC2.Subnet.SubnetId'}})
                    check(any('identifier reference does not match observed target' in error for error in validator.errors), 'explicit offline reference validation detects the preserved mismatch')
                check(current.values['desired.row.014-007.value'] == fields['ResourceId'] and import_guard.resource_config(current.values, '014', path) == baseline,
                      'Flow Log configuration and main-vpc logical reference stay exact')
                check(current.values['observed.row.014-007.value'] == vpcs[0]['VpcId'] and
                      current.values['observed.row.014-002.value'] == previous.values['observed.row.014-002.value'],
                      'reference observation follows captured VPC ID without claiming Flow Log deployment')
                saved = snapshot(root)
                m.refresh(root, 'dev', 'vpc', cli_runner=cli(vpcs))
                check(snapshot(root) == saved, 'reordered repeated inventory yields byte-identical sources/views')
                rejected(lambda: m.refresh(root, 'dev', 'vpc', cli_runner=cli([])), 'main-vpc has no retrieved VPC')
                check(snapshot(root) == saved and not (root / 'logs').exists(), 'empty VPC inventory stops without writes or logs')


def check_reference_failure_reason():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = fixture(root)
        template = m.service_source(path)[1]
        text = template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n',
            '# definition: Fixture_dev\n# reference: MissingGroup {"instance":"absent-group","resourceType":"Logs.LogGroup"}\n')
        template.write_text(text.replace('desired.row.row_001-001.value=`fixture-001`',
                                       'desired.row.row_001-001.value=<<MissingGroup>>'), encoding='utf-8')
        before = snapshot(root)
        stream = io.StringIO()
        with patch.object(m, 'import_context', side_effect=AssertionError('AWS acquisition forbidden')), \
                patch.object(sys, 'argv', ['import-model', '--repository-root', str(root), '--environment', 'dev',
                                          '--service', 'cloudwatch-logs', '--dry-run']), redirect_stdout(stream):
            check(m.main() == 2, 'missing reference retains failed exit status')
        failure = json.loads(stream.getvalue())
        check(failure['status'] == 'failed' and
              failure['reason'] == 'unknown instance reference: fixture/MissingGroup: absent-group',
              'real reference failure reason identifies consumer, parameter and missing instance')
        check(failure['location']['file'] == 'framework/scripts/model_parameter_inputs.py',
              'reference failure identifies the actual resolver')
        source = (m.ROOT / failure['location']['file']).read_text(encoding='utf-8').splitlines()
        check('unknown instance reference:' in source[failure['location']['line'] - 1],
              'reference failure location points to the actual raise')
        check(snapshot(root) == before and not (root / 'logs').exists(),
              'failure report creates no logs or source/view changes')


def check_optional_profile():
    with tempfile.TemporaryDirectory() as tmp, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        root = Path(tmp) / 'profiles'; root.mkdir()
        fixture(root)
        project = json.loads((root / 'project.json').read_text(encoding='utf-8'))
        target = project['targets'][0]
        target['awsExecutionAccountId'] = '999999999999'
        for profile in ['confirmed', None]:
            if profile is None:
                target.pop('awsProfile')
            (root / 'project.json').write_text(json_text(project) + '\n', encoding='utf-8')
            before = snapshot(root)
            cli = AwsCli(account=target['awsExecutionAccountId'], profile=profile)
            plan = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=cli)
            check(plan['status'] == 'dry-run' and plan['connection'] == {
                'profile': profile, 'region': target['awsRegion'], 'account': target['awsExecutionAccountId'], 'sts': 'verified'},
                'optional profile report retains region and verified execution account')
            check(cli.calls[0] == ('sts', 'get-caller-identity', {}) and len(cli.calls) > 1, 'STS precedes inventory with either profile selection')
            stream = io.StringIO()
            with redirect_stdout(stream): m.print_report(plan)
            check('Profile=' + (profile or 'default credential chain') in stream.getvalue(), 'report identifies configured/default credential selection')
            for failed, code in [(AwsCli(account=ACCOUNT, profile=profile), 'AccountMismatch'),
                                 (AwsCli(fail='An error occurred (AccessDenied) when calling GetCallerIdentity: SECRET-CREDENTIAL', profile=profile), 'AccessDenied')]:
                try:
                    m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=failed)
                except m.comparator().AcquisitionError as error:
                    check(error.code == code and 'SECRET' not in str(error), 'optional profile fails safely on account/auth errors')
                    check(failed.calls == [('sts', 'get-caller-identity', {})], 'no fallback or inventory after failed STS')
                else:
                    raise AssertionError('must stop on failed identity')
            cli = AwsCli(profile=profile)
            rejected(lambda: m.import_context(root, {**target, 'awsRegion': 'UNSET'}, cli), 'RegionMismatch')
            check(not cli.calls and snapshot(root) == before, 'invalid region stops before CLI and preview/failures change no files')
        subprocess.run(['git', 'add', 'project.json'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'optional profile'], cwd=root, check=True)
        reserve(root, plan)
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=AwsCli(account=target['awsExecutionAccountId'], profile=None))
        check(result['status'] == 'complete' and result['markdown'] == 'generated' and result['connection']['profile'] is None,
              'mock normal import without profile generates and verifies fixture views')


def check_explicit_no_profile_in_primary_checkout():
    from worktree_task import committed_task_paths
    with tempfile.TemporaryDirectory() as tmp, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        root = Path(tmp).resolve() / 'checkout'; root.mkdir()
        path = fixture(root)
        project_file = root / 'project.json'
        project = json.loads(project_file.read_bytes())
        project['targets'][0]['awsExecutionAccountId'] = '999999999999'
        project_file.write_text(json_text(project) + '\n', encoding='utf-8')
        project_bytes = project_file.read_bytes()
        before = snapshot(root)
        original = load_model(path).values
        check((root / '.git').is_dir(), 'normal Git checkout, not a linked worktree')
        cli = AwsCli(account='999999999999', profile=None)
        plan = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=cli, no_profile=True)
        check(plan['connection'] == {'profile': None, 'region': 'ap-northeast-1', 'account': '999999999999', 'sts': 'verified'},
              'explicit omission reports the actual default credential selection and execution account')
        check(snapshot(root) == before, 'explicit profile omission changes no project or preview files')
        configured = AwsCli(account='999999999999')
        configured_plan = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=configured)
        check(configured_plan['connection']['profile'] == 'confirmed', 'profile omission never persists to the next invocation')

        for failed, code in [(AwsCli(account=ACCOUNT, profile=None), 'AccountMismatch'),
                             (AwsCli(fail='An error occurred (AccessDenied) when calling GetCallerIdentity: SECRET-CREDENTIAL', profile=None), 'AccessDenied')]:
            with pytest.raises(m.comparator().AcquisitionError) as failure:
                m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=failed, no_profile=True)
            check(failure.value.code == code and 'SECRET' not in str(failure.value), 'explicit omission retains safe account/auth failure')
            check(failed.calls == [('sts', 'get-caller-identity', {})], 'explicit omission never retries or acquires inventory after failed STS')

        actual_refresh = m.refresh
        cli = AwsCli(account='999999999999', profile=None)
        aws_config = Path(tmp) / 'aws-config'
        aws_config.write_text('[profile inherited-profile]\nregion = ap-northeast-1\n', encoding='utf-8')
        def inherited_cli(command, **kwargs):
            check(kwargs['env']['AWS_PROFILE'] == 'inherited-profile', 'default credential chain retains inherited AWS_PROFILE')
            return cli(command, **kwargs)
        stream = io.StringIO()
        with patch.dict(os.environ, {'AWS_PROFILE': 'inherited-profile', 'AWS_CONFIG_FILE': str(aws_config),
                                    'AWS_SHARED_CREDENTIALS_FILE': str(Path(tmp) / 'absent-credentials')}), \
                patch.object(m, 'refresh', side_effect=lambda *args, **kwargs: actual_refresh(*args, **kwargs, cli_runner=inherited_cli)), \
                patch.object(sys, 'argv', ['import-model', '--repository-root', str(root), '--environment', 'dev',
                                          '--service', 'cloudwatch-logs', '--dry-run', '--no-profile']), redirect_stdout(stream):
            check(m.main() == 0, 'CLI forwards explicit profile omission through real refresh: ' + stream.getvalue())
        check('Profile=default credential chain' in stream.getvalue() and len(cli.calls) > 1,
              'CLI reports omitted profile after verified inventory')
        for invalid in ['', None, 'UNSET']:
            project['targets'][0]['awsProfile'] = invalid
            project_file.write_text(json_text(project) + '\n', encoding='utf-8')
            failed = AwsCli(profile=None)
            with pytest.raises(RuntimeError, match='target AWS profile is invalid'):
                m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=failed, no_profile=True)
            check(not failed.calls, 'explicit omission does not bypass configured-value validation')
        project_file.write_bytes(project_bytes)
        check(snapshot(root) == before, 'previews and failures preserve current-checkout inputs')

        subprocess.run(['git', 'add', 'project.json'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'execution account'], cwd=root, check=True)
        contract(root, [])
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            check(committed_task_paths(root, 'tasks/import-fixture.md') is None, 'current-checkout import needs no managed lifecycle state')
            result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=AwsCli(account='999999999999', profile=None), no_profile=True)
            check(result['status'] == 'complete' and result['markdown'] == 'generated',
                  'current-checkout normal import registers candidates, saves, generates and verifies without a new worktree')
            m.require_import_changes(root)
            proof = json.loads(import_guard.proof_path(root).read_text(encoding='utf-8'))
            check(proof['model'] == 'reflected' and proof['worktree'] == m.task_contract.worktree_identity(root),
                  'verified import evidence remains bound to the primary checkout')
            linked = Path(tmp) / 'evidence-linked'
            subprocess.run(['git', 'worktree', 'add', '--detach', str(linked), 'HEAD'], cwd=root, check=True, capture_output=True)
            proof_file = import_guard.proof_path(root)
            original_proof = proof_file.read_bytes()
            try:
                proof['worktree'] = m.task_contract.worktree_identity(linked)
                proof_file.write_text(json_text(proof), encoding='utf-8')
                rejected(lambda: m.require_import_changes(root), 'verified /import evidence')
            finally:
                proof_file.write_bytes(original_proof)
                subprocess.run(['git', 'worktree', 'remove', str(linked)], cwd=root, check=True, capture_output=True)
            m.require_import_changes(root)
        check(import_guard.resource_config(original, '002') == import_guard.resource_config(load_model(path).values, '002'),
              'current-checkout profile omission preserves CREATE exactly')
        check(project_file.read_bytes() == project_bytes and not (root / '.worktrees').exists(),
              'normal import retains configured profile bytes and creates no worktree or lifecycle metadata')


def check_single_acquisition():
    from task_contract import reservations, contracts
    from import_scope import restrict
    with tempfile.TemporaryDirectory() as temporary, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        root = Path(temporary).resolve() / 'single'; root.mkdir()
        path = fixture(root)
        contract(root, [])
        original = load_model(path).values
        own = root / 'tasks/import-fixture.md'
        before = own.read_bytes()
        with restrict(('dev', ACCOUNT, 'cloudwatch-logs')):
            for sources, views in [({root / 'project.json'}, set()),
                                   ({root / 'model/parameters/dev' / ACCOUNT / 'cloudwatch-logs/secret.json'}, set()),
                                   (set(), {root / 'docs/designs/dev' / ACCOUNT / 'iam.md'}),
                                   ({root / 'model/templates' / ACCOUNT / 'iam.properties.tpl'}, set())]:
                rejected(lambda: m.reserve_outputs(root, ('dev', ACCOUNT, 'cloudwatch-logs'), sources, views), 'outside selected')
                check(own.read_bytes() == before, 'out-of-scope candidates do not broaden contract')
        cli = AwsCli()
        with patch.object(m.comparator(), 'compare_resource', side_effect=AssertionError('no comparison')):
            result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
        check(result['status'] == 'complete' and result['markdown'] == 'generated', 'contract-only normal import completes without dry-run')
        check(cli.calls == [('sts', 'get-caller-identity', {}), ('logs', 'describe-log-groups', {})], 'ordinary invocation performs one identity check and one inventory listing')
        registered = reservations(root, contracts(root))['tasks/import-fixture.md']
        check(registered.files == set(result['files']) | {'tasks/import-fixture.md'} and registered.active == registered.files,
              'exact candidate paths including new observed file are registered and acquired')
        check(m.section(own.read_text(encoding='utf-8'), '## Validation scope') == ['- `dev/' + ACCOUNT + '/cloudwatch-logs`'], 'output registration preserves selected scope')
        check(import_guard.resource_config(original, '002') == import_guard.resource_config(load_model(path).values, '002'), 'single acquisition preserves CREATE')
        cli = AwsCli()
        cli.logs += [dict(logGroupName='large-' + str(index), retentionInDays=7, logGroupClass='STANDARD') for index in range(35)]
        expanded = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
        parts = {file for file in expanded['files'] if '/part-' in file}
        check(parts and all((root / file).is_file() for file in parts), 'inventory-discovered template parts registered without preview')
        check(sum(call[0] == 'logs' for call in cli.calls) == 1, 'part discovery does not reacquire inventory')
        cli = AwsCli()
        reduced = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
        deleted = {file for file in parts if not (root / file).exists()}
        check(not deleted and len(m.entries(load_model(path).values, 'desired.resource.')) == 3,
              'inventory shrink removes only selected bindings and retains definitions potentially used by other consumers')
        check(reduced['status'] == 'complete' and sum(call[0] == 'logs' for call in cli.calls) == 1, 'shrink completes in one acquisition')
        before = snapshot(root)
        cli = AwsCli()
        check(m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)['status'] == 'complete', 'identical inventory still verifies views')
        check(snapshot(root) == before and sum(call[0] == 'logs' for call in cli.calls) == 1, 'identical inventory avoids source/contract rewrites')


def check_reservation_races():
    from task_contract import suspend, reservations, contracts
    for race in ('release', 'source'):
        with tempfile.TemporaryDirectory() as temporary, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            root = Path(temporary).resolve() / race; root.mkdir()
            path = fixture(root)
            parameters = m.service_source(path)[2] / 'parameters.yaml'
            relative = parameters.relative_to(root).as_posix()
            contract(root, [])
            blocker = (root / 'tasks/import-fixture.md').read_text(encoding='utf-8').replace('import-fixture', 'import-blocker')
            blocker = blocker.replace('- `tasks/import-blocker.md`', '- `tasks/import-blocker.md`\n- `' + relative + '`')
            start(root, 'tasks/import-blocker.md', blocker)
            before = snapshot(root)
            cli = AwsCli()
            waits = []
            def release(_):
                check(sum(call[0] == 'logs' for call in cli.calls) == 1, 'waiting retains one acquired inventory')
                entry = reservations(root, contracts(root))['tasks/import-fixture.md']
                check(relative not in entry.active and (root / relative).read_bytes() == before[Path(relative)], 'Deferred source remains unwritten')
                waits.append(True)
                if race == 'source':
                    parameters.write_bytes(before[Path(relative)] + b'\n')
                elif race == 'issue':
                    issue = root / 'issues/dev' / ACCOUNT / 'issues.md'
                    issue.parent.mkdir(parents=True, exist_ok=True)
                    issue.write_text('### cloudwatch-logs\n1. Blocking issue\n', encoding='utf-8')
                suspend(root, 'tasks/import-blocker.md', 'Fixture reservation released')
            batches = m.reserved_batches
            with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}), patch.object(m, 'reserved_batches', side_effect=lambda root, jobs: batches(root, jobs, sleeper=release)):
                if race == 'release':
                    check(m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)['status'] == 'complete', 'released reservations publish same candidate')
                else:
                    rejected(lambda: m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli), 'sources changed' if race == 'source' else 'unresolved')
                    for file, data in before.items():
                        if file.parts[0] != 'tasks' and not (race == 'source' and file == Path(relative)):
                            check((root / file).read_bytes() == data, 'waiting race publishes no candidate sources/views')
                    check(not (parameters.parent / 'observed.json').exists(), 'waiting race creates no observed output')
            check(len(waits) == 1 and cli.calls == [('sts', 'get-caller-identity', {}), ('logs', 'describe-log-groups', {})], 'reservation resume never repeats AWS acquisition')


def check_create_definition_reuse():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve() / 'create'; root.mkdir()
        path = fixture(root, parameter=False)
        data = {key: value for key, value in values().items() if not key.startswith(('desired.resource.001.', 'display.resource.001.', 'desired.row.001-'))}
        write_model(path, data)
        _, template, directory = m.service_source(path)
        declarations = '\n'.join('# parameter: ' + name + ' ' + json_text({'type': kind, 'description': 'CREATE設定', 'required': True})
                                 for name, kind in [('Days', 'integer'), ('GroupName', 'string'), ('HasClass', 'boolean')])
        text = template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n', '# definition: Fixture_dev\n' + declarations + '\n')
        text = text.replace('desired.row.row_002-001.value=`fixture-002`', 'desired.row.row_002-001.value=`<<GroupName>>`')
        text = text.replace('desired.row.row_002-002.value=`30`', 'desired.row.row_002-002.value=<<Days>>')
        text = text.replace('desired.resource.resource_002.anchor=cloudwatch-logs-fixture-002', 'desired.resource.resource_002.anchor=cloudwatch-logs-<<GroupName>>')
        text = text.replace('# end-definition', '\n'.join('# optional: desired.row.row_002-004.' + leaf + ' HasClass' for leaf in ('property', 'value', 'comment')) + '\n# end-definition')
        metadata = [line for line in text.splitlines() if line.startswith(('desired.service.', 'display.service.'))]
        text = '\n'.join(line for line in text.splitlines() if line not in metadata) + '\n# definition: Metadata\n' + '\n'.join(metadata) + '\n# end-definition\n'
        template.write_text(text, encoding='utf-8')
        binding = json.loads((directory / 'bindings.json').read_text(encoding='utf-8'))['instances']['fixture']
        second = {**binding, 'resources': {local: '003' for local in binding['resources']},
                  'rows': {local: row.replace('002-', '003-') for local, row in binding['rows'].items() if not row.endswith('-004')}}
        (directory / 'bindings.json').write_text(json_text({'instances': {'fixture': binding, 'second': second,
            'metadata': {'definition': 'Metadata', 'resources': {}, 'rows': {}, 'parameters': {}}}}) + '\n', encoding='utf-8')
        (directory / 'parameters.yaml').write_text('instances:\n  fixture:\n    parameters:\n      Days: 30\n      GroupName: first\n      HasClass: true\n  second:\n    parameters:\n      Days: 7\n      GroupName: second\n      HasClass: false\n', encoding='utf-8')
        expansion = load_expansion(path)
        output = m.snapshot_sources(path, expansion, expansion.values)
        check(not output, 'unchanged CREATE reuses original definitions, optional directives, bindings and inputs byte for byte')
        from sync_files import save_files
        save_files(output)
        check(load_expansion(path).values == expansion.values, 'CREATE expanded output preserved including parameters and optional rows')


def check_cli_faults_and_shared_consumers():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'faults'; root.mkdir()
        path = fixture(root)
        target = m.target_for(root, 'dev', 'cloudwatch-logs')
        for response, code in [('[]', 'ValueError'), ('not-json PRIVATE-CREDENTIAL', 'JSONDecodeError')]:
            runner = lambda command, **kwargs: subprocess.CompletedProcess(command, 0, response, '')
            ctx = m.import_context(root, target, runner)
            try: ctx.verify()
            except m.comparator().AcquisitionError as error: check(error.code == code, 'CLI malformed/pagination response fails closed')
            else: raise AssertionError('must reject incomplete CLI response')
        for error, code in [(FileNotFoundError(), 'FileNotFoundError'), (subprocess.TimeoutExpired(['aws'], 60), 'TimeoutExpired')]:
            def runner(command, **kwargs): raise error
            ctx = m.import_context(root, target, runner)
            try: ctx.verify()
            except m.comparator().AcquisitionError as failure: check(failure.code == code, 'CLI transport failure is sanitized')
            else: raise AssertionError('must reject CLI failure')
        real_run = subprocess.run
        def no_aws(command, **kwargs):
            if command[0] == 'aws':
                return subprocess.CompletedProcess(command, 1, '', 'An error occurred (AccessDenied) when calling GetCallerIdentity: PRIVATE-CREDENTIAL')
            return real_run(command, **kwargs)
        stream = io.StringIO()
        with patch.object(subprocess, 'run', side_effect=no_aws), patch.object(sys, 'argv', ['import-model', '--repository-root', str(root), '--environment', 'dev', '--service', 'cloudwatch-logs', '--dry-run']), redirect_stdout(stream):
            check(m.main() == 2, 'CLI authentication failure is not success')
        check('AccessDenied' in stream.getvalue() and 'PRIVATE-CREDENTIAL' not in stream.getvalue(), 'CLI stderr/credential values never escape report')
        failure = json.loads(stream.getvalue())
        check(failure['location']['file'] == 'framework/scripts/check-model-aws.py' and
              type(failure['location']['line']) is int, 'authentication failure reports only a repository code location')
        real_import = builtins.__import__
        def missing_dependency(name, *args, **kwargs):
            if name == 'pystache':
                raise ModuleNotFoundError('PRIVATE-CREDENTIAL')
            return real_import(name, *args, **kwargs)
        stream = io.StringIO()
        with patch.object(builtins, '__import__', side_effect=missing_dependency), \
                patch.object(m, 'refresh', side_effect=lambda *args, **kwargs: resolve('prefix-<<Name>>', {'Name': 'fixture'})), \
                patch.object(sys, 'argv', ['import-model', '--environment', 'dev', '--service', 'cloudwatch-logs']), redirect_stdout(stream):
            check(m.main() == 2, 'dependency failure is not success')
        failure = json.loads(stream.getvalue())
        check(failure['reason'] == 'ValueError' and failure['location']['file'] == 'framework/scripts/model_templates.py',
              'masked ValueError identifies the actual Model expansion failure')
        source = (m.ROOT / failure['location']['file']).read_text(encoding='utf-8').splitlines()
        check("raise ValueError('install framework/scripts/requirements.txt" in source[failure['location']['line'] - 1],
              'reported line is the actual dependency failure raise')
        check(set(failure['location']) == {'file', 'line'} and 'PRIVATE-CREDENTIAL' not in stream.getvalue() and
              str(root) not in stream.getvalue() and str(m.ROOT) not in stream.getvalue(),
              'diagnostic omits exception values, source lines, locals and absolute paths')
        for error in [ValueError('PRIVATE-CREDENTIAL'), subprocess.CalledProcessError(1, ['aws', 'PRIVATE-CREDENTIAL'],
                output='PRIVATE-CREDENTIAL', stderr='PRIVATE-CREDENTIAL')]:
            stream = io.StringIO()
            with patch.object(m, 'refresh', side_effect=error), \
                    patch.object(sys, 'argv', ['import-model', '--environment', 'dev', '--service', 'cloudwatch-logs']), redirect_stdout(stream):
                check(m.main() == 2, 'unknown runtime failure retains exit 2')
            failure = json.loads(stream.getvalue())
            check('location' in failure and 'PRIVATE-CREDENTIAL' not in stream.getvalue(),
                  'unknown exception and subprocess payloads stay masked')
        plan = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=AwsCli())
        reserve(root, plan)
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            with patch.object(sync_runtime, 'generate_files', side_effect=ValueError('Markdown generation failed')):
                failed = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=AwsCli())
            check(failed['model'] == 'reflected' and failed['markdown'] == 'failed', 'display failure retains Model reflection')
            result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=AwsCli())
            check(result['model'] == 'unchanged' and result['markdown'] == 'generated', 'unchanged Model can refresh stale views')
            cli = AwsCli(); cli.logs = []
            result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
            check(result['resources']['import'] == 0 and len(m.entries(load_model(path).values, 'desired.resource.')) == 1, 'successful empty AWS list removes stale IMPORT and preserves CREATE')

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'shared'; root.mkdir()
        dev = fixture(root)
        stg = root / 'model/stg' / ACCOUNT / 'cloudwatch-logs.properties'
        write_model(stg, values())
        project = json.loads((root / 'project.json').read_text(encoding='utf-8'))
        project['targets'].append({**project['targets'][0], 'environment': 'stg', 'awsProfile': 'stg-must-not-be-used'})
        (root / 'project.json').write_text(json_text(project) + '\n', encoding='utf-8')
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'shared'], cwd=root, check=True)
        plan = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=AwsCli())
        check(plan['scope'] == ['dev/' + ACCOUNT + '/cloudwatch-logs'] and plan['affectedConsumers']==['stg/' + ACCOUNT + '/cloudwatch-logs'], 'local preservation reports registered consumers while acquisition stays selected')
        reserve(root, plan)
        cli = AwsCli()
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
            check(result['status'] == 'complete', 'selected service import completes with shared template')
            check(not (root / 'docs/designs/stg' / ACCOUNT / 'cloudwatch-logs.md').exists(), 'other environment Markdown is never generated')
            check(all(call[0] in {'sts', 'logs'} for call in cli.calls), 'source impact does not expand AWS retrieval scope')


def check_vpc_inventory_references():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'vpc'; root.mkdir()
        path = setup_service(root, 'vpc', 'EC2.VPC', {'CidrBlock': 'old-ignored', 'Name': 'old-ignored'})
        mapping = root / 'framework/mappings/aws/vpc.yaml'
        text = mapping.read_text(encoding='utf-8')
        for leaf in ('Key', 'Value'):
            text = text.replace('model: {include: false}\n        display: {show: false, name: \'Tags[].' + leaf + '\'}',
                                'model: {include: true}\n        display: {show: false, name: \'Tags[].' + leaf + '\'}')
        mapping.write_text(text, encoding='utf-8')
        subprocess.run(['git','add','.'],cwd=root,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','explicit tag include'],cwd=root,check=True)
        vpc_id, subnet_id, route_id = 'vpc-' + '1' * 17, 'subnet-' + '3' * 17, 'rtb-' + '4' * 17
        cli = AwsCli()
        cli.responses = {
            ('ec2', 'describe-subnets'): {'Subnets': [{'SubnetId': subnet_id, 'VpcId': vpc_id, 'CidrBlock': '10.1.1.0/24', 'AvailabilityZone': 'ap-northeast-1a', 'MapPublicIpOnLaunch': False, 'Tags': [{'Key': 'Name', 'Value': 'actual-subnet'}, {'Key': 'Environment', 'Value': 'dev'}]}]},
            ('ec2', 'describe-route-tables'): {'RouteTables': [{'RouteTableId': route_id, 'VpcId': vpc_id, 'Tags': [{'Key': 'Name', 'Value': 'actual-route'}], 'Associations': [{'RouteTableAssociationId': 'rtbassoc-' + '5' * 17, 'SubnetId': subnet_id}]}]},
        }
        plan = m.refresh(root, 'dev', 'vpc', dry_run=True, cli_runner=cli)
        check(plan['resources']['import'] == 4 and plan['unreflected'] == [], 'all VPC types and tag values captured')
        reserve(root, plan, 'vpc')
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            result = m.refresh(root, 'dev', 'vpc', cli_runner=cli)
            check(result['status'] == 'complete', 'VPC children and grouped association roundtrip')
            current = load_model(path).values
            check(any(row['property'] == 'EC2.SubnetRouteTableAssociation.RouteTableId' for _, row in m.entries(current, 'desired.row.')), 'unidentified association follows existing inline parent convention')
            check(any(row['property'] == 'EC2.Subnet.Tags[].Key' and row['value'] == '`Environment`' for _, row in m.entries(current, 'desired.row.')), 'non-Name AWS tags retained')
            check(any(row['property'] == 'EC2.Subnet.VpcId' and m.LINK.fullmatch(row['value']) for _, row in m.entries(current, 'desired.row.')), 'AWS physical IDs resolve to logical links')


def check_exact_scope():
    from import_scope import restrict
    from model_templates import affected
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve() / 'exact'; root.mkdir()
        path = fixture(root)
        def scoped_cli():
            cli = AwsCli()
            cli.logs[0]['deletionProtectionEnabled'] = False
            return cli
        foreign = root / 'model/parameters/stg' / ACCOUNT / 'cloudwatch-logs'
        foreign.mkdir(parents=True)
        (foreign / 'parameters.yaml').write_text('broken: [', encoding='utf-8')
        other = root / 'model/parameters/dev/other/cloudwatch-logs'
        other.mkdir(parents=True)
        (other / 'parameters.yaml').write_text('broken: [', encoding='utf-8')
        kms = root / 'model/dev' / ACCOUNT / 'kms.properties'
        key_values = values_for_service('kms', 'KMS.Key', {'KeyId': '11111111-1111-1111-1111-111111111111'})
        write_model(kms, key_values)
        (root / 'model/templates' / ACCOUNT / 'kms.properties.tpl').write_text('invalid template', encoding='utf-8')
        project = json.loads((root / 'project.json').read_text(encoding='utf-8'))
        project['targets'].append({**project['targets'][0], 'environment': 'stg', 'awsProfile': 'UNSET'})
        (root / 'project.json').write_text(json_text(project) + '\n', encoding='utf-8')
        document = root / 'docs/designs/dev' / ACCOUNT / 'kms.md'
        document.parent.mkdir(parents=True); document.write_text('invalid foreign design', encoding='utf-8')
        issues = root / 'issues/stg' / ACCOUNT / 'issues.md'
        issues.parent.mkdir(parents=True); issues.write_text('invalid foreign issues', encoding='utf-8')
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'foreign inputs'], cwd=root, check=True)
        original_open, original_glob = Path.open, Path.glob
        def permitted(file):
            if not file.is_relative_to(root):
                return True
            relative = file.relative_to(root).as_posix()
            if relative.startswith(('model/', 'docs/designs/', 'issues/')):
                return (relative.startswith(('model/templates/', 'model/parameters/stg/' + ACCOUNT + '/cloudwatch-logs/', 'model/parameters/dev/' + ACCOUNT + '/cloudwatch-logs/',
                        'model/templates/' + ACCOUNT + '/cloudwatch-logs.properties',
                        'docs/designs/dev/' + ACCOUNT + '/cloudwatch-logs')) or
                        relative == 'issues/dev/' + ACCOUNT + '/issues.md')
            return True
        def bounded_open(file, *args, **kwargs):
            check(permitted(file), 'foreign service file must not be opened: ' + str(file))
            return original_open(file, *args, **kwargs)
        def bounded_glob(directory, pattern, *args, **kwargs):
            check(not directory.is_relative_to(root / 'model/parameters') or directory == root / 'model/parameters' and pattern in {'*/*/*', '*/' + ACCOUNT + '/cloudwatch-logs'}, 'only consumer registration directory discovery is permitted')
            check(directory != root / 'issues', 'no issue target discovery scan')
            return original_glob(directory, pattern, *args, **kwargs)
        with patch.object(Path, 'open', bounded_open), patch.object(Path, 'glob', bounded_glob):
            plan = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=scoped_cli())
        check(plan['scope'] == ['dev/' + ACCOUNT + '/cloudwatch-logs'], 'dry-run selects only exact identity despite broken foreign inputs')
        reserve(root, plan)
        cli = scoped_cli()
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}), patch.object(Path, 'open', bounded_open), patch.object(Path, 'glob', bounded_glob):
            result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
            check(result['status'] == 'complete', 'normal import, guard and generator ignore foreign inputs')
            with restrict(('dev', ACCOUNT, 'cloudwatch-logs')):
                check(affected(root, set()) == set(), 'no-change import does not scan foreign templates')
                ctx = m.import_context(root, m.target_for(root, 'dev', 'cloudwatch-logs'), cli, 'cloudwatch-logs')
                ctx.verify()
                rejected(lambda: ctx.call('kms', 'describe_key', KeyId='foreign'), 'read-only allowlist')
                rejected(lambda: ctx.model(kms), 'outside selected')
            comparator = m.comparator()
            comparator.MODULES.clear()
            m.import_context(root, m.target_for(root, 'dev', 'cloudwatch-logs'), cli, 'cloudwatch-logs')
            check(set(comparator.MODULES) == {'cloudwatch-logs'}, 'only selected acquisition adapter is initialized')
            template = m.service_source(path)[1]
            original = template.read_text(encoding='utf-8')
            template.write_text(original.replace('.value=`30`', '.value=`31`'), encoding='utf-8')
            from import_guard import require_import_changes
            rejected(lambda: require_import_changes(root), 'differs from acquired change plan')
            template.write_text(original, encoding='utf-8')
        check({call[0] for call in cli.calls} == {'sts', 'logs'}, 'AWS calls remain selected service plus mandatory STS')
        # A foreign link is reported incomplete without reading its Model or invoking its API.
        linked = values()
        linked.update({'desired.row.001-900.property': 'Logs.LogGroup.KmsKeyId',
                      'desired.row.001-900.value': '[Key](kms.md#' + key_values['desired.resource.001.anchor'] + ')',
                      'desired.row.001-900.comment': '外部参照'})
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': ''}):
            # The direct fixture writer is test setup, outside the import execution boundary.
            (root / 'tasks/import-fixture.md').unlink()
            write_model(path, linked)
        cli = scoped_cli()
        cli.logs[0]['retentionInDays'] = 30
        cli.logs[0]['kmsKeyId'] = 'arn:aws:kms:ap-northeast-1:' + ACCOUNT + ':key/11111111-1111-1111-1111-111111111111'
        with patch.object(Path, 'open', bounded_open), patch.object(Path, 'glob', bounded_glob):
            result = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=cli)
        check(result['status'] == 'dry-run' and not result['unreflected'], 'foreign reference values are captured without reading the producer')
        check({call[0] for call in cli.calls} == {'sts', 'logs'}, 'foreign reference never calls KMS')
        template = m.service_source(path)[1]
        declaration = '# reference: ForeignKey ' + json_text({'service': 'kms', 'resource': '001', 'resourceType': 'KMS.Key'})
        template.write_text(template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n', '# definition: Fixture_dev\n' + declaration + '\n').replace(linked['desired.row.001-900.value'], '<<ForeignKey>>'), encoding='utf-8')
        cli = scoped_cli()
        cli.logs[0]['retentionInDays'] = 30
        cli.logs[0]['kmsKeyId'] = 'arn:aws:kms:ap-northeast-1:' + ACCOUNT + ':key/11111111-1111-1111-1111-111111111111'
        with patch.object(Path, 'open', bounded_open), patch.object(Path, 'glob', bounded_glob):
            result = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=cli)
        check(result['status'] == 'dry-run' and not result['unreflected'], 'external template reference is retained without expanding its producer')


def check_create_external_references():
    from import_scope import restrict
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve() / 'create-links'; root.mkdir()
        fixture(root)
        small_framework(root, ['vpc', 'iam'], ['EC2.VPC', 'IAM.Role'])
        path = root / 'model/dev' / ACCOUNT / 'vpc.properties'
        data = values_for_service('vpc', 'EC2.VPC', {'Name': 'vpc-fixture-dev', 'CidrBlock': '10.0.0.0/16', 'VpcId': 'unused'})
        data['desired.service.vpc.ownedCatalogResourceTypes'] += ',EC2.FlowLog'
        data['desired.row.001-003.value'] = '[Fixture001](#vpc-vpc-fixture-dev)'
        data['observed.row.001-003.value'] = '`vpc-' + '1' * 17 + '`'
        data.update({'desired.resource.002.resourceType': 'EC2.FlowLog',
                     'desired.resource.002.resourceMode': 'CREATE', 'desired.resource.002.logicalId': 'FlowLog002', 'desired.resource.002.anchor': 'vpc-flowlog-fixture-dev',
                     'display.resource.002.comment': '保持するCREATE'})
        fields = [('Name', '`flowlog-fixture-dev`'), ('Id', '[FlowLog002](#vpc-flowlog-fixture-dev)'),
                  ('DeliverLogsPermissionArn', '[SavedRole](iam.md#custom-role-anchor)'),
                  ('LogDestinationType', '`cloud-watch-logs`'), ('LogGroupName', '[SavedLogs](cloudwatch-logs.md#custom-log-anchor)'),
                  ('MaxAggregationInterval', '`60`'), ('ResourceId', '[Fixture001](#vpc-vpc-fixture-dev)'),
                  ('ResourceType', '`VPC`'), ('TrafficType', '`ALL`')]
        for index, (prop, value) in enumerate(fields, 1):
            key = f'desired.row.002-{index:03d}.'
            data.update({key + 'property': 'EC2.FlowLog.' + prop, key + 'value': value, key + 'comment': '保持する設定'})
        data['observed.row.002-002.value'] = '`PENDING_DEPLOY`'
        data['observed.row.002-007.value'] = 'vpc-' + '1' * 17
        write_model(path, data)
        document = root / 'docs/designs/dev' / ACCOUNT / 'vpc.md'
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(b'outdated generated view\r\n')
        producers = {}
        for service, kind, fields_by_name, anchor in [
                ('iam', 'IAM.Role', {'RoleName': 'SavedRole'}, 'custom-role-anchor'),
                ('cloudwatch-logs', 'Logs.LogGroup', {'LogGroupName': 'SavedLogs'}, 'custom-log-anchor')]:
            producer = values_for_service(service, kind, fields_by_name)
            producer['desired.resource.001.anchor'] = anchor
            if service == 'iam':
                producer = {key.replace('.001.', '.075.').replace('.001-', '.075-'): value for key, value in producer.items()}
                producer.update({key.replace('.075.', '.076.').replace('.075-', '.076-'): value for key, value in list(producer.items()) if '.075.' in key or '.075-' in key})
                producer['desired.resource.076.anchor'] = 'other-role-anchor'
            producer_path = root / 'model/dev' / ACCOUNT / (service + '.properties')
            write_model(producer_path, producer)
            producers[service] = m.service_source(producer_path)[1]
        producer_sources = {file: file.read_bytes() for service in producers
                            for file in load_expansion(root / 'model/dev' / ACCOUNT / (service + '.properties')).files}
        forbid_views = True
        template = m.service_source(path)[1]
        text = template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n', '# definition: Fixture_dev\n' +
            '# reference: Role {"service":"iam","resource":"075","resourceType":"IAM.Role"}\n' +
            '# reference: Logs {"service":"cloudwatch-logs","resource":"001","resourceType":"Logs.LogGroup"}\n')
        text = text.replace(fields[2][1], '<<Role>>').replace(fields[4][1], '<<Logs>>')
        template.write_text(text, encoding='utf-8')
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'CREATE references'], cwd=root, check=True)
        original_open = Path.open
        def bounded_open(file, *args, **kwargs):
            if file.is_relative_to(root / 'model') or file.is_relative_to(root / 'docs/designs'):
                relative = file.relative_to(root).as_posix()
                allowed = ('vpc', 'iam', 'cloudwatch-logs')
                check(any(relative.startswith(('model/templates/' + ACCOUNT + '/' + service + '.properties',
                      'model/parameters/dev/' + ACCOUNT + '/' + service + '/')) for service in allowed) or
                      ((not forbid_views or 'w' in (args[0] if args else kwargs.get('mode', 'r'))) and
                       relative == 'docs/designs/dev/' + ACCOUNT + '/vpc.md'),
                      'CREATE resolution reads only selected/declared sources, no input views: ' + relative)
            return original_open(file, *args, **kwargs)
        with patch.object(Path, 'open', bounded_open), restrict(('dev', ACCOUNT, 'vpc')):
            previous = load_expansion(path)
            check(all(previous.values[key] == value for key, value in data.items()), 'CREATE logical links and local references retain exact values')
            check(not any(file.is_relative_to(root / 'docs/designs') for file in previous.files), 'generated views are absent from import inputs')
            baseline = import_guard.resource_config(previous.values, '002', path)
            before = {file: file.read_bytes() for file in previous.files}
            cli = AwsCli()
            for view in (b'outdated generated view\r\n', b'invalid duplicated links\n', None):
                if view is None:
                    document.unlink(missing_ok=True)
                else:
                    document.write_bytes(view)
                cli = AwsCli()
                plan = m.refresh(root, 'dev', 'vpc', dry_run=True, cli_runner=cli)
                check(plan['status'] == 'dry-run', 'missing/stale/CRLF Markdown does not affect import')
                check(all(file.read_bytes() == content for file, content in before.items()), 'dry-run changes no authoritative sources')
            check(not document.exists(), 'dry-run with absent Markdown does not generate it')
            class ViewRaceCli(AwsCli):
                def __call__(self, command, **kwargs):
                    response = super().__call__(command, **kwargs)
                    if command[1:3] == ['ec2', 'describe-flow-logs']:
                        document.write_bytes(b'concurrent generated view\r\n')
                    return response
            check(m.refresh(root, 'dev', 'vpc', dry_run=True, cli_runner=ViewRaceCli())['status'] == 'dry-run',
                  'concurrent Markdown changes are not authoritative-source changes')
            document.unlink()
            check({call[0] for call in cli.calls} == {'sts', 'ec2'}, 'CREATE links require no IAM/Logs acquisition')
        reserve(root, plan, 'vpc')
        forbid_views = False
        with patch.object(Path, 'open', bounded_open), patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            cli = AwsCli()
            result = m.refresh(root, 'dev', 'vpc', cli_runner=cli)
            check(result['status'] == 'complete' and result['markdown'] == 'generated', 'normal import retains CREATE external template links through guards and generator')
            check(import_guard.resource_config(load_model(path).values, '002', path) == baseline, 'CREATE configuration and reference declarations remain identical after publication')
            check({call[0] for call in cli.calls} == {'sts', 'ec2'}, 'normal import calls selected service and STS only')
            with restrict(('dev', ACCOUNT, 'vpc')):
                current = load_expansion(path)
            create_prefixes = ('desired.resource.002.', 'display.resource.002.', 'desired.row.002-', 'observed.row.002-')
            check({key: value for key, value in current.values.items() if key.startswith(create_prefixes)} ==
                  {key: value for key, value in previous.values.items() if key.startswith(create_prefixes)},
                  'all CREATE settings, identity, comments and observed values remain exact')
            check(current.values['desired.row.002-003.value'] == fields[2][1] and current.values['desired.row.002-005.value'] == fields[4][1], 'custom anchors resolved from declared producer sources')
            check(all(file.read_bytes() == content for file, content in producer_sources.items()), 'producer sources remain unchanged')
            check(not (document.parent / 'iam.md').exists() and not (document.parent / 'cloudwatch-logs.md').exists(), 'only selected service is generated')
            document.write_bytes(document.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            check(m.refresh(root, 'dev', 'vpc', cli_runner=AwsCli())['status'] == 'complete',
                  'normal import with existing CRLF Markdown verifies generated views without input drift')
            # A changed reference declaration cannot bypass CREATE preservation.
            parts = m.model_parts(template)
            part = next(part for part in parts if '# reference: Role' in part.read_text(encoding='utf-8') and 'Import_' in part.read_text(encoding='utf-8'))
            saved = part.read_text(encoding='utf-8')
            marker = saved.rfind('# reference: Role')
            part.write_text(saved[:marker] + saved[marker:].replace('"target":"075"', '"target":"076"').replace('"resource":"075"', '"resource":"076"'), encoding='utf-8')
            rejected(lambda: import_guard.require_import_changes(root), 'differs from acquired change plan')
            part.write_text(saved, encoding='utf-8')
            bindings_path = m.service_source(path)[2] / 'bindings.json'
            original_bindings = bindings_path.read_bytes()
            bindings = json.loads(original_bindings)
            bindings['instances']['fixture']['labels'] = {'Role': 'ChangedLabel'}
            bindings_path.write_text(json_text(bindings) + '\n', encoding='utf-8')
            rejected(lambda: import_guard.require_import_changes(root), 'differs from acquired change plan')
            bindings_path.write_bytes(original_bindings)
            producer = producers['iam']
            old = producer.read_bytes()
            producer.unlink()
            check(m.refresh(root, 'dev', 'vpc', dry_run=True, cli_runner=AwsCli())['status'] == 'dry-run',
                  'missing external producer does not prevent selected import')
            producer.write_bytes(old)


def check_mapping_preservation():
    """Config plans and publication use real readers/generator with synthetic inputs only."""
    from sync_files import save_files
    with tempfile.TemporaryDirectory() as tmp, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        root = Path(tmp).resolve() / 'config-preservation'; root.mkdir()
        path = setup_service(root, 'config', 'Config.DeliveryChannel', {'Name': 'delivery', 'S3BucketName': 'old-bucket',
                    'ConfigSnapshotDeliveryProperties.DeliveryFrequency': 'TwentyFour_Hours'},
                    {'Name': 'created', 'S3BucketName': 'create-bucket'})
        _, template, directory = m.service_source(path)
        text = template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n', '# definition: Fixture_dev\n' +
            '# parameter: DeliveryBucketName {"type":"string","description":"Delivery bucket","required":true}\n')
        text = text.replace('desired.row.row_001-002.value=`old-bucket`', 'desired.row.row_001-002.value=`<<DeliveryBucketName>>`')
        template.write_text(text, encoding='utf-8')
        params = directory / 'parameters.yaml'
        params.write_text('instances:\n  fixture:\n    parameters:\n      DeliveryBucketName: old-bucket\n', encoding='utf-8')
        mapping = root / 'framework/mappings/aws/config.yaml'
        mapping.write_text(mapping.read_text(encoding='utf-8').replace('display: {show: true, name: S3BucketName}',
                           'display: {show: false, name: S3BucketName}'), encoding='utf-8')
        foreign = root / 'model/parameters/stg' / ACCOUNT / 'config'
        foreign.mkdir(parents=True)
        (foreign / 'parameters.yaml').write_text('foreign bytes must remain unchanged\n', encoding='utf-8')
        def cli(bucket='new-bucket', extra=None):
            runner = AwsCli()
            runner.responses = {('configservice', 'describe-configuration-recorders'): {'ConfigurationRecorders': []},
                                ('configservice', 'describe-delivery-channels'): {'DeliveryChannels': [
                                    {'name': 'delivery', 's3BucketName': bucket, 's3KeyPrefix': 'captured-prefix',
                                     'configSnapshotDeliveryProperties': {'deliveryFrequency': 'Six_Hours'}, **(extra or {})},
                                    {'name': 'created', 's3BucketName': 'must-not-change-create'}]}}
            return runner
        subprocess.run(['git','add','.'],cwd=root,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','P6 synthetic baseline'],cwd=root,check=True)
        expansion = load_expansion(path)
        before = snapshot(root)
        captured = []
        original = m.promoted_sources
        def capture(*args):
            result = original(*args)
            captured.append({p.relative_to(root): text for p, text in result[0].items()})
            return result
        with patch.object(m, 'promoted_sources', side_effect=capture):
            plan = m.refresh(root, 'dev', 'config', dry_run=True, cli_runner=cli())
        check(snapshot(root) == before, 'P6 preview writes nothing')
        check(captured[-1].keys() == {params.relative_to(root)}, 'DeliveryBucketName update changes parameters.yaml only')
        check(m.yaml_read(captured[-1][params.relative_to(root)])['instances']['fixture']['parameters']['DeliveryBucketName'] == 'new-bucket', 'meaningful parameter name retained')
        check(not any(row['property'].endswith('S3KeyPrefix') for row in plan['rows']), 'include=false excludes a new AWS property')
        missing = cli()
        missing.responses[('configservice', 'describe-delivery-channels')]['DeliveryChannels'][0].pop('s3BucketName')
        skipped = m.refresh(root, 'dev', 'config', dry_run=True, cli_runner=missing)
        check(skipped['status'] == 'incomplete' and skipped['unreflected'][0]['classification'] == 'missing',
              'unretrieved existing value is retained and classified as unconfirmed')
        wrong_type = m.refresh(root, 'dev', 'config', dry_run=True, cli_runner=cli(False))
        check(wrong_type['status'] == 'incomplete' and wrong_type['unreflected'][0]['classification'] == 'type-mismatch',
              'AWS boolean does not become a string parameter')
        check(snapshot(root) == before, 'missing and type-mismatch previews change no inputs')
        coincident = cli('bucket-channel')
        coincident.responses[('configservice', 'describe-delivery-channels')]['DeliveryChannels'].append(
            {'name': 'bucket-channel', 's3BucketName': 'external-bucket'})
        ctx = m.import_context(root, m.target_for(root, 'dev', 'config'), coincident, 'config')
        ctx.verify()
        model = ctx.model(path)
        binding = json.loads((directory / 'bindings.json').read_text(encoding='utf-8'))['instances']
        captured_values, _, _, _ = m.snapshot_values(ctx, model, m.inventory(ctx, 'config'), binding)
        check(captured_values['desired.row.001-002.value'] == '`bucket-channel`',
              'a bucket string matching another channel identity does not become a logical reference')
        reserve(root, plan, 'config')
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}), patch.object(m, 'promoted_sources', side_effect=capture):
            result = m.refresh(root, 'dev', 'config', cli_runner=cli())
        check(captured[-1] == captured[-2], 'dry-run and normal publication use identical source plans')
        check(result['status'] == 'complete', 'Config parameter publication and Model/Markdown equality pass')
        current = load_expansion(path)
        check(current.provenance['desired.row.001-002.value']['parameters'] == ['DeliveryBucketName'], 'variable provenance retained')
        check(current.values['desired.row.001-003.value'] == expansion.values['desired.row.001-003.value'], 'include=false is not deletion or overwrite')
        check(import_guard.resource_config(current.values, '002') == import_guard.resource_config(expansion.values, '002'), 'CREATE unchanged')
        check(template.read_bytes() == before[template.relative_to(root)], 'parameter-only import leaves template bytes unchanged')
        check((foreign / 'parameters.yaml').read_bytes() == before[(foreign / 'parameters.yaml').relative_to(root)], 'foreign environment untouched')
        doc = root / 'docs/designs/dev' / ACCOUNT / 'config.md'
        check('new-bucket' not in doc.read_text(encoding='utf-8') and current.values['desired.row.001-002.value'] == '`new-bucket`',
              'show=false hides Markdown but retains Model value')
        # The same public variable must not silently change CREATE or excluded destinations.
        conflicting = template.read_text(encoding='utf-8').replace('desired.row.row_002-002.value=`create-bucket`',
                                                                  'desired.row.row_002-002.value=`<<DeliveryBucketName>>`')
        template.write_text(conflicting, encoding='utf-8')
        check_before = snapshot(root)
        rejected(lambda: m.refresh(root, 'dev', 'config', dry_run=True, cli_runner=cli('next-bucket')), 'required YAML Model input missing')
        check(snapshot(root) == check_before, 'CREATE-variable conflict writes no files')
        template.write_bytes(before[template.relative_to(root)])
        # A newly selected Mapping property creates one stable row and retains the old expression.
        text = mapping.read_text(encoding='utf-8').replace('model: {include: false}\n        display: {show: false, name: S3KeyPrefix}',
                                                          'model: {include: true}\n        display: {show: false, name: S3KeyPrefix}')
        mapping.write_text(text, encoding='utf-8')
        subprocess.run(['git','add','.'],cwd=root,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','P6 next baseline'],cwd=root,check=True)
        plan = m.refresh(root, 'dev', 'config', dry_run=True, cli_runner=cli())
        check(any(row['property'].endswith('S3KeyPrefix') and row['status'] == 'captured' for row in plan['rows']), 'include=true adds a new row')
        # Existing contract remains selected; importer registers the additional private sources.
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            result = m.refresh(root, 'dev', 'config', cli_runner=cli())
        check(result['markdown'] == 'unchanged', 'hidden new row leaves already-current Markdown unchanged')
        latest = load_expansion(path)
        check(latest.values['desired.row.001-002.value'] == '`new-bucket`' and
              latest.provenance['desired.row.001-002.value']['parameters'] == ['DeliveryBucketName'], 'addition preserves existing variable')
        check(any(row['property'] == 'Config.DeliveryChannel.S3KeyPrefix' for _, row in m.entries(latest.values, 'desired.row.')), 'new row stored in Model')
        check(template.read_text(encoding='utf-8').startswith(before[template.relative_to(root)].decode()), 'old common definition is structurally unchanged')
        # Service input updates must agree across all its selected Model uses.
        (directory / 'bindings.json').write_bytes(before[(directory / 'bindings.json').relative_to(root)])
        shared_text = before[template.relative_to(root)].decode().replace('# model-template: 1\n', '# model-template: 1\n' +
            '# input: SharedBucket {"type":"string","description":"Shared bucket","required":true,"source":"service"}\n')
        shared_text = shared_text.replace('`<<DeliveryBucketName>>`', '`<<SharedBucket>>`').replace(
            '# parameter: DeliveryBucketName {"type":"string","description":"Delivery bucket","required":true}\n', '')
        shared_text = shared_text.replace('desired.row.row_002-002.value=`create-bucket`', 'desired.row.row_002-002.value=`<<SharedBucket>>`')
        shared_text = shared_text.replace('desired.resource.resource_002.resourceMode=CREATE', 'desired.resource.resource_002.resourceMode=IMPORT')
        template.write_text(shared_text, encoding='utf-8')
        params.write_text('parameters:\n  SharedBucket: new-bucket\ninstances: {}\n', encoding='utf-8')
        shared = load_expansion(path)
        desired = dict(shared.values)
        desired['desired.row.001-002.value'] = '`agreed-bucket`'
        desired['desired.row.002-002.value'] = '`agreed-bucket`'
        output = m.snapshot_sources(path, shared, desired)
        check(set(output) == {params}, 'consistent shared variable changes YAML only')
        check(m.yaml_read(output[params])['parameters']['SharedBucket'] == 'agreed-bucket', 'service shared input updated once')
        desired['desired.row.002-002.value'] = '`conflicting-bucket`'
        rejected(lambda: m.snapshot_sources(path, shared, desired), 'inconsistent AWS values')
        # Keep references/internal/context and combined expressions, including JSON, fail closed on ambiguity.
        from import_sources import equivalent
        check(not equivalent('`true`', '`1`'), 'boolean and number are distinct')
        check(not equivalent('`[true]`', '`[1]`'), 'nested JSON booleans and numbers are distinct')



def check_shared_promotion():
    from model_templates import parse_template
    from sync_files import save_files
    with tempfile.TemporaryDirectory() as tmp, patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        root = Path(tmp).resolve() / 'shared-promotion'; root.mkdir()
        path = fixture(root)
        template = m.service_source(path)[1]
        spec = lambda kind: json_text({'type':kind,'description':'Fixture input','required':True})
        text = '# model-template: 1\n# input: Environment ' + json_text({'type':'string','description':'Consumer','required':True,'source':'consumer.environment'}) + '\n'
        text += '# input: Days ' + spec('integer') + '\n# definition: Metadata\ndesired.service.cloudwatch-logs.serviceId=cloudwatch-logs\ndesired.service.cloudwatch-logs.ownedCatalogResourceTypes=Logs.LogGroup\ndisplay.service.title=# CloudWatch Logs 詳細設計\n# end-definition\n'
        text += '# definition: Group\n# parameter: Mode ' + spec('string') + '\n# parameter: Label ' + spec('string') + '\n# internal: Anchor string\n# resource: group\n'
        text += ''.join('# row: ' + name + ' group\n' for name in ('name','days','protected','class'))
        text += 'display.resource.group.comment=ログ設定\ndesired.resource.group.logicalId=LogGroup<<Id_group>>\ndesired.resource.group.resourceType=Logs.LogGroup\ndesired.resource.group.resourceMode=<<Mode>>\ndesired.resource.group.anchor=<<Anchor>>\n'
        for name, prop, raw in [('name','LogGroupName','`log-<<Environment>>-<<Label>>`'),('days','RetentionInDays','<<Days>>'),('protected','DeletionProtectionEnabled','`false`'),('class','LogGroupClass','`STANDARD`')]:
            text += 'desired.row.'+name+'.property=Logs.LogGroup.'+prop+'\ndesired.row.'+name+'.value='+raw+'\ndesired.row.'+name+'.comment=ログ設定\n'
        text += '# end-definition\n'
        template.write_text(text,encoding='utf-8')
        project = json.loads((root/'project.json').read_text(encoding='utf-8'))
        originals = {}
        for env in ('dev','stg','prod'):
            if env != 'dev': project['targets'].append({**project['targets'][0],'environment':env,'awsProfile':env+'-never-use'})
            directory = root/'model/parameters'/env/ACCOUNT/'cloudwatch-logs'; directory.mkdir(parents=True,exist_ok=True)
            bindings = {'instances':{'metadata':{'definition':'Metadata','resources':{},'rows':{},'parameters':{}}}}
            params = {'parameters':{'Days':30},'instances':{}}
            for label, rid in [('a','001'),('b','003'),('c','002')]:
                bindings['instances'][label] = {'definition':'Group','resources':{'group':rid},'rows':{name:rid+'-'+str(i).zfill(3) for i,name in enumerate(('name','days','protected','class'),1)},'parameters':{'Anchor':'cloudwatch-logs-'+env+'-'+label}}
                params['instances'][label] = {'parameters':{'Mode':'CREATE' if label=='c' or env=='stg' else 'IMPORT','Label':label}}
            save_files({directory/'bindings.json':json_text(bindings)+'\n',directory/'parameters.yaml':parameter_text(params,parse_template(template)[0],bindings)})
        (root/'project.json').write_text(json_text(project)+'\n',encoding='utf-8')
        for env in ('dev','stg','prod'):
            originals[env] = load_expansion(root/'model'/env/ACCOUNT/'cloudwatch-logs.properties').values
        issue=root/'issues/stg'/ACCOUNT/'issues.md';issue.parent.mkdir(parents=True)
        issue.write_text('### cloudwatch-logs\n1. Fixture unresolved issue\n',encoding='utf-8')
        subprocess.run(['git','add','.'],cwd=root,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','shared fixture'],cwd=root,check=True)
        cli = AwsCli(); cli.logs = [dict(logGroupName='log-dev-'+label,retentionInDays=days,deletionProtectionEnabled=protected,logGroupClass='STANDARD') for label,days,protected in [('a',90,True),('b',7,False),('c',99,True)]]
        before = snapshot(root)
        foreign_input = root/'model/parameters/stg'/ACCOUNT/'cloudwatch-logs/parameters.yaml'
        original_input = foreign_input.read_bytes()
        class InventoryRace(AwsCli):
            def __call__(self, command, **kwargs):
                if command[1:3] == ['logs','describe-log-groups']:
                    foreign_input.write_bytes(original_input + b'# concurrent comment\n')
                return super().__call__(command, **kwargs)
        m.refresh(root,'dev','cloudwatch-logs',dry_run=True,cli_runner=InventoryRace())
        check(foreign_input.read_bytes().endswith(b'# concurrent comment\n'), 'preservation reads current consumer inputs after acquisition without overwriting them')
        foreign_input.write_bytes(original_input)
        check(snapshot(root) == before, 'AWS-time preservation input race saves no sources/views/evidence')
        plan = m.refresh(root,'dev','cloudwatch-logs',dry_run=True,cli_runner=cli)
        check(snapshot(root)==before and len(plan['promotions'])==2, 'shared Days side effects and fixed boolean are isolated in dry-run')
        reserve(root,plan)
        with patch.dict(os.environ,{'BLUEPRINT_TASK_FILE':'tasks/import-fixture.md'}):
            # A concurrent preservation-consumer edit blocks the whole publication.
            foreign = root/'model/parameters/stg'/ACCOUNT/'cloudwatch-logs/parameters.yaml'
            foreign_bytes = foreign.read_bytes()
            template_bytes = template.read_bytes()
            selected_bytes = (root/'model/parameters/dev'/ACCOUNT/'cloudwatch-logs/parameters.yaml').read_bytes()
            batches = m.reserved_batches
            def race(repository, jobs):
                for item in batches(repository, jobs):
                    foreign.write_bytes(foreign_bytes + b'# concurrent input\n')
                    yield item
            with patch.object(m,'reserved_batches',side_effect=race):
                rejected(lambda:m.refresh(root,'dev','cloudwatch-logs',cli_runner=cli),'sources changed')
            check(template.read_bytes()==template_bytes and (root/'model/parameters/dev'/ACCOUNT/'cloudwatch-logs/parameters.yaml').read_bytes()==selected_bytes,'non-selected input race saves no candidate sources')
            foreign.write_bytes(foreign_bytes)
            # New consumers discovered after candidate validation invalidate the whole plan.
            extra=root/'model/parameters/qa'/ACCOUNT/'cloudwatch-logs'
            def register_consumer(repository,jobs):
                for item in batches(repository,jobs):
                    shutil.copytree(root/'model/parameters/prod'/ACCOUNT/'cloudwatch-logs',extra)
                    yield item
            with patch.object(m,'reserved_batches',side_effect=register_consumer):
                rejected(lambda:m.refresh(root,'dev','cloudwatch-logs',cli_runner=cli),'registered consumers changed')
            check(template.read_bytes()==template_bytes,'new consumer registration saves no stale candidate')
            shutil.rmtree(extra)
            # Simulate a partial source-write failure inside the existing publication journal.
            import sync_files
            original_save = sync_files.save_files
            def fail_publication(output):
                file = next(iter(output))
                original_save({file:output[file]})
                raise OSError('fixture publication failure')
            with patch.object(sync_files,'save_files',side_effect=fail_publication):
                try: m.refresh(root,'dev','cloudwatch-logs',cli_runner=cli)
                except OSError: pass
                else: raise AssertionError('publication failure must stop')
            check(template.read_bytes()==template_bytes and foreign.read_bytes()==foreign_bytes and (root/'model/parameters/dev'/ACCOUNT/'cloudwatch-logs/parameters.yaml').read_bytes()==selected_bytes,'partial shared source publication rolls back every source')
            result=m.refresh(root,'dev','cloudwatch-logs',cli_runner=cli)
            check(result['status']=='complete','shared multi-consumer import publishes and generates')
            outside = AwsCli(profile='stg-never-use')
            rejected(lambda:m.refresh(root,'stg','cloudwatch-logs',cli_runner=outside),'fixed Task target')
            check(not outside.calls,'expanded Validation scope never authorizes a second AWS acquisition target')
            for env in ('stg','prod'):
                check(load_expansion(root/'model'/env/ACCOUNT/'cloudwatch-logs.properties').values==originals[env], 'non-selected '+env+' Model is byte-for-byte identical')
                check(not (root/'docs/designs'/env/ACCOUNT/'cloudwatch-logs.md').exists(), 'non-selected '+env+' views are not generated')
            current=load_expansion(path).values
            check(import_guard.resource_config(current,'002')==import_guard.resource_config(originals['dev'],'002'), 'selected CREATE shared-variable destinations remain exact')
            check(m.comparator().literal(current['desired.row.001-002.value'])=='90' and m.comparator().literal(current['desired.row.003-002.value'])=='7', 'same Definition retains per-instance AWS values')
            check(len(parse_template(template)[0])==2,'value-only changes reuse both common Definitions')
            import_guard.require_import_changes(root)
            after=snapshot(root)
            result=m.refresh(root,'dev','cloudwatch-logs',cli_runner=cli)
            check(snapshot(root)==after and not result['files'],'shared promotion is source-idempotent')
            original_foreign = foreign.read_bytes()
            foreign.write_text(original_foreign.decode('utf-8').replace(': 30',': 31'),encoding='utf-8')
            rejected(lambda: import_guard.require_import_changes(root),'differs from acquired change plan')
            foreign.write_bytes(original_foreign)
            proof=import_guard.proof_path(root); proof.unlink()
            rejected(lambda: import_guard.require_import_changes(root),'no verified /import evidence')
        check({call[0] for call in cli.calls}=={'sts','logs'},'three local environments never enlarge AWS scope')


def check_optional_promotion_and_rejection():
    from import_promotion import plan_promotions, preserve_consumers, apply_promotions, safe_expression
    from sync_files import save_files
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp).resolve();path=root/'model/dev'/ACCOUNT/'vpc.properties'
        write_model(path,values_for_service('vpc','EC2.VPC',{'Name':'before'}))
        _,template,directory=m.service_source(path)
        before=load_expansion(path);trace=before.provenance['desired.row.001-001.value']
        collision='Import_'+hashlib.sha256('/'.join(('vpc',trace['definition'],trace['key'])).encode()).hexdigest()[:20]
        spec=lambda kind:json_text({'type':kind,'description':'Fixture','required':True})
        text=template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n','# definition: Fixture_dev\n# parameter: HasName '+spec('boolean')+'\n# parameter: '+collision+' '+spec('string')+'\n')
        text=text.replace('display.resource.resource_001.comment=既存の設定','display.resource.resource_001.comment=<<'+collision+'>>')
        text=text.replace('# end-definition', ''.join('# optional: desired.row.row_001-001.'+leaf+' HasName\n' for leaf in ('property','value','comment'))+'# end-definition')
        template.write_text(text,encoding='utf-8')
        original_binding=json.loads((directory/'bindings.json').read_text(encoding='utf-8'))
        params={'instances':{'fixture':{'parameters':{'HasName':True,collision:'unchanged'}}}}
        original_yaml=parameter_text(params,m.parse_template(template)[0],original_binding)
        save_files({directory/'parameters.yaml':original_yaml})
        foreign=root/'model/parameters/stg'/ACCOUNT/'vpc';foreign.mkdir(parents=True)
        binding=json.loads(json_text(original_binding));binding['instances']['fixture']['rows']={}
        params['instances']['fixture']['parameters']['HasName']=False
        save_files({foreign/'bindings.json':json_text(binding)+'\n',foreign/'parameters.yaml':parameter_text(params,m.parse_template(template)[0],binding)})
        other=root/'model/stg'/ACCOUNT/'vpc.properties';old_foreign=load_expansion(other).values
        before=load_expansion(path);wanted={**before.values,'desired.row.001-001.value':'`actual`'}
        plan,params=plan_promotions(path,before,wanted,lambda prop:{'type':'string'},m.unsafe,lambda prop:False)
        check(plan[0]['parameter']==collision+'_2','deterministic parameter naming avoids an existing unrelated declaration')
        output=apply_promotions(path,plan,params,preserve_consumers(path,before,plan))
        check(foreign/'parameters.yaml' not in output,'absent optional instance needs no unused parameter')
        save_files(output)
        check(load_expansion(other).values==old_foreign,'optional omission preserves every foreign Model key exactly')
        save_files({template:text,directory/'parameters.yaml':original_yaml})
        for actual, secret in [('`[physical](#anchor)`',False),('`PRIVATE-CREDENTIAL`',True)]:
            try:
                plan_promotions(path,before,{**before.values,'desired.row.001-001.value':actual},lambda prop:{'type':'string'},m.unsafe,lambda prop:secret)
            except ValueError as error:
                message=str(error)
                check(all(label+':' in message for label in ('Environment','Target','Service','Instance','Definition','Resource ID','Row ID','Property','Template file','Template line','Conflict type','Reason')) and 'PRIVATE-CREDENTIAL' not in message and 'arn:aws' not in message,'promotion rejection identifies source without disclosing values')
            else:
                raise AssertionError('unsafe promotion must stop')
        selected=m.parse_template(template)[0][trace['definition']]
        rejected(lambda:safe_expression(selected._replace(choices={(trace['key'],None,'Choice'): '`alternative`'}),trace['key']),'conditional JSON/choice')


def check_existing_snapshot_promotion():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp).resolve()/'legacy-shared';root.mkdir()
        path=fixture(root)
        _,template,directory=m.service_source(path)
        name='Import_'+hashlib.sha256(('dev/'+ACCOUNT+'/cloudwatch-logs.properties').encode()).hexdigest()[:16]+'_shared'
        template.write_text(template.read_text(encoding='utf-8').replace('Fixture_dev',name),encoding='utf-8')
        binding=directory/'bindings.json'
        binding.write_text(binding.read_text(encoding='utf-8').replace('Fixture_dev',name),encoding='utf-8')
        foreign=root/'model/parameters/stg'/ACCOUNT/'cloudwatch-logs'
        shutil.copytree(directory,foreign)
        other=root/'model/stg'/ACCOUNT/'cloudwatch-logs.properties'
        before=load_expansion(other).values
        project=json.loads((root/'project.json').read_text(encoding='utf-8'))
        project['targets'].append({**project['targets'][0],'environment':'stg'})
        (root/'project.json').write_text(json_text(project)+'\n',encoding='utf-8')
        subprocess.run(['git','add','.'],cwd=root,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','existing shared snapshot'],cwd=root,check=True)
        plan=m.refresh(root,'dev','cloudwatch-logs',dry_run=True,cli_runner=AwsCli())
        reserve(root,plan)
        with patch.dict(os.environ,{'BLUEPRINT_TASK_FILE':'tasks/import-fixture.md'}):
            result=m.refresh(root,'dev','cloudwatch-logs',cli_runner=AwsCli())
            check(result['status']=='complete' and load_expansion(other).values==before,'existing Import-prefixed Definition can be safely promoted across consumers')
            import_guard.require_import_changes(root)
            definitions=m.parse_template(template)[0]
            changed=template.read_text(encoding='utf-8')
            bad=changed.replace('desired.row.row_001-004.value=`STANDARD`','desired.row.row_001-004.value=`INFREQUENT_ACCESS`')
            template.write_text(bad,encoding='utf-8')
            rejected(lambda:import_guard.require_import_changes(root),'differs from acquired change plan')
            template.write_text(changed,encoding='utf-8')


def check_identifier_parameter_rejection():
    from import_promotion import plan_promotions
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp).resolve();path=root/'model/dev'/ACCOUNT/'vpc.properties'
        write_model(path,values_for_service('vpc','EC2.VPC',{'VpcId':'vpc-old'}))
        _,template,directory=m.service_source(path)
        text=template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n','# definition: Fixture_dev\n# parameter: PhysicalId '+json_text({'type':'string','description':'Fixture','required':True})+'\n').replace('`vpc-old`','`<<PhysicalId>>`')
        template.write_text(text,encoding='utf-8')
        (directory/'parameters.yaml').write_text('instances:\n  fixture:\n    parameters:\n      PhysicalId: vpc-old\n',encoding='utf-8')
        before=load_expansion(path)
        rejected(lambda:plan_promotions(path,before,{**before.values,'desired.row.001-001.value':'`vpc-new`'},lambda prop:{'type':'string'},m.unsafe,lambda prop:False),'identifier output')
        # Both sensitive and ambiguous typed values stop before independent inversion.
        template.write_text(text.replace('EC2.VPC.VpcId','EC2.VPC.Name'),encoding='utf-8')
        before=load_expansion(path)
        rejected(lambda:plan_promotions(path,before,{**before.values,'desired.row.001-001.value':'`PRIVATE-CREDENTIAL`'},lambda prop:{'type':'string'},m.unsafe,lambda prop:True),'sensitive')
        rejected(lambda:plan_promotions(path,before,{**before.values,'desired.row.001-001.value':'`false`'},lambda prop:{'type':['string','boolean']},m.unsafe,lambda prop:False),'union-typed scalar')
        def missing_schema(prop):
            raise ValueError('PRIVATE-CREDENTIAL')
        rejected(lambda:plan_promotions(path,before,{**before.values,'desired.row.001-001.value':'`new-name`'},missing_schema,m.unsafe,lambda prop:False),'registered Property schema could not be resolved')


def check_context_inversion():
    from import_promotion import plan_promotions
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp).resolve();path=root/'model/dev'/ACCOUNT/'config.properties'
        write_model(path,values_for_service('config','Config.ConfigurationRecorder',{'Name':'cfg-dev-east'}))
        template=m.service_source(path)[1]
        text=template.read_text(encoding='utf-8').replace('# model-template: 1\n','# model-template: 1\n# input: Environment '+json_text({'type':'string','description':'Consumer','required':True,'source':'consumer.environment'})+'\n')
        text=text.replace('# definition: Fixture_dev\n','# definition: Fixture_dev\n# parameter: Suffix '+json_text({'type':'string','description':'Suffix','required':True})+'\n').replace('`cfg-dev-east`','`cfg-<<Environment>><<Suffix>>`')
        template.write_text(text,encoding='utf-8')
        params=m.service_source(path)[2]/'parameters.yaml'
        params.write_text('instances:\n  fixture:\n    parameters:\n      Suffix: -east\n',encoding='utf-8')
        before=load_expansion(path);wanted={**before.values,'desired.row.001-001.value':'`cfg-dev-west`'}
        plans,inputs=plan_promotions(path,before,wanted,lambda prop:{'type':'string'},m.unsafe,lambda prop:False)
        check(not plans and inputs['instances']['fixture']['parameters']['Suffix']=='-west','fixed consumer context permits safe independent suffix inversion without promotion')


def check_import_document():
    from sync_files import save_files
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp).resolve()/'document';root.mkdir()
        path=setup_service(root,'config','Config.ConfigurationRecorder',{'Name':'actual-recorder','RecordingGroup.ResourceTypes':['AWS::EC2::Subnet']})
        old=load_expansion(path).values
        old['desired.row.001-002.value']='[ResourceTypes](config/resource-types.json)'
        old['desired.row.001-002.document']='["AWS::EC2::Subnet"]'
        write_model(path,old)
        expansion=load_expansion(path)
        cli=AwsCli();ctx=m.import_context(root,m.target_for(root,'dev','config'),cli,'config');ctx.verify()
        bindings=json.loads((m.service_source(path)[2]/'bindings.json').read_text(encoding='utf-8'))['instances']
        wanted,_,_,_=m.snapshot_values(ctx,ctx.model(path),m.inventory(ctx,'config'),bindings)
        check(wanted['desired.row.001-002.document']=='["AWS::EC2::VPC"]' and wanted['desired.row.001-002.value']==old['desired.row.001-002.value'],'inventory retains existing JSON document source and link')
        output,_,promotions=m.promoted_sources(path,expansion,wanted)
        check(any(item['property']=='Config.ConfigurationRecorder.RecordingGroup.ResourceTypes' for item in promotions),'mapped JSON document uses generic promotion')
        save_files(output)
        check(load_expansion(path).values['desired.row.001-002.document']==wanted['desired.row.001-002.document'],'mapped document and derived hash re-expand correctly')


def check_promotion_json_types():
    from import_promotion import plan_promotions, preserve_consumers, apply_promotions
    from sync_files import save_files
    cases = [('array',[1,False,None,{'text':'日本語'}],[2,True,None,{'text':'別'}]),
             ('object',{'x':[1,False]},{'x':[2,True],'z':None}), ('null',None,None),
             ('number',1.25,2.5), ('string','false','true')]
    for kind, old, new in cases:
        for document in (False,True):
            if old == new: continue
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve()
                path=root/'model/dev'/ACCOUNT/'config.properties'
                values=values_for_service('config','Config.ConfigurationRecorder',{'RecordingGroup':old})
                key='desired.row.001-001.value'
                if document:
                    values['desired.row.001-001.document']=json_text(old)
                    values[key]='[document](config/fixture.json)'
                    key='desired.row.001-001.document'
                write_model(path,values)
                before=load_expansion(path)
                wanted={**before.values,key:json_text(new) if document else m.model_literal(new)}
                plans,params=plan_promotions(path,before,wanted,lambda prop:{'type':kind},m.unsafe,lambda prop:False)
                output=apply_promotions(path,plans,params,preserve_consumers(path,before,plans))
                save_files(output)
                actual=load_expansion(path)
                check(actual.values[key]==wanted[key] and plans[0]['spec']['type']==kind,'typed '+kind+' '+('document' if document else 'scalar')+' exact round-trip')
                if kind=='string':
                    check(type(next(iter(m.yaml_read(output[m.service_source(path)[2]/'parameters.yaml'])['instances']['fixture']['parameters'].values()))) is str,'boolean-looking string stays string')
    # Null is supported as a whole JSON node, without pretending missing means null.
    from model_parameter_inputs import check_value, schema
    check_value(schema({'type':'null','description':'null','required':True,'format':'literal'}),None,'null')
    check(resolve('<<Node>>',{'Node':None},structured=True) is None,'null node remains JSON null')


def check_promotion_engine():
    from import_promotion import plan_promotions, preserve_consumers, apply_promotions
    from sync_files import save_files
    from model_templates import parse_template
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / 'promotion'; root.mkdir()
        path = fixture(root, parameter=False)
        template = m.service_source(path)[1]
        definition_count = len(parse_template(template)[0])
        before = load_expansion(path)
        wanted = dict(before.values)
        wanted.update({'desired.row.001-001.value': '`actual-name`',
                       'desired.row.001-002.value': '`90`', 'desired.row.001-003.value': '`true`'})
        catalog = m.comparator().DesignSchemaCatalog(m.ROOT)
        schema_for = lambda prop: catalog.property_schema(m.property_kind_from(prop), m.schema_property(m.property_kind_from(prop), prop))
        plans, parameters = plan_promotions(path, before, wanted, schema_for, m.unsafe, lambda prop: False)
        check(len(plans) == 3 and {plan['spec']['type'] for plan in plans} == {'string','integer','boolean'},
              'fixed string, numeric and boolean promote only differing Properties with exact types')
        preserved = preserve_consumers(path, before, plans)
        output = apply_promotions(path, plans, parameters, preserved)
        save_files(output)
        current = load_expansion(path)
        check(all(equivalent_value == current.values[key] for key, equivalent_value in wanted.items()), 'typed promotion round trip')
        check(import_guard.resource_config(before.values, '002') == import_guard.resource_config(current.values, '002'), 'mixed CREATE is unchanged')
        check(len(parse_template(template)[0]) == definition_count, 'no value-only snapshot definitions')
        plans, parameters = plan_promotions(path, current, wanted, schema_for, m.unsafe, lambda prop: False)
        check(not plans and not apply_promotions(path, plans, parameters, preserve_consumers(path, current, plans)), 'identical values produce no second source diff')


def check_source_expressions():
    from sync_files import save_files
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / 'expressions'; root.mkdir()
        path = setup_service(root, 'config', 'Config.ConfigurationRecorder',
                  {'Name': 'cfg-dev-east', 'RecordingGroup.ResourceTypes': ['AWS::EC2::VPC'], 'RecordingGroup.AllSupported': False})
        _, template, directory = m.service_source(path)
        declarations = (
            '# input: Environment {"type":"string","description":"Consumer","required":true,"source":"consumer.environment"}\n'
            '# input: Account {"type":"string","description":"Account","required":true,"source":"consumer.executionAccountId"}\n')
        text = template.read_text(encoding='utf-8').replace('# model-template: 1\n', '# model-template: 1\n' + declarations)
        local = ''.join('# parameter: ' + name + ' ' + json_text({'type': kind, 'description': name, 'required': True,
                       **({'internal': True} if name == 'AllSupported' else {})}) + '\n'
                        for name, kind in [('Prefix','string'),('Suffix','string'),('ResourceType','string'),('AllSupported','boolean')])
        text = text.replace('# definition: Fixture_dev\n', '# definition: Fixture_dev\n' + local)
        text = text.replace('desired.row.row_001-001.value=`cfg-dev-east`', 'desired.row.row_001-001.value=`<<Prefix>><<Environment>><<Suffix>>`')
        text = text.replace('desired.row.row_001-002.value=`["AWS::EC2::VPC"]`', 'desired.row.row_001-002.value=`["<<ResourceType>>"]`')
        text = text.replace('desired.row.row_001-003.value=`false`', 'desired.row.row_001-003.value=<<AllSupported>>')
        text = text.replace('display.resource.resource_001.comment=既存の設定', 'display.resource.resource_001.comment=Account <<Account>>')
        template.write_text(text, encoding='utf-8')
        binding = json.loads((directory / 'bindings.json').read_text(encoding='utf-8'))
        binding['instances']['fixture']['parameters']['AllSupported'] = False
        (directory / 'bindings.json').write_text(json_text(binding)+'\n', encoding='utf-8')
        (directory / 'parameters.yaml').write_text('instances:\n  fixture:\n    parameters:\n      Prefix: cfg-\n      Suffix: -east\n      ResourceType: AWS::EC2::VPC\n', encoding='utf-8')
        expansion = load_expansion(path)
        wanted = dict(expansion.values)
        wanted['desired.row.001-002.value'] = '`["AWS::EC2::Subnet"]`'
        output = m.snapshot_sources(path, expansion, wanted)
        check(set(output) == {directory / 'parameters.yaml'}, 'JSON internal parameter inversion changes YAML only')
        save_files(output)
        check(load_expansion(path).values['desired.row.001-002.value'] == wanted['desired.row.001-002.value'], 'JSON parameter round trip preserves types and structure')
        expansion = load_expansion(path)
        check(not m.snapshot_sources(path, expansion, expansion.values), 'unchanged combined, internal, environment and account expressions reuse source bytes')
        wanted = dict(expansion.values); wanted['desired.row.001-001.value'] = '`other-prod-west`'
        output, _, promotions = m.promoted_sources(path, expansion, wanted)
        check(len(promotions)==1 and promotions[0]['property']=='Config.ConfigurationRecorder.Name' and template in output,'safe combined expression promotes at Property scope')
        wanted = dict(expansion.values); wanted['desired.row.001-003.value'] = 'true'
        rejected(lambda: m.promoted_sources(path, expansion, wanted), 'internal identifier')
        # Existing optional syntax reuses its definition and variable, with stable explicit row IDs.
        text = template.read_text(encoding='utf-8').replace('# definition: Fixture_dev\n', '# definition: Fixture_dev\n' +
            '# parameter: HasFrequency {"type":"boolean","description":"Frequency present","required":true}\n' +
            '# parameter: Frequency {"type":"string","description":"Recording frequency","required":true}\n' +
            '# row: frequency resource_001\n' +
            ''.join('# optional: desired.row.frequency.' + leaf + ' HasFrequency\n' for leaf in ('property','value','comment')))
        text = text.replace('# end-definition', 'desired.row.frequency.property=Config.ConfigurationRecorder.RecordingMode.RecordingFrequency\n' +
            'desired.row.frequency.value=`<<Frequency>>`\ndesired.row.frequency.comment=記録頻度\n# end-definition')
        template.write_text(text, encoding='utf-8')
        params = directory / 'parameters.yaml'
        params.write_text(params.read_text(encoding='utf-8') + '      HasFrequency: false\n', encoding='utf-8')
        expansion = load_expansion(path)
        wanted = dict(expansion.values)
        wanted.update({'desired.row.001-004.property': 'Config.ConfigurationRecorder.RecordingMode.RecordingFrequency',
                       'desired.row.001-004.value': '`DAILY`', 'desired.row.001-004.comment': 'AWSから取得した設定'})
        before = template.read_bytes()
        output = m.snapshot_sources(path, expansion, wanted)
        check(template not in output and set(output) == {params, directory / 'bindings.json'}, 'optional row reuses template without a derived definition')
        check(all(m.yaml_read(output[params])['instances']['fixture']['parameters'].get(key) == value for key, value in {'HasFrequency': True, 'Frequency': 'DAILY'}.items()), 'optional selector and meaningful value input retained')
        save_files(output)
        current = load_expansion(path)
        check(current.values['desired.row.001-004.value'] == '`DAILY`' and current.provenance['desired.row.001-004.value']['parameters'] == ['Frequency','HasFrequency'],
              'optional row has stable explicit ID and original provenance')
        check(template.read_bytes() == before, 'optional activation changes no shared template bytes')
        wanted = dict(current.values)
        wanted.update({'desired.row.001-005.property': 'Config.ConfigurationRecorder.RecordingGroup.IncludeGlobalResourceTypes',
                       'desired.row.001-005.value': 'true', 'desired.row.001-005.comment': 'AWSから取得した設定'})
        output = m.snapshot_sources(path, current, wanted)
        save_files(output)
        derived = load_expansion(path)
        check(derived.provenance['desired.row.001-004.value']['parameters'] == ['Frequency','HasFrequency'],
              'unrelated new row preserves optional selectors and expressions in a derived definition')

def small_framework(root, services, kinds):
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


def check_import_json_transaction():
    import sync_files
    from sync_runtime import generate_views, validate_candidates
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        small_framework(root, ['cloudwatch-logs'], ['Logs.LogGroup'])
        mapping = root / 'framework/mappings/aws/cloudwatch-logs.yaml'
        mapping.write_text(mapping.read_text(encoding='utf-8').replace('DataProtectionPolicy:\n        model: {include: false}\n        display: {show: false, name: DataProtectionPolicy}',
            'DataProtectionPolicy:\n        model: {include: true}\n        display: {show: true, name: DataProtectionPolicy}'), encoding='utf-8')
        path = root / 'model/dev' / ACCOUNT / 'cloudwatch-logs.properties'
        data = values()
        data.update({'desired.row.001-005.property': 'Logs.LogGroup.DataProtectionPolicy',
                     'desired.row.001-005.value': '[Policy](cloudwatch-logs/policy.json)',
                     'desired.row.001-005.document': '{"Statement":[]}', 'desired.row.001-005.comment': 'ログ保護ポリシー'})
        write_model(path, data)
        document = root / 'docs/designs/dev' / ACCOUNT / 'cloudwatch-logs.md'
        artifact = document.with_suffix('') / 'policy.json'
        failures = []; destinations = {document: load_expansion(path).values}
        generated = generate_views(root, root, destinations, failures)
        validate_candidates(root, root, generated, destinations, failures, 1, True)
        check(not failures and artifact.is_file(), 'real generator produces and validates JSON fixture: ' + '; '.join(failures))
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'JSON baseline'], cwd=root, check=True)
        contract(root, [(artifact.parent / 'unowned.json').relative_to(root).as_posix()])
        cli = AwsCli(); cli.logs = []
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}):
            originals = {p: p.read_bytes() for p in [*load_expansion(path).files, document, artifact]}
            original_save = sync_files.save_files
            def fail(output):
                original_save(dict(list(output.items())[:2]))
                raise OSError('injected source and view publication failure')
            with patch.object(sync_files, 'save_files', side_effect=fail):
                try:
                    m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
                except OSError:
                    pass
                else:
                    raise AssertionError('partial publication must fail')
            check(all(p.read_bytes() == content for p, content in originals.items()), 'sources, Markdown and JSON rollback together')
            check(not import_guard.proof_path(root).exists(), 'failed candidate evidence cannot authorize later operations')
            unowned = artifact.with_name('unowned.json'); unowned.write_text('{}', encoding='utf-8')
            def fail_views(output):
                if any('/docs/designs/' in str(p) for p in output):
                    original_save(dict(list(output.items())[:1]))
                    raise OSError('injected view publication failure')
                original_save(output)
            with patch.object(sync_files, 'save_files', side_effect=fail_views):
                failed = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
            check(failed['model'] == 'reflected' and failed['markdown'] == 'failed', 'view failure preserves completed Model')
            check(document.read_bytes() == originals[document] and artifact.read_bytes() == originals[artifact], 'only partial view changes roll back')
            check(len(m.entries(load_model(path).values, 'desired.resource.')) == 1, 'successful empty inventory remains reflected after display failure')
            import_guard.require_import_changes(root)
            check(unowned.read_text(encoding='utf-8') == '{}', 'unowned JSON remains untouched')
            calls = list(cli.calls)
            check(sync_runtime.sync(root, True, 'dev', ACCOUNT, ['cloudwatch-logs']) == 0, 'saved Model recovers display without acquisition')
            check(cli.calls == calls and not artifact.exists() and unowned.read_text() == '{}', 'recovery deletes only previously owned stale JSON without AWS')



import pytest
from support.pytest_cli import run


@pytest.fixture(autouse=True)
def reset_count():
    global COUNT
    COUNT = 0
    yield
    COUNT = 0


def check_input_source_edits():
    from import_sources import parameter_edit
    original = "# keep header\nparameters:\n  Old: 3 # keep sibling\ninstances:\n  fixture:\n    parameters:\n      Days: 30 # days\n      Name: 'unchanged' # keep quotes\n"
    wanted = m.yaml_read(original)
    wanted['instances']['fixture']['parameters']['Days'] = 90
    wanted['instances']['fixture']['parameters']['Enabled'] = True
    result = parameter_edit(original, wanted)
    check('Old: 3 # keep sibling' in result and "Name: 'unchanged' # keep quotes" in result and '# keep header' in result,
          'input edits preserve unrelated spelling, comments and order')
    check(m.yaml_read(result) == wanted and parameter_edit(result, wanted) == result, 'typed input update is lossless and idempotent')
    del wanted['parameters']['Old']
    check(m.yaml_read(parameter_edit(result, wanted)) == wanted, 'empty mapping remains explicit after a targeted removal')


def check_reflection_validation_boundary():
    from contextlib import ExitStack
    import model_templates
    import model_design
    import issues_scan
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        path = fixture(root)
        template = m.service_source(path)[1]
        template.write_text(template.read_text().replace('"description":"保持日数","required":true',
            '"description":"保持日数","required":true,"constraints":{"maximum":30}'))
        text = template.read_text().replace('desired.row.row_002-002.value=`30`', 'desired.row.row_002-002.value=<<CreateDays>>')
        template.write_text(text.replace('# end-definition',
            '# parameter: CreateDays {"type":"integer","description":"CREATE input","required":true}\n'
            '# row: kms resource_001\n'
            'desired.row.kms.property=Logs.LogGroup.KmsKeyId\n'
            'desired.row.kms.value=[old key](kms.md#key)\n'
            'desired.row.kms.comment=KMS reference\n# end-definition'))
        directory = m.service_source(path)[2]
        parameters = directory / 'parameters.yaml'
        parameters.write_text(parameters.read_text() + '      CreateDays: invalid-existing-type\n')
        bindings = json.loads((directory / 'bindings.json').read_text())
        bindings['instances']['fixture']['rows']['kms'] = '001-005'
        (directory / 'bindings.json').write_text(json_text(bindings))
        cli = AwsCli()
        actual = 'arn:aws:kms:ap-northeast-1:' + ACCOUNT + ':key/acquired-key'
        cli.logs[0]['kmsKeyId'] = actual
        issues = root / 'issues/dev' / ACCOUNT / 'issues.md'
        issues.parent.mkdir(parents=True)
        issues.write_text('# Issues\n### cloudwatch-logs\n1. unresolved fixture issue\n')
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'constraints'], cwd=root, check=True)
        plan = m.refresh(root, 'dev', 'cloudwatch-logs', dry_run=True, cli_runner=cli)
        reserve(root, plan)
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/import-fixture.md'}), ExitStack() as stack:
            forbidden = [(model_templates, 'load_expansion'), (model_templates, 'validate_local'),
                         (model_design, 'validate_required_properties'), (sync_runtime, 'validate_candidates'),
                         (import_guard, 'snapshots'), (shutil, 'copytree')]
            mocks = [stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name + ' forbidden')))
                     for owner, name in forbidden]
            result = m.refresh(root, 'dev', 'cloudwatch-logs', cli_runner=cli)
            check(result['model'] == 'reflected' and result['markdown'] == 'generated', 'design constraint does not block acquired values')
            saved = model_templates.load_for_edit(path).values
            check(saved['desired.row.001-005.value'] == '[old key](kms.md#key)' and m.comparator().literal(saved['observed.row.001-005.value']) == actual, 'acquired ARN persists separately from the unchanged logical link')
            check(saved['desired.row.002-002.value'] == 'invalid-existing-type', 'untouched invalid CREATE input remains unchanged')
            check(all(mock.call_count == 0 for mock in mocks), 'runtime import boundary excludes validation and copies')
        errors, _, _ = issues_scan.mechanical(root, {('dev', ACCOUNT, 'cloudwatch-logs')}, fresh=True, jobs=1)
        check(any('maximum' in str(error) for error in errors), 'explicit issues detects retained input constraint violation')


def check_import_worktree_completion():
    import worktree_task
    import task_contract
    lifecycle = load('worktree_task.checks', 'import_worktree_fixture')
    with lifecycle.fixture() as root:
        path = fixture(root)
        document = root / 'docs/designs/dev' / ACCOUNT / 'cloudwatch-logs.md'
        from sync_files import save_files
        save_files(sync_runtime.generate_files(document, load_expansion(path).values, root))
        lifecycle.git(root, 'add', '.')
        lifecycle.git(root, 'commit', '-qm', 'baseline display')
        state = lifecycle.cli(root, 'create', 'import-fixture')
        target = Path(state['worktree'])
        contract(target, [])
        with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': state['task_file']}):
            with patch.object(sync_runtime, 'generate_files', side_effect=ValueError('display fixture failure')):
                result = m.refresh(target, 'dev', 'cloudwatch-logs', cli_runner=AwsCli())
            check(result['model'] == 'reflected' and result['markdown'] == 'failed', 'saved sources survive display failure before integration')
            task_contract.complete(target, state['task_file'])
            with patch.object(import_guard, 'snapshots', side_effect=AssertionError('old Model expansion forbidden')) as baseline:
                completed = worktree_task.finalize(root, 'import-fixture')
            check(completed['cleaned'] and not target.exists() and baseline.call_count == 0, 'real commit, merge and cleanup use source evidence without design validation')
        check(m.comparator().literal(load_model(path).values['desired.row.001-002.value']) == '90', 'integrated sources retain acquired values')


def main():
    return run(__file__, message='import-model CLI checks: PASS')


if __name__ == '__main__':
    raise SystemExit(main())
