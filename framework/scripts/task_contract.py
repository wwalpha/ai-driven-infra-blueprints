"""Select independent task contracts and reserve exact repository file paths."""

import argparse
from contextlib import contextmanager
import fnmatch
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import subprocess
import time
from typing import NamedTuple


SELECTOR = "BLUEPRINT_TASK_FILE"
TASK_NAME = re.compile(r"tasks/[a-z0-9]+(?:-[a-z0-9]+)*\.md")
RETRY_INTERVAL = 30
MAX_RETRIES = 20


class DeferredWrite(ValueError):
    """Only the requested write unit is temporarily unavailable."""


class DeferredExhausted(Exception):
    """Clean worker exit with unfinished reservations retained."""


class RegistrationBusy(ValueError):
    pass


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


def directory_identity(root):
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()


def worktree_identity(root):
    if not (root / ".git").exists():
        return directory_identity(root)  # Initialization and contract-free fixtures before git init.
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"}}
    result = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=root,
                            env=environment, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ValueError("cannot determine Git worktree identity")
    return hashlib.sha256(str(Path(result.stdout.strip()).resolve()).encode()).hexdigest()


def worktree_owner(text):
    entries = [line for line in section(text, "## Task contract") if line.startswith("- Worktree identity:")]
    if not entries:
        return None  # Unbound legacy contracts belong to the checkout containing them.
    if len(entries) != 1 or not re.fullmatch(r"- Worktree identity: `[0-9a-f]{64}`", entries[0]):
        raise ValueError("invalid Worktree identity")
    return entries[0].split("`")[1]


def local_contract(root, text):
    return worktree_owner(text) in {None, worktree_identity(root), directory_identity(root)}


def selected_text(root, records, name):
    if not TASK_NAME.fullmatch(name):
        raise ValueError(f"invalid task selector: {name}")
    if name not in records:
        raise ValueError(f"selected task contract missing: {name}")
    if not local_contract(root, records[name]):
        raise ValueError(f"selected task belongs to another worktree: {name}")
    return records[name]


def bind_worktree(root, text):
    identity = f"- Worktree identity: `{worktree_identity(root)}`"
    if worktree_owner(text) is not None:
        return re.sub(r"^- Worktree identity: `[^`]+`$", identity, text, flags=re.M)
    return text.replace("## Task contract\n", "## Task contract\n" + identity + "\n", 1)


def contracts(root, include_foreign=False):
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
    if include_foreign:
        return result
    identities = {None, worktree_identity(root), directory_identity(root)}
    return {name: text for name, text in result.items() if worktree_owner(text) in identities}


def status(text, legacy=False):
    entries = [line for line in section(text, "## Task contract") if line.startswith("- Task status:")]
    if legacy and not entries:
        return "running"
    if len(entries) != 1 or entries[0] not in {f"- Task status: `{state}`" for state in ("running", "suspend", "completed")}:
        raise ValueError("Task status must be exactly one of running/suspend/completed")
    if entries[0] == "- Task status: `suspend`" and not section(text, "## Suspension reason"):
        raise ValueError("suspend task must record a concrete Suspension reason")
    return entries[0].split("`")[1]


class Reservation(NamedTuple):
    state: str
    files: set | None  # Requested paths, retained for contract validation.
    active: set | None
    deferred: dict  # File -> current owners; empty tuple means awaiting acquisition.


def claimed_files(text, files):
    if "## Active files" not in text.splitlines():
        return files  # Legacy contracts retain their existing grants until refreshed.
    entries = section(text, "## Active files")
    active = paths_in(text, "## Active files") if entries else set()
    for value in active:
        if value not in files:
            raise ValueError(f"Active file is outside Modified files: {value}")
    pending = paths_in(text, "## Deferred files") if section(text, "## Deferred files") else set()
    if active & pending or pending - files:
        raise ValueError("Deferred files must be disjoint from Active files and within Modified files")
    return active


