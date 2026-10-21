"""Explicit properties authorities and offline AWS transport; no executing project inputs."""
import json
from pathlib import Path
import shutil
import subprocess
from model.format import serialize

FRAMEWORK = Path(__file__).resolve().parents[4]


def logs_fixture(root):
    """Install immutable catalog/mapping/schema inputs before the first reader."""
    for name in ('materials', 'mappings', 'rules'):
        shutil.copytree(FRAMEWORK / 'framework' / name, root / 'framework' / name)
    (root / 'project.json').write_text(json.dumps({'projectName': 'fixture', 'targets': [
        {'environment': 'qa-synthetic', 'alias': 'team-a', 'awsAccountId': '123456789012',
         'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}), encoding='utf-8')
    model = root / 'model/qa-synthetic/team-a/cloudwatch-logs.properties'
    model.parent.mkdir(parents=True)
    values = {'desired.service.cloudwatch-logs.serviceId': 'cloudwatch-logs',
              'desired.service.cloudwatch-logs.ownedCatalogResourceTypes': 'Logs.LogGroup',
              'display.service.title': '# 合成 Log Group 詳細設計',
              'desired.resource.001.resourceType': 'Logs.LogGroup',
              'desired.resource.001.logicalId': 'fixed-logs', 'desired.resource.001.anchor': 'logs-fixed',
              'desired.resource.001.resourceMode': 'IMPORT', 'display.resource.001.comment': '合成 Log Group'}
    for index, (prop, value) in enumerate([('LogGroupName', '[fixture](#logs-fixed)'),
            ('RetentionInDays', '`30`'), ('DeletionProtectionEnabled', '`false`'), ('LogGroupClass', '`STANDARD`')], 1):
        values.update({f'desired.row.001-{index:03d}.property': 'Logs.LogGroup.' + prop,
                       f'desired.row.001-{index:03d}.value': value, f'desired.row.001-{index:03d}.comment': '合成値'})
    values['observed.row.001-001.value'] = '`fixture-001`'
    model.write_text(serialize(values), encoding='utf-8')
    return model


def import_contract(name, model):
    model = Path(model).as_posix()
    view = model.replace('model/', 'docs/designs/', 1).replace('.properties', '.md')
    listed = ''.join('- `' + path + '`\n' for path in (name, model, view))
    return '''# Synthetic Import
## Task contract
- Task type: `design`
- Task status: `running`
- Workflow: `import`
- IMPORT target: `qa-synthetic/team-a/cloudwatch-logs`
- AWS API execution: `read-only`
- deploy/apply: `forbidden`
## Validation scope
- `qa-synthetic/team-a/cloudwatch-logs`
## Required changes
- [R1] Synthetic explicit Import
## Acceptance checks
- [R1] `exists:project.json`
## Modified files
''' + listed + '\n## Allowed paths\n' + listed


class LogsCli:
    def __init__(self, groups=None):
        self.calls = []
        self.groups = groups if groups is not None else [{'logGroupName': 'fixture-001', 'retentionInDays': 90,
                'deletionProtectionEnabled': True, 'logGroupClass': 'STANDARD'}]

    def __call__(self, command, **kwargs):
        service, operation = command[1:3]
        self.calls.append((service, operation))
        assert command[0] == 'aws' and kwargs['timeout'] == 60
        if (service, operation) == ('sts', 'get-caller-identity'):
            value = {'Account': '123456789012'}
        elif (service, operation) == ('logs', 'describe-log-groups'):
            value = {'logGroups': self.groups}
        else:
            raise AssertionError('unmocked AWS transport: ' + service + '/' + operation)
        return subprocess.CompletedProcess(command, 0, json.dumps(value), '')

from model.sources import Scope, load_model
from model.format import parse

def format_fixture(root, *, target='one', environment='qa-custom', service='network'):
    project = {'targets': [
        {'environment': environment, 'alias': 'one', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation', 'awsExecutionAccountId': '999999999999'},
        {'environment': environment, 'alias': 'two', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'},
        {'environment': environment + '-single', 'awsAccountId': '222222222222', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}
    (root / 'project.json').write_text(json.dumps(project), encoding='utf-8')
    scope = Scope(root, environment + '-single' if target == '222222222222' else environment, target, service)
    values = {
        'desired.resource.007.resourceType': 'EC2.VPC',
        'desired.resource.007.logicalId': 'original',
        'desired.resource.007.anchor': 'network',
        'desired.resource.007.resourceMode': 'IMPORT',
        'desired.row.007-001.property': 'EC2.VPC.VpcId',
        'desired.row.007-001.value': '[Network](#network)',
        'desired.row.007-001.comment': '合成 ID',
        'observed.row.007-001.value': '',
        'desired.row.007-002.property': 'EC2.VPC.CidrBlock',
        'desired.row.007-002.value': ' 010 \\ " ',
        'desired.row.007-002.comment': '原文保持'}
    scope.path.parent.mkdir(parents=True)
    scope.path.write_text(serialize(values), encoding='utf-8')
    return scope, values


def source_context(scope, *, imported=False):
    # Unit-only capability fixture: factory/worktree authorization is tested separately.
    from types import SimpleNamespace
    from generation_inputs import GenerationInputs
    from model.sources import SourceWriteContext
    values = parse(scope.path.read_text(encoding='utf-8')).values
    values['desired.resource.007.resourceMode'] = 'IMPORT' if imported else 'CREATE'
    scope.path.write_text(serialize(values), encoding='utf-8')
    task = scope.root / 'tasks/active.md'
    task.parent.mkdir(exist_ok=True)
    listed = ''.join('- `' + path + '`\n' for path in ('tasks/active.md', scope.path.relative_to(scope.root).as_posix()))
    task.write_text('## Task contract\n- Task type: `governance`\n- Task status: `running`\n' +
                    '## Modified files\n' + listed + '## Allowed paths\n' + listed, encoding='utf-8')
    inputs = GenerationInputs(scope.root, task_file='tasks/active.md')
    model = load_model(scope, inputs)
    context = SourceWriteContext._authorized(scope.root, inputs, SimpleNamespace(action='import-delete'),
                                            lambda changes: None, frozenset(model.files))
    return model, context


def acquisition_fixture(snapshot, *, action='refresh', resource='007'):
    from datetime import datetime, timezone
    from model.operations import operation_values
    from import_guard import digest
    identity = 'vpc-original' if action == 'refresh' else 'vpc-acquired'
    record = {'record': 'record-one', 'kind': 'EC2.VPC', 'identity': identity,
              'identityProperty': 'EC2.VPC.VpcId', 'properties': {
                  'EC2.VPC.VpcId': {'status': 'captured', 'value': identity},
                  'EC2.VPC.CidrBlock': {'status': 'captured', 'value': '10.0.0.0/16'}}}
    value = {'version': 3, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1,
             'task': 'tasks/import.md', 'root': str(snapshot.scope.root),
             'scope': [snapshot.scope.environment, snapshot.scope.target, snapshot.scope.service],
             'sources': {}, 'connection': {}, 'acquiredAt': datetime.now(timezone.utc).isoformat(),
             'records': [record], 'inventory': {'EC2.VPC': {'status': 'complete'}}}
    decision = {'record': record['record'], 'resource': resource, 'action': action,
                'reason': '合成 fixture の明示的選択', 'basis': ['EC2.VPC.VpcId']}
    if action in {'bind', 'replace'}:
        decision['before'] = {'identity': None if action == 'bind' else 'vpc-original',
                              'model': digest(operation_values(snapshot.authoritative, resource))}
    return value, {'resources': [decision], 'excluded': [], 'unreflected': []}



def role_operation_fixture(root):
    from model.sources import Scope
    root.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'qa-synthetic', 'alias': 'team-a',
        'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}), encoding='utf-8')
    scope = Scope(root, 'qa-synthetic', 'team-a', 'iam')
    values = {'desired.service.iam.serviceId': 'iam', 'desired.service.iam.ownedCatalogResourceTypes': 'IAM.Role',
              'display.service.title': '# 合成 IAM Role'}
    for rid, name in [('007', 'source'), ('008', 'destination'), ('009', 'unrelated')]:
        values.update({f'desired.resource.{rid}.resourceType': 'IAM.Role', f'desired.resource.{rid}.resourceMode': 'IMPORT',
            f'desired.resource.{rid}.logicalId': 'fixed-' + name, f'desired.resource.{rid}.anchor': name,
            f'display.resource.{rid}.comment': name,
            f'desired.row.{rid}-001.property': 'IAM.Role.RoleName', f'desired.row.{rid}-001.value': f'[{name}](#{name})',
            f'desired.row.{rid}-001.comment': name + ' identity', f'observed.row.{rid}-001.value': '`role-' + name + '`',
            f'desired.row.{rid}-002.property': 'IAM.Role.AssumeRolePolicyDocument',
            f'desired.row.{rid}-002.value': f'[Policy](iam/{name}.json)', f'desired.row.{rid}-002.comment': name + ' policy',
            f'desired.row.{rid}-002.document': json.dumps({'Version': '2012-10-17', 'Statement': [
                {'Effect': 'Allow', 'Action': 'sts:AssumeRole', 'Principal': {'AWS': f'[{name}](#{name})'},
                 'Condition': {'Bool': {'aws:SecureTransport': True}}, 'fixture-order': [1, '1', False]}]})})
    scope.path.parent.mkdir(parents=True)
    scope.path.write_text(serialize(values), encoding='utf-8')
    return scope, values


def retarget_fixture(root):
    from model.sources import Scope
    root.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': 'qa-synthetic', 'alias': alias, 'awsAccountId': '123456789012',
         'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'} for alias in ('team-a', 'team-b')]}), encoding='utf-8')
    producer = Scope(root, 'qa-synthetic', 'team-a', 'network')
    values = {}
    for rid, name in [('007', 'source'), ('008', 'destination')]:
        values.update({f'desired.resource.{rid}.resourceType': 'EC2.VPC', f'desired.resource.{rid}.resourceMode': 'IMPORT',
            f'desired.resource.{rid}.anchor': name, f'desired.resource.{rid}.logicalId': rid,
            f'desired.row.{rid}-001.property': 'EC2.VPC.VpcId', f'desired.row.{rid}-001.value': f'[{rid}](#{name})',
            f'desired.row.{rid}-001.comment': '合成 ID', f'observed.row.{rid}-001.value': 'vpc-' + name})
    producer.path.parent.mkdir(parents=True)
    producer.path.write_text(serialize(values), encoding='utf-8')
    consumer = Scope(root, producer.environment, producer.target, 'security-group')
    values = {'desired.resource.001.resourceType': 'EC2.SecurityGroup', 'desired.resource.001.resourceMode': 'CREATE',
        'desired.resource.001.logicalId': 'fixed-consumer', 'desired.resource.001.anchor': 'consumer',
        'desired.row.001-001.property': 'EC2.SecurityGroup.VpcId',
        'desired.row.001-001.value': 'qa-synthetic:123456789012:vpc-source', 'desired.row.001-001.comment': '合成参照'}
    resource = {'consumerKey': 'desired.row.001-001.value', 'text': 'vpc-source', 'occurrence': '1',
        'producerKind': 'resource', 'producerScope': 'qa-synthetic/team-a/network', 'producerId': '007',
        'resourceType': 'EC2.VPC', 'format': 'identifier', 'property': 'EC2.VPC.VpcId', 'labelPolicy': 'none'}
    context = {'consumerKey': 'desired.row.001-001.value', 'text': '123456789012', 'occurrence': '1',
        'producerKind': 'context', 'producerScope': 'qa-synthetic/team-a', 'format': 'literal',
        'labelPolicy': 'none', 'contextProperty': 'executionAccountId'}
    for identity, spec in [('resource-use', resource), ('context-use', context)]:
        values.update({f'desired.reference.{identity}.{field}': value for field, value in spec.items()})
    consumer.path.write_text(serialize(values), encoding='utf-8')
    return consumer, values


def value_snapshot(values, provenance=None, files=None):
    """Minimal reader result for pure value-verifier tests; source guards use real snapshots."""
    from types import SimpleNamespace
    from model.sources import runtime_values
    if provenance:
        raise ValueError('test fixture requires explicit reference metadata, not template provenance')
    return SimpleNamespace(authoritative=dict(values), values=runtime_values(values), files=files or {}, warnings=())


def import_publication_case(monkeypatch, failure):
    import sys
    import pytest
    from model.sources import load_model
    from model.importing import cli
    from model.format import parse, patch
    from support.model_v2_fixtures import logs_fixture, LogsCli, import_contract
    from support.worktree_task_fixtures import fixture, git, start
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    with fixture() as root:
        model = logs_fixture(root)
        if failure == 'bind':
            model.write_text(patch(parse(model.read_text(encoding='utf-8')), {'observed.row.001-001.value': None}), encoding='utf-8')
        incoming_source = None
        if failure in {'bind', 'replace'}:
            from model.format import serialize
            incoming_source = model.with_name('codebuild.properties')
            fields = {'desired.resource.002.resourceType': 'CodeBuild.Project', 'desired.resource.002.resourceMode': 'IMPORT',
                'desired.resource.002.anchor': 'consumer', 'desired.row.002-001.property': 'CodeBuild.Project.LogsConfig.CloudWatchLogs.GroupName',
                'desired.row.002-001.value': 'fixture-001', 'desired.row.002-001.comment': '合成 incoming 参照'}
            for key, value in {'consumerKey': 'desired.row.002-001.value', 'text': 'fixture-001', 'occurrence': '1',
                    'producerKind': 'resource', 'producerScope': 'qa-synthetic/team-a/cloudwatch-logs', 'producerId': '001',
                    'resourceType': 'Logs.LogGroup', 'format': 'identifier', 'property': 'Logs.LogGroup.LogGroupName', 'labelPolicy': 'none'}.items():
                fields['desired.reference.fixed-use.' + key] = value
            incoming_source.write_text(serialize(fields), encoding='utf-8')
            incoming_before = incoming_source.read_bytes()
        relative = model.relative_to(root)
        git(root, 'add', 'framework', 'model', 'project.json')
        git(root, 'commit', '-qm', 'synthetic properties Import')
        target, state = start(root, files=(relative.as_posix(),))
        (target / state['task_file']).write_text(import_contract(state['task_file'], relative), encoding='utf-8')
        path = target / relative
        original = path.read_bytes()
        aws = LogsCli()
        if failure == 'replace':
            aws.groups[0]['logGroupName'] = 'replacement-001'

        result = cli.acquire(target, 'qa-synthetic', 'cloudwatch-logs', 'team-a', cli_runner=aws,
                             resource_types=['Logs.LogGroup'])
        evidence = Path(result['evidence'])
        assert result['status'] == 'acquired' and len(result['records']) == 1, result
        record = result['records'][0]
        candidate = evidence.parent / 'candidates' / relative
        candidate.parent.mkdir(parents=True)
        changes = {'desired.row.001-002.value': '`90`', 'desired.row.001-003.value': '`true`'}
        action = failure if failure in {'bind', 'replace'} else 'refresh'
        chosen = {'record': record['record'], 'resource': '001', 'action': action,
            'reason': '合成の明示的な対応選択', 'basis': ['Logs.LogGroup.LogGroupName']}
        if failure in {'bind', 'replace'}:
            from import_guard import digest
            from model.operations import operation_values
            chosen['before'] = {'identity': None if failure == 'bind' else 'fixture-001',
                'model': digest(operation_values(load_model(path).authoritative, '001'))}
            changes['observed.row.001-001.value'] = '`' + record['identity'] + '`'
        candidate.write_text(patch(parse(original.decode('utf-8')), changes), encoding='utf-8')
        (evidence.parent / 'selection.json').write_text(json.dumps({'resources': [chosen], 'excluded': [], 'unreflected': []}), encoding='utf-8')
        (evidence.parent / 'review-input.json').write_text(json.dumps({'risks': {record['record']: []}}), encoding='utf-8')
        reviewed = cli.review_acquisition(target, 'qa-synthetic', 'cloudwatch-logs', evidence, 'team-a')
        assert reviewed['status'] == 'reviewed' and path.read_bytes() == original
        if incoming_source is not None:
            assert any(item.get('consumer') == 'qa-synthetic/team-a/codebuild/002'
                       for item in reviewed['review']['referenceImpact']['warnings'])
        calls = list(aws.calls)
        if failure == 'source':
            path.write_bytes(original + b'# concurrent edit\n')
        elif failure == 'task':
            task = target / state['task_file']
            task.write_bytes(task.read_bytes() + b'\n## Notes\nchanged Task\n')
        elif failure == 'review':
            file = evidence.parent / 'review.json'
            changed = json.loads(file.read_text(encoding='utf-8'))
            changed['dispositions'][0]['risks'] = ['changed review']
            file.write_text(json.dumps(changed), encoding='utf-8')
        elif failure == 'head':
            git(target, 'commit', '--allow-empty', '-qm', 'changed HEAD')
        elif failure == 'candidate':
            candidate.write_text(candidate.read_text(encoding='utf-8').replace('`90`', '`91`'), encoding='utf-8')
        elif failure == 'source-set':
            extra = path.with_suffix('') / 'part-003.properties'
            extra.parent.mkdir()
            extra.write_text('# model-format: 2\n', encoding='utf-8')
        if failure == 'selection-target':
            selection = evidence.parent / 'selection.json'
            value = json.loads(selection.read_text())
            value['resources'][0]['resource'] = '009'
            selection.write_text(json.dumps(value), encoding='utf-8')
        elif failure == 'candidate-resource':
            candidate.write_text(candidate.read_text() + 'desired.resource.002.resourceType=Logs.LogGroup\ndesired.resource.002.resourceMode=IMPORT\ndesired.resource.002.anchor=unselected\n', encoding='utf-8')
        elif failure == 'candidate-reference':
            extra = {**parse(candidate.read_text()).values}
            for field, value in {'consumerKey': 'desired.row.001-001.value', 'text': '[fixture](#logs-fixed)', 'occurrence': '1',
                    'producerKind': 'resource', 'producerScope': 'qa-synthetic/team-a/cloudwatch-logs', 'producerId': '001',
                    'resourceType': 'Logs.LogGroup', 'format': 'link', 'labelPolicy': 'fixed'}.items():
                extra['desired.reference.unreviewed.' + field] = value
            from model.format import serialize
            candidate.write_text(serialize(extra), encoding='utf-8')
        if failure in {'source', 'task', 'head', 'review', 'candidate', 'source-set', 'selection-target', 'candidate-resource', 'candidate-reference'}:
            with pytest.raises(ValueError, match='changed|differs|unregistered|stale|candidate|selected Resource|reference map|correspondence'):
                cli.publish_acquisition(target, 'qa-synthetic', 'cloudwatch-logs', evidence, 'team-a')
            assert path.read_bytes() == original + (b'# concurrent edit\n' if failure == 'source' else b'')
            from import_guard import proof_path
            assert not proof_path(target).exists()
            assert aws.calls == calls
            return
        if failure.endswith('-crash'):
            program = "import sys,os\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom task_contract import selected_task\nfrom model.importing import cli\nimport sync_files\nroot,name,path,evidence=Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4]),Path(sys.argv[5])\nmode=sys.argv[6]\nif mode=='receipt-crash':\n    original=cli.record_import\n    def crash(*args,**kwargs):\n        original(*args,**kwargs)\n        os._exit(17)\n    cli.record_import=crash\nelse:\n    original=sync_files.save_files\n    def crash(outputs):\n        selected=path if mode=='source-crash' else next((p for p in outputs if p.suffix=='.md'),None)\n        if selected in outputs:\n            selected.parent.mkdir(parents=True,exist_ok=True)\n            selected.write_bytes(b'partial child bytes')\n            os._exit(17)\n        return original(outputs)\n    sync_files.save_files=crash\nwith selected_task(root,name):\n    cli.publish_acquisition(root,'qa-synthetic','cloudwatch-logs',evidence,'team-a')\nraise AssertionError('injected crash did not execute')\n"
            crashed = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(FRAMEWORK / 'framework/scripts'),
                str(target), state['task_file'], str(path), str(evidence), failure], capture_output=True, text=True, encoding='utf-8')
            assert crashed.returncode == 17, crashed.stdout + crashed.stderr
            from import_guard import proof_path
            assert proof_path(target).is_file()
            with pytest.raises(ValueError, match='pending Model publication'):
                load_model(path)
            assert cli.recover_transaction(target, 'qa-synthetic', 'cloudwatch-logs', evidence, 'team-a')['status'] == 'recovered'
            if failure == 'display-crash':
                assert path.read_bytes() == candidate.read_bytes()
                assert cli.recover_display(target, 'qa-synthetic', 'cloudwatch-logs', 'team-a')['status'] == 'complete'
            else:
                assert path.read_bytes() == original and not proof_path(target).exists()
                assert cli.publish_acquisition(target, 'qa-synthetic', 'cloudwatch-logs', evidence, 'team-a')['status'] == 'complete'
            assert aws.calls == calls
            assert (root / relative).read_bytes() == original
            return
        with monkeypatch.context() as injection:
            if failure.startswith('post-'):
                original_outputs = cli.record_outputs
                injected = False
                def race(*args, **kwargs):
                    nonlocal injected
                    result = original_outputs(*args, **kwargs)
                    if injected:
                        return result
                    injected = True
                    if failure in {'post-review', 'post-draft'}:
                        file = evidence.parent / ('review.json' if failure == 'post-review' else 'review-input.json')
                        file.write_bytes(file.read_bytes() + b' ')
                    elif failure == 'post-candidate':
                        candidate.write_bytes(candidate.read_bytes() + b'# changed candidate\n')
                    elif failure == 'post-acquisition':
                        envelope = json.loads(evidence.read_text(encoding='utf-8'))
                        envelope['payload']['status'] = 'changed acquisition'
                        evidence.write_text(json.dumps(envelope), encoding='utf-8')
                    elif failure == 'post-baseline':
                        path.write_bytes(original + b'# external source edit\n')
                    elif failure == 'post-task':
                        task = target / state['task_file']
                        task.write_bytes(task.read_bytes() + b'\n## Notes\nexternal Task edit\n')
                    else:
                        from datetime import datetime, timedelta
                        from model.importing import approval
                        class ExpiredClock(datetime):
                            @classmethod
                            def now(cls, tz=None):
                                return datetime.now(tz) + timedelta(days=8)
                        injection.setattr(approval, 'datetime', ExpiredClock)
                    return result
                injection.setattr(cli, 'record_outputs', race)
            if failure in {'model-io', 'display-io'}:
                import sync_files
                save = sync_files.save_files
                def fail(output):
                    selected = {file: text for file, text in output.items() if
                                (file == path if failure == 'model-io' else file.suffix == '.md')}
                    if selected:
                        file = next(iter(selected))
                        file.parent.mkdir(parents=True, exist_ok=True)
                        file.write_text('partial output', encoding='utf-8')
                        raise OSError('injected write failure')
                    return save(output)
                injection.setattr(sync_files, 'save_files', fail)
            elif failure == 'receipt':
                finish = cli.finish_import
                def fail(root, model=None, markdown=None):
                    if model is not None:
                        finish(root, model, markdown)
                        raise ValueError('injected receipt failure')
                    return finish(root, model, markdown)
                injection.setattr(cli, 'finish_import', fail)
            if failure in {'model-io', 'receipt'} or failure.startswith('post-'):
                with pytest.raises((OSError, ValueError)):
                    cli.publish_acquisition(target, 'qa-synthetic', 'cloudwatch-logs', evidence, 'team-a')
                assert path.read_bytes() == original + (b'# external source edit\n' if failure == 'post-baseline' else b'')
                from import_guard import proof_path
                assert not proof_path(target).exists()
                assert aws.calls == calls
                return
            if failure == 'subprocess':
                import os
                command = [sys.executable, '-I', '-B', str(FRAMEWORK / 'framework/scripts/model/cli.py'), 'import', 'publish',
                    '--repository-root', str(target), '--environment', 'qa-synthetic', '--target', 'team-a',
                    '--service', 'cloudwatch-logs', '--evidence', str(evidence), '--task-file', state['task_file']]
                completed = subprocess.run(command, capture_output=True, text=True,
                    env={key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'BLUEPRINT_TASK_FILE'}})
                assert completed.returncode == 0, completed.stdout + completed.stderr
                published = json.loads(completed.stdout)
            else:
                published = cli.publish_acquisition(target, 'qa-synthetic', 'cloudwatch-logs', evidence, 'team-a')
        assert published['model'] == 'reflected', published
        if failure == 'display-io':
            assert published['status'] == 'display-failed', published
            assert path.read_bytes() == candidate.read_bytes()
            from unittest.mock import patch as mock_patch
            with mock_patch.object(cli, 'read_acquisition', side_effect=AssertionError('display recovery must not reacquire or read acquisition')):
                assert cli.recover_display(target, 'qa-synthetic', 'cloudwatch-logs', 'team-a')['status'] == 'complete'
        else:
            assert published['status'] == 'complete', published
        assert path.read_bytes() == candidate.read_bytes()
        assert aws.calls == calls
        assert (target / 'docs/designs/qa-synthetic/team-a/cloudwatch-logs.md').is_file()
        assert (root / relative).read_bytes() == original
        if incoming_source is not None:
            assert (target / incoming_source.relative_to(root)).read_bytes() == incoming_before

