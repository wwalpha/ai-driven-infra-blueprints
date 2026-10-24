"""Compatibility input-cache exports and content-addressed validation results."""

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import model.files as _imports_model_files
import model.sources as _imports_model_sources
import utils.aws_mappings as _imports_utils_aws_mappings
from utils.file_operations import atomic_replace_file
from utils.input_cache import _baselines as _baselines
from utils.input_cache import _generation_inputs as _generation_inputs
from utils.input_cache import _inputs as _inputs
from utils.input_cache import baseline_scope as baseline_scope
from utils.input_cache import digest_files as digest_files
from utils.input_cache import input_bytes as input_bytes
from utils.input_cache import input_context as input_context
from utils.input_cache import input_exists as input_exists
from utils.input_cache import input_is_dir as input_is_dir
from utils.input_cache import input_is_file as input_is_file
from utils.input_cache import input_is_symlink as input_is_symlink
from utils.input_cache import input_kind as input_kind
from utils.input_cache import input_recorder as input_recorder
from utils.input_cache import input_scope as input_scope
from utils.input_cache import input_select as input_select
from utils.input_cache import input_text as input_text
from utils.input_cache import memo_table as memo_table
from utils.input_cache import memoized as memoized
from utils.input_cache import recording_inputs as recording_inputs


class PassCache:
    def __init__(self, root, fresh=False, directory=None, *, include_project=True, definitions_root=None):
        self.root = root
        definition_root = _imports_utils_aws_mappings.definition_root
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
        model_exists = _imports_model_sources.model_exists
        source_inputs = _imports_model_sources.source_inputs
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
                read_model = _imports_model_files.read_model
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
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            atomic_replace_file(self.directory / f"{key}.json", json.dumps(
                {"version": 1, "key": key, "result": "pass", "checks": checks}))
        except OSError:
            pass  # Cache availability never replaces actual validation.
