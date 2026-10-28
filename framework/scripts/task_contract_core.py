"""Select task contracts and manage their ordinary status transitions."""

import fnmatch
import hashlib
import os
import re
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import partial as _bind_framework_callback
from pathlib import Path, PurePosixPath
from types import MappingProxyType

import utils.json_format as _imports_utils_json_format
from utils.file_operations import atomic_files
from utils.function_wrapper import FunctionWrapper
from utils.input_cache import (
    digest_files as digest_files,
)
from utils.input_cache import (
    input_bytes,
    input_context,
    input_is_dir,
    input_is_file,
    input_is_symlink,
    input_select,
    memoized,
    recording_inputs,
)
from utils.input_cache import (
    input_text as input_text,
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
    return (
        path == pattern
        or (pattern.endswith("/**") and path.startswith(pattern[:-3] + "/"))
        or fnmatch.fnmatchcase(path, pattern)
    )


def issues_save_only(root, *, scope=..., text=None, paths=(), contract_file=None):
    """Identify scoped report-only saving and validation."""
    with task_reads(root):
        snapshot = task_snapshot(
            root, contract_file, required=False, executable=contract_file is None
        )
        if snapshot is None:
            return False
        prompt = snapshot.path
        text = text if text is not None else snapshot.text
        types = [
            line
            for line in section(text, "## Task contract")
            if line.startswith("- Task type:")
        ]
        if types != ["- Task type: `migration`"]:
            return False
        if scope is ...:
            scope = active_scope(root, contract_file=contract_file)
        if not scope:
            return False
        reports = {
            f"issues/{env}/{target}/{name}"
            for env, target, _ in scope
            for name in ("issues.md", "iac-issues.md")
        }
        permitted = reports | {prompt.relative_to(root).as_posix()}
        allowed = paths_in(text, "## Allowed paths")
        return bool(
            allowed & reports
            and allowed <= permitted
            and paths_in(text, "## Modified files") <= permitted
            and set(paths) <= permitted
        )


def relative_path(value):
    path = PurePosixPath(value)
    if (
        not value
        or not path.parts
        or path.is_absolute()
        or str(path) != value
        or ".." in path.parts
        or "\\" in value
        or any(char in value for char in "*?[]\x00\n\r")
        or path.parts[0] in {".git", ".lock"}
    ):
        raise ValueError(
            f"task path must be an exact repository-relative path: {value}"
        )
    return path


def safe_path(root, value):
    relative_path(value)
    candidate = root / value
    if any(
        parent.is_symlink()
        for parent in [candidate, *candidate.parents]
        if parent != root and parent.is_relative_to(root)
    ):
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


@dataclass(frozen=True)
class TaskSnapshot:
    name: str
    root: Path
    path: Path
    text: str
    raw: bytes
    raw_digest: str
    selector: tuple[str | None, str | None]

    @property
    def status(self) -> str:
        return status(self.text)

    @property
    def task_digest(self) -> str:
        return task_digest(self.text)

    @property
    def scope(self) -> frozenset[tuple[str, str, str]] | None:
        return _scope(self.text)


@dataclass(frozen=True)
class ContractSnapshot:
    root: Path
    tasks: tuple[TaskSnapshot, ...]
    selector: tuple


@dataclass
class _TaskReads:
    root: Path
    tasks: dict[str, TaskSnapshot]
    catalog: ContractSnapshot | None = None
    selector: tuple = ()
    read_depth: int = 0


_read_contracts = ContextVar("task_read_contracts", default=None)


def _selector(root: Path) -> tuple:
    return (_selected_tasks.get().get(root.resolve()), os.environ.get(SELECTOR))


def _read_task(root: Path, name: str) -> TaskSnapshot:
    if not TASK_NAME.fullmatch(name):
        raise ValueError(f"invalid task selector: {name}")
    path = safe_path(root, name)
    if not input_is_file(path):
        raise ValueError(f"selected task contract missing: {name}")
    raw = input_bytes(path)
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return TaskSnapshot(
        name, root, path, text, raw, hashlib.sha256(raw).hexdigest(), _selector(root)
    )


def _catalog(
    root: Path, retained: dict[str, TaskSnapshot] | None = None
) -> ContractSnapshot:
    directory = root / "tasks"
    if input_is_symlink(directory):
        raise ValueError("tasks directory must not use symlinks")
    tasks = []
    if input_is_dir(directory):
        for path in input_select(directory):
            name = path.relative_to(root).as_posix()
            if (
                not TASK_NAME.fullmatch(name)
                or input_is_symlink(path)
                or not input_is_file(path)
            ):
                raise ValueError(f"invalid task contract file: {name}")
            tasks.append(
                retained[name]
                if retained is not None and name in retained
                else _read_task(root, name)
            )
    return ContractSnapshot(root, tuple(tasks), _selector(root))


def contract_snapshot(root: Path) -> ContractSnapshot:
    current = _read_contracts.get()
    if current is not None and current.root == root:
        if current.catalog is None:
            current.catalog = _catalog(root, current.tasks)
            current.tasks.update((task.name, task) for task in current.catalog.tasks)
        return current.catalog
    return _catalog(root)


@contextmanager
def task_reads(
    root: Path,
    *,
    live: bool = False,
    snapshot: ContractSnapshot | TaskSnapshot | None = None,
):
    """Reuse bytes within one operation; live authorization always starts fresh."""
    current = _read_contracts.get()
    if not live and snapshot is None and current is not None and current.root == root:
        yield current
        return
    if snapshot is not None and snapshot.root != root:
        raise ValueError("task snapshot belongs to another repository")
    tasks = (
        snapshot.tasks
        if isinstance(snapshot, ContractSnapshot)
        else (() if snapshot is None else (snapshot,))
    )
    state = _TaskReads(
        root,
        {task.name: task for task in tasks},
        snapshot if isinstance(snapshot, ContractSnapshot) else None,
        _selector(root),
    )
    token = _read_contracts.set(state)
    try:
        with input_context(), recording_inputs(None) if live else nullcontext():
            yield state
    finally:
        _read_contracts.reset(token)


@contextmanager
def contract_reads(
    root: Path, *, snapshot: ContractSnapshot | None = None, verify: bool = True
):
    """Pin the catalog once; workers can bind an immutable parent snapshot."""
    with task_reads(root, snapshot=snapshot) as current:
        owner = current.read_depth == 0
        current.read_depth += 1
        try:
            captured = contract_snapshot(root)
            yield captured
            if verify and owner:
                verify_snapshot(captured)
        finally:
            current.read_depth -= 1


def verify_snapshot(
    snapshot: TaskSnapshot | ContractSnapshot, *, selector: tuple | None = None
) -> None:
    """Read live bytes once, outside a GenerationInputs recorder."""
    with recording_inputs(None):
        if selector is not None and selector != _selector(snapshot.root):
            raise ValueError("task selection changed during validation")
        if snapshot.selector != _selector(snapshot.root):
            raise ValueError("task selection changed during validation")
        if isinstance(snapshot, ContractSnapshot):
            current = _catalog(snapshot.root)
            before = tuple((task.name, task.raw_digest) for task in snapshot.tasks)
            after = tuple((task.name, task.raw_digest) for task in current.tasks)
            if before != after:
                raise ValueError("task contracts changed during validation")
        elif _read_task(snapshot.root, snapshot.name) != snapshot:
            raise ValueError("task contract changed during validation")


def verify_contract_reads(root: Path) -> None:
    current = _read_contracts.get()
    if current is not None and current.root == root:
        if current.catalog is not None:
            verify_snapshot(current.catalog)
        else:
            for snapshot in current.tasks.values():
                verify_snapshot(snapshot, selector=current.selector)


def _invoke_contract_read_scope(function, /, root, *args, **kwargs):
    with contract_reads(root):
        return function(root, *args, **kwargs)


def contract_read_scope(function):
    return FunctionWrapper(function, _invoke_contract_read_scope)


def _invoke_task_read_scope(function, root_for, /, *args, **kwargs):
    root = (
        root_for(*args, **kwargs)
        if root_for is not None
        else args[0]
        if args
        else kwargs["root"]
    )
    with task_reads(root) if root is not None else nullcontext():
        return function(*args, **kwargs)


def task_read_scope(function=None, *, root=None):
    """Own one operation's reads; resolve non-root API arguments before memoization."""
    if function is None:
        return _bind_framework_callback(task_read_scope, root=root)
    return FunctionWrapper(function, _invoke_task_read_scope, root)


def contracts(root):
    return {task.name: task.text for task in contract_snapshot(root).tasks}


def _contracts(root):
    return {task.name: task.text for task in _catalog(root).tasks}


@memoized
def status(text):
    entries = [
        line
        for line in section(text, "## Task contract")
        if line.startswith("- Task status:")
    ]
    if len(entries) != 1 or entries[0] not in {
        f"- Task status: `{state}`" for state in ("running", "suspend", "completed")
    }:
        raise ValueError("Task status must be exactly one of running/suspend/completed")
    if entries[0] == "- Task status: `suspend`" and not section(
        text, "## Suspension reason"
    ):
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
        if value not in allowed and not any(
            matches(value, pattern) for pattern in allowed
        ):
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
        if self.action == "model-delete":
            return frozenset(
                tuple(source.split("/")[:3]) for source in self.delete_sources
            )
        return frozenset({self.scope})

    @property
    def scopes(self):
        return (
            self.source_scopes
            | frozenset(tuple(ref.consumer.split("/")[:3]) for ref in self.references)
            | frozenset(
                tuple(detach.consumer.split("/")[:3]) for detach in self.detaches
            )
        )


def _model_operation_address(value):
    if not isinstance(value, str) or not re.fullmatch(
        "(?:[a-z0-9]+(?:[-_][a-z0-9]+)*/){3}[0-9]{3,}", value
    ):
        raise ValueError(
            "Model operation requires exact environment/target/service/fixed Resource IDs"
        )
    return value


def _callback_model_operation_objects(records, strict_json, /, heading):
    for line in records.get(heading, ()):
        if not line.startswith("- {") or not line.endswith("}"):
            raise ValueError("invalid Model operation JSON entry: " + line)
        value = strict_json(line[2:])
        if not isinstance(value, dict):
            raise ValueError("Model operation entry must be an object")
        yield value


def _callback_model_operation_field(lines, /, name, required=True):
    selected = [line for line in lines if line.startswith("- " + name + ":")]
    if not selected and not required:
        return None
    match = (
        re.fullmatch(r"- " + re.escape(name) + r": `([^`]+)`", selected[0])
        if len(selected) == 1
        else None
    )
    if match is None:
        raise ValueError("Model-only update requires exactly one " + name)
    return match[1]


@memoized
def model_operation(text: str) -> ModelOperation | None:
    """Parse only reserved operation declarations; never expand or read Model sources."""
    strict_json = _imports_utils_json_format.policy_json
    lines = section(text, "## Task contract")
    fields = ("Model operation",)
    headings = (
        "## Model merge pairs",
        "## Model reference changes",
        "## Model delete sources",
    )
    reserved = [
        line
        for line in lines
        if any(re.match(r"-\s*" + name + r"\b", line) for name in fields)
    ]
    present = {heading for heading in headings if heading in text.splitlines()}
    # Detect malformed reserved headings too, without constraining ordinary prose.
    for line in text.splitlines():
        if (
            re.match(
                r"##\s+Model (merge pairs|reference changes|delete sources)\b", line
            )
            and line not in headings
        ):
            raise ValueError("invalid Model operation section: " + line)
    records = {heading: section(text, heading) for heading in present}
    if not reserved and not present:
        return None
    for line in reserved:
        if not any(re.fullmatch(r"- " + name + r": `[^`]+`", line) for name in fields):
            raise ValueError("invalid Model operation declaration: " + line)
    field = _bind_framework_callback(_callback_model_operation_field, lines)

    address = _model_operation_address

    objects = _bind_framework_callback(
        _callback_model_operation_objects, records, strict_json
    )

    if field("Task type") != "design" or field("Workflow") != "update":
        raise ValueError("Model-only operations require the design /update workflow")
    if (
        field("AWS API execution") != "forbidden"
        or field("deploy/apply") != "forbidden"
    ):
        raise ValueError("Model-only operations forbid AWS and deploy/apply")
    action = field("Model operation")
    if action == "import-delete":
        action = "model-delete"
    if action not in {"import-merge", "model-delete", "import-retarget"}:
        raise ValueError("unknown Model-only operation")
    deleting = action == "model-delete"
    delete_sources = ()
    if deleting:
        if headings[0] in present:
            raise ValueError("Model deletion has no merge pairs")
        delete_sources = tuple(
            sorted(address(value) for value in paths_in(text, headings[2]))
        )
        if len({tuple(value.split("/")[:2]) for value in delete_sources}) != 1:
            raise ValueError("Model deletion requires the same environment/target")
    elif headings[2] in present:
        raise ValueError("Model delete sources requires model-delete")
    standalone = action == "import-retarget"
    if standalone and headings[0] in present:
        raise ValueError("standalone retarget has no merge pairs")
    pairs = []
    for value in objects(headings[0]):
        if set(value) != {"source", "destination"}:
            raise ValueError("merge pair requires exactly source and destination")
        pairs.append(MergePair(address(value["source"]), address(value["destination"])))
    if not pairs and not standalone and not deleting:
        raise ValueError("IMPORT merge requires nonempty pairs")
    scope = tuple(pairs[0].source.split("/")[:3]) if pairs else None
    sources, destinations = {p.source for p in pairs}, {p.destination for p in pairs}
    if deleting:
        scope = tuple(delete_sources[0].split("/")[:3])
    if (
        len(sources) != len(pairs)
        or len(destinations) != len(pairs)
        or sources & destinations
    ):
        raise ValueError(
            "IMPORT merge requires disjoint unique source/destination sets"
        )
    if any(
        tuple(value.split("/")[:3]) != scope
        for pair in pairs
        for value in (pair.source, pair.destination)
    ):
        raise ValueError("IMPORT merge requires the same environment/target/service")
    references, positions = [], set()
    for value in objects(headings[1]):
        kind = value.get("field")
        keys = {"consumer", "field", "source", "destination"}
        if kind in {"value", "document"}:
            keys.add("property")
        if (
            kind == "document"
            or action == "import-retarget"
            and kind == "value"
            and "pointer" in value
        ):
            keys.add("pointer")
        if kind not in {"value", "document", "parentReference"} or set(value) != keys:
            raise ValueError("invalid reference fields")
        consumer, source, destination = (
            address(value[k]) for k in ("consumer", "source", "destination")
        )
        if standalone and scope is None:
            scope = tuple(consumer.split("/")[:3])
        if (
            tuple(consumer.split("/")[:2]) != scope[:2]
            or consumer in sources
            or consumer in delete_sources
        ):
            raise ValueError(
                "reference consumer must remain in the same environment/target"
            )
        if standalone and (
            kind == "parentReference"
            or source == destination
            or any(tuple(a.split("/")[:2]) != scope[:2] for a in (source, destination))
        ):
            raise ValueError(
                "standalone retarget requires distinct producers and a configuration Property in the same target"
            )
        if deleting and (
            source not in delete_sources
            or destination in delete_sources
            or tuple(destination.split("/")[:2]) != scope[:2]
        ):
            raise ValueError(
                "deletion reference repair must replace a declared deleted producer within the same target"
            )
        if (
            not standalone
            and not deleting
            and MergePair(source, destination) not in pairs
            and not (source == destination and source in destinations)
        ):
            raise ValueError(
                "reference must match a registered pair or destination reevaluation"
            )
        prop, pointer = value.get("property"), value.get("pointer")
        if kind != "parentReference" and (
            not isinstance(prop, str)
            or not re.fullmatch(
                r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+(?:\[[1-9][0-9]*\])?)+",
                prop,
            )
        ):
            raise ValueError("reference requires a formal Property")
        if (kind == "document" or "pointer" in value) and (
            not isinstance(pointer, str)
            or not pointer.startswith("/")
            or "*" in pointer
            or re.search(r"~(?![01])", pointer)
        ):
            raise ValueError("reference requires a non-root RFC 6901 pointer")
        position = (consumer, kind, prop, pointer)
        if position in positions:
            raise ValueError("duplicate reference position")
        positions.add(position)
        references.append(
            ReferenceChange(consumer, kind, source, destination, prop, pointer)
        )
    if standalone and any(
        ref.consumer in {a for r in references for a in (r.source, r.destination)}
        for ref in references
    ):
        raise ValueError("retarget producers cannot also be edited consumers")
    if standalone and not references:
        raise ValueError("standalone retarget requires nonempty reference declarations")
    if deleting:
        if headings[1] in present and not references:
            raise ValueError("Model reference changes must be nonempty")
        operation = ModelOperation(
            action, scope, references=tuple(references), delete_sources=delete_sources
        )
        return replace(
            operation, detaches=model_refactor(text, operation=operation) or ()
        )
    return ModelOperation(action, scope, tuple(pairs), tuple(references))


