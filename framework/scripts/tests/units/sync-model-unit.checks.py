#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.sync_model_fixtures import *

def check_property_path_parents():
    paths = {"ConnectionInput.PhysicalConnectionRequirements.SubnetId", "Rules[].Target.Name", "ConnectionInputName"}
    assert property_paths_with_parents(paths) == {
        *paths, "ConnectionInput", "ConnectionInput.PhysicalConnectionRequirements", "Rules", "Rules[]", "Rules[].Target",
    }
    assert "ConnectionInput" not in property_paths_with_parents({"ConnectionInputName"})
    assert not property_paths_with_parents(set())



@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("final", [False, True])
def check_markdown_newlines(tmp_path, newline, final):
    from support.model_sources import write_fixture_files as save_files
    path = tmp_path / "design.md"
    expected = ("# 日本語" + newline + "value" + (newline if final else "")).encode("utf-8")
    path.write_bytes(expected)
    write_fixture_files({path: "# 日本語\nvalue\n"})
    assert path.read_bytes() == expected
    write_fixture_files({path: "# 日本語\nchanged\n"})
    assert path.read_bytes() == expected.replace(b"value", b"changed"), "semantic change must remain visible"
    before = path.read_bytes()
    from sync_files import changed_files
    assert changed_files({path: '# 日本語\nchanged\n'}) == {}, 'publication comparison must preserve newlines'
    assert set(changed_files({path: '# 日本語\nupdated\n'})) == {path}
    with patch.object(Path, "write_text", side_effect=AssertionError("idempotent Markdown rewritten")):
        write_fixture_files({path: before.decode("utf-8")})
    path.write_bytes(b"one\r\ntwo\n")
    with pytest.raises(ValueError, match="mixed Markdown newlines"):
        write_fixture_files({path: "one\ntwo\n"})
    assert path.read_bytes() == b"one\r\ntwo\n"
    path.write_bytes(b"one\rtwo")
    with pytest.raises(ValueError, match="unsupported Markdown newline"):
        write_fixture_files({path: "one\ntwo\n"})
    assert path.read_bytes() == b"one\rtwo"


def check_file_rollback(tmp_path):
    from support.model_sources import write_fixture_files as save_files
    root = tmp_path
    first, created, last = [root / name for name in ('first.md', 'new.json', 'last.md')]
    originals = {first: b'first\r\n', last: b'last\r\n'}
    write_text, write_bytes = Path.write_text, Path.write_bytes
    for failed in (first, created, last):
        for path, content in originals.items():
            path.write_bytes(content)
        calls = []
        def fail_write(path, *args, **kwargs):
            calls.append(path)
            if path == failed:
                write_text(path, 'partially written', encoding='utf-8')
                raise OSError('injected publication failure')
            return write_text(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail_write):
            with pytest.raises(OSError) as error:
                write_fixture_files({first: 'changed\n', created: '{}\n', last: 'changed\n'})
            assert str(error.value) == 'injected publication failure'
        assert failed in calls
        assert {path: path.read_bytes() for path in originals} == originals
    restores = []
    def fail_restore(path, content):
        restores.append(path)
        raise OSError('injected restoration failure')
    with patch.object(Path, 'write_text', fail_write), patch.object(Path, 'write_bytes', fail_restore):
        with pytest.raises(OSError) as error:
            write_fixture_files({first: 'changed\n', created: '{}\n', last: 'changed\n'})
        assert 'generated-file rollback failed:' in str(error.value)
        assert all(f'{path}: injected restoration failure' in str(error.value) for path in (last, first))
    assert last in calls and restores == [last, first]
    for path, content in originals.items():
        write_bytes(path, content)
    with patch.object(Path, 'write_text', side_effect=AssertionError('unchanged file rewritten')):
        write_fixture_files({path: content.decode('utf-8') for path, content in originals.items()})
    print('File rollback: PASS (first/middle/last partial write, restoration error, no-op)')


import threading
import sync_progress as progress


def check_progress_heartbeat_and_waits():
    output = io.StringIO()
    reporter = progress.Progress(interval=0.01)
    with redirect_stderr(output), reporter.worker('dev/team/iam'):
        progress.consumers({('dev', 'team', 'iam')})
        with progress.phase('dependency-model', total=2):
            progress.advance()
            # Trigger exactly one heartbeat without sleeping or changing production interval.
            with patch.object(reporter.stop, 'wait', side_effect=[False, True]):
                reporter.heartbeat()
        lock = threading.Lock()
        lock.acquire()
        original_acquire = lock.acquire
        class ReleasedLock:
            def acquire(self, blocking=True):
                if not blocking:
                    return False
                lock.release()
                return original_acquire()
            def release(self):
                lock.release()
        with progress.thread_lock(ReleasedLock()):
            pass
        with progress.phase('generation', status='running'):
            pass
        progress.completed(('dev', 'team', 'iam'))
        with pytest.raises(ValueError), progress.phase('candidate-validation'):
            raise ValueError('injected')
    text = output.getvalue()
    for expected in ['heartbeat', 'items=1/2', 'completed=1/1', 'lock-wait', 'stage-failed', 'remaining=unknown', 'not proof of progress']:
        assert expected in text
    assert reporter.states == []



