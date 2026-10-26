#!/usr/bin/env python3
"""Create one evidence-backed Implement handoff from the current Deploy failure."""

import argparse
import json
import sys
from pathlib import Path

import worktree_task
from deploy import handoff
from task_contract_core import task_snapshot
from utils.sealed_evidence import evidence_store, write_sealed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--failure", type=Path, required=True)
    parser.add_argument("--diagnosis", type=Path, required=True)
    parser.add_argument("--path", action="append", required=True)
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    try:
        request = handoff.issue_request(
            root,
            args.failure,
            json.loads(args.diagnosis.read_text(encoding="utf-8")),
            args.path,
        )
        request_path = (
            evidence_store(root)
            / ("deploy-repair-" + request["requestId"])
            / "request.json"
        )
        request_path.parent.mkdir(mode=0o700)
        write_sealed(root, request_path, request)
        request = worktree_task.deploy_checkpoint(
            root, Path(task_snapshot(root).name).stem, request_path
        )
        print(json.dumps(request, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Deploy handoff: BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
