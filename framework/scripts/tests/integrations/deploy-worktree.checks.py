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
import task_contract_runtime as tasks
import task_contract_runtime as transitions
import worktree_checkpoint as checkpoints
import worktree_state as ws
import worktree_task as wt
from deploy import (
    contracts,
    controller,
    current_request,
    guards,
    inputs,
    operation_journal,
    steps,
    worktree,
)
from deploy import git_publication as publication
from model.format import parse
from model.format import patch as patch_properties
from support.deploy_controller_fixtures import ACCOUNT, aws_state, invoke
from support.pytest_cli import run
from support.worktree_deploy_fixtures import seed
from support.worktree_task_fixtures import fixture, git
from task_contract_core import read_task_snapshot, selected_task, set_status, start
from utils.aws.client import AwsError
from utils.sealed_evidence import evidence_store as old_store

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def pin_progress(backend, identity):
    backend.progress_identity = identity
    backend.progress_root = backend.root.resolve()
    backend.progress_directory = backend.run_context.get("directory")
    backend.progress_destination = worktree.progress_path(backend.root, create=True)
    backend.run_context["repository"] = str(backend.root)
    backend.run_context.setdefault("stepwise", False)
    backend.run_context.setdefault("consumedInputs", {})
    backend.run_context.setdefault("stepUnits", [])
    backend.target = identity["target"]
    backend.run_context.update(
        {
            key: identity[key]
            for key in ("taskFile", "taskDigest", "target", "environment")
        }
    )


@pytest.fixture(autouse=True)
def private_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)


class RequestProbe:
    def __init__(self):
        self.tokens = []
        self.finished = False
        self.lost = False
        self.preparing = False
        self.found = False

    def aws(self, operation, **arguments):
        name = arguments["StackName"]
        if operation == "describe_stacks":
            return {"Stacks": [{"StackId": name, "StackStatus": "UPDATE_COMPLETE"}]}
        if operation == "describe_change_set":
            if self.preparing and not self.found:
                raise AwsError("cloudformation", operation, "ChangeSetNotFound")
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
        if not self.lost:
            self.lost = True
            raise TimeoutError("synthetic lost Execute response")
        self.found = True
        return {"Id": arguments.get("ChangeSetName"), "StackId": arguments["StackName"]}


@pytest.mark.parametrize("legacy", [None, b"{}", b"{broken"])
def check_current_request_is_shared_without_history_or_duplicate_execute(
    tmp_path, legacy
):
    case = TestCase()
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
    ):
        first = Path(wt.create(primary, "request-one")["worktree"])
        second = Path(wt.create(primary, "request-two")["worktree"])
        target = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}
        probe = RequestProbe()
        states = {
            "Example": {
                "currentStack": {"StackId": "Example", "StackStatus": "UPDATE_COMPLETE"}
            }
        }
        one = SimpleNamespace(root=first, target=target, aws=probe.aws, states=states)
        two = SimpleNamespace(root=second, target=target, aws=probe.aws, states=states)
        journal = tmp_path / "operations/journal.json"
        if legacy is not None:
            journal.parent.mkdir(mode=0o700)
            journal.write_bytes(legacy)
        with patch.object(operation_journal, "location", return_value=journal):
            arguments = {
                "StackName": "Example",
                "ChangeSetName": "change",
                "ClientRequestToken": "original",
            }
            with case.assertRaises(TimeoutError):
                current_request.send(
                    one, "execute_change_set", dict(arguments), probe.send
                )
            case.assertIsNotNone(current_request.reconcile(two, {"name": "Example"}))
            with pytest.raises(ValueError, match="unconfirmed"):
                current_request.send(
                    two,
                    "execute_change_set",
                    {**arguments, "ClientRequestToken": "new-token-must-not-be-used"},
                    probe.send,
                )
            case.assertEqual(probe.tokens, [("Example", "original")])
            assert (journal.read_bytes() if journal.exists() else None) == legacy
            probe.finished = True
            settled = current_request.reconcile(two, {"name": "Example"})
            case.assertTrue(settled["settled"])
            current_request.release(two, settled)
            case.assertFalse(current_request.location(target, "Example").exists())
            # A broken request affects its Stack only; no Observed/Task/Git proof is read.
            current_request.location(target, "Example").write_text(
                "broken", encoding="utf-8"
            )
            current_request.send(
                two,
                "execute_change_set",
                {
                    "StackName": "Independent",
                    "ChangeSetName": "other",
                    "ClientRequestToken": "independent",
                },
                probe.send,
            )
            case.assertEqual(probe.tokens[-1], ("Independent", "independent"))

            # Create retransmission retains the original name/token, including a rejected retry.
            probe.preparing, probe.found, probe.finished, probe.lost = (
                True,
                False,
                False,
                False,
            )
            states["Creating"] = {
                "currentStack": {
                    "StackId": "Creating",
                    "StackStatus": "UPDATE_COMPLETE",
                }
            }
            create = {
                "StackName": "Creating",
                "ChangeSetName": "create",
                "ClientToken": "create-original",
            }
            with case.assertRaises(TimeoutError):
                current_request.send(one, "create_change_set", dict(create), probe.send)
            with case.assertRaises(AwsError):
                current_request.send(
                    two,
                    "create_change_set",
                    dict(create),
                    Mock(
                        side_effect=AwsError(
                            "cloudformation", "create_change_set", "ValidationError"
                        )
                    ),
                )
            case.assertTrue(current_request.location(target, "Creating").exists())
            current_request.send(two, "create_change_set", dict(create), probe.send)
            case.assertEqual(probe.tokens.count(("Creating", "create-original")), 1)
            probe.finished = True
            settled = current_request.reconcile(two, {"name": "Creating"})
            case.assertTrue(settled["settled"])
            current_request.release(two, settled)

            # Secret bootstrap keeps only the version token/identity, never the value.
            metadata = Mock(
                return_value={
                    "Stacks": [
                        {"StackId": "SecretOwner", "StackStatus": "UPDATE_COMPLETE"}
                    ],
                    "VersionIdsToStages": {},
                }
            )
            one.aws = two.aws = metadata
            secret = {
                "SecretId": "synthetic-secret",
                "SecretString": "private-value-must-not-be-recorded",
                "ClientRequestToken": "stable-version",
            }
            transport = Mock(side_effect=[TimeoutError("lost secret reply"), {}])
            with case.assertRaises(TimeoutError):
                current_request.send(
                    one,
                    "put_secret_value",
                    dict(secret),
                    transport,
                    service="secretsmanager",
                    stack_name="SecretOwner",
                )
            case.assertNotIn(
                secret["SecretString"],
                current_request.location(target, "SecretOwner").read_text(),
            )
            current_request.send(
                two,
                "put_secret_value",
                dict(secret),
                transport,
                service="secretsmanager",
                stack_name="SecretOwner",
            )
            case.assertEqual(
                transport.call_args.args[3]["ClientRequestToken"], "stable-version"
            )
            case.assertFalse(current_request.location(target, "SecretOwner").exists())


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


