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
