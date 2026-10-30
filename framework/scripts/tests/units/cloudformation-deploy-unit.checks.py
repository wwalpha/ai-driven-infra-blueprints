#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from deploy.scheduler import read_parallel
from support import deploy_controller_fixtures as controller
from support.cloudformation_deploy_fixtures import (
    ROOT,
    TARGET,
    Fake,
    M,
    Path,
    Runtime,
    StubAws,
    finish,
    rejects,
    run,
    scheduler,
    stack_model,
    starts,
    states,
    sys,
    units,
)
from utils.aws import cloudformation as cfn

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_scheduler_transient(failed, poll, /, unit, state):
    if not failed[0]:
        failed[0] = True
        raise M.Blocked("read access temporarily unavailable")
    return poll(unit, state)


def _callback_check_scheduler_read(state, /, unit, snapshot):
    snapshot["readEvidence"] = unit["name"]
    assert "readEvidence" not in state[unit["name"]]
    raise M.Blocked("injected read loss")


def _callback_check_scheduler_save(_state_check_scheduler_42, /):
    _state_check_scheduler_42.trace.append(
        (
            "save",
            _state_check_scheduler_42.state["A"]["status"],
            _state_check_scheduler_42.state["A"].get("clientToken"),
        )
    )
    if _state_check_scheduler_42.state["A"]["status"] == "RUNNING" and (
        _state_check_scheduler_42.boundary == "intent"
        or _state_check_scheduler_42.boundary == "response"
        and starts(_state_check_scheduler_42.fake)
    ):
        raise OSError("injected persistence failure")


def _callback_check_scheduler_submit(_state_check_scheduler_42, /, unit, snapshot):
    assert _state_check_scheduler_42.trace[-1] == (
        "save",
        "RUNNING",
        snapshot["clientToken"],
    )
    _state_check_scheduler_42.execute(unit, snapshot)
    if _state_check_scheduler_42.boundary == "submitted":
        raise TimeoutError("injected uncertain submission")


