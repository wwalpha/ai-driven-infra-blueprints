"""Offline boundary counts, execution evidence, and deployment safety regressions."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import copy
import json
from unittest.mock import patch

import pytest
from deploy import change_sets as change_sets
from deploy import guards
from deploy import observed as observed
from deploy.recovery import reset_after_cleanup
from deploy.s3_delivery import preflight
from deploy.timing import Timing
from support.cloudformation_deploy_fixtures import TARGET as TARGET
from support.cloudformation_deploy_fixtures import DeliveryAws
from support.cloudformation_deploy_fixtures import states as states
from support.cloudformation_deploy_fixtures import units as units
from support.pytest_cli import run
from utils.aws.client import AwsError

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def runtime_inputs(tmp_path, large=False, artifact=False, count=1):
    runtime = DeliveryAws(tmp_path / "repo", tmp_path / "session.files")
    selected = units(*([10] * count))
    document = {"Resources": {}}
    if artifact:
        document["Resources"]["Job"] = {
            "Type": "AWS::Glue::Job",
            "Properties": {
                "Command": {
                    "ScriptLocation": "s3://app-dev-assets/artifacts/current.py"
                }
            },
        }
        source = runtime.root / "infra/cloudformation/artifacts/job.py"
        source.parent.mkdir(parents=True)
        source.write_text("print('hello')\n")
        for unit in selected:
            unit["artifacts"] = [
                {
                    "stack": unit["name"],
                    "resource": "Job",
                    "property": "Command.ScriptLocation",
                    "source": source.relative_to(runtime.root).as_posix(),
                    "bucket": "app-dev-assets",
                    "keyPrefix": "artifacts/",
                }
            ]
    if large:
        document["Description"] = "x" * 52000
        for unit in selected:
            unit.update(templateBucket="app-dev-assets", templateKeyPrefix="templates/")
    for unit in selected:
        template, parameters = runtime.paths(unit)
        template.parent.mkdir(parents=True, exist_ok=True)
        parameters.parent.mkdir(parents=True, exist_ok=True)
        template.write_text(json.dumps(document))
        parameters.write_text("[]")
        runtime.load_inputs(unit)
    runtime.states = states(selected)
    runtime.expected_digests = {
        unit["name"]: runtime.input_digest(unit) for unit in selected
    }
    return runtime, selected


@pytest.mark.parametrize(
    "large,artifact,count",
    [
        (False, False, 1),
        (True, False, 1),
        (False, True, 1),
        (True, True, 1),
        (True, False, 3),
    ],
)
def check_boundary_sharing(tmp_path, large, artifact, count):
    runtime, selected = runtime_inputs(tmp_path, large, artifact, count)
    with (
        patch(
            "model.adapters.observed.mappings",
            side_effect=AssertionError("whole-scope mapping forbidden"),
        ),
        patch("subprocess.run", side_effect=AssertionError("AWS CLI/lint forbidden")),
    ):
        runtime.prepare_delivery_group(selected, runtime.states)
        unit = selected[0]
        state = runtime.states[unit["name"]]
        assert runtime.prepare(unit, state) == "READY"
        state["clientToken"] = "token"
        runtime.execute(unit, state)
    before_execute = [
        operation for operation, _ in runtime.calls if operation != "execute_change_set"
    ]
    if large or artifact:
        assert sum(op == "get_bucket_policy" for op in before_execute) == 3
        assert sum(op == "get_bucket_encryption" for op in before_execute) == 3
    # Delivery, Create, and Execute each acquire their own bucket snapshot.
    assert not any(op == "list_exports" for op in before_execute)
    assert state["executionEvidence"]["clientToken"] == "token"
    assert "TemplateBody" not in json.dumps(state["delivery"])


def check_exports_and_boundary_freshness(tmp_path):
    runtime, selected = runtime_inputs(tmp_path, artifact=True, count=2)
    runtime.prepare_delivery_group(selected, runtime.states)
    assert not any(op == "list_exports" for op, _ in runtime.calls)
    # Required exports only. An unrelated export is not part of the delivery fingerprint.
    for unit in selected:
        document, parameters = runtime.templates[unit["name"]]
        document["Outputs"] = {"Imported": {"Value": {"Fn::ImportValue": "Required"}}}
    runtime.export_values = {"Required": "value", "Unrelated": "before"}
    runtime.states = states(selected)
    runtime.calls.clear()
    runtime.prepare_delivery_group(selected, runtime.states)
    assert sum(op == "list_exports" for op, _ in runtime.calls) == 1
    runtime.export_values["Unrelated"] = "after"
    state = runtime.states["A"]
    assert runtime.prepare(selected[0], state) == "READY"
    state["clientToken"] = "token"
    runtime.execute(selected[0], state)
    assert sum(op == "list_exports" for op, _ in runtime.calls) == 3
    runtime.export_values["Required"] = "changed"
    state = runtime.states["B"]
    with pytest.raises(ValueError if False else RuntimeError, match="Export"):
        runtime.prepare(selected[1], state)


def check_key_policy_and_current_objects(tmp_path):
    runtime, selected = runtime_inputs(tmp_path, artifact=True)
    runtime.prepare_delivery_group(selected, runtime.states)
    obj = runtime.states["A"]["delivery"]["objects"][0]
    assert not obj["consumeVersion"], "versionless s3 URI must check current key"
    # The next boundary detects an overwritten current key even if an old version still exists.
    runtime.objects[obj["bucket"], obj["key"]]["ChecksumSHA256"] = "changed"
    with pytest.raises(RuntimeError, match="checksum/size"):
        runtime.prepare(selected[0], runtime.states["A"])
    runtime, selected = runtime_inputs(tmp_path / "other", large=True)
    runtime.prepare_delivery_group(selected, runtime.states)
    runtime.policy = {
        "Statement": [
            {
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:PutObject",
                "Resource": "arn:aws:s3:::app-dev-assets/templates/*",
                "Condition": {
                    "StringEquals": {"s3:x-amz-server-side-encryption": "AES256"}
                },
            }
        ]
    }
    with pytest.raises(RuntimeError, match="MISMATCH"):
        runtime.prepare(selected[0], runtime.states["A"])


def check_remove_without_startup_mapping(tmp_path):
    runtime, selected = runtime_inputs(tmp_path)
    runtime.change["Changes"] = [
        {
            "ResourceChange": {
                "Action": "Remove",
                "LogicalResourceId": "Old",
                "ResourceType": "AWS::EC2::VPC",
                "PhysicalResourceId": "vpc-old",
                "PolicyAction": "Delete",
            }
        }
    ]
    state = runtime.states["A"]
    assert runtime.prepare(selected[0], state) == "BLOCKED"
    runtime.approvals.add(state["changeSetId"])
    assert runtime.prepare(selected[0], state) == "READY"
    state["clientToken"] = "token"
    with patch(
        "model.adapters.observed.mappings",
        side_effect=AssertionError("Remove mapping forbidden"),
    ):
        runtime.execute(selected[0], state)
    evidence = state["executionEvidence"]
    assert evidence["resources"][0]["PhysicalResourceId"] == "vpc-old"
    assert (
        evidence["StackId"] == state["stackId"]
        and evidence["ChangeSetId"] == state["changeSetId"]
    )
    runtime.change["Changes"][0]["ResourceChange"]["PolicyAction"] = "Retain"
    with pytest.raises(RuntimeError, match="approval invalid"):
        runtime.execute(selected[0], state)


@pytest.mark.parametrize(
    "policy,expected",
    [
        ("Retain", set()),
        ("RetainExceptOnCreate", set()),
        ("Delete", {"Old"}),
        ("Snapshot", {"Old"}),
        (None, None),
        ("Unsupported", None),
    ],
)
def check_observed_selection(policy, expected):
    document = {
        "Conditions": {"Disabled": False},
        "Resources": {
            "Current": {"Type": "AWS::EC2::VPC"},
            "Inactive": {"Type": "AWS::EC2::VPC", "Condition": "Disabled"},
        },
    }
    removed = {
        "Old": {"Type": "AWS::EC2::VPC", "PolicyAction": policy},
        "Retained": {"Type": "AWS::EC2::VPC", "PolicyAction": "Retain"},
    }
    arguments = (document, {}, {"AWS::StackName": "A"}, removed, set())
    if expected is None:
        with pytest.raises(ValueError, match="removal policy is unknown"):
            observed.selected_resources(*arguments)
    else:
        assert observed.selected_resources(*arguments) == {"Current"} | expected
        removed["Child"] = {"Type": "AWS::S3::BucketPolicy", "PolicyAction": "Delete"}
        assert (
            observed.selected_resources(
                document,
                {},
                {"AWS::StackName": "A"},
                removed,
                {"AWS::S3::BucketPolicy"},
            )
            == {"Current"} | expected
        )


@pytest.mark.parametrize(
    "action,status,physical,expected",
    [
        ("Retain", None, None, False),
        ("RetainExceptOnCreate", None, None, False),
        (None, None, None, None),
        ("Delete", "DELETE_SKIPPED", "vpc-old", False),
        ("Delete", "DELETE_COMPLETE", "vpc-old", True),
        ("Snapshot", "DELETE_COMPLETE", "vpc-old", True),
        ("Delete", None, None, None),
    ],
)
def check_deletion_evidence(action, status, physical, expected):
    state = {
        "stackId": "stack",
        "changeSetId": "change",
        "changeDigest": "digest",
        "clientToken": "token",
    }
    state["executionEvidence"] = {
        "StackId": "stack",
        "ChangeSetId": "change",
        "changeDigest": "digest",
        "clientToken": "token",
    }
    removal = {
        "Type": "AWS::EC2::VPC",
        "PolicyAction": action,
        "PhysicalResourceId": physical,
    }
    actuals = (
        {
            "Old": {
                "ResourceStatus": status,
                "PhysicalResourceId": physical,
                "ResourceType": "AWS::EC2::VPC",
            }
        }
        if status
        else {}
    )
    runtime = SimpleNamespace(aws=lambda *a, **k: {"StackEvents": []})
    if expected is None:
        with pytest.raises(ValueError, match="unknown"):
            observed.deleted_resource(runtime, "A", "Old", removal, state, actuals)
    else:
        assert (
            observed.deleted_resource(runtime, "A", "Old", removal, state, actuals)
            is expected
        )


def check_mutation_guard_is_immediate(tmp_path):
    runtime = SimpleNamespace(
        root=tmp_path,
        environment="dev",
        directory="target",
        connection=("context",),
        timing=Timing(tmp_path),
    )
    runtime.guard = lambda: (_ for _ in ()).throw(RuntimeError("changed input"))
    for operation, service in [
        ("create_change_set", "cloudformation"),
        ("execute_change_set", "cloudformation"),
        ("delete_stack", "cloudformation"),
        ("put_object", "s3"),
        ("put_secret_value", "secretsmanager"),
        ("update_secret_version_stage", "secretsmanager"),
    ]:
        with patch.object(
            guards.SERVICES[service],
            operation,
            side_effect=AssertionError("unguarded mutation"),
        ):
            with pytest.raises(RuntimeError, match="changed input"):
                guards.call(runtime, service, operation, {})


def _callback_check_conditional_put_outcomes_aws(
    code, committed, original, requests, status, /, operation, **arguments
):
    if operation == "put_object":
        requests.append(dict(arguments))
        assert arguments["IfNoneMatch"] == "*" and "ExpectedBucketOwner" in arguments
        if len(requests) == 1:
            if committed:
                original(operation, **arguments)
            raise AwsError("s3", operation, code, status)
    return original(operation, **arguments)


@pytest.mark.parametrize(
    "code,status,committed,puts",
    [
        ("PreconditionFailed", 412, True, 1),
        ("ReadTimeoutError", None, True, 1),
        ("ConditionalRequestConflict", 409, False, 2),
        ("AccessDenied", 403, False, 1),
    ],
)
def check_conditional_put_outcomes(tmp_path, code, status, committed, puts):
    runtime, selected = runtime_inputs(tmp_path, artifact=True)
    original = runtime.aws
    requests = []
    aws = _bind_framework_callback(
        _callback_check_conditional_put_outcomes_aws,
        code,
        committed,
        original,
        requests,
        status,
    )
    runtime.aws = aws
    if status == 403:
        with pytest.raises(RuntimeError, match="AccessDenied"):
            runtime.prepare_delivery_group(selected, runtime.states)
    else:
        runtime.prepare_delivery_group(selected, runtime.states)
        obj = runtime.states["A"]["delivery"]["objects"][0]
        assert (
            obj["checksum"]
            == runtime.objects[obj["bucket"], obj["key"]]["ChecksumSHA256"]
        )
    assert len(requests) == puts


def check_key_policy_scope(tmp_path):
    runtime, _ = runtime_inputs(tmp_path)
    placement = runtime.placement()
    runtime.policy = {
        "Statement": [
            {
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:PutObject",
                "Resource": "arn:aws:s3:::app-dev-assets/denied/*",
                "Condition": {
                    "StringEquals": {"s3:x-amz-server-side-encryption": "AES256"}
                },
            }
        ]
    }
    boundary = {}
    preflight(placement, "app-dev-assets", "allowed/", ["allowed/file"], boundary)
    with pytest.raises(RuntimeError, match="MISMATCH"):
        preflight(placement, "app-dev-assets", "denied/", ["denied/file"], boundary)
    assert sum(op == "get_bucket_policy" for op, _ in runtime.calls) == 1


def _callback_check_cleanup_refreshes_create_boundary_aws(
    cleaned, mutation, original, /, operation, **arguments
):
    if operation == "describe_stacks" and not cleaned:
        return {
            "Stacks": [{"StackStatus": "ROLLBACK_COMPLETE", "StackId": "failed-stack"}]
        }
    response = original(operation, **arguments)
    if operation == "list_exports" and cleaned and mutation == "producer":
        response["Exports"][0]["ExportingStackId"] = "changed-producer"
    return response


def _callback_check_cleanup_refreshes_create_boundary_cleanup(
    cleaned, mutation, runtime, state, /, *args, **kwargs
):
    cleaned.append(True)
    if mutation == "encryption":
        runtime.default_algorithm = "aws:kms"
    if mutation == "policy":
        runtime.policy = {
            "Statement": [
                {
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "s3:PutObject",
                    "Resource": "arn:aws:s3:::app-dev-assets/artifacts/*",
                    "Condition": {
                        "StringEquals": {"s3:x-amz-server-side-encryption": "AES256"}
                    },
                }
            ]
        }
    if mutation == "kms":
        runtime.key_state, runtime.key_enabled = "Disabled", False
    if mutation == "current":
        obj = state["delivery"]["objects"][0]
        runtime.objects[obj["bucket"], obj["key"]]["ChecksumSHA256"] = "changed"
    if mutation == "export":
        runtime.export_values["Required"] = "after"
    return True


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize(
    "mutation",
    ["encryption", "policy", "kms", "current", "export", "producer", "unchanged"],
)
def check_cleanup_refreshes_create_boundary(tmp_path, resume, mutation):
    runtime, selected = runtime_inputs(tmp_path, artifact=True)
    document, parameters = runtime.templates["A"]
    document["Outputs"] = {"Imported": {"Value": {"Fn::ImportValue": "Required"}}}
    runtime.export_values = {"Required": "before"}
    if mutation == "kms":
        runtime.default_algorithm, runtime.default_key = "aws:kms", runtime.key_arn
        runtime.add_bucket("app-dev-assets", "aws:kms", runtime.key_arn)
    runtime.prepare_delivery_group(selected, runtime.states)
    state = runtime.states["A"]
    if resume:
        state["cleanupStatus"] = "DELETE_INTENT"
    original = runtime.aws
    cleaned = []
    aws = _bind_framework_callback(
        _callback_check_cleanup_refreshes_create_boundary_aws,
        cleaned,
        mutation,
        original,
    )
    cleanup = _bind_framework_callback(
        _callback_check_cleanup_refreshes_create_boundary_cleanup,
        cleaned,
        mutation,
        runtime,
        state,
    )
    runtime.aws = aws
    runtime.cleanup_failed_create = cleanup
    if mutation == "unchanged":
        assert runtime.begin_prepare(selected[0], state) == "CHANGESET_CREATING"
        assert any(op == "create_change_set" for op, _ in runtime.calls)
    else:
        with pytest.raises(RuntimeError):
            runtime.begin_prepare(selected[0], state)
        assert not any(
            op in {"validate_template", "create_change_set", "execute_change_set"}
            for op, _ in runtime.calls
        )
    assert cleaned


def check_cleanup_delivery_evidence_is_durable():
    record = {
        "imports": {"Required": {"Value": "before", "ExportingStackId": "producer"}}
    }
    state = {
        "status": "BLOCKED",
        "delivery": record,
        "cleanupStatus": "DELETE_COMPLETE",
    }
    saved = []
    reset_after_cleanup(
        lambda: saved.append(copy.deepcopy(state)), state, retain_delivery=True
    )
    assert saved[-1]["delivery"] == record
    # A repaired input gets a new delivery plan through the existing default path.
    reset_after_cleanup(lambda: saved.append(copy.deepcopy(state)), state)
    assert "delivery" not in saved[-1]


class DeletionEvents:
    def __init__(self, event):
        self.event, self.calls = event, []

    def aws(self, operation, **arguments):
        self.calls.append((operation, arguments))
        if operation == "describe_stack_events":
            return {"StackEvents": [self.event]}
        if operation == "describe_stacks":
            return {"Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}]}
        if operation == "list_stack_resources":
            return {"StackResourceSummaries": []}
        raise AssertionError(operation)


@pytest.mark.parametrize(
    "mismatch", [None, "ClientRequestToken", "StackId", "PhysicalResourceId"]
)
def check_deletion_event_identity(tmp_path, mismatch):
    state = {
        "status": "SUCCESS",
        "stackStatus": "UPDATE_COMPLETE",
        "stackId": "stack",
        "changeSetId": "change",
        "changeDigest": "digest",
        "clientToken": "token",
    }
    removal = {
        "Action": "Remove",
        "LogicalResourceId": "Old",
        "ResourceType": "AWS::EC2::VPC",
        "PolicyAction": "Delete",
        "PhysicalResourceId": "vpc-old",
    }
    state["executionEvidence"] = {
        "StackId": "stack",
        "ChangeSetId": "change",
        "changeDigest": "digest",
        "clientToken": "token",
        "resources": [removal],
    }
    event = {
        "StackId": "stack",
        "ClientRequestToken": "token",
        "LogicalResourceId": "Old",
        "PhysicalResourceId": "vpc-old",
        "ResourceType": "AWS::EC2::VPC",
        "ResourceStatus": "DELETE_COMPLETE",
    }
    if mismatch:
        event[mismatch] = "unrelated"
    backend = DeletionEvents(event)
    definition = {
        "Type": "AWS::EC2::VPC",
        "PolicyAction": "Delete",
        "PhysicalResourceId": "vpc-old",
    }
    if mismatch is None:
        assert observed.deleted_resource(backend, "A", "Old", definition, state, {})
    else:
        # The real collector must fail before it can propose or publish PENDING_DEPLOY.
        source = tmp_path / "model/dev/team/ec2.properties"
        backend.root, backend.environment, backend.directory = tmp_path, "dev", "team"
        backend.target, backend.templates = TARGET, {"A": ({"Resources": {}}, {})}
        backend.run_context = {"states": {"A": state}}
        mapped = {
            "A": {
                "Old": (
                    source,
                    "001",
                    {},
                    [("001-001", {"property": "EC2.VPC.VpcId"})],
                    {"EC2.VPC.VpcId"},
                )
            }
        }
        with (
            patch.object(
                observed, "resolve_resources", return_value=({source: {}}, mapped)
            ),
            patch("model.adapters.observed.publish_observed") as publish,
        ):
            with pytest.raises(ValueError, match="physical destruction is unconfirmed"):
                observed.sync_successful(backend, [{"name": "A"}], {"A": state})
        publish.assert_not_called()
        assert not state.get("observedSynced") and not source.exists()
    assert any(op == "describe_stack_events" for op, _ in backend.calls)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
