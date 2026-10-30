#!/usr/bin/env python3
"""Focused Model Test identifier and report behavior."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from model.projection import resource_display_rows
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
        self.item["awsValue"] = "vpc-456"
        self.assertEqual(self.result()["status"], "difference")

    def test_missing_pending_ambiguous_and_invalid(self):
        for value in (
            None,
            "`PENDING_DEPLOY`",
            "`UNSET`",
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
