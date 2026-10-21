#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
from model.identity import allocate
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from support.validator import diagnostics

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import io
import json
import os
import shutil
import threading
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
import pytest
import sync_progress as progress
import sync_runtime
import sync_views
import model.render as model_design
import model.validation as model_validation
import model.projection as model_projection
from model.files import load_model, read_model
from design_catalog import property_paths_with_parents
from support.validator import load
from support.pytest_cli import run
from support.model_sources import write_model, write_fixture_files
from support.sync_model_fixtures import MODULE, SCRIPT, generated_policy
from utils.aws_mappings import definition_root

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


from support.it_workspace import copy_framework

def check_stage_definition_sources(generated_policy, tmp_path):
    from utils.aws_mappings import mapping_alias, mappings_for
    from design_document import DesignIndex
    root, model, values, design, artifact, _ = generated_policy
    originals = {p: p.read_bytes() for p in (design, artifact)}
    definitions = {p: p.read_bytes() for p in (definition_root(root) / 'framework').rglob('*') if p.is_file()}
    stage = tmp_path / 'candidates'
    staged = stage / design.relative_to(root)
    with mapping_alias(root, stage):
        sync_runtime.stage_inputs(stage, root, {design: values}, [model], [design], ['iam'], False)
        assert mappings_for(stage) is mappings_for(root)
        failures = []
        generated = sync_runtime.generate_views(stage, root, {design: values}, failures)
        sync_runtime.validate_candidates(stage, root, generated, {design: values}, failures, 1, False)
        assert not failures, failures
        assert not (stage / 'framework').exists() and not (stage / 'framework').is_symlink()
        assert load_model(stage / model.relative_to(root)).values == load_model(model).values
        assert {p: (stage / p.relative_to(root)).read_bytes() for p in originals} == originals
        assert DesignIndex(root).get(staged).headings.expanded == DesignIndex(root).get(design).headings.expanded
        validator = sync_views.view_validator(stage, root)
        assert validator.root == stage and validator.definitions_root == definition_root(root)
        assert validator.findings.canonical_root == stage.resolve()
        validator.check_resource_layout()
        assert not validator.errors, validator.errors
    values['desired.note.001.text'] = '最小stageの通常保存を検証する。'
    write_model(model, values)
    register = generated_policy[-1]
    unrelated = [root/'docs/designs/dev/123456789012/unrelated.md', root/'infra/unrelated.yaml', root/'tests/results/unrelated.log']
    for path in unrelated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('unrelated input\n')
    validate = sync_runtime.validate_generation
    def inspect(plan, **kwargs):
        result = validate(plan, **kwargs)
        assert not (plan.stage/'framework').exists() and not (plan.stage/'framework').is_symlink()
        assert not (root/'framework').exists()
        assert all(not (plan.stage/p.relative_to(root)).exists() for p in unrelated)
        assert set(p.relative_to(plan.stage).parts[0] for p in plan.stage.rglob('*')) <= {'model', 'docs', 'project.json'}
        # An unrelated log's content is not a generation dependency.
        assert unrelated[-1] not in plan.snapshot.contents
        unrelated[-1].write_text('log changed during generation\n')
        return result
    with patch.dict(os.environ, register([design, artifact])), patch.object(sync_runtime, 'validate_generation', side_effect=inspect):
        assert MODULE.sync(root, True, 'dev', '123456789012', ['iam'], definitions_root=definition_root(root)) == 0
    assert {p: p.read_bytes() for p in definitions} == definitions
    assert values['desired.note.001.text'] in design.read_text()

    # Four IAM candidates resolve KMS identifiers through real cold validation workers.
    import model.sources as model_sources
    from model.sources import json_text
    from model.format import serialize
    from validation_cache import memo_table
    project = json.loads((root/'project.json').read_text(encoding='utf-8'))
    sources, models = {}, []
    for number in range(4):
        environment = 'ref' + str(number)
        project['targets'].append({**project['targets'][0], 'environment': environment})
        (root/'project.json').write_text(json_text(project) + '\n', encoding='utf-8')
        producer = root/'model'/environment/'123456789012/kms.properties'
        write_model(producer, {
            'desired.service.kms.serviceId': 'kms',
            'desired.resource.001.resourceType': 'KMS.Key',
            'desired.resource.001.logicalId': 'KMS_Key_001',
            'desired.service.identity.lastAllocated': '{"KMS.Key":1}',
            'desired.row.001-001.property': 'KMS.Key.KeyId',
            'desired.row.001-001.value': f'resource://{environment}/123456789012/kms/KMS_Key_001',
            'desired.row.001-001.comment': '合成識別子',
            'observed.row.001-001.value': '`source-key`',
        })
        consumer = producer.with_name('iam.properties')
        candidate = dict(values)
        document = json.loads(candidate['desired.row.001-002.document'])
        document['Statement'][0]['Condition'] = {'StringEquals': {'kms:KeyId': 'source-key'}}
        candidate['desired.row.001-002.document'] = json_text(document)
        write_model(consumer, candidate)
        fields = {'consumerKey': 'desired.row.001-002.document', 'pointer': '/Statement/0/Condition/StringEquals/kms:KeyId',
                  'text': 'source-key', 'occurrence': '1', 'producerKind': 'resource',
                  'producerScope': environment + '/123456789012/kms', 'producerLogicalId': 'KMS_Key_001',
                  'resourceType': 'KMS.Key', 'format': 'identifier', 'property': 'KMS.Key.KeyId', 'labelPolicy': 'none'}
        candidate.update({'desired.reference.key-id.' + key: value for key, value in fields.items()})
        write_model(consumer, candidate)
        destination = root/'docs/designs'/environment/'123456789012/iam.md'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text('', encoding='utf-8')
        sources[destination] = load_model(consumer).values
        models.append(consumer)
    (root/'project.json').write_text(json_text(project) + '\n', encoding='utf-8')
    results = []
    original_validate = sync_views.validate_views
    original_reader = model_sources._read_model
    for jobs in (1, 4):
        stage = tmp_path/('identifier-stage-' + str(jobs))
        with mapping_alias(root, stage):
            sync_runtime.stage_inputs(stage, root, sources, models, list(sources), ['iam'], False)
            assert not (stage/'framework').exists()
            for consumer in models:
                producer = stage / consumer.with_name('kms.properties').relative_to(root)
                snapshot = load_model(producer)
                producer.write_text(serialize({**snapshot.authoritative, 'observed.row.001-001.value': '`stage-key`'}))
            candidates = {path: load_model(stage/model.relative_to(root)).values
                          for path, model in zip(sources, models)}
            failures = []
            generated = sync_runtime.generate_views(stage, root, candidates, failures)
            assert not failures and len(generated) == 4, failures
            before = {p.relative_to(stage): p.read_bytes() for files in generated.values() for p in files}
            workers, references = set(), []
            barrier = threading.Barrier(4) if jobs == 4 else None
            def validate(*args, **kwargs):
                assert memo_table() is None, 'candidate must start without expanded Model cache'
                workers.add(threading.get_ident())
                if barrier is not None:
                    barrier.wait(timeout=30)
                from validation_cache import input_scope
                @input_scope
                def verify_reference():
                    model = stage / 'model' / args[2][0].relative_to(stage / 'docs/designs').with_suffix('.properties')
                    snapshot = load_model(model)
                    assert any('differs from saved text' in warning['message'] for warning in snapshot.warnings)
                verify_reference()
                return original_validate(*args, **kwargs)
            def read(scope, reads):
                result = original_reader(scope, reads)
                if scope.service == 'kms':
                    assert scope.path.is_relative_to(stage)
                    assert result.authoritative['observed.row.001-001.value'] == '`stage-key`'
                    references.append(scope.path)
                return result
            with patch.object(sync_views, 'validate_views', side_effect=validate), \
                 patch.object(model_sources, '_read_model', side_effect=read):
                sync_runtime.validate_candidates(stage, root, generated, candidates, failures, jobs, False)
            assert not failures and len(generated) == 4, failures
            assert len(workers) == jobs and len(references) >= 4, (jobs, workers, references)
            assert before == {p.relative_to(stage): p.read_bytes() for files in generated.values() for p in files}
            results.append(before)
    assert results[0] == results[1]
    assert all('source-key' in load_model(model).values['desired.row.001-002.document'] for model in models)


