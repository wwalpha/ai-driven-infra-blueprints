"""Normal fresh Python startup, optional-dependency boundaries and public CLI entrypoints."""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import worktree
from support.framework_input_isolation_fixtures import (
    PUBLIC_API_MODULES,
    VALIDATION_MODULES,
)
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]
REPOSITORY = FRAMEWORK = ROOT
SCRIPTS = ROOT / "framework/scripts"


@pytest.mark.parametrize(
    "module",
    [
        "design.layout",
        "design.policy_tables",
        "design.services.ec2.security_groups",
        "design.document",
        "model.display",
        "model.validations.full_inputs",
        "model.render",
        "model.change_plan",
        "design.array_display",
        "design.common",
        "design.services.codebuild",
        "design.services.codepipeline",
        "design.services.cloudtrail",
        "design.services.guardduty",
        "design.services.secrets_manager",
    ],
)
def check_import_order(module):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib; importlib.import_module(" + repr(module) + ")",
        ],
        cwd=REPOSITORY / "framework/scripts",
        capture_output=True,
        text=True,
    )
    TestCase().assertTrue(result.returncode == 0, result.stderr)


@pytest.mark.parametrize("name", PUBLIC_API_MODULES)
def check_fresh_import_and_hints(name):
    code = "\nimport importlib, inspect, sys, typing\nmodule = importlib.import_module(sys.argv[1])\nfor value in vars(module).values():\n    if inspect.isfunction(value) and value.__module__ == module.__name__ and not value.__name__.startswith('_'):\n        typing.get_type_hints(value)\n"
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, name],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        timeout=30,
    )
    TestCase().assertTrue(result.returncode == 0, result.stderr)


