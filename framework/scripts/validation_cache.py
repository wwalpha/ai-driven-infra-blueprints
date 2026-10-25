"""Invocation-local validation results."""

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
from utils.input_cache import digest_files, input_select, memo_table


class PassCache:
    def __init__(
        self,
        root,
        fresh=False,
        directory=None,
        *,
        include_project=True,
        definitions_root=None,
    ):
        self.root = root
        definition_root = _imports_utils_aws_mappings.definition_root
        self.definitions_root = definitions_root or definition_root(root)
        self.fresh = fresh
        self.common = None
        self.include_project = include_project
        self.directory = Path(
            directory
            or os.environ.get("BLUEPRINT_VALIDATION_CACHE_DIR")
            or Path(tempfile.gettempdir()) / "blueprint-validation-cache"
        ).resolve()
        if self.directory == root or root in self.directory.parents:
            raise ValueError("validation cache must be outside the repository")
        # No trusted Framework release identity exists: never reuse a prior run's PASS.
        self.passes = {}

    def common_inputs(self, snapshot=None):
        """Mutable Project dependencies; Framework/distributed definitions are static."""
        base = self.root / ".agents"
        if snapshot is None:
            selected = input_select(
                base, "*", recursive=True, kinds=("file", "symlink")
            )
        else:
            selected = snapshot.select(base, "*", True, ("file", "symlink"))
        paths = {
            p for p in selected if not (p.suffix == ".pyc" and "__pycache__" in p.parts)
        }
        paths.update(self.root / name for name in ("AGENTS.md", "README.md"))
        if self.include_project:
            paths.add(self.root / "project.json")
        if snapshot is not None:
            for path in paths:
                snapshot.read(path)
        return {self.root: paths}

    def common_key(self, contents=None, *, snapshot=None):
        groups = self.common_inputs(snapshot)
        if snapshot is not None:
            contents = snapshot.contents
        inputs = [
            [str(root), digest_files(root, paths, contents)]
            for root, paths in groups.items()
        ]
        return hashlib.sha256(json.dumps(inputs).encode()).hexdigest()

    def key(self, kind, inputs=""):
        if self.common is None:
            self.common = self.common_key()
        return hashlib.sha256(
            json.dumps(
                [1, sys.version, sys.platform, kind, self.common, inputs]
            ).encode("utf-8")
        ).hexdigest()

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
                paths.update(
                    file
                    for file in entrance.with_suffix("").rglob("*")
                    if file.is_file() or file.is_symlink()
                )
            paths.update(
                file
                for file in model.with_suffix("").rglob("*")
                if file.is_file() or file.is_symlink()
            )
            texts = [path.read_text(encoding="utf-8")]
            if model_exists(model):
                read_model = _imports_model_files.read_model
                texts.append(read_model(model))
            for text in texts:
                for raw in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                    if raw.startswith(("https://", "http://", "mailto:")):
                        continue
                    dependency = (
                        (path.parent / raw.partition("#")[0]).resolve()
                        if raw.partition("#")[0]
                        else path
                    )
                    if (
                        not dependency.is_relative_to(self.root)
                        or not dependency.is_file()
                    ):
                        raise ValueError(
                            "unknown design dependency; require fresh validation"
                        )
                    if dependency.suffix == ".md":
                        pending.append(dependency)
                    else:
                        paths.add(dependency)
        return self.key("service:" + "/".join(entry), digest_files(self.root, paths))

    def _results(self):
        memo = memo_table()
        if memo is None:
            return self.passes
        return memo.setdefault(
            (PassCache, self.root, self.definitions_root, self.directory), {}
        )

    def load(self, key):
        if self.fresh or key is None:
            return None
        return self._results().get(key)

    def save(self, key, checks):
        if key is None or type(checks) is not int or checks <= 0:
            return
        self._results()[key] = checks