def rewrite_base(root):
    old = git(root, "rev-parse", "HEAD")
    replacement = git(
        root, "commit-tree", "HEAD^{tree}", "-m", "Unrelated replacement history"
    )
    git(root, "update-ref", "refs/heads/main", replacement, old)
    assert (
        not ws.git(
            root, "merge-base", "--is-ancestor", old, "main", check=False
        ).returncode
        == 0
    )


def check_start_creates_and_reuses_official_worktree(monkeypatch):
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
    ):
        state = worktree.start(primary, "deploy")
        root = Path(state["worktree"])
        start(
            root, state["task_file"], deploy_contract(state["task_file"], ["file.txt"])
        )
        assert worktree.start(primary, "deploy")["start"] == state["start"]
        assert len(ws.worktrees(primary)) == 2
        (primary / "file.txt").write_text("main advanced\n")
        git(primary, "add", "file.txt")
        git(primary, "commit", "-qm", "Advance")
        assert (
            ws.deploy_start_commit(root, state["task_file"], required=True)
            == state["start"]
        )
        rewrite_base(primary)
        assert (
            ws.deploy_start_commit(root, state["task_file"], required=True)
            == state["start"]
        )
        with pytest.raises(ValueError, match="rewritten"):
            ws.task_start_commit(root, state["task_file"])
        # A same-named Task in the primary checkout cannot execute this Deploy.
        with selected_task(root, state["task_file"]):
            assert worktree.require(root)["task_id"] == "deploy"
        with pytest.raises(ValueError, match="another managed worktree"):
            ws.deploy_start_commit(primary, state["task_file"], required=True)
        start(
            primary,
            state["task_file"],
            deploy_contract(state["task_file"], ["file.txt"]),
        )
        runtime = SimpleNamespace(
            root=primary, guard=Mock(side_effect=partial(worktree.require, primary))
        )
        with (
            selected_task(primary, state["task_file"]),
            pytest.raises(ValueError, match="another managed worktree"),
        ):
            guards.call(runtime, "cloudformation", "execute_change_set", {})
        runtime.guard.assert_called_once()


def check_git_conflict_checkpoints_peers_and_recovers(monkeypatch, tmp_path):
    # This case isolates real Git retention; the controller case below runs real Model guards.
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
        patch.object(publication, "check_scope"),
        patch.object(wt, "_run_model_guard"),
        patch.object(publication, "validate_candidate"),
    ):
        relative = "model/dev/a/ec2.properties"
        source = primary / relative
        source.parent.mkdir(parents=True)
        source.write_text("# model-format: 2\nobserved.row.001-001.value=`before`\n")
        git(primary, "add", relative)
        git(primary, "commit", "-qm", "Model fixture")
        state = worktree.start(primary, "deploy")
        root = Path(state["worktree"])
        name = state["task_file"]
        start(root, name, deploy_contract(name, [relative, "file.txt"]))
        with selected_task(root, name):
            identity = worktree.bind(
                root, read_task_snapshot(root, name), {}, "dev", ["A", "B"]
            )
            backend = SimpleNamespace(
                root=root,
                phase="deploy",
                run_context={
                    "taskFile": name,
                    "states": {
                        "A": {"status": "SUCCESS", "observedSynced": True},
                        "B": {"status": "NOT_STARTED"},
                    },
                    "inputDigests": {"A": "digest"},
                },
                save=Mock(),
            )
            pin_progress(backend, identity)
            worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
            (root / relative).write_text(
                "# model-format: 2\nobserved.row.001-001.value=`aws`\n"
            )
            source.write_text("# model-format: 2\nobserved.row.001-001.value=`main`\n")
            git(primary, "add", relative)
            git(primary, "commit", "-qm", "Conflicting main observation")
            result = publication.publish(root, "deploy")
            assert (
                result["status"] == "CONFLICT"
                and result["conflicts"][0]["items"][0]["deployed"] == "`aws`"
            )
            first = git(root, "rev-parse", "HEAD")
            (root / "file.txt").write_text("Independent Stack B\n")
            backend.run_context["states"]["B"] = {
                "status": "SUCCESS",
                "observedSynced": True,
            }
            backend.run_context["inputDigests"]["B"] = "b-digest"
            worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
            publication.sync(backend)
            assert publication.display(backend)["status"] == "CONFLICT"
            assert git(root, "rev-parse", "HEAD") != first
            assert (primary / "file.txt").read_text() == "original\n"
            result = publication.publish(root, "deploy")
            resolution = tmp_path / "resolution.json"
            resolution.write_text(
                json.dumps(
                    {
                        "approval": "Fixture Human chooses the AWS observation",
                        "base": result["base"],
                        "source": result["source"],
                        "files": {relative: (root / relative).read_text()},
                    }
                )
            )
            assert (
                publication.publish(root, "deploy", resolution)["status"] == "SUCCESS"
            )
            assert (
                source.read_text()
                == "# model-format: 2\nobserved.row.001-001.value=`aws`\n"
            )
            assert (primary / "file.txt").read_text() == "Independent Stack B\n"
            assert all(
                s["status"] == "SUCCESS" for s in backend.run_context["states"].values()
            )
            assert not wt.changed_paths(root) and not wt.changed_paths(primary)


