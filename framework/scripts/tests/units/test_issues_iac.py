import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hashlib
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import comparison as issues_iac
import comparison.references as _imports_comparison_references
import issues.aggregate as _imports_issues_aggregate
import pytest
import utils.json_format as _imports_utils_json_format
from comparison import registry
from comparison.evaluation import project_actual
from comparison.methods import compare_values, keyed
from comparison.result import redacted, value_differences
from comparison.values import PreparedValue, desired_value
from design.catalog import DesignSchemaCatalog
from issues.inputs import Comparison as IssueComparison
from model.format import serialize
from model.identity import COUNTERS
from model.sources import Scope
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference, same
from utils.reference_contracts import KMS_FORMS, REF_ATTRIBUTES


def candidate_test_reference(left, right, path):
    equal = (
        None
        if any(
            isinstance(value, Expression) and value.operation == "Unverified"
            for value in (left, right)
        )
        else NotImplemented
    )
    return _imports_comparison_references.ReferenceDecision(equal)


def resolve_keyless_policy_test(value):
    if value == {"Condition": "Yes"}:
        return True
    if value in ({"Fn::Sub": "${B}"}, {"Fn::Sub": "variable"}):
        return "b"
    if isinstance(value, dict) and "Ref" in value:
        raise KeyError(value["Ref"])
    if value == {"Fn::Sub": 42}:
        raise ValueError("invalid Fn::Sub")
    return value


class ModelDependencyTests(unittest.TestCase):
    def dependency_models(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "project.json").write_text(
            json.dumps(
                {
                    "targets": [
                        dict(
                            environment="fixture",
                            alias="team",
                            awsAccountId="123456789012",
                            awsRegion="ap-northeast-1",
                            iacEngine="cloudformation",
                        )
                    ]
                }
            ),
            encoding="utf-8",
        )
        consumer = root / "model/fixture/team/s3.properties"
        consumer.parent.mkdir(parents=True)
        consumer.write_text(
            serialize(
                {
                    COUNTERS: json.dumps({"S3.Bucket": 1}),
                    "desired.service.s3.serviceId": "s3",
                    "desired.resource.001.resourceType": "S3.Bucket",
                    "desired.resource.001.logicalId": "S3_Bucket_001",
                    "desired.row.001-001.property": "S3.Bucket.KmsMasterKeyId",
                    "desired.row.001-001.value": "[key](kms.md#key)",
                    "desired.row.001-001.comment": "合成参照",
                }
            ),
            encoding="utf-8",
        )
        producer = consumer.with_name("kms.properties")
        raw = serialize(
            {
                COUNTERS: json.dumps({"KMS.Key": 1}),
                "desired.service.kms.serviceId": "kms",
                "desired.resource.001.resourceType": "KMS.Key",
                "desired.resource.001.logicalId": "KMS_Key_001",
                "desired.resource.001.anchor": "key",
            }
        ).encode("utf-8")
        return root, producer, raw

    def test_missing_producer_dependency(self):
        for comparison_type in (issues_iac.Comparison, IssueComparison):
            with self.subTest(comparison=comparison_type):
                root, producer, raw = self.dependency_models()
                with patch("comparison.inputs.hashlib", wraps=hashlib) as hashing:
                    comparison = comparison_type(root, "fixture", "team", ["s3"])
                    assert not comparison.load_errors
                    assert comparison.models["s3"].dependencies[producer] is None
                    assert producer not in comparison.model_reads.contents
                    assert producer in comparison.inputs
                    producer.write_bytes(raw)
                    if comparison_type is IssueComparison:
                        assert comparison.model("kms").dependencies[producer] == raw
                        assert (
                            comparison.read_hashes == {}
                            and hashing.sha256.call_count == 0
                        )
                        assert not getattr(comparison, "stale_inputs", False)
                    else:
                        assert comparison.read_hashes[producer] is None
                        with pytest.raises(
                            ValueError,
                            match="stale scan: contradictory input observations: model/fixture/team/kms.properties",
                        ):
                            comparison.model("kms")
                        assert comparison.stale_inputs

    def test_existing_producer_dependency(self):
        for comparison_type in (issues_iac.Comparison, IssueComparison):
            with self.subTest(comparison=comparison_type):
                root, producer, raw = self.dependency_models()
                producer.write_bytes(raw)
                comparison = comparison_type(root, "fixture", "team", ["s3"])
                assert not comparison.load_errors
                assert comparison.models["s3"].dependencies[producer] == raw
                assert producer in comparison.inputs
                with (
                    patch.object(
                        Path,
                        "read_bytes",
                        side_effect=AssertionError(
                            "dependency retention must not reread"
                        ),
                    ),
                    patch(
                        "comparison.inputs.hashlib",
                        sha256=Mock(
                            side_effect=AssertionError(
                                "same bytes must not be hashed twice"
                            )
                        ),
                    ),
                    patch(
                        "comparison.inputs.load_model",
                        side_effect=AssertionError("cached Model must not reload"),
                    ),
                ):
                    assert comparison.model("s3") is comparison.models["s3"]
                    comparison.retain_model_dependencies(
                        comparison.models["s3"].dependencies
                    )
                if comparison_type is IssueComparison:
                    with patch(
                        "comparison.inputs.hashlib",
                        sha256=Mock(side_effect=AssertionError("Issue must not hash")),
                    ):
                        comparison.retain_model_dependencies(
                            {producer: raw + b"# changed\n"}
                        )
                    assert comparison.read_hashes == {}
                else:
                    assert (
                        comparison.read_hashes[producer]
                        == hashlib.sha256(raw).hexdigest()
                    )
                    with pytest.raises(
                        ValueError, match="contradictory input observations"
                    ):
                        comparison.retain_model_dependencies(
                            {producer: raw + b"# changed\n"}
                        )
                    assert comparison.stale_inputs


def legacy_comparison(root, count=3, services=1, stacks=2):
    """Synthetic current Models and real local templates; no consumer inputs."""
    models, documents, units = {}, [{"Resources": {}} for _ in range(stacks)], []
    for number in range(count):
        service, identity = f"service-{number % services}", f"{number:04d}"
        values = models.setdefault(
            service, {f"desired.service.{service}.serviceId": service}
        )
        values.update(
            {
                f"desired.resource.{identity}.resourceType": "Logs.LogGroup",
                f"desired.resource.{identity}.logicalId": f"Log{number}",
                f"desired.row.{identity}-001.property": "Logs.LogGroup.RetentionInDays",
                f"desired.row.{identity}-001.value": "`7`",
            }
        )
        documents[number % stacks]["Resources"][f"Log{number}"] = {
            "Type": "AWS::Logs::LogGroup",
            "Properties": {"RetentionInDays": 7},
        }
    loaded = {}
    for service, values in models.items():
        path = root / "model/fixture/team" / (service + ".properties")
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = serialize(values).encode()
        path.write_bytes(raw)
        loaded[path] = SimpleNamespace(
            values=values,
            authoritative=values,
            dependencies={path: raw},
            locations={},
            scope=Scope(root, "fixture", "team", service),
        )
    for number, document in enumerate(documents):
        unit = {
            "name": f"stack{number}",
            "template": f"{number}.json",
            "parameters": f"{number}.json",
        }
        units.append((str(number), unit))
        for path, value in [
            (root / "infra/cloudformation/templates" / unit["template"], document),
            (
                root
                / "infra/cloudformation/parameters/fixture/team"
                / unit["parameters"],
                [],
            ),
        ]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")
    catalog = DesignSchemaCatalog(Path(__file__).resolve().parents[4])
    target = {
        "iacEngine": "cloudformation",
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
    }
    with (
        patch("comparison.inputs.load_target", return_value=target),
        patch(
            "comparison.inputs.load_model", side_effect=lambda path, reads: loaded[path]
        ),
    ):
        comparison = issues_iac.Comparison(
            root, "fixture", "team", models, catalog=catalog
        )
    comparison.templates = lambda: units
    return comparison


def iam_policy_comparison(root, kind, desired, actual):
    comparison = legacy_comparison(root, count=1, stacks=1)
    comparison.local_comparison = True
    resource_type = "IAM." + kind
    resource = comparison.resources["service-0"]["0000"]
    resource.update(resourceType=resource_type, **{"cfn-logicalId": "stack0-Log0"})
    values = comparison.models["service-0"].values
    values["desired.resource.0000.resourceType"] = resource_type
    values["desired.resource.0000.cfn-logicalId"] = "stack0-Log0"
    rows = []
    fields = desired.items() if isinstance(desired, dict) else desired
    for index, (prop, value) in enumerate(fields, 1):
        rid = f"0000-{index:03d}"
        row = {
            "property": resource_type + "." + prop,
            "value": "`"
            + (value if isinstance(value, str) else json.dumps(value))
            + "`",
        }
        rows.append((rid, row))
        values[f"desired.row.{rid}.property"] = row["property"]
        values[f"desired.row.{rid}.value"] = row["value"]
    comparison.rows["service-0"]["0000"] = rows
    _, (document, _, _) = comparison.stack(comparison.templates()[0][1])
    document["Resources"]["Log0"] = {"Type": "AWS::IAM::" + kind, "Properties": actual}
    return comparison, resource, document


