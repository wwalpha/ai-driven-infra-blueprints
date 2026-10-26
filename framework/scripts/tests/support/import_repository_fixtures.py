"""In-process repository state for Import IT; CLI processes always use real Git."""

import shutil
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

import model.importing.repository as _imports_model_importing_repository
from model.importing.scope import read_consumers
from utils import sealed_evidence

from model import dependency_index

_cases = ContextVar("import_it_repositories", default=None)


def contents(root):
    files = [root / "project.json"]
    for directory in ("model", "tasks"):
        files.extend(path for path in (root / directory).rglob("*") if path.is_file())
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in files
        if path.is_file()
    }


@dataclass
class Repository:
    root: Path
    head: str = "synthetic-head"
    base: str = "synthetic-head"
    task: str = "tasks/import-fixture.md"
    baseline: dict = field(default_factory=dict)

    def checkpoint(self):
        self.baseline = contents(self.root)
        self.base = self.head


def checkpoint(root, *, task="tasks/import-fixture.md"):
    cases = _cases.get()
    if cases is None:
        return  # Real-Git boundary suites use the same authored seed, without this provider.
    root = root.resolve()
    state = cases.setdefault(root, Repository(root, task=task))
    state.task = task
    state.checkpoint()
    identities = {
        (*path.relative_to(root / "model").parts[:2], path.stem)
        for path in (root / "model").rglob("*.properties")
        if len(path.relative_to(root / "model").parts) == 3
    }
    with read_consumers(identities):
        dependency_index.rebuild(root)
    return state


def state(root):
    return _cases.get()[root.resolve()]


def _callback_repositories_changed(root, *, task_file=None):
    before, after = state(root).baseline, contents(root)
    return {
        name
        for name in before.keys() | after.keys()
        if before.get(name) != after.get(name)
    }


@contextmanager
def repositories(monkeypatch):
    repository = _imports_model_importing_repository
    cases = {}
    token = _cases.set(cases)
    changed = _callback_repositories_changed
    with monkeypatch.context() as patch:
        patch.setattr(repository, "has_baseline", lambda root: root.resolve() in cases)
        patch.setattr(repository, "working_revision", lambda root: state(root).head)
        patch.setattr(repository, "task_head", lambda root: state(root).head)
        patch.setattr(
            repository, "task_start_commit", lambda root, name: state(root).base
        )
        patch.setattr(repository, "changed_paths", changed)
        patch.setattr(
            repository,
            "publication_revision",
            lambda root, name: (str(root.resolve()), name, state(root).head),
        )
        try:
            yield cases
        finally:
            _cases.reset(token)
            evidence_store = sealed_evidence.evidence_store
            for root in cases:
                directory = evidence_store(root, create=False)
                if directory.exists():
                    shutil.rmtree(directory)


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix="model-publication-") as directory:
        root = Path(directory).resolve() / "baseline"
        root.mkdir()
        yield root


def start(root):
    checkpoint(root, task="tasks/example.md")
    target = root.with_name("candidate")
    target.mkdir()
    (target / "tasks").mkdir()
    shutil.copyfile(root / "project.json", target / "project.json")
    shutil.copytree(root / "model", target / "model")
    checkpoint(target, task="tasks/example.md")
    return target, {"task_file": "tasks/example.md", "start": state(target).base}


def _publication_workspace_begin(root, relative):
    return start(root)


def _publication_workspace_advance(target):
    state(target).head = "changed-head"


@contextmanager
def publication_workspace():
    with fixture() as root:
        begin = _publication_workspace_begin
        advance = _publication_workspace_advance
        yield root, begin, advance
