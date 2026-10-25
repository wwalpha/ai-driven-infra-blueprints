"""Prove the one historical no-change SUCCESS defect before strict resume validation."""

import copy
from datetime import datetime

from utils.cloudformation.inputs import Blocked

from deploy import change_sets, observed_resume
from deploy.scheduler import SUCCESS


def timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise Blocked("no-change recovery requires timezone-aware AWS timestamps")
    return value


def stack_evidence(stack):
    return {
        key: stack.get(key)
        for key in ("StackId", "StackStatus", "CreationTime", "LastUpdatedTime")
    }


def verified_status(aws, name, state):
    stack_id = state["stackId"]
    change = aws(
        "describe_change_set", StackName=name, ChangeSetName=state["changeSetId"]
    )
    if (
        not change_sets.no_changes(change)
        or change.get("ExecutionStatus") != "UNAVAILABLE"
        or change.get("Changes") != []
        or change.get("ChangeSetId") != state["changeSetId"]
        or change.get("StackId") != stack_id
        or change.get("StackName") != name
    ):
        raise Blocked(
            "no-change recovery cannot prove the saved unexecuted ChangeSet: " + name
        )
    # An AWS cutoff preceding the original SUCCESS avoids relying on controller clock skew.
    cutoff = timestamp(change.get("CreationTime"))
    stacks = aws("describe_stacks", StackName=stack_id).get("Stacks", [])
    if (
        len(stacks) != 1
        or stacks[0].get("StackId") != stack_id
        or stacks[0].get("StackStatus") not in SUCCESS
    ):
        raise Blocked("no-change recovery Stack identity/status differs: " + name)
    stack = stacks[0]
    created = timestamp(stack.get("CreationTime"))
    updated = timestamp(stack.get("LastUpdatedTime", created))
    if created > updated or updated > cutoff:
        raise Blocked("no-change recovery detected a later Stack update: " + name)
    events = aws("describe_stack_events", StackName=stack_id).get("StackEvents")
    if not isinstance(events, list) or not events:
        raise Blocked("no-change recovery has no Stack Events: " + name)
    terminal = False
    for event in events:
        when = timestamp(event.get("Timestamp"))
        if event.get("StackId") != stack_id or when > cutoff:
            raise Blocked(
                "no-change recovery detected later/foreign Stack Events: " + name
            )
        if (
            event.get("ResourceType") == "AWS::CloudFormation::Stack"
            and event.get("PhysicalResourceId") == stack_id
            and event.get("ResourceStatus") == stack["StackStatus"]
            and when >= updated
        ):
            terminal = True
    if not terminal:
        raise Blocked(
            "no-change recovery lacks the original terminal Stack Event: " + name
        )
    fresh = aws("describe_stacks", StackName=stack_id).get("Stacks", [])
    if len(fresh) != 1 or stack_evidence(fresh[0]) != stack_evidence(stack):
        raise Blocked("no-change recovery Stack changed during verification: " + name)
    return stack["StackStatus"]


def candidate(backend, session):
    """Return a private candidate; only the verified formal Resume caller may save it."""
    plan = session["pendingObserved"]
    missing = [
        name
        for name, saved in plan["evidence"].items()
        if saved.get("stackStatus") is None
    ]
    if not missing:
        return None
    for name, saved in plan["evidence"].items():
        state = session["states"][name]
        if saved != {key: state.get(key) for key in observed_resume.EVIDENCE_FIELDS}:
            raise Blocked("no-change recovery states/plan evidence differs: " + name)
        if name not in missing:
            continue
        if (
            plan["stage"] != "PREPARED"
            or state.get("status") != "SUCCESS"
            or state.get("stackStatus") is not None
            or state.get("reason") != "no changes; existing stack terminal success"
            or state.get("operationType") != "UPDATE"
            or state.get("absentBeforeCreate") is not False
            or state.get("observedSynced")
            or any(
                state.get(key) is not None
                for key in (
                    "executionEvidence",
                    "executionStarted",
                    "clientToken",
                    "changeDigest",
                    "approvedChangeDigest",
                )
            )
            or any(
                not isinstance(state.get(key), str) or not state[key].strip()
                for key in ("stackId", "changeSetId")
            )
        ):
            raise Blocked("not the recoverable no-change SUCCESS defect: " + name)
    result = copy.deepcopy(session)
    for name in missing:
        status = verified_status(backend.aws, name, session["states"][name])
        result["states"][name]["stackStatus"] = status
        result["pendingObserved"]["evidence"][name]["stackStatus"] = status
    return result