def publish_unstarted_snapshot(settled):
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
        patch.object(publication, "check_scope"),
        patch.object(wt, "_run_model_guard"),
        patch.object(publication, "validate_candidate"),
    ):
        relative = "model/dev/a/ec2.properties"
        source = primary / relative
        source.parent.mkdir(parents=True)
        source.write_text("# model-format: 2\nobserved.row.001-001.value=`before`\n")
        name = "tasks/deploy.md"
        (primary / name).parent.mkdir()
        (primary / name).write_text(deploy_contract(name, [relative]))
        git(primary, "add", "-f", name)
        git(primary, "add", relative)
        git(primary, "commit", "-qm", "Model fixture")
        state = wt.create(primary, "deploy")
        root = Path(state["worktree"])
        name = state["task_file"]
        with selected_task(root, name):
            identity = worktree.bind(
                root,
                read_task_snapshot(root, name),
                {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
                "dev",
                ["A", "B", "C"],
            )
            states = {
                "A": {
                    "status": "SUCCESS",
                    "observedSynced": True,
                    "currentStack": {"StackStatus": "UPDATE_COMPLETE"},
                },
                "B": {
                    "status": "SETTLED" if settled else "FAILED",
                    **({"attemptResult": "UNKNOWN"} if settled else {}),
                    "observedSynced": True,
                    "currentStack": {
                        "StackStatus": "UPDATE_COMPLETE"
                        if settled
                        else "UPDATE_ROLLBACK_COMPLETE"
                    },
                },
                "C": {
                    "status": "NOT_STARTED",
                    "observedSynced": True,
                    "currentStack": {"StackStatus": "UPDATE_COMPLETE"},
                },
            }
            backend = SimpleNamespace(
                root=root,
                phase="deploy",
                run_context={
                    "taskFile": name,
                    "states": states,
                    "stepwise": False,
                    "inputDigests": {},
                    "stepUnits": [
                        {"name": "A", "deployOrder": 1},
                        {"name": "B", "deployOrder": 1},
                        {"name": "C", "deployOrder": 2},
                    ],
                    "deployResult": "UNKNOWN" if settled else "FAIL",
                    "snapshotValidation": "PASS",
                },
            )
            pin_progress(backend, identity)
            worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
            (root / relative).write_text(
                "# model-format: 2\nobserved.row.001-001.value=`aws`\n"
            )
            states["C"]["unexecutedReason"] = (
                "DEPLOY_ENDED_WITHOUT_EXECUTION"
                if settled
                else "PREVIOUS_DEPLOY_ORDER_FAILED"
            )
            snapshot = read_task_snapshot(root, name, live=True)
            backend.states = states
            backend.guard = Mock()
            backend.save = partial(
                worktree.save_progress, backend, operation_journal.OPERATION_FIELDS
            )
            backend.run_context["checkpointPending"] = {
                "stacks": [],
                "before": {relative: "before"},
                "after": contracts.validation_snapshot(root),
                "final": {
                    "taskBefore": snapshot.text,
                    "taskAfter": set_status(snapshot.text, "completed"),
                },
            }
            backend.save()
            checkpoints.snapshot_checkpoint(backend, [])
            publication.publish(root, "deploy")
            saved = worktree.read_progress(root, wt.load(root, "deploy")[3])[
                "runContext"
            ]
            TestCase().assertEqual(
                saved["states"]["C"]["unexecutedReason"],
                states["C"]["unexecutedReason"],
            )
            result = publication.finalize(root, "deploy")
            assert result["verified"] and result["merged"]
            assert source.read_text().endswith("observed.row.001-001.value=`aws`\n")
            assert read_task_snapshot(primary, name, live=True).status == "completed"
            progress = worktree.read_progress(root, result)
            assert progress["runContext"]["deployResult"] == (
                "UNKNOWN" if settled else "FAIL"
            )
            if settled:
                assert (
                    progress["runContext"]["states"]["B"]["attemptResult"] == "UNKNOWN"
                )
            assert progress["runContext"]["states"]["C"]["status"] == "NOT_STARTED"
            old = old_store(root)
            (old / "seal.key").write_bytes(b"broken")
            receipt = old / "deploy.json"
            receipt.write_text("{broken", encoding="utf-8")
            assert wt.cleanup(primary, "deploy")["cleaned"]
            assert receipt.read_text(encoding="utf-8") == "{broken"


def check_failed_snapshot_with_unstarted_stack_publishes():
    publish_unstarted_snapshot(False)
    publish_unstarted_snapshot(True)


def run_controller(root, report, aws):
    if read_task_snapshot(root, "tasks/deploy.md", live=True).status == "completed":
        return invoke(root, report, aws, ["--action", "checkpoint"])
    for _ in range(12):
        assert invoke(root, report, aws, ["--action", "advance"]) == 0
        context = json.loads(report.read_text())
        names = [
            name
            for name, saved in context["states"].items()
            if saved["status"] == "SUCCESS" and not saved.get("observedSynced")
        ]
        if names:
            assert (
                invoke(
                    root,
                    report,
                    aws,
                    [
                        "--action",
                        "sync",
                        *[arg for name in names for arg in ("--sync-stack", name)],
                    ],
                )
                == 0
            )
        context = json.loads(report.read_text())
        pending = context.get("checkpointPending")
        if (
            pending
            and pending.get("after") is not None
            and not context.get("pendingGeneration")
        ):
            assert (
                invoke(
                    root,
                    report,
                    aws,
                    [
                        "--action",
                        "checkpoint",
                        *[
                            arg
                            for name in pending["stacks"]
                            for arg in ("--sync-stack", name)
                        ],
                    ],
                )
                == 0
            )
        context = json.loads(report.read_text())
        if all(
            saved["status"] == "SUCCESS" and saved.get("checkpointed")
            for saved in context["states"].values()
        ):
            return 0
    raise AssertionError("short operations did not complete local checkpoints")


def check_controller_keeps_aws_success_after_rewrite_and_conflict(
    tmp_path, monkeypatch
):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "orders")
    primary = Path(ws.load(root, "deploy")[0])
    rewrite_base(primary)
    source = primary / f"model/dev/{ACCOUNT}/ec2/001.properties"
    if not source.is_file():
        source = primary / f"model/dev/{ACCOUNT}/ec2.properties"
    source.write_text(
        patch_properties(
            parse(source.read_text()), {"observed.row.001-001.value": "`vpc-main`"}
        )
    )
    git(primary, "add", source.relative_to(primary).as_posix())
    git(primary, "commit", "-qm", "Main conflicting observation")
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/deploy.md")
    aws_state(aws)
    assert run_controller(root, report, aws) == 0
    context = json.loads(report.read_text())
    assert all(
        s["status"] == "SUCCESS" and s.get("observedSynced")
        for s in context["states"].values()
    )
    assert context["gitPublication"]["status"] == "CONFLICT", context.get(
        "gitPublication"
    )
    before = json.loads(aws.read_text())["calls"]
    assert run_controller(root, report, aws) == 0
    resumed = json.loads(report.read_text())
    assert resumed["gitPublication"]["status"] == "CONFLICT"
    assert all(s["status"] == "SUCCESS" for s in resumed["states"].values())
    assert not any(
        op in {"create_change_set", "execute_change_set"}
        for _, op, _ in json.loads(aws.read_text())["calls"][len(before) :]
    )
    before = json.loads(aws.read_text())["calls"]
    with selected_task(root, "tasks/deploy.md"):
        result = publication.publish(root, "deploy")
        assert result["status"] == "CONFLICT"
        resolution = tmp_path / "human-resolution.json"
        resolution.write_text(
            json.dumps(
                {
                    "approval": "Fixture Human accepts AWS values and generated views",
                    "base": result["base"],
                    "source": result["source"],
                    "files": {
                        r["path"]: (root / r["path"]).read_text()
                        for r in result["conflicts"]
                    },
                }
            )
        )
        assert publication.publish(root, "deploy", resolution)["status"] == "SUCCESS"
        with pytest.raises(ValueError, match="final candidate"):
            worktree.require_complete(root, read_task_snapshot(root, "tasks/deploy.md"))
    assert json.loads(aws.read_text())["calls"] == before
    assert (
        invoke(
            root,
            report,
            aws,
            ["--action", "status"],
        )
        == 0
    )
    assert not any(
        op == "execute_change_set"
        for _, op, _ in json.loads(aws.read_text())["calls"][len(before) :]
    )


