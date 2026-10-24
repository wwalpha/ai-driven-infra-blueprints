"""Model reader, publisher, CLI and Review integration over synthetic properties."""

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch as mock_patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import subprocess
import tempfile

import model.core as _imports_model_core
import model.identity as _imports_model_identity
import model.importing.approval as _imports_model_importing_approval
import model.observed as _imports_model_observed
import model.operations as _imports_model_operations
import model.sources as _imports_model_sources
import pytest
import support.repository_fixtures as _imports_support_repository_fixtures
import sync_files as _imports_sync_files
from generation_inputs import GenerationInputs
from model.adapters.task import (
    edit_write_context,
    observed_write_context,
    source_write_context,
)
from model.audit import generate
from model.cli import main
from model.core import validate_authority, validate_runtime_keys
from model.format import FORMAT, INDEX, owner, parse, patch, serialize
from model.format import split as split
from model.importing.approval import (
    build_review,
    review_binding,
    verify_review,
)
from model.operations import verify_model_operation
from model.references import declarations, diagnose, incoming, usages
from model.sources import Scope, list_models, load_model, runtime_values, source_scope
from support.model_sources import catalog_display
from support.model_v2_fixtures import (
    FRAMEWORK,
    acquisition_fixture,
    logs_fixture,
    properties_fixture,
    retarget_fixture,
    role_operation_fixture,
    source_context,
)
from support.model_v2_fixtures import format_fixture as fixture
from support.sync_model_fixtures import build_generated_policy
from sync_runtime import generate_views, stage_inputs
from task_contract_core import MergePair, ModelOperation, ReferenceChange, selected_task
from utils.aws_mappings import mapping_alias
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.input_cache import input_context, recording_inputs

