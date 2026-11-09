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
from design.catalog import DesignSchemaCatalog
from model.adapters.aws import Unresolved, service_module
from model.adapters.observation_sources import physical_identifier_source
from model.adapters.observed import (
    propagate_references,
    resolve_resources,
)
from model.core import properties
from model.files import read_model
from model.format import parse
from support import model_reference_fixtures
from support.cloudformation_deploy_fixtures import TARGET
from support.model_sources import allocate_fixture, write_model
from utils.aws.client import AwsError

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _config_rule_denied_aws(document, denied, operation, **kwargs):
    if operation == ("get_template" if denied == "template" else "get_resource"):
        raise AwsError("aws", operation, "AccessDeniedException")
    return _config_rule_sync_aws(document, operation, **kwargs)


def _cloudcontrol_test_aws(document, physical, attribute, stack, operation, **kwargs):
    if operation == "get_template":
        return {"TemplateBody": document}
    if operation == "get_resource":
        return {
            "ResourceDescription": {
                "Identifier": physical,
                "Properties": json.dumps({attribute: physical}),
            }
        }
    if operation == "describe_stacks":
        return {"Stacks": [stack]}
    raise AssertionError(operation)


def _permission_test_aws(document, fault, arn, statement, stack, operation, **kwargs):
    if operation == "get_template":
        return {"TemplateBody": document}
    if operation == "describe_rule":
        bus = (
            "aws.partner/vendor/bus"
            if fault == "partner"
            else "default"
            if fault == "rule-bus-omitted"
            else "custom"
        )
        assert kwargs == {"service": "events", "Name": "my-rule", "EventBusName": bus}
        return {
            "Name": "other" if fault == "name" else "my-rule",
            "EventBusName": "other" if fault == "bus" else bus,
            "Arn": arn + "-other" if fault == "arn" else arn,
        }
    if operation == "get_policy":
        return {"Policy": json.dumps({"Statement": [statement]})}
    if operation == "describe_stacks":
        return {"Stacks": [stack]}
    raise AssertionError(operation)


def _config_rule_evidence_aws(document, fault, description, stack, operation, **kwargs):
    if operation == "get_template":
        return {"TemplateBody": document}
    if operation == "get_resource":
        assert kwargs == {
            "service": "cloudcontrol",
            "TypeName": "AWS::Config::ConfigRule",
            "Identifier": "rule-name",
        }
        if fault == "denied":
            raise AwsError("cloudcontrol", "get_resource", "AccessDeniedException")
        if fault == "no-description":
            return {}
        if fault == "invalid-description":
            return {"ResourceDescription": []}
        return {"ResourceDescription": description}
    if operation == "describe_stacks":
        return {
            "Stacks": [
                dict(stack, StackStatus="UPDATE_IN_PROGRESS")
                if fault == "changed"
                else stack
            ]
        }
    raise AssertionError(operation)


def _config_rule_sync_aws(document, operation, **kwargs):
    if operation == "get_template":
        return {"TemplateBody": document}
    if operation == "get_resource":
        return {
            "ResourceDescription": {
                "Identifier": "rule-name",
                "Properties": json.dumps(
                    {"ConfigRuleName": "rule-name", "ConfigRuleId": "rule-id"}
                ),
            }
        }
    raise AssertionError(operation)


def _permission_evidence_aws(
    document, fault, function_name, statement, stack, operation, **kwargs
):
    if operation == "get_template":
        return {"TemplateBody": document}
    if operation == "get_resource" and fault in {
        "getatt",
        "getatt-sub",
        "source-mismatch",
    }:
        return {
            "ResourceDescription": {
                "Identifier": "my-bucket",
                "Properties": json.dumps(
                    {"BucketName": "my-bucket", "Arn": "arn:aws:s3:::my-bucket"}
                ),
            }
        }
    if operation == "list_exports" and fault == "import":
        return {
            "Exports": [
                {
                    "Name": "BucketName",
                    "Value": "my-bucket",
                    "ExportingStackId": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/bucket/unique",
                }
            ]
        }
    if (
        operation == "describe_stacks"
        and fault == "import"
        and kwargs.get("StackName", "").endswith("stack/bucket/unique")
    ):
        return {
            "Stacks": [
                {
                    "StackId": kwargs["StackName"],
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [
                        {
                            "OutputKey": "Bucket",
                            "OutputValue": "my-bucket",
                            "ExportName": "BucketName",
                        }
                    ],
                }
            ]
        }
    if operation == "get_policy":
        assert kwargs == {"service": "lambda", "FunctionName": function_name}
        if fault == "denied":
            raise AwsError("lambda", "get_policy", "AccessDeniedException")
        return {
            "Policy": json.dumps(
                {"Statement": [statement, dict(statement, Sid="sid-2")]}
            )
        }
    if operation == "describe_stacks":
        return {"Stacks": [stack]}
    raise AssertionError(operation)


def _permission_sync_aws(document, statements, operation, **kwargs):
    if operation == "get_template":
        return {"TemplateBody": document}
    if operation == "get_policy":
        return {"Policy": json.dumps({"Statement": statements})}
    raise AssertionError(operation)


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