def interrupt_git(actual, owner, boundary, root, *args, **kwargs):
    if root == owner and boundary == "before-commit" and args[0] == "commit":
        raise OSError("interrupted before Git commit")
    result = actual(root, *args, **kwargs)
    if root == owner and (
        boundary == "commit"
        and args[0] == "commit"
        or boundary == "merge"
        and args[:2] == ("merge", "--ff-only")
    ):
        raise OSError("interrupted after Git " + boundary)
    return result


@pytest.mark.parametrize("boundary", ["commit", "merge"])
def check_interrupted_publication_retries_and_cleans(monkeypatch, boundary):
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
        patch.object(publication, "check_scope"),
        patch.object(wt, "_run_model_guard"),
        patch.object(publication, "validate_candidate"),
    ):
        state = worktree.start(primary, "deploy")
        root = Path(state["worktree"])
        name = state["task_file"]
        start(root, name, deploy_contract(name, ["file.txt"]))
        with selected_task(root, name):
            identity = worktree.bind(
                root, read_task_snapshot(root, name), {}, "dev", ["A"]
            )
            backend = SimpleNamespace(
                root=root,
                phase="deploy",
                run_context={
                    "states": {"A": {"status": "SUCCESS", "observedSynced": True}},
                    "inputDigests": {"A": "hash"},
                },
            )
            pin_progress(backend, identity)
            worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
            (root / "file.txt").write_text("Task output\n")
            owner = root if boundary == "commit" else primary
            with patch.object(
                wt, "git", partial(interrupt_git, wt.git, owner, boundary)
            ):
                with pytest.raises(OSError, match="interrupted"):
                    publication.publish(root, "deploy")
            assert publication.publish(root, "deploy")["status"] == "SUCCESS"
            assert (primary / "file.txt").read_text() == "Task output\n"
            snapshot = read_task_snapshot(root, name, live=True)
            backend.states = backend.run_context["states"]
            backend.states["A"]["currentStack"] = {"StackStatus": "UPDATE_COMPLETE"}
            backend.guard = Mock()
            backend.save = partial(
                worktree.save_progress, backend, operation_journal.OPERATION_FIELDS
            )
            snapshot_files = contracts.validation_snapshot(root)
            backend.run_context["checkpointPending"] = {
                "stacks": [],
                "before": snapshot_files,
                "after": snapshot_files,
                "final": {
                    "taskBefore": snapshot.text,
                    "taskAfter": set_status(snapshot.text, "completed"),
                },
            }
            backend.save()
            checkpoints.snapshot_checkpoint(backend, [])
            publication.publish(root, "deploy")
            publication.finalize(root, "deploy")
            assert wt.cleanup(primary, "deploy")["cleaned"]
            assert not root.exists() and not wt.branch_exists(primary, state["branch"])


@contextmanager
def stepwise_repository(tracked_contract=False, untracked_contract=False):
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
        name = "tasks/deploy.md"
        contract = deploy_contract(name, [relative])
        if tracked_contract:
            (primary / name).parent.mkdir()
            (primary / name).write_text(contract, encoding="utf-8")
            git(primary, "add", "-f", name)
        git(primary, "add", "model", "infra")
        git(primary, "commit", "-qm", "Stepwise synthetic inputs")
        state = wt.create(primary, "deploy")
        root = Path(state["worktree"])
        if not tracked_contract:
            start(root, name, contract)
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
                "stepwise": True,
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
                worktree.save_progress, backend, operation_journal.OPERATION_FIELDS
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


