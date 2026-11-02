#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from functools import partial
from types import SimpleNamespace
from unittest import TestCase

import pytest
from deploy import inputs
from deploy import scope as execution_scope
from model.change_plan import ServiceChange
from support import deploy_controller_fixtures as controller_fixtures
from support.deploy_preparation_fixtures import (
    ROOT,
    STACKS,
    TARGET,
    M,
    Path,
    fixture,
    json,
    patch,
    subprocess,
    sys,
    tempfile,
)
from utils.aws.identity import IdentityError
from utils.cloudformation.inputs import Blocked
from validation.findings import Findings

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_dependencies_and_timing():
    with (
        patch.object(M.importlib, "import_module", side_effect=ImportError),
        patch.object(M.shutil, "which", return_value=None),
    ):
        try:
            M.environment(ROOT)
        except ValueError as error:
            assert all(
                name in str(error) for name in ("boto3", "botocore", "PyYAML", "git")
            )
        else:
            raise AssertionError("missing dependencies accepted")
    with (
        patch.object(M.importlib, "import_module"),
        patch.object(M.importlib.metadata, "version", return_value="different.patch"),
        patch.object(M.shutil, "which", return_value="tool"),
        patch.object(subprocess, "run") as run,
    ):
        run.return_value.returncode = 0
        assert M.environment(ROOT)["versions"]["boto3"] == "different.patch"
        assert run.call_args.args[0] == [sys.executable, "-m", "pip", "check"]
        run.return_value.returncode = 1
        run.return_value.stdout, run.return_value.stderr = "conflicting dependency", ""
        try:
            M.environment(ROOT)
        except ValueError as error:
            assert "conflicting dependency" in str(error)
        else:
            raise AssertionError("pip check failure accepted")
    with tempfile.TemporaryDirectory() as directory:
        try:
            M.Timing(Path(directory), Path(directory) / "timing.jsonl")
        except ValueError:
            pass
        else:
            raise AssertionError("repository-local timing accepted")
        path = Path(directory) / "external.jsonl"
        timing = M.Timing(ROOT, path)
        try:
            with timing.phase("authenticationContext"):
                raise RuntimeError("credential failure")
        except RuntimeError:
            pass
        event = json.loads(path.read_text())
        assert event["result"] == "FAIL" and event["phase"] == "authenticationContext"


def check_identity_failure_precedes_preparation(tmp_path):
    args = SimpleNamespace(
        task_file="tasks/test.md",
        stack=["Test"],
        service=["vpc"],
        environment="dev",
        aws_account_id="123456789012",
        alias=None,
        profile="explicit",
    )
    target = {
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "iacEngine": "cloudformation",
    }
    timing = M.Timing(tmp_path / "repository", tmp_path / "timing.jsonl")
    with (
        patch.object(M, "environment", return_value={}),
        patch.object(M, "load_target", return_value=target),
        patch.object(
            M, "select_profile", side_effect=IdentityError("identity rejected")
        ) as select,
        patch.object(M, "candidate") as candidate,
        patch.object(M.subprocess, "run") as aws,
    ):
        with pytest.raises(IdentityError, match="identity rejected"):
            M.prepare(tmp_path / "repository", args, tmp_path / "run", timing)
        select.assert_called_once_with(target, "explicit")
        candidate.assert_not_called()
        aws.assert_not_called()


def check_instruction_changes_do_not_invalidate_registration(tmp_path):
    root, run = tmp_path / "repo", tmp_path / "run"
    fixture(root)
    run.mkdir()
    args = SimpleNamespace(
        task_file="tasks/deploy-test.md",
        service=["ec2", "iam"],
        environment="dev",
        aws_account_id="123456789012",
        alias=None,
        stack=STACKS,
        profile=None,
        sequential=True,
    )
    timing = M.Timing(root)
    with patch.object(
        M, "environment", return_value={"python": sys.executable, "tools": {}}
    ):
        plan = M.prepare(root, args, run, timing)
    plan["preparationSeconds"] = 0
    path = run / "preparation.json"
    path.write_text(json.dumps(plan))
    for relative in (
        "AGENTS.md",
        ".agents/skills/deploy/SKILL.md",
        "framework/rules/cloudformation.md",
    ):
        instruction = root / relative
        instruction.parent.mkdir(parents=True, exist_ok=True)
        instruction.write_text("Changed instruction body")
    task = root / args.task_file
    task.parent.mkdir()
    task.write_text(Path(plan["contract"]).read_text())
    with patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
        registered = M.register(root, path, timing)
    assert registered["registeredContractDigest"] == M.sha(task)
    assert not any(
        p.startswith(("AGENTS.md", ".agents/", "framework/")) for p in plan["inputs"]
    )


