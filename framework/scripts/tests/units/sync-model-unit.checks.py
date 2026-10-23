#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import io
import threading
from contextlib import redirect_stderr
from unittest.mock import patch

import pytest
import sync_progress as progress
import sync_runtime
import sync_views
import validation.design_links as _imports_validation_design_links
import validation_cache as _imports_validation_cache
from design_catalog import property_paths_with_parents
from script_loader import module
from support.validator import load
from support.worktree_task_fixtures import contract
from sync_files import changed_files, markdown_newlines
from utils.input_cache import (
    input_bytes,
    input_context,
    input_scope,
    memo_table,
    recording_inputs,
)
from validation.findings import CheckResult, Findings
from validation.task import TaskValidation

from model import projection

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

_CALLBACK_DEFAULT = object()



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





def _callback_check_internal_sync_concurrent_output_execute(barrier, reports, /, root, write, **kwargs):
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


def check_internal_sync_concurrent_output(tmp_path, capsys):

    runner = module('sync-model.py', 'blueprint_sync_model')
    barrier = threading.Barrier(2, timeout=10)
    reports = []
    execute = (input_scope)(_bind_framework_callback(_callback_check_internal_sync_concurrent_output_execute, barrier, reports))
    roots = [tmp_path/'first', tmp_path/'second']
    with patch.object(runner, 'sync', side_effect=execute), ThreadPoolExecutor(2) as executor:
        futures = [executor.submit(runner.run, ['--all'], repository_root=root) for root in roots]
        results = [future.result() for future in futures]
    for root, other, (code, text) in zip(roots, reversed(roots), results, strict=False):
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
    runner = module('sync-model.py', 'blueprint_sync_model')
    (tmp_path/'tasks').mkdir()
    (tmp_path/'tasks/example.md').write_text('## Task contract\n- Task type: `governance`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n## Validation scope\n- `all`\n')
    result, text = runner.run(arguments, repository_root=tmp_path)
    assert result == code and diagnostic in text, text
    assert progress._current.get() is None and progress._output.get() is None
    assert capsys.readouterr() == ('', '')


def _callback_check_progress_heartbeat_and_waits_ReleasedLock_release(self, lock, /):
    lock.release()


class ReleasedLock:
    def __init__(self, lock, acquire):
        self.lock = lock
        self.original_acquire = acquire

    def acquire(self, blocking=True):
        if not blocking:
            return False
        self.lock.release()
        return self.original_acquire()

    def release(self):
        self.lock.release()



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
        with progress.thread_lock(ReleasedLock(lock, original_acquire)):
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
    input_bytes = _imports_validation_cache.input_bytes
    input_is_file = _imports_validation_cache.input_is_file
    input_select = _imports_validation_cache.input_select
    recording_inputs = _imports_validation_cache.recording_inputs
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


def _callback_check_stage_dependency_selection_loaded(authority, inputs, values, /, path, read_context=None):
    assert read_context is None or read_context is inputs
    return SimpleNamespace(values=values, files={authority: input_bytes(authority).decode()},
                           dependencies={authority: input_bytes(authority)})


def check_stage_dependency_selection(tmp_path):

    root, stage = tmp_path/'root', tmp_path/'stage'
    _ = root/'docs/designs/dev/team/iam.md'
    files = {'docs/designs/dev/team/iam.md': '# selected\n',
             'docs/designs/dev/team/iam/policy.json': '{}\n',
             'docs/designs/dev/team/other.md': '# unrelated\n',
             'docs/designs/dev/team/out.md': '# reference\n',
             'docs/designs/dev/team/in.md': '[incoming](iam.md#id)\n',
             'model/dev/team/iam.properties': '# model-format: 2\n# required\n',
             'model/dev/team/unrelated.properties': '# model-format: 2\n# unused\n',
             'project.json': '{}\n', 'tests/results/unrelated.log': 'unrelated\n'}
    for relative, text in files.items():
        file = root/relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    model = root/'model/dev/team/iam.properties'
    authority = root/'model/dev/team/iam.properties'
    inputs = sync_runtime.GenerationInputs(root)
    # Caller-owned snapshots are reused, including readers, without inner cleanup.
    values = {'link': '[out](out.md#id)'}
    loaded = _bind_framework_callback(_callback_check_stage_dependency_selection_loaded, authority, inputs, values)
    inputs.stage = stage
    with patch.object(sync_runtime.GenerationInputs, '__init__', side_effect=AssertionError('duplicate recorder')), \
         patch.object(inputs, 'close', wraps=inputs.close) as close, \
         patch('validation_cache.PassCache.common_inputs', side_effect=AssertionError('duplicate common registration')), \
         patch.object(sync_runtime, 'registered_models', return_value=[model]), \
         patch.object(sync_runtime, 'model_exists', side_effect=lambda path, read_context: path == authority and read_context is inputs), \
         patch.object(sync_runtime, 'load_model', side_effect=loaded), \
         patch.object(sync_runtime, 'generate_views', return_value={}), \
         patch.object(sync_views, 'broken_design_links', return_value={}):
        plan = sync_runtime.prepare_generation(root, {('dev', 'team', 'iam')}, snapshot=inputs)
        plan.close()
        assert not close.called
    assert inputs.contents[authority] == b'# model-format: 2\n# required\n'
    present = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}
    assert present == {p for p in files if p not in {'docs/designs/dev/team/other.md', 'model/dev/team/unrelated.properties', 'tests/results/unrelated.log'}}
    assert root/'tests/results/unrelated.log' not in inputs.contents
    inputs.close()


