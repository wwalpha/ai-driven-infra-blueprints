#!/usr/bin/env python3
"""Compatibility CLI for the importable validation runner."""

import cProfile as _imports_cProfile
import pstats as _imports_pstats

import validation.runner as _exports_validation_runner
from validation.runner import (
    CODEX_PROMPT_FILENAME_PATTERN as CODEX_PROMPT_FILENAME_PATTERN,
)
from validation.runner import REQUIRED_NAME_PROPERTIES as REQUIRED_NAME_PROPERTIES
from validation.runner import STACK_DESIGN as STACK_DESIGN
from validation.runner import TABLE_ALIGNMENT as TABLE_ALIGNMENT
from validation.runner import TABLE_HEADER as TABLE_HEADER
from validation.runner import DesignIndex as DesignIndex
from validation.runner import DesignSchemaCatalog as DesignSchemaCatalog
from validation.runner import Findings as Findings
from validation.runner import PassCache as PassCache
from validation.runner import ThreadPoolExecutor as ThreadPoolExecutor
from validation.runner import Validator as Validator
from validation.runner import active_scope as active_scope
from validation.runner import annotations as annotations
from validation.runner import artifact_id as artifact_id
from validation.runner import cloudformation as cloudformation
from validation.runner import contract_reads as contract_reads
from validation.runner import design as design
from validation.runner import design_links as design_links
from validation.runner import design_tables as design_tables
from validation.runner import framework_contracts as framework_contracts
from validation.runner import iac as iac
from validation.runner import input_is_file as input_is_file
from validation.runner import input_scope as input_scope
from validation.runner import owned_field as owned_field
from validation.runner import project as project
from validation.runner import properties as properties
from validation.runner import recording_inputs as recording_inputs
from validation.runner import rendered_policy_design as rendered_policy_design
from validation.runner import run_validation as run_validation
from validation.runner import scenario as scenario
from validation.runner import scoped_files as scoped_files
from validation.runner import subprocess as subprocess
from validation.runner import terraform as terraform
from validation.runner import verify_contract_reads as verify_contract_reads
from validation.task import TaskValidation as TaskValidation

# Preserve shared fixtures and compatibility exports under their historical names.
Path = _exports_validation_runner.Path
SELECTOR = _exports_validation_runner.SELECTOR
argparse = _exports_validation_runner.argparse
os = _exports_validation_runner.os
sys = _exports_validation_runner.sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--task-file", help="Selected tasks/<task-name>.md contract")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Generate, validate and publish selected service views",
    )
    parser.add_argument(
        "--all", action="store_true", help="Explicit repository-wide validation"
    )
    parser.add_argument(
        "--repository-wide-iac",
        action="store_true",
        help="Retain whole-IaC checks for full/framework regression",
    )
    parser.add_argument(
        "--contract-scope",
        action="store_true",
        help="Also enforce the active generation scope while validating all services",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Revalidate instead of reusing successful content-addressed checks",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        choices=(1, 2, 4),
        default=4,
        help="Service validation workers",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.task_file:
        os.environ[SELECTOR] = args.task_file
    root = args.repository_root.resolve()
    if not (root / ".git").exists():
        print(f"repository root is invalid: {root}", file=sys.stderr)
        return 2
    try:
        if directory := os.environ.get("BLUEPRINT_PROFILE_DIR"):
            cProfile = _imports_cProfile
            pstats = _imports_pstats
            profile = cProfile.Profile()
            try:
                validator = profile.runcall(run_validation, root, args)
            finally:
                profile.dump_stats(str(Path(directory) / "validate-blueprint.prof"))
                pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(
                    25
                )
        else:
            validator = run_validation(root, args)
        return validator.display_report()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Blueprint repository validation: FAIL\n- {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
