#!/usr/bin/env python3
"""Run the deterministic local blueprint validation on any supported OS."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("local",), required=True)
    parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    commands = [
        [
            sys.executable,
            str(root / "scripts" / "validate-blueprint.py"),
            "--repository-root",
            str(root),
        ],
        *([sys.executable, str(path)] for path in sorted((root / "scripts").glob("*.checks.py"))),
    ]
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for command in commands:
        result = subprocess.run(command, cwd=root, check=False, env=environment)
        if result.returncode:
            print(f"Blueprint local loop: FAIL ({Path(command[1]).name})")
            return result.returncode
    print(f"Blueprint local loop: PASS ({len(commands) - 1} focused check scripts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
