"""Public generation projects JSON without quality gates and never imports Model quality validation."""

import ast
import copy
import json
import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from generation_inputs import GenerationInputs
from model.core import ModelNeedsFixError, SnapshotValues
from model.sources import Scope
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from support.pytest_cli import run
from utils.aws_mappings import mapping_alias
from utils.input_cache import input_context, recording_inputs

from model import projection, render, validation

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPTS = FRAMEWORK / "framework/scripts"
ENTRIES = ("generate_files", "generate_markdown", "render_validated_model")


@pytest.mark.parametrize(
    "statement",
    (
        "import model.validation",
        "import model.render",
        "import model.validation; import model.render",
        "import model.render; import model.validation",
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
    assert result.returncode == 0, result.stderr


def test_render_has_no_direct_or_indirect_validation_dependency():
    graph = {}
    for path in SCRIPTS.rglob("*.py"):
        if "tests" in path.relative_to(SCRIPTS).parts:
            continue
        module = ".".join(path.relative_to(SCRIPTS).with_suffix("").parts)
        dependencies = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                dependencies.add(node.module)
                dependencies.update(
                    node.module + "." + alias.name for alias in node.names
                )
        graph[module] = dependencies
    pending, seen = [("model.render",)], set()
    while pending:
        chain = pending.pop()
        name = chain[-1]
        assert name != "model.validation", chain
        if name in seen:
            continue
        seen.add(name)
        pending.extend(
            (*chain, child) for child in graph.get(name, ()) if child in graph
        )
    assert {"model.projection", "design.document"} <= seen


@pytest.fixture
def model(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        scope, values = resource(
            tmp_path, "lambda", "Lambda.Function", attribute="FunctionName"
        )
        values["desired.row.001-001.value"] = "`synthetic-function`"
        values.update(
            {
                "desired.row.001-002.property": "Lambda.Function.Environment.Variables",
                "desired.row.001-002.value": "`"
                + json.dumps({"SELF": reference("Lambda_Function_001", "FunctionName")})
                + "`",
                "desired.row.001-002.comment": "合成JSON参照",
            }
        )
        save(scope, values)
        view = tmp_path / "docs/designs/qa/team/lambda.md"
        yield scope, values, view


def generate(entry, scope, values, view):
    if entry == "render_validated_model":
        return render.render_validated_model(
            view, values, scope.root, definitions_root=FRAMEWORK
        )
    return getattr(render, entry)(view, values, scope.root)


@pytest.mark.parametrize("entry", ENTRIES)
def test_public_entry_skips_quality_checks_and_keeps_outputs(model, entry):
    scope, values, view = model
    before = copy.deepcopy(values)
    expected = render.generate_markdown(view, values, scope.root)
    with patch.object(
        projection, "validate_json_documents", wraps=projection.validate_json_documents
    ) as checks:
        actual = generate(entry, scope, values, view)
    assert checks.call_count == 0
    assert (actual[view] if isinstance(actual, dict) else actual) == expected
    assert "[synthetic-function](#saved-001)" in expected
    assert values == before
    assert validation.validate_json_documents is projection.validate_json_documents


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize(
    "invalid", ("`{broken}`", '`{"SELF":{"$modelRef":{"logicalId":"bad"}}}`')
)
def test_public_entry_rejects_invalid_json(model, entry, invalid):
    scope, values, view = model
    values["desired.row.001-002.value"] = invalid
    with pytest.raises(ValueError):
        generate(entry, scope, values, view)


@pytest.mark.parametrize("entry", ENTRIES)
def test_invalid_resource_reference_keeps_diagnostics(model, entry):
    scope, values, view = model
    values["desired.row.001-002.value"] = (
        "`"
        + json.dumps({"SELF": reference("Missing_Function_001", "FunctionName")})
        + "`"
    )
    actual = generate(entry, scope, values, view)
    markdown = actual[view] if isinstance(actual, dict) else actual
    assert "$modelRef" in markdown and "Missing_Function_001" in markdown
    with pytest.raises(ModelNeedsFixError):
        validation.validate_json_documents(values, scope.path)


@pytest.mark.parametrize("intrinsic", (False, True))
def test_files_keep_json_artifacts_warnings_and_input_tracking(model, intrinsic):
    scope, _, _ = model
    policy_scope = Scope(scope.root, "qa", "team", "iam")
    from_values = project(scope.root)[3]
    if intrinsic:
        document = json.loads(from_values["desired.row.001-002.document"])
        document["Statement"][0]["Resource"] = {"Fn::Sub": "${ExternalArn}"}
        from_values["desired.row.001-002.document"] = json.dumps(document)
    producer_scope = Scope(scope.root, "qa", "team", "kms")
    _, producer = resource(
        scope.root,
        "kms",
        "KMS.Key",
        observed="arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
    )
    save(producer_scope, producer)
    view = scope.root / "docs/designs/qa/team/iam.md"
    warnings, expected_warnings = [], []
    projection.validate_json_documents(
        from_values, policy_scope.path, warnings=expected_warnings
    )
    before = copy.deepcopy(from_values)
    with (
        closing(GenerationInputs(scope.root)) as recorder,
        recording_inputs(recorder),
        input_context(),
    ):
        with patch.object(
            projection,
            "validate_json_documents",
            wraps=projection.validate_json_documents,
        ) as checks:
            files = render.generate_files(
                view, from_values, scope.root, warnings=warnings
            )
    assert checks.call_count == 0
    assert warnings == []
    assert bool(expected_warnings) == intrinsic
    if not intrinsic:
        assert producer_scope.path in recorder.contents
    artifact = view.with_suffix("") / "policy.json"
    expected = json.loads(from_values["desired.row.001-002.document"])
    assert files[artifact] == json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
    assert files[view] == render.generate_markdown(view, from_values, scope.root)
    assert from_values == before


def test_snapshots_and_partial_reference_context_are_not_reused(model):
    scope, values, view = model
    first = SnapshotValues(values)
    second = SnapshotValues(
        dict(values, **{"desired.row.001-001.value": "`changed-function`"})
    )
    with patch.object(
        projection, "validate_json_documents", wraps=projection.validate_json_documents
    ) as checks:
        a = render.generate_files(view, first, scope.root)
        b = render.generate_files(view, second, scope.root)
    assert checks.call_count == 0
    assert "synthetic-function" in a[view] and "changed-function" in b[view]
    _, consumer = resource(
        scope.root, "lambda", "Lambda.Function", attribute="FunctionName", number="002"
    )
    consumer["desired.row.002-001.value"] = "`consumer-function`"
    consumer.update(
        {
            "desired.row.002-002.property": "Lambda.Function.Environment.Variables",
            "desired.row.002-002.value": values["desired.row.001-002.value"],
            "desired.row.002-002.comment": "合成参照",
        }
    )
    complete = SnapshotValues(dict(second, **consumer))
    with patch.object(
        projection, "validate_json_documents", wraps=projection.validate_json_documents
    ) as checks:
        partial = render.generate_markdown(
            view, consumer, scope.root, reference_values=complete
        )
    assert checks.call_count == 0
    assert "[changed-function](#saved-001)" in partial


@pytest.mark.parametrize("name", [None, "PENDING_DEPLOY", "UNSET"])
def test_unconfirmed_names_keep_anchor_and_model(model, name):
    scope, values, view = model
    if name is None:
        for key in list(values):
            if key.startswith("desired.row.001-001."):
                del values[key]
    else:
        values["desired.row.001-001.value"] = "`" + name + "`"
    before = copy.deepcopy(values)
    view.parent.mkdir(parents=True, exist_ok=True)
    view.write_text("# obsolete\n[broken](missing.md#missing)\n", encoding="utf-8")
    files = render.generate_files(view, values, scope.root)
    assert "### Lambda.Function: Lambda_Function_001" in files[view]
    assert '<a id="saved-001"></a>' in files[view]
    assert values == before


if __name__ == "__main__":
    raise SystemExit(run(__file__))
