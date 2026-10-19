"""Raw source locations and rollback-protected publication, independent of expansion."""
from __future__ import annotations
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from collections.abc import Mapping, Callable
from typing import Protocol, TYPE_CHECKING
from validation_cache import (input_exists, input_is_dir, input_is_file, input_is_symlink,
                              input_select, input_text, memo_table, recording_inputs)
from iac_values import unique_object, invalid_constant
from sync_progress import phase, thread_lock
import sync_files

if TYPE_CHECKING:
    from sync_runtime import GenerationInputs
    from task_contract import ModelOperation

_locks = {}
_guard = threading.Lock()
_local = threading.local()

def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def json_read(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} requires exactly {sorted(keys)}")



def source_paths(path):
    path = path.absolute()
    if (len(path.parents) < 4 or path.parents[2].name != "model" or
            path.suffix != '.properties' or path.parents[1].name in {'parameters', 'templates'}):
        return None
    root = path.parents[3]
    env, alias, filename = path.relative_to(root / "model").parts
    if any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', item) for item in (env, alias, path.stem)):
        return None
    directory = root / "model/parameters" / env / alias / path.stem
    return root, root / "model/templates" / alias / (filename + ".tpl"), directory


def safe(root, path):
    if not path.is_relative_to(root) or any(input_is_symlink(p) for p in [path, *path.parents] if p.is_relative_to(root)):
        raise ValueError(f"unsafe Model source path: {path}")


@contextmanager
def publication_lock(root, *, read_only=False):
    """OS releases the lock on process exit; restore an interrupted batch before reads."""
    key = str(root.resolve())
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    with thread_lock(lock):
        depths = getattr(_local, 'depths', {})
        _local.depths = depths
        if key in depths:
            yield depths[key]
            return
        directory = Path(tempfile.gettempdir()) / 'blueprint-model-publication'
        directory.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(key.encode()).hexdigest()
        journal = directory / (name + '.json')
        with (directory / (name + '.lock')).open('a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    with phase("publication-lock", status="lock-wait"):
                        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    with phase("publication-lock", status="lock-wait"):
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            depths[key] = journal
            try:
                if journal.is_file():
                    if read_only:
                        raise ValueError('pending Model publication recovery; read-only analysis stopped')
                    record = json_read(journal.read_text(encoding='utf-8'))
                    exact(record, {'root', 'originals'}, 'publication journal')
                    if record['root'] != key:
                        raise ValueError('publication journal root mismatch')
                    originals = {}
                    for relative, data in record['originals'].items():
                        candidate = root / relative
                        if Path(relative).is_absolute() or '..' in Path(relative).parts:
                            raise ValueError('unsafe publication journal')
                        safe(root, candidate)
                        originals[candidate] = None if data is None else base64.b64decode(data, validate=True)
                    sync_files.restore_files(originals)
                    if memo_table() is not None:
                        memo_table().clear()
                    journal.unlink()
                yield journal
            finally:
                del depths[key]
                if os.name == 'nt':
                    stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)



def _publish_transaction(root, output, obsolete, journal, *, originals=None, finish=None):
    """Journal and rollback shared by guarded publication and validated generation plans.

    The caller holds publication_lock and owns authorization/input validation. A supplied
    originals map is the already compared generation plan, including only changed files.
    """
    planned = originals is not None
    if originals is None:
        originals = {p: p.read_bytes() if p.is_file() else None for p in set(output) | set(obsolete)}
    record = {'root': str(root.resolve()), 'originals': {p.relative_to(root).as_posix():
              None if data is None else base64.b64encode(data).decode() for p, data in originals.items()}}
    temporary = journal.with_suffix('.pending')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(json_text(record)); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, journal)
    if memo_table() is not None:
        memo_table().clear()
    try:
        if planned:
            for path, content in output.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8', newline='')
        else:
            sync_files.save_files(output)
        for path in obsolete:
            path.unlink(missing_ok=True)
        if finish is not None:
            finish()
    except (OSError, ValueError):
        sync_files.restore_files(originals)
        journal.unlink()
        raise
    journal.unlink()



def parameter_files(directory):
    if input_exists(directory/'parameters.json'):
        raise ValueError(f'unsupported JSON Model inputs: {directory / "parameters.json"}')
    return [directory/'parameters.yaml', directory/'bindings.json']



def consumers(root, alias, service):
    result = set()
    for path in input_select(root / 'model/parameters', '*/' + alias + '/' + service):
        safe(root, path)
        environment = path.parent.parent.name
        if not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', environment) or not input_is_dir(path):
            raise ValueError('invalid registered Model consumer')
        result.add((environment, alias, service))
    return result


MAX_LINES = 600
PART_LINES = 550
INDEX_HEADER = "# model-index: 1"
PART_PREFIX = "# part: "