@dataclass(frozen=True)
class DependencyDetach:
    consumer: str
    producer: str
    key: str
    pointer: str | None = None


@memoized
def model_refactor(text: str, *, operation=None) -> tuple[DependencyDetach, ...] | None:
    """Opt-in design declaration, independent of Model operation and ordinary design."""
    strict_json = _imports_utils_json_format.policy_json
    lines = section(text, "## Task contract")
    heading = "## Model dependency detach"
    reserved = [line for line in lines if re.match(r"-\s*Model refactor\b", line)]
    headings = [
        line
        for line in text.splitlines()
        if re.match(r"##\s+Model dependency detach\b", line)
    ]
    if not reserved and not headings:
        return None
    if reserved != ["- Model refactor: `value-preserving`"] or headings != [heading]:
        raise ValueError("invalid Model refactor declaration/section")
    for name, expected in [
        ("Task type", "design"),
        ("Workflow", "update"),
        ("AWS API execution", "forbidden"),
        ("deploy/apply", "forbidden"),
    ]:
        found = [
            line for line in lines if re.match(r"-\s*" + re.escape(name) + r"\b", line)
        ]
        if found != ["- " + name + ": `" + expected + "`"]:
            raise ValueError("Model refactor requires " + name + ": " + expected)
    if operation is None:
        operation = model_operation(text)
    if operation is not None and operation.action != "model-delete":
        raise ValueError(
            "Model refactor cannot be combined with Model operation except model-delete"
        )
    result, seen = [], set()
    for line in section(text, heading):
        if not line.startswith("- {") or not line.endswith("}"):
            raise ValueError("invalid Model dependency detach JSON entry")
        value = strict_json(line[2:])
        if not isinstance(value, dict) or set(value) not in (
            {"consumer", "producer", "key"},
            {"consumer", "producer", "key", "pointer"},
        ):
            raise ValueError(
                "detach requires consumer, producer, key and optional pointer"
            )
        consumer, producer = (
            resource_address(value["consumer"]),
            resource_address(value["producer"]),
        )
        key, pointer = value["key"], value.get("pointer")
        if consumer[:2] != producer[:2] or consumer == producer:
            raise ValueError(
                "detach requires distinct Resources in the same environment/target"
            )
        if not isinstance(key, str) or not re.fullmatch(
            r"(?:desired|display)\.(?:row|resource)\.[0-9]{3,}(?:-[0-9]{3,})?\.[A-Za-z][A-Za-z0-9]*",
            key,
        ):
            raise ValueError("detach requires an exact expanded Model key")
        parts = key.split(".")
        owner = parts[2].rpartition("-")[0] if parts[1] == "row" else parts[2]
        if owner != consumer[3]:
            raise ValueError("detach key does not belong to its consumer")
        if "pointer" in value and (
            not isinstance(pointer, str)
            or not pointer.startswith("/")
            or re.search(r"~(?![01])", pointer)
            or not key.endswith(".document")
        ):
            raise ValueError("detach pointer requires a document scalar RFC 6901 path")
        if operation is not None and (
            value["producer"] not in operation.delete_sources
            or value["consumer"] in operation.delete_sources
        ):
            raise ValueError(
                "deletion detach must repair a surviving consumer of a deleted producer"
            )
        record = DependencyDetach(value["consumer"], value["producer"], key, pointer)
        if record in seen or any(
            r.consumer == record.consumer
            and r.producer == record.producer
            and r.key == key
            and (r.pointer is None or pointer is None)
            for r in result
        ):
            raise ValueError("duplicate/overlapping dependency detach")
        seen.add(record)
        result.append(record)
    if not result:
        raise ValueError(
            "Model refactor requires nonempty dependency detach declarations"
        )
    return tuple(result)


