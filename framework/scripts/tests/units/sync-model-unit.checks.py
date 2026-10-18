#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import io
from contextlib import redirect_stderr
import os
import pytest
from unittest.mock import patch
from support.validator import load
from design_catalog import property_paths_with_parents
import sync_runtime
import sync_views
from sync_files import save_files as write_fixture_files




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
    from sync_files import markdown_newlines, changed_files
    path = tmp_path / 'design.md'
    expected = ('# 日本語' + newline + 'value' + (newline if final else '')).encode('utf-8')
    path.write_bytes(expected)
    assert markdown_newlines(path, '# 日本語\nvalue\n').encode() == expected
    assert changed_files({path: '# 日本語\nvalue\n'}) == {}
    assert set(changed_files({path: '# 日本語\nchanged\n'})) == {path}
    path.write_bytes(b'one\r\ntwo\n')
    with pytest.raises(ValueError, match='mixed Markdown newlines'):
        markdown_newlines(path, 'one\ntwo\n')
    path.write_bytes(b'one\rtwo')
    with pytest.raises(ValueError, match='unsupported Markdown newline'):
        markdown_newlines(path, 'one\ntwo\n')


import threading
import sync_progress as progress








def check_internal_sync_concurrent_output(tmp_path, capsys):
    from concurrent.futures import ThreadPoolExecutor
    from script_loader import module
    from validation_cache import input_scope, memo_table
    runner = module('sync-model.py', 'blueprint_sync_model')
    barrier = threading.Barrier(2, timeout=10)
    reports = []
    @input_scope
    def execute(root, write, **kwargs):
        memo = memo_table()
        memo['root'] = root
        reports.append(progress._current.get()[0])
        barrier.wait()
        assert memo == {'root': root}
        print(str(root), file=progress.output_file())
        with progress.phase('isolated-heartbeat'):
            reporter = progress._current.get()[0]
            with patch.object(reporter.stop, 'wait', side_effect=[False, True]):
                reporter.heartbeat()
        raise ValueError('invalid generation at ' + str(root))
    roots = [tmp_path/'first', tmp_path/'second']
    with patch.object(runner, 'sync', side_effect=execute), ThreadPoolExecutor(2) as executor:
        futures = [executor.submit(runner.run, ['--all'], repository_root=root) for root in roots]
        results = [future.result() for future in futures]
    for root, other, (code, text) in zip(roots, reversed(roots), results):
        assert code == 1 and str(root) in text and str(other) not in text
        assert 'heartbeat' in text and 'invalid generation at' in text
    assert len({id(report) for report in reports}) == 2
    assert all(report.stop.is_set() and not report.states for report in reports)
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('arguments,code,diagnostic', [
    (['--help'], 0, 'usage:'), (['--jobs', '3'], 2, 'invalid choice'),
    (['--environment', 'dev'], 2, 'exactly one'),
    (['--scope', '../team/config'], 1, 'invalid generation scope')])
def check_internal_sync_arguments(tmp_path, arguments, code, diagnostic, capsys):
    from script_loader import module
    runner = module('sync-model.py', 'blueprint_sync_model')
    (tmp_path/'tasks').mkdir()
    (tmp_path/'tasks/active.md').write_text('## Validation scope\n- `all`\n')
    result, text = runner.run(arguments, repository_root=tmp_path)
    assert result == code and diagnostic in text, text
    assert progress._current.get() is None and progress._output.get() is None
    assert capsys.readouterr() == ('', '')


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







def check_snapshot_conflict(tmp_path):
    from validation_cache import recording_inputs, input_bytes, input_select, input_is_file
    snapshot = sync_runtime.GenerationInputs(tmp_path)
    path = tmp_path / 'project.json'
    assert snapshot.read(path) is None
    with pytest.raises(ValueError, match='inputs changed while reading'):
        snapshot.record(path, b'different')
    with pytest.raises(ValueError, match='inputs changed before publication'):
        snapshot.verify()
    snapshot.close()
    snapshot = sync_runtime.GenerationInputs(tmp_path)
    with recording_inputs(snapshot):
        assert not input_is_file(path)
        with pytest.raises(FileNotFoundError):
            input_bytes(path)
        assert input_select(tmp_path, '*.json') == ()
        snapshot.seal()
        path.write_bytes(b'new')
        assert not input_is_file(path)  # Sealed reads retain the recorded missing state.
        with pytest.raises(ValueError, match='after seal'):
            snapshot.read(tmp_path / 'new-dependency')
        with pytest.raises(ValueError, match='inputs changed before publication'):
            snapshot.verify()
    snapshot.close()


