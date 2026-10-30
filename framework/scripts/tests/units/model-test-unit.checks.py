#!/usr/bin/env python3
"""Focused Model Test identifier and report behavior."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from design.layout import confirmed_display_name
from model.audit import disambiguate_names
from model.projection import resource_display_rows
from model.reference_values import confirmed
from model.render import display_name

from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


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
                "desired.resource.002.parentReference": "[Key](#key)",
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
