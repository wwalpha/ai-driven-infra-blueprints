"""Short-operation decisions and complete identifier coverage, without AWS or worktrees."""

import json
import os
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import (
    cli_guidance,
    controller,
    current_request,
    current_state,
    observed,
    operation_journal,
    recovery,
    scheduler,
    steps,
    worktree,
)
from model.core import properties, stack_model, validate_model_keys
from model.observed import verify_observed_outputs
from model.projection import observed_value
from support.cloudformation_deploy_fixtures import Fake, states, units
from support.pytest_cli import run
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

prepare_complete = worktree.prepare_complete


def check_advance_returns_with_running_peers_without_sync():
    scoped = units(10, 10, 20)
    state = states(scoped)
    backend = Fake(completions={"A": ["CREATE_COMPLETE"], "B": ["CREATE_IN_PROGRESS"]})
    backend.sync_completed = Mock(side_effect=AssertionError("LLM owns sync"))
    sleep = Mock(side_effect=AssertionError("advance must return"))
    assert (
        scheduler.run_group(scoped, 2, state, backend, sleep=sleep, single_step=True)
        == "ACTIVE"
    )
    assert state["A"]["status"] == state["B"]["status"] == "RUNNING"
    assert (
        scheduler.run_group(scoped, 2, state, backend, sleep=sleep, single_step=True)
        == "ACTIVE"
    )
    assert state["A"]["status"] == "SUCCESS"
    assert state["B"]["status"] == "RUNNING"
    assert state["C"]["status"] == "NOT_STARTED"
    backend.sync_completed.assert_not_called()
    result = steps.describe(
        SimpleNamespace(run_context={"states": state}, states=state)
    )
    assert {"action": "sync", "stacks": ["A"]} in result["nextActions"]


def check_advance_retains_original_execute_after_interruption():
    scoped = units(10, 10)
    state = states(scoped)
    backend = Fake(
        completions={"A": ["CREATE_IN_PROGRESS"], "B": ["CREATE_IN_PROGRESS"]}
    )
    scheduler.run_group(scoped, 2, state, backend, single_step=True)
    tokens = {n: s["clientToken"] for n, s in state.items()}
    scheduler.run_group(scoped, 2, state, backend, single_step=True)
    assert {n: s["clientToken"] for n, s in state.items()} == tokens
    assert len([e for e in backend.events if e[0] == "start"]) == 2


def check_checkpoint_pending_is_unfinished_even_after_observed():
    assert not operation_journal.unfinished(
        {"status": "NOT_STARTED", "checkpointRequired": True}
    )
    assert operation_journal.unfinished(
        {"status": "SUCCESS", "observedSynced": True, "checkpointRequired": True}
    )
    assert not operation_journal.unfinished(
        {"status": "SUCCESS", "observedSynced": True}
    )
    states = {"A": {"status": "SUCCESS", "observedSynced": True, "checkpointed": True}}
    backend = SimpleNamespace(
        phase="deploy",
        task_status="completed",
        states=states,
        run_context={
            "states": states,
            "snapshotValidation": "PASS",
            "gitPublication": {"status": "CONFLICT"},
        },
    )
    report = steps.describe(backend)
    assert report["result"] == "PUBLICATION_PENDING"
    assert report["states"]["A"]["aws"] == "SUCCESS"
    assert report["gitPublication"]["status"] == "CONFLICT"


@pytest.mark.parametrize("status", ["NOT_STARTED", "READY"])
def check_intermediate_sync_does_not_finish_unattempted_deploy(status):
    saved = {"status": status, "observedSynced": True, "checkpointed": True}
    state = {"A": saved}
    backend = SimpleNamespace(
        states=state,
        run_context={"states": state, "snapshotValidation": "PASS"},
    )
    TestCase().assertNotEqual(steps.describe(backend)["result"], "COMPLETE")


def check_failed_attempt_cannot_finish_with_unstarted_stack():
    states = {
        name: {"status": status, "observedSynced": True, "checkpointed": True}
        for name, status in [("A", "SUCCESS"), ("B", "FAILED"), ("C", "NOT_STARTED")]
    }
    backend = SimpleNamespace(
        states=states,
        run_context={
            "states": states,
            "deployResult": "FAIL",
            "snapshotValidation": "PASS",
        },
    )
    TestCase().assertNotEqual(steps.describe(backend)["result"], "COMPLETE")


@pytest.mark.parametrize("status", ["PENDING", "CONFLICT", "SUCCESS"])
def check_git_next_actions_are_exposed_until_publication_succeeds(status):
    states = {"A": {"status": "SUCCESS", "observedSynced": True, "checkpointed": True}}
    action = (
        {
            "action": "deploy-publish",
            "command": ["python3", "worktree_task.py", "deploy-publish"],
        }
        if status == "PENDING"
        else {
            "action": "review-publication-conflict",
            "command": None,
            "humanApprovalRequired": True,
        }
    )
    actions = [] if status == "SUCCESS" else [action]
    backend = SimpleNamespace(
        phase="deploy",
        task_status="completed",
        states=states,
        run_context={
            "states": states,
            "snapshotValidation": "PASS",
            "gitPublication": {"status": status, "nextActions": actions},
        },
    )
    report = steps.describe(backend)
    assert report["result"] == (
        "COMPLETE" if status == "SUCCESS" else "PUBLICATION_PENDING"
    )
    assert report["nextActions"] == actions
    backend.run_context["checkpointPending"] = {"stacks": ["A"], "after": {}}
    pending_report = steps.describe(backend)
    assert pending_report["result"] != "COMPLETE"
    assert not any(
        a["action"] == "deploy-publish" for a in pending_report["nextActions"]
    )
    assert not pending_report["gitPublication"]["retryable"]
    assert not any(
        a["action"] == "deploy-publish"
        for a in pending_report["gitPublication"]["nextActions"]
    )
    backend.run_context.pop("checkpointPending")
    states["A"]["status"] = "FAILED"
    TestCase().assertEqual(steps.describe(backend)["deployResult"], "FAIL")


