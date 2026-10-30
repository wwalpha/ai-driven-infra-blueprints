"""Current Scan, Review detail and immutable snapshot publication."""

import argparse
import json
import os
import sys
from pathlib import Path

from utils.comparison_contract import CATEGORIES
from utils.json_format import strict_json

from .aggregate import IAC_CLASSES
from .records import safe_text
from .review_progress import DEFAULT_MAX_BYTES, SECTIONS, ReviewController

SELECTOR = "BLUEPRINT_TASK_FILE"


def outside(root, path):
    path = path.resolve()
    if path.is_relative_to(root):
        raise ValueError(
            "scan/review/diagnostics artifacts must be outside the repository"
        )
    return path


def parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().resolve())
    parser.add_argument("--task-file")
    commands = parser.add_subparsers(dest="command", required=True)
    scanparser = commands.add_parser("scan")
    scanparser.add_argument("--environment", required=True)
    scanparser.add_argument("--target-directory", required=True)
    scanparser.add_argument("--service", action="append", required=True)
    scanparser.add_argument("--artifact", type=Path, required=True)
    scanparser.add_argument("--fresh", action="store_true")
    scanparser.add_argument("--jobs", type=int, choices=(1, 2, 4), default=4)
    detail = commands.add_parser("detail")
    detail.add_argument("--artifact", type=Path, required=True)
    detail.add_argument(
        "--section",
        choices=(
            "ordinary",
            "naming",
            "judgments",
            "human_confirmations",
            "iac",
            "iac_issues",
            "machine_diagnostics",
            "warnings",
            "information",
            "unverified",
            "processing_errors",
            "naming_context",
            "cfn_lint",
            "lint_coverage",
            "check_results",
        ),
        required=True,
    )
    detail.add_argument("--offset", type=int, default=0)
    detail.add_argument("--limit", type=int, default=50)
    detail.add_argument(
        "--category",
        choices=IAC_CLASSES,
        help="IaC classification filter; applied before pagination",
    )
    detail.add_argument(
        "--record-category",
        choices=CATEGORIES,
        help="comparison record filter for section iac; cannot combine with Issue filters",
    )
    detail.add_argument(
        "--issue-id",
        help="stable ISSUE-<id>; retrieve members from this artifact without comparison",
    )
    saveparser = commands.add_parser("save")
    saveparser.add_argument("--artifact", type=Path, required=True)
    saveparser.add_argument("--review", type=Path, required=True)
    reviewparser = commands.add_parser("review", help="checkpointed complete Review")
    reviewcommands = reviewparser.add_subparsers(dest="review_command", required=True)
    for operation in (
        "init",
        "next",
        "submit",
        "status",
        "inspect",
        "revise",
        "export",
    ):
        command = reviewcommands.add_parser(operation)
        command.add_argument("--artifact", type=Path, required=True)
        command.add_argument("--state", type=Path, required=True)
        if operation == "next":
            command.add_argument("--limit", type=int, default=20)
            command.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
        elif operation == "submit":
            command.add_argument("--submission", type=Path, required=True)
        elif operation == "inspect":
            command.add_argument("--section", choices=SECTIONS, required=True)
            command.add_argument("--id", required=True)
        elif operation == "revise":
            command.add_argument("--revision", type=Path, required=True)
        elif operation == "export":
            command.add_argument("--review", type=Path, required=True)
    return parser


def run_review(args, root):
    controller = ReviewController(root, args.artifact, args.state)
    if args.review_command == "init":
        output = controller.initialize()
    elif args.review_command == "status":
        output = controller.status()
    elif args.review_command == "next":
        output = controller.next_batch(args.limit, args.max_bytes)
    elif args.review_command == "submit":
        submission = strict_json(outside(root, args.submission).read_bytes())
        output = controller.submit(submission)
    elif args.review_command == "inspect":
        output = controller.inspect(args.section, args.id)
    elif args.review_command == "revise":
        revision = strict_json(outside(root, args.revision).read_bytes())
        output = controller.revise(revision)
    else:
        output = controller.export(args.review)
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    return 2 if output.get("blocked") else 0


def main():
    args = parser().parse_args()
    root = args.repository_root.resolve()
    if args.task_file:
        os.environ[SELECTOR] = args.task_file
    try:
        return run_review(args, root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Local issues: ERROR: " + safe_text(str(error)), file=sys.stderr)
        return 2
