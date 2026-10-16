"""API-only comparison stays partial; implementation type resolution still fails."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy

from collections import Counter

import json

import subprocess

import tempfile

from unittest.mock import patch

from design_catalog import DesignSchemaCatalog

from issues_iac import Comparison

from issues_reports import iac_summary, iac_report

from issues_scan import main, summary

from support.validator import load

ROOT = Path(__file__).resolve().parents[4]

def cli_exit(root, temporary, artifact, expected):
    before = copy.deepcopy(artifact)
    with patch('issues_scan.scan', return_value=artifact), patch('issues_scan.review_payload', return_value={}), \
         patch('sys.argv', ['issues_scan.py', '--repository-root', str(root), 'scan', '--environment', 'dev',
                            '--target-directory', '123456789012', '--service', 's3',
                            '--artifact', str(temporary / 'scan.json')]):
        assert main() == expected
    assert artifact == before
    assert json.loads((temporary / 'scan.json').read_text(encoding='utf-8')) == artifact


__all__ = ['Comparison', 'Counter', 'DesignSchemaCatalog', 'Path', 'ROOT', 'cli_exit', 'copy', 'iac_report', 'iac_summary', 'json', 'load', 'main', 'patch', 'subprocess', 'summary', 'sys', 'tempfile']