@pytest.mark.parametrize("operation", ["register", "run_controller"])
def check_unsupported_preparation_field_rejected_before_changes(tmp_path, operation):
    path = tmp_path / "preparation.json"
    path.write_text(json.dumps({"documents": []}))
    with patch.object(M.subprocess, "run") as execute:
        with pytest.raises(ValueError, match="unsupported preparation field"):
            if operation == "register":
                M.register(tmp_path, path, M.Timing(tmp_path))
            else:
                M.run_controller(tmp_path, path)
        execute.assert_not_called()
    assert json.loads(path.read_text()) == {"documents": []}


def guard_view_access(design, original, path, *args, **kwargs):
    if path.is_relative_to(design):
        raise AssertionError("preparation read or scanned View: " + str(path))
    return original(path, *args, **kwargs)


def check_candidate_paths_come_from_model_without_reading_views(tmp_path):
    root = tmp_path / "repo"
    fixture(root)
    design = root / "docs/designs/dev/123456789012"
    legacy = design / "iam/legacy.json"
    legacy.write_bytes(b"keep legacy")
    (design / "ec2.md").unlink()
    (design / "iam.md").write_bytes(b"stale Markdown")
    (design / "iam/worker-role-trust-policy.json").write_bytes(b"stale JSON")
    with (
        patch.object(
            Path, "read_bytes", partial(guard_view_access, design, Path.read_bytes)
        ),
        patch.object(
            Path, "read_text", partial(guard_view_access, design, Path.read_text)
        ),
        patch.object(Path, "rglob", partial(guard_view_access, design, Path.rglob)),
    ):
        text, _, _, views = M.candidate(
            root,
            "tasks/deploy.md",
            "dev",
            "123456789012",
            TARGET,
            STACKS,
            ["ec2", "iam"],
        )
    TestCase().assertEqual(
        views,
        {
            design / "ec2.md",
            design / "iam.md",
            design / "iam/worker-role-trust-policy.json",
        },
    )
    TestCase().assertNotIn(legacy.relative_to(root).as_posix(), text)
    TestCase().assertEqual(legacy.read_bytes(), b"keep legacy")


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))


@pytest.mark.parametrize(
    ("lower", "upper", "expected"),
    [
        (None, 20, ["One", "Two"]),
        (30, 50, ["Three", "Four"]),
        (40, 40, ["Four"]),
        (30, None, ["Three", "Four"]),
    ],
)
def test_order_selection(lower, upper, expected):
    values = {}
    for number, (name, order) in enumerate(
        (("One", 10), ("Two", 20), ("Three", 30), ("Four", 40)), 1
    ):
        values[f"desired.stack.{number}.name"] = name
        values[f"desired.stack.{number}.deployOrder"] = str(order)
    TestCase().assertEqual(
        [
            stack["name"]
            for _, stack in M.select_stacks(values, order_from=lower, order_to=upper)
        ],
        expected,
    )
    with pytest.raises(Blocked):
        M.select_stacks(values, ["One"], order_to=20)
    with pytest.raises(Blocked):
        M.select_stacks(values, order_from=50, order_to=40)
    with pytest.raises(Blocked):
        M.select_stacks(values, order_from=50)


def test_invalid_stack_diagnostic_identifies_outside_stack(tmp_path):
    values = {"desired.deployment.maxConcurrentStacks": "1"}
    for number, name in ((1, "One"), (2, "Two")):
        for key, value in {
            "name": name,
            "deployOrder": str(number * 10),
            "template": "valid.yaml",
            "parameters": f"{number}.json",
        }.items():
            values[f"desired.stack.{number}.{key}"] = value
    values["desired.stack.2.template"] = "bad/path"
    with pytest.raises(
        Blocked,
        match="cloudformation-stacks.properties: StackName=Two DeployOrder=20.*template='bad/path'",
    ):
        M.load_units(
            tmp_path, "dev", "target", ["One"], snapshot=SimpleNamespace(values=values)
        )
    values["desired.stack.2.template"] = "valid.yaml"
    values["desired.stack.2.parameters"] = "1.json"
    with pytest.raises(Blocked, match="StackName=Two.*parameter.*StackName=One"):
        M.load_units(
            tmp_path, "dev", "target", ["One"], snapshot=SimpleNamespace(values=values)
        )


