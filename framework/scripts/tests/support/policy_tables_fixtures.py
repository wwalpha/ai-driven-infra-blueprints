"""Check service policy views, IAM regression and the unchanged model contract."""

import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import subprocess
import tempfile

import aws_mapping
import aws_mapping_display
import model.projection as model_projection
import pytest
import utils.aws_mappings as _imports_utils_aws_mappings
from design.array_display import indexed_rows
from design.layout_schema import ALIGNMENT, HEADER
from design.policy_tables import IAM_END as END
from design.policy_tables import IAM_START as START
from design.policy_tables import (
    iam_role_policy_artifact_filename,
    main,
    policy_lines,
    rendered_design,
    resources_in,
    without_policy_tables,
)
from support.pytest_cli import run
from support.validator import load
from utils.input_cache import input_scope

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")



SCRIPTS = Path(__file__).resolve().parents[2]

VALIDATOR = load("validate-blueprint")


__all__ = ['ALIGNMENT', 'END', 'HEADER', 'Path', 'SCRIPTS', 'START', 'VALIDATOR', 'iam_role_policy_artifact_filename', 'indexed_rows', 'json', 'load', 'model_projection', 'policy_lines', 'pytest', 'pytestmark', 'rendered_design', 'resources_in', 'run', 'subprocess', 'sys', 'tempfile', 'without_policy_tables']


def policy_cli(argv):

    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(argv)
    return subprocess.CompletedProcess(argv, code, stdout.getvalue().encode(), stderr.getvalue().encode())


@pytest.fixture
def policy_mapping_cache(catalog_display_fixture):
    """Static Mapping reuse is owned by the production root factory."""
    yield


__all__ += ['policy_cli', 'policy_mapping_cache']


def _callback_mapping_cache_checks_read(root):
    return (aws_mapping_display.owners(root), aws_mapping_display.rules(root, 'IAM.Role'),
            aws_mapping.runtime_registry(root, 'iam'))


def mapping_cache_checks():

    read = (input_scope)(_callback_mapping_cache_checks_read)

    with tempfile.TemporaryDirectory() as directory:
        roots = [Path(directory) / name for name in ('first', 'second')]
        first, second = (read(root) for root in roots[:2])
        definition_root = _imports_utils_aws_mappings.definition_root
        assert first[2].root == definition_root(roots[0]) and second[2].root == definition_root(roots[1])
        assert read(roots[0])[2] is first[2]
        assert read(roots[1])[2] is second[2]


__all__ += ['mapping_cache_checks']


def iam_fixture(root):
    path = root / "docs/designs/dev/123456789012/iam.md"
    path.parent.mkdir(parents=True)
    artifacts = path.parent / "iam"
    artifacts.mkdir()
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "vpc-flow-logs.amazonaws.com"},
        "Action": "sts:AssumeRole", "Condition": {
            "StringEquals": {"aws:SourceAccount": "123456789012"},
            "ArnLike": {"aws:SourceArn": "arn:aws:ec2:ap-northeast-1:123456789012:vpc-flow-log/*"},
        },
    }]}
    inline = {"Version": "2012-10-17", "Id": "Logging", "Statement": [
        {"Sid": "Write", "Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": ["arn:aws:logs:*:123456789012:log-group:example:*"]},
        {"Effect": "Deny", "NotAction": ["logs:DescribeLogGroups"], "NotResource": "arn:aws:logs:*:123456789012:log-group:other:*"},
    ]}
    text = """# IAM設計書

- Design service ID: `iam`
- Owned catalog resource types: `IAM.Role`, `IAM.InstanceProfile`

## リソース一覧

### IAM.Role

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [RoleA](#iam-rolea) | Flow Logsに使用するRole |
| 2 | [RoleB](#iam-roleb) | 追加ログを記録するRole |

### IAM.InstanceProfile

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [Profile](#iam-profile) | EC2へroleを渡すprofile |

## リソース詳細

"""
    for logical_id in ("RoleA", "RoleB"):
        file_id = VALIDATOR.artifact_id(logical_id)
        for suffix, document in (("trust-policy", trust), ("logging", inline), ("extra", inline)):
            (artifacts / f"{file_id}-{suffix}.json").write_text(json.dumps(document), encoding="utf-8")
        text += f'''<a id="iam-{logical_id.lower()}"></a>

### IAM.Role: {logical_id}

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RoleName | `{logical_id}` | ロールの名前 |
| 2 | AssumeRolePolicyDocument | [FlowLogsTrust](iam/{file_id}-trust-policy.json) | 信頼ポリシー |
| 3 | Policies[].PolicyName | `Logging` | ポリシーの名前 |
| 4 | Policies[].PolicyDocument | [Logging](iam/{file_id}-logging.json) | 権限ポリシー |
| 5 | Policies[].PolicyName | `Extra` | ポリシーの名前 |
| 6 | Policies[].PolicyDocument | [Extra](iam/{file_id}-extra.json) | 追加の権限ポリシー |

'''
    text += '''<a id="iam-profile"></a>

### IAM.InstanceProfile: Profile

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | InstanceProfileName | `example` | インスタンスプロファイルの名前 |
'''
    path.write_text(text, encoding="utf-8")
    return path, artifacts, trust, inline, text