@pytest.mark.parametrize('fault,expected', [
    ('model', 'model service'), ('names', 'resource heading must display resource name'),
    ('tables', 'schema'), ('overview', 'resource overview must appear exactly once'),
    ('policy', 'invalid policy tables'), ('links', 'broken design link'),
])
def check_stage_candidate_isolation(generated_policy, tmp_path, fault, expected):
    from utils.aws_mappings import mapping_alias
    root, model, values, design, artifact, _ = generated_policy
    stage = tmp_path / 'candidates'
    staged = stage / design.relative_to(root)
    originals = {p: p.read_bytes() for p in (design, artifact)}
    with mapping_alias(root, stage):
        sync_runtime.stage_inputs(stage, root, {design: values}, [model], [design], ['iam'], False)
        validator = sync_views.view_validator(stage, root)
        validator.scope = {('dev', '123456789012', 'iam')}
        validator.check_project_topology()
        if fault == 'model':
            write_model(stage / model.relative_to(root), values | {'desired.service.iam.serviceId': 's3'})
        elif fault == 'policy':
            (stage / artifact.relative_to(root)).write_text('{}\n', encoding='utf-8')
        else:
            content = staged.read_text(encoding='utf-8')
            if fault == 'names':
                content = content.replace('### IAM.Role: app-dev-role', '### IAM.Role: other-role')
            elif fault == 'tables':
                content = content.replace('| RoleName |', '| MaxSessionDuration |')
            elif fault == 'overview':
                content = content.replace('## リソース一覧', '## 候補の破損')
            else:
                content += '\n[参照先](missing.md#missing)\n'
            staged.write_text(content, encoding='utf-8')
        metadata, *catalog = validator.check_design_service_ownership([staged])
        validator.check_resource_names(metadata, [staged])
        validator.check_design_tables(metadata, *catalog, [staged])
        validator.check_design_overviews([staged])
        validator.check_design_links(catalog[2], [staged])
        validator.check_policy_tables()
        assert any(expected in error for error in diagnostics(validator)), diagnostics(validator)
        assert all(str(root) not in error and str(stage) not in error for error in validator.errors)
        assert not (stage / 'framework').exists()
    assert {p: p.read_bytes() for p in originals} == originals


@pytest.mark.parametrize('definition', ['schema', 'mapping', 'naming', 'layout'])
def check_stage_definition_errors(generated_policy, tmp_path, definition):
    from utils.aws_mappings import mapping_alias
    root, model, values, design, _, _ = generated_policy
    stage = tmp_path / 'candidates'
    staged = stage / design.relative_to(root)
    sync_runtime.stage_inputs(stage, root, {design: values}, [model], [design], ['iam'], False)
    source = definition_root(root) / 'framework' / {
        'schema': 'materials/cloudformation-schema/ap-northeast-1/index.json',
        'mapping': 'mappings/aws/owners.json',
        'naming': 'rules/aws-resource-naming.md',
        'layout': 'rules/resource-layout.json',
    }[definition]
    read = Path.read_text
    def fail(path, *args, **kwargs):
        if path == source:
            raise FileNotFoundError('unavailable Framework definition: ' + definition)
        return read(path, *args, **kwargs)
    with patch.object(Path, 'read_text', fail):
        if definition == 'layout':
            validator = sync_views.view_validator(stage, root)
            validator.check_resource_layout()
            assert any('unavailable Framework definition: layout' in e for e in validator.errors), validator.errors
        else:
            with pytest.raises(FileNotFoundError, match='unavailable Framework definition: ' + definition):
                if definition == 'mapping':
                    from utils.aws_mappings import Mappings
                    Mappings(definition_root(root))
                elif definition == 'schema':
                    sync_views.view_validator(stage, root)
                else:
                    model_design.markdown_for(staged, values, stage, definitions_root=definition_root(root))
    assert not (stage / 'framework').exists()


def check_stage_cloudformation_definitions(generated_policy, tmp_path):
    from utils.aws_mappings import mapping_alias
    root, model, values, design, _, _ = generated_policy
    stack_model = model.with_name('cloudformation-stacks.properties')
    stack_design = design.with_name('cloudformation-stacks.md')
    stacks = {
        'desired.deployment.maxConcurrentStacks': '1',
        'desired.stack.001.name': 'cfn-stack-app-dev-iam',
        'desired.stack.001.template': 'iam.yaml',
        'desired.stack.001.parameters': 'iam.json',
        'desired.stack.001.deployOrder': '10',
        'display.stack.001.comment': 'アプリケーションの実行権限',
    }
    write_model(stack_model, stacks)
    values = values | {'desired.resource.001.cfn-logicalId': 'cfn-stack-app-dev-iam-AppRole'}
    write_model(model, values)
    expected = design.read_bytes()
    expected_stack = model_design.markdown_for(stack_design, stacks, root, definitions_root=definition_root(root)).encode('utf-8')
    stack_design.write_bytes(expected_stack)
    stage = tmp_path / 'candidates'
    staged = stage / design.relative_to(root)
    staged_stack = stage / stack_design.relative_to(root)
    with mapping_alias(root, stage):
        sources = {design: values, stack_design: stacks}
        sync_runtime.stage_inputs(stage, root, sources, [model, stack_model], list(sources), ['iam', 'cloudformation-stacks'], False)
        failures = []
        generated = sync_runtime.generate_views(stage, root, sources, failures)
        validation = {}
        sync_runtime.validate_candidates(stage, root, generated, sources, failures, 1, True, validation)
        assert not failures, failures
        assert staged.read_bytes() == expected and staged_stack.read_bytes() == expected_stack
        scope = {('dev', '123456789012', service) for service in ('iam', 'cloudformation-stacks')}
        metadata = validation[None].result('design.stacks', scope).metadata['stack_definitions']
        assert metadata[staged_stack][0]['name'] == 'cfn-stack-app-dev-iam'
        # IaC uses the validated candidate, even when the saved stack is stale.
        stack_design.write_bytes(expected_stack.replace(b'iam.json', b'stale.json'))
        parameter = root/'infra/cloudformation/parameters/dev/123456789012/iam.json'
        parameter.parent.mkdir(parents=True, exist_ok=True)
        parameter.write_text('[]\n')
        template = root/'infra/cloudformation/templates/iam.yaml'
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text('Resources: {}\n')
        iac_validator = load('validate-blueprint').Validator(root, scope, iac_paths={template, parameter})
        iac_validator.check_project_topology()
        logical = {root/path.relative_to(stage): definitions for path, definitions in metadata.items()}
        with patch('validation.cloudformation.stack_design', side_effect=AssertionError('candidate stack reparsed')):
            iac_validator.check_cloudformation_environment_parameters(stack_definitions=logical)
        assert not iac_validator.errors, iac_validator.errors
        stack_design.write_bytes(expected_stack)
        # Only the staged stack authority changes; the saved stack remains valid.
        write_model(stage / stack_model.relative_to(root), stacks | {'desired.stack.001.name': 'cfn-stack-other-dev-iam'})
        with pytest.raises(ValueError, match='undeclared stack'):
            model_design.markdown_for(staged, values, stage, definitions_root=definition_root(root))
        validator = sync_views.view_validator(stage, root)
        validator.scope = {('dev', '123456789012', 'cloudformation-stacks')}
        validator.check_project_topology()
        staged_stack.write_text(expected_stack.decode('utf-8').replace('cfn-stack-app-dev-iam', 'cfn-stack-other-dev-iam'), encoding='utf-8')
        validator.check_stack_designs([staged_stack])
        assert any('undeclared stack' in error for error in validator.errors), validator.errors
    assert stack_design.read_bytes() == expected_stack and not (stage / 'framework').exists()


@pytest.mark.parametrize('fault', ['source', 'mapping', 'project', 'part', 'consumer', 'extra', 'contract'])
def check_publication_boundary(generated_policy, fault):
    root, model, values, design, artifact, register = generated_policy
    values['desired.note.001.text'] = '保存前の一括照合を確認する。'
    write_model(model, values)
    env = register([design, artifact])
    originals = {file: file.read_bytes() for file in (design, artifact)}
    validate = sync_runtime.validate_candidates
    concurrent = None

    def mutate_before_save(*args, **kwargs):
        nonlocal concurrent
        result = validate(*args, **kwargs)
        template = model
        target = {'source': template, 'mapping': definition_root(root)/'framework/mappings/aws/iam.yaml',
                  'project': root/'project.json', 'part': template.with_suffix('')/'unlisted.properties',
                  'consumer': root/'model/dev/other/new.properties',
                  'extra': artifact.parent/'unexpected.json', 'contract': root/env['BLUEPRINT_TASK_FILE']}[fault]
        concurrent = target, (target.read_bytes() if target.exists() else b'') + b'\n'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(concurrent[1])
        return result
    with patch.dict(os.environ, env), patch.object(sync_runtime, 'validate_candidates', side_effect=mutate_before_save), \
         patch.object(sync_runtime, '_publish_transaction', side_effect=AssertionError('published before input comparison')):
        with pytest.raises(ValueError, match='inputs changed'):
            MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert {file: file.read_bytes() for file in originals} == originals
    assert concurrent[0].read_bytes() == concurrent[1]


