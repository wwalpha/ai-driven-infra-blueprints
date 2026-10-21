"""Fixed legacy Framework and synthetic sources, in separate runtimes."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import hashlib
import os
import json
import subprocess
import tempfile
import pytest
from model.migration.export import export_legacy
from model.migration.convert import convert_export
from model.migration.compare import compare_export
from model.sources import Scope, load_model

FRAMEWORK = Path(__file__).resolve().parents[4]
BASELINE = 'd0c5824fed507db234a7532a309b3c8c3482fb60'


def properties_fixture(root):
    from model.format import serialize
    scope = Scope(root, 'qa-synthetic', 'team-a', 'network')
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': scope.environment, 'alias': scope.target, 'awsAccountId': '123456789012',
         'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}), encoding='utf-8')
    scope.path.parent.mkdir(parents=True)
    scope.path.write_text(serialize({'desired.resource.007.resourceType': 'EC2.VPC',
        'desired.resource.007.logicalId': 'original', 'desired.resource.007.anchor': 'network',
        'desired.resource.007.resourceMode': 'IMPORT', 'desired.row.007-001.property': 'EC2.VPC.VpcId',
        'desired.row.007-001.value': '[Network](#network)', 'desired.row.007-001.comment': '合成 ID',
        'observed.row.007-001.value': 'vpc-original'}), encoding='utf-8')
    return scope


@pytest.mark.parametrize('failure', ['none', 'task', 'source', 'unregistered', 'reuse', 'io', 'head', 'post-dependency', 'post-task', 'post-head', 'post-file-set', 'callback', 'process-death'])
def check_managed_properties_save(monkeypatch, failure):
    from model import prepare_edit, publish_edit
    from model.adapters.task import source_write_context
    from model.format import patch
    from validation_cache import input_context
    from support.worktree_task_fixtures import fixture, git, start
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    with fixture() as root, input_context():
        scope = properties_fixture(root)
        relative = scope.path.relative_to(root).as_posix()
        git(root, 'add', 'model', 'project.json')
        git(root, 'commit', '-qm', 'synthetic properties')
        target, state = start(root, files=(relative,))
        name = state['task_file']
        contract = '''# Model deletion
## Task contract
- Task type: `design`
- Task status: `running`
- Workflow: `update`
- Model operation: `import-delete`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`
- Source resource: `qa-synthetic/team-a/network/007`
## Validation scope
- `qa-synthetic/team-a/network`
## Required changes
- [R1] Synthetic Model-only deletion
## Acceptance checks
- [R1] `exists:project.json`
'''
        listed = ''.join('- `' + item + '`\n' for item in (name, relative))
        for heading in ('Modified files', 'Allowed paths'):
            contract += '\n## ' + heading + '\n' + listed
        (target / name).write_text(contract, encoding='utf-8')
        path = target / relative
        original = path.read_bytes()
        with source_write_context(target, name) as context:
            with pytest.raises(AttributeError):
                context.operation = type('Policy', (), {'action': 'import'})()
            with pytest.raises(AttributeError):
                context.closed = False
            from model.operations import EditPlan
            with pytest.raises(TypeError, match='constructor grants no save authority'):
                EditPlan(approved=True)
            snapshot = load_model(path, context.snapshot)
            proposed = patch(snapshot.documents[path], {'desired.row.007-001.comment': '中間保存'})
            plan = prepare_edit(snapshot, {path: proposed}, context)
            if failure == 'task':
                (target / name).write_text(contract + '\n# changed\n', encoding='utf-8')
            elif failure == 'source':
                path.write_bytes(original + b'# concurrent edit\n')
            elif failure == 'unregistered':
                with pytest.raises(ValueError, match='unregistered'):
                    prepare_edit(snapshot, {target / 'project.json': '{}'}, context)
                return
            elif failure == 'process-death':
                program = "import sys, os\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[1])\nfrom task_contract import selected_task\nfrom model.adapters.task import source_write_context\nfrom model.sources import load_model\nfrom model.operations import prepare_edit, publish_edit\nfrom model.format import patch\nimport sync_files\nroot, name, path = Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])\ndef crash(outputs):\n    path.write_bytes(b'partial child bytes')\n    os._exit(17)\nwith selected_task(root, name), source_write_context(root, name) as context:\n    snapshot = load_model(path, context.snapshot)\n    candidate = patch(snapshot.documents[path], {'desired.row.007-001.comment': 'child candidate'})\n    plan = prepare_edit(snapshot, {path: candidate}, context)\n    sync_files.save_files = crash\n    publish_edit(plan, context)\n"
                crashed = subprocess.run([sys.executable, '-B', '-c', program, str(FRAMEWORK / 'framework/scripts'), str(target), name, str(path)],
                                         capture_output=True, text=True, encoding='utf-8')
                assert crashed.returncode == 17, crashed.stdout + crashed.stderr
                assert path.read_bytes() == b'partial child bytes'
                with pytest.raises(ValueError, match='journal|publication|recovery'):
                    load_model(path)
                assert path.read_bytes() == b'partial child bytes'
                with source_write_context(target, name) as recovered:
                    assert recovered.snapshot.read(path) == original
                assert path.read_bytes() == original
                return
            elif failure == 'callback':
                def fail_callback():
                    assert path.read_text(encoding='utf-8') == proposed
                    assert load_model(path).authoritative['desired.row.007-001.comment'] == '中間保存'
                    raise ValueError('injected source completion callback failure')
                context._finish = fail_callback
            elif failure == 'io':
                import sync_files
                def fail(files):
                    path.write_bytes(b'partial')
                    raise OSError('injected publication failure')
                monkeypatch.setattr(sync_files, 'save_files', fail)
            elif failure == 'head':
                git(target, 'commit', '--allow-empty', '-qm', 'changed HEAD')
            elif failure.startswith('post-'):
                import sync_files
                save = sync_files.save_files
                def concurrent(files):
                    save(files)
                    if failure == 'post-dependency':
                        project = target / 'project.json'
                        project.write_bytes(project.read_bytes() + b'\n')
                    elif failure == 'post-task':
                        (target / name).write_text(contract + '\n# changed\n', encoding='utf-8')
                    elif failure == 'post-head':
                        git(target, 'commit', '--allow-empty', '-qm', 'changed HEAD during save')
                    else:
                        extra = path.with_suffix('') / 'part-099.properties'
                        extra.parent.mkdir(exist_ok=True)
                        extra.write_text('# competing file\n', encoding='utf-8')
                monkeypatch.setattr(sync_files, 'save_files', concurrent)
            if failure in {'none', 'reuse'}:
                assert publish_edit(plan, context) == (path,)
                assert path.read_text(encoding='utf-8') == proposed
                if failure == 'reuse':
                    with pytest.raises(ValueError, match='consumed'):
                        publish_edit(plan, context)
            else:
                with pytest.raises((OSError, ValueError), match='changed|injected'):
                    publish_edit(plan, context)
                assert path.read_bytes() == original + (b'# concurrent edit\n' if failure == 'source' else b'')
                if failure == 'callback':
                    assert load_model(path).authoritative['desired.row.007-001.comment'] == '合成 ID'
            assert context.closed
        assert (root / relative).read_bytes() == original


def check_properties_context_requires_managed_running_task(tmp_path, monkeypatch):
    from model.adapters.task import source_write_context
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    properties_fixture(tmp_path)
    with pytest.raises(ValueError, match='selected task contract missing'):
        with source_write_context(tmp_path, 'tasks/missing.md'):
            raise AssertionError('missing Task granted Model publication')


def deploy_properties_fixture(root):
    from model.format import serialize
    scope = properties_fixture(root)
    stacks = scope.path.with_name('cloudformation-stacks.properties')
    stacks.write_text(serialize({'desired.stack.009.name': 'CurrentName',
        'desired.stack.009.placementName': 'FixedPlacement', 'desired.stack.009.template': 'stack.yaml',
        'desired.stack.009.parameters': 'stack.json', 'desired.stack.009.deployOrder': '1'}), encoding='utf-8')
    tasks = root / 'tasks'
    tasks.mkdir()
    (tasks / 'active.md').write_text('''# Deploy fixture
## Task contract
- Task type: `infrastructure`
- Task status: `running`
## Validation scope
- `qa-synthetic/team-a/network`
''', encoding='utf-8')
    return scope, stacks


@pytest.mark.parametrize('field', ['display', 'reference', 'placement'])
def check_deploy_digest_covers_all_nonobserved_authority(tmp_path, monkeypatch, field):
    from deployment.session import design_digest, model_input_manifest
    from model.format import parse, patch
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    scope, stacks = deploy_properties_fixture(tmp_path)
    before = design_digest(tmp_path, scope.environment, scope.target)
    manifest = model_input_manifest(tmp_path, scope.environment, scope.target)
    original = scope.path.read_text(encoding='utf-8')
    scope.path.write_text(patch(parse(original), {'observed.row.007-001.value': 'vpc-observed'}), encoding='utf-8')
    assert design_digest(tmp_path, scope.environment, scope.target) == before
    assert model_input_manifest(tmp_path, scope.environment, scope.target) != manifest
    path, changes = scope.path, {'display.resource.007.label': 'Changed display'}
    if field == 'placement':
        path, changes = stacks, {'desired.stack.009.placementName': 'ChangedPlacement'}
    elif field == 'reference':
        spec = {'consumerKey': 'desired.row.007-001.value', 'text': '[Network](#network)', 'occurrence': '1',
                'producerKind': 'resource', 'producerScope': 'qa-synthetic/team-a/network', 'producerId': '007',
                'resourceType': 'EC2.VPC', 'format': 'link', 'labelPolicy': 'fixed'}
        changes = {f'desired.reference.stable.{key}': value for key, value in spec.items()}
    path.write_text(patch(parse(path.read_text(encoding='utf-8')), changes), encoding='utf-8')
    assert design_digest(tmp_path, scope.environment, scope.target) != before


@pytest.mark.parametrize('change', ['observed', 'desired', 'display', 'raw', 'concurrent'])
def check_deploy_observed_baseline_advances_only_proven_outputs(tmp_path, monkeypatch, change):
    from deployment.session import design_digest, verify_observed_transition, model_input_manifest
    from model.sources import authority_snapshot
    from model.format import parse, patch
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    before = authority_snapshot(tmp_path, scope.environment, scope.target)
    intended = design_digest(tmp_path, scope.environment, scope.target)
    prior_manifest = model_input_manifest(tmp_path, scope.environment, scope.target)
    original = scope.path.read_text(encoding='utf-8')
    changes = {'observed.row.007-001.value': 'vpc-new'}
    if change == 'desired':
        changes['desired.row.007-001.comment'] = 'unrelated edit'
    elif change == 'display':
        changes['display.resource.007.label'] = 'unrelated edit'
    output = patch(parse(original), changes)
    if change == 'raw':
        output += '# unrelated reformat\n'
    scope.path.write_text(output + ('# concurrent edit\n' if change == 'concurrent' else ''), encoding='utf-8')
    if change == 'observed':
        advanced = verify_observed_transition(tmp_path, scope.environment, scope.target, before, {scope.path: output}, intended)
        assert advanced != prior_manifest
        assert design_digest(tmp_path, scope.environment, scope.target) == intended
    else:
        with pytest.raises((RuntimeError, ValueError), match='non-observed|unrelated|outside authorized'):
            verify_observed_transition(tmp_path, scope.environment, scope.target, before, {scope.path: output}, intended)


def check_deploy_preparation_separates_producer_reads_from_writes(tmp_path, monkeypatch):
    from deploy_preparation import candidate
    from model.format import parse, patch, serialize
    from task_contract import paths_in
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    scope, stacks = deploy_properties_fixture(tmp_path)
    producer = scope.path.with_name('security.properties')
    producer.write_text(serialize({'desired.resource.009.resourceType': 'EC2.VPC',
        'desired.resource.009.anchor': 'security', 'desired.resource.009.resourceMode': 'IMPORT'}), encoding='utf-8')
    scope.path.write_text(patch(parse(scope.path.read_text(encoding='utf-8')), {
        'desired.row.007-002.property': 'EC2.VPC.Name',
        'desired.row.007-002.value': '[Producer](security.md#security)',
        'desired.row.007-002.comment': '合成参照'}), encoding='utf-8')
    text, sources, _, _ = candidate(tmp_path, 'tasks/deploy.md', scope.environment, scope.target,
        {'awsAccountId': '123456789012', 'alias': scope.target}, ['CurrentName'], ['network', 'cloudformation-stacks'])
    allowed = paths_in(text, '## Allowed paths')
    assert producer in sources
    assert producer.relative_to(tmp_path).as_posix() not in allowed
    assert 'project.json' not in allowed and tmp_path / 'project.json' in sources
    assert scope.path.relative_to(tmp_path).as_posix() in allowed
    assert stacks.relative_to(tmp_path).as_posix() in allowed


@pytest.mark.parametrize('failure', ['none', 'source', 'task', 'head', 'review', 'candidate', 'source-set', 'model-io', 'receipt', 'display-io', 'subprocess', 'source-crash', 'receipt-crash', 'display-crash', 'bind', 'replace'])
def check_properties_import_acquire_review_publish(monkeypatch, failure):
    from support.model_v2_fixtures import import_publication_case
    import_publication_case(monkeypatch, failure)



def check_properties_standalone_audit_has_no_framework_runtime(tmp_path, monkeypatch):
    from support.model_v2_fixtures import logs_fixture
    from model.audit import generate
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    model = logs_fixture(tmp_path)
    original = model.read_bytes()
    source, inputs, _ = generate(tmp_path, 'qa-synthetic', 'team-a', 'cloudwatch-logs')
    assert model.relative_to(tmp_path).as_posix() in inputs
    assert not any(path.endswith(('parameters.yaml', 'bindings.json', 'observed.json')) for path in inputs)
    output = tmp_path / 'standalone.py'
    output.write_text(source, encoding='utf-8')
    program = '''import sys,subprocess
from pathlib import Path
def forbidden(*args,**kwargs): raise AssertionError('audit setup called a subprocess')
subprocess.run=forbidden
namespace={'__name__':'standalone_audit_test'}
exec(compile(Path(sys.argv[1]).read_text(encoding='utf-8'),sys.argv[1],'exec'),namespace)
engine=namespace['engine'](namespace['SNAPSHOT'])
assert engine.service_module('cloudwatch-logs').one is engine.one
assert not any(name=='model' or name.startswith('model.') for name in sys.modules)
print('standalone audit engine: PASS')
'''
    checked = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(output)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert model.read_bytes() == original


@pytest.mark.parametrize('change', ['delete', 'merge', 'identity', 'observation', 'native', 'unselected'])
def check_properties_model_operation_preservation(tmp_path, monkeypatch, change):
    import shutil
    from support.model_v2_fixtures import role_operation_fixture
    from model.format import owner, serialize
    from model.operations import verify_model_operation
    from task_contract import ModelOperation, MergePair
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    before, after = tmp_path / 'before', tmp_path / 'after'
    scope, values = role_operation_fixture(before)
    shutil.copytree(before, after)
    identity = scope.environment, scope.target, scope.service
    source = '/'.join((*identity, '007'))
    destination = '/'.join((*identity, '008'))
    operation = ModelOperation('import-delete' if change == 'delete' else 'import-merge', identity,
        pairs=() if change == 'delete' else (MergePair(source, destination),),
        delete_source=source if change == 'delete' else None, delete_sources=(source,) if change == 'delete' else ())
    candidate = {key: value for key, value in values.items() if owner(key, values) != ('resource', '007')}
    if change != 'delete':
        candidate['observed.row.008-001.value'] = values['observed.row.007-001.value']
        candidate['desired.row.008-002.document'] = values['desired.row.007-002.document'].replace('[source](#source)', '[destination](#destination)')
    if change == 'identity':
        candidate['desired.resource.008.logicalId'] = 'changed'
    elif change == 'observation':
        candidate['observed.row.008-001.value'] = '`lost-source-identity`'
    elif change == 'native':
        candidate['desired.row.008-002.document'] = candidate['desired.row.008-002.document'].replace('[1, "1", false]', '[true, "1", false]')
    elif change == 'unselected':
        candidate['display.resource.009.comment'] = 'changed unrelated display'
    path = after / scope.path.relative_to(before)
    path.write_text(serialize(candidate), encoding='utf-8')
    sources = {scope.path.relative_to(before).as_posix()}
    if change in {'delete', 'merge'}:
        verify_model_operation(before, after, operation, sources)
    else:
        with pytest.raises(ValueError, match='identity|observation|undeclared|unspecified'):
            verify_model_operation(before, after, operation, sources)


@pytest.mark.parametrize('change', ['retarget', 'prefix', 'context-scope', 'context-text', 'format', 'rename-id'])
def check_properties_retarget_keeps_other_fragments_and_reference_ids(tmp_path, monkeypatch, change):
    import shutil
    from support.model_v2_fixtures import retarget_fixture
    from model.format import serialize
    from model.operations import verify_model_operation
    from task_contract import ModelOperation, ReferenceChange
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    before, after = tmp_path / 'before', tmp_path / 'after'
    scope, values = retarget_fixture(before)
    shutil.copytree(before, after)
    values['desired.row.001-001.value'] = 'qa-synthetic:123456789012:vpc-destination'
    values['desired.reference.resource-use.producerId'] = '008'
    values['desired.reference.resource-use.text'] = 'vpc-destination'
    if change == 'prefix':
        values['desired.row.001-001.value'] = 'changed-prefix:123456789012:vpc-destination'
    elif change == 'context-scope':
        values['desired.reference.context-use.producerScope'] = 'qa-synthetic/team-b'
    elif change == 'context-text':
        values['desired.reference.context-use.text'] = '123'
    elif change == 'format':
        values['desired.reference.resource-use.format'] = 'name'
    elif change == 'rename-id':
        values = {key.replace('desired.reference.resource-use.', 'desired.reference.renumbered.'): value for key, value in values.items()}
    path = after / scope.path.relative_to(before)
    path.write_text(serialize(values), encoding='utf-8')
    identity = scope.environment, scope.target, scope.service
    reference = ReferenceChange('/'.join((*identity, '001')), 'value',
        'qa-synthetic/team-a/network/007', 'qa-synthetic/team-a/network/008', 'EC2.SecurityGroup.VpcId')
    operation = ModelOperation('import-retarget', identity, references=(reference,))
    if change == 'retarget':
        verify_model_operation(before, after, operation, {path.relative_to(after).as_posix()})
    else:
        with pytest.raises(ValueError, match='affixes|another reference|format|fixed reference|renumber'):
            verify_model_operation(before, after, operation, {path.relative_to(after).as_posix()})


def old_python():
    return os.environ.get('BLUEPRINT_LEGACY_PYTHON', sys.executable)


@pytest.fixture(scope='module')
def old_checkout():
    checkout = os.environ.get('BLUEPRINT_LEGACY_FRAMEWORK')
    interpreter = os.environ.get('BLUEPRINT_LEGACY_PYTHON')
    if bool(checkout) != bool(interpreter):
        raise ValueError('fixed-old tests require both BLUEPRINT_LEGACY_FRAMEWORK and BLUEPRINT_LEGACY_PYTHON')
    if checkout:
        yield Path(checkout).resolve()
        return
    with tempfile.TemporaryDirectory(prefix='model-v2-old-framework-') as directory:
        old = Path(directory) / 'old'
        def git(*args):
            subprocess.run(['git', *args], check=True, capture_output=True, text=True)
        # A Framework-local convenience only; consumers supply the explicit fixed checkout/runtime pair.
        git('clone', '--shared', '--no-checkout', str(FRAMEWORK), str(old))
        git('-C', str(old), 'sparse-checkout', 'set', '--no-cone', '/framework/', '/.agents/', '/AGENTS.md', '/README.md')
        git('-C', str(old), 'checkout', '--detach', BASELINE)
        yield old


def legacy_fixture(root):
    root.mkdir()
    project = {'targets': [{'environment': 'qa-synthetic', 'alias': 'team-a', 'awsAccountId': '123456789012',
                            'awsExecutionAccountId': '999999999999', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}
    (root / 'project.json').write_text(json.dumps(project), encoding='utf-8')
    template = root / 'model/templates/team-a/network.properties.tpl'
    template.parent.mkdir(parents=True)
    template.write_text('''# model-template: 1
# input: Environment {"type":"string","description":"環境","required":true,"source":"consumer.environment"}
# definition: Vpc
# parameter: Name {"type":"string","description":"名前","required":true}
# resource: vpc
# row: id vpc
# row: name vpc
desired.resource.vpc.resourceType=EC2.VPC
desired.resource.vpc.logicalId=fixed-logical-id
desired.resource.vpc.anchor=network-fixed
desired.resource.vpc.resourceMode=IMPORT
desired.row.id.property=EC2.VPC.VpcId
desired.row.id.value=[Network](#network-fixed)
desired.row.id.comment=合成識別子
desired.row.name.property=EC2.VPC.Name
desired.row.name.value=<<Name>>-<<Environment>>
desired.row.name.comment=合成名称
# end-definition
''', encoding='utf-8')
    directory = root / 'model/parameters/qa-synthetic/team-a/network'
    directory.mkdir(parents=True)
    (directory / 'parameters.yaml').write_text('instances:\n  selected:\n    parameters:\n      Name: synthetic\n', encoding='utf-8')
    (directory / 'bindings.json').write_text(json.dumps({'instances': {'selected': {'definition': 'Vpc',
        'resources': {'vpc': '007'}, 'rows': {'id': '007-001', 'name': '007-002'}, 'parameters': {}}}}), encoding='utf-8')
    (directory / 'observed.json').write_text(json.dumps({'version': 1, 'values': {'observed.row.007-001.value': ''}}), encoding='utf-8')


def check_export_convert_and_strict_compare(old_checkout, tmp_path):
    root = tmp_path / 'source'
    legacy_fixture(root)
    template = root / 'model/templates/team-a/network.properties.tpl'
    text = template.read_text(encoding='utf-8')
    text = text.replace('# row: name vpc\n', '# row: name vpc\n# row: dynamic vpc\n# row: literal vpc\n# row: native vpc\n# row: opaque vpc\n')
    text = text.replace('# resource: vpc\n', '# parameter: Opaque {"type":"string","description":"literal data","required":true}\n# resource: vpc\n')
    opaque = '`{{resolve:secretsmanager:fixture:SecretString:password}}`'
    literal_link = '`[raw](https://example.invalid/item)`'
    text = text.replace('# end-definition',
        'desired.row.dynamic.property=EC2.VPC.CidrBlock\ndesired.row.dynamic.value=' + opaque + '\ndesired.row.dynamic.comment=opaque scalar\n'
        'desired.row.literal.property=EC2.VPC.InstanceTenancy\ndesired.row.literal.value=' + literal_link + '\ndesired.row.literal.comment=literal link\n'
        'desired.row.native.property=EC2.VPC.Tags\ndesired.row.native.value=`{"a":[1,false,"1"]}`\ndesired.row.native.comment=native JSON\n'
        'desired.row.opaque.property=EC2.VPC.DhcpOptionsId\ndesired.row.opaque.value=<<Opaque>>\ndesired.row.opaque.comment=literal token\n# end-definition')
    text += '\n# definition: Unused\n# resource: unused\n# row: name unused\n'
    text += 'desired.resource.unused.resourceType=Unsupported.Resource\ndesired.resource.unused.anchor=unused\n'
    text += 'desired.row.name.property=Unsupported.Resource.Name\ndesired.row.name.value=unused\ndesired.row.name.comment=unbound definition\n# end-definition\n'
    template.write_text(text, encoding='utf-8')
    binding = root / 'model/parameters/qa-synthetic/team-a/network/bindings.json'
    data = json.loads(binding.read_text())
    data['instances']['selected']['rows'].update(dynamic='007-003', literal='007-004', native='007-005', opaque='007-006')
    import copy
    data['instances']['duplicate'] = copy.deepcopy(data['instances']['selected'])
    data['instances']['duplicate']['resources']['vpc'] = '008'
    data['instances']['duplicate']['rows'] = {key: value.replace('007-', '008-') for key, value in data['instances']['selected']['rows'].items()}
    binding.write_text(json.dumps(data), encoding='utf-8')
    parameters = binding.with_name('parameters.yaml')
    parameters.write_text('instances:\n  selected:\n    parameters:\n      Name: synthetic\n      Opaque: "<<not-reparsed>>"\n  duplicate:\n    parameters:\n      Name: other\n      Opaque: "<<literal-two>>"\n', encoding='utf-8')
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    modules_before = set(sys.modules)
    exported = export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'export.json')
    assert 'model_templates' not in set(sys.modules) - modules_before
    assert exported['complete'] is True and exported['legacyRevision'] == BASELINE
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
    candidate = convert_export(exported, tmp_path / 'candidate')
    result = compare_export(exported, candidate)
    assert result == {'status': 'equivalent', 'modelFormat': 2, 'models': 1, 'designValidation': 'not-run'}
    model = load_model(Scope(candidate, 'qa-synthetic', 'team-a', 'network'))
    assert model.authoritative['observed.row.007-001.value'] == ''
    assert model.authoritative['desired.row.007-002.value'] == 'synthetic-qa-synthetic'
    assert not any(key.startswith('desired.reference.') for key in model.authoritative)
    assert model.authoritative['desired.row.007-003.value'] == opaque
    assert model.authoritative['desired.row.007-004.value'] == literal_link
    assert json.loads(model.authoritative['desired.row.007-005.value'][1:-1]) == {'a': [1, False, '1']}
    assert model.authoritative['desired.row.007-006.value'] == '<<not-reparsed>>'
    assert model.authoritative['desired.row.008-006.value'] == '<<literal-two>>'
    assert 'observed.row.008-001.value' not in model.authoritative
    assert exported['models'][0]['resourceOrder'] == ['007', '008']
    assert any(warning['code'] == 'reference.ambiguous_anchor' for warning in exported['models'][0]['warnings'])
    assert all('Unsupported.Resource' not in raw for raw in model.authoritative.values())
    original = template.read_bytes()
    template.write_bytes(original.replace(b'desired.row.opaque.value=<<Opaque>>', b'desired.row.opaque.value=<<Unknown>>'))
    with pytest.raises(ValueError, match='undeclared template variables: Vpc'):
        export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'unexpanded.json')
    assert not (tmp_path / 'unexpanded.json').exists()
    template.write_bytes(original)


@pytest.mark.parametrize('change', ['missing', 'reference', 'identity', 'observation', 'type'])
def check_migration_rejects_meaning_loss(old_checkout, tmp_path, change):
    root = tmp_path / 'source'
    legacy_fixture(root)
    exported = export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'export.json')
    candidate = convert_export(exported, tmp_path / 'candidate')
    path = candidate / 'model/qa-synthetic/team-a/network.properties'
    text = path.read_text(encoding='utf-8')
    if change == 'missing':
        text = text.replace('observed.row.007-001.value=\n', '')
    elif change == 'reference':
        text += ''.join('desired.reference.link.' + field + '=' + value + '\n' for field, value in {
            'consumerKey': 'desired.row.007-001.value', 'text': '[Network](#network-fixed)', 'occurrence': '1',
            'producerKind': 'resource', 'producerScope': 'qa-synthetic/team-a/network', 'producerId': '007',
            'resourceType': 'EC2.VPC', 'format': 'link', 'labelPolicy': 'fixed'}.items())
    elif change == 'identity':
        text = text.replace('fixed-logical-id', 'other-logical-id')
    elif change == 'observation':
        text = text.replace('observed.row.007-001.value=\n', 'observed.row.007-001.value=PENDING_DEPLOY\n')
    else:
        text = text.replace('resourceType=EC2.VPC', 'resourceType=EC2.Subnet')
    path.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError, match='authority differs'):
        compare_export(exported, candidate)


def check_export_retains_name_identifier_and_local_link(old_checkout, tmp_path):
    root = tmp_path / 'source'
    legacy_fixture(root)
    template = root / 'model/templates/team-a/network.properties.tpl'
    template.write_text(template.read_text(encoding='utf-8').replace('# model-template: 1\n',
        '# model-template: 1\n# input: Account {"type":"string","description":"実行先","required":true,"source":"consumer.executionAccountId"}\n') + '''# definition: Subnet
# reference: Vpc {"instance":"selected","resourceType":"EC2.VPC"}
# reference: RawName {"service":"network","resource":"007","resourceType":"EC2.VPC","format":"name"}
# reference: PhysicalId {"service":"network","resource":"007","resourceType":"EC2.VPC","format":"identifier","property":"EC2.VPC.VpcId"}
# resource: subnet
# row: id subnet
# row: vpc subnet
# row: tags subnet
desired.resource.subnet.resourceType=EC2.Subnet
desired.resource.subnet.logicalId=subnet-fixed
desired.resource.subnet.anchor=subnet-fixed
desired.resource.subnet.resourceMode=IMPORT
desired.row.id.property=EC2.Subnet.SubnetId
desired.row.id.value=[Subnet](#subnet-fixed)
desired.row.id.comment=合成識別子
desired.row.vpc.property=EC2.Subnet.VpcId
desired.row.vpc.value=<<Vpc>>
desired.row.vpc.comment=論理参照
desired.row.tags.property=EC2.Subnet.Tags
desired.row.tags.value=`[{"Key":"Name","Value":"prefix-<<RawName>>-<<RawName>>"},{"Key":"Id","Value":"<<PhysicalId>>"},{"Key":"Environment","Value":"<<Environment>>"},{"Key":"Account","Value":"<<Account>>"}]`
desired.row.tags.comment=参照付きJSON
# end-definition
''', encoding='utf-8')
    directory = root / 'model/parameters/qa-synthetic/team-a/network'
    binding = json.loads((directory / 'bindings.json').read_text(encoding='utf-8'))
    binding['instances']['child'] = {'definition': 'Subnet', 'resources': {'subnet': '008'},
        'rows': {'id': '008-001', 'vpc': '008-002', 'tags': '008-003'}, 'parameters': {}}
    (directory / 'bindings.json').write_text(json.dumps(binding), encoding='utf-8')
    (directory / 'observed.json').write_text(json.dumps({'version': 1, 'values': {
        'observed.row.007-001.value': '`vpc-physical`'}}), encoding='utf-8')
    exported = export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'export.json')
    candidate = convert_export(exported, tmp_path / 'candidate')
    model = load_model(Scope(candidate, 'qa-synthetic', 'team-a', 'network'))
    from model.references import declarations, usages
    specs = list(declarations(model.authoritative).values())
    assert {'literal', 'name', 'identifier', 'link'} <= {spec['format'] for spec in specs}
    contexts = [spec for spec in specs if spec['producerKind'] == 'context']
    assert len(contexts) == 1 and contexts[0]['contextProperty'] == 'executionAccountId'
    tags = json.loads(model.authoritative['desired.row.008-003.value'][1:-1])
    assert tags[2:] == [{'Key': 'Environment', 'Value': 'qa-synthetic'}, {'Key': 'Account', 'Value': '999999999999'}]
    names = [spec for spec in specs if spec['format'] == 'name']
    assert len(names) == 2 and {spec['occurrence'] for spec in names} == {'1', '2'}
    assert {spec['pointer'] for spec in names} == {'/0/Value'}
    assert all(spec['property'] == 'EC2.VPC.Name' for spec in names)
    identifiers = [spec for spec in specs if spec['format'] == 'identifier']
    assert len(identifiers) == 1 and identifiers[0]['text'] == 'vpc-physical'
    assert sum(usage.consumer_key == 'desired.row.008-002.value' for usage in usages(model)) == 1
    assert compare_export(exported, candidate)['status'] == 'equivalent'


def check_export_real_stack_links_root_names_and_retained_display(old_checkout, tmp_path):
    root = tmp_path / 'source'
    legacy_fixture(root)

    def service(name, definition, bindings):
        template = root / 'model/templates/team-a' / (name + '.properties.tpl')
        template.write_text('# model-template: 1\n# definition: Main\n' + definition + '\n# end-definition\n', encoding='utf-8')
        directory = root / 'model/parameters/qa-synthetic/team-a' / name
        directory.mkdir()
        (directory / 'parameters.yaml').write_text('instances: {}\n', encoding='utf-8')
        (directory / 'bindings.json').write_text(json.dumps(bindings), encoding='utf-8')

    def resource(kind, props):
        text = '# resource: main\ndesired.resource.main.resourceType=' + kind + '\n'
        text += 'desired.resource.main.logicalId=fixed\ndesired.resource.main.anchor=fixed\ndesired.resource.main.resourceMode=IMPORT\n'
        for number, (prop, value) in enumerate(props, 1):
            text += f'# row: r{number} main\ndesired.row.r{number}.property={kind}.{prop}\ndesired.row.r{number}.value={value}\ndesired.row.r{number}.comment=fixture\n'
        bindings = {'instances': {'main': {'definition': 'Main', 'resources': {'main': '001'},
                    'rows': {'r' + str(i): f'001-{i:03d}' for i in range(1, len(props) + 1)}, 'parameters': {}}}}
        return text, bindings

    for name, kind, props in [
        ('s3', 'S3.Bucket', [('BucketName', '`fixture-bucket`')]),
        ('kms', 'KMS.Key', [('Description', '`fixture-key`')]),
        ('codebuild', 'CodeBuild.Project', [('Name', '`fixture-project`'),
            ('Environment.EnvironmentVariables[].Name', '`nested-name`'),
            ('LogsConfig.CloudWatchLogs.GroupName', '`nested-group`')])]:
        text, bindings = resource(kind, props)
        service(name, text, bindings)
    stacks = ('# reference: Bucket {"service":"s3","resource":"001","resourceType":"S3.Bucket"}\n'
        'desired.stack.009.name=RenamedStack\ndesired.stack.009.template=stack.yaml\n'
        'desired.stack.009.parameters=stack.json\ndesired.stack.009.deployOrder=1\ndisplay.stack.009.comment=fixture\n'
        'desired.deployment.templateBucket=<<Bucket>>\ndesired.deployment.templateKeyPrefix=templates/\n'
        'desired.artifact.001.stack=RenamedStack\ndesired.artifact.001.resource=Function\n'
        'desired.artifact.001.property=Code\n'
        'desired.artifact.001.source=infra/cloudformation/artifacts/function.zip\n'
        'desired.artifact.001.bucket=<<Bucket>>\ndesired.artifact.001.keyPrefix=artifacts/\n')
    service('cloudformation-stacks', stacks, {'stacks': {'009': 'FixedPlacement'},
        'instances': {'main': {'definition': 'Main', 'resources': {}, 'rows': {}, 'parameters': {}}}})
    template = root / 'model/templates/team-a/network.properties.tpl'
    text = template.read_text(encoding='utf-8').replace('# resource: vpc',
        '# reference: Build {"service":"codebuild","resource":"001","resourceType":"CodeBuild.Project","format":"name"}\n'
        '# reference: Key {"service":"kms","resource":"001","resourceType":"KMS.Key"}\n'
        '# resource: vpc')
    text = text.replace('# end-definition', '# retained-display: 099\ndisplay.resource.099.comment=retained comment\n'
        'desired.note.001.text=<<Build>> <<Key>> <<Key>>\n# end-definition')
    template.write_text(text, encoding='utf-8')
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    exported = export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'export.json')
    candidate = convert_export(exported, tmp_path / 'candidate')
    assert compare_export(exported, candidate)['models'] == 5
    model = load_model(Scope(candidate, 'qa-synthetic', 'team-a', 'network'))
    from model.references import declarations
    specs = list(declarations(model.authoritative).values())
    assert [spec['property'] for spec in specs if spec['format'] == 'name'] == ['CodeBuild.Project.Name']
    keys = [spec for spec in specs if spec.get('resourceType') == 'KMS.Key']
    assert {spec['labelPolicy'] for spec in keys} == {'resource-id'}
    assert {spec['occurrence'] for spec in keys} == {'1', '2'}
    assert {spec['text'] for spec in keys} == {'[001](kms.md#fixed)'}
    assert model.authoritative['display.resource.099.comment'] == 'retained comment'
    assert 'desired.resource.099.resourceType' not in model.authoritative
    from model.core import entries
    assert list(dict(entries(model.authoritative, 'desired.resource.'))) == ['007']
    # Independent public legacy resolution establishes the expected label, not exporter metadata.
    program = "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import model_templates as m; print(m.load_for_analysis(Path(sys.argv[2])).values['desired.note.001.text'])"
    actual = subprocess.check_output([old_python(), '-I', '-B', '-c', program,
        str(old_checkout / 'framework/scripts'), str(root / 'model/qa-synthetic/team-a/network.properties')], text=True).strip()
    assert actual == 'fixture-project [001](kms.md#fixed) [001](kms.md#fixed)'
    assert model.authoritative['desired.note.001.text'] == actual
    stack = load_model(Scope(candidate, 'qa-synthetic', 'team-a', 'cloudformation-stacks'))
    assert stack.authoritative['desired.stack.009.placementName'] == 'FixedPlacement'
    bucket_refs = list(declarations(stack.authoritative).values())
    assert {spec['consumerKey'] for spec in bucket_refs} == {'desired.deployment.templateBucket', 'desired.artifact.001.bucket'}
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()} == before


def check_export_parent_runtime_isolated(old_checkout, tmp_path):
    root = tmp_path / 'source'
    legacy_fixture(root)
    program = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from model.migration.export import export_legacy
export_legacy(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5], Path(sys.argv[6]))
assert 'model_templates' not in sys.modules
assert 'model_parameter_inputs' not in sys.modules
"""
    result = subprocess.run([sys.executable, '-I', '-B', '-c', program,
        str(Path(__file__).resolve().parents[2]), str(old_checkout), old_python(),
        str(root), BASELINE, str(tmp_path / 'export.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def check_pending_journal_stops_export_without_recovery(old_checkout, tmp_path):
    import base64
    from model.sources import publication_lock
    root = tmp_path / 'source'
    legacy_fixture(root)
    file = root / 'model/parameters/qa-synthetic/team-a/network/parameters.yaml'
    original = file.read_bytes()
    with publication_lock(root, read_only=True) as journal:
        journal.write_text(json.dumps({'root': str(root.resolve()), 'originals': {
            file.relative_to(root).as_posix(): base64.b64encode(b'recovery must not run').decode()}}), encoding='utf-8')
    try:
        with pytest.raises(ValueError, match='pending Model publication recovery'):
            export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'export.json')
        assert file.read_bytes() == original and journal.is_file()
        assert not (tmp_path / 'export.json').exists()
    finally:
        journal.unlink()  # Only this test's artificial journal; the OS lock is untouched.


@pytest.mark.parametrize('change', ['bytes', 'file-set'])
def check_legacy_export_rejects_changed_inputs(old_checkout, tmp_path, monkeypatch, change):
    import model.migration.export as exporting
    root = tmp_path / 'source'
    legacy_fixture(root)
    insertion = ("(root / 'model/parameters/qa-synthetic/team-a/network/parameters.yaml').write_text('concurrent change', encoding='utf-8')"
                 if change == 'bytes' else "(root / 'model/concurrent.properties').write_text('concurrent change', encoding='utf-8')")
    # Deterministic child-boundary injection exercises the real end snapshot comparison.
    monkeypatch.setattr(exporting, 'CHILD', exporting.CHILD.replace('    finish = inputs()', '    ' + insertion + '\n    finish = inputs()'))
    with pytest.raises(ValueError, match='legacy inputs changed during export'):
        export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'export.json')
    changed = root / ('model/parameters/qa-synthetic/team-a/network/parameters.yaml' if change == 'bytes' else 'model/concurrent.properties')
    assert changed.read_text(encoding='utf-8') == 'concurrent change'
    assert not (tmp_path / 'export.json').exists()


def check_export_file_failure_leaves_no_partial_result(old_checkout, tmp_path, monkeypatch):
    import os
    root = tmp_path / 'source'
    legacy_fixture(root)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    def fail(*args):
        raise OSError('injected export publication failure')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='injected export publication'):
        export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'export.json')
    assert not (tmp_path / 'export.json').exists()
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before