@pytest.mark.parametrize(
    "statement",
    (
        "import model.validations.full_inputs",
        "import model.render",
        "import model.validations.full_inputs; import model.render",
        "import model.render; import model.validations.full_inputs",
    ),
)
def test_fresh_process_imports(statement):
    env = dict(os.environ, PYTHONPATH=str(SCRIPTS))
    result = subprocess.run(
        [sys.executable, "-B", "-c", statement],
        cwd=FRAMEWORK,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    TestCase().assertTrue(result.returncode == 0, result.stderr)


def check_imports_in_one_process():
    modules = [module.__name__ for module in VALIDATION_MODULES]
    modules.extend(["model.render", "validation.change", "validation.runner"])
    statement = "; ".join((f"import {name}" for name in modules))
    result = subprocess.run(
        [sys.executable, "-B", "-c", statement],
        env=dict(os.environ, PYTHONPATH=str(ROOT / "framework/scripts")),
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    TestCase().assertTrue(result.returncode == 0, result.stderr)


def check_deploy_modules_import_first_in_fresh_processes():
    for module in ("scheduler", "operation_journal", "controller"):
        subprocess.run(
            [sys.executable, "-c", f"import deploy.{module}"],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
            check=True,
            capture_output=True,
        )


def check_local_imports_without_sdk():
    code = "\nimport importlib.abc, sys\nclass NoSdk(importlib.abc.MetaPathFinder):\n    def find_spec(self, fullname, path=None, target=None):\n        if fullname.split('.')[0] in {'boto3', 'botocore'}:\n            raise AssertionError('SDK import forbidden: ' + fullname)\nsys.meta_path.insert(0, NoSdk())\nimport task_contract_runtime, sync_runtime, validation.runner, model.reference_values\nassert 'utils.aws_sdk_runtime' not in sys.modules\n"
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )
    TestCase().assertTrue(result.returncode == 0, result.stderr)


def check_startup_needs_only_standard_library():
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            f"import sys; sys.path.insert(0, {str(Path(worktree.__file__).resolve().parents[1])!r}); from deploy.worktree import start; assert 'yaml' not in sys.modules; assert 'boto3' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    TestCase().assertTrue(result.returncode == 0, result.stderr)


@pytest.mark.parametrize(
    "first",
    [
        "utils.aws.client",
        "comparison.inputs",
        "deploy.controller",
        "model.importing.references",
        "validation.framework_contracts",
    ],
)
def check_import_order_and_blocked_identity(first, tmp_path):
    scripts = Path(__file__).resolve().parents[2]
    code = f"\nimport importlib, sys\nsys.path.insert(0, {str(scripts)!r})\nimportlib.import_module({first!r})\nfrom utils.cloudformation.inputs import Blocked\nfor name in ('utils.aws.client', 'comparison.resource', 'deploy.controller',\n             'model.adapters.observed', 'iac_evaluation'):\n    assert importlib.import_module(name).Blocked is Blocked, name\nassert 'cloudformation_inputs' not in sys.modules\nassert 'cloudformation_schema' not in sys.modules\nassert 'utils.cloudformation_format' not in sys.modules\n"
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    TestCase().assertTrue(result.returncode == 0, result.stdout + result.stderr)


@pytest.mark.parametrize(
    "first",
    [
        "utils.aws_mappings",
        "model.sources",
        "model.adapters.aws",
        "design.policy_tables",
    ],
)
def check_isolated_imports_and_standalone_audit(first, tmp_path):
    scripts = Path(__file__).resolve().parents[2]
    code = f"""\nimport sys, importlib, json\nsys.path.insert(0, {str(scripts)!r})\nimportlib.import_module({first!r})\nfor name in ('model.format', 'model.render', 'model.validations.full_inputs', 'model.importing.inventory',\n             'utils.cloudformation.inputs', 'sync_runtime', 'utils.json_format'):\n    importlib.import_module(name)\nfrom model.audit import definitions\nfrom pathlib import Path\nsource = definitions(Path({str(scripts / "utils/json_format.py")!r}),\n                     ['unique_object', 'invalid_constant', 'policy_json'])\nnamespace = {{'json': json}}\nexec(source, namespace)\nassert namespace['policy_json']('{{"日本語":1}}') == {{'日本語': 1}}\n"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    TestCase().assertTrue(result.returncode == 0, result.stdout + result.stderr)


@pytest.mark.parametrize(
    ("script", "module", "tokens"),
    [
        (
            "deploy_preparation.py",
            "deploy/preparation.py",
            ["Offline Preparation", "--register", "--run-controller", "--service"],
        ),
        (
            "cloudformation-deploy.py",
            "deploy/controller.py",
            ["--action", "--approve-change-set", "MaxConcurrentStacks", "Snapshot"],
        ),
        (
            "deploy_handoff.py",
            "deploy_handoff.py",
            ["inputRefs", "modelRefs", "--discard-failure", "local request.json"],
        ),
        (
            "check-deploy-context.py",
            "aws_context.py",
            [
                "terraform init",
                "terraform plan -out=",
                "terraform apply",
                "partial",
                "AWS_PROFILE",
            ],
        ),
    ],
)
def check_cli_help_and_example_options(script, module, tokens):
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "framework/scripts" / script), "--help"],
        capture_output=True,
        text=True,
    )
    TestCase().assertTrue(result.returncode == 0, result.stderr)
    TestCase().assertTrue(all((token in result.stdout for token in tokens)))
    tree = ast.parse((ROOT / "framework/scripts" / module).read_text())
    options = {"--help"} | {
        a.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and (n.func.attr == "add_argument")
        for a in n.args
        if isinstance(a, ast.Constant)
        and isinstance(a.value, str)
        and a.value.startswith("--")
    }
    for line in result.stdout.splitlines():
        if script in line and line.strip().startswith(("python3 ", "env ")):
            for option in re.findall("--[a-z][a-z-]+", line):
                TestCase().assertTrue(option in options, (script, option))
    if script == "cloudformation-deploy.py":
        TestCase().assertTrue(
            "A failed attempt retains Deploy FAIL when its Task completes."
            in result.stdout
        )
        TestCase().assertTrue("all are needed for COMPLETE" not in result.stdout)
        TestCase().assertTrue(
            all(
                (
                    old not in result.stdout
                    for old in [
                        "--state",
                        "--resume",
                        "--repair-result",
                        "--observe-only",
                    ]
                )
            )
        )


def check_mapping_import_is_lazy():
    # A fresh interpreter verifies import side effects without reloading shared state.
    code = """from pathlib import Path
from unittest.mock import patch
with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected read')):
    import utils.aws_mappings
assert not utils.aws_mappings._instances
"""
    subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT / "framework/scripts", check=True
    )


def check_catalog_lock_cli_startup():
    script = ROOT / "framework/scripts/update-catalog-lock.py"
    normal = subprocess.run([sys.executable, str(script)], capture_output=True)
    isolated = subprocess.run([sys.executable, "-S", str(script)], capture_output=True)
    TestCase().assertEqual(normal.returncode, 0, normal.stderr)
    TestCase().assertEqual(
        (normal.returncode, normal.stdout, normal.stderr),
        (isolated.returncode, isolated.stdout, isolated.stderr),
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
