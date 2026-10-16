#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.regression_guard_fixtures import *

def main():
    with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
        root = Path(temporary).resolve()
        password = "fixture-only-long-password"
        lock = root / ".lock"
        with patch.object(guard, "__file__", str(root / "framework/scripts/regression_guard.py")), \
             patch.object(guard, "password_input", side_effect=[password, "different-confirmation"]):
            rejected(guard.install)
            assert not lock.exists()
        with patch.object(guard, "__file__", str(root / "framework/scripts/regression_guard.py")), \
             patch.object(guard, "password_input", return_value=password) as entry:
            guard.install()
            assert [path.name for path in root.iterdir()] == [".lock"], "service_source created extra files/directories"
            saved = lock.read_text(encoding="utf-8")
            assert password not in saved
            entry.reset_mock()
            rejected(guard.install)
            entry.assert_not_called()
            assert lock.read_text(encoding="utf-8") == saved, "service_source overwrote existing .lock"
        record = json.loads(saved)
        assert record["version"] == 1 and len(bytes.fromhex(record["salt"])) == 16
        assert bytes.fromhex(record["hash"]) == guard.password_hash(password, bytes.fromhex(record["salt"]))
        with patch.object(guard, "password_input", return_value=password) as entry:
            guard.verify(root)
            entry.return_value = "incorrect-password"
            rejected(lambda: guard.verify(root))
            entry.side_effect = EOFError()
            rejected(lambda: guard.verify(root), EOFError)
            entry.side_effect = KeyboardInterrupt()
            rejected(lambda: guard.verify(root), KeyboardInterrupt)
            entry.side_effect = None
            entry.reset_mock()
            for malformed in ('{}', 'not JSON', '{"version":1,"salt":"00","hash":"00"}',
                              '{"version":1,"salt":null,"hash":"00"}'):
                lock.write_text(malformed, encoding="utf-8")
                rejected(lambda: guard.verify(root))
                entry.assert_not_called()
            lock.unlink()
            rejected(lambda: guard.verify(root))
            entry.assert_not_called()
            lock.write_text(saved, encoding="utf-8")
            with patch.object(guard, "os", SimpleNamespace(name="nt")):
                entry.return_value = password
                guard.authorize_full_regression(root)
                entry.return_value = "incorrect-password"
                rejected(lambda: guard.authorize_full_regression(root))
            # Every invocation prompts again; no reusable authorization flag/state.
            assert entry.call_count == 2
    print("regression_guard: PASS (single repo .lock, preserved service_source, password matching and failure checks)")


if __name__ == "__main__":
    main()