def interrupt_saved_state(actual, boundary, path, state):
    actual(path, state)
    if (
        boundary == "receipt"
        and state.get("deployCheckpoints")
        or boundary == "intent"
        and state.get("deployPublication", {}).get("intent")
    ):
        raise OSError("interrupted after saved " + boundary)


def change_publication_candidate(root, tree, base, task):
    source = root / "model/dev/app/ec2.properties"
    source.write_text(
        source.read_text(encoding="utf-8") + "# concurrent candidate\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "boundary",
    [
        None,
        "before-commit",
        "commit",
        "receipt",
        "intent",
        "merge",
        "pendingObserved",
        "pendingGeneration",
        "candidate-change",
    ],
)
def check_stepwise_checkpoint_publication_isolation(boundary):
    with stepwise_repository() as (primary, backend, relative):
        root = backend.root
        synchronized_candidate(backend, relative, "A")
        base = git(primary, "rev-parse", "HEAD")
        with pytest.raises(ValueError, match="checkpoint evidence"):
            publication.publish(root, "deploy")
        assert git(primary, "rev-parse", "HEAD") == base
        assert not wt.load(root, "deploy")[3].get("deployCheckpoints")
        if boundary in {"before-commit", "commit", "receipt"}:
            guard = (
                patch.object(wt, "git", partial(interrupt_git, wt.git, root, boundary))
                if boundary in {"before-commit", "commit"}
                else patch.object(
                    wt, "save", partial(interrupt_saved_state, wt.save, "receipt")
                )
            )
            with guard, pytest.raises(OSError, match="interrupted"):
                checkpoints.snapshot_checkpoint(backend, ["A"])
            committed = git(root, "rev-parse", "HEAD")
            if boundary in {"before-commit", "commit"}:
                with pytest.raises(ValueError, match="checkpoint operation"):
                    publication.publish(root, "deploy")
            else:
                assert publication.publish(root, "deploy")["status"] == "SUCCESS"
            checkpoints.snapshot_checkpoint(backend, ["A"])
            if boundary == "before-commit":
                assert committed == base
                committed = git(root, "rev-parse", "HEAD")
                assert (
                    git(root, "rev-list", "--count", base.strip() + "..HEAD").strip()
                    == "1"
                )
            assert git(root, "rev-parse", "HEAD") == committed
        else:
            checkpoints.snapshot_checkpoint(backend, ["A"])
        saved = git(root, "rev-parse", "HEAD")
        if boundary == "candidate-change":
            with (
                patch.object(
                    publication, "validate_candidate", change_publication_candidate
                ),
                pytest.raises(ValueError, match="inputs changed"),
            ):
                publication.publish(root, "deploy")
            assert git(primary, "rev-parse", "HEAD") == base
            assert git(root, "rev-parse", "HEAD") == saved
            return
        publication.sync(backend)
        assert publication.display(backend)["status"] == "SUCCESS"
        # B edits the same Model file; A's Git retry must preserve B's staged candidate.
        synchronized_candidate(backend, relative, "B")
        if boundary in {"pendingObserved", "pendingGeneration"}:
            backend.run_context[boundary] = {"B": "retained candidate"}
            backend.save()
        git(root, "add", relative)
        candidate = (root / relative).read_bytes()
        index = git(root, "write-tree")
        first_main = git(primary, "rev-parse", "HEAD")
        result = publication.publish(root, "deploy")
        assert result["status"] == "SUCCESS"
        assert git(primary, "rev-parse", "HEAD") == first_main
        assert git(root, "rev-parse", "HEAD") == saved
        assert (
            git(root, "write-tree") == index
            and (root / relative).read_bytes() == candidate
        )
        assert "observed.b.value=`before`" in (primary / relative).read_text()
        backend.run_context.pop("pendingObserved", None)
        backend.run_context.pop("pendingGeneration", None)
        checkpoints.snapshot_checkpoint(backend, ["B"])
        if boundary in {"intent", "merge"}:
            guard = (
                patch.object(
                    wt, "save", partial(interrupt_saved_state, wt.save, "intent")
                )
                if boundary == "intent"
                else patch.object(
                    wt, "git", partial(interrupt_git, wt.git, primary, "merge")
                )
            )
            with guard, pytest.raises(OSError, match="interrupted"):
                publication.publish(root, "deploy")
        result = publication.publish(root, "deploy")
        merged = git(primary, "rev-parse", "HEAD")
        assert result["status"] == "SUCCESS" and result["commit"] == merged
        assert not result["nextActions"]
        assert publication.publish(root, "deploy")["commit"] == merged
        assert git(primary, "rev-parse", "HEAD") == merged
        assert (primary / relative).read_bytes() == candidate


