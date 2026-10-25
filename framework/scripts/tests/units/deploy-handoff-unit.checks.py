"""Problem policy/evidence checks, without AWS, real consumer inputs or Git mutation."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import contracts, controller, failures, handoff, resume
from deploy import retry_policy as policy
from deploy.controller import create_runtime
from deploy.recovery import cleanup_unexecuted
from deploy_handoff import main
from support.cloudformation_deploy_fixtures import TARGET, StubAws
from support.model_sources import allocate_fixture, write_model
from support.pytest_cli import run
from task_contract_core import selected_task, set_status, task_digest
from utils import file_operations
from utils.aws.client import AwsError
from utils.aws_mappings import definition_root
from utils.cloudformation.inputs import Blocked
from utils.file_operations import sha
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.json_format import fingerprint as fingerprint
from utils.sealed_evidence import write_sealed

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def workflow(*problems, budget=20):
    return {
        "budget": budget,
        "reserved": 0,
        "attempts": {},
        "problems": {p: {"observations": [], "attempts": []} for p in problems},
    }


def observed(w, *problems, execution, revision):
    for problem in problems:
        policy.observe(w, problem, {"execution": execution, "revision": revision})


def attempted(w, *problems, revision):
    attempt = policy.reserve(w, "request-" + str(w["reserved"]), problems)
    attempt["acceptedRevision"] = revision
    return attempt


@pytest.mark.parametrize(
    "sequence,expected",
    [
        (("A", "A"), "STOPPED"),
        (("A", "B"), "REPAIR_ALLOWED"),
        (("A", "B", "C"), "REPAIR_ALLOWED"),
        (("A", "B", "A"), "STOPPED"),
    ],
)
def check_problem_sequences(sequence, expected):
    w = workflow("A", "B", "C")
    for index, problem in enumerate(sequence):
        observed(w, problem, execution="execution-" + str(index), revision=index)
        if index:
            for prior in set(sequence[:index]) - {problem}:
                w["problems"][prior]["absentAfterRepair"] = True
        result = policy.decision(w, [problem])
        if index < len(sequence) - 1:
            assert result == "REPAIR_ALLOWED"
            attempted(w, problem, revision=index + 1)
    assert result == expected


def check_unrepaired_peers_and_request_idempotency():
    w = workflow("A", "B")
    observed(w, "A", "B", execution="one", revision=0)
    attempt = policy.reserve(w, "request", ["A"])
    assert policy.reserve(w, "request", ["A"]) is attempt and w["reserved"] == 1
    attempt["acceptedRevision"] = 1
    observed(w, "B", execution="two", revision=1)
    assert policy.decision(w, ["B"]) == "REPAIR_ALLOWED"
    assert not w["problems"]["B"]["attempts"]
    with pytest.raises(ValueError):
        policy.reserve(w, "request", ["B"])


def check_progress_limits_and_budget():
    w = workflow("A", budget=20)
    observed(w, "A", execution="one", revision=0)
    for index in range(3):
        assert policy.decision(w, ["A"]) == "REPAIR_ALLOWED"
        attempted(w, "A", revision=index + 1)
        policy.observe(
            w,
            "A",
            {"execution": str(index), "revision": index + 1},
            ["nested-" + str(index)],
        )
    assert policy.decision(w, ["A"]) == "WAITING_HUMAN"
    w = workflow("A", "B", budget=1)
    observed(w, "A", "B", execution="one", revision=0)
    attempted(w, "A", "B", revision=1)
    assert w["reserved"] == 1 and all(
        len(w["problems"][p]["attempts"]) == 1 for p in ("A", "B")
    )
    assert policy.decision(w, ["B"]) == "WAITING_HUMAN"
    w["budget"] += 1
    assert policy.decision(w, ["B"]) == "REPAIR_ALLOWED"


def check_duplicate_poll_is_not_a_new_failure():
    w = workflow("A")
    observed(w, "A", execution="one", revision=0)
    attempted(w, "A", revision=1)
    observed(w, "A", execution="one", revision=0)
    assert len(w["problems"]["A"]["observations"]) == 1
    assert policy.decision(w, ["A"]) == "REPAIR_ALLOWED"
    observed(w, "A", execution="two", revision=1)
    assert policy.decision(w, ["A"]) == "STOPPED"


@pytest.mark.parametrize(
    "stage,code,service,operation,expected",
    [
        (
            "PREPARATION",
            "ValidationError",
            "cloudformation",
            "validate_template",
            "IAC_CANDIDATE",
        ),
        (
            "PREPARATION",
            "ValidationException",
            "cloudformation",
            "create_change_set",
            "IAC_CANDIDATE",
        ),
        (
            "PREPARATION",
            "AccessDenied",
            "cloudformation",
            "create_change_set",
            "AUTHORIZATION",
        ),
        (
            "PREPARATION",
            "ReadTimeoutError",
            "cloudformation",
            "create_change_set",
            "NEEDS_HUMAN",
        ),
        ("POLL", "ValidationError", "cloudformation", "describe_stacks", "NEEDS_HUMAN"),
        (
            "EXECUTE",
            "ReadTimeoutError",
            "cloudformation",
            "execute_change_set",
            "SUBMISSION_UNKNOWN",
        ),
    ],
)
def check_failure_classes(stage, code, service, operation, expected):
    error = ValueError("must not be persisted as diagnosis")
    error.code, error.deploy_service, error.deploy_operation = code, service, operation
    state = {"status": "RUNNING" if stage == "EXECUTE" else "BLOCKED"}
    failures.exception(state, error, stage)
    assert state["failure"]["classification"] == expected
    assert "must not be persisted" not in json.dumps(state)
    assert failures.repairable({"awsState": state}) == (expected == "IAC_CANDIDATE")


def _lambda_check_effective_inputs_and_safe_events_effective_129(
    artifact, parameters, template, tmp_path, units, /
):
    return handoff.effective(
        tmp_path,
        units,
        lambda u: (template, parameters),
        lambda us: [template, parameters, artifact],
    )


def check_effective_inputs_and_safe_events(tmp_path):
    template, parameters, artifact = [
        tmp_path / p for p in ("template.yaml", "parameters.json", "script.py")
    ]
    template.write_text(
        "Resources: {R: {Type: AWS::EC2::VPC, Properties: {CidrBlock: 10.0.0.0/16}}}\n"
    )
    parameters.write_text("[]")
    artifact.write_text("approved")
    units = [{"name": "Stack"}]
    effective = _bind_framework_callback(
        _lambda_check_effective_inputs_and_safe_events_effective_129,
        artifact,
        parameters,
        template,
        tmp_path,
        units,
    )
    first = effective()
    template.write_text(template.read_text() + "# formatting only\n")
    assert effective() == first
    parameters.write_text('[{"ParameterKey":"Name","ParameterValue":"sensitive"}]')
    assert effective() != first and "sensitive" not in json.dumps(effective())
    second = effective()
    artifact.write_text("different")
    assert effective() != second
    event = {
        "LogicalResourceId": "R",
        "ResourceType": "AWS::EC2::VPC",
        "ResourceStatus": "CREATE_FAILED",
        "ResourceStatusReason": "CidrBlock rejected (HandlerErrorCode: InvalidRequest), RequestId 123, secret-value",
    }
    document = {"Resources": {"R": {"Properties": {"CidrBlock": "10.0.0.0/16"}}}}
    record = failures.event(event, document)
    assert record["properties"] == ["CidrBlock"] and record["code"] == "InvalidRequest"
    assert not any(word in json.dumps(record) for word in ("secret-value", "RequestId"))
    event["ResourceStatusReason"] = (
        "CidrBlock rejected (HandlerErrorCode: InvalidRequest), RequestId 999"
    )
    later = failures.event(event, document)
    assert (
        later["properties"] == record["properties"] and later["code"] == record["code"]
    )


def check_status_helpers_preserve_task_identity():
    text = "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n- Authorized delete/replacement: `none`\n"
    suspended = (
        set_status(text, "suspend") + "\n## Suspension reason\n\n    awaiting child\n"
    )
    assert (
        task_digest(text)
        == task_digest(suspended)
        == task_digest(set_status(suspended, "running"))
    )
    assert task_digest(text) == task_digest(text.replace("`none`", "`change-set`"))
    assert task_digest(text) != task_digest(text + "\n## Other\nchanged\n")


def check_session_save_uses_shared_api(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    session = {"status": "保存", "states": {}}
    text = json.dumps(session, indent=2) + "\n"
    with patch.object(
        handoff, "atomic_replace_file", wraps=file_operations.atomic_replace_file
    ) as save:
        handoff.save(path, session)
    save.assert_called_once_with(path, text, mode=0o666)
    assert path.read_text(encoding="utf-8") == text
    with (
        patch.object(
            handoff, "atomic_replace_file", side_effect=OSError("session save")
        ),
        pytest.raises(OSError, match="session save"),
    ):
        handoff.save(path, session)


def _callback_check_signed_ledger_rejects_rollback_and_recovers_interrupted(
    actual_replace, path, after_replace, /, source, target
):
    if Path(target) == path and not after_replace:
        raise OSError("injected session replacement")
    result = actual_replace(source, target)
    if Path(target) == path:
        raise OSError("injected session replacement")
    return result


@pytest.mark.parametrize("after_replace", [False, True])
def check_signed_ledger_rejects_rollback_and_recovers(tmp_path, after_replace):
    root = tmp_path / "repo"
    root.mkdir()
    path = tmp_path / "state.json"
    session = {
        "repository": str(root),
        "taskFile": "tasks/deploy.md",
        "states": {"Stack": {"status": "NOT_STARTED"}},
    }
    session["workflow"] = handoff.new_workflow()
    session["inputRevision"] = 0
    session.setdefault("workflow", handoff.new_workflow())
    handoff.bind(root, path, session)
    handoff.save(path, session)
    handoff.restore(root, path, json.loads(path.read_text()))
    old = path.read_bytes()
    session["workflow"]["reserved"] = 1
    actual_replace = file_operations.os.replace
    interrupted = _bind_framework_callback(
        _callback_check_signed_ledger_rejects_rollback_and_recovers_interrupted,
        actual_replace,
        path,
        after_replace,
    )
    with (
        patch.object(file_operations.os, "replace", side_effect=interrupted),
        pytest.raises(OSError, match="injected session replacement"),
    ):
        handoff.save(path, session)
    recovered = json.loads(path.read_text())
    handoff.restore(root, path, recovered)
    assert recovered["workflow"]["reserved"] == 1
    altered = json.loads(path.read_text())
    altered.pop("inputRevision")
    with pytest.raises(Blocked, match="ledger"):
        handoff.restore(root, path, altered)
    path.write_bytes(old)
    with pytest.raises((Blocked, ValueError), match="ledger"):
        handoff.restore(root, path, json.loads(path.read_text()))
    path.unlink()
    final = handoff.recover_session(root, path, "tasks/deploy.md")
    assert (
        final["workflow"]["reserved"] == 1
        and final["workflow"]["workflowId"] == session["workflow"]["workflowId"]
    )
    with pytest.raises((Blocked, ValueError), match="original session"):
        handoff.recover_session(root, tmp_path / "new-state.json", "tasks/deploy.md")


def check_total_budget_is_not_three_global_failures():
    names = [str(i) for i in range(21)]
    w = workflow(*names)
    for index, name in enumerate(names[:20]):
        observed(w, name, execution=str(index), revision=index)
        attempted(w, name, revision=index + 1)
    observed(w, names[-1], execution="twenty-one", revision=20)
    assert w["reserved"] == 20 and policy.decision(w, [names[-1]]) == "WAITING_HUMAN"
    w["budget"] += 1
    assert policy.decision(w, [names[-1]]) == "REPAIR_ALLOWED"


def diagnosis_fixture(tmp_path, peer=False):
    root = tmp_path
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "fixture",
                "targets": [
                    {
                        "environment": "dev",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        )
    )
    template = root / "infra/template.yaml"
    template.parent.mkdir()
    template.write_text(
        "Resources: {Item: {Type: AWS::EC2::VPC, Properties: {CidrBlock: wrong, EnableDnsSupport: true}}}"
    )
    if peer:
        template.write_text(
            template.read_text().replace(
                "Resources: {",
                "Resources: {Item2: {Type: AWS::EC2::VPC, Properties: {CidrBlock: wrong}}, ",
            )
        )
    model = root / "model/dev/123456789012/ec2.properties"
    values = {
        "desired.resource.001.resourceType": "EC2.VPC",
        "desired.resource.001.cfn-logicalId": "Stack-Item",
        "desired.row.001-001.property": "EC2.VPC.CidrBlock",
        "desired.row.001-001.value": "10.0.0.0/16",
        "desired.row.001-001.comment": "承認済アドレス",
        "desired.row.001-002.property": "EC2.VPC.EnableDnsSupport",
        "desired.row.001-002.value": "true",
        "desired.row.001-002.comment": "承認済DNS",
    }
    if peer:
        values.update(
            {
                "desired.resource.002.resourceType": "EC2.VPC",
                "desired.resource.002.cfn-logicalId": "Stack-Item2",
                "desired.row.002-001.property": "EC2.VPC.CidrBlock",
                "desired.row.002-001.value": "10.0.0.0/16",
                "desired.row.002-001.comment": "承認済アドレス",
            }
        )
    values.update(allocate_fixture(values, ["001", "002"] if peer else ["001"]))
    write_model(model, values)
    relative, model_relative = (
        template.relative_to(root).as_posix(),
        model.relative_to(root).as_posix(),
    )
    state = {
        "status": "FAILED",
        "stackStatus": "ROLLBACK_COMPLETE",
        "failureEvents": [
            {
                "resourcePath": "Item",
                "ResourceType": "AWS::EC2::VPC",
                "ResourceStatus": "CREATE_FAILED",
                "code": "InvalidRequest",
                "properties": ["CidrBlock"],
            }
        ],
    }
    session = {
        "inputRevision": 0,
        "logicalTarget": ["dev", "account", "region"],
        "modelInputManifest": {model_relative: sha(model)},
        "states": {"Stack": state},
        "unitInputPaths": {"Stack": [relative]},
        "failureObservations": [
            {
                "observationId": "one",
                "stack": "Stack",
                "execution": "token-one",
                "revision": 0,
                "inputManifest": {relative: sha(template)},
                "awsState": state,
            }
        ],
    }
    session["workflow"] = handoff.new_workflow()
    session["workflow"]["latestObservations"] = ["one"]
    problem = {
        "relation": "NEW",
        "relatedProblemIds": [],
        "reason": "The failed CidrBlock differs from the approved Model row in the referenced template.",
        "evidenceRefs": [{"observationId": "one", "revision": 0, "eventIndices": [0]}],
        "observationId": "one",
        "eventIndices": [0],
        "resourcePath": "Item",
        "resourceType": "AWS::EC2::VPC",
        "operation": "CREATE",
        "property": "CidrBlock",
        "constraint": "approved-cidr",
        "cause": "IAC_PROPERTY",
        "inputRefs": [
            {
                "path": relative,
                "sha256": sha(template),
                "pointer": "/Resources/Item/Properties/CidrBlock",
            }
        ],
        "modelRefs": [
            {
                "path": model_relative,
                "sha256": sha(model),
                "key": "desired.row.001-001.value",
            }
        ],
    }
    return session, problem


@pytest.mark.parametrize(
    "pending",
    [
        "generation-only",
        "pendingObserved",
        "success",
        "observedError",
        "running",
        "pollError",
    ],
)
def check_diagnosis_observed_barrier(tmp_path, pending):
    session, problem = diagnosis_fixture(tmp_path)
    session.update(generationError="publication failed", pendingGeneration={"view": {}})
    session["states"]["Peer"] = {"status": "SUCCESS", "observedSynced": True}
    if pending == "pendingObserved":
        session[pending] = {"stage": "MODEL_PUBLISHED"}
    elif pending == "observedError":
        session[pending] = "Observed failure"
    elif pending == "success":
        session["states"]["Peer"]["observedSynced"] = False
    elif pending == "running":
        session["states"]["Peer"]["status"] = "RUNNING"
    elif pending == "pollError":
        session["states"]["Peer"][pending] = "poll failed"
    before = copy.deepcopy(session)
    diagnosis = {"revision": 0, "problems": [problem]}
    if pending == "generation-only":
        assert handoff.diagnose(tmp_path, session, diagnosis) == "REPAIR_ALLOWED"
        assert session["pendingGeneration"] == before["pendingGeneration"]
        assert session["generationError"] == before["generationError"]
    else:
        with pytest.raises(Blocked, match="drain/observe"):
            handoff.diagnose(tmp_path, session, diagnosis)
        assert session == before


@pytest.mark.parametrize(
    "defect",
    [
        "unknown",
        "same-constraint-proof",
        "wrong-property-proof",
        "wrong-sha",
        "wrong-event",
        "uncovered",
    ],
)
def check_ambiguous_new_and_invalid_evidence_rejected(tmp_path, defect):
    session, problem = diagnosis_fixture(tmp_path)
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
        == "REPAIR_ALLOWED"
    )
    first = session["workflow"]["currentProblemIds"][0]
    entry = copy.deepcopy(problem)
    if defect == "unknown":
        entry["property"] = "unknown"
    elif defect == "same-constraint-proof":
        entry.update(constraint="new-claim-only", relatedProblemIds=[first])
    elif defect == "wrong-property-proof":
        entry.update(property="EnableDnsSupport", relatedProblemIds=[first])
    elif defect == "wrong-sha":
        entry["inputRefs"][0]["sha256"] = "bad"
    elif defect == "wrong-event":
        entry["resourcePath"] = "Other"
    else:
        session["failureObservations"][0]["awsState"]["failureEvents"].append(
            {
                "resourcePath": "Unknown",
                "ResourceType": "Custom::Unknown",
                "ResourceStatus": "DELETE_FAILED",
            }
        )
    if defect == "same-constraint-proof":
        assert (
            handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
            == "NEEDS_DIAGNOSIS"
        )
    else:
        with pytest.raises((Blocked, ValueError)):
            handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})


def check_distinct_property_and_request_id_stability(tmp_path):
    session, problem = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
    first = session["workflow"]["currentProblemIds"][0]
    state = session["failureObservations"][0]["awsState"]
    state["failureEvents"][0]["RequestId"] = "different-only"
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
    assert session["workflow"]["currentProblemIds"] == [first]
    other = copy.deepcopy(problem)
    other.update(
        property="EnableDnsSupport", constraint="boolean", relatedProblemIds=[first]
    )
    other["inputRefs"][0]["pointer"] = "/Resources/Item/Properties/EnableDnsSupport"
    other["modelRefs"][0]["key"] = "desired.row.001-002.value"
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [other]})
        == "NEEDS_DIAGNOSIS"
    )
    session["failureObservations"][0]["awsState"]["failureEvents"][0]["properties"] = [
        "EnableDnsSupport"
    ]
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [other]})
        == "REPAIR_ALLOWED"
    )
    assert session["workflow"]["currentProblemIds"] != [first]


@pytest.mark.parametrize(
    "classification,allowed",
    [
        ("IAC_CANDIDATE", True),
        ("INPUT_CANDIDATE", True),
        ("APPROVAL", False),
        ("AUTHORIZATION", False),
        ("SUBMISSION_UNKNOWN", False),
        ("NEEDS_HUMAN", False),
    ],
)
def check_unexecuted_diagnosis_preserves_aws_state(tmp_path, classification, allowed):
    session, problem = diagnosis_fixture(tmp_path)
    state = session["failureObservations"][0]["awsState"]
    state.clear()
    state.update(
        status="BLOCKED",
        failure={
            "classification": classification,
            "executionState": "NOT_EXECUTED",
            "operation": "validate_template",
        },
        failureEvents=[],
    )
    problem.update(eventIndices=[], operation="validate_template")
    problem["evidenceRefs"][0]["eventIndices"] = []
    if allowed:
        assert (
            handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
            == "REPAIR_ALLOWED"
        )
    else:
        with pytest.raises(Blocked):
            handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
    assert state["status"] == "BLOCKED" and "stackStatus" not in state


def _callback_check_unexecuted_shell_recovery_aws(
    calls, change, defect, stack, /, operation, **arguments
):
    calls.append((operation, arguments))
    assert arguments["StackName"] == "original"
    if operation == "describe_stacks":
        if defect == "interrupted":
            raise AwsError(
                "cloudformation", operation, "ValidationError", stack_absent=True
            )
        return {"Stacks": [stack]}
    if operation == "describe_change_set":
        return change
    if operation == "list_stack_resources":
        if defect == "read":
            raise AwsError("cloudformation", operation, "AccessDenied")
        return {"StackResourceSummaries": [{}] if defect == "resources" else []}
    assert operation == "delete_stack"


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "origin",
        "identity",
        "protected",
        "parent",
        "status",
        "change-stack",
        "executed",
        "change-status",
        "resources",
        "read",
        "interrupted",
    ],
)
def check_unexecuted_shell_recovery(defect):
    proof = {
        "stackId": "original",
        "changeSetId": "change",
        "operationType": "CREATE",
        "absentBeforeCreate": True,
    }
    state = {
        "status": "NOT_STARTED",
        "stackId": "original",
        "preExecutionRecovery": proof,
    }
    stack = {"StackId": "original", "StackStatus": "REVIEW_IN_PROGRESS"}
    change = {
        "StackId": "original",
        "ChangeSetId": "change",
        "Status": "FAILED",
        "ExecutionStatus": "UNAVAILABLE",
    }
    if defect == "origin":
        proof["absentBeforeCreate"] = False
    if defect == "identity":
        stack["StackId"] = "reused"
    if defect == "protected":
        stack["EnableTerminationProtection"] = True
    if defect == "parent":
        stack["ParentId"] = "parent"
    if defect == "status":
        stack["StackStatus"] = "CREATE_COMPLETE"
    if defect == "change-stack":
        change["StackId"] = "other"
    if defect == "executed":
        change["ExecutionStatus"] = "EXECUTE_COMPLETE"
    if defect == "change-status":
        change["Status"] = "CREATE_COMPLETE"
    if defect == "interrupted":
        state.update(cleanupStatus="DELETE_INTENT", cleanupStackId="original")
    calls, saves, waits = [], [], []
    aws = _bind_framework_callback(
        _callback_check_unexecuted_shell_recovery_aws, calls, change, defect, stack
    )
    if defect in {"none", "interrupted"}:
        cleanup_unexecuted(
            aws,
            lambda: saves.append(copy.deepcopy(state)),
            lambda s: waits.append(s["stackId"]),
            state,
        )
        assert state["status"] == "NOT_STARTED" and "stackStatus" not in state
        assert (waits == ["original"]) == (defect == "none")
    else:
        with pytest.raises(Blocked):
            cleanup_unexecuted(
                aws,
                lambda: saves.append(copy.deepcopy(state)),
                lambda s: waits.append(s["stackId"]),
                state,
            )
        assert not any(op == "delete_stack" for op, _ in calls)
        assert not waits
    assert saves or defect not in {"none", "interrupted"}


@pytest.mark.parametrize("defect", ["order", "metadata", "missing-previous"])
def check_constraint_identity_ignores_reference_order(tmp_path, defect):
    session, problem = diagnosis_fixture(tmp_path)
    relative = (
        "framework/materials/cloudformation-schema/ap-northeast-1/aws-ec2-vpc.json"
    )
    digest = sha(definition_root(tmp_path) / relative)
    refs = [
        {
            "path": relative,
            "sha256": digest,
            "pointer": "/properties/CidrBlock" + suffix,
        }
        for suffix in ("", "/type")
    ]
    if defect != "missing-previous":
        problem["constraintRefs"] = copy.deepcopy(refs)
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
    original = session["workflow"]["currentProblemIds"][0]
    entry = copy.deepcopy(problem)
    entry.update(
        constraint="same-proofs-new-name",
        relatedProblemIds=[original],
        constraintRefs=list(reversed(refs)),
    )
    if defect == "metadata":
        entry["constraintRefs"][0]["note"] = "not a new constraint"
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
        == "NEEDS_DIAGNOSIS"
    )
    assert list(session["workflow"]["problems"]) == [original]


def _callback_check_bootstrap_history_preserves_distinct_safe_failure_aws(
    identifier, /, operation, **arguments
):
    if operation == "describe_stacks":
        return {"Stacks": [{"StackStatus": "ROLLBACK_COMPLETE"}]}
    assert operation == "describe_stack_events", (
        "non-secret failure must not PUT or clean a shell"
    )
    return {
        "StackEvents": [
            {
                "StackId": "original",
                "ResourceType": "AWS::CloudFormation::Stack",
                "ClientRequestToken": "one",
                "ResourceStatus": "ROLLBACK_COMPLETE",
            },
            {
                "LogicalResourceId": "Item",
                "ResourceType": "AWS::EC2::VPC",
                "ClientRequestToken": "one",
                "ResourceStatus": "CREATE_FAILED",
                "EventId": identifier[0],
                "ResourceStatusReason": "invalid CidrBlock DUMMY_PRIVATE (HandlerErrorCode: InvalidRequest)",
            },
        ]
    }


def check_bootstrap_history_preserves_distinct_safe_failure(tmp_path):
    session, problem = diagnosis_fixture(tmp_path)
    task = tmp_path / "tasks/deploy.md"
    task.parent.mkdir()
    task.write_text(
        "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n"
        "- Runtime recovery: `allowed`\n## Modified files\n- `tasks/deploy.md`\n## Allowed paths\n- `tasks/deploy.md`\n"
    )
    target = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}
    backend = create_runtime(tmp_path, "dev", "123456789012", target)
    unit = {"name": "Stack"}
    document, errors = handoff.decode((tmp_path / "infra/template.yaml").read_bytes())
    assert not errors
    backend.templates["Stack"] = (document, {})
    backend.session = session
    state = session["states"]["Stack"]
    state.update(
        clientToken="one",
        stackId="original",
        repairs=[{"classification": "RUNTIME_BOOTSTRAP", "stage": "RETRY_READY"}],
    )
    identifier = ["request-one"]
    aws = _bind_framework_callback(
        _callback_check_bootstrap_history_preserves_distinct_safe_failure_aws,
        identifier,
    )
    backend.aws = aws
    with selected_task(tmp_path, "tasks/deploy.md"):
        assert backend.poll(unit, state) == "ROLLBACK_COMPLETE"
        assert not backend.repair(unit, state)
        assert state["failureClassification"] == "NEEDS_DIAGNOSIS"
    assert state["failureEvents"][0]["properties"] == ["CidrBlock"]
    assert state["failureEvents"][0]["code"] == "InvalidRequest"
    assert "DUMMY_PRIVATE" not in json.dumps(state)
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
        == "REPAIR_ALLOWED"
    )
    original = session["workflow"]["currentProblemIds"]
    identifier[0] = "different-request-only"
    backend.poll(unit, state)
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
        == "REPAIR_ALLOWED"
    )
    assert session["workflow"]["currentProblemIds"] == original


def next_diagnosis(
    session, entry, *, relation="SAME", related=None, properties=None, code=None
):
    """A distinct AWS execution, with immutable previous observation evidence."""
    previous = session["failureObservations"][-1]
    observation = copy.deepcopy(previous)
    observation.update(
        observationId="obs-" + str(len(session["failureObservations"])),
        execution="exec-" + str(len(session["failureObservations"])),
        revision=session["inputRevision"] + 1,
    )
    if properties is not None:
        observation["awsState"]["failureEvents"][0]["properties"] = properties
    if code is not None:
        observation["awsState"]["failureEvents"][0]["code"] = code
    session["failureObservations"].append(observation)
    session["inputRevision"] = observation["revision"]
    session["workflow"]["latestObservations"] = [observation["observationId"]]
    candidate = copy.deepcopy(entry)
    candidate.update(
        relation=relation,
        relatedProblemIds=related or session["workflow"]["currentProblemIds"],
        observationId=observation["observationId"],
        reason="Compare this distinct AWS execution with the cited prior failure and approved input/Model locations.",
    )
    candidate["evidenceRefs"].append(
        {
            "observationId": observation["observationId"],
            "revision": observation["revision"],
            "eventIndices": [0],
        }
    )
    return candidate


@pytest.mark.parametrize(
    "difference", ["schema-pointer", "label", "request-and-prose", "invalid-value"]
)
def check_relabel_does_not_buy_new_attempt(tmp_path, difference):
    session, entry = diagnosis_fixture(tmp_path)
    schema = "framework/materials/cloudformation-schema/ap-northeast-1/aws-ec2-vpc.json"
    entry["constraintRefs"] = [
        {
            "path": schema,
            "sha256": sha(definition_root(tmp_path) / schema),
            "pointer": "/properties/CidrBlock/type",
        }
    ]
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
    identity = session["workflow"]["currentProblemIds"][0]
    attempted(session["workflow"], identity, revision=1)
    new = next_diagnosis(session, entry, relation="NEW")
    new["constraint"] = "different-name"
    if difference == "schema-pointer":
        new["constraintRefs"][0]["pointer"] = "/properties/CidrBlock"
    elif difference == "request-and-prose":
        session["failureObservations"][-1]["awsState"]["failureEvents"][0].update(
            RequestId="new", reasonDigest="new-prose"
        )
        session["taskFile"] = "tasks/another.md"
    elif difference == "invalid-value":
        path = tmp_path / new["inputRefs"][0]["path"]
        path.write_text(path.read_text().replace("wrong", "still-invalid"))
        digest = sha(path)
        new["inputRefs"][0]["sha256"] = digest
        session["failureObservations"][-1]["inputManifest"][
            new["inputRefs"][0]["path"]
        ] = digest
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 1, "problems": [new]})
        == "NEEDS_DIAGNOSIS"
    )
    assert (
        list(session["workflow"]["problems"]) == [identity]
        and session["workflow"]["reserved"] == 1
    )
    new.update(relation="SAME")
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 1, "problems": [new]})
        == "STOPPED"
    )
    assert session["workflow"]["currentProblemIds"] == [identity]
    # Rewriting the diagnosis and duplicate polling never erase a spent attempt/stop.
    new["constraint"] = "yet-another-name"
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 1, "problems": [new]})
        == "STOPPED"
    )
    assert len(session["workflow"]["problems"][identity]["observations"]) == 2


@pytest.mark.parametrize(
    "missing",
    [
        "relation",
        "relatedProblemIds",
        "reason",
        "evidenceRefs",
        "prior-reference",
        "prior-comparison",
        "boilerplate",
    ],
)
def check_relation_contract_and_atomic_rejection(tmp_path, missing):
    session, entry = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
    new = next_diagnosis(session, entry, relation="NEW", code="AnotherCode")
    if missing == "prior-reference":
        new["evidenceRefs"] = new["evidenceRefs"][-1:]
    elif missing == "boilerplate":
        new["reason"] = "different cause"
    elif missing == "prior-comparison":
        new["relatedProblemIds"] = []
    else:
        new.pop(missing)
    before = copy.deepcopy(session)
    with pytest.raises(Blocked):
        handoff.diagnose(tmp_path, session, {"revision": 1, "problems": [new]})
    assert session == before


@pytest.mark.parametrize("repairable", [True, False])
def check_unknown_is_durable_and_never_issues_request(tmp_path, repairable):
    session, entry = diagnosis_fixture(tmp_path)
    if not repairable:
        session["failureObservations"][0]["awsState"]["failure"] = {
            "classification": "NEEDS_HUMAN"
        }
    entry.update(
        relation="UNKNOWN",
        reason="The available event does not distinguish the input defect from the runtime constraint; read-only evidence is required.",
    )
    for key in ("cause", "constraint", "property"):
        entry.pop(key)
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
        == "NEEDS_DIAGNOSIS"
    )
    path = tmp_path / "session.json"
    handoff.save(path, session)
    restored = json.loads(path.read_text())
    assert restored["workflow"]["diagnoses"][0]["problems"][0]["relation"] == "UNKNOWN"
    assert not restored["workflow"]["problems"]
    with pytest.raises(ValueError, match="NEEDS_DIAGNOSIS"):
        handoff.issue_request(tmp_path, path, restored, [], [], [])


@pytest.mark.parametrize("target", ["Item/Child", "Item2"])
def check_same_cause_across_resource_targets_shares_attempt_limit(tmp_path, target):
    session, entry = diagnosis_fixture(tmp_path, peer=target == "Item2")
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
    original = session["workflow"]["currentProblemIds"][0]
    attempted(session["workflow"], original, revision=1)
    new = next_diagnosis(session, entry)
    new["resourcePath"] = target
    session["failureObservations"][-1]["awsState"]["failureEvents"][0][
        "resourcePath"
    ] = target
    if target == "Item2":
        new["inputRefs"][0]["pointer"] = "/Resources/Item2/Properties/CidrBlock"
        new["modelRefs"][0]["key"] = "desired.row.002-001.value"
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 1, "problems": [new]})
        == "STOPPED"
    )
    other = session["workflow"]["currentProblemIds"][0]
    assert other != original
    assert session["workflow"]["problems"][other]["causeId"] == original
    assert len(policy.attempts_for(session["workflow"], other)) == 1
    assert session["workflow"]["problems"][original]["attempts"]


def check_new_code_is_evidence_not_python_cause_inference(tmp_path):
    session, entry = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
    original = session["workflow"]["currentProblemIds"][0]
    attempted(session["workflow"], original, revision=1)
    new = next_diagnosis(session, entry, relation="NEW", code="DifferentConstraint")
    new["constraint"] = "second-constraint"
    new["reason"] = (
        "The current AWS operation reports a different constraint code after the first constraint was corrected; compare both cited executions."
    )
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 1, "problems": [new]})
        == "REPAIR_ALLOWED"
    )
    second = session["workflow"]["currentProblemIds"][0]
    assert second != original
    attempted(session["workflow"], second, revision=2)
    again = next_diagnosis(session, entry, related=[original], code="InvalidRequest")
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 2, "problems": [again]})
        == "STOPPED"
    )
    assert session["workflow"]["currentProblemIds"] == [original]
    # SAME cannot transfer an already known signature to a different cause either.
    again["relatedProblemIds"] = [second]
    again["evidenceRefs"].extend(new["evidenceRefs"])
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 2, "problems": [again]})
        == "NEEDS_DIAGNOSIS"
    )
    assert session["workflow"]["reserved"] == 2


def check_budget_text_is_not_human_authority(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    task = root / "tasks/deploy.md"
    task.parent.mkdir()
    task.write_text(
        "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n"
        "## Modified files\n- `tasks/deploy.md`\n## Allowed paths\n- `tasks/deploy.md`\n"
    )
    session = {
        "repository": str(root),
        "taskFile": "tasks/deploy.md",
        "taskDigest": task_digest(task.read_text()),
        "states": {"Stack": {"status": "NOT_STARTED"}},
    }
    path = tmp_path / "state.json"
    session["workflow"] = handoff.new_workflow()
    handoff.bind(root, path, session)
    session["workflow"]["reserved"] = 20
    handoff.save(path, session)
    assert (
        main(
            [
                "budget",
                "--repository-root",
                str(root),
                "--state",
                str(path),
                "--additional-cycles",
                "20",
                "--authorization",
                "LLMが作った文字列",
            ]
        )
        == 2
    )
    restored = json.loads(path.read_text())
    assert restored["workflow"]["budget"] == restored["workflow"]["reserved"] == 20
    assert restored["workflow"]["status"] == "WAITING_HUMAN"
    assert not restored["workflow"].get("budgetExtensions")
    assert (
        main(
            [
                "close",
                "--repository-root",
                str(root),
                "--state",
                str(path),
                "--authorization",
                "stop",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "budget",
                "--repository-root",
                str(root),
                "--state",
                str(path),
                "--additional-cycles",
                "20",
                "--authorization",
                "another self-issued string",
            ]
        )
        == 2
    )
    assert json.loads(path.read_text())["workflow"]["status"] == "CLOSED"


@pytest.mark.parametrize("progress", ["nested", "peer", "static"])
def check_only_observed_target_progress_counts(tmp_path, progress):
    session, entry = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
    identity = session["workflow"]["currentProblemIds"][0]
    attempted(session["workflow"], identity, revision=1)
    new = next_diagnosis(session, entry)
    state = session["failureObservations"][-1]["awsState"]
    state["successEvents"] = [
        {
            "resourcePath": "Item/Child" if progress == "nested" else "Peer",
            "ResourceStatus": "CREATE_COMPLETE",
        }
    ]
    state["staticValidation"] = "PASS"
    expected = "REPAIR_ALLOWED" if progress == "nested" else "STOPPED"
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 1, "problems": [new]})
        == expected
    )


@pytest.mark.parametrize("targeted", [True, False])
def check_common_cause_progress_requires_repaired_target_success(tmp_path, targeted):
    session, entry = diagnosis_fixture(tmp_path, peer=True)
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [entry]})
    identity = session["workflow"]["currentProblemIds"][0]
    attempt = attempted(session["workflow"], identity, revision=1)
    attempt["expectation"] = [
        {
            "stack": "Stack",
            "resourcePath": "Item",
            "operation": "CREATE",
            "status": "CREATE_COMPLETE",
        }
    ]
    new = next_diagnosis(session, entry)
    new["resourcePath"] = "Item2"
    new["inputRefs"][0]["pointer"] = "/Resources/Item2/Properties/CidrBlock"
    new["modelRefs"][0]["key"] = "desired.row.002-001.value"
    session["failureObservations"][-1]["awsState"]["failureEvents"][0][
        "resourcePath"
    ] = "Item2"
    session["states"]["Stack"].update(
        clientToken="actual-new-execution",
        successEvents=[
            {
                "resourcePath": "Item" if targeted else "UnrelatedPeer",
                "ResourceStatus": "CREATE_COMPLETE",
            }
        ],
    )
    handoff.record_outcomes(session)
    assert (
        bool(session["workflow"]["problems"][identity].get("resolvedByExecution"))
        == targeted
    )
    assert handoff.diagnose(tmp_path, session, {"revision": 1, "problems": [new]}) == (
        "REPAIR_ALLOWED" if targeted else "STOPPED"
    )


class ReceiptInputs:
    def __init__(self, root):
        self.root, self.templates, self.hashes, self.expected_digests = root, {}, {}, {}
        self.target = TARGET

    def paths(self, unit):
        return self.root / "infra" / (
            unit["name"] + ".yaml"
        ), self.root / "infra" / "parameters.json"

    def deployment_input_paths(self, units):
        return [path for unit in units for path in self.paths(unit)]

    def load_inputs(self, unit):
        controller.load_inputs(self, unit)


@pytest.fixture
def acceptance(tmp_path):
    root = tmp_path / "repo"
    (root / "infra").mkdir(parents=True)
    (root / "infra/parameters.json").write_text("[]")
    units = [{"name": name} for name in ("First", "Second")]
    backend = ReceiptInputs(root)
    for unit in units:
        backend.paths(unit)[0].write_text(
            "Resources: {Vpc: {Type: AWS::EC2::VPC, Properties: {CidrBlock: 10.2.0.0/16}}}"
        )
    before = {
        p.relative_to(root).as_posix(): sha(p)
        for p in backend.deployment_input_paths(units)
    }
    effective = handoff.effective(
        root, units, backend.paths, backend.deployment_input_paths
    )
    session = {
        "repository": str(root),
        "taskFile": "tasks/deploy.md",
        "taskDigest": "task",
        "inputRevision": 0,
        "infraManifest": before,
        "unitDigests": {"First": "first", "Second": "second"},
        "effectiveDigests": effective,
        "states": {
            "First": {
                "status": "SUCCESS",
                "observedSynced": True,
                "executionEvidence": {"clientToken": "successful"},
            },
            "Second": {
                "status": "BLOCKED",
                "failure": {"classification": "INPUT_CANDIDATE"},
            },
        },
    }
    workflow = session["workflow"] = handoff.new_workflow()
    workflow.update(
        reserved=1,
        attempts={"attempt": {"requestId": "request", "stage": "STATIC_PASSED"}},
    )
    request_path = tmp_path / "repair/request.json"
    request_path.parent.mkdir()
    request = {
        "requestId": "request",
        "attemptId": "attempt",
        "workflowId": workflow["workflowId"],
        "repository": str(root),
        "session": str(tmp_path / "session.json"),
        "requestPath": str(request_path),
        "taskFile": session["taskFile"],
        "taskDigest": "task",
        "revision": 0,
        "allowedPaths": ["infra/Second.yaml"],
    }
    session["pendingRequest"] = copy.deepcopy(request)
    backend.paths(units[1])[0].write_text(
        backend.paths(units[1])[0].read_text().replace("10.2.", "10.0.")
    )
    current = {
        p.relative_to(root).as_posix(): sha(p)
        for p in backend.deployment_input_paths(units)
    }
    effective_after = handoff.effective(
        root, units, backend.paths, backend.deployment_input_paths
    )
    result = {
        **request,
        "result": "VALIDATED_CANDIDATE",
        "commit": "commit",
        "parentTip": "parent",
        "changes": {
            "infra/Second.yaml": {
                "before": before["infra/Second.yaml"],
                "after": current["infra/Second.yaml"],
            }
        },
        "validation": {"snapshot": {"infra/Second.yaml": current["infra/Second.yaml"]}},
        "effectiveInputs": {"before": effective, "after": effective_after},
    }
    result_path = request_path.with_name("result.json")
    write_sealed(root, result_path, result)
    return root, session, backend, units, current, result_path


def check_validation_snapshot_project_paths(tmp_path):
    paths = {"README.md", "infra/new.json", "missing.md"}
    for relative in paths - {"missing.md"}:
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(relative)
    with (
        patch.object(contracts, "paths", return_value=paths) as listing,
        patch.object(contracts, "sha", wraps=sha) as hashes,
    ):
        snapshot = contracts.validation_snapshot(tmp_path)
    listing.assert_called_once_with(
        tmp_path,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        ".",
        ":(top,exclude)framework",
    )
    assert set(snapshot) == paths and snapshot["missing.md"] is None
    assert {call.args[0] for call in hashes.call_args_list} == {
        tmp_path / p for p in paths - {"missing.md"}
    }


def receipt_git_output(root, *args):
    assert args in {("rev-parse", "HEAD"), ("rev-parse", "commit^")}
    return "commit" if args[-1] == "HEAD" else "parent"


@pytest.mark.parametrize(
    "shared,status,after_replace",
    [
        (True, "FAILED", False),
        (False, "FAILED", False),
        (False, "FAILED", True),
        (False, "BLOCKED", True),
    ],
)
def check_accept_protects_success_and_retries(
    acceptance, shared, status, after_replace
):
    root, session, backend, units, current, result_path = acceptance
    if status == "FAILED":
        session["states"]["Second"].update(
            status="FAILED",
            stackStatus="ROLLBACK_COMPLETE",
            stackId="failed-stack",
            changeSetId="failed-change",
            clientToken="failed-token",
            changeDigest="failed-digest",
            executionEvidence={
                "StackId": "failed-stack",
                "ChangeSetId": "failed-change",
                "clientToken": "failed-token",
                "changeDigest": "failed-digest",
                "inputDigest": "second",
            },
            failureTemplateSafety={"Resources": {"Vpc": {"Type": "AWS::EC2::VPC"}}},
        )
    if shared:
        session["declaredConsumers"] = {"Second": ["First"]}
    path = Path(session["pendingRequest"]["session"])
    # Worktree registration and Git provenance are external adapters; the signed save/restore is real.
    with patch.object(handoff, "register_workflow"):
        session.setdefault("workflow", handoff.new_workflow())
        handoff.bind(root, path, session)
    handoff.save(path, session)
    initial = copy.deepcopy(session)
    current_units = {"First": "first", "Second": "repaired"}
    with (
        patch.object(resume, "verify_integration_owner"),
        patch.object(
            resume._dependency_deploy_contracts,
            "output",
            side_effect=receipt_git_output,
        ),
        patch.object(
            resume._dependency_deploy_contracts,
            "paths",
            return_value={"infra/Second.yaml"},
        ),
        patch.object(
            resume._dependency_deploy_contracts,
            "validation_snapshot",
            return_value={"infra/Second.yaml": current["infra/Second.yaml"]},
        ),
        patch.object(handoff, "verify_inputs"),
    ):
        if shared:
            with pytest.raises(Blocked, match="successful Stack"):
                resume.accept(
                    root, result_path, session, backend, units, current_units, current
                )
            assert session["workflow"]["status"] == "WAITING_HUMAN"
            assert (
                session["states"] == initial["states"]
                and session["pendingRequest"] == initial["pendingRequest"]
            )
            assert (
                session["inputRevision"] == 0 and session["workflow"]["reserved"] == 1
            )
            restored = json.loads(path.read_text())
            handoff.restore(root, path, restored)
            assert restored == session
            return
        with patch.object(
            handoff, "effective", side_effect=OSError("before acceptance")
        ):
            with pytest.raises(OSError, match="before acceptance"):
                resume.accept(
                    root, result_path, session, backend, units, current_units, current
                )
        assert session == initial and json.loads(path.read_text()) == initial
        resume.accept(
            root, result_path, session, backend, units, current_units, current
        )
        accepted = copy.deepcopy(session)
        actual_replace = file_operations.os.replace
        interrupted = _bind_framework_callback(
            _callback_check_signed_ledger_rejects_rollback_and_recovers_interrupted,
            actual_replace,
            path,
            after_replace,
        )
        with (
            patch.object(file_operations.os, "replace", side_effect=interrupted),
            pytest.raises(OSError, match="injected session replacement"),
        ):
            handoff.save(path, session)
        on_disk = json.loads(path.read_text())
        assert on_disk == (accepted if after_replace else initial)
        intent = handoff.binding_path(root, session["taskFile"]).with_suffix(
            ".json.intent"
        )
        assert intent.is_file()
        # Restore the actual before/after disk state, then accept the canonical/copied result again.
        handoff.restore(root, path, on_disk)
        assert on_disk == accepted and not intent.exists()
        copied = result_path.with_name("copy.json")
        copied.write_bytes(result_path.read_bytes())
        saved_bytes = path.read_bytes()
        resume.accept(root, copied, on_disk, backend, units, current_units, current)
        resume.accept(
            root, result_path, on_disk, backend, units, current_units, current
        )
        assert on_disk == accepted and path.read_bytes() == saved_bytes
        assert accepted["states"]["First"] == initial["states"]["First"]
        assert accepted["inputRevision"] == 1 and accepted["workflow"]["reserved"] == 1
        assert "pendingRequest" not in accepted and accepted["workflow"][
            "accepted"
        ] == [str(result_path)]
        assert accepted["workflow"]["attempts"]["attempt"]["acceptedRevision"] == 1
        if status == "FAILED":
            assert accepted["states"]["Second"] == {
                **initial["states"]["Second"],
                "externalRepair": initial["pendingRequest"]["requestId"],
                "recoveryPending": True,
            }
        else:
            assert accepted["states"]["Second"]["status"] == "NOT_STARTED"
            assert "executionEvidence" not in accepted["states"]["Second"]


def check_issue_request_stability(tmp_path):
    session, problem = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
    relative = problem["inputRefs"][0]["path"]
    session.update(
        repository=str(tmp_path),
        taskFile="tasks/deploy.md",
        taskDigest="task",
        target=TARGET,
        environment="dev",
        inputDigest="inputs",
        designDigest="design",
        validationScope=["dev/team/ec2"],
        infraManifest={relative: sha(tmp_path / relative)},
    )
    task = tmp_path / "tasks/deploy.md"
    task.parent.mkdir()
    task.write_text(
        "## Task contract\n- Task status: `running`\n- External IaC repair: `allowed`\n"
        "## Modified files\n- `tasks/deploy.md`\n## Allowed paths\n- `tasks/deploy.md`\n"
    )
    path = tmp_path.parent / (tmp_path.name + "-request-session.json")
    problems = session["workflow"]["currentProblemIds"]
    expected = [
        {
            "stack": "Stack",
            "resourcePath": "Item",
            "operation": "CREATE",
            "status": "CREATE_COMPLETE",
        }
    ]
    with selected_task(tmp_path, "tasks/deploy.md"):
        pending = handoff.issue_request(
            tmp_path, path, session, problems, [relative], expected
        )
        restored = json.loads(path.read_text())
        assert (
            handoff.issue_request(
                tmp_path, path, restored, problems, [relative], expected
            )
            == pending
        )
        assert (
            restored["pendingRequest"] == pending
            and restored["workflow"]["reserved"] == 1
        )
        assert len(restored["workflow"]["attempts"]) == 1
        changed = copy.deepcopy(expected)
        changed[0]["status"] = "UPDATE_COMPLETE"
        with pytest.raises(Blocked, match="another request"):
            handoff.issue_request(
                tmp_path, path, restored, problems, [relative], changed
            )
        assert json.loads(path.read_text()) == restored


@pytest.mark.parametrize(
    "field", ["executionEvidence", "approvedChangeDigest", "pendingObserved", "metrics"]
)
def check_signed_protected_fields(tmp_path, field):
    root = tmp_path / "repo"
    root.mkdir()
    path = tmp_path / "session.json"
    session = {
        "repository": str(root),
        "taskFile": "tasks/deploy.md",
        "states": {
            "A": {
                "status": "SUCCESS",
                "executionEvidence": {"clientToken": "token"},
                "approvedChangeDigest": "digest",
            }
        },
        "pendingObserved": {"stage": "PREPARED"},
        "metrics": {},
    }
    session.setdefault("workflow", handoff.new_workflow())
    handoff.bind(root, path, session)
    handoff.save(path, session)
    restored = json.loads(path.read_text())
    if field == "pendingObserved":
        restored.pop(field)
    elif field == "metrics":
        restored.update(metrics={"duration": 1})
    else:
        restored["states"]["A"][field] = "tampered"
    if field == "metrics":
        handoff.restore(root, path, restored)
        assert (
            restored["states"] == session["states"]
            and restored["pendingObserved"] == session["pendingObserved"]
        )
    else:
        with pytest.raises(Blocked, match="ledger"):
            handoff.restore(root, path, restored)


@pytest.mark.parametrize("after_replace", [False, True])
def check_no_change_recovery_save_is_one_signed_revision(tmp_path, after_replace):
    root = tmp_path / "repo"
    root.mkdir()
    path = tmp_path / "session.json"
    session = {
        "repository": str(root),
        "taskFile": "tasks/deploy.md",
        "workflow": handoff.new_workflow(),
        "states": {"A": {"status": "SUCCESS", "stackId": "stack", "stackStatus": None}},
        "pendingObserved": {
            "evidence": {"A": {"stackId": "stack", "stackStatus": None}},
            "outputs": {"model/dev/team/example.properties": "saved candidate"},
            "beforeManifest": {"source": "before"},
            "afterManifest": {"source": "after"},
        },
    }
    handoff.bind(root, path, session)
    handoff.save(path, session)
    original = copy.deepcopy(session)
    session["states"]["A"]["stackStatus"] = "UPDATE_COMPLETE"
    session["pendingObserved"]["evidence"]["A"]["stackStatus"] = "UPDATE_COMPLETE"
    repaired = copy.deepcopy(session)
    interrupted = _bind_framework_callback(
        _callback_check_signed_ledger_rejects_rollback_and_recovers_interrupted,
        file_operations.os.replace,
        path,
        after_replace,
    )
    with (
        patch.object(file_operations.os, "replace", side_effect=interrupted),
        pytest.raises(OSError, match="injected session replacement"),
    ):
        handoff.save(path, session)
    restored = json.loads(path.read_text())
    assert restored == (repaired if after_replace else original)
    handoff.restore(root, path, restored)
    assert restored == repaired
    proof = handoff.binding_path(root, session["taskFile"])
    receipt = proof.read_bytes()
    handoff.restore(root, path, restored)
    assert proof.read_bytes() == receipt
    assert restored["workflow"] == original["workflow"]
    restored["states"]["A"]["stackStatus"] = None
    restored["pendingObserved"]["evidence"]["A"]["stackStatus"] = None
    assert restored == original


def failed_operation_call(
    actual, failed_operation, runtime, service, operation, arguments
):
    if operation == failed_operation:
        raise AwsError(service, operation, "ValidationError")
    return actual(operation, **arguments)


@pytest.mark.parametrize(
    "stage", ["decode", "validate_template", "create_change_set", "review"]
)
def check_unexecuted_exception_to_diagnosis(tmp_path, stage):
    session, problem = diagnosis_fixture(tmp_path)
    backend = StubAws()
    unit = {
        "name": "Stack",
        "template": "template.yaml",
        "parameters": "parameters.json",
    }
    template = tmp_path / problem["inputRefs"][0]["path"]
    parameters = template.with_name("parameters.json")
    parameters.write_text("[]")
    backend.root = tmp_path
    backend.paths = lambda unit: (template, parameters)
    state = {"status": "BLOCKED", "preparationId": "preparation"}
    if stage == "decode":
        template.write_text("Resources: [invalid")
        operation = "decode_input"
        problem.update(
            resourcePath="Template",
            resourceType="AWS::CloudFormation::Stack",
            property="Template",
            cause="IAC_SYNTAX",
        )
        problem["inputRefs"][0]["pointer"] = ""
        model = tmp_path / "model/dev/123456789012/cloudformation-stacks.properties"
        write_model(
            model,
            {
                "desired.stack.001.name": "Stack",
                "desired.stack.001.template": "template.yaml",
                "desired.stack.001.parameters": "parameters.json",
                "desired.stack.001.deployOrder": "10",
            },
        )
        model_relative = model.relative_to(tmp_path).as_posix()
        session["modelInputManifest"][model_relative] = sha(model)
        problem["modelRefs"] = [
            {
                "path": model_relative,
                "sha256": sha(model),
                "key": "desired.stack.001.template",
            }
        ]
        with pytest.raises(Blocked) as caught:
            backend.load_inputs(unit)
    elif stage == "review":
        operation = "create_change_set"
        with pytest.raises(Blocked) as caught:
            backend.review_prepared(
                unit,
                state,
                {
                    "Status": "FAILED",
                    "ExecutionStatus": "UNAVAILABLE",
                    "StatusReason": "CidrBlock failed (HandlerErrorCode: InvalidRequest)",
                },
            )
    else:
        operation = stage
        backend.load_inputs(unit)
        call = _bind_framework_callback(failed_operation_call, backend.aws, stage)
        backend.aws = _bind_framework_callback(controller.aws, backend)
        with (
            patch.object(controller, "call", side_effect=call),
            pytest.raises(Blocked) as caught,
        ):
            backend.begin_prepare(unit, state)
    failures.exception(
        state,
        caught.value,
        "INPUT_DECODE"
        if stage == "decode"
        else "CHANGESET_REVIEW"
        if stage == "review"
        else "PREPARATION",
    )
    session["states"] = {"Stack": state}
    session["failureObservations"] = []
    session["infraManifest"] = {problem["inputRefs"][0]["path"]: sha(template)}
    handoff.record_stop(session, [unit])
    observation = session["failureObservations"][0]
    assert observation["awsState"]["failure"]["classification"] == (
        "INPUT_CANDIDATE" if stage == "decode" else "IAC_CANDIDATE"
    )
    assert (
        "executionEvidence" not in state
        and "executionEvidence" not in observation["awsState"]
    )
    problem.update(
        observationId=observation["observationId"], eventIndices=[], operation=operation
    )
    problem["evidenceRefs"] = [
        {
            "observationId": observation["observationId"],
            "revision": 0,
            "eventIndices": [],
        }
    ]
    problem["inputRefs"][0]["sha256"] = sha(template)
    assert (
        handoff.diagnose(tmp_path, session, {"revision": 0, "problems": [problem]})
        == "REPAIR_ALLOWED"
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
