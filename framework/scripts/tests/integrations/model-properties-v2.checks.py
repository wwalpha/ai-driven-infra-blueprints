"""Model reader, publisher, CLI and Review integration over synthetic properties."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import json
import tempfile
import pytest
from model.format import FORMAT, INDEX, parse, patch, serialize, split
from model.sources import Scope, load_model, list_models
from model.references import declarations, diagnose
from support.model_v2_fixtures import format_fixture as fixture, source_context, acquisition_fixture

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
    from model.sources import source_scope
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
            from unittest.mock import patch as mock_patch
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
    from model.format import owner
    assert owner('desired.service.network.serviceId', {}) == owner('display.service.title', {})
    assert owner('desired.deployment.templateBucket', {}) == owner('desired.deployment.templateKeyPrefix', {})
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        for index in range(3, 220):
            values.update({f'desired.row.007-{index:03d}.{field}': value for field, value in (
                ('property', 'EC2.VPC.Name'), ('value', 'example'), ('comment', '合成行'))})
        values.update({'desired.resource.008.resourceType': 'EC2.VPC', 'desired.resource.008.anchor': 'second'})
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
            extra.write_text(serialize({'desired.resource.007.anchor': 'split'}), encoding='utf-8')
            if failure != 'unlisted':
                index += '# part: network/part-003.properties\n'
            if failure == 'split':
                del values['desired.resource.007.anchor']
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
                'producerKind': 'resource', 'producerScope': 'qa-custom/one/network', 'producerId': '007',
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
    import os
    import subprocess
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        cli = Path(__file__).resolve().parents[2] / 'model/cli.py'
        environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        result = subprocess.run([sys.executable, '-I', '-B', str(cli), 'read', str(scope.path)],
                                capture_output=True, text=True, env=environment, cwd=directory)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['authoritative'] == values
        result = subprocess.run([sys.executable, '-I', '-B', str(cli), 'trace', str(scope.path), 'desired.resource.007.anchor'],
                                capture_output=True, text=True, env=environment, cwd=directory)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['value'] == 'network'
        from model import load_model as public_load
        from model.sources import load_model as source_load
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
        from model.core import stack_model
        assert stack_model(model.values)[1][0][1]['name'] == 'NewStackName'
        assert 'placementName' not in stack_model(model.authoritative)[1][0][1]
        assert model.authoritative['desired.note.001.text'] == model.values['desired.note.001.text']
        from model.core import validate_authority
        for placement in ('', 'invalid_name', None):
            bad = {**values, 'desired.stack.009.placementName': placement}
            if placement is None:
                del bad['desired.stack.009.placementName']
            with pytest.raises(ValueError, match='placementName'):
                validate_authority(bad)
        with pytest.raises(TypeError):
            model.authoritative['desired.stack.009.name'] = 'mutated'


def check_observed_byte_preservation_and_one_use():
    from model import prepare_observed, publish_edit
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


@pytest.mark.parametrize('failure', ['source', 'task', 'io'])
def check_source_save_conflict_and_rollback(failure, monkeypatch):
    from model import prepare_observed, publish_edit
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        snapshot, context = source_context(scope)
        original = scope.path.read_bytes()
        plan = prepare_observed(snapshot, {'observed.row.007-001.value': 'vpc-new'}, context)
        if failure == 'source':
            scope.path.write_bytes(original + b'# concurrent change\n')
        elif failure == 'task':
            task = scope.root / 'tasks/active.md'
            task.parent.mkdir(exist_ok=True)
            task.write_text('changed', encoding='utf-8')
        else:
            write = Path.write_text
            def fail(path, *args, **kwargs):
                if path == scope.path:
                    write(path, 'partial write', encoding='utf-8')
                    raise OSError('injected I/O failure')
                return write(path, *args, **kwargs)
            monkeypatch.setattr(Path, 'write_text', fail)
        with pytest.raises((ValueError, OSError)):
            publish_edit(plan, context)
        assert context.closed
        assert scope.path.read_bytes() == original + (b'# concurrent change\n' if failure == 'source' else b'')


def check_observed_cannot_bypass_import_or_change_authority():
    from model import prepare_observed, prepare_edit
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
    from model.references import usages, incoming
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        key = 'desired.row.007-001.value'
        spec = {'consumerKey': key, 'text': values[key], 'occurrence': '1',
                'producerKind': 'resource', 'producerScope': 'qa-custom/one/network', 'producerId': '007',
                'resourceType': 'EC2.VPC', 'format': 'link', 'labelPolicy': 'fixed'}
        values.update({f'desired.reference.stable.{field}': value for field, value in spec.items()})
        scope.path.write_text(serialize(values), encoding='utf-8')
        model = load_model(scope)
        assert len([usage for usage in usages(model) if usage.consumer_key == key]) == 1
        values.update({'desired.resource.008.resourceType': 'EC2.VPC', 'desired.resource.008.anchor': 'other',
                       'desired.reference.stable.producerId': '008'})
        scope.path.write_text(serialize(values), encoding='utf-8')
        original = scope.path.read_bytes()
        model = load_model(scope)
        assert len([usage for usage in usages(model) if usage.consumer_key == key]) == 2
        assert any('both meanings' in warning['message'] for warning in model.warnings)
        assert len(incoming(model, '007')) == len(incoming(model, '008')) == 1
        assert scope.path.read_bytes() == original
        values['desired.reference.stable.producerId'] = '007'
        values['desired.resource.008.anchor'] = values['desired.resource.007.anchor']
        scope.path.write_text(serialize(values), encoding='utf-8')
        ambiguous = load_model(scope)
        assert len([usage for usage in usages(ambiguous) if usage.consumer_key == key]) == 2
        assert any('ambiguous' in warning['message'] for warning in ambiguous.warnings)
        assert ambiguous.authoritative[key] == values[key]


def check_reference_occurrence_identifies_overlapping_text():
    from model.references import usages
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        key = 'desired.row.007-002.value'
        values[key] = 'aaa'
        spec = {'consumerKey': key, 'text': 'aa', 'occurrence': '2',
                'producerKind': 'resource', 'producerScope': 'qa-custom/one/network', 'producerId': '007',
                'resourceType': 'EC2.VPC', 'format': 'name', 'property': 'EC2.VPC.Name', 'labelPolicy': 'none'}
        values.update({f'desired.reference.stable.{field}': value for field, value in spec.items()})
        scope.path.write_text(serialize(values), encoding='utf-8')
        matches = [usage for usage in usages(load_model(scope)) if usage.metadata_id == 'stable']
        assert len(matches) == 1 and matches[0].start == 1 and matches[0].end == 3


@pytest.mark.parametrize('legacy', ['templates', 'parameters'])
def check_normal_reader_rejects_legacy_authorities(legacy):
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        (scope.root / 'model' / legacy).mkdir()
        with pytest.raises(ValueError, match='explicit migration'):
            load_model(scope)
        with pytest.raises(ValueError, match='explicit migration'):
            list_models(scope.root)


@pytest.mark.parametrize('action', ['add', 'refresh', 'bind', 'replace'])
def check_properties_import_review_operations(action):
    from model.importing.approval import build_review, verify_review, review_binding
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
            after['desired.resource.008.anchor'] = 'added'
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
    from model.importing.approval import build_review, reference_provenance, verify_review
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        values.update({'desired.resource.008.resourceType': 'EC2.VPC', 'desired.resource.008.anchor': 'second',
            'desired.resource.008.resourceMode': 'IMPORT', 'desired.row.008-001.property': 'EC2.VPC.VpcId',
            'desired.row.008-001.value': '[Second](#second)', 'desired.row.008-001.comment': '合成',
            'observed.row.008-001.value': 'vpc-second', 'observed.row.007-001.value': 'vpc-original'})
        spec = {'consumerKey': 'desired.row.007-001.value', 'text': '[Network](#network)', 'occurrence': '1',
                'producerKind': 'resource', 'producerScope': 'qa-custom/one/network', 'producerId': '007',
                'resourceType': 'EC2.VPC', 'format': 'link', 'labelPolicy': 'fixed'}
        values.update({f'desired.reference.stable.{field}': value for field, value in spec.items()})
        scope.path.write_text(serialize(values), encoding='utf-8')
        before = load_model(scope)
        acquisition, selection = acquisition_fixture(before)
        proposed = {} if change.startswith('delete') else {'stable': {**spec,
            **({'consumerKey': 'desired.row.008-001.value', 'text': '[Second](#second)'} if change == 'move-unselected'
               else {'producerId': '008', 'labelPolicy': 'display-name'})}}
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


@pytest.mark.parametrize('kind', ['acquisition', 'review', 'binding', 'checkpoint'])
def check_properties_import_rejects_legacy_evidence(kind):
    from model.importing.approval import require_format
    with pytest.raises(ValueError, match='format is incompatible'):
        require_format({'version': {'acquisition': 2, 'review': 3, 'binding': 1, 'checkpoint': 1}[kind]},
                       {'acquisition': 3, 'review': 4, 'binding': 2, 'checkpoint': 2}[kind], kind)


def check_runtime_projection_validation_and_metadata_separation():
    from model.core import validate_authority, validate_runtime_keys
    from model.sources import runtime_values
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
    import subprocess
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
    from model.references import incoming
    scope, values = fixture(tmp_path)
    key = 'desired.row.007-002.value'
    values[key] = 'original missing'
    for identity, producer, text in (('stable-one', '007', 'original'), ('stable-two', '009', 'missing')):
        for field, value in {'consumerKey': key, 'text': text, 'occurrence': '1',
                'producerKind': 'resource', 'producerScope': '/'.join((scope.environment, scope.target, scope.service)),
                'producerId': producer, 'resourceType': 'EC2.VPC', 'format': 'name',
                'property': 'EC2.VPC.Name', 'labelPolicy': 'none'}.items():
            values['desired.reference.' + identity + '.' + field] = value
    scope.path.write_text(serialize(values), encoding='utf-8')
    uses = incoming(load_model(scope), '009')
    assert len(uses) == 1 and uses[0][1].producer_id == '009'
    assert uses[0][1].text == 'missing'


def check_properties_normal_generation_uses_new_authority(tmp_path, monkeypatch):
    from support.sync_model_fixtures import build_generated_policy
    from support.model_sources import catalog_display
    from generation_inputs import GenerationInputs
    from validation_cache import recording_inputs
    from sync_runtime import stage_inputs, generate_views
    from utils.aws_mappings import mapping_alias
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    root = tmp_path / 'synthetic'
    root.mkdir()
    framework = Path(__file__).resolve().parents[4]
    with catalog_display():
        values = build_generated_policy(root, definitions_root=framework)
        model = root / 'model/dev/123456789012/iam.properties'
        design = root / 'docs/designs/dev/123456789012/iam.md'
        artifact = design.with_suffix('') / 'app-role-trust-policy.json'
        before = {path: path.read_bytes() for path in (model, design, artifact)}
        with mapping_alias(framework, root):
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


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