def test_config_rule_identifier_mapping_does_not_require_output(project_workspace):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root, "config-rules", "Config.ConfigRule", attribute="ConfigRuleId"
    )
    model_reference_fixtures.write(scope, values)
    document = {"Resources": {"Resource001": {"Type": "AWS::Config::ConfigRule"}}}
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
    assert "Config.ConfigRule.ConfigRuleId" in mapped["producer"]["Resource001"][4]


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "identifier",
        "name",
        "missing",
        "denied",
        "changed",
        "no-description",
        "invalid-description",
        "unrelated-noecho",
        "required-noecho",
    ],
)
def test_cloudcontrol_config_rule_evidence(project_workspace, fault):
    root = project_workspace
    stack_id = (
        "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/producer/unique"
    )
    stack = {"StackId": stack_id, "StackStatus": "CREATE_COMPLETE", "Outputs": []}
    document = {"Resources": {"Resource001": {"Type": "AWS::Config::ConfigRule"}}}
    actual = {"ResourceStatus": "CREATE_COMPLETE", "PhysicalResourceId": "rule-name"}
    if fault in {"unrelated-noecho", "required-noecho"}:
        document["Parameters"] = {"Secret": {"Type": "String", "NoEcho": True}}
        stack["Parameters"] = [{"ParameterKey": "Secret", "ParameterValue": "****"}]
        if fault == "required-noecho":
            document["Conditions"] = {
                "Enabled": {"Fn::Equals": [{"Ref": "Secret"}, "x"]}
            }
            document["Resources"]["Resource001"]["Condition"] = "Enabled"
    payload = {
        "ConfigRuleName": "other" if fault == "name" else "rule-name",
        "ConfigRuleId": "rule-id",
    }
    description = {
        "Identifier": "other" if fault == "identifier" else "rule-name",
        "Properties": json.dumps(payload),
    }
    if fault == "missing":
        description.pop("Properties")

    aws = _bind_framework_callback(
        _config_rule_evidence_aws, document, fault, description, stack
    )

    backend = SimpleNamespace(root=root, target=TARGET, aws=aws)
    value, reason = deploy_observed.cloudcontrol_observation(
        backend,
        stack,
        document,
        {},
        actual,
        {"resourceType": "Config.ConfigRule"},
        "Config.ConfigRule.ConfigRuleId",
        DesignSchemaCatalog(root),
    )
    if fault in {None, "unrelated-noecho"}:
        assert (value, reason) == ("rule-id", None)
    else:
        assert value is None and reason
        if fault == "denied":
            assert "AccessDeniedException" in reason


@pytest.mark.parametrize(
    "previous,output,expected,denied",
    [
        (None, None, "UPDATED", False),
        ("rule-id", "rule-id", "UNCONFIRMED", "template"),
        ("rule-id", None, "MATCHED", False),
        (None, "different", "UNCONFIRMED", False),
        ("rule-id", "rule-id", "UNCONFIRMED", True),
    ],
)
def test_config_rule_collects_checked_api_value(
    project_workspace, monkeypatch, previous, output, expected, denied
):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root,
        "config-rules",
        "Config.ConfigRule",
        attribute="ConfigRuleId",
        observed=previous,
    )
    model_reference_fixtures.write(scope, values)
    document = {"Resources": {"Resource001": {"Type": "AWS::Config::ConfigRule"}}}
    if output:
        document["Outputs"] = {
            "Id": {"Value": {"Fn::GetAtt": ["Resource001", "ConfigRuleId"]}}
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
    stack = {
        "StackId": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/producer/unique",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": [{"OutputKey": "Id", "OutputValue": output}] if output else [],
    }

    aws = _bind_framework_callback(_config_rule_sync_aws, document)
    if denied:
        aws = _bind_framework_callback(_config_rule_denied_aws, document, denied)

    backend = SimpleNamespace(
        root=root,
        environment="qa",
        directory="team",
        target=TARGET,
        templates={"producer": (document, {})},
        aws=aws,
        run_context={},
    )
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
                "ResourceType": "AWS::Config::ConfigRule",
                "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": "rule-name",
            }
        ],
    )
    captured = {}
    monkeypatch.setattr(
        deploy_observed,
        "observed_destinations",
        _bind_framework_callback(_capture_destinations, captured),
    )
    states = {"producer": {}}
    deploy_observed.collect_successful(backend, [unit], states)
    assert states["producer"]["observedCoverage"]["Resource001"]["status"] == expected
    if expected == "UNCONFIRMED":
        assert "observed.row.001-001.value" not in captured[scope.path]
    else:
        assert captured[scope.path]["observed.row.001-001.value"] == "`rule-id`"


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "sid",
        "function",
        "parent",
        "action",
        "denied",
        "qualifier",
        "duplicate",
        "getatt",
        "getatt-sub",
        "import",
        "source-mismatch",
        "principal",
        "arn",
        "other-function-sid",
    ],
)
def test_lambda_permission_policy_identity(project_workspace, fault):
    root = project_workspace
    stack_id = (
        "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/producer/unique"
    )
    stack = {"StackId": stack_id, "StackStatus": "CREATE_COMPLETE", "Outputs": []}
    document = {
        "Resources": {
            "Function": {"Type": "AWS::Lambda::Function"},
            "Permission": {
                "Type": "AWS::Lambda::Permission",
                "Properties": {
                    "FunctionName": {"Ref": "Function"},
                    "Action": "lambda:InvokeFunction",
                    "Principal": "events.amazonaws.com",
                },
            },
        }
    }
    if fault == "qualifier":
        document["Resources"]["Permission"]["Properties"]["FunctionName"] = {
            "Fn::Sub": "${Function}:live"
        }
    if fault == "arn":
        document["Resources"]["Permission"]["Properties"]["FunctionName"] = (
            "arn:aws:lambda:ap-northeast-1:123456789012:function:my-function:live"
        )
    if fault == "import":
        document["Resources"]["Permission"]["Properties"]["SourceArn"] = {
            "Fn::Sub": [
                "arn:${AWS::Partition}:s3:::${BucketName}",
                {"BucketName": {"Fn::ImportValue": "BucketName"}},
            ]
        }
    if fault in {"getatt", "getatt-sub", "source-mismatch"}:
        document["Resources"]["Bucket"] = {"Type": "AWS::S3::Bucket"}
        document["Resources"]["Permission"]["Properties"]["SourceArn"] = (
            {"Fn::GetAtt": ["Bucket", "Arn"]}
            if fault != "getatt-sub"
            else {"Fn::Sub": "${Bucket.Arn}"}
        )
    function_name = (
        "arn:aws:lambda:ap-northeast-1:123456789012:function:my-function:live"
        if fault == "arn"
        else "my-function:live"
        if fault == "qualifier"
        else "my-function"
    )
    resource = {
        "resourceType": "Lambda.Permission",
        "parentReference": json.dumps(
            model_reference_fixtures.reference(
                "Other" if fault == "parent" else "Lambda_Function_001", "FunctionName"
            )
        ),
    }
    mapped = {
        "Function": (
            None,
            None,
            {"resourceType": "Lambda.Function", "logicalId": "Lambda_Function_001"},
            [],
            set(),
        )
    }
    mapped["Permission"] = (None, None, resource, [], set())
    if fault == "other-function-sid":
        mapped["OtherPermission"] = (
            None,
            None,
            {
                "resourceType": "Lambda.Permission",
                "parentReference": json.dumps(
                    model_reference_fixtures.reference("Other_Function", "FunctionName")
                ),
            },
            [],
            set(),
        )
        mapped["OtherFunction"] = (
            None,
            None,
            {"resourceType": "Lambda.Function", "logicalId": "Other_Function"},
            [],
            set(),
        )
    if fault in {"getatt", "getatt-sub", "source-mismatch"}:
        mapped["Bucket"] = (None, None, {"resourceType": "S3.Bucket"}, [], set())
    parent = {
        "LogicalResourceId": "Function",
        "ResourceType": "AWS::Lambda::Function",
        "ResourceStatus": "CREATE_COMPLETE",
        "PhysicalResourceId": "my-function",
    }
    actual = {
        "LogicalResourceId": "Permission",
        "ResourceType": "AWS::Lambda::Permission",
        "ResourceStatus": "CREATE_COMPLETE",
        "PhysicalResourceId": "sid-1",
    }
    statement = {
        "Sid": "wrong" if fault == "sid" else "sid-1",
        "Action": "wrong" if fault == "action" else "lambda:InvokeFunction",
        "Principal": {
            "Service": "wrong.amazonaws.com"
            if fault == "principal"
            else "events.amazonaws.com"
        },
        "Resource": "arn:aws:lambda:ap-northeast-1:123456789012:function:"
        + (
            "other"
            if fault == "function"
            else "my-function:live"
            if fault == "arn"
            else function_name
        ),
    }

    if fault in {"getatt", "getatt-sub", "import", "source-mismatch"}:
        statement["Condition"] = {
            "ArnLike": {
                "AWS:SourceArn": "arn:aws:s3:::other"
                if fault == "source-mismatch"
                else "arn:aws:s3:::my-bucket"
            }
        }

    aws = _bind_framework_callback(
        _permission_evidence_aws, document, fault, function_name, statement, stack
    )

    backend = SimpleNamespace(root=root, target=TARGET, aws=aws)
    value, reason = deploy_observed.permission_observation(
        backend,
        stack,
        document,
        {},
        {},
        [parent, actual]
        + (
            [
                dict(
                    parent,
                    LogicalResourceId="OtherFunction",
                    PhysicalResourceId="another-function",
                )
            ]
            if fault == "other-function-sid"
            else []
        )
        + (
            [
                {
                    "LogicalResourceId": "Bucket",
                    "ResourceType": "AWS::S3::Bucket",
                    "ResourceStatus": "CREATE_COMPLETE",
                    "PhysicalResourceId": "my-bucket",
                }
            ]
            if fault in {"getatt", "getatt-sub", "source-mismatch"}
            else []
        )
        + (
            [dict(actual, LogicalResourceId="OtherPermission")]
            if fault in {"duplicate", "other-function-sid"}
            else []
        ),
        mapped,
        "Permission",
        actual,
        resource,
    )
    if fault in {
        None,
        "qualifier",
        "getatt",
        "getatt-sub",
        "import",
        "arn",
        "other-function-sid",
    }:
        assert (value, reason) == ("sid-1", None), reason
    else:
        assert value is None and reason
        if fault == "denied":
            assert "AccessDeniedException" in reason


