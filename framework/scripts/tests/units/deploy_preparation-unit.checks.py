#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import io
from contextlib import nullcontext, redirect_stderr
from functools import partial
from types import SimpleNamespace
from unittest import TestCase

import pytest
from deploy import inputs
from deploy import scope as execution_scope
from model.change_plan import ServiceChange
from model.render import stack_markdown
from support import deploy_controller_fixtures as controller_fixtures
from support.deploy_preparation_fixtures import (
    ROOT,
    STACKS,
    TARGET,
    M,
    Path,
    arguments,
    fixture,
    json,
    patch,
    subprocess,
    sys,
    tempfile,
    write_model,
)
from task_contract_core import selected_task
from utils.aws.identity import IdentityError
from utils.aws_mappings import mapping_alias
from utils.cloudformation.inputs import Blocked
from validation.findings import Findings
from validation.runner import Validator

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
    with (
        mapping_alias(ROOT, root),
        patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
    ):
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


@pytest.mark.parametrize(
    "failure",
    [
        "runtime",
        "input",
        "deferred",
        "inventory",
        "owner",
        "file-set",
        "candidate",
        "candidate-location",
        "registration",
        "none",
    ],
)
def test_preparation_registration_boundaries(tmp_path, failure):
    check = TestCase()
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "project.json"
    source.write_text("input")
    deferred = root / "model.properties"
    deferred.write_text("deferred")
    candidate = tmp_path / "contract.md"
    candidate.write_text("reviewed contract")
    task = root / "tasks/prepare.md"
    task.parent.mkdir()
    task.write_text("registered contract")
    plan = dict(
        repository=str(root),
        runtime=dict(python=sys.executable, tools={}),
        environment={"PATH": M.os.environ.get("PATH")},
        reviewStarted=0,
        inputs={"project.json": M.sha(source)},
        inputIdentities={"model.properties": M.file_revision(deferred)},
        scope=["dev/team/iam"],
        ownership=dict(
            environment="dev", directory="team", target={}, units=[], resources={}
        ),
        modelInputPaths=["model.properties"],
        contract=str(candidate),
        contractDigest=M.sha(candidate),
        taskFile="tasks/prepare.md",
        preparationSeconds=0,
    )
    if failure == "runtime":
        plan["environment"]["PATH"] = "changed"
    elif failure == "input":
        source.write_text("changed")
    elif failure == "deferred":
        deferred.write_text("changed")
    elif failure == "candidate":
        candidate.write_text("unreviewed candidate")
    elif failure == "candidate-location":
        plan["contract"] = str(source)
        plan["contractDigest"] = M.sha(source)
    path = tmp_path / "preparation.json"
    path.write_text(json.dumps(plan))
    timing = SimpleNamespace(phase=lambda *args, **kwargs: nullcontext())
    with (
        patch.object(
            M,
            "model_inventory",
            side_effect=[{}, {"changed": True}] if failure == "inventory" else None,
            return_value={},
        ),
        patch.object(
            M,
            "owning_resources",
            return_value={"changed": True} if failure == "owner" else {},
        ),
        patch.object(
            M,
            "model_input_paths",
            return_value=[] if failure == "file-set" else ["model.properties"],
        ),
        patch.object(
            M.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], int(failure == "registration"), "registration failed", ""
            ),
        ) as launch,
    ):
        if failure == "none":
            result = M.register(root, path, timing)
            check.assertEqual(result["registeredContractDigest"], M.sha(task))
        else:
            with pytest.raises(ValueError):
                M.register(root, path, timing)
    check.assertEqual(launch.call_count, int(failure in {"registration", "none"}))
    check.assertEqual(task.read_text(), "registered contract")
    if failure != "none":
        check.assertEqual(json.loads(path.read_text()), plan)


