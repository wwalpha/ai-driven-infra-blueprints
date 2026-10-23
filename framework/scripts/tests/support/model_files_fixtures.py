"""Checks for bounded, indexed authoritative service models."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import io
import os
import shutil
import subprocess
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch

import sync_files
from issue_gate import unresolved_services
from model.core import properties
from model.files import (
    load_model,
    model_file_contents,
    model_parts,
    read_model,
    resource_keys,
)
from model.format import INDEX as INDEX_HEADER
from model.render import markdown_for
from support.model_sources import write_model
from support.validator import load
from validation_scope import scoped_files

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]

SYNC = load('sync-model')

VALIDATOR = load('validate-blueprint')

DEPLOY = load('cloudformation-deploy')


__all__ = ['DEPLOY', 'INDEX_HEADER', 'Path', 'ROOT', 'SYNC', 'VALIDATOR', 'io', 'load', 'load_model', 'markdown_for', 'model_file_contents', 'model_parts', 'os', 'patch', 'properties', 'read_model', 'redirect_stdout', 'resource_keys', 'scoped_files', 'shutil', 'subprocess', 'sync_files', 'sys', 'tempfile', 'unresolved_services', 'write_model']