def test_two_lambda_permissions_collect_independently(project_workspace, monkeypatch):
    root = project_workspace
    stack = {
        "StackId": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/producer/unique",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": [],
    }
    document = {"Resources": {"Function": {"Type": "AWS::Lambda::Function"}}}
    path = root / "model/qa/team/lambda.properties"
    parent = {"resourceType": "Lambda.Function", "logicalId": "Lambda_Function_001"}
    mapped = {"producer": {"Function": (path, "001", parent, [], set())}}
    records = [
        {
            "LogicalResourceId": "Function",
            "ResourceType": "AWS::Lambda::Function",
            "ResourceStatus": "CREATE_COMPLETE",
            "PhysicalResourceId": "my-function",
        }
    ]
    statements = []
    for number in (1, 2):
        logical, sid, row = (
            f"Permission{number}",
            f"sid-{number}",
            f"00{number + 1}-001",
        )
        document["Resources"][logical] = {
            "Type": "AWS::Lambda::Permission",
            "Properties": {
                "FunctionName": {"Ref": "Function"},
                "Action": "lambda:InvokeFunction",
                "Principal": "events.amazonaws.com",
            },
        }
        resource = {
            "resourceType": "Lambda.Permission",
            "logicalId": f"Lambda_Permission_00{number}",
            "parentReference": json.dumps(
                model_reference_fixtures.reference(
                    "Lambda_Function_001", "FunctionName"
                )
            ),
        }
        mapped["producer"][logical] = (
            path,
            f"00{number + 1}",
            resource,
            [(row, {"property": "Lambda.Permission.Id"})],
            {"Lambda.Permission.Id"},
        )
        records.append(
            {
                "LogicalResourceId": logical,
                "ResourceType": "AWS::Lambda::Permission",
                "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": sid,
            }
        )
        statements.append(
            {
                "Sid": sid,
                "Action": "lambda:InvokeFunction",
                "Principal": {"Service": "events.amazonaws.com"},
                "Resource": "arn:aws:lambda:ap-northeast-1:123456789012:function:my-function",
            }
        )

    aws = _bind_framework_callback(_permission_sync_aws, document, statements)

    backend = SimpleNamespace(
        root=root,
        environment="qa",
        directory="team",
        target=TARGET,
        templates={"producer": (document, {})},
        aws=aws,
        run_context={},
    )
    monkeypatch.setattr(
        deploy_observed, "resolve_resources", lambda *a, **k: ({path: {}}, mapped)
    )
    monkeypatch.setattr(
        deploy_observed.execution_scope, "check_fixed_resources", lambda *a, **k: None
    )
    monkeypatch.setattr(deploy_observed.current_state, "read", lambda *a: stack)
    monkeypatch.setattr(deploy_observed.current_state, "pages", lambda *a, **k: records)
    monkeypatch.setattr(deploy_observed, "propagate_references", lambda *a, **k: None)
    captured = {}
    monkeypatch.setattr(
        deploy_observed,
        "observed_destinations",
        _bind_framework_callback(_capture_destinations, captured),
    )
    states = {"producer": {}}
    deploy_observed.collect_successful(backend, [{"name": "producer"}], states)
    assert captured[path] == {
        "observed.row.002-001.value": "`sid-1`",
        "observed.row.003-001.value": "`sid-2`",
    }
    assert all(
        states["producer"]["observedCoverage"][f"Permission{n}"]["status"] == "UPDATED"
        for n in (1, 2)
    )


