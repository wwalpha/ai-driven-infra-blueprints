"""Small authored cross-service Model fixtures; no generated project or Git setup."""

import json
from pathlib import Path

from comparison import Comparison
from model.format import serialize
from model.identity import COUNTERS
from model.sources import Scope, load_model

from model import dependency_index

FRAMEWORK = Path(__file__).resolve().parents[4]


def reference(logical="KMS_Key_001", attribute="Arn"):
    return {"$modelRef": {"logicalId": logical, "attribute": attribute}}


def save(scope, values):
    scope.path.parent.mkdir(parents=True, exist_ok=True)
    scope.path.write_text(serialize(values), encoding="utf-8")
    if (scope.root / "project.json").is_file():
        dependency_index.rebuild(scope.root)


def resource(
    root, service, kind, *, target="team", attribute="Arn", observed=None, number="001"
):
    scope = Scope(root, "qa", target, service)
    logical = kind.replace(".", "_") + "_" + number
    values = {
        COUNTERS: json.dumps({kind: int(number)}),
        f"desired.service.{service}.serviceId": service,
        f"desired.service.{service}.ownedCatalogResourceTypes": kind,
        "display.service.title": "# 合成参照",
        f"desired.resource.{number}.resourceType": kind,
        f"desired.resource.{number}.logicalId": logical,
        f"desired.resource.{number}.anchor": "saved-" + number,
        f"desired.resource.{number}.resourceMode": "CREATE",
        f"desired.resource.{number}.cfn-logicalId": "producer-Resource" + number,
        f"display.resource.{number}.comment": "合成",
        f"desired.row.{number}-001.property": kind + "." + attribute,
        f"desired.row.{number}-001.value": "[self](#saved-" + number + ")",
        f"desired.row.{number}-001.comment": "合成",
    }
    if observed is not None:
        values[f"observed.row.{number}-001.value"] = "`" + observed + "`"
    save(scope, values)
    return scope, values


def project(root):
    data = {
        "targets": [
            {
                "environment": "qa",
                "alias": target,
                "awsAccountId": "123456789012",
                "awsRegion": "ap-northeast-1",
                "iacEngine": "cloudformation",
            }
            for target in ("team", "other")
        ]
    }
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    producer, values = resource(root, "kms", "KMS.Key")
    consumer, policy = resource(
        root, "iam", "IAM.ManagedPolicy", attribute="ManagedPolicyName"
    )
    policy.update(
        {
            "desired.row.001-001.value": "`synthetic-policy`",
            "desired.row.001-002.property": "IAM.ManagedPolicy.PolicyDocument",
            "desired.row.001-002.value": "[Policy](iam/policy.json)",
            "desired.row.001-002.comment": "合成JSON",
            "desired.row.001-002.document": json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "kms:Decrypt",
                            "Resource": reference(),
                        }
                    ],
                }
            ),
        }
    )
    policy["desired.resource.001.cfn-logicalId"] = "consumer-Policy"
    save(consumer, policy)
    return producer, values, consumer, policy


def comparison(root, services=("iam", "kms")):
    result = Comparison(root, "qa", "team", services)
    result.local_comparison = True
    pseudo = {
        "AWS::Region": "ap-northeast-1",
        "AWS::AccountId": "123456789012",
        "AWS::Partition": "aws",
    }
    result.stack_inputs = {
        "producer": (
            {
                "Resources": {"Resource001": {"Type": "AWS::KMS::Key"}},
                "Outputs": {
                    "Reference": {
                        "Value": {"Fn::GetAtt": ["Resource001", "Arn"]},
                        "Export": {"Name": "ExampleKmsKeyArn"},
                    }
                },
            },
            {},
            pseudo,
        ),
        "consumer": (
            {"Resources": {"Policy": {"Type": "AWS::IAM::ManagedPolicy"}}},
            {},
            pseudo,
        ),
    }
    result._templates = [(name, {"name": name}) for name in result.stack_inputs]
    return result


def pipeline(root):
    producers = [
        (
            "codecommit",
            "CodeCommit.Repository",
            "RepositoryName",
            "Source",
            "CodeCommit",
            "RepositoryName",
            "Name",
        ),
        (
            "codebuild",
            "CodeBuild.Project",
            "Name",
            "Build",
            "CodeBuild",
            "ProjectName",
            "Name",
        ),
        ("s3", "S3.Bucket", "BucketName", "Source", "S3", "S3Bucket", "BucketName"),
    ]
    actions = []
    for service, kind, setting, category, provider, key, attribute in producers:
        scope, first = resource(
            root, service, kind, attribute=setting, observed="PENDING_DEPLOY"
        )
        _, second = resource(
            root,
            service,
            kind,
            attribute=setting,
            number="002",
            observed="PENDING_DEPLOY",
        )
        first.update(second)
        first["desired.row.001-001.value"] = "`synthetic-" + service + "-a`"
        first["desired.row.002-001.value"] = "`synthetic-" + service + "-b`"
        save(scope, first)
        actions.append(
            {
                "Name": provider,
                "ActionTypeId": dict(
                    Category=category, Owner="AWS", Provider=provider, Version="1"
                ),
                "Configuration": {
                    key: reference(kind.replace(".", "_") + "_001", attribute)
                },
            }
        )
    stages = [
        {"Name": "First", "Actions": actions[:2]},
        {"Name": "Second", "Actions": actions[2:]},
    ]
    scope, values = resource(
        root, "codepipeline", "CodePipeline.Pipeline", attribute="Name"
    )
    values.update(
        {
            "desired.row.001-001.value": "`synthetic-pipeline`",
            "desired.row.001-002.property": "CodePipeline.Pipeline.Stages",
            "desired.row.001-002.value": "`" + json.dumps(stages) + "`",
            "desired.row.001-002.comment": "合成Stages",
        }
    )
    save(scope, values)
    pseudo = {
        "AWS::Region": "ap-northeast-1",
        "AWS::AccountId": "123456789012",
        "AWS::Partition": "aws",
    }
    stack_inputs = {}
    for service, kind, setting, *_ in producers:
        producer_scope = Scope(root, "qa", "team", service)
        from_values = load_model(producer_scope).authoritative
        authored = dict(from_values)
        definitions = {}
        for number in ("001", "002"):
            authored["desired.resource." + number + ".cfn-logicalId"] = (
                service + "-Resource" + number
            )
            definitions["Resource" + number] = {
                "Type": "AWS::" + kind.replace(".", "::"),
                "Properties": {
                    setting: "synthetic-"
                    + service
                    + "-"
                    + ("a" if number == "001" else "b")
                },
            }
        save(producer_scope, authored)
        document = {"Resources": definitions}
        if service == "codecommit":
            document["Outputs"] = {
                "Name": {
                    "Value": {"Fn::GetAtt": ["Resource001", "Name"]},
                    "Export": {"Name": "RepositoryName"},
                }
            }
        stack_inputs[service] = (document, {}, pseudo)
    result = comparison(root, ("codepipeline", "codecommit", "codebuild", "s3"))
    result.stack_inputs = stack_inputs
    result._templates = [(name, {"name": name}) for name in stack_inputs]
    return result, scope, values, stages
