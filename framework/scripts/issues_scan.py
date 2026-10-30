#!/usr/bin/env python3
"""Local issues command compatibility entrypoint."""

import argparse
import sys

selector = argparse.ArgumentParser(add_help=False)
selector.add_argument("--repository-root")
selector.add_argument("--task-file")
selector.add_argument("command", nargs="?")
selected, _ = selector.parse_known_args()
if selected.command == "review":
    from issues.review_cli import main
else:
    from issues.cli import main

sys.dont_write_bytecode = True

if __name__ == "__main__":
    raise SystemExit(main())
