"""Shared validator instance and isolated filesystem/Git setup for checks."""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import subprocess
import sys
from threading import RLock
import tempfile

SCRIPT = Path(__file__).resolve().parents[2] / "validate-blueprint.py"


_load_lock = RLock()


def load(name, module_name=None):
    with _load_lock:
        if module_name is not None and module_name in sys.modules:
            return sys.modules[module_name]
        path = SCRIPT.with_name(name + ".py")
        if name == "conftest":
            path = SCRIPT.parent / "tests/conftest.py"
        elif name.endswith(".checks"):
            matches = list((SCRIPT.parent / "tests").glob("*/" + name + ".py"))
            if len(matches) != 1:
                raise ValueError(f"expected one test module: {name}; found {len(matches)}")
            path = matches[0]
        spec = importlib.util.spec_from_file_location(module_name or name.replace("-", "_"), path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        if module_name is not None:
            sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


from validation import runner as MODULE


@contextmanager
def project():
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory).resolve()


@contextmanager
def git_project():
    with project() as root:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        yield root


def commit(root, paths, message):
    subprocess.run(["git", "add", *paths], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", message], cwd=root, check=True)


def write(path, text):
    from support.model_sources import write_fixture_files
    write_fixture_files({path: text})


def schema_validator(root):
    validator = MODULE.Validator(root, definitions_root=SCRIPT.parents[2])
    validator.schema_catalog = MODULE.DesignSchemaCatalog(SCRIPT.parents[2])
    return validator
