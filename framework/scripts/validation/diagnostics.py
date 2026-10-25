"""Validation evidence with explicit ownership, independent of display prose."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


def service_scope(root, path):
    if path is None:
        return None
    path = Path(path)
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    for base, suffix in (("model", ".properties"), ("docs/designs", ".md")):
        directory = root.resolve() / base
        if not path.is_relative_to(directory):
            continue
        parts = path.relative_to(directory).parts
        if len(parts) == 3 and path.suffix == suffix:
            return (*parts[:2], path.stem)
    return None


def relative_path(root, path):
    if path is None:
        return None
    path = Path(path)
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    return (
        path.relative_to(root.resolve()).as_posix()
        if path.is_relative_to(root.resolve())
        else str(path)
    )


def json_reference(root, source, raw, findings):
    target = None
    try:
        target = (source.parent / raw).resolve()
        reason = (
            "JSON link must be relative"
            if Path(raw).is_absolute()
            else "JSON link is outside repository"
            if not target.is_relative_to(root.resolve())
            else "design JSON artifact must be stored under owning service"
            if target.parent != source.with_suffix("").resolve()
            else None
        )
    except (OSError, ValueError) as error:
        reason = f"invalid JSON link path: {error}"
    if reason is None:
        return target
    findings.add_diagnostic(
        Diagnostic.create(
            root,
            code="design.artifact.placement",
            check_id="design.artifacts",
            service=service_scope(root, source),
            source_path=source,
            target_path=target,
            location=raw,
            message=f"{reason}: {findings.relative(source)}: {raw}",
        )
    )
    return None


def plaintext_diagnostics(root, path, error):
    return [
        Diagnostic.create(
            root,
            code="codebuild.plaintext-reference",
            check_id="design.tables",
            service=service_scope(root, path),
            source_path=path,
            location=f"{position['anchor']}/{position['property']}/{position['name']}",
            message=f"{relative_path(root, path)}: {position['message']}",
        )
        for position in error.positions
    ]


def display_diagnostics(root, path, error, check_id):
    source = relative_path(root, path)
    for position in error.positions:
        cause = stable_id([source, position])
        yield Diagnostic.create(
            root,
            code="design.display.mismatch",
            check_id=check_id,
            service=service_scope(root, path),
            source_path=path,
            cause_key=cause,
            location=position["location"],
            details=position,
            message=f"design.display.mismatch: {source}: {position['resourceLogicalId']} / {position['property']}: {position['savedDisplay']} → {position['expectedDisplay']}",
        )


def stable_id(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    check_id: str
    service: tuple | None
    source_path: str | None
    target_path: str | None
    message: str
    cause_key: str | None = None
    affected_services: tuple = ()
    location: str | None = None
    details: dict = field(default_factory=dict)

    @classmethod
    def create(cls, root, *, source_path=None, target_path=None, **details):
        return cls(
            source_path=relative_path(root, source_path),
            target_path=relative_path(root, target_path),
            **details,
        )

    @property
    def identity(self):
        identity = (
            self.code,
            self.service,
            self.source_path,
            self.target_path,
            self.location,
            self.cause_key,
        )
        if self.code == "design.display.mismatch":
            return (
                self.check_id,
                *identity,
                *(
                    self.details.get(key)
                    for key in ("resourceLogicalId", "anchor", "property", "occurrence")
                ),
            )
        return identity

    def record(self):
        record = asdict(self)
        record.pop("details")
        if self.details:
            record.update(self.details)
            record.update(
                sourcePath=self.source_path,
                checkId=self.check_id,
                diagnosticId=stable_id(self.identity),
            )
        return record


@dataclass
class ArtifactReferences:
    sources: dict = field(default_factory=dict)
    complete: dict = field(default_factory=dict)

    def start(self, path):
        self.complete[path.resolve()] = False

    def add(self, artifact, source, owner):
        self.sources.setdefault(artifact.resolve(), {})[source.resolve()] = owner

    def finish(self, path):
        self.complete[path.resolve()] = True
