"""Shared validator instance and isolated filesystem/Git setup for checks."""

import importlib.util
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

import support.model_sources as _imports_support_model_sources
from validation import runner as MODULE

SCRIPT = Path(__file__).resolve().parents[2] / "validate-blueprint.py"


_load_lock = RLock()


def load(name, module_name=None):
    if name in {"cloudformation-deploy", "check-deploy-context", "deploy_preparation"}:
        return importlib.import_module({"cloudformation-deploy": "deploy.controller", "check-deploy-context": "aws_context", "deploy_preparation": "deploy.preparation"}[name])
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
    write_fixture_files = _imports_support_model_sources.write_fixture_files
    write_fixture_files({path: text})


def schema_validator(root):
    validator = MODULE.Validator(root, definitions_root=SCRIPT.parents[2])
    validator.schema_catalog = MODULE.DesignSchemaCatalog(SCRIPT.parents[2])
    return validator


def diagnostics(validator):
    """Assert blocking errors separately where severity matters; retain all messages here."""
    return [*validator.errors, *(item['message'] for item in validator.findings.warnings)]