@pytest.mark.parametrize('write', [False, True])
def check_linked_attachments(tmp_path, write):

    check_design_links = _imports_validation_design_links.check_design_links
    root, stage = tmp_path/'root', tmp_path/'stage'
    design = root/'docs/designs/dev/team/service.md'
    reference = design.with_name('reference.md')
    payloads = {
        design.parent/'service/code.zip': b'PK\x03\x04\x00\xff\x80',
        design.parent/'service/nested/requirements.txt': b'package==1\r\n',
        design.parent/'shared/opaque': b'\x00\xfe',
        design.parent/'reference/attachment.bin': b'\x81\x00',
        design.parent/'service/extra.json': b'{}\n',
    }
    for path, data in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    saved = '[zip](service/code.zip) [txt](service/nested/requirements.txt)\n'
    design.write_text(saved, encoding='utf-8')
    reference.write_text('[attachment](reference/attachment.bin)\n', encoding='utf-8')
    values = {'note': saved + '[opaque](shared/opaque) [reference](reference.md) '
              '[missing](service/missing.txt) [web](https://example.com/file.zip)'}
    unrelated = design.parent/'service/unreferenced.bin'
    unrelated.write_bytes(b'unused')
    snapshot = sync_runtime.GenerationInputs(root) if write else None
    if snapshot:
        snapshot.stage = stage
    try:
        with recording_inputs(snapshot) if write else nullcontext():
            with patch.object(sync_runtime, 'registered_models', return_value=[]), \
                 patch.object(sync_views, 'broken_design_links', return_value={}):
                sync_runtime.stage_inputs(stage, root, {design: values}, [], [design], ['service'], write, snapshot)
            for path, data in payloads.items():
                assert (stage/path.relative_to(root)).read_bytes() == data
            assert not (stage/unrelated.relative_to(root)).exists()
            staged = stage/design.relative_to(root)
            staged.write_text(values['note'], encoding='utf-8')
            findings = Findings(stage)
            check_design_links({}, [staged], design_sources={staged: {}}, findings=findings,
                               root=stage, scope=None)
            assert len(findings.errors) == 1 and 'broken design link' in findings.errors[0], findings.errors
            assert 'service/missing.txt' in findings.errors[0]
            generated = staged.with_suffix('')/'generated.json'
            generated.write_bytes(b'{}')
            sync_runtime.restore_view(stage, root, design)
            assert staged.read_bytes() == design.read_bytes()
            assert not generated.exists()
            for path, data in payloads.items():
                assert (stage/path.relative_to(root)).read_bytes() == data
            findings = Findings(stage)
            check_design_links({}, [staged], design_sources={staged: {}}, findings=findings,
                               root=stage, scope=None)
            assert not findings.errors, findings.errors
            if snapshot:
                snapshot.seal()
                snapshot.verify()
                attachment = design.parent/'service/code.zip'
                attachment.write_bytes(b'changed')
                with pytest.raises(ValueError, match='inputs changed before publication'):
                    snapshot.verify()
    finally:
        if snapshot:
            snapshot.close()


