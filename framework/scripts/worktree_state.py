"""Read shared worktree identity and lifecycle state without Python setup dependencies."""

import json
import os
import re
import subprocess
from pathlib import Path

from utils.git_changes import collect_working_paths, read_paths


class Blocked(ValueError):
    pass


def git(root, *args, check=True):
    # Never route commands through an inherited worktree/private index or prompt.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(
        GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true", GIT_SEQUENCE_EDITOR="true"
    )
    result = subprocess.run(
        ["git", *map(str, args)],
        cwd=root,
        env=environment,
        capture_output=True,
        encoding="utf-8",
    )
    if check and result.returncode:
        raise Blocked(
            f"git {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def output(root, *args, runner=None):
    runner = runner or git
    return runner(root, *args).stdout.strip()


def worktrees(root):
    records = []
    for block in git(root, "worktree", "list", "--porcelain", "-z").stdout.split(
        "\0\0"
    ):
        if block:
            records.append(
                dict(line.partition(" ")[::2] for line in block.split("\0") if line)
            )
    return records


def _repository(where: Path) -> tuple[Path, Path, Path, list[dict[str, str]]]:
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
    common = Path(common)
    records = worktrees(root)
    primary = Path(records[0]["worktree"]).resolve()
    if not primary.is_dir() or "prunable" in records[0]:
        raise Blocked("primary worktree is missing or stale")
    return root, common, primary, records


def repository(where):
    return _repository(where)[:3]


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


def _load(primary: Path, common: Path, task_id: str) -> tuple[Path, Path, Path, dict]:
    path = state_path(primary, task_id)
    state = json.loads(path.read_text(encoding="utf-8"))
    if (
        state["task_id"] != task_id
        or state["branch"] != f"codex/worktree/{task_id}"
        or state["task_file"] != f"tasks/{task_id}.md"
        or state["primary"] != str(primary)
        or Path(state["worktree"]) != primary / ".worktrees" / task_id
    ):
        raise Blocked("task lifecycle state does not match this repository")
    # Cleanup can remove the caller's checkout; control Git from a surviving root.
    return primary, common, path, state


def paths(root, *args, runner=None):
    return read_paths(root, *args, runner=runner or git)


def task_start_commit(root, task_file):
    """Return the Task's shared-base boundary, excluding inherited base commits."""
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
    start = output(
        root,
        "rev-parse",
        "--verify",
        state.get("validation_base", state["start"]) + "^{commit}",
    )
    text = (root / task_file).read_text(encoding="utf-8")
    if "- Infrastructure phase: `implement`" in text.splitlines():
        return start
    if git(root, "merge-base", "--is-ancestor", start, "HEAD", check=False).returncode:
        raise Blocked("task lifecycle start is not an ancestor of HEAD")
    base = output(
        root, "rev-parse", "--verify", f"refs/heads/{state['base']}^{{commit}}"
    )
    if git(root, "merge-base", "--is-ancestor", start, base, check=False).returncode:
        raise Blocked("base history was rewritten; task retained for review")
    return output(root, "merge-base", base, "HEAD")


def committed_task_paths(root, task_file):
    """Committed Task changes relative to its shared base, including all paths."""
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
    _, common, primary, records = _repository(root)
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
    task_worktree(root, state, records=records)
    start = output(root, "rev-parse", "--verify", state["start"] + "^{commit}")
    head = output(root, "rev-parse", "HEAD")
    intent = state.get("deployCheckpointIntent")
    # Only the checkpoint helper may finish an interrupted, exactly recorded commit.
    if head != state["tip"] and not (
        intent
        and output(root, "rev-parse", "HEAD^") == intent["head"] == state["tip"]
        and output(root, "rev-parse", "HEAD^{tree}") == intent["tree"]
        and output(root, "log", "-1", "--format=%s") == intent["message"]
    ):
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


def task_worktree(root, state, *, records=None):
    target = Path(state["worktree"])
    entries = [
        entry
        for entry in (worktrees(root) if records is None else records)
        if Path(entry["worktree"]).resolve() == target
    ]
    if (
        len(entries) != 1
        or "locked" in entries[0]
        or "prunable" in entries[0]
        or entries[0].get("branch") != f"refs/heads/{state['branch']}"
        or not target.is_dir()
    ):
        raise Blocked(
            "task worktree missing, locked, stale or switched; retain it for review"
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
