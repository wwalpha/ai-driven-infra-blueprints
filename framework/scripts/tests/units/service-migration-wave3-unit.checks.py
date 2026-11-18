"""Context and row ownership through the Wave 3 service hooks."""

import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from model.display import display_rows
from services.contracts import DisplayExtension, DisplayRowGroup, ReferenceMode
from services.reference_engine import ReferenceEngine
from services.registry import REGISTRY
from support.pytest_cli import run

IMPORT = ReferenceMode.IMPORT
VARIABLE = "Environment.EnvironmentVariables[3].Value"


@pytest.mark.parametrize(
    ("value_type", "expected"),
    [
        ("PLAINTEXT", {}),
        ("SECRETS_MANAGER", {"SecretsManager.Secret": ("Id", "Name")}),
        ("PARAMETER_STORE", {"SSM.Parameter": ("Name",)}),
    ],
)
def check_codebuild_reference_policy_and_forms(value_type, expected):
    engine = ReferenceEngine()
    context = {"Type": value_type}
    assert (
        engine.receiver_forms(
            "CodeBuild.Project", VARIABLE, mode=IMPORT, context=context
        )
        == expected
    )
    error = engine.reference_error("CodeBuild.Project", VARIABLE, context)
    assert bool(error) == (value_type == "PLAINTEXT")
    assert engine.requires_context("CodeBuild.Project", VARIABLE, context) == (
        value_type != "PLAINTEXT"
    )


def check_action_configuration_requires_a_complete_action_type():
    engine = ReferenceEngine()
    kind = "CodePipeline.Pipeline"
    path = "Stages[1].Actions[1].Configuration.RepositoryName"
    complete = {
        "Category": "Source",
        "Owner": "AWS",
        "Provider": "CodeCommit",
        "Version": "1",
    }
    assert engine.receiver_forms(
        kind, path, mode=IMPORT, context={"ActionTypeId": complete}
    ) == {"CodeCommit.Repository": ("Name",)}
    assert (
        engine.receiver_forms(
            kind, path, mode=IMPORT, context={"ActionTypeId": complete | {"Version": 1}}
        )
        == {}
    )
    assert (
        engine.receiver_forms(
            kind,
            path,
            mode=IMPORT,
            context={"ActionTypeId": {"Provider": "CodeCommit"}},
        )
        == {}
    )
    assert engine.requires_context(kind, path)
    assert REGISTRY.binds_reference_context(
        "CodePipeline.Pipeline.Stages[1].Actions[1]"
    )
    assert not REGISTRY.binds_reference_context(path)


def check_incomplete_special_group_reports_the_missing_fields():
    extension = REGISTRY.display("CodeBuild.Project")
    rows = [
        ["01", "CodeBuild.Project.Environment.EnvironmentVariables[].Name", "`VAR`", ""]
    ]
    with pytest.raises(ValueError, match="contiguous Name/Type/Value"):
        extension.render_group(rows, 0, mode="CREATE", counts={}, references=set())


def malformed_group(consumed, rows, index, /, **context):
    return DisplayRowGroup(rows[index], consumed)


@pytest.mark.parametrize("consumed", [(), ("02",), ("01", "01")])
def check_shared_display_rejects_dropped_or_reused_source_ids(monkeypatch, consumed):
    rows = [
        ["01", "Synthetic.Row.Name", "`one`", ""],
        ["02", "Synthetic.Row.Mode", "`two`", ""],
    ]
    hook = partial(malformed_group, consumed)
    monkeypatch.setattr(
        REGISTRY, "presentation", lambda _: DisplayExtension(render_group=hook)
    )
    monkeypatch.setattr(
        "aws_mapping_display.selected_rows", lambda selected, root: selected
    )
    with pytest.raises(ValueError, match="omitted or consumed more than once"):
        display_rows("Synthetic.Row", rows)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
