"""Real managed Git lifecycle, plus synthetic AWS controller/Model publication integration."""

import json
import os
import subprocess
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
    scheduler,
    steps,
    temporary,
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
from utils.json_format import fingerprint

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def pin_progress(backend, identity):
    backend.progress_identity = identity
    backend.progress_root = backend.root.resolve()
    backend.progress_directory = backend.run_context.get("directory")
    backend.progress_destination = worktree.progress_path(backend.root, create=True)
    backend.run_context["repository"] = str(backend.root)
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


def assert_request_lock_survives_process_exit(path):
    original = path.read_bytes()
    script = "from pathlib import Path; import sys; from deploy.operation_journal import locked\nwith locked(Path(sys.argv[1])):\n print('READY', flush=True)\n sys.stdin.read()\n"
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(operation_journal.__file__).resolve().parents[1]),
    }
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", script, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        assert process.stdout.readline().strip() == "READY"
        inode = path.with_suffix(".lock").stat().st_ino
        with pytest.raises(operation_journal.Blocked, match="lock busy"):
            with operation_journal.locked(path):
                raise AssertionError("concurrent request lock acquired")
        process.kill()
        process.wait(timeout=5)
        with operation_journal.locked(path):
            assert path.with_suffix(".lock").stat().st_ino == inode
            assert path.read_bytes() == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def check_current_request_is_shared_without_history_or_duplicate_execute(tmp_path):
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
            with pytest.raises(current_request.Blocked, match="unconfirmed"):
                current_request.send(
                    two,
                    "execute_change_set",
                    {**arguments, "ClientRequestToken": "new-token-must-not-be-used"},
                    probe.send,
                )
            case.assertEqual(probe.tokens, [("Example", "original")])
            assert not journal.exists()
            owner = SimpleNamespace(name="tasks/request-one.md", task_digest="one")
            directory = temporary.create(journal, first, owner, target, ["Example"])
            template = directory / "Example.json"
            template.write_text("{}", encoding="utf-8")
            states["Example"].update(status="RUNNING", delivery={"path": str(template)})
            one.phase = "deploy"
            one.run_context = {
                "states": states,
                "directory": "app",
                "inputDigests": {"Example": "fixed"},
            }
            identity = {
                "taskFile": owner.name,
                "taskDigest": owner.task_digest,
                "target": target,
                "environment": "dev",
                "stacks": ["Example"],
            }
            pin_progress(one, identity)
            worktree.save_progress(one, operation_journal.OPERATION_FIELDS)
            progress_path = worktree.progress_path(first)
            progress_bytes = progress_path.read_bytes()
            request_path = current_request.location(target, "Example")
            request_bytes = request_path.read_bytes()
            temporary.reclaim(
                journal,
                second,
                target,
                task=SimpleNamespace(name="tasks/request-two.md", task_digest="two"),
                run_context={"states": {}},
            )
            assert template.read_text(encoding="utf-8") == "{}"
            assert (
                progress_path.read_bytes() == progress_bytes
                and request_path.read_bytes() == request_bytes
            )
            restored = worktree.read_progress(first, {"deployIdentity": identity})[
                "runContext"
            ]
            assert restored["states"]["Example"]["delivery"]["path"] == str(template)
            temporary.reclaim(journal, first, target, task=owner, run_context=restored)
            assert template.exists()
            assert_request_lock_survives_process_exit(
                current_request.location(target, "Example")
            )
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


@pytest.mark.parametrize("settled", [False, True])
def check_failed_snapshot_with_unstarted_stack_publishes(settled):
    with managed_repository() as (primary, backend, relative):
        for name in ("A", "B"):
            synchronized_candidate(backend, relative, name)
            if name == "A":
                backend.states[name].update(
                    status="SETTLED" if settled else "FAILED",
                    **({"attemptResult": "UNKNOWN"} if settled else {}),
                )
                checkpoints.snapshot_checkpoint(backend, [name])
                publication.publish(backend.root, "deploy")
        backend.states["B"].update(
            status="NOT_STARTED",
            unexecutedReason="DEPLOY_ENDED_WITHOUT_EXECUTION"
            if settled
            else "PREVIOUS_DEPLOY_ORDER_FAILED",
        )
        backend.run_context["deployResult"] = "UNKNOWN" if settled else "FAIL"
        snapshot = read_task_snapshot(backend.root, "tasks/deploy.md", live=True)
        backend.run_context["checkpointPending"]["final"] = {
            "taskBefore": snapshot.text,
            "taskAfter": set_status(snapshot.text, "completed"),
        }
        backend.save()
        checkpoints.snapshot_checkpoint(backend, ["B"])
        publication.publish(backend.root, "deploy")
        result = publication.finalize(backend.root, "deploy")
        saved = worktree.read_progress(backend.root, result)["runContext"]
        assert saved["deployResult"] == ("UNKNOWN" if settled else "FAIL")
        assert saved["states"]["B"]["status"] == "NOT_STARTED"
        if settled:
            assert saved["states"]["A"]["attemptResult"] == "UNKNOWN"
        assert (
            read_task_snapshot(backend.root, "tasks/deploy.md", live=True).status
            == "completed"
        )
        assert wt.cleanup(primary, "deploy")["cleaned"]


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
def check_managed_checkpoint_publication_isolation(boundary):
    with managed_repository() as (primary, backend, relative):
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
def check_managed_final_contract_checkpoint(boundary, tracked):
    with managed_repository(tracked_contract=tracked) as (primary, backend, relative):
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
    with managed_repository() as (primary, backend, relative):
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


