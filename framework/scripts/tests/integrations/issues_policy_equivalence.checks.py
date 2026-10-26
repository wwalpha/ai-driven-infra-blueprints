#!/usr/bin/env python3
"""IAM Action forms and proven local S3 ARN/Sub equality without weakening JSON."""

import sys
from contextlib import nullcontext
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json
import tempfile
from copy import deepcopy
from unittest.mock import patch

from issues.aggregate import aggregate
from issues.artifact import detail_payload, summary
from issues.records import identifier
from issues.reports import iac_report
from support import issues_scan_fixtures as fixtures
from support.it_case_receipt import it_case
from support.model_sources import catalog_display
from support.validator import load as load

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_main_checks_record(root, /, candidate):
    fixtures.mutate_template(root, candidate)
    comparison, records = fixtures.compare(root, ["iam"])
    selected = [r for r in records if r["property"] == "IAM.Role.Policies"]
    assert len(selected) == 1, records
    return comparison, selected[0]


def _lambda_main_checks_callback_76(comparison, /, a, b, path):
    return comparison.reference_same(a, b, "IAM.Role", path)


@it_case
def main_checks():
    with tempfile.TemporaryDirectory(prefix="policy-equivalence-") as temporary:
        root = Path(temporary) / "project"
        _, template = fixtures.fixture(root, stacks=2, services=("s3",))
        consumer, producer = "cfn-stack-app-dev-data1", "cfn-stack-app-dev-data2"
        arn = "arn:aws:s3:::bucket-app-dev-data2"
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": "s3:GetBucketLocation", "Resource": arn},
                {
                    "Effect": "Allow",
                    "Action": "s3:ListBucket",
                    "Resource": arn,
                    "Condition": {
                        "StringLike": {"s3:prefix": ["results/", "results/*"]}
                    },
                },
                {
                    "Effect": "Allow",
                    "Action": "s3:GetObject",
                    "Resource": arn + "/results/*",
                },
            ],
        }
        values = {
            "desired.service.iam.serviceId": "iam",
            "desired.resource.001.resourceType": "IAM.Role",
            "desired.resource.001.cfn-logicalId": consumer + "-Role",
            "desired.resource.001.logicalId": "IAM_Role_001",
            "desired.service.identity.lastAllocated": '{"IAM.Role":1}',
            "desired.row.001-001.property": "IAM.Role.Policies[].PolicyName",
            "desired.row.001-001.value": "`ReadResults`",
            "desired.row.001-002.property": "IAM.Role.Policies[].PolicyDocument",
            "desired.row.001-002.value": "policy.json",
            "desired.row.001-002.document": json.dumps(policy),
        }
        fixtures.write(
            root / "model/dev/123456789012/iam.properties",
            "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        )
        imported = {"Fn::ImportValue": "app-dev-data2-BucketArn"}
        template["Outputs"] = {
            "BucketArn": {
                "Value": {"Fn::GetAtt": ["Bucket", "Arn"]},
                "Export": {"Name": {"Fn::Sub": "${Name}-BucketArn"}},
            }
        }
        actual = deepcopy(policy)
        for statement in actual["Statement"]:
            statement["Action"] = [statement["Action"]]
            statement["Resource"] = deepcopy(imported)
        actual["Statement"][2]["Resource"] = {
            "Fn::Sub": ["${BucketArn}/results/*", {"BucketArn": imported}]
        }
        template["Resources"]["Role"] = {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "Policies": [{"PolicyName": "ReadResults", "PolicyDocument": actual}]
            },
        }
        original = deepcopy(template)

        record = _bind_framework_callback(_callback_main_checks_record, root)

        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            comparison, result = record(original)
            assert result["category"] == "matched", result
            # Real setting changes still differ, and display does not repeat equivalent fields.
            for field, value in [("Action", ["s3:PutObject"]), ("Effect", "Deny")]:
                changed = deepcopy(original)
                changed["Resources"]["Role"]["Properties"]["Policies"][0][
                    "PolicyDocument"
                ]["Statement"][0][field] = value
                comparison, result = record(changed)
                assert result["category"] == "difference", result
                fields = comparison.display_differences[identifier(result)]
                assert len(fields) == 1 and fields[0]["path"].endswith("." + field), (
                    fields
                )
            changed = deepcopy(original)
            changed["Resources"]["Role"]["Properties"]["Policies"][0]["PolicyDocument"][
                "Statement"
            ][2]["Resource"]["Fn::Sub"][0] = "${BucketArn}/other/*"
            comparison, result = record(changed)
            assert result["category"] == "difference", result
            assert all(
                "arn:aws:" not in json.dumps(field)
                for field in comparison.display_differences[identifier(result)]
            )
            changed = deepcopy(original)
            changed["Resources"]["Role"]["Properties"]["Policies"][0]["PolicyDocument"][
                "Statement"
            ][1]["Condition"]["StringLike"]["s3:prefix"] = ["other/*"]
            assert record(changed)[1]["category"] == "difference"
            changed = deepcopy(original)
            changed["Resources"]["Bucket"]["Properties"]["BucketName"] = (
                "different-bucket"
            )
            assert record(changed)[1]["category"] == "difference"

            # No inferred names, arbitrary ARN construction or ambiguous/inactive handoffs.
            for name in (None, "invalid/path", "wildcard-*", {"Ref": "Bucket"}):
                changed = deepcopy(original)
                props = changed["Resources"]["Bucket"]["Properties"]
                if name is None:
                    del props["BucketName"]
                else:
                    props["BucketName"] = name
                assert record(changed)[1]["category"] == "uncompared"
            changed = deepcopy(original)
            changed["Resources"]["Bucket"]["Condition"] = "Inactive"
            changed["Conditions"]["Inactive"] = {"Fn::Equals": ["yes", "no"]}
            assert record(changed)[1]["category"] == "uncompared"
            changed = deepcopy(original)
            changed["Outputs"]["Duplicate"] = deepcopy(changed["Outputs"]["BucketArn"])
            assert record(changed)[1]["category"] == "uncompared"
            changed = deepcopy(original)
            del changed["Outputs"]["BucketArn"]
            assert record(changed)[1]["category"] == "uncompared"
            s3 = root / "model/dev/123456789012/s3.properties"
            original_model = fixtures.read_model(s3)
            duplicate = fixtures.properties(original_model)
            duplicate.update(
                {
                    "desired.resource.003.resourceType": "S3.Bucket",
                    "desired.resource.003.logicalId": "S3_Bucket_003",
                    "desired.service.identity.lastAllocated": '{"S3.Bucket":3}',
                    "desired.resource.003.cfn-logicalId": producer + "-Bucket",
                }
            )
            fixtures.write_model(s3, duplicate)
            assert record(original)[1]["category"] == "uncompared"
            fixtures.write(s3, original_model)
            comparison, result = record(original)
            assert result["category"] == "matched"
            reference = comparison.evaluate(consumer, imported)
            comparison.resources["s3"]["002"]["resourceMode"] = "IMPORT"
            assert comparison.reference_same(reference, arn, "IAM.Role", "") is None
    print(
        "Policy equivalence: PASS (IAM Action scope; S3 ARN/Sub/import; real differences; unresolved guards; report masking)"
    )


