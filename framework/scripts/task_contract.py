"""Select independent task contracts and reserve exact repository file paths."""

import argparse
from contextlib import contextmanager
import fnmatch
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import tempfile


SELECTOR = "BLUEPRINT_TASK_FILE"
TASK_NAME = re.compile(r"tasks/[a-z0-9]+(?:-[a-z0-9]+)*\.md")


def section(text, heading):
    result = []
    inside = False
    found = False
    for line in text.splitlines():
        if line == heading:
            if found:
                raise ValueError(f"duplicate task section: {heading}")
            inside = found = True
        elif line.startswith("## "):
            inside = False
        elif inside and line.strip():
            result.append(line)
    return result


def paths_in(text, heading):
    result = []
    for line in section(text, heading):
        match = re.fullmatch(r"- `([^`]+)`", line)
        if not match:
            raise ValueError(f"invalid {heading} entry: {line}")
        result.append(match.group(1))
    if not result or len(result) != len(set(result)):
        raise ValueError(f"missing or duplicate paths: {heading}")
    return set(result)


def matches(path, pattern):
    return path == pattern or (pattern.endswith("/**") and path.startswith(pattern[:-3] + "/")) or fnmatch.fnmatchcase(path, pattern)


def safe_path(root, value):
    path = PurePosixPath(value)
    if (not value or not path.parts or path.is_absolute() or str(path) != value or ".." in path.parts
            or "\\" in value or any(char in value for char in "*?[]\x00\n\r")
            or path.parts[0] in {".git", ".lock"}):
        raise ValueError(f"task file reservation must be an exact repository-relative path: {value}")
    candidate = root / value
    if any(parent.is_symlink() for parent in [candidate, *candidate.parents]
           if parent != root and parent.is_relative_to(root)):
        raise ValueError(f"task path must not use symlinks: {value}")
    if candidate.is_dir():
        raise ValueError(f"task must reserve files, not directories: {value}")
    return candidate


def contracts(root):
    directory = root / "tasks"
    if directory.is_symlink():
        raise ValueError("tasks directory must not use symlinks")
    result = {}
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root).as_posix()
            if not TASK_NAME.fullmatch(relative) or path.is_symlink() or not path.is_file():
                raise ValueError(f"invalid task contract file: {relative}")
            result[relative] = path.read_text(encoding="utf-8")
    return result


def status(text, legacy=False):
    entries = [line for line in section(text, "## Task contract") if line.startswith("- Task status:")]
    if legacy and not entries:
        return "running"
    if len(entries) != 1 or entries[0] not in {"- Task status: `running`", "- Task status: `completed`"}:
        raise ValueError("Task status must be exactly one of running/completed")
    return entries[0].split("`")[1]


def reservations(root, records):
    result = {}
    for name, text in records.items():
        legacy = name == "tasks/active.md" and len(records) == 1
        if name == "tasks/active.md" and not legacy:
            raise ValueError("migrate tasks/active.md before adding concurrent tasks")
        state = status(text, legacy)
        if legacy and not section(text, "## Modified files"):
            result[name] = (state, None)
            continue
        files = paths_in(text, "## Modified files")
        allowed = paths_in(text, "## Allowed paths")
        if name not in files:
            raise ValueError(f"Modified files must include its own contract: {name}")
        for value in files:
            safe_path(root, value)
            if value.startswith("tasks/") and value != name:
                raise ValueError(f"task cannot reserve another contract: {name}: {value}")
            if not any(matches(value, pattern) for pattern in allowed):
                raise ValueError(f"reserved file is outside Allowed paths: {name}: {value}")
        result[name] = (state, files)
    running = [(name, files) for name, (state, files) in result.items() if state == "running" and files is not None]
    for index, (name, files) in enumerate(running):
        for other, other_files in running[index + 1:]:
            overlap = files & other_files
            if overlap:
                raise ValueError(f"task file conflict: {name} with {other}: {', '.join(sorted(overlap))}; stop the new task")
    return result


def task_path(root, selected=None):
    records = contracts(root)
    reservations(root, records)
    selected = selected or os.environ.get(SELECTOR)
    if selected:
        if not TASK_NAME.fullmatch(selected):
            raise ValueError(f"invalid task selector: {selected}")
        if selected not in records:
            raise ValueError(f"selected task contract missing: {selected}")
        return root / selected
    running = [name for name, text in records.items() if status(text, name == "tasks/active.md") == "running"]
    if len(running) > 1:
        raise ValueError(f"multiple running tasks; select a contract with {SELECTOR} or --task-file")
    if running:
        return root / running[0]
    return root / "tasks/active.md"  # Missing idle contract preserves the existing idle checks.


def task_changes(root, changed, selected=None):
    records = contracts(root)
    reserved = reservations(root, records)
    if selected == "tasks/active.md" and len(records) == 1 and reserved[selected][1] is None:
        return changed
    running_files = set().union(*(files for state, files in reserved.values() if state == "running"))
    covered = set().union(*(files for _, files in reserved.values()))
    # Contract removals release reservations and are allowed without retaining history.
    unknown = {path for path in changed - covered if not (TASK_NAME.fullmatch(path) and not (root / path).exists())}
    if unknown:
        raise ValueError(f"changed paths have no task reservation: {', '.join(sorted(unknown))}")
    if selected is None:
        if running_files:
            raise ValueError("running task must be selected")
        return set()  # Completed, still-dirty outputs have ownership but no active task checks.
    owned = reserved.get(selected)
    if owned is None:
        raise ValueError(f"selected task contract missing: {selected}")
    files = owned[1]
    if owned[0] == "completed":
        files = files - running_files
    return changed & files


def require_writable(root, paths):
    records = contracts(root)
    if not records and not os.environ.get(SELECTOR):
        return  # Preserve the existing explicit-target generation API on contract-free inputs.
    selected = task_path(root)
    name = selected.relative_to(root).as_posix()
    reserved = reservations(root, records)
    if name not in reserved:
        raise ValueError("active task prompt missing")
    state, files = reserved[name]
    if state != "running":
        raise ValueError(f"completed task cannot write: {name}")
    if files is not None:
        requested = {path.relative_to(root).as_posix() for path in paths}
        if requested - files:
            raise ValueError(f"output has no selected task reservation: {', '.join(sorted(requested - files))}")


@contextmanager
def registration_lock(root):
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
    lock = Path(tempfile.gettempdir()) / f"blueprint-task-registration-{key}.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError(f"task registration is busy; retry after the other registration finishes: {lock}") from None
    try:
        yield
    finally:
        lock.rmdir()


def start(root, name, text):
    if name == "tasks/active.md" or not TASK_NAME.fullmatch(name):
        raise ValueError("new task must use tasks/<task-name>.md")
    with registration_lock(root):
        records = contracts(root)
        if name in records:
            raise ValueError(f"task contract already exists: {name}")
        if status(text) != "running":
            raise ValueError("new task must have running status")
        reservations(root, {**records, name: text})
        destination = safe_path(root, name)
        destination.parent.mkdir(exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--source", type=Path, help="Register a new contract from a file outside the repository")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    try:
        if args.source:
            if args.source.resolve().is_relative_to(root):
                raise ValueError("new contract source must be outside the repository")
            start(root, args.task_file, args.source.read_text(encoding="utf-8"))
        selected = task_path(root, args.task_file)
        print(f"Task contract: {selected.relative_to(root)}")
    except (OSError, ValueError) as error:
        print(f"Task contract: BLOCKED ({error})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
