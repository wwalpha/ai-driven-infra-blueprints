import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from functools import partial as _bind_framework_callback
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from model.audit import (
    dependencies,
    reference_rows,
)
from model.reference_values import ReferenceValue
from model.sources import load_model
from support.model_sources import write_model
from support.model_test_adapter_cases import endpoint_case
from support.model_test_references import ReferenceFixture
from support.regression_cases import case_ids
from utils.input_cache import input_scope

from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _flow_log_cli(response, command, **kwargs):
    if command[1] == "sts":
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"Account": "123456789012"}), ""
        )
    if response is None:
        return subprocess.CompletedProcess(
            command, 1, "", "An error occurred (AccessDenied) when calling Mock: denied"
        )
    return subprocess.CompletedProcess(
        command, 0, json.dumps({"FlowLogs": response}), ""
    )


def _flow_log_id_cli(records, command, **kwargs):
    value = (
        {"Account": "123456789012"} if command[1] == "sts" else {"FlowLogs": records}
    )
    return subprocess.CompletedProcess(command, 0, json.dumps(value), "")


class ReferenceTests(ReferenceFixture, unittest.TestCase):
    def test_flow_log_traffic_type_outcomes(self):
        self.consumer = self.model(
            "EC2.FlowLog",
            "EC2_FlowLog_001",
            {
                "Id": self.ref("EC2_FlowLog_001", "Id"),
                "ResourceId": "vpc-123",
                "TrafficType": "ALL",
            },
        )
        self.save()
        snapshot = self.snapshot()
        record = {"FlowLogId": "fl-123", "ResourceId": "vpc-123", "TrafficType": "ALL"}
        for case, response, status in (
            ("untagged", [record], "match"),
            ("missing", [], "resource_missing"),
            (
                "ambiguous",
                [record, {**record, "FlowLogId": "fl-456"}],
                "design_unresolved",
            ),
            ("denied", None, "acquisition_failed"),
        ):
            with self.subTest(case=case):
                cli = _bind_framework_callback(_flow_log_cli, response)
                item = next(
                    (
                        item
                        for item in audit.audit(snapshot, cli_runner=cli)[2]
                        if item["propertiesKey"] == "EC2.FlowLog.TrafficType"
                    )
                )
                self.assertEqual(item["status"], status, item)
                if case == "untagged":
                    self.assertEqual(item["awsValue"], "ALL")

    def test_flow_log_identifier_evidence(self):
        self.consumer = self.model(
            "EC2.FlowLog",
            "EC2_FlowLog_001",
            {"Id": self.ref("EC2_FlowLog_001", "Id"), "ResourceId": "vpc-123"},
        )
        for observed, records, status in (
            ("PENDING_DEPLOY", [], "resource_missing"),
            ("PENDING_DEPLOY", [{"FlowLogId": "fl-new"}], "pending_identifier"),
            ("fl-old", [], "resource_missing"),
            ("fl-old", [{"FlowLogId": "fl-old"}], "match"),
            ("fl-old", [{"FlowLogId": "fl-new"}], "difference"),
            (
                "PENDING_DEPLOY",
                [{"FlowLogId": "fl-a"}, {"FlowLogId": "fl-b"}],
                "design_unresolved",
            ),
        ):
            with self.subTest(observed=observed, records=records):
                self.consumer["observed.row.001-001.value"] = f"`{observed}`"
                self.save()
                cli = _bind_framework_callback(_flow_log_id_cli, records)
                item = next(
                    (
                        item
                        for item in audit.audit(self.snapshot(), cli_runner=cli)[2]
                        if item["propertiesKey"] == "EC2.FlowLog.Id"
                    )
                )
                self.assertEqual(item["status"], status, item)
                if observed == "PENDING_DEPLOY":
                    self.assertIsNone(item["designValue"])
                    self.assertIn("REFERENCE_PENDING_DEPLOY", item["reason"])

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
                self.actual, self.missing = (actual, False)
                item = next(
                    (
                        item
                        for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                        if item["propertiesKey"] == prop
                    )
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
                    self.actual, self.missing = (actual, False)
                    item = next(
                        (
                            item
                            for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                            if item["propertiesKey"].endswith("LogGroupName")
                        )
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
                self.missing, self.actual = (True, None)
                item = next(
                    (
                        item
                        for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                        if item["propertiesKey"].endswith("LogGroupName")
                    )
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
                self.actual, self.missing = (True, False)
                item = next(
                    (
                        item
                        for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                        if item["propertiesKey"].endswith("LogGroupName")
                    )
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
                self.actual, self.missing = ("/aws/vpc/flowlogs/fixture", False)
                snapshot = self.snapshot()
                for field in ("Key", "Value"):
                    snapshot["mappings"]["vpc"]["properties"][
                        "EC2.FlowLog.Tags[]." + field
                    ]["field"].update(
                        getter="base", classification="supported", reason=""
                    )
                item = next(
                    (
                        item
                        for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                        if item["propertiesKey"].endswith("Tags[].Key")
                    )
                )
                self.assertEqual(item["status"], "match", item)
                self.assertEqual(item["designValue"], ["/aws/vpc/flowlogs/fixture"])
                if reference:
                    self.missing = True
                    item = next(
                        (
                            item
                            for item in audit.audit(snapshot, cli_runner=self.cli)[2]
                            if item["propertiesKey"].endswith("Tags[].Key")
                        )
                    )
                    self.assertEqual(item["status"], "resource_missing", item)
                    self.assertEqual(item["designValue"], ["/aws/vpc/flowlogs/fixture"])

    def test_acquisition_failure_keeps_resolved_scalar(self):
        snapshot = self.snapshot()
        self.missing, self.actual = (True, None)
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
                self.missing, self.actual = (True, None)
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
                    (
                        item
                        for item in audit.audit(snapshot, cli_runner=calls)[2]
                        if item["propertiesKey"].endswith("LogGroupName")
                    )
                )
                self.assertEqual(
                    item["status"],
                    "resource_missing"
                    if failure == "ResourceNotFound"
                    else "acquisition_failed",
                )
                self.assertIn("must be string", item["reason"])
                self.assertIn(
                    "AwsCliError" if failure == "AccessDenied" else failure,
                    item["reason"],
                )
                self.assertIsNone(item["designValue"])
                self.assertEqual(
                    sum(
                        (
                            call.args[0][1:3] == ["ec2", "describe-flow-logs"]
                            for call in calls.call_args_list
                        )
                    ),
                    1,
                )

    def test_difference_and_account_failure(self):
        snapshot = self.snapshot()
        self.missing, self.actual = (False, "/different")
        records = audit.audit(snapshot, cli_runner=self.cli)[2]
        item = next(
            (
                item
                for item in records
                if item["propertiesKey"].endswith(".LogGroupName")
            )
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
                    {"VpcId": self.ref("EC2_VPC_001", "VpcId")},
                )
                self.save()
                snapshot = self.snapshot()
                row = snapshot["referenceRows"]["dev/cde/vpc"]["001-001"]
                self.assertEqual(row["status"], expected, row)
                self.assertIsNone(row["value"])
                self.missing, self.actual = (False, None)
                item = audit.audit(snapshot, cli_runner=self.cli)[2][0]
                self.assertEqual(item["status"], "design_unresolved", item)
                self.assertIn("Design reference unresolved", item["reason"])
        self.consumer = self.model(
            "EC2.VPC",
            "EC2_VPC_001",
            {"CidrBlock": self.ref("Logs_LogGroup_001", "RetentionInDays")},
        )
        self.producer = self.model(
            "Logs.LogGroup",
            "Logs_LogGroup_001",
            {"LogGroupName": "/fixture", "RetentionInDays": 7},
        )
        self.save()
        row = self.snapshot()["referenceRows"]["dev/cde/vpc"]["001-001"]
        self.assertEqual(row["status"], "unresolved", row)
        self.assertIn("MODEL_REF_TYPE_MISMATCH", row["reason"])

    @input_scope
    def test_reference_intrinsics_only_resolve_proven_values(self):
        reference = self.ref("Logs_LogGroup_001", "LogGroupName")
        for expression, expected in (
            (
                {"Fn::Sub": ["prefix-${Name}", {"Name": reference}]},
                "prefix-/aws/vpc/flowlogs/fixture",
            ),
            (
                {"Fn::Sub": ["${Name}-${Unknown}", {"Name": reference}]},
                {
                    "Fn::Sub": [
                        "${Name}-${Unknown}",
                        {"Name": "/aws/vpc/flowlogs/fixture"},
                    ]
                },
            ),
            (
                {"Fn::Join": ["-", [reference, {"Fn::GetAtt": ["Unknown", "Arn"]}]]},
                {
                    "Fn::Join": [
                        "-",
                        [
                            "/aws/vpc/flowlogs/fixture",
                            {"Fn::GetAtt": ["Unknown", "Arn"]},
                        ],
                    ]
                },
            ),
        ):
            with self.subTest(expression=expression):
                self.consumer["desired.row.001-002.value"] = (
                    "`" + json.dumps(expression) + "`"
                )
                self.save()
                row = self.snapshot()["referenceRows"]["dev/cde/vpc"]["001-002"]
                self.assertEqual(row["value"], expected)

    @input_scope
    def test_nested_native_values_and_stable_row_ids(self):
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
        self.missing, self.actual = (True, None)
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
            self.missing, self.actual = (False, raw.strip("`"))
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
                self.missing, self.actual = (missing, "never-print")
                records = audit.audit(snapshot, cli_runner=self.cli)[2]
                self.assertEqual(records[-1]["designValue"], "[REDACTED]")
                text, _ = audit.report(
                    snapshot, None, "account", records, datetime.now(timezone.utc)
                )
                self.assertNotIn("never-print", text)


@pytest.mark.parametrize(
    "case_id", case_ids("model_test_references", prefix="endpoint-")
)
def test_endpoint_observation_and_unresolved_reasons(
    case_runner, tmp_path, monkeypatch, case_id
):
    case_runner.run(
        "model_test_references",
        case_id,
        _bind_framework_callback(endpoint_case, tmp_path, monkeypatch),
    )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
