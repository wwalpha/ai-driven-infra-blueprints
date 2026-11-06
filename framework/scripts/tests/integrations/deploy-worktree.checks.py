"""Real managed Git lifecycle, plus synthetic AWS controller/Model publication integration."""

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import task_contract_runtime as transitions
import worktree_checkpoint as checkpoints
import worktree_state as ws
import worktree_task as wt
from deploy import (
    completion,
    contracts,
    inputs,
    operation_journal,
    preparation,
    worktree,
)
from deploy import git_publication as publication
from deploy import progress as deploy_progress
from model.format import parse
from model.render import stack_markdown
from model.sources import load_model
from support import (
    deploy_controller_fixtures,
    model_design_fixtures,
    worktree_deploy_fixtures,
)
from support.deploy_controller_fixtures import ACCOUNT, aws_state, invoke
from support.model_sources import write_model
from support.pytest_cli import run
from support.worktree_deploy_fixtures import pin_progress, seed
from support.worktree_task_fixtures import fixture, git
from task_contract import main as task_main
from task_contract_core import read_task_snapshot, selected_task, start
from utils.local_evidence import read_sealed

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture(autouse=True)
def private_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)


class RequestProbe:
    def __init__(self):
        self.tokens = []
        self.finished = False

    def aws(self, operation, **arguments):
        name = arguments["StackName"]
        if operation == "describe_stacks":
            return {"Stacks": [{"StackId": name, "StackStatus": "UPDATE_COMPLETE"}]}
        if operation == "describe_change_set":
            return {
                "Status": "CREATE_COMPLETE" if self.finished else "CREATE_IN_PROGRESS",
                "ChangeSetId": arguments["ChangeSetName"],
                "StackId": name,
                "ExecutionStatus": "EXECUTE_COMPLETE" if self.finished else "AVAILABLE",
            }
        if operation == "describe_stack_events":
            token = next(
                (token for stack, token in reversed(self.tokens) if stack == name), None
            )
            return {
                "StackEvents": [
                    {
                        "StackId": name,
                        "PhysicalResourceId": name,
                        "ClientRequestToken": token,
                        "ResourceType": "AWS::CloudFormation::Stack",
                        "ResourceStatus": "UPDATE_COMPLETE",
                    }
                ]
                if self.finished and token
                else []
            }
        raise ValueError(operation)

    def send(self, runtime, service, operation, arguments):
        key = (
            arguments["StackName"],
            arguments.get("ClientRequestToken", arguments.get("ClientToken")),
        )
        if key not in self.tokens:
            self.tokens.append(key)
        return {"Id": arguments.get("ChangeSetName"), "StackId": arguments["StackName"]}




def deploy_contract(name, files):
    listed = "\n".join(f"- `{p}`" for p in [name, *files])
    return f"""## Task contract
- Task type: `infrastructure`
- Task status: `running`
- Infrastructure phase: `deploy`
## Required changes
- [R1] Publish observations
## Acceptance checks
- [R1] `exists:{files[0]}`
## Validation scope
- `dev/123456789012/ec2`
## Modified files
{listed}
## Allowed paths
{listed}
"""


