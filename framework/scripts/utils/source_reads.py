"""Recorded source reads and candidate overlays, independent of Model operations."""

from concurrent.futures import Future
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import RLock

import generation_inputs as _imports_generation_inputs

from utils.input_cache import (
    input_bytes,
    input_exists,
    input_is_dir,
    input_is_file,
    input_is_symlink,
    input_select,
)


class CandidateReads:
    """Overlay candidate bytes on the existing input recorder, including file sets."""

    def __init__(self, before, changes):
        self.before, self.changes = before, changes

    def read(self, path):
        if path in self.changes:
            value = self.changes[path]
            return None if value is None else value.encode("utf-8")
        return self.before.read(path)

    def kind(self, path):
        actual = self.before.kind(path)
        if actual == "symlink":
            return actual
        if path in self.changes:
            return "missing" if self.changes[path] is None else "file"
        if any(
            value is not None and path in candidate.parents
            for candidate, value in self.changes.items()
        ):
            return "dir"
        return actual

    def select(self, base, pattern="*", recursive=False, kinds=None):
        result = set(
            self.before.select(base, pattern, recursive=recursive, kinds=kinds)
        )
        candidates = set(self.changes)
        for path, value in self.changes.items():
            if value is not None:
                candidates.update(
                    parent
                    for parent in path.parents
                    if parent.is_relative_to(base) and parent != base
                )
        for path in candidates:
            if not path.is_relative_to(base) or path == base:
                continue
            relative = path.relative_to(base)
            if not relative.match(pattern) or (
                not recursive
                and "**" not in pattern
                and len(relative.parts) != len(Path(pattern).parts)
            ):
                continue
            kind = self.kind(path)
            if kind == "missing" or kinds is not None and kind not in kinds:
                result.discard(path)
            else:
                result.add(path)
        return tuple(sorted(result))


class FileReads:
    """Use the existing invocation recorder/cache for file and discovery dependencies."""

    def __init__(self):
        self.lock = RLock()
        self.cache_identity = object()
        self.contents = {}
        self.models = {}
        self.snapshots = {}
        self.documents = {}
        self.selections = {}
        self.kinds = {}
        self.read_failures = {}
        self.indexes = {}

    def fork(self):
        """Private Model tables over shared lazy bytes, documents and index reads."""
        reads = FileReads()
        reads.cache_identity = self.cache_identity
        reads.lock = self.lock
        reads.models = {
            key: replace(snapshot, warnings=deepcopy(snapshot.warnings))
            if snapshot is not None and snapshot.warnings
            else snapshot
            for key, snapshot in self.models.items()
        }
        for name in (
            "contents",
            "documents",
            "selections",
            "kinds",
            "read_failures",
            "indexes",
            "snapshots",
        ):
            setattr(reads, name, getattr(self, name))
        return reads

    def snapshot(self, key, build, *args):
        """Single-flight immutable results; never hold the read lock during construction/wait."""
        with self.lock:
            pending = self.snapshots.get(key)
            owner = pending is None
            if owner:
                pending = self.snapshots[key] = Future()
        if owner:
            try:
                result = build(*args)
            except BaseException as error:
                with self.lock:
                    del self.snapshots[key]
                    pending.set_exception(error)
                raise
            pending.set_result(result)
        return pending.result()

    def read(self, path):
        with self.lock:
            if path not in self.contents:
                try:
                    self.contents[path] = (
                        input_bytes(path) if input_exists(path) else None
                    )
                except OSError as error:
                    self.read_failures.setdefault(path, type(error).__name__)
                    raise
            return self.contents[path]

    def kind(self, path):
        with self.lock:
            if path not in self.kinds:
                self.kinds[path] = (
                    "symlink"
                    if input_is_symlink(path)
                    else "file"
                    if input_is_file(path)
                    else "dir"
                    if input_is_dir(path)
                    else "missing"
                )
            return self.kinds[path]

    def select(self, base, pattern="*", recursive=False, kinds=None):
        key = base, pattern, recursive, None if kinds is None else tuple(kinds)
        with self.lock:
            if key not in self.selections:
                self.selections[key] = tuple(
                    input_select(base, pattern, recursive=recursive, kinds=kinds)
                )
            return self.selections[key]

    def verify(self):
        """Fresh raw bytes, absence, file kind and discovery sets; bypass invocation caches."""
        GenerationInputs = _imports_generation_inputs.GenerationInputs
        for path, raw in self.contents.items():
            if (path.read_bytes() if path.is_file() else None) != raw:
                raise ValueError("Model input changed during read: " + str(path))
        for path, kind in self.kinds.items():
            if GenerationInputs.live_kind(path) != kind:
                raise ValueError("Model input kind changed during read: " + str(path))
        for selector, paths in self.selections.items():
            if tuple(GenerationInputs.live_select(*selector)) != paths:
                raise ValueError(
                    "Model file set changed during read: " + str(selector[0])
                )
