"""Select independent task contracts and reserve exact repository file paths."""

import argparse
from contextlib import contextmanager
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import subprocess
import time
import threading
from typing import NamedTuple

from sync_files import atomic_files
from validation_cache import memoized


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
    return list(_section(text, heading))


@memoized
def _section(text, heading):
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
    return tuple(result)


def paths_in(text, heading):
    return set(_paths_in(text, heading))


@memoized
def _paths_in(text, heading):
    result = []
    for line in section(text, heading):
        match = re.fullmatch(r"- `([^`]+)`", line)
        if not match:
            raise ValueError(f"invalid {heading} entry: {line}")
        result.append(match.group(1))
    if not result or len(result) != len(set(result)):
        raise ValueError(f"missing or duplicate paths: {heading}")
    return frozenset(result)


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


def plain_git_config(path):
    """Accept a conservative subset; let Git handle includes and unusual syntax."""
    if not path.exists():
        return not path.is_symlink()
    section_name = None
    for line in path.read_bytes().decode("utf-8").split("\n"):
        line = line.strip(" \t\r")
        if not line or line.startswith(("#", ";")):
            continue
        section_match = re.fullmatch(r'\[([a-zA-Z][a-zA-Z0-9.-]*)(?: "[^"\\\x00-\x1f]+")?\]', line)
        if section_match:
            section_name = section_match[1].lower()
            if section_name not in {"core", "user", "credential", "remote", "branch", "pull"}:
                return False
            continue
        value = re.fullmatch(r'([a-zA-Z][a-zA-Z0-9-]*)\s*=\s*([^"\\\x00-\x1f]*)', line)
        if section_name is None or value is None:
            return False
        if section_name == "user" and value[1].lower() not in {"name", "email", "signingkey"}:
            return False
        if section_name == "core":
            key, setting = value[1].lower(), value[2].strip().lower()
            if key == "repositoryformatversion":
                if setting != "0":
                    return False
            elif key not in {"filemode", "bare", "logallrefupdates", "ignorecase", "precomposeunicode"} or setting not in {"true", "false"}:
                return False
    return True


def direct_git_directory(root):
    if any(key.startswith("GIT_") and key != "GIT_PAGER" for key in os.environ) or os.name != "posix":
        return None
    try:
        dotgit = root / ".git"
        if dotgit.is_symlink():
            return None
        directory = dotgit
        if dotgit.is_file():
            reference = dotgit.read_text(encoding="utf-8")
            if not re.fullmatch(r"gitdir: [^\x00\r\n]+\n?", reference):
                return None
            target = reference.removeprefix("gitdir: ").rstrip("\n")
            if target != target.strip():
                return None
            directory = root / target
        directory = directory.resolve(strict=True)
        common = directory
        commondir = directory / "commondir"
        if commondir.exists():
            reference = commondir.read_text(encoding="utf-8")
            if not re.fullmatch(r"[^\x00\r\n]+\n?", reference) or reference.strip() != reference.rstrip("\n"):
                return None
            common = (directory / reference.rstrip("\n")).resolve(strict=True)
        if os.geteuid() == 0 or any(path.stat().st_uid != os.geteuid() for path in (root, dotgit, directory, common)):
            return None
        if (directory / "HEAD").is_symlink():
            return None
        head = (directory / "HEAD").read_text(encoding="ascii")
        if not re.fullmatch(r"(?:ref: refs/[^\x00-\x20]+|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\n?", head):
            return None
        if not all(path.is_dir() and os.access(path, os.X_OK) for path in (common / "objects", common / "refs")):
            return None
        executable = shutil.which("git")
        if executable is None:
            return None
        config_paths = {common / "config", Path("/etc/gitconfig"),
                        Path(executable).parent.parent / "etc/gitconfig",
                        Path(executable).resolve().parent.parent / "etc/gitconfig",
                        Path.home() / ".gitconfig",
                        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "git/config"}
        if not all(plain_git_config(path) for path in config_paths):
            return None
        return directory
    except (OSError, ValueError, RuntimeError):
        return None  # Preserve Git's own diagnostics/error behavior for uncertain structures.


def worktree_identity(root):
    if not (root / ".git").exists():
        return directory_identity(root)  # Initialization and contract-free fixtures before git init.
    directory = direct_git_directory(root)
    if directory is not None:
        return hashlib.sha256(str(directory).encode()).hexdigest()
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