def final_framework_task(text, changed_paths=()):
    """Use the existing explicit Framework scope only for Framework-only work."""
    contract = section(text, "## Task contract")
    if not any(
        f"- Task type: `{kind}`" in contract
        for kind in ("governance", "catalog-maintenance", "migration")
    ) or section(text, "## Validation scope") != ["- `framework`"]:
        return False
    declared = paths_in(text, "## Modified files")
    owned_files = {
        ".gitattributes",
        ".gitignore",
        ".github/workflows/framework-it.yml",
        ".github/workflows/python-quality.yml",
        "AGENTS.md",
        "CMD.md",
        "README.md",
        "docs/system-overview.md",
        "pyproject.toml",
    }
    changed = set(changed_paths() if callable(changed_paths) else changed_paths)
    return (
        bool(changed)
        and changed <= declared
        and all(
            p in owned_files or p.startswith(("framework/", ".agents/", "tasks/"))
            for p in declared
        )
        and all(
            p in owned_files or p.startswith(("framework/", ".agents/"))
            for p in changed
        )
    )


def final_model_task(text, changed_paths=()):
    """Select the final candidate path only for an authorized Model-only change."""
    operation = model_operation(text)
    refactor = model_refactor(text, operation=operation)
    if operation is not None or refactor is not None:
        return True
    lines = section(text, "## Task contract")
    for name, value in (
        ("Task type", "design"),
        ("Workflow", "update"),
        ("AWS API execution", "forbidden"),
        ("deploy/apply", "forbidden"),
    ):
        if [
            line for line in lines if re.match(r"-\s*" + re.escape(name) + r"\b", line)
        ] != [f"- {name}: `{value}`"]:
            return False
    declared = paths_in(text, "## Modified files")
    changed = set(changed_paths() if callable(changed_paths) else changed_paths)
    return (
        bool(changed & declared)
        and any(
            p.startswith("model/") and p.endswith(".properties")
            for p in changed & declared
        )
        and changed <= declared
        and all(
            (p.startswith("model/") and p.endswith(".properties"))
            or (p.startswith("docs/designs/") and p.endswith((".md", ".json")))
            or TASK_NAME.fullmatch(p) is not None
            for p in declared | changed
        )
    )


