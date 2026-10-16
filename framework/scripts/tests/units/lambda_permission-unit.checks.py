#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.lambda_permission_fixtures import *

def check_permission_catalog():
    assert not layout_errors(ROOT)
    assert formal_property("Permission.Action", FUNCTION) == PERMISSION + ".Action"



import pytest
pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
