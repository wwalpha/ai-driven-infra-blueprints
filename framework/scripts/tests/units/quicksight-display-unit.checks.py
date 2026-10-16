#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.quicksight_display_fixtures import *

def check_alias_catalog():
    fields = [line.partition("=")[0] for line in
              (ROOT / "framework/materials/aws/QuickSight_DataSource.properties").read_text(encoding="utf-8").splitlines()
              if ".DataSourceParameters." in line]

    assert len(fields) == 15



def check_alias_rows():
    fields = [line.partition("=")[0] for line in
              (ROOT / "framework/materials/aws/QuickSight_DataSource.properties").read_text(encoding="utf-8").splitlines()
              if ".DataSourceParameters." in line]
    source = [[str(index), field, f"`value-{index}`", f"設定の説明{index}"]
              for index, field in enumerate(fields, 1)]
    source.append(["16", KIND + ".Type", "`ATHENA`", "接続先の種類"])
    shown = display_rows(KIND, source)

    assert shown == [[identity, prop.removeprefix(KIND + ".").removeprefix("DataSourceParameters."), value, comment]
                     for identity, prop, value, comment in source]



import pytest
pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