def test_unsupported_observation_reports_and_remains_unconfirmed(
    project_workspace, monkeypatch
):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root,
        "config-rules",
        "Config.ConfigRule",
        attribute="ConfigRuleId",
        observed="old",
    )
    model_reference_fixtures.write(scope, values)
    document = {"Resources": {"Resource001": {"Type": "AWS::Config::ConfigRule"}}}
    monkeypatch.setattr(observed_adapter, "cloudcontrol_source", lambda *args: None)
    monkeypatch.setattr(deploy_observed, "cloudcontrol_source", lambda *args: None)
    with pytest.warns(
        UserWarning, match="unsupported observation.*Config.ConfigRule.ConfigRuleId"
    ):
        mapped = resolve_resources(
            root,
            "qa",
            "team",
            {"producer": (document, {})},
            [{"name": "producer"}],
            {"producer": {"Resource001"}},
            target=TARGET,
            check_scope=False,
        )
    stack = {"StackId": "stack", "StackStatus": "CREATE_COMPLETE", "Outputs": []}
    backend = SimpleNamespace(
        root=root,
        environment="qa",
        directory="team",
        target=TARGET,
        templates={"producer": (document, {})},
        aws=Mock(),
        run_context={},
    )
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
                "ResourceType": "AWS::Config::ConfigRule",
                "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": "rule-name",
            }
        ],
    )
    captured = {}
    monkeypatch.setattr(
        deploy_observed,
        "observed_destinations",
        _bind_framework_callback(_capture_destinations, captured),
    )
    states = {"producer": {}}
    deploy_observed.collect_successful(backend, [{"name": "producer"}], states)
    assert "observed.row.001-001.value" not in captured[scope.path]
    coverage = states["producer"]["observedCoverage"]["Resource001"]
    assert coverage["status"] == "UNCONFIRMED"
    assert (
        "supported API getter" in coverage["reasons"]["Config.ConfigRule.ConfigRuleId"]
    )


def test_evidence_parameters_ignore_unrelated_noecho():
    document = {
        "Parameters": {
            "Secret": {"Type": "String", "NoEcho": True},
            "Name": {"Type": "String"},
        },
        "Conditions": {"Selected": {"Fn::Equals": [{"Ref": "Name"}, "yes"]}},
    }
    stack = {
        "Parameters": [
            {"ParameterKey": "Secret", "ParameterValue": "****"},
            {"ParameterKey": "Name", "ParameterValue": "yes"},
        ]
    }
    assert deploy_observed.checked_evidence_parameters(
        document, {"Name": "yes", "Secret": "private"}, stack, {"Condition": "Selected"}
    )
    assert not deploy_observed.checked_evidence_parameters(
        document, {"Name": "no", "Secret": "private"}, stack, {"Condition": "Selected"}
    )
    assert not deploy_observed.checked_evidence_parameters(
        document, {"Secret": "private"}, stack, {"Ref": "Secret"}
    )


def test_security_group_physical_id_contract():
    resource = {"resourceType": "EC2.SecurityGroup"}
    assert physical_identifier_source(resource, "EC2.SecurityGroup.Id", "sg-0123abcd")
    assert not physical_identifier_source(
        resource, "EC2.SecurityGroup.Id", "group-name"
    )
    assert not physical_identifier_source(
        {"resourceType": "WAFv2.WebACL"}, "WAFv2.WebACL.Id", "name|id|scope"
    )


@pytest.mark.parametrize(
    "kind,physical,output,expected",
    [
        ("EC2.SecurityGroup", "sg-0123abcd", None, "sg-0123abcd"),
        ("EC2.SecurityGroupIngress", "sgr-0123abcd", None, "sgr-0123abcd"),
        ("EC2.SecurityGroupEgress", "sgr-0123abcd", None, "sgr-0123abcd"),
        ("EC2.SecurityGroupIngress", "sg-0123abcd", None, None),
        ("Glue.Connection", "connection", None, "connection"),
        ("Glue.Connection", "connection", "connection", "connection"),
        ("Glue.Connection", "connection", "other", None),
    ],
)
def test_stack_physical_identifier_observation(
    project_workspace, monkeypatch, kind, physical, output, expected
):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    service, attribute = (
        ("glue", "Name") if kind == "Glue.Connection" else ("security-group", "Id")
    )
    scope, values = model_reference_fixtures.resource_values(
        root, service, kind, attribute=attribute
    )
    values["desired.row.001-001.property"] = f"{kind}.{attribute}"
    model_reference_fixtures.write(scope, values)
    cfn_type = "AWS::" + kind.replace(".", "::")
    document = {"Resources": {"Resource001": {"Type": cfn_type}}}
    if output is not None:
        document["Outputs"] = {"ResourceName": {"Value": {"Ref": "Resource001"}}}
    unit = {"name": "producer"}
    _, mapped = resolve_resources(
        root,
        "qa",
        "team",
        {"producer": (document, {})},
        [unit],
        {"producer": {"Resource001"}},
        target=TARGET,
        check_scope=False,
    )
    stack = {
        "StackId": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/producer/unique",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": (
            [] if output is None else [{"OutputKey": "ResourceName", "OutputValue": output}]
        ),
    }
    backend = SimpleNamespace(
        root=root,
        environment="qa",
        directory="team",
        target=TARGET,
        templates={"producer": (document, {})},
        aws=Mock(),
        run_context={},
    )
    monkeypatch.setattr(
        deploy_observed,
        "resolve_resources",
        lambda *a, **k: ({scope.path: values}, mapped),
    )
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
                "ResourceType": cfn_type,
                "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": physical,
            }
        ],
    )
    captured = {}
    monkeypatch.setattr(
        deploy_observed,
        "observed_destinations",
        _bind_framework_callback(_capture_destinations, captured),
    )
    states = {"producer": {}}
    deploy_observed.collect_successful(backend, [unit], states)
    coverage = states["producer"]["observedCoverage"]["Resource001"]
    if expected is None:
        assert coverage["status"] == "UNCONFIRMED"
        assert "observed.row.001-001.value" not in captured[scope.path]
    else:
        assert coverage["status"] == "UPDATED"
        assert captured[scope.path]["observed.row.001-001.value"] == f"`{expected}`"


