"""Run the repository's Python quality checks in the current Python environment."""

import os
import re
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REQUIREMENTS = "framework/scripts/requirements.txt"


def main():
    pins = re.findall(r"(?m)^ruff==([^\s]+)$", Path(REQUIREMENTS).read_text(encoding="utf-8"))
    try:
        installed = version("ruff")
    except PackageNotFoundError:
        installed = "missing"
    if pins != [installed] or installed == "missing":
        print(f"{REQUIREMENTS}: expected one pinned Ruff version {pins}, installed: {installed}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="blueprint-ruff-config-") as config:
        env = dict(os.environ, XDG_CONFIG_HOME=config, RUFF_NO_CACHE="true")
        results = [
            subprocess.run([sys.executable, *args], env=env, check=False)
            for args in (
                ("-m", "ruff", "check", "framework/scripts"),
                ("-B", "framework/scripts/python_structure.py"),
            )
        ]
    return int(any(result.returncode for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
