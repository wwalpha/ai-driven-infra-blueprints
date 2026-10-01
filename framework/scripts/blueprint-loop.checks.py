#!/usr/bin/env python3
"""Focused check for complete diagnostics and assertion-safe execution."""

from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("blueprint-loop.py")


def main() -> None:
    for check in SCRIPT.parent.glob("*.checks.py"):
        optimized = subprocess.run(
            [sys.executable, "-O", str(check)], capture_output=True, text=True
        )
        assert optimized.returncode != 0 and "Focused checks require assertions" in optimized.stderr, check
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scripts = root / "framework" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
        (scripts / "validate-blueprint.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
        (scripts / "a.checks.py").write_text("assert False, 'assertions must run'\n", encoding="utf-8")
        (scripts / "b.checks.py").write_text(
            "from pathlib import Path\nPath('continued').write_text('yes', encoding='utf-8')\n",
            encoding="utf-8",
        )
        command = [sys.executable, "-O", str(scripts / SCRIPT.name), "--mode", "local"]
        environment = {**os.environ, "PYTHONOPTIMIZE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode != 0
        assert "AssertionError: assertions must run" in result.stderr
        assert "validate-blueprint.py, a.checks.py" in result.stdout
        assert (root / "continued").read_text(encoding="utf-8") == "yes"

        (scripts / "validate-blueprint.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        (scripts / "a.checks.py").write_text("assert True\n", encoding="utf-8")
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS (2 focused check scripts)" in result.stdout
    print("blueprint-loop: PASS")


if __name__ == "__main__":
    main()
