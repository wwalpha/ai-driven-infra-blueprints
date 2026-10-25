"""One Deploy invocation's FileReads/models, shared by all scheduled Stacks."""

import hashlib
from threading import RLock
from types import MappingProxyType

import model.sources as sources
from model.dependency_index import logical_models, revision
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


class SessionModels(FileReads):
    def __init__(self, root, session):
        super().__init__()
        self.root, self.session = root, session
        self.lock = RLock()
        self.revisions = {}
        self.digests = {}
        self.stages = set()
        self.checks = {}

    def canonical(self, path):
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
            canonical = self.canonical(path)
            if path != canonical:
                raw = self.read(canonical)
                if (path.read_bytes() if path.is_file() else None) != raw:
                    raise ValueError(
                        "staged Model differs from checked authority: " + str(path)
                    )
                return raw
            current = revision(path) if path.is_file() else None
            if path in self.revisions and self.revisions[path] != current:
                raise ValueError("consumed Model input changed: " + str(path))
            raw = super().read(path)
            self.revisions[path] = current
            expected = self.session.setdefault("modelInputManifest", {})
            relative = path.relative_to(self.root).as_posix()
            if path not in self.digests:
                self.digests[path] = (
                    None if raw is None else hashlib.sha256(raw).hexdigest()
                )
            digest = self.digests[path]
            if relative in expected and expected[relative] != digest:
                raise ValueError(
                    "consumed Model revision differs from saved session: " + relative
                )
            expected[relative] = digest
            return raw

    def consume(self, snapshot, reads):
        for path, raw in snapshot.dependencies.items():
            if self.read(path) != raw or reads is not self and reads.read(path) != raw:
                raise ValueError(
                    "Model snapshot differs from consumed inputs: " + str(path)
                )
        recorder = input_recorder(self.canonical(snapshot.scope.path))
        if recorder is not None and recorder is not reads:
            for path, raw in snapshot.dependencies.items():
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
        return snapshot

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
            return self.consume(
                self.rebased(sources._read_source_snapshot(primary, self), scope.root),
                reads,
            )

    def load(self, scope, reads):
        with self.lock, sources.model_session(self):
            primary = sources.Scope(
                self.root, scope.environment, scope.target, scope.service
            )
            return self.consume(
                self.rebased(sources._load_model(primary, self), scope.root), reads
            )

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
            for path, text in outputs.items():
                if path in self.contents:
                    self.contents[path] = text.encode("utf-8")
                    self.revisions[path] = published[path]
                    self.digests[path] = hashlib.sha256(self.contents[path]).hexdigest()
            self.session.setdefault("modelInputManifest", {}).update(
                hashes({p: t.encode("utf-8") for p, t in outputs.items()}, self.root)
            )
