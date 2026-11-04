"""Model reader, publisher, CLI and Review integration over synthetic properties."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import subprocess
import tempfile
from unittest import TestCase

import model.observed as _imports_model_observed
import model.operations as _imports_model_operations
import model.sources as _imports_model_sources
import pytest
import support.repository_fixtures as _imports_support_repository_fixtures
from generation_inputs import GenerationInputs
from model.adapters.task import (
    edit_write_context,
    observed_write_context,
    source_write_context,
)
from model.audit import generate
from model.cli import main
from model.format import parse, patch, serialize
from model.format import split as split
from model.sources import Scope, load_model
from support.model_sources import catalog_display
from support.model_v2_fixtures import format_fixture as fixture
from support.model_v2_fixtures import (
    logs_fixture,
    properties_fixture,
    source_context,
)
from support.sync_model_fixtures import build_generated_policy
from sync_runtime import generate_views, stage_inputs
from task_contract_core import selected_task
from utils.aws_mappings import mapping_alias
from utils.input_cache import input_context, recording_inputs

import model as _imports_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_cli_subprocess_and_canonical_imports():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = fixture(Path(directory))
        cli = Path(__file__).resolve().parents[2] / "model/cli.py"
        help_result = subprocess.run(
            [sys.executable, "-B", str(cli), "edit", "--help"],
            capture_output=True, text=True,
        )
        assert help_result.returncode == 0
        assert "external directory" in help_result.stdout
        assert "not a single properties file" in " ".join(help_result.stdout.split())
        environment = {
            key: value for key, value in os.environ.items() if key != "PYTHONPATH"
        }
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(cli), "read", str(scope.path)],
            capture_output=True,
            text=True,
            env=environment,
            cwd=directory,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["authoritative"] == values
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(cli),
                "trace",
                str(scope.path),
                "desired.resource.007.logicalId",
            ],
            capture_output=True,
            text=True,
            env=environment,
            cwd=directory,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["value"] == "EC2_VPC_001"
        source_load = _imports_model_sources.load_model

        public_load = _imports_model.load_model
        assert public_load is source_load
        assert source_load(scope).__class__ is load_model(scope).__class__


def check_observed_byte_preservation_and_one_use():
    prepare_observed = _imports_model.prepare_observed
    publish_edit = _imports_model.publish_edit
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        snapshot, context = source_context(scope)
        original = scope.path.read_bytes()
        try:
            plan = prepare_observed(
                snapshot, {"observed.row.007-001.value": "vpc-new"}, context
            )
            assert (
                plan.candidate.authoritative["observed.row.007-001.value"] == "vpc-new"
            )
            publish_edit(plan, context)
            assert scope.path.read_bytes() == original.replace(
                b"observed.row.007-001.value=\n",
                b"observed.row.007-001.value=vpc-new\n",
            )
        finally:
            context.close()


def check_stack_render_cli_uses_only_canonical_modules():
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = fixture(Path(directory))
        stack = Scope(
            scope.root, scope.environment, scope.target, "cloudformation-stacks"
        )
        stack.path.write_text(
            serialize(
                {
                    "desired.stack.009.name": "NewStackName",
                    "desired.stack.009.placementName": "FixedPlacement",
                    "desired.stack.009.template": "stack.yaml",
                    "desired.stack.009.parameters": "stack.json",
                    "desired.stack.009.deployOrder": "1",
                    "display.stack.009.comment": "合成表示",
                }
            ),
            encoding="utf-8",
        )
        scripts = Path(__file__).resolve().parents[2]
        program = """import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])