def check_contract_preparation_correction_round_trip(tmp_path, monkeypatch):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "orders")
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", f"tasks/{root.name}.md")
    path = root / f"tasks/{root.name}.md"
    omitted = f"docs/designs/dev/{ACCOUNT}/s3/s3-bucket-001-bucket-policy.json"
    old = path.read_text(encoding="utf-8")
    assert old.count(f"- `{omitted}`\n") == 2
    path.write_text(old.replace(f"- `{omitted}`\n", ""), encoding="utf-8")
    aws_state(aws)
    for _ in range(6):
        assert invoke(root, report, aws, ["--action", "advance"]) == 0
        if all(
            s["status"] == "SUCCESS"
            for s in json.loads(report.read_text(encoding="utf-8"))["states"].values()
        ):
            break
    assert all(
        s["status"] == "SUCCESS"
        for s in json.loads(report.read_text(encoding="utf-8"))["states"].values()
    )
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    transitions.suspend(
        root, f"tasks/{root.name}.md", "omitted necessary generated JSON path"
    )
    suspended = path.read_text(encoding="utf-8")
    candidate = suspended.replace(
        "## Modified files\n", f"## Modified files\n- `{omitted}`\n"
    ).replace("## Allowed paths\n", f"## Allowed paths\n- `{omitted}`\n")
    source = tmp_path / "corrected-contract.md"
    source.write_text(candidate, encoding="utf-8")
    before = deploy_progress.read_task(root, read_task_snapshot(root, f"tasks/{root.name}.md", live=True))["runContext"]
    with patch.object(
        sys,
        "argv",
        [
            "task_contract.py",
            "--task-file",
            f"tasks/{root.name}.md",
            "--correct-deploy-contract",
            str(source),
        ],
    ):
        assert task_main() == 0
    assert json.loads(aws.read_text(encoding="utf-8"))["calls"] == calls
    progress = deploy_progress.read_task(root, read_task_snapshot(root, f"tasks/{root.name}.md", live=True))["runContext"]
    assert progress["states"] == before["states"]
    assert progress["inputIdentities"] == before["inputIdentities"]
    assert read_task_snapshot(root, f"tasks/{root.name}.md", live=True).status == "suspend"
    transitions.resume(root, f"tasks/{root.name}.md")
    assert run_controller(root, report, aws) == 0
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert all(
        s["status"] == "SUCCESS" and s.get("observedSynced")
        for s in saved["states"].values()
    )
    assert saved["snapshotValidation"] == "PASS"
    assert "gitPublication" not in saved
    assert read_task_snapshot(root, f"tasks/{root.name}.md", live=True).task_digest == progress["taskDigest"]
    assert not any(
        op in {"create_change_set", "execute_change_set"}
        for _, op, _ in json.loads(aws.read_text(encoding="utf-8"))["calls"][
            len(calls) :
        ]
    )


def seed_unrelated_service(root, report, case, **kwargs):
    deploy_controller_fixtures.seed(root, report, case, **kwargs)
    values = model_design_fixtures.model(
        "dynamodb",
        "DynamoDB.Table",
        "app-dev-unrelated",
        [("TableName", "`app-dev-unrelated`", "名前")],
    )
    values.pop("desired.resource.001.cfn-logicalId", None)
    values["desired.resource.001.resourceMode"] = "IMPORT"
    write_model(root / f"model/dev/{ACCOUNT}/dynamodb.properties", values)
    git(root, "add", "model")
    git(root, "commit", "-qm", "Synthetic unrelated service")