def check_unknown_poll_stops_without_resubmit():
    scoped = units(10)
    state = states(scoped)
    backend = Fake(completions={"A": ["UNRECOGNIZED"]})
    scheduler.run_group(scoped, 1, state, backend, single_step=True)
    token = state["A"]["clientToken"]
    TestCase().assertEqual(
        scheduler.run_group(scoped, 1, state, backend, single_step=True), "ACTIVE"
    )
    TestCase().assertEqual(
        scheduler.run_group(scoped, 1, state, backend, single_step=True), "ACTIVE"
    )
    TestCase().assertEqual(
        scheduler.run_group(scoped, 1, state, backend, single_step=True), "STOPPED"
    )
    result = steps.describe(
        SimpleNamespace(run_context={"states": state}, states=state)
    )
    TestCase().assertEqual(result["result"], "PENDING")
    TestCase().assertIn({"action": "advance"}, result["nextActions"])
    assert state["A"]["clientToken"] == token
    assert len([e for e in backend.events if e[0] == "start"]) == 1


def check_corrupt_journal_is_never_reset(tmp_path):
    journal = tmp_path / "journal.json"
    journal.write_text("broken", encoding="utf-8")
    journal.chmod(0o600)
    backend = SimpleNamespace(
        root=tmp_path, units=[{"name": "A"}], run_context={"inputDigests": {}}
    )
    with (
        patch.object(steps.worktree, "require", return_value=None),
        patch.object(steps.worktree, "progress_state", return_value={}),
        patch.object(steps.worktree, "read_progress", return_value=None),
        patch.object(
            operation_journal,
            "read",
            side_effect=AssertionError("ordinary restore must not read legacy history"),
        ),
    ):
        steps.restore(backend, journal, SimpleNamespace(name="tasks/deploy.md"))
    TestCase().assertEqual(journal.read_text(encoding="utf-8"), "broken")


def check_runtime_cleanup_returns_after_one_read():
    aws = Mock(
        return_value={
            "Stacks": [{"StackId": "original", "StackStatus": "DELETE_IN_PROGRESS"}]
        }
    )
    state = {"stackId": "original", "cleanupStatus": "DELETE_INTENT"}
    with patch.object(
        recovery.time, "sleep", side_effect=AssertionError("must return")
    ):
        with pytest.raises(recovery.RuntimePending):
            recovery.wait_cleanup(aws, Mock(), state, single_step=True)
    aws.assert_called_once_with("describe_stacks", StackName="original")
    assert state["cleanupStatus"] == "DELETE_INTENT"


def check_legacy_recovery_retains_unrelated_step_journal(tmp_path):
    target = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}
    record = {
        "target": target,
        "operations": {
            "A": {
                "unit": {"name": "A"},
                "inputDigest": None,
                "state": {"status": "NOT_STARTED", "checkpointRequired": True},
            }
        },
        "publication": {
            "repository": str(tmp_path),
            "taskFile": "tasks/other.md",
            "taskDigest": "other",
            "target": target,
            "environment": "dev",
            "directory": "app",
            "stepwise": True,
        },
    }
    journal = tmp_path / "journal.json"
    journal.parent.chmod(0o700)
    operation_journal.write_records(journal, [record])
    backend = SimpleNamespace(
        root=tmp_path,
        environment="dev",
        directory="app",
        target=target,
        aws=Mock(
            side_effect=AssertionError(
                "unrelated step must not be polled or synchronized"
            )
        ),
    )
    operation_journal.recover(
        backend,
        journal,
        SimpleNamespace(name="tasks/current.md", task_digest="current", text=""),
        ["B"],
    )
    assert backend.retained_records == [record]
    assert operation_journal.read(journal) == [record]


def check_step_diagnostics_do_not_expose_unknown_error_values():
    assert "private-value" not in str(
        cli_guidance.safe_error(ValueError("private-value"))
    )
    known = cli_guidance.safe_error(
        cli_guidance.DeployStepBlocked("base advanced; review retained commit")
    )
    assert known["code"] == "DEPLOY_STEP_BLOCKED"
    assert known["reason"] == "base advanced; review retained commit"


@pytest.mark.parametrize(
    "missing", [False, True, "unknown-literal", "missing-status", "wrong-type"]
)
@pytest.mark.parametrize("already_matches", [False, True])
def check_every_identifier_is_confirmed(tmp_path, missing, already_matches):
    source = tmp_path / "model/dev/app/ec2.properties"
    resource = {"resourceType": "EC2.VPC", "logicalId": "EC2_VPC_001"}
    rows = [("001-001", {"property": "EC2.VPC.VpcId", "value": "[self](#vpc)"})]
    mapped = {"A": {"Vpc": (source, "001", resource, rows, {"EC2.VPC.VpcId"})}}
    state = {
        "A": {"status": "SUCCESS", "stackId": "stack", "stackStatus": "CREATE_COMPLETE"}
    }
    backend = SimpleNamespace(
        run_context={},
        root=tmp_path,
        environment="dev",
        directory="app",
        target={"awsRegion": "region", "awsAccountId": "account"},
        templates={"A": ({"Resources": {"Vpc": {"Type": "AWS::EC2::VPC"}}}, {})},
        aws=Mock(
            side_effect=[
                {"Stacks": [{"StackId": "stack", "StackStatus": "CREATE_COMPLETE"}]},
                {
                    "StackResourceSummaries": [
                        {
                            "LogicalResourceId": "Vpc",
                            "ResourceType": "AWS::S3::Bucket"
                            if missing == "wrong-type"
                            else "AWS::EC2::VPC",
                            "ResourceStatus": None
                            if missing == "missing-status"
                            else "CREATE_COMPLETE",
                            **(
                                {}
                                if missing is True
                                else {
                                    "PhysicalResourceId": "UNKNOWN"
                                    if missing == "unknown-literal"
                                    else "vpc-actual"
                                }
                            ),
                        }
                    ]
                },
                {"Stacks": [{"StackId": "stack", "StackStatus": "CREATE_COMPLETE"}]},
            ]
        ),
    )
    loaded = {
        source: {
            "observed.row.001-001.value": "`vpc-actual`"
            if already_matches
            else "`PENDING_DEPLOY`"
        }
    }
    with (
        patch.object(observed, "DesignSchemaCatalog"),
        patch.object(observed, "resolve_resources", return_value=(loaded, mapped)),
        patch.object(observed, "identifier_source", return_value=(True, [])),
        patch.object(observed, "own_key", return_value="self"),
        patch.object(observed, "propagate_references"),
        patch.object(
            observed, "observed_destinations", return_value=({}, [], None)
        ) as destinations,
    ):
        backend.run_context = {}
        observed.sync_successful(backend, [{"name": "A"}], state)
        TestCase().assertTrue(state["A"]["observedSynced"])
        TestCase().assertEqual(state["A"]["stackStatus"], "CREATE_COMPLETE")
        if missing == "wrong-type":
            TestCase().assertEqual(
                state["A"]["currentStack"]["reason"], "RESOURCE_TYPE_UNCONFIRMED"
            )
        TestCase().assertNotIn("cloudformation-stacks", state["A"]["observedServices"])
        if missing:
            TestCase().assertIsNone(
                destinations.call_args.args[4][source]["observed.row.001-001.value"]
            )
        TestCase().assertEqual(
            state["A"]["observedCoverage"]["Vpc"]["status"],
            "UNCONFIRMED" if missing else "MATCHED" if already_matches else "UPDATED",
        )


