#!/usr/bin/env python3
"""Focused checks for PDF bundling and link targets."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import importlib.util
import tempfile

from support.it_case_receipt import it_case

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPT = Path(__file__).resolve().parents[2] / "export-design-pdf.py"
SPEC = importlib.util.spec_from_file_location("export_design_pdf", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@it_case
def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        base = root / "docs" / "designs"
        cde = base / "dev" / "cde"
        stg = base / "stg" / "non-cde"
        cde.mkdir(parents=True)
        stg.mkdir(parents=True)
        iam = cde / "iam.md"
        vpc = cde / "vpc.md"
        other = stg / "vpc.md"
        s3 = cde / "s3.md"
        artifact = cde / "vpc" / "policy.json"
        artifact.parent.mkdir()
        artifact.write_text(
            '{"Version":"2012-10-17","Statement":[]}\n', encoding="utf-8"
        )
        iam.write_text(
            "# IAM 詳細設計\n\n## リソース一覧\n\n### IAM.Role\n\n"
            "| Role |\n| --- |\n| [Role](#iam-role) |\n| [RoleTwo](#iam-role-two) |\n\n"
            "### IAM.Policy\n\n| Policy |\n| --- |\n| [Policy](#iam-policy) |\n\n"
            '## リソース詳細\n\n<a id="iam-role"></a>\n### IAM.Role: Role\n\n'
            "| No. | Property |\n| ---: | --- |\n| 1 | RoleName |\n\n"
            '<a id="iam-role-two"></a>\n### IAM.Role: RoleTwo\n\n'
            '<a id="iam-policy"></a>\n### IAM.Policy: Policy\n\n'
            "#### IAM Policy: Example\n\n<details>\n"
            "<summary>ExamplePolicy</summary>\n\n"
            '```json\n{"Action": "s3:GetObject"}\n```\n\n'
            "| No. | Action |\n| ---: | --- |\n| 1 | s3:GetObject |\n\n</details>\n",
            encoding="utf-8",
        )
        vpc.write_text(
            "# VPC 詳細設計\n\n## リソース一覧\n\n"
            "| VPC |\n| --- |\n| [A](#vpc-a) |\n\n"
            '## リソース詳細\n\n<a id="vpc-a"></a>\n### EC2.VPC: A\n\n'
            "[A](#vpc-a) [Role](iam.md#iam-role)\n"
            "[policy](vpc/policy.json) [policy again](vpc/policy.json)\n"
            "~~~md\n[example](missing.md#example)\n~~~\n",
            encoding="utf-8",
        )
        s3.write_text(
            "# S3 詳細設計\n\n<!-- policy-tables:start -->\n\n"
            "<details>\n<summary>BucketPolicy</summary>\n\n"
            '```json\n{"Action": "s3:PutObject"}\n```\n\n</details>\n\n'
            "<!-- policy-tables:end -->\n",
            encoding="utf-8",
        )
        other.write_text(
            "# VPC 詳細設計\n\n## リソース一覧\n\n"
            "| VPC |\n| --- |\n| [A](#vpc-a) |\n\n"
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
            "stg-non-cde-vpc-a": 2,
        }, expected
        assert "<details>" not in merged
        assert '"Action": "s3:GetObject"' in merged
        assert '"Action": "s3:PutObject"' in merged
        pdf_root = root / "pdf-project"
        pdf_source = pdf_root / "docs/designs/dev/cde/iam.md"
        pdf_source.parent.mkdir(parents=True)
        pdf_source.write_text(
            "# IAM\n\n[Policy](#policy)<!-- [Policy](iam/policy.json) -->\n\n"
            '<a id="policy"></a>\n\n#### IAM Policy: Example\n\n<details>\n'
            "<summary>ExamplePolicy</summary>\n\n"
            '```json\n{"Action": "s3:GetObject"}\n```\n\n'
            "| No. | Action |\n| ---: | --- |\n| 1 | s3:GetObject |\n\n</details>\n",
            encoding="utf-8",
        )
        artifact_path = pdf_source.parent / "iam/policy.json"
        artifact_path.parent.mkdir()
        artifact_path.write_text('{"Action": "s3:GetObject"}', encoding="utf-8")
        pdf = root / "design.pdf"
        MODULE.export(pdf_root, pdf)
        extracted = "\n".join(
            page.extract_text() for page in MODULE._imports_pypdf.PdfReader(pdf).pages
        )
        assert extracted.count("s3:GetObject") >= 2
        assert "[Role](#dev-cde-iam-role)" in merged
        assert "[A](#dev-cde-vpc-a)" in merged
        assert "[A](#stg-non-cde-vpc-a)" in merged
        assert merged.count("{#appendix-dev-cde-vpc-policy}") == 1
        assert merged.count("](#appendix-dev-cde-vpc-policy)") == 2
        assert "[example](missing.md#example)" in merged
        assert "# 詳細設計書" not in merged
        assert "# dev / cde {#target-dev-cde .target-title .first-target}" in merged
        assert "# stg / non-cde {#target-stg-non-cde .target-title}" in merged
        assert (
            "## IAM 詳細設計 {#service-dev-cde-iam .service-title .first-service}"
            in merged
        )
        assert "## VPC 詳細設計 {#service-dev-cde-vpc .service-title}" in merged
        assert (
            "## VPC 詳細設計 {#service-stg-non-cde-vpc .service-title .first-service}"
            in merged
        )
        assert (
            "| No. | Role |\n| ---: | --- |\n| 1 | [Role](#dev-cde-iam-role) |\n| 2 | [RoleTwo](#dev-cde-iam-role-two) |"
            in merged
        )
        assert (
            "| No. | Policy |\n| ---: | --- |\n| 1 | [Policy](#dev-cde-iam-policy) |"
            in merged
        )
        assert "| No. | Property |\n| ---: | --- |\n| 1 | RoleName |" in merged
        assert '<a id="dev-cde-vpc-a"></a>\n\n#### EC2.VPC: A' in merged

    print("export-design-pdf: PASS (bundle, links, appendix, fences, anchors)")


if __name__ == "__main__":
    main()
