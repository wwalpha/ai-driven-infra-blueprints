"""Current Scan, Review detail and immutable snapshot publication."""

import json
import os
import shlex
import sys

from utils.input_cache import input_context

import issues.artifact as _imports_issues_artifact
import issues.publication as _imports_issues_publication
import issues.runner as _imports_issues_runner

from .reader import read_review_json, read_scan_artifact
from .records import safe_text
from .review_cli import SELECTOR, outside, parser, run_review


def main():
    args = parser().parse_args()
    root = args.repository_root.resolve()
    if args.task_file:
        os.environ[SELECTOR] = args.task_file
    try:
        if args.command == "review":
            return run_review(args, root)
        if args.command == "scan":
            review_payload = _imports_issues_artifact.review_payload
            scan_exit_code = _imports_issues_artifact.scan_exit_code
            scan = _imports_issues_runner.scan
            artifact_path = outside(root, args.artifact)
            with input_context():
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
            artifact = read_scan_artifact(outside(root, args.artifact)).artifact
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
            loaded = read_scan_artifact(outside(root, args.artifact))
            review = read_review_json(outside(root, args.review))
            paths, snapshot, task_name = save_scan(root, loaded, review)
            artifact = json.loads(snapshot.data)
        saved_summary = summary(artifact)
        print(
            json.dumps(
                {
                    "publication_status": "SAVED",
                    "validation_status": saved_summary["validation_status"],
                    "saved": [path.relative_to(root).as_posix() for path in paths],
                    "summary": saved_summary,
                    "post_save_validation_execution": "NOT_STARTED",
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
