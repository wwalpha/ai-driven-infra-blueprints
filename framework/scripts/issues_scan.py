#!/usr/bin/env python3
"""Local issues command compatibility entrypoint."""

import sys

from issues.cli import main

sys.dont_write_bytecode = True

if __name__ == "__main__":
    raise SystemExit(main())
