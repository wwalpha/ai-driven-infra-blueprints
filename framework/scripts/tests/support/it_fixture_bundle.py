"""One immutable collection of authored IT seeds, owned by the suite runner."""

import atexit
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import support.import_model_fixtures as _imports_support_import_model_fixtures
import support.model_sources as _imports_support_model_sources
import support.service_fixtures as _imports_support_service_fixtures
import support.sync_model_fixtures as _imports_support_sync_model_fixtures

ENV = "BLUEPRINT_IT_FIXTURES"
REPOSITORY = Path(__file__).resolve().parents[4]
NAMES = ("input_templates", "typed_services", "generated_policy", "import_sources")
_local = None


def fingerprint(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(str(path.stat().st_mode).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def protect(root, readonly):
    for path in [*root.rglob("*"), root]:
        mode = path.stat().st_mode
        path.chmod(mode & ~0o222 if readonly else mode | 0o200)


def build(root, name):
    destination = root / name
    destination.mkdir()
    if name in ("input_templates", "typed_services"):
        service_fixtures = _imports_support_service_fixtures
        getattr(service_fixtures, "build_" + name)(destination)
    elif name == "import_sources":
        build_seed = _imports_support_import_model_fixtures.build_seed
        build_seed(destination)
    elif name == "generated_policy":
        catalog_display = _imports_support_model_sources.catalog_display
        build_generated_policy = (
            _imports_support_sync_model_fixtures.build_generated_policy
        )
        with catalog_display():
            values = build_generated_policy(destination, definitions_root=REPOSITORY)
        (destination / "fixture-values.json").write_text(
            json.dumps(values), encoding="utf-8"
        )
    else:
        raise ValueError(f"unknown IT fixture: {name}")
    sys.audit("blueprint.it_fixture.generated", name)
    print(f"IT fixture generated: {name}", flush=True)


@contextmanager
def bundle():
    with tempfile.TemporaryDirectory(prefix="framework-it-fixtures-") as directory:
        root = Path(directory)
        try:
            for name in NAMES:
                build(root, name)
            sys.audit("blueprint.it_bundle.initialized")
            protect(root, True)
            before = fingerprint(root)
            yield root
            if fingerprint(root) != before:
                raise RuntimeError("shared IT fixture was modified")
            print("IT shared fixture integrity: PASS", flush=True)
        finally:
            protect(root, False)


def _source_cleanup():
    protect(Path(_local.name), False)
    _local.cleanup()


def source(name):
    """Standalone UT/IT callers get a process-local seed; official runs never regenerate."""
    global _local
    if name not in NAMES:
        raise ValueError(f"unknown IT fixture: {name}")
    if ENV in os.environ:
        return Path(os.environ[ENV]) / name
    if _local is None:
        _local = tempfile.TemporaryDirectory(prefix="framework-test-fixtures-")
        cleanup = _source_cleanup
        atexit.register(cleanup)
    root = Path(_local.name)
    if not (root / name).is_dir():
        build(root, name)
        protect(root / name, True)
    return root / name