@pytest.mark.parametrize(
    "kind,attribute,physical",
    [
        ("Route53Resolver.ResolverEndpoint", "ResolverEndpointId", "rslvr-in-0123"),
        ("CloudFront.OriginAccessControl", "Id", "E123456789"),
        ("GuardDuty.MalwareProtectionPlan", "MalwareProtectionPlanId", "0123456789abcdef0123"),
    ],
)
def test_provider_confirms_single_identifier_without_output(
    project_workspace, kind, attribute, physical
):
    stack = {
        "StackId": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/producer/unique",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": [],
    }
    document = {
        "Resources": {
            "Resource001": {
                "Type": DesignSchemaCatalog(project_workspace).cloudformation_type(kind)
            }
        }
    }
    actual = {
        "LogicalResourceId": "Resource001",
        "ResourceStatus": "CREATE_COMPLETE",
        "PhysicalResourceId": physical,
    }

    aws = _bind_framework_callback(
        _cloudcontrol_test_aws, document, physical, attribute, stack
    )

    backend = SimpleNamespace(root=project_workspace, target=TARGET, aws=aws)
    assert deploy_observed.cloudcontrol_observation(
        backend,
        stack,
        document,
        {},
        actual,
        {"resourceType": kind},
        kind + "." + attribute,
        DesignSchemaCatalog(project_workspace),
    ) == (physical, None)


def test_incomplete_stack_observation_is_rejected():
    good = {
        "LogicalResourceId": "Thing",
        "ResourceType": "AWS::S3::Bucket",
        "ResourceStatus": "CREATE_COMPLETE",
    }
    assert deploy_observed.complete_stack_observation({"Outputs": []}, [good])
    assert not deploy_observed.complete_stack_observation(
        {"Outputs": [{"OutputKey": "Id"}]}, [good]
    )
    assert not deploy_observed.complete_stack_observation(
        {"Outputs": []}, [{"ResourceType": "AWS::S3::Bucket"}]
    )
    assert not deploy_observed.complete_stack_observation(
        {
            "Outputs": [
                {"OutputKey": "Id", "OutputValue": "one"},
                {"OutputKey": "Id", "OutputValue": "two"},
            ]
        },
        [good],
    )