def reservations(root, records):
    identities = {None, worktree_identity(root), directory_identity(root)}
    records = {name: text for name, text in records.items() if worktree_owner(text) in identities}
    result = {}
    claims = {}
    for name, text in records.items():
        legacy = name == "tasks/active.md" and len(records) == 1
        if name == "tasks/active.md" and not legacy:
            raise ValueError("migrate tasks/active.md before adding concurrent tasks")
        state = status(text, legacy)
        if legacy and not section(text, "## Modified files"):
            result[name] = Reservation(state, None, None, {})
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
        active = claimed_files(text, files)
        if state == "completed" and files - active:
            raise ValueError(f"completed task has Deferred files: {name}: {', '.join(sorted(files - active))}")
        result[name] = Reservation(state, files, active, {})
        if state == "running":
            for value in active:
                claims.setdefault(value, []).append(name)
    for name, entry in list(result.items()):
        if entry.state != "running" or entry.files is None:
            continue
        # An overlapping manual/legacy claim denies only that file to every contender.
        active = {value for value in entry.active if claims[value] == [name]}
        deferred = {value: tuple(owner for owner in claims.get(value, []) if owner != name)
                    for value in sorted(entry.files - active)}
        result[name] = entry._replace(active=active, deferred=deferred)
    return result


def task_path(root, selected=None):
    all_records = contracts(root, include_foreign=True)
    selected = selected or os.environ.get(SELECTOR)
    if selected:
        selected_text(root, all_records, selected)
    reserved = reservations(root, all_records)
    if selected:
        if reserved[selected].state == "suspend":
            raise ValueError(f"suspend task cannot execute; resume with task_contract.py --task-file {selected} --resume")
        return root / selected
    running = [name for name, entry in reserved.items() if entry.state == "running"]
    if len(running) > 1:
        raise ValueError(f"multiple running tasks; select a contract with {SELECTOR} or --task-file")
    if running:
        return root / running[0]
    if "tasks/active.md" in reserved and reserved["tasks/active.md"].state == "suspend":
        raise ValueError("suspend task cannot execute; resume with task_contract.py --task-file tasks/active.md --resume")
    # Never return an existing foreign legacy contract as an implicit idle selection.
    return root / ("tasks/.idle" if "tasks/active.md" in all_records and "tasks/active.md" not in reserved
                   else "tasks/active.md")


def task_changes(root, changed, selected=None):
    all_records = contracts(root, include_foreign=True)
    if selected is not None:
        selected_text(root, all_records, selected)
    reserved = reservations(root, all_records)
    changed = changed - (all_records.keys() - reserved.keys())
    if selected == "tasks/active.md" and reserved[selected].files is None:
        return changed
    running_files = set().union(*(entry.active or set() for entry in reserved.values() if entry.state == "running"))
    covered = set().union(*(entry.active or set() for entry in reserved.values()))
    # Contract removals release reservations and are allowed without retaining history.
    unknown = {path for path in changed - covered if not (TASK_NAME.fullmatch(path) and not (root / path).exists())}
    if unknown:
        raise ValueError(f"changed paths have no task reservation: {', '.join(sorted(unknown))}")
    if selected is None:
        if any(entry.state == "running" for entry in reserved.values()):
            raise ValueError("running task must be selected")
        return set()  # Completed, still-dirty outputs have ownership but no active task checks.
    entry = reserved[selected]
    files = entry.active if entry.state == "running" else entry.active - running_files
    return changed & files


def require_writable(root, paths, selected=None):
    records = contracts(root, include_foreign=True)
    if not records and not selected and not os.environ.get(SELECTOR):
        return  # Preserve the existing explicit-target generation API on contract-free inputs.
    selected = task_path(root, selected)
    name = selected.relative_to(root).as_posix()
    reserved = reservations(root, records)
    if name not in reserved:
        raise ValueError("active task prompt missing")
    entry = reserved[name]
    if entry.state != "running":
        raise ValueError(f"{entry.state} task cannot write: {name}")
    if entry.files is not None:
        requested = {path.relative_to(root).as_posix() for path in paths}
        if requested - entry.files:
            raise ValueError(f"output has no selected task reservation: {', '.join(sorted(requested - entry.files))}")
        pending = requested - entry.active
        if pending:
            details = "; ".join(f"{value} -> {', '.join(entry.deferred[value]) or 'awaiting reservation refresh'}"
                                for value in sorted(pending))
            raise DeferredWrite(f"Deferred file cannot write: {details}; continue Active files")


