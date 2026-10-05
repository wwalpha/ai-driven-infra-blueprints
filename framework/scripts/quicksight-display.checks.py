#!/usr/bin/env python3
"""QuickSight datasource aliases preserve every selected parameter row."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from pathlib import Path

from design_layout import ALIGNMENT, HEADER, expanded_design
from model_design import display_rows


ROOT = Path(__file__).resolve().parents[2]
KIND = "QuickSight.DataSource"


def main():
    fields = [line.partition("=")[0] for line in
              (ROOT / "framework/materials/aws/QuickSight_DataSource.properties").read_text(encoding="utf-8").splitlines()
              if ".DataSourceParameters." in line]
    assert len(fields) == 15
    source = [[str(index), field, f"`value-{index}`", f"設定の説明{index}"]
              for index, field in enumerate(fields, 1)]
    source.append(["16", KIND + ".Type", "`ATHENA`", "接続先の種類"])
    shown = display_rows(KIND, source)
    assert shown == [[identity, prop.removeprefix(KIND + ".").removeprefix("DataSourceParameters."), value, comment]
                     for identity, prop, value, comment in source]
    lines = ["### " + KIND + ": datasource", HEADER, ALIGNMENT,
             *("| " + " | ".join(row) + " |" for row in shown)]
    restored, children = expanded_design(lines)
    assert not children
    assert restored[3:] == ["| " + " | ".join(row) + " |" for row in source]
    print("QuickSight display: PASS (15 parameter aliases, unchanged Type, lossless rows)")


if __name__ == "__main__":
    main()
