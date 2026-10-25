"""QuickSight datasource aliases preserve every selected parameter row."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from design.layout import expanded_design
from design.layout_schema import ALIGNMENT, HEADER
from model.display import display_rows

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]

KIND = "QuickSight.DataSource"


__all__ = [
    "ALIGNMENT",
    "HEADER",
    "KIND",
    "Path",
    "ROOT",
    "display_rows",
    "expanded_design",
    "sys",
]
