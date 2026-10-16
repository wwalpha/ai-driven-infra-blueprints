"""Focused self-checks for generated service models."""

from __future__ import annotations

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model_files import read_model, load_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model, write_fixture_files

import pytest

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

from support.pytest_cli import run

import sync_views

import sync_runtime

import model_design

import model_projection

import io

import json

import os

import shutil

from contextlib import contextmanager, redirect_stdout, redirect_stderr

from support.validator import load

from unittest.mock import patch

from design_catalog import property_paths_with_parents

SCRIPT = (Path(__file__).resolve().parents[2] / 'sync-model.py')

MODULE = load('sync-model')

def build_generated_policy(root):
    (root / 'project.json').write_text(json.dumps({'projectName': 'test', 'targets': [{
        'environment': 'dev', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1',
        'iacEngine': 'cloudformation'}]}) + '\n', encoding='utf-8')
    model = root / 'model/dev/123456789012/iam.properties'
    values = {
        'desired.service.iam.serviceId': 'iam',
        'desired.service.iam.ownedCatalogResourceTypes': 'IAM.Role',
        'display.service.title': '# IAM 詳細設計',
        'desired.resource.001.resourceType': 'IAM.Role',
        'desired.resource.001.logicalId': 'AppRole',
        'desired.resource.001.anchor': 'iam-app-dev-role',
        'display.resource.001.comment': 'アプリケーションの実行権限',
        'desired.row.001-001.property': 'IAM.Role.RoleName',
        'desired.row.001-001.value': '`app-dev-role`',
        'desired.row.001-001.comment': '権限を識別する名前',
        'desired.row.001-002.property': 'IAM.Role.AssumeRolePolicyDocument',
        'desired.row.001-002.value': '[信頼ポリシー](iam/app-role-trust-policy.json)',
        'desired.row.001-002.comment': '引受元に許可する権限',
        'desired.row.001-002.document': json.dumps({'Version': '2012-10-17', 'Statement': [{
            'Effect': 'Allow', 'Principal': {'Service': 'lambda.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]}),
    }
    write_model(model, values)
    if MODULE.sync(root, True, 'dev', '123456789012', ['iam']) != 0:
        raise RuntimeError('generated_policy fixture initialization failed')
    return values


@pytest.fixture
def generated_policy(tmp_path):
    from support.it_workspace import populate
    root = populate("generated_policy", tmp_path)
    populate("framework", root)
    model = root / 'model/dev/123456789012/iam.properties'
    values = json.loads((root / 'fixture-values.json').read_text(encoding='utf-8'))
    (root / 'fixture-values.json').unlink()
    design = root / 'docs/designs/dev/123456789012/iam.md'
    artifact = design.with_suffix('') / 'app-role-trust-policy.json'

    def register(outputs):
        import task_contract as tasks
        name = 'tasks/generated-policy.md'
        files = [root / name, *load_model(model).files, *outputs]
        listed = '\n'.join(f'- `{file.relative_to(root).as_posix()}`' for file in files)
        tasks.start(root, name, '# Test\n## Task contract\n- Task type: `design`\n'
                    '- Task status: `running`\n## Validation scope\n- `dev/123456789012/iam`\n'
                    f'## Modified files\n{listed}\n## Allowed paths\n{listed}\n')
        return {tasks.SELECTOR: name}

    return root, model, values, design, artifact, register


__all__ = ['MODULE', 'Path', 'SCRIPT', 'annotations', 'contextmanager', 'generated_policy', 'io', 'json', 'load', 'load_model', 'model_design', 'model_projection', 'os', 'patch', 'property_paths_with_parents', 'pytest', 'pytestmark', 'read_model', 'redirect_stderr', 'redirect_stdout', 'run', 'shutil', 'sync_runtime', 'sync_views', 'sys', 'write_fixture_files', 'write_model']