def reserved_batches(root, jobs, sleeper=None, task_file=None):
    """Yield writable job keys first; retry pending atomic write units without rerunning work.

    The caller finishes each yielded job before requesting the next. Jobs map keys
    to exact output paths; a multi-file job is never split. Exhaustion is not failure.
    """
    pending = {key: set(paths) for key, paths in jobs.items()}
    selected = task_path(root, task_file)
    name = selected.relative_to(root).as_posix() if selected.is_file() else None
    sleeper = sleeper or time.sleep
    attempts = 0
    waiting = False
    while pending:
        try:
            if name:
                refresh(root, name)
        except RegistrationBusy:
            pass  # No ownership changes; only existing grants may be used this round.
        ready = []
        for key, paths in pending.items():
            try:
                require_writable(root, paths, name)
            except DeferredWrite:
                continue
            ready.append(key)
        for key in ready:
            if waiting:
                print("Acquired deferred reservation: " + ", ".join(sorted(
                    path.relative_to(root).as_posix() for path in pending[key])) + "; continuing task.", flush=True)
            yield key
            del pending[key]
        if not pending:
            return
        if ready:
            continue  # Finish every available unit before any sleep.
        if attempts == MAX_RETRIES:
            raise DeferredExhausted("Deferred reservations remain after 20 retries. "
                                    "Task remains unfinished; current execution is ending cleanly.")
        if not waiting:
            print("Waiting for same-worktree reservations; retry every 30 sec, up to 20 attempts.", flush=True)
            waiting = True
        sleeper(RETRY_INTERVAL)  # Never hold the registration lock while sleeping or working.
        attempts += 1  # One bounded budget across this worker's waiting phases.


def wait_deferred(root, name, sleeper=None):
    """Agent entrypoint after Active work: return as soon as any Deferred file is acquired."""
    records = contracts(root, include_foreign=True)
    selected_text(root, records, name)
    entry = reservations(root, records)[name]
    if entry.state != "running":
        raise ValueError("only a running task can wait for Deferred files")
    if not entry.deferred:
        return set()
    previous = entry.active
    # The generator does not execute work: the agent immediately continues acquired
    # files, then calls again only when its new Active work is finished.
    next(reserved_batches(root, {path: [root / path] for path in entry.deferred}, sleeper, name), None)
    return reservations(root, contracts(root))[name].active - previous


@contextmanager
def registration_lock(root):
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
    lock = Path(tempfile.gettempdir()) / f"blueprint-task-registration-{key}.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise RegistrationBusy(f"task registration is busy; retry after the other registration finishes: {lock}") from None
    try:
        yield
    finally:
        lock.rmdir()


def acquire(root, name, text, records):
    reserved = reservations(root, {key: value for key, value in records.items() if key != name})
    blocked = set().union(*(claimed_files(records[key], entry.files) for key, entry in reserved.items()
                            if entry.state == "running" and entry.files is not None))
    own = reservations(root, {name: text})[name]
    if own.files is None:
        return bind_worktree(root, text)
    active = own.files - blocked
    allocations = (("## Active files", active), ("## Deferred files", own.files - active))
    for heading, _ in allocations:
        text = re.sub(r"^" + heading + r"\n.*?(?=^## |\Z)", "", text, flags=re.M | re.S)
    for heading, files in allocations:
        text = text.rstrip() + "\n\n" + heading + "\n\n" + "".join(f"- `{value}`\n" for value in sorted(files))
    return bind_worktree(root, text)