@pytest.mark.parametrize(
    "boundary", [None, "adopt", "before-commit", "commit", "receipt", "intent", "merge"]
)
@pytest.mark.parametrize("tracked", [False, True])
def check_stepwise_final_contract_checkpoint(boundary, tracked):
    with stepwise_repository(tracked_contract=tracked) as (primary, backend, relative):
        root = backend.root
        synchronized_candidate(backend, relative, "A")
        checkpoints.snapshot_checkpoint(backend, ["A"])
        publication.publish(root, "deploy")
        synchronized_candidate(backend, relative, "B")
        pending = backend.run_context["checkpointPending"]
        snapshot = read_task_snapshot(root, "tasks/deploy.md", live=True)
        pending["final"] = {
            "taskBefore": snapshot.text,
            "taskAfter": set_status(snapshot.text, "completed"),
        }
        backend.save()
        parent = git(root, "rev-parse", "HEAD")
        writes = partial(interrupt_final_adoption, checkpoints.tasks.atomic_files)
        if boundary in {"adopt", "before-commit", "commit", "receipt"}:
            guard = (
                patch.object(checkpoints.tasks, "atomic_files", writes)
                if boundary == "adopt"
                else patch.object(wt, "save", partial(interrupt_final_receipt, wt.save))
                if boundary == "receipt"
                else patch.object(
                    wt, "git", partial(interrupt_git, wt.git, root, boundary)
                )
            )
            with guard, pytest.raises(OSError, match="interrupted"):
                checkpoints.snapshot_checkpoint(backend, ["B"])
            # Real reload uses only saved progress; no new final flag or observation.
            backend.run_context = worktree.read_progress(
                root, wt.load(root, "deploy")[3]
            )["runContext"]
            backend.states = backend.run_context["states"]
        checkpoints.snapshot_checkpoint(backend, ["B"])
        source = git(root, "rev-parse", "HEAD").strip()
        assert (
            git(root, "rev-list", "--count", parent.strip() + "..HEAD").strip() == "1"
        )
        paths = set(
            git(
                root, "diff-tree", "--no-commit-id", "--name-only", "-r", source
            ).splitlines()
        )
        assert relative in paths and ((snapshot.name in paths) == tracked)
        if tracked:
            assert "- Task status: `completed`" in git(
                root, "show", source + ":" + snapshot.name
            )
        else:
            assert not git(root, "ls-files", snapshot.name)
        if boundary in {"intent", "merge"}:
            guard = (
                patch.object(
                    wt, "save", partial(interrupt_saved_state, wt.save, "intent")
                )
                if boundary == "intent"
                else patch.object(
                    wt, "git", partial(interrupt_git, wt.git, primary, "merge")
                )
            )
            with guard, pytest.raises(OSError, match="interrupted"):
                publication.publish(root, "deploy")
        assert publication.publish(root, "deploy")["status"] == "SUCCESS"
        result = publication.finalize(root, "deploy")
        assert result["verified"] and git(root, "rev-parse", "HEAD").strip() == source
        assert wt.cleanup(primary, "deploy")["cleaned"]


def interrupt_final_receipt(real, path, state):
    real(path, state)
    if state.get("deployPublication", {}).get("finalCandidate"):
        raise OSError("interrupted after final receipt")


def interrupt_final_adoption(real, outputs, **kwargs):
    real(outputs, **kwargs)
    if any(str(path).endswith("tasks/deploy.md") for path in outputs):
        raise OSError("interrupted after final Task adoption")


@pytest.mark.parametrize(
    "problem", ["target", "commit", "zero", "coverage", "services"]
)
def check_task_completion_rechecks_checkpoint_receipts(problem):
    with stepwise_repository() as (primary, backend, relative):
        root = backend.root
        for name in ["A", "B"]:
            if name == "B" and problem == "zero":
                snapshot = contracts.validation_snapshot(root)
                backend.states[name].update(
                    status="SUCCESS",
                    observedSynced=True,
                    currentStack={"StackStatus": "UPDATE_COMPLETE"},
                )
                backend.run_context["checkpointPending"] = {
                    "stacks": [name],
                    "before": snapshot,
                    "after": snapshot,
                }
                backend.save()
            else:
                synchronized_candidate(backend, relative, name)
            checkpoints.snapshot_checkpoint(backend, [name])
            publication.publish(root, "deploy")
        _, _, path, state = wt.load(root, "deploy")
        if problem == "target":
            state["deployCheckpoints"]["A"]["identity"] = {
                **state["deployIdentity"],
                "target": {"awsAccountId": "other"},
            }
        elif problem == "commit":
            state["deployCheckpoints"]["A"]["commit"] = "unrecorded-commit"
        elif problem == "coverage":
            state["deployCheckpoints"]["A"]["coverage"] = {"ec2": {"other": True}}
        elif problem == "services":
            state["deployCheckpoints"]["A"]["services"] = ["other"]
        else:
            assert (
                state["deployCheckpoints"]["A"]["commit"]
                == state["deployCheckpoints"]["B"]["commit"]
            )
        wt.save(path, state)
        progress = worktree.read_progress(root, state)
        before = json.loads(json.dumps(progress["runContext"]["states"]))
        with pytest.raises(ValueError, match="final candidate"):
            tasks.complete(root, "tasks/deploy.md")
        assert (
            read_task_snapshot(root, "tasks/deploy.md", live=True).status == "running"
        )
        assert worktree.read_progress(root, state)["runContext"]["states"] == before