def check_normal_writer_contents(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    values['desired.note.001.text'] = '一回の候補を保存する。'
    document = json.loads(values['desired.row.001-002.document'])
    document['Statement'][0]['Sid'] = 'WrittenOnce'
    values['desired.row.001-002.document'] = json.dumps(document)
    write_model(model, values)
    from validation_cache import input_scope
    import model.sources as model_sources
    from contextlib import ExitStack
    from validation import design as design_checks, design_tables, design_links, cloudformation
    materialize = sync_runtime.GenerationInputs.open_stage
    stages = []
    def check_stage(inputs):
        stage = materialize(inputs)
        assert not (stage / 'framework').exists()
        assert not (stage / 'framework').is_symlink()
        stages.append(stage)
        return stage
    with ExitStack() as stack:
        stack.enter_context(patch.object(sync_runtime.GenerationInputs, 'open_stage', check_stage))
        checks = [(design_checks, name) for name in ('check_design_service_ownership', 'check_resource_names',
                  'check_observed_values', 'check_policy_tables')]
        checks += [(sync_runtime, 'validate_required_properties'), (design_tables, 'check_design_tables'), (design_links, 'check_design_overviews'),
                   (design_links, 'check_design_links'), (design_links, 'check_design_artifacts'),
                   (cloudformation, 'check_stack_designs')]
        counters = [stack.enter_context(patch.object(module, name, wraps=getattr(module, name))) for module, name in checks]
        with patch.dict(os.environ, register([design, artifact])), \
             patch.object(sync_runtime, 'generate_views', wraps=sync_runtime.generate_views) as generate, \
             patch.object(sync_views, 'validate_views', wraps=sync_views.validate_views) as validate, \
             patch.object(sync_runtime.GenerationInputs, 'verify', autospec=True, side_effect=sync_runtime.GenerationInputs.verify) as verify, \
             patch.object(model_sources, '_read_model', wraps=model_sources._read_model) as expand, \
             patch.object(sync_runtime, 'verify_saved', side_effect=AssertionError('post-save readback')):
            assert sync_runtime.sync(root, True, 'dev', '123456789012', ['iam']) == 0
        assert len(set(stages)) == generate.call_count == validate.call_count == verify.call_count == 1
        contexts = [(call.args[0], id(call.args[1])) for call in expand.call_args_list if call.args[0].service == 'iam']
        assert contexts and len(contexts) == len(set(contexts)), expand.call_args_list
        assert [counter.call_count for counter in counters] == [1, 1, 2, 1, 0, 1, 1, 1, 1, 1], [counter.call_count for counter in counters]
    assert values['desired.note.001.text'] in design.read_text()
    assert json.loads(artifact.read_text()) == json.loads(values['desired.row.001-002.document'])


@pytest.mark.parametrize('note', [False, True])
def check_unchanged_sidecar(generated_policy, note):
    root, model, values, design, artifact, register = generated_policy
    if note:
        values['desired.note.001.text'] = '利用開始前に実行主体の権限を確認する。'
        write_model(model, values)
    env = register([design] if note else [])
    before = artifact.read_bytes(), artifact.stat().st_mtime_ns
    with patch.dict(os.environ, env), patch.object(sync_runtime, '_publish_transaction', wraps=sync_runtime._publish_transaction) as publish, \
         patch.object(sync_runtime, 'validate_candidates', wraps=sync_runtime.validate_candidates) as validate:
        assert MODULE.sync(root, True, 'dev', '123456789012', ['iam']) == 0
    assert validate.call_count == 1, 'no-op outputs still require candidate validation'
    assert publish.call_count == int(note)
    if note:
        assert set(publish.call_args.args[1]) == {design}, 'unchanged JSON must not enter publication'
        assert values['desired.note.001.text'] in design.read_text(encoding='utf-8')
    assert (artifact.read_bytes(), artifact.stat().st_mtime_ns) == before
    with patch.dict(os.environ, env):
        assert MODULE.sync(root, False, 'dev', '123456789012', ['iam']) == 0


@pytest.mark.parametrize('change', ['model', 'stale', 'missing'])
def check_changed_sidecar_publication(generated_policy, change):
    root, model, values, design, artifact, register = generated_policy
    if change == 'model':
        document = json.loads(values['desired.row.001-002.document'])
        document['Statement'][0]['Sid'] = 'Changed'
        values['desired.row.001-002.document'] = json.dumps(document)
        write_model(model, values)
    elif change == 'stale':
        artifact.write_text('{}\n', encoding='utf-8')
    else:
        artifact.unlink()
    env = register([design])
    with patch.dict(os.environ, env):
        assert MODULE.sync(root, True, 'dev', '123456789012', ['iam']) == 0
    assert json.loads(artifact.read_text()) == json.loads(values['desired.row.001-002.document'])



@pytest.mark.parametrize('note', [False, True])
@pytest.mark.parametrize('drift', ['sidecar', 'source', 'task'])
def check_publication_rechecks_excluded_outputs(generated_policy, note, drift):
    root, model, values, design, artifact, register = generated_policy
    if note:
        values['desired.note.001.text'] = '公開前に変更の競合を確認する。'
        write_model(model, values)
    env = register([design] if note else [])
    original = design.read_bytes()
    changed = (artifact if drift == 'sidecar' else root / env['BLUEPRINT_TASK_FILE'] if drift == 'task'
               else model)
    content = ('{}\n' if drift == 'sidecar' else '# concurrent change\n' + changed.read_text(encoding='utf-8'))
    validate = sync_runtime.validate_candidates
    def mutate(*args, **kwargs):
        result = validate(*args, **kwargs)
        changed.write_text(content, encoding='utf-8')
        return result
    with patch.dict(os.environ, env), patch.object(sync_runtime, 'validate_candidates', side_effect=mutate):
        with pytest.raises(ValueError, match='inputs changed'):
            MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert design.read_bytes() == original
    assert changed.read_text(encoding='utf-8') == content



@pytest.mark.parametrize('note', [False, True])
def check_changed_sidecar_publication_rollback(generated_policy, note):
    root, model, values, design, artifact, register = generated_policy
    before = {file: file.read_bytes() for file in (design, artifact)}
    if note:
        values['desired.note.001.text'] = '注記だけの公開もロールバックする。'
    else:
        document = json.loads(values['desired.row.001-002.document'])
        document['Statement'][0]['Sid'] = 'Changed'
        values['desired.row.001-002.document'] = json.dumps(document)
    write_model(model, values)
    env = register([design] if note else [design, artifact])
    write = Path.write_text

    def fail_markdown(path, *args, **kwargs):
        if path == design:
            if note:
                write(artifact, '{}\n', encoding='utf-8')
            else:
                assert artifact.read_bytes() != before[artifact]
            write(path, 'partial Markdown', encoding='utf-8')
            raise OSError('injected Markdown publication failure')
        return write(path, *args, **kwargs)

    with patch.dict(os.environ, env), patch.object(Path, 'write_text', fail_markdown):
        with pytest.raises(ValueError, match='injected Markdown publication failure'):
            MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert design.read_bytes() == before[design]
    assert artifact.read_bytes() == (b'{}\n' if note else before[artifact])
    if note:
        artifact.write_bytes(before[artifact])
    with patch.dict(os.environ, env):
        assert MODULE.sync(root, True, 'dev', '123456789012', ['iam']) == 0
        assert MODULE.sync(root, False, 'dev', '123456789012', ['iam']) == 0


def check_unchanged_sidecar_path_safety(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    env = register([])
    external = root / 'external-policy.json'
    external.write_bytes(artifact.read_bytes())
    artifact.unlink()
    artifact.symlink_to(external)
    with patch.dict(os.environ, env), pytest.raises(ValueError, match=r'unsafe generation input \(symlink\)'):
        MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert artifact.is_symlink()


def check_unchanged_sidecar_validation(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    env = register([])
    before = {file: file.read_bytes() for file in (design, artifact)}
    with patch.dict(os.environ, env), \
         patch.object(sync_views, 'validate_views', side_effect=ValueError('injected candidate validation failure')), \
         patch.object(sync_runtime, '_publish_transaction', side_effect=AssertionError('invalid candidate published')):
        with pytest.raises(ValueError, match='injected candidate validation failure'):
            MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert {file: file.read_bytes() for file in before} == before


def check_failure_counts(framework_root) -> None:
    from types import SimpleNamespace
    from validation.findings import Findings
    root = framework_root
    (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'dev', 'alias': 'non-cde',
        'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
    models = root / "model/dev/non-cde"
    docs = root / "docs/designs/dev/non-cde"
    models.mkdir(parents=True)
    docs.mkdir(parents=True)
    for number in range(17):
        write_model(models / f"service-{number:02d}.properties", {f"desired.service.service-{number:02d}.serviceId": f"service-{number:02d}", f"desired.service.service-{number:02d}.ownedCatalogResourceTypes": ""})
        (docs / f"service-{number:02d}.md").write_text("generated\n")

    def render(path, values, stage, *, definitions_root=None):
        assert definitions_root == root
        if int(path.stem.removeprefix("service-")) < 9:
            raise ValueError("fixture render failure")
        return "generated\n"

    # Retained references warn without adding a failed service or failure diagnostics.
    broken = {f"reference-{number}": docs / "service-09.md" for number in range(5)}
    def context(stage, source, generated, destinations, accounts=None, definitions_root=None):
        findings = Findings(stage)
        scope = {(*p.relative_to(root / 'docs/designs').parts[:2], p.stem) for p in generated}
        for name in ('design.collections', 'design.ownership', 'design.stacks', 'framework.policy-tables'):
            findings.evaluate(name, scope, lambda: None)
        return SimpleNamespace(errors=[], findings=findings)
    def checked(stage, source, paths, sources, **kwargs):
        findings = Findings(stage)
        findings.candidate = kwargs['context'].findings.candidate
        scope = {(*p.relative_to(stage / 'docs/designs').parts[:2], p.stem) for p in paths}
        for name in ('design.names', 'design.tables', 'design.overviews', 'design.links', 'design.artifacts', 'design.observed'):
            findings.evaluate(name, scope, lambda: None)
        return findings
    for extra_inputs in (False, True):
        if extra_inputs:
            write_model(models / 'invalid.properties', 'invalid properties\n')
            (docs / "orphan.md").write_text("saved Markdown\n")
        for write in (False, True):
            warnings = io.StringIO()
            with redirect_stderr(warnings), patch.object(sync_runtime, "validate_required_properties"), \
                 patch.object(sync_runtime, "markdown_for", side_effect=render), \
                 patch.object(sync_runtime, "rendered_design", return_value="generated\n"), \
                 patch.object(sync_views, "validate_views", side_effect=checked if write else None), \
                 patch.object(sync_views, "validation_context", side_effect=context), \
                 patch.object(sync_views, "broken_design_links", side_effect=[{}, broken, {}]), \
                 redirect_stdout(io.StringIO()):
                try:
                    MODULE.sync(root, write, "dev", "non-cde")
                except ValueError as error:
                    failed, diagnostics = (11, 11) if extra_inputs else (9, 9)
                    assert str(error).splitlines()[0] == f"8 services succeeded; {failed} services failed; {diagnostics} diagnostics", error
                    assert len(str(error).splitlines()) == diagnostics + 1, error
                    assert "saved reference" not in str(error), error
                    assert warnings.getvalue().count("saved reference needs repair") == (5 if write else 0)
                    if extra_inputs:
                        assert "invalid or duplicate model property" in str(error), error
                        assert "properties Model inputs missing" in str(error), error
                else:
                    raise AssertionError("partial generation failure accepted")
    print("Failure counts: PASS (17 models, 8 successes, 9 failed services, 9 diagnostics, invalid/missing models, read/write)")


@pytest.mark.parametrize("write", [False, True])
def check_incoming_reference_models(framework_root, tmp_path, write) -> None:
    root = framework_root
    (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'dev', 'awsAccountId': '123456789012',
        'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
    models = root / "model/dev/123456789012"
    docs = root / "docs/designs/dev/123456789012"
    docs.mkdir(parents=True)
    for service in ("s3", "kms"):
        write_model(models / f"{service}.properties", f"desired.service.{service}.serviceId={service}\n")
        (docs / f"{service}.md").write_text(f"# {service}\n### {service}\n", encoding="utf-8")
    selected = docs / "s3.md"
    incoming = docs / "kms.md"
    incoming.write_text("# kms\n### kms\n[S3](s3.md#s3)\n", encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()

    def check_snapshot(stage, root, paths, *, definitions_root=None):
        assert stage / incoming.relative_to(root) in paths
        assert read_model(stage / (models / "kms.properties").relative_to(root)) == read_model(models / "kms.properties")
        return {}

    with patch.object(sync_views, "broken_design_links", side_effect=check_snapshot) as check:
        saved, _ = sync_runtime.stage_inputs(stage, root, {selected: {}},
                                            [models / "s3.properties"], [selected], ["s3"], write)
    assert (incoming in saved) == write
    assert check.call_count == int(write)
    if write:
        assert (stage / incoming.relative_to(root)).exists()


def check_required_preflight(framework_root) -> None:
    root = framework_root
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
        "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
    model = root / "model/dev/123456789012/quicksight.properties"
    model.parent.mkdir(parents=True)
    values = {"desired.service.quicksight.serviceId": "quicksight",
        "desired.service.quicksight.ownedCatalogResourceTypes": "QuickSight.DataSource",
        "desired.resource.001.resourceType": "QuickSight.DataSource",
        "display.service.title": "# QuickSight 詳細設計",
        "display.resource.001.comment": "分析用データソース",
        "desired.row.001-001.property": "QuickSight.DataSource.Name",
        "desired.row.001-001.value": "`qs-app-dev-athena`",
        "desired.row.001-001.comment": "データソースの名前",
        "desired.row.001-002.property": "QuickSight.DataSource.Credentials.KeyPairCredentials",
        "desired.row.001-002.value": "[設定](quicksight/credentials.json)",
        "desired.row.001-002.document": '{"KeyPairUsername":"test","PrivateKey":"test"}',
        "desired.row.001-002.comment": "接続の認証設定"}
    values.update(allocate(values, ['001']))
    source = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    write_model(model, source)
    source = read_model(model)
    design = root / "docs/designs/dev/123456789012/quicksight.md"
    artifact = design.with_suffix("") / "credentials.json"
    for existing in (False, True):
        if existing:
            artifact.parent.mkdir(parents=True)
            design.write_text("existing Markdown\n")
            artifact.write_text("existing JSON\n")
        for write in (False, True):
            # Neither the renderer nor artifact writer may run for this service.
            with patch.object(sync_runtime, "markdown_for", side_effect=AssertionError("rendered before preflight")), \
                 patch.object(sync_runtime, "save_files", side_effect=AssertionError("wrote before preflight")):
                with pytest.raises(ValueError) as error:
                    MODULE.sync(root, write, "dev", "123456789012")
                assert "AthenaSource: required provider schema property missing: QuickSight.DataSource.Type" in str(error.value)
            assert read_model(model) == source
            if existing:
                assert design.exists() and artifact.exists()
                assert design.read_text() == "existing Markdown\n"
                assert artifact.read_text() == "existing JSON\n"
    with pytest.raises(ValueError) as error:
        model_design.markdown_for(design, values, root)
    assert "QuickSight.DataSource.Type" in str(error.value)
    complete = values | {
        "desired.row.001-003.property": "QuickSight.DataSource.Type",
        "desired.row.001-003.value": "`ATHENA`",
        "desired.row.001-003.comment": "データソースの接続方式",
    }
    model_validation.validate_required_properties(complete, root)
    for empty in ("", "``", '`""`', "`UNSET`"):
        with pytest.raises(ValueError) as error:
            model_validation.validate_required_properties(complete | {"desired.row.001-003.value": empty}, root)
        assert "QuickSight.DataSource.Type" in str(error.value)
    grouped = {key: value for key, value in complete.items() if not key.startswith('desired.row.001-003.')} | {
        "desired.resource.001.resourceType": "S3.Bucket",
        "desired.row.001-001.property": "S3.Bucket.BucketName",
        "desired.row.001-002.property": "S3.BucketPolicy.PolicyDocument",
        "desired.row.001-002.value": "",
    }
    with pytest.raises(ValueError) as error:
        model_validation.validate_required_properties(grouped, root)
    assert "S3.BucketPolicy.PolicyDocument" in str(error.value)
    assert "S3.BucketPolicy.Bucket" not in str(error.value)
    # An unrelated valid service still saves while the incomplete one fails.
    stack = model.with_name("cloudformation-stacks.properties")
    write_model(stack, "desired.stack.001.name=cfn-stack-app-dev-general-01\n"
                     "desired.stack.001.template=app.yaml\n"
                     "desired.stack.001.parameters=app.json\n"
                     "desired.stack.001.deployOrder=10\n"
                     "display.stack.001.comment=アプリケーションのstack\n")
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True, "dev", "123456789012")
        assert "1 services succeeded; 1 services failed; 1 diagnostics" in str(error.value), error.value
    assert design.with_name("cloudformation-stacks.md").is_file()
    assert design.read_text() == "existing Markdown\n" and artifact.read_text() == "existing JSON\n"
    print("Required-property preflight: PASS (new/existing, read/write, direct renderer, partial success)")


def check_required_property_parents(tmp_path) -> None:
    root = tmp_path
    copy_framework(definition_root(root) / 'framework')
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
        "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
    model = root / "model/dev/123456789012/glue.properties"
    model.parent.mkdir(parents=True)
    values = {"desired.service.glue.serviceId": "glue",
        "desired.service.glue.ownedCatalogResourceTypes": "Glue.Connection",
        "desired.resource.001.resourceType": "Glue.Connection",
        "display.service.title": "# AWS Glue 詳細設計",
        "display.resource.001.comment": "データ取得に使用する接続"}
    values.update(allocate(values, ['001']))
    for number, (field, value) in enumerate((
        ("ConnectionInput.Name", "`sample`"),
        ("Name", "[Connection](#glue-sample)"),
        ("CatalogId", "`123456789012`"),
        ("ConnectionInput.ConnectionType", "`JDBC`"),
        ("ConnectionInput.PhysicalConnectionRequirements.AvailabilityZone", "`ap-northeast-1a`"),
        ("ConnectionInput.ValidateCredentials", "`true`"),
    ), 1):
        key = f"001-{number:03d}"
        comment = "一意に識別するID" if field == "Name" else "接続の設定"
        values.update({f"desired.row.{key}.property": "Glue.Connection." + field,
                       f"desired.row.{key}.value": value, f"desired.row.{key}.comment": comment})
    values.update({"observed.row.001-002.property": "Glue.Connection.Name",
                   "observed.row.001-002.value": "`sample`", "observed.row.001-002.comment": "一意に識別するID"})
    source = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    write_model(model, source)
    source = read_model(model)
    design = root / "docs/designs/dev/123456789012/glue.md"
    model_validation.validate_required_properties(values, root)
    assert MODULE.sync(root, True, "dev", "123456789012") == 0
    assert read_model(model) == source
    assert "| ConnectionInput |" not in design.read_text()  # Presence is inferred without inventing a row.

    def design_errors(content):
        design.write_text(content)
        validator = sync_views.view_validator(root, root)
        validator.check_design_tables({design: ("glue", ("Glue.Connection",))}, *validator.catalog_design_properties())
        return validator.errors

    original = design.read_text()
    assert not design_errors(original), design_errors(original)
    for missing in ("ConnectionInput", "CatalogId"):
        removed = {key.rsplit(".", 1)[0] for key, value in values.items()
                   if key.endswith(".property") and (value == f"Glue.Connection.{missing}" or value.startswith(f"Glue.Connection.{missing}."))}
        incomplete = {key: value for key, value in values.items() if key.rsplit(".", 1)[0] not in removed}
        with pytest.raises(ValueError) as error:
            model_validation.validate_required_properties(incomplete, root)
        assert f"required provider schema property missing: Glue.Connection.{missing}" in str(error.value)
        content = "\n".join(line for line in original.splitlines()
                            if f" | {missing} |" not in line and f" | {missing}." not in line) + "\n"
        assert any(f"Glue.Connection.{missing}" in error and "required provider schema property missing" in error for error in design_errors(content))
    assert any("provider schema violation" in error for error in design_errors(original.replace("`true`", "`not-a-boolean`")))
    print("Required-property parents: PASS (Glue generation, design validation and true missing inputs)")


def check_workflow(tmp_path) -> None:
    root = tmp_path
    copy_framework(root / "framework/mappings", relative="mappings")
    materials = root / "framework" / "materials" / "aws"
    materials.mkdir(parents=True)
    (materials / 'EC2_VPC.properties').write_text('EC2.VPC.VpcId=IDENTIFIER_OUTPUT\n',encoding="utf-8")
    (materials / 'EC2_Subnet.properties').write_text('EC2.Subnet.SubnetId=IDENTIFIER_OUTPUT\nEC2.Subnet.VpcId=\n',encoding="utf-8")
    (materials / 'S3_Bucket.properties').write_text('S3.Bucket.BucketName=\nS3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID=\nS3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm=\nS3.Bucket.VersioningConfiguration.Status=\n',encoding="utf-8")
    (materials / 'S3_BucketPolicy.properties').write_text('S3.BucketPolicy.Bucket=\nS3.BucketPolicy.PolicyDocument=\n',encoding="utf-8")
    (materials / 'KMS_Alias.properties').write_text('KMS.Alias.AliasName=\nKMS.Alias.TargetKeyId=\n',encoding="utf-8")
    design = root / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
    artifact = design.parent / "vpc" / "vpc01-policy.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
        encoding="utf-8",
    )
    design.write_text(
        """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`

## リソース詳細

<a id="vpc-vpc-app-dev"></a>

### EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | PENDING_DEPLOY | VPCを一意に識別するID |
| 2 | CidrBlock | 10.1.0.0/16 | VPCで使用するIPv4アドレス範囲 |
| 3 | Name | vpc-app-dev | VPCを識別するNameタグの値 |
| 4 | PolicyDocument | [policy](vpc/vpc01-policy.json) | VPCに適用するpolicy文書 |

<a id="vpc-sbnt-app-dev-private-01"></a>

### EC2.Subnet: sbnt-app-dev-private-01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | SubnetId | PENDING_DEPLOY | Subnetを一意に識別するID |
| 2 | VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
| 3 | Name | sbnt-app-dev-private-01 | Subnetを識別するNameタグの値 |
""",
        encoding="utf-8",
    )
    from design_layout import expanded_design, stack_design, stack_deployment_policy
    model = "\n".join(expanded_design(design.read_text().splitlines())[0])
    assert '- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`' in model
    assert '### EC2.VPC: vpc-app-dev' in model
    assert '| EC2.VPC.VpcId | PENDING_DEPLOY |' in model
    assert '| EC2.VPC.CidrBlock | 10.1.0.0/16 |' in model
    assert '| EC2.VPC.Name | vpc-app-dev |' in model
    assert model_projection.json_sha256(artifact)
    assert '| EC2.Subnet.SubnetId | PENDING_DEPLOY |' in model
    assert '| EC2.Subnet.VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) |' in model
    assert '| EC2.Subnet.Name | sbnt-app-dev-private-01 |' in model
    assert "\n".join(expanded_design(design.read_text().splitlines())[0]) == model

    s3_design = design.with_name("s3.md")
    s3_artifact = s3_design.parent / "s3" / "app-data-bucket-policy.json"
    s3_artifact.parent.mkdir(parents=True)
    s3_artifact.write_text(
        '{"Version":"2012-10-17","Statement":[]}\n', encoding="utf-8"
    )
    kms_design = design.with_name("kms.md")
    kms_design.write_text(
        """# AWS KMS 詳細設計

- Design service ID: `kms`
- Owned catalog resource types: `KMS.Key`, `KMS.Alias`

## リソース詳細

<a id="kms-appdatakey"></a>

### KMS.Key: AppDataKey

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | 1234abcd-12ab-34cd-56ef-1234567890ab | KMS keyを識別するID |
| 2 | KMS.Alias.AliasName | alias/app-data | <a id="kms-appdatakeyalias"></a><!-- logical-id: AppDataKeyAlias --> application data用keyを識別するalias |
""",
        encoding="utf-8",
    )
    s3_design.write_text(
        """# Amazon S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`, `S3.BucketPolicy`

## リソース一覧

### S3.Bucket

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |

## リソース詳細

<a id="s3-app-dev-data-123456789012"></a>

### S3.Bucket: app-dev-data-123456789012

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | app-dev-data-123456789012 | application dataを格納するbucketの名前 |
| 2 | Region | us-east-1 | bucketを配置するAWS region |
| 3 | BucketEncryption[].KMSMasterKeyID | [alias/app-data](kms.md#kms-appdatakeyalias) | 新規objectのdefault暗号化に使用するKMS key alias |
| 4 | BucketEncryption[].SSEAlgorithm | aws:kms | 暗号化方式 |
| 5 | VersioningConfiguration.Status | Enabled | objectのversion保持状態 |
| 6 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |
""",
        encoding="utf-8",
    )
    lines, children = expanded_design(s3_design.read_text().splitlines())
    s3_model = "\n".join(lines)
    assert '### S3.Bucket: app-dev-data-123456789012' in s3_model
    assert not children  # BucketPolicy is an identity-free configuration.
    assert '| S3.Bucket.BucketName | app-dev-data-123456789012 |' in s3_model
    assert '| S3.Bucket.Region | us-east-1 |' in s3_model
    assert '| S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID | [alias/app-data](kms.md#kms-appdatakeyalias) |' in s3_model
    assert '| S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm |' in s3_model
    assert 'S3.BucketPolicy.Bucket |' not in s3_model
    assert '| S3.BucketPolicy.PolicyDocument |' in s3_model
    assert model_projection.json_sha256(s3_artifact)
    assert len([line for line in lines if line.startswith('### S3.Bucket:')]) == 1
    original_digest = model_projection.json_sha256(artifact)
    artifact.write_text(
        '{\r\n  "Action": [\r\n    "s3:GetObject"\r\n  ],\r\n'
        '  "Version": "2012-10-17"\r\n}',
        encoding="utf-8",
        newline="",
    )
    assert model_projection.json_sha256(artifact) == original_digest
    artifact.write_text(
        '{"Version":"2012-10-17","Action":["s3:PutObject"]}\n',
        encoding="utf-8",
    )
    assert model_projection.json_sha256(artifact) != original_digest
    artifact.write_text(
        '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
        encoding="utf-8",
    )
    design.write_text(
        design.read_text(encoding="utf-8")
        .replace("VpcId | PENDING_DEPLOY", "VpcId | vpc-0123456789abcdef0")
        .replace("[PENDING_DEPLOY](#vpc-vpc-app-dev)", "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)")
        .replace("SubnetId | PENDING_DEPLOY", "SubnetId | subnet-0123456789abcdef0"),
        encoding="utf-8",
    )
    deployed = "\n".join(expanded_design(design.read_text().splitlines())[0])
    assert '| EC2.VPC.VpcId | vpc-0123456789abcdef0 |' in deployed
    assert '| EC2.Subnet.SubnetId | subnet-0123456789abcdef0 |' in deployed
    assert '| EC2.Subnet.VpcId | [vpc-0123456789abcdef0](#vpc-vpc-app-dev) |' in deployed
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True)
        assert "properties Model inputs missing" in str(error.value)

    alias_design = root / "docs" / "designs" / "dev" / "cde" / "vpc.md"
    alias_design.parent.mkdir(parents=True)
    alias_artifact = alias_design.parent / "vpc" / "vpc01-policy.json"
    alias_artifact.parent.mkdir(parents=True)
    alias_artifact.write_text(
        '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
        encoding="utf-8",
    )
    alias_design.write_text(
        design.read_text(encoding="utf-8").replace(
            "vpc-0123456789abcdef0", "vpc-11111111111111111"
        ),
        encoding="utf-8",
    )
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True, "dev", "cde")
        assert "properties Model inputs missing" in str(error.value)
    assert sync_runtime.selected(alias_design, root / "docs" / "designs", "dev", "cde")
    assert not sync_runtime.selected(alias_design, root / "docs" / "designs", "dev", "123456789012")
    stacks = design.with_name("cloudformation-stacks.md")
    stacks.write_text(
        """# CloudFormation stack 詳細設計

<!-- max-concurrent-stacks: 2 -->

## Stack一覧
| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 10 | stack-job-01 | job.yaml | job-01.json | 日次jobを配置するstack |
| 2 | 10 | stack-job-02 | job.yaml | job-02.json | 月次jobを配置するstack |
""",
        encoding="utf-8",
    )
    stack_rows = stack_design(stacks)
    assert [row['template'] for row in stack_rows] == ['job.yaml', 'job.yaml']
    assert stack_rows[1]['parameters'] == 'job-02.json'
    assert [row['comment'] for row in stack_rows] == ['日次jobを配置するstack', '月次jobを配置するstack']
    assert stack_deployment_policy(stacks) == 2
    assert stack_rows[1]['deployOrder'] == '10'
    assert all(set(row) == {'name', 'template', 'parameters', 'deployOrder', 'comment'} for row in stack_rows)
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True, "dev", "123456789012")
        assert "properties Model inputs missing" in str(error.value)



def main():
    return run(__file__, message='sync-model: PASS (generation, changed outputs, publication drift and rollback)')


import threading
import task_contract as tasks
import sync_progress as progress


def check_publication_lock_wait(tmp_path):
    import model.sources as model_sources
    output = io.StringIO()
    waiting = threading.Event()
    reporter = progress.Progress()
    errors = []
    emit = reporter.emit
    def notify(state, event):
        emit(state, event)
        if state[5] == 'lock-wait':
            waiting.set()
    reporter.emit = notify
    def worker():
        try:
            with reporter.worker('dev/team/iam'), model_sources.publication_lock(tmp_path):
                with model_sources.publication_lock(tmp_path):
                    pass
        except BaseException as error:
            errors.append(error)
    with redirect_stderr(output):
        with model_sources.publication_lock(tmp_path):
            thread = threading.Thread(target=worker)
            thread.start()
            observed = waiting.wait(5)
        thread.join(5)
    assert observed and not thread.is_alive() and not errors
    assert 'lock-wait' in output.getvalue()


def check_generation_output_compatibility(generated_policy):
    root, _, _, design, artifact, register = generated_policy
    before = {p: p.read_bytes() for p in (design, artifact)}
    plain, observed, diagnostics = io.StringIO(), io.StringIO(), io.StringIO()
    with patch.dict(os.environ, register([design, artifact])):
        with redirect_stdout(plain):
            assert sync_runtime.sync(root, True, 'dev', '123456789012', ['iam']) == 0
        @progress.reported_main
        def generate():
            return sync_runtime.sync(root, True, 'dev', '123456789012', ['iam'])
        with redirect_stdout(observed), redirect_stderr(diagnostics):
            assert generate() == 0
    assert observed.getvalue() == plain.getvalue()
    assert before == {p: p.read_bytes() for p in before}
    for stage in ['snapshot', 'dependency-model', 'stage-placement', 'candidate-generation', 'candidate-validation', 'publication', 'completed=1/1']:
        assert stage in diagnostics.getvalue()


def check_two_consumer_cli(generated_policy):
    import json
    import shutil
    import subprocess
    from support.validator import load
    root, _, _, design, artifact, register = generated_policy
    shutil.copytree(root / 'model/dev', root / 'model/stg')
    shutil.copytree(root / 'docs/designs/dev', root / 'docs/designs/stg')
    project = json.loads((root / 'project.json').read_text())
    project['targets'].append({**project['targets'][0], 'environment': 'stg'})
    (root / 'project.json').write_text(json.dumps(project) + '\n')
    for arguments in [('init', '-q'), ('add', '.'),
                      ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'baseline')]:
        subprocess.run(['git', *arguments], cwd=root, check=True, capture_output=True)
    outputs = [design, artifact, root / 'docs/designs/stg/123456789012/iam.md',
               root / 'docs/designs/stg/123456789012/iam/app-role-trust-policy.json']
    environment = register(outputs)
    name = environment[tasks.SELECTOR]
    (root / name).write_text((root / name).read_text().replace(
        '- `dev/123456789012/iam`', '- `dev/123456789012/iam`\n- `stg/123456789012/iam`'))
    tasks.refresh(root, name)
    for selected_env in ('dev', 'stg'):
        source = root / 'model' / selected_env / '123456789012/iam.properties'
        source.write_text(source.read_text().replace('アプリケーションの実行権限', '更新後の処理権限'))
    cli = load('sync-model')
    arguments = ['sync-model.py', '--repository-root', str(root), '--scope', 'dev/123456789012/iam',
                 '--scope', 'stg/123456789012/iam', '--jobs', '2']
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, environment), redirect_stdout(stdout), redirect_stderr(stderr):
        with patch.object(sys, 'argv', [*arguments, '--write']):
            assert cli.main() == 0
        written = {file: file.read_bytes() for file in outputs}
        with patch.object(sys, 'argv', arguments):
            assert cli.main() == 0
        assert written == {file: file.read_bytes() for file in outputs}
        with patch.object(sys, 'argv', ['sync-model.py', '--repository-root', str(root), '--scope', 'prod/123456789012/iam']):
            assert cli.main() == 1
    assert 'sync-model progress:' not in stdout.getvalue()
    assert 'stage=impact-scope' in stderr.getvalue()
    assert 'completed=2/2' in stderr.getvalue()
    assert 'state=failed' in stderr.getvalue()
    for document in (outputs[0], outputs[2]):
        assert '更新後の処理権限' in document.read_text()


