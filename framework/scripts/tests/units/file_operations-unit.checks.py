#!/usr/bin/env python3
"""Byte preservation and failure boundaries of shared file publication."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.function_wrapper import BoundCallback as _bind_framework_callback
from unittest.mock import patch

import pytest
import sync_files
from support.pytest_cli import run
from utils import file_operations as files

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


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


def _callback_check_atomic_failure_replace(last, real_replace, /, source, destination):
    if destination == last:
        raise OSError('injected replace')
    return real_replace(source, destination)


@pytest.mark.parametrize('failure', ['write', 'replace'])
def check_atomic_failure(tmp_path, failure):
    old, new, deleted, last = [tmp_path / name for name in ('old', 'new', 'deleted', 'last')]
    originals = {old: b'old\r\n\x00', deleted: b'deleted\xff', last: b'last'}
    for path, content in originals.items():
        path.write_bytes(content)
    real_replace = files.os.replace
    replace = _bind_framework_callback(_callback_check_atomic_failure_replace, last, real_replace)
    target = patch.object(files.os, 'fsync', side_effect=OSError('injected write')) if failure == 'write' else patch.object(files.os, 'replace', side_effect=replace)
    with target, pytest.raises(OSError, match='injected'):
        files.atomic_files({old: 'updated', new: 'created', deleted: None, last: 'changed'})
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert not new.exists()
    assert set(tmp_path.iterdir()) == set(originals)


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
