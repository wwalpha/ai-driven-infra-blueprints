"""Short-operation decisions and complete identifier coverage, without AWS or worktrees."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import cli_guidance, observed, operation_journal, recovery, scheduler, steps
from support.cloudformation_deploy_fixtures import Fake, states, units
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


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
        states=states,
        run_context={"states": states, "gitPublication": {"status": "CONFLICT"}},
    )
    report = steps.describe(backend)
    assert report["result"] == "PUBLICATION_PENDING"
    assert report["states"]["A"]["aws"] == "SUCCESS"
    assert report["gitPublication"]["status"] == "CONFLICT"


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
        states=states,
        run_context={
            "states": states,
            "gitPublication": {"status": status, "nextActions": actions},
        },
    )
    report = steps.describe(backend)
    assert report["result"] == (
        "COMPLETE" if status == "SUCCESS" else "PUBLICATION_PENDING"
    )
    assert report["nextActions"] == actions
    backend.run_context["checkpointPending"] = {"stacks": ["A"], "after": {}}
    assert steps.describe(backend)["result"] != "COMPLETE"
    backend.run_context.pop("checkpointPending")
    states["A"]["status"] = "FAILED"
    assert steps.describe(backend)["result"] == "STOPPED"


def check_unknown_poll_stops_without_resubmit():
    scoped = units(10)
    state = states(scoped)
    backend = Fake(completions={"A": ["UNRECOGNIZED"]})
    scheduler.run_group(scoped, 1, state, backend, single_step=True)
    token = state["A"]["clientToken"]
    assert scheduler.run_group(scoped, 1, state, backend, single_step=True) == "STOPPED"
    result = steps.describe(
        SimpleNamespace(run_context={"states": state}, states=state)
    )
    assert result["result"] == "STOPPED"
    assert {"action": "advance"} not in result["nextActions"]
    assert state["A"]["clientToken"] == token
    assert len([e for e in backend.events if e[0] == "start"]) == 1


def check_corrupt_journal_is_never_reset(tmp_path):
    journal = tmp_path / "journal.json"
    journal.write_text("broken", encoding="utf-8")
    journal.chmod(0o600)
    backend = SimpleNamespace(units=[{"name": "A"}])
    with patch.object(operation_journal, "write_records") as write:
        with pytest.raises(ValueError):
            steps.restore(backend, journal, SimpleNamespace(name="tasks/deploy.md"))
    assert journal.read_text(encoding="utf-8") == "broken"
    write.assert_not_called()


def check_runtime_cleanup_returns_after_one_read():
    aws = Mock(return_value={"Stacks": [{"StackStatus": "DELETE_IN_PROGRESS"}]})
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


@pytest.mark.parametrize("missing", [False, True])
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
                            "ResourceType": "AWS::EC2::VPC",
                            **({} if missing else {"PhysicalResourceId": "vpc-actual"}),
                        }
                    ]
                },
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
        patch.object(observed, "reference_key", return_value="self"),
        patch.object(observed, "own_key", return_value="self"),
        patch.object(observed, "propagate_references"),
        patch.object(observed, "observed_destinations", return_value=({}, [], None)),
    ):
        if missing:
            with pytest.raises(ValueError, match="non-ARN identifier unavailable"):
                observed.sync_successful(backend, [{"name": "A"}], state)
            assert not state["A"].get("observedSynced")
            assert state["A"]["observedCoverage"]["Vpc"]["status"] == "UNRESOLVED"
        else:
            backend.run_context = {}
            observed.sync_successful(backend, [{"name": "A"}], state)
            assert state["A"]["observedSynced"]
            assert state["A"]["observedCoverage"]["Vpc"]["status"] == (
                "MATCHED" if already_matches else "UPDATED"
            )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
