"""Validation-backed Task transitions, separate from the standard-library facade."""

import argparse as argparse
from functools import wraps as wraps

import import_guard as _imports_import_guard
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
from task_contract_core import invalidate_task_reads
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
from validation import acceptance
from validation.findings import Findings
from validation.runner import Validator
from validation.task import TaskValidation


def refresh(root, name, resuming=False):
    snapshot = task_snapshot(root, name, executable=False, live=True)
    text = snapshot.text
    state = status(text)
    if state == "suspend" and not resuming:
        raise ValueError("suspend task cannot execute; use --resume")
    if state == "completed":
        if resuming:
            raise ValueError("completed task cannot resume")
        validate_contract(root, name, text)
        return
    text = set_status(text, "running")
    validate_contract(root, name, text)
    if text != snapshot.text:
        verify_snapshot(snapshot)
        atomic_files({safe_path(root, name): text}, staging_directory=root)
        invalidate_task_reads(root)


def complete(root, name):
    snapshot = task_snapshot(root, name, executable=False, live=True)
    text = snapshot.text
    with task_reads(root, snapshot=snapshot):
        if status(text) != "running":
            raise ValueError("only a running task can complete")
        require_import_changes = _imports_import_guard.require_import_changes
        previous = os.environ.get(SELECTOR)
        try:
            os.environ[SELECTOR] = name
            if issues_save_only(root, text=text):
                require_import_changes(root, set())
            else:
                require_import_changes(root)
            validator = Validator(
                root,
                set(snapshot.scope) if snapshot.scope is not None else None,
                cache=False,
                issues_save=issues_save_only(root, text=text),
                model_validation="change",
            )
            validator.run()
            if validator.report():
                raise ValueError(
                    "Task Acceptance FAIL: "
                    + "; ".join(
                        item["reason"] for item in validator.findings.failures()
                    )
                )
        finally:
            if previous is None:
                os.environ.pop(SELECTOR, None)
            else:
                os.environ[SELECTOR] = previous
    verify_snapshot(snapshot)
    atomic_files(
        {safe_path(root, name): set_status(text, "completed")}, staging_directory=root
    )
    invalidate_task_reads(root)


def approve_out_of_task_failures(root, name, records):
    with selected_task(root, name), task_reads(root, live=True):
        acceptance.approve(
            TaskValidation(root, Findings(root), contract_file=name), records
        )


def check_resume_scope(root, name):
    with selected_task(root, name), task_reads(root, live=True):
        snapshot = task_snapshot(root, name, executable=False)
        if snapshot.status != "suspend":
            raise ValueError("scope preflight requires a suspended task")
        _ = snapshot.scope  # Validate the declared scope without running it.
        findings = Findings(root)
        TaskValidation(root, findings, contract_file=name).check_task_scope()
        if findings.errors:
            raise ValueError("scope preflight failed: " + "; ".join(findings.errors))
        verify_snapshot(snapshot)


def resume(root, name):
    snapshot = task_snapshot(root, name, executable=False, live=True)
    if snapshot.status == "suspend":
        check_resume_scope(root, name)
        verify_snapshot(snapshot)
    refresh(root, name, resuming=True)