def check_managed_success_while_peer_running(tmp_path, monkeypatch):
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
    with managed_repository(
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
    with managed_repository(tracked_contract=True) as (primary, backend, relative):
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
    with managed_repository(tracked_contract=True) as (primary, backend, relative):
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


@pytest.mark.parametrize(
    "released,missing_stack", [(False, False), (False, True), (True, False)]
)
def check_create_review_execute_uses_one_atomic_request(
    tmp_path, released, missing_stack
):
    name = "Example"
    stack = "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/Example/stack-id"
    change = "arn:aws:cloudformation:ap-northeast-1:123456789012:changeSet/change/id"
    observed = {
        "StackId": stack,
        "ChangeSetId": change,
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "Changes": [],
    }
    unit = {"name": name, "deployOrder": 1}
    state = {
        "status": "CHANGESET_CREATING",
        "stackId": stack,
        "changeSetId": "change",
        "preparationId": "create-token",
    }
    request = tmp_path / "request.json"
    progress = tmp_path / "progress.json"
    calls = []
    saves = []
    runtime = SimpleNamespace(
        target={"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
        states={name: state},
        templates={name: ({}, None)},
        expected_digests={name: "input"},
    )

    def save():
        worktree.write_sealed(tmp_path, progress, state)
        saves.append(
            (
                json.loads(request.read_text()) if request.exists() else None,
                json.loads(json.dumps(state)),
            )
        )

    def transport(_runtime, _service, operation, arguments):
        calls.append((operation, dict(arguments), json.loads(request.read_text())))
        return (
            {"StackId": None if missing_stack else stack}
            if operation == "create_change_set"
            else {}
        )

    def aws(operation, **arguments):
        if operation in {"create_change_set", "execute_change_set"}:
            return current_request.send(runtime, operation, arguments, transport)
        if operation == "describe_stacks":
            return {"Stacks": [{"StackId": stack, "StackStatus": "UPDATE_COMPLETE"}]}
        if operation == "describe_change_set":
            return dict(observed)
        if operation == "describe_stack_events":
            return {"StackEvents": []}
        raise AssertionError(operation)

    runtime.aws = aws
    runtime.save = save
    runtime.describe_change_set = lambda _unit, _state: dict(observed)
    runtime.approvals = set()
    runtime.review_prepared = partial(controller.review_prepared, runtime)
    runtime.execute = partial(controller.execute, runtime)
    runtime.prepare = Mock()
    runtime.load_inputs = Mock()
    runtime.observed_readiness = Mock()
    runtime.input_digest = lambda _unit, fresh=False: "input"
    runtime.file_digest = Mock()
    runtime.template_arguments = Mock()
    runtime.check_imports = Mock()
    runtime.poll = Mock()
    with patch.object(current_request, "location", return_value=request):
        aws(
            "create_change_set",
            StackName=name,
            ChangeSetName="change",
            ClientToken="create-token",
        )
        if released:
            state["currentStack"] = {"StackId": stack, "StackStatus": "UPDATE_COMPLETE"}
            settled = current_request.reconcile(runtime, unit)
            assert settled["settled"]
            current_request.end_tracking(state, settled)
            save()
            current_request.release(runtime, settled)
            assert not request.exists()
        assert current_request.current_state.same_change_set("change", change)
        assert not current_request.current_state.same_change_set(change, "change")
        assert scheduler.run_group([unit], 1, runtime.states, runtime, save) == "ACTIVE"
        assert [call[0] for call in calls] == [
            "create_change_set",
            "execute_change_set",
        ]
        assert calls[-1][2]["submission"] == "SENDING"
        assert calls[-1][1]["ClientRequestToken"] != "create-token"
        assert any(
            item[0]
            and item[0]["operation"] == "create_change_set"
            and item[1].get("endedRequest")
            for item in saves
        )
        assert json.loads(request.read_text())["submission"] == "SENT"
        assert state["changeDigest"] == fingerprint([])
        with pytest.raises(current_request.Blocked):
            aws(
                "execute_change_set",
                StackName=stack,
                ChangeSetName=change,
                ClientRequestToken=state["clientToken"],
            )
        assert len(calls) == 2


if __name__ == "__main__":
    raise SystemExit(run(__file__))
