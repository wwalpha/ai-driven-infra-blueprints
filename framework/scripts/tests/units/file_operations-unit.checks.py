#!/usr/bin/env python3
"""Byte preservation and failure boundaries of shared file publication."""

import os
import stat
import sys
import tempfile
from collections.abc import Callable
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import Mock, patch

import pytest
import sync_files
from support.pytest_cli import run
from utils import file_operations as files
from utils.function_wrapper import BoundCallback as _bind_framework_callback

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize('content', ['日本語\r\nline\n\x00', b'\xff\x00\r\n'])
def check_stage_and_publish(tmp_path: Path, content: str | bytes) -> None:
    destination = tmp_path / 'file'
    destination.write_bytes(b'original')
    with patch.object(files.os, 'fsync', side_effect=AssertionError('unexpected fsync')):
        first = files.stage_file(destination, content, newline='')
        second = files.stage_file(destination, content, newline='')
        assert first != second and first.parent == destination.parent
        expected = content.encode('utf-8') if isinstance(content, str) else content
        assert first.read_bytes() == second.read_bytes() == expected
        assert destination.read_bytes() == b'original'
        files.publish_staged(first, destination)
        files.publish_staged(second, destination)
    assert destination.read_bytes() == expected
    assert list(tmp_path.iterdir()) == [destination]


def _failed_write_stream(
    fdopen: Callable[..., TextIO], descriptor: int, *args: object, **kwargs: object,
) -> TextIO:
    stream = fdopen(descriptor, *args, **kwargs)
    stream.write = Mock(side_effect=OSError('injected write'))
    return stream


@pytest.mark.parametrize('failure', ['open', 'write', 'fsync', 'replace'])
def check_single_failure(tmp_path: Path, failure: str) -> None:
    destination = tmp_path / 'file'
    destination.write_bytes(b'original\xff\r\n')
    if failure == 'write':
        injection = patch.object(files.os, 'fdopen', side_effect=partial(_failed_write_stream, files.os.fdopen))
    else:
        target = {'open': 'fdopen', 'fsync': 'fsync', 'replace': 'replace'}[failure]
        injection = patch.object(files.os, target, side_effect=OSError('injected ' + failure))
    with injection, pytest.raises(OSError, match='injected ' + failure):
        files.atomic_replace_file(destination, 'changed', fsync=True)
    assert destination.read_bytes() == b'original\xff\r\n'
    assert list(tmp_path.iterdir()) == [destination]


def check_single_fsync_and_default_newlines(tmp_path: Path) -> None:
    reference, destination = tmp_path / 'reference', tmp_path / 'file'
    text = '日本語\nline\r\n'
    reference.write_text(text, encoding='utf-8')
    with patch.object(files.os, 'fsync', wraps=files.os.fsync) as fsync:
        files.atomic_replace_file(destination, text, fsync=True)
    assert fsync.call_count == 1
    assert destination.read_bytes() == reference.read_bytes()


def check_stage_collision(tmp_path: Path) -> None:
    occupied = tmp_path / 'tmpoccupied'
    occupied.write_bytes(b'preserve')
    with patch.object(files.uuid, 'uuid4', side_effect=[SimpleNamespace(hex='occupied'), SimpleNamespace(hex='unique')]):
        temporary = files.stage_file(tmp_path / 'file', b'new')
    assert temporary.name == 'tmpunique' and occupied.read_bytes() == b'preserve'
    temporary.unlink()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX creation modes')
@pytest.mark.parametrize('mode', [0o600, 0o666])
def check_single_permissions(tmp_path: Path, mode: int) -> None:
    reference, destination = tmp_path / 'reference', tmp_path / 'file'
    if mode == 0o600:
        with tempfile.NamedTemporaryFile(dir=tmp_path) as stream:
            expected = stat.S_IMODE(os.stat(stream.name).st_mode)
    else:
        reference.write_text('legacy', encoding='utf-8')
        expected = stat.S_IMODE(reference.stat().st_mode)
    for existing in (False, True):
        if existing:
            destination.chmod(0o400)
        files.atomic_replace_file(destination, b'new', mode=mode)
        assert stat.S_IMODE(destination.stat().st_mode) == expected


