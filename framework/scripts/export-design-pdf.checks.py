#!/usr/bin/env python3
"""Focused checks for PDF bundling and link targets."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).with_name("export-design-pdf.py")
SPEC = importlib.util.spec_from_file_location("export_design_pdf", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def expect_error(root: Path, message: str) -> None:
    try:
        MODULE.bundle(root)
    except ValueError as error:
        assert message in str(error), error
    else:
        raise AssertionError(f"expected {message}")


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        base = root / "docs" / "designs"
        cde = base / "dev" / "cde"
        staging = base / "staging" / "non-cde"
        cde.mkdir(parents=True)
        staging.mkdir(parents=True)
        iam = cde / "iam.md"
        vpc = cde / "vpc.md"
        other = staging / "vpc.md"
        artifact = cde / "vpc" / "policy.json"
        artifact.parent.mkdir()
        artifact.write_text('{"Version":"2012-10-17","Statement":[]}\n', encoding="utf-8")
        iam.write_text(
            '# IAM 詳細設計\n\n## リソース一覧\n\n### IAM.Role\n\n'
            '| Role |\n| --- |\n| [Role](#iam-role) |\n| [RoleTwo](#iam-role-two) |\n\n'
            '### IAM.Policy\n\n| Policy |\n| --- |\n| [Policy](#iam-policy) |\n\n'
            '## リソース詳細\n\n<a id="iam-role"></a>\n### IAM.Role: Role\n\n'
            '| No. | Property |\n| ---: | --- |\n| 1 | RoleName |\n\n'
            '<a id="iam-role-two"></a>\n### IAM.Role: RoleTwo\n\n'
            '<a id="iam-policy"></a>\n### IAM.Policy: Policy\n',
            encoding="utf-8",
        )
        vpc.write_text(
            '# VPC 詳細設計\n\n## リソース一覧\n\n'
            '| VPC |\n| --- |\n| [A](#vpc-a) |\n\n'
            '## リソース詳細\n\n<a id="vpc-a"></a>\n### EC2.VPC: A\n\n'
            '[A](#vpc-a) [Role](iam.md#iam-role)\n'
            '[policy](vpc/policy.json) [policy again](vpc/policy.json)\n'
            '~~~md\n[example](missing.md#example)\n~~~\n',
            encoding="utf-8",
        )
        other.write_text(
            '# VPC 詳細設計\n\n## リソース一覧\n\n'
            '| VPC |\n| --- |\n| [A](#vpc-a) |\n\n'
            '## リソース詳細\n\n<a id="vpc-a"></a>\n### EC2.VPC: A\n[A](#vpc-a)\n',
            encoding="utf-8",
        )

        merged, expected = MODULE.bundle(root)
        assert expected == {
            "dev-cde-vpc-a": 2,
            "dev-cde-iam-role": 2,
            "dev-cde-iam-role-two": 1,
            "dev-cde-iam-policy": 1,
            "appendix-dev-cde-vpc-policy": 2,
            "staging-non-cde-vpc-a": 2,
        }, expected
        assert '[Role](#dev-cde-iam-role)' in merged
        assert '[A](#dev-cde-vpc-a)' in merged
        assert '[A](#staging-non-cde-vpc-a)' in merged
        assert merged.count('{#appendix-dev-cde-vpc-policy}') == 1
        assert merged.count('](#appendix-dev-cde-vpc-policy)') == 2
        assert '[example](missing.md#example)' in merged
        assert '# 詳細設計書' not in merged
        assert '# dev / cde {#target-dev-cde .target-title .first-target}' in merged
        assert '# staging / non-cde {#target-staging-non-cde .target-title}' in merged
        assert '## IAM 詳細設計 {#service-dev-cde-iam .service-title .first-service}' in merged
        assert '## VPC 詳細設計 {#service-dev-cde-vpc .service-title}' in merged
        assert '## VPC 詳細設計 {#service-staging-non-cde-vpc .service-title .first-service}' in merged
        assert '| No. | Role |\n| ---: | --- |\n| 1 | [Role](#dev-cde-iam-role) |\n| 2 | [RoleTwo](#dev-cde-iam-role-two) |' in merged
        assert '| No. | Policy |\n| ---: | --- |\n| 1 | [Policy](#dev-cde-iam-policy) |' in merged
        assert '| No. | Property |\n| ---: | --- |\n| 1 | RoleName |' in merged
        assert '<a id="dev-cde-vpc-a"></a>\n\n#### EC2.VPC: A' in merged

        vpc.write_text(vpc.read_text(encoding="utf-8").replace('iam.md#iam-role', 'iam.md#missing'), encoding="utf-8")
        expect_error(root, "missing PDF link target")
        vpc.write_text(vpc.read_text(encoding="utf-8").replace('iam.md#missing', 'iam.md#iam-role'), encoding="utf-8")
        iam.write_text(iam.read_text(encoding="utf-8") + '<a id="iam-role"></a>\n', encoding="utf-8")
        expect_error(root, "duplicate design anchor")
    print("export-design-pdf: PASS (bundle, links, appendix, fences, missing/duplicate anchors)")


if __name__ == "__main__":
    main()
