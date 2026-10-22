#!/usr/bin/env python3
"""Run Python arguments, or --command <CLI> arguments, with this worktree's registered Python."""

import os
from pathlib import Path
import subprocess
import sys
import worktree_python


def main():
    try:
        root = Path(__file__).resolve().parents[2]
        args = sys.argv[1:]
        if args[:1] == ["--repository-root"]:
            if len(args) < 2:
                raise ValueError("--repository-root requires a Project directory")
            root = Path(args[1]).resolve()
            args = args[2:]
        selected = worktree_python.runtime(root)
        interpreter, env = selected or (Path(sys.executable), os.environ.copy())
        if sys.dont_write_bytecode:
            env["PYTHONDONTWRITEBYTECODE"] = "1"
        if args[:1] == ["--command"]:
            command = args[1:]
            if not command:
                raise ValueError("--command requires a CLI")
        else:
            command = [str(interpreter), *args]
        if sys.platform == "win32":
            # Windows exec starts another process and exits before its result is available.
            return subprocess.call(command, env=env)
        os.execvpe(command[0], command, env)
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
