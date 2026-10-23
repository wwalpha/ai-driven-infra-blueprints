#!/usr/bin/env python3
"""Local issues command compatibility entrypoint."""
import sys
sys.dont_write_bytecode = True
from issues.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
