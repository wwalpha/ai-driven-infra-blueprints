"""Check service policy views, IAM regression and the unchanged model contract."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import pytest

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

from support.pytest_cli import run

import model_projection

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
def policy_mapping_cache(catalog_display_fixture, monkeypatch):
    """Replace invocation memoization only for static Mapping definitions."""
    from functools import wraps
    import aws_mapping
    import aws_mapping_display

    from validation_cache import memoized

    results = {}

    @memoized
    def snapshot(root):
        # Existing input scopes pin inputs only for one generation/validation call.
        return tuple((path.name, path.read_bytes())
                     for path in sorted((root / 'framework/mappings/aws').glob('*.yaml')))

    def cached(function):
        @wraps(function)
        def wrapper(root, *args):
            root = Path(root)
            actual = root if (root / 'framework/mappings/aws').is_dir() else aws_mapping_display.ROOT
            key = (function, root, snapshot(actual), args)
            if key not in results:
                results[key] = function.__wrapped__(root, *args)
            return results[key]
        return wrapper

    functions = [(module, name, getattr(module, name))
                 for module, name in ((aws_mapping_display, 'owners'), (aws_mapping_display, 'rules'),
                                      (aws_mapping, 'runtime_registry'))]
    with monkeypatch.context() as patches:
        for module, name, function in functions:
            patches.setattr(module, name, cached(function))
        yield
    assert all(getattr(module, name) is function for module, name, function in functions)


__all__ += ['policy_cli', 'policy_mapping_cache']


def mapping_cache_checks():
    import os
    import aws_mapping
    import aws_mapping_display
    from validation_cache import input_scope

    @input_scope
    def read(root):
        return (aws_mapping_display.owners(root), aws_mapping_display.rules(root, 'IAM.Role'),
                aws_mapping.runtime_registry(root, 'iam'))

    with tempfile.TemporaryDirectory() as directory:
        roots = [Path(directory) / name for name in ('first', 'second')]
        content = (SCRIPTS.parents[1] / 'framework/mappings/aws/iam.yaml').read_text(encoding='utf-8')
        for root in roots:
            path = root / 'framework/mappings/aws/iam.yaml'
            path.parent.mkdir(parents=True)
            path.write_text(content, encoding='utf-8')
        first, second = (read(root) for root in roots)
        assert first[2].root == roots[0] and second[2].root == roots[1]
        assert read(roots[0])[2] is first[2], 'unchanged Mapping should reuse its registry'
        path = roots[0] / 'framework/mappings/aws/iam.yaml'
        stat = path.stat()
        # A comment-only change with restored timestamps must still invalidate.
        path.write_text(content + '\n# changed Mapping\n', encoding='utf-8')
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert read(roots[0])[2] is not first[2]
        assert read(roots[1])[2] is second[2]
        path.write_text(content.replace('name: RoleName', 'name: ChangedName'), encoding='utf-8')
        changed = read(roots[0])
        assert changed[1]['IAM.Role.RoleName'].name == 'ChangedName'
        assert changed[2].properties['IAM.Role.RoleName'].name == 'ChangedName'
        extra = path.with_name('extra.yaml')
        extra.write_text('resourceTypes: {Example.Resource: {}}', encoding='utf-8')
        assert read(roots[0])[0]['Example.Resource'] == 'extra'
        extra.unlink()
        assert 'Example.Resource' not in read(roots[0])[0]
        path.write_text('invalid: [', encoding='utf-8')
        with pytest.raises(ValueError):
            read(roots[0])
        path.write_text(content, encoding='utf-8')
        assert read(roots[0])[1]['IAM.Role.RoleName'].name == 'RoleName'


__all__ += ['mapping_cache_checks']
