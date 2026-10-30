"""Task transition CLI."""

import argparse
import json
from pathlib import Path

import task_contract_core as _core
from utils.script_loader import module


def refresh(root, name, resuming=False):
    return module("task_contract_runtime.py", "task_contract_runtime").refresh(
        root, name, resuming=resuming
    )


def complete(root, name):
    return module("task_contract_runtime.py", "task_contract_runtime").complete(
        root, name
    )


def check_resume_scope(root, name):
    return module(
        "task_contract_runtime.py", "task_contract_runtime"
    ).check_resume_scope(root, name)


def approve_out_of_task_failures(root, name, records):
    return module(
        "task_contract_runtime.py", "task_contract_runtime"
    ).approve_out_of_task_failures(root, name, records)


def resume(root, name):
    return module("task_contract_runtime.py", "task_contract_runtime").resume(
        root, name
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().resolve())
    parser.add_argument("--task-file", required=True)
    parser.add_argument(
        "--source",
        type=Path,
        help="Register a new contract from a file outside the repository",
    )
    transition = parser.add_mutually_exclusive_group()
    transition.add_argument(
        "--suspend-reason", help="Suspend only this task and record the problem"
    )
    transition.add_argument("--resume", action="store_true", help="Resume this task")
    transition.add_argument(
        "--check-resume-scope",
        action="store_true",
        help="Read-only suspended Task scope preflight",
    )
    transition.add_argument(
        "--complete",
        action="store_true",
        help="Complete after successful required validation",
    )
    transition.add_argument(
        "--approve-out-of-task-failures",
        type=Path,
        help="Record explicit Human approval of exact evidenced Model FAILs for this Task only",
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    try:
        if args.source and (
            args.suspend_reason is not None
            or args.resume
            or args.complete
            or args.check_resume_scope
            or args.approve_out_of_task_failures
        ):
            raise ValueError("--source cannot be combined with a status transition")
        if args.suspend_reason is not None:
            changed = _core.suspend(root, args.task_file, args.suspend_reason)
            print(
                f"Task contract: {args.task_file} ({'suspend' if changed else 'status unchanged'})"
            )
            return 0
        if args.approve_out_of_task_failures:
            approve_out_of_task_failures(
                root,
                args.task_file,
                json.loads(
                    args.approve_out_of_task_failures.read_text(encoding="utf-8")
                ),
            )
        elif args.check_resume_scope:
            check_resume_scope(root, args.task_file)
        elif args.resume:
            resume(root, args.task_file)
        elif args.complete:
            complete(root, args.task_file)
        if args.source:
            if args.source.resolve().is_relative_to(root):
                raise ValueError("new contract source must be outside the repository")
            _core.start(root, args.task_file, args.source.read_text(encoding="utf-8"))
        elif (
            not args.resume
            and not args.complete
            and not args.check_resume_scope
            and not args.approve_out_of_task_failures
        ):
            refresh(root, args.task_file)
        selected = (
            _core.contract_path(root, args.task_file)
            if args.check_resume_scope or args.approve_out_of_task_failures
            else _core.task_path(root, args.task_file)
        )
        print(f"Task contract: {selected.relative_to(root)}")
    except (OSError, ValueError) as error:
        print(f"Task contract: BLOCKED ({error})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