def _callback_check_final_git_paths_git_paths(baseline, calls, committed, final, index, /, args):
    calls.append(args)
    if args[0] == 'ls-files':
        return final if '--cached' in args else set()
    if '--cached' in args:
        return index
    if 'HEAD' in args:
        return committed
    return final if baseline in args else set()


@pytest.mark.parametrize('baseline,final,index,committed', [
    ('start', {'view.md'}, set(), {'view.md'}),
    ('start', set(), {'view.md'}, {'view.md'}),
    ('start', set(), {'view.md'}, set()),
    (None, {'new.md'}, {'new.md'}, set()),
])
def check_final_git_paths(tmp_path, baseline, final, index, committed):
    task = TaskValidation(tmp_path, Findings(tmp_path))
    task.baseline, task.baseline_fixed = baseline, True
    if baseline is None:
        (tmp_path/'new.md').write_bytes(b'exists')
    calls = []
    git_paths = _bind_framework_callback(_callback_check_final_git_paths_git_paths, baseline, calls, committed, final, index)
    task.git_paths = git_paths
    assert task.final_paths() == final
    assert all('--cached' not in call for call in calls if call[0] == 'diff')
    # Permission scope preserves the independent index change.
    task.permission_paths = index | committed
    task.changed_paths = final
    task.acceptance_checks = [('R1', 'changed', 'view.md')]
    task.check_acceptance_checks({})
    assert bool(task.acceptance_results) == ('view.md' in final)


def _callback_check_git_baseline_fail_closed_task(tmp_path, /):
    return TaskValidation(tmp_path, Findings(tmp_path))


def _callback_check_git_baseline_fail_closed_git(root, *args, **kwargs):
    return SimpleNamespace(returncode=1 if args[0] == 'show-ref' else 128, stdout='', stderr='missing HEAD')


def check_git_baseline_fail_closed(tmp_path):

    (tmp_path / 'tasks').mkdir()
    (tmp_path / 'tasks/example.md').write_text(contract('example', ['file.txt']))
    task = _bind_framework_callback(_callback_check_git_baseline_fail_closed_task, tmp_path)
    with patch('worktree_state.task_start_commit', return_value='task-start'), \
         patch('worktree_state.git', side_effect=AssertionError('managed fallback to HEAD')):
        current = task()
        current.fix_baseline()
        assert current.baseline == 'task-start'
    git = _callback_check_git_baseline_fail_closed_git
    with patch('worktree_state.task_start_commit', return_value=None), \
         patch('worktree_state.output', return_value='refs/heads/new'), patch('worktree_state.git', side_effect=git):
        current = task()
        current.fix_baseline()
        assert current.baseline_fixed and current.baseline is None
    with patch('worktree_state.task_start_commit', side_effect=ValueError('invalid managed state')), \
         pytest.raises(ValueError, match='invalid managed state'):
        task().fix_baseline()
    with patch('worktree_state.task_start_commit', return_value=None), \
         patch('worktree_state.output', side_effect=ValueError('broken Git')), \
         patch('worktree_state.git', side_effect=git), pytest.raises(ValueError, match='broken Git'):
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


def _callback_check_result_reuse_is_scoped_fail(calls, findings, /):
    calls.append('fail')
    findings.check(False, 'content failed')


def check_result_reuse_is_scoped(tmp_path):
    findings = Findings(tmp_path)
    task = TaskValidation(tmp_path, findings)
    first, second = {('dev', 'team', 'iam')}, {('stg', 'team', 'iam')}
    calls = []
    fail = _bind_framework_callback(_callback_check_result_reuse_is_scoped_fail, calls, findings)
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


def _callback_check_resource_row_reuse_and_edits_rows_444(_default_mapping, _default_identity, /, mapping=_CALLBACK_DEFAULT, identity=_CALLBACK_DEFAULT):
    if mapping is _CALLBACK_DEFAULT:
        mapping = _default_mapping
    if identity is _CALLBACK_DEFAULT:
        identity = _default_identity
    return projection.resource_rows(mapping, identity, 'IAM.Role', Path('/synthetic'))