def start(root, name, text):
    if name == "tasks/active.md" or not TASK_NAME.fullmatch(name):
        raise ValueError("new task must use tasks/<task-name>.md")
    with registration_lock(root):
        records = contracts(root, include_foreign=True)
        if name in records:
            selected_text(root, records, name)
            raise ValueError(f"task contract already exists: {name}")
        if not local_contract(root, text):
            raise ValueError(f"selected task belongs to another worktree: {name}")
        if status(text) != "running":
            raise ValueError("new task must have running status")
        # Validate the combined contracts (including legacy concurrency) before publication.
        reservations(root, {**records, name: text})
        text = acquire(root, name, text, records)
        destination = safe_path(root, name)
        destination.parent.mkdir(exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(text)


def refresh(root, name, resuming=False):
    with registration_lock(root):
        records = contracts(root, include_foreign=True)
        text = selected_text(root, records, name)
        state = status(text, name == "tasks/active.md")
        if state == "suspend" and not resuming:
            raise ValueError("suspend task cannot execute; use --resume")
        if state == "completed":
            if resuming:
                raise ValueError("completed task cannot resume")
            reservations(root, records)
            return
        text = acquire(root, name, set_status(text, "running"), records)
        if text != records[name]:
            safe_path(root, name).write_text(text, encoding="utf-8")


def complete(root, name):
    with registration_lock(root):
        records = contracts(root, include_foreign=True)
        text = selected_text(root, records, name)
        entry = reservations(root, records)[name]
        if entry.state != "running":
            raise ValueError("only a running task can complete")
        if entry.deferred:
            raise ValueError(f"task has Deferred files; cannot complete: {', '.join(entry.deferred)}")
        safe_path(root, name).write_text(set_status(text, "completed"), encoding="utf-8")


def set_status(text, state):
    if state == "completed" and section(text, "## Deferred files"):
        raise ValueError("task has Deferred files; cannot complete")
    text = re.sub(r"^## Suspension reason\n.*?(?=^## |\Z)", "", text, flags=re.M | re.S)
    if any(line.startswith("- Task status:") for line in section(text, "## Task contract")):
        prefix, body = text.split("## Task contract\n", 1)
        return prefix + "## Task contract\n" + re.sub(r"^- Task status: `[^`]+`$", f"- Task status: `{state}`", body, count=1, flags=re.M)
    if "## Task contract" not in text.splitlines():
        text += "\n## Task contract\n"
    return text.replace("## Task contract\n", f"## Task contract\n- Task status: `{state}`\n", 1)


def suspend(root, name, reason):
    if not reason.strip():
        raise ValueError("suspend requires a concrete reason")
    with registration_lock(root):
        if not TASK_NAME.fullmatch(name):
            raise ValueError(f"invalid task selector: {name}")
        path = safe_path(root, name)
        text = path.read_text(encoding="utf-8")
        if not local_contract(root, text):
            raise ValueError(f"selected task belongs to another worktree: {name}")
        if status(text, name == "tasks/active.md") != "running":
            return False
        # Do not inspect other contracts: their errors must not prevent releasing this task.
        text = set_status(text, "suspend")
        text += "\n## Suspension reason\n\n" + "\n".join(f"    {line}".rstrip() for line in reason.strip().splitlines()) + "\n"
        path.write_text(text, encoding="utf-8")
    return True


def resume(root, name):
    refresh(root, name, resuming=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--source", type=Path, help="Register a new contract from a file outside the repository")
    transition = parser.add_mutually_exclusive_group()
    transition.add_argument("--suspend-reason", help="Suspend only this task, record the problem and release its reservations")
    transition.add_argument("--resume", action="store_true", help="Resume/refresh this task and acquire available Deferred files")
    transition.add_argument("--complete", action="store_true", help="Complete after a successful loop; reject remaining Deferred files")
    transition.add_argument("--wait", action="store_true", help="After Active work, automatically acquire Deferred files (30 sec x 20); continue acquired work")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    try:
        if args.source and (args.suspend_reason is not None or args.resume or args.complete or args.wait):
            raise ValueError("--source cannot be combined with a status transition")
        if args.suspend_reason is not None:
            changed = suspend(root, args.task_file, args.suspend_reason)
            print(f"Task contract: {args.task_file} ({'suspend; reservations released' if changed else 'status unchanged'})")
            return 0
        if args.wait:
            os.environ[SELECTOR] = args.task_file
            wait_deferred(root, args.task_file)
        elif args.resume:
            resume(root, args.task_file)
        elif args.complete:
            complete(root, args.task_file)
        if args.source:
            if args.source.resolve().is_relative_to(root):
                raise ValueError("new contract source must be outside the repository")
            start(root, args.task_file, args.source.read_text(encoding="utf-8"))
        elif not args.resume and not args.complete and not args.wait:
            refresh(root, args.task_file)
        selected = task_path(root, args.task_file)
        print(f"Task contract: {selected.relative_to(root)}")
        entry = reservations(root, contracts(root))[args.task_file]
        if entry.files is not None:
            print("Active: " + ", ".join(sorted(entry.active)))
            for value, owners in entry.deferred.items():
                print(f"Deferred: {value} -> {', '.join(owners) or 'awaiting reservation refresh'}")
    except DeferredExhausted as error:
        print(str(error))
        return 0
    except (OSError, ValueError) as error:
        print(f"Task contract: BLOCKED ({error})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
