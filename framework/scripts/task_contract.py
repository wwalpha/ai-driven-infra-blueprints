"""Select task contracts and manage their ordinary status transitions."""

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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
    model_refactor(text)
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


@dataclass(frozen=True)
class MergePair:
    source: str
    destination: str


@dataclass(frozen=True)
class ReferenceChange:
    consumer: str
    field: str
    source: str
    destination: str
    property_name: str | None = None
    pointer: str | None = None


@dataclass(frozen=True)
class ModelOperation:
    action: str
    scope: tuple[str, str, str]
    pairs: tuple[MergePair, ...] = ()
    references: tuple[ReferenceChange, ...] = ()
    delete_source: str | None = None
    delete_sources: tuple[str, ...] = ()
    detaches: tuple["DependencyDetach", ...] = ()

    @property
    def source_scopes(self):
        if self.action == 'import-delete':
            return frozenset(tuple(source.split('/')[:3]) for source in self.delete_sources)
        return frozenset({self.scope})

    @property
    def scopes(self):
        return self.source_scopes | frozenset(tuple(ref.consumer.split('/')[:3]) for ref in self.references) | frozenset(
            tuple(detach.consumer.split('/')[:3]) for detach in self.detaches)


def model_operation(text: str) -> ModelOperation | None:
    """Parse only reserved operation declarations; never expand or read Model sources."""
    from iac_values import strict_json
    lines = section(text, '## Task contract')
    fields = ('Model operation', 'Source resource', 'Destination resource')
    headings = ('## Model merge pairs', '## Model reference changes', '## Model delete sources')
    reserved = [line for line in lines if any(re.match(r'-\s*' + name + r'\b', line) for name in fields)]
    present = {heading for heading in headings if heading in text.splitlines()}
    # Detect malformed reserved headings too, without constraining ordinary prose.
    for line in text.splitlines():
        if re.match(r'##\s+Model (merge pairs|reference changes|delete sources)\b', line) and line not in headings:
            raise ValueError('invalid Model operation section: ' + line)
    records = {heading: section(text, heading) for heading in present}
    if not reserved and not present:
        return None
    for line in reserved:
        if not any(re.fullmatch(r'- ' + name + r': `[^`]+`', line) for name in fields):
            raise ValueError('invalid Model operation declaration: ' + line)
    legacy = any(line.startswith(('- Source resource:', '- Destination resource:')) for line in reserved)
    if legacy and present - {'## Model reference changes'}:
        raise ValueError('cannot mix legacy resources and Model operation sections')

    def field(name, required=True):
        selected = [line for line in lines if line.startswith('- ' + name + ':')]
        if not selected and not required:
            return None
        match = re.fullmatch(r'- ' + re.escape(name) + r': `([^`]+)`', selected[0]) if len(selected) == 1 else None
        if match is None:
            raise ValueError('Model-only update requires exactly one ' + name)
        return match[1]

    def address(value):
        if not isinstance(value, str) or not re.fullmatch(r'(?:[a-z0-9]+(?:[-_][a-z0-9]+)*/){3}[0-9]{3,}', value):
            raise ValueError('IMPORT operation requires exact environment/target/service/fixed Resource IDs')
        return value

    def objects(heading):
        for line in records.get(heading, ()):
            if not line.startswith('- {') or not line.endswith('}'):
                raise ValueError('invalid Model operation JSON entry: ' + line)
            value = strict_json(line[2:])
            if not isinstance(value, dict):
                raise ValueError('Model operation entry must be an object')
            yield value

    if field('Task type') != 'design' or field('Workflow') != 'update':
        raise ValueError('Model-only IMPORT operations require the design /update workflow')
    if field('AWS API execution') != 'forbidden' or field('deploy/apply') != 'forbidden':
        raise ValueError('Model-only IMPORT operations forbid AWS and deploy/apply')
    action = field('Model operation')
    if action not in {'import-merge', 'import-delete', 'import-retarget'}:
        raise ValueError('unknown Model-only IMPORT operation')
    deleting = action == 'import-delete'
    delete_sources = ()
    if deleting:
        if headings[0] in present or field('Destination resource', False) is not None:
            raise ValueError('IMPORT deletion has no destination or merge pairs')
        if legacy:
            delete_sources = (address(field('Source resource')),)
        else:
            delete_sources = tuple(sorted(address(value) for value in paths_in(text, headings[2])))
        if len({tuple(value.split('/')[:2]) for value in delete_sources}) != 1:
            raise ValueError('IMPORT deletion requires the same environment/target')
    elif headings[2] in present:
        raise ValueError('Model delete sources requires import-delete')
    if legacy and present and not deleting:
        raise ValueError('cannot mix legacy resources and Model operation sections')
    standalone = action == 'import-retarget'
    if standalone and (legacy or headings[0] in present):
        raise ValueError('standalone retarget has no merge pairs or legacy resources')
    pairs = []
    if legacy and not deleting:
        pairs.append(MergePair(address(field('Source resource')), address(field('Destination resource'))))
    else:
        for value in objects(headings[0]):
            if set(value) != {'source', 'destination'}:
                raise ValueError('merge pair requires exactly source and destination')
            pairs.append(MergePair(address(value['source']), address(value['destination'])))
    if not pairs and not standalone and not deleting:
        raise ValueError('IMPORT merge requires nonempty pairs')
    scope = tuple(pairs[0].source.split('/')[:3]) if pairs else None
    sources, destinations = {p.source for p in pairs}, {p.destination for p in pairs}
    if deleting:
        scope = tuple(delete_sources[0].split('/')[:3])
    if len(sources) != len(pairs) or len(destinations) != len(pairs) or sources & destinations:
        raise ValueError('IMPORT merge requires disjoint unique source/destination sets')
    if any(tuple(value.split('/')[:3]) != scope for pair in pairs for value in (pair.source, pair.destination)):
        raise ValueError('IMPORT merge requires the same environment/target/service')
    references, positions = [], set()
    for value in objects(headings[1]):
        kind = value.get('field')
        keys = {'consumer', 'field', 'source', 'destination'}
        if kind in {'value', 'document'}:
            keys.add('property')
        if kind == 'document' or action == 'import-retarget' and kind == 'value' and 'pointer' in value:
            keys.add('pointer')
        if kind not in {'value', 'document', 'parentReference'} or set(value) != keys:
            raise ValueError('invalid reference fields')
        consumer, source, destination = (address(value[k]) for k in ('consumer', 'source', 'destination'))
        if standalone and scope is None:
            scope = tuple(consumer.split('/')[:3])
        if tuple(consumer.split('/')[:2]) != scope[:2] or consumer in sources or consumer in delete_sources:
            raise ValueError('reference consumer must remain in the same environment/target')
        if standalone and (kind == 'parentReference' or source == destination or any(tuple(a.split('/')[:2]) != scope[:2] for a in (source, destination))):
            raise ValueError('standalone retarget requires distinct producers and a configuration Property in the same target')
        if deleting and (source not in delete_sources or destination in delete_sources or tuple(destination.split('/')[:2]) != scope[:2]):
            raise ValueError('deletion reference repair must replace a declared deleted producer within the same target')
        if not standalone and not deleting and MergePair(source, destination) not in pairs and not (source == destination and source in destinations):
            raise ValueError('reference must match a registered pair or destination reevaluation')
        prop, pointer = value.get('property'), value.get('pointer')
        if kind != 'parentReference' and (not isinstance(prop, str) or not re.fullmatch(r'[A-Za-z0-9_]+\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+(?:\[[1-9][0-9]*\])?)+', prop)):
            raise ValueError('reference requires a formal Property')
        if (kind == 'document' or 'pointer' in value) and (not isinstance(pointer, str) or not pointer.startswith('/') or '*' in pointer or re.search(r'~(?![01])', pointer)):
            raise ValueError('reference requires a non-root RFC 6901 pointer')
        position = (consumer, kind, prop, pointer)
        if position in positions:
            raise ValueError('duplicate reference position')
        positions.add(position)
        references.append(ReferenceChange(consumer, kind, source, destination, prop, pointer))
    if standalone and any(ref.consumer in {a for r in references for a in (r.source, r.destination)} for ref in references):
        raise ValueError('retarget producers cannot also be edited consumers')
    if standalone and not references:
        raise ValueError('standalone retarget requires nonempty reference declarations')
    if deleting:
        if headings[1] in present and not references:
            raise ValueError('Model reference changes must be nonempty')
        from dataclasses import replace
        single = None
        if len(delete_sources) == 1:
            single = delete_sources[0]
        operation = ModelOperation(action, scope, references=tuple(references), delete_source=single, delete_sources=delete_sources)
        return replace(operation, detaches=model_refactor(text, operation=operation) or ())
    return ModelOperation(action, scope, tuple(pairs), tuple(references))


