"""Fresh Python startup, optional-dependency boundaries and public CLI entrypoints."""

import ast
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPTS = Path(__file__).resolve().parents[2]
IMPORTS = r"""
import importlib
import sys
import traceback

failures = []

def import_modules(names):
    for name in names:
        try:
            importlib.import_module(name)
        except Exception:
            failures.append(f"{name}:\n{traceback.format_exc()}")

sys.path.insert(0, sys.argv[1])
"""
FINISH = r"""
if failures:
    sys.exit("\n".join(failures))
"""


def run_python(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", *args],
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )


def assert_startup(result):
    if result.returncode:
        pytest.fail(
            f"Python exited with {result.returncode}\n{result.stdout}{result.stderr}",
            pytrace=False,
        )


@pytest.mark.parametrize(
    "modules",
    [
        pytest.param(
            (
                "model.validations.full_inputs",
                "model.change_plan",
                "validation.change",
                "validation.runner",
                "design.services.ec2.security_groups",
                "design.layout",
                "design.common",
                "design.services.codebuild",
                "design.services.codepipeline",
                "design.services.cloudtrail",
                "design.services.guardduty",
                "design.services.secrets_manager",
                "model.validations.change_inputs",
                "model.validations.environment",
            ),
            id="validation-and-design",
        ),
        pytest.param(("design.document",), id="document-first"),
        pytest.param(("design.policy_tables",), id="policy-tables-first"),
        pytest.param(
            ("model.render", "model.validations.full_inputs"), id="render-first"
        ),
        pytest.param(("design.array_display",), id="array-display-first"),
        pytest.param(
            ("deploy.scheduler", "deploy.operation_journal", "model.display"),
            id="scheduler-and-model-display-first",
        ),
    ],
)
def check_import_order(modules):
    # Document, policy tables and render form a cycle. Array display and Model display
    # enter a separate cycle that scheduler and journal startup do not load.
    assert_startup(
        run_python(
            "-c",
            IMPORTS + "import_modules(sys.argv[2:])" + FINISH,
            str(SCRIPTS),
            *modules,
            cwd=SCRIPTS,
        )
    )


def check_local_imports_without_sdk():
    code = """
import importlib.abc

class NoSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'boto3', 'botocore'}:
            raise AssertionError('SDK import forbidden: ' + fullname)

sys.meta_path.insert(0, NoSdk())
import_modules(('task_contract_runtime', 'sync_runtime', 'validation.runner',
                'model.reference_values'))
for name in ('boto3', 'botocore', 'utils.aws_sdk_runtime'):
    if name in sys.modules:
        failures.append(f"Unexpected SDK dependency: {name}")
"""
    assert_startup(run_python("-c", IMPORTS + code + FINISH, str(SCRIPTS), cwd=SCRIPTS))


def check_startup_needs_only_standard_library():
    code = """
import sys
sys.path.insert(0, sys.argv[1])
from deploy.progress import progress_path
assert not {'yaml', 'boto3'} & sys.modules.keys()
"""
    assert_startup(run_python("-S", "-c", code, str(SCRIPTS)))


@pytest.mark.parametrize(
    "modules",
    [
        pytest.param(("comparison.inputs",), id="comparison-first"),
        pytest.param(("deploy.controller",), id="deploy-first"),
        pytest.param(
            ("model.importing.references", "model.adapters.aws"),
            id="model-import-first",
        ),
    ],
)
def check_import_order_and_blocked_identity(modules, tmp_path):
    code = """
import_modules(sys.argv[2:])
names = ('utils.cloudformation.inputs', 'utils.aws.client', 'comparison.resource',
         'deploy.controller', 'model.adapters.observed', 'iac_evaluation')
import_modules(names)
canonical = sys.modules.get(names[0])
blocked = getattr(canonical, 'Blocked', None)
if canonical is not None and blocked is None:
    failures.append(f"{names[0]}.Blocked is missing")
for name in names[1:]:
    if blocked is not None and name in sys.modules:
        if getattr(sys.modules[name], 'Blocked', None) is not blocked:
            failures.append(f"{name}.Blocked differs from {names[0]}.Blocked")
for name in ('cloudformation_inputs', 'cloudformation_schema', 'utils.cloudformation_format'):
    if name in sys.modules:
        failures.append(f"Legacy module loaded: {name}")
"""
    assert_startup(
        run_python(
            "-I", "-c", IMPORTS + code + FINISH, str(SCRIPTS), *modules, cwd=tmp_path
        )
    )


def check_isolated_imports_and_standalone_audit(tmp_path):
    code = r"""
import json
from pathlib import Path
from unittest.mock import patch

# Observe the mapping import before any Model or AWS module can cache it.
try:
    with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected read')):
        import utils.aws_mappings as mappings
    assert not mappings._instances, 'mapping instances created during import'
except Exception:
    failures.append(f"Lazy mapping import:\n{traceback.format_exc()}")

import_modules(('model.sources', 'utils.aws.client', 'validation.framework_contracts',
                'model.format', 'model.render', 'model.validations.full_inputs',
                'model.importing.inventory', 'utils.cloudformation.inputs',
                'sync_runtime', 'utils.json_format'))

try:
    from model.audit import definitions
    source = definitions(Path(sys.argv[1]) / 'utils/json_format.py',
                         ['unique_object', 'invalid_constant', 'policy_json'])
    namespace = {'json': json}
    exec(source, namespace)
    assert namespace['policy_json']('null') is None
except Exception:
    failures.append(f"Standalone audit JSON:\n{traceback.format_exc()}")
"""
    assert_startup(
        run_python("-I", "-c", IMPORTS + code + FINISH, str(SCRIPTS), cwd=tmp_path)
    )


@pytest.mark.parametrize(
    ("script", "module", "options"),
    [
        (
            "deploy_preparation.py",
            "deploy/preparation.py",
            {"--register", "--run-controller", "--service"},
        ),
        (
            "cloudformation-deploy.py",
            "deploy/controller.py",
            {"--action", "--approve-change-set"},
        ),
        ("check-deploy-context.py", "aws_context.py", {"--environment", "--alias"}),
    ],
)
def check_cli_help_and_example_options(script, module, options):
    result = run_python(str(SCRIPTS / script), "--help")
    assert_startup(result)
    advertised = set(re.findall(r"--[a-z][a-z-]+", result.stdout))
    missing = options - advertised
    retired = (
        advertised & {"--state", "--resume", "--observe-only"}
        if script == "cloudformation-deploy.py"
        else set()
    )
    tree = ast.parse((SCRIPTS / module).read_text(encoding="utf-8"))
    declared = {"--help"} | {
        arg.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for arg in node.args
        if isinstance(arg, ast.Constant)
        and isinstance(arg.value, str)
        and arg.value.startswith("--")
    }
    unknown = {
        option
        for line in result.stdout.splitlines()
        if script in line and line.strip().startswith(("python3 ", "env "))
        for option in re.findall(r"--[a-z][a-z-]+", line)
        if option not in declared
    }
    assert not (missing or unknown or retired), (
        f"{script}: missing options {sorted(missing)}, unknown example options {sorted(unknown)}, "
        f"retired options {sorted(retired)}"
    )


def check_catalog_lock_cli_startup():
    script = str(SCRIPTS / "update-catalog-lock.py")
    normal = run_python(script)
    isolated = run_python("-S", script)
    assert (normal.returncode, isolated.returncode) == (0, 0), (
        f"normal: {normal.stdout}{normal.stderr}\n-S: {isolated.stdout}{isolated.stderr}"
    )
    assert (normal.stdout, normal.stderr) == (isolated.stdout, isolated.stderr)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