@it_case
def sqs_policy_artifact_checks():
    with tempfile.TemporaryDirectory(prefix="sqs-policy-artifact-") as temporary:
        root = Path(temporary) / "project"
        values, template = fixtures.fixture(root, services=("sqs",))
        stack = "cfn-stack-app-dev-data1"
        queue_arn = "arn:aws:sqs:ap-northeast-1:123456789012:fixture-dlq"
        rule_arn = "arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule"
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "events.amazonaws.com"},
                    "Action": "sqs:SendMessage",
                    "Resource": queue_arn,
                    "Condition": {"ArnEquals": {"aws:SourceArn": rule_arn}},
                }
            ],
        }
        model = values["sqs"]
        model.update(
            {
                "desired.row.001-001.value": "`fixture-dlq`",
                "desired.service.identity.lastAllocated": '{"SQS.Queue":1,"SQS.QueuePolicy":2}',
                "desired.resource.002.resourceType": "SQS.QueuePolicy",
                "desired.resource.002.logicalId": "SQS_QueuePolicy_002",
                "desired.resource.002.cfn-logicalId": stack + "-QueuePolicy",
                "desired.resource.002.resourceMode": "CREATE",
                "desired.row.002-001.property": "SQS.QueuePolicy.PolicyDocument",
                "desired.row.002-001.value": "policy.json",
                "desired.row.002-001.comment": "synthetic policy",
                "desired.row.002-001.document": json.dumps(policy),
            }
        )
        fixtures.write_model(
            root / "model/dev/123456789012/eventbridge.properties",
            {
                "desired.service.eventbridge.serviceId": "eventbridge",
                "desired.service.identity.lastAllocated": '{"Events.Rule":1}',
                "desired.resource.001.resourceType": "Events.Rule",
                "desired.resource.001.logicalId": "Events_Rule_001",
                "desired.resource.001.cfn-logicalId": stack + "-Rule",
                "desired.resource.001.resourceMode": "CREATE",
                "desired.row.001-001.comment": "synthetic name",
                "desired.row.001-002.comment": "synthetic bus",
                "desired.row.001-001.property": "Events.Rule.Name",
                "desired.row.001-001.value": "`fixture-rule`",
                "desired.row.001-002.property": "Events.Rule.EventBusName",
                "desired.row.001-002.value": "`default`",
            },
        )
        template["Resources"]["Queue"]["Properties"]["QueueName"] = "fixture-dlq"
        template["Resources"]["Rule"] = {
            "Type": "AWS::Events::Rule",
            "Properties": {"Name": "fixture-rule", "EventBusName": "default"},
        }
        actual = deepcopy(policy)
        actual["Statement"][0]["Resource"] = {"Fn::GetAtt": ["Queue", "Arn"]}
        actual["Statement"][0]["Condition"]["ArnEquals"]["aws:SourceArn"] = {
            "Fn::GetAtt": ["Rule", "Arn"]
        }
        template["Resources"]["QueuePolicy"] = {
            "Type": "AWS::SQS::QueuePolicy",
            "Properties": {"Queues": [{"Ref": "Queue"}], "PolicyDocument": actual},
        }
        for category in ("matched", "difference", "uncompared", "error"):
            candidate = deepcopy(template)
            desired = deepcopy(policy)
            if category == "difference":
                desired["Statement"][0]["Resource"] = queue_arn.replace(
                    "ap-northeast-1", "us-east-1"
                )
            elif category == "uncompared":
                candidate["Resources"]["Queue"]["Properties"].pop("QueueName")
            model["desired.row.002-001.document"] = json.dumps(desired)
            fixtures.write_model(root / "model/dev/123456789012/sqs.properties", model)
            fixtures.mutate_template(root, candidate)
            fault = (
                patch(
                    "comparison.registry.named_arn",
                    side_effect=OSError("synthetic ARN I/O failure"),
                )
                if category == "error"
                else nullcontext()
            )
            with (
                patch("socket.socket", side_effect=AssertionError("network forbidden")),
                fault,
            ):
                comparison, records = fixtures.compare(root, ["sqs"])
            selected = [item for item in records if item["resource"] == "002"]
            assert len(selected) == 1 and selected[0]["category"] == category, records
            artifact = dict(
                version=6,
                **aggregate(
                    selected,
                    "dev",
                    "123456789012",
                    ["sqs"],
                    comparison.display_differences,
                    redact=comparison.redacted,
                ),
            )
            path = Path(temporary) / "artifact.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            artifact = json.loads(path.read_text(encoding="utf-8"))
            overview = summary(artifact)
            assert (
                overview[
                    "iac_"
                    + (
                        "differences"
                        if category == "difference"
                        else "errors"
                        if category == "error"
                        else category
                    )
                ]
                == 1
            ), overview
            detail = detail_payload(artifact, "iac")["items"][0]
            assert detail["category"] == category
            report = iac_report(
                "dev", "123456789012", ["sqs"], selected, artifact=artifact
            )
            if category in {"difference", "uncompared"}:
                diagnostics = detail["reference_diagnostics"]
                queue = next(
                    item for item in diagnostics if item["path"].endswith(".Resource")
                )
                rule = next(
                    item
                    for item in diagnostics
                    if item["path"].endswith("aws:SourceArn")
                )
                assert (
                    queue["local_comparison"] == category
                    and rule["local_comparison"] == "matched"
                )
                assert queue["producers"] == [
                    {"producer": "sqs/001", "attribute": "Arn"}
                ]
                shown = artifact["overview"]["groups"][0]["examples"][0][
                    "reference_diagnostics"
                ]
                assert (
                    next(item for item in shown if item["path"].endswith(".Resource"))[
                        "local_comparison"
                    ]
                    == category
                )
                assert (
                    "参照field: SQS.QueuePolicy.PolicyDocument.Statement[].Resource"
                    in report
                )
                assert (
                    "- ローカル具体値比較: " + category in report
                    and "未比較field" not in report
                )
                assert "静的形式適合性" in report and "参照同一性" in report
                assert overview["iac_uncompared"] == int(category == "uncompared")
            elif category == "error":
                assert (
                    overview["validation_status"] == "ERROR"
                    and "synthetic ARN I/O failure" in detail["reason"]
                )
            assert queue_arn not in json.dumps(artifact) and rule_arn not in report
            assert "123456789012" not in json.dumps(
                detail.get("reference_diagnostics", [])
            )
            assert "123456789012" not in json.dumps(artifact["overview"]["groups"])
    print(
        "SQS policy artifact: PASS (matched/difference/uncompared/error; SQS-only region difference; proof/report masking)"
    )


if __name__ == "__main__":
    with catalog_display():
        main_checks()
        sqs_policy_artifact_checks()
