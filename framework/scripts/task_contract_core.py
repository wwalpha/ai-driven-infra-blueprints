"""Select task contracts and manage their ordinary status transitions."""

import fnmatch
import hashlib
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import partial as _bind_framework_callback
from pathlib import Path, PurePosixPath
from types import MappingProxyType

import utils.json_format as _imports_utils_json_format
from utils.file_operations import atomic_files
from utils.function_wrapper import FunctionWrapper
from utils.input_cache import (
    digest_files,
    input_bytes,
    input_is_dir,
    input_is_file,
    input_is_symlink,
    input_select,
    input_text,
    memoized,
    recording_inputs,
)
from utils.model_addresses import resource_address

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


def issues_save_only(root, *, scope=..., text=None, paths=()):
    """Share the scoped report-only exception between saving, validation and Issue Gate."""
    prompt = task_path(root, required=False)
    if prompt is None:
        return False
    text = text if text is not None else input_text(prompt, encoding="utf-8")
    types = [line for line in section(text, "## Task contract") if line.startswith("- Task type:")]
    if types != ['- Task type: `migration`']:
        return False
    if scope is ...:
        scope = active_scope(root)
    if not scope:
        return False
    reports = {f"issues/{env}/{target}/{name}" for env, target, _ in scope
               for name in ("issues.md", "iac-issues.md")}
    permitted = reports | {prompt.relative_to(root).as_posix()}
    allowed = paths_in(text, "## Allowed paths")
    return bool(allowed & reports and allowed <= permitted
                and paths_in(text, "## Modified files") <= permitted and set(paths) <= permitted)


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


_read_contracts = ContextVar('task_read_contracts', default=None)


@contextmanager
def contract_reads(root):
    """Pin read-only validation inputs; authority writers must remain outside."""
    current = _read_contracts.get()
    if current is not None and current[0] == root:
        yield
        return
    records = _contracts(root)
    selector = (_selected_tasks.get(), os.environ.get(SELECTOR))
    paths = [root / name for name in records]
    digest = digest_files(root, paths, {path: input_bytes(path) for path in paths})
    token = _read_contracts.set((root, records, {}, selector, digest))
    try:
        yield
        verify_contract_reads(root)
    finally:
        _read_contracts.reset(token)


def verify_contract_reads(root):
    current = _read_contracts.get()
    if current is not None and current[0] == root:
        if current[3] != (_selected_tasks.get(), os.environ.get(SELECTOR)):
            raise ValueError('task selection changed during validation')
        # Compare live bytes/file sets even when generation has an input recorder.
        with recording_inputs(None):
            records = _contracts(root)
            if current[1] != records or current[4] != digest_files(root, [root / name for name in records]):
                raise ValueError('task contracts changed during validation')


def _invoke_contract_read_scope(function, /, root, *args, **kwargs):
    with contract_reads(root):
        return function(root, *args, **kwargs)


def contract_read_scope(function):
    wrapped = FunctionWrapper(function, _invoke_contract_read_scope)
    return wrapped


def contracts(root):
    current = _read_contracts.get()
    if current is not None and current[0] == root:
        return dict(current[1])
    return _contracts(root)


def _contracts(root):
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


def status(text):
    entries = [line for line in section(text, "## Task contract") if line.startswith("- Task status:")]
    if len(entries) != 1 or entries[0] not in {f"- Task status: `{state}`" for state in ("running", "suspend", "completed")}:
        raise ValueError("Task status must be exactly one of running/suspend/completed")
    if entries[0] == "- Task status: `suspend`" and not section(text, "## Suspension reason"):
        raise ValueError("suspend task must record a concrete Suspension reason")
    return entries[0].split("`")[1]


def validate_contract(root, name, text, *, check_paths=True):
    """Validate the selected contract declaration."""
    status(text)
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




def _model_operation_address(value):
    if not isinstance(value, str) or not re.fullmatch('(?:[a-z0-9]+(?:[-_][a-z0-9]+)*/){3}[0-9]{3,}', value):
        raise ValueError('IMPORT operation requires exact environment/target/service/fixed Resource IDs')
    return value


def _callback_model_operation_objects(records, strict_json, /, heading):
    for line in records.get(heading, ()):
        if not line.startswith('- {') or not line.endswith('}'):
            raise ValueError('invalid Model operation JSON entry: ' + line)
        value = strict_json(line[2:])
        if not isinstance(value, dict):
            raise ValueError('Model operation entry must be an object')
        yield value


def _callback_model_operation_field(lines, /, name, required=True):
    selected = [line for line in lines if line.startswith('- ' + name + ':')]
    if not selected and not required:
        return None
    match = re.fullmatch(r'- ' + re.escape(name) + r': `([^`]+)`', selected[0]) if len(selected) == 1 else None
    if match is None:
        raise ValueError('Model-only update requires exactly one ' + name)
    return match[1]


def model_operation(text: str) -> ModelOperation | None:
    """Parse only reserved operation declarations; never expand or read Model sources."""
    strict_json = _imports_utils_json_format.policy_json
    lines = section(text, '## Task contract')
    fields = ('Model operation',)
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
    field = _bind_framework_callback(_callback_model_operation_field, lines)

    address = _model_operation_address

    objects = _bind_framework_callback(_callback_model_operation_objects, records, strict_json)

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
        if headings[0] in present:
            raise ValueError('IMPORT deletion has no merge pairs')
        delete_sources = tuple(sorted(address(value) for value in paths_in(text, headings[2])))
        if len({tuple(value.split('/')[:2]) for value in delete_sources}) != 1:
            raise ValueError('IMPORT deletion requires the same environment/target')
    elif headings[2] in present:
        raise ValueError('Model delete sources requires import-delete')
    standalone = action == 'import-retarget'
    if standalone and headings[0] in present:
        raise ValueError('standalone retarget has no merge pairs')
    pairs = []
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
        operation = ModelOperation(action, scope, references=tuple(references), delete_sources=delete_sources)
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
    strict_json = _imports_utils_json_format.policy_json
    lines = section(text, '## Task contract')
    heading = '## Model dependency detach'
    reserved = [line for line in lines if re.match(r'-\s*Model refactor\b', line)]
    headings = [line for line in text.splitlines() if re.match(r'##\s+Model dependency detach\b', line)]
    if not reserved and not headings:
        return None
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


