"""Short-operation decisions and complete identifier coverage, without AWS or worktrees."""

import base64
import copy
import json
import os
import stat
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
    completion,
    controller,
    current_state,
    failures,
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
from deploy import progress as deploy_progress
from model.core import properties, stack_model, validate_model_keys
from model.observed import verify_observed_outputs
from model.projection import observed_value
from support.cloudformation_deploy_fixtures import Fake, advance_group, states, units
from support.fixture_cases import load_case
from support.pytest_cli import run
from support.regression_cases import case_ids
from utils import local_evidence
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked

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


def checkpoint_pending_is_unfinished_even_after_observed_case(monkeypatch, case):
    data = case["data"]
    states = copy.deepcopy(data["states"])
    backend = SimpleNamespace(
        phase=data["phase"],
        task_status=data["taskStatus"],
        states=states,
        run_context={
            **data["context"],
            "states": states,
            "gitPublication": copy.deepcopy(data["publication"]),
        },
    )
    backend.run_context["syncPending"] = {"stacks": ["A"], "final": True}
    report = steps.describe(backend)
    assert report["result"] != "COMPLETE"
    assert report["states"]["A"]["attempt"] == "SUCCESS"
    assert "gitPublication" not in report
    return report


@pytest.mark.parametrize("case_id", case_ids("deploy_steps", prefix="checkpoint-"))
def check_checkpoint_pending_is_unfinished_even_after_observed(
    monkeypatch, case_runner, case_id
):
    case_runner.run(
        "deploy_steps",
        case_id,
        partial(checkpoint_pending_is_unfinished_even_after_observed_case, monkeypatch),
    )


def intermediate_sync_does_not_finish_unattempted_deploy_case(case):
    data = case["data"]
    saved = {"status": data["status"], "observedSynced": True, "checkpointed": True}
    state = {"A": saved}
    backend = SimpleNamespace(
        states=state, run_context={"states": state, "snapshotValidation": "PASS"}
    )
    report = steps.describe(backend)
    TestCase().assertNotEqual(report["result"], "COMPLETE")
    state["B"] = {
        "status": "SETTLED",
        "attemptResult": "UNKNOWN",
        "observedSynced": True,
    }
    TestCase().assertNotEqual(steps.describe(backend)["result"], "COMPLETE")
    return {"initial": report, "unknownPeer": steps.describe(backend)}


@pytest.mark.parametrize("case_id", case_ids("deploy_steps", prefix="intermediate-"))
def check_intermediate_sync_does_not_finish_unattempted_deploy(case_runner, case_id):
    case_runner.run(
        "deploy_steps",
        case_id,
        intermediate_sync_does_not_finish_unattempted_deploy_case,
    )


def failed_attempt_cannot_finish_with_unstarted_stack_case(case):
    data = case["data"]
    states = copy.deepcopy(data["states"])
    backend = SimpleNamespace(
        states=states, run_context={**data["context"], "states": states}
    )
    report = steps.describe(backend)
    TestCase().assertNotEqual(report["result"], "COMPLETE")
    return report


@pytest.mark.parametrize("case_id", case_ids("deploy_steps", prefix="failed-"))
def check_failed_attempt_cannot_finish_with_unstarted_stack(case_runner, case_id):
    case_runner.run(
        "deploy_steps", case_id, failed_attempt_cannot_finish_with_unstarted_stack_case
    )


def unknown_poll_stops_without_resubmit_case(case):
    data = case["data"]
    scoped = units(*data["orders"])
    state = states(scoped)
    backend = Fake(completions=data["completions"])
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
    TestCase().assertTrue(state["A"]["clientToken"] == token)
    TestCase().assertTrue(len([e for e in backend.events if e[0] == "start"]) == 1)
    return {"report": result, "events": [list(event) for event in backend.events]}


@pytest.mark.parametrize("case_id", case_ids("deploy_steps", prefix="unknown-"))
def check_unknown_poll_stops_without_resubmit(case_runner, case_id):
    case_runner.run("deploy_steps", case_id, unknown_poll_stops_without_resubmit_case)


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
    assert "private-value" not in json.dumps(
        cli_guidance.safe_error(cli_guidance.DeployStepBlocked("private-value"))
    )