def check_generation_counts(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    values['desired.note.001.text'] = '一回の候補を保存する。'
    write_model(model, values)
    from model_templates import load_sources
    from validation_cache import input_scope
    import model_templates
    from contextlib import ExitStack
    from validation import design as design_checks, design_tables, design_links, cloudformation
    with ExitStack() as stack:
        checks = [(design_checks, name) for name in ('check_design_service_ownership', 'check_resource_names',
                  'check_observed_values', 'check_policy_tables')]
        checks += [(sync_runtime, 'validate_required_properties'), (design_tables, 'check_design_tables'), (design_links, 'check_design_overviews'),
                   (design_links, 'check_design_links'), (design_links, 'check_design_artifacts'),
                   (cloudformation, 'check_stack_designs'), (sync_views, 'check_projection')]
        counters = [stack.enter_context(patch.object(module, name, wraps=getattr(module, name))) for module, name in checks]
        with patch.dict(os.environ, register([design, artifact])), \
             patch.object(sync_runtime, 'generate_views', wraps=sync_runtime.generate_views) as generate, \
             patch.object(sync_views, 'validate_views', wraps=sync_views.validate_views) as validate, \
             patch.object(sync_runtime.GenerationInputs, 'verify', autospec=True, side_effect=sync_runtime.GenerationInputs.verify) as verify, \
             patch.object(model_templates, 'load_sources', wraps=load_sources) as expand, \
             patch.object(sync_runtime, 'verify_saved', side_effect=AssertionError('post-save readback')):
            assert sync_runtime.sync(root, True, 'dev', '123456789012', ['iam']) == 0
        assert generate.call_count == validate.call_count == verify.call_count == 1
        assert len([call for call in expand.call_args_list if call.args[0].stem == 'iam']) == 1
        assert all(counter.call_count == 1 for counter in counters), [counter.call_count for counter in counters]
    assert values['desired.note.001.text'] in design.read_text()
    assert json.loads(artifact.read_text()) == json.loads(values['desired.row.001-002.document'])


@pytest.mark.parametrize('mutation', ['parameters', 'bindings', 'observed', 'template', 'consumer', 'common', 'contract'])
def check_batch_input_change(generated_policy, mutation):
    root, model, values, design, artifact, register = generated_policy
    env = register([design, artifact])
    targets = {'parameters': root/'model/parameters/dev/123456789012/iam/parameters.yaml',
               'bindings': root/'model/parameters/dev/123456789012/iam/bindings.json',
               'observed': root/'model/parameters/dev/123456789012/iam/observed.json',
               'template': root/'model/templates/123456789012/iam.properties.tpl',
               'consumer': root/'model/parameters/stg/123456789012/iam/bindings.json',
               'common': root/'framework/rules/model-information.md',
               'contract': root/env['BLUEPRINT_TASK_FILE']}
    changed = targets[mutation]
    original = {p: p.read_bytes() for p in (design, artifact)}
    validate = sync_runtime.validate_candidates
    def mutate(*args, **kwargs):
        result = validate(*args, **kwargs)
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_bytes((changed.read_bytes() if changed.exists() else b'') + b'\n')
        return result
    with patch.dict(os.environ, env), patch.object(sync_runtime, 'validate_candidates', side_effect=mutate), \
         patch.object(sync_runtime, '_publish_transaction', side_effect=AssertionError('saved before global comparison')):
        with pytest.raises(ValueError, match='inputs changed.*' + changed.name):
            sync_runtime.sync(root, True, 'dev', '123456789012', ['iam'])
    assert original == {p: p.read_bytes() for p in original}
    assert changed.read_bytes().endswith(b'\n')


def check_snapshot_conflict(tmp_path):
    root = tmp_path
    snapshot = sync_runtime.GenerationInputs(root)
    path = root/'project.json'
    with pytest.raises(ValueError, match='inputs changed while reading'):
        snapshot.record(path, b'different')
    with pytest.raises(ValueError, match='inputs changed before publication'):
        snapshot.verify()


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
    values['desired.note.001.text'] = '統合した生成と検証を確認する。'
    write_model(model, values)
    validator_module = load('validate-blueprint')
    import model_templates, import_guard
    with patch.dict(os.environ, env), \
         patch.object(model_templates, 'affected', wraps=model_templates.affected) as impact, \
         patch.object(import_guard, 'require_import_changes', wraps=import_guard.require_import_changes) as import_check, \
         patch.object(sync_runtime, 'generate_views', wraps=sync_runtime.generate_views) as generate, \
         patch.object(sync_views, 'validate_views', wraps=sync_views.validate_views) as validate, \
         patch.object(sync_runtime.GenerationInputs, 'verify', autospec=True, side_effect=sync_runtime.GenerationInputs.verify) as verify, \
         patch.object(validator_module.Validator, 'check_generated_service_models', side_effect=AssertionError('regenerated for Acceptance')):
        validator = validator_module.Validator(root, {('dev', '123456789012', 'iam')}, write=True)
        assert validator.run() == 0, validator.errors
        assert len(validator.acceptance_results) == 3
    assert generate.call_count == validate.call_count == verify.call_count == 1
    assert impact.call_count == import_check.call_count == 1
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
        # Publication can return a pre-existing Git difference to HEAD/Index.
        values.pop('desired.note.001.text')
        write_model(model, values)
        template = root/'model/templates/123456789012/iam.properties.tpl'
        template.write_bytes(template.read_bytes()+b'# source-only comment\n')
        task.write_text(task.read_text()+'- [R1] `changed:docs/designs/dev/123456789012/iam.md`\n')
        with patch.dict(os.environ, env):
            restored = validator_module.Validator(root, scope, write=True)
            assert restored.run() == 1
        assert design.read_bytes() == head_design
        assert any('required changed path missing' in error for error in restored.errors)
        assert design.relative_to(root).as_posix() not in restored.changed_paths
    if initial:
        originals = {p: p.read_bytes() for p in (design, artifact)}
        values['desired.note.001.text'] = '保存失敗時にもModel入力を保持する。'
        write_model(model, values)
        write = Path.write_text
        def fail_write(path, *args, **kwargs):
            if path == design:
                write(path, 'partial output', encoding='utf-8')
                raise OSError('injected publication I/O')
            return write(path, *args, **kwargs)
        with patch.dict(os.environ, env), patch.object(Path, 'write_text', fail_write), \
             patch.object(validator_module.Validator, 'check_policy_tables', side_effect=AssertionError('post-save content handler')):
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
                  'desired.resource.001.logicalId': 'ApplicationLog',
                  'desired.resource.001.anchor': 'logs-cwlogs-app-stg',
                  'display.resource.001.comment': 'アプリケーションの実行ログ',
                  'desired.row.001-001.property': 'Logs.LogGroup.LogGroupName',
                  'desired.row.001-001.value': '`cwlogs-app-stg`',
                  'desired.row.001-001.comment': 'ログを識別する名前'}
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
            source = root/'model/parameters/stg/123456789012/logs/parameters.yaml'
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
            from model_templates import publication_lock
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


