"""One Deploy invocation's FileReads/models, shared by all scheduled Stacks."""

import hashlib
import os
from pathlib import Path
from threading import RLock
from types import MappingProxyType

import model.sources as sources
from model.dependency_index import logical_models, revision, verify_snapshot
from utils.input_cache import input_recorder
from utils.source_reads import FileReads


def hashes(contents, root):
    return {
        p.relative_to(root).as_posix(): None
        if raw is None
        else hashlib.sha256(raw).hexdigest()
        for p, raw in contents.items()
        if p.is_relative_to(root) and not p.is_relative_to(root / "framework")
    }


class RunModels(FileReads):
    def __init__(self, root, run_context):
        super().__init__()
        self.root, self.run_context = root, run_context
        self.lock = RLock()
        self.revisions = {}
        self.digests = {}
        self.stages = set()
        self.checks = {}
        self.reference_revision = object()
        self.consumed = {}
        self.dependency_index = None
        self.index_checks = {}

    def canonical(self, path):
        path = Path(os.path.abspath(path))
        return next(
            (
                self.root / path.relative_to(stage)
                for stage in self.stages
                if path.is_relative_to(stage)
            ),
            path,
        )

    def read(self, path):
        with self.lock:
            path = Path(os.path.abspath(path))
            if path in self.contents:
                return self.contents[path]
            canonical = self.canonical(path)
            if path != canonical:
                raw = self.read(canonical)
                if (path.read_bytes() if path.is_file() else None) != raw:
                    raise ValueError(
                        "staged Model differs from checked authority: " + str(path)
                    )
                self.contents[path] = raw
                return raw
            current = revision(path) if path.is_file() else None
            raw = super().read(path)
            if (revision(path) if path.is_file() else None) != current:
                self.contents.pop(path, None)
                raise ValueError("Model input changed during first read: " + str(path))
            self.revisions[path] = current
            expected = self.run_context.setdefault("modelInputs", {})
            relative = path.relative_to(self.root).as_posix()
            if path not in self.digests:
                self.digests[path] = (
                    None if raw is None else hashlib.sha256(raw).hexdigest()
                )
            digest = self.digests[path]
            if relative in expected and expected[relative] != digest:
                self.contents.pop(path, None)
                self.revisions.pop(path, None)
                self.digests.pop(path, None)
                raise ValueError(
                    "consumed Model revision differs from fixed run input: " + relative
                )
            expected[relative] = digest
            return raw

    def consume(self, snapshot, reads, scope, *, source=False):
        recorder = input_recorder(self.canonical(snapshot.scope.path))
        key = (
            scope,
            source,
            sources._imports_model_importing_scope.read_context(self.root),
            reads,
            recorder,
        )
        checked = self.consumed.get(key)
        if checked is not None and checked[0] is snapshot.dependencies:
            return checked[1]
        projected = self.rebased(snapshot, scope.root)
        for path, raw in projected.dependencies.items():
            if self.read(path) != raw or reads is not self and reads.read(path) != raw:
                raise ValueError(
                    "Model snapshot differs from consumed inputs: " + str(path)
                )
        if recorder is not None and recorder is not reads:
            for path, raw in projected.dependencies.items():
                if recorder.read(self.canonical(path)) != raw:
                    raise ValueError(
                        "Model snapshot differs from publication inputs: " + str(path)
                    )
        if reads is not self:
            for selector, paths in self.selections.items():
                base, pattern, recursive, kinds = selector
                if self.canonical(base) != base:
                    continue
                if (
                    reads.select(base, pattern, recursive=recursive, kinds=kinds)
                    != paths
                ):
                    raise ValueError("Model file set changed: " + str(base))
        self.consumed[key] = snapshot.dependencies, projected
        return projected

    def rebased(self, snapshot, root):
        if root == self.root:
            return snapshot
        result = {}
        for field in ("documents", "files", "dependencies"):
            result[field] = MappingProxyType(
                {
                    root / p.relative_to(self.root)
                    if p.is_relative_to(self.root)
                    else p: value
                    for p, value in getattr(snapshot, field).items()
                }
            )
        result["locations"] = MappingProxyType(
            {
                key: (root / path.relative_to(self.root), line)
                for key, (path, line) in snapshot.locations.items()
            }
        )
        result["parts"] = tuple(root / p.relative_to(self.root) for p in snapshot.parts)
        return snapshot._replace(
            scope=sources.Scope(
                root,
                snapshot.scope.environment,
                snapshot.scope.target,
                snapshot.scope.service,
            ),
            **result,
        )

    def source(self, scope, reads):
        with self.lock, sources.model_session(self):
            primary = sources.Scope(
                self.root, scope.environment, scope.target, scope.service
            )
            snapshot = sources._read_source_snapshot(primary, self)
            key = (
                "source",
                primary,
                sources._imports_model_importing_scope.read_context(self.root),
            )
            if (
                self.dependency_index is not None
                and self.index_checks.get(key) is not snapshot.dependencies
            ):
                verify_snapshot(self.dependency_index, snapshot, self.revisions)
                self.index_checks[key] = snapshot.dependencies
            return self.consume(snapshot, reads, scope, source=True)

    def load(self, scope, reads):
        with self.lock, sources.model_session(self):
            primary = sources.Scope(
                self.root, scope.environment, scope.target, scope.service
            )
            return self.consume(sources._load_model(primary, self), reads, scope)

    def logical_models(self, scope, logical):
        return [
            sources.Scope(scope.root, s.environment, s.target, s.service)
            for s in logical_models(self.root, scope.environment, scope.target, logical)
        ]

    def apply_observed(self, outputs):
        """Only after verified atomic publication; retain desired validation and dependencies."""
        with self.lock:
            published = {}
            for path, text in outputs.items():
                before = revision(path)
                if (
                    path.read_bytes() != text.encode("utf-8")
                    or revision(path) != before
                ):
                    raise ValueError(
                        "observed publication differs from verified cache delta: "
                        + str(path)
                    )
                published[path] = before
            if published:
                # References may cross services; the full check includes those diagnostics.
                self.reference_revision = object()
                self.checks.clear()
            for key, snapshot in tuple(self.models.items()):
                candidate = sources.observed_snapshot(snapshot, outputs)
                dependencies = {
                    **candidate.dependencies,
                    **{
                        p: t.encode("utf-8")
                        for p, t in outputs.items()
                        if p in candidate.dependencies
                    },
                }
                self.models[key] = candidate._replace(
                    dependencies=MappingProxyType(dependencies)
                )
                if self.index_checks.get(key) is snapshot.dependencies:
                    self.index_checks[key] = self.models[key].dependencies
            for path, text in outputs.items():
                if path in self.contents:
                    self.contents[path] = text.encode("utf-8")
                    self.revisions[path] = published[path]
                    self.digests[path] = hashlib.sha256(self.contents[path]).hexdigest()
            self.run_context.setdefault("modelInputs", {}).update(
                hashes({p: t.encode("utf-8") for p, t in outputs.items()}, self.root)
            )
