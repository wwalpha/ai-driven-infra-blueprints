"""Check service policy views, IAM regression and the unchanged model contract."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import pytest

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

from support.pytest_cli import run

import model_projection

import json

from support.validator import load

import subprocess

import tempfile

from array_display import indexed_rows

from design_layout import HEADER, ALIGNMENT

from policy_tables import IAM_END as END, IAM_START as START, iam_role_policy_artifact_filename, policy_lines, rendered_design, resources_in, without_policy_tables

SCRIPTS = Path(__file__).resolve().parents[2]

VALIDATOR = load("validate-blueprint")


__all__ = ['ALIGNMENT', 'END', 'HEADER', 'Path', 'SCRIPTS', 'START', 'VALIDATOR', 'iam_role_policy_artifact_filename', 'indexed_rows', 'json', 'load', 'model_projection', 'policy_lines', 'pytest', 'pytestmark', 'rendered_design', 'resources_in', 'run', 'subprocess', 'sys', 'tempfile', 'without_policy_tables']