@pytest.mark.parametrize('filename', ['entry', 'part', 'other-model', 'project'])
@pytest.mark.parametrize('mutation', ['change', 'delete', 'add'])
def check_input_mutation(generated_policy, filename, mutation):
    root, model, _, design, artifact, register = generated_policy
    from model.format import FORMAT, INDEX
    if filename == 'part':
        part = model.with_suffix('') / 'part-003.properties'
        part.parent.mkdir()
        part.write_bytes(model.read_bytes())
        model.write_text(FORMAT + '\n' + INDEX + '\n# part: iam/part-003.properties\n')
        source = part
    elif filename == 'other-model':
        source = model.with_suffix('') / 'part-003.properties'
        source.parent.mkdir()
        source.write_bytes(model.read_bytes())
        model.write_text(FORMAT + '\n' + INDEX + '\n# part: iam/part-003.properties\n')
    else:
        source = model if filename == 'entry' else root / 'project.json'
    if mutation == 'add':
        source = model.with_suffix('') / 'added.properties' if filename == 'part' else root / 'model/dev/new/iam.properties'
    original = {p: p.read_bytes() for p in (design, artifact)}
    validate = sync_runtime.validate_candidates
    def mutate(*args, **kwargs):
        validate(*args, **kwargs)
        if mutation == 'delete':
            source.unlink()
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes((source.read_bytes() if source.exists() else b'') + b'\n')
    with patch.dict(os.environ, register([design, artifact])), patch.object(sync_runtime, 'validate_candidates', side_effect=mutate):
        with pytest.raises(ValueError, match='inputs changed'):
            sync_runtime.sync(root, True, 'dev', '123456789012', ['iam'])
    assert original == {p: p.read_bytes() for p in original}



