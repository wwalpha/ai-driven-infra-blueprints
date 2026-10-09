"""Invocation-local input reuse and content-addressed successful validation results."""

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


def input_scope(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _inputs.get() is not None:
            return function(*args, **kwargs)
        token = _inputs.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _inputs.reset(token)
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


def digest_files(root, paths):
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if any((root.joinpath(*relative.parts[:number])).is_symlink()
               for number in range(1, len(relative.parts) + 1)):
            raise ValueError("symlink inputs cannot reuse validation results")
        content = path.read_bytes() if path.is_file() else None
        # Length-delimited names and byte hashes distinguish missing/empty/new files.
        digest.update(json.dumps([relative.as_posix(), None if content is None else
                                  hashlib.sha256(content).hexdigest()]).encode("utf-8"))
    return digest.hexdigest()


class PassCache:
    def __init__(self, root, fresh=False, directory=None):
        self.root = root
        self.fresh = fresh
        self.common = None
        self.directory = Path(directory or os.environ.get("BLUEPRINT_VALIDATION_CACHE_DIR") or
                              Path(tempfile.gettempdir()) / "blueprint-validation-cache").resolve()
        if self.directory == root or root in self.directory.parents:
            raise ValueError("validation cache must be outside the repository")

    def common_key(self):
        paths = [self.root / "project.json", self.root / "AGENTS.md", self.root / "README.md"]
        paths.extend(path for directory in ("framework", ".agents")
                     for path in (self.root / directory).rglob("*") if path.is_file() or path.is_symlink())
        inputs = [digest_files(self.root, paths)]
        runtime = Path(__file__).resolve().parents[2]
        if runtime != self.root:
            inputs.append(digest_files(runtime, [path for path in (runtime / "framework").rglob("*")
                                                 if path.is_file() or path.is_symlink()]))
        return hashlib.sha256(json.dumps(inputs).encode()).hexdigest()

    def key(self, kind, inputs=""):
        if self.common is None:
            self.common = self.common_key()
        return hashlib.sha256(json.dumps([1, sys.version, sys.platform, kind,
                                         self.common, inputs]).encode("utf-8")).hexdigest()

    def service_key(self, entry):
        from model_files import model_parts
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
            if model.is_file():
                paths.update([model, *model_parts(model)])
            elif path == docs / environment / target / f"{service}.md":
                raise ValueError("missing service model")
            # Include the complete file set to detect orphan artifacts and unlisted parts.
            for entrance in (path, model):
                paths.update(file for file in entrance.with_suffix("").rglob("*")
                             if file.is_file() or file.is_symlink())
            texts = [path.read_text(encoding="utf-8")]
            if model.is_file():
                texts.extend(part.read_text(encoding="utf-8") for part in model_parts(model))
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
