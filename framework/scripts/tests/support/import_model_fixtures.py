"""Authored import seeds and Mock CLI only; never read an executing project's Model."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from script_loader import module
from model_templates import json_text, load_for_edit, service_source
from model_parameter_inputs import yaml_read
from import_sources import parameter_edit
from support.model_sources import write_model

m = module('import-model.py', 'import_model_cli')
ACCOUNT = '123456789012'
TARGET = 'cde'
SERVICES = ('vpc', 'config', 'cloudwatch-logs', 'data-firehose', 'quicksight', 'security-hub', 'transit-gateway')
SUBNETS = [
    ('dat-private-1a', '10.10.0.0/25', 'ap-northeast-1a'),
    ('dat-private-1c', '10.10.0.128/25', 'ap-northeast-1c'),
    ('snf-private-1a', '10.10.1.0/26', 'ap-northeast-1a'),
    ('snf-private-1c', '10.10.1.64/26', 'ap-northeast-1c'),
    ('pen-private-1a', '10.10.1.128/26', 'ap-northeast-1a'),
    ('tgw-private-1a', '10.10.1.192/28', 'ap-northeast-1a'),
    ('tgw-private-1c', '10.10.1.208/28', 'ap-northeast-1c'),
]
VPC_ID = 'vpc-00000000000000001'


def check(value, message):
    assert value, message


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
    paths = {p for p in paths if p.parent != Path("framework/rules/aws-resource-naming") or (m.ROOT / p).is_file()}
    for relative in paths:
        destination = root / relative; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(m.ROOT / relative, destination)
    owners = json.loads((m.ROOT / 'framework/mappings/aws/owners.json').read_text(encoding='utf-8'))
    (root / 'framework/mappings/aws/owners.json').write_text(json.dumps({kind: service for kind, service in owners.items()
        if service in services}), encoding='utf-8')
    (root / 'project.json').write_text(json_text({'projectName': 'fixture', 'targets': [{'environment': 'dev',
        'awsAccountId': ACCOUNT, 'awsProfile': 'confirmed', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n', encoding='utf-8')



def spec(kind='string', **extra):
    return {'type': kind, 'description': '合成fixtureの設定', 'required': True, **extra}


def metadata(service, kinds):
    return ['# definition: Metadata', 'desired.service.' + service + '.serviceId=' + service,
            'desired.service.' + service + '.ownedCatalogResourceTypes=' + ','.join(kinds),
            'display.service.title=# ' + service + ' 詳細設計', '# end-definition']


def binding(definition, number, rows, anchor):
    return {'definition': definition, 'resources': {'resource': number},
            'rows': {name: number + '-' + str(index).zfill(3) for index, name in enumerate(rows, 1)},
            'parameters': {'Anchor': anchor}}


def declaration(name, kind, fields, parameters, mode='<<ResourceMode>>'):
    lines = ['# definition: ' + name, '# internal: Anchor string', '# resource: resource']
    lines += ['# parameter: ' + key + ' ' + json_text(value) for key, value in parameters.items()]
    lines += ['# row: ' + local + ' resource' for local in fields]
    lines += ['desired.resource.resource.resourceType=' + kind,
              'desired.resource.resource.anchor=<<Anchor>>',
              'desired.resource.resource.resourceMode=' + mode,
              'display.resource.resource.comment=合成テスト用のリソース']
    for local, (prop, value) in fields.items():
        lines += ['desired.row.' + local + '.property=' + kind + '.' + prop,
                  'desired.row.' + local + '.value=' + value,
                  'desired.row.' + local + '.comment=合成テストの取得設定']
    return lines + ['# end-definition']


def save_service(root, service, template, parameters, bindings, observed=None, environment='dev'):
    import yaml
    entry = root / 'model/templates' / TARGET / (service + '.properties.tpl')
    directory = root / 'model/parameters' / environment / TARGET / service
    entry.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(parents=True, exist_ok=True)
    entry.write_text('\n'.join(template) + '\n', encoding='utf-8')
    (directory / 'parameters.yaml').write_text('# Authored synthetic fixture; never live AWS evidence\n' + yaml.safe_dump(parameters, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding='utf-8')
    (directory / 'bindings.json').write_text(json.dumps(bindings, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if observed:
        (directory / 'observed.json').write_text(json.dumps({'version': 1, 'values': observed}, indent=2) + '\n', encoding='utf-8')


def build_seed(root):
    root.mkdir(exist_ok=True)
    kinds = ['EC2.VPC', 'EC2.Subnet', 'Config.ConfigurationRecorder', 'Logs.LogGroup',
             'KinesisFirehose.DeliveryStream', 'QuickSight.DataSource', 'SecurityHub.Hub', 'EC2.TransitGatewayVpcAttachment']
    small_framework(root, SERVICES, kinds)
    (root / 'project.json').write_text(json_text({'projectName': 'synthetic-import-fixture', 'targets': [
        {'environment': env, 'alias': TARGET, 'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1',
         'awsProfile': 'confirmed', 'iacEngine': 'cloudformation'} for env in ('dev', 'stg')]}), encoding='utf-8')
    empty = {'definition': 'Metadata', 'resources': {}, 'rows': {}, 'parameters': {}}
    vpc_fields = {'id': ('VpcId', '[<<Id_resource>>](#<<Anchor>>)'), 'cidr': ('CidrBlock', '<<CidrBlock>>'),
                  'name': ('Name', '`main-vpc`'), 'hostnames': ('EnableDnsHostnames', '`true`'), 'support': ('EnableDnsSupport', '`true`')}
    subnet_fields = {'id': ('SubnetId', '[<<Id_resource>>](#<<Anchor>>)'), 'vpc': ('VpcId', '[001](#vpc-main)'),
                     'cidr': ('CidrBlock', '<<CidrBlock>>'), 'name': ('Name', '<<SubnetName>>'),
                     'zone': ('AvailabilityZone', '`<<AvailabilityZone1>>`'), 'public': ('MapPublicIpOnLaunch', '`false`')}
    lines = ['# model-template: 1'] + ['# input: ' + name + ' ' + json_text(spec(source='service'))
                                      for name in ('ResourceMode', 'AvailabilityZone1', 'AvailabilityZone2')]
    lines += metadata('vpc', ['EC2.VPC', 'EC2.Subnet'])
    lines += declaration('Vpc', 'EC2.VPC', vpc_fields, {'CidrBlock': spec(format='literal')})
    lines += declaration('SubnetZone1', 'EC2.Subnet', subnet_fields, {'CidrBlock': spec(format='literal'), 'SubnetName': spec(format='literal')})
    lines += declaration('SubnetZone2', 'EC2.Subnet', {k: (p, v.replace('AvailabilityZone1', 'AvailabilityZone2')) for k, (p, v) in subnet_fields.items()},
                         {'CidrBlock': spec(format='literal'), 'SubnetName': spec(format='literal')})
    parameters = {'parameters': {'ResourceMode': 'IMPORT', 'AvailabilityZone1': 'ap-northeast-1a', 'AvailabilityZone2': 'ap-northeast-1c'},
                  'instances': {'main-vpc': {'parameters': {'CidrBlock': '10.10.0.0/23'}}}}
    bindings = {'instances': {'service': empty, 'main-vpc': binding('Vpc', '001', vpc_fields, 'vpc-main')}}
    observed = {'observed.row.001-001.value': VPC_ID}
    for n, (name, cidr, az) in enumerate(SUBNETS, 2):
        number = str(n).zfill(3)
        parameters['instances'][name] = {'parameters': {'CidrBlock': cidr, 'SubnetName': name}}
        bindings['instances'][name] = binding('SubnetZone1' if az.endswith('a') else 'SubnetZone2', number, subnet_fields, 'vpc-' + name)
        observed['observed.row.' + number + '-001.value'] = 'subnet-' + str(n).zfill(17)
        observed['observed.row.' + number + '-002.value'] = VPC_ID
    save_service(root, 'vpc', lines, parameters, bindings, observed)
    stg = copy.deepcopy(parameters)
    stg['parameters']['ResourceMode'] = 'CREATE'
    save_service(root, 'vpc', lines, stg, bindings, environment='stg')

    fields = {'name': ('LogGroupName', '<<LogGroupName>>'), 'days': ('RetentionInDays', '<<RetentionDays>>'),
              'protected': ('DeletionProtectionEnabled', '`false`'), 'class': ('LogGroupClass', '`STANDARD`')}
    lines = ['# model-template: 1'] + metadata('cloudwatch-logs', ['Logs.LogGroup'])
    lines += declaration('LogGroup', 'Logs.LogGroup', fields,
                         {'ResourceMode': spec(), 'LogGroupName': spec(format='literal'), 'RetentionDays': spec('integer')})
    bindings = {'instances': {'service': empty, 'application-log': binding('LogGroup', '001', fields, 'cloudwatch-logs-application'),
                             'create-log': binding('LogGroup', '002', fields, 'cloudwatch-logs-create')}}
    for env in ('dev', 'stg'):
        parameters = {'instances': {'application-log': {'parameters': {'ResourceMode': 'IMPORT' if env == 'dev' else 'CREATE',
                           'LogGroupName': 'fixture-001' if env == 'dev' else 'stg-application', 'RetentionDays': 30}},
                       'create-log': {'parameters': {'ResourceMode': 'CREATE', 'LogGroupName': 'fixture-002', 'RetentionDays': 30}}}}
        save_service(root, 'cloudwatch-logs', lines, parameters, bindings, environment=env)
    basic = {
        'config': ('Config.ConfigurationRecorder', {'Name': 'actual-recorder', 'Id': 'actual-recorder',
                   'RecordingGroup.AllSupported': False, 'RecordingGroup.IncludeGlobalResourceTypes': True,
                   'RecordingGroup.ResourceTypes': ['AWS::EC2::VPC'], 'RecordingGroup.ExclusionByResourceTypes.ResourceTypes': [],
                   'RoleARN': 'AWSServiceRoleForConfig'}),
        'data-firehose': ('KinesisFirehose.DeliveryStream', {'DeliveryStreamName': 'fixture'}),
        'quicksight': ('QuickSight.DataSource', {'DataSourceId': 'actual-source', 'Name': 'actual-source', 'Type': 'ATHENA'}),
        'security-hub': ('SecurityHub.Hub', {'AutoEnableControls': True, 'ControlFindingGenerator': 'SECURITY_CONTROL'}),
        'transit-gateway': ('EC2.TransitGatewayVpcAttachment', {'Id': 'tgw-attach-fixture', 'VpcId': VPC_ID,
                            'TransitGatewayId': 'tgw-fixture', 'SubnetIds': ['subnet-' + str(2).zfill(17)]}),
    }
    for service, (kind, fields) in basic.items():
        values = {'desired.service.' + service + '.serviceId': service,
                  'desired.service.' + service + '.ownedCatalogResourceTypes': kind,
                  'display.service.title': '# ' + service + ' 詳細設計',
                  'desired.resource.001.resourceType': kind, 'desired.resource.001.resourceMode': 'IMPORT',
                  'desired.resource.001.anchor': service + '-fixture', 'display.resource.001.comment': '合成fixture'}
        for i, (prop, value) in enumerate(fields.items(), 1):
            key = 'desired.row.001-' + str(i).zfill(3) + '.'
            values.update({key + 'property': kind + '.' + prop, key + 'value': m.model_literal(value), key + 'comment': '合成fixture'})
        write_model(root / 'model/dev' / TARGET / (service + '.properties'), values)


def fixture(root, service='cloudwatch-logs', register=True):
    from support.it_workspace import populate
    from task_contract import start
    populate('import_sources', root)
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic import seed'], cwd=root, check=True)
    path = root / 'model/dev' / TARGET / (service + '.properties')
    if register:
        sources = {p.relative_to(root).as_posix() for p in load_for_edit(path).files}
        sources |= {f'model/parameters/dev/{TARGET}/{service}/observed.json', f'docs/designs/dev/{TARGET}/{service}.md'}
        paths = sorted(sources | {'tasks/import-fixture.md'})
        text = '\n'.join(['# Import fixture', '## Task contract', '- Task type: `design`', '- Workflow: `import`',
                           '- Task status: `running`', '- IMPORT target: `dev/' + TARGET + '/' + service + '`',
                           '## Goal', 'Apply authored synthetic candidates', '## Required changes', '- [R1] Reflect selected synthetic values',
                           '## Validation scope', '- `dev/' + TARGET + '/' + service + '`',
                           '## Allowed paths', *['- `' + p + '`' for p in paths],
                           '## Modified files', *['- `' + p + '`' for p in paths],
                           '## Acceptance checks', '- [R1] `exists:docs/designs/dev/' + TARGET + '/' + service + '.md`']) + '\n'
        start(root, 'tasks/import-fixture.md', text)
    return path


def aws(service='cloudwatch-logs', *, changed=False, noise=False, profile='confirmed'):
    cli = AwsCli(profile=profile)
    cli.logs = [{'logGroupName': 'fixture-001', 'retentionInDays': 90 if changed else 30, 'deletionProtectionEnabled': False, 'logGroupClass': 'STANDARD'},
                {'logGroupName': 'fixture-002', 'retentionInDays': 99, 'deletionProtectionEnabled': True, 'logGroupClass': 'STANDARD'}]
    cli.logs.append({'logGroupName': 'managed-new', 'retentionInDays': 90, 'deletionProtectionEnabled': False, 'logGroupClass': 'STANDARD'})
    vpcs = [{'VpcId': VPC_ID, 'CidrBlock': '10.11.0.0/23' if changed else '10.10.0.0/23', 'Tags': [{'Key': 'Name', 'Value': 'main-vpc'}]}]
    subnets = [{'SubnetId': 'subnet-' + str(n).zfill(17), 'VpcId': VPC_ID, 'CidrBlock': cidr, 'AvailabilityZone': az,
                'MapPublicIpOnLaunch': False, 'Tags': [{'Key': 'Name', 'Value': name}]} for n, (name, cidr, az) in enumerate(SUBNETS, 2)]
    if noise:
        vpcs.insert(0, {'VpcId': 'vpc-00000000000000000', 'CidrBlock': '172.16.0.0/16', 'Tags': [{'Key': 'Name', 'Value': 'unmanaged'}]})
        subnets += [{'SubnetId': 'subnet-unmanaged', 'VpcId': 'vpc-00000000000000000', 'CidrBlock': SUBNETS[0][1], 'AvailabilityZone': SUBNETS[0][2],
                     'Tags': [{'Key': 'Name', 'Value': SUBNETS[0][0]}], 'MapPublicIpOnLaunch': False}]
    cli.responses.update({
        ('ec2', 'describe-vpcs'): {'Vpcs': vpcs}, ('ec2', 'describe-subnets'): {'Subnets': subnets},
        ('firehose', 'list-delivery-streams'): {'DeliveryStreamNames': ['fixture']},
        ('firehose', 'describe-delivery-stream'): {'DeliveryStreamDescription': {'DeliveryStreamName': 'fixture', 'DeliveryStreamType': 'DirectPut', 'Destinations': []}},
        ('securityhub', 'describe-hub'): {'HubArn': 'arn:aws:securityhub:ap-northeast-1:' + ACCOUNT + ':hub/default', 'AutoEnableControls': True, 'ControlFindingGenerator': 'SECURITY_CONTROL'},
        ('ec2', 'describe-transit-gateway-vpc-attachments'): {'TransitGatewayVpcAttachments': [{'TransitGatewayAttachmentId': 'tgw-attach-fixture', 'VpcId': VPC_ID,
              'TransitGatewayId': 'tgw-fixture', 'SubnetIds': ['subnet-' + str(2).zfill(17)]}]},
    })
    return cli


def stage(acquisition, files, resources=(), excluded=(), pending=()):
    destination = Path(acquisition['candidates'])
    for relative, text in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    Path(acquisition['selection']).write_text(json_text({'resources': list(resources), 'excluded': list(excluded), 'unreflected': list(pending)}), encoding='utf-8')


def correspondence(acquisition, identity, resource='003', action='add', basis=()):
    record = next(r for r in acquisition['records'] if r['identity'] == identity)
    return {'record': record['record'], 'resource': resource, 'action': action,
            'reason': 'Synthetic project membership explicitly supplied by the test', 'basis': list(basis)}


def exclusions(acquisition, selected):
    return [{'record': r['record'], 'reason': 'Synthetic fixture marks this resource as outside management'}
            for r in acquisition['records'] if r['record'] not in {item['record'] for item in selected}]


def logs_edit(root, acquisition, days=90):
    path = root / 'model/parameters/dev' / TARGET / 'cloudwatch-logs/parameters.yaml'
    original = path.read_text(encoding='utf-8')
    params = yaml_read(original)
    params['instances']['managed-log'] = {'parameters': {'ResourceMode': 'IMPORT', 'LogGroupName': 'managed-new', 'RetentionDays': days}}
    bindings_file = path.with_name('bindings.json')
    bindings = json.loads(bindings_file.read_text(encoding='utf-8'))
    seed = bindings['instances']['application-log']
    bindings['instances']['managed-log'] = {**copy.deepcopy(seed), 'resources': {'resource': '003'},
        'rows': {local: number.replace('001-', '003-') for local, number in seed['rows'].items()}, 'parameters': {'Anchor': 'cloudwatch-logs-managed'}}
    files = {path.relative_to(root).as_posix(): parameter_edit(original, params),
             bindings_file.relative_to(root).as_posix(): json.dumps(bindings, indent=2) + '\n'}
    selected = [correspondence(acquisition, 'managed-new')]
    stage(acquisition, files, selected, exclusions(acquisition, selected))
    return files


def publish_fixture(root, acquisition, service='cloudwatch-logs', dry_run=False):
    return m.publish_acquisition(root, 'dev', service, acquisition['evidence'], TARGET, dry_run)


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}


def operation_fixture(root):
    from support.import_model_fixtures import metadata, declaration, binding, save_service, spec
    fields = {'id': ('VpcId', '[<<Id_resource>>](#<<Anchor>>)'),
              'cidr': ('CidrBlock', '<<CidrBlock>>'), 'dns': ('EnableDnsSupport', '`false`')}
    incoming = {'dns': ('EnableDnsSupport', '`true`'), 'cidr': fields['cidr'], 'id': fields['id']}
    params = {'CidrBlock': spec(format='literal'), 'ResourceMode': spec()}
    template = ['# model-template: 1'] + metadata('vpc', ['EC2.VPC'])
    template += declaration('Vpc', 'EC2.VPC', fields, params)
    template += declaration('ImportedVpc', 'EC2.VPC', incoming, params)
    empty = {'definition': 'Metadata', 'resources': {}, 'rows': {}, 'parameters': {}}
    for env in ('dev', 'stg'):
        parameters = {'instances': {'main-vpc': {'parameters': {'CidrBlock': '10.1.0.0/16', 'ResourceMode': 'CREATE' if env == 'dev' else 'IMPORT'}}}}
        bindings = {'instances': {'service': empty, 'main-vpc': binding('Vpc', '001', fields, 'vpc-main')}}
        observed = {'observed.row.001-001.value': 'vpc-' + env}
        if env == 'stg':
            parameters['instances']['imported-vpc'] = {'parameters': {'CidrBlock': '10.9.0.0/16', 'ResourceMode': 'IMPORT'}}
            bindings['instances']['imported-vpc'] = binding('ImportedVpc', '009', incoming, 'vpc-imported')
            observed['observed.row.009-003.value'] = 'vpc-source'
        save_service(root, 'vpc', template, parameters, bindings, observed, environment=env)
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': env, 'alias': 'cde', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'} for env in ('dev', 'stg')]}))


def operation_candidate(before, after, action='import-merge'):
    import shutil
    from support.import_model_fixtures import spec
    from model_templates import json_text
    shutil.copytree(before, after)
    directory = after / 'model/parameters/stg/cde/vpc'
    params_file, bindings_file, observed_file = [directory / name for name in ('parameters.yaml', 'bindings.json', 'observed.json')]
    parameters = yaml_read(params_file.read_text())
    bindings, observed = [json.loads(file.read_text()) for file in (bindings_file, observed_file)]
    del parameters['instances']['imported-vpc']
    del bindings['instances']['imported-vpc']
    observed['values'].pop('observed.row.009-003.value')
    if action == 'import-merge':
        parameters['instances']['main-vpc']['parameters'].update(CidrBlock='10.9.0.0/16', DnsSupport=True)
        observed['values']['observed.row.001-001.value'] = 'vpc-source'
        template = after / 'model/templates/cde/vpc.properties.tpl'
        text = template.read_text().replace('# definition: Vpc\n', '# definition: Vpc\n# parameter: DnsSupport ' + json_text(spec('boolean', format='literal')) + '\n')
        text = text.replace('desired.row.dns.value=`false`', 'desired.row.dns.value=<<DnsSupport>>')
        template.write_text(text)
        foreign = after / 'model/parameters/dev/cde/vpc/parameters.yaml'
        inputs = yaml_read(foreign.read_text())
        inputs['instances']['main-vpc']['parameters']['DnsSupport'] = False
        foreign.write_text(parameter_edit(foreign.read_text(), inputs))
    params_file.write_text(parameter_edit(params_file.read_text(), parameters))
    bindings_file.write_text(json.dumps(bindings))
    observed_file.write_text(json.dumps(observed))
    return {p.relative_to(after).as_posix() for p in after.rglob('*') if p.is_file() and p.read_bytes() != (before / p.relative_to(after)).read_bytes()}


def operation_contract(action='import-merge', source='stg/cde/vpc/009', destination='stg/cde/vpc/001'):
    return ('## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `update`\n'
            '- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n'
            '- Model operation: `' + action + '`\n- Source resource: `' + source + '`\n'
            + ('- Destination resource: `' + destination + '`\n' if action == 'import-merge' else ''))
