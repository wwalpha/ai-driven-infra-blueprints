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
        design = root / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
        artifact = design.parent / "vpc" / "vpc01-policy.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"Version":"2012-10-17"}\n', encoding="utf-8")
        design.write_text(
            """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`

<a id="vpc-vpc01"></a>

## EC2.VPC: VPC01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EC2.VPC.CidrBlock | 10.1.0.0/16 | VPCで使用するIPv4アドレス範囲 |
| 2 | VPC ID | PENDING_DEPLOY | デプロイされたVPCを一意に識別するID |
| 3 | PolicyDocument | [policy](vpc/vpc01-policy.json) | VPCに適用するpolicy文書 |
""",
            encoding="utf-8",
        )
        model = MODULE.model_for(design)
        assert "desired.service.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet" in model
        assert "desired.resource.001.logicalId=VPC01" in model
        assert "desired.row.001-001.value=10.1.0.0/16" in model
        assert "observed.row.001-002.value=PENDING_DEPLOY" in model
        assert "desired.row.001-003.artifactSha256=" in model
        assert model == MODULE.model_for(design)
        with redirect_stdout(io.StringIO()):
            assert MODULE.sync(root, True) == 0
            artifact.write_text('{"Version":"changed"}\n', encoding="utf-8")
            assert MODULE.sync(root, False) == 1
    print("sync-model: PASS (8 focused checks)")


if __name__ == "__main__":
    main()