def check_fixed_stack_placement_is_distinct_from_name(old_checkout, tmp_path):
    root = tmp_path / 'source'
    legacy_fixture(root)
    template = root / 'model/templates/team-a/cloudformation-stacks.properties.tpl'
    template.write_text('''# model-template: 1
# definition: Stacks
desired.stack.009.name=RenamedStack
desired.stack.009.template=stack.yaml
desired.stack.009.parameters=stack.json
desired.stack.009.deployOrder=1
display.stack.009.comment=合成配置
# end-definition
''', encoding='utf-8')
    directory = root / 'model/parameters/qa-synthetic/team-a/cloudformation-stacks'
    directory.mkdir()
    (directory / 'parameters.yaml').write_text('instances: {}\n', encoding='utf-8')
    (directory / 'bindings.json').write_text(json.dumps({'stacks': {'009': 'OriginalPlacement'},
        'instances': {'stacks': {'definition': 'Stacks', 'resources': {}, 'rows': {}, 'parameters': {}}}}), encoding='utf-8')
    exported = export_legacy(old_checkout, old_python(), root, BASELINE, tmp_path / 'export.json')
    candidate = convert_export(exported, tmp_path / 'candidate')
    model = load_model(Scope(candidate, 'qa-synthetic', 'team-a', 'cloudformation-stacks'))
    assert model.authoritative['desired.stack.009.name'] == 'RenamedStack'
    assert model.authoritative['desired.stack.009.placementName'] == 'OriginalPlacement'
    assert 'desired.stack.009.placementName' not in model.values
    assert compare_export(exported, candidate)['models'] == 2


