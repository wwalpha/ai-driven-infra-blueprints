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
        with progress.phase('reservation', status='reservation-wait'):
            pass
        progress.completed(('dev', 'team', 'iam'))
        with pytest.raises(ValueError), progress.phase('candidate-validation'):
            raise ValueError('injected')
    text = output.getvalue()
    for expected in ['heartbeat', 'items=1/2', 'completed=1/1', 'lock-wait', 'reservation-wait', 'stage-failed', 'remaining=unknown', 'not proof of progress']:
        assert expected in text
    assert reporter.states == []



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
