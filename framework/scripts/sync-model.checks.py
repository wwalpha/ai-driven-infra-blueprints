#!/usr/bin/env python3
"""Focused self-checks for generated service models."""

from __future__ import annotations

import importlib.util
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync-model.py")
SPEC = importlib.util.spec_from_file_location("sync_model", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        materials = root / "framework" / "materials" / "aws"
        materials.mkdir(parents=True)
        (materials / "EC2_VPC.properties").write_text(
            "EC2.VPC.VpcId=IDENTIFIER_OUTPUT\n", encoding="utf-8"
        )
        (materials / "EC2_Subnet.properties").write_text(
            "EC2.Subnet.SubnetId=IDENTIFIER_OUTPUT\nEC2.Subnet.VpcId=\n", encoding="utf-8"
        )
        design = root / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
        artifact = design.parent / "vpc" / "vpc01-policy.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"Version":"2012-10-17"}\n', encoding="utf-8")
        design.write_text(
            """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`

<a id="vpc-vpc-app-dev"></a>

## EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EC2.VPC.VpcId | PENDING_DEPLOY | VPCを一意に識別するID |
| 2 | EC2.VPC.CidrBlock | 10.1.0.0/16 | VPCで使用するIPv4アドレス範囲 |
| 3 | EC2.VPC.Name | vpc-app-dev | VPCを識別するNameタグの値 |
| 4 | PolicyDocument | [policy](vpc/vpc01-policy.json) | VPCに適用するpolicy文書 |

<a id="vpc-sbnt-app-dev-private-01"></a>

## EC2.Subnet: sbnt-app-dev-private-01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EC2.Subnet.SubnetId | PENDING_DEPLOY | Subnetを一意に識別するID |
| 2 | EC2.Subnet.VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
| 3 | EC2.Subnet.Name | sbnt-app-dev-private-01 | Subnetを識別するNameタグの値 |
""",
            encoding="utf-8",
        )
        model = MODULE.model_for(design, root)
        assert "desired.service.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet" in model
        assert "desired.resource.001.logicalId=vpc-app-dev" in model
        assert "desired.row.001-001.value=[vpc-app-dev](#vpc-vpc-app-dev)" in model
        assert "observed.row.001-001.value=PENDING_DEPLOY" in model
        assert "desired.row.001-002.value=10.1.0.0/16" in model
        assert "desired.row.001-003.property=EC2.VPC.Name" in model
        assert "desired.row.001-004.artifactSha256=" in model
        assert "desired.row.002-001.value=[sbnt-app-dev-private-01](#vpc-sbnt-app-dev-private-01)" in model
        assert "observed.row.002-001.value=PENDING_DEPLOY" in model
        assert "desired.row.002-002.value=[vpc-app-dev](#vpc-vpc-app-dev)" in model
        assert "desired.row.002-003.property=EC2.Subnet.Name" in model
        assert model == MODULE.model_for(design, root)
        design.write_text(
            design.read_text(encoding="utf-8")
            .replace("EC2.VPC.VpcId | PENDING_DEPLOY", "EC2.VPC.VpcId | vpc-0123456789abcdef0")
            .replace("[PENDING_DEPLOY](#vpc-vpc-app-dev)", "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)")
            .replace("EC2.Subnet.SubnetId | PENDING_DEPLOY", "EC2.Subnet.SubnetId | subnet-0123456789abcdef0"),
            encoding="utf-8",
        )
        deployed = MODULE.model_for(design, root)
        assert "observed.row.001-001.value=vpc-0123456789abcdef0" in deployed
        assert "observed.row.002-001.value=subnet-0123456789abcdef0" in deployed
        assert "observed.row.002-002.value=vpc-0123456789abcdef0" in deployed
        with redirect_stdout(io.StringIO()):
            assert MODULE.sync(root, True) == 0
            artifact.write_text('{"Version":"changed"}\n', encoding="utf-8")
            assert MODULE.sync(root, False) == 1

        alias_design = root / "docs" / "designs" / "dev" / "cde" / "vpc.md"
        alias_design.parent.mkdir(parents=True)
        alias_artifact = alias_design.parent / "vpc" / "vpc01-policy.json"
        alias_artifact.parent.mkdir(parents=True)
        alias_artifact.write_text('{"Version":"2012-10-17"}\n', encoding="utf-8")
        alias_design.write_text(
            design.read_text(encoding="utf-8").replace(
                "vpc-0123456789abcdef0", "vpc-11111111111111111"
            ),
            encoding="utf-8",
        )
        with redirect_stdout(io.StringIO()):
            assert MODULE.sync(root, True, "dev", "cde") == 0
        assert (root / "model" / "dev" / "cde" / "vpc.properties").is_file()
        assert MODULE.selected(alias_design, root / "docs" / "designs", "dev", "cde")
        assert not MODULE.selected(alias_design, root / "docs" / "designs", "dev", "123456789012")
    print("sync-model: PASS (18 focused checks)")


if __name__ == "__main__":
    main()