def check_scope_failure_correction_round_trip(tmp_path, monkeypatch):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    with patch.object(worktree_deploy_fixtures, "seed_project", seed_unrelated_service):
        root = seed(tmp_path / "project", report, "orders")
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", f"tasks/{root.name}.md")
    path = root / f"tasks/{root.name}.md"
    unrelated = root / f"model/dev/{ACCOUNT}/dynamodb.properties"
    unrelated_before = unrelated.read_bytes()
    text = path.read_text(encoding="utf-8")
    target = json.loads((root / "project.json").read_text(encoding="utf-8"))["targets"][
        0
    ]
    _, units = inputs.load_units(
        root, "dev", ACCOUNT, deploy_controller_fixtures.stack_names(root)
    )
    mappings = preparation.owning_resources(root, "dev", ACCOUNT, target, units)
    execution = "## Execution scope\n" + "".join(
        "- `"
        + json.dumps(
            dict(stack=stack, logicalId=logical, **item),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "`\n"
        for stack, group in sorted(mappings.items())
        for logical, item in sorted(group.items())
    )
    scope = f"- `dev/{ACCOUNT}/s3`\n"
    assert scope in text
    path.write_text(
        text.replace(
            "## Validation scope\n", execution + "## Validation scope\n"
        ).replace(scope, ""),
        encoding="utf-8",
    )
    aws_state(aws)
    assert invoke(root, report, aws, ["--action", "advance"]) != 0
    before = deploy_progress.read_task(root, read_task_snapshot(root, f"tasks/{root.name}.md", live=True))["runContext"]
    failure = Path(before["currentFailure"])
    assert failure.is_file()
    assert any(
        item.get("failure", {}).get("classification") == "OWNER_SCOPE_MISSING"
        for item in before["states"].values()
    )
    failure_bytes = failure.read_bytes()
    from_evidence = read_sealed(root, failure)
    assert from_evidence["states"]
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    transitions.suspend(root, f"tasks/{root.name}.md", "missing owning service")
    candidate = path.read_text(encoding="utf-8").replace(
        "## Validation scope\n", "## Validation scope\n" + scope
    )
    source = tmp_path / "owner-correction.md"
    source.write_text(candidate, encoding="utf-8")
    transitions.correct_deploy_contract(root, f"tasks/{root.name}.md", source)
    after = deploy_progress.read_task(root, read_task_snapshot(root, f"tasks/{root.name}.md", live=True))["runContext"]
    assert before["inputIdentities"] == after["inputIdentities"]
    assert "currentFailure" not in after and after["resolvedScopeFailures"][0][
        "evidence"
    ] == str(failure)
    assert failure.read_bytes() == failure_bytes
    assert json.loads(aws.read_text(encoding="utf-8"))["calls"] == calls
    transitions.resume(root, f"tasks/{root.name}.md")
    assert run_controller(root, report, aws) == 0
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["snapshotValidation"] == "PASS"
    assert unrelated.read_bytes() == unrelated_before
    all_calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    for call in calls:
        if call[1] in {"create_change_set", "execute_change_set"}:
            assert all_calls.count(call) == calls.count(call)


def run_controller(root, report, aws):
    return deploy_controller_fixtures.drive(root, report, aws)


@contextmanager
def managed_repository(tracked_contract=False, untracked_contract=False):
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
        patch.object(publication, "check_scope"),
        patch.object(wt, "_run_model_guard"),
        patch.object(publication, "validate_candidate"),
        patch.object(checkpoints, "validate"),
    ):
        if untracked_contract:
            ignore = primary / ".gitignore"
            ignore.write_text(
                ignore.read_text(encoding="utf-8").replace("tasks/**\n", ""),
                encoding="utf-8",
            )
            git(primary, "add", ".gitignore")
        relative = "model/dev/app/ec2.properties"
        text = (
            "# model-format: 2\nobserved.a.value=`before`\nobserved.b.value=`before`\n"
        )
        source = primary / relative
        source.parent.mkdir(parents=True)
        source.write_text(text, encoding="utf-8")
        units = [
            {"name": name, "template": name + ".yaml", "parameters": name + ".json"}
            for name in ["A", "B"]
        ]
        for path in inputs.deployment_input_paths(primary, "dev", "app", {}, units):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("immutable input", encoding="utf-8")
        git(primary, "add", "model", "infra")
        git(primary, "commit", "-qm", "Stepwise synthetic inputs")
        state = wt.create(primary, "deploy")
        root = Path(state["worktree"])
        name = state["task_file"]
        start(root, name, deploy_contract(name, [relative]))
        if tracked_contract:
            # Simulate a retained legacy managed snapshot that tracked its contract.
            path = primary / name
            path.parent.mkdir()
            path.write_bytes((root / name).read_bytes())
            git(primary, "add", "-f", name)
            git(primary, "commit", "-qm", "Legacy tracked contract")
            (root / name).unlink()
            git(root, "merge", "--ff-only", state["base"])
            state.update(start=git(root, "rev-parse", "HEAD").strip(), tip=git(root, "rev-parse", "HEAD").strip())
            wt.save(wt.state_path(primary, state["task_id"]), state)
        with selected_task(root, name):
            task = read_task_snapshot(root, name, live=True)
            identity = worktree.bind(
                root,
                task,
                {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
                "dev",
                ["A", "B"],
            )
            context = {
                "taskFile": name,
                "taskDigest": task.task_digest,
                "directory": "app",
                "stepUnits": units,
                "inputDigests": {},
                "consumedInputs": {},
                "states": {
                    n: {
                        "status": "RUNNING",
                        "stackId": "stack-" + n,
                        "stackStatus": "CREATE_COMPLETE",
                    }
                    for n in ["A", "B"]
                },
            }
            for unit in units:
                paths = inputs.deployment_input_paths(root, "dev", "app", {}, [unit])
                digests = [inputs.file_digest({}, p, fresh=True) for p in paths]
                context["inputDigests"][unit["name"]] = inputs.fingerprint(digests)
                context["consumedInputs"].update(
                    {
                        p.relative_to(root).as_posix(): digest
                        for p, digest in zip(paths, digests, strict=True)
                    }
                )
            backend = SimpleNamespace(
                root=root,
                phase="deploy",
                run_context=context,
                states=context["states"],
                guard=Mock(),
                deployment_input_paths=partial(
                    inputs.deployment_input_paths, root, "dev", "app", {}
                ),
            )
            pin_progress(backend, identity)
            backend.save = partial(
                deploy_progress.save_progress, backend, operation_journal.OPERATION_FIELDS
            )
            backend.save()
            yield primary, backend, relative


def synchronized_candidate(backend, relative, name):
    root, context = backend.root, backend.run_context
    before = contracts.validation_snapshot(root)
    source = root / relative
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "observed." + name.lower() + ".value=`before`",
            "observed." + name.lower() + ".value=`aws`",
        ),
        encoding="utf-8",
    )
    backend.states[name].update(
        status="SUCCESS",
        observedSynced=True,
        currentStack={"StackStatus": "UPDATE_COMPLETE"},
    )
    context["checkpointPending"] = {
        "stacks": [name],
        "before": before,
        "after": contracts.validation_snapshot(root),
    }
    backend.save()






