"""Worker ownership and communication failures, without cfn-lint or AWS."""
import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import pytest
from deployment import lint_worker as worker


def check_scope_ownership():
    backend = SimpleNamespace(lint=object())
    previous = backend.lint
    with patch.object(worker, 'Worker') as factory:
        with worker.scope(backend, [1]):
            assert backend.lint is previous
        with patch.object(worker.sys, "platform", "win32"), worker.scope(backend, [1, 2]):
            assert backend.lint is previous
        factory.assert_not_called()
        with pytest.raises(RuntimeError), worker.scope(backend, [1, 2]):
            assert backend.lint == factory.return_value.run
            raise RuntimeError('injected validation failure')
        factory.return_value.close.assert_called_once()
        assert backend.lint is previous
    backend = SimpleNamespace()
    with worker.scope(backend, [1, 2]):
        assert backend.lint.__self__.process is None  # No process without a lint call.
    assert not hasattr(backend, 'lint')


def check_communication_rejects_and_reaps():
    for response in ('', 'invalid\n', '[]\n', '{"returncode":false,"stdout":"","stderr":""}\n'):
        process = Mock(stdin=io.StringIO(), stdout=io.StringIO(response))
        with patch.object(worker.subprocess, 'Popen', return_value=process):
            lint = worker.Worker()
            with pytest.raises(ValueError, match='communication failed'):
                lint.run(['cfn-lint'])
            lint.close()
        process.wait.assert_called_once_with(timeout=10)
        assert process.stdin.closed and process.stdout.closed
    process = Mock(stdin=Mock(), stdout=Mock())
    process.stdin.close.side_effect = BrokenPipeError()
    process.wait.side_effect = [subprocess.TimeoutExpired('worker', 10), 0]
    lint = worker.Worker()
    lint.process = process
    lint.close()
    process.terminate.assert_called_once()
    assert process.wait.call_count == 2
    process.stdout.close.assert_called_once()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
