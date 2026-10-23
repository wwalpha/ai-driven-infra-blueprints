#!/usr/bin/env python3
"""Task selection, ordinary transitions and atomic contract publication."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest
import task_contract as tasks
from issues.publication import save
from support.pytest_cli import run
from utils.file_operations import atomic_files
from validation_scope import active_scope

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

def contract(name, files, state="running", kind="governance", scope="framework"):
    paths = [name, *files]
    listed = "\n".join(f"- `{path}`" for path in paths)
    return f"""# Task
## Task contract
- Task type: `{kind}`
- Task status: `{state}`
- Target: test
- Goal: test
## Validation scope
- `{scope}`
## Required changes
- [R1] Test
## Acceptance checks
- [R1] `changed:{files[0]}`
## Modified files
{listed}
## Allowed paths
{listed}
"""


def blocked(callback, message):
    with pytest.raises(ValueError) as error:
        callback()
    assert message in str(error.value), str(error.value)


def check_completed_legacy_and_paths(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
        old = "tasks/old.md"
        new = "tasks/new.md"
        tasks.start(root, old, contract(old, ["README.md", "old.md"]))
        (root / old).write_text(contract(old, ["README.md", "old.md"], state="completed"))
        tasks.start(root, new, contract(new, ["README.md"]))
        assert tasks.task_path(root) == root / new
        _ = {old, new, "README.md", "old.md", "tasks/removed.md"}
        for name in (old, new):
            (root / name).unlink()
        assert tasks.task_path(root, required=False) is None
        assert tasks.task_revision(root) == (None, None)
        blocked(lambda: tasks.task_path(root), "selected task contract required")
        blocked(lambda: tasks.status("## Task contract\n"), "Task status")
        for value in ("../escape", "/tmp/escape", "./file", "a//file", "a/../file", "*.md", "a/**", ".git/config", "."):
            blocked(lambda value=value: tasks.start(root, new, contract(new, [value])), "exact repository-relative path")
        (root / "linked").symlink_to(root / "elsewhere")
        blocked(lambda: tasks.start(root, new, contract(new, ["linked/file.md"])), "symlinks")
        blocked(lambda: tasks.start(root, new, contract(new, [old])), "another contract")
        blocked(lambda: tasks.start(root, new, contract(new, ["file.md", "file.md"])), "duplicate paths")
        blocked(lambda: tasks.start(root, new, contract(new, ["file.md"], state="paused")), "Task status")


def check_suspend_and_resume(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
        first, second = "tasks/first.md", "tasks/second.md"
        tasks.start(root, first, contract(first, ["shared.md", "own.md"]))
        blocked(lambda: tasks.suspend(root, first, " "), "concrete reason")
        assert tasks.suspend(root, first, "other task: schema failure in model/dev/cde/ec2.properties")
        saved = (root / first).read_bytes()
        assert tasks.status(saved.decode()) == "suspend"
        assert "schema failure in model/dev/cde/ec2.properties" in saved.decode()
        assert tasks.task_path(root, required=False) is None
        assert active_scope(root) == set()
        with patch.dict(os.environ, {tasks.SELECTOR: first}):
            blocked(lambda: tasks.task_path(root), "suspend task cannot execute")
        assert tasks.contract_path(root, first) == root / first
        assert active_scope(root, contract_file=first) == set()
        blocked(lambda: active_scope(root, task_file=first), "suspend task cannot execute")
        blocked(lambda: tasks.task_revision(root, first), "suspend task cannot execute")
        blocked(lambda: tasks.contract_path(root, '../first.md'), "invalid task selector")
        blocked(lambda: tasks.contract_path(root, 'tasks/missing.md'), "missing")
        saved = (root / first).read_bytes()
        (root / 'shared.md').symlink_to(root / 'elsewhere')
        blocked(lambda: tasks.contract_path(root, first), "symlinks")
        (root / 'shared.md').unlink()
        (root / first).write_text(saved.decode().replace('## Modified files', '## Missing files'))
        blocked(lambda: tasks.contract_path(root, first), "missing or duplicate paths")
        (root / first).write_bytes(saved)
        tasks.start(root, second, contract(second, ["shared.md"]))
        assert tasks.task_path(root) == root / second
        tasks.resume(root, first)
        assert "## Suspension reason" not in (root / first).read_text()
        with patch.dict(os.environ, {tasks.SELECTOR: first}):
            tasks.task_path(root)
        tasks.suspend(root, first, "own check failed")
        saved = (root / first).read_bytes()
        other = (root / second).read_bytes()
        assert not tasks.suspend(root, first, "overwrite")
        assert (root / first).read_bytes() == saved and (root / second).read_bytes() == other
        tasks.suspend(root, second, "own acceptance check failed: changed:shared.md")
        tasks.resume(root, first)
        assert tasks.status((root / first).read_text()) == "running"
        assert "## Suspension reason" not in (root / first).read_text()
        tasks.resume(root, second)
        # Invalid other contracts cannot prevent suspension of the explicitly selected task.
        (root / second).write_text("invalid contract")
        assert tasks.suspend(root, first, "invalid contract: tasks/second.md")
        blocked(lambda: tasks.status(contract(first, ["shared.md"], state="suspend")), "Suspension reason")
        # A reason is diagnostic text, even if an error contains Markdown headings.
        (root / second).unlink()
        tasks.resume(root, first)
        tasks.suspend(root, first, "error\n## Modified files\n- `unexpected.md`")
        assert tasks.paths_in((root / first).read_text(), "## Modified files") == {first, "shared.md", "own.md"}


def _callback_check_atomic_contract_reads_pause(paused, release, /):
    paused.set()
    assert release.wait(10), "reader did not release publication"


def _callback_check_atomic_contract_reads_replacing(destination, original_replace, pause, /, source, target):
    if Path(target) == destination:
        pause()  # Atomic publication must still expose only the previous contract.
    return original_replace(source, target)


def _callback_check_atomic_contract_reads_opening(destination, original_open, pause, /, path, mode='r', *args, **kwargs):
    stream = original_open(path, mode, *args, **kwargs)
    if path == destination and mode in {"w", "x"}:
        pause()  # The old implementation has already truncated/created the file.
    return stream


@pytest.mark.parametrize("transition", ["start", "complete", "suspend", "resume"])
def check_atomic_contract_reads(tmp_path, transition):
    root = tmp_path
    name = "tasks/writer.md"
    owner = "tasks/owner.md"
    with patch.dict(os.environ, {}, clear=True):
        if transition != "start":
            tasks.start(root, owner, contract(owner, ["shared.md"]))
            tasks.start(root, name, contract(name, ["shared.md"]))
            tasks.complete(root, owner)
        if transition == "complete":
            tasks.refresh(root, name)
        if transition == "resume":
            tasks.suspend(root, name, "fixture stop")
        before = tasks.contracts(root)
        destination = root / name
        paused, release = Event(), Event()
        original_open, original_replace = Path.open, os.replace
        pause = _bind_framework_callback(_callback_check_atomic_contract_reads_pause, paused, release)
        opening = _bind_framework_callback(_callback_check_atomic_contract_reads_opening, destination, original_open, pause)
        replacing = _bind_framework_callback(_callback_check_atomic_contract_reads_replacing, destination, original_replace, pause)
        operations = {
            "start": lambda: tasks.start(root, name, contract(name, ["shared.md"])),
            "refresh": lambda: tasks.refresh(root, name),
            "complete": lambda: tasks.complete(root, name),
            "suspend": lambda: tasks.suspend(root, name, "fixture stop"),
            "resume": lambda: tasks.resume(root, name),
        }
        with patch.object(Path, "open", opening), patch.object(os, "replace", replacing), ThreadPoolExecutor(max_workers=1) as executor:
            writer = executor.submit(operations[transition])
            try:
                assert paused.wait(10), "publication was not intercepted"
                during = tasks.contracts(root)
                for text in during.values():
                    tasks.status(text)
                assert during == before, "lock-free reader observed partial contract"
            finally:
                release.set()
                writer.result(timeout=10)


def check_admission_selection(tmp_path, monkeypatch):
    monkeypatch.delenv(tasks.SELECTOR, raising=False)
    first, second = 'tasks/first.md', 'tasks/second.md'
    tasks.start(tmp_path, first, contract(first, ['new/file.md']))
    assert tasks.task_path(tmp_path) == tmp_path / first
    assert active_scope(tmp_path) == set()
    before = (tmp_path / first).read_bytes()
    tasks.start(tmp_path, second, contract(second, ['new/file.md', 'other.md'], kind='design', scope='dev/cde/ec2'))
    assert (tmp_path / first).read_bytes() == before
    blocked(lambda: tasks.task_path(tmp_path), 'multiple running tasks')
    monkeypatch.setenv(tasks.SELECTOR, second)
    assert active_scope(tmp_path) == {('dev', 'cde', 'ec2')}
    blocked(lambda: tasks.task_path(tmp_path, 'tasks/missing.md'), 'missing')
    blocked(lambda: tasks.task_path(tmp_path, '../first.md'), 'invalid task selector')
    before = (tmp_path / second).read_bytes()
    tasks.refresh(tmp_path, second)
    assert (tmp_path / second).read_bytes() == before
    tasks.complete(tmp_path, first)
    tasks.complete(tmp_path, second)


def check_shared_issue_files(tmp_path, monkeypatch):
    first, second = 'tasks/first.md', 'tasks/second.md'
    report = 'issues/dev/cde/issues.md'
    tasks.start(tmp_path, first, contract(first, [report], kind='migration', scope='dev/cde/ec2'))
    tasks.start(tmp_path, second, contract(second, [report], kind='migration', scope='dev/cde/s3'))
    monkeypatch.setenv(tasks.SELECTOR, first)
    save(tmp_path, 'dev', 'cde', ['ec2'], additions=[{'service': 'ec2', 'message': 'retained issue'}])
    monkeypatch.setenv(tasks.SELECTOR, second)
    save(tmp_path, 'dev', 'cde', ['s3'], additions=[{'service': 's3', 'message': 'second issue'}])
    assert all(value in (tmp_path / report).read_text() for value in ('retained issue', 'second issue'))
    blocked(lambda: tasks.safe_path(tmp_path, 'issues/../escape.md'), 'exact repository-relative path')


def _callback_check_atomic_output_rollback_fail_second(replace, tmp_path, /, source, destination):
    if Path(destination) == tmp_path / 'two.txt':
        raise OSError('injected publication failure')
    return replace(source, destination)


def check_atomic_output_rollback(tmp_path):
    files = {tmp_path / 'one.txt': 'first', tmp_path / 'two.txt': 'second'}
    for path, value in files.items():
        path.write_text(value)
    replace = os.replace
    fail_second = _bind_framework_callback(_callback_check_atomic_output_rollback_fail_second, replace, tmp_path)
    with patch('os.replace', side_effect=fail_second), pytest.raises(OSError):
        atomic_files({path: 'new' for path in files}, staging_directory=tmp_path)
    assert all(path.read_text() == value for path, value in files.items())


if __name__ == '__main__':
    raise SystemExit(run(__file__))
