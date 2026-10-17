"""Checks for authoritative properties, service displays and service failure protection."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from support.model_sources import snapshot_model

from model_files import read_model, load_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model, write_fixture_files

import sync_views

import sync_runtime

import sync_files

import model_design

import model_projection

from contextlib import redirect_stderr

import io

import json

import os

import shutil

import pytest

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

import subprocess

from support.validator import load

from support.pytest_cli import Diagnostics, run

from unittest.mock import patch

from types import SimpleNamespace

from model_design import (
    naming_rule_files, naming_targets, naming_target_matches, markdown_for, naming_errors,
    validate_kms_policy_accounts,
)

from model_display import display_rows

from model_core import properties, stack_model

from design_layout import (
    stack_design, stack_deployment_policy, SUBNET_LIST_PROPERTIES, CODEBUILD_VPC_PROPERTIES, HEADER,
    ALIGNMENT, expanded_display_rows,
)

from model_design import design_naming_errors

from model_references import resource_rows

from model_display import row_table, catalog_display_rows

from design_layout import catalog_order_errors

from design_layout import resource_display_name, resource_anchor, resource_has_name_property

from security_group_tables import COMMENTS, GROUP_COMMENTS

ROOT = Path(__file__).resolve().parents[4]

SYNC = load('sync-model')

def model(service, kind, name, rows, logical_id=None, label=None):
    anchor = resource_anchor(service, name, kind)
    result = {
        f"desired.service.{service}.serviceId": service,
        f"desired.service.{service}.ownedCatalogResourceTypes": kind,
        "display.service.title": f"# {service} 詳細設計",
        "desired.resource.001.resourceType": kind,
        "desired.resource.001.logicalId": logical_id or name,
        "desired.resource.001.anchor": anchor,
        "display.resource.001.comment": "対象環境のデータ処理を提供するresource",
    }
    if label:
        result["display.resource.001.label"] = label
    for number, (field, value, comment) in enumerate(rows, 1):
        key = f"001-{number:03d}"
        result[f"desired.row.{key}.property"] = kind + "." + field
        result[f"desired.row.{key}.value"] = value
        result[f"desired.row.{key}.comment"] = comment
    return result

def text(values):
    values = dict(values)
    for key, value in list(values.items()):
        if key.endswith('.document'):
            document = json.loads(value)
            values[key] = json.dumps(document, ensure_ascii=False, separators=(',', ':'))
            values[key.removesuffix('.document')+'.artifactSha256'] = model_projection.document_sha256(document)
    return "# Generated Model; edit registered template/parameters/observed, not this file.\n" + "".join(f"{key}={value}\n" for key, value in sorted(values.items()))

def roundtrip(path, values, root):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_for(path, values, root), encoding="utf-8")
    projected = properties(model_projection.model_for(path, root, source=values))
    expected = {key: value for key, value in values.items() if not key.startswith("display.") and not key.endswith(".cfn-logicalId")}
    assert projected == expected, (path.name, {key: (projected.get(key), expected.get(key)) for key in projected.keys() | expected.keys() if projected.get(key) != expected.get(key)})
    return path.read_text(encoding="utf-8")

@pytest.fixture
def root(tmp_path):
    from support.it_fixture_bundle import source

    (tmp_path / "framework").symlink_to(
        source("framework") / "framework", target_is_directory=True,
    )
    return tmp_path.resolve()

@pytest.fixture
def project(root):
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
        "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1",
        "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")


__all__ = ['ALIGNMENT', 'CODEBUILD_VPC_PROPERTIES', 'COMMENTS', 'Diagnostics', 'GROUP_COMMENTS', 'HEADER', 'Path', 'ROOT', 'SUBNET_LIST_PROPERTIES', 'SYNC', 'SimpleNamespace', 'catalog_display_rows', 'catalog_order_errors', 'design_naming_errors', 'display_rows', 'expanded_display_rows', 'io', 'json', 'load', 'load_model', 'markdown_for', 'model', 'model_design', 'model_projection', 'naming_errors', 'naming_rule_files', 'naming_target_matches', 'naming_targets', 'os', 'patch', 'project', 'properties', 'pytest', 'pytestmark', 'read_model', 'redirect_stderr', 'resource_anchor', 'resource_display_name', 'resource_has_name_property', 'resource_rows', 'root', 'roundtrip', 'row_table', 'run', 'shutil', 'snapshot_model', 'stack_deployment_policy', 'stack_design', 'stack_model', 'subprocess', 'sync_files', 'sync_runtime', 'sync_views', 'sys', 'text', 'validate_kms_policy_accounts', 'write_fixture_files', 'write_model']

def main():
    return run(Path(__file__).resolve().parents[1] / 'integrations/model_design.checks.py', message="model_design: PASS (authoritative updates, service rollback, naming coverage and service displays)")

__all__.append('main')
