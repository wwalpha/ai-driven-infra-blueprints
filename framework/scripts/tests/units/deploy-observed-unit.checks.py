"""Selected ownership and incoming discovery, without validating unrelated Models."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json

import pytest
from deploy.observed import security_group_rule_id
from model.adapters.aws import Unresolved, service_module
from model.adapters.observed import identifier_source, propagate_references, resolve_resources
from model.files import read_model
from support.cloudformation_deploy_fixtures import TARGET
from support.model_sources import allocate_fixture, write_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def test_queue_policy_id_requires_getatt_output():
    catalog = SimpleNamespace(schema=lambda kind: {"primaryIdentifier": ["/properties/Id"]})
    resource = {"resourceType": "SQS.QueuePolicy"}
    outputs = {"Id"}
    declarations = {"id": {"Fn::GetAtt": ["Policy", "Id"]}, "ref": {"Ref": "Policy"}}
    assert identifier_source(catalog, resource, outputs, "Policy", "SQS.QueuePolicy.Id", declarations) == (False, ["id"])
    assert identifier_source(catalog, resource, outputs, "Policy", "SQS.QueuePolicy.Id", {"ref": {"Ref": "Policy"}}) == (False, [])


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


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))


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

    def aws(operation, **kwargs):
        if operation == "get_template":
            return {"TemplateBody": document}
        if operation == "describe_security_group_rules":
            return {"SecurityGroupRules": records}
        if operation == "describe_stacks":
            return {"Stacks": [stack]}
        raise AssertionError(operation)

    backend = SimpleNamespace(aws=aws)

    def result(output="sgr-12345678"):
        return security_group_rule_id(
            backend, stack, document, {}, {}, [], "Rule", actual, output
        )

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
