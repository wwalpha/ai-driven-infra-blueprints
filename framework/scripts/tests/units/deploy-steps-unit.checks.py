"""Short-operation decisions and complete identifier coverage, without AWS or worktrees."""

import base64
import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from functools import partial, partialmethod
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
from deploy import (
    git_publication as publication,
)
from model.core import properties, stack_model, validate_model_keys
from model.observed import verify_observed_outputs
from model.projection import observed_value
from support.cloudformation_deploy_fixtures import Fake, advance_group, states, units
from support.pytest_cli import run
from utils import sealed_evidence
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def recovery_test_aws(operation, *, current, execution, **kwargs):
    if operation == "describe_stacks":
        return {"Stacks": [{"StackId": "stack", "StackStatus": current}]}
    if operation == "describe_change_set":
        return {
            "ChangeSetId": "change",
            "StackId": "stack",
            "ExecutionStatus": execution,
        }
    if operation == "describe_stack_events":
        return {"StackEvents": []}
    raise AssertionError(operation)


def later_event_test_aws(operation, **kwargs):
    if operation == "describe_stacks":
        return {
            "Stacks": [
                {
                    "StackId": "stack",
                    "StackStatus": "UPDATE_ROLLBACK_COMPLETE",
                }
            ]
        }
    if operation == "describe_change_set":
        return {
            "ChangeSetId": "change",
            "StackId": "stack",
            "ExecutionStatus": "EXECUTE_COMPLETE",
        }
    if operation == "describe_stack_events":
        return {
            "StackEvents": [
                {
                    "StackId": "stack",
                    "PhysicalResourceId": "stack",
                    "ResourceType": "AWS::CloudFormation::Stack",
                    "ClientRequestToken": "later",
                    "ResourceStatus": "UPDATE_ROLLBACK_COMPLETE",
                }
            ]
        }
    raise AssertionError(operation)


def wrong_owner(path, *, original_lstat, directory):
    info = original_lstat(path)
    if path == directory:
        return SimpleNamespace(st_mode=info.st_mode, st_uid=-1)
    return info


def set_test_coverage(status, _backend, _units, checked):
    checked["A"]["observedCoverage"] = {"Resource": {"status": status}}


def save_test_snapshot(saved, state, path):
    saved.append((dict(state), path.exists()))


def candidate_test_git(root, *args):
    if args[0] == "clone":
        Path(args[-1]).mkdir()


prepare_complete = worktree.prepare_complete


def check_advance_returns_with_running_peers_without_sync():
    scoped = units(10, 10, 20)
    state = states(scoped)
    backend = Fake(completions={"A": ["CREATE_COMPLETE"], "B": ["CREATE_IN_PROGRESS"]})
    assert scheduler.run_group(scoped, 2, state, backend) == "ACTIVE"
    assert state["A"]["status"] == state["B"]["status"] == "RUNNING"
    assert scheduler.run_group(scoped, 2, state, backend) == "ACTIVE"
    assert state["A"]["status"] == "SUCCESS"
    assert state["B"]["status"] == "RUNNING"
    assert state["C"]["status"] == "NOT_STARTED"
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
    scheduler.run_group(scoped, 2, state, backend)
    tokens = {n: s["clientToken"] for n, s in state.items()}
    scheduler.run_group(scoped, 2, state, backend)
    assert {n: s["clientToken"] for n, s in state.items()} == tokens
    assert len([e for e in backend.events if e[0] == "start"]) == 2


def check_checkpoint_pending_is_unfinished_even_after_observed(monkeypatch):
    monkeypatch.setattr(publication, "display", lambda backend: {"status": "CONFLICT"})
    states = {"A": {"status": "SUCCESS", "observedSynced": True, "checkpointed": True}}
    backend = SimpleNamespace(
        phase="deploy",
        task_status="completed",
        states=states,
        run_context={
            "states": states,
            "snapshotValidation": "PASS",
            "taskFile": "tasks/deploy.md",
            "gitPublication": {"status": "CONFLICT"},
        },
    )
    report = steps.describe(backend)
    assert report["result"] == "PUBLICATION_PENDING"
    assert report["states"]["A"]["attempt"] == "SUCCESS"
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
    state["B"] = {
        "status": "SETTLED",
        "attemptResult": "UNKNOWN",
        "observedSynced": True,
    }
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
def check_git_next_actions_are_exposed_until_publication_succeeds(status, monkeypatch):
    monkeypatch.setattr(
        publication,
        "display",
        lambda backend: copy.deepcopy(backend.run_context["gitPublication"]),
    )
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
            "taskFile": "tasks/deploy.md",
            "gitPublication": {"status": status, "nextActions": actions},
        },
    )
    report = steps.describe(backend)
    assert report["result"] == (
        "COMPLETE" if status == "SUCCESS" else "PUBLICATION_PENDING"
    )
    assert report["nextActions"] == (
        [{"action": "finalize", "taskId": "deploy"}] if status == "SUCCESS" else actions
    )
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
    scheduler.run_group(scoped, 1, state, backend)
    token = state["A"]["clientToken"]
    TestCase().assertEqual(scheduler.run_group(scoped, 1, state, backend), "ACTIVE")
    TestCase().assertEqual(scheduler.run_group(scoped, 1, state, backend), "ACTIVE")
    TestCase().assertEqual(scheduler.run_group(scoped, 1, state, backend), "STOPPED")
    result = steps.describe(
        SimpleNamespace(run_context={"states": state}, states=state)
    )
    TestCase().assertEqual(result["result"], "PENDING")
    TestCase().assertIn({"action": "advance"}, result["nextActions"])
    assert state["A"]["clientToken"] == token
    assert len([e for e in backend.events if e[0] == "start"]) == 1


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


def check_step_diagnostics_do_not_expose_unknown_error_values():
    assert "private-value" not in str(
        cli_guidance.safe_error(ValueError("private-value"))
    )
    known = cli_guidance.safe_error(
        cli_guidance.DeployStepBlocked("base advanced; review retained commit")
    )
    assert known["code"] == "DEPLOY_STEP_BLOCKED"
    assert known["reason"] == "base advanced; review retained commit"


@pytest.mark.parametrize("output,physical,expected", [
    ("fl-new", "fl-new", "`fl-new`"),
    (None, "fl-new", "`fl-new`"),
    ("fl-other", "fl-new", None),
])
def check_flowlog_observed_identifier(tmp_path, output, physical, expected):
    source = tmp_path / "model/dev/app/vpc.properties"
    resource = {"resourceType": "EC2.FlowLog", "logicalId": "EC2_FlowLog_001"}
    rows = [("001-001", {"property": "EC2.FlowLog.Id"})]
    mapped = {"A": {"Flow": (source, "001", resource, rows, {"EC2.FlowLog.Id"})}}
    document = {"Resources": {"Flow": {"Type": "AWS::EC2::FlowLog"}},
                "Outputs": {"FlowId": {"Value": {"Ref": "Flow"}}}}
    stack = {"StackId": "stack", "StackStatus": "CREATE_COMPLETE",
             "Outputs": [] if output is None else [{"OutputKey": "FlowId", "OutputValue": output}]}
    backend = SimpleNamespace(root=tmp_path, environment="dev", directory="app",
        target={"awsRegion": "region", "awsAccountId": "account"},
        templates={"A": (document, {})}, aws=Mock(side_effect=[
            {"Stacks": [stack]}, {"StackResourceSummaries": [{"LogicalResourceId": "Flow",
                "ResourceType": "AWS::EC2::FlowLog", "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": physical}]}, {"Stacks": [stack]}]))
    catalog = Mock()
    catalog.schema.return_value = {"primaryIdentifier": ["/properties/Id"]}
    loaded = {source: {"observed.row.001-001.value": "`PENDING_DEPLOY`"}}
    state = {"A": {"status": "SUCCESS"}}
    with (patch.object(observed, "DesignSchemaCatalog", return_value=catalog),
          patch.object(observed, "resolve_resources", return_value=(loaded, mapped)),
          patch.object(observed, "own_key", return_value="self"),
          patch.object(observed, "propagate_references"),
          patch.object(observed, "observed_destinations", return_value=({}, [], None)) as destinations):
        observed.collect_successful(backend, [{"name": "A"}], state)
    assert destinations.call_args.args[4][source]["observed.row.001-001.value"] == expected
    assert state["A"]["observedCoverage"]["Flow"]["status"] == ("UPDATED" if expected else "UNCONFIRMED")