def model_parts(path: Path, *, text: str | None = None, read_context: SourceReadContext | None = None) -> list[Path]:
    is_symlink = (lambda p: read_context.kind(p) == 'symlink') if read_context else input_is_symlink
    is_file = (lambda p: read_context.kind(p) == 'file') if read_context else input_is_file
    select = read_context.select if read_context else input_select
    if is_symlink(path) or is_symlink(path.with_suffix("")):
        raise ValueError(f"model files must not use symlinks: {path}")
    lines = ((read_context.read(path).decode("utf-8") if read_context else input_text(path, encoding="utf-8")) if text is None else text).splitlines()
    indexed = bool(lines and lines[0] == INDEX_HEADER)
    if any(line.startswith(("# model-index:", PART_PREFIX)) for line in lines) and not indexed:
        raise ValueError(f"invalid model index: {path}")
    parts = []
    if indexed:
        if len(lines) > MAX_LINES or any(line.strip() and not line.startswith("#") for line in lines):
            raise ValueError(f"model index must contain comments only, at most {MAX_LINES} lines: {path}")
        for line in lines[1:]:
            if not line.startswith(PART_PREFIX):
                continue
            expected = f"{path.stem}/part-{len(parts) + 1:03d}.properties"
            if line.removeprefix(PART_PREFIX) != expected:
                raise ValueError(f"invalid or duplicate model part; expected {expected}: {path}")
            part = path.parent / expected
            if is_symlink(part) or not is_file(part):
                raise ValueError(f"missing or unsafe model part: {part}")
            parts.append(part)
        if not parts:
            raise ValueError(f"model index has no parts: {path}")
    extras = set(select(path.with_suffix(""), "*.properties", recursive=True)) - set(parts)
    if extras:
        raise ValueError(f"unlisted model parts: {sorted(str(part) for part in extras)}")
    return parts if indexed else [path]


class SourceReadContext(Protocol):
    def read(self, path: Path) -> bytes | None: ...
    def kind(self, path: Path) -> str: ...
    def select(self, base: Path, pattern: str = '*', recursive: bool = False, kinds=None): ...


def read_sources(model_path: Path, *, read_context: SourceReadContext | None = None) -> Mapping[Path, str | None]:
    """Read registered raw inputs without expansion; missing optional observed is None.

    Required inputs/index errors raise ValueError/OSError. Entering publication_lock
    may recover an interrupted existing journal before the raw read (and write files).
    """
    location = source_paths(model_path)
    if location is None:
        raise ValueError('invalid logical Model path: ' + str(model_path))
    root, template, directory = location
    kind = read_context.kind if read_context else lambda p: 'symlink' if p.is_symlink() else 'file' if p.is_file() else 'dir' if p.is_dir() else 'missing'
    def check(path):
        if not path.is_relative_to(root) or any(kind(p) == 'symlink' for p in (path, *path.parents) if p.is_relative_to(root)):
            raise ValueError('unsafe Model source path: ' + str(path))
    with publication_lock(root):
        if kind(directory / 'parameters.json') != 'missing':
            raise ValueError('unsupported JSON Model inputs')
        paths = [template, directory / 'parameters.yaml', directory / 'bindings.json']
        for path in paths:
            check(path)
            if kind(path) != 'file':
                raise ValueError('required YAML Model input missing: ' + str(path))
        paths.extend(model_parts(template, read_context=read_context))
        paths.append(directory / 'observed.json')
        result = {}
        for path in paths:
            check(path)
            raw = read_context.read(path) if read_context else path.read_bytes() if path.is_file() else None
            result[path] = None if raw is None else raw.decode('utf-8')
        return result


class SourceWriteContext:
    """One-use authorized state. Obtain it only from import_guard.source_write_context."""
    root: Path
    snapshot: GenerationInputs
    operation: ModelOperation
    paths: frozenset[Path]
    closed: bool

    def __init__(self):
        raise TypeError('use import_guard.source_write_context')

    @classmethod
    def _authorized(cls, root: Path, snapshot: GenerationInputs, operation: ModelOperation,
                    require_current: Callable, paths: frozenset[Path]):
        context = object.__new__(cls)
        context.root, context.snapshot, context.operation = root, snapshot, operation
        context._require_current, context.paths = require_current, paths
        context.closed = False
        return context

    def close(self) -> None:
        self.closed = True
        self.snapshot.close()


def write_sources(context: SourceWriteContext, changes: Mapping[Path, str | None]) -> tuple[Path, ...]:
    """Save only supplied raw files (None deletes), without expansion or final checks.

    The factory-bound current/scope guard and recorded inputs are checked under the
    existing publication lock. Any outcome consumes the context. I/O errors retain
    existing single-write rollback; preceding successful leaf writes remain saved.
    """
    if not isinstance(context, SourceWriteContext) or context.closed:
        raise ValueError('source write context is closed or unauthorized')
    try:
        with publication_lock(context.root) as journal:
            actual = {}
            for path, text in changes.items():
                if not isinstance(path, Path) or not path.is_absolute() or '..' in path.parts:
                    raise ValueError('source write requires absolute canonical paths')
                safe(context.root, path)
                if path not in context.paths:
                    raise ValueError('unregistered source write: ' + str(path))
                if text is not None and not isinstance(text, str):
                    raise ValueError('source content must be UTF-8 text or None')
                raw = None if text is None else text.encode('utf-8')
                if context.snapshot.contents[path] != raw:
                    if text is not None:
                        if path.suffix == '.json':
                            json_read(text)
                        elif path.suffix in {'.yaml', '.yml'}:
                            from model_parameter_inputs import yaml_read
                            yaml_read(text)
                        else:
                            # Definition-local duplicate keys are valid across definitions.
                            for line in text.splitlines():
                                if line.strip() and not line.startswith('#'):
                                    from model_core import properties
                                    properties(line)
                    actual[path] = text
            context.snapshot.verify()
            context._require_current(actual)
            if actual:
                _publish_transaction(context.root, {p: t for p, t in actual.items() if t is not None},
                                     {p for p, t in actual.items() if t is None}, journal)
            return tuple(sorted(actual))
    finally:
        context.close()