@pytest.mark.parametrize('change', ['none', 'desired', 'reference', 'row', 'import', 'io', 'task', 'concurrent'])
def check_managed_observation_preserves_exact_authority(monkeypatch, change):
    from model.adapters.task import observed_write_context
    from model.observed import prepare_observed
    from model.operations import prepare_edit, publish_edit
    from model.format import parse, patch, serialize
    from support.worktree_task_fixtures import fixture, git, start
    from task_contract import selected_task
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    with fixture() as root:
        scope = properties_fixture(root)
        values = dict(load_model(scope).authoritative)
        values['desired.resource.007.resourceMode'] = 'CREATE'
        values['desired.row.007-002.property'] = 'EC2.VPC.Name'
        values['desired.row.007-002.value'] = 'synthetic'
        values['desired.row.007-002.comment'] = '合成名前'
        scope.path.write_text(serialize(values) + '# preserve original trailing comment  \n', encoding='utf-8')
        relative = scope.path.relative_to(root).as_posix()
        git(root, 'add', 'model', 'project.json')
        git(root, 'commit', '-qm', 'synthetic CREATE observation')
        target, state = start(root, files=(relative,))
        name, path = state['task_file'], target / relative
        listed = ''.join('- `' + item + '`\n' for item in (name, relative))
        contract = '''# Observation fixture
## Task contract
- Task type: `design`
- Task status: `running`
- Workflow: `update`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`
## Validation scope
- `qa-synthetic/team-a/network`
## Required changes
- [R1] Synthetic selected observation
## Acceptance checks
- [R1] `exists:project.json`
'''
        for heading in ('Modified files', 'Allowed paths'):
            contract += '\n## ' + heading + '\n' + listed
        (target / name).write_text(contract, encoding='utf-8')
        if change == 'import':
            path.write_text(path.read_text(encoding='utf-8').replace('resourceMode=CREATE', 'resourceMode=IMPORT'), encoding='utf-8')
        original = path.read_bytes()
        key = 'observed.row.007-001.value'
        with selected_task(target, name), observed_write_context(target, {path: {key: '`vpc-updated`'}}) as context:
            snapshot = load_model(path, context.snapshot)
            if change == 'import':
                with pytest.raises(ValueError, match='IMPORT physical identity'):
                    prepare_observed(snapshot, {key: '`vpc-updated`'}, context)
                return
            if change in {'desired', 'reference', 'row'}:
                proposed = {key: '`vpc-updated`'}
                if change == 'desired':
                    proposed['display.resource.007.label'] = 'unapproved display'
                elif change == 'reference':
                    proposed.update({'desired.reference.r01.' + field: value for field, value in {
                        'consumerKey': 'desired.row.007-002.value', 'text': 'synthetic', 'occurrence': '1',
                        'producerKind': 'resource', 'producerScope': 'qa-synthetic/team-a/network', 'format': 'name',
                        'producerId': '007', 'resourceType': 'EC2.VPC', 'property': 'EC2.VPC.Name', 'labelPolicy': 'none'}.items()})
                else:
                    proposed['observed.row.007-002.value'] = 'unselected row'
                with pytest.raises(ValueError, match='non-observed|outside the authorized selection'):
                    prepare_edit(snapshot, {path: patch(snapshot.documents[path], proposed)}, context)
                assert path.read_bytes() == original
                return
            plan = prepare_observed(snapshot, {key: '`vpc-updated`'}, context)
            if change == 'io':
                import sync_files
                def fail(files):
                    path.write_bytes(b'partial')
                    raise OSError('injected observed I/O failure')
                monkeypatch.setattr(sync_files, 'save_files', fail)
            elif change == 'task':
                (target / name).write_text(contract + '\n# changed\n', encoding='utf-8')
            elif change == 'concurrent':
                path.write_bytes(original + b'# concurrent\n')
            if change == 'none':
                publish_edit(plan, context)
                assert path.read_text(encoding='utf-8') == patch(parse(original.decode('utf-8')), {key: '`vpc-updated`'})
                assert dict(load_model(path).authoritative) == {**snapshot.authoritative, key: '`vpc-updated`'}
            else:
                with pytest.raises((OSError, ValueError), match='changed|injected'):
                    publish_edit(plan, context)
                assert path.read_bytes() == original + (b'# concurrent\n' if change == 'concurrent' else b'')
        assert (root / relative).read_bytes() == original