_selected_tasks = ContextVar('selected_tasks', default=MappingProxyType({}))


@contextmanager
def selected_task(root: Path, task_file: str | None):
    """Bind an explicit API selector for nested readers without mutating process environment."""
    token = _selected_tasks.set({**_selected_tasks.get(), root.resolve(): task_file})
    try:
        yield
    finally:
        _selected_tasks.reset(token)


def _selected_contract(root, selected=None):
    selected = selected or _selected_tasks.get().get(root.resolve()) or os.environ.get(SELECTOR)
    current = _read_contracts.get()
    if current is not None and current[0] == root:
        if selected not in current[2]:
            current[2][selected] = _select_contract(root, selected, current[1])
        return current[2][selected]
    return _select_contract(root, selected, contracts(root))


def _select_contract(root, selected, records):
    if selected:
        selected_text(root, records, selected)
    states = {name: status(text) for name, text in records.items()}
    if not selected:
        running = [name for name, state in states.items() if state == "running"]
        if len(running) > 1:
            raise ValueError(f"multiple running tasks; select a contract with {SELECTOR} or --task-file")
        selected = running[0] if running else None
    if selected:
        text = records[selected]
        validate_contract(root, selected, text, check_paths=False)
        return root / selected, text
    return None, None


def contract_path(root, selected=None, *, required=True):
    """Read a valid contract in any status without granting execution permission."""
    path, text = _selected_contract(root, selected)
    if text is not None:
        validate_contract(root, path.relative_to(root).as_posix(), text)
    if required and path is None:
        raise ValueError("selected task contract required")
    return path


def task_path(root, selected=None, *, required=True):
    path, text = _selected_contract(root, selected)
    if text is not None and status(text) == 'suspend':
        name = path.relative_to(root).as_posix()
        raise ValueError(f"suspend task cannot execute; resume with task_contract.py --task-file {name} --resume")
    if required and path is None:
        raise ValueError("selected task contract required")
    return path


def task_revision(root, selected=None):
    """Pin task planning content so later changes invalidate the plan."""
    path = task_path(root, selected, required=False)
    if path is None:
        return None, None
    text = path.read_text(encoding="utf-8") if path.is_file() else None
    return path.relative_to(root).as_posix(), text


def start(root, name, text):
    if not TASK_NAME.fullmatch(name):
        raise ValueError("new task must use tasks/<task-name>.md")
    records = contracts(root)
    if name in records:
        selected_text(root, records, name)
        raise ValueError(f"task contract already exists: {name}")
    if status(text) != "running":
        raise ValueError("new task must have running status")
    validate_contract(root, name, text)
    destination = safe_path(root, name)
    destination.parent.mkdir(exist_ok=True)
    atomic_files({destination: text}, staging_directory=root)






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
    if status(text) != "running":
        return False
    # Do not inspect other contracts when suspending this task.
    text = set_status(text, "suspend")
    text += "\n## Suspension reason\n\n" + "\n".join(f"    {line}".rstrip() for line in reason.strip().splitlines()) + "\n"
    atomic_files({path: text}, staging_directory=root)
    return True








def active_scope(root: Path, full: bool = False, *, task_file=None, contract_file=None) -> set[tuple[str, str, str]] | None:
    if full:
        return None
    path = contract_path(root, selected=contract_file) if contract_file is not None else task_path(root, selected=task_file, required=False)
    if path is None:
        if contracts(root):
            return set()  # All registered tasks are completed; retain shared idle checks.
        raise ValueError("validation scope missing: selected task contract; specify scope or --all")
    lines = input_text(path, encoding="utf-8").splitlines()
    selected = []
    inside = False
    found = False
    for line in lines:
        if line == "## Validation scope":
            if found:
                raise ValueError("duplicate Validation scope section")
            inside = True
            found = True
        elif line.startswith("## "):
            inside = False
        elif inside and line.strip():
            match = re.fullmatch(r"- `([^`]+)`", line)
            if not match:
                raise ValueError(f"invalid validation scope: {line}")
            selected.append(match.group(1))
    if not selected:
        raise ValueError("validation scope missing: specify environment/target-directory/service; no automatic full validation")
    if selected == ["all"]:
        return None
    if selected == ["framework"]:
        if not any(line in {"- Task type: `governance`", "- Task type: `catalog-maintenance`", "- Task type: `migration`"} for line in lines):
            raise ValueError("framework scope requires a framework task")
        return set()
    scope = set()
    for value in selected:
        parts = value.split("/")
        if len(parts) != 3 or any(not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", part) for part in parts):
            raise ValueError(f"invalid validation scope: {value}; expected environment/target-directory/service")
        scope.add(tuple(parts))
    if len(scope) != len(selected):
        raise ValueError("duplicate validation scope entry")
    return scope



def task_digest(text):
    # Human approval updates the existing contract, not deployment inputs/scope.
    text = set_status(text, 'running').rstrip()
    text = '\n'.join(line for line in text.splitlines() if not line.startswith(('- Authorized delete/replacement:', '- Task status:')))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


TASK_TYPES = {
    "initialization",
    "design",
    "infrastructure",
    "scenario-test",
    "governance",
    "catalog-maintenance",
    "migration",
}
