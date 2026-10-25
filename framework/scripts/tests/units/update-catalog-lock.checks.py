#!/usr/bin/env python3
"""Focused checks for catalog input and identifier output counts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import importlib.util
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest.mock import patch

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPT = Path(__file__).resolve().parents[2] / "update-catalog-lock.py"
SPEC = importlib.util.spec_from_file_location("update_catalog_lock", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> None:
    names = ["ApiGateway_ApiKey.properties", "ApiGatewayV2_Api.properties"]
    for path_type in (PurePosixPath, PureWindowsPath):
        paths = [path_type(name) for name in names]
        with patch.object(MODULE, "CATALOG_DIR") as directory:
            directory.glob.return_value = paths
            assert [path.name for path in MODULE.catalog_files()] == sorted(names)
    print("update-catalog-lock: PASS")


if __name__ == "__main__":
    main()
