"""Runnable checks for issue isolation, remediation and mutation guards."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json
import subprocess
import tempfile
from unittest import mock

from issue_gate import (
    issue_errors,
    remediation_scope,
    require_no_issues,
    require_target_no_issues,
)
from support.validator import load

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

__all__ = [
    "Path",
    "issue_errors",
    "json",
    "load",
    "mock",
    "remediation_scope",
    "require_no_issues",
    "require_target_no_issues",
    "subprocess",
    "sys",
    "tempfile",
]