def check_stepwise_success_while_peer_running(tmp_path, monkeypatch):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "orders", same_group=True)
    primary = Path(ws.load(root, "deploy")[0])
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/deploy.md")
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
    stack_model = root / "model/dev/123456789012/cloudformation-stacks.properties"
    stack_bytes = stack_model.read_bytes()
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", first]) == 0
    assert stack_model.read_bytes() == stack_bytes
    before = git(primary, "rev-parse", "HEAD")
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", first]) == 0
    assert stack_model.read_bytes() == stack_bytes
    assert git(primary, "rev-parse", "HEAD") == before
    with selected_task(root, "tasks/deploy.md"):
        TestCase().assertEqual(publication.publish(root, "deploy")["status"], "SUCCESS")
    assert git(primary, "rev-parse", "HEAD") == before
    with patch.object(
        publication, "publish", side_effect=ws.Blocked("temporary Git interruption")
    ):
        assert (
            invoke(root, report, aws, ["--action", "checkpoint", "--sync-stack", first])
            == 0
        )
    context = json.loads(report.read_text())
    TestCase().assertEqual(context["gitPublication"]["status"], "SUCCESS")
    TestCase().assertFalse(context["gitPublication"]["retryable"])
    provider = json.loads(aws.read_text())
    provider["stacks"][second]["status"] = "CREATE_COMPLETE"
    aws.write_text(json.dumps(provider))
    assert invoke(root, report, aws, ["--action", "advance"]) == 0
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", second]) == 0
    candidates = {p: (root / p).read_bytes() for p in wt.changed_paths(root)}
    TestCase().assertFalse(candidates)
    calls = json.loads(aws.read_text())["calls"]
    result = wt.run_deploy_publication(root, "deploy")
    assert result["status"] == "SUCCESS"
    assert wt.changed_paths(root) == set(candidates)
    assert all((root / p).read_bytes() == content for p, content in candidates.items())
    assert json.loads(aws.read_text())["calls"] == calls
    assert git(primary, "rev-parse", "HEAD") != before
    TestCase().assertEqual(result["checkpointRequired"], [])
    assert (
        invoke(root, report, aws, ["--action", "checkpoint", "--sync-stack", second])
        == 0
    )
    with selected_task(root, "tasks/deploy.md"):
        TestCase().assertEqual(
            read_task_snapshot(root, "tasks/deploy.md", live=True).status, "running"
        )
        assert invoke(root, report, aws, ["--action", "sync", "--final"]) == 0
        transitions.complete(root, "tasks/deploy.md")
    _, _, path, lifecycle = wt.load(root, "deploy")
    original = path.read_bytes()
    evidence = worktree.progress_path(root).read_bytes()
    provider = aws.read_bytes()
    controller_report = report.read_bytes()
    task_bytes = (root / "tasks/deploy.md").read_bytes()
    heads = [git(where, "rev-parse", "HEAD") for where in (primary, root)]
    statuses = [git(where, "status", "--porcelain") for where in (primary, root)]
    for missing in ("one", "all"):
        altered = json.loads(original)
        if missing == "one":
            altered["deployCheckpoints"].pop(first)
        else:
            altered["deployCheckpoints"] = {}
        try:
            wt.save(path, altered)
            metadata = path.read_bytes()
            with selected_task(root, "tasks/deploy.md"):
                worktree.require_complete(
                    root, read_task_snapshot(root, "tasks/deploy.md", live=True)
                )
            TestCase().assertEqual(
                read_task_snapshot(root, "tasks/deploy.md", live=True).status,
                "completed",
                missing,
            )
            TestCase().assertEqual(
                worktree.progress_path(root).read_bytes(), evidence, missing
            )
            TestCase().assertEqual(path.read_bytes(), metadata, missing)
            TestCase().assertEqual(aws.read_bytes(), provider, missing)
            TestCase().assertEqual(report.read_bytes(), controller_report, missing)
            TestCase().assertEqual(
                (root / "tasks/deploy.md").read_bytes(), task_bytes, missing
            )
            TestCase().assertEqual(
                [git(where, "rev-parse", "HEAD") for where in (primary, root)],
                heads,
                missing,
            )
            TestCase().assertEqual(
                [git(where, "status", "--porcelain") for where in (primary, root)],
                statuses,
                missing,
            )
            TestCase().assertEqual(wt.load(root, "deploy")[3], altered, missing)
            TestCase().assertEqual(
                altered["deployPublication"], lifecycle["deployPublication"], missing
            )
            TestCase().assertEqual(
                altered["deployPublication"]["status"], "SUCCESS", missing
            )
            TestCase().assertTrue(
                all(
                    saved["status"] == "SUCCESS" and saved["observedSynced"]
                    for saved in worktree.read_progress(root, altered)["runContext"][
                        "states"
                    ].values()
                ),
                missing,
            )
        except Exception as exc:
            raise AssertionError(f"receipt case {missing} failed: {exc}") from exc
        finally:
            path.write_bytes(original)
            TestCase().assertEqual(path.read_bytes(), original, missing)
    try:
        with selected_task(root, "tasks/deploy.md"):
            worktree.require_complete(
                root, read_task_snapshot(root, "tasks/deploy.md", live=True)
            )
            TestCase().assertEqual(
                read_task_snapshot(root, "tasks/deploy.md").status, "completed"
            )
        assert wt.finalize(root, "deploy")["cleaned"]
        assert not root.exists()
        TestCase().assertFalse(path.exists(), "normal: lifecycle cleanup")
    except Exception as exc:
        raise AssertionError(f"receipt case normal failed: {exc}") from exc


@pytest.mark.parametrize("mode", ["tracked", "ignored", "untracked"])
def check_final_zero_model_delta_keeps_exact_source_history(mode):
    tracked = mode == "tracked"
    with stepwise_repository(
        tracked_contract=tracked, untracked_contract=mode == "untracked"
    ) as (primary, backend, relative):
        for name in ("A", "B"):
            synchronized_candidate(backend, relative, name)
            checkpoints.snapshot_checkpoint(backend, [name])
            publication.publish(backend.root, "deploy")
        root = backend.root
        parent = git(root, "rev-parse", "HEAD").strip()
        task = read_task_snapshot(root, "tasks/deploy.md", live=True)
        snapshot = contracts.validation_snapshot(root)
        backend.run_context["checkpointPending"] = {
            "stacks": [],
            "before": snapshot,
            "after": snapshot,
            "final": {
                "taskBefore": task.text,
                "taskAfter": set_status(task.text, "completed"),
            },
        }
        backend.save()
        checkpoints.snapshot_checkpoint(backend, [])
        source = git(root, "rev-parse", "HEAD").strip()
        assert (source != parent) == tracked
        if tracked:
            assert set(
                git(
                    root, "diff-tree", "--no-commit-id", "--name-only", "-r", source
                ).splitlines()
            ) == {task.name}
        assert publication.publish(root, "deploy")["status"] == "SUCCESS"
        publication.finalize(root, "deploy")
        assert git(root, "rev-parse", "HEAD").strip() == source
        if mode == "untracked":
            with (
                patch.object(wt, "git", partial(interrupt_untracked_cleanup, wt.git)),
                pytest.raises(OSError, match="interrupted"),
            ):
                wt.cleanup(primary, "deploy")
            assert root.exists() and not (root / task.name).exists()
        assert wt.cleanup(primary, "deploy")["cleaned"]


def interrupt_untracked_cleanup(real, root, *args, **kwargs):
    if args[:2] == ("worktree", "remove"):
        raise OSError("interrupted after untracked Task removal")
    return real(root, *args, **kwargs)


