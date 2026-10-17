"""One immutable collection of authored IT seeds, owned by the suite runner."""
from contextlib import contextmanager
from pathlib import Path
import atexit
import hashlib
import json
import os
import shutil
import tempfile
import sys

ENV = 'BLUEPRINT_IT_FIXTURES'
REPOSITORY = Path(__file__).resolve().parents[4]
NAMES = ('framework', 'input_templates', 'typed_services', 'generated_policy', 'import_sources')
_local = None


def fingerprint(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(str(path.stat().st_mode).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def protect(root, readonly):
    for path in [*root.rglob('*'), root]:
        mode = path.stat().st_mode
        path.chmod(mode & ~0o222 if readonly else mode | 0o200)


def build(root, name):
    destination = root / name
    destination.mkdir()
    if name == 'framework':
        shutil.copytree(REPOSITORY / 'framework', destination / 'framework',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    elif name in ('input_templates', 'typed_services'):
        from support import service_fixtures
        getattr(service_fixtures, 'build_' + name)(destination)
    elif name == 'import_sources':
        from support.import_model_fixtures import build_seed
        build_seed(destination)
    elif name == 'generated_policy':
        from support.sync_model_fixtures import build_generated_policy
        from support.model_sources import catalog_display
        # The generator needs framework catalogs; only the authored outputs enter this seed.
        shutil.copytree(root / 'framework/framework', destination / 'framework')
        with catalog_display():
            values = build_generated_policy(destination)
        protect(destination / 'framework', False)
        shutil.rmtree(destination / 'framework')
        (destination / 'fixture-values.json').write_text(json.dumps(values), encoding='utf-8')
    else:
        raise ValueError(f'unknown IT fixture: {name}')
    sys.audit('blueprint.it_fixture.generated', name)
    print(f'IT fixture generated: {name}', flush=True)


@contextmanager
def bundle():
    with tempfile.TemporaryDirectory(prefix='framework-it-fixtures-') as directory:
        root = Path(directory)
        try:
            for name in NAMES:
                build(root, name)
            sys.audit('blueprint.it_bundle.initialized')
            protect(root, True)
            before = fingerprint(root)
            yield root
            if fingerprint(root) != before:
                raise RuntimeError('shared IT fixture was modified')
            print('IT shared fixture integrity: PASS', flush=True)
        finally:
            protect(root, False)


def source(name):
    """Standalone UT/IT callers get a process-local seed; official runs never regenerate."""
    global _local
    if name not in NAMES:
        raise ValueError(f'unknown IT fixture: {name}')
    if ENV in os.environ:
        return Path(os.environ[ENV]) / name
    if _local is None:
        _local = tempfile.TemporaryDirectory(prefix='framework-test-fixtures-')
        def cleanup():
            protect(Path(_local.name), False)
            _local.cleanup()
        atexit.register(cleanup)
    root = Path(_local.name)
    if not (root / name).is_dir():
        if name == 'generated_policy':
            source('framework')
        build(root, name)
        protect(root / name, True)
    return root / name
