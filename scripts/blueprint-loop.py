#!/usr/bin/env python3
"""Run the deterministic local blueprint validation on any supported OS."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("local",), required=True)
    parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "validate-blueprint.py"),
            "--repository-root",
            str(root),
        ],
        cwd=root,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