@dataclass(frozen=True)
class DependencyDetach:
    consumer: str
    producer: str
    key: str
    pointer: str | None = None


def model_refactor(text: str, *, operation=None) -> tuple[DependencyDetach, ...] | None:
    """Opt-in design declaration, independent of Model operation and ordinary design."""
    from iac_values import strict_json
    lines = section(text, '## Task contract')
    heading = '## Model dependency detach'
    reserved = [line for line in lines if re.match(r'-\s*Model refactor\b', line)]
    headings = [line for line in text.splitlines() if re.match(r'##\s+Model dependency detach\b', line)]
    if not reserved and not headings:
        return None
    from model_reference_usage import resource_address
    if reserved != ['- Model refactor: `value-preserving`'] or headings != [heading]:
        raise ValueError('invalid Model refactor declaration/section')
    for name, expected in [('Task type', 'design'), ('Workflow', 'update'),
                           ('AWS API execution', 'forbidden'), ('deploy/apply', 'forbidden')]:
        found = [line for line in lines if re.match(r'-\s*' + re.escape(name) + r'\b', line)]
        if found != ['- ' + name + ': `' + expected + '`']:
            raise ValueError('Model refactor requires ' + name + ': ' + expected)
    if operation is None:
        operation = model_operation(text)
    if operation is not None and operation.action != 'import-delete':
        raise ValueError('Model refactor cannot be combined with Model operation except import-delete')
    result, seen = [], set()
    for line in section(text, heading):
        if not line.startswith('- {') or not line.endswith('}'):
            raise ValueError('invalid Model dependency detach JSON entry')
        value = strict_json(line[2:])
        if not isinstance(value, dict) or set(value) not in ({'consumer', 'producer', 'key'}, {'consumer', 'producer', 'key', 'pointer'}):
            raise ValueError('detach requires consumer, producer, key and optional pointer')
        consumer, producer = resource_address(value['consumer']), resource_address(value['producer'])
        key, pointer = value['key'], value.get('pointer')
        if consumer[:2] != producer[:2] or consumer == producer:
            raise ValueError('detach requires distinct Resources in the same environment/target')
        if not isinstance(key, str) or not re.fullmatch(r'(?:desired|display)\.(?:row|resource)\.[0-9]{3,}(?:-[0-9]{3,})?\.[A-Za-z][A-Za-z0-9]*', key):
            raise ValueError('detach requires an exact expanded Model key')
        parts = key.split('.')
        owner = parts[2].rpartition('-')[0] if parts[1] == 'row' else parts[2]
        if owner != consumer[3]:
            raise ValueError('detach key does not belong to its consumer')
        if 'pointer' in value and (not isinstance(pointer, str) or not pointer.startswith('/') or re.search(r'~(?![01])', pointer) or not key.endswith('.document')):
            raise ValueError('detach pointer requires a document scalar RFC 6901 path')
        if operation is not None and (value['producer'] not in operation.delete_sources or value['consumer'] in operation.delete_sources):
            raise ValueError('deletion detach must repair a surviving consumer of a deleted producer')
        record = DependencyDetach(value['consumer'], value['producer'], key, pointer)
        if record in seen or any(r.consumer == record.consumer and r.producer == record.producer and r.key == key
                                 and (r.pointer is None or pointer is None) for r in result):
            raise ValueError('duplicate/overlapping dependency detach')
        seen.add(record)
        result.append(record)
    if not result:
        raise ValueError('Model refactor requires nonempty dependency detach declarations')
    return tuple(result)


