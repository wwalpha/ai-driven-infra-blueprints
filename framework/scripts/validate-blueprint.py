#!/usr/bin/env python3
"""CLI for the validation runner."""

import argparse
import cProfile
import os
import pstats
import sys
from pathlib import Path

import validation.runner as _runner
from task_contract_core import SELECTOR


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
        "--model-validation",
        choices=("change", "full"),
        help="Select independent full Model checks or Task changes",
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
        print(
            f"Blueprint repository validation: FAIL\n- check_id=validation.input; scope={root}; reason=repository root is invalid",
            file=sys.stderr,
        )
        return 1
    try:
        if directory := os.environ.get("BLUEPRINT_PROFILE_DIR"):
            profile = cProfile.Profile()
            try:
                validator = profile.runcall(_runner.run_validation, root, args)
            finally:
                profile.dump_stats(str(Path(directory) / "validate-blueprint.prof"))
                pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(
                    25
                )
        else:
            validator = _runner.run_validation(root, args)
        return validator.display_report()
    except (Exception, KeyboardInterrupt) as error:
        print(
            f"Blueprint repository validation: FAIL\n- check_id=validation.input; scope={args.task_file or root}; reason={type(error).__name__}: {error or 'validation interrupted'}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
