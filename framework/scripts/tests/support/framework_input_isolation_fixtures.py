"""Framework validation must never inspect real consumer inputs."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from contextlib import ExitStack, redirect_stdout

import io

from tempfile import TemporaryDirectory

from unittest.mock import patch

from support.validator import MODULE

from validation.framework_contracts import check_structure

from validation.findings import Findings

from validation.project import check_validation_scope

from validation_cache import PassCache


ROOT = Path(__file__).resolve().parents[4]


__all__ = ['ExitStack', 'Findings', 'MODULE', 'PassCache', 'Path', 'ROOT', 'TemporaryDirectory', 'check_structure', 'check_validation_scope', 'io', 'patch', 'redirect_stdout', 'sys']