@pytest.mark.parametrize(
    "missing", [False, True, "unknown-literal", "missing-status", "wrong-type"]
)
@pytest.mark.parametrize("already_matches", [False, True])
def check_every_identifier_is_confirmed(tmp_path, missing, already_matches):
    source = tmp_path / "model/dev/app/ec2.properties"
    resource = {"resourceType": "EC2.VPC", "logicalId": "EC2_VPC_001"}
    rows = [
        (
            "001-001",
            {
                "property": "EC2.VPC.VpcId",
                "value": '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
            },
        )
    ]
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
            "trackingReason": "CHANGESET_EXECUTION_ENDED",
            "result": "SUCCESS",
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
            )
            self.assertEqual(saved[-1]["status"], "SUCCESS")
            self.assertNotIn("attemptResult", saved[-1])
            release.assert_called_once_with(backend, request)

    def test_restarting_clears_unexecuted_reason(self):
        scoped = units(10)
        state = states(scoped)
        state["A"]["unexecutedReason"] = "DEPLOY_ENDED_WITHOUT_EXECUTION"
        scheduler.run_group(scoped, 1, state, Fake())
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
        self.assertEqual(record["result"], "SETTLED")
        other_event = {
            "ResourceType": "AWS::CloudFormation::Stack",
            "StackId": "stack",
            "PhysicalResourceId": "stack",
            "ClientRequestToken": "other",
            "ResourceStatus": "UPDATE_COMPLETE",
        }
        self.assertTrue(
            current_request.settled(
                Mock(side_effect=[change, {"StackEvents": [other_event]}]),
                record.copy(),
                current,
            )
        )
        self.assertTrue(
            current_request.settled(
                Mock(return_value=change), record, current | {"StackId": "other"}
            )
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

    def test_uncertain_submission_and_identity_mismatches_keep_request(self):
        record = {
            "operation": "execute_change_set",
            "name": "A",
            "stackId": "stack",
            "changeSetId": "change",
            "token": "own",
            "submission": "SENDING",
        }
        change = {
            "ChangeSetId": "change",
            "StackId": "stack",
            "ExecutionStatus": "EXECUTE_COMPLETE",
        }
        current = {"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}
        later = {
            "ResourceType": "AWS::CloudFormation::Stack",
            "StackId": "stack",
            "PhysicalResourceId": "stack",
            "ClientRequestToken": "other",
            "ResourceStatus": "UPDATE_COMPLETE",
        }
        aws = Mock(side_effect=[change, {"StackEvents": [later]}])
        self.assertTrue(current_request.settled(aws, record, current))
        later["ClientRequestToken"] = "own"
        aws = Mock(side_effect=[change, {"StackEvents": [later]}])
        self.assertTrue(current_request.settled(aws, record, current))
        self.assertEqual(record["result"], "SETTLED")
        for key, wrong in [
            ("StackId", "other"),
            ("ChangeSetId", "other"),
            ("clientToken", "other"),
        ]:
            state = {
                "status": "RUNNING",
                "clientToken": "own",
                "changeSetId": "change",
                "executionEvidence": {
                    "StackId": "stack",
                    "ChangeSetId": "change",
                    "clientToken": "own",
                },
            }
            state["executionEvidence"][key] = wrong
            backend = SimpleNamespace(
                states={"A": state},
                units=[{"name": "A"}],
                aws=partial(
                    recovery_test_aws,
                    current="UPDATE_COMPLETE",
                    execution="EXECUTE_COMPLETE",
                ),
                target={},
                save=Mock(),
            )
            backend.poll = partial(controller.poll, backend)
            with (
                patch.object(
                    current_request,
                    "reconcile",
                    return_value=record | {"settled": True},
                ),
                patch.object(current_request, "release") as release,
            ):
                steps.refresh_requests(backend)
            self.assertTrue(state["requestPending"])
            release.assert_not_called()
            backend.save.assert_not_called()

    def test_uncertain_terminal_change_sets_settle_only_when_stack_is_stable(self):
        record = {
            "operation": "execute_change_set",
            "name": "A",
            "stackId": "stack",
            "changeSetId": "change",
            "token": "own",
            "submission": "SENDING",
        }
        current = {"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}
        for execution in ("EXECUTE_FAILED", "OBSOLETE", "EXECUTE_COMPLETE"):
            change = {
                "ChangeSetId": "change",
                "StackId": "stack",
                "ExecutionStatus": execution,
            }
            with self.subTest(execution=execution):
                evidence = dict(record)
                self.assertTrue(
                    current_request.settled(
                        Mock(return_value=change), evidence, current
                    )
                )
                self.assertEqual(evidence["result"], "SETTLED")
                self.assertFalse(
                    current_request.settled(
                        Mock(return_value=change),
                        dict(record),
                        current | {"StackStatus": "UPDATE_IN_PROGRESS"},
                    )
                )
        change["ExecutionStatus"] = "EXECUTE_FAILED"
        for status in (
            "UPDATE_FAILED",
            "CREATE_FAILED",
            "UNKNOWN",
            "NEW_UNRECOGNIZED_STATUS",
        ):
            self.assertFalse(
                current_request.settled(
                    Mock(return_value=change),
                    dict(record),
                    current | {"StackStatus": status},
                )
            )
        change["ExecutionStatus"] = "EXECUTE_IN_PROGRESS"
        self.assertFalse(
            current_request.settled(Mock(return_value=change), dict(record), current)
        )
        change["ExecutionStatus"] = "AVAILABLE"
        self.assertFalse(
            current_request.settled(Mock(return_value=change), dict(record), current)
        )
        change["ExecutionStatus"] = "EXECUTE_IN_PROGRESS"
        self.assertFalse(
            current_request.settled(
                Mock(return_value=change),
                dict(record),
                current | {"StackStatus": "UPDATE_IN_PROGRESS"},
            )
        )

    def test_settled_revalidation_allows_next_order_without_reexecuting(self):
        scoped = units(10, 20)
        state = states(scoped)
        state["A"] = {"status": "SETTLED", "attemptResult": "UNKNOWN"}
        backend = Fake()
        backend.current_satisfied = Mock()
        self.assertEqual(scheduler.run_group(scoped, 1, state, backend), "ACTIVE")
        self.assertEqual(state["A"]["attemptResult"], "UNKNOWN")
        self.assertEqual(state["A"]["status"], "SETTLED")
        self.assertEqual(
            [event[1] for event in backend.events if event[0] == "start"], ["B"]
        )
        scheduler.run_group(scoped, 1, state, backend)
        self.assertEqual(state["B"]["status"], "SUCCESS")
        self.assertEqual(scheduler.run_group(scoped, 1, state, backend), "COMPLETE")
        self.assertEqual(backend.current_satisfied.call_count, 3)

    def test_settled_revalidation_blocks_next_order_on_mismatch(self):
        scoped = units(10, 20)
        state = states(scoped)
        state["A"] = {"status": "SETTLED", "attemptResult": "UNKNOWN"}
        backend = Fake()
        backend.current_satisfied = Mock(side_effect=Blocked("current input differs"))
        for _ in range(2):
            self.assertEqual(
                scheduler.run_group(scoped, 1, state, backend),
                "STOPPED",
            )
        self.assertEqual(state["B"]["status"], "NOT_STARTED")
        self.assertEqual(state["A"]["attemptResult"], "UNKNOWN")
        self.assertFalse(backend.events)

    def test_current_satisfied_checks_fixed_template_parameters_outputs_and_identifiers(
        self,
    ):
        unit = {"name": "A", "deployOrder": 10}
        document = {
            "Parameters": {"Count": {"Type": "Number"}},
            "Resources": {},
            "Outputs": {"Example": {"Value": "expected"}},
        }
        current = {
            "StackId": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/A/id",
            "StackStatus": "UPDATE_COMPLETE",
            "Parameters": [{"ParameterKey": "Count", "ParameterValue": "2"}],
            "Outputs": [{"OutputKey": "Example", "OutputValue": "expected"}],
        }
        state = {
            "status": "SETTLED",
            "attemptResult": "UNKNOWN",
            "observedSynced": True,
            "executionEvidence": {
                "StackId": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/A/id"
            },
            "currentStack": current_state.observation(current),
        }
        aws = Mock(
            side_effect=lambda operation, **kwargs: {"Stacks": [current]}
            if operation == "describe_stacks"
            else {"TemplateBody": document}
        )
        backend = SimpleNamespace(
            states={"A": state},
            templates={"A": (document, {"Count": "2"})},
            target={"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
            expected_digests={"A": "digest"},
            load_inputs=Mock(),
            input_digest=Mock(return_value="digest"),
            aws=aws,
        )
        with (
            patch.object(current_request, "reconcile", return_value=None),
            patch.object(observed, "collect_successful") as collect,
        ):
            controller.current_satisfied(backend, unit)
            collect.assert_called_once()
            self.assertNotIn("executionEvidence", collect.call_args.args[2]["A"])
            for status in ("UNCONFIRMED", "UPDATED"):
                collect.side_effect = partial(set_test_coverage, status)
                with self.assertRaises(Blocked):
                    controller.current_satisfied(backend, unit)
            collect.side_effect = None
            current["Outputs"][0]["OutputValue"] = "incorrect"
            with self.assertRaises(Blocked):
                controller.current_satisfied(backend, unit)
            current["Outputs"][0]["OutputValue"] = "expected"
            current["Parameters"][0]["ParameterValue"] = "3"
            with self.assertRaises(Blocked):
                controller.current_satisfied(backend, unit)
            current["Parameters"][0]["ParameterValue"] = "2"
            aws.side_effect = (
                lambda operation, **kwargs: {"Stacks": [current]}
                if operation == "describe_stacks"
                else {"TemplateBody": {"Resources": {"Other": {}}}}
            )
            with self.assertRaises(Blocked):
                controller.current_satisfied(backend, unit)
            fake = Fake()
            backend.states["B"] = {"status": "NOT_STARTED"}
            backend.current_satisfied = partial(controller.current_satisfied, backend)
            backend.prepare, backend.execute, backend.poll = (
                fake.prepare,
                fake.execute,
                fake.poll,
            )
            consumer = {
                "name": "B",
                "deployOrder": 20,
                "template": "b",
                "parameters": "b",
            }
            self.assertEqual(
                scheduler.run_group([unit, consumer], 1, backend.states, backend),
                "STOPPED",
            )
            self.assertEqual(backend.states["B"]["status"], "NOT_STARTED")
            aws.side_effect = (
                lambda operation, **kwargs: {"Stacks": [current]}
                if operation == "describe_stacks"
                else {"TemplateBody": document}
            )
            self.assertEqual(
                scheduler.run_group([unit, consumer], 1, backend.states, backend),
                "ACTIVE",
            )
            self.assertEqual(
                [event[1] for event in fake.events if event[0] == "start"], ["B"]
            )
        self.assertEqual(state["attemptResult"], "UNKNOWN")

    def test_settled_artifact_is_reconstructed_from_fixed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "code.zip"
            source.write_bytes(b"artifact")
            digest = "a" * 64
            artifact = {
                "resource": "Function",
                "property": "Code",
                "bucket": "bucket",
                "keyPrefix": "code/",
            }
            unit = {"name": "A", "artifacts": [artifact]}
            document = {
                "Resources": {
                    "Function": {
                        "Type": "AWS::Lambda::Function",
                        "Properties": {
                            "Code": {"S3Bucket": "bucket", "S3Key": "code/placeholder"}
                        },
                    }
                }
            }
            deployed = copy.deepcopy(document)
            code = deployed["Resources"]["Function"]["Properties"]["Code"]
            code.update(S3Key="code/" + digest + ".zip", S3ObjectVersion="version")
            obj = {
                "bucket": "bucket",
                "key": code["S3Key"],
                "checksum": base64.b64encode(bytes.fromhex(digest)).decode(),
                "size": source.stat().st_size,
                "version": "version",
            }
            current = {"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}
            state = {
                "status": "SETTLED",
                "attemptResult": "UNKNOWN",
                "observedSynced": True,
                "currentStack": current,
                "delivery": {"inputDigest": "fixed", "imports": {}, "objects": [obj]},
            }
            backend = SimpleNamespace(
                states={"A": state},
                templates={"A": (document, {})},
                target={"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
                expected_digests={"A": "fixed"},
                load_inputs=Mock(),
                input_digest=Mock(return_value="fixed"),
                source_path=Mock(return_value=source),
                file_digest=Mock(return_value=digest),
                exports_for=Mock(return_value={}),
                verify_object=Mock(),
                aws=Mock(
                    side_effect=lambda operation, **kwargs: {"Stacks": [current]}
                    if operation == "describe_stacks"
                    else {"TemplateBody": deployed}
                ),
            )
            with (
                patch.object(current_request, "reconcile", return_value=None),
                patch.object(observed, "collect_successful"),
            ):
                controller.current_satisfied(backend, unit)
                backend.verify_object.assert_called_once_with(obj)
                obj["checksum"] = "wrong"
                with self.assertRaises(Blocked):
                    controller.current_satisfied(backend, unit)
            self.assertNotIn(
                "S3ObjectVersion",
                document["Resources"]["Function"]["Properties"]["Code"],
            )

    def test_imports_revalidate_settled_producer_without_changing_attempt(self):
        producer = {"name": "A", "deployOrder": 10}
        consumer = {"name": "B", "deployOrder": 20}
        state = {
            "A": {"status": "SETTLED", "attemptResult": "UNKNOWN"},
            "B": {"status": "NOT_STARTED"},
        }
        document = {
            "Resources": {
                "Consumer": {
                    "Type": "Test",
                    "Properties": {"Value": {"Fn::ImportValue": "export"}},
                }
            }
        }
        exports = {
            "export": {
                "Value": "value",
                "ExportingStackId": "arn:aws:cloudformation:region:account:stack/A/id",
            }
        }
        backend = SimpleNamespace(
            states=state,
            units=[producer, consumer],
            verified_settled={"A"},
            templates={"B": (document, {})},
            target={"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
            exports_for=Mock(return_value=exports),
            aws=Mock(),
        )
        with patch.object(controller, "current_satisfied") as verify:
            controller.check_imports(backend, consumer)
            verify.assert_called_once_with(backend, producer)
        self.assertEqual(state["A"], {"status": "SETTLED", "attemptResult": "UNKNOWN"})
        with patch.object(
            controller, "current_satisfied", side_effect=Blocked("changed")
        ):
            with self.assertRaises(Blocked):
                controller.check_imports(backend, consumer)

    def test_uncertain_terminal_requests_persist_before_release(self):
        for execution in ("EXECUTE_FAILED", "OBSOLETE"):
            with (
                self.subTest(execution=execution),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory).resolve() / "request.json"
                record = {
                    "operation": "execute_change_set",
                    "name": "A",
                    "stackId": "stack",
                    "changeSetId": "change",
                    "token": "own",
                    "submission": "SENDING",
                }
                path.write_text(json.dumps(record), encoding="utf-8")
                path.chmod(0o600)
                state = {
                    "status": "RUNNING",
                    "clientToken": "own",
                    "changeSetId": "change",
                    "executionEvidence": {
                        "StackId": "stack",
                        "ChangeSetId": "change",
                        "clientToken": "own",
                    },
                }
                backend = SimpleNamespace(
                    target={},
                    states={"A": state},
                    units=[{"name": "A"}],
                    templates={},
                    aws=partial(
                        recovery_test_aws,
                        current="UPDATE_COMPLETE",
                        execution=execution,
                    ),
                )
                backend.poll = partial(controller.poll, backend)
                saved = []
                backend.save = partial(save_test_snapshot, saved, state, path)
                with patch.object(current_request, "location", return_value=path):
                    steps.refresh_requests(backend)
                    self.assertEqual(saved[-1][0]["status"], "SETTLED")
                    self.assertEqual(saved[-1][0]["attemptResult"], "UNKNOWN")
                    self.assertTrue(saved[-1][1])
                    self.assertFalse(path.exists())
                    steps.refresh_requests(backend)
                    self.assertEqual(state["status"], "SETTLED")
                    self.assertEqual(state["attemptResult"], "UNKNOWN")

    def test_settled_unknown_is_terminal_without_reexecution(self):
        state = {
            "status": "SETTLED",
            "attemptResult": "UNKNOWN",
            "currentStack": {"StackStatus": "UPDATE_COMPLETE"},
        }
        backend = Fake()
        backend.execute = Mock(side_effect=AssertionError("duplicate execution"))
        outcome = advance_group(
            [{"name": "A", "deployOrder": 1}], 1, {"A": state}, backend
        )
        self.assertEqual(outcome, "STOPPED")
        backend.execute.assert_not_called()
        self.assertTrue(worktree.attempts_finished({"A": state}, "UNKNOWN"))
        self.assertEqual(state["attemptResult"], "UNKNOWN")

    def test_explicit_completion_requires_the_saved_final_candidate(self):
        task = SimpleNamespace(
            text="## Task contract\n- Task type: `infrastructure`\n- Infrastructure phase: `deploy`\n"
        )
        with patch.object(
            worktree, "require_complete", side_effect=Blocked("use sync --final")
        ) as required:
            with self.assertRaisesRegex(Blocked, "sync --final"):
                prepare_complete(Path("/synthetic"), task)
            required.assert_called_once()

    def test_settled_execution_is_not_sent_again_before_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "request.json"
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
            runtime = SimpleNamespace(target={}, aws=Mock(), states={})
            with (
                patch.object(current_request, "location", return_value=path),
                patch.object(
                    current_state,
                    "read",
                    return_value={"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"},
                ),
                patch.object(current_request, "settled", return_value=True),
            ):
                with self.assertRaisesRegex(Blocked, "settled request needs durable progress"):
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
                    "ATTEMPT_SUCCESS",
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
            self.assertIn(
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
        scheduler.run_group(scoped, 1, state, backend)
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
        scheduler.run_group(scoped, 1, state, backend)
        self.assertEqual(state["B"]["status"], "RUNNING")

    def test_short_advances_do_not_starve_independent_peers(self):
        scoped = units(10, 10, 20)
        state = states(scoped)
        backend = Fake(blocked={"A"})
        scheduler.run_group(scoped, 1, state, backend)
        scheduler.run_group(scoped, 1, state, backend)
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
        scheduler.run_group(scoped, 1, state, Fake())
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

    def test_completed_changeset_outweighs_stale_failure_event(self):
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
        self.assertTrue(current_request.settled(aws, record, stack))

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
        self.assertEqual(failed["status"], "BLOCKED")

    def test_missing_request_recovers_changeset_result_and_keeps_current_observation(
        self,
    ):
        for execution, current, expected in [
            ("EXECUTE_COMPLETE", "UPDATE_COMPLETE", "SETTLED"),
            ("EXECUTE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "SETTLED"),
            ("EXECUTE_FAILED", "UPDATE_COMPLETE", "SETTLED"),
            ("AVAILABLE", "UPDATE_COMPLETE", "BLOCKED"),
        ]:
            with (
                self.subTest(execution=execution),
                tempfile.TemporaryDirectory() as directory,
            ):
                state = {
                    "status": "RUNNING",
                    "clientToken": "own",
                    "changeSetId": "change",
                    "executionEvidence": {"StackId": "stack"},
                }

                aws = partial(recovery_test_aws, current=current, execution=execution)
                reader = Mock(side_effect=aws)
                backend = SimpleNamespace(
                    target={},
                    states={"A": state},
                    units=[{"name": "A"}],
                    aws=reader,
                    templates={},
                    save=Mock(),
                )
                backend.poll = partial(controller.poll, backend)
                with patch.object(
                    current_request,
                    "location",
                    return_value=Path(directory).resolve() / "absent",
                ):
                    steps.refresh_requests(backend)
                self.assertEqual(state["status"], expected, state)
                self.assertEqual(state["currentStack"]["StackStatus"], current)
                self.assertIn(
                    "describe_change_set",
                    [call.args[0] for call in reader.call_args_list],
                )
                self.assertNotIn(
                    "execute_change_set",
                    [call.args[0] for call in reader.call_args_list],
                )
                if expected == "SETTLED":
                    backend.save.assert_called_once()
                else:
                    self.assertTrue(state["requestPending"])

    def test_completed_shared_request_is_saved_before_release_with_later_event(self):
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
            state = {
                "status": "RUNNING",
                "clientToken": "original",
                "changeSetId": "change",
                "executionEvidence": {
                    "StackId": "stack",
                    "ChangeSetId": "change",
                    "clientToken": "original",
                },
            }

            backend = SimpleNamespace(
                target={},
                states={"A": state},
                units=[{"name": "A"}],
                aws=later_event_test_aws,
                templates={},
            )
            backend.poll = partial(controller.poll, backend)
            progress = path.parent / "progress.json"
            backend.save = Mock(
                side_effect=partial(save_test_state, self, path, progress, state)
            )
            with patch.object(current_request, "location", return_value=path):
                steps.refresh_requests(backend)
            saved = worktree.read_sealed(path.parent, progress)
            self.assertEqual(saved["status"], "SETTLED")
            self.assertEqual(saved["attemptResult"], "UNKNOWN")
            self.assertEqual(
                saved["currentStack"]["StackStatus"], "UPDATE_ROLLBACK_COMPLETE"
            )
            self.assertFalse(path.exists())

    def test_inconsistent_saved_execution_identity_stays_unconfirmed(self):
        for field, value in [("clientToken", "other"), ("ChangeSetId", "other")]:
            state = {
                "status": "RUNNING",
                "clientToken": "original",
                "changeSetId": "change",
                "executionEvidence": {
                    "StackId": "stack",
                    "ChangeSetId": "change",
                    "clientToken": "original",
                },
            }
            state["executionEvidence"][field] = value
            aws = Mock(
                return_value={
                    "Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}]
                }
            )
            status = controller.poll(
                SimpleNamespace(aws=aws, templates={}), {"name": "A"}, state
            )
            self.assertEqual(status, "UNCONFIRMED")
            self.assertFalse(
                current_request.owns(
                    state,
                    {
                        "operation": "execute_change_set",
                        "token": "original",
                        "changeSetId": "change",
                        "stackId": "stack",
                    },
                )
            )

    def test_unknown_identifier_does_not_render_an_old_id(self):
        row = {
            "property": "EC2.VPC.VpcId",
            "value": '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
        }
        rendered = observed_value("001-001", row, None, {row["property"]})
        self.assertNotIn("vpc-old", rendered)
        self.assertEqual(rendered, row["value"])

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
                "taskFile": "tasks/deploy.md",
                "snapshotValidation": "PASS",
            },
        )
        result = steps.describe(backend)
        self.assertEqual(result["result"], "COMPLETE")
        self.assertEqual(result["deployResult"], "FAIL")
        backend.run_context["generationError"] = "broken reference"
        self.assertNotEqual(steps.describe(backend)["result"], "COMPLETE")


def progress_backend(root, context):
    identity = dict(
        taskFile="tasks/deploy.md",
        taskDigest="digest",
        target={},
        environment="dev",
        stacks=["A"],
        snapshot="fixed",
    )
    context.update(
        {
            key: identity[key]
            for key in ("taskFile", "taskDigest", "target", "environment")
        }
    )
    context["repository"] = str(root)
    context.setdefault("consumedInputs", {})
    context.setdefault("stepUnits", [{"name": "A"}])
    return SimpleNamespace(
        root=root,
        phase="deploy",
        run_context=context,
        progress_identity=identity,
        progress_root=root.resolve(),
        progress_directory=context.get("directory"),
        progress_destination=worktree.progress_path(root, create=True),
    )


def check_progress_initialization_private_and_resumable(tmp_path, monkeypatch):
    monkeypatch.setattr(sealed_evidence.tempfile, "gettempdir", lambda: str(tmp_path))
    old = os.umask(0o022)
    try:
        path = worktree.progress_path(tmp_path / "project", create=True)
        for directory in (path.parent, path.parent.parent, path.parent.parent.parent):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        context = {
            "states": {"A": {"status": "SUCCESS"}},
            "inputDigests": {"A": "hash"},
        }
        backend = progress_backend(tmp_path / "project", context)
        with operation_journal.locked(path):
            worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
        with operation_journal.locked(
            worktree.progress_path(backend.root, create=True)
        ):
            assert (
                worktree.read_progress(
                    backend.root, {"deployIdentity": backend.progress_identity}
                )["runContext"]["states"]["A"]["status"]
                == "SUCCESS"
            )
    finally:
        os.umask(old)


@pytest.mark.parametrize("unsafe", ["permissions", "owner", "symlink"])
@pytest.mark.parametrize("level", [0, 1, 2])
def check_progress_rejects_unsafe_directories(tmp_path, monkeypatch, unsafe, level):
    monkeypatch.setattr(sealed_evidence.tempfile, "gettempdir", lambda: str(tmp_path))
    root = tmp_path / "project"
    path = worktree.progress_path(root, create=True)
    directory = (path.parent.parent.parent, path.parent.parent, path.parent)[level]
    if unsafe == "permissions":
        directory.chmod(0o755)
    elif unsafe == "symlink":
        moved = directory.with_name(directory.name + "-original")
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    else:
        original_lstat = Path.lstat
        monkeypatch.setattr(
            Path,
            "lstat",
            partialmethod(
                wrong_owner, original_lstat=original_lstat, directory=directory
            ),
        )
    expected = (
        ("private to the current user" if level < 2 else "unsafe local evidence")
        if unsafe == "owner"
        else None
    )
    with pytest.raises(ValueError, match=expected):
        worktree.progress_path(root, create=True)


def check_candidate_validation_displays_report_once(tmp_path, monkeypatch, capsys):
    task = SimpleNamespace(
        name="tasks/a.md", text="task", scope=set(), status="running"
    )
    monkeypatch.setattr(publication.tasks, "selected_task", lambda *a: nullcontext())
    monkeypatch.setattr(publication.tasks, "task_snapshot", lambda *a, **k: task)
    monkeypatch.setattr(publication, "require_observation_delta", lambda *a: None)
    monkeypatch.setattr(publication, "definition_root", lambda root: root)
    monkeypatch.setattr(publication.wt, "paths", lambda *a: set())
    validator = Mock()
    validator.display_report.side_effect = lambda: (
        print("specific failure\nTask Acceptance: FAIL"),
        1,
    )[1]
    monkeypatch.setattr(publication, "Validator", lambda *a, **k: validator)
    assert (
        publication.validate_snapshot(tmp_path, tmp_path, "base", "tree", task.name)
        == 1
    )
    assert "specific failure" in capsys.readouterr().out
    validator.run.assert_called_once()
    validator.display_report.assert_called_once()


@pytest.mark.parametrize("returncode", [0, 1])
def check_candidate_subprocess_result_and_resolved_root(
    tmp_path, monkeypatch, returncode
):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(
        publication.tempfile,
        "TemporaryDirectory",
        lambda **kwargs: nullcontext(str(alias)),
    )
    monkeypatch.setattr(
        publication.wt.python_env, "runtime", lambda root: (sys.executable, {})
    )
    monkeypatch.setattr(publication.wt, "git", candidate_test_git)
    result = SimpleNamespace(
        returncode=returncode,
        stdout="specific failure\nTask Acceptance: FAIL",
        stderr="diagnostic stderr",
    )
    run = Mock(return_value=result)
    monkeypatch.setattr(publication.subprocess, "run", run)
    task = SimpleNamespace(name="tasks/a.md", raw=b"task")
    if returncode:
        with pytest.raises(
            Exception,
            match="(?s)specific failure.*Task Acceptance: FAIL.*diagnostic stderr",
        ):
            publication.validate_candidate(tmp_path, "tree", "base", task)
    else:
        publication.validate_candidate(tmp_path, "tree", "base", task)
    assert run.call_args.kwargs["cwd"] == (real / "repository").resolve()
    assert run.call_args.kwargs["capture_output"] is True


@pytest.mark.parametrize(
    "operation", ["execute_change_set", "delete_stack", "continue_update_rollback"]
)
def check_deleted_original_stack_ends_tracking_without_success(operation):
    record = {
        "operation": operation,
        "name": "A",
        "stackId": "old-id",
        "changeSetId": "old-change",
        "token": "original",
    }
    aws = Mock(
        side_effect=AwsError(
            "cloudformation", "describe_stacks", "ValidationError", stack_absent=True
        )
    )
    assert current_request.settled(aws, record, {"StackStatus": "ABSENT"})
    aws.assert_called_once_with("describe_stacks", StackName="old-id")
    assert record["result"] == "SETTLED"
    assert record["trackingReason"] == "ORIGINAL_STACK_DELETED"


@pytest.mark.parametrize(
    "operation", ["execute_change_set", "create_change_set", "put_secret_value"]
)
def check_recreated_stack_does_not_mix_request_targets(operation):
    record = {
        "operation": operation,
        "name": "A",
        "stackId": "old-id",
        "changeSetId": "old-change",
        "token": "original",
        "resourceId": "secret",
    }
    if operation == "put_secret_value":
        record["service"] = "secretsmanager"
        aws = Mock(return_value={"VersionIdsToStages": {"other": ["AWSCURRENT"]}})
    else:
        aws = Mock(
            side_effect=AwsError(
                "cloudformation", "describe_change_set", "ChangeSetNotFound"
            )
        )
    confirmed = current_request.settled(
        aws, record, {"StackId": "new-id", "StackStatus": "UPDATE_COMPLETE"}
    )
    assert confirmed == (operation == "execute_change_set")
    if confirmed:
        assert record["result"] == "SETTLED"
        aws.assert_not_called()


@pytest.mark.parametrize("error", ["AccessDenied", "EndpointConnectionError"])
def check_original_stack_read_error_never_means_deleted(error):
    record = {
        "operation": "execute_change_set",
        "name": "A",
        "stackId": "old-id",
        "changeSetId": "change",
        "token": "original",
    }
    aws = Mock(side_effect=AwsError("cloudformation", "describe_stacks", error))
    assert not current_request.settled(aws, record, {"StackStatus": "ABSENT"})
    assert "trackingReason" not in record


def check_ended_unknown_detaches_submission_and_allows_fresh_preparation():
    record = {
        "operation": "execute_change_set",
        "name": "A",
        "stackId": "old-id",
        "changeSetId": "old-change",
        "token": "original",
        "settled": True,
        "trackingReason": "ORIGINAL_STACK_REPLACED",
        "result": "SETTLED",
    }
    state = {
        "status": "RUNNING",
        "clientToken": "original",
        "changeSetId": "old-change",
        "executionEvidence": {"StackId": "old-id"},
        "currentStack": {"StackId": "new-id", "StackStatus": "UPDATE_COMPLETE"},
    }
    current_request.end_tracking(state, record)
    assert state["attemptResult"] == state["endedRequest"]["result"] == "UNKNOWN"
    assert (
        not {"clientToken", "changeSetId", "executionEvidence", "preparationId"}
        & state.keys()
    )
    backend = SimpleNamespace(states={"A": state}, run_context={})
    steps.retry_terminal_attempts(backend, {"A"})
    assert state["status"] == "NOT_STARTED"
    assert state["endedRequest"]["result"] == "UNKNOWN"
    assert not state.get("clientToken")


@pytest.mark.parametrize("action", ["advance", "checkpoint", "status"])
def check_final_cli_rejected_before_action(action):
    with patch.object(steps, "run") as run_step, pytest.raises(SystemExit):
        controller.controller_main(
            [
                "--environment",
                "dev",
                "--alias",
                "app",
                "--stack",
                "A",
                "--action",
                action,
                "--final",
            ]
        )
    run_step.assert_not_called()


@pytest.mark.parametrize(
    "owner,change",
    [("original", "change"), ("foreign", "change"), ("original", "other")],
)
def check_completed_create_only_allows_its_own_execute(tmp_path, owner, change):
    stack = "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/A/id"
    change_arn = (
        "arn:aws:cloudformation:ap-northeast-1:123456789012:changeSet/change/id"
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "operation": "create_change_set",
                "name": "A",
                "stackId": stack,
                "changeSetId": "change",
                "token": "original",
            }
        ),
        encoding="utf-8",
    )
    request.chmod(0o600)
    runtime = SimpleNamespace(
        target={"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
        states={
            "A": {
                "preparationId": owner,
                "changeSetId": change_arn,
                "stackId": stack,
                "changeDigest": fingerprint([]),
                "approvedChangeDigest": fingerprint([]),
                "clientToken": "execute",
                "executionEvidence": {
                    "StackId": stack,
                    "ChangeSetId": change_arn,
                    "clientToken": "execute",
                    "changeDigest": fingerprint([]),
                    "inputDigest": "input",
                },
            }
        },
        save=Mock(),
        aws=Mock(
            return_value={
                "StackId": stack,
                "ChangeSetId": change_arn,
                "Status": "CREATE_COMPLETE",
                "ExecutionStatus": "AVAILABLE",
            }
        ),
    )
    arguments = {
        "StackName": stack,
        "ChangeSetName": change_arn if change == "change" else change,
        "ClientRequestToken": "execute",
    }
    transport = Mock(return_value={})
    with (
        patch.object(current_request, "location", return_value=request),
        patch.object(
            current_state,
            "read",
            return_value={"StackId": stack, "StackStatus": "UPDATE_COMPLETE"},
        ),
    ):
        if owner == "original" and change == "change":
            current_request.send(runtime, "execute_change_set", arguments, transport)
            transport.assert_called_once_with(
                runtime, "cloudformation", "execute_change_set", arguments
            )
            TestCase().assertEqual(
                json.loads(request.read_text(encoding="utf-8"))["operation"],
                "execute_change_set",
            )
        else:
            with pytest.raises(Blocked, match="fresh current ChangeSet"):
                current_request.send(
                    runtime, "execute_change_set", arguments, transport
                )
            transport.assert_not_called()
    runtime.save.assert_called_once()


@pytest.mark.parametrize(
    "generation,after,names,final",
    [
        (True, None, ["A", "B"], False),
        (True, {}, ["A", "B"], False),
        (True, {"model": "changed"}, ["A", "B"], False),
        (False, None, ["A", "B"], False),
        (True, None, ["B"], False),
        (True, None, ["A"], False),
        (True, None, ["A", "B"], True),
    ],
)
def check_pending_generation_sync_preserves_candidate_scope(
    tmp_path, generation, after, names, final
):
    pending = {"stacks": ["A"], "before": {}, "after": after}
    if final:
        pending["final"] = {"taskAfter": "completed"}
    backend = SimpleNamespace(
        root=tmp_path,
        phase="update",
        units=[{"name": "A"}, {"name": "B"}],
        states={"A": {}, "B": {}},
        guard=Mock(),
        claim_inputs=Mock(),
        save=Mock(side_effect=RuntimeError("selected snapshot")),
        run_context={
            "inputDigests": {"A": "a", "B": "b"},
            "checkpointPending": pending,
        },
    )
    if generation:
        backend.run_context["pendingGeneration"] = {"view": {}}
    with (
        patch.object(steps, "task_snapshot"),
        patch.object(steps.contracts, "validation_snapshot", return_value={}),
    ):
        if generation and after in (None, {}) and "A" in names and not final:
            with pytest.raises(RuntimeError, match="selected snapshot"):
                steps.sync(backend, names)
            TestCase().assertEqual(pending["stacks"], sorted(names))
            backend.save.assert_called_once()
        else:
            with pytest.raises(
                steps.Blocked, match="Stack scope|synchronized candidate changed"
            ):
                steps.sync(backend, names)
            TestCase().assertEqual(pending["stacks"], ["A"])
            backend.save.assert_not_called()
    backend.claim_inputs.assert_not_called()


def check_final_cli_accepts_saved_observations_without_sync_stack():
    with patch.object(steps, "run", return_value=0) as run_step:
        assert (
            controller.controller_main(
                [
                    "--environment",
                    "dev",
                    "--alias",
                    "app",
                    "--stack",
                    "A",
                    "--action",
                    "sync",
                    "--final",
                ]
            )
            == 0
        )
    assert run_step.call_args.args[0].final
    assert run_step.call_args.args[0].sync_stack == []


def check_missing_execution_identity_cannot_adopt_current_success():
    backend = SimpleNamespace(
        aws=Mock(
            return_value={
                "Stacks": [{"StackId": "current", "StackStatus": "UPDATE_COMPLETE"}]
            }
        ),
        states={},
    )
    state = {"status": "BLOCKED", "attemptResult": "UNKNOWN"}
    with patch.object(current_request, "reconcile", return_value=None):
        assert controller.poll(backend, {"name": "A"}, state) == "UNCONFIRMED"
    assert (
        state["attemptResult"] == "UNKNOWN"
        and "identity is incomplete" in state["requestError"]
    )


def check_refresh_only_reads_selected_sync_stacks_once():
    backend = SimpleNamespace(
        units=[{"name": "A"}, {"name": "B"}],
        states={
            "A": {"status": "NOT_STARTED"},
            "B": {"status": "SUCCESS", "observedSynced": True},
        },
        aws=Mock(
            return_value={
                "Stacks": [{"StackId": "a", "StackStatus": "UPDATE_COMPLETE"}]
            }
        ),
    )
    with patch.object(current_request, "reconcile", return_value=None):
        steps.refresh_requests(backend, [backend.units[0]])
    backend.aws.assert_called_once_with("describe_stacks", StackName="A")
    assert backend.states["B"] == {"status": "SUCCESS", "observedSynced": True}


def check_final_acceptance_includes_earlier_task_checkpoints(tmp_path, monkeypatch):
    task = SimpleNamespace(
        name="tasks/a.md", text="completed Task", scope=set(), status="completed"
    )
    monkeypatch.setattr(publication.tasks, "selected_task", lambda *a: nullcontext())
    monkeypatch.setattr(publication.tasks, "task_snapshot", lambda *a, **k: task)
    monkeypatch.setattr(publication, "require_observation_delta", lambda *a: None)
    monkeypatch.setattr(publication, "definition_root", lambda root: root)
    monkeypatch.setattr(
        publication.ws, "deploy_start_commit", Mock(return_value="fixed-start")
    )
    paths = Mock(
        side_effect=[{"tasks/a.md"}, {"model/earlier.properties", "tasks/a.md"}]
    )
    monkeypatch.setattr(publication.wt, "paths", paths)
    validator = Mock()
    validator.display_report.return_value = 0
    factory = Mock(return_value=validator)
    monkeypatch.setattr(publication, "Validator", factory)
    assert (
        publication.validate_snapshot(
            tmp_path, tmp_path / "private", "latest-base", "final-tree", task.name
        )
        == 0
    )
    candidate = factory.call_args.kwargs["final_candidate"]
    assert candidate.changed_paths == frozenset(
        {"tasks/a.md", "model/earlier.properties"}
    )
    assert (
        candidate.base_commit == "latest-base"
        and candidate.deploy_source_root == tmp_path
    )
    assert paths.call_args_list[1].args[0] == tmp_path
    assert paths.call_args_list[1].args[-1] == "HEAD"


def check_unconfirmed_create_preserves_original_recovery_identity(tmp_path):
    request = tmp_path / "request.json"
    record = {
        "operation": "create_change_set",
        "name": "A",
        "stackId": None,
        "changeSetId": "original-change",
        "token": "original-token",
    }
    request.write_text(json.dumps(record), encoding="utf-8")
    request.chmod(0o600)
    state = {
        "status": "CHANGESET_CREATING",
        "preparationId": "original-token",
        "changeSetId": "original-change",
        "currentStack": {"StackStatus": "ABSENT"},
    }
    backend = SimpleNamespace(
        target={},
        states={"A": state},
        aws=Mock(
            side_effect=AwsError(
                "cloudformation", "describe_change_set", "ChangeSetNotFound"
            )
        ),
    )
    with patch.object(current_request, "location", return_value=request):
        found = current_request.reconcile(backend, {"name": "A"})
    assert state["createUnconfirmed"] and found["createUnconfirmed"]
    assert (
        found["token"] == "original-token" and found["changeSetId"] == "original-change"
    )
    assert (
        not found.get("settled")
        and json.loads(request.read_text(encoding="utf-8")) == record
    )


@pytest.mark.parametrize(
    "condition",
    ["request", "approval", "authorization", "ended-unknown", "generation-error"],
)
def check_current_guidance_preserves_safe_recovery_and_final_choices(condition):
    state = {
        "status": "SUCCESS",
        "observedSynced": True,
        "currentStack": {"StackStatus": "UPDATE_COMPLETE", "StackId": "stack"},
    }
    context = {
        "states": {"A": state},
        "stepUnits": [{"name": "A", "deployOrder": 10}],
        "taskFile": "tasks/deploy.md",
        "snapshotValidation": "PASS",
    }
    if condition == "request":
        state.update(status="RUNNING", requestPending=True)
    elif condition in {"approval", "authorization"}:
        state.update(status="BLOCKED", failure={"classification": condition.upper()})
    elif condition == "ended-unknown":
        state.update(
            status="SETTLED",
            attemptResult="UNKNOWN",
            endedRequest={"result": "UNKNOWN"},
        )
    else:
        context["generationError"] = "generation incomplete"
    backend = SimpleNamespace(
        run_context=context,
        states=context["states"],
        units=context["stepUnits"],
        phase="deploy",
        task_status="running",
    )
    original = copy.deepcopy(context)
    with patch.object(publication, "display", return_value=None):
        report = steps.describe(backend)
    actions = report["nextActions"]
    assert bool([a for a in actions if a.get("final")]) == (
        condition in {"approval", "authorization", "ended-unknown"}
    )
    assert ({"action": "advance"} in actions) == (
        condition in {"request", "ended-unknown"}
    )
    assert actions and all(
        a["action"] in {"advance", "sync", "review"} for a in actions
    )
    assert context == original
    if condition == "ended-unknown":
        assert report["deployResult"] == "UNKNOWN" and report["task"] == "running"


@pytest.mark.parametrize(
    "problem",
    [
        "owner",
        "stack",
        "changeset",
        "same-name-other-id",
        "approval",
        "digest",
        "evidence",
        "token",
        "failed",
        "in-progress",
        "unavailable",
        "account",
        "region",
        "partition",
        "input",
        "ended",
        "ended-missing-identity",
        "ended-delete-unconfirmed",
    ],
)
def check_create_handoff_rejects_mismatched_evidence(tmp_path, problem):
    stack = "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/A/stack-id"
    change = "arn:aws:cloudformation:ap-northeast-1:123456789012:changeSet/change/id"
    digest = fingerprint([])
    prior = {
        "operation": "create_change_set",
        "name": "A",
        "stackId": stack,
        "changeSetId": "change",
        "token": "create",
    }
    state = {
        "status": "RUNNING",
        "preparationId": "create",
        "stackId": stack,
        "changeSetId": change,
        "clientToken": "execute",
        "changeDigest": digest,
        "approvedChangeDigest": digest,
        "executionEvidence": {
            "StackId": stack,
            "ChangeSetId": change,
            "clientToken": "execute",
            "changeDigest": digest,
            "inputDigest": "input",
        },
    }
    observed = {
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "StackId": stack,
        "ChangeSetId": change,
        "Changes": [],
    }
    arguments = {
        "StackName": stack,
        "ChangeSetName": change,
        "ClientRequestToken": "execute",
    }
    if problem == "owner":
        state["preparationId"] = "foreign"
    if problem == "stack":
        prior["stackId"] = stack + "-other"
    if problem == "changeset":
        state["changeSetId"] = change + "-other"
    if problem == "same-name-other-id":
        observed["ChangeSetId"] = change + "-other"
    if problem == "approval":
        state.pop("approvedChangeDigest")
    if problem == "digest":
        observed["Changes"] = [{"other": "change"}]
    if problem == "evidence":
        state["executionEvidence"]["StackId"] = stack + "-other"
    if problem == "token":
        arguments["ClientRequestToken"] = "other"
    if problem == "failed":
        observed["Status"] = "FAILED"
    if problem == "in-progress":
        observed["Status"] = "CREATE_IN_PROGRESS"
    if problem == "unavailable":
        observed["ExecutionStatus"] = "OBSOLETE"
    if problem == "input":
        state["executionEvidence"].pop("inputDigest")
    if problem == "ended-missing-identity":
        state["endedRequest"] = {
            "request": {
                "operation": "execute_change_set",
                "settled": True,
                "trackingReason": "TOKEN_ROOT_EVENT",
                "result": "FAIL",
            },
            "executionEvidence": {"inputDigest": "earlier-input"},
            "result": "FAIL",
        }
    if problem == "ended-delete-unconfirmed":
        state["endedRequest"] = {
            "request": {
                "operation": "delete_stack",
                "name": "A",
                "stackId": stack + "-previous",
                "token": "previous",
                "settled": True,
                "trackingReason": "ORIGINAL_STACK_DELETED",
                "result": "SETTLED",
                "originalStack": {"StackStatus": "ROLLBACK_COMPLETE"},
            },
            "result": "UNKNOWN",
        }
    if problem == "ended":
        state["endedRequest"] = {"request": {"token": "earlier"}, "result": "UNKNOWN"}
    if problem == "partition":
        stack_other = stack.replace("arn:aws:", "arn:aws-cn:")
        change_other = change.replace("arn:aws:", "arn:aws-cn:")
        prior["stackId"] = stack_other
        state.update(stackId=stack_other, changeSetId=change_other)
        state["executionEvidence"].update(StackId=stack_other, ChangeSetId=change_other)
        observed.update(StackId=stack_other, ChangeSetId=change_other)
        arguments.update(StackName=stack_other, ChangeSetName=change_other)
        stack = stack_other
    request = tmp_path / "request.json"
    request.write_text(json.dumps(prior), encoding="utf-8")
    request.chmod(0o600)
    backend = SimpleNamespace(
        target={"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
        states={"A": state},
        aws=Mock(return_value=observed),
        save=Mock(),
    )
    if problem == "account":
        backend.target["awsAccountId"] = "999999999999"
    if problem == "region":
        backend.target["awsRegion"] = "us-east-1"
    transport = Mock()
    with (
        patch.object(current_request, "location", return_value=request),
        patch.object(
            current_state,
            "read",
            return_value={"StackId": stack, "StackStatus": "UPDATE_COMPLETE"},
        ),
    ):
        with pytest.raises(Blocked):
            current_request.send(backend, "execute_change_set", arguments, transport)
    transport.assert_not_called()
    if problem == "ended":
        assert state["endedRequest"]["request"]["token"] == "earlier"
        assert json.loads(request.read_text())["token"] == "create"
        backend.save.assert_not_called()


def handoff_test_save(boundary, tmp_path, progress, state):
    if boundary == "save":
        raise OSError("save interrupted")
    worktree.write_sealed(tmp_path, progress, state)


def handoff_test_replace_file(boundary, replace, *args, **kwargs):
    if boundary == "replace":
        raise OSError("replace interrupted")
    result = replace(*args, **kwargs)
    if boundary == "after_replace":
        raise OSError("after replace interrupted")
    return result


@pytest.mark.parametrize("boundary", ["save", "replace", "after_replace", "transport"])
@pytest.mark.parametrize("previous", [None, "SUCCESS", "FAIL", "DELETED"])
def check_create_handoff_interruption_preserves_evidence(tmp_path, boundary, previous):
    stack = "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/A/stack-id"
    change = "arn:aws:cloudformation:ap-northeast-1:123456789012:changeSet/change/id"
    digest = fingerprint([])
    prior = {
        "operation": "create_change_set",
        "name": "A",
        "stackId": stack,
        "changeSetId": "change",
        "token": "create",
    }
    state = {
        "status": "RUNNING",
        "preparationId": "create",
        "stackId": stack,
        "changeSetId": change,
        "clientToken": "execute",
        "changeDigest": digest,
        "approvedChangeDigest": digest,
        "executionEvidence": {
            "StackId": stack,
            "ChangeSetId": change,
            "clientToken": "execute",
            "changeDigest": digest,
            "inputDigest": "input",
        },
    }
    if previous:
        state["endedRequest"] = {
            "request": {
                "operation": "execute_change_set",
                "stackId": stack,
                "changeSetId": change + "-previous",
                "token": "previous",
                "settled": True,
                "trackingReason": "TOKEN_ROOT_EVENT",
                "result": previous,
            },
            "executionEvidence": {
                "StackId": stack,
                "ChangeSetId": change + "-previous",
                "clientToken": "previous",
                "inputDigest": "earlier-input",
            },
            "result": previous,
        }
    if previous == "DELETED":
        state["endedRequest"] = {
            "request": {
                "operation": "delete_stack",
                "name": "A",
                "stackId": stack.replace("stack-id", "previous-stack"),
                "token": "previous",
                "settled": True,
                "trackingReason": "ORIGINAL_STACK_DELETED",
                "result": "SETTLED",
                "originalStack": {"StackStatus": "ABSENT"},
            },
            "result": "UNKNOWN",
        }
    observed = {
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "StackId": stack,
        "ChangeSetId": change,
        "Changes": [],
    }
    arguments = {
        "StackName": stack,
        "ChangeSetName": change,
        "ClientRequestToken": "execute",
    }
    request, progress = tmp_path / "request.json", tmp_path / "progress.json"
    request.write_text(json.dumps(prior), encoding="utf-8")
    request.chmod(0o600)

    save = partial(handoff_test_save, boundary, tmp_path, progress, state)

    backend = SimpleNamespace(
        target={"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
        states={"A": state},
        aws=Mock(return_value=observed),
        save=save,
    )
    transport = Mock(side_effect=OSError("transport interrupted"))
    replace = current_request.atomic_replace_file

    replace_file = partial(handoff_test_replace_file, boundary, replace)

    with (
        patch.object(current_request, "location", return_value=request),
        patch.object(
            current_state,
            "read",
            return_value={"StackId": stack, "StackStatus": "UPDATE_COMPLETE"},
        ),
        patch.object(current_request, "atomic_replace_file", side_effect=replace_file),
    ):
        with pytest.raises(OSError):
            current_request.send(backend, "execute_change_set", arguments, transport)
    saved_request = json.loads(request.read_text())
    assert saved_request["operation"] == (
        "execute_change_set"
        if boundary in {"after_replace", "transport"}
        else "create_change_set"
    )
    assert transport.call_count == (1 if boundary == "transport" else 0)
    if boundary != "save":
        assert worktree.read_sealed(tmp_path, progress)["endedRequest"]["request"][
            "token"
        ] == ("previous" if previous else "create")
    if boundary in {"after_replace", "transport"}:
        assert saved_request["submission"] == "SENDING"
        with (
            patch.object(current_request, "location", return_value=request),
            patch.object(
                current_state,
                "read",
                return_value={"StackId": stack, "StackStatus": "UPDATE_COMPLETE"},
            ),
        ):
            backend.aws = Mock(
                side_effect=lambda operation, **kwargs: observed
                if operation == "describe_change_set"
                else {"StackEvents": []}
            )
            with pytest.raises(Blocked):
                current_request.send(
                    backend, "execute_change_set", arguments, transport
                )
        assert transport.call_count == (1 if boundary == "transport" else 0)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