@pytest.mark.parametrize('change', ['none', 'baseline', 'paths', 'export', 'export-meaning', 'candidate', 'project', 'iac', 'issues'])
def check_limited_format_migration_contract(old_checkout, tmp_path, change, monkeypatch):
    import shutil
    from model.migration.contract import migration_contract, verify_migration
    from import_guard import snapshots
    from support.worktree_task_fixtures import git
    from task_contract import selected_task
    from issue_gate import task_issue_errors
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    root = tmp_path / 'source'
    legacy_fixture(root)
    if change == 'none':
        for name in ('AGENTS.md', 'README.md', 'docs/system-overview.md'):
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('# Synthetic format-migration fixture\n', encoding='utf-8')
        for name in ('docs/designs', 'infra', 'tests/scenarios', 'tests/results'):
            (root / name).mkdir(parents=True, exist_ok=True)
    issue = root / 'issues/qa-synthetic/team-a/issues.md'
    issue.parent.mkdir(parents=True)
    issue.write_text('### network\n1. Existing design problem remains unresolved.\n', encoding='utf-8')
    iac = root / 'infra/qa-synthetic/team-a/stack.yaml'
    iac.parent.mkdir(parents=True)
    iac.write_text('Resources: {}\n', encoding='utf-8')
    (root / '.gitignore').write_text('tasks/**\n', encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'config', 'commit.gpgsign', 'false')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'fixed legacy sources and existing issue')
    baseline = git(root, 'rev-parse', 'HEAD')
    export = tmp_path / 'export.json'
    value = export_legacy(old_checkout, old_python(), root, BASELINE, export)
    candidate = convert_export(value, tmp_path / 'candidate')
    original_export = json.loads(json.dumps(value))
    shutil.rmtree(root / 'model')
    shutil.copytree(candidate / 'model', root / 'model')
    paths = frozenset(filter(None, git(root, 'diff', '--no-renames', '--name-only').splitlines())) | frozenset(
        filter(None, git(root, 'ls-files', '--others', '--exclude-standard', '--', 'model').splitlines()))
    descriptor = {'baseline': baseline, 'legacyRevision': BASELINE, 'oldCheckout': str(old_checkout),
        'oldPython': old_python(), 'exportPath': str(export), 'exportSha256': hashlib.sha256(export.read_bytes()).hexdigest(),
        'fromVersion': 1, 'toVersion': 2, 'services': ['qa-synthetic/team-a/network'], 'paths': sorted(paths)}
    listed = ''.join('- `' + path + '`\n' for path in sorted(paths | {'tasks/migrate.md'}))
    if change == 'baseline':
        descriptor['baseline'] = '0' * 40
    elif change == 'export':
        export.write_bytes(export.read_bytes() + b' ')
    elif change == 'export-meaning':
        value['models'][0]['authoritative']['desired.row.007-002.value'] = 'fabricated baseline'
        export.write_text(json.dumps(value), encoding='utf-8')
        descriptor['exportSha256'] = hashlib.sha256(export.read_bytes()).hexdigest()
    elif change == 'candidate':
        path = root / 'model/qa-synthetic/team-a/network.properties'
        path.write_text(path.read_text(encoding='utf-8').replace('synthetic-qa-synthetic', 'changed'), encoding='utf-8')
    elif change == 'project':
        (root / 'project.json').write_bytes((root / 'project.json').read_bytes() + b'\n')
    elif change == 'iac':
        iac.write_text('changed\n', encoding='utf-8')
    elif change == 'issues':
        issue.unlink()
    contract_text = '''# One-time format migration
## Task contract
- Task type: `migration`
- Task status: `running`
- Workflow: `model-format-migration`
- Model format migration: `properties-v2`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`
## Validation scope
- `qa-synthetic/team-a/network`
## Required changes
- [R1] Exact format equivalence
## Acceptance checks
- [R1] `check:model.format-migration`
## Model format migration
- ''' + json.dumps(descriptor) + '\n## Modified files\n' + listed + '\n## Allowed paths\n' + listed
    contract = migration_contract(contract_text)
    (root / 'tasks').mkdir()
    (root / 'tasks/migrate.md').write_text(contract_text, encoding='utf-8')
    modules_before = set(sys.modules)
    with snapshots(root, baseline, {}, definitions_root=FRAMEWORK) as (before, after):
        if change == 'none':
            assert verify_migration(root, before, after, contract, baseline, paths) == ()
            with selected_task(root, 'tasks/migrate.md'):
                assert task_issue_errors(root, {('qa-synthetic', 'team-a', 'network')}) == []
            assert 'Existing design problem remains unresolved.' in issue.read_text(encoding='utf-8')
            from validation.runner import Validator
            from types import SimpleNamespace
            from contextlib import redirect_stdout
            import io
            scope = {('qa-synthetic', 'team-a', 'network')}
            final = SimpleNamespace(base_commit=baseline, changed_paths=paths, scope=scope)
            for final_candidate in (None, final):
                with selected_task(root, 'tasks/migrate.md'), redirect_stdout(io.StringIO()):
                    validator = Validator(root, scope=scope, definitions_root=FRAMEWORK, final_candidate=final_candidate)
                    result = validator.run()
                assert result == 0, validator.errors
                assert validator.findings.result('model.format-migration', scope).status == 'PASS'
                assert 'Existing design problem remains unresolved.' in issue.read_text(encoding='utf-8')
        else:
            with pytest.raises(ValueError, match='migration|authority differs|legacy export'):
                verify_migration(root, before, after, contract, baseline, paths - {next(iter(paths))} if change == 'paths' else paths)
    assert 'model_templates' not in set(sys.modules) - modules_before
    assert compare_export(original_export, candidate)['designValidation'] == 'not-run'


