"""Select task contracts and manage their ordinary status transitions."""

import argparse
import fnmatch
import os
from pathlib import Path, PurePosixPath
import re

from sync_files import atomic_files
from validation_cache import memoized, input_is_dir, input_is_file, input_is_symlink, input_select, input_text


SELECTOR = "BLUEPRINT_TASK_FILE"
TASK_NAME = re.compile(r"tasks/[a-z0-9]+(?:-[a-z0-9]+)*\.md")


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
        raise ValueError(f"task path must be an exact repository-relative path: {value}")
    candidate = root / value
    if any(parent.is_symlink() for parent in [candidate, *candidate.parents]
           if parent != root and parent.is_relative_to(root)):
        raise ValueError(f"task path must not use symlinks: {value}")
    if candidate.is_dir():
        raise ValueError(f"task path must be a file, not a directory: {value}")
    return candidate


def selected_text(root, records, name):
    if not TASK_NAME.fullmatch(name):
        raise ValueError(f"invalid task selector: {name}")
    if name not in records:
        raise ValueError(f"selected task contract missing: {name}")
    return records[name]


def contracts(root):
    directory = root / "tasks"
    if input_is_symlink(directory):
        raise ValueError("tasks directory must not use symlinks")
    result = {}
    if input_is_dir(directory):
        for path in sorted(input_select(directory)):
            relative = path.relative_to(root).as_posix()
            if not TASK_NAME.fullmatch(relative) or input_is_symlink(path) or not input_is_file(path):
                raise ValueError(f"invalid task contract file: {relative}")
            result[relative] = input_text(path, encoding="utf-8")
    return result


def status(text, legacy=False):
    entries = [line for line in section(text, "## Task contract") if line.startswith("- Task status:")]
    if legacy and not entries:
        return "running"
    if len(entries) != 1 or entries[0] not in {f"- Task status: `{state}`" for state in ("running", "suspend", "completed")}:
        raise ValueError("Task status must be exactly one of running/suspend/completed")
    if entries[0] == "- Task status: `suspend`" and not section(text, "## Suspension reason"):
        raise ValueError("suspend task must record a concrete Suspension reason")
    return entries[0].split("`")[1]


def validate_contract(root, name, text, legacy=False, *, check_paths=True):
    """Validate the selected contract declaration."""
    status(text, legacy)
    model_operation(text)
    files = paths_in(text, "## Modified files")
    allowed = paths_in(text, "## Allowed paths")
    if name not in files:
        raise ValueError(f"Modified files must include its own contract: {name}")
    for value in files:
        if check_paths:
            safe_path(root, value)
        if value.startswith("tasks/") and value != name:
            raise ValueError(f"task cannot modify another contract: {name}: {value}")
        if value not in allowed and not any(matches(value, pattern) for pattern in allowed):
            raise ValueError(f"Modified file is outside Allowed paths: {name}: {value}")


def model_operation(text):
    """Exact Model-only update request; actual differences must still prove the operation."""
    lines = section(text, '## Task contract')
    fields = ('Model operation', 'Source resource', 'Destination resource')
    if not any(line.startswith('- ' + field + ':') for line in lines for field in fields):
        return None
    def field(name, required=True):
        selected = [line for line in lines if line.startswith('- ' + name + ':')]
        if not selected and not required:
            return None
        match = re.fullmatch(r'- ' + re.escape(name) + r': `([^`]+)`', selected[0]) if len(selected) == 1 else None
        if match is None:
            raise ValueError('Model-only update requires exactly one ' + name)
        return match[1]
    if field('Task type') != 'design' or field('Workflow') != 'update':
        raise ValueError('Model-only IMPORT operations require the design /update workflow')
    if field('AWS API execution') != 'forbidden' or field('deploy/apply') != 'forbidden':
        raise ValueError('Model-only IMPORT operations forbid AWS and deploy/apply')
    action = field('Model operation')
    if action not in {'import-merge', 'import-delete'}:
        raise ValueError('unknown Model-only IMPORT operation')
    source = field('Source resource')
    destination = field('Destination resource', action == 'import-merge')
    pattern = r'(?:[a-z0-9]+(?:[-_][a-z0-9]+)*/){3}[0-9]{3,}'
    if not re.fullmatch(pattern, source) or destination is not None and not re.fullmatch(pattern, destination):
        raise ValueError('IMPORT operation requires exact environment/target/service/fixed Resource IDs')
    if action == 'import-delete' and destination is not None:
        raise ValueError('IMPORT deletion has no destination')
    if destination is not None and (source == destination or source.rsplit('/', 1)[0] != destination.rsplit('/', 1)[0]):
        raise ValueError('IMPORT merge requires distinct resources in the same environment/target/service')
    return action, tuple(source.split('/')[:3]), source.split('/')[-1], destination.split('/')[-1] if destination else None