def missing_changeset_aws(event, operation, **arguments):
    if operation == "describe_stacks":
        return {"Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}]}
    if operation == "describe_change_set":
        raise AwsError("cloudformation", operation, "ChangeSetNotFound")
    return {"StackEvents": [event]}


def save_test_state(case, request, progress, state):
    case.assertTrue(request.exists())
    worktree.write_sealed(progress.parent, progress, state)


class TestCurrentState(TestCase):
    def test_deploy_modules_import_first_in_fresh_processes(self):
        for module in (
            "scheduler",
            "current_request",
            "operation_journal",
            "controller",
        ):
            subprocess.run(
                [sys.executable, "-c", f"import deploy.{module}"],
                env={
                    **os.environ,
                    "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                },
                check=True,
                capture_output=True,
            )

    def test_confirmed_execution_without_root_event_is_saved_before_release(self):
        request = {
            "operation": "execute_change_set",
            "name": "A",
            "stackId": "stack",
            "changeSetId": "change",
            "token": "own",
            "settled": True,
            "result": "SETTLED",
            "attemptStatus": "UPDATE_COMPLETE",
        }
        state = {
            "status": "RUNNING",
            "clientToken": "own",
            "changeSetId": "change",
            "executionEvidence": {"StackId": "stack"},
            "attemptResult": "UNKNOWN",
        }
        backend = SimpleNamespace(
            states={"A": state},
            templates={},
            aws=Mock(
                side_effect=[
                    {
                        "Stacks": [
                            {"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}
                        ]
                    },
                    {"StackEvents": []},
                ]
            ),
        )
        backend.poll = lambda unit, snapshot: controller.poll(backend, unit, snapshot)
        saved = []
        with (
            patch.object(current_request, "reconcile", return_value=request),
            patch.object(current_request, "release") as release,
        ):
            scheduler.run_group(
                [{"name": "A", "deployOrder": 1}],
                1,
                backend.states,
                backend,
                save=lambda: saved.append(dict(state)),
                single_step=True,
            )
            self.assertEqual(saved[-1]["status"], "SUCCESS")
            self.assertNotIn("attemptResult", saved[-1])
            release.assert_called_once_with(backend, request)

    def test_restarting_clears_unexecuted_reason(self):
        scoped = units(10)
        state = states(scoped)
        state["A"]["unexecutedReason"] = "DEPLOY_ENDED_WITHOUT_EXECUTION"
        scheduler.run_group(scoped, 1, state, Fake(), single_step=True)
        self.assertNotIn("unexecutedReason", state["A"])
        state["A"]["unexecutedReason"] = "stale"
        current_state.record_attempt(state["A"], "UPDATE_COMPLETE")
        self.assertNotIn("unexecutedReason", state["A"])

    def test_change_set_completion_requires_matching_identities(self):
        record = {
            "operation": "execute_change_set",
            "name": "A",
            "stackId": "stack",
            "changeSetId": "change",
            "token": "own",
        }
        change = {
            "ChangeSetId": "change",
            "StackId": "stack",
            "ExecutionStatus": "EXECUTE_COMPLETE",
        }
        current = {"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}
        aws = Mock(side_effect=[change, {"StackEvents": []}])
        self.assertTrue(current_request.settled(aws, record, current))
        self.assertEqual(record["attemptStatus"], "UPDATE_COMPLETE")
        other_event = {
            "ResourceType": "AWS::CloudFormation::Stack",
            "StackId": "stack",
            "PhysicalResourceId": "stack",
            "ClientRequestToken": "other",
            "ResourceStatus": "UPDATE_COMPLETE",
        }
        self.assertFalse(
            current_request.settled(
                Mock(side_effect=[change, {"StackEvents": [other_event]}]),
                record.copy(),
                current,
            )
        )
        self.assertFalse(
            current_request.settled(Mock(), record, current | {"StackId": "other"})
        )
        for wrong in (change | {"ChangeSetId": "other"}, change | {"StackId": "other"}):
            with self.assertRaises(Blocked):
                current_request.settled(Mock(return_value=wrong), record, current)
        self.assertFalse(
            current_request.owns(
                {
                    "clientToken": "other",
                    "changeSetId": "change",
                    "executionEvidence": {"StackId": "stack"},
                },
                record,
            )
        )

    def test_explicit_completion_persists_unexecuted_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "progress.json"
            identity = {"stacks": ["A", "B"]}
            lifecycle = {
                "deployIdentity": identity,
                "tip": "checkpoint",
                "deployPublication": {
                    "status": "SUCCESS",
                    "publishedSource": "checkpoint",
                },
            }
            states = {
                "A": {
                    "status": "FAILED",
                    "observedSynced": True,
                    "currentStack": {"StackStatus": "UPDATE_ROLLBACK_COMPLETE"},
                },
                "B": {
                    "status": "NOT_STARTED",
                    "observedSynced": True,
                    "currentStack": {"StackStatus": "UPDATE_COMPLETE"},
                },
            }
            progress = {
                "identity": identity,
                "states": states,
                "stepUnits": [
                    {"name": "A", "deployOrder": 1},
                    {"name": "B", "deployOrder": 2},
                ],
                "pendingObserved": False,
                "pendingGeneration": False,
                "runContext": {
                    "snapshotValidation": "PASS",
                    "deployResult": "FAIL",
                    "states": states,
                },
            }
            task = SimpleNamespace(
                text="## Task contract\n- Task type: `infrastructure`\n- Infrastructure phase: `deploy`\n"
            )
            with (
                patch.object(worktree, "require", return_value=lifecycle),
                patch.object(worktree, "progress_path", return_value=path),
                patch.object(
                    worktree, "prepare_complete", side_effect=prepare_complete
                ),
            ):
                worktree.write_sealed(root, path, progress)
                worktree.prepare_complete(root, task)
                saved = worktree.read_progress(root, lifecycle)
                self.assertEqual(
                    saved["states"]["B"]["unexecutedReason"],
                    "PREVIOUS_DEPLOY_ORDER_FAILED",
                )
                self.assertEqual(saved["runContext"]["deployResult"], "FAIL")
                worktree.prepare_complete(root, task)
                self.assertEqual(worktree.read_progress(root, lifecycle), saved)
                with patch.object(
                    worktree, "require_complete", side_effect=Blocked("validation")
                ):
                    with self.assertRaises(Blocked):
                        worktree.prepare_complete(root, task)
                resumed = worktree.read_progress(root, lifecycle)["states"]
                scheduler.run_group(
                    [{"name": "B", "deployOrder": 2}],
                    1,
                    resumed,
                    Fake(),
                    single_step=True,
                )
                self.assertNotIn("unexecutedReason", resumed["B"])

    def test_settled_execution_is_not_sent_again_before_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            record = {
                "name": "A",
                "operation": "execute_change_set",
                "stackId": "stack",
                "changeSetId": "change",
                "token": "own",
            }
            path.write_text(json.dumps(record), encoding="utf-8")
            path.chmod(0o600)
            transport = Mock()
            runtime = SimpleNamespace(target={}, aws=Mock())
            with (
                patch.object(current_request, "location", return_value=path),
                patch.object(
                    current_state,
                    "read",
                    return_value={"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"},
                ),
                patch.object(current_request, "settled", return_value=True),
            ):
                with self.assertRaises(Blocked):
                    current_request.send(
                        runtime,
                        "execute_change_set",
                        {"StackName": "A", "ChangeSetName": "change"},
                        transport,
                    )
            transport.assert_not_called()
            self.assertTrue(path.exists())

    def test_missing_changeset_poll_saves_before_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "request.json"
            record = {
                "name": "A",
                "operation": "execute_change_set",
                "stackId": "stack",
                "changeSetId": "change",
                "token": "original",
            }
            path.write_text(json.dumps(record), encoding="utf-8")
            path.chmod(0o600)
            event = {
                "StackId": "stack",
                "PhysicalResourceId": "stack",
                "ResourceType": "AWS::CloudFormation::Stack",
                "ClientRequestToken": "original",
                "ResourceStatus": "UPDATE_COMPLETE",
            }
            state = {
                "status": "RUNNING",
                "clientToken": "original",
                "changeSetId": "change",
                "executionEvidence": {"StackId": "stack"},
            }
            backend = SimpleNamespace(
                target={},
                states={"A": state},
                units=[{"name": "A"}],
                aws=partial(missing_changeset_aws, event),
                templates={},
            )
            backend.poll = partial(controller.poll, backend)
            progress = path.parent / "progress.json"
            backend.save = Mock(
                side_effect=partial(save_test_state, self, path, progress, state)
            )
            with patch.object(current_request, "location", return_value=path):
                worker_state = dict(state)
                self.assertEqual(
                    controller.poll(backend, {"name": "A"}, worker_state),
                    "UPDATE_COMPLETE",
                )
                self.assertEqual(json.loads(path.read_text()), record)
                steps.refresh_requests(backend)
            self.assertEqual(state["status"], "SUCCESS")
            self.assertEqual(
                worktree.read_sealed(path.parent, progress)["status"], "SUCCESS"
            )
            self.assertFalse(path.exists())
            backend.save.assert_called_once()

    def test_release_preserves_newer_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "request.json"
            old = {
                "name": "A",
                "operation": "execute_change_set",
                "stackId": "stack",
                "changeSetId": "old",
                "token": "old",
            }
            new = old | {"changeSetId": "new", "token": "new"}
            path.write_text(json.dumps(new), encoding="utf-8")
            path.chmod(0o600)
            with patch.object(current_request, "location", return_value=path):
                current_request.release(SimpleNamespace(target={}), old)
            self.assertEqual(json.loads(path.read_text()), new)

    def test_request_ownership_checks_original_stack(self):
        record = {
            "operation": "execute_change_set",
            "token": "token",
            "changeSetId": "change",
            "stackId": "stack",
        }
        state = {
            "clientToken": "token",
            "changeSetId": "change",
            "executionEvidence": {"StackId": "other"},
        }
        self.assertFalse(current_request.owns(state, record))
        state["executionEvidence"]["StackId"] = "stack"
        self.assertTrue(current_request.owns(state, record))
        self.assertTrue(current_request.owns(state, record | {"stackId": None}))
        state["executionEvidence"] = {}
        self.assertFalse(current_request.owns(state, record | {"stackId": None}))

    def test_released_request_recovers_from_saved_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "request.json"
            event = {
                "StackId": "stack",
                "PhysicalResourceId": "stack",
                "ResourceType": "AWS::CloudFormation::Stack",
                "ClientRequestToken": "original",
                "ResourceStatus": "UPDATE_COMPLETE",
            }
            state = {
                "status": "RUNNING",
                "clientToken": "original",
                "changeSetId": "deleted",
                "executionEvidence": {"StackId": "stack"},
            }
            aws = Mock(side_effect=partial(missing_changeset_aws, event))
            backend = SimpleNamespace(
                target={},
                states={"A": state},
                units=[{"name": "A"}],
                aws=aws,
                templates={},
                save=Mock(),
            )
            backend.poll = partial(controller.poll, backend)
            with patch.object(current_request, "location", return_value=path):
                steps.refresh_requests(backend)
            self.assertEqual(state["status"], "SUCCESS")
            backend.save.assert_called_once()
            self.assertNotIn(
                "describe_change_set", [call.args[0] for call in aws.call_args_list]
            )

    def test_interruption_before_save_or_release_recovers(self):
        for boundary in ("save", "release"):
            with (
                self.subTest(boundary=boundary),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory).resolve()
                path, progress = root / "request.json", root / "progress.json"
                record = {
                    "name": "A",
                    "operation": "execute_change_set",
                    "stackId": "stack",
                    "changeSetId": "change",
                    "token": "original",
                }
                path.write_text(json.dumps(record), encoding="utf-8")
                path.chmod(0o600)
                event = {
                    "StackId": "stack",
                    "PhysicalResourceId": "stack",
                    "ResourceType": "AWS::CloudFormation::Stack",
                    "ClientRequestToken": "original",
                    "ResourceStatus": "UPDATE_COMPLETE",
                }
                original = {
                    "status": "RUNNING",
                    "clientToken": "original",
                    "changeSetId": "change",
                    "executionEvidence": {"StackId": "stack"},
                }
                state = dict(original)
                aws = Mock(side_effect=partial(missing_changeset_aws, event))
                backend = SimpleNamespace(
                    target={},
                    states={"A": state},
                    units=[{"name": "A"}],
                    aws=aws,
                    templates={},
                )
                backend.poll = partial(controller.poll, backend)
                backend.save = Mock(
                    side_effect=OSError("interrupted")
                    if boundary == "save"
                    else partial(worktree.write_sealed, root, progress, state)
                )
                release = current_request.release
                with (
                    patch.object(current_request, "location", return_value=path),
                    patch.object(
                        current_request,
                        "release",
                        side_effect=OSError("interrupted")
                        if boundary == "release"
                        else None,
                        wraps=release,
                    ),
                ):
                    with self.assertRaises(OSError):
                        steps.refresh_requests(backend)
                    self.assertTrue(path.exists())
                state = (
                    worktree.read_sealed(root, progress)
                    if progress.exists()
                    else dict(original)
                )
                backend.states = {"A": state}
                backend.save = Mock(
                    side_effect=partial(worktree.write_sealed, root, progress, state)
                )
                with patch.object(current_request, "location", return_value=path):
                    steps.refresh_requests(backend)
                self.assertEqual(state["status"], "SUCCESS")
                self.assertFalse(path.exists())
                self.assertNotIn(
                    "execute_change_set", [call.args[0] for call in aws.call_args_list]
                )

    def test_unknown_attempt_does_not_restart(self):
        scoped = [{"name": "A", "deployOrder": 10}]
        state = {"A": {"status": "BLOCKED", "attemptResult": "UNKNOWN"}}
        backend = Fake()
        backend.prepare = Mock()
        backend.execute = Mock()
        scheduler.run_group(scoped, 1, state, backend, single_step=True)
        steps.retry_terminal_attempts(
            SimpleNamespace(states=state, units=scoped), {"A"}
        )
        self.assertEqual(state["A"]["attemptResult"], "UNKNOWN")
        backend.prepare.assert_not_called()
        backend.execute.assert_not_called()

    def test_request_read_failure_does_not_stop_other_stack(self):
        states = {"A": {"status": "RUNNING"}, "B": {"status": "SUCCESS"}}
        backend = SimpleNamespace(
            units=[{"name": "A"}, {"name": "B"}],
            states=states,
            aws=Mock(
                return_value={
                    "Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}]
                }
            ),
        )
        with patch.object(
            current_request, "reconcile", side_effect=[Blocked("busy"), None]
        ):
            steps.refresh_requests(backend)
        self.assertTrue(states["A"]["requestPending"])
        self.assertEqual(states["A"]["requestError"], "busy")
        self.assertEqual(states["B"]["status"], "SUCCESS")
        self.assertEqual(states["B"]["currentStack"]["StackStatus"], "UPDATE_COMPLETE")

    def test_next_order_requires_aws_success_without_observed_or_git(self):
        scoped = units(10, 20)
        state = states(scoped)
        state["A"].update(status="SUCCESS", observedSynced=False)
        backend = Fake()
        scheduler.run_group(scoped, 1, state, backend, single_step=True)
        self.assertEqual(state["B"]["status"], "RUNNING")

    def test_short_advances_do_not_starve_independent_peers(self):
        scoped = units(10, 10, 20)
        state = states(scoped)
        backend = Fake(blocked={"A"})
        scheduler.run_group(scoped, 1, state, backend, single_step=True)
        scheduler.run_group(scoped, 1, state, backend, single_step=True)
        self.assertEqual(state["B"]["status"], "RUNNING")
        self.assertEqual(state["C"]["status"], "NOT_STARTED")
        state["A"].update(status="FAILED")
        state["B"].update(status="NOT_STARTED")
        steps.retry_terminal_attempts(
            SimpleNamespace(states=state, units=scoped, run_context={}), {"A"}
        )
        self.assertEqual(state["A"]["status"], "FAILED")

    def test_old_scheduler_diagnostic_does_not_stop_current_scope(self):
        scoped = units(10)
        state = states(scoped)
        state["A"]["schedulerError"] = "past concurrency mode"
        scheduler.run_group(scoped, 1, state, Fake(), single_step=True)
        self.assertEqual(state["A"]["status"], "RUNNING")
        self.assertNotIn("schedulerError", state["A"])

    def test_read_failure_and_rollback_tracking_keep_distinct_attempt_results(self):
        state = {"status": "RUNNING", "pollReadFailures": 3}
        backend = SimpleNamespace(
            states={"A": state}, run_context={"states": {"A": state}}
        )
        self.assertEqual(steps.describe(backend)["deployResult"], "UNKNOWN")
        state["failureDetected"] = True
        self.assertEqual(steps.describe(backend)["deployResult"], "FAIL")

    def test_external_change_review_survives_intermediate_observation(self):
        state = {
            "status": "SUCCESS",
            "currentStack": {"StackId": "old", "StackStatus": "CREATE_COMPLETE"},
        }
        backend = SimpleNamespace(
            states={"A": state},
            run_context={},
            aws=Mock(
                return_value={
                    "Stacks": [{"StackId": "current", "StackStatus": "UPDATE_COMPLETE"}]
                }
            ),
        )
        current_state.refresh(backend, [{"name": "A"}])
        current_state.refresh(backend, [{"name": "A"}])
        self.assertEqual(state["status"], "SUCCESS")
        self.assertTrue(state["needsCurrentReview"])
        steps.retry_terminal_attempts(backend, {"A"})
        self.assertEqual(state["status"], "NOT_STARTED")

    def test_mid_failure_with_stale_stack_read_cannot_retire_request(self):
        stack = {"StackId": "root", "StackStatus": "UPDATE_COMPLETE"}
        record = {
            "operation": "execute_change_set",
            "name": "A",
            "stackId": "root",
            "changeSetId": "change",
            "token": "original",
            "before": current_state.identity(stack),
        }
        aws = Mock(
            side_effect=[
                {
                    "ChangeSetId": "change",
                    "StackId": "root",
                    "Status": "CREATE_COMPLETE",
                    "ExecutionStatus": "EXECUTE_COMPLETE",
                },
                {
                    "StackEvents": [
                        {
                            "StackId": "root",
                            "PhysicalResourceId": "root",
                            "ResourceType": "AWS::CloudFormation::Stack",
                            "ClientRequestToken": "original",
                            "ResourceStatus": "UPDATE_FAILED",
                        }
                    ]
                },
            ]
        )
        self.assertFalse(current_request.settled(aws, record, stack))

    def test_status_classes_are_distinct(self):
        cases = {
            "CREATE_COMPLETE": "SUCCESS",
            "UPDATE_COMPLETE": "SUCCESS",
            "IMPORT_COMPLETE": "SUCCESS",
            "UPDATE_ROLLBACK_COMPLETE": "ROLLED_BACK",
            "UPDATE_ROLLBACK_FAILED": "FAILED",
            "ROLLBACK_COMPLETE": "FAILED",
            "UPDATE_IN_PROGRESS": "RUNNING",
            "REVIEW_IN_PROGRESS": "REVIEW",
            "ABSENT": "ABSENT",
            "UNKNOWN": "UNKNOWN",
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                self.assertEqual(current_state.classify(status), expected)
        self.assertEqual(
            current_state.classify(
                "REVIEW_IN_PROGRESS", [{"ExecutionStatus": "EXECUTE_IN_PROGRESS"}]
            ),
            "RUNNING",
        )

    def test_api_errors_are_never_absence(self):
        for code, absent in [
            ("ValidationError", True),
            ("AccessDenied", False),
            ("RequestTimeout", False),
        ]:
            with self.subTest(code=code):
                aws = Mock(
                    side_effect=AwsError(
                        "cloudformation", "describe_stacks", code, stack_absent=absent
                    )
                )
                self.assertEqual(
                    current_state.read(aws, "Example")["StackStatus"],
                    "ABSENT" if absent else "UNKNOWN",
                )
        self.assertEqual(
            current_state.read(Mock(return_value={"Stacks": []}), "Example")[
                "StackStatus"
            ],
            "UNKNOWN",
        )

    def test_old_state_and_failure_history_do_not_control_refresh(self):
        states = {
            "A": {
                "status": "NOT_STARTED",
                "stackStatus": "CREATE_COMPLETE",
                "expectedOutputs": {"old": "obsolete"},
            }
        }
        backend = SimpleNamespace(
            states=states,
            aws=Mock(
                return_value={
                    "Stacks": [{"StackId": "current", "StackStatus": "UPDATE_COMPLETE"}]
                }
            ),
        )
        current_state.refresh(backend, [{"name": "A"}])
        self.assertEqual(states["A"]["stackStatus"], "UPDATE_COMPLETE")
        self.assertEqual(states["A"]["status"], "NOT_STARTED")

    def test_malformed_reads_are_unknown_and_not_absence(self):
        for response in [
            None,
            {"Stacks": None},
            {"Stacks": [None]},
            {
                "Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}],
                "NextToken": "unfinished",
            },
        ]:
            with self.subTest(response=response):
                self.assertEqual(
                    current_state.read(Mock(return_value=response), "A")["StackStatus"],
                    "UNKNOWN",
                )
        with self.assertRaises(ValueError):
            validate_model_keys({"observed.stack.001.status": "UNKNOWN"})
        with self.assertRaises(Blocked):
            current_state.pages(
                Mock(return_value={"StackEvents": [None]}),
                "describe_stack_events",
                "StackEvents",
                StackName="A",
            )

    def test_foreign_settled_failure_is_not_this_attempts_failure(self):
        record = {
            "operation": "execute_change_set",
            "name": "A",
            "stackId": "stack",
            "token": "submitted",
            "changeSetId": "change",
            "result": "FAIL",
        }
        for own in [False, True]:
            state = {
                "status": "NOT_STARTED",
                "currentStack": {"StackStatus": "UPDATE_COMPLETE"},
            }
            if own:
                state.update(
                    clientToken="submitted",
                    changeSetId="change",
                    executionEvidence={"StackId": "stack"},
                )
            backend = SimpleNamespace(target={}, states={"A": state}, aws=Mock())
            with (
                self.subTest(own=own),
                patch.object(current_request, "location", return_value=Mock()),
                patch.object(operation_journal, "locked", return_value=nullcontext()),
                patch.object(current_request, "read", return_value=record),
                patch.object(current_request, "settled", return_value=True),
            ):
                found = current_request.reconcile(backend, {"name": "A"})
                self.assertTrue(found["settled"])
                self.assertEqual(current_request.owns(state, found), own)
                self.assertFalse(state.get("failureDetected", False))

    def test_nested_stack_event_does_not_settle_the_root_request(self):
        record = {
            "operation": "continue_update_rollback",
            "name": "A",
            "stackId": "root",
            "token": "submitted",
        }
        event = {
            "StackId": "root",
            "PhysicalResourceId": "child",
            "ResourceType": "AWS::CloudFormation::Stack",
            "ClientRequestToken": "submitted",
            "ResourceStatus": "UPDATE_COMPLETE",
        }
        aws = Mock(return_value={"StackEvents": [event]})
        current = {"StackId": "root", "StackStatus": "UPDATE_COMPLETE"}
        self.assertFalse(current_request.settled(aws, record, current))
        event["PhysicalResourceId"] = "root"
        self.assertTrue(current_request.settled(aws, record, current))
        event.pop("ResourceStatus")
        self.assertFalse(current_request.settled(aws, record, current))

    def test_pending_secret_request_preserves_bootstrap_resume(self):
        states = {
            "Owner": {"status": "SUCCESS"},
            "Consumer": {"status": "FAILED", "bootstrap": {"stage": "PUT_SUBMITTED"}},
        }
        backend = SimpleNamespace(
            units=[{"name": "Owner"}, {"name": "Consumer"}],
            states=states,
            aws=Mock(
                side_effect=[
                    {
                        "Stacks": [
                            {"StackId": "owner", "StackStatus": "CREATE_COMPLETE"}
                        ]
                    },
                    {
                        "Stacks": [
                            {"StackId": "consumer", "StackStatus": "ROLLBACK_COMPLETE"}
                        ]
                    },
                ]
            ),
            run_context={"deployResult": "FAIL"},
        )
        with patch.object(
            current_request,
            "reconcile",
            side_effect=[
                {"service": "secretsmanager", "operation": "put_secret_value"},
                None,
            ],
        ):
            steps.refresh_requests(backend)
        steps.retry_terminal_attempts(backend, {"Consumer"})
        self.assertEqual(states["Owner"]["status"], "SUCCESS")
        self.assertEqual(states["Consumer"]["status"], "FAILED")
        self.assertEqual(states["Consumer"]["bootstrap"]["stage"], "PUT_SUBMITTED")

    def test_all_pages_and_incomplete_listing(self):
        aws = Mock(
            side_effect=[
                {
                    "StackResourceSummaries": [{"LogicalResourceId": "One"}],
                    "NextToken": "next",
                },
                {"StackResourceSummaries": [{"LogicalResourceId": "Two"}]},
            ]
        )
        self.assertEqual(
            len(
                current_state.pages(
                    aws,
                    "list_stack_resources",
                    "StackResourceSummaries",
                    StackName="Example",
                )
            ),
            2,
        )
        aws = Mock(
            side_effect=[
                {"StackResourceSummaries": [{}], "NextToken": "next"},
                AwsError("cloudformation", "list_stack_resources", "AccessDenied"),
            ]
        )
        with self.assertRaises(AwsError):
            current_state.pages(
                aws,
                "list_stack_resources",
                "StackResourceSummaries",
                StackName="Example",
            )

    def test_old_complete_does_not_settle_lost_execute(self):
        record = {
            "operation": "execute_change_set",
            "name": "Example",
            "changeSetId": "change",
            "stackId": "stack",
            "token": "original",
        }
        aws = Mock(
            side_effect=[
                {
                    "ExecutionStatus": "AVAILABLE",
                    "ChangeSetId": "change",
                    "StackId": "stack",
                },
                {"StackEvents": []},
            ]
        )
        self.assertFalse(
            current_request.settled(
                aws, record, {"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}
            )
        )
        aws = Mock(
            return_value={
                "ExecutionStatus": "EXECUTE_COMPLETE",
                "ChangeSetId": "change",
                "StackId": "stack",
            }
        )
        self.assertTrue(
            current_request.settled(
                aws,
                record,
                {"StackId": "stack", "StackStatus": "UPDATE_ROLLBACK_COMPLETE"},
            )
        )

    def test_missing_change_set_requires_terminal_original_root_event(self):
        record = {
            "operation": "execute_change_set",
            "name": "Example",
            "changeSetId": "change",
            "stackId": "stack",
            "token": "original",
        }
        event = {
            "StackId": "stack",
            "PhysicalResourceId": "stack",
            "ResourceType": "AWS::CloudFormation::Stack",
            "ClientRequestToken": "original",
            "ResourceStatus": "UPDATE_COMPLETE",
        }
        current = {"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}
        for events, expected in [([], False), ([event], True)]:
            aws = Mock(
                side_effect=[
                    AwsError(
                        "cloudformation", "describe_change_set", "ChangeSetNotFound"
                    ),
                    {"StackEvents": events},
                ]
            )
            self.assertEqual(current_request.settled(aws, record, current), expected)

    def test_attempt_events_do_not_replace_current_stack_observation(self):
        for current, event_status, expected in [
            ("UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "FAILED"),
            ("UPDATE_ROLLBACK_COMPLETE", "CREATE_COMPLETE", "SUCCESS"),
            ("UNKNOWN", "CREATE_COMPLETE", "SUCCESS"),
        ]:
            with self.subTest(current=current, event=event_status):
                state = {
                    "status": "RUNNING",
                    "clientToken": "own",
                    "executionEvidence": {"StackId": "original"},
                }
                event = {
                    "StackId": "original",
                    "PhysicalResourceId": "original",
                    "ResourceType": "AWS::CloudFormation::Stack",
                    "ClientRequestToken": "own",
                    "ResourceStatus": event_status,
                }
                aws = Mock(
                    side_effect=[
                        {"Stacks": [{"StackId": "current", "StackStatus": current}]},
                        {"StackEvents": [event]},
                    ]
                )
                backend = SimpleNamespace(aws=aws, templates={})
                with patch.object(current_request, "reconcile", return_value=None):
                    result = controller.poll(backend, {"name": "A"}, state)
                current_state.record_attempt(state, result)
                self.assertEqual(state["status"], expected)
                self.assertEqual(state["stackStatus"], current)
                self.assertEqual(aws.call_args.kwargs["StackName"], "original")
        state = {"currentStack": {"StackStatus": "UPDATE_COMPLETE"}}
        current_state.record_attempt(state, "UNCONFIRMED")
        self.assertEqual(state["status"], "BLOCKED")
        self.assertEqual(state["attemptResult"], "UNKNOWN")
        failed = {"failureDetected": True}
        current_state.record_attempt(failed, "UNCONFIRMED")
        self.assertEqual(failed["status"], "FAILED")

    def test_unknown_identifier_does_not_render_an_old_id(self):
        row = {
            "property": "EC2.VPC.VpcId",
            "value": "[vpc-old](ec2.md#resource-EC2_VPC_001)",
        }
        rendered = observed_value("001-001", row, None, {row["property"]})
        self.assertNotIn("vpc-old", rendered)
        self.assertIn("UNOBSERVED", rendered)

    def test_stack_observations_are_rejected(self):
        before = "# model-format: 2\ndesired.stack.001.name=Example\ndesired.stack.001.template=example.yaml\ndesired.stack.001.parameters=example.json\ndesired.stack.001.deployOrder=10\n"
        after = before + "observed.stack.001.status=UPDATE_ROLLBACK_COMPLETE\n"
        with self.assertRaises(ValueError):
            verify_observed_outputs(
                {Path("stacks"): before.encode()}, {Path("stacks"): after}
            )
        with self.assertRaises(ValueError):
            validate_model_keys(properties(after))
        stack_model(properties(before))

    def test_external_request_completion_requires_fresh_desired_changeset(self):
        backend = SimpleNamespace(
            units=[{"name": "A"}],
            states={"A": {"status": "NOT_STARTED"}},
            target={},
            aws=Mock(
                return_value={
                    "Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}]
                }
            ),
        )
        pending = {
            "operation": "execute_change_set",
            "changeSetId": "foreign",
            "token": "foreign-token",
        }
        with patch.object(current_request, "reconcile", side_effect=[pending, None]):
            steps.refresh_requests(backend)
            self.assertTrue(backend.states["A"]["externalOperation"])
            steps.refresh_requests(backend)
        self.assertEqual(backend.states["A"]["status"], "NOT_STARTED")
        self.assertNotIn("clientToken", backend.states["A"])

    def test_update_refreshes_only_unclaimed_input_identities(self):
        unit = {"name": "A"}
        saved = {
            "taskDigest": "task",
            "target": {},
            "stepUnits": [unit],
            "states": {"A": {"status": "NOT_STARTED"}},
            "inputDigests": {},
            "consumedInputs": {},
            "inputIdentities": {"unclaimed": [1]},
        }
        for phase, expected in [("deploy", [1]), ("update", [2])]:
            with (
                self.subTest(phase=phase),
                patch.object(
                    steps.worktree, "require", return_value={"deployIdentity": {}}
                ),
                patch.object(
                    steps.worktree, "read_progress", return_value={"runContext": saved}
                ),
            ):
                backend = SimpleNamespace(
                    root=Path("/synthetic"),
                    units=[unit],
                    target={},
                    phase=phase,
                    run_context={"inputIdentities": {"unclaimed": [2]}},
                )
                steps.restore(
                    backend,
                    Path("/unused-journal"),
                    SimpleNamespace(task_digest="task"),
                )
                self.assertEqual(
                    backend.run_context["inputIdentities"]["unclaimed"], expected
                )

    def test_local_publication_guard_does_not_require_old_execution_inputs(self):
        task = SimpleNamespace(status="running", task_digest="current")
        target = {"awsAccountId": "123456789012", "awsRegion": "region"}
        backend = SimpleNamespace(
            root=Path("/synthetic"),
            environment="dev",
            target=target,
            run_context={"consumedInputs": {"infra/old.yaml": "old-digest"}},
            file_digest=Mock(
                side_effect=AssertionError("local save must not prove old AWS inputs")
            ),
            input_digest=Mock(
                side_effect=AssertionError(
                    "local save must not prove old runtime inputs"
                )
            ),
        )
        with (
            patch.object(steps, "task_snapshot", return_value=task),
            patch.object(steps.worktree, "require"),
            patch.object(steps.context, "load_target", return_value=target),
        ):
            self.assertIs(steps.guard_local_publication(backend, task), task)
        backend.file_digest.assert_not_called()
        backend.input_digest.assert_not_called()

    def test_external_secret_repair_settles_initial_stage_without_overwrite(self):
        record = {
            "service": "secretsmanager",
            "operation": "update_secret_version_stage",
            "resourceId": "secret",
            "token": "original",
        }
        metadata = {
            "VersionIdsToStages": {"original": ["PRIVATE"], "external": ["AWSCURRENT"]}
        }
        self.assertTrue(
            current_request.settled(
                Mock(return_value=metadata), record, {"StackStatus": "UPDATE_COMPLETE"}
            )
        )
        transport = Mock()
        with self.assertRaises(Blocked):
            current_request.send(
                SimpleNamespace(),
                "update_secret_version_stage",
                {
                    "MoveToVersionId": "original",
                    "RemoveFromVersionId": "external",
                    "VersionStage": "AWSCURRENT",
                },
                transport,
                service="secretsmanager",
                stack_name="Owner",
            )
        transport.assert_not_called()

    def test_new_advance_uses_external_repair_without_inheriting_failure(self):
        state = {
            "status": "FAILED",
            "failureDetected": True,
            "clientToken": "past",
            "currentStack": {"StackId": "current", "StackStatus": "UPDATE_COMPLETE"},
            "stackStatus": "UPDATE_COMPLETE",
            "requestPending": False,
        }
        backend = SimpleNamespace(
            states={"A": state}, run_context={"deployResult": "FAIL"}
        )
        steps.retry_terminal_attempts(backend, {"A"})
        self.assertEqual(state["status"], "NOT_STARTED")
        self.assertNotIn("failureDetected", state)
        self.assertNotIn("deployResult", backend.run_context)
        state.update(status="FAILED", requestPending=True)
        steps.retry_terminal_attempts(backend, {"A"})
        self.assertEqual(state["status"], "FAILED")

    def test_generation_is_independent_of_deploy_result(self):
        states = {
            "A": {"status": "FAILED", "observedSynced": True, "checkpointed": True}
        }
        backend = SimpleNamespace(
            states=states,
            task_status="completed",
            run_context={
                "states": states,
                "deployResult": "FAIL",
                "snapshotValidation": "PASS",
            },
        )
        result = steps.describe(backend)
        self.assertEqual(result["result"], "COMPLETE")
        self.assertEqual(result["deployResult"], "FAIL")
        backend.run_context["generationError"] = "broken reference"
        self.assertNotEqual(steps.describe(backend)["result"], "COMPLETE")


if __name__ == "__main__":
    raise SystemExit(run(__file__))