@pytest.mark.parametrize('change', ['display', 'create', 'import-config', 'fixed-id', 'missing-task', 'cli'])
def check_ordinary_properties_edit_uses_real_task_guard(monkeypatch, tmp_path, change):
    from model.adapters.task import edit_write_context
    from model.operations import prepare_edit, publish_edit
    from model.format import patch, serialize
    from model.cli import main
    from support.worktree_task_fixtures import fixture, git, start
    from task_contract import selected_task
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    with fixture() as root:
        import shutil
        from support.it_workspace import copy_framework
        copy_framework(root / "framework/materials", relative="materials")
        mapping = root / "framework/mappings/aws/owners.json"
        mapping.parent.mkdir(parents=True)
        shutil.copyfile(FRAMEWORK / "framework/mappings/aws/owners.json", mapping)
        scope = properties_fixture(root)
        if change == 'create':
            values = dict(load_model(scope).authoritative)
            values['desired.resource.007.resourceMode'] = 'CREATE'
            scope.path.write_text(serialize(values), encoding='utf-8')
        relative = scope.path.relative_to(root).as_posix()
        git(root, 'add', 'model', 'project.json', 'framework')
        git(root, 'commit', '-qm', 'synthetic editable Model')
        target, state = start(root, files=(relative,))
        name, path = state['task_file'], target / relative
        listed = ''.join('- `' + item + '`\n' for item in (name, relative))
        contract = '# Ordinary Model edit\n## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n## Validation scope\n- `qa-synthetic/team-a/network`\n## Required changes\n- [R1] Explicit candidate edit\n## Acceptance checks\n- [R1] `exists:project.json`\n'
        for heading in ('Modified files', 'Allowed paths'):
            contract += '\n## ' + heading + '\n' + listed
        (target / name).write_text(contract, encoding='utf-8')
        original = path.read_bytes()
        fields = {'display.resource.007.label': 'explicit display'}
        if change in {'create', 'import-config'}:
            fields = {'desired.row.007-001.value': '[another](other.md#other)'}
        elif change == 'fixed-id':
            fields = {'desired.resource.007.anchor': 'changed-fixed-anchor'}
        if change == 'missing-task':
            (target / name).unlink()
            with pytest.raises(ValueError, match='selected task contract missing'):
                with edit_write_context(target, {('qa-synthetic', 'team-a', 'network')}, name):
                    raise AssertionError('missing Task granted source write')
            return
        with selected_task(target, name):
            if change == 'cli':
                before = load_model(path)
                candidate = tmp_path / 'candidate' / relative
                candidate.parent.mkdir(parents=True)
                candidate.write_text(patch(before.documents[path], fields), encoding='utf-8')
                assert main(['edit', str(path), '--candidate', str(tmp_path / 'candidate'), '--task-file', name]) == 0
            else:
                with edit_write_context(target, {('qa-synthetic', 'team-a', 'network')}, name) as context:
                    before = load_model(path, context.snapshot)
                    candidate = patch(before.documents[path], fields)
                    if change in {'import-config', 'fixed-id'}:
                        with pytest.raises(ValueError, match='IMPORT configuration|fixed identity'):
                            plan = prepare_edit(before, {path: candidate}, context)
                            publish_edit(plan, context)
                        assert path.read_bytes() == original
                    else:
                        publish_edit(prepare_edit(before, {path: candidate}, context), context)
                        assert path.read_text(encoding='utf-8') == candidate
        assert (root / relative).read_bytes() == original


