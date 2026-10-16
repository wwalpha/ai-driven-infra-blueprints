"""Checks for bounded, indexed authoritative service models."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model

import sync_files

import io

import os

import shutil

import subprocess

import tempfile

from contextlib import redirect_stdout

from support.validator import load

from unittest.mock import patch

from model_files import INDEX_HEADER, model_parts, model_file_contents, read_model, resource_keys, load_model

from model_design import markdown_for

from model_core import properties

from validation_scope import scoped_files

from issue_gate import unresolved_services

ROOT = Path(__file__).resolve().parents[4]

SYNC = load('sync-model')

VALIDATOR = load('validate-blueprint')

DEPLOY = load('cloudformation-deploy')


__all__ = ['DEPLOY', 'INDEX_HEADER', 'Path', 'ROOT', 'SYNC', 'VALIDATOR', 'io', 'load', 'load_model', 'markdown_for', 'model_file_contents', 'model_parts', 'os', 'patch', 'properties', 'read_model', 'redirect_stdout', 'resource_keys', 'scoped_files', 'shutil', 'subprocess', 'sync_files', 'sys', 'tempfile', 'unresolved_services', 'write_model']