@pytest.mark.parametrize("sub", [False, True])
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "name",
        "bus",
        "arn",
        "physical",
        "if-inactive",
        "if-secret",
        "if-missing",
        "bus-ref",
        "bus-arn",
        "partner",
        "bus-account",
        "bus-region",
        "bus-ambiguous",
        "no-value",
        "no-value-mismatch",
        "no-value-required",
        "if-noecho-inactive",
        "no-value-account",
        "no-value-account-mismatch",
        "bus-type",
        "rule-bus-omitted",
        "rule-name-omitted",
        "rule-bus-custom",
        "rule-condition-unknown",
        "rule-unused-secret",
        "rule-unused-resource",
    ],
)
def test_permission_event_rule_arn_identity(project_workspace, sub, fault):
    root = project_workspace
    stack_id = (
        "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/producer/unique"
    )
    stack = {"StackId": stack_id, "StackStatus": "CREATE_COMPLETE", "Outputs": []}
    arn = "arn:aws:events:ap-northeast-1:123456789012:rule/custom/my-rule"
    expression = (
        {"Fn::Sub": "${EventRule.Arn}"} if sub else {"Fn::GetAtt": ["EventRule", "Arn"]}
    )
    document = {
        "Resources": {
            "Function": {"Type": "AWS::Lambda::Function"},
            "EventRule": {
                "Type": "AWS::Events::Rule",
                "Properties": {"Name": "my-rule", "EventBusName": "custom"},
            },
            "Permission": {
                "Type": "AWS::Lambda::Permission",
                "Properties": {
                    "FunctionName": {"Ref": "Function"},
                    "Action": "lambda:InvokeFunction",
                    "Principal": "events.amazonaws.com",
                    "SourceArn": expression,
                },
            },
        }
    }
    params = {}
    bus_props = document["Resources"]["EventRule"]["Properties"]
    if fault in {"bus-ref", "bus-ambiguous", "bus-type"}:
        document["Resources"]["Bus"] = {"Type": "AWS::Events::EventBus"}
        bus_props["EventBusName"] = {"Ref": "Bus"}
    elif fault in {"bus-arn", "bus-account", "bus-region"}:
        account = "999999999999" if fault == "bus-account" else "123456789012"
        region = "us-east-1" if fault == "bus-region" else "ap-northeast-1"
        bus_props["EventBusName"] = (
            f"arn:aws:events:{region}:{account}:event-bus/custom"
        )
    elif fault == "partner":
        bus_props["EventBusName"] = "aws.partner/vendor/bus"
        arn = "arn:aws:events:ap-northeast-1:123456789012:rule/aws.partner/vendor/bus/my-rule"
    if fault in {
        "no-value",
        "no-value-mismatch",
        "no-value-required",
        "if-noecho-inactive",
        "no-value-account",
        "no-value-account-mismatch",
    }:
        document["Parameters"] = {"Secret": {"Type": "String", "NoEcho": True}}
        document["Conditions"] = {"Selected": {"Fn::Equals": ["yes", "yes"]}}
        stack["Parameters"] = [{"ParameterKey": "Secret", "ParameterValue": "****"}]
        params = {"Secret": "private"}
        props = document["Resources"]["Permission"]["Properties"]
        if fault == "if-noecho-inactive":
            props["SourceArn"] = {"Fn::If": ["Selected", expression, {"Ref": "Secret"}]}
        else:
            key = (
                "Action"
                if fault == "no-value-required"
                else "SourceAccount"
                if fault in {"no-value-account", "no-value-account-mismatch"}
                else "SourceArn"
            )
            props[key] = {"Fn::If": ["Selected", {"Ref": "AWS::NoValue"}, expression]}
    if fault.startswith("if-") and fault != "if-noecho-inactive" if fault else False:
        document["Parameters"] = {
            "Choice": {"Type": "String"},
            "Secret": {"Type": "String", "NoEcho": True},
        }
        document["Conditions"] = {
            "Selected": {"Fn::Equals": [{"Ref": "Choice"}, "yes"]}
        }
        stack["Parameters"] = [
            {"ParameterKey": "Choice", "ParameterValue": "yes"},
            {"ParameterKey": "Secret", "ParameterValue": "****"},
        ]
        params = {"Choice": "yes", "Secret": "private"}
        unused = (
            {"Ref": "Secret"}
            if fault == "if-secret"
            else {"Fn::GetAtt": ["Missing", "Arn"]}
        )
        condition = "Unknown" if fault == "if-missing" else "Selected"
        document["Resources"]["Permission"]["Properties"]["SourceArn"] = {
            "Fn::If": [
                condition,
                unused if fault == "if-secret" else expression,
                expression if fault == "if-secret" else unused,
            ]
        }
    if fault and fault.startswith("rule-"):
        document["Conditions"] = {"Selected": {"Fn::Equals": ["yes", "yes"]}}
        if fault == "rule-bus-omitted":
            bus_props["EventBusName"] = {
                "Fn::If": ["Selected", {"Ref": "AWS::NoValue"}, "custom"]
            }
            arn = "arn:aws:events:ap-northeast-1:123456789012:rule/my-rule"
        elif fault == "rule-name-omitted":
            bus_props["Name"] = {
                "Fn::If": ["Selected", {"Ref": "AWS::NoValue"}, "other"]
            }
        elif fault == "rule-bus-custom":
            bus_props["EventBusName"] = {
                "Fn::If": ["Selected", "custom", {"Ref": "AWS::NoValue"}]
            }
        elif fault == "rule-condition-unknown":
            bus_props["EventBusName"] = {
                "Fn::If": ["Unknown", "custom", {"Ref": "AWS::NoValue"}]
            }
        elif fault == "rule-unused-secret":
            document["Parameters"] = {"Secret": {"Type": "String", "NoEcho": True}}
            stack["Parameters"] = [{"ParameterKey": "Secret", "ParameterValue": "****"}]
            params = {"Secret": "private"}
            bus_props["EventBusName"] = {
                "Fn::If": ["Selected", "custom", {"Ref": "Secret"}]
            }
        else:
            bus_props["Name"] = {
                "Fn::If": ["Selected", "my-rule", {"Fn::GetAtt": ["Missing", "Arn"]}]
            }
    resource = {
        "resourceType": "Lambda.Permission",
        "parentReference": json.dumps(
            model_reference_fixtures.reference("Lambda_Function_001", "FunctionName")
        ),
    }
    mapped = {
        "Function": (
            None,
            None,
            {"resourceType": "Lambda.Function", "logicalId": "Lambda_Function_001"},
            [],
            set(),
        ),
        "EventRule": (None, None, {"resourceType": "Events.Rule"}, [], set()),
        "Permission": (None, None, resource, [], set()),
    }
    if fault in {"bus-ref", "bus-ambiguous", "bus-type"}:
        mapped["Bus"] = (
            None,
            None,
            {"resourceType": "S3.Bucket" if fault == "bus-type" else "Events.EventBus"},
            [],
            set(),
        )
    actuals = [
        {
            "LogicalResourceId": logical,
            "ResourceType": kind,
            "ResourceStatus": "CREATE_COMPLETE",
            "PhysicalResourceId": physical,
        }
        for logical, kind, physical in [
            ("Function", "AWS::Lambda::Function", "my-function"),
            (
                "EventRule",
                "AWS::Events::Rule",
                "wrong" if fault == "physical" else "my-rule",
            ),
            ("Permission", "AWS::Lambda::Permission", "sid-1"),
        ]
    ]
    permission_actual = actuals[-1]
    if fault in {"bus-ref", "bus-ambiguous", "bus-type"}:
        bus_actual = {
            "LogicalResourceId": "Bus",
            "ResourceType": "AWS::Events::EventBus",
            "ResourceStatus": "CREATE_COMPLETE",
            "PhysicalResourceId": "custom",
        }
        actuals.append(bus_actual)
        if fault == "bus-ambiguous":
            actuals.append(dict(bus_actual))
    statement = {
        "Sid": "sid-1",
        "Action": "lambda:InvokeFunction",
        "Principal": {"Service": "events.amazonaws.com"},
        "Resource": "arn:aws:lambda:ap-northeast-1:123456789012:function:my-function",
        "Condition": {"ArnLike": {"AWS:SourceArn": arn}},
    }
    if fault == "no-value":
        statement.pop("Condition")
    if fault == "no-value-account-mismatch":
        statement["Condition"]["StringEquals"] = {"AWS:SourceAccount": "123456789012"}

    aws = _bind_framework_callback(
        _permission_test_aws, document, fault, arn, statement, stack
    )

    backend = SimpleNamespace(root=root, target=TARGET, aws=aws)
    value, reason = deploy_observed.permission_observation(
        backend,
        stack,
        document,
        params,
        {},
        actuals,
        mapped,
        "Permission",
        permission_actual,
        resource,
    )
    assert (
        (value == "sid-1" and reason is None)
        if fault
        in {
            None,
            "if-inactive",
            "if-noecho-inactive",
            "bus-ref",
            "bus-arn",
            "partner",
            "no-value",
            "no-value-account",
            "rule-bus-omitted",
            "rule-name-omitted",
            "rule-bus-custom",
            "rule-unused-secret",
            "rule-unused-resource",
        }
        else (value is None and reason)
    ), reason


def test_evidence_if_uses_only_confirmed_branch(project_workspace):
    document = {
        "Parameters": {
            "Secret": {"Type": "String", "NoEcho": True},
            "Choice": {"Type": "String"},
        },
        "Conditions": {"Selected": {"Fn::Equals": [{"Ref": "Choice"}, "yes"]}},
    }
    stack = {
        "Parameters": [
            {"ParameterKey": "Secret", "ParameterValue": "****"},
            {"ParameterKey": "Choice", "ParameterValue": "yes"},
        ]
    }
    params = {"Secret": "private", "Choice": "yes"}
    good = {"Fn::If": ["Selected", "safe", {"Ref": "Secret"}]}
    bad = {"Fn::If": ["Selected", {"Ref": "Secret"}, "safe"]}
    assert deploy_observed.checked_evidence_parameters(document, params, stack, good)
    assert not deploy_observed.checked_evidence_parameters(document, params, stack, bad)
    backend = SimpleNamespace(
        root=project_workspace,
        target=TARGET,
        aws=lambda *a, **k: pytest.fail("inactive GetAtt fetched"),
    )
    inactive = {"Fn::If": ["Selected", "safe", {"Fn::GetAtt": ["Missing", "Arn"]}]}
    assert (
        deploy_observed.permission_expression(
            inactive, backend, [], {}, document, params, {}, stack
        )
        == "safe"
    )
    with pytest.raises(deploy_observed.Blocked):
        deploy_observed.permission_expression(
            {"Fn::If": ["Missing", "safe", "other"]},
            backend,
            [],
            {},
            document,
            params,
            {},
            stack,
        )


