#!/usr/bin/env python3
"""Worktree command entry point."""

import sys
from importlib import import_module


def main():
    if sys.argv[1:2] == ["run"]:
        return import_module("worktree.worktree_runner").main(sys.argv[2:])
    return import_module("worktree.worktree_task").main()


if __name__ == "__main__":
    raise SystemExit(main())