def check_safe_failure_diagnostics_distinguish_root_rollback_and_unknown():
    template = {"Resources": {"Bucket": {"Properties": {"BucketName": "x"}}}}
    first = failures.event(
        {
            "LogicalResourceId": "Bucket",
            "ResourceType": "AWS::S3::Bucket",
            "ResourceStatus": "CREATE_FAILED",
            "EventId": "first",
            "Timestamp": "2026-01-01T00:00:01Z",
            "ResourceStatusReason": "private-value BucketName (HandlerErrorCode: InvalidRequest)",
        },
        template,
    )
    rollback = failures.event(
        {
            "LogicalResourceId": "Bucket",
            "ResourceStatus": "DELETE_FAILED",
            "EventId": "second",
            "Timestamp": "2026-01-01T00:00:02Z",
            "ResourceStatusReason": "private-value",
        },
        template,
    )
    state = {
        "status": "FAILED",
        "stackId": "stack",
        "failureEvents": [rollback, first],
        "eventReadStatus": "COMPLETE",
    }
    diagnostic = failures.diagnostic(state)
    assert diagnostic["eventId"] == "first"
    assert diagnostic["code"] == "InvalidRequest"
    assert diagnostic["resource"]["LogicalResourceId"] == "Bucket"
    assert diagnostic["resource"]["properties"] == ["BucketName"]
    assert diagnostic["reasonRedacted"]
    assert "private-value" not in json.dumps(state) + json.dumps(diagnostic)
    state.update(
        failureClassification="HUMAN_REQUIRED",
        failure={
            "classification": "HUMAN_REQUIRED",
            "stage": "RECOVERY",
            "code": "RECOVERY_BLOCKED",
            "message": "Recovery blocked",
            "requiredAction": "Review recovery",
            "previousFailure": {"code": "older"},
        },
    )
    separated = failures.diagnostic(state)
    assert separated["primaryFailure"]["code"] == "InvalidRequest"
    assert separated["primaryFailure"]["eventId"] == "first"
    assert separated["recoveryFailure"]["code"] == "RECOVERY_BLOCKED"
    assert "eventId" not in separated["recoveryFailure"]
    assert separated["requiredAction"] == "Review recovery"
    state["attemptResult"] = "UNKNOWN"
    unconfirmed = failures.diagnostic(state)
    assert unconfirmed["code"] == "SUBMISSION_UNKNOWN"
    assert "primaryFailure" not in unconfirmed and "eventId" not in unconfirmed
    assert not unconfirmed["retryable"]
    state.pop("attemptResult")
    state["failureEvents"] = [rollback]
    assert failures.diagnostic(state)["primaryFailure"]["code"] == "UNKNOWN_REASON"
    state.pop("failureClassification")
    state.pop("failure")
    duplicate = dict(first, LogicalResourceId="Other", EventId="same-time")
    state["failureEvents"] = [first, duplicate]
    assert failures.diagnostic(state)["code"] == "UNKNOWN_REASON"
    assert "eventId" not in failures.diagnostic(state)
    state.update(failureEvents=[rollback], eventReadStatus="EVENT_READ_FAILED")
    assert failures.diagnostic(state)["code"] == "EVENT_READ_FAILED"
    state.update(status="BLOCKED", attemptResult="UNKNOWN")
    assert failures.diagnostic(state)["code"] == "SUBMISSION_UNKNOWN"
    denied = {"status": "BLOCKED"}
    failures.exception(
        denied,
        AwsError("cloudformation", "create_change_set", "AccessDenied"),
        "CHANGESET_REVIEW",
    )
    assert failures.diagnostic(denied)["classification"] == "AUTHORIZATION"
    assert failures.diagnostic(denied)["code"] == "AccessDenied"
    observed = current_state.observation(
        {
            "StackStatus": "CREATE_FAILED",
            "StackStatusReason": "private-value (HandlerErrorCode: InvalidRequest)",
        }
    )
    assert observed["statusReason"]["code"] == "InvalidRequest"
    assert "private-value" not in json.dumps(observed)
    unknown = {"status": "RUNNING"}
    error = AwsError("cloudformation", "execute_change_set", "ReadTimeoutError")
    error.deploy_operation = "execute_change_set"
    failures.exception(unknown, error, "EXECUTE")
    result = failures.diagnostic(unknown)
    assert (
        result["operation"] == "execute_change_set"
        and result["code"] == "ReadTimeoutError"
    )
    assert not result["retryable"]


