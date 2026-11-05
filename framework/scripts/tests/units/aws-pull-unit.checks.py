"""Offline approved-key integrity and real editor/Change Validation regression."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import import_guard
import model.adapters.aws as aws
import pytest
from generation_inputs import GenerationInputs
from model.format import serialize
from model.operations import prepare_edit, publish_edit
from model.pull_review import MARKER, build, verify
from model.sources import SourceWriteContext, raw_model
from support.import_model_fixtures import resource_values
from support.producer_identifier_reference_fixtures import setup, write_model
from support.pytest_cli import run
from support.repository_fixtures import git
from task_contract_core import selected_task, start

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


KEY = "desired.row.001-001.value"
TASK = "tasks/pull.md"


def pair(tmp_path, after="7200"):
    scope = SimpleNamespace(
        root=tmp_path, environment="stg", target="cde", service="iam"
    )
    values = resource_values(
        "001", "IAM.Role", "role", "CREATE", [("MaxSessionDuration", "3600")]
    )
    path = tmp_path / "model/stg/cde/iam.properties"
    old = SimpleNamespace(
        scope=scope,
        authoritative=values,
        files={path: serialize(values)},
        dependencies={},
    )
    new_values = dict(values, **{KEY: after})
    new = SimpleNamespace(
        scope=scope,
        authoritative=new_values,
        files={path: serialize(new_values)},
        dependencies={},
    )
    return old, new


def contract(review):
    return (
        "## Task contract\n" + MARKER + "\n"
        "- Task type: `design`\n- Workflow: `update`\n"
        "- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n"
        "## AWS pull review\n" + json.dumps(review)
    )


def check_approved_and_no_difference(tmp_path):
    old, new = pair(tmp_path)
    review = build(old, new, TASK, {KEY: "iam.get_role, verified role, timestamp"})
    verify(old, new, TASK, contract(review))
    assert build(old, old, TASK, {})["changes"] == []
    verify(old, new, TASK, "## Task contract\n- Workflow: `update`")


@pytest.mark.parametrize(
    "mutation",
    [
        "before",
        "after",
        "extra",
        "identity",
        "mode",
        "scope",
        "task",
        "worktree",
        "comment",
    ],
)
def check_stale_or_unapproved_changes_rejected(tmp_path, mutation):
    old, new = pair(tmp_path)
    review = build(old, new, TASK, {KEY: "iam.get_role verified"})
    text = contract(review)
    if mutation == "before":
        old.authoritative[KEY] = "4000"
    elif mutation in {"after", "extra", "identity", "mode"}:
        key = {
            "after": KEY,
            "extra": "display.resource.001.comment",
            "identity": "desired.resource.001.logicalId",
            "mode": "desired.resource.001.resourceMode",
        }[mutation]
        new.authoritative[key] = "IMPORT" if mutation == "mode" else "changed"
    elif mutation == "scope":
        new.scope = copy.copy(old.scope)
        old.scope.service = "kms"
    elif mutation == "task":
        text = contract(dict(review, task="tasks/other.md"))
    elif mutation == "worktree":
        text = contract(dict(review, worktree="/other"))
    else:
        new.files[next(iter(new.files))] += "# unapproved\n"
    with pytest.raises(ValueError):
        verify(old, new, TASK, text)


def check_import_and_missing_evidence_rejected(tmp_path):
    old, new = pair(tmp_path)
    for model in (old, new):
        model.authoritative["desired.resource.002.resourceType"] = "IAM.Role"
        model.authoritative["desired.resource.002.resourceMode"] = "IMPORT"
        model.authoritative["desired.row.002-001.property"] = "IAM.Role.Description"
        model.authoritative["desired.row.002-001.value"] = "old"
    assert len(build(old, new, TASK, {KEY: "verified"})["changes"]) == 1
    new.authoritative["desired.row.002-001.value"] = "new"
    with pytest.raises(ValueError, match="CREATE"):
        build(old, new, TASK, {KEY: "verified"})
    old, new = pair(tmp_path)
    with pytest.raises(ValueError, match="evidence"):
        build(old, new, TASK, {})
    with pytest.raises(ValueError):
        verify(old, new, TASK, "## Task contract\n" + MARKER)


@pytest.mark.parametrize(
    "value",
    [
        '`[1,2,{"a":true}]`',
        '{"Statement":[{"Resource":{"$modelRef":{"logicalId":"KMS_Key_001","attribute":"Arn"}}}]}',
    ],
)
def check_review_preserves_exact_json(tmp_path, value):
    old, new = pair(tmp_path, value)
    review = build(old, new, TASK, {KEY: "verified"})
    assert review["changes"][0]["after"] == value
    verify(old, new, TASK, contract(review))


def check_real_sources_and_shared_change_validation(tmp_path):
    root = tmp_path / "repo"
    setup(root, ["iam"], ["IAM.ManagedPolicy"])
    values = resource_values(
        "001",
        "IAM.ManagedPolicy",
        "policy",
        "CREATE",
        [("ManagedPolicyName", "fixture"), ("Description", "old")],
    )
    path = root / "model/preview/team/iam.properties"
    write_model(path, values)
    assert raw_model(path).authoritative["desired.row.001-002.value"] == "old"
    before = raw_model(path)
    changed = dict(values, **{"desired.row.001-002.value": "new"})
    after = before._replace(authoritative=changed, files={path: serialize(changed)})
    review = build(
        before, after, TASK, {"desired.row.001-002.value": "verified iam.get_policy"}
    )
    listed = "\n".join("- `" + p + "`" for p in [TASK, str(path.relative_to(root))])
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    start(
        root,
        TASK,
        "## Task contract\n"
        + MARKER
        + "\n- Task type: `design`\n- Task status: `running`\n"
        "- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n"
        "## Required changes\n- [R1] update\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        "## Validation scope\n- `preview/team/iam`\n## Modified files\n"
        + listed
        + "\n## Allowed paths\n"
        + listed
        + "\n## AWS pull review\n"
        + json.dumps(review),
    )
    with selected_task(root, TASK):
        inputs = GenerationInputs(root, task_file=TASK)
        context = SourceWriteContext._authorized(
            root,
            inputs,
            SimpleNamespace(action="edit"),
            lambda changes: None,
            frozenset({path}),
        )
        changed = dict(values, **{"desired.row.001-002.value": "new"})
        plan = prepare_edit(path, {path: serialize(changed)}, context)
        assert publish_edit(plan, context) == (path,)
        assert raw_model(path).authoritative["desired.row.001-002.value"] == "new"
        import_guard.require_import_changes(root)
        path.write_text(
            serialize(dict(changed, **{"desired.row.001-001.value": "unapproved"}))
        )
        with pytest.raises(ValueError):
            import_guard.require_import_changes(root)


class ComparisonContext:
    resources = ()

    def __init__(self, *args):
        pass

    def verify(self):
        pass

    def model(self, path):
        return SimpleNamespace(resources=self.resources)


@pytest.mark.parametrize(
    "create_only,expected",
    [(True, ["CREATE", "default"]), (False, ["CREATE", "IMPORT", "default"])],
)
def check_comparator_create_filter(tmp_path, monkeypatch, create_only, expected):
    root = tmp_path / "repo"
    setup(root, ["iam"], ["IAM.Role"])
    path = root / "model/preview/team/iam.properties"
    write_model(path, resource_values("001", "IAM.Role", "role", "CREATE", []))
    resources = [
        SimpleNamespace(spec={"resourceMode": mode}, label=mode)
        for mode in ["CREATE", "IMPORT"]
    ]
    resources.append(SimpleNamespace(spec={}, label="default"))
    called = []
    monkeypatch.setattr(ComparisonContext, "resources", resources)
    monkeypatch.setattr(aws, "Context", ComparisonContext)
    monkeypatch.setattr(
        aws._imports_aws_mapping_compare, "comparison", lambda *args: (None, {})
    )
    monkeypatch.setattr(
        aws,
        "compare_resource",
        lambda ctx, resource: called.append(resource.label) or [],
    )
    target = {
        "environment": "preview",
        "directory": "team",
        "awsAccountId": "111111111111",
        "awsRegion": "ap-northeast-1",
    }
    aws.run(root, [(target, path)], create_only=create_only)
    assert called == expected


if __name__ == "__main__":
    raise SystemExit(run(__file__))