_selected_tasks = ContextVar("selected_tasks", default=MappingProxyType({}))


@contextmanager
def selected_task(root: Path, task_file: str | None):
    """Bind an explicit API selector for nested readers without mutating process environment."""
    token = _selected_tasks.set({**_selected_tasks.get(), root.resolve(): task_file})
    try:
        yield
    finally:
        _selected_tasks.reset(token)


def read_task_snapshot(root: Path, name: str, *, live: bool = False) -> TaskSnapshot:
    """Acquire raw Task data; lifecycle callers retain their own validation boundaries."""
    if live:
        with task_reads(root, live=True):
            return read_task_snapshot(root, name)
    current = _read_contracts.get()
    snapshot = (
        current.tasks.get(name)
        if current is not None and current.root == root
        else None
    )
    if snapshot is None:
        if current is not None and current.root == root and current.catalog is not None:
            selected_text(
                root, {task.name: task.text for task in current.catalog.tasks}, name
            )
        snapshot = _read_task(root, name)
        if current is not None and current.root == root:
            current.tasks[name] = snapshot
    return snapshot


def task_snapshot(
    root: Path,
    selected: str | None = None,
    *,
    required: bool = True,
    executable: bool = True,
    check_paths: bool | None = None,
    live: bool = False,
) -> TaskSnapshot | None:
    if live:
        with task_reads(root, live=True):
            return task_snapshot(
                root,
                selected,
                required=required,
                executable=executable,
                check_paths=check_paths,
            )
    selected = (
        selected
        or _selected_tasks.get().get(root.resolve())
        or os.environ.get(SELECTOR)
    )
    if selected:
        snapshot = read_task_snapshot(root, selected)
    else:
        catalog = contract_snapshot(root)
        path, _ = _select_contract(
            root, None, {task.name: task.text for task in catalog.tasks}
        )
        snapshot = next((task for task in catalog.tasks if task.path == path), None)
    if snapshot is not None:
        validate_contract(
            root,
            snapshot.name,
            snapshot.text,
            check_paths=not executable if check_paths is None else check_paths,
        )
        if executable and snapshot.status == "suspend":
            raise ValueError(
                f"suspend task cannot execute; resume with task_contract.py --task-file {snapshot.name} --resume"
            )
    elif required:
        raise ValueError("selected task contract required")
    return snapshot