def check_resource_row_reuse_and_edits():

    values = {f'desired.row.role-001.{key}': value for key, value in
              dict(property='IAM.Role.Description', value='first', comment='fixture').items()}
    rows = _bind_framework_callback(_callback_check_resource_row_reuse_and_edits_rows_444, values, 'role')
    with input_context(), patch.object(projection, 'catalog_outputs', return_value=set()), \
            patch.object(projection, 'entries', wraps=projection.entries) as parse:
        with projection.resource_row_scope():
            assert parse.call_count == 0  # Lazy, even for an empty generation.
            first = rows()
            first[0][2] = 'caller edit'
            first.clear()
            assert rows()[0][2] == 'first' and parse.call_count == 1
            other = dict(values)
            assert rows(other) == rows() and parse.call_count == 2
            values['desired.row.role-001.value'] = 'edited'
            assert rows()[0][2] == 'edited' and parse.call_count == 3
            for key, value in dict(property='IAM.Role.Path', value='/fixture/', comment='added').items():
                values[f'desired.row.role-002.{key}'] = value
            assert len(rows()) == 2 and parse.call_count == 4
            del values['desired.row.role-002.comment']
            with pytest.raises(ValueError, match='invalid resource row: role-002'):
                rows()
            for key in list(values):
                if key.startswith('desired.row.role-002.'):
                    del values[key]
            assert len(rows()) == 1 and parse.call_count == 6
            values['observed.row.role-001.value'] = 'invalid observation'
            with pytest.raises(ValueError, match='observed value requires'):
                rows()
            del values['observed.row.role-001.value']
            assert rows()[0][2] == 'edited'
            # Reordering an otherwise identical mapping must also invalidate it.
            key = next(iter(values))
            values[key] = values.pop(key)
            before = parse.call_count
            rows()
            assert parse.call_count == before + 1
            values.clear()
            assert rows() == []
            before = parse.call_count
            assert rows() == [] and parse.call_count == before
        assert projection._resource_row_cache.get() is None
        with projection.resource_row_scope():
            rows()
            assert parse.call_count == before + 1


def check_resource_row_legacy_and_invalid_entries():
    values = {}
    for identity in ('legacy-001', 'legacy-child-001', 'legacyish-001'):
        values.update({f'desired.row.{identity}.{key}': value for key, value in
                       dict(property='IAM.Role.Description', value=identity, comment='fixture').items()})
    with patch.object(projection, 'catalog_outputs', return_value=set()), projection.resource_row_scope():
        rows = projection.resource_rows(values, 'legacy', 'IAM.Role', Path('/synthetic'))
        assert [row[0] for row in rows] == ['legacy-001', 'legacy-child-001']
        # An unrelated malformed row is validated only when its resource is requested.
        values['desired.row.unrelated-001.extra'] = 'invalid'
        assert projection.resource_rows(values, 'legacy', 'IAM.Role', Path('/synthetic')) == rows
        with pytest.raises(ValueError, match='invalid resource row: unrelated-001'):
            projection.resource_rows(values, 'unrelated', 'IAM.Role', Path('/synthetic'))
        values['desired.row.missing-field'] = 'invalid entry'
        with pytest.raises(ValueError, match='invalid model entry: desired.row.missing-field'):
            projection.resource_rows(values, 'legacy', 'IAM.Role', Path('/synthetic'))
        del values['desired.row.missing-field']
        assert projection.resource_rows(values, 'legacy', 'IAM.Role', Path('/synthetic')) == rows


def _callback_check_resource_row_scope_restoration_fail(outer, /, _):
    assert projection._resource_row_cache.get() is not outer
    raise RuntimeError('generation failed')


def check_resource_row_scope_restoration():
    assert projection._resource_row_cache.get() is None
    with projection.resource_row_scope():
        outer = projection._resource_row_cache.get()
        with pytest.raises(RuntimeError, match='generation failed'):
            with projection.resource_row_scope():
                assert projection._resource_row_cache.get() is not outer
                raise RuntimeError('generation failed')
        assert projection._resource_row_cache.get() is outer
        fail = _bind_framework_callback(_callback_check_resource_row_scope_restoration_fail, outer)
        with patch.object(sync_runtime, 'total', side_effect=fail), pytest.raises(RuntimeError):
            sync_runtime.generate_views(Path('/stage'), Path('/root'), {}, [], definitions_root=Path('/definitions'))
        assert projection._resource_row_cache.get() is outer
        with patch.object(sync_runtime, 'total'):
            assert sync_runtime.generate_views(Path('/stage'), Path('/root'), {}, [], definitions_root=Path('/definitions')) == {}
        assert projection._resource_row_cache.get() is outer
    assert projection._resource_row_cache.get() is None


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