def check_distribution_manifest_covers_deletions_support_and_fixed_blobs(tmp_path):
    from model.migration.distribution import distribution_manifest
    from support.worktree_task_fixtures import git
    root = tmp_path / 'framework-only'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'config', 'commit.gpgsign', 'false')
    files = {'AGENTS.md': 'old authority\n', 'README.md': 'same bytes\n',
        'framework/scripts/model/cli.py': 'entry\n', 'framework/scripts/requirements.txt': 'requirements\n',
        'framework/scripts/tests/run_it.py': 'runner\n', 'framework/scripts/tests/CASES.md': 'cases\n',
        'framework/scripts/tests/support/fixture.py': 'support\n',
        '.agents/skills/env-diff/SKILL.md': 'retired\n'}
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'old distribution')
    baseline = git(root, 'rev-parse', 'HEAD')
    (root / 'AGENTS.md').write_text('properties authority\n', encoding='utf-8')
    (root / '.agents/skills/env-diff/SKILL.md').unlink()
    added = root / 'framework/scripts/tests/integrations/new.checks.py'
    added.parent.mkdir(parents=True)
    added.write_text('new same-revision tests\n', encoding='utf-8')
    (root / 'framework/scripts/tests/run_it.py').chmod(0o755)
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'new distribution')
    revision = git(root, 'rev-parse', 'HEAD')
    (root / 'AGENTS.md').write_text('uncommitted text must not enter the manifest\n', encoding='utf-8')
    output = tmp_path / 'manifest.json'
    result = distribution_manifest(root, baseline, revision, output)
    assert json.loads(output.read_text(encoding='utf-8')) == result
    assert result['frameworkRevision'] == revision and result['copyPerformed'] is False
    changes = {record['path']: record for record in result['changes']}
    assert {path: record['action'] for path, record in changes.items()} == {
        'AGENTS.md': 'overwrite', '.agents/skills/env-diff/SKILL.md': 'delete',
        'framework/scripts/tests/integrations/new.checks.py': 'add', 'framework/scripts/tests/run_it.py': 'overwrite'}
    assert changes['AGENTS.md']['after']['sha256'] == hashlib.sha256(b'properties authority\n').hexdigest()
    assert changes['.agents/skills/env-diff/SKILL.md']['after'] is None
    assert changes['framework/scripts/tests/run_it.py']['after']['gitMode'] == '100755'
    inventory = {record['path']: record for record in result['files']}
    assert {'README.md', 'framework/scripts/tests/support/fixture.py', 'framework/scripts/requirements.txt'} <= inventory.keys()
    assert {record['revision'] for record in inventory.values()} == {revision}
    with pytest.raises(ValueError, match='new external'):
        distribution_manifest(root, baseline, revision, output)
    with pytest.raises(ValueError, match='new external'):
        distribution_manifest(root, baseline, revision, root / 'manifest.json')