def check_planned_outputs_and_boundary(tmp_path):
    from types import SimpleNamespace
    from sync_files import markdown_newlines
    from validation.findings import Findings
    from validation.task import TaskValidation
    path, created = tmp_path/'view.md', tmp_path/'new.json'
    path.write_bytes(b'original\r\n')
    snapshot = sync_runtime.GenerationInputs(tmp_path)
    expected = {path: markdown_newlines(path, 'original\n'), created: '{}\n'}
    plan = SimpleNamespace(expected_outputs={path: expected}, snapshot=snapshot)
    assert sync_runtime.planned_outputs(plan) == {created}
    expected[path] = markdown_newlines(path, 'changed\n')
    assert sync_runtime.planned_outputs(plan) == {path, created}
    findings = Findings(tmp_path)
    task = TaskValidation(tmp_path, findings)
    task.task_type = 'scenario-test'
    task.changed_paths = {'tests/scenarios/allowed/scenario.md'}
    task.check_task_boundary(tmp_path/'tasks/test.md')
    assert not findings.errors
    task.check_task_boundary(tmp_path/'tasks/test.md', {'docs/designs/dev/team/iam.md'})
    assert len(findings.errors) == 1 and 'scenario-test task boundary' in findings.errors[0]
    assert task.changed_paths == {'tests/scenarios/allowed/scenario.md'}
    snapshot.close()


def check_stage_dependency_selection(tmp_path):
    from types import SimpleNamespace
    from validation_cache import recording_inputs
    root, stage = tmp_path/'root', tmp_path/'stage'
    selected = root/'docs/designs/dev/team/iam.md'
    files = {'docs/designs/dev/team/iam.md': '# selected\n',
             'docs/designs/dev/team/iam/policy.json': '{}\n',
             'docs/designs/dev/team/other.md': '# unrelated\n',
             'docs/designs/dev/team/out.md': '# reference\n',
             'docs/designs/dev/team/in.md': '[incoming](iam.md#id)\n',
             'model/templates/team/iam.properties.tpl': '# required\n',
             'model/templates/team/unrelated.properties.tpl': '# unused\n',
             'model/parameters/dev/team/iam/parameters.yaml': 'instances: {}\n',
             'project.json': '{}\n', 'tests/results/unrelated.log': 'unrelated\n'}
    for relative, text in files.items():
        file = root/relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    model = root/'model/dev/team/iam.properties'
    template, parameters = root/'model/templates/team/iam.properties.tpl', root/'model/parameters/dev/team/iam/parameters.yaml'
    inputs = sync_runtime.GenerationInputs(root)
    # Caller-owned snapshots are reused, including readers, without inner cleanup.
    values = {'link': '[out](out.md#id)'}
    def loaded(path):
        from validation_cache import input_bytes
        return SimpleNamespace(values=values, files={p: input_bytes(p).decode() for p in (template, parameters)})
    inputs.stage = stage
    with patch.object(sync_runtime.GenerationInputs, '__init__', side_effect=AssertionError('duplicate recorder')), \
         patch.object(inputs, 'close', wraps=inputs.close) as close, \
         patch('validation_cache.PassCache.common_inputs', side_effect=AssertionError('duplicate common registration')), \
         patch.object(sync_runtime, 'registered_models', return_value=[model]), \
         patch.object(sync_runtime, 'service_source', return_value=(root, template, parameters.parent)), \
         patch.object(sync_runtime, 'load_model', side_effect=loaded), \
         patch.object(sync_runtime, 'generate_views', return_value={}), \
         patch.object(sync_views, 'broken_design_links', return_value={}):
        plan = sync_runtime.prepare_generation(root, {('dev', 'team', 'iam')}, snapshot=inputs)
        plan.close()
        assert not close.called
    assert inputs.contents[template] == b'# required\n'
    present = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}
    assert present == {p for p in files if p not in {'docs/designs/dev/team/other.md', 'model/templates/team/unrelated.properties.tpl', 'tests/results/unrelated.log'}}
    assert root/'tests/results/unrelated.log' not in inputs.contents
    inputs.close()