from model import load_model,render_model
from model.importing.approval import build_review
from model.importing.references import Resolver
from model.adapters.task import source_write_context
snapshot=load_model(Path(sys.argv[2]))
rendered=render_model(snapshot,None)
assert not any(name.startswith('model_') for name in sys.modules), sorted(sys.modules)
assert 'NewStackName' in next(iter(rendered.values()))
assert 'FixedPlacement' not in next(iter(rendered.values()))
print(json.dumps({'rendered':len(rendered)}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", program, str(scripts), str(stack.path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"rendered": 1}
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(scripts / "model/cli.py"),
                "render",
                str(stack.path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "NewStackName" in next(iter(json.loads(result.stdout).values()))
        assert not (scope.root / "docs/designs").exists()


def check_properties_normal_generation_uses_new_authority(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    root = tmp_path / "synthetic"
    root.mkdir()
    framework = Path(__file__).resolve().parents[4]
    with catalog_display(), mapping_alias(framework, root):
        _ = build_generated_policy(root, definitions_root=framework)
        model = root / "model/dev/123456789012/iam.properties"
        design = root / "docs/designs/dev/123456789012/iam.md"
        artifact = design.with_suffix("") / "iam-role-001-trust-policy.json"
        before = {path: path.read_bytes() for path in (model, design, artifact)}
        inputs = GenerationInputs(root, framework)
        try:
            stage = inputs.open_stage()
            with recording_inputs(inputs):
                snapshot = load_model(model, inputs)
                stage_inputs(
                    stage,
                    root,
                    {design: snapshot.values},
                    [model],
                    [design],
                    ["iam"],
                    False,
                    inputs,
                    framework,
                )
                failures = []
                generated = generate_views(
                    stage, root, {design: snapshot.values}, failures, framework
                )
            assert not failures, failures
            assert generated[design]
            assert (stage / model.relative_to(root)).read_bytes() == before[model]
            assert (stage / artifact.relative_to(root)).read_bytes() == before[artifact]
            assert (stage / design.relative_to(root)).read_bytes() == before[design]
            assert not (stage / "framework").exists()
            assert all(
                not any(name in path.parts for name in ("templates", "parameters"))
                for path in inputs.contents
                if path.is_relative_to(root / "model")
            )
            inputs.verify()
        finally:
            inputs.close()
        assert {path: path.read_bytes() for path in before} == before


def check_managed_properties_save(monkeypatch):
    fixture = _imports_support_repository_fixtures.fixture
    git = _imports_support_repository_fixtures.git
    start = _imports_support_repository_fixtures.start

    prepare_edit = _imports_model.prepare_edit
    publish_edit = _imports_model.publish_edit
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    with fixture() as root, input_context():
        scope = properties_fixture(root)
        relative = scope.path.relative_to(root).as_posix()
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "synthetic properties")
        target, state = start(root, files=(relative,))
        name = state["task_file"]
        contract = """# Model deletion
## Task contract
- Task type: `design`
- Task status: `running`
- Workflow: `update`
- Model operation: `model-delete`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`
## Model delete sources
- `qa-synthetic/team-a/network/007`
## Validation scope
- `qa-synthetic/team-a/network`
## Required changes
- [R1] Synthetic Model-only deletion
## Acceptance checks
- [R1] `exists:project.json`
"""
        listed = "".join("- `" + item + "`\n" for item in (name, relative))
        for heading in ("Modified files", "Allowed paths"):
            contract += "\n## " + heading + "\n" + listed
        (target / name).write_text(contract, encoding="utf-8")
        path = target / relative
        original = path.read_bytes()
        with source_write_context(target, name) as context:
            snapshot = load_model(path, context.snapshot)
            proposed = patch(
                snapshot.documents[path], {"desired.row.007-001.comment": "中間保存"}
            )
            plan = prepare_edit(snapshot, {path: proposed}, context)
            TestCase().assertEqual(publish_edit(plan, context), (path,))
            TestCase().assertEqual(path.read_text(encoding="utf-8"), proposed)
            TestCase().assertTrue(context.closed)
        assert (root / relative).read_bytes() == original


def check_properties_standalone_audit_has_no_framework_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    model = logs_fixture(tmp_path)
    original = model.read_bytes()
    source, inputs, _ = generate(tmp_path, "qa-synthetic", "team-a", "cloudwatch-logs")
    assert model.relative_to(tmp_path).as_posix() in inputs
    assert not any(
        path.endswith(("parameters.yaml", "bindings.json", "observed.json"))
        for path in inputs
    )
    output = tmp_path / "standalone.py"
    output.write_text(source, encoding="utf-8")
    program = """import sys,subprocess
from pathlib import Path
def forbidden(*args,**kwargs): raise AssertionError('audit setup called a subprocess')
subprocess.run=forbidden
namespace={'__name__':'standalone_audit_test'}
exec(compile(Path(sys.argv[1]).read_text(encoding='utf-8'),sys.argv[1],'exec'),namespace)
engine=namespace['engine'](namespace['SNAPSHOT'])
assert engine.service_module('cloudwatch-logs').one is engine.one
assert not any(name=='model' or name.startswith('model.') for name in sys.modules)
print('standalone audit engine: PASS')
"""
    checked = subprocess.run(
        [sys.executable, "-I", "-B", "-c", program, str(output)],
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert model.read_bytes() == original


def check_managed_observation_preserves_exact_authority(monkeypatch):
    prepare_observed = _imports_model_observed.prepare_observed
    publish_edit = _imports_model_operations.publish_edit
    fixture = _imports_support_repository_fixtures.fixture
    git = _imports_support_repository_fixtures.git
    start = _imports_support_repository_fixtures.start
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    with fixture() as root:
        scope = properties_fixture(root)
        values = dict(load_model(scope).authoritative)
        values["desired.resource.007.resourceMode"] = "CREATE"
        values["desired.row.007-002.property"] = "EC2.VPC.Name"
        values["desired.row.007-002.value"] = "synthetic"
        values["desired.row.007-002.comment"] = "合成名前"
        scope.path.write_text(
            serialize(values) + "# preserve original trailing comment  \n",
            encoding="utf-8",
        )
        relative = scope.path.relative_to(root).as_posix()
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "synthetic CREATE observation")
        target, state = start(root, files=(relative,))
        name, path = state["task_file"], target / relative
        listed = "".join("- `" + item + "`\n" for item in (name, relative))
        contract = """# Observation fixture
## Task contract
- Task type: `design`
- Task status: `running`
- Workflow: `update`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`
## Validation scope
- `qa-synthetic/team-a/network`
## Required changes
- [R1] Synthetic selected observation
## Acceptance checks
- [R1] `exists:project.json`
"""
        for heading in ("Modified files", "Allowed paths"):
            contract += "\n## " + heading + "\n" + listed
        (target / name).write_text(contract, encoding="utf-8")
        original = path.read_bytes()
        key = "observed.row.007-001.value"
        with (
            selected_task(target, name),
            observed_write_context(target, {path: {key: "`vpc-updated`"}}) as context,
        ):
            snapshot = load_model(path, context.snapshot)
            plan = prepare_observed(snapshot, {key: "`vpc-updated`"}, context)
            publish_edit(plan, context)
            TestCase().assertEqual(
                path.read_text(encoding="utf-8"),
                patch(parse(original.decode("utf-8")), {key: "`vpc-updated`"}),
            )
            TestCase().assertEqual(
                dict(load_model(path).authoritative),
                {**snapshot.authoritative, key: "`vpc-updated`"},
            )
        assert (root / relative).read_bytes() == original


@pytest.mark.parametrize(
    "change", ["display", "create", "import-config", "fixed-id", "cli"]
)
def check_ordinary_properties_edit_uses_real_task_guard(monkeypatch, tmp_path, capsys, change):
    prepare_edit = _imports_model_operations.prepare_edit
    publish_edit = _imports_model_operations.publish_edit
    fixture = _imports_support_repository_fixtures.fixture
    git = _imports_support_repository_fixtures.git
    start = _imports_support_repository_fixtures.start
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    with fixture() as root:
        scope = properties_fixture(root)
        if change == "create":
            values = dict(load_model(scope).authoritative)
            values["desired.resource.007.resourceMode"] = "CREATE"
            values["desired.resource.007.cfn-logicalId"] = "fixture-Vpc"
            scope.path.write_text(serialize(values), encoding="utf-8")
        if change == "fixed-id":
            values = dict(load_model(scope).authoritative)
            del values["desired.resource.007.cfn-logicalId"]
            scope.path.write_text(serialize(values), encoding="utf-8")
        relative = scope.path.relative_to(root).as_posix()
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "synthetic editable Model")
        target, state = start(root, files=(relative,))
        name, path = state["task_file"], target / relative
        listed = "".join("- `" + item + "`\n" for item in (name, relative))
        contract = "# Ordinary Model edit\n## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n## Validation scope\n- `qa-synthetic/team-a/network`\n## Required changes\n- [R1] Explicit candidate edit\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        for heading in ("Modified files", "Allowed paths"):
            contract += "\n## " + heading + "\n" + listed
        (target / name).write_text(contract, encoding="utf-8")
        original = path.read_bytes()
        fields = {"display.resource.007.label": "explicit display"}
        if change in {"create", "import-config"}:
            fields = {
                "desired.row.007-001.value": '`{ "$modelRef": {"logicalId": "EC2_VPC_001", "attribute": "VpcId"} }`'
            }
        elif change == "fixed-id":
            fields = {
                "desired.resource.007.logicalId": "EC2_VPC_002",
                "desired.row.007-001.value": '`{"$modelRef":{"logicalId":"EC2_VPC_002","attribute":"VpcId"}}`',
                "desired.service.identity.lastAllocated": '{"EC2.VPC":2}',
            }
        with selected_task(target, name):
            if change == "cli":
                before = load_model(path)
                candidate = tmp_path / "candidate" / relative
                candidate.parent.mkdir(parents=True)
                candidate.write_text(
                    patch(before.documents[path], fields), encoding="utf-8"
                )
                assert main([
                    "edit", str(path), "--candidate", str(candidate), "--task-file", name
                ]) == 1
                assert "directory, not a file" in capsys.readouterr().err
                assert path.read_bytes() == original
                assert (
                    main(
                        [
                            "edit",
                            str(path),
                            "--candidate",
                            str(tmp_path / "candidate"),
                            "--task-file",
                            name,
                        ]
                    )
                    == 0
                )
            else:
                with edit_write_context(
                    target, {("qa-synthetic", "team-a", "network")}, name
                ) as context:
                    before = load_model(path, context.snapshot)
                    candidate = patch(before.documents[path], fields)
                    publish_edit(
                        prepare_edit(before, {path: candidate}, context), context
                    )
                    assert path.read_text(encoding="utf-8") == candidate
        assert (root / relative).read_bytes() == original


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
