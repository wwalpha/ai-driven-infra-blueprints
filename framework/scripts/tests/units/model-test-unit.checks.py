#!/usr/bin/env python3
"""Focused Model Test identifier and report behavior."""

import ast
import json
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
from model.audit import dependencies, disambiguate_names, generate, reference_rows
from model.projection import resource_display_rows
from model.reference_values import ReferenceValue, confirmed
from model.render import display_name
from model.sources import load_model
from support.model_sources import write_model
from utils.input_cache import input_scope

from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


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


if __name__ == "__main__":
    unittest.main()