import model as _imports_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_discovery_alias_and_account():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first, _ = fixture(root)
        assert [scope.target for scope in list_models(root)] == ['one']
        second, _ = fixture(root, target='two')
        third, _ = fixture(root, target='222222222222')
        assert {scope.target for scope in list_models(root)} == {'one', 'two', '222222222222'}
        assert {scope.environment for scope in list_models(root)} == {'qa-custom', 'qa-custom-single'}
        assert load_model(first).scope.path != load_model(second).scope.path
        assert all('999999999999' not in str(scope.path) for scope in list_models(root))
        assert load_model(third).scope.target == '222222222222'
    for environment in ('templates', 'parameters'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, values = fixture(root, environment=environment, service='network.v1')
            part = scope.path.with_suffix('') / 'part-001.properties'
            part.parent.mkdir()
            part.write_text(serialize(values), encoding='utf-8')
            scope.path.write_text(FORMAT + '\n' + INDEX + '\n# part: network.v1/part-001.properties\n', encoding='utf-8')
            assert source_scope(root, part) == scope
            assert load_model(scope).authoritative == values
            assert [item.environment for item in list_models(root)] == [environment]
            project = root / 'project.json'
            retained = root / 'project-original.json'
            project.rename(retained)
            project.symlink_to(retained)
            with mock_patch.object(Path, 'read_bytes', side_effect=AssertionError('symlink input was read')):
                with pytest.raises(ValueError, match='unsafe'):
                    load_model(scope)


def check_runtime_metadata_is_not_authority():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        model = load_model(scope)
        assert model.values['observed.row.007-001.property'] == values['desired.row.007-001.property']
        assert 'observed.row.007-001.property' not in model.authoritative
        assert model.values['observed.row.007-001.value'] == ''
        del values['observed.row.007-001.value']
        scope.path.write_text(serialize(values), encoding='utf-8')
        assert 'observed.row.007-001.value' not in load_model(scope).values
        values['observed.row.007-001.value'] = 'PENDING_DEPLOY'
        scope.path.write_text(serialize(values), encoding='utf-8')
        assert load_model(scope).values['observed.row.007-001.value'] == 'PENDING_DEPLOY'


def check_parts_and_large_resource():
    assert owner('desired.service.network.serviceId', {}) == owner('display.service.title', {})
    assert owner('desired.deployment.templateBucket', {}) == owner('desired.deployment.templateKeyPrefix', {})
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        for index in range(3, 220):
            values.update({f'desired.row.007-{index:03d}.{field}': value for field, value in (
                ('property', 'EC2.VPC.Name'), ('value', 'example'), ('comment', '合成行'))})
        values.update({'desired.resource.008.resourceType': 'EC2.VPC', 'desired.resource.008.logicalId': 'EC2_VPC_002', 'desired.resource.008.anchor': 'resource-EC2_VPC_002', 'desired.service.identity.lastAllocated': '{"EC2.VPC":2}'})
        output = split(scope.path, values)
        assert output[scope.path].splitlines()[1] == INDEX
        assert len(next(text for path, text in output.items() if path != scope.path).splitlines()) > 600
        for path, text in output.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        assert load_model(scope).authoritative == values
        part = scope.path.with_suffix('') / 'part-002.properties'
        renamed = part.with_name('part-003.properties')
        part.rename(renamed)
        scope.path.write_text(output[scope.path].replace('part-002', 'part-003'), encoding='utf-8')
        assert load_model(scope).authoritative == values


@pytest.mark.parametrize('failure', ['missing', 'duplicate', 'unlisted', 'escape', 'symlink', 'split', 'duplicate-key'])
def check_unsafe_parts(failure):
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        part = scope.path.with_suffix('') / 'part-001.properties'
        part.parent.mkdir()
        part.write_text(serialize(values), encoding='utf-8')
        index = FORMAT + '\n' + INDEX + '\n# part: network/part-001.properties\n'
        if failure == 'missing':
            part.unlink()
        elif failure == 'duplicate':
            index += '# part: network/part-001.properties\n'
        elif failure == 'escape':
            index = index.replace('network/part-001', '../part-001')
        elif failure == 'symlink':
            part.unlink()
            part.symlink_to(scope.root / 'project.json')
        else:
            extra = part.with_name('part-003.properties')
            extra.write_text(serialize({'desired.resource.007.logicalId': 'EC2_VPC_001'}), encoding='utf-8')
            if failure != 'unlisted':
                index += '# part: network/part-003.properties\n'
            if failure == 'split':
                del values['desired.resource.007.logicalId']
                part.write_text(serialize(values), encoding='utf-8')
        scope.path.write_text(index, encoding='utf-8')
        with pytest.raises(ValueError):
            load_model(scope)


def check_reference_schema_and_pointer():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        key = 'desired.row.007-002.value'
        values[key] = '`{"value":"vpc-one"}`'
        spec = {'consumerKey': key, 'pointer': '/value', 'text': 'vpc-one', 'occurrence': '1',
                'producerKind': 'resource', 'producerScope': 'qa-custom/one/network', 'producerLogicalId': 'EC2_VPC_001',
                'resourceType': 'EC2.VPC', 'format': 'identifier', 'property': 'EC2.VPC.VpcId', 'labelPolicy': 'none'}
        values.update({f'desired.reference.stable.{field}': value for field, value in spec.items()})
        scope.path.write_text(serialize(values), encoding='utf-8')
        model = load_model(scope)
        assert declarations(model.authoritative) == {'stable': spec}
        warnings, _ = diagnose(model)
        assert warnings and 'nonempty non-ARN' in warnings[0]['message']
        broken = {**values, 'desired.reference.stable.pointer': '/missing'}
        with pytest.raises(ValueError, match='existing string leaf'):
            declarations(broken)
        for orphan in ('display.resource.999.comment', 'display.stack.999.comment'):
            broken = {key: value for key, value in values.items() if key != 'desired.reference.stable.pointer'}
            broken[orphan] = 'vpc-one'
            broken['desired.reference.stable.consumerKey'] = orphan
            with pytest.raises(ValueError, match='consumer owner is absent'):
                declarations(broken)


def check_cli_subprocess_and_canonical_imports():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        cli = Path(__file__).resolve().parents[2] / 'model/cli.py'
        environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        result = subprocess.run([sys.executable, '-I', '-B', str(cli), 'read', str(scope.path)],
                                capture_output=True, text=True, env=environment, cwd=directory)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['authoritative'] == values
        result = subprocess.run([sys.executable, '-I', '-B', str(cli), 'trace', str(scope.path), 'desired.resource.007.logicalId'],
                                capture_output=True, text=True, env=environment, cwd=directory)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['value'] == 'EC2_VPC_001'
        source_load = _imports_model_sources.load_model

        public_load = _imports_model.load_model
        assert public_load is source_load
        assert source_load(scope).__class__ is load_model(scope).__class__


def check_stack_metadata_is_not_runtime_input():
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        stack = Scope(scope.root, scope.environment, scope.target, 'cloudformation-stacks')
        values = {'desired.stack.009.name': 'NewStackName', 'desired.stack.009.placementName': 'OriginalPlacement',
                  'desired.stack.009.template': 'stack.yaml', 'desired.stack.009.parameters': 'stack.json',
                  'desired.stack.009.deployOrder': '1', 'desired.service.cloudformation-stacks.serviceId': 'cloudformation-stacks',
                  'desired.service.cloudformation-stacks.ownedCatalogResourceTypes': 'CloudFormation.Stack',
                  'desired.note.001.text': '保存する設計注記'}
        stack.path.write_text(serialize(values), encoding='utf-8')
        model = load_model(stack)
        assert model.authoritative['desired.stack.009.placementName'] == 'OriginalPlacement'
        assert 'desired.stack.009.placementName' not in model.values
        stack_model = _imports_model_core.stack_model
        assert stack_model(model.values)[1][0][1]['name'] == 'NewStackName'
        assert 'placementName' not in stack_model(model.authoritative)[1][0][1]
        assert model.authoritative['desired.note.001.text'] == model.values['desired.note.001.text']
        validate_authority = _imports_model_core.validate_authority
        for placement in ('', 'invalid_name', None):
            bad = {**values, 'desired.stack.009.placementName': placement}
            if placement is None:
                del bad['desired.stack.009.placementName']
            with pytest.raises(ValueError, match='placementName'):
                validate_authority(bad)
        with pytest.raises(TypeError):
            model.authoritative['desired.stack.009.name'] = 'mutated'


def check_observed_byte_preservation_and_one_use():
    prepare_observed = _imports_model.prepare_observed
    publish_edit = _imports_model.publish_edit
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        snapshot, context = source_context(scope)
        original = scope.path.read_bytes()
        try:
            plan = prepare_observed(snapshot, {'observed.row.007-001.value': 'vpc-new'}, context)
            assert plan.candidate.authoritative['observed.row.007-001.value'] == 'vpc-new'
            publish_edit(plan, context)
            assert scope.path.read_bytes() == original.replace(b'observed.row.007-001.value=\n', b'observed.row.007-001.value=vpc-new\n')
            with pytest.raises(ValueError, match='consumed'):
                publish_edit(plan, context)
        finally:
            context.close()


def _callback_check_source_save_conflict_and_rollback_fail(scope, write, /, path, *args, **kwargs):
    if path == scope.path:
        write(path, 'partial write', encoding='utf-8')
        raise OSError('injected I/O failure')
    return write(path, *args, **kwargs)


@pytest.mark.parametrize('failure', ['source', 'task', 'io'])
def check_source_save_conflict_and_rollback(failure, monkeypatch):
    prepare_observed = _imports_model.prepare_observed
    publish_edit = _imports_model.publish_edit
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        snapshot, context = source_context(scope)
        original = scope.path.read_bytes()
        plan = prepare_observed(snapshot, {'observed.row.007-001.value': 'vpc-new'}, context)
        if failure == 'source':
            scope.path.write_bytes(original + b'# concurrent change\n')
        elif failure == 'task':
            task = scope.root / 'tasks/example.md'
            task.parent.mkdir(exist_ok=True)
            task.write_text('changed', encoding='utf-8')
        else:
            write = Path.write_text
            fail = _bind_framework_callback(_callback_check_source_save_conflict_and_rollback_fail, scope, write)
            monkeypatch.setattr(Path, 'write_text', fail)
        with pytest.raises((ValueError, OSError)):
            publish_edit(plan, context)
        assert context.closed
        assert scope.path.read_bytes() == original + (b'# concurrent change\n' if failure == 'source' else b'')


def check_observed_cannot_bypass_import_or_change_authority():
    prepare_edit = _imports_model.prepare_edit
    prepare_observed = _imports_model.prepare_observed
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        snapshot, context = source_context(scope, imported=True)
        try:
            with pytest.raises(ValueError, match='IMPORT physical identity'):
                prepare_observed(snapshot, {'observed.row.007-001.value': 'vpc-other'}, context)
            with pytest.raises(ValueError, match='observed.row'):
                prepare_observed(snapshot, {'desired.row.007-001.value': 'changed'}, context)
            with pytest.raises(ValueError, match='unregistered'):
                prepare_edit(snapshot, {scope.path.with_name('other.properties'): FORMAT + '\n'}, context)
            with pytest.raises(ValueError, match='names and flags'):
                prepare_edit(snapshot, {}, {'approved': True})
        finally:
            context.close()


def check_declared_and_direct_links_coalesce_or_retain_conflicts():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        key = 'desired.row.007-001.value'
        spec = {'consumerKey': key, 'text': values[key], 'occurrence': '1',
                'producerKind': 'resource', 'producerScope': 'qa-custom/one/network', 'producerLogicalId': 'EC2_VPC_001',
                'resourceType': 'EC2.VPC', 'format': 'link', 'labelPolicy': 'fixed'}
        values.update({f'desired.reference.stable.{field}': value for field, value in spec.items()})
        scope.path.write_text(serialize(values), encoding='utf-8')
        model = load_model(scope)
        assert len([usage for usage in usages(model) if usage.consumer_key == key]) == 1
        values.update({'desired.resource.008.resourceType': 'EC2.VPC', 'desired.resource.008.logicalId': 'EC2_VPC_002', 'desired.resource.008.anchor': 'resource-EC2_VPC_002', 'desired.service.identity.lastAllocated': '{"EC2.VPC":2}',
                       'desired.reference.stable.producerLogicalId': 'EC2_VPC_002'})
        scope.path.write_text(serialize(values), encoding='utf-8')
        original = scope.path.read_bytes()
        model = load_model(scope)
        assert len([usage for usage in usages(model) if usage.consumer_key == key]) == 2
        assert any('both meanings' in warning['message'] for warning in model.warnings)
        assert len(incoming(model, '007')) == len(incoming(model, '008')) == 1
        assert scope.path.read_bytes() == original
        values['desired.reference.stable.producerLogicalId'] = 'EC2_VPC_001'
        values['desired.resource.008.logicalId'] = values['desired.resource.007.logicalId']
        scope.path.write_text(serialize(values), encoding='utf-8')
        with pytest.raises(ValueError, match='duplicate logicalId'):
            load_model(scope)
        assert parse(scope.path.read_text()).values[key] == values[key]


def check_reference_occurrence_identifies_overlapping_text():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        key = 'desired.row.007-002.value'
        values[key] = 'aaa'
        spec = {'consumerKey': key, 'text': 'aa', 'occurrence': '2',
                'producerKind': 'resource', 'producerScope': 'qa-custom/one/network', 'producerLogicalId': 'EC2_VPC_001',
                'resourceType': 'EC2.VPC', 'format': 'name', 'property': 'EC2.VPC.Name', 'labelPolicy': 'none'}
        values.update({f'desired.reference.stable.{field}': value for field, value in spec.items()})
        scope.path.write_text(serialize(values), encoding='utf-8')
        matches = [usage for usage in usages(load_model(scope)) if usage.metadata_id == 'stable']
        assert len(matches) == 1 and matches[0].start == 1 and matches[0].end == 3




@pytest.mark.parametrize('action', ['add', 'refresh', 'bind', 'replace'])
def check_properties_import_review_operations(action):
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        values['observed.row.007-001.value'] = 'vpc-original' if action != 'bind' else 'PENDING_DEPLOY'
        values['desired.row.007-002.value'] = '10.0.0.0/16'
        scope.path.write_text(serialize(values), encoding='utf-8')
        before = load_model(scope)
        rid = '008' if action == 'add' else '007'
        acquisition, selection = acquisition_fixture(before, action=action, resource=rid)
        after = dict(before.authoritative)
        if action == 'add':
            after.update({key.replace('.007.', '.008.').replace('.007-', '.008-'): value.replace('#network', '#added')
                          for key, value in values.items()})
            allocate = _imports_model_identity.allocate
            del after['desired.resource.008.logicalId']
            after = allocate(after, ['008'])
            after['desired.row.008-001.value'] = '[EC2_VPC_002](network.md#resource-EC2_VPC_002)'
        after[f'observed.row.{rid}-001.value'] = acquisition['records'][0]['identity']
        review = build_review(acquisition, selection, before, after, {'record-one': []}, lambda prop: {'type': 'string'})
        assert review['version'] == 4 and len(review['dispositions']) == 1
        assert review['dispositions'][0]['operation'] == action
        assert review['dispositions'][0]['physicalId'] == acquisition['records'][0]['identity']
        verify_review(review, review)
        assert review_binding(review, acquisition)['version'] == 2
        assert scope.path.read_text(encoding='utf-8') == serialize(values)


@pytest.mark.parametrize('change', ['delete-selected', 'delete-unselected', 'move-unselected', 'meaning'])
def check_properties_reference_review_after_map_and_ownership(change):
    build_review = _imports_model_importing_approval.build_review
    reference_provenance = _imports_model_importing_approval.reference_provenance
    verify_review = _imports_model_importing_approval.verify_review
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        values.update({'desired.resource.008.resourceType': 'EC2.VPC', 'desired.resource.008.logicalId': 'EC2_VPC_002', 'desired.resource.008.anchor': 'resource-EC2_VPC_002', 'desired.service.identity.lastAllocated': '{"EC2.VPC":2}',
            'desired.resource.008.resourceMode': 'IMPORT', 'desired.row.008-001.property': 'EC2.VPC.VpcId',
            'desired.row.008-001.value': '[EC2_VPC_002](network.md#resource-EC2_VPC_002)', 'desired.row.008-001.comment': '合成',
            'observed.row.008-001.value': 'vpc-second', 'observed.row.007-001.value': 'vpc-original'})
        spec = {'consumerKey': 'desired.row.007-001.value', 'text': values['desired.row.007-001.value'], 'occurrence': '1',
                'producerKind': 'resource', 'producerScope': 'qa-custom/one/network', 'producerLogicalId': 'EC2_VPC_001',
                'resourceType': 'EC2.VPC', 'format': 'link', 'labelPolicy': 'fixed'}
        values.update({f'desired.reference.stable.{field}': value for field, value in spec.items()})
        scope.path.write_text(serialize(values), encoding='utf-8')
        before = load_model(scope)
        acquisition, selection = acquisition_fixture(before)
        proposed = {} if change.startswith('delete') else {'stable': {**spec,
            **({'consumerKey': 'desired.row.008-001.value', 'text': '[EC2_VPC_002](network.md#resource-EC2_VPC_002)'} if change == 'move-unselected'
               else {'producerLogicalId': 'EC2_VPC_002', 'labelPolicy': 'display-name'})}}
        if change == 'delete-unselected':
            acquisition['records'][0]['identity'] = 'vpc-second'
            acquisition['records'][0]['properties']['EC2.VPC.VpcId']['value'] = 'vpc-second'
            selection['resources'][0]['resource'] = '008'
        if change in {'delete-unselected', 'move-unselected'}:
            with pytest.raises(ValueError, match='unselected'):
                build_review(acquisition, selection, before, dict(values), {'record-one': []},
                             lambda prop: {'type': 'string'}, proposed_references=proposed)
        else:
            review = build_review(acquisition, selection, before, dict(values), {'record-one': []},
                                  lambda prop: {'type': 'string'}, proposed_references=proposed)
            assert review['referenceProvenance']['before'] == {'stable': spec}
            assert review['referenceProvenance']['after'] == proposed
            unchanged = build_review(acquisition, selection, before, dict(values), {'record-one': []}, lambda prop: {'type': 'string'})
            assert unchanged['referenceProvenance']['after'] == reference_provenance(before)
            with pytest.raises(ValueError, match='changed or stale'):
                verify_review(review, unchanged)




def check_runtime_projection_validation_and_metadata_separation():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        projected = runtime_values(values)
        validate_runtime_keys(projected)
        with pytest.raises(ValueError, match='unknown Model field'):
            validate_authority(projected)
        projected['observed.row.007-001.comment'] = 'different from desired'
        with pytest.raises(ValueError, match='derived observed metadata'):
            validate_runtime_keys(projected)


def check_stack_render_cli_uses_only_canonical_modules():
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        stack = Scope(scope.root, scope.environment, scope.target, 'cloudformation-stacks')
        stack.path.write_text(serialize({'desired.stack.009.name': 'NewStackName',
            'desired.stack.009.placementName': 'FixedPlacement', 'desired.stack.009.template': 'stack.yaml',
            'desired.stack.009.parameters': 'stack.json', 'desired.stack.009.deployOrder': '1',
            'display.stack.009.comment': '合成表示'}), encoding='utf-8')
        scripts = Path(__file__).resolve().parents[2]
        program = '''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])

from model import load_model,render_model
from model.importing.approval import build_review
from model.importing.references import Resolver
from model.adapters.task import source_write_context
snapshot=load_model(Path(sys.argv[2]))
rendered=render_model(snapshot,None)
assert not any(name.startswith('model_') for name in sys.modules), sorted(sys.modules)
assert 'NewStackName' in next(iter(rendered.values()))
assert 'FixedPlacement' not in next(iter(rendered.values()))
print(json.dumps({'rendered':len(rendered)}))
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(scripts), str(stack.path)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {'rendered': 1}
        result = subprocess.run([sys.executable, '-I', '-B', str(scripts / 'model/cli.py'), 'render', str(stack.path)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert 'NewStackName' in next(iter(json.loads(result.stdout).values()))
        assert not (scope.root / 'docs/designs').exists()


def check_incoming_missing_producer_does_not_match_unrelated_metadata(tmp_path):
    scope, values = fixture(tmp_path)
    key = 'desired.row.007-002.value'
    values[key] = 'original missing'
    for identity, producer, text in (('stable-one', '007', 'original'), ('stable-two', '009', 'missing')):
        for field, value in {'consumerKey': key, 'text': text, 'occurrence': '1',
                'producerKind': 'resource', 'producerScope': '/'.join((scope.environment, scope.target, scope.service)),
                'producerLogicalId': 'EC2_VPC_' + ('001' if producer == '007' else producer), 'resourceType': 'EC2.VPC', 'format': 'name',
                'property': 'EC2.VPC.Name', 'labelPolicy': 'none'}.items():
            values['desired.reference.' + identity + '.' + field] = value
    scope.path.write_text(serialize(values), encoding='utf-8')
    uses = incoming(load_model(scope), 'EC2_VPC_009')
    assert len(uses) == 1 and uses[0][1].logical_id == 'EC2_VPC_009'
    assert uses[0][1].text == 'missing'


def check_properties_normal_generation_uses_new_authority(tmp_path, monkeypatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    root = tmp_path / 'synthetic'
    root.mkdir()
    framework = Path(__file__).resolve().parents[4]
    with catalog_display(), mapping_alias(framework, root):
        _ = build_generated_policy(root, definitions_root=framework)
        model = root / 'model/dev/123456789012/iam.properties'
        design = root / 'docs/designs/dev/123456789012/iam.md'
        artifact = design.with_suffix('') / 'iam-role-001-trust-policy.json'
        before = {path: path.read_bytes() for path in (model, design, artifact)}
        inputs = GenerationInputs(root, framework)
        try:
            stage = inputs.open_stage()
            with recording_inputs(inputs):
                snapshot = load_model(model, inputs)
                stage_inputs(stage, root, {design: snapshot.values}, [model], [design], ['iam'], False, inputs, framework)
                failures = []
                generated = generate_views(stage, root, {design: snapshot.values}, failures, framework)
            assert not failures, failures
            assert generated[design]
            assert (stage / model.relative_to(root)).read_bytes() == before[model]
            assert (stage / artifact.relative_to(root)).read_bytes() == before[artifact]
            assert (stage / design.relative_to(root)).read_bytes() == before[design]
            assert not (stage / 'framework').exists()
            assert all(not any(name in path.parts for name in ('templates', 'parameters')) for path in inputs.contents
                       if path.is_relative_to(root / 'model'))
            inputs.verify()
        finally:
            inputs.close()
        assert {path: path.read_bytes() for path in before} == before



def _callback_check_managed_properties_save_fail_callback(path, proposed, /):
    assert path.read_text(encoding='utf-8') == proposed
    assert load_model(path).authoritative['desired.row.007-001.comment'] == '中間保存'
    raise ValueError('injected source completion callback failure')


def _callback_check_managed_properties_save_fail(path, /, files):
    path.write_bytes(b'partial')
    raise OSError('injected publication failure')


def _callback_check_managed_properties_save_concurrent(contract, failure, git, name, path, save, target, /, files):
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


@pytest.mark.parametrize('failure', ['none', 'task', 'source', 'unregistered', 'reuse', 'io', 'head', 'post-dependency', 'post-task', 'post-head', 'post-file-set', 'callback', 'process-death'])
def check_managed_properties_save(monkeypatch, failure):
    fixture = _imports_support_repository_fixtures.fixture
    git = _imports_support_repository_fixtures.git
    start = _imports_support_repository_fixtures.start

    prepare_edit = _imports_model.prepare_edit
    publish_edit = _imports_model.publish_edit
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
## Model delete sources
- `qa-synthetic/team-a/network/007`
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
            EditPlan = _imports_model_operations.EditPlan
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
                program = "import sys, os\nfrom pathlib import Path\nsys.path[:0] = [sys.argv[1], str(Path(sys.argv[1]) / 'tests')]\nfrom task_contract import selected_task\nfrom model.adapters.task import source_write_context\nfrom model.sources import load_model\nfrom model.operations import prepare_edit, publish_edit\nfrom model.format import patch\nimport sync_files\nroot, name, path = Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])\ndef crash(outputs):\n    path.write_bytes(b'partial child bytes')\n    os._exit(17)\nfrom support.publication_fixtures import publication_repository\nwith publication_repository(), selected_task(root, name), source_write_context(root, name) as context:\n    snapshot = load_model(path, context.snapshot)\n    candidate = patch(snapshot.documents[path], {'desired.row.007-001.comment': 'child candidate'})\n    plan = prepare_edit(snapshot, {path: candidate}, context)\n    sync_files.save_files = crash\n    publish_edit(plan, context)\n"
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
                fail_callback = _bind_framework_callback(_callback_check_managed_properties_save_fail_callback, path, proposed)
                context._finish = fail_callback
            elif failure == 'io':
                sync_files = _imports_sync_files
                fail = _bind_framework_callback(_callback_check_managed_properties_save_fail, path)
                monkeypatch.setattr(sync_files, 'save_files', fail)
            elif failure == 'head':
                git(target, 'commit', '--allow-empty', '-qm', 'changed HEAD')
            elif failure.startswith('post-'):
                sync_files = _imports_sync_files
                save = sync_files.save_files
                concurrent = _bind_framework_callback(_callback_check_managed_properties_save_concurrent, contract, failure, git, name, path, save, target)
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
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    properties_fixture(tmp_path)
    with pytest.raises(ValueError, match='selected task contract missing'):
        with source_write_context(tmp_path, 'tasks/missing.md'):
            raise AssertionError('missing Task granted Model publication')



def check_properties_standalone_audit_has_no_framework_runtime(tmp_path, monkeypatch):
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

    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    before, after = tmp_path / 'before', tmp_path / 'after'
    scope, values = role_operation_fixture(before)
    shutil.copytree(before, after)
    identity = scope.environment, scope.target, scope.service
    source = '/'.join((*identity, '007'))
    destination = '/'.join((*identity, '008'))
    operation = ModelOperation('import-delete' if change == 'delete' else 'import-merge', identity,
        pairs=() if change == 'delete' else (MergePair(source, destination),),
        delete_sources=(source,) if change == 'delete' else ())
    candidate = {key: value for key, value in values.items() if owner(key, values) != ('resource', '007')}
    if change != 'delete':
        candidate['observed.row.008-001.value'] = values['observed.row.007-001.value']
        candidate['desired.row.008-002.document'] = values['desired.row.007-002.document'].replace('[role](#role-source)', '[role](#role-destination)')
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
        with pytest.raises(ValueError, match='identity|logicalId|observation|undeclared|unspecified'):
            verify_model_operation(before, after, operation, sources)



@pytest.mark.parametrize('change', ['retarget', 'prefix', 'context-scope', 'context-text', 'format', 'rename-id'])
def check_properties_retarget_keeps_other_fragments_and_reference_ids(tmp_path, monkeypatch, change):

    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    before, after = tmp_path / 'before', tmp_path / 'after'
    scope, values = retarget_fixture(before)
    shutil.copytree(before, after)
    values['desired.row.001-001.value'] = 'qa-synthetic:123456789012:vpc-destination'
    values['desired.reference.resource-use.producerLogicalId'] = 'EC2_VPC_008'
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



def _callback_check_managed_observation_preserves_exact_authority_fail(path, /, files):
    path.write_bytes(b'partial')
    raise OSError('injected observed I/O failure')


@pytest.mark.parametrize('change', ['none', 'desired', 'reference', 'row', 'import', 'io', 'task', 'concurrent'])
def check_managed_observation_preserves_exact_authority(monkeypatch, change):
    prepare_observed = _imports_model_observed.prepare_observed
    prepare_edit = _imports_model_operations.prepare_edit
    publish_edit = _imports_model_operations.publish_edit
    fixture = _imports_support_repository_fixtures.fixture
    git = _imports_support_repository_fixtures.git
    start = _imports_support_repository_fixtures.start
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
                        'producerLogicalId': 'EC2_VPC_001', 'resourceType': 'EC2.VPC', 'property': 'EC2.VPC.Name', 'labelPolicy': 'none'}.items()})
                else:
                    proposed['observed.row.007-002.value'] = 'unselected row'
                with pytest.raises(ValueError, match='non-observed|outside the authorized selection'):
                    prepare_edit(snapshot, {path: patch(snapshot.documents[path], proposed)}, context)
                assert path.read_bytes() == original
                return
            plan = prepare_observed(snapshot, {key: '`vpc-updated`'}, context)
            if change == 'io':
                sync_files = _imports_sync_files
                fail = _bind_framework_callback(_callback_check_managed_observation_preserves_exact_authority_fail, path)
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



@pytest.mark.parametrize('change', ['display', 'create', 'import-config', 'fixed-id', 'missing-task', 'cli'])
def check_ordinary_properties_edit_uses_real_task_guard(monkeypatch, tmp_path, change):
    prepare_edit = _imports_model_operations.prepare_edit
    publish_edit = _imports_model_operations.publish_edit
    fixture = _imports_support_repository_fixtures.fixture
    git = _imports_support_repository_fixtures.git
    start = _imports_support_repository_fixtures.start
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    with fixture() as root:
        scope = properties_fixture(root)
        if change == 'create':
            values = dict(load_model(scope).authoritative)
            values['desired.resource.007.resourceMode'] = 'CREATE'
            scope.path.write_text(serialize(values), encoding='utf-8')
        relative = scope.path.relative_to(root).as_posix()
        git(root, 'add', 'model', 'project.json')
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
            fields = {'desired.row.007-001.value': '[corrected](network.md#network-existing)'}
        elif change == 'fixed-id':
            fields = {'desired.resource.007.logicalId': 'EC2_VPC_002', 'desired.service.identity.lastAllocated': '{"EC2.VPC":2}'}
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
                    publish_edit(prepare_edit(before, {path: candidate}, context), context)
                    assert path.read_text(encoding='utf-8') == candidate
        assert (root / relative).read_bytes() == original


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