@pytest.mark.parametrize('baseline,final,index,committed', [
    ('start', {'view.md'}, set(), {'view.md'}),
    ('start', set(), {'view.md'}, {'view.md'}),
    ('start', set(), {'view.md'}, set()),
    (None, {'new.md'}, {'new.md'}, set()),
])
def check_final_git_paths(tmp_path, baseline, final, index, committed):
    from validation.findings import Findings
    from validation.task import TaskValidation
    task = TaskValidation(tmp_path, Findings(tmp_path))
    task.baseline, task.baseline_fixed = baseline, True
    if baseline is None:
        (tmp_path/'new.md').write_bytes(b'exists')
    calls = []
    def git_paths(args):
        calls.append(args)
        if args[0] == 'ls-files':
            return final if '--cached' in args else set()
        if '--cached' in args:
            return index
        if 'HEAD' in args:
            return committed
        return final if baseline in args else set()
    task.git_paths = git_paths
    assert task.final_paths() == final
    assert all('--cached' not in call for call in calls if call[0] == 'diff')
    # Permission scope preserves the independent index change.
    task.permission_paths = index | committed
    task.changed_paths = final
    task.acceptance_checks = [('R1', 'changed', 'view.md')]
    task.check_acceptance_checks({})
    assert bool(task.acceptance_results) == ('view.md' in final)


def check_git_baseline_fail_closed(tmp_path):
    from types import SimpleNamespace
    from validation.findings import Findings
    from validation.task import TaskValidation
    def task():
        return TaskValidation(tmp_path, Findings(tmp_path))
    with patch('worktree_task.task_start_commit', return_value='task-start'), \
         patch('worktree_task.git', side_effect=AssertionError('managed fallback to HEAD')):
        current = task()
        current.fix_baseline()
        assert current.baseline == 'task-start'
    def git(root, *args, **kwargs):
        return SimpleNamespace(returncode=1 if args[0] == 'show-ref' else 128, stdout='', stderr='missing HEAD')
    with patch('worktree_task.task_start_commit', return_value=None), \
         patch('worktree_task.output', return_value='refs/heads/new'), patch('worktree_task.git', side_effect=git):
        current = task()
        current.fix_baseline()
        assert current.baseline_fixed and current.baseline is None
    with patch('worktree_task.task_start_commit', side_effect=ValueError('invalid managed state')), \
         pytest.raises(ValueError, match='invalid managed state'):
        task().fix_baseline()
    with patch('worktree_task.task_start_commit', return_value=None), \
         patch('worktree_task.output', side_effect=ValueError('broken Git')), \
         patch('worktree_task.git', side_effect=git), pytest.raises(ValueError, match='broken Git'):
        task().fix_baseline()
    with patch('validation.task.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='rename old\0追加 file\0deleted\0', stderr='')):
        assert task().git_paths(['diff']) == {'rename old', '追加 file', 'deleted'}
    with patch('validation.task.subprocess.run', return_value=SimpleNamespace(returncode=128, stdout='', stderr='broken')), \
         pytest.raises(ValueError, match='git diff failed'):
        task().git_paths(['diff'])


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
    stack = findings.result('design.stacks', first)
    stack.status, stack.metadata = 'PASS', {'stack_definitions': {'candidate': []}}
    findings.bind_candidate(object(), set())
    stale = findings.result('design.stacks', first)
    assert stale.status == 'NOT_RUN' and stale.metadata == {}


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
