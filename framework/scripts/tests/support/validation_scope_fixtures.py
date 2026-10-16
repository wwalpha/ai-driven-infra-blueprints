"""Regression checks for explicit scope, isolated services, and parallel targets."""

from __future__ import annotations

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model_files import read_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model

import model_projection

from contextlib import redirect_stdout

import io

import json

from support.validator import load

import shutil

import subprocess

import tempfile

import threading

from unittest.mock import patch

from validation_scope import active_scope, scoped_files

from design_catalog import DesignSchemaCatalog

from validation_cache import PassCache

from model_design import resource_anchor

ROOT = Path(__file__).resolve().parents[4]

VALIDATOR = load('validate-blueprint')

SYNC = load('sync-model')


__all__ = ['DesignSchemaCatalog', 'PassCache', 'Path', 'ROOT', 'SYNC', 'VALIDATOR', 'active_scope', 'annotations', 'io', 'json', 'load', 'model_projection', 'patch', 'read_model', 'redirect_stdout', 'resource_anchor', 'scoped_files', 'shutil', 'subprocess', 'sys', 'tempfile', 'threading', 'write_model']
