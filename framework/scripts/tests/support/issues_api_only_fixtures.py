"""API-only comparison stays partial; implementation type resolution still fails."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import copy
import json
import subprocess
import tempfile
from collections import Counter
from unittest.mock import patch

from comparison import Comparison
from design_catalog import DesignSchemaCatalog
from issues.aggregate import iac_summary
from issues.artifact import summary
from issues.cli import main
from issues.reports import iac_report
from support.validator import load

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

ROOT = Path(__file__).resolve().parents[4]

def cli_exit(root, temporary, artifact, expected):
    before = copy.deepcopy(artifact)
    with patch('issues.runner.scan', return_value=artifact), patch('issues.artifact.review_payload', return_value={}), \
         patch('sys.argv', ['issues_scan.py', '--repository-root', str(root), 'scan', '--environment', 'dev',
                            '--target-directory', '123456789012', '--service', 's3',
                            '--artifact', str(temporary / 'scan.json')]):
        assert main() == expected
    assert artifact == before
    assert json.loads((temporary / 'scan.json').read_text(encoding='utf-8')) == artifact


__all__ = ['Comparison', 'Counter', 'DesignSchemaCatalog', 'Path', 'ROOT', 'cli_exit', 'copy', 'iac_report', 'iac_summary', 'json', 'load', 'main', 'patch', 'subprocess', 'summary', 'sys', 'tempfile']