def final_model_task(text):
    """Only explicit Model operations/refactors share the final candidate composition."""
    return model_operation(text) is not None or model_refactor(text) is not None


_selected_tasks = ContextVar('selected_tasks', default={})


@contextmanager
def selected_task(root: Path, task_file: str | None):
    """Bind an explicit API selector for nested readers without mutating process environment."""
    token = _selected_tasks.set({**_selected_tasks.get(), root.resolve(): task_file})
    try:
        yield
    finally:
        _selected_tasks.reset(token)


def _selected_contract(root, selected=None):
    records = contracts(root)
    selected = selected or _selected_tasks.get().get(root.resolve()) or os.environ.get(SELECTOR)
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
        text = records[selected]
        if selected != "tasks/active.md" or section(text, "## Modified files"):
            validate_contract(root, selected, text, legacy=selected == "tasks/active.md", check_paths=False)
        return root / selected, text
    return root / "tasks/active.md", None


def contract_path(root, selected=None):
    """Read a valid contract in any status without granting execution permission."""
    path, text = _selected_contract(root, selected)
    if text is not None:
        validate_contract(root, path.relative_to(root).as_posix(), text, legacy=path.name == 'active.md')
    return path


def task_path(root, selected=None):
    path, text = _selected_contract(root, selected)
    if text is not None and status(text, path.name == 'active.md') == 'suspend':
        name = path.relative_to(root).as_posix()
        raise ValueError(f"suspend task cannot execute; resume with task_contract.py --task-file {name} --resume")
    return path


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
    if resuming and model_operation(text) is not None:
        from issue_gate import require_no_issues
        from validation_scope import active_scope
        require_no_issues(root, active_scope(root, contract_file=name), contract_file=name)
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
    if "- Workflow: `import`" in section(text, "## Task contract") or final_model_task(text):
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