def check_managed_success_while_peer_running(tmp_path, monkeypatch):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "orders", same_group=True)
    primary = Path(ws.load(root, root.name)[0])
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", f"tasks/{root.name}.md")
    monkeypatch.setenv("TMPDIR", tempfile.gettempdir())
    aws_state(aws)
    assert invoke(root, report, aws, ["--action", "advance"]) == 0
    provider = json.loads(aws.read_text())
    second = "cfn-stack-app-dev-second"
    first = "cfn-stack-app-dev-first"
    provider["stacks"][second]["status"] = "CREATE_IN_PROGRESS"
    aws.write_text(json.dumps(provider))
    assert invoke(root, report, aws, ["--action", "advance"]) == 0
    context = json.loads(report.read_text())
    assert context["states"][first]["status"] == "SUCCESS"
    assert context["states"][second]["status"] == "RUNNING"
    assert invoke(root, report, aws, ["--action", "sync", "--final", "--sync-stack", first, "--sync-stack", second]) == 2
    assert "syncPending" not in json.loads(report.read_text())
    stack_model = root / "model/dev/123456789012/cloudformation-stacks.properties"
    stack_bytes = stack_model.read_bytes()
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", first]) == 0
    assert stack_model.read_bytes() == stack_bytes
    before = git(primary, "rev-parse", "HEAD")
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", first]) == 0
    assert stack_model.read_bytes() == stack_bytes
    assert git(primary, "rev-parse", "HEAD") == before
    provider = json.loads(aws.read_text())
    provider["stacks"][second]["status"] = "CREATE_COMPLETE"
    aws.write_text(json.dumps(provider))
    assert invoke(root, report, aws, ["--action", "advance"]) == 0
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", second]) == 0
    assert git(primary, "rev-parse", "HEAD") == before
    assert wt.changed_paths(root)
    assert invoke(root, report, aws, ["--action", "sync", "--final"]) == 0
    assert read_task_snapshot(root, f"tasks/{root.name}.md", live=True).status == "completed"
    assert git(primary, "rev-parse", "HEAD") == before
    assert root.is_dir()




def seed_reference_consumer(root, report, case, **kwargs):
    deploy_controller_fixtures.seed(root, report, case, **kwargs)
    values = model_design_fixtures.model(
        "rds",
        "RDS.DBSubnetGroup",
        "app-dev-consumer",
        [
            ("DBSubnetGroupName", "`app-dev-consumer`", "名前"),
            (
                "SubnetIds[]",
                '`{"$modelRef":{"logicalId":"EC2_Subnet_001","attribute":"SubnetId"}}`',
                "参照",
            ),
            ("DBSubnetGroupDescription", "`synthetic consumer`", "説明"),
        ],
    )
    values.pop("desired.resource.001.cfn-logicalId", None)
    values["desired.resource.001.resourceMode"] = "IMPORT"
    values["observed.row.001-002.value"] = "`subnet-before`"
    source = write_model(root / f"model/dev/{ACCOUNT}/rds.properties", values)
    view = root / f"docs/designs/dev/{ACCOUNT}/rds.md"
    view.write_text(
        model_design_fixtures.markdown_for(view, load_model(source).values, root),
        encoding="utf-8",
    )
    # An unrelated Model remains a read-only input throughout recovery.
    values = model_design_fixtures.model(
        "dynamodb",
        "DynamoDB.Table",
        "app-dev-unrelated",
        [("TableName", "`app-dev-unrelated`", "名前")],
    )
    values.pop("desired.resource.001.cfn-logicalId", None)
    values["desired.resource.001.resourceMode"] = "IMPORT"
    write_model(root / f"model/dev/{ACCOUNT}/dynamodb.properties", values)
    git(root, "add", "model", "docs")
    git(root, "commit", "-qm", "Synthetic reference consumers")