@pytest.mark.parametrize(
    "case,old,expected,status",
    [
        ("unrelated-unicode", "old", "`project`", "UPDATED"),
        ("selected-template", "old", None, "UNCONFIRMED"),
        ("missing-template-resource", "old", None, "UNCONFIRMED"),
        ("template-conditions", "old", None, "UNCONFIRMED"),
        ("no-output", "old", "`project`", "UPDATED"),
        ("omitted", "old", "`project`", "UPDATED"),
        ("not-found", "old", None, "UNCONFIRMED"),
        ("not-found-invalid", "old", None, "UNCONFIRMED"),
        ("multiple", "old", None, "UNCONFIRMED"),
        ("missing-projects", "old", None, "UNCONFIRMED"),
        ("invalid-project", "old", None, "UNCONFIRMED"),
        ("output", "old", "`project`", "UPDATED"),
        ("output", "project", "`project`", "MATCHED"),
        ("output-mismatch", "old", None, "UNCONFIRMED"),
        ("physical-mismatch", "old", None, "UNCONFIRMED"),
        ("missing", "old", None, "UNCONFIRMED"),
        ("incomplete", "old", None, "UNCONFIRMED"),
        ("denied", "old", None, "UNCONFIRMED"),
        ("output-denied", "old", None, "UNCONFIRMED"),
        ("changed", "old", None, "UNCONFIRMED"),
        ("account", "old", None, "UNCONFIRMED"),
        ("region", "old", None, "UNCONFIRMED"),
        ("wrong-stack", "old", None, "UNCONFIRMED"),
        ("arn-account", "old", None, "UNCONFIRMED"),
        ("arn-region", "old", None, "UNCONFIRMED"),
    ],
)
def test_codebuild_id_from_api_without_output(
    project_workspace, monkeypatch, case, old, expected, status
):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    scope, values = model_reference_fixtures.resource_values(
        root, "codebuild", "CodeBuild.Project", attribute="Id", observed=old
    )
    model_reference_fixtures.write(scope, values)
    document = {"Resources": {"Resource001": {"Type": "AWS::CodeBuild::Project"}}}
    if case in {"output", "output-mismatch", "output-denied"}:
        document["Outputs"] = {"Project": {"Value": {"Ref": "Resource001"}}}
    if case == "unrelated-unicode":
        document["Conditions"] = {"OtherAbsent": {"Fn::Equals": [1, 2]}}
        document["Resources"]["Other"] = {
            "Type": "AWS::SNS::Topic",
            "Condition": "OtherAbsent",
            "Properties": {"DisplayName": "承認"},
        }
    unit = {"name": "producer"}
    _, mapped = resolve_resources(
        root,
        "qa",
        "team",
        {"producer": (document, {})},
        [unit],
        {"producer": {"Resource001"}},
        target=TARGET,
        check_scope=False,
    )
    stack = {
        "StackId": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/producer/unique",
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": (
            [
                {
                    "OutputKey": "Project",
                    "OutputValue": "other" if case == "output-mismatch" else "project",
                }
            ]
            if "Outputs" in document
            else []
        ),
    }
    if case == "account":
        stack["StackId"] = stack["StackId"].replace("123456789012", "999999999999")
    if case == "region":
        stack["StackId"] = stack["StackId"].replace("ap-northeast-1", "us-east-1")
    if case == "wrong-stack":
        stack["StackId"] = stack["StackId"].replace("/producer/", "/other/")

    backend = SimpleNamespace(
        root=root,
        environment="qa",
        directory="team",
        target=TARGET,
        templates={"producer": (document, {})},
        aws=_bind_framework_callback(_codebuild_sync_aws, document, case),
        run_context={},
    )
    monkeypatch.setattr(
        deploy_observed,
        "resolve_resources",
        lambda *a, **k: ({scope.path: values}, mapped),
    )
    monkeypatch.setattr(
        deploy_observed.execution_scope, "check_fixed_resources", lambda *a, **k: None
    )
    reads = []

    monkeypatch.setattr(
        deploy_observed.current_state,
        "read",
        _bind_framework_callback(_codebuild_sync_read, reads, stack, case),
    )
    monkeypatch.setattr(
        deploy_observed.current_state,
        "pages",
        lambda *a, **k: [
            {
                "LogicalResourceId": "Resource001",
                "ResourceType": "AWS::CodeBuild::Project",
                "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": "project",
            }
        ],
    )
    captured = {}
    monkeypatch.setattr(
        deploy_observed,
        "observed_destinations",
        _bind_framework_callback(_capture_destinations, captured),
    )
    states = {"producer": {}}
    deploy_observed.collect_successful(backend, [unit], states)
    if expected is None:
        assert "observed.row.001-001.value" not in captured[scope.path]
        assert "`old`" in scope.path.read_text(encoding="utf-8")
    else:
        assert captured[scope.path]["observed.row.001-001.value"] == expected
    assert states["producer"]["observedCoverage"]["Resource001"]["status"] == status


def _codebuild_sync_aws(document, case, operation, **kwargs):
    if operation == "get_template":
        deployed = json.loads(json.dumps(document))
        if case == "unrelated-unicode":
            deployed["Resources"]["Other"]["Properties"]["DisplayName"] = "??"
        if case == "selected-template":
            deployed["Resources"]["Resource001"]["Properties"] = {"Name": "other"}
        if case == "missing-template-resource":
            deployed["Resources"].pop("Resource001")
        if case == "template-conditions":
            deployed["Conditions"] = {"Enabled": {"Fn::Equals": [1, 2]}}
        return {"TemplateBody": deployed}
    if operation == "batch_get_projects":
        assert kwargs == {"service": "codebuild", "names": ["project"]}
        if case in {"denied", "output-denied"}:
            raise AwsError("codebuild", operation, "AccessDeniedException")
        if case == "missing":
            return {"projects": [], "projectsNotFound": ["project"]}
        if case == "incomplete":
            return {"projects": [{"name": "project"}], "projectsNotFound": []}
        if case == "missing-projects":
            return {"projectsNotFound": []}
        if case == "invalid-project":
            return {"projects": ["project"], "projectsNotFound": []}
        name = "other" if case == "physical-mismatch" else "project"
        arn = "arn:aws:codebuild:ap-northeast-1:123456789012:project/" + name
        if case == "arn-account":
            arn = arn.replace("123456789012", "999999999999")
        if case == "arn-region":
            arn = arn.replace("ap-northeast-1", "us-east-1")
        projects = [{"name": name, "arn": arn}]
        if case == "multiple":
            projects.append(projects[0])
        response = {"projects": projects}
        if case != "omitted":
            response["projectsNotFound"] = (
                ["project"]
                if case == "not-found"
                else "invalid"
                if case == "not-found-invalid"
                else []
            )
        return response
    raise AssertionError(operation)


