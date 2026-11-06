#!/usr/bin/env python3
"""Create one evidence-backed Implement handoff from the current Deploy failure."""

import argparse
import json
import sys
from pathlib import Path

from deploy import cli_guidance, handoff, operation_journal
from deploy import progress as deploy_progress
from utils.local_evidence import evidence_store, read_sealed, write_sealed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=cli_guidance.HANDOFF_HELP,
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--failure", type=Path, required=True)
    parser.add_argument("--discard-failure", action="store_true")
    parser.add_argument("--diagnosis", type=Path)
    parser.add_argument("--path", action="append")
    args = parser.parse_args(argv)
    if args.discard_failure:
        if args.diagnosis or args.path:
            parser.error("--discard-failure cannot issue a repair request")
    elif not args.diagnosis or not args.path:
        parser.error("request creation requires --diagnosis and --path")
    root = args.repository_root.resolve()
    try:
        if args.discard_failure:
            handoff.discard_failure(root, args.failure)
            print(
                json.dumps(
                    {
                        "discardedFailure": str(args.failure),
                        **cli_guidance.handoff_result(discarded=True),
                    }
                )
            )
            return 0
        failure = read_sealed(root, handoff.external(root, args.failure))
        with (
            operation_journal.locked(deploy_progress.progress_path(root, failure["taskFile"], create=True)),
            handoff.repair_lock(root),
        ):
            request = handoff.issue_request(
                root,
                args.failure,
                json.loads(args.diagnosis.read_text(encoding="utf-8")),
                args.path,
            )
            if request["target"] != failure["target"]:
                raise handoff.Blocked("failure target changed before handoff")
            request_path = (
                evidence_store(root)
                / ("deploy-repair-" + request["requestId"])
                / "request.json"
            )
            request_path.parent.mkdir(mode=0o700)
            write_sealed(root, request_path, request)
        print(
            json.dumps(
                {
                    **request,
                    "requestPath": str(request_path),
                    **cli_guidance.handoff_result(request),
                },
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(
            json.dumps(
                {"result": "STOPPED", **cli_guidance.stopped("HANDOFF", error)},
                indent=2,
            )
        )
        print(f"Deploy handoff: BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
