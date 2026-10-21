"""Properties discovery, immutable raw snapshots and journalled publication."""
from __future__ import annotations
from utils.json_format import json_text, strict_json
import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Mapping
from types import MappingProxyType
from validation_cache import (input_bytes, input_exists, input_is_dir, input_is_file,
    input_is_symlink, input_select, memo_table, memoized)
from sync_progress import phase, thread_lock
import sync_files
from model.format import FORMAT, INDEX, PART, parse, validate_blocks

_locks = {}
_guard = threading.Lock()
_local = threading.local()


json_read = strict_json


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + ' requires exactly ' + str(sorted(keys)))


def safe(root, path):
    if '..' in path.parts or not path.is_relative_to(root) or any(
            input_is_symlink(p) for p in (path, *path.parents) if p.is_relative_to(root)):
        raise ValueError('unsafe Model source path: ' + str(path))


def _receipt_original(root, record):
    """The only external rollback target is this root's named Import receipt."""
    from import_guard import evidence_store
    from task_contract import TASK_NAME
    exact(record, {'task', 'original'}, 'Import receipt journal')
    if not isinstance(record['task'], str) or not TASK_NAME.fullmatch(record['task']):
        raise ValueError('invalid Import receipt journal Task')
    file = evidence_store(root) / (Path(record['task']).stem + '.json')
    if file.is_symlink():
        raise ValueError('unsafe Import receipt journal path')
    data = record['original']
    return {file: None if data is None else base64.b64decode(data, validate=True)}


@contextmanager
def publication_lock(root, *, read_only=False, recovery_check=None):
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
                    exact(record, {'root', 'originals', *({'importReceipt'} if 'importReceipt' in record else set())}, 'publication journal')
                    if record['root'] != key:
                        raise ValueError('publication journal root mismatch')
                    if recovery_check is not None:
                        recovery_check(record)
                    originals = {}
                    for relative, data in record['originals'].items():
                        candidate = root / relative
                        if Path(relative).is_absolute() or '..' in Path(relative).parts:
                            raise ValueError('unsafe publication journal')
                        safe(root, candidate)
                        originals[candidate] = None if data is None else base64.b64decode(data, validate=True)
                    if 'importReceipt' in record:
                        originals.update(_receipt_original(root, record['importReceipt']))
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



def _publish_transaction(root, output, obsolete, journal, *, originals=None, start=None, finish=None, receipt=None):
    """Journal and rollback shared by guarded publication and validated generation plans.

    The caller holds publication_lock and owns authorization/input validation. A supplied
    originals map is the already compared generation plan, including only changed files.
    """
    planned = originals is not None
    if originals is None:
        originals = {p: p.read_bytes() if p.is_file() else None for p in set(output) | set(obsolete)}
    record = {'root': str(root.resolve()), 'originals': {p.relative_to(root).as_posix():
              None if data is None else base64.b64encode(data).decode() for p, data in originals.items()}}
    if receipt is not None:
        task, original = receipt
        record['importReceipt'] = {'task': task, 'original': None if original is None else base64.b64encode(original).decode()}
        originals = {**originals, **_receipt_original(root, record['importReceipt'])}
    temporary = journal.with_suffix('.pending')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(json_text(record)); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, journal)
    if memo_table() is not None:
        memo_table().clear()
    try:
        if start is not None:
            start()
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
    except Exception:
        sync_files.restore_files(originals)
        journal.unlink()
        raise
    finally:
        if memo_table() is not None:
            memo_table().clear()
    journal.unlink()



@dataclass(frozen=True)
class Scope:
    root: Path
    environment: str
    target: str
    service: str

    @property
    def path(self):
        return self.root / 'model' / self.environment / self.target / (self.service + '.properties')


def scope_for(path):
    path = Path(path).absolute()
    if len(path.parents) < 4 or path.parents[2].name != 'model' or path.suffix != '.properties':
        raise ValueError('Model requires model/<environment>/<target>/<service>.properties')
    return Scope(path.parents[3], path.parents[1].name, path.parent.name, path.stem)


def source_scope(root, file):
    """Map only an entrance or a named part to its Model scope, including absent files."""
    file = Path(file)
    relative = file.relative_to(root / 'model')
    if len(relative.parts) == 3 and file.suffix == '.properties':
        return scope_for(file)
    if len(relative.parts) == 4 and re.fullmatch(r'part-[0-9]{3,}\.properties', file.name):
        return scope_for(file.parent.with_name(file.parent.name + '.properties'))
    raise ValueError('invalid authoritative Model path: ' + str(file))


