"""Private local evidence boundaries."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from support.pytest_cli import run
from utils import local_evidence as evidence

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_private_store_and_file(tmp_path):
    with patch.object(evidence.tempfile, "gettempdir", return_value=str(tmp_path)):
        store = evidence.shared_store(tmp_path)
        file = store / "receipt.json"
        evidence.write_sealed(tmp_path, file, {"task": "example"})
        assert evidence.read_sealed(tmp_path, file) == {"task": "example"}
        if os.name != "nt":
            assert not file.stat().st_mode & 0o077
            file.chmod(0o644)
            with pytest.raises(ValueError, match="unsafe"):
                evidence.read_sealed(tmp_path, file)
            file.chmod(0o600)
            store.chmod(0o755)
            with pytest.raises(ValueError, match="unsafe"):
                evidence.shared_store(tmp_path)


def check_symlinks_and_atomic_failure(tmp_path):
    with patch.object(evidence.tempfile, "gettempdir", return_value=str(tmp_path)):
        store = evidence.shared_store(tmp_path)
        file = store / "receipt.json"
        target = tmp_path / "target"
        target.write_text("unchanged", encoding="utf-8")
        file.symlink_to(target)
        with pytest.raises(ValueError, match="unsafe"):
            evidence.write_sealed(tmp_path, file, {})
        with pytest.raises(ValueError, match="unsafe"):
            evidence.read_sealed(tmp_path, file)
        file.unlink()
        evidence.write_sealed(tmp_path, file, {"old": True})
        with patch("utils.file_operations.os.replace", side_effect=OSError("failed")):
            with pytest.raises(OSError, match="failed"):
                evidence.write_sealed(tmp_path, file, {"new": True})
        assert evidence.read_sealed(tmp_path, file) == {"old": True}
        assert target.read_text(encoding="utf-8") == "unchanged"
        file.unlink()
        store.rmdir()
        store.symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(ValueError, match="unsafe"):
            evidence.shared_store(tmp_path)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
