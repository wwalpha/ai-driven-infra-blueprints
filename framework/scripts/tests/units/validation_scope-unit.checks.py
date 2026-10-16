#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.validation_scope_fixtures import *

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
