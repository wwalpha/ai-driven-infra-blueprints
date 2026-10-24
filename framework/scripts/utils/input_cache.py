"""Invocation-local input reuse and content-addressed successful validation results."""

import hashlib
import json
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from utils.function_wrapper import FunctionWrapper

_baselines = ContextVar('import_baselines', default=None)


@contextmanager
def baseline_scope():
    if _baselines.get() is not None:
        yield
        return
    with tempfile.TemporaryDirectory(prefix='blueprint-import-baselines-') as directory:
        token = _baselines.set((Path(directory).resolve(), {}))
        try:
            yield
        finally:
            _baselines.reset(token)


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
        with baseline_scope():
            yield
    finally:
        _inputs.reset(token)


def _invoke_input_scope(function, /, *args, **kwargs):
    with input_context():
        return function(*args, **kwargs)


def input_scope(function):
    wrapped = FunctionWrapper(function, _invoke_input_scope)
    return wrapped


def memo_table():
    return _inputs.get()


def _invoke_memoized(function, /, *args, **kwargs):
    memo = _inputs.get()
    if memo is None:
        return function(*args, **kwargs)
    key = (function, args, tuple(sorted(kwargs.items()))) if kwargs else (function, args)
    if key not in memo:
        memo[key] = function(*args, **kwargs)
    return memo[key]


def memoized(function):
    wrapped = FunctionWrapper(function, _invoke_memoized)
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
