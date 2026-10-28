"""IAM RoleName suffix validation through save and issue scan."""

import json
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from generation_inputs import GenerationInputs
from issues.publication import save_scan
from issues.runner import scan
from model.format import serialize
from model.operations import prepare_edit, publish_edit
from model.render import markdown_for
from model.validations.naming import (
    check_iam_role_suffix as suffix_errors,
)
from model.validations.naming import (
    resolve_target_suffix,
    validate_resource_naming_suffix,
)
from support.import_model_fixtures import resource_values, service_values
from support.issues_scan_fixtures import fixture, review_for, task
from support.producer_identifier_reference_fixtures import setup, write_model
from support.pytest_cli import run

from model import sources

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.mark.parametrize(
    "suffix,name,valid",
    [
        (None, "venusinf-stg-PatRotationRole", True),
        (None, "venusinf-stg-PatRotationRole-p4x8r2", False),
        (None, "venusinf-stg-PatRotationRole-foobar", False),
        ("p4x8r2", "venusinf-stg-PatRotationRole", False),
        ("p4x8r2", "venusinf-stg-PatRotationRole-p4x8r2", True),
        ("p4x8r2", "venusinf-stg-PatRotationRole-foobar", False),
        ("p4x8r2", "venusinf-stg-PatRotationRole-P4x8r2", False),
        (None, "venusinf-stg-patrotationRole", False),
        (None, "venusinf-stg-PatRotationRole-extra-tail", False),
    ],
)
def check_suffix(suffix, name, valid):
    assert (not suffix_errors(name, suffix)) == valid


def check_targets(tmp_path):
    targets = [
        {"environment": "dev", "alias": "a", "suffix": "one"},
        {"environment": "dev", "alias": "b"},
        {"environment": "stg", "alias": "a", "suffix": "two"},
        {"environment": "stg", "awsAccountId": "123", "suffix": "three"},
    ]
    (tmp_path / "project.json").write_text(json.dumps({"targets": targets}))
    view = tmp_path / "docs/designs"
    assert resolve_target_suffix(view / "dev/a/iam.md", tmp_path) == "one"
    assert resolve_target_suffix(view / "dev/b/iam.md", tmp_path) is None
    assert resolve_target_suffix(view / "stg/a/iam.md", tmp_path) == "two"
    assert resolve_target_suffix(view / "stg/123/iam.md", tmp_path) == "three"
    with pytest.raises(ValueError, match="target cannot be resolved"):
        resolve_target_suffix(view / "dev/missing/iam.md", tmp_path)
    assert not validate_resource_naming_suffix("IAM.Role", "IMPORT", [], view, tmp_path)
    assert not validate_resource_naming_suffix(
        "S3.Bucket", "CREATE", [], view, tmp_path
    )


def role(name):
    return {
        **service_values("iam", ["IAM.Role"]),
        **resource_values(
            "001",
            "IAM.Role",
            "role",
            "CREATE",
            [("RoleName", name), ("Description", "before")],
        ),
    }


@pytest.mark.parametrize("case", ["invalid", "valid", "unrelated"])
def check_save(project_workspace, case):
    root = project_workspace
    setup(root, ["iam"], ["IAM.Role"])
    path = root / "model/preview/team/iam.properties"
    before = role(
        "app-preview-ExampleRole-bad"
        if case == "unrelated"
        else "app-preview-ExampleRole"
    )
    write_model(path, before)
    original = path.read_bytes()
    after = dict(before)
    if case == "invalid":
        after["desired.row.001-001.value"] = "app-preview-ExampleRole-bad"
    elif case == "valid":
        after["desired.row.001-001.value"] = "app-preview-AnotherRole"
    else:
        after["desired.row.001-002.value"] = "after"
    with closing(GenerationInputs(root)) as reads:
        context = sources.SourceWriteContext._authorized(
            root,
            reads,
            SimpleNamespace(action="edit"),
            lambda changes: None,
            frozenset({path}),
        )
        try:
            if case == "invalid":
                with pytest.raises(ValueError, match="suffix mismatch"):
                    prepare_edit(path, {path: serialize(after)}, context)
                assert path.read_bytes() == original
            else:
                plan = prepare_edit(path, {path: serialize(after)}, context)
                assert publish_edit(plan, context) == (path,)
                assert sources.raw_model(path).authoritative == after
        finally:
            context.close()


def check_issue_scan(project_workspace):
    root = project_workspace
    fixture(root, services=("s3",))
    path = root / "model/dev/123456789012/iam.properties"
    view = root / "docs/designs/dev/123456789012/iam.md"
    values = role("app-dev-ExampleRole-bad")
    write_model(path, values)
    view.write_text(markdown_for(view, values, root), encoding="utf-8")
    services = ["cloudformation-stacks", "s3", "iam"]
    artifact = scan(root, "dev", "123456789012", services, jobs=1)
    matches = [
        item
        for item in artifact["ordinary"]
        if "suffix mismatch" in item.get("message", "")
    ]
    assert len(matches) == 1, artifact
    assert matches[0]["cause_kind"] == "input_invalid"
    with task(root, services):
        outputs, _, _ = save_scan(root, artifact, review_for(artifact))
    report = outputs[0].read_text(encoding="utf-8")
    assert "suffix mismatch" in report and "ExampleRole-bad" in report
    again = scan(root, "dev", "123456789012", services, jobs=1)
    assert [
        item["id"]
        for item in again["ordinary"]
        if "suffix mismatch" in item.get("message", "")
    ] == [matches[0]["id"]]
    with task(root, services):
        save_scan(root, again, review_for(again))
    assert outputs[0].read_text(encoding="utf-8").count("suffix mismatch") == 1
    values["desired.row.001-001.value"] = "app-dev-ExampleRole"
    write_model(path, values)
    view.write_text(markdown_for(view, values, root), encoding="utf-8")
    clean = scan(root, "dev", "123456789012", services, jobs=1)
    assert not [
        item
        for item in clean["ordinary"]
        if "suffix mismatch" in item.get("message", "")
    ]
    project_path = root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["targets"][0]["suffix"] = "new"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    changed = scan(root, "dev", "123456789012", services, jobs=1)
    assert any(
        "suffix mismatch" in item.get("message", "") for item in changed["ordinary"]
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
