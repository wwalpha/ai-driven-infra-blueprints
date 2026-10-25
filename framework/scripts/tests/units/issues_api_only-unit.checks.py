#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from comparison import Comparison
from issues.aggregate import aggregate, iac_summary
from issues.artifact import summary
from issues.reports import iac_report
from support.issues_api_only_fixtures import (
    ROOT,
    DesignSchemaCatalog,
    Path,
    sys,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_api_type_rejection():
    catalog = DesignSchemaCatalog(ROOT)
    for kind in catalog.api_schemas:
        try:
            catalog.cloudformation_type(kind)
        except ValueError as error:
            assert (
                "implementation remains incomplete if this resource is in scope"
                in str(error)
            )
        else:
            raise AssertionError("API resource accepted as implemented CFn")


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


def api_comparison(resource, *, load_errors=()):
    comparison = Comparison.__new__(Comparison)
    comparison.root = Path("/synthetic")
    comparison.services, comparison.target = ["s3"], {"iacEngine": "cloudformation"}
    comparison.symbols, comparison.reference_unavailable, comparison.models = {}, {}, {}
    comparison.load_errors, comparison.results = list(load_errors), []
    comparison.resources = {"s3": {"002": resource}}
    comparison.catalog = DesignSchemaCatalog(ROOT)
    comparison.sensitive_values = set()
    comparison.templates = lambda: []
    return comparison


def check_api_record_classification():
    for kind in DesignSchemaCatalog(ROOT).api_schemas:
        records = api_comparison({"resourceType": kind}).run()
        (api,) = records
        assert api["category"] == "uncompared"
        assert api["cause"] == {
            "kind": "cloudformation-unsupported",
            "resource_type": kind,
            "implementation_status": "unverified",
        }
        stats = iac_summary(records, "dev", "123456789012", ["s3"])
        assert stats["records"] == dict(
            difference=0, uncompared=1, error=0, matched=0, deferred=0, excluded=0
        )
        assert (
            stats["categories"]["CFn非対応・比較対象外"] == stats["proven_causes"] == 1
        )
        assert (
            stats["categories"]["処理エラー"] == stats["categories"]["原因未確定"] == 0
        )
        artifact = dict(
            version=3,
            ordinary=[],
            judgments=[],
            naming={"names": []},
            **aggregate(records, "dev", "123456789012", ["s3"]),
        )
        assert summary(artifact)["iac_status"] == "partial"
        report = iac_report("dev", "123456789012", ["s3"], records)
        assert "今回の判定: partial" in report and "CFn非対応・比較対象外" in report
        assert (
            "API側の実装状態は未確認" in report
            and "完了" in report
            and "実装scope" in report
        )
        assert "complete match" not in report and "## 処理エラー" not in report
    for resource in ({"resourceType": "Macie.Unknown"}, {}, {"resourceType": []}):
        records = api_comparison(resource).run()
        (failure,) = records
        assert (
            failure["category"] == "error"
            and failure.get("cause", {}).get("kind") != "cloudformation-unsupported"
        )
        artifact = dict(version=3, **aggregate(records, "dev", "123456789012", ["s3"]))
        assert summary(artifact)["iac_status"] == "error"


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
