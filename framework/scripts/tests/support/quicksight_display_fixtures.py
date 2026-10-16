"""QuickSight datasource aliases preserve every selected parameter row."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from design_layout import ALIGNMENT, HEADER, expanded_design

from model_display import display_rows

ROOT = Path(__file__).resolve().parents[4]

KIND = "QuickSight.DataSource"


__all__ = ['ALIGNMENT', 'HEADER', 'KIND', 'Path', 'ROOT', 'display_rows', 'expanded_design', 'sys']