def test_stack_view_diagnostics_identify_mismatched_stack(tmp_path):
    root = tmp_path / "repo"
    fixture(root)
    source = root / "model/dev/123456789012/cloudformation-stacks.properties"
    design = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
    snapshot = M.stack_snapshot(source)
    design.write_text(
        design.read_text(encoding="utf-8").replace("second.yaml", "incorrect.yaml"),
        encoding="utf-8",
    )
    with pytest.raises(
        inputs.DeployStepBlocked, match="StackName=" + STACKS[1] + ".*template"
    ):
        inputs.check_stack_markdown(root, snapshot)
    design.write_text(
        design.read_text(encoding="utf-8").replace("shared.yaml", "wrong.yaml"),
        encoding="utf-8",
    )
    with pytest.raises(inputs.DeployStepBlocked):
        inputs.check_stack_markdown(root, snapshot)


def test_ownership_discovery_uses_selected_stack(tmp_path):
    root = tmp_path / "repo"
    fixture(root)
    _, units = M.load_units(root, "dev", "123456789012", [STACKS[0]])
    resources = M.owning_resources(root, "dev", "123456789012", TARGET, units)
    TestCase().assertEqual(set(resources), {STACKS[0]})
    TestCase().assertEqual(resources[STACKS[0]]["WorkerRole"]["service"], "iam")
    dependency_index.rebuild(root)
    entrance = root / "model/dev/123456789012/ec2.properties"
    ec2 = next(
        path
        for path in (entrance, *entrance.with_suffix("").rglob("*.properties"))
        if STACKS[1] + "-Vpc" in path.read_text(encoding="utf-8")
    )
    original = ec2.read_text(encoding="utf-8")
    ec2.write_text(
        original.replace(STACKS[1] + "-Vpc", STACKS[0] + "-WorkerRole"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="matches=2"):
        M.owning_resources(root, "dev", "123456789012", TARGET, units)
    ec2.write_text(original, encoding="utf-8")
    template = root / "infra/cloudformation/templates/shared.yaml"
    template.write_text(
        "Resources:\n  Unknown:\n    Type: AWS::IAM::Role\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="explicit mapping required"):
        M.owning_resources(root, "dev", "123456789012", TARGET, units)


def test_fixed_resource_mapping_cannot_be_replaced(tmp_path):
    path = tmp_path / "model/dev/team/iam.properties"
    task = SimpleNamespace(
        text='## Execution scope\n- `{"stack":"One","logicalId":"Role","service":"iam","resource":"IAM_Role_001"}`\n'
    )
    mapped = {"One": {"Role": (path, "001", {"logicalId": "IAM_Role_001"}, [], set())}}
    execution_scope.check_fixed_resources(tmp_path, mapped, task=task)
    mapped["One"]["Role"] = (path, "002", {"logicalId": "IAM_Role_002"}, [], set())
    with pytest.raises(ValueError, match="fixed Execution scope"):
        execution_scope.check_fixed_resources(tmp_path, mapped, task=task)


def test_observed_row_from_another_selected_service_stack_is_rejected(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    root = controller_fixtures.seed(tmp_path / "repo", tmp_path / "session.json")
    task_text = (root / "tasks/deploy.md").read_text(encoding="utf-8")
    line = next(
        line
        for line in task_text.splitlines()
        if line.startswith("- Deployment scope:")
    )
    task = SimpleNamespace(
        text=task_text.replace(line, "- Deployment scope: `cfn-stack-app-dev-first`")
    )
    source = M.load_model(root / "model/dev/123456789012/ec2.properties")
    row = next(rid for rid, _ in inputs.entries(source.authoritative, "desired.row."))
    change = ServiceChange(source, source, observed_rows={row})
    with pytest.raises(
        ValueError, match="observed write outside fixed selected Resources"
    ):
        execution_scope.validate_selected(
            root, task, Findings(root), plan=SimpleNamespace(changes={"ec2": change})
        )


def test_removed_resource_observation_remains_authorized(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    root = controller_fixtures.seed(
        tmp_path / "repo", tmp_path / "session.json", "remove"
    )
    task = SimpleNamespace(text=(root / "tasks/deploy.md").read_text(encoding="utf-8"))
    source = M.load_model(root / "model/dev/123456789012/ec2.properties")
    change = ServiceChange(source, source, observed_rows={"002-001"})
    findings = Findings(root)
    execution_scope.validate_selected(
        root, task, findings, plan=SimpleNamespace(changes={"ec2": change})
    )
    TestCase().assertEqual(findings.errors, [])
