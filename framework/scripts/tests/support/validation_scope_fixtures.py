"""Regression checks for explicit scope, isolated services, and parallel targets."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import io
import json
import shutil
import subprocess
import tempfile
import threading
from contextlib import redirect_stdout
from unittest.mock import patch

import model.projection as model_projection
from design.catalog import DesignSchemaCatalog
from design.layout_schema import resource_anchor
from model.files import read_model
from support.model_sources import write_model
from support.validator import load
from validation_cache import PassCache
from validation_scope import active_scope, scoped_files

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]

VALIDATOR = load("validate-blueprint")

SYNC = load("sync-model")


__all__ = [
    "DesignSchemaCatalog",
    "PassCache",
    "Path",
    "ROOT",
    "SYNC",
    "VALIDATOR",
    "active_scope",
    "annotations",
    "io",
    "json",
    "load",
    "model_projection",
    "patch",
    "read_model",
    "redirect_stdout",
    "resource_anchor",
    "scoped_files",
    "shutil",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "write_model",
]
