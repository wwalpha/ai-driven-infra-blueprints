#!/usr/bin/env python3
"""Standalone audit generation and execution checks; no AWS/network access."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

import ast
from contextlib import redirect_stdout
import copy
from datetime import datetime, timezone
import io
import json
import os
import socket
import subprocess
import tempfile
from unittest.mock import patch

from script_loader import module
from support.model_sources import write_model
from validation_cache import input_scope

ROOT = Path(__file__).resolve().parents[4]
generator = module('model/audit.py', 'model.audit')


def snapshot(source):
    node = ast.parse(source).body[1]
    assert isinstance(node, ast.Assign) and node.targets[0].id == 'SNAPSHOT'
    return json.loads(ast.literal_eval(node.value.args[0]))


def fixture(base, service, resources):
    data = copy.deepcopy(base)
    data['service'] = service
    data['target'] = {'environment': 'dev', 'directory': 'cde', 'awsAccountId': '111111111111',
                      'awsExecutionAccountId': '123456789012', 'awsRegion': 'ap-northeast-1'}
    values = {}
    for number, kind, anchor, rows in resources:
        for key, value in {'resourceType': kind, 'anchor': anchor, 'logicalId': anchor}.items():
            values[f'desired.resource.{number}.{key}'] = value
        for index, (prop, value, document) in enumerate(rows, 1):
            prefix = f'desired.row.{number}-{index:03d}.'
            values.update({prefix + 'property': kind + '.' + prop, prefix + 'value': value, prefix + 'comment': 'fixture'})
            if document is not None:
                values[prefix + 'document'] = json.dumps(document)
    data['models'] = {'dev/cde/' + service: values}
    return data


POLICY = {'Version': '2012-10-17', 'Statement': [
    {'Effect': 'Allow', 'Action': ['s3:GetObject', 's3:ListBucket'], 'Resource': ['arn:aws:s3:::a', 'arn:aws:s3:::a/*'],
     'Condition': {'StringEquals': {'aws:PrincipalOrgID': ['o-a', 'o-b']}}},
    {'Effect': 'Deny', 'Action': 's3:DeleteObject', 'Resource': '*'}]}


def runtime(data):
    namespace = {'__name__': 'audit_fixture', '__file__': '/offline/tests/dev/cde/vpc.py', 'SNAPSHOT': data}
    exec(compile((ROOT / 'framework/scripts/model/audit_runtime.py').read_text(encoding='utf-8'), '<runtime>', 'exec'), namespace)
    return namespace


class CLI:
    def __init__(self, responses, account='123456789012', fail=None):
        self.responses, self.account, self.fail, self.calls = responses, account, fail, []

    def __call__(self, command, **kwargs):
        assert command[0] == 'aws'
        api = tuple(command[1:3])
        inputs = json.loads(command[command.index('--cli-input-json') + 1])
        self.calls.append((api, inputs, command))
        assert '--region' in command and command[command.index('--region') + 1] == 'ap-northeast-1'
        if api == ('sts', 'get-caller-identity'):
            value = {'Account': self.account, 'Arn': 'arn:aws:iam::' + self.account + ':user/offline'}
        elif api == self.fail:
            return subprocess.CompletedProcess(command, 1, '', 'An error occurred (AccessDenied) when calling Mock: secret-not-for-output')
        else:
            assert api in self.responses, api
            value = self.responses[api]
            value = value(inputs) if callable(value) else value
        return subprocess.CompletedProcess(command, 0, json.dumps(value), '')


@it_case
@input_scope
def check():
    # Generation uses authored authorities; the framework checkout has no consumer data.
    real_run = subprocess.run
    def offline_run(command, **kwargs):
        assert command[0] == 'git', 'generation launched an external process: ' + command[0]
        return real_run(command, **kwargs)
    with tempfile.TemporaryDirectory(prefix='audit-generation-') as directory, \
         patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')), \
         patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')), \
         patch.object(subprocess, 'run', side_effect=offline_run):
        root = Path(directory).resolve()
        (root/'project.json').write_text(json.dumps({'projectName':'fixture','targets':[
            {'environment':'dev','alias':alias,'awsAccountId':account,'awsRegion':'ap-northeast-1','iacEngine':'cloudformation'}
            for alias,account in [('cde','123456789012'),('other','210987654321')]]}),encoding='utf-8')
        iam = fixture({}, 'iam', [
            ('001','IAM.Role','role',[('RoleName','`fixture-role`',None),('AssumeRolePolicyDocument','[trust](iam/trust.json)',POLICY),
                ('Policies[].PolicyName','`inline`',None),('Policies[].PolicyDocument','[inline](iam/inline.json)',POLICY),
                ('ManagedPolicyArns','`[]`',None),('PermissionsBoundary','`arn:aws:iam::123456789012:policy/boundary`',None)]),
            ('002','IAM.ManagedPolicy','managed',[('ManagedPolicyName','`managed`',None),('PolicyDocument','[managed](iam/managed.json)',POLICY)])])
        vpc = fixture({}, 'vpc', [
            ('001','EC2.VPC','main-vpc',[('Name','`fixture-vpc`',None),('CidrBlock','`10.10.0.0/23`',None),('EnableDnsSupport','`true`',None),('VpcId','`vpc-fixture`',None)]),
            ('002','EC2.Subnet','subnet',[('Name','`fixture-subnet`',None),('VpcId','[main](#main-vpc)',None)]),
            ('003','EC2.FlowLog','flowlog',[('DeliverLogsPermissionArn','[role](iam.md#role)',None)])])
        for service, data in [('vpc',vpc),('iam',iam)]:
            write_model(root/'model/dev/cde'/(service+'.properties'),data['models']['dev/cde/' + service])
        sources = {service: generator.generate(root, 'dev', 'cde', service)[0] for service in ('vpc', 'iam')}
        for service, source in sources.items():
            assert generator.generate(root, 'dev', 'cde', service)[0] == source
            compile(source, service + '.py', 'exec')
        # Same account, duplicate Alias/service names and another environment stay distinct.
        crossroot = root / 'cross-synthetic'
        crossroot.mkdir()
        project = json.loads((root / 'project.json').read_text())
        project['targets'][1]['awsAccountId'] = '123456789012'
        project['targets'].append({**project['targets'][0], 'environment': 'prod'})
        (crossroot / 'project.json').write_text(json.dumps(project), encoding='utf-8')
        write_model(crossroot / 'model/dev/cde/iam.properties', iam['models']['dev/cde/iam'])
        for env, alias in [('dev', 'other'), ('prod', 'cde')]:
            write_model(crossroot / 'model' / env / alias / 'vpc.properties', vpc['models']['dev/cde/vpc'])
            gateway = fixture({}, 'ec2', [('001', 'EC2.TransitGateway', 'gateway', [('TransitGatewayId', '`tgw-fixture`', None)])])
            write_model(crossroot / 'model' / env / alias / 'ec2.properties', gateway['models']['dev/cde/ec2'])
        cross_values = dict(vpc['models']['dev/cde/vpc'])
        cross_values['desired.row.002-002.value'] = '[other](../other/vpc.md#main-vpc)'
        cross_values.update({'desired.row.002-003.property': 'EC2.Subnet.Tags',
            'desired.row.002-003.value': '`["[prod](../../prod/cde/vpc.md#main-vpc)"]`',
            'desired.row.002-003.comment': 'cross environment',
            'desired.row.002-004.property': 'EC2.Subnet.Tags',
            'desired.row.002-004.value': '`["[missing](../other/missing.md#missing)"]`',
            'desired.row.002-004.comment': 'missing producer',
            'desired.row.002-005.property': 'EC2.Subnet.Tags',
            'desired.row.002-005.value': '`["[gateway](../other/ec2.md#gateway)","[gateway](../../prod/cde/ec2.md#gateway)"]`',
            'desired.row.002-005.comment': 'Cloud Control references'})
        write_model(crossroot / 'model/dev/cde/vpc.properties', cross_values)
        from validation_cache import input_context
        with input_context():
            cross = snapshot(generator.generate(crossroot, 'dev', 'cde', 'vpc')[0])
        assert {'dev/cde/vpc', 'dev/other/vpc', 'prod/cde/vpc'} <= cross['models'].keys()
        with patch.dict(sys.modules):
            m = runtime(cross)['engine'](cross)
            ctx = m.Context(m.ROOT, cross['target'], cli_runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError('AWS forbidden')))
            consumer = ctx.model(m.ROOT / 'model/dev/cde/vpc.properties').resources[1]
            for link, address in [('[other](../other/vpc.md#main-vpc)', 'dev/other/vpc'),
                                  ('[prod](../../prod/cde/vpc.md#main-vpc)', 'prod/cde/vpc')]:
                producer = consumer.reference(link)
                assert producer.model.path == m.ROOT / 'model' / (address + '.properties')
                gateway_link = link.replace('vpc.md#main-vpc', 'ec2.md#gateway')
                gateway = consumer.reference(gateway_link)
                assert gateway.kind == 'EC2.TransitGateway'
                for selected in (producer, gateway):
                    key = (selected.model.path, selected.number, 'base')
                    ctx.fetch_cache[key], ctx.fetch_trace[key] = {'id': 'cached'}, []
                    for acquire in (lambda: selected.identity(), lambda: ctx.fetch(selected, 'base'),
                                    lambda: ctx._fetch(selected, 'base')):
                        try:
                            acquire()
                        except m.Unresolved as error:
                            assert 'outside authorized AWS retrieval scope' in str(error)
                        else:
                            raise AssertionError('cross-scope reference expanded AWS authorization')
            try:
                consumer.reference('[missing](../other/missing.md#missing)')
            except m.Unresolved as error:
                assert 'producer Model is absent' in str(error)
            else:
                raise AssertionError('absent producer used another scope')
            try:
                consumer.reference('[escape](../../../escape.md#main-vpc)')
            except ValueError as error:
                assert 'outside the Model tree' in str(error)
            else:
                raise AssertionError('Model tree escape accepted')
        from task_contract import SELECTOR, task_revision
        from support.worktree_task_fixtures import contract
        from support.it_workspace import copy_framework
        copy_framework(root / 'framework')
        name = 'tasks/audit.md'
        prompt = root / name
        prompt.parent.mkdir()
        text = contract('audit', ['tests/dev/cde/vpc.py']).replace('`governance`', '`migration`').replace('`framework`', '`dev/cde/vpc`')
        prompt.write_text(text)
        output = root / 'tests/dev/cde/vpc.py'
        arguments = ['model/cli.py', '--repository-root', str(root), '--environment', 'dev', '--target', 'cde', '--service', 'vpc', '--task-file', name]
        with patch.object(generator, 'ROOT', root), patch.dict(os.environ, {SELECTOR: name}), \
             patch.object(sys, 'argv', arguments), redirect_stdout(io.StringIO()) as messages:
            assert generator.main() == 0, messages.getvalue()
            before = output.read_bytes()
            assert before.decode() == sources['vpc']
            for state in ('completed', 'suspend'):
                prompt.write_text(text.replace('`running`', f'`{state}`') +
                                  ('\n## Suspension reason\nExplicit test stop\n' if state == 'suspend' else ''))
                if state == 'completed':
                    assert task_revision(root, name)[1] == prompt.read_text()
                assert generator.main() == 2 and output.read_bytes() == before
                output.unlink()
                assert generator.main() == 2 and not output.exists()
                output.write_bytes(before)
            prompt.write_text(text)
            def change(*args):
                prompt.write_text(text.replace('`running`', '`completed`'))
                return 'changed source', {}, []
            with patch.object(generator, 'generate', side_effect=change):
                assert generator.main() == 2 and output.read_bytes() == before
            prompt.unlink()
            assert generator.main() == 2 and output.read_bytes() == before
    snapshots = {service: snapshot(source) for service, source in sources.items()}
    assert 'dev/cde/iam' in snapshots['vpc']['models'], 'VPC flow-log IAM reference dependency'
    assert set(snapshots['vpc']['models']) != set(generator.module('model/adapters/aws.py', 'model.adapters.aws').SERVICES)
    vpc = fixture(snapshots['vpc'], 'vpc', [('001', 'EC2.VPC', 'main-vpc', [
        ('Name', '`test-vpc`', None), ('CidrBlock', '`10.10.0.0/23`', None),
        ('EnableDnsSupport', '`true`', None), ('VpcId', '`vpc-observed`', None)])])
    vpc['models']['dev/cde/vpc']['observed.row.001-004.value'] = '`vpc-observed`'
    responses = {('ec2', 'describe-vpcs'): {'Vpcs': [{'VpcId': 'vpc-observed', 'CidrBlock': '10.10.0.0/23',
                  'Tags': [{'Key': 'Name', 'Value': 'test-vpc'}]}]},
                 ('ec2', 'describe-vpc-attribute'): {'EnableDnsSupport': {'Value': False}}}
    rt = runtime(vpc)
    cli = CLI(responses)
    _, account, records = rt['audit'](vpc, 'dev-profile', cli)
    status = {r['propertiesKey']: r['status'] for r in records}
    assert status['EC2.VPC.CidrBlock'] == 'match', records
    assert status['EC2.VPC.EnableDnsSupport'] == 'difference', records
    assert status['EC2.VPC.VpcId'] == 'identifier', records
    stamp = datetime(2026, 10, 15, tzinfo=timezone.utc)
    text, code = rt['report'](vpc, 'dev-profile', account, records, stamp)
    assert code == 2 and '[ERROR] main-vpc.EC2.VPC.VpcId' in text
    assert 'aws ec2 describe-vpc-attribute' in text and 'Diff paths: $' in text
    assert 'Model SHA256:' in text and 'Executed:' in text
    # No lookup-only property can produce an overall configuration PASS.
    ordinary = [r for r in records if r['status'] != 'identifier']
    assert rt['report'](vpc, None, account, ordinary, stamp)[1] == 1
    for r in ordinary:
        r['status'] = 'match'
    assert rt['report'](vpc, None, account, ordinary, stamp)[1] == 0
    _, _, failed = rt['audit'](vpc, None, CLI(responses, fail=('ec2', 'describe-vpcs')))
    assert len(failed) == len(records), failed
    assert any(r['status'] == 'acquisition_failed' for r in failed)
    # Configured profile conflict and account/authentication errors stop before resource APIs.
    configured = copy.deepcopy(vpc)
    configured['target']['awsProfile'] = 'required'
    cli = CLI(responses)
    assert all(r['status'] == 'acquisition_failed' for r in rt['audit'](configured, 'wrong', cli)[2])
    assert not cli.calls
    cli = CLI(responses)
    assert all(r['status'] == 'acquisition_failed' for r in rt['audit'](vpc, '', cli)[2])
    assert not cli.calls
    cli = CLI(responses, account='999999999999')
    assert all(r['status'] == 'acquisition_failed' for r in rt['audit'](vpc, None, cli)[2])
    assert all(api == ('sts', 'get-caller-identity') for api, _, _ in cli.calls)
    # Unresolved references remain visible, independent of the other attributes.
    unresolved = copy.deepcopy(vpc)
    unresolved['models']['dev/cde/vpc']['desired.row.001-002.value'] = '[missing](#missing)'
    result = rt['audit'](unresolved, None, CLI(responses))[2]
    assert any(r['propertiesKey'] == 'EC2.VPC.CidrBlock' and r['status'] == 'design_unresolved' for r in result)
    # A valid parent reference uses the fetched identity, then checks membership.
    referenced = fixture(snapshots['vpc'], 'vpc', [
        ('001', 'EC2.VPC', 'main-vpc', [('Name', '`test-vpc`', None), ('CidrBlock', '`10.10.0.0/23`', None)]),
        ('002', 'EC2.Subnet', 'subnet', [('Name', '`test-subnet`', None), ('VpcId', '[main](#main-vpc)', None)])])
    membership = {**responses, ('ec2', 'describe-subnets'): {'Subnets': [
        {'SubnetId': 'subnet-01', 'VpcId': 'vpc-wrong-parent', 'Tags': [{'Key': 'Name', 'Value': 'test-subnet'}]}]}}
    resolved = rt['audit'](referenced, None, CLI(membership))[2]
    assert any(r['propertiesKey'] == 'EC2.Subnet.VpcId' and r['status'] == 'difference' and
               r['designValue'] == 'vpc-observed' for r in resolved), resolved
    # Trust, inline, managed, attached policies, and permissions boundary.
    iam = fixture(snapshots['iam'], 'iam', [('001', 'IAM.Role', 'role', [
        ('RoleName', '`test-role`', None), ('AssumeRolePolicyDocument', '[trust](trust.json)', POLICY),
        ('Policies[].PolicyName', '`inline`', None), ('Policies[].PolicyDocument', '[inline](inline.json)', POLICY),
        ('ManagedPolicyArns', '`["arn:aws:iam::123456789012:policy/managed"]`', None),
        ('PermissionsBoundary', '`arn:aws:iam::123456789012:policy/boundary`', None)]),
        ('002', 'IAM.ManagedPolicy', 'managed', [('ManagedPolicyName', '`managed`', None),
                                              ('PolicyDocument', '[managed](managed.json)', POLICY)])])
    iam['schemas']['IAM.Role.PermissionsBoundary'] = {'type': 'string'}
    reordered = copy.deepcopy(POLICY)
    reordered['Statement'].reverse()
    reordered['Statement'][1]['Action'].reverse()
    reordered['Statement'][1]['Resource'].reverse()
    reordered['Statement'][1]['Condition']['StringEquals']['aws:PrincipalOrgID'].reverse()
    iam_responses = {('iam', 'get-role'): {'Role': {'RoleName': 'test-role', 'AssumeRolePolicyDocument': reordered,
                   'PermissionsBoundary': {'PermissionsBoundaryArn': 'arn:aws:iam::123456789012:policy/boundary'}}},
        ('iam', 'list-role-policies'): {'PolicyNames': ['inline']},
        ('iam', 'get-role-policy'): {'PolicyDocument': reordered},
        ('iam', 'list-attached-role-policies'): {'AttachedPolicies': [{'PolicyArn': 'arn:aws:iam::123456789012:policy/managed'}]},
        ('iam', 'list-policies'): {'Policies': [{'PolicyName': 'managed', 'Arn': 'arn:aws:iam::123456789012:policy/managed', 'DefaultVersionId': 'v1'}]},
        ('iam', 'get-policy-version'): {'PolicyVersion': {'Document': reordered}}}
    irt = runtime(iam)
    _, account, result = irt['audit'](iam, None, CLI(iam_responses))
    assert all(r['status'] == 'match' for r in result), result
    assert len(result) == 8
    for change in ('Action', 'Condition'):
        altered = copy.deepcopy(iam_responses)
        statement = altered[('iam', 'get-role')]['Role']['AssumeRolePolicyDocument']['Statement'][1]
        if change == 'Action':
            statement['Action'].append('s3:PutObject')
        else:
            statement['Condition']['StringEquals']['aws:PrincipalOrgID'] = ['o-different']
        changed = irt['audit'](iam, None, CLI(altered))[2]
        assert any(r['propertiesKey'] == 'IAM.Role.AssumeRolePolicyDocument' and r['status'] == 'difference' for r in changed)
        assert '$.Statement' in irt['report'](iam, None, account, changed, stamp)[0]
    # The existing resolver assumes every GetAtt means Arn. Audits reject that guess.
    role_arn = 'arn:aws:iam::123456789012:role/test-role'
    symbolic = copy.deepcopy(iam)
    symbolic_responses = copy.deepcopy(iam_responses)
    symbolic_responses[('iam', 'get-role')]['Role']['Arn'] = role_arn
    actual_policy = copy.deepcopy(POLICY)
    actual_policy['Statement'][0]['Resource'] = role_arn
    symbolic_responses[('iam', 'get-role')]['Role']['AssumeRolePolicyDocument'] = actual_policy
    for expression, expected in [({'Fn::GetAtt': ['role', 'Arn']}, 'match'),
                                 ({'Fn::GetAtt': ['role', 'RoleId']}, 'design_unresolved'),
                                 ({'Fn::Sub': '${role.RoleId}'}, 'design_unresolved')]:
        document = copy.deepcopy(POLICY)
        document['Statement'][0]['Resource'] = expression
        symbolic['models']['dev/cde/iam']['desired.row.001-002.document'] = json.dumps(document)
        result = irt['audit'](symbolic, None, CLI(symbolic_responses))[2]
        item, = [r for r in result if r['propertiesKey'] == 'IAM.Role.AssumeRolePolicyDocument']
        assert item['status'] == expected, item
        if expected == 'design_unresolved':
            assert 'unsupported GetAtt attribute' in item['reason'], item
    # Unsupported attributes are explicit errors, even when Mapping include=false.
    unsupported = copy.deepcopy(iam)
    for key, value in [('property', 'IAM.Role.MaxSessionDuration'), ('value', '`3600`'), ('comment', 'fixture')]:
        unsupported['models']['dev/cde/iam']['desired.row.001-007.' + key] = value
    result = irt['audit'](unsupported, None, CLI(iam_responses))[2]
    assert any(r['propertiesKey'] == 'IAM.Role.MaxSessionDuration' and r['status'] == 'sdk_unavailable' and r['reason'] for r in result)
    assert irt['masked']({'password': 'never-print', 'Tags': [{'Key': 'token', 'Value': 'never-print'}]}) == {'password': '[REDACTED]', 'Tags': ['[REDACTED]']}
    with tempfile.TemporaryDirectory(prefix='model-test-') as temporary:
        folder = Path(temporary)
        script = folder / 'tests/dev/cde/vpc.py'
        script.parent.mkdir(parents=True)
        capture = io.StringIO()
        with redirect_stdout(capture):
            assert rt['main'](['--profile', 'dev-profile'], CLI(responses), script) == 2
        logs = list((folder / 'tests/results/dev/cde').glob('vpc-*.log'))
        assert len(logs) == 1 and logs[0].read_text(encoding='utf-8') == capture.getvalue()
        assert 'secret-not-for-output' not in capture.getvalue()
        # Isolated Python process with a fake AWS executable proves no repo/PyPI imports.
        fake = folder / 'aws'
        fake.write_text('#!' + sys.executable + '\nimport json, sys\nprint(json.dumps(' + repr(responses[('ec2', 'describe-vpcs')]) +
                        ' if sys.argv[1:3] == ["ec2", "describe-vpcs"] else ' + repr(responses[('ec2', 'describe-vpc-attribute')]) +
                        ' if sys.argv[1] == "ec2" else {"Account":"123456789012", "Arn":"arn:aws:iam::123456789012:user/offline"}))\n', encoding='utf-8')
        fake.chmod(0o700)
        source = sources['vpc']
        old = repr(json.dumps(snapshots['vpc'], sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
        replacement = repr(json.dumps(vpc, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
        assert old in source
        script.write_text(source.replace(old, replacement, 1), encoding='utf-8')
        process = subprocess.run([sys.executable, '-I', '-B', str(script)], cwd=folder,
                                 env={**os.environ, 'PATH': str(folder)}, capture_output=True, text=True, timeout=30)
        assert process.returncode == 2 and '[OK] main-vpc.EC2.VPC.CidrBlock' in process.stdout, (process.stdout, process.stderr)
        flat = folder / 'vpc.py'
        flat.write_text(script.read_text(encoding='utf-8'), encoding='utf-8')
        process = subprocess.run([sys.executable, '-I', '-B', str(flat)], cwd=folder,
                                 env={**os.environ, 'PATH': str(folder)}, capture_output=True, text=True, timeout=30)
        assert process.returncode == 2 and '[OK] main-vpc.EC2.VPC.CidrBlock' in process.stdout, (process.stdout, process.stderr)
        assert any(path.read_text(encoding='utf-8') == process.stdout for path in logs[0].parent.glob('vpc-*.log'))

    from validation.scenario import check_results
    from validation.findings import Findings
    with tempfile.TemporaryDirectory(prefix='audit-log-layout-') as temporary:
        folder = Path(temporary)
        log = folder / 'tests/results/dev/cde/vpc-20261015-214500.log'
        log.parent.mkdir(parents=True)
        log.write_text('audit evidence', encoding='utf-8')
        script = folder / 'tests/dev/cde/vpc.py'
        script.parent.mkdir(parents=True)
        script.touch()
        findings = Findings(folder)
        check_results(folder, {('dev', 'cde'): {}}, False, {}, findings)
        assert not findings.errors, findings.errors
        log.rename(log.with_name('vpc-invalid.log'))
        findings = Findings(folder)
        check_results(folder, {('dev', 'cde'): {}}, False, {}, findings)
        assert any('invalid audit log' in error for error in findings.errors)
    print('Model audit tests: PASS (offline generation, VPC/IAM, references, policies, auth, standalone, logs, determinism)')


if __name__ == '__main__':
    with patch.dict(sys.modules):
        check()