@pytest.mark.parametrize(
    "failure",
    [
        "repository",
        "python",
        "controller",
        "root-argument",
        "root-equals",
        "contract",
        "runtime",
        "child",
        "none",
    ],
)
def test_preparation_controller_launch_boundaries(tmp_path, failure):
    check = TestCase()
    command = [
        sys.executable,
        str(M.definition_root(tmp_path) / "framework/scripts/cloudformation-deploy.py"),
        "--action",
        "advance",
    ]
    plan = dict(
        repository=str(tmp_path),
        controllerArgv=command,
        taskFile="tasks/prepare.md",
        registeredContractDigest="digest",
        environment={"PATH": M.os.environ.get("PATH")},
    )
    if failure == "repository":
        plan["repository"] += "-other"
    elif failure == "python":
        command[0] = "other-python"
    elif failure == "controller":
        command[1] = "other-controller.py"
    elif failure.startswith("root-"):
        command.extend(
            ["--repository-root", str(tmp_path)]
            if failure == "root-argument"
            else ["--repository-root=" + str(tmp_path)]
        )
    elif failure == "runtime":
        plan["environment"]["PATH"] = "changed"
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    with (
        patch.object(
            M._imports_task_contract,
            "task_snapshot",
            return_value=SimpleNamespace(
                raw_digest="changed" if failure == "contract" else "digest"
            ),
        ),
        patch.object(
            M.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 2 if failure == "child" else 0
            ),
        ) as launch,
    ):
        if failure in {"child", "none"}:
            check.assertEqual(
                M.run_controller(tmp_path, path), 2 if failure == "child" else 0
            )
            launch.assert_called_once_with(
                command, cwd=tmp_path, env=M.os.environ | plan["environment"]
            )
        else:
            with pytest.raises(ValueError):
                M.run_controller(tmp_path, path)
            launch.assert_not_called()


def test_generated_execution_conflict_and_symlink(tmp_path):
    base = tmp_path
    root = base / "repo"
    fixture(root)
    artifacts = root / "infra/cloudformation/artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    with (
        patch.object(
            M,
            "owning_resources",
            return_value={"a": {"x": {"service": "iam"}, "y": {"service": "ec2"}}},
        ),
        patch.object(
            M,
            "paths",
            return_value=(
                root
                / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json",
                artifacts / "execution.json",
            ),
        ),
        patch.object(
            M,
            "deployment_input_paths",
            return_value=[
                root / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json"
            ],
        ),
    ):
        output = io.StringIO()
        with redirect_stderr(output):
            TestCase().assertEqual(M.main(arguments(root, base)), 1)
        TestCase().assertIn(
            "generated view conflicts with execution/required input", output.getvalue()
        )
    parameter = root / "infra/cloudformation/parameters/dev/123456789012/1.json"
    parameter.unlink()
    parameter.symlink_to(parameter.with_name("2.json"))
    output = io.StringIO()
    with redirect_stderr(output):
        TestCase().assertEqual(M.main(arguments(root, base)), 1)
    TestCase().assertIn("task path must not use symlinks", output.getvalue())


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


def selected_values():
    values = {"desired.deployment.maxConcurrentStacks": "1"}
    for number, name, order in ((1, "One", 30), (2, "Two", 60)):
        for key, value in {
            "name": name,
            "placementName": name,
            "deployOrder": str(order),
            "template": "valid.yaml",
            "parameters": f"{number}.json",
        }.items():
            values[f"desired.stack.{number}.{key}"] = value
        values[f"display.stack.{number}.comment"] = "合成Stack"
    return values


@pytest.mark.parametrize("field", ["template", "parameters", "artifact"])
def test_invalid_outside_stack_does_not_block(tmp_path, field):
    values = selected_values()
    if field == "artifact":
        values.update(
            {"desired.artifact.1.stack": "Two", "desired.artifact.1.source": "bad/path"}
        )
    else:
        values[f"desired.stack.2.{field}"] = "bad/path"
    names = [
        stack["name"]
        for _, stack in M.select_stacks(values, order_from=30, order_to=50)
    ]
    _, units = M.load_units(
        tmp_path, "dev", "target", names, snapshot=SimpleNamespace(values=values)
    )
    TestCase().assertEqual([unit["name"] for unit in units], ["One"])


