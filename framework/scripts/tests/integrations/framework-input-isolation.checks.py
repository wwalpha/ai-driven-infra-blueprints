#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import integrations.validation_checks.task as _imports_integrations_validation_checks_task
from support.blueprint_loop_fixtures import make_project_fixture
from support.framework_input_isolation_fixtures import (
    MODULE,
    ROOT,
    ExitStack,
    Path,
    io,
    patch,
    redirect_stdout,
    sys,
)
from support.it_case_receipt import it_case
from support.repository_fixtures import contract, fixture, git
from task_contract_core import selected_task
from utils.function_wrapper import BoundCallback as _bind_framework_callback

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

_CALLBACK_DEFAULT = object()


def _callback_check_guarded_45(
    root, _default_original, /, path, *args, original=_CALLBACK_DEFAULT, **kwargs
):
    if original is _CALLBACK_DEFAULT:
        original = _default_original
    assert all(
        path != base / "project.json" and not path.is_relative_to(base / "model")
        for base in (root, ROOT)
    ), path
    return original(path, *args, **kwargs)


@it_case
def check():
    check_task_type_dispatch = (
        _imports_integrations_validation_checks_task.check_task_type_dispatch
    )
    if not __debug__:
        raise SystemExit("Focused checks require assertions; run without -O")
    with fixture() as root:
        make_project_fixture(ROOT, root)
        git(root, "add", ".")
        git(root, "commit", "-qm", "synthetic Framework inputs")
        name = "tasks/isolation.md"
        (root / name).parent.mkdir(exist_ok=True)
        (root / name).write_text(contract("isolation", ("file.txt",)))
        validator = MODULE.Validator(root, set(), cache=True, fresh=True)
        with (
            selected_task(root, name),
            ExitStack() as stack,
            redirect_stdout(io.StringIO()) as output,
        ):
            for method in ("stat", "open", "glob", "rglob", "iterdir"):
                original = getattr(Path, method)
                guarded = _bind_framework_callback(
                    _callback_check_guarded_45, root, original
                )
                stack.enter_context(patch.object(Path, method, guarded))
            assert validator.run() == 0, (validator.errors, output.getvalue())
            check_task_type_dispatch()
    print(
        "Framework input isolation: PASS (no Model/project access; consumer validation retained)"
    )


if __name__ == "__main__":
    check()