def check_atomic_bytes(tmp_path):
    old, new, deleted = [tmp_path / name for name in ('old', 'new', 'deleted')]
    old.write_bytes(b'original\r\n')
    deleted.write_bytes(b'delete\x00')
    files.atomic_files({old: '日本語\r\n', new: 'new\x00', deleted: None})
    assert old.read_bytes() == '日本語\r\n'.encode('utf-8')
    assert new.read_bytes() == b'new\x00' and not deleted.exists()
    with patch.object(files.os, 'replace', wraps=files.os.replace):
        files.atomic_files({old: '日本語\r\n'})
    assert sorted(p.name for p in tmp_path.iterdir()) == ['new', 'old']


def _callback_check_atomic_failure_replace(last, real_replace, after_replace, state, /, source, destination):
    if destination == last and not state.fired:
        state.fired = True
        if after_replace:
            real_replace(source, destination)
        raise OSError('injected replace')
    return real_replace(source, destination)


@pytest.mark.parametrize('failure', ['staging', 'replace', 'replace-after'])
def check_atomic_failure(tmp_path, failure):
    old, new, deleted, last = [tmp_path / name for name in ('old', 'new', 'deleted', 'last')]
    originals = {old: b'old\r\n\x00', deleted: b'deleted\xff', last: b'last'}
    for path, content in originals.items():
        path.write_bytes(content)
    real_replace = files.os.replace
    replace = _bind_framework_callback(_callback_check_atomic_failure_replace, last, real_replace, failure == 'replace-after', SimpleNamespace(fired=False))
    target = patch.object(files.os, 'fsync', side_effect=OSError('injected staging')) if failure == 'staging' else patch.object(files.os, 'replace', side_effect=replace)
    with target, pytest.raises(OSError, match='injected'):
        files.atomic_files({old: 'updated', new: 'created', deleted: None, last: 'changed'})
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert not new.exists()
    assert set(tmp_path.iterdir()) == set(originals)


def _publish_after_staging(
    real_replace: Callable[[Path, Path], None], contents: dict[Path, str], state: SimpleNamespace, /,
    temporary: Path, destination: Path,
) -> None:
    state.calls += 1
    if state.calls == 1:
        assert all(path.read_bytes() == b'old' for path in contents)
        assert len(list(destination.parent.glob('tmp*'))) == len(contents)
    elif state.calls == 2:
        raise OSError('second replace')
    real_replace(temporary, destination)


def check_batch_stages_before_publish(tmp_path: Path) -> None:
    contents = {tmp_path / 'first': 'new', tmp_path / 'second': 'new'}
    for path in contents:
        path.write_bytes(b'old')
    replace = partial(_publish_after_staging, files.os.replace, contents, SimpleNamespace(calls=0))
    with patch.object(files, 'stage_file', wraps=files.stage_file) as stage, \
            patch.object(files.os, 'replace', side_effect=replace), \
            patch.object(files.os, 'fsync', wraps=files.os.fsync) as fsync:
        with pytest.raises(OSError, match='second replace'):
            files.atomic_files(contents)
    assert stage.call_count == 3 and fsync.call_count == 2
    assert all(path.read_bytes() == b'old' for path in contents)
    assert set(tmp_path.iterdir()) == set(contents)


def _callback_check_save_rollback_patch_fail(new, write, /, path, *args, **kwargs):
    if path == new:
        path.write_bytes(b'partial')
        raise OSError('injected write')
    return write(path, *args, **kwargs)


def check_save_rollback_patch(tmp_path):
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.write_bytes(b'old\r\n\x00')
    write = Path.write_text
    fail = _bind_framework_callback(_callback_check_save_rollback_patch_fail, new, write)
    with patch.object(Path, 'write_text', side_effect=AssertionError('unchanged write')):
        sync_files.save_files({old: 'old\r\n\x00'})
    with patch.object(Path, 'write_text', fail), patch.object(sync_files, 'restore_files', wraps=files.restore_files) as restore, pytest.raises(OSError, match='injected write'):
        sync_files.save_files({old: 'changed', new: 'new'})
    assert list(restore.call_args.args[0]) == [new, old]
    assert old.read_bytes() == b'old\r\n\x00' and not new.exists()
    with patch.object(Path, 'write_text', fail), patch.object(sync_files, 'restore_files', side_effect=OSError('injected rollback')), pytest.raises(OSError, match='generated-file rollback failed: injected rollback'):
        sync_files.save_files({new: 'new'})


if __name__ == '__main__':
    raise SystemExit(run(__file__))