@pytest.mark.parametrize("field", ["template", "parameters", "artifact"])
def test_invalid_selected_stack_blocks(tmp_path, field):
    values = selected_values()
    if field == "artifact":
        values.update(
            {"desired.artifact.1.stack": "One", "desired.artifact.1.source": "bad/path"}
        )
    else:
        values[f"desired.stack.1.{field}"] = "bad/path"
    with pytest.raises(
        Blocked,
        match="StackName=One.*" + ("artifact" if field == "artifact" else field),
    ):
        M.load_units(
            tmp_path, "dev", "target", ["One"], snapshot=SimpleNamespace(values=values)
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "One"),
        ("deployOrder", "unknown"),
        ("parameters", "1.json"),
        ("placementName", "One"),
    ],
)
def test_global_selection_and_selected_collisions_block(tmp_path, field, value):
    values = selected_values()
    values[f"desired.stack.2.{field}"] = value
    with pytest.raises(Blocked):
        M.load_units(
            tmp_path, "dev", "target", ["One"], snapshot=SimpleNamespace(values=values)
        )


@pytest.mark.parametrize(
    "change",
    [
        "comment",
        "invalid-unrelated",
        "owner",
        "duplicate",
        "missing",
        "new-owner",
        "dependency",
    ],
)
def test_registration_rechecks_selected_ownership(tmp_path, change):
    root, run = tmp_path / "repo", tmp_path / "run"
    fixture(root)
    run.mkdir()
    args = SimpleNamespace(
        task_file="tasks/deploy-test.md",
        service=None,
        environment="dev",
        aws_account_id="123456789012",
        alias=None,
        stack=None,
        order_from=10,
        order_to=10,
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
    path.write_text(json.dumps(plan), encoding="utf-8")
    entrance = root / "model/dev/123456789012/ec2.properties"
    part = next(
        p
        for p in (entrance, *entrance.with_suffix("").rglob("*.properties"))
        if STACKS[1] + "-Vpc" in p.read_text(encoding="utf-8")
    )
    original = part.read_text(encoding="utf-8")
    if change == "comment":
        part.write_text(original + "# unrelated display comment\n", encoding="utf-8")
    elif change == "invalid-unrelated":
        part.write_text(
            original.replace(STACKS[1] + "-Vpc", "invalid"), encoding="utf-8"
        )
    elif change == "duplicate":
        part.write_text(
            original.replace(STACKS[1] + "-Vpc", STACKS[0] + "-WorkerRole"),
            encoding="utf-8",
        )
    elif change == "new-owner":
        values = dict(M.raw_model(entrance).authoritative)
        values["desired.resource.001.cfn-logicalId"] = STACKS[0] + "-WorkerRole"
        write_model(entrance.with_name("unexpected.properties"), values)
    else:
        owner = root / "model/dev/123456789012/iam.properties"
        if change == "missing":
            owner.unlink()
        else:
            owner.write_text(
                owner.read_text(encoding="utf-8")
                + (
                    "# changed dependency\n"
                    if change == "dependency"
                    else "desired.resource.001.cfn-logicalId=Changed-Owner\n"
                ),
                encoding="utf-8",
            )
    task = root / args.task_file
    task.parent.mkdir()
    task.write_text(
        Path(plan["contract"]).read_text(encoding="utf-8"), encoding="utf-8"
    )
    with patch.object(
        M.subprocess, "run", return_value=SimpleNamespace(returncode=0)
    ) as register:
        if change in {"comment", "invalid-unrelated"}:
            M.register(root, path, timing)
            register.assert_called_once()
        else:
            with pytest.raises(ValueError):
                M.register(root, path, timing)
            register.assert_not_called()


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


@pytest.mark.parametrize("field", ["template", "parameters", "artifact"])
def test_preparation_ignores_real_outside_stack_definition(tmp_path, field):
    root, run = tmp_path / "repo", tmp_path / "run"
    fixture(root)
    run.mkdir()
    source = root / "model/dev/123456789012/cloudformation-stacks.properties"
    text = (
        source.read_text(encoding="utf-8")
        .replace(".deployOrder=10", ".deployOrder=30")
        .replace(".deployOrder=20", ".deployOrder=60")
    )
    source.write_text(text, encoding="utf-8")
    design = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
    design.write_text(
        stack_markdown(
            design, M.stack_snapshot(source).values, root, validate_delivery=False
        ),
        encoding="utf-8",
    )
    if field == "artifact":
        text += f"desired.artifact.001.stack={STACKS[1]}\ndesired.artifact.001.source=bad/path\n"
    else:
        text = text.replace(
            "second.yaml" if field == "template" else "2.json", "bad/path"
        )
    source.write_text(text, encoding="utf-8")
    args = SimpleNamespace(
        task_file="tasks/deploy-test.md",
        service=None,
        environment="dev",
        aws_account_id="123456789012",
        alias=None,
        stack=None,
        order_from=30,
        order_to=50,
        profile=None,
        sequential=True,
    )
    with patch.object(
        M, "environment", return_value={"python": sys.executable, "tools": {}}
    ):
        plan = M.prepare(root, args, run, M.Timing(root))
    TestCase().assertEqual(plan["scope"], ["dev/123456789012/iam"])
    TestCase().assertEqual(
        [unit["name"] for unit in plan["ownership"]["units"]], [STACKS[0]]
    )
    with pytest.raises(ValueError):
        inputs.stack_model(M.stack_snapshot(source).values)


@pytest.mark.parametrize("number", ["001", "003"])
def test_mixed_service_validates_only_selected_resource(tmp_path, monkeypatch, number):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    root = controller_fixtures.seed(
        tmp_path / "repo", tmp_path / "session.json", "multi-observed"
    )
    path = root / "model/dev/123456789012/ec2.properties"
    values = dict(M.load_model(path).authoritative)
    values[f"desired.row.{number}-002.property"] = "EC2.VPC.UnsupportedProperty"
    write_model(path, values)
    text = (root / "tasks/deploy.md").read_text(encoding="utf-8")
    line = next(
        line for line in text.splitlines() if line.startswith("- Deployment scope:")
    )
    task = SimpleNamespace(
        text=text.replace(line, "- Deployment scope: `cfn-stack-app-dev-first`")
    )
    findings = Findings(root)
    (root / "docs/designs/dev/123456789012/cloudformation-stacks.md").unlink()
    execution_scope.validate_selected(root, task, findings)
    if number == "001":
        TestCase().assertEqual(findings.errors, [])
    else:
        TestCase().assertTrue(findings.errors)


def test_full_deploy_validation_uses_model_without_saved_views(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    root = controller_fixtures.seed(tmp_path / "repo", tmp_path / "session.json")
    target = root / "docs/designs/dev/123456789012"
    for path in target.glob("*.md"):
        path.unlink()
    scope = {
        ("dev", "123456789012", name) for name in ("s3", "ec2", "cloudformation-stacks")
    }
    with selected_task(root, "tasks/deploy.md"):
        validator = Validator(root, scope, model_validation="full")
        if validator.run() or validator.errors:
            pytest.fail(str(validator.errors))
        path = root / "model/dev/123456789012/ec2.properties"
        values = dict(M.load_model(path).authoritative)
        values["desired.row.001-002.property"] = "EC2.VPC.UnsupportedProperty"
        write_model(path, values)
        validator = Validator(root, scope, model_validation="full")
        if not validator.run() or not validator.errors:
            pytest.fail("Full Model validation accepted an unsupported property")


@pytest.mark.parametrize("number", ["1", "2"])
def test_reference_metadata_follows_selected_stack(number):
    values = selected_values()
    values["desired.reference.incomplete.consumerKey"] = (
        f"desired.stack.{number}.template"
    )
    if number == "2":
        selected = inputs.selected_stack_values(values, ["One"])
        TestCase().assertNotIn("desired.reference.incomplete.consumerKey", selected)
    else:
        with pytest.raises(ValueError, match="invalid reference fields"):
            inputs.selected_stack_values(values, ["One"])
