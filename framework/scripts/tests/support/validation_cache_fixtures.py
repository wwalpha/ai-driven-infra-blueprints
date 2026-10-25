"""Small runnable checks for content-addressed results and invocation-local inputs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import os
import tempfile

from design.catalog import design_material_files
from model.core import entries
from support.model_sources import write_model
from utils.input_cache import digest_files, input_scope
from validation_cache import PassCache

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

__all__ = [
    "PassCache",
    "Path",
    "design_material_files",
    "digest_files",
    "entries",
    "input_scope",
    "os",
    "sys",
    "tempfile",
    "write_model",
]
