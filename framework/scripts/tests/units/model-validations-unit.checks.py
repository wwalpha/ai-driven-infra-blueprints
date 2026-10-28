"""Model 検証モジュールの接続・診断順序と移管した命名検証を確認する。"""

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from model.validations import (
    change_inputs,
    environment,
    full_inputs,
    identity,
    json_settings,
    naming,
    policies,
    presentation,
    references,
    schema,
    stacks,
    structure,
)
from model.validations.naming import (
    design_naming_errors,
    naming_errors,
    naming_rule_files,
    naming_target_matches,
    naming_targets,
)
from support.producer_identifier_reference_fixtures import resource, setup
from support.pytest_cli import run
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from validation.findings import Findings

from model import change_plan, sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]
MODULES = (
    full_inputs,
    change_inputs,
    structure,
    naming,
    schema,
    json_settings,
    environment,
    references,
    policies,
    identity,
    stacks,
    presentation,
)


@pytest.mark.parametrize(
    "module", MODULES, ids=lambda module: module.__name__.rsplit(".", 1)[-1]
)
def check_module_structure_and_imports(module):
    path = Path(module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert functions
    for node in functions:
        assert ast.get_docstring(node)
        assert node.returns is not None
        assert all(
            arg.annotation is not None
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        )
        assert not any(
            isinstance(
                child,
                (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef),
            )
            for statement in node.body
            for child in ast.walk(statement)
        )


def check_imports_in_one_process():
    modules = [module.__name__ for module in MODULES]
    modules.extend(["model.render", "validation.change", "validation.runner"])
    statement = "; ".join(f"import {name}" for name in modules)
    result = subprocess.run(
        [sys.executable, "-B", "-c", statement],
        env=dict(os.environ, PYTHONPATH=str(ROOT / "framework/scripts")),
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "owner,name",
    [
        (schema, "validate_required_properties"),
        (schema, "validate_api_constraints"),
        (schema, "_callback_check_model_inputs_literal_check"),
        (naming, "_callback_check_model_inputs_names"),
        (identity, "validate_resource_identities"),
        (json_settings, "validate_json_settings"),
    ],
)
def check_full_and_change_share_rules(owner, name):
    assert getattr(full_inputs, name) is getattr(owner, name)
    assert getattr(change_inputs, name) is getattr(owner, name)


@pytest.mark.parametrize("failure", [False, True])
def check_structure_order_and_short_circuit(failure):
    calls = []
    keys = Mock(side_effect=ValueError("invalid keys") if failure else None)
    rows = Mock()
    calls.extend([keys, rows])
    parent = Mock()
    parent.attach_mock(keys, "keys")
    parent.attach_mock(rows, "rows")
    values = {"desired.service.logs.serviceId": "logs"}
    if failure:
        with pytest.raises(ValueError, match="invalid keys"):
            structure._callback_check_model_inputs_structure(rows, keys, values)
        rows.assert_not_called()
    else:
        structure._callback_check_model_inputs_structure(rows, keys, values)
        assert [call[0] for call in parent.mock_calls] == ["keys", "rows"]
    keys.assert_called_once_with(values)


def check_reference_adapter_preserves_context_and_warnings(tmp_path):
    path = tmp_path / "model/preview/team/logs.properties"
    view = tmp_path / "docs/designs/preview/team/logs.md"
    values = {"desired.service.logs.serviceId": "logs"}
    findings = Findings(tmp_path, source_path=path)
    warnings = [{"code": "fixture.reference", "message": "unresolved fixture"}]
    with patch("model.references.diagnose", return_value=(warnings, {})) as diagnose:
        references._callback_check_model_inputs_references(
            SimpleNamespace(view=view), findings, tmp_path, values
        )
    candidate = diagnose.call_args.args[0]
    assert candidate.scope.path == path
    assert candidate.authoritative is values
    assert candidate.dependencies == {}
    assert diagnose.call_args.kwargs["errors"] is findings.errors
    assert findings.warnings == warnings


@pytest.mark.parametrize("source", ["model", "view"])
def check_presentation_adapter_uses_canonical_scope(tmp_path, source):
    model = tmp_path / "model/preview/team/logs.properties"
    view = tmp_path / "docs/designs/preview/team/logs.md"
    values = {"desired.service.logs.serviceId": "logs"}
    findings = Findings(tmp_path, source_path=model)
    details = Mock()
    anchors = {"001": "saved-anchor"}
    with patch.object(
        presentation, "bound_resource_anchors", return_value=anchors
    ) as bound:
        presentation._callback_check_model_inputs_presentation(
            ROOT,
            findings,
            ["Logs.LogGroup"],
            model if source == "model" else view,
            details,
            [],
            tmp_path,
            "logs",
            values,
        )
    bound.assert_called_once_with(view)
    assert details.call_args.args == (
        values,
        ROOT,
        "logs",
        ["Logs.LogGroup"],
        [],
        anchors,
    )
    assert details.call_args.kwargs["scope"].path == model
    assert details.call_args.kwargs["findings"] is findings


@pytest.mark.parametrize("failure", [False, True])
def check_json_adapter_order_and_reference_authority(tmp_path, failure):
    view = tmp_path / "docs/designs/preview/team/logs.md"
    model = tmp_path / "model/preview/team/logs.properties"
    values, authority, warnings = {}, {"fixture": "context"}, []
    excluded = {("001-001", "document", "/Resource")}
    parent = Mock()
    env = Mock(side_effect=ValueError("pending fixture") if failure else None)
    document = Mock()
    parent.attach_mock(env, "environment")
    parent.attach_mock(document, "document")
    with (
        patch.object(json_settings, "validate_environment_settings", env),
        patch.object(json_settings, "validate_json_documents", document),
    ):
        if failure:
            with pytest.raises(ValueError, match="pending fixture"):
                json_settings.validate_json_settings(
                    values,
                    view,
                    warnings=warnings,
                    excluded_references=excluded,
                    reference_values=authority,
                )
        else:
            json_settings.validate_json_settings(
                values,
                view,
                warnings=warnings,
                excluded_references=excluded,
                reference_values=authority,
            )
    env.assert_called_once_with(
        values, model, warnings=warnings, reference_values=authority
    )
    if failure:
        document.assert_not_called()
    else:
        document.assert_called_once_with(
            values,
            view,
            warnings=warnings,
            excluded_references=excluded,
            reference_values=authority,
        )
        assert [call[0] for call in parent.mock_calls] == ["environment", "document"]


@pytest.mark.parametrize("mode", ["full", "change"])
def check_ordered_schema_diagnostic_contract(project_workspace, mode):
    root = project_workspace
    setup(root, ["logs"], [])
    path = root / "model/preview/team/logs.properties"
    before = resource(
        "001",
        "Logs.LogGroup",
        "logs-001",
        [("LogGroupName", "fixture-001"), ("RetentionInDays", "7")],
    )
    before["desired.service.logs.ownedCatalogResourceTypes"] = "Logs.LogGroup"
    after = {**before, "desired.row.001-002.value": "bad"}
    if mode == "full":
        findings = full_inputs.check_model_inputs(path, after, root)
        check_id = "model.literal.001-002"
    else:
        old = SimpleNamespace(scope=sources.scope_for(path), authoritative=before)
        new = SimpleNamespace(scope=sources.scope_for(path), authoritative=after)
        selected = change_plan.compare(old, new)
        with patch.object(
            full_inputs,
            "check_model_inputs",
            side_effect=AssertionError("Full called from Change"),
        ):
            findings = change_inputs.check_change_inputs(path, after, root, selected)
        check_id = "change.literal.001-002"
    assert findings.errors == [
        "provider schema violation: Logs.LogGroup.RetentionInDays: must be integer"
    ]
    assert findings.warnings == []
    assert findings.checks == 1
    assert [
        (item.code, item.check_id, item.cause_kind, item.location)
        for item in findings.diagnostics
    ] == [
        (
            "validation.check",
            check_id,
            "input_invalid",
            "desired.resource.001/Logs.LogGroup.RetentionInDays",
        )
    ]


def _callback_check_service_scoped_naming_scoped_read(
    read_text, /, path, *args, **kwargs
):
    if path.parent.name == "aws-resource-naming":
        assert path.name == "S3.md", f"unselected naming rule read: {path}"
    return read_text(path, *args, **kwargs)


def check_service_scoped_naming(tmp_path):
    datazone_targets = naming_targets(ROOT, "DataZone")
    for kind in ("DataZone.Domain", "DataZone.Project", "DataZone.DataSource"):
        assert datazone_targets[kind] == {"Name"}, kind
        assert not design_naming_errors(ROOT, kind), kind
    selected = naming_rule_files(ROOT, "S3")
    assert [path.name for path in selected] == ["aws-resource-naming.md", "S3.md"]
    read_text = Path.read_text

    scoped_read = _bind_framework_callback(
        _callback_check_service_scoped_naming_scoped_read, read_text
    )

    with patch.object(Path, "read_text", scoped_read):
        assert not naming_errors(
            ROOT,
            "S3.Bucket",
            [["1", "BucketName", "`app-dev-data-123456789012`", "名前"]],
        )
        assert set(naming_targets(ROOT, "S3")) == {"S3.Bucket"}


def check_naming_target_paths():
    targets = naming_targets(ROOT, "CodeBuild")["CodeBuild.Project"]
    assert naming_target_matches("Name", targets, "CodeBuild.Project")
    assert not naming_target_matches(
        "Environment.EnvironmentVariables[].Name", targets, "CodeBuild.Project"
    )
    assert not naming_target_matches("Artifacts.Name", targets, "CodeBuild.Project")
    pipeline = naming_targets(ROOT, "CodePipeline")["CodePipeline.Pipeline"]
    assert naming_target_matches("Name", pipeline, "CodePipeline.Pipeline")
    for field in ("Stages[].Name", "Stages[].Actions[].Name", "Variables[].Name"):
        assert not naming_target_matches(field, pipeline, "CodePipeline.Pipeline"), (
            field
        )
    glue = naming_targets(ROOT, "Glue")["Glue.Job"]
    assert naming_target_matches("Name", glue, "Glue.Job")
    assert not naming_target_matches("Command.Name", glue, "Glue.Job")
    # An explicitly declared nested target remains exact and valid.
    s3 = naming_targets(ROOT, "S3")["S3.Bucket"]
    assert naming_target_matches("LifecycleConfiguration.Rules[].Id", s3, "S3.Bucket")
    assert not naming_target_matches("Other.Rules[].Id", s3, "S3.Bucket")
    print("Naming Target paths: PASS (root-only implicit match, exact nested target)")


@pytest.mark.parametrize(
    "kind, field",
    [
        ("Logs.LogGroup", "LogGroupName"),
        ("Scheduler.Schedule", "Name"),
        ("EC2.VPC", "Name"),
        ("Athena.WorkGroup", "Name"),
        ("CloudTrail.Trail", "TrailName"),
    ],
)
def check_naming_coverage(kind, field):
    assert not naming_errors(ROOT, kind, [["1", field, "`example`", "名前"]])


def check_naming_edges():
    assert naming_errors(
        ROOT,
        "CloudFront.CachePolicy",
        [["1", "CachePolicyConfig.Name", "`example`", "名前"]],
    )
    assert not naming_errors(
        ROOT, "Glue.Connection", [["1", "Name", "`PENDING_DEPLOY`", "生成される名前"]]
    )
    assert not naming_errors(
        ROOT,
        "Glue.Connection",
        [["1", "ConnectionInput.Name", "`example`", "作成する接続の名前"]],
    )
    assert not naming_errors(
        ROOT, "Scheduler.Schedule", [["1", "GroupName", "`default`", "所属先"]]
    )
    assert not naming_errors(
        ROOT,
        "SecurityHub.Hub",
        [["1", "EnableDefaultStandards", "`true`", "標準を有効化"]],
    )
    assert not naming_errors(
        ROOT,
        "SecurityHub.Hub",
        [
            ["1", "Tags[].Key", '"purpose"', "タグ"],
            ["2", "Tags[].Value", '"security"', "用途"],
        ],
    )
    assert naming_errors(
        ROOT,
        "SecurityHub.Hub",
        [
            ["1", "Tags[].Key", '"Name"', "タグ"],
            ["2", "Tags[].Value", '"security"', "名前"],
        ],
    )
    assert not naming_errors(
        ROOT,
        "EC2.Instance",
        [["1", "Tags[].Key", '"Name"', "タグ"], ["2", "Tags[].Value", '"app"', "名前"]],
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
