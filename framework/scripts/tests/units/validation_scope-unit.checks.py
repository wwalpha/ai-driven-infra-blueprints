#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.validation_scope_fixtures import *
import pytest


@pytest.mark.parametrize('scope', [None, {('stg', 'team', 'config'), ('dev', 'team', 'config')}])
@pytest.mark.parametrize('workers', [1, 4])
def check_internal_generation_dispatch(tmp_path, scope, workers):
    from script_loader import module
    runner = module('sync-model.py', 'blueprint_sync_model')
    expected = ['--jobs', str(workers)] + (['--all'] if scope is None else
        [arg for entry in sorted(scope) for arg in ('--scope', '/'.join(entry))])
    with patch.object(runner, 'run', return_value=(1, 'consumer missing: stg/team/config')) as run, \
         patch.object(subprocess, 'run', side_effect=AssertionError('Python subprocess')):
        validator = VALIDATOR.Validator(tmp_path, scope, workers=workers)
        validator.check_generated_service_models()
        validator.check_generated_service_models()
    run.assert_called_once_with(expected, repository_root=tmp_path)
    assert any('consumer missing: stg/team/config' in error for error in validator.errors)
    with patch.object(runner, 'run', side_effect=AssertionError('hook bypassed')):
        empty = VALIDATOR.Validator(tmp_path, set())
        empty.check_generated_service_models()
        assert not empty.errors
        selections = []
        def hook(selected):
            selections.append(selected)
            return []
        hooked = VALIDATOR.Validator(tmp_path, scope, model_check=hook)
        hooked.check_generated_service_models()
        assert selections == [scope] and not hooked.errors

def check_active_scope(tmp_path):
    root = tmp_path
    (root / 'tasks').mkdir()
    active = root / 'tasks/active.md'
    for text in ("", "## Validation scope\n- `dev/cde`\n", "## Validation scope\n- `ec2`\n"):
        active.write_text(text)
        try:
            active_scope(root)
        except ValueError:
            pass
        else:
            raise AssertionError("missing/incomplete scope accepted")
    assert active_scope(root, True) is None
    active.write_text("## Validation scope\n- `all`\n")
    assert active_scope(root) is None
    scope = {(env, target, "ec2") for env in ("dev", "stg") for target in ("cde", "non-cde")}
    contract = "## Validation scope\n" + "".join(f"- `{'/'.join(item)}`\n" for item in sorted(scope))
    active.write_text(contract)
    assert active_scope(root) == scope



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