@pytest.mark.parametrize(
    "stack_status",
    ["CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UPDATE_ROLLBACK_IN_PROGRESS"],
)
def check_observed_resource_progress_deduplicates_and_marks_uncertainty(stack_status):
    common = {
        "StackId": "stack-a",
        "ClientRequestToken": "current",
        "ResourceType": "AWS::S3::Bucket",
    }
    start = {
        **common,
        "LogicalResourceId": "Bucket",
        "ResourceStatus": "CREATE_IN_PROGRESS",
        "EventId": "one",
        "Timestamp": "2026-01-01T00:00:01Z",
    }
    complete = {
        **start,
        "ResourceStatus": "CREATE_COMPLETE",
        "EventId": "two",
        "Timestamp": "2026-01-01T00:00:02Z",
    }
    active = {
        **start,
        "LogicalResourceId": "Key",
        "ResourceStatus": "UPDATE_IN_PROGRESS",
        "EventId": "three",
    }
    foreign = {
        **start,
        "LogicalResourceId": "Foreign",
        "ClientRequestToken": "old",
        "EventId": "four",
    }
    other_stack = {
        **start,
        "LogicalResourceId": "OtherStack",
        "StackId": "stack-b",
        "EventId": "five",
    }
    stack = {"StackId": "stack-a", "StackStatus": stack_status, "observedAt": "now"}
    root = {
        "StackId": "stack-a",
        "ClientRequestToken": "current",
        "PhysicalResourceId": "stack-a",
        "ResourceStatus": stack_status,
        "Timestamp": "2026-01-01T00:00:00Z",
    }
    progress = current_state.event_progress(
        stack,
        [root, start, complete, complete, active, foreign, other_stack],
        "current",
        "stack-a",
        "A",
    )
    assert progress["available"] and progress["partial"]
    assert (
        progress["observedResources"],
        progress["completed"],
        progress["inProgress"],
        progress["failed"],
    ) == (2, 1, 1, 0)
    assert [item["logicalId"] for item in progress["activeResources"]] == ["Key"]
    assert len(progress["resources"]) == 2 and not progress["resourcesTruncated"]
    assert progress["resourcesOmitted"] == 0
    many = [
        {
            **start,
            "LogicalResourceId": f"Item{i:03}",
            "EventId": f"large-{i}",
            "ResourceStatus": "CREATE_FAILED"
            if i == 100
            else "CREATE_IN_PROGRESS"
            if i == 99
            else "CREATE_COMPLETE",
        }
        for i in range(101)
    ]
    large = current_state.event_progress(
        stack, [root, *many, foreign, other_stack], "current", "stack-a", "A"
    )
    assert (
        large["observedResources"],
        large["completed"],
        large["inProgress"],
        large["failed"],
    ) == (101, 99, 1, 1)
    assert len(large["resources"]) == 30 and large["resourcesOmitted"] == 71
    assert large["resourcesTruncated"]
    assert {item["logicalId"] for item in large["resources"][:2]} == {
        "Item099",
        "Item100",
    }
    assert "percent" not in progress and "total" not in progress
    missing_token = current_state.event_progress(
        stack,
        [root, active, {**complete, "ClientRequestToken": None}],
        "current",
        "stack-a",
        "A",
    )
    assert missing_token["partial"] and missing_token["inProgress"] == 1
    assert not current_state.event_progress(stack, [active], None, "stack-a", "A")[
        "available"
    ]
    assert not current_state.event_progress(
        stack, [active], "current", "old-stack", "A"
    )["available"]
    failure = {
        **start,
        "ResourceStatus": "CREATE_FAILED",
        "EventId": "failure",
        "ResourceStatusReason": "private-value (HandlerErrorCode: InvalidRequest)",
    }
    recovered = current_state.event_progress(
        stack, [root, failure, complete], "current", "stack-a", "A"
    )
    assert recovered["failed"] == 0 and recovered["completed"] == 1
    assert recovered["recentFailures"][0]["eventId"] == "failure"
    assert "private-value" not in json.dumps(recovered)
    incomplete = current_state.event_progress(
        stack, [root, {**active, "Timestamp": None}], "current", "stack-a", "A"
    )
    assert incomplete["partial"] and incomplete["observedResources"] == 0
    unknown_boundary = current_state.event_progress(
        stack, [complete], "current", "stack-a", "A"
    )
    assert (
        not unknown_boundary["countsAvailable"]
        and unknown_boundary["completed"] is None
    )
    rollback = {**stack, "StackStatus": "UPDATE_ROLLBACK_IN_PROGRESS"}
    rollback_start = {
        **root,
        "ResourceStatus": "UPDATE_ROLLBACK_IN_PROGRESS",
        "Timestamp": "2026-01-01T00:00:03Z",
    }
    after_rollback = current_state.event_progress(
        rollback, [failure, complete, rollback_start], "current", "stack-a", "A"
    )
    assert (
        after_rollback["completed"] == 0
        and after_rollback["recentFailures"][0]["eventId"] == "failure"
    )


