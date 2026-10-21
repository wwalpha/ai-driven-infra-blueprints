"""Authored import seeds and Mock CLI only; never read an executing project's Model."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from model.sources import json_text, load_model
from yaml_values import yaml_read
from support.model_sources import write_model

from model.importing import cli as m
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
    kinds = set(kinds) | {kind for service in services for kind in yaml_read((m.ROOT / 'framework/mappings/aws' / (service + '.yaml')).read_text(encoding='utf-8'))['resourceTypes']}
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



def service_values(service, kinds):
    return {'desired.service.' + service + '.serviceId': service,
            'desired.service.' + service + '.ownedCatalogResourceTypes': ','.join(kinds),
            'display.service.title': '# ' + service + ' 詳細設計'}


def resource_values(rid, kind, anchor, mode, rows):
    values = {f'desired.resource.{rid}.resourceType': kind, f'desired.resource.{rid}.resourceMode': mode,
              f'desired.resource.{rid}.anchor': anchor, f'desired.resource.{rid}.logicalId': anchor,
              f'display.resource.{rid}.comment': '合成テスト用のリソース'}
    for index, (prop, raw) in enumerate(rows, 1):
        prefix = f'desired.row.{rid}-{index:03d}.'
        values.update({prefix + 'property': kind + '.' + prop, prefix + 'value': raw,
                       prefix + 'comment': '合成テストの取得設定'})
    return values


def build_seed(root):
    root.mkdir(exist_ok=True)
    kinds = ['EC2.VPC', 'EC2.Subnet', 'Config.ConfigurationRecorder', 'Logs.LogGroup',
             'KinesisFirehose.DeliveryStream', 'QuickSight.DataSource', 'SecurityHub.Hub', 'EC2.TransitGatewayVpcAttachment']
    small_framework(root, SERVICES, kinds)
    # Install the selected catalog before any reader can cache it.
    import yaml
    mapping_path = root / 'framework/mappings/aws/cloudwatch-logs.yaml'
    mapping = yaml_read(mapping_path.read_text(encoding='utf-8'))
    mapping['resourceTypes'] = {'Logs.LogGroup': mapping['resourceTypes']['Logs.LogGroup']}
    mapping_path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding='utf-8')
    owners_path = root / 'framework/mappings/aws/owners.json'
    owners = json.loads(owners_path.read_text(encoding='utf-8'))
    owners_path.write_text(json_text({kind: owner for kind, owner in owners.items()
        if owner != 'cloudwatch-logs' or kind == 'Logs.LogGroup'}), encoding='utf-8')
    (root / 'project.json').write_text(json_text({'projectName': 'synthetic-import-fixture', 'targets': [
        {'environment': env, 'alias': TARGET, 'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1',
         'awsProfile': 'confirmed', 'iacEngine': 'cloudformation'} for env in ('dev', 'stg')]}), encoding='utf-8')
    for env in ('dev', 'stg'):
        mode = 'IMPORT' if env == 'dev' else 'CREATE'
        values = service_values('vpc', ['EC2.VPC', 'EC2.Subnet'])
        values.update(resource_values('001', 'EC2.VPC', 'vpc-main', mode, [
            ('VpcId', '[001](#vpc-main)'), ('CidrBlock', '`10.10.0.0/23`'), ('Name', '`main-vpc`'),
            ('EnableDnsHostnames', '`true`'), ('EnableDnsSupport', '`true`')]))
        if env == 'dev':
            values['observed.row.001-001.value'] = VPC_ID
        for n, (name, cidr, zone) in enumerate(SUBNETS, 2):
            rid = f'{n:03d}'
            values.update(resource_values(rid, 'EC2.Subnet', 'vpc-' + name, mode, [
                ('SubnetId', f'[{rid}](#vpc-{name})'), ('VpcId', '[001](#vpc-main)'),
                ('CidrBlock', m.model_literal(cidr)), ('Name', m.model_literal(name)),
                ('AvailabilityZone', m.model_literal(zone)), ('MapPublicIpOnLaunch', '`false`')]))
            if env == 'dev':
                values[f'observed.row.{rid}-001.value'] = 'subnet-' + str(n).zfill(17)
                values[f'observed.row.{rid}-002.value'] = VPC_ID
        write_model(root / 'model' / env / TARGET / 'vpc.properties', values)
        logs = service_values('cloudwatch-logs', ['Logs.LogGroup'])
        for rid, name, logmode, anchor in [('001', 'fixture-001' if env == 'dev' else 'stg-application', mode, 'application'),
                                          ('002', 'fixture-002', 'CREATE', 'create')]:
            logs.update(resource_values(rid, 'Logs.LogGroup', 'cloudwatch-logs-' + anchor, logmode, [
                ('LogGroupName', m.model_literal(name)), ('RetentionInDays', '`30`'),
                ('DeletionProtectionEnabled', '`false`'), ('LogGroupClass', '`STANDARD`')]))
        write_model(root / 'model' / env / TARGET / 'cloudwatch-logs.properties', logs)
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
                  'desired.resource.001.anchor': service + '-fixture', 'desired.resource.001.logicalId': service + '-fixed', 'display.resource.001.comment': '合成fixture'}
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
        sources = {p.relative_to(root).as_posix() for p in load_model(path).files}
        sources |= {f'docs/designs/dev/{TARGET}/{service}.md'}
        paths = sorted(sources | {'tasks/import-fixture.md'})
        text = '\n'.join(['# Import fixture', '## Task contract', '- Task type: `design`', '- Workflow: `import`',
                           '- Task status: `running`', '- IMPORT target: `dev/' + TARGET + '/' + service + '`',
                           '## Goal', 'Apply authored synthetic candidates', '## Required changes', '- [R1] Reflect selected synthetic values',
                           '## Validation scope', '- `dev/' + TARGET + '/' + service + '`', '- `stg/' + TARGET + '/' + service + '`',
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


def stage(root, acquisition, files, resources=(), excluded=(), pending=()):
    """Build a complete external properties candidate, including explicit no-op candidates."""
    destination = Path(acquisition['candidates'])
    scope = acquisition['scope']
    entry = root / 'model' / scope[0] / scope[1] / (scope[2] + '.properties')
    files = dict(files)
    if entry.relative_to(root).as_posix() not in files:
        if entry.is_file():
            files = {**{file.relative_to(root).as_posix(): text for file, text in load_model(entry).files.items()}, **files}
        else:
            from model.format import serialize
            files[entry.relative_to(root).as_posix()] = serialize({})
    for relative, text in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    Path(acquisition['selection']).write_text(json_text({'resources': list(resources), 'excluded': list(excluded), 'unreflected': list(pending)}) + '\n', encoding='utf-8')


def correspondence(acquisition, identity, resource='003', action='add', basis=()):
    record = next(r for r in acquisition['records'] if r['identity'] == identity)
    return {'record': record['record'], 'resource': resource, 'action': action,
            'reason': 'Synthetic project membership explicitly supplied by the test', 'basis': list(basis)}


def exclusions(acquisition, selected):
    return [{'record': r['record'], 'reason': 'Synthetic fixture marks this resource as outside management'}
            for r in acquisition['records'] if r['record'] not in {item['record'] for item in selected}]


def logs_edit(root, acquisition, days=90):
    from model.format import serialize
    path = root / 'model/dev' / TARGET / 'cloudwatch-logs.properties'
    values = dict(load_model(path).authoritative)
    values.update(resource_values('003', 'Logs.LogGroup', 'cloudwatch-logs-managed', 'IMPORT', [
        ('LogGroupName', '`managed-new`'), ('RetentionInDays', '`' + str(days) + '`'),
        ('DeletionProtectionEnabled', '`false`'), ('LogGroupClass', '`STANDARD`')]))
    files = {path.relative_to(root).as_posix(): serialize(values)}
    selected = [correspondence(acquisition, 'managed-new')]
    stage(root, acquisition, files, selected, exclusions(acquisition, selected))
    return files


def review_proof_fixture(root, proof):
    """Authored integrity proof for guard-only tests, never Human authentication."""
    from datetime import datetime, timedelta
    from import_guard import digest
    proof['acquisition'] = digest(proof['acquisition'])
    binding = {name: digest(name) for name in ('sourceBaselineDigest', 'reviewDigest', 'recordsDigest',
               'selectionDigest', 'referencesDigest', 'proposedValuesDigest', 'impactDigest')}
    from model.importing.evidence import FORMAT_FIELDS
    binding.update(version=2, **FORMAT_FIELDS, task=proof['task'], worktree=str(root.resolve()), scope=proof['scope'],
                   acquisitionDigest=proof['acquisition'], acquiredAt=proof['acquiredAt'],
                   expiresAt=(datetime.fromisoformat(proof['acquiredAt']) + timedelta(days=7)).isoformat())
    proof.update(version=6, **FORMAT_FIELDS, reviewBinding=binding, reviewBindingDigest=digest(binding))


def review_fixture(root, acquisition, service='cloudwatch-logs', dry_run=False):
    from model.importing.approval import reference_provenance
    from model.sources import candidate_sources, FileReads
    evidence = Path(acquisition['evidence'])
    env, target, actual_service = acquisition['scope']
    path = root / 'model' / env / target / (actual_service + '.properties')
    before = m.before_model(path, FileReads())
    _, after = candidate_sources(root, evidence.parent / 'candidates', before)
    (evidence.parent / 'review-input.json').write_text(json_text({
        'referenceProvenance': reference_provenance(after),
        'risks': {record['record']: [] for record in acquisition['records']}}), encoding='utf-8')
    return m.review_acquisition(root, env, actual_service, evidence, target, dry_run)


def publish_fixture(root, acquisition, service='cloudwatch-logs', dry_run=False):
    review_fixture(root, acquisition, service, dry_run)
    env, target, actual_service = acquisition['scope']
    return m.publish_acquisition(root, env, actual_service, acquisition['evidence'], target, dry_run)


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}


def operation_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': env, 'alias': TARGET, 'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1',
         'iacEngine': 'cloudformation'} for env in ('dev', 'stg')]}))
    for env in ('dev', 'stg'):
        values = service_values('vpc', ['EC2.VPC'])
        values.update(resource_values('001', 'EC2.VPC', 'vpc-main', 'CREATE' if env == 'dev' else 'IMPORT', [
            ('VpcId', '[001](#vpc-main)'), ('CidrBlock', '`10.1.0.0/16`'), ('EnableDnsSupport', '`false`')]))
        values['observed.row.001-001.value'] = 'vpc-' + env
        if env == 'stg':
            values.update(resource_values('009', 'EC2.VPC', 'vpc-imported', 'IMPORT', [
                ('EnableDnsSupport', '`true`'), ('CidrBlock', '`10.9.0.0/16`'), ('VpcId', '[009](#vpc-imported)')]))
            values['observed.row.009-003.value'] = 'vpc-source'
        write_model(root / 'model' / env / TARGET / 'vpc.properties', values)


def operation_candidate(before, after, action='import-merge'):
    from model.format import owner
    from model.operations import operation_rows
    shutil.copytree(before, after)
    path = after / 'model/stg/cde/vpc.properties'
    values = dict(load_model(path).authoritative)
    if action == 'import-merge':
        destination = operation_rows(values, '001')
        for prop, (rid, row) in operation_rows(values, '009').items():
            target_row = destination[prop][0] if prop in destination else '001-' + rid.split('-', 1)[1]
            for field, raw in row.items():
                if field != 'comment' or prop not in destination:
                    values[f'desired.row.{target_row}.{field}'] = raw.replace('#vpc-imported)', '#vpc-main)').replace('[009]', '[001]')
            old_observed, new_observed = f'observed.row.{rid}.value', f'observed.row.{target_row}.value'
            if old_observed in values:
                values[new_observed] = values[old_observed]
            else:
                values.pop(new_observed, None)
    values = {key: value for key, value in values.items() if owner(key, values) != ('resource', '009')}
    write_model(path, values)
    return {p.relative_to(after).as_posix() for p in after.rglob('*') if p.is_file() and
            (not (before / p.relative_to(after)).is_file() or p.read_bytes() != (before / p.relative_to(after)).read_bytes())}


def operation_contract(action='import-merge', source='stg/cde/vpc/009', destination='stg/cde/vpc/001'):
    return ('## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `update`\n'
            '- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n'
            '- Model operation: `' + action + '`\n- Source resource: `' + source + '`\n'
            + ('- Destination resource: `' + destination + '`\n' if action == 'import-merge' else ''))


class CloudControlCli:
    """Synthetic paginated provider with separately counted physical CLI requests."""
    def __init__(self, resources, *, account=ACCOUNT, fail=None):
        from threading import Lock
        self.resources, self.account, self.fail = resources, account, fail or {}
        self.calls, self.lock = [], Lock()

    def __call__(self, command, **kwargs):
        service, operation = command[1:3]
        inputs = json.loads(command[command.index('--cli-input-json') + 1])
        with self.lock:
            self.calls.append((service, operation, inputs))
        failure = self.fail.get((service, operation, inputs.get('Identifier')))
        if failure:
            return subprocess.CompletedProcess(command, 1, '', 'An error occurred (' + failure + ') when calling fixture: denied')
        if service == 'sts':
            response = {'Account': self.account}
        elif service == 'cloudcontrol':
            kind = inputs['TypeName'].removeprefix('AWS::').replace('::', '.', 1)
            records = self.resources.get(kind, [])
            if operation == 'list-resources':
                filters = json.loads(inputs.get('ResourceModel', '{}'))
                records = [item for item in records if all(item['properties'].get(k) == v for k, v in filters.items())]
                offset = int(inputs.get('NextToken', '0'))
                selected = records[offset:offset+1]
                response = {'ResourceDescriptions': [{'Identifier': item['identifier'], 'Properties': json.dumps(item.get('list', {}))} for item in selected]}
                if offset + 1 < len(records):
                    response['NextToken'] = str(offset + 1)
            elif operation == 'get-resource':
                item = next(item for item in records if item['identifier'] == inputs['Identifier'])
                response = {'ResourceDescription': {'Identifier': item['identifier'], 'Properties': json.dumps(item['properties'])}}
            else:
                raise AssertionError('unmocked Cloud Control operation')
        elif service == 'cloudtrail':
            if operation == 'get-trail':
                response = {'Trail': {'Name': 'audit', 'CloudWatchLogsLogGroupArn': 'arn:aws:logs:ap-northeast-1:' + ACCOUNT + ':log-group:audit',
                            'CloudWatchLogsRoleArn': 'arn:aws:iam::' + ACCOUNT + ':role/audit', 'LogFileValidationEnabled': True,
                            'IncludeGlobalServiceEvents': True, 'IsMultiRegionTrail': True, 'KmsKeyId': 'key-confirmed', 'S3BucketName': 'audit-bucket'}}
            elif operation == 'get-trail-status':
                response = {'IsLogging': True}
            elif operation == 'get-event-selectors':
                response = {'EventSelectors': [{'DataResources': [{'Type': 'AWS::S3::Object', 'Values': ['arn:aws:s3:::audit-bucket/']}],
                            'IncludeManagementEvents': True, 'ReadWriteType': 'All'}]}
            else:
                raise AssertionError('unmocked Trail operation')
        else:
            raise AssertionError('unmocked AWS call: ' + service + '.' + operation)
        return subprocess.CompletedProcess(command, 0, json.dumps(response), '')


def batch_operation_fixture(before, after):
    """Five independent fixed pairs, with Row IDs transferred by formal Property."""
    from model.format import owner
    operation_fixture(before)
    pairs = [('022', '009'), ('023', '010'), ('024', '011'), ('025', '012'), ('028', '013')]
    path = before / 'model/stg/cde/vpc.properties'
    original = dict(load_model(path).authoritative)
    expanded = {key: value for key, value in original.items() if owner(key, original)[0] != 'resource'}
    for source, destination in pairs:
        for old_id, new_id in [('001', destination), ('009', source)]:
            for key, value in original.items():
                if owner(key, original) != ('resource', old_id):
                    continue
                new_key = key.replace('.' + old_id + '.', '.' + new_id + '.').replace('.' + old_id + '-', '.' + new_id + '-')
                raw = value.replace('[' + old_id + ']', '[' + new_id + ']')
                raw = raw.replace('#vpc-main)', '#vpc-main-' + destination + ')').replace('#vpc-imported)', '#vpc-imported-' + source + ')')
                if key.endswith(('.anchor', '.logicalId')):
                    raw += '-' + new_id
                expanded[new_key] = raw
    write_model(path, expanded)
    shutil.copytree(before, after)
    changed = dict(expanded)
    from model.operations import operation_rows
    for source, destination in pairs:
        target_rows = operation_rows(expanded, destination)
        for prop, (row_id, row) in operation_rows(expanded, source).items():
            target_id = target_rows[prop][0]
            for field, raw in row.items():
                if field != 'comment':
                    changed[f'desired.row.{target_id}.{field}'] = raw.replace(
                        '#vpc-imported-' + source + ')', '#vpc-main-' + destination + ')').replace('[' + source + ']', '[' + destination + ']')
            observed = f'observed.row.{row_id}.value'
            if observed in expanded:
                changed[f'observed.row.{target_id}.value'] = expanded[observed]
        changed = {key: value for key, value in changed.items() if owner(key, changed) != ('resource', source)}
    write_model(after / 'model/stg/cde/vpc.properties', changed)
    contract = operation_contract().split('- Source resource:')[0] + '## Model merge pairs\n' + ''.join(
        '- ' + json.dumps({'source': 'stg/cde/vpc/' + source, 'destination': 'stg/cde/vpc/' + destination}) + '\n'
        for source, destination in pairs)
    return contract, {'model/stg/cde/vpc.properties'}


def reference_fields(identity, key, text, producer, *, kind='ServiceA.Resource', mode='name', prop='ServiceA.Resource.Name', pointer=None):
    scope, rid = producer.rsplit('/', 1)
    fields = {'consumerKey': key, 'text': text, 'occurrence': '1', 'producerKind': 'resource',
              'producerScope': scope, 'producerId': rid, 'resourceType': kind, 'format': mode,
              'labelPolicy': 'resource-id' if mode == 'link' else 'none'}
    if mode != 'link':
        fields['property'] = prop
    if pointer is not None:
        fields['pointer'] = pointer
    return {'desired.reference.' + identity + '.' + field: value for field, value in fields.items()}


def dependency_fixture(root):
    """Explicit cyclic links plus an independent same-name fixed producer."""
    root.mkdir(exist_ok=True, parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': env, 'alias': TARGET, 'awsAccountId': ACCOUNT, 'awsRegion': 'ap-northeast-1',
         'iacEngine': 'cloudformation'} for env in ('dev', 'stg')]}))
    for env in ('dev', 'stg'):
        name = 'same-name-' + env
        a = service_values('service-a', ['ServiceA.Resource'])
        a.update(resource_values('001', 'ServiceA.Resource', 'producer', 'IMPORT', [
            ('Name', name), ('Peer', '[002](service-b.md#consumer)')]))
        a.update(resource_values('003', 'ServiceA.Resource', 'other-producer', 'IMPORT', [('Name', name)]))
        b = service_values('service-b', ['ServiceB.Resource'])
        b.update(resource_values('002', 'ServiceB.Resource', 'consumer', 'IMPORT', [('Name', name)]))
        b.update(reference_fields('origin', 'desired.row.002-001.value', name, env + '/cde/service-a/001'))
        write_model(root / 'model' / env / TARGET / 'service-a.properties', a)
        write_model(root / 'model' / env / TARGET / 'service-b.properties', b)


def dependency_refactor(before, after):
    """Detach only the explicitly selected meaning; keep saved values byte-for-byte."""
    shutil.copytree(before, after)
    file = after / 'model/stg/cde/service-b.properties'
    values = {key: value for key, value in load_model(file).authoritative.items()
              if not key.startswith('desired.reference.origin.')}
    write_model(file, values)
    return {file.relative_to(after).as_posix()}


def dependency_contract():
    return ('## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `update`\n'
            '- Model refactor: `value-preserving`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n'
            '## Model dependency detach\n- ' + json.dumps({'consumer': 'stg/cde/service-b/002',
            'producer': 'stg/cde/service-a/001', 'key': 'desired.row.002-001.value'}) + '\n')
