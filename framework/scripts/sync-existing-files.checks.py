#!/usr/bin/env python3
"""Focused check for framework-only repository synchronization."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync-existing-files.py")


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--target", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (target / "framework" / "scripts" / SCRIPT.name).is_file()
        assert not (target / "docs").exists()
        assert not (target / "tasks").exists()
    print("sync-existing-files: PASS")


if __name__ == "__main__":
    main()
