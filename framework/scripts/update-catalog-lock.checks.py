#!/usr/bin/env python3
"""Focused checks for catalog input and identifier output counts."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("update-catalog-lock.py")
SPEC = importlib.util.spec_from_file_location("update_catalog_lock", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        catalog = Path(directory) / "EC2_VPC.properties"
        catalog.write_text(
            "EC2.VPC.CidrBlock=\nEC2.VPC.VpcId=IDENTIFIER_OUTPUT\n",
            encoding="utf-8",
        )
        assert MODULE.catalog_counts([catalog]) == (1, 1)
        catalog.write_text("EC2.VPC.VpcId=UNKNOWN\n", encoding="utf-8")
        try:
            MODULE.catalog_counts([catalog])
        except ValueError:
            pass
        else:
            raise AssertionError("unknown catalog marker was accepted")
    print("update-catalog-lock: PASS")


if __name__ == "__main__":
    main()
