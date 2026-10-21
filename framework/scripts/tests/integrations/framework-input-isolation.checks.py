#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.framework_input_isolation_fixtures import *

@it_case
def check():
    from integrations.validation_checks.task import check_task_type_dispatch
    if not __debug__:
        raise SystemExit('Focused checks require assertions; run without -O')
    from support.worktree_task_fixtures import fixture, git, contract
    from support.blueprint_loop_fixtures import make_framework_fixture
    from task_contract import selected_task
    with fixture() as root:
        make_framework_fixture(ROOT, root)
        git(root, 'add', '.')
        git(root, 'commit', '-qm', 'synthetic Framework inputs')
        name = 'tasks/isolation.md'
        (root / name).parent.mkdir(exist_ok=True)
        (root / name).write_text(contract('isolation', ('file.txt',)))
        validator = MODULE.Validator(root, set(), cache=True, fresh=True)
        with selected_task(root, name), ExitStack() as stack, redirect_stdout(io.StringIO()) as output:
            for method in ('stat', 'open', 'glob', 'rglob', 'iterdir'):
                original = getattr(Path, method)
                def guarded(path, *args, original=original, **kwargs):
                    assert all(path != base/'project.json' and not path.is_relative_to(base/'model')
                               for base in (root, ROOT)), path
                    return original(path, *args, **kwargs)
                stack.enter_context(patch.object(Path, method, guarded))
            assert validator.run() == 0, (validator.errors, output.getvalue())
            check_task_type_dispatch()
    print('Framework input isolation: PASS (no Model/project access; consumer validation retained)')


if __name__ == '__main__':
    check()