def validate_contract(root, name, text, legacy=False, *, check_paths=True):
    """Validate one authority without computing inter-task conflicts."""
    state = status(text, legacy)
    files = paths_in(text, "## Modified files")
    allowed = paths_in(text, "## Allowed paths")
    if name not in files:
        raise ValueError(f"Modified files must include its own contract: {name}")
    for value in files:
        if check_paths:
            safe_path(root, value)
        if value.startswith("tasks/") and value != name:
            raise ValueError(f"task cannot reserve another contract: {name}: {value}")
        if value not in allowed and not any(matches(value, pattern) for pattern in allowed):
            raise ValueError(f"reserved file is outside Allowed paths: {name}: {value}")
    active = claimed_files(text, files)
    if state == "completed" and files - active:
        raise ValueError(f"completed task has Deferred files: {name}: {', '.join(sorted(files - active))}")
    return Reservation(state, files, active, {})


def contract_authorities(root, records, *, check_paths=True):
    """Validate contract scope; conflict calculation is a separate write/validation step."""
    identities = {None, worktree_identity(root), directory_identity(root)}
    records = {name: text for name, text in records.items() if worktree_owner(text) in identities}
    result = {}
    for name, text in records.items():
        legacy = name == "tasks/active.md" and len(records) == 1
        if name == "tasks/active.md" and not legacy:
            raise ValueError("migrate tasks/active.md before adding concurrent tasks")
        state = status(text, legacy)
        if legacy and not section(text, "## Modified files"):
            result[name] = Reservation(state, None, None, {})
        else:
            entry = validate_contract(root, name, text, legacy, check_paths=check_paths)
            result[name] = entry._replace(deferred={value: () for value in entry.files - entry.active})
    return result


def reservations(root, records, *, check_paths=True):
    result = contract_authorities(root, records, check_paths=check_paths)
    claims = {}
    for name, entry in result.items():
        if entry.state == "running" and entry.active is not None:
            for value in entry.active:
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


# One process-local authority snapshot, never a cache of reservation results.
_managed_cache = None