def task_path(root, selected=None):
    records = contracts(root)
    selected = selected or os.environ.get(SELECTOR)
    if selected:
        selected_text(root, records, selected)
    if "tasks/active.md" in records and len(records) != 1:
        raise ValueError("migrate tasks/active.md before adding concurrent tasks")
    states = {name: status(text, name == "tasks/active.md") for name, text in records.items()}
    if not selected:
        running = [name for name, state in states.items() if state == "running"]
        if len(running) > 1:
            raise ValueError(f"multiple running tasks; select a contract with {SELECTOR} or --task-file")
        selected = running[0] if running else ("tasks/active.md" if "tasks/active.md" in records else None)
    if selected:
        if states[selected] == "suspend":
            raise ValueError(f"suspend task cannot execute; resume with task_contract.py --task-file {selected} --resume")
        text = records[selected]
        if selected != "tasks/active.md" or section(text, "## Modified files"):
            validate_contract(root, selected, text, legacy=selected == "tasks/active.md", check_paths=False)
        return root / selected
    return root / "tasks/active.md"


def task_revision(root, selected=None):
    """Pin task planning content so later changes invalidate the plan."""
    path = task_path(root, selected)
    text = path.read_text(encoding="utf-8") if path.is_file() else None
    return path.relative_to(root).as_posix(), text


def start(root, name, text):
    if name == "tasks/active.md" or not TASK_NAME.fullmatch(name):
        raise ValueError("new task must use tasks/<task-name>.md")
    records = contracts(root)
    if "tasks/active.md" in records:
        raise ValueError("migrate tasks/active.md before adding concurrent tasks")
    if name in records:
        selected_text(root, records, name)
        raise ValueError(f"task contract already exists: {name}")
    if status(text) != "running":
        raise ValueError("new task must have running status")
    validate_contract(root, name, text)
    destination = safe_path(root, name)
    destination.parent.mkdir(exist_ok=True)
    atomic_files({destination: text}, staging_directory=root)


def refresh(root, name, resuming=False):
    records = contracts(root)
    text = selected_text(root, records, name)
    state = status(text, name == "tasks/active.md")
    if state == "suspend" and not resuming:
        raise ValueError("suspend task cannot execute; use --resume")
    if state == "completed":
        if resuming:
            raise ValueError("completed task cannot resume")
        validate_contract(root, name, text)
        return
    text = set_status(text, "running")
    if name != "tasks/active.md" or section(text, "## Modified files"):
        validate_contract(root, name, text)
    if text != records[name]:
        atomic_files({safe_path(root, name): text}, staging_directory=root)


def complete(root, name):
    records = contracts(root)
    text = selected_text(root, records, name)
    if status(text, name == "tasks/active.md") != "running":
        raise ValueError("only a running task can complete")
    if "- Workflow: `import`" in section(text, "## Task contract") or model_operation(text) is not None:
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
    if not TASK_NAME.fullmatch(name):
        raise ValueError(f"invalid task selector: {name}")
    path = safe_path(root, name)
    text = path.read_text(encoding="utf-8")
    if status(text, name == "tasks/active.md") != "running":
        return False
    # Do not inspect other contracts when suspending this task.
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
    transition.add_argument("--suspend-reason", help="Suspend only this task and record the problem")
    transition.add_argument("--resume", action="store_true", help="Resume this task")
    transition.add_argument("--complete", action="store_true", help="Complete after successful required validation")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    try:
        if args.source and (args.suspend_reason is not None or args.resume or args.complete):
            raise ValueError("--source cannot be combined with a status transition")
        if args.suspend_reason is not None:
            changed = suspend(root, args.task_file, args.suspend_reason)
            print(f"Task contract: {args.task_file} ({'suspend' if changed else 'status unchanged'})")
            return 0
        if args.resume:
            resume(root, args.task_file)
        elif args.complete:
            complete(root, args.task_file)
        if args.source:
            if args.source.resolve().is_relative_to(root):
                raise ValueError("new contract source must be outside the repository")
            start(root, args.task_file, args.source.read_text(encoding="utf-8"))
        elif not args.resume and not args.complete:
            refresh(root, args.task_file)
        selected = task_path(root, args.task_file)
        print(f"Task contract: {selected.relative_to(root)}")
    except (OSError, ValueError) as error:
        print(f"Task contract: BLOCKED ({error})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
