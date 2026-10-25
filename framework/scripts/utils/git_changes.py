"""Read Git working paths without changing the caller's Git environment."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

GitRunner = Callable[..., subprocess.CompletedProcess[str]]
PathReader = Callable[[list[str]], set[str]]


@dataclass(frozen=True)
class GitWorkingPaths:
    unstaged: frozenset[str]
    staged: frozenset[str]
    untracked: frozenset[str]

    @property
    def all_paths(self) -> frozenset[str]:
        return self.unstaged | self.staged | self.untracked


def run_readonly(
    root: Path, *args: str, runner: GitRunner | None = None
) -> subprocess.CompletedProcess[str]:
    options = {
        "diff": {"--cached", "--no-renames", "--name-only", "-z", "--diff-filter=U"},
        "ls-files": {"--cached", "--others", "--ignored", "--exclude-standard", "-z"},
    }
    if not args or args[0] not in options:
        raise ValueError("only read-only Git path commands are permitted")
    for argument in args[1:]:
        if argument == "--":
            break
        if argument.startswith("-") and argument not in options[args[0]]:
            raise ValueError(f"unsupported Git path option: {argument}")
    if runner is None:
        # Decode after capture so CR/LF characters inside filenames remain intact.
        captured = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, check=False
        )
        result = subprocess.CompletedProcess(
            captured.args,
            captured.returncode,
            captured.stdout.decode("utf-8"),
            captured.stderr.decode("utf-8"),
        )
    else:
        result = runner(root, *args)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def read_paths(root: Path, *args: str, runner: GitRunner | None = None) -> set[str]:
    return {
        path
        for path in run_readonly(root, *args, runner=runner).stdout.split("\0")
        if path
    }


def collect_working_paths(
    root: Path,
    *,
    runner: GitRunner | None = None,
    path_reader: PathReader | None = None,
) -> GitWorkingPaths:
    paths = [
        frozenset(
            path_reader(args)
            if path_reader is not None
            else read_paths(root, *args, runner=runner)
        )
        for args in (
            ["diff", "--no-renames", "--name-only", "-z"],
            ["diff", "--cached", "--no-renames", "--name-only", "-z"],
            ["ls-files", "--others", "--exclude-standard", "-z"],
        )
    ]
    return GitWorkingPaths(*paths)