@pytest.mark.parametrize('scope,contract_scope', [(set(), None), (None, set())])
def check_framework_write_does_not_discover(tmp_path, scope, contract_scope):
    module = load('validate-blueprint')
    with patch.object(Path, 'rglob', side_effect=AssertionError('Model discovery')), \
         patch.object(sync_runtime, 'prepare_generation', side_effect=AssertionError('Model generation')):
        validator = module.Validator(tmp_path, scope, contract_scope, write=True)
        assert validator.run() == 1
        assert 'framework scope' in validator.errors[0]


def check_result_reuse_is_scoped(tmp_path):
    from validation.findings import Findings, CheckResult
    from validation.task import TaskValidation
    findings = Findings(tmp_path)
    task = TaskValidation(tmp_path, findings)
    first, second = {('dev', 'team', 'iam')}, {('stg', 'team', 'iam')}
    calls = []
    def fail():
        calls.append('fail')
        findings.check(False, 'content failed')
    task.acceptance_checks = [('R1', 'check', 'content'), ('R2', 'check', 'content')]
    findings.evaluate('content', first, fail)
    task.check_acceptance_checks({'content': fail}, first)
    assert calls == ['fail'] and not task.acceptance_results
    task.acceptance_checks = [('R3', 'check', 'content')]
    task.check_acceptance_checks({'content': lambda: calls.append('other scope')}, second)
    assert calls[-1] == 'other scope' and len(task.acceptance_results) == 1
    key = ('content', frozenset(first), object())
    findings.candidate = key[2]
    findings.results[key] = CheckResult(*key)
    task.check_acceptance_checks({'content': lambda: calls.append('not run')}, first)
    assert calls[-1] == 'not run'


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
