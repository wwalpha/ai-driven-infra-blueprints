#!/usr/bin/env python3
"""Progress and permission parsing reuse retain live safety checks."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import io
import os
import threading
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
import pytest
import task_contract as tasks
import import_scope
import sync_progress as progress
import sync_runtime
from validation_cache import input_scope
from support.sync_model_fixtures import generated_policy
from support.pytest_cli import run

pytestmark = pytest.mark.usefixtures('catalog_display_fixture')


def contract(name, allowed='output.txt', workflow=''):
    return (f'## Task contract\n- Task type: `migration`\n- Task status: `running`\n{workflow}'
            '## Validation scope\n- `dev/team/iam`\n'
            f'## Modified files\n- `{name}`\n- `output.txt`\n'
            f'## Allowed paths\n- `{name}`\n- `{allowed}`\n')


@pytest.mark.parametrize('allowed,accepted', [('output.txt', True), ('*.txt', True), ('out*', True), ('other.txt', False)])
def check_allowed_paths(tmp_path, allowed, accepted):
    name = 'tasks/test.md'
    records = {name: contract(name, allowed)}
    if accepted:
        assert tasks.reservations(tmp_path, records)[name].active == {name, 'output.txt'}
        if allowed == 'output.txt':
            with patch.object(tasks, 'matches', side_effect=AssertionError('exact matches need no pattern scan')):
                tasks.reservations(tmp_path, records)
    else:
        with pytest.raises(ValueError, match='outside Allowed paths'):
            tasks.reservations(tmp_path, records)
    external = tmp_path / 'external'
    external.write_text('safe')
    (tmp_path / 'output.txt').symlink_to(external)
    with pytest.raises(ValueError, match='symlinks'):
        tasks.reservations(tmp_path, records)


def check_live_selection(tmp_path):
    (tmp_path / 'tasks').mkdir()
    one, two = 'tasks/one.md', 'tasks/two.md'
    original = contract(one)
    (tmp_path / one).write_text(original)
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'tasks').mkdir()
    (other / one).write_text(contract(one, workflow='- Workflow: `import`\n'))

    @input_scope
    def exercise():
        with patch.dict(os.environ, {tasks.SELECTOR: one}):
            assert import_scope.selected(tmp_path) is None
            assert import_scope.selected(tmp_path) is None  # cached negative parsing result
            from validation_cache import memo_table
            assert (import_scope._selection.__wrapped__, (tmp_path, one, original)) in memo_table()
            assert import_scope.selected(other) == ('dev', 'team', 'iam')
            stat = (tmp_path / one).stat()
            (tmp_path / one).write_text(contract(one, workflow='- Workflow: `import`\n'))
            os.utime(tmp_path / one, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            assert import_scope.selected(tmp_path) == ('dev', 'team', 'iam')
            (tmp_path / one).write_text(original)
            assert import_scope.selected(tmp_path) is None
            (tmp_path / two).write_text(contract(two, workflow='- Workflow: `import`\n- IMPORT target: `stg/team/config`\n'))
            with patch.dict(os.environ, {tasks.SELECTOR: two}):
                assert import_scope.selected(tmp_path) == ('stg', 'team', 'config')
            assert import_scope.selected(tmp_path) is None
            with import_scope.restrict(('dev', 'team', 'vpc')):
                assert import_scope.selected(tmp_path) == ('dev', 'team', 'vpc')
            assert import_scope.selected(tmp_path) is None
            (tmp_path / two).unlink()
            (tmp_path / one).write_text(contract(one, 'denied'))
            with pytest.raises(ValueError, match='outside Allowed paths'):
                import_scope.selected(tmp_path)
            (tmp_path / one).write_text(original)
            (tmp_path / 'external').write_text('safe')
            (tmp_path / 'output.txt').symlink_to(tmp_path / 'external')
            with pytest.raises(ValueError, match='symlinks'):
                import_scope.selected(tmp_path)
            (tmp_path / 'output.txt').unlink()
            (tmp_path / one).write_text(original.replace('`running`', '`suspend`')+'## Suspension reason\nExplicit test stop\n')
            with pytest.raises(ValueError, match='suspend task'):
                import_scope.selected(tmp_path)
    exercise()


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
        with progress.phase('reservation', status='reservation-wait'):
            pass
        progress.completed(('dev', 'team', 'iam'))
        with pytest.raises(ValueError), progress.phase('candidate-validation'):
            raise ValueError('injected')
    text = output.getvalue()
    for expected in ['heartbeat', 'items=1/2', 'completed=1/1', 'lock-wait', 'reservation-wait', 'stage-failed', 'remaining=unknown', 'not proof of progress']:
        assert expected in text
    assert reporter.states == []


def check_publication_lock_wait(tmp_path):
    import model_templates
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
            with reporter.worker('dev/team/iam'), model_templates.publication_lock(tmp_path):
                with model_templates.publication_lock(tmp_path):
                    pass
        except BaseException as error:
            errors.append(error)
    with redirect_stderr(output):
        with model_templates.publication_lock(tmp_path):
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
    shutil.copytree(root / 'model/parameters/dev', root / 'model/parameters/stg')
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
    template = root / 'model/templates/123456789012/iam.properties.tpl'
    template.write_text(template.read_text().replace('アプリケーションの実行権限', '更新後の処理権限'))
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


@pytest.mark.parametrize('filename', ['parameters.yaml', 'bindings.json', 'observed.json', 'template'])
@pytest.mark.parametrize('mutation', ['change', 'delete', 'add'])
def check_input_mutation(generated_policy, filename, mutation):
    root, model, _, design, artifact, register = generated_policy
    directory = root / 'model/parameters/dev/123456789012/iam'
    source = root / 'model/templates/123456789012/iam.properties.tpl' if filename == 'template' else directory / filename
    if mutation == 'add' and filename != 'observed.json':
        source = (source.with_suffix('') / 'added.properties' if filename == 'template' else directory / 'new' / filename)
    if filename == 'observed.json' and mutation != 'add' and not source.exists():
        source.write_text('{"version":1,"values":{}}\n')
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


if __name__ == '__main__':
    raise SystemExit(run(__file__, message='sync performance: PASS'))