@pytest.fixture
def internal_sync_project(tmp_path):
    from support.model_templates_fixtures import fixture, config_model, write_fixture
    import subprocess
    from support.it_fixture_bundle import source as seed
    from utils.aws_mappings import mapping_alias
    definitions = seed('framework')
    lifetime = __import__('contextlib').ExitStack()
    lifetime.enter_context(mapping_alias(definitions, tmp_path))
    fixture(tmp_path, ('dev', 'stg'), definitions_root=definitions)
    for env in ('dev', 'stg'):
        write_fixture(tmp_path, env, 'config', config_model())
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    try:
        yield tmp_path
    finally:
        lifetime.close()



@pytest.mark.parametrize('selection', [
    ['--scope', 'dev/team/config', '--scope', 'stg/team/config'], ['--all']])
@pytest.mark.parametrize('jobs', [1, 4])
def check_internal_sync_isolation(internal_sync_project, selection, jobs, capsys):
    from script_loader import module
    from validation_cache import input_scope, memo_table
    runner = module('sync-model.py', 'blueprint_sync_model')
    root = internal_sync_project
    entry = ('dev', 'team', 'config')
    source = root/'model/dev/team/config.properties'
    design = root/'docs/designs/dev/team/config.md'
    saved = design.read_bytes()
    inputs = root/'model/dev/team/config.properties'
    original = inputs.read_bytes()
    memories = []
    sync = runner.sync
    def observed(*args, **kwargs):
        assert memo_table() is None
        assert sync_views._saved_design_validation.get() is None
        assert progress._current.get()[0] is not parent_progress
        return sync(*args, **kwargs)
    @input_scope
    def calls():
        parent = memo_table()
        load_model(source)
        parent_snapshot = dict(parent)
        with sync_views.saved_design_validation(root, entry), \
             parent_progress.worker('parent'), patch.object(runner, 'sync', side_effect=observed):
            for invalid in (False, True, False):
                # Parent memo retains the old source; the runner must read it again.
                inputs.write_bytes(original + (b'broken: [\n' if invalid else b''))
                code, text = runner.run(['--jobs', str(jobs), *selection], repository_root=root)
                assert code == (1 if invalid else 0), text
                assert ('Design Markdown sync: FAIL' if invalid else 'Design Markdown sync: PASS') in text, text
                assert 'consumer=parent' not in text
                assert memo_table() is parent and parent == parent_snapshot
                assert sync_views._saved_design_validation.get() == (root, entry)
                memories.append(text)
        assert design.read_bytes() == saved
    parent_progress = progress.Progress()
    capsys.readouterr()
    # Keep the parent's progress out of the streams under test as well.
    parent_progress.output = io.StringIO()
    calls()
    captured = capsys.readouterr()
    assert not captured.out and not captured.err, captured
    assert progress._current.get() is None and memo_table() is None
    assert sync_views._saved_design_validation.get() is None
    assert len(memories) == 3



