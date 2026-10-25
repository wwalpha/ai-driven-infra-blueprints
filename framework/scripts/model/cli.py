#!/usr/bin/env python3
"""Properties Model command entrypoint; no persistent PYTHONPATH configuration."""

import argparse
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from utils.input_cache import input_scope
from utils.script_loader import module


@input_scope
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["aws-compare"]:
        return module("model/adapters/aws.py", "model.adapters.aws").main(argv[1:])
    if argv[:1] == ["import"]:
        return module("model/importing/cli.py", "model.importing.cli").main(argv[1:])
    if argv[:1] == ["audit"]:
        return module("model/audit.py", "model.audit").main(argv[1:])
    if argv[:1] == ["observed"]:
        return module("model/adapters/observed.py", "model.adapters.observed").main(
            argv[1:]
        )
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "aws-compare",
        help="compare saved Model with AWS (requires explicit AWS authorization)",
    )
    commands.add_parser(
        "import", help="acquire/review/publish/recover one explicitly selected service"
    )
    commands.add_parser(
        "observed",
        help="inspect offline CloudFormation identifier mappings before observation retrieval",
    )
    commands.add_parser(
        "audit", help="generate a standalone AWS audit without executing AWS"
    )
    read = commands.add_parser("read")
    read.add_argument("model", type=Path)
    trace = commands.add_parser("trace")
    trace.add_argument("model", type=Path)
    trace.add_argument("key")
    edit = commands.add_parser(
        "edit", help="publish one ordinary properties candidate under the selected Task"
    )
    edit.add_argument("model", type=Path)
    edit.add_argument("--candidate", type=Path, required=True)
    edit.add_argument("--task-file", required=True)
    render = commands.add_parser("render")
    render.add_argument("model", type=Path)
    for name in ("resource", "find"):
        command = commands.add_parser(name)
        command.add_argument("model", type=Path)
        command.add_argument("selector")
    incoming = commands.add_parser("incoming")
    incoming.add_argument("model", type=Path)
    incoming.add_argument("resource")
    listing = commands.add_parser("list")
    listing.add_argument("--repository-root", type=Path, default=Path.cwd())
    indexing = commands.add_parser(
        "index",
        help="rebuild derived ownership/reference metadata offline; never deploy",
    )
    indexing.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    return module("model/cli_runtime.py", "model.cli_runtime").execute(args)


if __name__ == "__main__" and not __package__:
    raise SystemExit(main())
