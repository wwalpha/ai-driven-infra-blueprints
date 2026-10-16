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
    validator = MODULE.Validator(ROOT, set(), cache=True, fresh=True)
    with ExitStack() as stack, redirect_stdout(io.StringIO()) as output:
        for name in ('stat', 'open', 'glob', 'rglob', 'iterdir'):
            original = getattr(Path, name)
            def guarded(path, *args, original=original, **kwargs):
                assert path != ROOT/'project.json' and not path.is_relative_to(ROOT/'model'), path
                return original(path, *args, **kwargs)
            stack.enter_context(patch.object(Path, name, guarded))
        assert validator.run() == 0, output.getvalue()
        check_task_type_dispatch()
    print('Framework input isolation: PASS (no Model/project access; consumer validation retained)')


if __name__ == '__main__':
    check()

