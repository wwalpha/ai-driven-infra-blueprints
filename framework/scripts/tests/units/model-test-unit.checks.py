#!/usr/bin/env python3
"""Focused Model Test identifier and report behavior."""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from design.layout import confirmed_display_name
from model.adapters.aws import AcquisitionError, Unresolved, service_module
from model.audit import (
    definitions,
    dependencies,
    disambiguate_names,
    embed_adapter,
    generate,
    reference_rows,
)
from model.projection import resource_display_rows
from model.reference_values import ReferenceValue, confirmed
from model.render import display_name
from model.sources import load_model
from support.model_sources import write_model
from utils.input_cache import input_scope

from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


class MacieLookupTests(unittest.TestCase):
    def test_job_lookup(self):
        adapter = service_module("macie")
        resource = Mock()
        resource.value.return_value = "fixture-job"
        ctx = Mock()
        ctx.call.return_value = {"name": "fixture-job"}
        resource.current.return_value = "confirmed-id"
        adapter.fetch(ctx, resource, "job")
        ctx.pages.assert_not_called()
        ctx.call.assert_called_once_with(
            "macie2", "describe_classification_job", jobId="confirmed-id"
        )

        resource.current.return_value = None
        ctx.reset_mock()
        ctx.pages.return_value = {
            "items": [{"name": "fixture-job", "jobId": "found-id"}]
        }
        adapter.fetch(ctx, resource, "job")
        ctx.pages.assert_called_once_with(
            "macie2",
            "list_classification_jobs",
            filterCriteria={
                "includes": [
                    {"key": "name", "comparator": "EQ", "values": ["fixture-job"]}
                ]
            },
        )
        ctx.call.assert_called_once_with(
            "macie2", "describe_classification_job", jobId="found-id"
        )
        for items, error in [
            ([], AcquisitionError),
            (
                [
                    {"name": "fixture-job", "jobId": "a"},
                    {"name": "fixture-job", "jobId": "b"},
                ],
                Unresolved,
            ),
        ]:
            with self.subTest(items=items):
                ctx.reset_mock()
                ctx.pages.return_value = {"items": items}
                with self.assertRaises(error):
                    adapter.fetch(ctx, resource, "job")
                ctx.call.assert_not_called()