def _selected_contract(root, selected=None, *, allow_empty=False):
    if allow_empty and not input_is_dir(root / "tasks"):
        return None, None
    snapshot = task_snapshot(
        root, selected, required=False, executable=False, check_paths=False
    )
    return (snapshot.path, snapshot.text) if snapshot is not None else (None, None)


def _select_contract(root, selected, records):
    if selected:
        text = selected_text(root, records, selected)
    else:
        running = [name for name, text in records.items() if status(text) == "running"]
        if len(running) > 1:
            raise ValueError(
                f"multiple running tasks; select a contract with {SELECTOR} or --task-file"
            )
        selected = running[0] if running else None
        text = records[selected] if selected else None
    if text is not None:
        validate_contract(root, selected, text, check_paths=False)
    return (root / selected, text) if selected else (None, None)


def contract_path(root, selected=None, *, required=True):
    """Read a valid contract in any status without granting execution permission."""
    snapshot = task_snapshot(root, selected, required=required, executable=False)
    return snapshot.path if snapshot is not None else None


def task_path(root, selected=None, *, required=True):
    snapshot = task_snapshot(root, selected, required=required)
    return snapshot.path if snapshot is not None else None


def task_revision(root, selected=None, *, live=False):
    """Pin the already acquired planning content."""
    snapshot = task_snapshot(root, selected, required=False, live=live)
    return (snapshot.name, snapshot.text) if snapshot is not None else (None, None)


