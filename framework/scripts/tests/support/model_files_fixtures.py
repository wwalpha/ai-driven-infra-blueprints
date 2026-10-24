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


def resource_reading_fixture(root):
    source = root / "model/dev/123456789012/kms.properties"
    values = {
        "desired.service.kms.serviceId": "kms",
        "desired.service.kms.ownedCatalogResourceTypes": "KMS.Key,KMS.Alias",
        "display.service.title": "# KMS 詳細設計",
        "desired.service.identity.lastAllocated": '{"KMS.Key":60,"KMS.Alias":3}',
        "desired.note.001.text": "共通注記はresource番号と同じでもservice全体に適用する",
    }
    for number in range(1, 61):
        identity = f"{number:03d}"
        kind = "KMS.Alias" if number in (2, 3) else "KMS.Key"
        values.update({
            f"desired.resource.{identity}.resourceType": kind,
            f"desired.resource.{identity}.logicalId": kind.replace(".", "_") + "_" + identity, f'desired.resource.{identity}.anchor': 'resource-' + (kind.replace('.', '_') + '_' + identity),
            f"desired.resource.{identity}.resourceMode": "CREATE",
            f"display.resource.{identity}.comment": f"用途{number}",
            f"desired.row.{identity}-001.property": f"{kind}.Description",
            f"desired.row.{identity}-001.value": f"設定{number}=値",
            f"desired.row.{identity}-001.comment": f"説明{number}",
        })
        if number in (2, 3):
            values[f"desired.resource.{identity}.parentReference"] = "[KMS_Key_001](kms.md#resource-KMS_Key_001)"
            values[f"desired.resource.{identity}.parentProperty"] = "KMS.Alias.TargetKeyId"
        if number == 1:
            values.update({
                "desired.row.001-002.property": "KMS.Key.KeyId",
                "desired.row.001-002.comment": "識別子",
                "desired.row.001-002.value": "[KMS_Key_001](kms.md#resource-KMS_Key_001)",
                "observed.row.001-002.property": "KMS.Key.KeyId",
                "observed.row.001-002.value": "12345678-current-key-id",
                "desired.row.001-003.property": "KMS.Key.KeyPolicy",
                "desired.row.001-003.comment": "Policy",
                "desired.row.001-003.value": "[Policy](kms/key-policy.json)",
                "desired.row.001-003.document": '{"Statement": [{"Sid": "保持=値", "Resource": "[Recorder](config.md#config-recorder)"}]}',
            })


    write_model(source, values)
    return source, values
