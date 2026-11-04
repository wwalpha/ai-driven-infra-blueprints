"""Selected ownership and incoming discovery, without validating unrelated Models."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json

import deploy.observed as deploy_observed
import model.adapters.observed as observed_adapter
import pytest
from deploy import deferred
from deploy.observed import security_group_rule_id
from model.adapters.aws import Unresolved, service_module
from model.adapters.observed import (
    propagate_references,
    resolve_resources,
)
from model.files import read_model
from support import model_reference_fixtures
from support.cloudformation_deploy_fixtures import TARGET
from support.model_sources import allocate_fixture, write_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _sg_rule_aws(document, records, stack, operation, **kwargs):
    if operation == "get_template":
        return {"TemplateBody": document}
    if operation == "describe_security_group_rules":
        return {"SecurityGroupRules": records}
    if operation == "describe_stacks":
        return {"Stacks": [stack]}
    raise AssertionError(operation)


def _sg_rule_result(backend, stack, document, actual, output="sgr-12345678"):
    return security_group_rule_id(
        backend, stack, document, {}, {}, [], "Rule", actual, output
    )


def _capture_destinations(captured, root, environment, directory, loaded, changes):
    captured.update(changes)
    return {}, [], None


@pytest.mark.parametrize("old_output", [False, True])
@pytest.mark.parametrize("old_row", [False, True])
def test_queue_policy_id_is_not_observed(project_workspace, old_output, old_row):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root, "sqs", "SQS.QueuePolicy", attribute="Id", observed="old-id"
    )
    if not old_row:
        values = {
            key: value for key, value in values.items() if ".row.001-001." not in key
        }
    model_reference_fixtures.write(scope, values)
    before = scope.path.read_bytes()
    document = {"Resources": {"Resource001": {"Type": "AWS::SQS::QueuePolicy"}}}
    if old_output:
        document["Outputs"] = {
            "PolicyId": {"Value": {"Fn::GetAtt": ["Resource001", "Id"]}}
        }
    _, mapped = resolve_resources(
        root,
        "qa",
        "team",
        {"producer": (document, {})},
        [{"name": "producer"}],
        {"producer": {"Resource001"}},
        target=TARGET,
        check_scope=False,
    )
    assert "SQS.QueuePolicy.Id" not in mapped["producer"]["Resource001"][4]
    assert scope.path.read_bytes() == before


@pytest.mark.parametrize("declared", [False, True])
def test_queue_policy_id_external_reference_is_diagnosed(project_workspace, declared):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root, "sqs", "SQS.QueuePolicy", attribute="Id", observed="old-id"
    )
    model_reference_fixtures.write(scope, values)
    consumer, other = model_reference_fixtures.resource_values(
        root, "iam", "IAM.ManagedPolicy", attribute="ManagedPolicyName"
    )
    other["desired.resource.001.cfn-logicalId"] = "consumer-Policy"
    other["desired.row.001-002.property"] = "IAM.ManagedPolicy.PolicyDocument"
    other["desired.row.001-002.comment"] = "consumer"
    other["desired.row.001-002.value"] = (
        "`"
        + json.dumps(model_reference_fixtures.reference("SQS_QueuePolicy_001", "Id"))
        + "`"
    )
    if declared:
        other["desired.row.001-002.value"] = "`old-id`"
        spec = {
            "consumerKey": "desired.row.001-002.value",
            "text": "old-id",
            "occurrence": "1",
            "producerKind": "resource",
            "producerScope": "qa/team/sqs",
            "producerLogicalId": "SQS_QueuePolicy_001",
            "resourceType": "SQS.QueuePolicy",
            "format": "identifier",
            "property": "SQS.QueuePolicy.Id",
            "labelPolicy": "none",
        }
        other.update(
            {f"desired.reference.external.{key}": value for key, value in spec.items()}
        )
    model_reference_fixtures.write(consumer, other)
    document = {"Resources": {"Resource001": {"Type": "AWS::SQS::QueuePolicy"}}}
    with pytest.raises(
        ValueError,
        match=r"iam.properties:desired.row.001-002.value.*cannot be observed",
    ):
        resolve_resources(
            root,
            "qa",
            "team",
            {"producer": (document, {})},
            [{"name": "producer"}],
            {"producer": {"Resource001"}},
            target=TARGET,
            check_scope=False,
        )


def test_queue_policy_id_other_setting_is_diagnosed(project_workspace):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root, "sqs", "SQS.QueuePolicy", attribute="Id"
    )
    values["desired.row.001-002.property"] = "SQS.QueuePolicy.Queues"
    values["desired.row.001-002.comment"] = "consumer"
    values["desired.row.001-002.value"] = (
        "`"
        + json.dumps([model_reference_fixtures.reference("SQS_QueuePolicy_001", "Id")])
        + "`"
    )
    model_reference_fixtures.write(scope, values)
    document = {"Resources": {"Resource001": {"Type": "AWS::SQS::QueuePolicy"}}}
    with pytest.raises(
        ValueError,
        match=r"sqs.properties:desired.row.001-002.value.*cannot be observed",
    ):
        resolve_resources(
            root,
            "qa",
            "team",
            {"producer": (document, {})},
            [{"name": "producer"}],
            {"producer": {"Resource001"}},
            target=TARGET,
            check_scope=False,
        )


@pytest.mark.parametrize(
    "expression",
    [{"Fn::GetAtt": ["Resource001", "Id"]}, {"Fn::Sub": "${Resource001.Id}"}],
)
def test_queue_policy_id_template_consumer_is_diagnosed(project_workspace, expression):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root, "sqs", "SQS.QueuePolicy", attribute="Id"
    )
    model_reference_fixtures.write(scope, values)
    document = {
        "Resources": {
            "Resource001": {"Type": "AWS::SQS::QueuePolicy"},
            "Consumer": {
                "Type": "AWS::SQS::Queue",
                "Properties": {"QueueName": expression},
            },
        }
    }
    with pytest.raises(
        ValueError, match=r"Resources.Consumer.Properties.QueueName.*cannot be observed"
    ):
        resolve_resources(
            root,
            "qa",
            "team",
            {"producer": (document, {})},
            [{"name": "producer"}],
            {"producer": {"Resource001"}},
            target=TARGET,
            check_scope=False,
        )


@pytest.mark.parametrize("old_output", [False, True])
def test_queue_policy_sync_preserves_old_observation(
    project_workspace, monkeypatch, old_output
):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root, "sqs", "SQS.QueuePolicy", attribute="Id", observed="old-id"
    )
    model_reference_fixtures.write(scope, values)
    document = {"Resources": {"Resource001": {"Type": "AWS::SQS::QueuePolicy"}}}
    if old_output:
        document["Outputs"] = {
            "PolicyId": {"Value": {"Fn::GetAtt": ["Resource001", "Id"]}}
        }
    unit = {"name": "producer"}
    mapped = resolve_resources(
        root,
        "qa",
        "team",
        {"producer": (document, {})},
        [unit],
        {"producer": {"Resource001"}},
        target=TARGET,
        check_scope=False,
    )
    backend = SimpleNamespace(
        root=root,
        environment="qa",
        directory="team",
        target=TARGET,
        templates={"producer": (document, {})},
        aws=Mock(),
        run_context={},
    )
    stack = {
        "StackId": "stack",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": [{"OutputKey": "PolicyId", "OutputValue": "new-id"}]
        if old_output
        else [],
    }
    monkeypatch.setattr(deploy_observed, "resolve_resources", lambda *a, **k: mapped)
    monkeypatch.setattr(
        deploy_observed.execution_scope, "check_fixed_resources", lambda *a, **k: None
    )
    monkeypatch.setattr(deploy_observed.current_state, "read", lambda *a: stack)
    monkeypatch.setattr(
        deploy_observed.current_state,
        "pages",
        lambda *a, **k: [
            {
                "LogicalResourceId": "Resource001",
                "ResourceType": "AWS::SQS::QueuePolicy",
                "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": "physical-id",
            }
        ],
    )
    captured = {}

    monkeypatch.setattr(
        deploy_observed,
        "observed_destinations",
        _bind_framework_callback(_capture_destinations, captured),
    )
    before = scope.path.read_bytes()
    states = {"producer": {}}
    deploy_observed.collect_successful(backend, [unit], states)
    assert captured[scope.path] == {}
    assert (
        states["producer"]["observedCoverage"]["Resource001"]["status"]
        == "NO_IDENTIFIER"
    )
    assert scope.path.read_bytes() == before


def seed(root, kind, child_kind, setting):
    task = root / "tasks/selected.md"
    task.parent.mkdir(exist_ok=True)
    task.write_text(
        "## Task contract\n- Task status: `running`\n## Modified files\n- `tasks/selected.md`\n## Allowed paths\n- `tasks/selected.md`\n## Validation scope\n- `all`\n"
    )
    (root / "project.json").write_text(
        json.dumps(
            {"targets": [{"environment": env, **TARGET} for env in ("dev", "stg")]}
        )
    )
    source = (
        root
        / "model/dev/123456789012"
        / ("s3.properties" if kind == "S3.Bucket" else "ec2.properties")
    )
    values = {}
    for number, logical in enumerate(("Parent", "OtherParent"), 1):
        identity = f"{number:03}"
        values.update(
            {
                f"desired.resource.{identity}.resourceType": kind,
                f"desired.resource.{identity}.cfn-logicalId": "Stack-" + logical,
                f"desired.row.{identity}-001.property": kind
                + (".BucketName" if kind == "S3.Bucket" else ".SubnetId"),
                f"desired.row.{identity}-001.value": "`"
                + json.dumps(
                    {
                        "$modelRef": {
                            "logicalId": kind.replace(".", "_") + "_" + identity,
                            "attribute": "BucketName"
                            if kind == "S3.Bucket"
                            else "SubnetId",
                        }
                    }
                )
                + "`",
                f"desired.row.{identity}-001.comment": "識別子",
                f"desired.row.{identity}-002.property": child_kind + "." + setting,
                f"desired.row.{identity}-002.value": "`setting`",
                f"desired.row.{identity}-002.comment": "子設定",
            }
        )
        values.update(allocate_fixture(values, [identity]))
    write_model(source, values)
    write_model(
        source.with_name("cloudformation-stacks.properties"),
        {
            f"desired.stack.001.{key}": value
            for key, value in {
                "name": "Stack",
                "template": "stack.yaml",
                "parameters": "stack.json",
                "deployOrder": "10",
            }.items()
        },
    )
    return source


def _callback_check_selected_parent_resolve(document, root, /):
    return resolve_resources(
        root,
        "dev",
        "123456789012",
        {"Stack": (document, {"Flag": "yes"})},
        [{"name": "Stack"}],
        {"Stack": {"Child", "InactiveChild"}},
        target=TARGET | {"awsExecutionAccountId": "999999999999"},
    )


@pytest.mark.parametrize(
    "kind,child_kind,parent_property,setting",
    [
        ("S3.Bucket", "S3.BucketPolicy", "Bucket", "PolicyDocument"),
        ("EC2.Subnet", "EC2.SubnetRouteTableAssociation", "SubnetId", "RouteTableId"),
    ],
)
@pytest.mark.parametrize(
    "expression,enabled,expected",
    [
        ({"Ref": "Parent"}, True, "001"),
        (
            {"Fn::If": ["Enabled", {"Ref": "Parent"}, {"Ref": "OtherParent"}]},
            True,
            "001",
        ),
        (
            {"Fn::If": ["Enabled", {"Ref": "Parent"}, {"Ref": "OtherParent"}]},
            False,
            "002",
        ),
        (
            {
                "Fn::If": [
                    "Enabled",
                    {"Fn::If": ["Nested", {"Ref": "Parent"}, "bad"]},
                    {"Ref": "Missing"},
                ]
            },
            True,
            "001",
        ),
        (
            {"Fn::If": ["Enabled", {"Ref": "Missing"}, {"Ref": "OtherParent"}]},
            False,
            "002",
        ),
        ({"Fn::If": ["Enabled", "bad", {"Ref": "OtherParent"}]}, True, None),
        ({"Ref": "Missing"}, True, None),
    ],
)
def check_selected_parent(
    project_workspace,
    kind,
    child_kind,
    parent_property,
    setting,
    expression,
    enabled,
    expected,
):
    root = project_workspace
    seed(root, kind, child_kind, setting)
    document = {
        "Conditions": {
            "Enabled": enabled,
            "Nested": {
                "Fn::And": [
                    {"Fn::Equals": [{"Ref": "Flag"}, "yes"]},
                    {"Fn::Equals": [{"Ref": "AWS::AccountId"}, "999999999999"]},
                ]
            },
        },
        "Resources": {
            "Parent": {"Type": "AWS::" + kind.replace(".", "::")},
            "OtherParent": {"Type": "AWS::" + kind.replace(".", "::")},
            "Child": {
                "Type": "AWS::" + child_kind.replace(".", "::"),
                "Properties": {parent_property: expression},
            },
            "InactiveChild": {
                "Condition": "Disabled",
                "Type": "AWS::" + child_kind.replace(".", "::"),
                "Properties": {parent_property: {"Ref": "Missing"}},
            },
        },
    }
    document["Conditions"]["Disabled"] = False
    resolve = _bind_framework_callback(
        _callback_check_selected_parent_resolve, document, root
    )
    if expected is None:
        with pytest.raises(ValueError, match="parent"):
            resolve()
    else:
        _, mapped = resolve()
        assert set(mapped["Stack"]) == {"Child"}
        assert mapped["Stack"]["Child"][1] == expected


def check_discovery_defers_semantics(project_workspace):
    root = project_workspace
    source = seed(root, "S3.Bucket", "S3.BucketPolicy", "PolicyDocument")
    unrelated = source.with_name("unrelated.properties")
    write_model(
        unrelated,
        {
            "desired.resource.001.resourceType": "S3.Bucket",
            "desired.resource.001.cfn-logicalId": "invalid",
            "desired.resource.001.deploymentEncryption": "invalid",
        },
    )
    templates = {"Stack": ({"Resources": {"Parent": {"Type": "AWS::S3::Bucket"}}}, {})}
    loaded, _ = resolve_resources(
        root,
        "dev",
        "123456789012",
        templates,
        [{"name": "Stack"}],
        {"Stack": {"Parent"}},
        target=TARGET,
    )
    assert set(loaded) == {source}
    other = root / "model/stg/123456789012/consumer.properties"
    write_model(
        other,
        {
            "desired.resource.001.resourceType": "S3.Bucket",
            "desired.resource.001.deploymentEncryption": "invalid",
            "desired.row.001-001.property": "S3.Bucket.BucketName",
            "desired.row.001-001.value": "`unrelated`",
        },
    )
    identifiers = {("dev", "123456789012", "s3", "S3_Bucket_001"): "bucket"}
    propagate_references(root, loaded, {}, identifiers)
    assert other not in loaded
    raw = other.read_text()
    # The same invalid consumer must fail when its raw link actually reaches the updated owner.
    write_model(
        other,
        raw.replace(
            "`unrelated`",
            "[owner](../../dev/123456789012/s3.md#resource-S3_Bucket_001)",
        ),
    )
    with pytest.raises(ValueError, match="Resource authority requires"):
        read_model(other)
    other.write_text("broken syntax\n")
    with pytest.raises(ValueError, match="unsupported Model format"):
        read_model(other)


@pytest.mark.parametrize("problem", [None, "key", "stack", "target", "owner"])
def check_deferred_reference_requires_exact_typed_ownership(project_workspace, problem):
    root = project_workspace
    model_reference_fixtures.project(root)
    record = dict(
        consumer="qa/team/iam",
        consumerKey="desired.row.001-002.document",
        producer="qa/team/kms/KMS_Key_001",
    )
    mappings = {
        "producer": {
            "Resource001": dict(service="kms", resource="KMS_Key_001"),
            "IntegratedChild": dict(service="kms", resource="KMS_Key_001"),
        }
    }
    if problem == "key":
        record["consumerKey"] = "desired.row.001-001.value"
    elif problem == "stack":
        record["stack"] = "unselected"
    elif problem == "target":
        record["consumer"] = "qa/other/iam"
    elif problem == "owner":
        mappings["producer"]["Resource001"]["resource"] = "KMS_Key_999"
    if problem:
        with pytest.raises((ValueError, RuntimeError)):
            deferred.verify(root, record, mappings, ("qa", "team"))
    else:
        verified = deferred.verify(root, record, mappings, ("qa", "team"))
        assert verified["stack"] == "producer" and not verified["referenceSynced"]


def check_deferred_owner_and_reference_barriers_are_separate():
    local = dict(
        stack="producer", consumer="qa/team/iam", approved=True, referenceSynced=True
    )
    foreign = dict(stack="producer", consumer="qa/other/iam", referenceSynced=False)
    context = dict(
        states={"producer": dict(deferredConsumers=[local, foreign])},
        pendingGeneration={"docs/designs/qa/team/iam.md": {}},
    )
    deferred.model_saved(context, dict(services=["iam"], evidence={"producer": {}}))
    assert local["ownerObservedSynced"] and foreign["ownerObservedSynced"]
    assert local["referenceObservedSynced"] and not local["referenceSynced"]
    deferred.views_saved(context)
    assert not local["referenceSynced"]
    context["pendingGeneration"].clear()
    context["generationError"] = "unresolved"
    deferred.views_saved(context)
    assert not local["referenceSynced"]
    context.pop("generationError")
    deferred.views_saved(context)
    assert local["referenceSynced"] and not foreign["referenceSynced"]
    assert len(context["states"]["producer"]["deferredConsumers"]) == 2


def check_other_target_declared_reference_is_retained_read_only(tmp_path, monkeypatch):
    consumer = tmp_path / "model/stg/other/rds.properties"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("independent target authority\n", encoding="utf-8")
    original = consumer.read_bytes()
    producer = tmp_path / "model/dev/team/ec2.properties"
    snapshot = SimpleNamespace(
        authoritative={"desired.reference.001.consumerKey": "desired.row.001-001.value"}
    )
    usage = SimpleNamespace(
        attribute=None,
        metadata_id="001",
        producer_kind="resource",
        producer_scope="dev/team/ec2",
        logical_id="EC2_Subnet_001",
        consumer_key="desired.row.001-001.value",
    )
    monkeypatch.setattr(observed_adapter, "model_paths", Mock(return_value=[consumer]))
    monkeypatch.setattr(observed_adapter, "raw_model", Mock(return_value=snapshot))
    monkeypatch.setattr(observed_adapter, "usages", Mock(return_value=[usage]))
    changes, records = {}, []
    propagate_references(
        tmp_path,
        {producer: {}},
        changes,
        {("dev", "team", "ec2", "EC2_Subnet_001"): "subnet-current"},
        allowed_services={("dev", "team", "ec2")},
        deferred=records,
    )
    assert not changes and len(records) == 1
    assert records[0]["consumer"] == "stg/other/rds"
    assert records[0]["producer"] == "dev/team/ec2/EC2_Subnet_001"
    assert records[0]["referenceKind"] == "declared"
    assert consumer.read_bytes() == original


def check_ingress_rule_confirmation():
    document = {
        "Resources": {
            "Rule": {
                "Type": "AWS::EC2::SecurityGroupIngress",
                "Properties": {
                    "GroupId": "sg-12345678",
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "SourceSecurityGroupId": "sg-abcdef12",
                },
            }
        }
    }
    stack = {
        "StackId": "stack",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": [],
        "Parameters": [],
    }
    actual = {"ResourceStatus": "CREATE_COMPLETE", "PhysicalResourceId": "sg-12345678"}
    rule = {
        "GroupId": "sg-12345678",
        "IsEgress": False,
        "IpProtocol": "tcp",
        "FromPort": 443,
        "ToPort": 443,
        "ReferencedGroupInfo": {"GroupId": "sg-abcdef12"},
        "SecurityGroupRuleId": "sgr-12345678",
    }
    records = [rule]

    aws = _bind_framework_callback(_sg_rule_aws, document, records, stack)

    backend = SimpleNamespace(aws=aws)

    result = _bind_framework_callback(_sg_rule_result, backend, stack, document, actual)

    assert result() == "sgr-12345678"
    assert result("sgr-99999999") is None
    records[:] = [rule, rule]
    assert result() is None
    records[:] = [{**rule, "IsEgress": True}]
    assert result() is None
    records[:] = [{**rule, "ReferencedGroupInfo": {"GroupId": "sg-bad"}}]
    assert result() is None
    records[:] = []
    assert result() is None
    assert service_module("security-group").rule_candidates(
        [rule],
        "sg-12345678",
        False,
        {
            "IpProtocol": "6",
            "FromPort": 443,
            "ToPort": 443,
            "SourceSecurityGroupId": "sg-abcdef12",
        },
    ) == [rule]


def check_ingress_cidr_and_recreation():
    module = service_module("security-group")
    expected = {
        "IpProtocol": "tcp",
        "FromPort": 443,
        "ToPort": 443,
        "CidrIp": "10.0.0.0/24",
    }
    rule = {
        "GroupId": "sg-parent",
        "IsEgress": False,
        "IpProtocol": "tcp",
        "FromPort": 443,
        "ToPort": 443,
        "CidrIpv4": "10.0.0.0/24",
        "SecurityGroupRuleId": "sgr-new",
    }
    assert module.rule_candidates([rule], "sg-parent", False, expected) == [rule]
    for replacement in (
        {"GroupId": "sg-other"},
        {"IsEgress": True},
        {"FromPort": 80},
        {"CidrIpv4": "10.0.1.0/24"},
    ):
        assert not module.rule_candidates(
            [{**rule, **replacement}], "sg-parent", False, expected
        )
    with pytest.raises(Unresolved):
        module.rule_candidates([rule], "sg-parent", False, {"IpProtocol": "tcp"})


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
