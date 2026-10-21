"""Focused self-checks for generated service models."""

from __future__ import annotations

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import json
import pytest
from model.files import load_model
from support.model_sources import write_model
from support.validator import load

SCRIPT = (Path(__file__).resolve().parents[2] / 'sync-model.py')

MODULE = load('sync-model')

def build_generated_policy(root, definitions_root=None):
    (root / 'project.json').write_text(json.dumps({'projectName': 'test', 'targets': [{
        'environment': 'dev', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1',
        'iacEngine': 'cloudformation'}]}) + '\n', encoding='utf-8')
    model = root / 'model/dev/123456789012/iam.properties'
    values = {
        'desired.service.iam.serviceId': 'iam',
        'desired.service.iam.ownedCatalogResourceTypes': 'IAM.Role',
        'display.service.title': '# IAM 詳細設計',
        'desired.resource.001.resourceType': 'IAM.Role',
        'desired.resource.001.logicalId': 'IAM_Role_001',
        'desired.service.identity.lastAllocated': '{"IAM.Role":1}',
        'desired.resource.001.cfn-logicalId': 'cfn-stack-app-dev-iam-AppRole',
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
    if MODULE.sync(root, True, 'dev', '123456789012', ['iam'], definitions_root=definitions_root) != 0:
        raise RuntimeError('generated_policy fixture initialization failed')
    return values


@pytest.fixture
def generated_policy(tmp_path, request):
    from support.it_workspace import populate
    root = populate("generated_policy", tmp_path)
    from support.it_fixture_bundle import source
    from support.it_workspace import copy_framework
    from utils.aws_mappings import mapping_alias
    definitions = source('framework')
    if request.node.originalname == 'check_stage_definition_errors' or (request.node.originalname == 'check_publication_boundary' and request.node.callspec.params.get('fault') == 'mapping'):
        definitions = tmp_path / 'private-definitions'
        copy_framework(definitions / 'framework')
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

    with mapping_alias(definitions, root):
        yield root, model, values, design, artifact, register