@pytest.mark.parametrize(
    "output,physical,expected",
    [
        ("fl-new", "fl-new", "`fl-new`"),
        (None, "fl-new", "`fl-new`"),
        ("fl-other", "fl-new", None),
    ],
)
def check_flowlog_observed_identifier(tmp_path, output, physical, expected):
    source = tmp_path / "model/dev/app/vpc.properties"
    resource = {"resourceType": "EC2.FlowLog", "logicalId": "EC2_FlowLog_001"}
    rows = [("001-001", {"property": "EC2.FlowLog.Id"})]
    mapped = {"A": {"Flow": (source, "001", resource, rows, {"EC2.FlowLog.Id"})}}
    document = {
        "Resources": {"Flow": {"Type": "AWS::EC2::FlowLog"}},
        "Outputs": {"FlowId": {"Value": {"Ref": "Flow"}}},
    }
    stack = {
        "StackId": "stack",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": []
        if output is None
        else [{"OutputKey": "FlowId", "OutputValue": output}],
    }
    backend = SimpleNamespace(
        root=tmp_path,
        environment="dev",
        directory="app",
        target={"awsRegion": "region", "awsAccountId": "account"},
        templates={"A": (document, {})},
        aws=Mock(
            side_effect=[
                {"Stacks": [stack]},
                {
                    "StackResourceSummaries": [
                        {
                            "LogicalResourceId": "Flow",
                            "ResourceType": "AWS::EC2::FlowLog",
                            "ResourceStatus": "CREATE_COMPLETE",
                            "PhysicalResourceId": physical,
                        }
                    ]
                },
                {"Stacks": [stack]},
            ]
        ),
    )
    catalog = Mock()
    catalog.schema.return_value = {"primaryIdentifier": ["/properties/Id"]}
    loaded = {source: {"observed.row.001-001.value": "`PENDING_DEPLOY`"}}
    state = {"A": {"status": "SUCCESS"}}
    with (
        patch.object(observed, "DesignSchemaCatalog", return_value=catalog),
        patch.object(observed, "resolve_resources", return_value=(loaded, mapped)),
        patch.object(observed, "own_key", return_value="self"),
        patch.object(observed, "propagate_references"),
        patch.object(
            observed, "observed_destinations", return_value=({}, [], None)
        ) as destinations,
    ):
        observed.collect_successful(backend, [{"name": "A"}], state)
    assert (
        destinations.call_args.args[4][source]["observed.row.001-001.value"] == expected
    )
    assert state["A"]["observedCoverage"]["Flow"]["status"] == (
        "UPDATED" if expected else "UNCONFIRMED"
    )


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