def model_paths(root, environment=None, alias=None, read_context=None):
    return [scope.path for scope in list_models(root, read_context)
            if (environment is None or scope.environment == environment)
            and (alias is None or scope.target == alias)]


def input_snapshot(path, read_context=None):
    return dict(load_model(path, read_context).dependencies)


def source_inputs(path, read_context=None):
    return set(input_snapshot(path, read_context))


def model_exists(path, read_context=None):
    scope = scope_for(path)
    reads = read_context or FileReads()
    _safe(scope.root, scope.path, reads)
    kind = reads.kind(scope.path)
    if kind not in {'file', 'missing'}:
        raise ValueError('invalid Model entrance: ' + str(path))
    return kind == 'file'


def design_source_digest(path, read_context=None):
    snapshot = load_model(path, read_context)
    authority = {key: value for key, value in snapshot.authoritative.items() if not key.startswith('observed.')}
    return hashlib.sha256(json.dumps(authority, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def authority_snapshot(root, environment, directory, read_context=None):
    reads = read_context or FileReads()
    return {file: data
            for path in model_paths(root, environment, directory, reads)
            for file, data in load_model(path, reads).dependencies.items()}


class FileReads:
    """Use the existing invocation recorder/cache for file and discovery dependencies."""
    def __init__(self):
        self.contents = {}
        self.models = {}
        self.selections = {}
        self.kinds = {}

    def read(self, path):
        if path not in self.contents:
            self.contents[path] = input_bytes(path) if input_exists(path) else None
        return self.contents[path]

    def kind(self, path):
        if path not in self.kinds:
            self.kinds[path] = ('symlink' if input_is_symlink(path) else 'file' if input_is_file(path)
                                else 'dir' if input_is_dir(path) else 'missing')
        return self.kinds[path]

    def select(self, base, pattern='*', recursive=False, kinds=None):
        key = base, pattern, recursive, None if kinds is None else tuple(kinds)
        if key not in self.selections:
            self.selections[key] = tuple(input_select(base, pattern, recursive=recursive, kinds=kinds))
        return self.selections[key]

    def verify(self):
        """Fresh raw bytes, absence, file kind and discovery sets; bypass invocation caches."""
        from generation_inputs import GenerationInputs
        for path, raw in self.contents.items():
            if (path.read_bytes() if path.is_file() else None) != raw:
                raise ValueError('Model input changed during read: ' + str(path))
        for path, kind in self.kinds.items():
            if GenerationInputs.live_kind(path) != kind:
                raise ValueError('Model input kind changed during read: ' + str(path))
        for selector, paths in self.selections.items():
            if tuple(GenerationInputs.live_select(*selector)) != paths:
                raise ValueError('Model file set changed during read: ' + str(selector[0]))


def _safe(root, path, reads):
    if '..' in path.parts or not path.is_relative_to(root) or any(
            reads.kind(parent) == 'symlink' for parent in (path, *path.parents) if parent.is_relative_to(root)):
        raise ValueError('unsafe Model path: ' + str(path))


@memoized
def _topology(raw):
    return strict_json(raw.decode('utf-8'))


def target_for(scope, reads):
    for name in (scope.environment, scope.target, scope.service):
        if not name or name in {'.', '..'} or '/' in name or '\\' in name:
            raise ValueError('invalid Model scope component')
    project = scope.root / 'project.json'
    _safe(scope.root, project, reads)
    raw = reads.read(project)
    if raw is None:
        raise ValueError('Model requires project.json')
    from project_targets import select_target, DeployContextError
    account = re.fullmatch(r'[0-9]{12}', scope.target) is not None
    try:
        target = select_target(_topology(raw), scope.environment,
                               scope.target if account else None, None if account else scope.target)
    except DeployContextError as error:
        raise ValueError(str(error)) from error
    return target, raw



def model_parts(path, *, read_context=None):
    reads = read_context or FileReads()
    scope = scope_for(path)
    _safe(scope.root, path, reads)
    directory = path.with_suffix('')
    _safe(scope.root, directory, reads)
    raw = reads.read(path)
    if raw is None:
        raise FileNotFoundError(path)
    lines = raw.decode('utf-8').splitlines()
    if not lines or lines[0] != FORMAT:
        raise ValueError('unsupported Model format: ' + str(path))
    parts = []
    if len(lines) > 1 and lines[1] == INDEX:
        for line in lines[2:]:
            if line.startswith(PART):
                name = line[len(PART):]
                if re.fullmatch(re.escape(path.stem) + r'/part-[0-9]{3,}\.properties', name) is None:
                    raise ValueError('unsafe Model part: ' + name)
                part = path.parent / name
                if part in parts:
                    raise ValueError('duplicate Model part: ' + name)
                _safe(scope.root, part, reads)
                if reads.kind(part) != 'file':
                    raise ValueError('missing Model part: ' + name)
                parts.append(part)
            elif line.strip() and (not line.startswith('#') or line.startswith(('# model-index:', '# model-format:'))):
                raise ValueError('invalid Model index line: ' + line)
        if not parts:
            raise ValueError('Model index has no parts')
    else:
        parse(raw.decode('utf-8'))
    extras = set(reads.select(directory, '*', recursive=True)) - set(parts)
    if extras:
        raise ValueError('unregistered Model parts: ' + ', '.join(str(p) for p in sorted(extras)))
    return parts or [path]


@dataclass(frozen=True)
class ModelSnapshot:
    scope: Scope
    authoritative: Mapping[str, str]
    values: Mapping[str, str]
    documents: Mapping[Path, object]
    locations: Mapping[str, tuple[Path, int]]
    files: Mapping[Path, str]
    dependencies: Mapping[Path, bytes | None]
    parts: tuple[Path, ...]
    warnings: tuple = ()
    provenance: Mapping = field(default_factory=dict)

    @property
    def text(self):
        return ''.join(key + '=' + value + '\n' for key, value in self.values.items())

    def _replace(self, **changes):
        from dataclasses import replace
        return replace(self, **changes)


def runtime_values(authoritative):
    """Derived metadata is never a serializer input."""
    from model.core import validate_authority
    validate_authority(authoritative)
    values = {key: value for key, value in authoritative.items()
              if not key.startswith('desired.reference.') and not key.endswith('.placementName')}
    for key, value in authoritative.items():
        if key.startswith('observed.row.'):
            prefix = 'desired.' + key.removeprefix('observed.').removesuffix('value')
            if prefix + 'value' not in authoritative:
                raise ValueError('orphan observed row: ' + key)
            for field in ('property', 'comment'):
                if prefix + field in authoritative:
                    values[key.removesuffix('value') + field] = authoritative[prefix + field]
        elif key.startswith('desired.row.') and key.endswith('.document'):
            from utils.json_format import document_sha256
            values[key.removesuffix('document') + 'artifactSha256'] = document_sha256(strict_json(value))
    return values


def _read_model(scope, read_context=None):
    scope = scope if isinstance(scope, Scope) else scope_for(scope)
    from model.importing.scope import require_readable
    require_readable(scope.root, scope.path)
    reads = read_context or _invocation_reads(scope.root)
    with publication_lock(scope.root, read_only=True):

        target, project = target_for(scope, reads)
        path = scope.path
        parts = tuple(model_parts(path, read_context=reads))
        files = {part: reads.read(part).decode('utf-8') for part in dict.fromkeys((path, *parts))}
        documents = {part: parse(files[part]) for part in parts}
        authoritative, locations = validate_blocks(documents)
        from model.references import declarations
        declarations(authoritative)
        values = runtime_values(authoritative)
        return ModelSnapshot(scope, MappingProxyType(authoritative), MappingProxyType(values),
                             MappingProxyType(documents), MappingProxyType(locations), MappingProxyType(files),
                             MappingProxyType({scope.root / 'project.json': project,
                                 **{p: text.encode('utf-8') for p, text in files.items()}}), parts)



def _model_snapshots(reads):
    memo = memo_table()
    return reads.models if isinstance(reads, FileReads) else (
        memo.setdefault((load_model, id(reads)), (reads, {}))[1] if memo is not None else {})


def _source_snapshot(scope, reads):
    from model.importing.scope import require_readable, read_context
    require_readable(scope.root, scope.path)
    models = _model_snapshots(reads)
    key = 'source', scope, read_context(scope.root)
    if key not in models:
        models[key] = _read_model(scope, reads)
    return models[key]


def load_model(scope, read_context=None):
    scope = scope if isinstance(scope, Scope) else scope_for(scope)
    from model.importing.scope import read_context as permission_context, require_readable
    require_readable(scope.root, scope.path)
    reads = read_context or _invocation_reads(scope.root)
    key = scope, permission_context(scope.root)
    models = _model_snapshots(reads)
    if key in models:
        return models[key]
    snapshot = _source_snapshot(scope, reads)
    from model.references import diagnose
    warnings, dependencies = diagnose(snapshot, reads)
    result = snapshot._replace(warnings=warnings, dependencies=MappingProxyType(dependencies))
    models[key] = result
    return result


def _invocation_reads(root):
    memo = memo_table()
    if memo is None:
        return FileReads()
    from model.importing.scope import read_context
    return memo.setdefault((FileReads, root, read_context(root)), FileReads())


def list_models(scope, read_context=None):
    """Discover existing entries only; project targets never create a Model."""
    reads = read_context or FileReads()
    if isinstance(scope, Scope):
        root, environment, target = scope.root, scope.environment, scope.target
    else:
        root, environment, target = Path(scope).absolute(), None, None
    result = []
    with publication_lock(root, read_only=True):

        for path in sorted(reads.select(root / 'model', '*/*/*.properties')):
            selected = scope_for(path)
            if environment is not None and selected.environment != environment or target is not None and selected.target != target:
                continue
            _safe(root, path, reads)
            target_for(selected, reads)
            if reads.kind(path) != 'file':
                raise ValueError('invalid Model entry: ' + str(path))
            result.append(selected)
    return result


class SourceWriteContext:
    """One-use authorized state, issued by the Task adapter after live ownership checks."""
    __slots__ = ('_root', '_snapshot', '_operation', '_paths', '_closed', '_require_current', '_start', '_finish', '_receipt')

    root = property(lambda self: self._root)
    snapshot = property(lambda self: self._snapshot)
    operation = property(lambda self: self._operation)
    paths = property(lambda self: self._paths)
    closed = property(lambda self: self._closed)

    def __init__(self):
        raise TypeError('use model.adapters.task.source_write_context')

    @classmethod
    def _authorized(cls, root: Path, snapshot: GenerationInputs, operation: ModelOperation,
                    require_current: Callable, paths: frozenset[Path], *, start=None, finish=None, receipt=None):
        context = object.__new__(cls)
        context._root, context._snapshot, context._operation = root, snapshot, operation
        context._require_current, context._paths = require_current, paths
        context._start, context._finish, context._receipt = start, finish, receipt
        context._closed = False
        return context

    def close(self) -> None:
        self._closed = True
        self.snapshot.close()



def candidate_sources(root, directory, before):
    """A complete selected-service properties candidate never grants producer write access."""
    from model.operations import CandidateReads
    directory = Path(directory).absolute()
    if directory.is_relative_to(root) or not directory.is_dir():
        raise ValueError('Model properties candidate must be outside the repository')
    output = {}
    for path in directory.rglob('*'):
        safe(directory, path)
        if path.is_dir():
            continue
        destination = root / path.relative_to(directory)
        if not path.is_file() or source_scope(root, destination) != before.scope:
            raise ValueError('Model candidate is outside the selected service: ' + str(path))
        output[destination] = path.read_bytes().decode('utf-8')
    if before.scope.path not in output:
        raise ValueError('Model requires a complete properties candidate including its entrance')
    output.update({path: None for path in before.files if path not in output})
    after = load_model(before.scope, CandidateReads(FileReads(), output))
    return {path: text for path, text in output.items()
            if (path.read_bytes() if path.is_file() else None) != (None if text is None else text.encode('utf-8'))}, after



def candidate_base(path, reads):
    if reads.kind(path) != 'missing':
        return load_model(path, reads)
    scope = scope_for(path)

    _, project = target_for(scope, reads)
    reads.read(path)
    if reads.select(path.with_suffix(''), '*', recursive=True):
        raise ValueError('missing Model entrance has unregistered parts: ' + str(path))
    return ModelSnapshot(scope, MappingProxyType({}), MappingProxyType({}), MappingProxyType({}),
        MappingProxyType({}), MappingProxyType({}), MappingProxyType({scope.root / 'project.json': project, path: None}), ())
