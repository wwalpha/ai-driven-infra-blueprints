"""Invocation-local input reuse and content-addressed successful validation results."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


_inputs = ContextVar("blueprint_inputs", default=None)


_generation_inputs = ContextVar("generation_inputs", default=None)


@contextmanager
def recording_inputs(inputs):
    token = _generation_inputs.set(inputs)
    try:
        yield
    finally:
        _generation_inputs.reset(token)


def input_recorder(path):
    inputs = _generation_inputs.get()
    return inputs if inputs is not None and inputs.tracks(Path(path)) else None


def input_bytes(path):
    path = Path(path)
    inputs = input_recorder(path)
    if inputs is None:
        return path.read_bytes()
    data = inputs.read(path)
    if data is None:
        raise FileNotFoundError(2, "No such file or directory", str(path))
    return data


def input_text(path, encoding="utf-8", errors=None):
    if input_recorder(path) is None:
        return Path(path).read_text(encoding=encoding, errors=errors)
    return input_bytes(path).decode(encoding, errors or "strict").replace("\r\n", "\n").replace("\r", "\n")


def input_kind(path):
    path = Path(path)
    inputs = input_recorder(path)
    if inputs is not None:
        return inputs.kind(path)
    return ("symlink" if path.is_symlink() else "file" if path.is_file() else
            "dir" if path.is_dir() else "missing")


def input_is_file(path):
    return input_kind(path) == "file"


def input_is_dir(path):
    return input_kind(path) == "dir"


def input_exists(path):
    return input_kind(path) != "missing"


def input_is_symlink(path):
    return input_kind(path) == "symlink"


def input_select(base, pattern="*", *, recursive=False, kinds=None):
    base = Path(base)
    inputs = input_recorder(base)
    if inputs is not None:
        return inputs.select(base, pattern, recursive, kinds)
    paths = base.rglob(pattern) if recursive else base.glob(pattern)
    return tuple(sorted(p for p in paths if kinds is None or input_kind(p) in kinds))


@contextmanager
def input_context():
    if _inputs.get() is not None:
        yield
        return
    token = _inputs.set({})
    try:
        from import_guard import baseline_scope
        with baseline_scope():
            yield
    finally:
        _inputs.reset(token)


def input_scope(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with input_context():
            return function(*args, **kwargs)
    return wrapped


def memo_table():
    return _inputs.get()


def memoized(function):
    @wraps(function)
    def wrapped(*args):
        memo = _inputs.get()
        if memo is None:
            return function(*args)
        key = (function, args)
        if key not in memo:
            memo[key] = function(*args)
        return memo[key]
    return wrapped


def digest_files(root, paths, contents=None):
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if any((root.joinpath(*relative.parts[:number])).is_symlink()
               for number in range(1, len(relative.parts) + 1)):
            raise ValueError("symlink inputs cannot reuse validation results")
        content = contents[path] if contents is not None else path.read_bytes() if path.is_file() else None
        # Length-delimited names and byte hashes distinguish missing/empty/new files.
        digest.update(json.dumps([relative.as_posix(), None if content is None else
                                  hashlib.sha256(content).hexdigest()]).encode("utf-8"))
    return digest.hexdigest()


class PassCache:
    def __init__(self, root, fresh=False, directory=None, *, include_project=True, definitions_root=None):
        self.root = root
        from utils.aws_mappings import definition_root
        self.definitions_root = definitions_root or definition_root(root)
        self.fresh = fresh
        self.common = None
        self.include_project = include_project
        self.directory = Path(directory or os.environ.get("BLUEPRINT_VALIDATION_CACHE_DIR") or
                              Path(tempfile.gettempdir()) / "blueprint-validation-cache").resolve()
        if self.directory == root or root in self.directory.parents:
            raise ValueError("validation cache must be outside the repository")

    def common_inputs(self, snapshot=None):
        """The complete historical common set, including actual definitions/runtime."""
        groups = {}
        runtime = Path(__file__).resolve().parents[2]
        for root, names in ((self.root, ('framework', '.agents')),
                            (self.definitions_root, ('framework', '.agents')), (runtime, ('framework',))):
            paths = groups.setdefault(root, set())
            for name in names:
                base = root / name
                selected = (snapshot.select(base, '*', True, ('file', 'symlink')) if snapshot else
                            input_select(base, '*', recursive=True, kinds=('file', 'symlink')))
                paths.update(p for p in selected if not (p.suffix == '.pyc' and '__pycache__' in p.parts))
        for root in {self.root, self.definitions_root}:
            groups[root].update(root / p for p in ('AGENTS.md', 'README.md'))
        if self.include_project:
            groups[self.root].add(self.root / 'project.json')
        if snapshot is not None:
            for paths in groups.values():
                for path in paths:
                    snapshot.read(path)
        return groups

    def common_key(self, contents=None, *, snapshot=None):
        groups = self.common_inputs(snapshot)
        if snapshot is not None:
            contents = snapshot.contents
        inputs = [[str(root), digest_files(root, paths, contents)] for root, paths in groups.items()]
        return hashlib.sha256(json.dumps(inputs).encode()).hexdigest()

    def key(self, kind, inputs=""):
        if self.common is None:
            self.common = self.common_key()
        return hashlib.sha256(json.dumps([1, sys.version, sys.platform, kind,
                                         self.common, inputs]).encode("utf-8")).hexdigest()

    def service_key(self, entry):
        from model.sources import source_inputs, model_exists
        environment, target, service = entry
        docs = self.root / "docs/designs"
        models = self.root / "model"
        pending = [docs / environment / target / f"{service}.md"]
        paths = set()
        while pending:
            path = pending.pop()
            if path in paths:
                continue
            if not path.is_relative_to(docs) or not path.is_file():
                raise ValueError("unknown design dependency; require fresh validation")
            paths.add(path)
            model = (models / path.relative_to(docs)).with_suffix(".properties")
            if model_exists(model):
                paths.update(source_inputs(model))
            elif path == docs / environment / target / f"{service}.md":
                raise ValueError("missing service model")
            # Include the complete file set to detect orphan artifacts and unlisted parts.
            for entrance in (path,):
                paths.update(file for file in entrance.with_suffix("").rglob("*")
                             if file.is_file() or file.is_symlink())
            paths.update(file for file in model.with_suffix("").rglob("*")
                         if file.is_file() or file.is_symlink())
            texts = [path.read_text(encoding="utf-8")]
            if model_exists(model):
                from model.files import read_model
                texts.append(read_model(model))
            for text in texts:
                for raw in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                    if raw.startswith(("https://", "http://", "mailto:")):
                        continue
                    dependency = (path.parent / raw.partition("#")[0]).resolve() if raw.partition("#")[0] else path
                    if not dependency.is_relative_to(self.root) or not dependency.is_file():
                        raise ValueError("unknown design dependency; require fresh validation")
                    if dependency.suffix == ".md":
                        pending.append(dependency)
                    else:
                        paths.add(dependency)
        return self.key("service:" + "/".join(entry), digest_files(self.root, paths))

    def load(self, key):
        if self.fresh or key is None:
            return None
        try:
            record = json.loads((self.directory / f"{key}.json").read_text(encoding="utf-8"))
            if record == {"version": 1, "key": key, "result": "pass", "checks": record["checks"]} and \
                    type(record["checks"]) is int and record["checks"] > 0:
                return record["checks"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def save(self, key, checks):
        if key is None or checks <= 0:
            return
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"version": 1, "key": key, "result": "pass", "checks": checks}, stream)
            os.replace(temporary, self.directory / f"{key}.json")
        except OSError:
            pass  # Cache availability never replaces actual validation.
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