def check_scheduler():
    # Cases 1 and 4: order barrier, including an early A completion.
    _state_check_scheduler_42 = _CallbackState()
    scoped = units(10, 20, 30)
    _state_check_scheduler_42.state, _state_check_scheduler_42.fake = (
        states(scoped),
        Fake(),
    )
    assert (
        finish(
            scoped, 3, _state_check_scheduler_42.state, _state_check_scheduler_42.fake
        )
        == "COMPLETE"
    )
    assert starts(_state_check_scheduler_42.fake) == ["A", "B", "C"]
    for previous, following in (("A", "B"), ("B", "C")):
        assert _state_check_scheduler_42.fake.events.index(
            ("poll", previous, "CREATE_COMPLETE")
        ) < next(
            i
            for i, e in enumerate(_state_check_scheduler_42.fake.events)
            if e[:2] == ("start", following)
        )
    scoped = units(10, 10, 20)
    _state_check_scheduler_42.state, _state_check_scheduler_42.fake = (
        states(scoped),
        Fake({"B": ["CREATE_IN_PROGRESS"] * 3 + ["CREATE_COMPLETE"]}),
    )
    assert (
        scheduler.run_group(
            scoped,
            2,
            _state_check_scheduler_42.state,
            _state_check_scheduler_42.fake,
            sleep=lambda _: None,
        )
        == "GROUP_COMPLETE"
    )
    assert starts(_state_check_scheduler_42.fake) == ["A", "B"]
    assert _state_check_scheduler_42.state["C"]["status"] == "NOT_STARTED"
    assert (
        finish(
            scoped, 2, _state_check_scheduler_42.state, _state_check_scheduler_42.fake
        )
        == "COMPLETE"
    )
    assert _state_check_scheduler_42.fake.events.index(
        ("poll", "B", "CREATE_COMPLETE")
    ) < next(
        i
        for i, e in enumerate(_state_check_scheduler_42.fake.events)
        if e[:2] == ("start", "C")
    )
    # Cases 2 and 3: slot reuse before B finishes, no template deduplication.
    scoped = units(10, 10, 10)
    _state_check_scheduler_42.state, _state_check_scheduler_42.fake = (
        states(scoped),
        Fake(
            {
                "A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"],
                "B": ["CREATE_IN_PROGRESS"] * 4 + ["CREATE_COMPLETE"],
            }
        ),
    )
    assert (
        finish(
            scoped, 2, _state_check_scheduler_42.state, _state_check_scheduler_42.fake
        )
        == "COMPLETE"
    )
    assert _state_check_scheduler_42.fake.peak == 2 and starts(
        _state_check_scheduler_42.fake
    ) == ["A", "B", "C"]
    assert next(
        i
        for i, e in enumerate(_state_check_scheduler_42.fake.events)
        if e[:2] == ("start", "C")
    ) < _state_check_scheduler_42.fake.events.index(("poll", "B", "CREATE_COMPLETE"))
    assert (
        _state_check_scheduler_42.state["A"]["changeSetId"]
        != _state_check_scheduler_42.state["B"]["changeSetId"]
    )
    assert (
        "prepare",
        "A",
        "app.yaml",
        "a.json",
    ) in _state_check_scheduler_42.fake.events
    assert (
        "prepare",
        "B",
        "app.yaml",
        "b.json",
    ) in _state_check_scheduler_42.fake.events
    # Case 5: detect failure while B runs, drain B, keep C/D unstarted.
    scoped = units(10, 10, 10, 20)
    _state_check_scheduler_42.state, _state_check_scheduler_42.fake = (
        states(scoped),
        Fake(
            {
                "A": [
                    "CREATE_IN_PROGRESS",
                    "ROLLBACK_IN_PROGRESS",
                    "ROLLBACK_COMPLETE",
                ],
                "B": ["CREATE_IN_PROGRESS"] * 3 + ["CREATE_COMPLETE"],
            }
        ),
    )
    assert (
        finish(
            scoped, 2, _state_check_scheduler_42.state, _state_check_scheduler_42.fake
        )
        == "STOPPED"
    )
    assert [s["status"] for s in _state_check_scheduler_42.state.values()] == [
        "FAILED",
        "SUCCESS",
        "SUCCESS",
        "NOT_STARTED",
    ]
    assert (
        starts(_state_check_scheduler_42.fake) == ["A", "B", "C"]
        and not _state_check_scheduler_42.fake.running
    )
    assert (
        scheduler.run_group(
            scoped, 2, _state_check_scheduler_42.state, _state_check_scheduler_42.fake
        )
        == "STOPPED"
    )
    # Restart after a failure was saved but another execution was still running.
    _state_check_scheduler_42.state = states(scoped)
    (
        _state_check_scheduler_42.state["A"]["status"],
        _state_check_scheduler_42.state["B"]["status"],
    ) = "FAILED", "RUNNING"
    _state_check_scheduler_42.fake = Fake(
        {"B": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]}
    )
    _state_check_scheduler_42.fake.running = {"B"}
    assert (
        finish(
            scoped, 2, _state_check_scheduler_42.state, _state_check_scheduler_42.fake
        )
        == "STOPPED"
    )
    assert (
        _state_check_scheduler_42.state["B"]["status"] == "SUCCESS"
        and not _state_check_scheduler_42.fake.running
        and starts(_state_check_scheduler_42.fake) == ["C"]
    )
    # A blocker in B leaves independent A and C in the same Order runnable.
    _state_check_scheduler_42.state, _state_check_scheduler_42.fake = (
        states(scoped),
        Fake({"A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]}, blocked={"B"}),
    )
    assert (
        finish(
            scoped, 2, _state_check_scheduler_42.state, _state_check_scheduler_42.fake
        )
        == "STOPPED"
    )
    assert [s["status"] for s in _state_check_scheduler_42.state.values()] == [
        "SUCCESS",
        "BLOCKED",
        "SUCCESS",
        "NOT_STARTED",
    ]
    assert (
        starts(_state_check_scheduler_42.fake) == ["A", "C"]
        and not _state_check_scheduler_42.fake.running
    )
    # Transient read errors preserve the active token and can recover.
    _state_check_scheduler_42.state, _state_check_scheduler_42.fake = (
        states(scoped),
        Fake({"A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]}),
    )
    poll, failed = _state_check_scheduler_42.fake.poll, [False]
    transient = _bind_framework_callback(
        _callback_check_scheduler_transient, failed, poll
    )
    _state_check_scheduler_42.fake.poll = transient
    assert (
        finish(
            scoped, 2, _state_check_scheduler_42.state, _state_check_scheduler_42.fake
        )
        == "COMPLETE"
    )
    assert (
        starts(_state_check_scheduler_42.fake) == ["A", "B", "C", "D"]
        and _state_check_scheduler_42.state["A"]["status"] == "SUCCESS"
    )

    # Intent persistence failure cannot reach execute; submission loss drains without retrying.
    selected = units(10)
    for _state_check_scheduler_42.boundary in ("intent", "submitted", "response"):
        (
            _state_check_scheduler_42.state,
            _state_check_scheduler_42.fake,
            _state_check_scheduler_42.trace,
        ) = states(selected), Fake(), []
        _state_check_scheduler_42.execute = _state_check_scheduler_42.fake.execute
        save = _bind_framework_callback(
            _callback_check_scheduler_save, _state_check_scheduler_42
        )
        submit = _bind_framework_callback(
            _callback_check_scheduler_submit, _state_check_scheduler_42
        )
        _state_check_scheduler_42.fake.execute = submit
        try:
            result = scheduler.run_group(
                selected,
                1,
                _state_check_scheduler_42.state,
                _state_check_scheduler_42.fake,
                save,
                sleep=lambda _: None,
            )
            assert (
                _state_check_scheduler_42.boundary == "submitted"
                and result == "GROUP_COMPLETE"
            )
        except OSError:
            assert _state_check_scheduler_42.boundary != "submitted"
        assert _state_check_scheduler_42.trace and _state_check_scheduler_42.state[
            "A"
        ].get("clientToken")
        assert starts(_state_check_scheduler_42.fake) == (
            [] if _state_check_scheduler_42.boundary == "intent" else ["A"]
        )
        if _state_check_scheduler_42.boundary != "intent":
            token = _state_check_scheduler_42.state["A"]["clientToken"]
            assert scheduler.run_group(
                selected,
                1,
                _state_check_scheduler_42.state,
                _state_check_scheduler_42.fake,
                sleep=lambda _: None,
                drain_only=True,
            ) == (
                "COMPLETE"
                if _state_check_scheduler_42.boundary == "submitted"
                else "STOPPED"
            )
            assert (
                _state_check_scheduler_42.state["A"]["status"] == "SUCCESS"
                and _state_check_scheduler_42.state["A"]["clientToken"] == token
            )
            assert starts(_state_check_scheduler_42.fake) == ["A"]
    # Worker writes are reflected only by the controller, including error snapshots.
    selected = units(10, 10)
    _state_check_scheduler_42.state = states(selected)
    read = _bind_framework_callback(
        _callback_check_scheduler_read, _state_check_scheduler_42.state
    )
    results = read_parallel(selected, _state_check_scheduler_42.state, read, 2)
    assert len(results) == 2 and all(
        error and snapshot["readEvidence"] == unit["name"]
        for unit, snapshot, _, error in results
    )
    assert all(
        "readEvidence" not in item for item in _state_check_scheduler_42.state.values()
    )


def _controller_sleep_only(options):
    controller.run_context.run_deploy.keywords["sleep"](5)
    controller.run_context.run_group.keywords["sleep"](5)
    assert controller.run_context.run_deploy.keywords["sleep"].args[0] == [5, 5]
    return 0


def check_controller_sleep_injection(tmp_path):
    original = controller.run_context.run_deploy, controller.run_context.run_group
    with patch.object(controller, "main", side_effect=_controller_sleep_only):
        assert (
            controller.invoke(
                tmp_path, tmp_path / "session.json", tmp_path / "aws.json"
            )
            == 0
        )
    assert (
        controller.run_context.run_deploy,
        controller.run_context.run_group,
    ) == original
    with (
        patch.object(controller, "main", side_effect=ValueError("controller failed")),
        pytest.raises(ValueError),
    ):
        controller.invoke(tmp_path, tmp_path / "session.json", tmp_path / "aws.json")
    assert (
        controller.run_context.run_deploy,
        controller.run_context.run_group,
    ) == original
    delays = []
    for _ in range(100):
        controller.fake_sleep(delays, 5)
    with pytest.raises(AssertionError, match="did not terminate"):
        controller.fake_sleep(delays, 5)
    assert delays == [5] * 100


class MarkedString(str):
    pass


def no_change_inputs():
    return (
        {
            "stackId": "stack",
            "changeSetId": "change",
            "operationType": "UPDATE",
            "absentBeforeCreate": False,
            "expectedOutputs": {},
        },
        {
            "Status": "FAILED",
            "StatusReason": "The submitted information didn't contain changes.",
            "ExecutionStatus": "UNAVAILABLE",
            "Changes": [],
            "ChangeSetId": "change",
            "StackId": "stack",
            "StackName": "A",
        },
    )


@pytest.mark.parametrize("status", sorted(scheduler.SUCCESS))
def check_no_change_success_evidence(status):
    state, change = no_change_inputs()
    backend = StubAws()
    with patch.object(
        backend,
        "aws",
        return_value={"Stacks": [{"StackId": "stack", "StackStatus": status}]},
    ) as aws:
        assert backend.review_prepared({"name": "A"}, state, change) == "SUCCESS"
    assert state["stackId"] == "stack" and state["stackStatus"] == status
    aws.assert_called_once_with("describe_stacks", StackName="A")


@pytest.mark.parametrize(
    "record,field,value",
    [
        ("state", "operationType", "CREATE"),
        ("state", "absentBeforeCreate", True),
        ("change", "ExecutionStatus", "AVAILABLE"),
        ("change", "Changes", [{"ResourceChange": {"Action": "Add"}}]),
        ("change", "NextToken", "more"),
        ("change", "NextToken", ""),
        ("change", "ChangeSetId", "other"),
        ("change", "StackName", "other"),
    ]
    + [
        ("state", field, "executed")
        for field in (
            "executionEvidence",
            "executionStarted",
            "clientToken",
            "changeDigest",
            "approvedChangeDigest",
        )
    ]
    + [
        ("change", field, None)
        for field in (
            "ExecutionStatus",
            "Changes",
            "ChangeSetId",
            "StackId",
            "StackName",
        )
    ]
    + [
        ("state", field, None)
        for field in ("operationType", "absentBeforeCreate", "changeSetId", "stackId")
    ],
)
def check_no_change_contradictory_or_missing_proof(record, field, value):
    state, change = no_change_inputs()
    target = state if record == "state" else change
    if value is None:
        target.pop(field)
    else:
        target[field] = value
    original = dict(state)
    backend = StubAws()
    with patch.object(backend, "aws") as aws, pytest.raises(M.Blocked):
        backend.review_prepared({"name": "A"}, state, change)
    aws.assert_not_called()
    assert state.get("stackId") == original.get("stackId")
    assert "stackStatus" not in state and "reason" not in state


@pytest.mark.parametrize(
    "stack,saved_id,change_id",
    [
        (
            {"StackId": "stack", "StackStatus": "UPDATE_ROLLBACK_COMPLETE"},
            "stack",
            "stack",
        ),
        ({"StackId": "other", "StackStatus": "UPDATE_COMPLETE"}, "stack", "stack"),
        ({"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}, None, "stack"),
        ({"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}, "stack", "other"),
        ({"StackId": "stack"}, "stack", "stack"),
        ({"StackStatus": "UPDATE_COMPLETE"}, "stack", "stack"),
        (None, "stack", "stack"),
    ],
)
def check_no_change_invalid_evidence_blocks(stack, saved_id, change_id):
    backend = StubAws()
    state, change = no_change_inputs()
    state["stackId"] = saved_id
    change["StackId"] = change_id
    if stack and stack.get("StackStatus") == "UPDATE_ROLLBACK_COMPLETE":
        with patch.object(backend, "aws", return_value={"Stacks": [stack]}):
            TestCase().assertEqual(
                backend.review_prepared({"name": "A"}, state, change), "SUCCESS"
            )
        return
    with patch.object(
        backend, "aws", return_value={"Stacks": [] if stack is None else [stack]}
    ) as aws:
        with pytest.raises(M.Blocked):
            backend.review_prepared(
                {"name": "A"},
                state,
                change,
            )
    assert "stackStatus" not in state
    assert all(call.args[0] != "execute_change_set" for call in aws.call_args_list)


def check_deployment_input_conditions():
    values = {"desired.deployment.maxConcurrentStacks": "2"}
    for i, unit in enumerate(units(20, 10, 10), 1):
        values.update(
            {f"desired.stack.{i:03}.{key}": value for key, value in unit.items()}
        )
        values[f"display.stack.{i:03}.comment"] = "アプリケーションを配置するstack"
    for field, invalid in (
        ("desired.deployment.maxConcurrentStacks", "0"),
        ("desired.deployment.maxConcurrentStacks", "-1"),
        ("desired.deployment.maxConcurrentStacks", "abc"),
        ("desired.stack.001.deployOrder", "0"),
        ("desired.stack.001.deployOrder", "-1"),
        ("desired.stack.001.deployOrder", "abc"),
    ):
        rejects(
            lambda *, field=field, invalid=invalid: stack_model(
                values | {field: invalid}
            ),
            "integer >= 1",
        )
    missing = dict(values)
    del missing["desired.stack.001.deployOrder"]
    rejects(lambda: stack_model(missing), "requires only")
    missing = dict(values)
    del missing["desired.deployment.maxConcurrentStacks"]
    assert stack_model(missing)[0] == 1
    for field in ("dependsOn", "AfterStack", "DependsOnStack", "Dependencies"):
        rejects(
            lambda *, field=field: stack_model(
                values | {"desired.stack.001." + field: "A"}
            ),
            "requires only",
        )
    assert M.change_sets.import_names(
        {"Fn::ImportValue": {"Fn::Join": ["", [{"Ref": "Prefix"}, "VpcId"]]}},
        {"Prefix": "Network"},
        {},
    ) == {"NetworkVpcId"}
    rejects(
        lambda: M.change_sets.import_names(
            {"Fn::ImportValue": {"Ref": "Resource"}}, {}, {}
        ),
        "unsupported",
    )
    conditional = {
        "Conditions": {
            "Dev": {"Fn::Equals": [{"Ref": "Environment"}, "dev"]},
            "Stg": {"Fn::Not": [{"Condition": "Dev"}]},
            "Active": {
                "Fn::And": [
                    {"Condition": "Dev"},
                    {"Fn::Or": [{"Condition": "Dev"}, {"Condition": "Stg"}]},
                ]
            },
        },
        "Resources": {
            "Mwaa": {
                "Properties": {
                    "Arn": {
                        "Fn::If": [
                            "Active",
                            {"Fn::ImportValue": "DevBucketArn"},
                            {"Fn::ImportValue": "StgBucketArn"},
                        ]
                    }
                }
            },
            "StgOnly": {
                "Condition": "Stg",
                "Properties": {"Arn": {"Fn::ImportValue": "StgRoleArn"}},
            },
        },
        "Outputs": {
            "StgOnly": {"Condition": "Stg", "Value": {"Fn::ImportValue": "StgOutput"}}
        },
    }
    assert M.change_sets.import_names(conditional, {"Environment": "dev"}, {}) == {
        "DevBucketArn"
    }
    assert M.change_sets.import_names(conditional, {"Environment": "stg"}, {}) == {
        "StgBucketArn",
        "StgRoleArn",
        "StgOutput",
    }
    backend = StubAws(["DevBucketArn"])
    backend.templates["A"] = (conditional, {"Environment": "dev"})
    assert backend.prepare(units(1)[0], {"clientToken": "dev-only"}) == "READY"
    backend.templates["A"] = (conditional, {"Environment": "stg"})
    rejects(lambda: backend.check_imports(units(1)[0]), "missing Export")
    conditional["Conditions"]["Dev"] = {"Condition": "Dev"}
    rejects(
        lambda: M.change_sets.import_names(conditional, {"Environment": "dev"}, {}),
        "cyclic Condition",
    )
    conditional["Conditions"]["Dev"] = {"Condition": "Missing"}
    rejects(
        lambda: M.change_sets.import_names(conditional, {"Environment": "dev"}, {}),
        "unresolved",
    )
    conditional["Conditions"]["Dev"] = "true"
    rejects(
        lambda: M.change_sets.import_names(conditional, {"Environment": "dev"}, {}),
        "non-boolean",
    )
    # Decoder scalars are subclasses; parameter values are plain strings.
    conditional["Conditions"]["Dev"] = {
        "Fn::Equals": [{"Ref": "Environment"}, MarkedString("dev")]
    }
    assert M.change_sets.import_names(conditional, {"Environment": "dev"}, {}) == {
        "DevBucketArn"
    }
    backend = Runtime(ROOT, "dev", "123456789012", TARGET, "test")
    with patch.object(cfn, "list_exports", return_value={"Exports": []}) as request:
        backend.aws("list_exports")
        assert request.call_args.args[0][:3] == (
            "test",
            "ap-northeast-1",
            "123456789012",
        )
        configured = {**TARGET, "awsProfile": "configured"}
        for explicit in (None, "configured"):
            backend = Runtime(ROOT, "dev", "123456789012", configured, explicit)
            assert backend.connection[0] == "configured"
        rejects(
            lambda: Runtime(ROOT, "dev", "123456789012", configured, "other"),
            "does not match target awsProfile",
        )
    # Native CFN pseudo parameters describe the stack account, independent of explicit resource IDs.
    execution = "999999999999"
    backend = StubAws([execution + "VpcId"])
    backend.target = {**TARGET, "awsExecutionAccountId": execution}
    backend.templates["A"] = (
        {"Fn::ImportValue": {"Fn::Sub": "${AWS::AccountId}VpcId"}},
        {},
    )
    backend.check_imports(units(1)[0])
    backend.exports = []
    artifact = {
        "resource": "Function",
        "property": "Code",
        "bucket": "bucket",
        "keyPrefix": execution + "/",
    }
    document = {
        "Resources": {
            "Function": {
                "Type": "AWS::Lambda::Function",
                "Properties": {
                    "Code": {
                        "S3Bucket": "bucket",
                        "S3Key": {"Fn::Sub": "${AWS::AccountId}/code.zip"},
                    }
                },
            }
        }
    }
    backend.templates["A"] = (document, {})
    assert (
        backend.artifact_bindings({"name": "A", "artifacts": [artifact]}, document, {})[
            0
        ][0]
        == artifact
    )
    assert backend.target["awsAccountId"] == TARGET["awsAccountId"]
    backend = Runtime(
        ROOT, "dev", "123456789012", {**TARGET, "awsExecutionAccountId": execution}
    )
    assert backend.connection[2] == execution


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