def invalidate_task_reads(root: Path) -> None:
    current = _read_contracts.get()
    if current is not None and current.root == root:
        current.tasks.clear()
        current.catalog = None


def start(root, name, text):
    if not TASK_NAME.fullmatch(name):
        raise ValueError("new task must use tasks/<task-name>.md")
    with recording_inputs(None):
        records = _contracts(root)
    if name in records:
        selected_text(root, records, name)
        raise ValueError(f"task contract already exists: {name}")
    if status(text) != "running":
        raise ValueError("new task must have running status")
    validate_contract(root, name, text)
    destination = safe_path(root, name)
    destination.parent.mkdir(exist_ok=True)
    atomic_files({destination: text}, staging_directory=root)
    invalidate_task_reads(root)


def set_status(text, state):
    text = re.sub(r"^## Suspension reason\n.*?(?=^## |\Z)", "", text, flags=re.M | re.S)
    if any(
        line.startswith("- Task status:") for line in section(text, "## Task contract")
    ):
        prefix, body = text.split("## Task contract\n", 1)
        return (
            prefix
            + "## Task contract\n"
            + re.sub(
                r"^- Task status: `[^`]+`$",
                f"- Task status: `{state}`",
                body,
                count=1,
                flags=re.M,
            )
        )
    if "## Task contract" not in text.splitlines():
        text += "\n## Task contract\n"
    return text.replace(
        "## Task contract\n", f"## Task contract\n- Task status: `{state}`\n", 1
    )