def check_order_range_preparation_publication_and_resume(tmp_path, monkeypatch):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    primary = deploy_controller_fixtures.seed(
        tmp_path / "project", report, "observed-peers"
    )
    first_template = primary / "infra/cloudformation/templates/first.yaml"
    first_template.write_text(
        deploy_controller_fixtures.load_case("deploy_controller", "orders")["files"][
            "infra/cloudformation/templates/first.yaml"
        ]
        + "\n  VpcFirst:\n    Type: AWS::EC2::VPC\n    Properties: {CidrBlock: 10.1.0.0/16}\n",
        encoding="utf-8",
    )
    stack_source = primary / f"model/dev/{ACCOUNT}/cloudformation-stacks.properties"
    values = dict(inputs.stack_snapshot(stack_source).values)
    for number, order in enumerate((30, 40, 60), 1):
        values[f"desired.stack.{number:03d}.deployOrder"] = str(order)
    write_model(stack_source, values)
    design = primary / f"docs/designs/dev/{ACCOUNT}/cloudformation-stacks.md"
    design.write_text(
        stack_markdown(design, values, primary, validate_delivery=False),
        encoding="utf-8",
    )
    outside_view = design.read_bytes()
    git(primary, "add", "model", "docs", "infra")
    git(primary, "commit", "-qm", "Synthetic partial deployment inputs")
    with patch.object(worktree_deploy_fixtures, "seed_project", return_value=primary):
        root = seed(primary, report)
    baseline = git(primary, "rev-parse", "HEAD")
    contract = root / f"tasks/{root.name}.md"
    contract.unlink()
    logs = tmp_path / "preparation"
    TestCase().assertEqual(
        preparation.main(
            [
                "--repository-root",
                str(root),
                "--environment",
                "dev",
                "--aws-account-id",
                ACCOUNT,
                "--order-from",
                "30",
                "--order-to",
                "50",
                "--task-file",
                f"tasks/{root.name}.md",
                "--log-dir",
                str(logs),
            ]
        ),
        0,
    )
    plan_path = next(logs.iterdir()) / "preparation.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    TestCase().assertEqual(plan["scope"], [f"dev/{ACCOUNT}/ec2", f"dev/{ACCOUNT}/s3"])
    selected = {"cfn-stack-app-dev-first", "cfn-stack-app-dev-second"}
    TestCase().assertEqual(set(plan["ownership"]["resources"]), selected)
    TestCase().assertEqual(
        preparation.main(
            [
                "--repository-root",
                str(root),
                "--register",
                str(plan_path),
            ]
        ),
        0,
    )
    fixed = contract.read_bytes()
    source = root / f"model/dev/{ACCOUNT}/s3.properties"
    before = {
        key: value
        for key, value in load_model(source).authoritative.items()
        if key.startswith(
            (
                "desired.resource.003.",
                "display.resource.003.",
                "desired.row.003-",
                "observed.row.003-",
            )
        )
    }
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", f"tasks/{root.name}.md")
    aws_state(aws)
    TestCase().assertEqual(run_controller(root, report, aws), 0)
    saved = json.loads(report.read_text(encoding="utf-8"))
    TestCase().assertEqual(set(saved["states"]), selected)
    TestCase().assertTrue(
        all(
            state.get("observedSynced")
            for state in saved["states"].values()
        )
    )
    TestCase().assertEqual(saved["snapshotValidation"], "PASS")
    TestCase().assertEqual(git(primary, "rev-parse", "HEAD"), baseline)
    TestCase().assertEqual(
        (root / design.relative_to(primary)).read_bytes(), outside_view
    )
    TestCase().assertEqual(design.read_bytes(), outside_view)
    TestCase().assertEqual(
        {
            key: value
            for key, value in load_model(source).authoritative.items()
            if key in before
        },
        before,
    )
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    TestCase().assertFalse(
        any("cfn-stack-app-dev-third" in str(arguments) for _, _, arguments in calls)
    )
    TestCase().assertEqual(invoke(root, report, aws, ["--action", "status"]), 0)
    TestCase().assertEqual(contract.read_bytes(), fixed)
    TestCase().assertEqual(
        set(json.loads(report.read_text(encoding="utf-8"))["states"]), selected
    )


