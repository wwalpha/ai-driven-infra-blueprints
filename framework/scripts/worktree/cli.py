#!/usr/bin/env python3
"""Worktree lifecycle command entry point."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worktree.worktree_task import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