def check_failed_final_validation_keeps_running_task_and_saved_model():
    with stepwise_repository(tracked_contract=True) as (primary, backend, relative):
        for name in ("A", "B"):
            synchronized_candidate(backend, relative, name)
            if name == "A":
                checkpoints.snapshot_checkpoint(backend, [name])
                publication.publish(backend.root, "deploy")
        root = backend.root
        task = read_task_snapshot(root, "tasks/deploy.md", live=True)
        pending = backend.run_context["checkpointPending"]
        pending["final"] = {
            "taskBefore": task.text,
            "taskAfter": set_status(task.text, "completed"),
        }
        backend.save()
        saved = (root / relative).read_bytes()
        heads = [git(where, "rev-parse", "HEAD") for where in (primary, root)]
        with (
            patch.object(
                publication,
                "validate_candidate",
                side_effect=ValueError("Acceptance FAIL"),
            ),
            pytest.raises(ValueError, match="Acceptance FAIL"),
        ):
            checkpoints.snapshot_checkpoint(backend, ["B"])
        assert read_task_snapshot(root, task.name, live=True).status == "running"
        assert (root / relative).read_bytes() == saved
        assert [git(where, "rev-parse", "HEAD") for where in (primary, root)] == heads
        retained = worktree.read_progress(root, wt.load(root, "deploy")[3])[
            "runContext"
        ]
        assert (
            retained["snapshotValidation"] == "FAIL"
            and retained["checkpointPending"]["final"]["taskAfter"]
            == pending["final"]["taskAfter"]
        )


@pytest.mark.parametrize("replacement_request", [False, True])
def check_old_worktree_reconciles_released_identity_without_removing_new_request(
    tmp_path, replacement_request
):
    # Two local progress stores share only the current request, never each other's files.
    target = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}
    roots = [tmp_path / "original", tmp_path / "peer"]
    for root in roots:
        root.mkdir()
    request = tmp_path / "request.json"
    original = {
        "operation": "execute_change_set",
        "name": "A",
        "service": "cloudformation",
        "resourceId": None,
        "stackId": "old-id",
        "changeSetId": "old-change",
        "token": "old-token",
    }
    request.write_text(json.dumps(original), encoding="utf-8")
    request.chmod(0o600)
    backends = []
    for root in roots:
        identity = {
            "taskFile": "tasks/deploy.md",
            "taskDigest": "fixed",
            "target": target,
            "environment": "dev",
            "stacks": ["A"],
        }
        state = {
            "status": "RUNNING",
            "clientToken": "old-token",
            "changeSetId": "old-change",
            "executionEvidence": {"StackId": "old-id"},
        }
        context = {
            "stepwise": True,
            "stepUnits": [{"name": "A", "deployOrder": 1}],
            "directory": "app",
            "states": {"A": state},
            "inputDigests": {"A": "fixed"},
        }
        backend = SimpleNamespace(
            root=root,
            phase="deploy",
            target=target,
            units=context["stepUnits"],
            states=context["states"],
            run_context=context,
            templates={},
            aws=Mock(
                return_value={
                    "Stacks": [{"StackId": "new-id", "StackStatus": "UPDATE_COMPLETE"}]
                }
            ),
        )
        pin_progress(backend, identity)
        backend.save = partial(
            worktree.save_progress, backend, operation_journal.OPERATION_FIELDS
        )
        backend.poll = partial(controller.poll, backend)
        backend.save()
        backends.append(backend)
    with patch.object(current_request, "location", return_value=request):
        steps.refresh_requests(backends[1])
        assert not request.exists()
        if replacement_request:
            new = original | {
                "stackId": "new-id",
                "changeSetId": "new-change",
                "token": "new-token",
            }
            request.write_text(json.dumps(new), encoding="utf-8")
            request.chmod(0o600)
        steps.refresh_requests(backends[0])
        saved = worktree.read_progress(
            roots[0], {"deployIdentity": backends[0].progress_identity}
        )["runContext"]["states"]["A"]
        assert saved["attemptResult"] == saved["endedRequest"]["result"] == "UNKNOWN"
        assert not {"clientToken", "changeSetId", "executionEvidence"} & saved.keys()
        assert saved["requestPending"] == replacement_request
        if replacement_request:
            assert json.loads(request.read_text(encoding="utf-8")) == new
        else:
            assert not request.exists()


def mutate_final_input(kind, relative, root, tree, base, task):
    if kind == "task":
        destination = root / task.name
        destination.write_text(
            destination.read_text(encoding="utf-8") + "\nchanged authority\n",
            encoding="utf-8",
        )
    elif kind == "input":
        destination = root / "infra/cloudformation/parameters/dev/app/B.json"
        destination.write_text("changed fixed parameters", encoding="utf-8")
    elif kind == "head":
        git(root, "commit", "--allow-empty", "-qm", "external HEAD change")
    elif kind == "index":
        git(root, "add", relative)
    else:
        destination = root / relative
        destination.write_text(
            destination.read_text(encoding="utf-8") + "# external Model candidate\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize("kind", ["task", "input", "head", "index", "candidate"])
def check_final_candidate_external_changes_stop_before_adoption(kind):
    with stepwise_repository(tracked_contract=True) as (primary, backend, relative):
        root = backend.root
        for name in ("A", "B"):
            synchronized_candidate(backend, relative, name)
            if name == "A":
                checkpoints.snapshot_checkpoint(backend, [name])
                publication.publish(root, "deploy")
        task = read_task_snapshot(root, "tasks/deploy.md", live=True)
        backend.run_context["checkpointPending"]["final"] = {
            "taskBefore": task.text,
            "taskAfter": set_status(task.text, "completed"),
        }
        backend.save()
        main = git(primary, "rev-parse", "HEAD")
        with (
            patch.object(
                publication,
                "validate_candidate",
                partial(mutate_final_input, kind, relative),
            ),
            pytest.raises(ValueError, match="changed during validation"),
        ):
            checkpoints.snapshot_checkpoint(backend, ["B"])
        assert read_task_snapshot(root, task.name, live=True).status == "running"
        assert git(primary, "rev-parse", "HEAD") == main
        assert (
            worktree.read_progress(root, wt.load(root, "deploy")[3])["runContext"][
                "checkpointPending"
            ]["final"].get("validated")
            is None
        )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
