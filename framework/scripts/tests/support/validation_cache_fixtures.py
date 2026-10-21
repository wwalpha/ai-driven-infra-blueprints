"""Small runnable checks for content-addressed results and invocation-local inputs."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model

import os

import tempfile

from validation_cache import PassCache, digest_files, input_scope

from design_catalog import design_material_files

from model.core import entries


__all__ = ['PassCache', 'Path', 'design_material_files', 'digest_files', 'entries', 'input_scope', 'os', 'sys', 'tempfile', 'write_model']