def check_internal_sync_real_diagnostics(internal_sync_project, capsys):
    from script_loader import module
    runner = module('sync-model.py', 'blueprint_sync_model')
    root = internal_sync_project
    scope = {(env, 'team', 'config') for env in ('dev', 'stg')}
    args = [arg for entry in sorted(scope) for arg in ('--scope', '/'.join(entry))]
    code, text = runner.run(['--scope', 'dev/team/config'], repository_root=root)
    assert code == 1 and 'include all affected Model services' in text and 'stg/team/config' in text
    design = root/'docs/designs/dev/team/config.md'
    saved = design.read_bytes()
    design.write_bytes(saved + b'old generated output\n')
    capsys.readouterr()
    code, text = runner.run(args, repository_root=root)
    assert code == 1 and 'generated Markdown is stale or missing' in text
    assert 'docs/designs/dev/team/config.md' in text
    validator = load('validate-blueprint').Validator(root, scope)
    validator.check_generated_service_models()
    assert any('generated Markdown is stale or missing' in error and 'dev/team/config.md' in error
               for error in validator.errors), validator.errors
    design.write_bytes(saved)
    assert runner.run(args, repository_root=root)[0] == 0
    assert capsys.readouterr() == ('', '')



@pytest.mark.parametrize('initial', [False, True])
def check_integrated_validator(generated_policy, initial):
    import subprocess
    root, model, values, design, artifact, register = generated_policy
    head_design = design.read_bytes()
    env = register([design, artifact, artifact.parent/"extra.json"])
    task = root/env['BLUEPRINT_TASK_FILE']
    task.write_text(task.read_text() + '\n## Required changes\n- [R1] Generate the selected service.\n'
                    '## Acceptance checks\n- [R1] `check:framework.generated-service-model`\n'
                    '- [R1] `check:framework.policy-tables`\n- [R1] `exists:docs/designs/dev/123456789012/iam.md`\n')
    for name in ('AGENTS.md', 'README.md', 'docs/system-overview.md'):
        p = root/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# Independent fixture\n')
    for name in ('infra/cloudformation/parameters/dev/123456789012', 'tests/scenarios', 'tests/results'):
        (root/name).mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Fixture'], cwd=root, check=True)
    if initial:
        shutil.rmtree(design.parent)
        readonly = load('validate-blueprint').Validator(root, {('dev', '123456789012', 'iam')})
        readonly.check_project_topology()
        readonly.check_validation_scope()
        assert any('validation input missing' in error for error in readonly.errors)
    from import_guard import snapshots
    base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    with snapshots(root, base, {}, definitions_root=definition_root(root)) as (before, after):
        assert after == root
        assert not (before/'framework').exists() and not (before/'framework').is_symlink()
        assert not any(p.name == 'framework' for p in before.parent.rglob('*'))
    original_project = (root/'project.json').read_bytes()
    with snapshots(root, base, {root/'project.json': '{}\n'}, definitions_root=definition_root(root)) as (before, after):
        assert after != root and (after/'project.json').read_bytes() == b'{}\n'
        assert (root/'project.json').read_bytes() == original_project
        assert not (after/'framework').exists() and not (before/'framework').exists()
    values['desired.note.001.text'] = '統合した生成と検証を確認する。'
    write_model(model, values)
    validator_module = load('validate-blueprint')
    import model.sources as model_sources
    import model.impact as model_impact
    import import_guard
    published = False
    read_bytes, transaction = Path.read_bytes, sync_runtime._publish_transaction
    def read(path):
        if published and path.is_relative_to(root):
            raise AssertionError('normal post-save readback: ' + str(path))
        return read_bytes(path)
    def publish(*args, **kwargs):
        nonlocal published
        result = transaction(*args, **kwargs)
        published = True
        return result
    with patch.dict(os.environ, env), \
         patch.object(model_impact, 'affected', wraps=model_impact.affected) as impact, \
         patch.object(import_guard, 'require_import_changes', wraps=import_guard.require_import_changes) as import_check, \
         patch.object(sync_runtime, '_publish_transaction', side_effect=publish), \
         patch.object(Path, 'read_bytes', read), \
         patch.object(model_sources, '_read_model', wraps=model_sources._read_model) as expand, \
         patch.object(sync_runtime, 'generate_views', wraps=sync_runtime.generate_views) as generate, \
         patch.object(sync_views, 'validate_views', wraps=sync_views.validate_views) as validate, \
         patch.object(sync_runtime.GenerationInputs, 'verify', autospec=True, side_effect=sync_runtime.GenerationInputs.verify) as verify, \
         patch.object(validator_module.Validator, 'check_generated_service_models', side_effect=AssertionError('regenerated for Acceptance')):
        validator = validator_module.Validator(root, {('dev', '123456789012', 'iam')}, write=True)
        assert validator.run() == 0, validator.errors
        assert len(validator.acceptance_results) == 3
    assert generate.call_count == validate.call_count == verify.call_count == 1
    contexts = [(call.args[0], id(call.args[1])) for call in expand.call_args_list]
    assert contexts and len(contexts) == len(set(contexts)), expand.call_args_list
    print('integrated write counts: Model once per input/permission context; generation=1, candidate validation=1, guard=1, post-save readback=0')
    assert import_check.call_count == 1 and impact.call_count == 2, (impact.call_count, import_check.call_count)
    assert values['desired.note.001.text'] in design.read_text()
    if not initial:
        from tempfile import TemporaryDirectory
        scope = {('dev', '123456789012', 'iam')}
        with TemporaryDirectory() as cache, patch.dict(os.environ, {**env, 'BLUEPRINT_VALIDATION_CACHE_DIR': cache}):
            cold = validator_module.Validator(root, scope, cache=True)
            assert cold.run() == 0, cold.errors
            with patch.object(sync_runtime, 'generate_views', side_effect=AssertionError('warm cache regenerated')):
                warm = validator_module.Validator(root, scope, cache=True)
                assert warm.run() == 0, warm.errors
            with patch.object(sync_runtime, 'generate_views', wraps=sync_runtime.generate_views) as generate:
                fresh = validator_module.Validator(root, scope, cache=True, fresh=True)
                assert fresh.run() == 0, fresh.errors
                assert generate.call_count == 1
            originals = {p: p.read_bytes() for p in (design, artifact)}
            extra = artifact.parent/'extra.json'
            for path, content in ((design, originals[design]+b'old Markdown\n'), (artifact, b'{}\n'), (extra, b'{}\n')):
                path.write_bytes(content)
                invalid = validator_module.Validator(root, scope, cache=True)
                assert invalid.run() == 1
                if path != extra:
                    assert not any('framework.generated-service-model' in result for result in invalid.acceptance_results)
                if path == extra:
                    path.unlink()
                else:
                    path.write_bytes(originals[path])
        # Real Git commits remain visible against the pinned synthetic managed baseline.
        baseline = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Task generated B'], cwd=root, check=True)
        with patch.dict(os.environ, env), patch('worktree_task.task_start_commit', return_value=baseline), \
             patch.object(sync_runtime.GenerationInputs, 'verify', autospec=True, side_effect=sync_runtime.GenerationInputs.verify) as guard, \
             patch.object(sync_runtime, '_publish_transaction', side_effect=AssertionError('no-op publication')):
            committed_write = validator_module.Validator(root, scope, write=True)
            assert committed_write.run() == 0, committed_write.errors
            assert guard.call_count == 1
            committed_read = validator_module.Validator(root, scope)
            assert committed_read.run() == 0, committed_read.errors
            assert committed_write.changed_paths == committed_read.changed_paths
            assert design.relative_to(root).as_posix() in committed_write.changed_paths
        # Publication can return committed B to the original Task-start A.

        values.pop('desired.note.001.text')
        write_model(model, values)
        template = model
        template.write_bytes(template.read_bytes()+b'# source-only comment\n')
        task.write_text(task.read_text()+'- [R1] `changed:docs/designs/dev/123456789012/iam.md`\n')
        with patch.dict(os.environ, env), patch('worktree_task.task_start_commit', return_value=baseline):
            restored = validator_module.Validator(root, scope, write=True)
            assert restored.run() == 1
        assert design.read_bytes() == head_design
        assert any('required changed path missing' in error for error in restored.errors)
        assert design.relative_to(root).as_posix() not in restored.changed_paths
        assert design.relative_to(root).as_posix() in restored.task.permission_paths
        from validation.findings import Findings
        from validation.task import TaskValidation
        with patch.dict(os.environ, env), patch('worktree_task.task_start_commit', return_value=baseline):
            final = TaskValidation(root, Findings(root))
            final.check_task_scope()
            assert design.relative_to(root).as_posix() not in final.changed_paths
            assert design.relative_to(root).as_posix() in final.permission_paths

    if initial:
        originals = {p: p.read_bytes() for p in (design, artifact)}
        contract = task.read_text()
        task.write_text(contract.replace('- Task type: `design`', '- Task type: `scenario-test`'))
        # Commit current source/output state so only the prospective output violates type.
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Boundary baseline'], cwd=root, check=True)
        with patch.dict(os.environ, env):
            boundary = validator_module.Validator(root, {('dev', '123456789012', 'iam')}, write=True)
            boundary.task.fix_baseline()
            design.unlink()
            # Hold initial permission paths empty; exercise the planned-output boundary itself.
            with patch.object(boundary.task, 'git_paths', return_value=set()), \
                 patch.object(sync_runtime, '_publish_transaction', side_effect=AssertionError('forbidden publisher')) as publisher:
                assert boundary.run() == 1
            assert not publisher.called
            assert any('scenario-test task boundary violation' in e for e in boundary.errors), boundary.errors
            assert not design.exists() and artifact.read_bytes() == originals[artifact]
        design.write_bytes(originals[design])
        task.write_text(contract)

        values['desired.note.001.text'] = '保存失敗時にもModel入力を保持する。'
        write_model(model, values)
        write = Path.write_text
        def fail_write(path, *args, **kwargs):
            if path == design:
                write(path, 'partial output', encoding='utf-8')
                raise OSError('injected publication I/O')
            return write(path, *args, **kwargs)
        original_policy_check = validator_module.Validator.check_policy_tables
        def candidate_policy_check(validator):
            if validator.root == root:
                raise AssertionError('post-save content handler')
            return original_policy_check(validator)
        with patch.dict(os.environ, env), patch.object(Path, 'write_text', fail_write), \
             patch.object(validator_module.Validator, 'check_policy_tables', candidate_policy_check):
            failed = validator_module.Validator(root, {('dev', '123456789012', 'iam')}, write=True)
            assert failed.run() == 1
        assert originals == {p: p.read_bytes() for p in originals}
        assert any('injected publication I/O' in error for error in failed.errors)
        assert not any('framework.policy-tables' in result for result in failed.acceptance_results)
        assert load_model(model).values['desired.note.001.text'] == values['desired.note.001.text']



