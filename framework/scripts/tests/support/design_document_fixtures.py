"""Plain Python snapshot checks and shared reference-heavy regression fixture."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import model_design

import model_core

import model_projection

import aws_mapping_display

import hashlib

import tempfile

from concurrent.futures import ThreadPoolExecutor

from unittest.mock import patch

import design_document as documents

from design_document import DesignIndex

import importlib.util

def reference_fixture(root, count=80):
    scripts = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('layout_fixtures', scripts / 'tests/support/design_layout_fixtures.py')
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    source = root / 'docs/designs/dev/account/s3.md'
    source.parent.mkdir(parents=True, exist_ok=True)
    target = source.with_name('kms.md')
    target_text = fixtures.KMS.replace('<a id="kms-keyone"></a>', '<!-- resource-logical-id: KeyHidden -->\n<a id="kms-keyone"></a>')
    # Invalid unrelated metadata must remain outside reference-target parsing scope.
    target_text += '\n<!-- resource-logical-id: Bad! -->\n<a id="kms-unrelated"></a>\n### KMS.Key: unrelated\n'
    source_text = fixtures.S3.split('| 3 | BucketEncryption', 1)[0]
    for number in range(count):
        label, anchor = ('alias/two', 'kms-aliastwo') if number % 2 == 0 else ('alias/three', 'kms-aliasthree')
        source_text += f'| {number+3} | BucketEncryption[].KMSMasterKeyID | [{label}](kms.md#{anchor}) | 暗号化に使用するKMS alias |\n'
    source_text += f'| {count+3} | SourceKeyId | [1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone) | 参照ID |\n'
    source_text += f'| {count+4} | SourceKeyId | [unresolved](absent.md#absent) | 未解決参照 |\n'
    source_text += f'| {count+5} | SourceKeyId | [unresolved](kms.md#absent) | 未解決anchor |\n'
    source_text += '<!-- [hidden](hidden.md#hidden) -->\n'
    source.write_text(source_text, encoding='utf-8')
    target.write_text(target_text, encoding='utf-8')
    return source, target, source_text, target_text


__all__ = ['DesignIndex', 'Path', 'ThreadPoolExecutor', 'aws_mapping_display', 'documents', 'hashlib', 'importlib', 'model_core', 'model_design', 'model_projection', 'patch', 'reference_fixture', 'sys', 'tempfile']