@pytest.mark.parametrize(
    "output,expected", [("policy-id", "`policy-id`"), (None, None)]
)
def test_queue_policy_getatt_observation(tmp_path, output, expected):
    source = tmp_path / "model/dev/app/sqs.properties"
    resource = {"resourceType": "SQS.QueuePolicy", "logicalId": "SQS_QueuePolicy_001"}
    rows = [("001-001", {"property": "SQS.QueuePolicy.Id", "value": "ref"})]
    mapped = {"A": {"Policy": (source, "001", resource, rows, {"SQS.QueuePolicy.Id"})}}
    stack = {
        "StackId": "stack",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": []
        if output is None
        else [{"OutputKey": "PolicyId", "OutputValue": output}],
    }
    backend = SimpleNamespace(
        run_context={},
        root=tmp_path,
        environment="dev",
        directory="app",
        target={"awsRegion": "region", "awsAccountId": "account"},
        templates={
            "A": (
                {
                    "Resources": {"Policy": {"Type": "AWS::SQS::QueuePolicy"}},
                    "Outputs": {
                        "PolicyId": {"Value": {"Fn::GetAtt": ["Policy", "Id"]}}
                    },
                },
                {},
            )
        },
        aws=Mock(
            side_effect=[
                {"Stacks": [stack]},
                {
                    "StackResourceSummaries": [
                        {
                            "LogicalResourceId": "Policy",
                            "ResourceType": "AWS::SQS::QueuePolicy",
                            "ResourceStatus": "CREATE_COMPLETE",
                            "PhysicalResourceId": "unproven-physical-id",
                        }
                    ]
                },
                {"Stacks": [stack]},
            ]
        ),
    )
    state = {
        "A": {"status": "SUCCESS", "stackId": "stack", "stackStatus": "CREATE_COMPLETE"}
    }
    with (
        patch.object(observed, "DesignSchemaCatalog"),
        patch.object(
            observed,
            "resolve_resources",
            return_value=(
                {source: {"observed.row.001-001.value": "`PENDING_DEPLOY`"}},
                mapped,
            ),
        ),
        patch.object(observed, "own_key", return_value="self"),
        patch.object(observed, "propagate_references"),
        patch.object(
            observed, "observed_destinations", return_value=({}, [], None)
        ) as destinations,
    ):
        observed.sync_successful(backend, [{"name": "A"}], state)
    assert (
        destinations.call_args.args[4][source]["observed.row.001-001.value"] == expected
    )
    assert state["A"]["observedCoverage"]["Policy"]["status"] == (
        "UPDATED" if output else "UNCONFIRMED"
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

    def test_restarting_clears_unexecuted_reason(self):
        scoped = units(10)
        state = states(scoped)
        state["A"]["unexecutedReason"] = "DEPLOY_ENDED_WITHOUT_EXECUTION"
        scheduler.run_group(scoped, 1, state, Fake())
        self.assertNotIn("unexecutedReason", state["A"])
        state["A"]["unexecutedReason"] = "stale"
        current_state.record_attempt(state["A"], "UPDATE_COMPLETE")
        self.assertNotIn("unexecutedReason", state["A"])




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
        scoped = units(
            *load_case("deploy_steps", "settled-order-input")["data"]["orders"]
        )
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
        self.assertTrue(completion.attempts_finished({"A": state}, "UNKNOWN"))
        self.assertEqual(state["attemptResult"], "UNKNOWN")










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
        self.assertEqual(state["status"], "SUCCESS")


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
                with nullcontext():
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
                    steps.deploy_progress, "read_task", return_value={"runContext": saved}
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
        task = SimpleNamespace(name="tasks/deploy.md", status="running", task_digest="current")
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
            patch.object(steps.context, "load_target", return_value=target),
        ):
            self.assertIs(steps.guard_local_publication(backend, task), task)
        backend.file_digest.assert_not_called()
        backend.input_digest.assert_not_called()



    def test_generation_is_independent_of_deploy_result(self):
        states = {
            "A": {"status": "FAILED", "observedSynced": True, "currentStack": {"StackStatus": "ROLLBACK_COMPLETE"}}
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
        progress_destination=deploy_progress.progress_path(root, create=True),
    )


def check_progress_initialization_private_and_resumable(tmp_path, monkeypatch):
    monkeypatch.setattr(local_evidence.tempfile, "gettempdir", lambda: str(tmp_path))
    old = os.umask(0o022)
    try:
        path = deploy_progress.progress_path(tmp_path / "project", create=True)
        for directory in (path.parent, path.parent.parent, path.parent.parent.parent):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        context = {
            "states": {"A": {"status": "SUCCESS"}},
            "inputDigests": {"A": "hash"},
        }
        backend = progress_backend(tmp_path / "project", context)
        with operation_journal.locked(path):
            deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
        with operation_journal.locked(
            deploy_progress.progress_path(backend.root, create=True)
        ):
            assert (
                deploy_progress.read_progress(
                    backend.root, {"deployIdentity": backend.progress_identity}
                )["runContext"]["states"]["A"]["status"]
                == "SUCCESS"
            )
    finally:
        os.umask(old)


