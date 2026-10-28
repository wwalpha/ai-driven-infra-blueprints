"""Current Scan, Review detail and immutable snapshot publication."""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from comparison.deferral import CATEGORIES
from utils.json_format import strict_json

import issues.artifact as _imports_issues_artifact
import issues.publication as _imports_issues_publication
import issues.runner as _imports_issues_runner

from .aggregate import IAC_CLASSES
from .records import safe_text
from .review_progress import DEFAULT_MAX_BYTES, ReviewController

SELECTOR = "BLUEPRINT_TASK_FILE"


def outside(root, path):
    path = path.resolve()
    if path.is_relative_to(root):
        raise ValueError(
            "scan/review/diagnostics artifacts must be outside the repository"
        )
    return path


def main():
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
    for operation in ("init", "next", "submit", "status", "export"):
        command = reviewcommands.add_parser(operation)
        command.add_argument("--artifact", type=Path, required=True)
        command.add_argument("--state", type=Path, required=True)
        if operation == "next":
            command.add_argument("--limit", type=int, default=20)
            command.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
        elif operation == "submit":
            command.add_argument("--submission", type=Path, required=True)
        elif operation == "export":
            command.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    if args.task_file:
        os.environ[SELECTOR] = args.task_file
    try:
        if args.command == "review":
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
            else:
                output = controller.export(args.review)
            print(json.dumps(output, ensure_ascii=False, allow_nan=False))
            return 2 if output.get("blocked") else 0
        if args.command == "scan":
            review_payload = _imports_issues_artifact.review_payload
            scan_exit_code = _imports_issues_artifact.scan_exit_code
            scan = _imports_issues_runner.scan
            artifact_path = outside(root, args.artifact)
            artifact = scan(
                root,
                args.environment,
                args.target_directory,
                args.service,
                fresh=args.fresh,
                jobs=args.jobs,
            )
            artifact_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            output = review_payload(artifact, artifact_path)
            print(json.dumps(output, ensure_ascii=False))
            return scan_exit_code(artifact)
        if args.command == "detail":
            detail_payload = _imports_issues_artifact.detail_payload
            artifact = json.loads(
                outside(root, args.artifact).read_text(encoding="utf-8")
            )
            print(
                json.dumps(
                    detail_payload(
                        artifact,
                        args.section,
                        args.offset,
                        args.limit,
                        args.category,
                        args.issue_id,
                        args.record_category,
                    ),
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "save":
            has_processing_errors = _imports_issues_artifact.has_processing_errors
            summary = _imports_issues_artifact.summary
            save_scan = _imports_issues_publication.save_scan
            artifact = json.loads(
                outside(root, args.artifact).read_text(encoding="utf-8")
            )
            review = json.loads(outside(root, args.review).read_text(encoding="utf-8"))
            paths, snapshot, task_name = save_scan(root, artifact, review)
            artifact = json.loads(snapshot.data)
        saved_summary = summary(artifact)
        print(
            json.dumps(
                {
                    "publication_status": "SAVED",
                    "validation_status": saved_summary["validation_status"],
                    "saved": [path.relative_to(root).as_posix() for path in paths],
                    "summary": saved_summary,
                    "post_save_validation": "NOT_RUN",
                    "post_save_validation_command": (
                        "blueprint-loop.py --mode local --task-file "
                        + shlex.quote(task_name)
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 2 if args.command == "save" and has_processing_errors(artifact) else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Local issues: ERROR: " + safe_text(str(error)), file=sys.stderr)
        return 2
