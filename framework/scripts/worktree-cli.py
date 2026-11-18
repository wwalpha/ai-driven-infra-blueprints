#!/usr/bin/env python3
"""Worktree command entry point."""

import sys


def main():
    if sys.argv[1:2] == ["run"]:
        from worktree.worktree_runner import main as run  # noqa: PLC0415

        return run(sys.argv[2:])
    from worktree.worktree_task import main as lifecycle  # noqa: PLC0415

    return lifecycle()


if __name__ == "__main__":
    raise SystemExit(main())