def _codebuild_sync_read(reads, stack, case, *args):
    reads.append(None)
    return (
        dict(stack, StackStatus="UPDATE_IN_PROGRESS")
        if case == "changed" and len(reads) > 2
        else stack
    )


def test_partial_identifiers_only_propagate_confirmed_reference(tmp_path, monkeypatch):
    producer = tmp_path / "model/dev/team/ec2.properties"
    consumer = tmp_path / "model/dev/team/app.properties"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("existing", encoding="utf-8")
    target = ("dev", "team", "ec2", "EC2_SecurityGroup_001")

    items = [
        SimpleNamespace(
            attribute=attribute,
            metadata_id=None,
            producer_kind="resource",
            producer_scope="dev/team/ec2",
            logical_id=target[-1],
            consumer_key=row,
        )
        for attribute, row in (
            ("GroupId", "desired.row.001-001.value"),
            ("VpcId", "desired.row.001-002.value"),
        )
    ]
    snapshot = SimpleNamespace(authoritative={"desired.reference.001.consumerKey": "x"})
    monkeypatch.setattr(observed_adapter, "model_paths", lambda *a, **k: [consumer])
    monkeypatch.setattr(observed_adapter, "raw_model", lambda *a, **k: snapshot)
    monkeypatch.setattr(observed_adapter, "usages", lambda *a, **k: items)
    monkeypatch.setattr(observed_adapter, "read_model", lambda *a: {})
    monkeypatch.setattr(observed_adapter, "properties", lambda *a: {})
    changes = {}
    records = [
        dict(
            consumer="dev/team/app",
            consumerKey=item.consumer_key,
            producer="/".join(target),
        )
        for item in items
    ]
    propagate_references(
        tmp_path,
        {producer: {}},
        changes,
        {target: "sg-123"},
        confirmed_properties={
            target: (
                "EC2.SecurityGroup",
                {"EC2.SecurityGroup.Id"},
                {"EC2.SecurityGroup.VpcId"},
            )
        },
        reference_consumers=records,
    )
    assert changes[consumer] == {"observed.row.001-001.value": None}
    assert consumer.read_text(encoding="utf-8") == "existing"


def test_partial_reference_publication_preserves_unconfirmed_model(project_workspace):
    root = project_workspace
    model_reference_fixtures.project_configuration(root)
    producer, values = model_reference_fixtures.resource_values(
        root, "ec2", "EC2.SecurityGroup", attribute="Id", observed="sg-old"
    )
    logical = "EC2_SecurityGroup_001"
    values.update(
        {
            "desired.row.001-002.property": "EC2.SecurityGroup.VpcId",
            "desired.row.001-002.value": "`vpc-old`",
            "desired.row.001-002.comment": "synthetic",
            "observed.row.001-002.value": "`vpc-old`",
        }
    )
    model_reference_fixtures.write(producer, values)
    consumer, cv = model_reference_fixtures.resource_values(
        root, "lambda", "Lambda.Function", attribute="FunctionName"
    )
    for number, attribute in (("002", "GroupId"), ("003", "VpcId")):
        cv.update(
            {
                f"desired.row.001-{number}.property": "Lambda.Function.Description",
                f"desired.row.001-{number}.value": "`"
                + json.dumps(model_reference_fixtures.reference(logical, attribute))
                + "`",
                f"desired.row.001-{number}.comment": "synthetic",
                f"observed.row.001-{number}.value": "`old-consumer-" + number + "`",
            }
        )
    model_reference_fixtures.write(consumer, cv)
    target = ("qa", "team", "ec2", logical)
    changes = {producer.path: {"observed.row.001-001.value": "`sg-new`"}}
    records = [
        {
            "consumer": "qa/team/lambda",
            "consumerKey": f"desired.row.001-{n}.value",
            "producer": "/".join(target),
        }
        for n in ("002", "003")
    ]
    propagate_references(
        root,
        {producer.path: values},
        changes,
        {target: "sg-new"},
        confirmed_properties={
            target: (
                "EC2.SecurityGroup",
                {"EC2.SecurityGroup.Id"},
                {"EC2.SecurityGroup.VpcId"},
            )
        },
        reference_consumers=records,
    )
    assert changes[consumer.path] == {"observed.row.001-002.value": None}
    loaded = {
        path: properties(read_model(path)) for path in (producer.path, consumer.path)
    }
    outputs, _, _ = observed_adapter.observed_destinations(
        root, "qa", "team", loaded, changes, check_scope=False
    )
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
    updated = parse(producer.path.read_text(encoding="utf-8")).values
    consumer_updated = parse(consumer.path.read_text(encoding="utf-8")).values
    assert updated["observed.row.001-001.value"] == "`sg-new`"
    assert updated["observed.row.001-002.value"] == "`vpc-old`"
    assert "observed.row.001-002.value" not in consumer_updated
    assert consumer_updated["observed.row.001-003.value"] == "`old-consumer-003`"


def test_deferred_reference_stays_pending_while_owner_is_unconfirmed():
    record = dict(
        stack="producer", consumer="qa/team/iam", approved=True, referenceSynced=False
    )
    context = {
        "states": {
            "producer": {
                "deferredConsumers": [record],
                "observedCoverage": {"Resource": {"status": "UNCONFIRMED"}},
            }
        },
        "pendingGeneration": {},
    }
    plan = {"services": ["iam"], "evidence": {"producer": {}}}
    deferred.model_saved(context, plan)
    deferred.views_saved(context)
    assert not record["ownerObservedSynced"]
    assert not record.get("referenceObservedSynced")
    assert not record["referenceSynced"]
    context["states"]["producer"]["observedCoverage"]["Resource"]["status"] = "MATCHED"
    deferred.model_saved(context, plan)
    deferred.views_saved(context)
    assert record["referenceSynced"]
