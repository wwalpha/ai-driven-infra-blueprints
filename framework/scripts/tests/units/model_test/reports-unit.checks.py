import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from model.audit import (
    disambiguate_names,
)
from model.projection import resource_display_rows
from model.render import display_name

from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


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
        root = Path(__file__).resolve().parents[5]
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
        root = Path(__file__).resolve().parents[5]
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


class GuardDutyReportTests(unittest.TestCase):
    def test_json_string_preserves_type_and_masks_secrets(self):
        value = '["build-artifact/"]'
        self.assertEqual(audit.masked(value), value)
        self.assertEqual(audit.different_paths([value], ["build-artifact/"]), ["$[0]"])
        secret = '{"password":"hidden","nested":[{"Key":"token","Value":"hidden"}]}'
        masked = audit.masked(secret)
        self.assertIsInstance(masked, str)
        self.assertNotIn("hidden", masked)
        self.assertEqual(json.loads(masked)["password"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
