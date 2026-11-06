"""Read shared worktree identity and lifecycle state without Python setup dependencies."""

import json
import os
import re
import subprocess
from pathlib import Path

from utils.git_changes import collect_working_paths, read_paths


class Blocked(ValueError):
    pass


class NeedsSync(Exception):
    """The base advanced; the caller must synchronize and reassess validation."""

    def __init__(self, base):
        self.base = base
        super().__init__("base advanced; synchronize and reassess validation")


def git(root, *args, check=True, timeout=None):
    # Never route commands through an inherited worktree/private index or prompt.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(
        GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true", GIT_SEQUENCE_EDITOR="true", LC_ALL="C"
    )
    result = subprocess.run(
        ["git", *map(str, args)],
        cwd=root,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if check and result.returncode:
        raise Blocked(
            f"git {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def output(root, *args, runner=None):
    runner = runner or git
    return runner(root, *args).stdout.strip()


def _repository_identity(where: Path) -> tuple[Path, Path]:
    values = output(
        where,
        "rev-parse",
        "--show-toplevel",
        "--is-bare-repository",
        "--path-format=absolute",
        "--git-common-dir",
    ).splitlines()
    # A newline in a path makes the batched output ambiguous.
    if len(values) != 3:
        values = [
            output(where, "rev-parse", "--show-toplevel"),
            output(where, "rev-parse", "--is-bare-repository"),
            output(where, "rev-parse", "--path-format=absolute", "--git-common-dir"),
        ]
    root, bare, common = values
    root = Path(root).resolve()
    if bare != "false":
        raise Blocked("a non-bare Git repository is required")
    return root, Path(common).resolve()


def repository(where: Path) -> tuple[Path, Path, Path]:
    root, common = _repository_identity(where)
    git_dir = Path(output(root, "rev-parse", "--absolute-git-dir")).resolve()
    if git_dir == common:
        return root, common, root
    if common.name != ".git" or not common.parent.is_dir():
        raise Blocked("cannot identify the primary checkout from the Git common directory")
    primary, primary_common = _repository_identity(common.parent)
    if primary != common.parent or primary_common != common:
        raise Blocked("Git common directory does not identify a primary checkout")
    return root, common, primary


def metadata_directory(primary):
    directory = primary / ".worktrees" / ".blueprint"
    for path in (directory.parent, directory, directory / "tasks"):
        if path.is_symlink():
            raise Blocked(f"worktree metadata must not use symlinks: {path}")
    return directory


def state_path(primary, task_id):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", task_id):
        raise Blocked("task-id must use the existing lower-kebab-case task naming rule")
    return metadata_directory(primary) / "tasks" / f"{task_id}.json"


def load(where, task_id):
    root, common, primary = repository(where)
    return _load(primary, common, task_id)


def load_candidate(where, state):
    root, common = _repository_identity(where)
    primary, primary_common = (
        (root, common)
        if Path(where) == Path(state["primary"])
        else _repository_identity(Path(state["primary"]))
    )
    if primary_common != common or primary != Path(state["primary"]):
        raise Blocked("task worktree belongs to another repository")
    return _load(primary, common, state["task_id"])


def _load(primary: Path, common: Path, task_id: str) -> tuple[Path, Path, Path, dict]:
    path = state_path(primary, task_id)
    if path.is_symlink() or not path.is_file():
        raise Blocked(f"task lifecycle state must be an owned regular file: {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if (
        state["task_id"] != task_id
        or state["branch"] != f"codex/worktree/{task_id}"
        or state["task_file"] != f"tasks/{task_id}.md"
        or state.get("base") == state["branch"]
        or state["primary"] != str(primary)
        or Path(state["worktree"]) != primary / ".worktrees" / task_id
    ):
        raise Blocked("task lifecycle state does not match this repository")
    # Cleanup can remove the caller's checkout; control Git from a surviving root.
    return primary, common, path, state


def paths(root, *args, runner=None):
    return read_paths(root, *args, runner=runner or git)


def task_start_commit(root, task_file):
    """Return the recorded Task diff boundary, independent of the current base."""
    _, _, primary = repository(root)
    path = state_path(primary, Path(task_file).stem)
    managed = root.resolve().parent == primary / ".worktrees"
    if not path.exists():
        if managed:
            raise Blocked("managed worktree task lifecycle state missing")
        return None
    _, _, _, state = load(root, Path(task_file).stem)
    if Path(state["worktree"]).resolve() != root.resolve():
        if managed:
            raise Blocked("selected task lifecycle belongs to another worktree")
        return None
    if state["task_file"] != task_file:
        raise Blocked("selected task does not match managed task_file")
    task_worktree(root, state)
    return _task_history(root, task_file, state, merge_base=True)


def _task_history(root, task_file, state, *, merge_base):
    boundary = state.get("validation_base", state["start"])
    if state.get("integrationMode") == "pr":
        boundary = state.get("prUpdate", {}).get(
            "syncBase", state.get("prPublication", {}).get("baseCommit", boundary)
        )
    start = output(root, "rev-parse", "--verify", boundary + "^{commit}")
    if git(root, "merge-base", "--is-ancestor", start, "HEAD", check=False).returncode:
        raise Blocked("task lifecycle start is not an ancestor of HEAD")
    return start


def committed_task_paths(root, task_file):
    """Committed Task changes relative to its recorded boundary, including all paths."""
    start = task_start_commit(root, task_file)
    return (
        None
        if start is None
        else paths(root, "diff", "--no-renames", "--name-only", "-z", start, "HEAD")
    )


def deploy_start_commit(root, task_file, *, required=False, allow_merged=False):
    """Deploy pins its own history; the publication branch is not an AWS input."""
    verified = deploy_task_state(
        root, task_file, required=required, allow_merged=allow_merged
    )
    return verified[0] if verified is not None else None


def deploy_task_state(
    root: Path, task_file: str, *, required: bool = False, allow_merged: bool = False
) -> tuple[str, dict] | None:
    """Read ownership and fixed history once for this authorization operation only."""
    _, common, primary = repository(root)
    path = state_path(primary, Path(task_file).stem)
    managed = root.resolve().parent == primary / ".worktrees"
    if not path.exists():
        if required or managed:
            raise Blocked("Deploy requires its registered managed worktree")
        return None
    state = _load(primary, common, Path(task_file).stem)[3]
    if Path(state["worktree"]) != root.resolve():
        if required or managed:
            raise Blocked("Deploy Task belongs to another managed worktree")
        return None
    if (
        state["task_file"] != task_file
        or state["merged"] is not None
        and not allow_merged
    ):
        raise Blocked("Deploy Task lifecycle is mismatched or already merged")
    task_worktree(root, state)
    start = output(root, "rev-parse", "--verify", state["start"] + "^{commit}")
    head = output(root, "rev-parse", "HEAD")
    if head != state["tip"]:
        raise Blocked("unexpected Deploy worktree HEAD; retain snapshot for review")
    if git(root, "merge-base", "--is-ancestor", start, head, check=False).returncode:
        raise Blocked("Deploy snapshot start is not an ancestor of its HEAD")
    return start, state


def idle_operations(root, *, runner=None):
    names = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
    )
    arguments = [argument for name in names for argument in ("--git-path", name)]
    resolved = output(
        root, "rev-parse", "--path-format=absolute", *arguments, runner=runner
    ).splitlines()
    # Newlines in a Git directory make the batched output ambiguous.
    if len(resolved) != len(names):
        resolved = [
            output(
                root,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                name,
                runner=runner,
            )
            for name in names
        ]
    for name, value in zip(names, resolved, strict=False):
        path = Path(value)
        if path.exists():
            raise Blocked(f"unfinished Git operation: {name}; worktree retained")


def idle_git(root, *, runner=None):
    idle_operations(root, runner=runner)
    if paths(root, "diff", "--name-only", "--diff-filter=U", "-z", runner=runner):
        raise Blocked("unresolved index conflicts; worktree retained")


def changed_paths(root):
    return set(collect_working_paths(root, runner=git).all_paths)


def task_git_directory(common, target):
    """Verify both pointers of the exact checkout's Git registration."""
    gitfile = target / ".git"
    admin = common / "worktrees"
    if (
        target.is_symlink()
        or target.parent.is_symlink()
        or gitfile.is_symlink()
        or not gitfile.is_file()
        or admin.is_symlink()
    ):
        raise Blocked("task worktree Git registration is missing or redirected")
    pointer = gitfile.read_text(encoding="utf-8").removesuffix("\n")
    if not pointer.startswith("gitdir: "):
        raise Blocked("task worktree has an invalid Git pointer")
    directory = target / pointer.removeprefix("gitdir: ")
    if (
        directory.resolve().parent != admin
        or directory.is_symlink()
        or not directory.is_dir()
    ):
        raise Blocked("task worktree belongs to another repository")
    directory = directory.resolve()
    backlink = directory / "gitdir"
    locked = directory / "locked"
    if (
        backlink.is_symlink()
        or not backlink.is_file()
        or (directory / backlink.read_text(encoding="utf-8").removesuffix("\n")).resolve()
        != gitfile
        or locked.exists()
        or locked.is_symlink()
    ):
        raise Blocked("task worktree Git registration is locked or mismatched")
    return directory


def task_worktree(root, state):
    target = Path(state["worktree"])
    _, common = _repository_identity(root)
    directory = task_git_directory(common, target)
    target_root, target_common = _repository_identity(target)
    ref = f"refs/heads/{state['branch']}"
    if (
        target_root != target
        or target_common != common
        or Path(output(target, "rev-parse", "--absolute-git-dir")).resolve() != directory
        or output(target, "symbolic-ref", "HEAD") != ref
        or output(target, "rev-parse", "--verify", "HEAD^{commit}")
        != output(root, "rev-parse", "--verify", ref + "^{commit}")
    ):
        raise Blocked(
            "task worktree Git identity or branch changed; retain it for review"
        )
    idle_git(target)
    return target


def subprocess_bytes(root, revision, relative):
    result = subprocess.run(
        ["git", "show", revision + ":" + relative], cwd=root, capture_output=True
    )
    if result.returncode:
        raise ValueError("recorded IaC blob missing")
    return result.stdout


def managed_task_state(root: Path, name: str):
    """Check live Task/worktree ownership; callers bind the returned state to their save."""
    state = load(root, Path(name).stem)[3]
    if (
        state["task_file"] != name
        or Path(state["worktree"]) != root
        or state["merged"] is not None
    ):
        raise ValueError("source write task/worktree is mismatched or merged")
    if task_worktree(root, state) != root:
        raise ValueError("source write requires its managed worktree")
    return state