def authority_stamp(paths, task_directory):
    result = []
    for path in paths:
        try:
            info = path.lstat()
            identity = (info.st_dev, info.st_ino, info.st_mode)
            # Output publication changes directory timestamps, not task authority.
            result.append(identity if stat.S_ISDIR(info.st_mode) and path != task_directory else
                          (*identity, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
        except FileNotFoundError:
            result.append(None)
    return tuple(result)


def managed_authority(root):
    """Revalidate on external changes; the hot path only stats authority inputs."""
    global _managed_cache
    cached = _managed_cache
    environment = tuple(sorted((k, v) for k, v in os.environ.items() if k.startswith("GIT_")))
    if cached and cached["root"] == root:
        if cached["environment"] == environment and authority_stamp(cached["watch"], root / "tasks") == cached["stamp"]:
            return cached
    else:
        cached = None
    from worktree_task import managed_state
    found = managed_state(root)
    if found is None:
        if cached:
            raise ValueError("managed worktree authority disappeared; retain work for review")
        return None
    state, metadata, gitdir, common = found
    directory = root / "tasks"
    watch = [root, root / ".git", directory, metadata, *list(metadata.parents)[:3],
             gitdir, common, common / "config", common / "worktrees",
             common / "packed-refs", common / "refs" / "heads" / state["branch"]]
    watch += [gitdir / name for name in ("HEAD", "commondir", "gitdir", "index", "locked",
              "config.worktree", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
              "rebase-merge", "rebase-apply", "sequencer")]
    if directory.is_dir():
        watch += sorted(directory.iterdir())
    before = authority_stamp(watch, directory)
    if json.loads(metadata.read_text(encoding="utf-8")) != state:
        raise ValueError("managed metadata changed during validation; retry explicitly")
    if (gitdir / "HEAD").read_text(encoding="utf-8").strip() != "ref: refs/heads/" + state["branch"]:
        raise ValueError("managed worktree branch changed during validation")
    records = contracts(root, include_foreign=True)
    identities = {None, state["identity"], directory_identity(root)}
    for name, text in records.items():
        if worktree_owner(text) in identities and name != state["task_file"]:
            raise ValueError("managed worktree contains another local task; retain work for review")
    entry = None
    if state["task_file"] in records:
        text = records[state["task_file"]]
        if worktree_owner(text) != state["identity"]:
            raise ValueError("managed task Worktree identity mismatch; explicit refresh required")
        entry = validate_contract(root, state["task_file"], text)
        entry = entry._replace(deferred={value: () for value in entry.files - entry.active})
    if authority_stamp(watch, directory) != before:
        raise ValueError("managed authority changed during validation; retry explicitly")
    _managed_cache = dict(root=root, state=state, records=records, entry=entry,
                          watch=watch, stamp=before, environment=environment)
    return _managed_cache


def authorizations(root, records=None, *, check_conflicts=True):
    managed = managed_authority(root)
    if managed is not None:
        name = managed["state"]["task_file"]
        if records is not None and records != managed["records"]:
            # Callers may pass only local records, but never stale or proposed grants.
            if records != {name: managed["records"].get(name)}:
                raise ValueError("managed task records changed; reread authority")
        return {name: managed["entry"]} if managed["entry"] is not None else {}
    records = contracts(root, include_foreign=True) if records is None else records
    batch = getattr(_write_local, 'batch', None)
    if not check_conflicts and batch is not None and batch['root'] == root:
        if records != batch['records']:
            raise ValueError("task authority changed during publication")
        return batch['reserved']
    return reservations(root, records) if check_conflicts else contract_authorities(root, records, check_paths=False)


def managed_selection(managed, selected):
    name = managed["state"]["task_file"]
    if selected and selected != name:
        raise ValueError("selected task does not match managed task_file")
    if managed["entry"] is None:
        raise ValueError("selected task contract missing: " + name)
    return name


def task_path(root, selected=None):
    batch = getattr(_write_local, 'batch', None)
    if batch is not None and batch['root'] == root:
        selected = selected or os.environ.get(SELECTOR) or batch['name']
    managed = managed_authority(root)
    if managed is not None:
        selected = selected or os.environ.get(SELECTOR)
        if not managed["records"] and not selected:
            return root / "tasks/active.md"
        name = managed_selection(managed, selected)
        if managed["entry"].state == "suspend":
            raise ValueError("suspend task cannot execute; use --resume")
        return root / name
    all_records = contracts(root, include_foreign=True)
    selected = selected or os.environ.get(SELECTOR)
    if selected:
        selected_text(root, all_records, selected)
    identities = {None, worktree_identity(root), directory_identity(root)}
    local = {name: text for name, text in all_records.items() if worktree_owner(text) in identities}
    if "tasks/active.md" in local and len(local) != 1:
        raise ValueError("migrate tasks/active.md before adding concurrent tasks")
    states = {name: status(text, name == "tasks/active.md") for name, text in local.items()}
    if not selected:
        running = [name for name, state in states.items() if state == "running"]
        if len(running) > 1:
            raise ValueError(f"multiple running tasks; select a contract with {SELECTOR} or --task-file")
        selected = running[0] if running else ("tasks/active.md" if "tasks/active.md" in local else None)
    if selected:
        if states[selected] == "suspend":
            raise ValueError(f"suspend task cannot execute; resume with task_contract.py --task-file {selected} --resume")
        text = local[selected]
        if selected != "tasks/active.md" or section(text, "## Modified files"):
            validate_contract(root, selected, text, legacy=selected == "tasks/active.md", check_paths=False)
        return root / selected
    return root / ("tasks/.idle" if "tasks/active.md" in all_records else "tasks/active.md")


def task_revision(root, selected=None):
    """Pin planning scope, excluding grants that Deferred acquisition may refresh."""
    path = task_path(root, selected)
    managed = managed_authority(root)
    text = managed['records'].get(path.relative_to(root).as_posix()) if managed is not None else (
        path.read_text(encoding='utf-8') if path.is_file() else None)
    if text is not None:
        if worktree_owner(text) is None:
            text = bind_worktree(root, text)
        text = re.sub(r'^## (?:Active|Deferred) files\n.*?(?=^## |\Z)', '', text, flags=re.M | re.S).strip()
    return path.relative_to(root).as_posix(), text


def task_changes(root, changed, selected=None, *, check_conflicts=True):
    managed = managed_authority(root)
    all_records = managed["records"] if managed is not None else contracts(root, include_foreign=True)
    if selected is not None:
        if managed is not None:
            managed_selection(managed, selected)
        else:
            selected_text(root, all_records, selected)
    reserved = authorizations(root, all_records, check_conflicts=check_conflicts)
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
    paths = set(paths)
    batch = getattr(_write_local, 'batch', None)
    if batch is not None and batch['root'] == root:
        selected = selected or os.environ.get(SELECTOR) or batch['name']
    for path in paths:
        safe_path(root, path.relative_to(root).as_posix())
    managed = managed_authority(root)
    if managed is not None:
        if batch is not None and batch['root'] == root and managed['records'] != batch['records']:
            raise ValueError("task authority changed during publication")
        if not managed["records"] and not selected and not os.environ.get(SELECTOR):
            return
        name = managed_selection(managed, selected or os.environ.get(SELECTOR))
        entry = managed["entry"]
        if entry.state != "running":
            raise ValueError(f"{entry.state} task cannot write: {name}")
        if entry.deferred:
            raise ValueError("managed task has Deferred files; explicit refresh required")
        requested = {path.relative_to(root).as_posix() for path in paths}
        if requested - entry.files:
            raise ValueError("output has no selected task reservation: " + ", ".join(sorted(requested - entry.files)))
        return
    records = contracts(root, include_foreign=True)
    if not records and not selected and not os.environ.get(SELECTOR):
        return  # Preserve the existing explicit-target generation API on contract-free inputs.
    selected = task_path(root, selected)
    name = selected.relative_to(root).as_posix()
    if not paths:
        text = selected_text(root, records, name)
        state = status(text, name == "tasks/active.md")
        if state != "running":
            raise ValueError(f"{state} task cannot write: {name}")
        return
    if batch is not None and batch['root'] == root:
        if records != batch['records'] or name != batch['name']:
            raise ValueError("task authority changed during publication")
        reserved = batch['reserved']
    else:
        reserved = reservations(root, records, check_paths=False)
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


_write_local = threading.local()


@contextmanager
def writable_batch(root, paths, selected=None, *, refresh_grants=False):
    """Pin current authority through publication; lock order is publication then registration."""
    from model_templates import publication_lock
    paths = set(paths)
    if not paths:
        require_writable(root, paths, selected)
        yield
        return
    existing = getattr(_write_local, 'batch', None)
    if existing is not None:
        if existing['root'] != root:
            raise ValueError("nested publication must use the same repository")
        require_writable(root, paths, selected)
        yield
        return
    with publication_lock(root), registration_lock(root):
        managed = managed_authority(root)
        if managed is not None:
            _write_local.batch = dict(root=root, name=managed['state']['task_file'] if managed['entry'] is not None else None,
                                     records=managed['records'])
            try:
                require_writable(root, paths, selected)
                yield
                require_writable(root, paths, selected)
            finally:
                del _write_local.batch
            return
        name = task_path(root, selected).relative_to(root).as_posix()
        records = contracts(root, include_foreign=True)
        reserved = reservations(root, records, check_paths=False) if records else {}
        if (refresh_grants and name in reserved and reserved[name].state == 'running' and
                (reserved[name].deferred or worktree_owner(records[name]) is None or
                 '## Active files' not in records[name].splitlines())):
            if reserved[name].files is not None:
                validate_contract(root, name, records[name], legacy=name == 'tasks/active.md')
            text = acquire(root, name, records[name], records, validated=reserved)
            if text != records[name]:
                atomic_files({safe_path(root, name): text}, staging_directory=root)
                records[name] = text
                own = reserved[name]
                active = claimed_files(text, own.files)
                reserved[name] = own._replace(active=active, deferred={p: owners for p, owners in own.deferred.items() if p not in active})
        _write_local.batch = dict(root=root, name=name if records else None, records=records, reserved=reserved)
        try:
            require_writable(root, paths, selected)
            yield
            if contracts(root, include_foreign=True) != records:
                raise ValueError("task authority changed during publication")
        finally:
            del _write_local.batch


def reserved_batches(root, jobs, sleeper=None, task_file=None, *, expected_task=None):
    """Yield whole write transactions; release both locks before Deferred waiting."""
    expected_task = expected_task if expected_task is not None else task_revision(root, task_file)
    if managed_authority(root) is not None:
        for key, paths in jobs.items():
            if task_revision(root, task_file) != expected_task:
                raise ValueError("task scope changed after planning; rerun generation")
            require_writable(root, paths, task_file)
            yield key
        return
    pending = {key: set(paths) for key, paths in jobs.items()}
    sleeper = sleeper or time.sleep
    attempts = 0
    waiting = False
    while pending:
        ready = False
        for key, paths in list(pending.items()):
            try:
                with writable_batch(root, paths, task_file, refresh_grants=True):
                    if task_revision(root, task_file) != expected_task:
                        raise ValueError("task scope changed after planning; rerun generation")
                    if waiting:
                        print("Acquired deferred reservation: " + ", ".join(sorted(
                            path.relative_to(root).as_posix() for path in paths)) + "; continuing task.", flush=True)
                    yield key
            except (DeferredWrite, RegistrationBusy):
                continue
            del pending[key]
            ready = True
        if not pending:
            return
        if ready:
            continue
        if attempts == MAX_RETRIES:
            raise DeferredExhausted("Deferred reservations remain after 20 retries. "
                                    "Task remains unfinished; current execution is ending cleanly.")
        if not waiting:
            print("Waiting for same-worktree reservations; retry every 30 sec, up to 20 attempts.", flush=True)
            waiting = True
        from sync_progress import phase
        with phase("reservation", status="reservation-wait"):
            sleeper(RETRY_INTERVAL)
        attempts += 1


def wait_deferred(root, name, sleeper=None):
    """Agent entrypoint after Active work: return as soon as any Deferred file is acquired."""
    managed = managed_authority(root)
    if managed is not None:
        managed_selection(managed, name)
        if managed["entry"].state != "running":
            raise ValueError("only a running task can wait for Deferred files")
        if managed["entry"].deferred:
            raise ValueError("managed task has Deferred files; explicit refresh required")
        return set()
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
    lock = Path(tempfile.gettempdir()) / f"blueprint-task-service_source-{key}.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise RegistrationBusy(f"task service_source is busy; retry after the other service_source finishes: {lock}") from None
    try:
        yield
    finally:
        lock.rmdir()


def validate_registration(root, name, text, records):
    managed = managed_authority(root)
    if managed is None:
        return reservations(root, {**records, name: text})
    else:
        if name != managed["state"]["task_file"]:
            raise ValueError("selected task does not match managed task_file")
        validate_contract(root, name, text)


def acquire(root, name, text, records, *, validated=None):
    managed = managed_authority(root)
    if managed is not None:
        if name != managed["state"]["task_file"]:
            raise ValueError("selected task does not match managed task_file")
        own = validate_contract(root, name, text)
        blocked = set()
    else:
        reserved = validated if validated is not None else validate_registration(root, name, text, records)
        blocked = set().union(*(claimed_files(records[key], entry.files) for key, entry in reserved.items()
                                if key != name and entry.state == "running" and entry.files is not None))
        own = reserved[name]
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
        validated = validate_registration(root, name, text, records)
        text = acquire(root, name, text, records, validated=validated)
        destination = safe_path(root, name)
        destination.parent.mkdir(exist_ok=True)
        atomic_files({destination: text}, staging_directory=root)


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
            authorizations(root, records)
            return
        text = acquire(root, name, set_status(text, "running"), records)
        if text != records[name]:
            atomic_files({safe_path(root, name): text}, staging_directory=root)


def complete(root, name):
    with registration_lock(root):
        records = contracts(root, include_foreign=True)
        text = selected_text(root, records, name)
        entry = authorizations(root, records)[name]
        if entry.state != "running":
            raise ValueError("only a running task can complete")
        if entry.deferred:
            raise ValueError(f"task has Deferred files; cannot complete: {', '.join(entry.deferred)}")
        if "- Workflow: `import`" in section(text, "## Task contract"):
            from import_guard import require_import_changes
            previous = os.environ.get(SELECTOR)
            try:
                os.environ[SELECTOR] = name
                require_import_changes(root)
            finally:
                if previous is None:
                    os.environ.pop(SELECTOR, None)
                else:
                    os.environ[SELECTOR] = previous
        atomic_files({safe_path(root, name): set_status(text, "completed")}, staging_directory=root)


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
        atomic_files({path: text}, staging_directory=root)
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
        entry = authorizations(root)[args.task_file]
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