@pytest.mark.parametrize('failure', ['none', 'input', 'candidate', 'io', 'rollback'])
def check_multiple_targets_barrier(generated_policy, failure):
    root, model, values, design, artifact, register = generated_policy
    scope = {('dev', '123456789012', 'iam'), ('stg', '123456789012', 'logs')}
    project = json.loads((root/'project.json').read_text())
    project['targets'].append({**project['targets'][0], 'environment': 'stg'})
    (root/'project.json').write_text(json.dumps(project)+'\n')
    log_model = root/'model/stg/123456789012/logs.properties'
    log_values = {'desired.service.logs.serviceId': 'logs',
        'desired.service.logs.ownedCatalogResourceTypes': 'Logs.LogGroup',
        'display.service.title': '# Logs 詳細設計',
        'desired.resource.001.resourceType': 'Logs.LogGroup',
        'display.resource.001.comment': 'アプリケーションの実行ログ',
        'desired.row.001-001.property': 'Logs.LogGroup.LogGroupName',
        'desired.row.001-001.value': '`cwlogs-app-stg`',
        'desired.row.001-001.comment': 'ログを識別する名前'}
    log_values.update(allocate(log_values, ['001']))
    if failure == 'candidate':
        del log_values['desired.row.001-001.value']
    write_model(log_model, log_values)
    log_design = root/'docs/designs/stg/123456789012/logs.md'
    env = register([design, artifact, log_design])
    task = root/env['BLUEPRINT_TASK_FILE']
    task.write_text(task.read_text().replace('- `dev/123456789012/iam`\n',
                    '- `dev/123456789012/iam`\n- `stg/123456789012/logs`\n', 1))
    original = design.read_bytes()
    values['desired.note.001.text'] = '先行対象も後続の確認を待つ。'
    write_model(model, values)
    events = []
    validate, transaction = sync_runtime.validate_generation, sync_runtime._publish_transaction
    def validated(plan, **kwargs):
        assert len(plan.generated) == (1 if failure == 'candidate' else 2)
        assert design.read_bytes() == original and not log_design.exists()
        validate(plan, **kwargs)
        events.append('validated')
        if failure == 'input':
            source = log_model
            source.write_bytes(source.read_bytes()+b'\n')
    published = False
    read_bytes = Path.read_bytes
    def read(path):
        if published and failure == 'none' and path.is_relative_to(root):
            raise AssertionError('normal post-save input/output read: ' + str(path))
        return read_bytes(path)
    def publish(*args, **kwargs):
        nonlocal published
        assert events == ['validated']
        if failure == 'io' and log_design in args[1]:
            raise OSError('injected late target I/O')
        if failure == 'rollback':
            import sync_files
            write = Path.write_text
            def failed_write(path, *a, **kw):
                if path == design:
                    write(path, 'partial output', encoding='utf-8')
                    raise OSError('injected write failure')
                return write(path, *a, **kw)
            with patch.object(Path, 'write_text', failed_write), \
                 patch.object(sync_files, 'restore_files', side_effect=OSError('injected restore failure')):
                return transaction(*args, **kwargs)
        result = transaction(*args, **kwargs)
        published = True
        return result
    with patch.dict(os.environ, env), patch.object(sync_runtime, 'validate_generation', side_effect=validated), \
         patch.object(sync_runtime, '_publish_transaction', side_effect=publish) as saved, \
         patch.object(sync_runtime, 'stage_inputs', wraps=sync_runtime.stage_inputs) as stages, \
         patch.object(Path, 'read_bytes', read):
        if failure == 'input':
            with pytest.raises(ValueError, match='inputs changed'):
                sync_runtime.run_generation(root, scope)
            assert not saved.called and design.read_bytes() == original and not log_design.exists()
        elif failure == 'rollback':
            with pytest.raises(ValueError, match='rollback incomplete; recovery journal retained'):
                sync_runtime.run_generation(root, scope)
            assert saved.call_count == 1 and not log_design.exists()
            from model.sources import publication_lock
            with publication_lock(root) as journal:
                assert not journal.exists() and design.read_bytes() == original
        elif failure in {'candidate', 'io'}:
            with pytest.raises(ValueError, match='1 services succeeded; 1 services failed'):
                sync_runtime.run_generation(root, scope)
            assert not log_design.exists() and values['desired.note.001.text'] in design.read_text()
        else:
            assert sync_runtime.run_generation(root, scope) == 0
            assert saved.call_count == 2 and log_design.is_file()
        assert stages.call_count == 1



if __name__ == "__main__":
    raise SystemExit(main())

