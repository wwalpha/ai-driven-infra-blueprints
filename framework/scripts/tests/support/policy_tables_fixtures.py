"""Check service policy views, IAM regression and the unchanged model contract."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import pytest

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

from support.pytest_cli import run

import model.projection as model_projection

import json

from support.validator import load

import subprocess

import tempfile

from array_display import indexed_rows

from design_layout import HEADER, ALIGNMENT

from policy_tables import IAM_END as END, IAM_START as START, iam_role_policy_artifact_filename, policy_lines, rendered_design, resources_in, without_policy_tables

SCRIPTS = Path(__file__).resolve().parents[2]

VALIDATOR = load("validate-blueprint")


__all__ = ['ALIGNMENT', 'END', 'HEADER', 'Path', 'SCRIPTS', 'START', 'VALIDATOR', 'iam_role_policy_artifact_filename', 'indexed_rows', 'json', 'load', 'model_projection', 'policy_lines', 'pytest', 'pytestmark', 'rendered_design', 'resources_in', 'run', 'subprocess', 'sys', 'tempfile', 'without_policy_tables']


def policy_cli(argv):
    from contextlib import redirect_stdout, redirect_stderr
    from io import StringIO
    from policy_tables import main
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(argv)
    return subprocess.CompletedProcess(argv, code, stdout.getvalue().encode(), stderr.getvalue().encode())


@pytest.fixture
def policy_mapping_cache(catalog_display_fixture):
    """Static Mapping reuse is owned by the production root factory."""
    yield


__all__ += ['policy_cli', 'policy_mapping_cache']


def mapping_cache_checks():
    import aws_mapping
    import aws_mapping_display
    from support.aws_mapping_fixtures import mapping_fixture
    from validation_cache import input_scope

    @input_scope
    def read(root):
        return (aws_mapping_display.owners(root), aws_mapping_display.rules(root, 'IAM.Role'),
                aws_mapping.runtime_registry(root, 'iam'))

    with tempfile.TemporaryDirectory() as directory:
        roots = [mapping_fixture(Path(directory) / name, 'iam') for name in ('first', 'second', 'renamed', 'invalid')]
        path = roots[2] / 'framework/mappings/aws/iam.yaml'
        path.write_text(path.read_text(encoding='utf-8').replace('name: RoleName', 'name: ChangedName'), encoding='utf-8')
        (roots[3] / 'framework/mappings/aws/iam.yaml').write_text('invalid: [', encoding='utf-8')
        first, second = (read(root) for root in roots[:2])
        assert first[2].root == roots[0] and second[2].root == roots[1]
        assert read(roots[0])[2] is first[2]
        assert read(roots[1])[2] is second[2]
        changed = read(roots[2])
        assert changed[1]['IAM.Role.RoleName'].name == 'ChangedName'
        assert changed[2].properties['IAM.Role.RoleName'].name == 'ChangedName'
        assert read(roots[0])[1]['IAM.Role.RoleName'].name == 'RoleName'
        for _ in range(2):
            with pytest.raises(ValueError):
                read(roots[3])


__all__ += ['mapping_cache_checks']
