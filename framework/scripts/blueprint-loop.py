#!/usr/bin/env python3
"""Compatibility CLI for the importable local-loop runner."""
from validation.loop import SELECTOR as SELECTOR
from validation.loop import Path as Path
from validation.loop import StartupDiagnostics as StartupDiagnostics
from validation.loop import active_scope as active_scope
from validation.loop import annotations as annotations
from validation.loop import argparse as argparse
from validation.loop import authorize_full_regression as authorize_full_regression
from validation.loop import changed_paths as changed_paths
from validation.loop import contextmanager as contextmanager
from validation.loop import contracts as contracts
from validation.loop import datetime as datetime
from validation.loop import definition_root as definition_root
from validation.loop import failure_reason as failure_reason
from validation.loop import framework_changed as framework_changed
from validation.loop import git as git
from validation.loop import index_tree as index_tree
from validation.loop import interrupt as interrupt
from validation.loop import json as json
from validation.loop import os as os
from validation.loop import run_commands as run_commands
from validation.loop import run_loop as run_loop
from validation.loop import select_checks as select_checks
from validation.loop import shutil as shutil
from validation.loop import signal as signal
from validation.loop import staged_snapshot as staged_snapshot
from validation.loop import subprocess as subprocess
from validation.loop import suspend as suspend
from validation.loop import suspend_selected as suspend_selected
from validation.loop import sys as sys
from validation.loop import task_path as task_path
from validation.loop import tempfile as tempfile
from validation.loop import time as time
from validation.loop import timezone as timezone
from validation.loop import traceback as traceback
from validation.loop import utf8_environment as utf8_environment
from validation.loop import utf8_preflight as utf8_preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("task", "full", "local"), required=True,
                        help="task/local: active-scope validation; full: also all unit regression tests")
    parser.add_argument("--all", action="store_true", help="Explicit whole-repository validation and all unit regression tests")
    parser.add_argument("--task-file", help="Selected tasks/<task-name>.md contract")
    parser.add_argument("--log-dir", type=Path, help="Parent directory for run logs (outside the repository; default: OS temporary directory)")
    parser.add_argument("--profile", action="store_true", help="Profile model_design/design_catalog checks into the run directory")
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2, help="Independent regression workers (default: 2)")
    parser.add_argument("--validation-jobs", type=int, choices=(1, 2, 4), default=4,
                        help="Service validation workers (default: 4)")
    parser.add_argument("--fresh", action="store_true", help="Revalidate catalog/services without successful-result reuse")
    parser.add_argument("--write", action="store_true", help="Generate and validate selected Models before remaining checks")
    parser.add_argument("--staged", action="store_true", help="Validate a fixed staged tree in a private repository")
    parser.add_argument("--base", help="Explicit comparison commit for --staged (including incoming changes)")
    parser.add_argument("--affected", action="store_true", help="Select affected checks (task/local default); unknown dependencies stop")
    args = parser.parse_args()
    if args.staged and args.write:
        parser.error('--staged cannot be combined with --write')
    if args.staged != bool(args.base):
        parser.error('--staged and --base must be specified together')
    if args.affected and (args.mode == 'full' or args.all):
        parser.error('--affected cannot narrow full/--all validation')
    return run_loop(Path.cwd().resolve(), args)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, interrupt)
    # UTF-8 mode must be set before Python initializes file/subprocess defaults.
    if not sys.flags.utf8_mode:
        command = [sys.executable, "-X", "utf8", *sys.argv]
        if sys.platform == "win32":
            # Wait on Windows so the caller receives the restarted loop's failure code.
            raise SystemExit(subprocess.call(command, env=utf8_environment()))
        os.execvpe(sys.executable, command, utf8_environment())
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