@pytest.mark.parametrize("unsafe", ["permissions", "owner", "symlink"])
@pytest.mark.parametrize("level", [0, 1, 2])
def check_progress_rejects_unsafe_directories(tmp_path, monkeypatch, unsafe, level):
    monkeypatch.setattr(local_evidence.tempfile, "gettempdir", lambda: str(tmp_path))
    root = tmp_path / "project"
    path = deploy_progress.progress_path(root, create=True)
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
        "unsafe local evidence"
        if unsafe == "owner"
        else None
    )
    with pytest.raises(ValueError, match=expected):
        deploy_progress.progress_path(root, create=True)


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
    pending = {"stacks": ["A"], "final": final}
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
            "syncPending": pending,
        },
    )
    if generation:
        backend.run_context["pendingGeneration"] = {"view": {}}
    with (
        patch.object(steps, "task_snapshot"),
    ):
        if not final and "A" in names and (names == ["A"] or generation):
            with pytest.raises(RuntimeError, match="selected snapshot"):
                steps.sync(backend, names)
            TestCase().assertEqual(backend.run_context["syncPending"]["stacks"], sorted(names))
            backend.save.assert_called_once()
        else:
            with pytest.raises(
                steps.Blocked, match="Stack scope"
            ):
                steps.sync(backend, names)
            TestCase().assertEqual(pending["stacks"], ["A"])
            backend.save.assert_not_called()
    backend.claim_inputs.assert_not_called()


def finish_or_collect(context, collected, _backend, units, _states):
    if context.get("pendingObserved"):
        context.pop("pendingObserved")
        collected.append(["saved A"])
    else:
        collected.append([unit["name"] for unit in units])


@pytest.mark.parametrize("names", [["A"], ["A", "B"]])
def check_pending_observed_finishes_before_collecting_other_stacks(tmp_path, names):
    context = {
        "inputDigests": {"A": "a", "B": "b"},
        "syncPending": {"stacks": ["A"], "final": False},
        "pendingObserved": {"evidence": {"A": {}}},
        "pendingGeneration": {"view": {}},
    }
    backend = SimpleNamespace(
        root=tmp_path,
        phase="update",
        target={},
        environment="dev",
        directory="team",
        units=[{"name": "A"}, {"name": "B"}],
        states={"A": {}, "B": {}},
        run_context=context,
        guard=Mock(),
        save=Mock(),
    )
    collected = []

    with (
        patch.object(steps, "task_snapshot"),
        patch.object(steps.observed_resume, "reconcile"),
        patch.object(steps.generation_resume, "recover_publications"),
        patch.object(steps.generation_resume, "run"),
        patch.object(
            steps.observed,
            "sync_successful",
            side_effect=partial(finish_or_collect, context, collected),
        ),
        patch.object(steps.completion, "validate_local"),
    ):
        steps.sync(backend, names)
    assert collected == ([["saved A"], ["B"]] if "B" in names else [["saved A"]])
    assert context["pendingGeneration"] == {"view": {}}


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
    assert controller.poll(backend, {"name": "A"}, state) == "UNCONFIRMED"
    assert state["attemptResult"] == "UNKNOWN"


def check_refresh_only_reads_selected_sync_stacks_once():
    backend = SimpleNamespace(
        units=[{"name": "A"}, {"name": "B"}],
        states={"A": {"status": "NOT_STARTED"}, "B": {"status": "SUCCESS", "observedSynced": True}},
        aws=Mock(return_value={"Stacks": [{"StackId": "a", "StackStatus": "UPDATE_COMPLETE"}]}),
    )
    current_state.refresh(backend, [backend.units[0]])
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
        state.update(status="RUNNING")
    elif condition in {"approval", "authorization"}:
        state.update(status="BLOCKED", failure={"classification": condition.upper()})
    elif condition == "ended-unknown":
        state.update(
            status="SETTLED",
            attemptResult="UNKNOWN",
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




if __name__ == "__main__":
    raise SystemExit(run(__file__))