def suspend(root, name, reason):
    if not reason.strip():
        raise ValueError("suspend requires a concrete reason")
    if not TASK_NAME.fullmatch(name):
        raise ValueError(f"invalid task selector: {name}")
    path = safe_path(root, name)
    with recording_inputs(None):
        text = _read_task(root, name).text
    if status(text) != "running":
        return False
    # Do not inspect other contracts when suspending this task.
    text = set_status(text, "suspend")
    text += (
        "\n## Suspension reason\n\n"
        + "\n".join(f"    {line}".rstrip() for line in reason.strip().splitlines())
        + "\n"
    )
    atomic_files({path: text}, staging_directory=root)
    invalidate_task_reads(root)
    return True


def active_scope(
    root: Path, full: bool = False, *, task_file=None, contract_file=None
) -> set[tuple[str, str, str]] | None:
    if full:
        return None
    with task_reads(root):
        snapshot = task_snapshot(
            root,
            contract_file or task_file,
            required=contract_file is not None,
            executable=contract_file is None,
        )
        if snapshot is None:
            if contracts(root):
                return set()
            raise ValueError(
                "validation scope missing: selected task contract; specify scope or --all"
            )
        scope = snapshot.scope
        return None if scope is None else set(scope)


@memoized
def _scope(text: str) -> frozenset[tuple[str, str, str]] | None:
    lines = text.splitlines()
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
        raise ValueError(
            "validation scope missing: specify environment/target-directory/service; no automatic full validation"
        )
    if selected == ["all"]:
        return None
    if selected == ["framework"]:
        if not any(
            line
            in {
                "- Task type: `governance`",
                "- Task type: `catalog-maintenance`",
                "- Task type: `migration`",
            }
            for line in lines
        ):
            raise ValueError("framework scope requires a framework task")
        return frozenset()
    scope = set()
    for value in selected:
        parts = value.split("/")
        if len(parts) != 3 or any(
            not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", part) for part in parts
        ):
            raise ValueError(
                f"invalid validation scope: {value}; expected environment/target-directory/service"
            )
        scope.add(tuple(parts))
    if len(scope) != len(selected):
        raise ValueError("duplicate validation scope entry")
    return frozenset(scope)


@memoized
def task_digest(text):
    # Human approval updates the existing contract, not deployment inputs/scope.
    text = set_status(text, "running").rstrip()
    text = "\n".join(
        line
        for line in text.splitlines()
        if not line.startswith(("- Authorized delete/replacement:", "- Task status:"))
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


TASK_TYPES = {
    "initialization",
    "design",
    "infrastructure",
    "scenario-test",
    "governance",
    "catalog-maintenance",
    "migration",
}
