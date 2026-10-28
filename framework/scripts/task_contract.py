"""Task transition CLI and compatibility exports for the read-only Task core."""

import argparse as argparse
import json
from functools import wraps as wraps

from task_contract_core import SELECTOR as SELECTOR
from task_contract_core import TASK_NAME as TASK_NAME
from task_contract_core import ContextVar as ContextVar
from task_contract_core import DependencyDetach as DependencyDetach
from task_contract_core import FunctionWrapper as FunctionWrapper
from task_contract_core import MergePair as MergePair
from task_contract_core import ModelOperation as ModelOperation
from task_contract_core import Path as Path
from task_contract_core import PurePosixPath as PurePosixPath
from task_contract_core import ReferenceChange as ReferenceChange
from task_contract_core import TaskSnapshot as TaskSnapshot
from task_contract_core import _bind_framework_callback as _bind_framework_callback
from task_contract_core import (
    _callback_model_operation_field as _callback_model_operation_field,
)
from task_contract_core import (
    _callback_model_operation_objects as _callback_model_operation_objects,
)
from task_contract_core import _contracts as _contracts
from task_contract_core import _imports_utils_json_format as _imports_utils_json_format
from task_contract_core import (
    _invoke_contract_read_scope as _invoke_contract_read_scope,
)
from task_contract_core import _model_operation_address as _model_operation_address
from task_contract_core import _paths_in as _paths_in
from task_contract_core import _read_contracts as _read_contracts
from task_contract_core import _section as _section
from task_contract_core import _select_contract as _select_contract
from task_contract_core import _selected_contract as _selected_contract
from task_contract_core import _selected_tasks as _selected_tasks
from task_contract_core import active_scope as active_scope
from task_contract_core import atomic_files as atomic_files
from task_contract_core import contextmanager as contextmanager
from task_contract_core import contract_path as contract_path
from task_contract_core import contract_read_scope as contract_read_scope
from task_contract_core import contract_reads as contract_reads
from task_contract_core import contract_snapshot as contract_snapshot
from task_contract_core import contracts as contracts
from task_contract_core import dataclass as dataclass
from task_contract_core import digest_files as digest_files
from task_contract_core import final_model_task as final_model_task
from task_contract_core import fnmatch as fnmatch
from task_contract_core import input_bytes as input_bytes
from task_contract_core import input_is_dir as input_is_dir
from task_contract_core import input_is_file as input_is_file
from task_contract_core import input_is_symlink as input_is_symlink
from task_contract_core import input_select as input_select
from task_contract_core import input_text as input_text
from task_contract_core import issues_save_only as issues_save_only
from task_contract_core import matches as matches
from task_contract_core import memoized as memoized
from task_contract_core import model_operation as model_operation
from task_contract_core import model_refactor as model_refactor
from task_contract_core import os as os
from task_contract_core import paths_in as paths_in
from task_contract_core import re as re
from task_contract_core import read_task_snapshot as read_task_snapshot
from task_contract_core import recording_inputs as recording_inputs
from task_contract_core import replace as replace
from task_contract_core import resource_address as resource_address
from task_contract_core import safe_path as safe_path
from task_contract_core import section as section
from task_contract_core import selected_task as selected_task
from task_contract_core import selected_text as selected_text
from task_contract_core import set_status as set_status
from task_contract_core import start as start
from task_contract_core import status as status
from task_contract_core import suspend as suspend
from task_contract_core import task_path as task_path
from task_contract_core import task_read_scope as task_read_scope
from task_contract_core import task_reads as task_reads
from task_contract_core import task_revision as task_revision
from task_contract_core import task_snapshot as task_snapshot
from task_contract_core import validate_contract as validate_contract
from task_contract_core import verify_contract_reads as verify_contract_reads
from task_contract_core import verify_snapshot as verify_snapshot
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
            changed = suspend(root, args.task_file, args.suspend_reason)
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
            start(root, args.task_file, args.source.read_text(encoding="utf-8"))
        elif (
            not args.resume
            and not args.complete
            and not args.check_resume_scope
            and not args.approve_out_of_task_failures
        ):
            refresh(root, args.task_file)
        selected = (
            contract_path(root, args.task_file)
            if args.check_resume_scope or args.approve_out_of_task_failures
            else task_path(root, args.task_file)
        )
        print(f"Task contract: {selected.relative_to(root)}")
    except (OSError, ValueError) as error:
        print(f"Task contract: BLOCKED ({error})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