class EmbeddedImportTests(unittest.TestCase):
    def test_imports_and_aliases(self):
        engine = "def policy(value): return value\nMISSING = 3\n"
        source = "from model.adapters.aws import policy as normalize, MISSING\nimport model.adapters.aws as aws\nresult = (normalize(aws.MISSING), MISSING)\n"
        transformed = embed_adapter(source, "sqs", engine)
        comparison = SimpleNamespace(policy=lambda value: value, MISSING=3)
        with patch.dict(sys.modules, {"audit_comparison": comparison}):
            namespace = {"_audit_comparison": comparison}
            exec(transformed, namespace)
        self.assertEqual(namespace["result"], (3, 3))
        self.assertIs(namespace["aws"], comparison)

    def test_unknown_dependencies_fail(self):
        for source in (
            "import model.unknown as x",
            "from model.adapters.aws import absent",
            "from model.importing.sdk_inventory import absent",
        ):
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(ValueError, "sqs: model.*unresolved dependency"),
            ):
                embed_adapter(source, "sqs", "MISSING = 1")

    def test_route53_definitions_copied(self):
        path = Path(__file__).resolve().parents[2] / "model/importing/sdk_inventory.py"
        source = definitions(
            path, ["identifier", "route53_pages", "route53_projection"]
        )
        self.assertEqual(
            {node.name for node in ast.parse(source).body},
            {"identifier", "route53_pages", "route53_projection"},
        )
        self.assertIn(
            "from audit_comparison import route53_pages as pages",
            embed_adapter(
                "from model.importing.sdk_inventory import route53_pages as pages\n",
                "route53",
                source,
            ),
        )


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="audit-reference-unit-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "project.json").write_text(
            json.dumps(
                {
                    "projectName": "fixture",
                    "targets": [
                        {
                            "environment": "dev",
                            "alias": "cde",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.consumer = self.model(
            "EC2.FlowLog",
            "EC2_FlowLog_001",
            {
                "Id": "fl-fixture",
                "LogGroupName": self.ref("Logs_LogGroup_001", "LogGroupName"),
            },
        )
        self.producer = self.model(
            "Logs.LogGroup",
            "Logs_LogGroup_001",
            {
                "LogGroupName": "/aws/vpc/flowlogs/fixture",
            },
        )
        self.save()

    @staticmethod
    def ref(logical, attribute):
        return {"$modelRef": {"logicalId": logical, "attribute": attribute}}

    @staticmethod
    def model(kind, logical, rows):
        values = {
            "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
            "desired.resource.001.resourceType": kind,
            "desired.resource.001.logicalId": logical,
            "desired.resource.001.anchor": "fixture",
            "desired.resource.001.cfn-logicalId": "fixture-" + logical.replace("_", ""),
        }
        for index, (prop, value) in enumerate(rows.items(), 1):
            prefix = f"desired.row.001-{index:03d}."
            values.update(
                {
                    prefix + "property": kind + "." + prop,
                    prefix + "value": "`"
                    + (value if isinstance(value, str) else json.dumps(value))
                    + "`",
                    prefix + "comment": "fixture",
                }
            )
        return values

    def save(self):
        for service, values in [
            ("vpc", self.consumer),
            ("cloudwatch-logs", self.producer),
        ]:
            write_model(self.root / "model/dev/cde" / (service + ".properties"), values)

    def snapshot(self):
        source = generate(self.root, "dev", "cde", "vpc")[0]
        assignment = ast.parse(source).body[1]
        return json.loads(ast.literal_eval(assignment.value.args[0]))

    def cli(self, command, **kwargs):
        if command[1] == "sts":
            value = {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/offline",
            }
        else:
            value = {
                "FlowLogs": []
                if self.missing
                else [
                    {
                        "FlowLogId": "fl-fixture",
                        "LogGroupName": self.actual,
                        "Tags": [{"Key": "/aws/vpc/flowlogs/fixture"}],
                    }
                ]
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    def result(self, snapshot):
        self.actual, self.missing = "/aws/vpc/flowlogs/fixture", False
        return [
            item
            for item in audit.audit(snapshot, cli_runner=self.cli)[2]
            if item["propertiesKey"] == "EC2.FlowLog.LogGroupName"
        ][0]

    def test_boolean_literal_comparisons(self):
        self.consumer["desired.row.001-002.value"] = "`False`"
        self.save()
        snapshot = self.snapshot()
        prop = "EC2.FlowLog.LogGroupName"
        snapshot["schemas"][prop] = {"type": "boolean"}
        for raw, actual, status in [
            ("False", False, "match"),
            ("True", True, "match"),
            ("True", False, "difference"),
            ("False", True, "difference"),
            ("yes", False, "design_unresolved"),
        ]:
            with self.subTest(raw=raw, actual=actual):
                snapshot["models"]["dev/cde/vpc"]["desired.row.001-002.value"] = (
                    f"`{raw}`"
                )
                self.actual, self.missing = actual, False
                item = next(
                    item
                    for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                    if item["propertiesKey"] == prop
                )
                self.assertEqual(item["status"], status, item)
                if status != "design_unresolved":
                    self.assertIs(item["designValue"], raw == "True")
                    self.assertIs(item["awsValue"], actual)

    def test_resolved_dependency_and_comparison(self):
        snapshot = self.snapshot()
        self.assertNotIn("dev/cde/cloudwatch-logs", snapshot["models"])
        self.assertEqual(
            snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]["value"],
            "/aws/vpc/flowlogs/fixture",
        )
        item = self.result(snapshot)
        self.assertEqual(item["status"], "match", item)
        self.assertEqual(item["designValue"], "/aws/vpc/flowlogs/fixture")

    def test_invalid_projection_is_rejected_for_reference_and_literal(self):
        self.consumer["desired.row.001-002.valueShape"] = "projection"
        for reference in (True, False):
            with self.subTest(reference=reference):
                if not reference:
                    self.consumer["desired.row.001-002.value"] = (
                        "`/aws/vpc/flowlogs/fixture`"
                    )
                self.save()
                item = self.result(self.snapshot())
                self.assertEqual(item["status"], "design_unresolved", item)

    def test_resolved_value_obeys_parser_schema(self):
        for reference in (True, False):
            with self.subTest(reference=reference):
                if not reference:
                    self.consumer["desired.row.001-002.value"] = (
                        "`/aws/vpc/flowlogs/fixture`"
                    )
                    self.save()
                snapshot = self.snapshot()
                snapshot["schemas"]["EC2.FlowLog.LogGroupName"] = {"type": "integer"}
                item = self.result(snapshot)
                self.assertEqual(item["status"], "design_unresolved", item)

    def test_resolved_scalar_preserves_native_type(self):
        snapshot = self.snapshot()
        snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]["value"] = 7
        item = self.result(snapshot)
        self.assertEqual(item["status"], "design_unresolved", item)

    def test_resolved_native_containers_are_validated_before_serialization(self):
        snapshot = self.snapshot()
        resolved = snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]
        for value in (
            ["/aws/vpc/flowlogs/fixture"],
            {"name": "fixture"},
            7,
            True,
            None,
        ):
            with self.subTest(value=value):
                resolved["value"] = value
                for actual in ("/aws/vpc/flowlogs/fixture", json.dumps(value)):
                    self.actual, self.missing = actual, False
                    item = next(
                        item
                        for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                        if item["propertiesKey"].endswith("LogGroupName")
                    )
                    self.assertEqual(item["status"], "design_unresolved", item)
                    self.assertIn("must be string", item["reason"])

    def test_resolved_number_and_boolean_type_mismatch(self):
        snapshot = self.snapshot()
        resolved = snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]
        for kind, value in (("number", True), ("boolean", 1)):
            with self.subTest(kind=kind):
                snapshot["schemas"]["EC2.FlowLog.LogGroupName"] = {"type": kind}
                resolved["value"] = value
                item = self.result(snapshot)
                self.assertEqual(item["status"], "design_unresolved", item)
                self.assertIn("must be " + kind, item["reason"])

    def test_resolved_native_array_and_object(self):
        snapshot = self.snapshot()
        m = audit.engine(snapshot)
        resource = (
            m.Context(m.ROOT, snapshot["target"])
            .model(m.ROOT / "model/dev/cde/vpc.properties")
            .resources[0]
        )
        row = resource.rows[1][1]
        resolved = snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]
        for kind, value in (("array", ["value"]), ("object", {"key": "value"})):
            with self.subTest(kind=kind):
                snapshot["schemas"][row["property"]] = {"type": kind}
                resolved["value"] = value
                self.assertEqual(resource.parse(row), value)

    def test_valid_containers_survive_acquisition_failure(self):
        snapshot = self.snapshot()
        resolved = snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]
        for kind, value in (("array", ["value"]), ("object", {"key": "value"})):
            with self.subTest(kind=kind):
                snapshot["schemas"]["EC2.FlowLog.LogGroupName"] = {"type": kind}
                resolved["value"] = value
                self.missing, self.actual = True, None
                item = next(
                    item
                    for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                    if item["propertiesKey"].endswith("LogGroupName")
                )
                self.assertEqual(item["status"], "resource_missing", item)
                self.assertEqual(item["designValue"], value)

    def test_boolean_is_not_an_integer(self):
        for reference in (True, False):
            with self.subTest(reference=reference):
                if not reference:
                    self.consumer["desired.row.001-002.value"] = "`true`"
                    self.save()
                snapshot = self.snapshot()
                snapshot["schemas"]["EC2.FlowLog.LogGroupName"] = {"type": "integer"}
                if reference:
                    snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]["value"] = True
                self.actual, self.missing = True, False
                item = next(
                    item
                    for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                    if item["propertiesKey"].endswith("LogGroupName")
                )
                self.assertEqual(item["status"], "design_unresolved", item)

    def test_projection_reference_matches_literal(self):
        self.consumer["desired.row.001-002.property"] = "EC2.FlowLog.Tags[].Key"
        self.consumer["desired.row.001-002.valueShape"] = "projection"
        self.consumer.update(
            {
                "desired.row.001-003.property": "EC2.FlowLog.Tags[].Value",
                "desired.row.001-003.value": '`["example"]`',
                "desired.row.001-003.comment": "fixture",
                "desired.row.001-003.valueShape": "projection",
            }
        )
        for reference in (True, False):
            with self.subTest(reference=reference):
                value = (
                    self.ref("Logs_LogGroup_001", "LogGroupName")
                    if reference
                    else "/aws/vpc/flowlogs/fixture"
                )
                self.consumer["desired.row.001-002.value"] = (
                    "`" + json.dumps([value]) + "`"
                )
                self.save()
                self.actual, self.missing = "/aws/vpc/flowlogs/fixture", False
                snapshot = self.snapshot()
                for field in ("Key", "Value"):
                    snapshot["mappings"]["vpc"]["properties"][
                        "EC2.FlowLog.Tags[]." + field
                    ]["field"].update(
                        getter="base", classification="supported", reason=""
                    )
                item = next(
                    item
                    for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                    if item["propertiesKey"].endswith("Tags[].Key")
                )
                self.assertEqual(item["status"], "match", item)
                self.assertEqual(item["designValue"], ["/aws/vpc/flowlogs/fixture"])
                if reference:
                    self.missing = True
                    item = next(
                        item
                        for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                        if item["propertiesKey"].endswith("Tags[].Key")
                    )
                    self.assertEqual(item["status"], "resource_missing", item)
                    self.assertEqual(item["designValue"], ["/aws/vpc/flowlogs/fixture"])

    def test_acquisition_failure_keeps_resolved_scalar(self):
        snapshot = self.snapshot()
        self.missing, self.actual = True, None
        item = [
            item
            for item in audit.audit(snapshot, cli_runner=self.cli)[2]
            if item["propertiesKey"] == "EC2.FlowLog.LogGroupName"
        ][0]
        self.assertEqual(item["reason"], "ResourceNotFound")
        self.assertEqual(item["status"], "resource_missing")
        self.assertEqual(item["designValue"], "/aws/vpc/flowlogs/fixture")

    def test_invalid_resolved_values_preserve_acquisition_failure(self):
        snapshot = self.snapshot()
        resolved = snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]
        for value, failure in (
            (["/aws/vpc/flowlogs/fixture"], "ResourceNotFound"),
            ({"name": "fixture"}, "AccessDenied"),
        ):
            with self.subTest(value=value, failure=failure):
                resolved["value"] = value
                self.missing, self.actual = True, None
                calls = Mock(side_effect=self.cli)
                if failure == "AccessDenied":
                    calls.side_effect = [
                        self.cli(["aws", "sts"]),
                        subprocess.CompletedProcess(
                            [],
                            1,
                            "",
                            "An error occurred (AccessDenied) when calling Mock: hidden",
                        ),
                    ]
                item = next(
                    item
                    for item in audit.audit(snapshot, cli_runner=calls)[2]
                    if item["propertiesKey"].endswith("LogGroupName")
                )
                self.assertEqual(
                    item["status"],
                    "resource_missing"
                    if failure == "ResourceNotFound"
                    else "acquisition_failed",
                )
                self.assertIn("must be string", item["reason"])
                self.assertIn(failure, item["reason"])
                self.assertIsNone(item["designValue"])
                self.assertEqual(
                    sum(
                        call.args[0][1:3] == ["ec2", "describe-flow-logs"]
                        for call in calls.call_args_list
                    ),
                    1,
                )

    def test_difference_and_account_failure(self):
        snapshot = self.snapshot()
        self.missing, self.actual = False, "/different"
        records = audit.audit(snapshot, cli_runner=self.cli)[2]
        item = next(
            item for item in records if item["propertiesKey"].endswith(".LogGroupName")
        )
        self.assertEqual(item["status"], "difference", item)
        self.assertEqual(item["designValue"], "/aws/vpc/flowlogs/fixture")
        self.assertEqual(item["awsValue"], "/different")
        configured = {
            **snapshot,
            "target": {**snapshot["target"], "awsProfile": "expected"},
        }
        records = audit.audit(
            configured,
            profile="wrong",
            cli_runner=Mock(side_effect=AssertionError("AWS forbidden")),
        )[2]
        self.assertEqual(records[-1]["designValue"], "/aws/vpc/flowlogs/fixture")

    def test_observed_and_regeneration_hash(self):
        initial = self.snapshot()
        self.producer["desired.row.001-001.value"] = "`UNSET`"
        self.producer["observed.row.001-001.value"] = "`/aws/vpc/flowlogs/fixture`"
        self.save()
        self.assertEqual(self.result(self.snapshot())["status"], "match")
        self.producer["desired.row.001-001.value"] = "`/changed`"
        self.producer["observed.row.001-001.value"] = "`/changed`"
        self.save()
        changed = self.snapshot()
        self.assertNotEqual(initial["modelHash"], changed["modelHash"])
        self.assertEqual(
            changed["referenceRows"]["dev/cde/vpc"]["001-002"]["value"], "/changed"
        )
        self.assertEqual(changed, self.snapshot())

    def test_missing_ambiguous_invalid_and_drift(self):
        cases = [
            (self.ref("Missing_001", "LogGroupName"), "MODEL_REF_TARGET_MISSING"),
            (self.ref("Logs_LogGroup_001", "Missing"), "MODEL_REF_INVALID_ATTRIBUTE"),
            (
                {"$modelRef": {"logicalId": "Logs_LogGroup_001"}},
                "MODEL_REF_INVALID_SYNTAX",
            ),
            (
                {"$modelRef": {"logicalId": 42, "attribute": "LogGroupName"}},
                "MODEL_REF_INVALID_SYNTAX",
            ),
            (
                {**self.ref("Logs_LogGroup_001", "LogGroupName"), "extra": True},
                "MODEL_REF_INVALID_SYNTAX",
            ),
        ]
        for value, code in cases:
            with self.subTest(code=code, value=value):
                self.consumer["desired.row.001-002.value"] = (
                    "`" + json.dumps(value) + "`"
                )
                self.save()
                item = self.result(self.snapshot())
                self.assertEqual(item["status"], "design_unresolved", item)
                self.assertIsNone(item["designValue"])
                self.assertIn(code, item["reason"])
                self.assertNotIn("NameError", item["reason"])
        self.consumer["desired.row.001-002.value"] = (
            "`" + json.dumps(self.ref("Logs_LogGroup_001", "LogGroupName")) + "`"
        )
        self.producer["observed.row.001-001.value"] = "`/drifted`"
        self.save()
        item = self.result(self.snapshot())
        self.assertIn("Desired and Observed differ", item["reason"])
        self.producer.pop("observed.row.001-001.value")
        duplicate = self.model(
            "Logs.LogGroup", "Logs_LogGroup_001", {"LogGroupName": "/other"}
        )
        write_model(self.root / "model/dev/cde/duplicate.properties", duplicate)
        item = self.result(self.snapshot())
        self.assertIn("MODEL_REF_TARGET_AMBIGUOUS", item["reason"])

    def test_pending_logical_only_and_invalid_type(self):
        for fields, expected in [
            (
                {"CidrBlock": "10.0.0.0/16", "VpcId": self.ref("EC2_VPC_001", "VpcId")},
                "pending_deploy",
            ),
            ({"CidrBlock": "10.0.0.0/16"}, "logical_only"),
        ]:
            with self.subTest(expected=expected):
                self.producer = self.model("EC2.VPC", "EC2_VPC_001", fields)
                if expected == "pending_deploy":
                    self.producer["observed.row.001-002.value"] = "`PENDING_DEPLOY`"
                self.consumer = self.model(
                    "EC2.Subnet",
                    "EC2_Subnet_001",
                    {
                        "VpcId": self.ref("EC2_VPC_001", "VpcId"),
                    },
                )
                self.save()
                snapshot = self.snapshot()
                row = snapshot["referenceRows"]["dev/cde/vpc"]["001-001"]
                self.assertEqual(row["status"], expected, row)
                self.assertIsNone(row["value"])
                self.missing, self.actual = False, None
                item = audit.audit(snapshot, cli_runner=self.cli)[2][0]
                self.assertEqual(item["status"], "design_unresolved", item)
                self.assertIn("Design reference unresolved", item["reason"])
        self.consumer = self.model(
            "EC2.VPC",
            "EC2_VPC_001",
            {
                "CidrBlock": self.ref("Logs_LogGroup_001", "RetentionInDays"),
            },
        )
        self.producer = self.model(
            "Logs.LogGroup",
            "Logs_LogGroup_001",
            {
                "LogGroupName": "/fixture",
                "RetentionInDays": 7,
            },
        )
        self.save()
        row = self.snapshot()["referenceRows"]["dev/cde/vpc"]["001-001"]
        self.assertEqual(row["status"], "unresolved", row)
        self.assertIn("MODEL_REF_TYPE_MISMATCH", row["reason"])

    @input_scope
    def test_nested_native_values_and_stable_row_ids(self):
        # Resolution/contract behavior is covered above; isolate projection's native types.
        document = {
            "items": [
                self.ref("Logs_LogGroup_001", "LogGroupName"),
                {"nested": self.ref("Logs_LogGroup_001", "LogGroupName")},
            ],
            "ordinary": {"RefLike": "unchanged"},
        }
        self.consumer["desired.row.001-002.value"] = "`" + json.dumps(document) + "`"
        self.consumer.update(
            {
                key.replace("001-002", "001-003"): value
                for key, value in list(self.consumer.items())
                if "001-002" in key
            }
        )
        self.save()
        data = load_model(self.root / "model/dev/cde/vpc.properties")
        for native in ("name", 7, True, [1, False], {"key": [2]}):
            with (
                self.subTest(native=native),
                patch(
                    "model.projection.reference_value",
                    return_value=ReferenceValue("resolved", native),
                ),
            ):
                rows = reference_rows(self.root, {"dev/cde/vpc": data})["dev/cde/vpc"]
                self.assertEqual(set(rows), {"001-002", "001-003"})
                self.assertEqual(
                    rows["001-002"]["value"],
                    {
                        "items": [native, {"nested": native}],
                        "ordinary": {"RefLike": "unchanged"},
                    },
                )
                self.assertIs(type(rows["001-003"]["value"]["items"][0]), type(native))

    def test_combined_failures_and_missing_snapshot_guard(self):
        self.consumer["desired.row.001-002.value"] = (
            "`" + json.dumps(self.ref("Missing_001", "LogGroupName")) + "`"
        )
        self.save()
        snapshot = self.snapshot()
        self.missing, self.actual = True, None
        item = audit.audit(snapshot, cli_runner=self.cli)[2][-1]
        self.assertIn("ResourceNotFound", item["reason"])
        self.assertEqual(item["status"], "resource_missing")
        self.assertIn("MODEL_REF_TARGET_MISSING", item["reason"])
        self.assertIsNone(item["designValue"])
        snapshot["referenceRows"] = {}
        self.assertIn(
            "missing generated row resolution", self.result(snapshot)["reason"]
        )

    def test_producer_reference_chain_is_not_a_confirmed_value(self):
        self.producer["desired.row.001-001.value"] = (
            "`" + json.dumps(self.ref("Logs_LogGroup_001", "LogGroupName")) + "`"
        )
        self.save()
        snapshot = self.snapshot()
        row = snapshot["referenceRows"]["dev/cde/vpc"]["001-002"]
        self.assertEqual(row["status"], "unresolved", row)
        self.assertIsNone(row["value"])
        item = self.result(snapshot)
        self.assertEqual(item["status"], "design_unresolved", item)
        self.assertIn("no confirmed desired or observed value", item["reason"])
        row.update(
            status="resolved", value=self.ref("Logs_LogGroup_001", "LogGroupName")
        )
        self.assertIn(
            "generated value still contains a Design reference",
            self.result(snapshot)["reason"],
        )

    @input_scope
    def test_dependency_cycles_duplicates_and_selected_resources(self):
        self.producer["desired.row.001-002.property"] = "Logs.LogGroup.KmsKeyId"
        self.producer["desired.row.001-002.value"] = (
            "`" + json.dumps(self.ref("EC2_FlowLog_001", "Id")) + "`"
        )
        self.producer["desired.row.001-002.comment"] = "fixture"
        unrelated = self.model(
            "Logs.LogGroup", "Logs_LogGroup_002", {"LogGroupName": "/unrelated"}
        )
        self.producer.update(
            {
                key.replace("001.", "002.").replace("001-", "002-"): value
                for key, value in unrelated.items()
                if not key.startswith("desired.service.")
            }
        )
        self.producer["desired.service.identity.lastAllocated"] = json.dumps(
            {"Logs.LogGroup": 2}
        )
        self.save()
        data = dependencies(self.root, {}, self.root / "model/dev/cde/vpc.properties")
        self.assertEqual(set(data), {"dev/cde/vpc", "dev/cde/cloudwatch-logs"})
        self.assertNotIn(
            "desired.resource.002.logicalId", data["dev/cde/cloudwatch-logs"].values
        )

    def test_no_reference_json_and_sensitive_report(self):
        for raw in (
            "`ordinary`",
            '`{"ordinary":[1,true]}`',
            '`[1,{"ordinary":false}]`',
        ):
            self.consumer["desired.row.001-002.value"] = raw
            self.save()
            snapshot = self.snapshot()
            self.assertEqual(snapshot["referenceRows"], {})
            self.missing, self.actual = False, raw.strip("`")
            records = audit.audit(snapshot, cli_runner=self.cli)[2]
            self.assertEqual(records[-1]["status"], "match", records[-1])
        snapshot = self.snapshot()
        text, _ = audit.report(
            snapshot,
            None,
            "account",
            [
                {
                    "resource": "EC2_FlowLog_001",
                    "propertiesKey": "Example.Resource.Secret",
                    "status": "acquisition_failed",
                    "reason": "ResourceNotFound",
                    "designValue": {"nested": "never-print"},
                    "awsValue": None,
                }
            ],
            datetime.now(timezone.utc),
        )
        self.assertNotIn("never-print", text)

    def test_resolved_sensitive_reference_is_masked_on_success_and_failure(self):
        self.producer["desired.row.001-001.value"] = "`never-print`"
        self.save()
        snapshot = self.snapshot()
        m = audit.engine(snapshot)
        m.service_module("vpc").sensitive = lambda prop: prop.endswith(".LogGroupName")
        for missing in (False, True):
            with (
                self.subTest(missing=missing),
                patch.object(audit, "engine", return_value=m),
            ):
                self.missing, self.actual = missing, "never-print"
                records = audit.audit(snapshot, cli_runner=self.cli)[2]
                self.assertEqual(records[-1]["designValue"], "[REDACTED]")
                text, _ = audit.report(
                    snapshot, None, "account", records, datetime.now(timezone.utc)
                )
                self.assertNotIn("never-print", text)