class BooleanValueTests(unittest.TestCase):
    def test_login_profile_boolean_comparison_and_issue_summary(self):
        prop = "LoginProfile.PasswordResetRequired"
        cases = [
            ("False", False, "matched"),
            ("false", False, "matched"),
            ("True", True, "matched"),
            ("true", True, "matched"),
            ("True", False, "difference"),
            ("False", True, "difference"),
        ]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("socket.socket", side_effect=AssertionError("network forbidden")),
        ):
            for model, actual, expected in cases:
                with self.subTest(model=model, actual=actual):
                    comparison = legacy_comparison(Path(directory), count=1, stacks=1)
                    comparison.resources["service-0"]["0000"].update(
                        resourceType="IAM.User", **{"cfn-logicalId": "stack0-Log0"}
                    )
                    comparison.models["service-0"].values.update(
                        {
                            "desired.resource.0000.resourceType": "IAM.User",
                            "desired.resource.0000.cfn-logicalId": "stack0-Log0",
                            "desired.row.0000-001.property": "IAM.User." + prop,
                            "desired.row.0000-001.value": "`" + model + "`",
                        }
                    )
                    row = {"property": "IAM.User." + prop, "value": "`" + model + "`"}
                    comparison.rows["service-0"]["0000"] = [("0000-001", row)]
                    _, (document, _, _) = comparison.stack(comparison.templates()[0][1])
                    document["Resources"]["Log0"] = {
                        "Type": "AWS::IAM::User",
                        "Properties": {
                            "LoginProfile": {"PasswordResetRequired": actual}
                        },
                    }
                    self.assertEqual(
                        comparison.catalog.literal_errors("IAM.User", prop, model), []
                    )
                    records = comparison.run()
                    self.assertEqual([item["category"] for item in records], [expected])
                    self.assertIs(
                        type(
                            comparison.prepare_value(
                                "service-0", row, "IAM.User"
                            ).require_value()
                        ),
                        bool,
                    )
                    summary = _imports_issues_aggregate.iac_summary(
                        records, "fixture", "team", ["service-0"]
                    )
                    self.assertEqual(summary["records"]["error"], 0)
                    self.assertEqual(summary["records"][expected], 1)
                    self.assertEqual(
                        summary["issue_count"], int(expected == "difference")
                    )

            comparison = legacy_comparison(Path(directory), count=1, stacks=1)
            comparison.resources["service-0"]["0000"].update(
                resourceType="IAM.User", **{"cfn-logicalId": "stack0-Log0"}
            )
            policies = [
                {
                    "PolicyName": "one",
                    "PolicyDocument": {
                        "Statement": [{"Action": ["a", "b"], "Effect": "Allow"}]
                    },
                },
                {
                    "PolicyName": "two",
                    "PolicyDocument": {
                        "Statement": [{"Action": "c", "Effect": "Allow"}]
                    },
                },
            ]
            value = "`" + json.dumps(policies) + "`"
            row = {"property": "IAM.User.Policies", "value": value}
            comparison.models["service-0"].values.update(
                {
                    "desired.resource.0000.resourceType": "IAM.User",
                    "desired.resource.0000.cfn-logicalId": "stack0-Log0",
                    "desired.row.0000-001.property": row["property"],
                    "desired.row.0000-001.value": value,
                }
            )
            comparison.rows["service-0"]["0000"] = [("0000-001", row)]
            _, (document, _, _) = comparison.stack(comparison.templates()[0][1])
            document["Resources"]["Log0"] = {
                "Type": "AWS::IAM::User",
                "Properties": {
                    "Policies": [
                        policies[1],
                        {
                            "PolicyName": "one",
                            "PolicyDocument": {
                                "Statement": [{"Action": ["b", "a"], "Effect": "Allow"}]
                            },
                        },
                    ]
                },
            }
            records = comparison.run()
            self.assertEqual([item["category"] for item in records], ["matched"])
            summary = _imports_issues_aggregate.iac_summary(
                records, "fixture", "team", ["service-0"]
            )
            self.assertEqual(summary["issue_count"], 0)
            document["Resources"]["Log0"]["Properties"]["Policies"][1][
                "PolicyDocument"
            ]["Statement"][0]["Action"] = ["b", "different"]
            records = comparison.run()[1:]
            self.assertEqual([item["category"] for item in records], ["difference"])
            summary = _imports_issues_aggregate.iac_summary(
                records, "fixture", "team", ["service-0"]
            )
            self.assertEqual(summary["issue_count"], 1)

    def test_keyless_policies_reordered_issue_summary(self):
        names = [
            ("literal", ["one", "two"], "matched"),
            ("sub-distinct", [{"Fn::Sub": "one"}, {"Fn::Sub": "two"}], "matched"),
            (
                "ref-distinct",
                [{"Ref": "AWS::Region"}, {"Ref": "AWS::AccountId"}],
                "matched",
            ),
            (
                "key-no-value",
                ["one", {"Fn::If": ["Yes", {"Ref": "AWS::NoValue"}, "one"]}],
                "matched",
            ),
            ("literal-duplicate", ["same", "same"], "invalid"),
            ("sub-duplicate", [{"Fn::Sub": "same"}] * 2, "invalid"),
            ("mixed-duplicate", ["same", {"Fn::Sub": "same"}], "invalid"),
            ("ref-duplicate", ["ap-northeast-1", {"Ref": "AWS::Region"}], "invalid"),
            (
                "if-duplicate",
                ["same", {"Fn::If": ["Yes", "same", {"Ref": "Inactive"}]}],
                "invalid",
            ),
            (
                "nested-if-duplicate",
                [
                    "same",
                    {
                        "Fn::If": [
                            "No",
                            {"Ref": "Inactive"},
                            {"Fn::If": ["Yes", "same", "other"]},
                        ]
                    },
                ],
                "invalid",
            ),
            ("unknown-key", ["one", {"Ref": "Missing"}], "uncompared"),
            (
                "unknown-condition",
                ["one", {"Fn::If": ["Missing", "one", "two"]}],
                "uncompared",
            ),
        ]
        for kind in ("User", "Role"):
            for label, policy_names, expected in names:
                with (
                    self.subTest(kind=kind, names=label),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    comparison = legacy_comparison(Path(directory), count=1, stacks=1)
                    resource_type = "IAM." + kind
                    comparison.resources["service-0"]["0000"].update(
                        resourceType=resource_type, **{"cfn-logicalId": "stack0-Log0"}
                    )
                    policies = [
                        {
                            "PolicyDocument": {
                                "Statement": [
                                    {
                                        "Effect": "Allow",
                                        "Action": action,
                                        "Resource": "*",
                                        "Condition": {"StringEquals": {"x": "y"}},
                                    }
                                ]
                            }
                        }
                        for action in ("s3:GetObject", "s3:PutObject")
                    ]
                    values = comparison.models["service-0"].values
                    values.update(
                        {
                            "desired.resource.0000.resourceType": resource_type,
                            "desired.resource.0000.cfn-logicalId": "stack0-Log0",
                        }
                    )
                    rows = []
                    for index, policy in enumerate(policies, 1):
                        rid = f"0000-{index:03d}"
                        row = {
                            "property": resource_type + ".Policies[].PolicyDocument",
                            "value": "`" + json.dumps(policy["PolicyDocument"]) + "`",
                        }
                        rows.append((rid, row))
                        values[f"desired.row.{rid}.property"] = row["property"]
                        values[f"desired.row.{rid}.value"] = row["value"]
                    comparison.rows["service-0"]["0000"] = rows
                    _, (document, _, _) = comparison.stack(comparison.templates()[0][1])
                    document["Conditions"] = {
                        "Yes": {"Fn::Equals": [1, 1]},
                        "No": {"Fn::Equals": [1, 2]},
                    }
                    actual = [
                        {"PolicyName": name, **json.loads(json.dumps(policy))}
                        for name, policy in reversed(
                            list(zip(policy_names, policies, strict=True))
                        )
                    ]
                    actual.extend(
                        [
                            {
                                "PolicyName": "extra",
                                "PolicyDocument": {"Ref": "Unrelated"},
                            },
                            {
                                "Fn::If": [
                                    "No",
                                    {"Ref": "Inactive"},
                                    {"Ref": "AWS::NoValue"},
                                ]
                            },
                        ]
                    )
                    document["Resources"]["Log0"] = {
                        "Type": "AWS::IAM::" + kind,
                        "Properties": {"Policies": actual},
                    }
                    records = comparison.run()
                    summary = _imports_issues_aggregate.iac_summary(
                        records, "fixture", "team", ["service-0"]
                    )
                    integrity = [
                        item for item in records if item.get("input_integrity")
                    ]
                    compared = [
                        item for item in records if not item.get("input_integrity")
                    ]
                    self.assertEqual(
                        [item["category"] for item in compared], ["matched"]
                    )
                    self.assertEqual(
                        [item["category"] for item in integrity],
                        []
                        if expected == "matched"
                        else ["difference" if expected == "invalid" else expected],
                        records,
                    )
                    if integrity:
                        item = integrity[0]
                        self.assertEqual(item["resource"], "0000")
                        self.assertEqual(
                            item["property"], resource_type + ".Policies[].PolicyName"
                        )
                        self.assertEqual(
                            item["iac"]["path"],
                            "infra/cloudformation/templates/0.json",
                        )
                        self.assertTrue(
                            item["iac"]["pointer"].startswith(
                                "/1/PolicyName"
                                if expected == "invalid"
                                else "/0/PolicyName"
                            )
                        )
                        self.assertIn("model", item)
                    if expected == "invalid":
                        self.assertEqual(item["cause"]["kind"], "input-invalid")
                        self.assertEqual(
                            item["cause"]["pointers"],
                            ["/0/PolicyName", "/1/PolicyName"],
                        )
                        self.assertEqual(
                            _imports_issues_aggregate.iac_dataset(
                                records, "fixture", "team", ["service-0"]
                            )[1][0]["classification"],
                            "IaC入力不正",
                        )
                    self.assertEqual(
                        summary["issue_count"], 0 if expected == "matched" else 1
                    )
                    if expected != "matched":
                        continue
                    actual[2]["PolicyDocument"] = {"Statement": []}
                    for field, replacement in (
                        ("Action", "s3:DeleteObject"),
                        ("Resource", "other"),
                        ("Condition", {"StringEquals": {"x": "z"}}),
                    ):
                        with self.subTest(field=field):
                            original = actual[0]["PolicyDocument"]["Statement"][0][
                                field
                            ]
                            actual[0]["PolicyDocument"]["Statement"][0][field] = (
                                replacement
                            )
                            start = len(comparison.results)
                            records = comparison.run()[start:]
                            summary = _imports_issues_aggregate.iac_summary(
                                records, "fixture", "team", ["service-0"]
                            )
                            self.assertEqual(
                                [item["category"] for item in records],
                                ["difference"],
                                records,
                            )
                            self.assertEqual(summary["issue_count"], 1)
                            details = [
                                item
                                for group in comparison.display_differences.values()
                                for item in group
                            ]
                            candidates = [
                                item for item in details if "IaC候補" in item["path"]
                            ]
                            self.assertTrue(candidates, details)
                            self.assertTrue(
                                all("差分未確定" in item["path"] for item in candidates)
                            )
                            self.assertIn(
                                replacement if isinstance(replacement, str) else '"z"',
                                str(candidates),
                            )
                            self.assertFalse(
                                any(
                                    item["path"].endswith("." + field)
                                    for item in details
                                ),
                                details,
                            )
                            self.assertNotIn("Unrelated", str(details))
                            actual[0]["PolicyDocument"]["Statement"][0][field] = (
                                original
                            )

    def test_policy_integrity_selection_scope(self):
        for kind in ("User", "Role"):
            name = kind + "Name"
            for selected in (
                {name},
                {"Policies"},
                {"Policies[].PolicyDocument"},
                {"Policies[].PolicyName"},
                None,
            ):
                for unknown in (False, True):
                    with (
                        self.subTest(kind=kind, selected=selected, unknown=unknown),
                        tempfile.TemporaryDirectory() as directory,
                    ):
                        desired = [(name, "Alice")]
                        for policy_name in ("one", "two"):
                            desired.extend(
                                [
                                    ("Policies[].PolicyName", policy_name),
                                    ("Policies[].PolicyDocument", {"Statement": []}),
                                ]
                            )
                        if selected == {name}:
                            desired = [(name, "Alice")]
                        actual = {
                            name: "Alice",
                            "Policies": [
                                {
                                    "PolicyName": "dupe",
                                    "PolicyDocument": {"Statement": []},
                                },
                                {
                                    "PolicyName": {"Ref": "Missing"}
                                    if unknown
                                    else "dupe",
                                    "PolicyDocument": {"Statement": []},
                                },
                            ],
                        }
                        comparison, resource, document = iam_policy_comparison(
                            Path(directory), kind, desired, actual
                        )
                        owner = document["Resources"]["Log0"]
                        evaluate = comparison.evaluate
                        with patch.object(
                            comparison, "evaluate", wraps=evaluate
                        ) as evaluated:
                            batch = comparison.compare_rows(
                                "service-0",
                                "0000",
                                resource,
                                "stack0",
                                "Log0",
                                comparison.root
                                / "infra/cloudformation/templates/0.json",
                                owner,
                                document,
                                properties=selected,
                            )
                        self.assertIsNone(batch.failure)
                        integrity = [
                            item
                            for item in batch.records
                            if item.get("input_integrity")
                        ]
                        expected = selected is None or selected in (
                            {"Policies"},
                            {"Policies[].PolicyName"},
                        )
                        self.assertEqual(len(integrity), int(expected), batch.records)
                        if expected:
                            self.assertEqual(
                                integrity[0]["category"],
                                "uncompared" if unknown else "difference",
                            )
                        else:
                            self.assertFalse(
                                any(
                                    call.args[1] == {"Ref": "Missing"}
                                    for call in evaluated.call_args_list
                                )
                            )
                        if selected == {name}:
                            self.assertEqual(
                                [
                                    (item["property"], item["category"])
                                    for item in batch.records
                                ],
                                [("IAM." + kind + "." + name, "matched")],
                            )
                        if selected == {"Policies[].PolicyDocument"}:
                            self.assertEqual(
                                [item["category"] for item in batch.records],
                                ["matched"],
                            )

    def test_duplicate_policy_issue_cause_and_evidence(self):
        for kind in ("User", "Role"):
            for change in (
                "names",
                "document",
                "other-name",
                "size",
                "unknown",
                "masked",
                "reference",
            ):
                with (
                    self.subTest(kind=kind, change=change),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    policies = [
                        {
                            "PolicyName": name,
                            "PolicyDocument": {
                                "Statement": [{"Effect": "Allow", "Action": ["a", "b"]}]
                            },
                        }
                        for name in (
                            ("one", "two")
                            if change == "names"
                            else ("one", "two", "three")
                        )
                    ]
                    actual = json.loads(json.dumps(policies))
                    actual[1]["PolicyName"] = "one"
                    actual[0]["PolicyDocument"]["Statement"][0]["Action"].reverse()
                    if change in {"document", "masked"}:
                        actual[2]["PolicyDocument"]["Statement"][0]["Effect"] = "Deny"
                    if change == "other-name":
                        actual[2]["PolicyName"] = "four"
                    if change == "size":
                        actual.append(json.loads(json.dumps(actual[2])))
                    if change == "unknown":
                        actual[2]["PolicyDocument"] = {"Ref": "Missing"}
                    comparison, _, _ = iam_policy_comparison(
                        Path(directory),
                        kind,
                        {"Policies": policies},
                        {"Policies": actual},
                    )
                    if change == "masked":
                        comparison.redacted = lambda value, prop="": redacted(
                            value, prop, sensitive_values=("Allow", "Deny")
                        )
                    if change == "reference":
                        reference = comparison.reference_decision
                        comparison.reference_decision = (
                            lambda left,
                            right,
                            kind,
                            path,
                            reference=reference,
                            **kwargs: (
                                _imports_comparison_references.ReferenceDecision(
                                    False,
                                    (
                                        {
                                            "path": path,
                                            "reason": "independent reference diagnostic",
                                        },
                                    ),
                                )
                                if path.endswith(".Effect")
                                else reference(left, right, kind, path, **kwargs)
                            )
                        )
                    with patch(
                        "comparison.evaluation.duplicate_key_cause", return_value=None
                    ):
                        baseline = json.loads(json.dumps(comparison.run()))
                    baseline_fields = list(comparison.display_differences.values())
                    comparison.results.clear()
                    comparison.display_differences.clear()
                    records = comparison.run()
                    self.assertEqual(
                        [
                            {
                                key: value
                                for key, value in item.items()
                                if key != "cause" or item.get("input_integrity")
                            }
                            for item in records
                        ],
                        baseline,
                    )
                    self.assertEqual(
                        list(comparison.display_differences.values()), baseline_fields
                    )
                    original = json.loads(json.dumps(records))
                    display = dict(comparison.display_differences)
                    entries, actions, shown = _imports_issues_aggregate.iac_dataset(
                        records, "fixture", "team", ["service-0"], display
                    )
                    self.assertEqual(records, original)
                    self.assertEqual(len(entries), len(records))
                    self.assertEqual(
                        sum(len(action["members"]) for action in actions), len(records)
                    )
                    self.assertEqual(
                        len(actions),
                        1
                        if change == "names"
                        else 3
                        if change in {"size", "unknown"}
                        else 2,
                    )
                    invalid = next(
                        action
                        for action in actions
                        if action["classification"] == "IaC入力不正"
                        and any(
                            entries[index]["record"].get("cause", {}).get("value")
                            == "one"
                            for index in action["members"]
                        )
                    )
                    self.assertEqual(invalid["repair_direction"], "入力修正")
                    self.assertEqual(
                        invalid["target"], "infra/cloudformation/templates/0.json"
                    )
                    self.assertEqual(invalid["status"], "要修正")
                    members = [entries[index]["record"] for index in invalid["members"]]
                    duplicate = next(
                        item for item in members if item.get("input_integrity")
                    )
                    self.assertEqual(
                        duplicate["cause"]["pointers"],
                        ["/0/PolicyName", "/1/PolicyName"],
                    )
                    self.assertEqual(duplicate["cause"]["value"], "one")
                    self.assertEqual(len(shown), 1)
                    self.assertEqual(len(display), 1)
                    self.assertEqual(comparison.display_differences, display)
                    if change == "names":
                        self.assertEqual(
                            _imports_issues_aggregate.iac_summary(
                                baseline, "fixture", "team", ["service-0"]
                            )["issue_count"],
                            2,
                        )
                        self.assertEqual(len(members), 2)
                        self.assertEqual(
                            [action["id"] for action in actions],
                            [
                                action["id"]
                                for action in _imports_issues_aggregate.iac_dataset(
                                    records[::-1], "fixture", "team", ["service-0"]
                                )[1]
                            ],
                        )
                        self.assertTrue(
                            all(item["category"] == "difference" for item in members)
                        )
                    if change == "document":
                        self.assertIn("Deny", str(shown))

    def test_keyless_candidate_errors_in_issue_results(self):
        for kind in ("User", "Role"):
            for relevant in (False, True):
                with (
                    self.subTest(kind=kind, relevant=relevant),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    comparison = legacy_comparison(Path(directory), count=1, stacks=1)
                    resource_type = "IAM." + kind
                    comparison.resources["service-0"]["0000"].update(
                        resourceType=resource_type, **{"cfn-logicalId": "stack0-Log0"}
                    )
                    values = comparison.models["service-0"].values
                    values.update(
                        {
                            "desired.resource.0000.resourceType": resource_type,
                            "desired.resource.0000.cfn-logicalId": "stack0-Log0",
                        }
                    )
                    rows = []
                    for index, action in enumerate(("a", "b"), 1):
                        rid = f"0000-{index:03d}"
                        row = {
                            "property": resource_type + ".Policies[].PolicyDocument",
                            "value": "`"
                            + json.dumps({"Statement": [{"Action": action}]})
                            + "`",
                        }
                        rows.append((rid, row))
                        values[f"desired.row.{rid}.property"] = row["property"]
                        values[f"desired.row.{rid}.value"] = row["value"]
                    comparison.rows["service-0"]["0000"] = rows
                    _, (document, _, _) = comparison.stack(comparison.templates()[0][1])
                    bad = {
                        "Fn::If": [
                            "Yes",
                            {
                                "PolicyName": "bad",
                                "PolicyDocument": {
                                    "Statement": [{"Action": {"Fn::Sub": 42}}]
                                },
                            },
                            {"Ref": "Inactive"},
                        ]
                    }
                    good = [
                        {
                            "PolicyName": action,
                            "PolicyDocument": {"Statement": [{"Action": action}]},
                        }
                        for action in ("a", "b")
                    ]
                    document["Conditions"] = {"Yes": {"Fn::Equals": [1, 1]}}
                    document["Resources"]["Log0"] = {
                        "Type": "AWS::IAM::" + kind,
                        "Properties": {
                            "Policies": [bad, *good[: 1 if relevant else 2]]
                        },
                    }
                    records = comparison.run()
                    if relevant:
                        self.assertIn(
                            "error", [item["category"] for item in records], records
                        )
                        self.assertIn(
                            "Fn::If/1/PolicyDocument/Statement/0/Action", str(records)
                        )
                    else:
                        self.assertEqual(
                            [item["category"] for item in records], ["matched"], records
                        )
                        summary = _imports_issues_aggregate.iac_summary(
                            records, "fixture", "team", ["service-0"]
                        )
                        self.assertEqual(summary["issue_count"], 0)

    def test_selected_policy_evaluation_follows_membership(self):
        statement_a = {
            "Sid": "A",
            "Effect": "Allow",
            "Action": ["a", "b"],
            "Resource": "*",
            "Condition": {"StringEquals": {"aws:RequestedRegion": "ap-northeast-1"}},
        }
        statement_b = {"Sid": "B", "Effect": "Allow", "Action": "c", "Resource": "*"}
        cases = [
            (False, False, True, None),
            (True, False, True, None),
            (True, False, True, "literal"),
            (False, True, True, None),
            (False, True, False, None),
            (True, True, "duplicate", None),
            (True, True, True, "condition"),
            (True, True, True, "action"),
            (True, True, True, "unresolved-condition"),
            (True, True, True, "unresolved-and-action"),
            (True, False, True, "duplicate"),
            (True, False, True, "unknown"),
        ]
        cases += [
            (order, False, True, change, wrap, kind)
            for kind in ("User", "Role")
            for order in (False, True)
            for wrap in ("if", "nested", "key", "removed", "unknown-if")
            for change in (None, "condition", "action")
        ]
        cases += [
            (True, statement_order, True, change, wrap, kind)
            for kind in ("User", "Role")
            for statement_order, change, wrap in (
                (False, None, None),
                (True, None, "if"),
                (False, "duplicate", "if"),
                (False, "unknown", "if"),
                (False, "missing", "if"),
            )
        ]
        for case in cases:
            policy_order, statement_order, sid, change = case[:4]
            wrap, kind = case[4:] if len(case) > 4 else (None, "User")
            with (
                self.subTest(
                    policy_order=policy_order,
                    statement_order=statement_order,
                    sid=sid,
                    change=change,
                    wrap=wrap,
                    kind=kind,
                ),
                tempfile.TemporaryDirectory() as directory,
            ):
                comparison = legacy_comparison(Path(directory), count=1, stacks=1)
                comparison.resources["service-0"]["0000"].update(
                    resourceType="IAM." + kind, **{"cfn-logicalId": "stack0-Log0"}
                )
                a, b = (
                    json.loads(json.dumps(statement_a)),
                    json.loads(json.dumps(statement_b)),
                )
                if not sid:
                    del a["Sid"], b["Sid"]
                elif sid == "duplicate":
                    b["Sid"] = a["Sid"]
                policies = [
                    {"PolicyName": "one", "PolicyDocument": {"Statement": [a, b]}},
                    {"PolicyName": "two", "PolicyDocument": {"Statement": [b]}},
                ]
                rows = []
                values = comparison.models["service-0"].values
                values.update(
                    {
                        "desired.resource.0000.resourceType": "IAM." + kind,
                        "desired.resource.0000.cfn-logicalId": "stack0-Log0",
                    }
                )
                for policy in policies:
                    for suffix, value in (
                        ("PolicyName", "`" + policy["PolicyName"] + "`"),
                        (
                            "PolicyDocument",
                            "`" + json.dumps(policy["PolicyDocument"]) + "`",
                        ),
                    ):
                        rid = f"0000-{len(rows) + 1:03d}"
                        row = {
                            "property": "IAM." + kind + ".Policies[]." + suffix,
                            "value": value,
                        }
                        rows.append((rid, row))
                        values.update(
                            {
                                f"desired.row.{rid}.property": row["property"],
                                f"desired.row.{rid}.value": value,
                            }
                        )
                comparison.rows["service-0"]["0000"] = rows
                actual = json.loads(json.dumps(policies))
                actual[0]["PolicyDocument"]["Statement"][0]["Condition"][
                    "StringEquals"
                ]["aws:RequestedRegion"] = {"Fn::Sub": "${AWS::Region}"}
                if change == "literal":
                    actual[0]["PolicyDocument"]["Statement"][0]["Condition"][
                        "StringEquals"
                    ]["aws:RequestedRegion"] = "ap-northeast-1"
                if change == "condition":
                    actual[0]["PolicyDocument"]["Statement"][0]["Condition"][
                        "StringEquals"
                    ]["aws:RequestedRegion"] = "elsewhere"
                if change in {"unresolved-condition", "unresolved-and-action"}:
                    actual[0]["PolicyDocument"]["Statement"][0]["Condition"][
                        "StringEquals"
                    ]["aws:RequestedRegion"] = {"Ref": "MissingParameter"}
                if change in {"action", "unresolved-and-action"}:
                    actual[0]["PolicyDocument"]["Statement"][0]["Action"] = ["a"]
                if statement_order:
                    actual[0]["PolicyDocument"]["Statement"].reverse()
                if change == "duplicate":
                    actual[1]["PolicyName"] = "one"
                if change == "missing":
                    del actual[0]["PolicyName"]
                if change == "unknown":
                    actual[0]["PolicyName"] = {"Ref": "MissingParameter"}
                actual[1]["Unselected"] = {"Ref": "MissingParameter"}
                actual.append(
                    {
                        "PolicyName": "extra",
                        "PolicyDocument": {"Ref": "MissingParameter"},
                    }
                )
                if wrap == "key":
                    actual[0]["PolicyName"] = {
                        "Fn::If": ["Yes", "one", {"Ref": "MissingParameter"}]
                    }
                elif wrap in {"if", "nested", "unknown-if"}:
                    active = actual[0]
                    if wrap == "nested":
                        active = {
                            "Fn::If": ["Yes", active, {"Ref": "MissingParameter"}]
                        }
                    actual[0] = {
                        "Fn::If": [
                            "Missing" if wrap == "unknown-if" else "Yes",
                            active,
                            {"Ref": "MissingParameter"},
                        ]
                    }
                elif wrap == "removed":
                    actual.append(
                        {
                            "Fn::If": [
                                "No",
                                {"Ref": "MissingParameter"},
                                {"Ref": "AWS::NoValue"},
                            ]
                        }
                    )
                if policy_order:
                    actual.reverse()
                _, (document, _, _) = comparison.stack(comparison.templates()[0][1])
                document["Conditions"] = {
                    "Yes": {"Fn::Equals": [1, 1]},
                    "No": {"Fn::Equals": [1, 2]},
                }
                document["Resources"]["Log0"] = {
                    "Type": "AWS::IAM::" + kind,
                    "Properties": {"Policies": actual},
                }
                records = comparison.run()
                summary = _imports_issues_aggregate.iac_summary(
                    records, "fixture", "team", ["service-0"]
                )
                if wrap == "unknown-if":
                    self.assertNotEqual(records[0]["category"], "matched", records)
                elif change in {None, "literal"}:
                    self.assertEqual(
                        [item["category"] for item in records], ["matched"], records
                    )
                    self.assertEqual(summary["issue_count"], 0)
                else:
                    self.assertNotEqual(records[0]["category"], "matched", records)
                    if change in {"condition", "action", "unresolved-and-action"}:
                        self.assertEqual(records[0]["category"], "difference", records)
                        if change != "unresolved-and-action":
                            self.assertEqual(summary["issue_count"], 1)
                        details = str(comparison.display_differences)
                        self.assertIn(
                            "Condition" if change == "condition" else "Action", details
                        )
                        self.assertNotIn("Unselected", details)

    def test_keyed_tags_resolve_only_active_selected_values(self):
        evaluate = Mock(side_effect=[True, "tag", "resolved"])

        result = project_actual(
            [
                {
                    "Fn::If": [
                        "Yes",
                        {
                            "Key": "tag",
                            "Value": {"Ref": "Selected"},
                            "Extra": {"Ref": "Missing"},
                        },
                        {"Ref": "Missing"},
                    ]
                }
            ],
            evaluate=evaluate,
            property_name="Tags",
            model_path="model",
            desired=[{"Key": "tag", "Value": "resolved"}],
            exact=False,
            rules={"Tags": keyed("Key")},
        )
        self.assertEqual(result.value[0]["Value"], "resolved")
        self.assertEqual(result.value[0]["Extra"], {"Ref": "Missing"})
        self.assertEqual(evaluate.call_count, 3)
        evaluate.assert_any_call({"Condition": "Yes"})
        evaluate.assert_any_call("tag")
        self.assertEqual(result.failures, ())

    def test_keyed_unselected_key_projects_by_position(self):
        evaluate = Mock(
            side_effect=lambda value: {"Ref": "Selected"} == value
            and "resolved"
            or value
        )
        result = project_actual(
            [{"Key": {"Ref": "Unselected"}, "Value": {"Ref": "Selected"}}],
            evaluate=evaluate,
            property_name="Tags",
            model_path="model",
            desired=[{"Value": "resolved"}],
            exact=False,
            rules={"Tags": keyed("Key")},
        )
        self.assertEqual(result.value[0]["Value"], "resolved")
        self.assertEqual(evaluate.call_args_list, [call({"Ref": "Selected"})])
        self.assertEqual(result.failures, ())

    def test_iam_policy_without_name_evaluates_selected_document(self):
        desired = [{"PolicyDocument": {"Statement": [{"Effect": "Allow"}]}}]
        actual = [
            {
                "PolicyName": "OnlyOne",
                "PolicyDocument": {"Statement": [{"Effect": {"Ref": "Effect"}}]},
            }
        ]
        evaluate = Mock(
            side_effect=lambda value: "Allow" if value == {"Ref": "Effect"} else value
        )
        for kind in ("IAM.User", "IAM.Role"):
            rules = registry.rules(kind)
            result = project_actual(
                actual,
                evaluate=evaluate,
                property_name="Policies",
                model_path="model",
                desired=desired,
                exact=False,
                rules=rules,
            )
            self.assertEqual(result.failures, ())
            self.assertIs(
                compare_values(desired, result.value, "Policies", rules=rules).equal,
                True,
            )

    def test_keyless_policy_lazy_intrinsics_and_extra_policy(self):
        desired = [
            {"PolicyDocument": {"Statement": [{"Action": "a"}]}},
            {"PolicyDocument": {"Statement": [{"Action": "b"}]}},
        ]
        actual = [
            {
                "Fn::If": [
                    "Yes",
                    {
                        "PolicyName": {"Fn::Sub": "variable"},
                        "PolicyDocument": {
                            "Statement": [{"Action": {"Fn::Sub": "${B}"}}]
                        },
                    },
                    {"Ref": "Inactive"},
                ]
            },
            {
                "PolicyName": "a",
                "PolicyDocument": {"Statement": [{"Action": "a"}]},
                "Extra": {"Ref": "Unselected"},
            },
            {"PolicyName": "extra", "PolicyDocument": {"Ref": "Unrelated"}},
        ]

        for kind in ("IAM.User", "IAM.Role"):
            evaluate = Mock(side_effect=resolve_keyless_policy_test)
            rules = registry.rules(kind)
            projected = project_actual(
                actual,
                evaluate=evaluate,
                property_name="Policies",
                model_path="model",
                desired=desired,
                exact=False,
                rules=rules,
            )
            result = compare_values(desired, projected.value, "Policies", rules=rules)
            self.assertIs(result.equal, True)
            self.assertNotIn(call({"Ref": "Unselected"}), evaluate.call_args_list)
            self.assertNotIn(call({"Ref": "Inactive"}), evaluate.call_args_list)
            self.assertNotIn(call({"Ref": "Unrelated"}), evaluate.call_args_list)
            self.assertEqual(
                evaluate.call_args_list.count(call({"Fn::Sub": "variable"})), 0
            )
            self.assertIs(
                compare_values(desired, projected.value, "Policies", rules=rules).equal,
                True,
            )
            self.assertEqual(
                evaluate.call_args_list.count(call({"Fn::Sub": "variable"})), 0
            )

    def test_keyless_candidate_evaluation_retains_errors(self):
        desired = [{"PolicyDocument": {"Statement": [{"Action": "a"}]}}]
        actual = [{"PolicyDocument": {"Statement": [{"Action": {"Fn::Sub": 42}}]}}]
        evaluate = Mock(side_effect=ValueError("invalid Fn::Sub"))
        rules = registry.rules("IAM.User")
        prepared = project_actual(
            actual,
            evaluate=evaluate,
            property_name="Policies",
            model_path="model",
            desired=desired,
            exact=False,
            rules=rules,
        )
        result = compare_values(
            desired,
            prepared.value,
            "Policies",
            rules=rules,
            reference=candidate_test_reference,
        )
        self.assertIsNone(result.equal)
        self.assertEqual(len(result.candidate_failures), 1)
        self.assertIsInstance(result.candidate_failures[0][2], ValueError)

    def test_keyless_difference_uses_proven_name_and_projected_values(self):
        desired = [
            {
                "PolicyName": "named",
                "PolicyDocument": {"Statement": [{"Action": ["a", "b"]}]},
            },
            {"PolicyDocument": {"Statement": [{"Action": "other"}]}},
        ]
        actual = [
            {
                "PolicyName": "other",
                "PolicyDocument": {"Statement": [{"Action": "other"}]},
            },
            {
                "PolicyName": "named",
                "PolicyDocument": {"Statement": [{"Action": {"Fn::Sub": "variable"}}]},
            },
        ]
        rules = registry.rules("IAM.User")
        projected = project_actual(
            actual,
            evaluate=resolve_keyless_policy_test,
            property_name="Policies",
            model_path="model",
            desired=desired,
            exact=False,
            rules=rules,
        )
        result = compare_values(
            desired,
            projected.value,
            "Policies",
            rules=rules,
            reference=candidate_test_reference,
        )
        self.assertIs(result.equal, False)
        details = value_differences(result, desired, projected.value, "Policies")
        self.assertTrue(details, details)
        self.assertTrue(
            all("PolicyName=named" in item["path"] for item in details), details
        )
        self.assertNotIn("other", str(details))
        self.assertIn("Action", str(details))

        keyless = [{"PolicyDocument": desired[0]["PolicyDocument"]}, desired[1]]
        for kind in ("IAM.User", "IAM.Role"):
            rules = registry.rules(kind)
            evaluate = Mock(side_effect=resolve_keyless_policy_test)
            projected = project_actual(
                actual,
                evaluate=evaluate,
                property_name="Policies",
                model_path="model",
                desired=keyless,
                exact=False,
                rules=rules,
            )
            result = compare_values(keyless, projected.value, "Policies", rules=rules)
            self.assertIs(result.equal, False)
            details = value_differences(result, keyless, projected.value, "Policies")
            self.assertEqual(len(details), 1, details)
            self.assertEqual(
                details[0]["path"], "Policies[0].PolicyDocument.Statement[0].Action"
            )
            self.assertEqual(details[0]["iac"], "b")
            self.assertNotIn("Fn::Sub", str(details))
            self.assertNotIn("other", str(details))
            self.assertEqual(
                evaluate.call_args_list.count(call({"Fn::Sub": "variable"})), 1
            )
            masked = value_differences(
                result,
                keyless,
                projected.value,
                "Policies",
                redact=_bind_framework_callback(redacted, sensitive_values=("b",)),
            )
            self.assertIn("<masked sensitive parameter>", masked[0]["iac"])
            self.assertNotIn('"Action":"b"', str(masked))

    def test_ordered_array_still_checks_position(self):
        with tempfile.TemporaryDirectory() as directory:
            comparison = legacy_comparison(Path(directory), count=1, stacks=1)
            comparison.resources["service-0"]["0000"].update(
                resourceType="IAM.User", **{"cfn-logicalId": "stack0-Log0"}
            )
            row = {"property": "IAM.User.Groups", "value": '`["one", "two"]`'}
            comparison.models["service-0"].values.update(
                {
                    "desired.resource.0000.resourceType": "IAM.User",
                    "desired.resource.0000.cfn-logicalId": "stack0-Log0",
                    "desired.row.0000-001.property": row["property"],
                    "desired.row.0000-001.value": row["value"],
                }
            )
            comparison.rows["service-0"]["0000"] = [("0000-001", row)]
            _, (document, _, _) = comparison.stack(comparison.templates()[0][1])
            document["Resources"]["Log0"] = {
                "Type": "AWS::IAM::User",
                "Properties": {"Groups": ["two", "one"]},
            }
            self.assertEqual(
                [item["category"] for item in comparison.run()], ["difference"]
            )

    def test_other_types_and_union_conversion_stay_unchanged(self):
        cases = [
            ("string", "False", "False"),
            ("integer", "7", 7),
            ("number", "1.25", 1.25),
            ("object", '{"enabled":true}', {"enabled": True}),
            ("array", "[false,1]", [False, 1]),
            ("null", "null", None),
            (["boolean", "null"], "false", False),
            (["string", "object"], '{"a":1}', {"a": 1}),
        ]
        schema = Mock()
        options = dict(
            local_comparison=True,
            desired_reference=Mock(),
            property_schema=schema,
            evaluate=Mock(),
            model_path=Path("/synthetic/model.properties"),
        )
        for kind, raw, expected in cases:
            with self.subTest(kind=kind, raw=raw):
                schema.return_value = {"type": kind}
                prepared = desired_value(
                    "fixture",
                    {"property": "IAM.User.Value", "value": "`" + raw + "`"},
                    "IAM.User",
                    **options,
                )
                self.assertEqual(prepared.require_value(), expected)
                self.assertIs(type(prepared.value), type(expected))
        for kind, raw, error in [
            (["boolean", "null"], "False", ValueError),
            (["string", "object"], "plain text", ValueError),
            (None, "false", Blocked),
            ("boolean", "yes", ValueError),
        ]:
            with self.subTest(kind=kind, raw=raw):
                schema.return_value = {"type": kind}
                prepared = desired_value(
                    "fixture",
                    {"property": "IAM.User.Value", "value": raw},
                    "IAM.User",
                    **options,
                )
                self.assertIsInstance(prepared.error, error)

    def test_boolean_model_reference_and_document_bypass_literal_conversion(self):
        reference = {"$modelRef": {"logicalId": "Fixture", "attribute": "Value"}}
        options = dict(
            local_comparison=True,
            desired_reference=Mock(),
            property_schema=Mock(return_value={"type": "boolean"}),
            evaluate=Mock(),
            model_path=Path("/synthetic/model.properties"),
        )
        for row, expected in [
            ({"value": json.dumps(reference)}, reference),
            ({"value": "", "document": "false"}, False),
        ]:
            with self.subTest(row=row):
                prepared = desired_value(
                    "fixture",
                    dict(row, property="IAM.User.LoginProfile.PasswordResetRequired"),
                    "IAM.User",
                    **options,
                )
                self.assertEqual(prepared.require_value(), expected)
                self.assertIs(type(prepared.value), type(expected))
        expressions = [
            {"Fn::GetAtt": ["Fixture", "Value"]},
            {"Fn::Sub": "${Fixture.Value}"},
            {"Fn::Join": ["", ["false"]]},
            {"Ref": "Fixture"},
        ]
        for local in (False, True):
            for expression in expressions:
                with self.subTest(local=local, expression=expression):
                    options.update(
                        local_comparison=local,
                        evaluate=Mock(return_value=False),
                        stack="fixture",
                    )
                    prepared = desired_value(
                        "fixture",
                        {
                            "property": "IAM.User.LoginProfile.PasswordResetRequired",
                            "value": json.dumps(expression),
                        },
                        "IAM.User",
                        **options,
                    )
                    self.assertEqual(
                        prepared.require_value(), False if local else expression
                    )


class IntrinsicWarningTests(unittest.TestCase):
    def test_unresolved_leaves_keep_other_comparisons_and_report_counts(self):
        comparison_status = _imports_issues_aggregate.comparison_status
        iac_summary = _imports_issues_aggregate.iac_summary
        validate_aws_document = _imports_utils_json_format.validate_aws_document
        expressions = [
            {"Fn::Sub": "${Missing}"},
            {"Fn::GetAtt": ["Missing", "Arn"]},
            {"Fn::ImportValue": "External"},
            {"Ref": "Missing"},
            {"Fn::Join": ["", [{"Fn::GetAtt": ["Missing", "Arn"]}]]},
            {"Fn::If": ["Pending", {"Ref": "Missing"}, "literal"]},
            {"Fn::UnknownFuture": "unverified"},
        ]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("socket.socket", side_effect=AssertionError("network forbidden")),
        ):
            for expression in expressions:
                with self.subTest(expression=expression):
                    comparison = legacy_comparison(Path(directory), count=1, stacks=1)
                    comparison.resources["service-0"]["0000"]["cfn-logicalId"] = (
                        "stack0-Log0"
                    )
                    comparison.models["service-0"].values[
                        "desired.resource.0000.cfn-logicalId"
                    ] = "stack0-Log0"
                    rows = comparison.rows["service-0"]["0000"]
                    rows.append(
                        (
                            "0000-002",
                            {
                                "property": "Logs.LogGroup.DataProtectionPolicy",
                                "value": "",
                                "document": json.dumps(
                                    {"Known": 7, "Deferred": expression}
                                ),
                            },
                        )
                    )
                    unit = comparison.templates()[0][1]
                    template, (document, _, _) = comparison.stack(unit)
                    document["Resources"]["Log0"]["Properties"][
                        "DataProtectionPolicy"
                    ] = {"Known": 7, "Deferred": expression}
                    results = comparison.run()
                    self.assertEqual(
                        [item["category"] for item in results],
                        ["matched", "uncompared"],
                    )
                    self.assertTrue(comparison.warnings)
                    saved_records, saved_warnings = (
                        list(comparison.results),
                        list(comparison.warnings),
                    )
                    partial = comparison.compare_rows(
                        "service-0",
                        "0000",
                        comparison.resources["service-0"]["0000"],
                        "stack0",
                        "Log0",
                        template,
                        document["Resources"]["Log0"],
                        document,
                        properties={"DataProtectionPolicy"},
                    )
                    self.assertEqual(
                        partial.records,
                        [
                            item
                            for item in results
                            if item["property"] == "Logs.LogGroup.DataProtectionPolicy"
                        ],
                    )
                    self.assertTrue(partial.warnings)
                    self.assertEqual(comparison.results, saved_records)
                    self.assertEqual(comparison.warnings, saved_warnings)

                    self.assertTrue(
                        all(
                            w["severity"] == "WARNING"
                            and w["property"] == "Logs.LogGroup.DataProtectionPolicy"
                            and w["pointer"].startswith("/Deferred")
                            for w in comparison.warnings
                        )
                    )
                    summary = iac_summary(results, "fixture", "team", ["service-0"])
                    self.assertEqual(summary["records"]["uncompared"], 1)
                    self.assertEqual(summary["records"]["error"], 0)
                    self.assertEqual(comparison_status(summary["records"]), "partial")
                    document["Resources"]["Log0"]["Properties"]["DataProtectionPolicy"][
                        "Known"
                    ] = 8
                    comparison.results = []
                    self.assertEqual(
                        [item["category"] for item in comparison.run()],
                        ["matched", "difference", "uncompared"],
                    )
                    with self.assertRaises(ValueError):
                        validate_aws_document(json.loads(rows[-1][1]["document"]))

    def test_local_functions_resolve_with_proven_stack_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            comparison = legacy_comparison(Path(directory), count=1, stacks=1)
            comparison.local_comparison = True
            comparison.stack_inputs["stack0"] = (
                {
                    "Conditions": {"Yes": {"Fn::Equals": [1, 1]}},
                    "Mappings": {"M": {"K": {"V": "mapped"}}},
                },
                {"Name": "confirmed"},
                {"AWS::Region": "fixture-region"},
            )
            expressions = [
                ({"Ref": "Name"}, "confirmed"),
                ({"Fn::Sub": "${AWS::Region}/${Name}"}, "fixture-region/confirmed"),
                ({"Fn::Join": ["-", ["a", "b"]]}, "a-b"),
                ({"Fn::Split": [",", "a,b"]}, ["a", "b"]),
                ({"Fn::Select": [0, ["a"]]}, "a"),
                ({"Fn::If": ["Yes", "a", {"Ref": "Unknown"}]}, "a"),
                ({"Fn::FindInMap": ["M", "K", "V"]}, "mapped"),
            ]
            for expression, expected in expressions:
                row = {
                    "property": "Logs.LogGroup.DataProtectionPolicy",
                    "value": "",
                    "document": json.dumps({"Value": expression}),
                }
                self.assertEqual(
                    comparison.prepare_value(
                        "service-0", row, "Logs.LogGroup", stack="stack0"
                    ).require_value(),
                    {"Value": expected},
                )
            self.assertFalse(comparison.warnings)
            row["document"] = '{"Value": {"Fn::Join": [""]}}'
            with self.assertRaises(ValueError):
                comparison.prepare_value(
                    "service-0", row, "Logs.LogGroup", stack="stack0"
                ).require_value()


class ExplicitIdentityTests(unittest.TestCase):
    def test_missing_mapping_never_searches_legacy_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            comparison = legacy_comparison(Path(directory))
            with patch.object(
                comparison,
                "stack_input",
                side_effect=AssertionError("implicit CFn search"),
            ):
                results = comparison.run()
            self.assertEqual([item["category"] for item in results], ["uncompared"] * 3)
            self.assertTrue(
                all(
                    "explicit cfn-logicalId is required" in item["reason"]
                    for item in results
                )
            )

    def test_explicit_mapping_and_run_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            comparison = legacy_comparison(Path(directory))
            for number in range(3):
                key = f"{number:04d}"
                mapping = f"stack{number % 2}-Log{number}"
                comparison.resources["service-0"][key]["cfn-logicalId"] = mapping
                comparison.models["service-0"].values[
                    f"desired.resource.{key}.cfn-logicalId"
                ] = mapping
            self.assertEqual(
                [item["category"] for item in comparison.run()], ["matched"] * 3
            )
            del comparison.stack_inputs["stack1"][0]["Resources"]["Log1"]
            comparison.results = []
            self.assertEqual(comparison.run()[1]["reason"], "resource missing")
            # Changing a Model logicalId never changes the explicit CFn correspondence.
            comparison.resources["service-0"]["0000"]["logicalId"] = "Logs_LogGroup_999"
            comparison.results = []
            self.assertEqual(comparison.run()[0]["category"], "matched")

    def test_duplicate_direct_ownership_and_type_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            comparison = legacy_comparison(Path(directory))
            for key in ("0000", "0001"):
                comparison.resources["service-0"][key]["cfn-logicalId"] = "stack0-Log0"
                comparison.models["service-0"].values[
                    f"desired.resource.{key}.cfn-logicalId"
                ] = "stack0-Log0"
            self.assertTrue(
                all(
                    "duplicate resource correspondence" in item["reason"]
                    for item in comparison.run()[:2]
                )
            )
            comparison.resources["service-0"]["0001"]["cfn-logicalId"] = "stack1-Log1"
            comparison.models["service-0"].values[
                "desired.resource.0001.cfn-logicalId"
            ] = "stack1-Log1"
            comparison.resources["service-0"]["0001"]["resourceType"] = "SQS.Queue"
            comparison._index = None
            comparison.results = []
            self.assertIn(
                "formal resource type mismatch", comparison.run()[1]["reason"]
            )


def _callback_ImportValueResolutionTests_test_formal_pipeline_membership_and_configuration_context_desired_value(
    contexts, /, service, row, kind, **kwargs
):
    value = row["value"].strip("`")
    if row["property"].endswith(".Configuration"):
        contexts.append(kwargs["context"])
        return json.loads(value)
    return value


def _callback_ImportValueResolutionTests_test_formal_pipeline_membership_and_configuration_context_selected_value(
    prepare, self, /, service, row, kind, **kwargs
):
    self.assertNotEqual(row["property"], "CodePipeline.Pipeline.Name")
    return prepare(service, row, kind, **kwargs)


def _callback_ImportValueResolutionTests_test_codecommit_name_uses_only_explicit_repository_name_equal(
    comparison, desired, path, /, actual
):
    return comparison.reference_same(desired, actual, "CodePipeline.Pipeline", path)


def _callback_ImportValueResolutionTests_test_codebuild_plaintext_resource_attributes_equal(
    comparison, prop, /, left, right
):
    return comparison.reference_same(left, right, "CodeBuild.Project", prop)


def _callback_ImportValueResolutionTests_test_codebuild_plaintext_resource_attributes_desired(
    comparison, /, logical, attribute=None, name="VALUE", variable_type="PLAINTEXT"
):
    service = {"Bucket": "s3", "Vpc": "vpc", "Secret": "secrets-manager"}.get(
        logical, "kms"
    )
    link = f"[resource]({service}.md#existing-{logical})"
    return comparison.desired_reference(
        "codebuild",
        link,
        "CodeBuild.Project",
        "Environment.EnvironmentVariables[].Value",
        attribute,
        {"Type": variable_type},
    )


def _callback_resource_attribute_symbol(
    comparison, /, logical, attribute=None, name="VALUE"
):
    service = {"Bucket": "s3", "Vpc": "vpc", "Secret": "secrets-manager"}.get(
        logical, "kms"
    )
    return comparison.reference(
        "codebuild", f"[resource]({service}.md#existing-{logical})", attribute
    )


class ImportValueResolutionTests(unittest.TestCase):
    def test_codecommit_name_uses_only_explicit_repository_name(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("socket.socket", side_effect=AssertionError("network forbidden")),
        ):
            comparison = legacy_comparison(Path(directory), count=1, stacks=1)
            comparison.local_comparison = comparison.reference_models_loaded = True
            resource = comparison.resources["service-0"]["0000"]
            resource.update(
                resourceType="CodeCommit.Repository",
                anchor="repository",
                **{"cfn-logicalId": "stack0-Repository"},
            )
            comparison.models["service-0"].values.update(
                {
                    "desired.resource.0000." + key: value
                    for key, value in resource.items()
                }
            )
            definition = {
                "Type": "AWS::CodeCommit::Repository",
                "Properties": {"RepositoryName": {"Fn::Sub": "${Prefix}-repository"}},
            }
            document = {
                "Resources": {"Repository": definition},
                "Conditions": {"Inactive": {"Fn::Equals": ["yes", "no"]}},
            }
            comparison.stack_inputs = {"stack0": (document, {"Prefix": "fixture"}, {})}
            path = "Stages[].Actions[].Configuration.RepositoryName"
            with patch("comparison.inputs.catalog_outputs", return_value=set()):
                desired = comparison.desired_reference(
                    "service-0",
                    "[repository](service-0.md#repository)",
                    "CodePipeline.Pipeline",
                    path,
                    context={
                        "ActionTypeId": dict(
                            Category="Source",
                            Owner="AWS",
                            Provider="CodeCommit",
                            Version="1",
                        )
                    },
                )
            equal = _bind_framework_callback(
                _callback_ImportValueResolutionTests_test_codecommit_name_uses_only_explicit_repository_name_equal,
                comparison,
                desired,
                path,
            )
            self.assertEqual(
                REF_ATTRIBUTES.get("CodeCommit.Repository"), "RepositoryId"
            )
            self.assertTrue(
                equal(
                    comparison.evaluate(
                        "stack0", {"Fn::GetAtt": ["Repository", "Name"]}
                    )
                )
            )
            self.assertFalse(
                equal(comparison.evaluate("stack0", {"Ref": "Repository"}))
            )
            self.assertTrue(equal("fixture-repository"))
            self.assertFalse(equal("different-repository"))
            self.assertEqual(
                comparison.reference_literal(
                    comparison.evaluate("stack0", {"Fn::Sub": "${Repository.Name}"})
                ),
                "fixture-repository",
            )
            self.assertEqual(
                comparison.evaluate("stack0", {"Fn::Sub": "${Repository}"})[
                    "$attribute"
                ],
                "RepositoryId",
            )
            for setting in [
                None,
                {"Ref": "Unknown"},
                {"Fn::GetAtt": ["Repository", "RepositoryId"]},
                42,
                True,
                ["repository"],
                "PENDING_DEPLOY",
                "",
            ]:
                definition["Properties"] = (
                    {} if setting is None else {"RepositoryName": setting}
                )
                with self.subTest(setting=setting):
                    self.assertIsNone(equal("fixture-repository"))
            definition["Properties"] = {"RepositoryName": "fixture-repository"}
            for change in [
                "condition",
                "transform",
                "resource-type",
                "resource-mapping",
                "stack-mapping",
            ]:
                with self.subTest(change=change):
                    comparison.symbols.clear()
                    if change == "condition":
                        definition["Condition"] = "Inactive"
                    elif change == "transform":
                        document["Transform"] = "UnresolvedTransform"
                    elif change == "resource-type":
                        definition["Type"] = "AWS::S3::Bucket"
                    elif change == "resource-mapping":
                        comparison.resources["service-0"]["duplicate"] = dict(resource)
                        comparison.models["service-0"].values.update(
                            {
                                "desired.resource.duplicate." + key: value
                                for key, value in resource.items()
                            }
                        )
                        comparison._index = None
                    else:
                        comparison.templates = lambda: [
                            ("one", {"name": "stack0"}),
                            ("two", {"name": "stack0"}),
                        ]
                    self.assertIsNone(equal("fixture-repository"))
                    definition.pop("Condition", None)
                    document.pop("Transform", None)
                    definition["Type"] = "AWS::CodeCommit::Repository"
                    if change == "resource-mapping":
                        comparison.resources["service-0"].pop("duplicate")
                        for key in resource:
                            comparison.models["service-0"].values.pop(
                                "desired.resource.duplicate." + key
                            )
                        comparison._index = None

    def test_resource_attributes_and_codebuild_plaintext_prohibition(self):
        # Authored identities and templates only; no consumer inputs or physical identifiers.
        with tempfile.TemporaryDirectory() as directory:
            comparison = issues_iac.Comparison.__new__(issues_iac.Comparison)
            comparison.export_provenance = {}
            comparison.sensitive_values = set()
            comparison.root = Path(directory)
            comparison.environment, comparison.directory = "fixture", "team"
            comparison.catalog = DesignSchemaCatalog(
                Path(__file__).resolve().parents[4]
            )
            comparison.local_comparison = comparison.reference_models_loaded = True
            comparison.reference_formats, comparison.symbols = {}, {}
            comparison._index = None
            comparison.resources = {
                "kms": {},
                "s3": {},
                "vpc": {},
                "secrets-manager": {},
            }
            comparison.rows = {service: {} for service in comparison.resources}
            comparison.models = {}
            definitions = {}
            for service, identity, kind, logical in [
                ("kms", "001", "KMS.Key", "Key"),
                ("kms", "002", "KMS.Alias", "Alias"),
                ("kms", "003", "KMS.Key", "OtherKey"),
                ("s3", "001", "S3.Bucket", "Bucket"),
                ("vpc", "001", "EC2.VPC", "Vpc"),
                ("secrets-manager", "001", "SecretsManager.Secret", "Secret"),
            ]:
                resource = {
                    "resourceType": kind,
                    "logicalId": kind.replace(".", "_") + "_" + identity,
                    "anchor": "existing-" + logical,
                    "cfn-logicalId": "producer-" + logical,
                }
                if kind == "KMS.Alias":
                    resource["parentReference"] = "[key](kms.md#existing-Key)"
                comparison.resources[service][identity] = resource
                comparison.rows[service][identity] = []
                definitions[logical] = {
                    "Type": "AWS::" + kind.replace(".", "::"),
                    "Properties": {},
                }
            definitions["Alias"]["Properties"] = {
                "AliasName": "alias/fixture",
                "TargetKeyId": {"Ref": "Key"},
            }
            definitions["Bucket"]["Properties"] = {"BucketName": "fixture-bucket"}
            for service, resources in comparison.resources.items():
                comparison.models[service] = SimpleNamespace(
                    values={
                        f"desired.resource.{identity}.{key}": value
                        for identity, resource in resources.items()
                        for key, value in resource.items()
                    }
                )
            producer = {"Resources": definitions}
            pseudo = {
                "AWS::Partition": "aws",
                "AWS::Region": "ap-northeast-1",
                "AWS::AccountId": "123456789012",
            }
            comparison.stack_inputs = {
                "producer": (producer, {}, pseudo),
                "build": ({}, {}, pseudo),
            }
            comparison.templates = lambda: [("001", {"name": "producer"})]
            comparison.stack = lambda unit: (
                Path("producer.yaml"),
                comparison.stack_inputs["producer"],
            )
            alias_value = {
                "Fn::Sub": [
                    "arn:${AWS::Partition}:kms:${AWS::Region}:${AWS::AccountId}:${Alias}",
                    {"Alias": {"Ref": "Alias"}},
                ]
            }
            producer["Outputs"] = {
                "Key": {
                    "Value": {"Fn::GetAtt": ["Key", "Arn"]},
                    "Export": {"Name": "key-export"},
                },
                "Alias": {"Value": alias_value, "Export": {"Name": "alias-export"}},
                "Bucket": {
                    "Value": {"Ref": "Bucket"},
                    "Export": {"Name": "bucket-export"},
                },
            }
            comparison.exports = None
            comparison.export_failures = []
            prop = "Environment.EnvironmentVariables[].Value"
            codebuild_desired = _bind_framework_callback(
                _callback_ImportValueResolutionTests_test_codebuild_plaintext_resource_attributes_desired,
                comparison,
            )
            desired = _bind_framework_callback(
                _callback_resource_attribute_symbol, comparison
            )
            equal = _bind_framework_callback(
                _callback_ImportValueResolutionTests_test_codebuild_plaintext_resource_attributes_equal,
                comparison,
                prop,
            )
            with patch("comparison.inputs.catalog_outputs", return_value=set()):
                bucket = comparison.evaluate("producer", {"Ref": "Bucket"})
                imported = comparison.evaluate(
                    "build", {"Fn::ImportValue": "bucket-export"}
                )
                for source in (bucket, imported):
                    for literal, expected in [
                        ("fixture-bucket", True),
                        ("other", False),
                    ]:
                        with self.subTest(source=source, literal=literal):
                            result = comparison.reference_decision(
                                literal,
                                source,
                                "CodeBuild.Project",
                                prop,
                                context={"Type": "PLAINTEXT"},
                            )
                            self.assertEqual(result.equal, expected)
                            self.assertEqual(
                                result.diagnostics[0]["evidence_type"],
                                "local_evaluation",
                            )
                            self.assertFalse(
                                result.diagnostics[0]["current_aws_verified"]
                            )
                definitions["Bucket"]["Properties"].clear()
                result = comparison.reference_decision(
                    "fixture-bucket",
                    bucket,
                    "CodeBuild.Project",
                    prop,
                    context={"Type": "PLAINTEXT"},
                )
                self.assertIsNone(result.equal)
                self.assertEqual(
                    result.diagnostics[0]["local_comparison"], "uncompared"
                )
                self.assertTrue(result.diagnostics[0]["reason"])
                definitions["Bucket"]["Properties"]["BucketName"] = "fixture-bucket"
                for literal, source, expected in [
                    ("alias/fixture", {"Ref": "Alias"}, True),
                    ("other", {"Ref": "Alias"}, False),
                    ("12345678-1234-1234-1234-123456789012", {"Ref": "Key"}, None),
                    (
                        "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                        {"Fn::GetAtt": ["Key", "Arn"]},
                        None,
                    ),
                ]:
                    with self.subTest(source=source):
                        value = comparison.evaluate("producer", source)
                        result = comparison.reference_decision(
                            literal,
                            value,
                            "CodeBuild.Project",
                            prop,
                            context={"Type": "PLAINTEXT"},
                        )
                        self.assertIs(result.equal, expected)
                bucket.saved_literal = "fixture-bucket"
                self.assertIsNone(
                    comparison.reference_decision(
                        bucket,
                        "fixture-bucket",
                        "CodeBuild.Project",
                        prop,
                        context={"Type": "PLAINTEXT"},
                    ).equal
                )
                nested = Expression("Join", ["", [bucket]])
                self.assertIsNone(
                    comparison.reference_decision(
                        nested,
                        "fixture-bucket",
                        "CodeBuild.Project",
                        prop,
                        context={"Type": "PLAINTEXT"},
                    ).equal
                )
                del bucket.saved_literal
                for variable_type in ("SECRETS_MANAGER", "PARAMETER_STORE"):
                    self.assertIsNone(
                        comparison.reference_decision(
                            "fixture-bucket",
                            bucket,
                            "CodeBuild.Project",
                            prop,
                            context={"Type": variable_type},
                        ).equal
                    )
                for logical in [
                    "Key",
                    "Alias",
                    "OtherKey",
                    "Bucket",
                    "Vpc",
                    "Secret",
                    "Missing",
                ]:
                    for attribute in [None, "Arn", "Name", "BucketName"]:
                        with self.subTest(logical=logical, attribute=attribute):
                            with self.assertRaisesRegex(Blocked, "PLAINTEXT"):
                                codebuild_desired(logical, attribute)
                key, alias = desired("Key", "Arn"), desired("Alias", "AliasArn")
                for model, actual, exported in [
                    (key, {"Fn::GetAtt": ["Key", "Arn"]}, "key-export"),
                    (alias, alias_value, "alias-export"),
                ]:
                    self.assertTrue(
                        equal(model, comparison.evaluate("producer", actual))
                    )
                    self.assertTrue(
                        equal(
                            model,
                            comparison.evaluate("build", {"Fn::ImportValue": exported}),
                        )
                    )
                    self.assertIsNot(equal(model, exported), True)
                self.assertFalse(equal(key, alias))
                self.assertFalse(
                    equal(key, comparison.evaluate("producer", alias_value))
                )
                self.assertFalse(equal(key, desired("OtherKey", "Arn")))
                self.assertFalse(equal(key, desired("Key", "KeyId")))
                self.assertFalse(equal(alias, desired("Alias", "AliasName")))
                with self.assertRaises((Blocked, KeyError)):
                    comparison.evaluate(
                        "producer", {"Fn::GetAtt": ["Alias", "AliasArn"]}
                    )
                self.assertFalse(
                    equal(alias, comparison.evaluate("producer", {"Ref": "Alias"}))
                )
                self.assertIsNone(
                    equal(
                        key,
                        "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                    )
                )
                self.assertTrue(
                    equal(
                        alias, "arn:aws:kms:ap-northeast-1:123456789012:alias/fixture"
                    )
                )
                definitions["Alias"]["Properties"].pop("AliasName")
                self.assertIsNone(
                    equal(
                        alias, "arn:aws:kms:ap-northeast-1:123456789012:alias/fixture"
                    )
                )
                definitions["Alias"]["Properties"]["AliasName"] = "alias/fixture"
                self.assertTrue(
                    equal(
                        desired("Bucket"),
                        comparison.evaluate("producer", {"Ref": "Bucket"}),
                    )
                )
                self.assertEqual(
                    desired("Key", "KeyId", name="KEY_ARN")["$attribute"], "KeyId"
                )
                self.assertEqual(
                    codebuild_desired("Secret", variable_type="SECRETS_MANAGER"),
                    comparison.evaluate("producer", {"Ref": "Secret"}),
                )
                for variable_type in [None, "INVALID"]:
                    with (
                        self.subTest(variable_type=variable_type),
                        self.assertRaisesRegex(
                            Blocked,
                            "reference context or receiving property contract unproven",
                        ),
                    ):
                        codebuild_desired("Bucket", variable_type=variable_type)
                with self.assertRaisesRegex(
                    Blocked, "reference attribute not confirmed: Name"
                ):
                    codebuild_desired("Bucket", variable_type="PARAMETER_STORE")
                comparison.resources["kms"]["001"]["resourceMode"] = "IMPORT"
                comparison.models["kms"].values["desired.resource.001.resourceMode"] = (
                    "IMPORT"
                )
                comparison.reference_anchor_indexes.pop("kms")
                with self.assertRaisesRegex(Blocked, "approved handoff"):
                    desired("Key", "Arn")
                comparison.resources["kms"]["001"].pop("resourceMode")
                comparison.models["kms"].values.pop("desired.resource.001.resourceMode")
                comparison.reference_anchor_indexes.pop("kms")
                for logical, attribute in [
                    ("Missing", "Arn"),
                    ("Key", "AliasArn"),
                ]:
                    with (
                        self.subTest(logical=logical, attribute=attribute),
                        self.assertRaises((Blocked, KeyError)),
                    ):
                        desired(logical, attribute)
                with self.assertRaises(Blocked):
                    comparison.evaluate("build", {"Fn::ImportValue": "unknown-export"})
                self.assertIsNone(equal(key, Expression("Sub", ["${Unknown}", {}])))
                unknown = Expression("Sub", ["${Unknown}", {}])
                self.assertIsNone(equal(unknown, unknown))

    def test_formal_pipeline_membership_and_configuration_context(self):
        comparison = issues_iac.Comparison.__new__(issues_iac.Comparison)
        comparison.models = {}
        comparison.sensitive_values = set()
        comparison.template_locations = {}
        comparison.catalog = Mock()
        comparison.stack_inputs = {"stack": ({}, {}, {})}
        comparison.evaluate = Mock()
        comparison.reference_decision = Mock()
        comparison.root = Path(__file__).resolve().parents[4]
        comparison.local_comparison = True
        comparison.results, comparison.warnings = [], []
        fields = [
            ("Stages[].Actions[].ActionTypeId.Category", "`Build`"),
            ("Stages[].Actions[].ActionTypeId.Owner", "`AWS`"),
            ("Stages[].Actions[].ActionTypeId.Provider", "`CodeBuild`"),
            ("Stages[].Actions[].ActionTypeId.Version", "`1`"),
            (
                "Stages[].Actions[].Configuration",
                '`{"ProjectName":"one","Extra":"two"}`',
            ),
            ("Stages[].Actions[].InputArtifacts[].Name", "`first`"),
            ("Stages[].Actions[].InputArtifacts[].Name", "`second`"),
            ("Stages[].Actions[].Name", "`Build`"),
            ("Stages[].Actions[].ActionTypeId.Category", "`Approval`"),
            ("Stages[].Actions[].Name", "`Approve`"),
            ("Stages[].Name", "`BuildAndApprove`"),
            ("Stages[].Actions[].Name", "`Finish`"),
            ("Stages[].Name", "`Final`"),
        ]
        rows = [
            (
                str(i),
                {
                    "property": "CodePipeline.Pipeline." + prop,
                    "value": value,
                    "comment": "ProjectName: project / Extra: extra"
                    if prop.endswith(".Configuration")
                    else "",
                },
            )
            for i, (prop, value) in enumerate(fields)
        ]
        comparison.rows = {"codepipeline": {"001": rows}}
        contexts = []
        desired_value = _bind_framework_callback(
            _callback_ImportValueResolutionTests_test_formal_pipeline_membership_and_configuration_context_desired_value,
            contexts,
        )
        comparison.prepare_value = lambda *args, **kwargs: PreparedValue(
            desired_value(*args, **kwargs), []
        )
        comparison.evaluate.side_effect = lambda stack, value: value
        ReferenceDecision = _imports_comparison_references.ReferenceDecision
        comparison.reference_decision.return_value = ReferenceDecision(True)
        stages = [
            {
                "Name": "BuildAndApprove",
                "Actions": [
                    {
                        "Name": "Build",
                        "ActionTypeId": {
                            "Category": "Build",
                            "Owner": "AWS",
                            "Provider": "CodeBuild",
                            "Version": "1",
                        },
                        "Configuration": {"ProjectName": "one", "Extra": "two"},
                        "InputArtifacts": [{"Name": "first"}, {"Name": "second"}],
                    },
                    {"Name": "Approve", "ActionTypeId": {"Category": "Approval"}},
                ],
            },
            {"Name": "Final", "Actions": [{"Name": "Finish"}]},
        ]
        template = comparison.root / "infra/cloudformation/templates/fixture.yaml"
        definition = {"Properties": {"Stages": stages}}
        batch = comparison.compare_rows(
            "codepipeline",
            "001",
            {"resourceType": "CodePipeline.Pipeline"},
            "stack",
            "Pipeline",
            template,
            definition,
            {},
        )
        self.assertEqual(
            contexts,
            [
                {
                    "ActionTypeId": {
                        "Category": "Build",
                        "Owner": "AWS",
                        "Provider": "CodeBuild",
                        "Version": "1",
                    }
                }
            ],
        )
        self.assertEqual(len(batch.records), 1)
        self.assertEqual(
            tuple(
                batch.records[0][key]
                for key in ("category", "service", "resource", "property", "reason")
            ),
            ("matched", "codepipeline", "001", "CodePipeline.Pipeline.Stages", "equal"),
        )
        self.assertEqual(comparison.results, [])
        self.assertEqual(comparison.warnings, [])
        # Selecting Stages still uses its sibling action context and never prepares Name.
        rows.append(
            (
                "other",
                {"property": "CodePipeline.Pipeline.Name", "value": "`unrelated`"},
            )
        )
        prepare = comparison.prepare_value
        selected_value = _bind_framework_callback(
            _callback_ImportValueResolutionTests_test_formal_pipeline_membership_and_configuration_context_selected_value,
            prepare,
            self,
        )
        comparison.prepare_value = selected_value
        selected = comparison.compare_rows(
            "codepipeline",
            "001",
            {"resourceType": "CodePipeline.Pipeline"},
            "stack",
            "Pipeline",
            template,
            definition,
            {},
            properties={"Stages"},
        )
        self.assertIsNone(selected.failure)
        self.assertEqual(selected.records, batch.records)
        self.assertEqual(contexts[-1], contexts[0])

        # Invalid indexed siblings defer their setting while independent Name still compares.
        comparison.rows["codepipeline"]["001"] = [
            (
                "bad",
                {
                    "property": "CodePipeline.Pipeline.Stages[0].Actions[1].ActionTypeId.Category",
                    "value": "`Build`",
                },
            ),
            ("name", {"property": "CodePipeline.Pipeline.Name", "value": "`pipeline`"}),
        ]
        comparison.prepare_value = lambda *args, **kwargs: PreparedValue("pipeline", [])
        definition = {"Properties": {"Name": "pipeline"}}
        complete = comparison.compare_rows(
            "codepipeline",
            "001",
            {"resourceType": "CodePipeline.Pipeline"},
            "stack",
            "Pipeline",
            template,
            definition,
            {},
        )
        self.assertIsNone(complete.failure)
        self.assertEqual(
            [(item["property"], item["category"]) for item in complete.records],
            [
                ("CodePipeline.Pipeline.Stages", "uncompared"),
                ("CodePipeline.Pipeline.Name", "matched"),
            ],
        )
        limited = comparison.compare_rows(
            "codepipeline",
            "001",
            {"resourceType": "CodePipeline.Pipeline"},
            "stack",
            "Pipeline",
            template,
            definition,
            {},
            properties={"Name"},
        )
        self.assertIsNone(limited.failure)
        self.assertEqual(limited.records, complete.records[1:])

    def test_api_managed_resource_remains_unverified_in_cloudformation_comparison(self):
        comparison = issues_iac.Comparison.__new__(issues_iac.Comparison)
        comparison.catalog = Mock(api_schemas={"Macie.ClassificationJob": {}})
        comparison.target = {"iacEngine": "cloudformation"}
        comparison.services = ["macie"]
        comparison.resources = {
            "macie": {"001": {"resourceType": "Macie.ClassificationJob"}}
        }
        comparison.results = []
        comparison.load_errors = []
        comparison.reference_unavailable = {}
        comparison.symbols = {}
        comparison.record = lambda *args, **kwargs: comparison.results.append(
            (args, kwargs)
        )
        comparison.templates = lambda: []

        with tempfile.TemporaryDirectory() as directory:
            comparison.root = Path(directory)
            results = comparison.run()

        self.assertEqual(
            results[0][0][:5],
            (
                "uncompared",
                "macie",
                "001",
                "*",
                "CloudFormation unsupported; outside CFn comparison; API implementation status unverified",
            ),
        )

        self.assertEqual(
            results[0][1]["cause"],
            {
                "kind": "cloudformation-unsupported",
                "resource_type": "Macie.ClassificationJob",
                "implementation_status": "unverified",
            },
        )

    def test_import_value_requires_a_complete_export_search(self):
        comparison = Mock()
        comparison.stack_inputs = {
            "s3": (
                {},
                {},
                {
                    "AWS::Partition": "aws",
                    "AWS::Region": "ap-northeast-1",
                    "AWS::AccountId": "123456789012",
                },
            )
        }
        comparison.evaluate.side_effect = lambda stack, value, seen: (
            "KmsAppKeyAlias-p4x8r2" if isinstance(value, dict) else value
        )
        comparison.templates.return_value = [
            (Path("missing.yaml"), {"name": "missing", "template": "missing.yaml"}),
            (Path("kms.yaml"), {"name": "kms", "template": "kms.yaml"}),
        ]
        comparison.stack.side_effect = [
            Blocked("stack input missing: missing.yaml"),
            (
                Path("kms.yaml"),
                (
                    {
                        "Outputs": {
                            "Alias": {
                                "Export": {"Name": "KmsAppKeyAlias-p4x8r2"},
                                "Value": "alias/app",
                            }
                        }
                    },
                    {},
                    {},
                ),
            ),
        ]
        comparison.exports = None
        comparison.export_failures = []
        comparison.local_comparison = True
        comparison.import_value = issues_iac.Comparison.import_value.__get__(comparison)

        with self.assertRaisesRegex(Blocked, "search incomplete"):
            comparison.import_value(
                "s3", {"Fn::ImportValue": "KmsAppKeyAlias-p4x8r2"}, frozenset()
            )

    def test_kms_alias_retains_identity_even_with_the_same_parent_key(self):
        comparison = issues_iac.Comparison.__new__(issues_iac.Comparison)
        comparison.sensitive_values = set()
        comparison.local_comparison = True
        comparison.resources = {
            "kms": {
                "002": {
                    "resourceType": "KMS.Alias",
                    "parentReference": "[LogKey](#kms-log)",
                },
                "001": {"resourceType": "KMS.Key", "anchor": "kms-log"},
            }
        }
        comparison.reference_formats = {}
        comparison.reference_forms = lambda kind, path: {"Arn"}

        left = ResourceReference(
            {"$resource": ["kms", "002"], "$attribute": "AliasName"}
        )
        right = ResourceReference({"$resource": ["kms", "001"], "$attribute": "Arn"})

        result = issues_iac.Comparison.reference_same(
            comparison, left, right, "S3.Bucket", "BucketEncryption"
        )

        self.assertFalse(result)
        self.assertFalse(
            issues_iac.Comparison.reference_same(
                comparison, right, left, "S3.Bucket", "BucketEncryption"
            )
        )
        self.assertTrue(
            issues_iac.Comparison.reference_same(
                comparison, right, right, "S3.Bucket", "BucketEncryption"
            )
        )
        comparison.resources["s3"] = {"001": {"resourceType": "S3.Bucket"}}
        bucket = ResourceReference({"$resource": ["s3", "001"], "$attribute": "Arn"})
        self.assertIs(
            comparison.reference_decision(
                bucket, right, "S3.BucketPolicy", "PolicyDocument"
            ).equal,
            False,
        )
        self.assertIs(
            comparison.reference_decision(
                right, bucket, "S3.BucketPolicy", "PolicyDocument"
            ).equal,
            False,
        )


def reference_comparison(root):
    comparison = issues_iac.Comparison.__new__(issues_iac.Comparison)
    comparison.root, comparison.environment, comparison.directory = (
        root,
        "fixture",
        "team",
    )
    comparison.catalog = DesignSchemaCatalog(Path(__file__).resolve().parents[4])
    comparison.local_comparison = comparison.reference_models_loaded = True
    comparison.reference_formats, comparison.symbols, comparison.export_provenance = (
        {},
        {},
        {},
    )
    comparison.sensitive_values, comparison._index = set(), None
    comparison.resources, comparison.rows, comparison.models = {}, {}, {}
    definitions = {}
    specifications = [
        ("kms", "001", "KMS.Key", "Key", {}),
        (
            "kms",
            "002",
            "KMS.Alias",
            "Alias",
            {"AliasName": "alias/fixture", "TargetKeyId": {"Ref": "Key"}},
        ),
        (
            "kms",
            "003",
            "KMS.Alias",
            "OtherAlias",
            {"AliasName": "alias/other", "TargetKeyId": {"Ref": "Key"}},
        ),
        ("kms", "004", "KMS.Key", "OtherKey", {}),
        (
            "cloudwatch-logs",
            "001",
            "Logs.LogGroup",
            "Log",
            {"LogGroupName": "/fixture/log"},
        ),
        ("codebuild", "001", "CodeBuild.Project", "Build", {"Name": "fixture-build"}),
        ("eventbridge", "001", "Events.Rule", "Rule", {"Name": "fixture-rule"}),
        ("s3", "002", "S3.Bucket", "Bucket", {"BucketName": "bucket-app-dev-data2"}),
    ]
    for service, identity, kind, logical, props in specifications:
        logical_id = (
            kind.replace(".", "_")
            + "_"
            + ("002" if logical in {"OtherAlias", "OtherKey"} else "001")
        )
        resource = {
            "resourceType": kind,
            "logicalId": logical_id,
            "anchor": "resource-" + logical_id,
            "cfn-logicalId": "producer-" + logical,
        }
        comparison.resources.setdefault(service, {})[identity] = resource
        comparison.rows.setdefault(service, {})[identity] = []
        definitions[logical] = {
            "Type": "AWS::" + kind.replace(".", "::"),
            "Properties": props,
        }
    comparison.resources["s3"]["001"] = {
        "resourceType": "S3.Bucket",
        "logicalId": "S3_Bucket_001",
        "anchor": "resource-S3_Bucket_001",
        "cfn-logicalId": "consumer-Bucket",
    }
    comparison.resources["s3"]["002"]["logicalId"] = "S3_Bucket_002"
    comparison.resources["s3"]["002"]["anchor"] = "resource-S3_Bucket_002"
    for service, resources in comparison.resources.items():
        comparison.models[service] = SimpleNamespace(
            values={
                f"desired.resource.{identity}.{key}": value
                for identity, resource in resources.items()
                for key, value in resource.items()
            }
        )
    pseudo = {
        "AWS::Partition": "aws",
        "AWS::Region": "ap-northeast-1",
        "AWS::AccountId": "123456789012",
    }
    comparison.stack_inputs = {
        "producer": ({"Resources": definitions}, {}, dict(pseudo)),
        "consumer": (
            {
                "Resources": {
                    "Bucket": {
                        "Type": "AWS::S3::Bucket",
                        "Properties": {"BucketName": "bucket-app-dev-data1"},
                    }
                }
            },
            {},
            dict(pseudo),
        ),
    }
    comparison.templates = lambda: [
        (name, {"name": name}) for name in comparison.stack_inputs
    ]
    comparison.stack = lambda unit: (
        Path(unit["name"] + ".yaml"),
        comparison.stack_inputs[unit["name"]],
    )
    comparison.stack_inputs["producer"][0]["Outputs"] = {
        "BucketArn": {
            "Value": {"Fn::GetAtt": ["Bucket", "Arn"]},
            "Export": {"Name": "fixture-BucketArn"},
        }
    }
    comparison.exports = None
    comparison.export_failures = []
    return comparison


def _lambda_main_checks_callback_156(comparison, /, a, b, p, *, kind):
    return comparison.reference_same(a, b, kind, p)


def _lambda_main_checks_callback_192(comparison, /, a, b, p):
    return comparison.reference_same(a, b, "IAM.Role", p)


def _lambda_main_checks_callback_76(comparison, /, a, b, path):
    return comparison.reference_same(a, b, "IAM.Role", path)


class ReferenceValueTests(unittest.TestCase):
    def test_kms_forms_and_arn_values(self):
        with tempfile.TemporaryDirectory() as directory:
            comparison = reference_comparison(Path(directory))
            stack = "producer"
            key_id = "12345678-1234-1234-1234-123456789012"
            key_arn = "arn:aws:kms:ap-northeast-1:123456789012:key/" + key_id
            alias_arn = "arn:aws:kms:ap-northeast-1:123456789012:alias/fixture"
            KMS_COMPARISON_FORMS = KMS_FORMS
            key = comparison.evaluate(stack, {"Ref": "Key"})
            arn = comparison.evaluate(stack, {"Fn::GetAtt": ["Key", "Arn"]})
            alias = comparison.reference(
                "kms", "[KMS_Alias_001](kms.md#resource-KMS_Alias_001)"
            )
            for prop, allowed in KMS_COMPARISON_FORMS.items():
                kind, path = (
                    ".".join(prop.split(".")[:2]),
                    ".".join(prop.split(".")[2:]),
                )
                callback = _bind_framework_callback(
                    _lambda_main_checks_callback_156, comparison, kind=kind
                )
                for form, literal in [
                    ("KeyId", key_id),
                    ("KeyArn", key_arn),
                    ("AliasName", "alias/fixture"),
                    ("AliasArn", alias_arn),
                ]:
                    assert same(literal, literal, reference=callback, path=path) is (
                        form in allowed
                    ), (prop, form)
                assert same(key, arn, reference=callback, path=path) is False
                assert (
                    same("not-a-key", "not-a-key", reference=callback, path=path)
                    is False
                )
                assert (
                    same(
                        "{{resolve:secretsmanager:key}}",
                        alias_arn if "AliasArn" in allowed else key_arn,
                        reference=callback,
                        path=path,
                    )
                    is None
                )
                assert same(key_arn, alias_arn, reference=callback, path=path) is False
                assert same(alias_arn, key_arn, reference=callback, path=path) is False
                if allowed == {"KeyArn"}:
                    with pytest.raises(
                        Blocked, match="outside receiving property contract"
                    ):
                        comparison.desired_reference(
                            "kms",
                            "[KMS_Alias_001](kms.md#resource-KMS_Alias_001)",
                            kind,
                            path,
                        )
                elif allowed <= {"KeyArn", "AliasArn"}:
                    symbolic = comparison.desired_reference(
                        "kms",
                        "[KMS_Alias_001](kms.md#resource-KMS_Alias_001)",
                        kind,
                        path,
                    )
                    assert symbolic["$attribute"] == "AliasArn"
                    assert same(symbolic, arn, reference=callback, path=path) is False
                    assert same(arn, symbolic, reference=callback, path=path) is False
                    assert same(symbolic, alias_arn, reference=callback, path=path) is (
                        "AliasArn" in allowed
                    )
                    assert same(alias_arn, symbolic, reference=callback, path=path) is (
                        "AliasArn" in allowed
                    )
                    assert (
                        same(
                            symbolic,
                            alias_arn.replace("123456789012", "999999999999"),
                            reference=callback,
                            path=path,
                        )
                        is False
                    )
                    assert (
                        same(
                            symbolic,
                            alias_arn.replace("ap-northeast-1", "us-east-1"),
                            reference=callback,
                            path=path,
                        )
                        is False
                    )
                    assert same(symbolic, alias, reference=callback, path=path) is False
                    other = comparison.desired_reference(
                        "kms",
                        "[KMS_Alias_002](kms.md#resource-KMS_Alias_002)",
                        kind,
                        path,
                    )
                    assert same(symbolic, other, reference=callback, path=path) is False
                else:
                    assert same(arn, key_arn, reference=callback, path=path) is None
                    assert same(key, key_arn, reference=callback, path=path) is False
                    assert (
                        same(key_id, key_id[:-1] + "3", reference=callback, path=path)
                        is False
                    )

            # Existing contracts outside this repair are deliberately unchanged.
            assert (
                comparison.reference_same(alias, alias, "CloudTrail.Trail", "KMSKeyId")
                is True
            )
            assert (
                comparison.reference_same(key, arn, "MWAA.Environment", "KmsKey")
                is True
            )
            assert (
                comparison.reference_same(
                    alias, alias, "SecretsManager.Secret", "KmsKeyId"
                )
                is True
            )
            assert (
                comparison.reference_same(
                    alias,
                    alias,
                    "S3.Bucket",
                    "BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID",
                )
                is True
            )

            for logical, expected in [
                (
                    "Log",
                    "arn:aws:logs:ap-northeast-1:123456789012:log-group:/fixture/log:*",
                ),
                (
                    "Build",
                    "arn:aws:codebuild:ap-northeast-1:123456789012:project/fixture-build",
                ),
                (
                    "Rule",
                    "arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule",
                ),
            ]:
                symbol = comparison.evaluate(stack, {"Fn::GetAtt": [logical, "Arn"]})
                callback = _bind_framework_callback(
                    _lambda_main_checks_callback_192, comparison
                )
                assert same(symbol, expected, reference=callback)
                assert same(expected, symbol, reference=callback)
                assert same(symbol, expected + "-wrong", reference=callback) is False
                expression = Expression("Sub", ["${Resource}", {"Resource": symbol}])
                assert same(expression, expected, reference=callback)
            log = comparison.evaluate(stack, {"Fn::GetAtt": ["Log", "Arn"]})
            expression = Expression("Select", [0, Expression("Split", [":*", log])])
            assert (
                comparison.reference_same(
                    expression,
                    "arn:aws:logs:ap-northeast-1:123456789012:log-group:/fixture/log",
                    "IAM.Role",
                    "",
                )
                is True
            )
            assert (
                comparison.reference_same(
                    Expression("Select", [9, Expression("Split", [":*", log])]),
                    "x",
                    "IAM.Role",
                    "",
                )
                is None
            )
            rule = comparison.evaluate(stack, {"Fn::GetAtt": ["Rule", "Arn"]})
            comparison.stack_inputs[stack][0]["Resources"]["Rule"]["Properties"][
                "EventBusName"
            ] = "other-bus"
            assert (
                comparison.reference_same(
                    rule,
                    "arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule",
                    "Lambda.Permission",
                    "SourceArn",
                )
                is False
            )
            comparison.stack_inputs[stack][0]["Resources"]["Build"]["Properties"].pop(
                "Name"
            )
            build = comparison.evaluate(stack, {"Fn::GetAtt": ["Build", "Arn"]})
            assert (
                comparison.reference_same(
                    build,
                    "arn:aws:codebuild:ap-northeast-1:123456789012:project/fixture-build",
                    "IAM.Role",
                    "",
                )
                is None
            )
            # Neither a fake Alias GetAtt nor a generated key ARN is synthesized.
            with pytest.raises(
                Blocked, match="unproven GetAtt return attribute: Alias.Arn"
            ):
                comparison.evaluate(stack, {"Fn::GetAtt": ["Alias", "Arn"]})
            with pytest.raises(
                (Blocked, ValueError),
                match="ARN requires a proven generated identifier: KeyId",
            ):
                comparison.reference_literal(arn)

    def test_policy_action_and_expression_values(self):
        with tempfile.TemporaryDirectory() as directory:
            comparison = reference_comparison(Path(directory))
            consumer, producer = "consumer", "producer"
            arn = "arn:aws:s3:::bucket-app-dev-data2"
            imported = {"Fn::ImportValue": "fixture-BucketArn"}
            actual = {
                "Statement": [
                    {},
                    {},
                    {
                        "Resource": {
                            "Fn::Sub": [
                                "${BucketArn}/results/*",
                                {"BucketArn": imported},
                            ]
                        }
                    },
                ]
            }
            callback = _bind_framework_callback(
                _lambda_main_checks_callback_76, comparison
            )
            reference = comparison.evaluate(consumer, imported)
            assert reference == {"$resource": ["s3", "002"], "$attribute": "Arn"}
            assert comparison.reference_literal(reference) == arn
            sub = comparison.evaluate(consumer, actual["Statement"][2]["Resource"])
            for symbolic, text in ((reference, arn), (sub, arn + "/results/*")):
                assert same(symbolic, text, reference=callback)
                assert same(text, symbolic, reference=callback)
                for wrong in (
                    text + "-other",
                    text.replace("aws:", "aws-cn:"),
                    text.replace("data2", "data1"),
                ):
                    assert same(symbolic, wrong, reference=callback) is False
            other = comparison.evaluate(consumer, {"Fn::GetAtt": ["Bucket", "Arn"]})
            assert same(reference, other, reference=callback) is False
            assert same(reference, dict(reference), reference=callback) is not True
            escaped = Expression(
                "Sub",
                [
                    "${BucketArn}/${!literal}/${Tail}",
                    {"BucketArn": reference, "Tail": "one"},
                ],
            )
            assert same(escaped, arn + "/${literal}/one", reference=callback)
            for unresolved in (
                Expression("Sub", ["${Missing}", {}]),
                Expression(
                    "Sub",
                    [
                        "${Value}",
                        {"Value": {"$resource": ["s3", "002"], "$attribute": "Arn"}},
                    ],
                ),
            ):
                assert same(unresolved, arn, reference=callback) is None
            for different in (
                Expression(
                    "Sub",
                    [
                        "${Value}",
                        {"Value": Expression("Join", ["", [reference, "/*"]])},
                    ],
                ),
                Expression("Join", ["", [reference, "/*"]]),
            ):
                assert same(different, arn, reference=callback) is False
            comparison.stack_inputs[producer][2]["AWS::Partition"] = "aws-cn"
            assert same(reference, arn, reference=callback) is False
            assert same(reference, arn.replace("aws:", "aws-cn:"), reference=callback)


if __name__ == "__main__":
    unittest.main()
