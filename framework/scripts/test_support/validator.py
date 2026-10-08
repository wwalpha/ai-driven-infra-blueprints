"""Shared validator instance and isolated filesystem/Git setup for checks."""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import subprocess
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / "validate-blueprint.py"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPT.with_name(name + ".py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load("validate-blueprint")


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
    path.write_text(text, encoding="utf-8")


def schema_validator(root):
    validator = MODULE.Validator(root)
    validator.schema_catalog = MODULE.DesignSchemaCatalog(SCRIPT.parents[2])
    return validator