class CloudTrailArrayTests(unittest.TestCase):
    setUp = ReferenceTests.setUp
    model = staticmethod(ReferenceTests.model)
    ref = staticmethod(ReferenceTests.ref)
    save = ReferenceTests.save

    def test_reference_array_membership(self):
        arn = "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture"
        producer = self.model(
            "Lambda.Function", "Lambda_Function_001", {"FunctionName": "fixture"}
        )
        write_model(self.root / "model/dev/cde/lambda.properties", producer)
        values = self.model("CloudTrail.Trail", "CloudTrail_Trail_001", {})
        fields = [
            ("TrailName", "`fixture`"),
            ("EventSelectors[].IncludeManagementEvents", "`true`"),
            ("EventSelectors[].ReadWriteType", "`All`"),
            ("EventSelectors[].DataResources[].Type", "`AWS::Lambda::Function`"),
            (
                "EventSelectors[].DataResources[].Values",
                "`" + json.dumps([self.ref("Lambda_Function_001", "Arn")]) + "`",
            ),
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3"]`'),
            ("EventSelectors[].IncludeManagementEvents", "`false`"),
            ("EventSelectors[].ReadWriteType", "`ReadOnly`"),
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3:::other/"]`'),
        ]
        for index, (prop, value) in enumerate(fields, 1):
            prefix = f"desired.row.001-{index:03d}."
            values.update(
                {
                    prefix + "property": "CloudTrail.Trail." + prop,
                    prefix + "value": value,
                    prefix + "comment": "fixture",
                }
            )
        path = self.root / "model/dev/cde/cloudtrail.properties"
        write_model(path, values)
        selectors = [
            {
                "IncludeManagementEvents": True,
                "ReadWriteType": "All",
                "DataResources": [
                    {"Type": "AWS::Lambda::Function", "Values": [arn]},
                    {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3"]},
                ],
            },
            {
                "IncludeManagementEvents": False,
                "ReadWriteType": "ReadOnly",
                "DataResources": [
                    {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3:::other/"]},
                ],
            },
        ]
        source = generate(self.root, "dev", "cde", "cloudtrail")[0]
        snapshot = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        self.assertEqual(
            snapshot["referenceRows"]["dev/cde/cloudtrail"]["001-005"]["status"],
            "resolved",
        )

        def records(response):
            cli = Mock(
                side_effect=[
                    subprocess.CompletedProcess(
                        [],
                        0,
                        json.dumps(
                            {
                                "Account": "123456789012",
                                "Arn": "arn:aws:iam::123456789012:user/offline",
                            }
                        ),
                        "",
                    ),
                    subprocess.CompletedProcess(
                        [], 0, json.dumps({"Trail": {"Name": "fixture"}}), ""
                    ),
                    subprocess.CompletedProcess(
                        [], 0, json.dumps({"EventSelectors": response}), ""
                    ),
                ]
            )
            return audit.audit(snapshot, cli_runner=cli)[2]

        for response, prop, expected in [
            (selectors, "ReadWriteType", "match"),
            (
                [dict(selectors[0], ReadWriteType="WriteOnly"), selectors[1]],
                "ReadWriteType",
                "difference",
            ),
            (
                [
                    dict(
                        selectors[0],
                        DataResources=[
                            dict(
                                selectors[0]["DataResources"][0],
                                Values=[arn + "-other"],
                            ),
                            selectors[0]["DataResources"][1],
                        ],
                    ),
                    selectors[1],
                ],
                "DataResources[].Values",
                "difference",
            ),
            (
                [
                    dict(
                        selectors[0], DataResources=selectors[0]["DataResources"][::-1]
                    ),
                    selectors[1],
                ],
                "DataResources[].Values",
                "difference",
            ),
        ]:
            with self.subTest(prop=prop, expected=expected):
                result = next(
                    r for r in records(response) if r["propertiesKey"].endswith(prop)
                )
                self.assertEqual(result["status"], expected, result)
        self.assertTrue(
            all(
                r["status"] == "match"
                for r in records(selectors)
                if "EventSelectors[]" in r["propertiesKey"]
            )
        )

        folder = self.root / "standalone"
        folder.mkdir()
        script = folder / "audit.py"
        script.write_text(source, encoding="utf-8")
        fake = folder / "aws"
        fake.write_text(
            "#!"
            + sys.executable
            + "\nimport json, sys\napi = sys.argv[1:3]\nprint(json.dumps({ 'Account': '123456789012', 'Arn': 'arn:aws:iam::123456789012:user/offline' } if api[0] == 'sts' else { 'Trail': {'Name': 'fixture'} } if api[1] == 'get-trail' else "
            + repr({"EventSelectors": selectors})
            + "))\n",
            encoding="utf-8",
        )
        fake.chmod(0o700)
        process = subprocess.run(
            [sys.executable, "-I", "-B", str(script)],
            cwd=folder,
            env={**os.environ, "PATH": str(folder)},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

        for missing in ("004", "005"):
            incomplete = dict(values)
            for field in ("property", "value", "comment"):
                incomplete.pop(f"desired.row.001-{missing}.{field}")
            write_model(path, incomplete)
            incomplete_source = generate(self.root, "dev", "cde", "cloudtrail")[0]
            snapshot = json.loads(
                ast.literal_eval(ast.parse(incomplete_source).body[1].value.args[0])
            )
            result = next(
                r
                for r in records(selectors)
                if r["propertiesKey"].endswith("ReadWriteType")
            )
            self.assertEqual(result["status"], "design_unresolved", result)

        values["desired.row.001-005.value"] = (
            "`" + json.dumps([self.ref("Missing_001", "Arn")]) + "`"
        )
        write_model(path, values)
        source = generate(self.root, "dev", "cde", "cloudtrail")[0]
        snapshot = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        result = next(
            r
            for r in records(selectors)
            if r["propertiesKey"].endswith("DataResources[].Values")
        )
        self.assertNotEqual(result["status"], "match", result)

    def test_event_selector_membership(self):
        fields = [
            ("TrailName", "`fixture`"),
            ("EventSelectors[].IncludeManagementEvents", "`true`"),
            ("EventSelectors[].ReadWriteType", "`All`"),
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3"]`'),
            ("EventSelectors[].DataResources[].Type", "`AWS::Lambda::Function`"),
            (
                "EventSelectors[].DataResources[].Values",
                '`["arn:aws:lambda:ap-northeast-1:123456789012:function:a"]`',
            ),
            ("EventSelectors[].IncludeManagementEvents", "`false`"),
            ("EventSelectors[].ReadWriteType", "`ReadOnly`"),
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3:::other/"]`'),
        ]
        values = self.model("CloudTrail.Trail", "CloudTrail_Trail_001", {})
        for index, (prop, value) in enumerate(fields, 1):
            prefix = f"desired.row.001-{index:03d}."
            values.update(
                {
                    prefix + "property": "CloudTrail.Trail." + prop,
                    prefix + "value": value,
                    prefix + "comment": "fixture",
                }
            )
        path = self.root / "model/dev/cde/cloudtrail.properties"
        write_model(path, values)
        selectors = [
            {
                "IncludeManagementEvents": True,
                "ReadWriteType": "All",
                "DataResources": [
                    {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3"]},
                    {
                        "Type": "AWS::Lambda::Function",
                        "Values": [
                            "arn:aws:lambda:ap-northeast-1:123456789012:function:a"
                        ],
                    },
                ],
            },
            {
                "IncludeManagementEvents": False,
                "ReadWriteType": "ReadOnly",
                "DataResources": [
                    {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3:::other/"]},
                ],
            },
        ]
        source = generate(self.root, "dev", "cde", "cloudtrail")[0]
        snapshot = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        for response, expected, data_expected in [
            (selectors, "match", "match"),
            (
                [dict(selectors[0], ReadWriteType="ReadOnly"), selectors[1]],
                "difference",
                "match",
            ),
            (selectors[::-1], "difference", "difference"),
            (
                [
                    dict(
                        selectors[0], DataResources=selectors[0]["DataResources"][::-1]
                    ),
                    selectors[1],
                ],
                "match",
                "difference",
            ),
        ]:
            with self.subTest(expected=expected, response=response):
                cli = Mock(
                    side_effect=[
                        subprocess.CompletedProcess(
                            [],
                            0,
                            json.dumps(
                                {
                                    "Account": "123456789012",
                                    "Arn": "arn:aws:iam::123456789012:user/offline",
                                }
                            ),
                            "",
                        ),
                        subprocess.CompletedProcess(
                            [], 0, json.dumps({"Trail": {"Name": "fixture"}}), ""
                        ),
                        subprocess.CompletedProcess(
                            [], 0, json.dumps({"EventSelectors": response}), ""
                        ),
                    ]
                )
                records = audit.audit(snapshot, cli_runner=cli)[2]
                result = next(
                    item
                    for item in records
                    if item["propertiesKey"]
                    == "CloudTrail.Trail.EventSelectors[].ReadWriteType"
                )
                self.assertEqual(result["status"], expected, result)
                data = next(
                    item
                    for item in records
                    if item["propertiesKey"]
                    == "CloudTrail.Trail.EventSelectors[].DataResources[].Type"
                )
                self.assertEqual(data["status"], data_expected, data)
                if expected == data_expected == "match":
                    self.assertTrue(
                        all(
                            item["status"] == "match"
                            for item in records
                            if "EventSelectors[]" in item["propertiesKey"]
                        ),
                        records,
                    )

        prepared = [
            (
                f"001-{index:03d}",
                {"property": "CloudTrail.Trail." + prop, "value": value},
            )
            for index, (prop, value) in enumerate(fields, 1)
        ]
        prepared[4][1]["property"] = (
            "CloudTrail.Trail.EventSelectors[1].DataResources[1].Values[1]"
        )
        with patch("model.audit.cloudtrail_rows", return_value=prepared):
            source = generate(self.root, "dev", "cde", "cloudtrail")[0]
        rejected = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        self.assertEqual(
            rejected["cloudtrailIndexedRows"]["001"]["001-005"],
            "CloudTrail.Trail.EventSelectors[].DataResources[].Values",
        )

        values.pop("desired.row.001-011.property")
        values.pop("desired.row.001-011.value")
        values.pop("desired.row.001-011.comment")
        write_model(path, values)
        source = generate(self.root, "dev", "cde", "cloudtrail")[0]
        snapshot = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        self.assertEqual(
            snapshot["cloudtrailIndexedRows"]["001"]["001-003"],
            "CloudTrail.Trail.EventSelectors[].ReadWriteType",
        )
        cli = Mock(
            side_effect=[
                subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps(
                        {
                            "Account": "123456789012",
                            "Arn": "arn:aws:iam::123456789012:user/offline",
                        }
                    ),
                    "",
                ),
                subprocess.CompletedProcess(
                    [], 0, json.dumps({"Trail": {"Name": "fixture"}}), ""
                ),
                subprocess.CompletedProcess(
                    [], 0, json.dumps({"EventSelectors": selectors}), ""
                ),
            ]
        )
        records = audit.audit(snapshot, cli_runner=cli)[2]
        result = next(
            item
            for item in records
            if item["propertiesKey"]
            == "CloudTrail.Trail.EventSelectors[].ReadWriteType"
        )
        self.assertEqual(result["status"], "design_unresolved", result)


class IdentifierTests(unittest.TestCase):
    def setUp(self):
        self.m = SimpleNamespace(
            ROOT=Path("/snapshot"),
            catalog_outputs=lambda root, kind: [kind + ".VpcId"],
            literal=lambda raw: raw.strip("`"),
            confirmed_display_name=confirmed_display_name,
            confirmed=confirmed,
            normalize=lambda ctx, value, norm: int(value)
            if norm == "number"
            else value,
            stable=lambda value: (type(value).__name__, value),
            redacted=lambda value: value,
            AcquisitionError=RuntimeError,
            Unresolved=ValueError,
        )
        self.resource = SimpleNamespace(
            kind="EC2.VPC",
            rows_for=Mock(
                return_value=[
                    ("001-001", {"property": "EC2.VPC.VpcId", "value": "[VPC](#vpc)"})
                ]
            ),
            model=SimpleNamespace(
                values={"observed.row.001-001.value": "`vpc-123`"}, service="vpc"
            ),
            parse=Mock(side_effect=lambda row, norm: row["value"].strip("`")),
            module=SimpleNamespace(sensitive=lambda prop: False),
        )
        self.ctx = SimpleNamespace(
            comparison=lambda service: (
                None,
                {"EC2.VPC.VpcId": SimpleNamespace(field=SimpleNamespace(norm="typed"))},
            )
        )
        self.item = {
            "status": "identifier",
            "propertiesKey": "EC2.VPC.VpcId",
            "awsValue": "vpc-123",
            "designValue": ["[VPC](#vpc)"],
        }

    def result(self):
        return audit.identifier_result(self.m, self.ctx, self.resource, self.item)

    def test_match_and_difference(self):
        self.assertEqual(self.result()["status"], "match")
        self.assertEqual(self.result()["designValue"], "vpc-123")
        self.assertFalse(self.result().get("reason"))
        self.item["awsValue"] = "vpc-456"
        self.assertEqual(self.result()["status"], "difference")
        self.assertEqual(self.result()["reason"], "value differs")

    def test_missing_pending_ambiguous_and_invalid(self):
        for value in (
            None,
            "`PENDING_DEPLOY`",
            "`UNSET`",
            "`PENDING`",
            "`TODO`",
            "`N/A`",
            "`UNUSED`",
            "`unresolved`",
            "`${Thing}`",
            "[VPC](#vpc)",
            '`["vpc-1","vpc-2"]`',
        ):
            with self.subTest(value=value):
                self.resource.model.values["observed.row.001-001.value"] = value
                self.assertEqual(self.result()["status"], "design_unresolved")
        self.resource.rows_for.return_value *= 2
        self.assertEqual(self.result()["status"], "design_unresolved")

    def test_acquisition_and_normal_attributes_unchanged(self):
        for status in ("acquisition_failed", "unimplemented"):
            item = {**self.item, "status": status}
            result = audit.identifier_result(self.m, self.ctx, self.resource, item)
            self.assertEqual(result["status"], status)
            self.assertEqual(result["designValue"], "vpc-123")
        item = {**self.item, "status": "match", "propertiesKey": "EC2.VPC.CidrBlock"}
        self.assertIs(
            audit.identifier_result(self.m, self.ctx, self.resource, item), item
        )

    def test_numeric_normalization_and_sensitive(self):
        self.ctx.comparison = lambda service: (
            None,
            {"EC2.VPC.VpcId": SimpleNamespace(field=SimpleNamespace(norm="number"))},
        )
        self.resource.model.values["observed.row.001-001.value"] = "`42`"
        self.item["awsValue"] = 42
        self.resource.module.sensitive = lambda prop: True
        result = self.result()
        self.assertEqual(result["status"], "match")
        self.assertEqual(result["designValue"], "[REDACTED]")
        self.assertEqual(result["awsValue"], "[REDACTED]")

    def test_report_uses_design_for_every_result(self):
        snapshot = {
            "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
            "service": "vpc",
            "modelHash": "hash",
            "names": {},
        }
        for status, reason in (
            ("match", ""),
            ("difference", "value differs"),
            ("design_unresolved", "Design reference unresolved"),
            ("resource_missing", "ResourceNotFound"),
            ("acquisition_failed", "AccessDenied"),
        ):
            with self.subTest(status=status):
                item = {
                    **self.item,
                    "resource": "id",
                    "status": status,
                    "reason": reason,
                    "designValue": "vpc-123",
                }
                text, _ = audit.report(
                    snapshot, None, "account", [item], datetime.now(timezone.utc)
                )
                self.assertIn('  Design: "vpc-123"', text)
                self.assertIn('  AWS:    "vpc-123"', text)
                self.assertNotIn("  Model:", text)
                self.assertIn("Design SHA256: hash", text)
                self.assertNotIn("Model SHA256", text)
                if reason:
                    self.assertIn(reason, text)

    def test_excluded_reporting_and_failure_codes(self):
        snapshot = {
            "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
            "service": "kms",
            "modelHash": "hash",
            "names": {},
        }
        excluded = {
            "resource": "key",
            "propertiesKey": "KMS.Key.PendingWindowInDays",
            "status": "excluded",
            "designValue": 30,
            "reason": "write-only",
        }
        ok = {**excluded, "propertiesKey": "KMS.Key.Enabled", "status": "match"}
        for records, code in [
            ([excluded, ok], 0),
            ([excluded], 2),
            ([excluded, {**ok, "status": "difference"}], 1),
            ([excluded, {**ok, "status": "sdk_unavailable"}], 2),
            ([excluded, {**ok, "status": "acquisition_failed"}], 2),
        ]:
            text, actual = audit.report(
                snapshot, None, "account", records, datetime.now(timezone.utc)
            )
            self.assertEqual(actual, code)
            self.assertIn("[INFO]", text)
            self.assertIn("Verification: NOT_VERIFIABLE", text)
            self.assertIn("INFO: 1", text)

    def test_report_translates_fixed_producer_diagnostic_only(self):
        snapshot = {
            "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
            "service": "vpc",
            "modelHash": "hash",
            "names": {},
        }
        item = {
            **self.item,
            "resource": "ModelResource",
            "status": "design_unresolved",
            "reason": "producer Model is absent",
            "designValue": "ModelValue",
        }
        text, _ = audit.report(
            snapshot, None, "account", [item], datetime.now(timezone.utc)
        )
        self.assertIn("producer Design is absent", text)
        self.assertIn("ModelValue", text)
        self.assertNotIn("producer Model is absent", text)

    def test_report_does_not_include_internal_id_or_api(self):
        snapshot = {
            "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
            "service": "vpc",
            "modelHash": "hash",
            "names": {"EC2_VPC_001": "vpc-name"},
        }
        item = {
            **self.item,
            "resource": "EC2_VPC_001",
            "resourceType": "EC2.VPC",
            "status": "match",
            "designValue": "vpc-123",
            "apis": [{"api": "ec2.describe_vpcs"}],
        }
        text, code = audit.report(
            snapshot, None, "account", [item], datetime.now(timezone.utc)
        )
        self.assertEqual(code, 0)
        self.assertIn("[OK] EC2.VPC | vpc-name | VpcId", text)
        self.assertNotIn("EC2_VPC_001", text)
        self.assertNotIn("API:", text)
        item["resource"] = "EC2_VPC_002"
        self.assertIn(
            "（名前未設定）",
            audit.report(snapshot, None, "account", [item], datetime.now(timezone.utc))[
                0
            ],
        )


class DisplayTests(unittest.TestCase):
    def test_duplicate_names_use_confirmed_identity(self):
        names = {
            "Internal_1": "duplicate",
            "Internal_2": "duplicate",
            "Internal_3": "unique",
            "Internal_4": "duplicate",
        }
        kinds = {key: "EC2.VPC" for key in names}
        identities = {
            "Internal_1": {"EC2.VPC.VpcId": "vpc-a"},
            "Internal_2": {"EC2.VPC.VpcId": "vpc-b"},
            "Internal_3": {"EC2.VPC.VpcId": "vpc-c"},
            "Internal_4": {},
        }
        disambiguate_names(names, kinds, identities, {"EC2.VPC": ("EC2.VPC.VpcId",)})
        self.assertEqual(
            list(names.values()),
            ["duplicate (vpc-a)", "duplicate (vpc-b)", "unique", "duplicate"],
        )
        self.assertNotIn("Internal_", " ".join(names.values()))

    def test_partial_and_duplicate_identifiers(self):
        vpc = "EC2.VPC.VpcId"
        allocation = "EC2.EIP.AllocationId"
        address = "EC2.EIP.PublicIp"
        cases = [
            (
                "EC2.VPC",
                (vpc,),
                [{vpc: "vpc-a"}, {}],
                ["duplicate (vpc-a)", "duplicate"],
            ),
            (
                "EC2.VPC",
                (vpc,),
                [{vpc: "vpc-a"}, {vpc: "vpc-a"}, {}],
                ["duplicate", "duplicate", "duplicate"],
            ),
            ("EC2.VPC", (vpc,), [{vpc: None}, {}], ["duplicate", "duplicate"]),
            (
                "EC2.EIP",
                (allocation, address),
                [{allocation: "alloc-a"}, {address: "ip-b"}, {}],
                ["duplicate (alloc-a)", "duplicate (ip-b)", "duplicate"],
            ),
            (
                "EC2.EIP",
                (allocation, address),
                [{allocation: "same"}, {address: "same"}, {}],
                ["duplicate", "duplicate", "duplicate"],
            ),
            (
                "EC2.EIP",
                (allocation, address),
                [{allocation: "same", address: "ip-a"}, {address: "same"}, {}],
                ["duplicate (ip-a)", "duplicate (same)", "duplicate"],
            ),
            (
                "EC2.EIP",
                (allocation, address),
                [
                    {allocation: "alloc-a", address: "ip-a"},
                    {allocation: "alloc-b", address: "ip-b"},
                    {},
                ],
                ["duplicate (alloc-a)", "duplicate (alloc-b)", "duplicate"],
            ),
            (
                "EC2.EIP",
                (allocation, address),
                [
                    {allocation: "alloc-a", address: "ip-a"},
                    {allocation: "alloc-a", address: "ip-b"},
                    {allocation: "alloc-b", address: "ip-a"},
                    {},
                ],
                [
                    "duplicate (alloc-a, ip-a)",
                    "duplicate (alloc-a, ip-b)",
                    "duplicate (alloc-b, ip-a)",
                    "duplicate",
                ],
            ),
        ]
        for kind, fields, values, expected in cases:
            with self.subTest(kind=kind, values=values):
                names = {f"Internal_{i}": "duplicate" for i in range(len(values))}
                kinds = dict.fromkeys(names, kind)
                identities = dict(zip(names, values, strict=True))
                disambiguate_names(names, kinds, identities, {kind: fields})
                self.assertEqual(list(names.values()), expected)
                self.assertNotIn("Internal_", " ".join(names.values()))

    def test_multiple_and_composite_identifiers(self):
        kinds = {str(i): "EC2.EIP" for i in range(3)}
        primary = {"EC2.EIP": ("EC2.EIP.AllocationId", "EC2.EIP.PublicIp")}
        identities = {
            "0": {"EC2.EIP.AllocationId": "alloc-a", "EC2.EIP.PublicIp": "ip-a"},
            "1": {"EC2.EIP.AllocationId": "alloc-b", "EC2.EIP.PublicIp": "ip-b"},
            "2": {"EC2.EIP.AllocationId": "alloc-c", "EC2.EIP.PublicIp": "ip-c"},
        }
        names = {"0": "duplicate", "1": "duplicate", "2": "unique"}
        disambiguate_names(names, kinds, identities, primary)
        self.assertEqual(
            list(names.values()),
            ["duplicate (alloc-a)", "duplicate (alloc-b)", "unique"],
        )
        names = dict.fromkeys(kinds, "duplicate")
        identities["1"]["EC2.EIP.AllocationId"] = "alloc-a"
        identities["2"]["EC2.EIP.PublicIp"] = "ip-a"
        disambiguate_names(names, kinds, identities, primary)
        self.assertEqual(
            list(names.values()),
            [
                "duplicate (alloc-a, ip-a)",
                "duplicate (alloc-a, ip-b)",
                "duplicate (alloc-c, ip-a)",
            ],
        )

    def test_formal_names(self):
        root = Path(__file__).resolve().parents[4]
        for kind, fields, expected in [
            ("EC2.VPC", [("Name", "vpc-name")], "vpc-name"),
            ("EC2.Subnet", [("Name", "subnet-name")], "subnet-name"),
            (
                "EC2.SecurityGroup",
                [("Tags[].Key", "Name"), ("Tags[].Value", "sg-name")],
                "sg-name",
            ),
            ("IAM.Role", [("RoleName", "role-name")], "role-name"),
            ("Lambda.Function", [("FunctionName", "function-name")], "function-name"),
            ("CodeBuild.Project", [("Name", "project-name")], "project-name"),
        ]:
            with self.subTest(kind=kind):
                resource = {
                    "resourceType": kind,
                    "logicalId": "Internal_001",
                    "anchor": "resource",
                }
                values = {
                    "desired.resource.001." + key: value
                    for key, value in resource.items()
                }
                for index, (field, value) in enumerate(fields, 1):
                    prefix = f"desired.row.001-{index:03d}."
                    values.update(
                        {
                            prefix + "property": kind + "." + field,
                            prefix + "value": "`" + value + "`",
                            prefix + "comment": "fixture",
                        }
                    )
                rows = resource_display_rows(values, "001", resource, root)
                name, _ = display_name(
                    values, "001", resource, rows, root, projection=True
                )
                self.assertEqual(name, expected)

    def test_kms_grouped_alias(self):
        root = Path(__file__).resolve().parents[4]
        resource = {
            "resourceType": "KMS.Key",
            "logicalId": "Internal_001",
            "anchor": "key",
        }
        values = {
            "desired.resource.001." + key: value for key, value in resource.items()
        }
        values.update(
            {
                "desired.resource.002.resourceType": "KMS.Alias",
                "desired.resource.002.logicalId": "Internal_002",
                "desired.resource.002.anchor": "alias",
                "desired.resource.002.parentReference": json.dumps(
                    {"$modelRef": {"logicalId": "Internal_001", "attribute": "KeyId"}}
                ),
                "desired.row.002-001.property": "KMS.Alias.AliasName",
                "desired.row.002-001.value": "`alias/app`",
                "desired.row.002-001.comment": "fixture",
            }
        )
        rows = resource_display_rows(values, "001", resource, root)
        name, _ = display_name(values, "001", resource, rows, root, projection=True)
        self.assertEqual(name, "app")


class PipelineMembershipTests(unittest.TestCase):
    save = ReferenceTests.save
    setUp = ReferenceTests.setUp
    model = staticmethod(ReferenceTests.model)
    ref = staticmethod(ReferenceTests.ref)

    def build(
        self, stages=2, actions=2, reference=False, ambiguous=False, varied=False
    ):
        values = self.model(
            "CodePipeline.Pipeline", "CodePipeline_Pipeline_001", {"Name": "fixture"}
        )
        rows = []
        response = []
        for stage in range(stages):
            aws_actions = []
            for action in range(actions):
                name = f"action-{stage}-{action}"
                category = "Build" if reference else f"category-{stage}-{action}"
                project = f"project-{stage}-{action}"
                config = {
                    "ProjectName": self.ref("CodeBuild_Project_001", "Name")
                    if reference and stage == action == 0
                    else project
                }
                if reference and stage == action == 0:
                    project = "build-project"
                rows.extend(
                    [
                        (
                            "Stages[].Actions[].ActionTypeId.Category",
                            category,
                            "fixture",
                        ),
                        ("Stages[].Actions[].ActionTypeId.Owner", "AWS", "fixture"),
                        (
                            "Stages[].Actions[].ActionTypeId.Provider",
                            "CodeBuild",
                            "fixture",
                        ),
                        ("Stages[].Actions[].ActionTypeId.Version", "1", "fixture"),
                        (
                            "Stages[].Actions[].Configuration",
                            json.dumps(config),
                            "ProjectName: project",
                        ),
                        ("Stages[].Actions[].Name", name, "fixture"),
                    ]
                )
                if varied and stage == 1 and action == 1:
                    rows.insert(
                        -1, ("Stages[].Actions[].Namespace", "optional", "fixture")
                    )
                aws_actions.append(
                    {
                        "name": name,
                        "actionTypeId": {
                            "category": category,
                            "owner": "AWS",
                            "provider": "CodeBuild",
                            "version": "1",
                        },
                        "configuration": {"ProjectName": project},
                    }
                )
            if varied and stage == 1:
                aws_actions[1]["namespace"] = "optional"
            rows.append(("Stages[].Name", f"stage-{stage}", "fixture"))
            response.append({"name": f"stage-{stage}", "actions": aws_actions})
        if ambiguous:
            rows.pop(5)
        for index, (prop, value, comment) in enumerate(rows, 2):
            prefix = f"desired.row.001-{index:03d}."
            values.update(
                {
                    prefix + "property": "CodePipeline.Pipeline." + prop,
                    prefix + "value": "`" + value + "`",
                    prefix + "comment": comment,
                }
            )
        write_model(self.root / "model/dev/cde/codepipeline.properties", values)
        if reference:
            producer = self.model(
                "CodeBuild.Project", "CodeBuild_Project_001", {"Name": "build-project"}
            )
            write_model(self.root / "model/dev/cde/codebuild.properties", producer)
        source = generate(self.root, "dev", "cde", "codepipeline")[0]
        snapshot = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        return snapshot, response, source

    def records(self, snapshot, stages):
        cli = Mock(
            side_effect=[
                subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps(
                        {
                            "Account": "123456789012",
                            "Arn": "arn:aws:iam::123456789012:user/offline",
                        }
                    ),
                    "",
                ),
                subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps({"pipeline": {"name": "fixture", "stages": stages}}),
                    "",
                ),
            ]
        )
        return audit.audit(snapshot, cli_runner=cli)[2]

    def test_membership_and_difference(self):
        for stages, actions in [(1, 1), (2, 2)]:
            with self.subTest(stages=stages, actions=actions):
                snapshot, response, _ = self.build(stages, actions)
                records = self.records(snapshot, response)
                selected = [r for r in records if "Stages[]" in r["propertiesKey"]]
                self.assertTrue(selected)
                self.assertTrue(all(r["status"] == "match" for r in selected), selected)
                response[0]["actions"][0]["configuration"]["ProjectName"] = "wrong"
                records = self.records(snapshot, response)
                config = next(
                    r for r in records if r["propertiesKey"].endswith(".Configuration")
                )
                category = next(
                    r for r in records if r["propertiesKey"].endswith(".Category")
                )
                self.assertEqual(config["status"], "difference", config)
                self.assertEqual(category["status"], "match", category)

    def test_varied_optional_fields(self):
        snapshot, response, _ = self.build(varied=True)
        records = self.records(snapshot, response)
        selected = [
            r
            for r in records
            if "Stages[]" in r["propertiesKey"]
            and not r["propertiesKey"].endswith(".Namespace")
        ]
        self.assertTrue(all(r["status"] == "match" for r in selected), selected)

    def test_ambiguous_membership(self):
        snapshot, response, _ = self.build(2, 2, ambiguous=True)
        self.assertFalse(snapshot["pipelineIndexedRows"]["001"])
        records = self.records(snapshot, response)
        self.assertTrue(
            all(
                r["status"] == "design_unresolved"
                for r in records
                if "Stages[]" in r["propertiesKey"]
            ),
            records,
        )

    def test_standalone(self):
        snapshot, response, source = self.build(reference=True)
        with tempfile.TemporaryDirectory(prefix="pipeline-standalone-") as directory:
            folder = Path(directory)
            script = folder / "audit.py"
            script.write_text(source, encoding="utf-8")
            fake = folder / "aws"
            fake.write_text(
                "#!"
                + sys.executable
                + "\nimport json, sys\nprint(json.dumps("
                + repr({"pipeline": {"name": "fixture", "stages": response}})
                + " if sys.argv[1] == 'codepipeline' else "
                + repr(
                    {
                        "Account": "123456789012",
                        "Arn": "arn:aws:iam::123456789012:user/offline",
                    }
                )
                + "))\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            process = subprocess.run(
                [sys.executable, "-I", "-B", str(script)],
                cwd=folder,
                env={**os.environ, "PATH": str(folder)},
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotIn("ModuleNotFoundError", process.stderr)
            self.assertIn("[OK] CodePipeline.Pipeline", process.stdout)
            self.assertNotIn("Design reference projection failed", process.stdout)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_reference(self):
        snapshot, response, _ = self.build(reference=True)
        records = self.records(snapshot, response)
        config = next(
            r for r in records if r["propertiesKey"].endswith(".Configuration")
        )
        self.assertEqual(config["status"], "match", config)
        failure = Mock(return_value=subprocess.CompletedProcess([], 1, "", "denied"))
        records = audit.audit(snapshot, cli_runner=failure)[2]
        config = next(
            r for r in records if r["propertiesKey"].endswith(".Configuration")
        )
        self.assertEqual(config["status"], "acquisition_failed", config)
        self.assertNotIn("Design reference projection failed", config["reason"])
        resolution = next(
            iter(snapshot["referenceRows"]["dev/cde/codepipeline"].values())
        )
        resolution.update(status="unresolved", reason="missing producer")
        records = self.records(snapshot, response)
        config = next(
            r for r in records if r["propertiesKey"].endswith(".Configuration")
        )
        self.assertEqual(config["status"], "design_unresolved", config)
        self.assertIn("missing producer", config["reason"])


if __name__ == "__main__":
    unittest.main()