@pytest.mark.parametrize('failure', [None, 'review', 'draft', 'candidate', 'acquisition', 'baseline',
                                    'approval-expired', 'source-save', 'display-save', 'task-baseline'])
def check_publication_transaction_without_host(monkeypatch, failure):
    from support.model_v2_fixtures import import_publication_case
    action = {None: 'none', 'review': 'post-review', 'draft': 'post-draft', 'candidate': 'post-candidate',
              'acquisition': 'post-acquisition', 'baseline': 'post-baseline', 'approval-expired': 'post-expiry',
              'source-save': 'receipt', 'display-save': 'display-io', 'task-baseline': 'post-task'}[failure]
    import_publication_case(monkeypatch, action)


def check_saved_display_recovery_needs_no_new_approval(monkeypatch):
    from support.model_v2_fixtures import import_publication_case
    import_publication_case(monkeypatch, 'display-io')


@pytest.mark.parametrize('change', ['property', 'destination', 'resource', 'selector'])
def check_candidate_review_mismatch_rejected_without_host(monkeypatch, change):
    from support.model_v2_fixtures import import_publication_case
    action = {'property': 'candidate', 'destination': 'selection-target', 'resource': 'candidate-resource',
              'selector': 'candidate-reference'}[change]
    import_publication_case(monkeypatch, action)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