def check_deferred_consumer_approved_reference_recovery(tmp_path, monkeypatch):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    with patch.object(
        worktree_deploy_fixtures, "seed_project", seed_reference_consumer
    ):
        root = seed(tmp_path / "project", report, "orders")
    monkeypatch.chdir(root)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", f"tasks/{root.name}.md")
    path = root / f"tasks/{root.name}.md"
    text = path.read_text(encoding="utf-8")
    target = json.loads((root / "project.json").read_text())["targets"][0]
    _, units = inputs.load_units(
        root, "dev", ACCOUNT, deploy_controller_fixtures.stack_names(root)
    )
    mappings = preparation.owning_resources(root, "dev", ACCOUNT, target, units)
    execution = "## Execution scope\n" + "".join(
        "- `"
        + json.dumps(
            dict(stack=stack, logicalId=logical, **item),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "`\n"
        for stack, group in sorted(mappings.items())
        for logical, item in sorted(group.items())
    )
    path.write_text(
        text.replace("## Validation scope\n", execution + "## Validation scope\n"),
        encoding="utf-8",
    )
    unrelated = root / f"model/dev/{ACCOUNT}/dynamodb.properties"
    unrelated_before = unrelated.read_bytes()
    consumer = root / f"model/dev/{ACCOUNT}/rds.properties"
    consumer_before = consumer.read_bytes()
    aws_state(aws)
    assert run_controller(root, report, aws) == 0
    progress = deploy_progress.read_task(root, read_task_snapshot(root, f"tasks/{root.name}.md", live=True))
    records = [
        record
        for state in progress["runContext"]["states"].values()
        for record in state.get("deferredConsumers", [])
    ]
    assert records and all(
        record["ownerObservedSynced"] and not record["referenceSynced"]
        for record in records
    )
    assert consumer.read_bytes() == consumer_before
    calls = json.loads(aws.read_text())["calls"]
    transitions.suspend(
        root, f"tasks/{root.name}.md", "Human-approved deferred rds reference synchronization"
    )
    candidate = path.read_text(encoding="utf-8").replace(
        "## Validation scope\n", f"## Validation scope\n- `dev/{ACCOUNT}/rds`\n"
    )
    for heading in ("Modified files", "Allowed paths"):
        candidate = candidate.replace(
            f"## {heading}\n",
            f"## {heading}\n- `model/dev/{ACCOUNT}/rds.properties`\n- `docs/designs/dev/{ACCOUNT}/rds.md`\n",
        )
    external = tmp_path / "reference-correction.md"
    external.write_text(candidate, encoding="utf-8")
    transitions.correct_deploy_contract(
        root, f"tasks/{root.name}.md", external, [f"dev/{ACCOUNT}/rds"]
    )
    corrected_progress = deploy_progress.read_task(root, read_task_snapshot(root, f"tasks/{root.name}.md", live=True))[
        "runContext"
    ]
    assert any(
        item.get("consumer") == f"dev/{ACCOUNT}/rds"
        for item in completion.final_blockers(corrected_progress)
    )
    transitions.resume(root, f"tasks/{root.name}.md")
    first = "cfn-stack-app-dev-first"
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", first]) == 0
    saved = deploy_progress.read_task(root, read_task_snapshot(root, f"tasks/{root.name}.md", live=True))["runContext"]
    resolved = [
        record
        for state in saved["states"].values()
        for record in state.get("deferredConsumers", [])
    ]
    assert len(resolved) == len(records) and all(
        record["referenceSynced"] for record in resolved
    )
    assert "observed.row.001-002.value" not in parse(consumer.read_text()).values
    assert unrelated.read_bytes() == unrelated_before
    assert (
        "subnet-before" not in (root / f"docs/designs/dev/{ACCOUNT}/rds.md").read_text()
    )
    assert json.loads(report.read_text())["snapshotValidation"] == "PASS"
    assert not any(
        operation in {"create_change_set", "execute_change_set"}
        for _, operation, _ in json.loads(aws.read_text())["calls"][len(calls) :]
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
