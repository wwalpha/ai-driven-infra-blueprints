#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
from functools import partial
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import issues.publication as publication
import issues.runner as scan_runner
import model.dependency_index as dependency_index
import model.sources as sources
import support.issues_scan_fixtures as _exports_support_issues_scan_fixtures
import support.issues_scan_fixtures as _retained_fixture_protected_sources
import support.issues_scan_fixtures as _retained_fixture_scan_project
import support.model_reference_fixtures as reference_fixtures
import sync_runtime
import validation.runner as validation_runner
from comparison.deferral import (
    CATEGORIES,
    DesiredPendingDeployExcluded,
    ImportReferenceDeferred,
)
from comparison.inputs import Inputs
from issues.aggregate import MAX_GROUPS, comparison_status, iac_actions
from issues.artifact import scan_exit_code, validate_artifact
from issues.cli import main as issues_main
from issues.inputs import view_text
from issues.records import brief, iac_key
from issues.reports import issue_key, ordinary_report
from model.core import ReferenceResolutionError, resource_row_index
from model.format import split
from model.sources import load_model as real_load
from support.issues_scan_fixtures import (
    Comparison,
    Counter,
    Path,
    aggregate,
    detail_payload,
    expect_error,
    hashlib,
    iac_dataset,
    iac_report,
    iac_summary,
    identifier,
    json,
    patch,
    pytest,
    re,
    render_iac,
    review_payload,
    run,
    summary,
    summary_fixture,
    sys,
    tempfile,
    value_differences,
    write,
)
from support.issues_scan_fixtures import pytestmark as pytestmark
from task_contract_core import contract_snapshot, task_reads, task_snapshot
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.input_cache import input_context
from validation.findings import Findings
from validation.runner import Validator

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

protected_sources = _retained_fixture_protected_sources.protected_sources
scan_project = _retained_fixture_scan_project.scan_project

_CALLBACK_DEFAULT = object()


# Preserve shared fixtures and compatibility exports under their historical names.
entries = _exports_support_issues_scan_fixtures.entries


def _callback_check_mismatch_rendering_fields(left, right, name="Setting", exact=False):
    return value_differences(left, right, name, exact=exact)


def check_mismatch_rendering():
    fields = _callback_check_mismatch_rendering_fields

    role = {"$resource": ["iam", "089"], "$attribute": "RoleName"}
    arn_role = dict(role, **{"$attribute": "Arn"})
    assert fields(role, arn_role) == [
        {"path": "$attribute", "model": "RoleName", "iac": "Arn"}
    ]
    assert [item["path"] for item in fields({"a": 1, "b": 2}, {"a": 3, "b": 4})] == [
        "a",
        "b",
    ]
    assert fields(
        {"Settings": {"Timeout": 1, "Enabled": True}},
        {"Settings": {"Timeout": 2, "Enabled": True}},
    ) == [{"path": "Settings.Timeout", "model": "1", "iac": "2"}]
    assert fields({"a": 1}, {"a": 1, "extra": 2}) == []
    assert fields({"a": 1}, {"a": 1, "extra": 2}, exact=True) == [
        {"path": "extra", "model": "欠落", "iac": "2"}
    ]
    assert fields({"a": None}, {}) == [{"path": "a", "model": "null", "iac": "欠落"}]
    for left, right, model, iac in [
        (None, False, "null", "false"),
        (True, 1, "true", "1"),
        (1, "1", "1", '"1"'),
        (False, "false", "false", '"false"'),
    ]:
        assert fields(left, right)[0] == {"path": "Setting", "model": model, "iac": iac}
    assert fields([1, 2], [2, 1], "Items") == [
        {"path": "Items[0]", "model": "1", "iac": "2"},
        {"path": "Items[1]", "model": "2", "iac": "1"},
    ]
    assert fields([None], [], "Items") == [
        {"path": "Items[0]", "model": "null", "iac": "欠落"}
    ]
    assert fields([], [None], "Items") == [
        {"path": "Items[0]", "model": "欠落", "iac": "null"}
    ]
    tags = [{"Key": "Name", "Value": "one"}]
    reordered = [{"Key": "owner", "Value": "other"}, *tags]
    assert fields(tags, reordered, "Tags") == []
    assert fields(
        tags,
        [{"Key": "owner", "Value": "other"}, {"Key": "Name", "Value": "two"}],
        "Tags",
    ) == [{"path": "Tags[Key=Name].Value", "model": "one", "iac": "two"}]
    assert fields(tags, [], "HostedZoneTags")[0]["iac"] == "欠落"
    assert fields(tags, tags * 2, "Tags") == [
        {"path": "Tags[Key=Name].要素数（キー重複）", "model": "1", "iac": "2"}
    ]
    assert fields(tags * 2, tags * 2, "Tags")[0]["model"] == "2"
    assert fields(
        tags, reordered, "Tags", exact=True
    )  # Exact whole-property arrays retain order/membership.
    long_value = "x" * 1000
    assert fields({"Config": long_value + "A"}, {"Config": long_value + "B"})[0][
        "model"
    ].endswith("A")
    secrets = fields(
        {"Password": "first", "Same": "unchanged"},
        {"Password": "second", "Same": "unchanged"},
    )
    assert secrets == [{"path": "Password", "model": '"<masked>"', "iac": '"<masked>"'}]
    assert "first" not in json.dumps(secrets) and "second" not in json.dumps(secrets)
    assert fields(tags, [{"Key": "Name", "Value": "one"}], "Tags") == []
    secret_tags = fields(
        [{"Key": "SECRET_TOKEN", "Value": "first"}],
        [{"Key": "SECRET_TOKEN", "Value": "second"}],
        "Tags",
    )
    assert (
        secret_tags[0]["model"] == '"<masked>"'
        and secret_tags[0]["iac"] == '"<masked>"'
    )
    assert fields(
        "arn:aws:iam::123456789012:role/a", "arn:aws:iam::123456789012:role/b"
    ) == [
        {
            "path": "Setting",
            "model": "arn:aws:iam::123456789012:role/a",
            "iac": "arn:aws:iam::123456789012:role/b",
        }
    ]
    assert brief("Resource <arn:aws:s3:::example-bucket> | differs") == (
        "Resource &lt;arn:aws:s3:::example-bucket&gt; ／ differs"
    )
    assert (
        fields("{{resolve:secretsmanager:first}}", "{{resolve:secretsmanager:second}}")[
            0
        ]["iac"]
        == '"<masked ARN/secret>"'
    )

    with tempfile.TemporaryDirectory(prefix="mismatch-display-") as directory:
        root = Path(directory)
        path = root / "issues/dev/cde/iac-issues.md"
        base = dict(
            category="difference",
            service="glue",
            resource="019",
            property="Glue.Job.Role",
            reason="value mismatch",
            stack="stack1",
            desired=role,
            actual=arn_role,
            model={"path": "model/dev/cde/glue.properties", "line": 999},
            model_sources=[
                {
                    "path": "model/dev/cde/glue.properties",
                    "line": 999,
                    "key": "desired.row.019.value",
                }
            ],
            iac={"path": "infra/cloudformation/templates/shared.yaml", "line": 999},
        )
        secret = dict(
            base,
            resource="020",
            property="Glue.Job.Password",
            desired="<masked>",
            actual="<masked>",
        )
        long_record = dict(
            base,
            resource="021",
            property="Glue.Job.Config",
            desired=long_value + "A",
            actual=long_value + "B",
        )
        records = [base, secret, long_record]
        original = json.loads(json.dumps(records))
        display = {
            identifier(base): fields(role, arn_role),
            identifier(secret): fields("first", "second", "Glue.Job.Password"),
            identifier(long_record): fields(
                long_record["desired"], long_record["actual"], "Glue.Job.Config"
            ),
        }
        # No source/evidence reads, even when saved line numbers are invalid.
        with patch(
            "issues.reports.evidence",
            side_effect=AssertionError("mismatch evidence read forbidden"),
        ):
            report, report_state = render_iac(
                root, path, "dev", "cde", ["glue"], records, display
            )
        assert "| 要修正 |" in report and "Glue.Job.Role" in report
        assert "修正対象" not in report and "必要な操作" not in report
        assert "相違項目" not in report and "shared.yaml" in report
        assert "glue.properties" not in report and ":999" not in report
        assert all(
            value not in report for value in (long_value + "A", "first", "second")
        )
        entries = report_state["entries"]
        assert Counter(
            json.dumps(entry["record"], sort_keys=True) for entry in entries
        ) == Counter(json.dumps(record, sort_keys=True) for record in original)
        assert {entry["id"] for entry in entries} == {
            iac_key(record) for record in original
        }
        expected_entries = [
            {"id": iac_key(record), "record": record, "retained": False}
            for record in records
        ]
        expected_entries.sort(
            key=lambda entry: (
                entry["record"]["service"],
                entry["id"],
                identifier(entry["record"]),
            )
        )
        assert iac_actions(entries, "dev", "cde") == iac_actions(
            expected_entries, "dev", "cde"
        )
        assert records == original and report_state["value_differences"] == display
        unsafe_display = {
            identifier(secret): [
                {"path": "Password", "model": "first", "iac": "second"}
            ]
        }
        masked_report, masked_data = render_iac(
            root, path, "dev", "cde", ["glue"], [secret], unsafe_display
        )
        assert "first" not in masked_report and "second" not in masked_report
        expect_error(
            lambda: render_iac(
                root, path, "dev", "cde", ["glue"], [base], {identifier(base): [{}]}
            ),
            "malformed",
        )
        duplicates = [
            dict(base, actual=dict(arn_role, **{"$attribute": f"Arn{i}"}))
            for i in range(12)
        ]
        duplicate_display = {
            identifier(record): fields(record["desired"], record["actual"])
            for record in duplicates
        }
        limited, limited_data = render_iac(
            root, path, "dev", "cde", ["glue"], duplicates, duplicate_display
        )
        assert len(limited_data["entries"]) == 12
        assert "相違項目:" not in limited and "省略代表例" not in limited
        no_fields, _ = render_iac(root, path, "dev", "cde", ["glue"], [secret])
        assert "相違項目" not in no_fields and "| 要修正 |" in no_fields


def _callback_summary_scale_cases_with_records_161(
    artifact,
    _default_services,
    _default_display,
    /,
    records,
    services=_CALLBACK_DEFAULT,
    display=_CALLBACK_DEFAULT,
):
    if services is _CALLBACK_DEFAULT:
        services = _default_services
    if display is _CALLBACK_DEFAULT:
        display = _default_display
    return dict(
        artifact,
        services=services,
        **aggregate(records, "dev", "cde", services, display),
    )


def summary_scale_cases():
    artifact = summary_fixture()
    with_records = _bind_framework_callback(
        _callback_summary_scale_cases_with_records_161,
        artifact,
        artifact["services"],
        None,
    )

    records = artifact["iac"]
    original = json.dumps(artifact, sort_keys=True)
    assert artifact["version"] == 6
    entries, actions, fields = iac_dataset(
        records, "dev", "cde", artifact["services"], artifact["iac_display"]
    )
    stats = iac_summary(
        records, "dev", "cde", artifact["services"], artifact["iac_display"]
    )
    signature = sorted(
        (
            group["id"],
            sorted(identifier(entries[i]["record"]) for i in group["members"]),
        )
        for group in actions
    )
    assert (
        hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest()
        == "2c4ff24d8644f2244287b0b238c6f0c73a8445fd59d8e717a647ef5e97b70a0e"
    )
    assert len(entries) == 2193 and len(actions) == 1194
    assert stats["categories"] == {
        "要修正": 100,
        "要対応": 0,
        "要判断": 0,
        "比較未完了": 1,
        "CFn非対応・比較対象外": 0,
        "処理エラー": 93,
        "原因未確定": 1000,
    }
    assert (
        stats["record_count"] == 2193
        and stats["direct_resources"] == 1100
        and stats["proven_causes"] == 1
    )
    assert stats["records"] == dict(
        difference=1100, uncompared=1000, error=93, matched=0, deferred=0, excluded=0
    )
    assert len(stats["groups"]) == MAX_GROUPS and stats["omitted_groups"] > 0
    assert sum(len(action["members"]) for action in actions) == len(records)
    assert sorted(
        entries[i]["record_index"] for action in actions for i in action["members"]
    ) == list(range(len(records)))
    assert {entry["id"] for entry in entries} == {iac_key(record) for record in records}
    with (
        patch.object(
            Comparison, "run", side_effect=AssertionError("detail must not compare")
        ),
        patch(
            "comparison.inputs.load_model",
            side_effect=AssertionError("detail must not parse"),
        ),
    ):
        for category, count in stats["categories"].items():
            assert (
                detail_payload(artifact, "iac_issues", category=category)["total"]
                == count
            )
        pending = detail_payload(artifact, "iac_issues", category="比較未完了")[
            "items"
        ][0]
        assert (
            detail_payload(
                artifact, "iac", issue_id=pending["id"], offset=900, limit=100
            )["total"]
            == 1000
        )
        assert (
            len(
                detail_payload(
                    artifact, "iac", issue_id=pending["id"], offset=900, limit=100
                )["items"]
            )
            == 100
        )
        for section in ("naming", "judgments"):
            total = 1000 if section == "naming" else 100
            ids = [
                item["id"]
                for offset in range(0, total, 50)
                for item in detail_payload(artifact, section, offset, 50)["items"]
            ]
            assert len(set(ids)) == total
        expect_error(
            lambda: detail_payload(artifact, "iac", issue_id="ISSUE-absent"),
            "not found",
        )
        expect_error(
            lambda: detail_payload(artifact, "naming", category="要判断"), "IaC filters"
        )
        expect_error(lambda: detail_payload(artifact, "iac", offset=-1), "range")
    report = iac_report(
        "dev",
        "cde",
        artifact["services"],
        records,
        artifact["iac_display"],
        stamp="fixed",
    )
    assert {group["category"] for group in stats["groups"]} == {
        category for category, count in stats["categories"].items() if count
    }
    stdout = json.dumps(
        review_payload(artifact, "/tmp/fixture-scan.json"), ensure_ascii=False
    )
    assert (
        stats["group_count"] == 1194
    )  # Unknown causes remain separate despite identical prose.
    assert stats["omitted_issues"] == 1178 and stats["omitted_records"] == 1178
    assert stats["omitted_categories"] == {
        "要修正": 87,
        "要対応": 0,
        "要判断": 0,
        "比較未完了": 0,
        "CFn非対応・比較対象外": 0,
        "処理エラー": 92,
        "原因未確定": 999,
    }
    assert stats["omitted_record_categories"] == dict(
        difference=1086, uncompared=0, error=92
    )
    assert "表示20件／全1194件／省略1174件" in report and "error 93件" in report
    assert len(re.findall(r"^\| ISSUE-", report, re.M)) == 20
    assert "### ISSUE-" not in report and "必要な操作" not in report
    ordered = sorted(
        artifact["iac_issues"], key=lambda item: item["compact"]["report_order"]
    )
    assert re.findall(r"^\| (ISSUE-[^ ]+)", report, re.M) == [
        item["id"] for item in ordered[:20]
    ]
    assert "index" not in json.loads(stdout)["iac_summary"]
    assert report == iac_report(
        "dev", "cde", artifact["services"], records, stamp="fixed", artifact=artifact
    )
    all_issues = [
        item
        for offset in range(0, 1194, 50)
        for item in detail_payload(artifact, "iac_issues", offset, 50)["items"]
    ]
    assert {item["id"] for item in all_issues} == {item["id"] for item in actions}
    omitted = ordered[20]
    assert omitted["id"] not in report
    assert detail_payload(artifact, "iac", issue_id=omitted["id"])["total"] == len(
        omitted["members"]
    )
    # Exercise the actual detail CLI for every Issue and an omitted Issue's members.
    with tempfile.TemporaryDirectory() as temporary:
        artifact_path = Path(temporary) / "scan.json"
        artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
        for section, extra, total in (
            ("iac_issues", [], 1194),
            ("iac", ["--issue-id", omitted["id"]], len(omitted["members"])),
        ):
            output = StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "issues_scan.py",
                        "detail",
                        "--artifact",
                        str(artifact_path),
                        "--section",
                        section,
                        "--limit",
                        "2000",
                        *extra,
                    ],
                ),
                redirect_stdout(output),
            ):
                assert issues_main() == 0
            result = json.loads(output.getvalue())
            assert result["total"] == len(result["items"]) == total
    # Rendering/order and IDs are deterministic; source lists are never mutated.
    reverse = iac_report(
        "dev",
        "cde",
        artifact["services"][::-1],
        records[::-1],
        artifact["iac_display"],
        stamp="fixed",
    )
    assert reverse == report
    assert "2026-10-08 09:00:00 Asia/Tokyo" in iac_report(
        "dev", "cde", artifact["services"], [], stamp=artifact["executed_at"]
    )
    again_entries, again_actions, _ = iac_dataset(
        records[::-1], "dev", "cde", artifact["services"], artifact["iac_display"]
    )
    assert [group["id"] for group in again_actions] == [
        group["id"] for group in actions
    ]
    assert [
        [again_entries[i]["id"] for i in group["members"]] for group in again_actions
    ] == [[entries[i]["id"] for i in group["members"]] for group in actions]
    assert json.dumps(artifact, sort_keys=True) == original
    # Matching/excluded records are preserved but never become independent Issues.
    extra = [
        dict(records[0], category="matched"),
        dict(records[1], category="excluded"),
    ]
    assert (
        iac_summary(records + extra, "dev", "cde", artifact["services"])["record_count"]
        == 2195
    )
    assert (
        iac_summary(records + extra, "dev", "cde", artifact["services"])["issue_count"]
        == 1194
    )
    # Secrets stay masked; ordinary ARNs remain in artifact/detail, not field-free Markdown.
    secret = dict(
        records[2000],
        property="Glue.Job.Settings",
        desired={
            "Password": "first",
            "Role": "arn:aws:iam::123456789012:role/a",
            "Value": "prefix-confidential-A",
        },
        actual={
            "Password": "second",
            "Role": "arn:aws:iam::123456789012:role/b",
            "Value": "prefix-confidential-B",
        },
    )
    safe = Comparison.__new__(Comparison)
    safe.sensitive_values = {"confidential"}
    hidden = dict(
        secret,
        desired=safe.redacted(secret["desired"]),
        actual=safe.redacted(secret["actual"]),
    )
    hidden_fields = {
        identifier(hidden): value_differences(
            secret["desired"],
            secret["actual"],
            secret["property"],
            redact=safe.redacted,
        )
    }
    secret_artifact = with_records([hidden], display=hidden_fields)
    for output in (
        json.dumps(secret_artifact),
        json.dumps(detail_payload(secret_artifact, "iac")),
    ):
        assert all(word not in output for word in ("first", "second", "confidential"))
        assert "arn:aws:iam::123456789012:role/a" in output
        assert "arn:aws:iam::123456789012:role/b" in output
    report = iac_report("dev", "cde", artifact["services"], [hidden], hidden_fields)
    assert all(word not in report for word in ("first", "second", "confidential"))
    assert "arn:aws:" not in report
    message = "Resource arn:aws:iam::123456789012:role/a differs from IaC"
    ordinary = ordinary_report(
        Path("/synthetic"),
        dict(
            secret_artifact,
            environment="dev",
            target="cde",
            ordinary=[dict(service=artifact["services"][0], message=message)],
            unverified=[],
            processing_errors=[],
            information=[],
            warnings=[],
        ),
    )
    assert message in ordinary
    for category, expected in [
        ("matched", "complete match"),
        ("uncompared", "partial"),
        ("excluded", "no compared records"),
        ("error", "error"),
    ]:
        current = dict(records[0], category=category)
        assert summary(with_records([current]))["iac_status"] == expected
        assert "今回の判定: " + expected in iac_report(
            "dev", "cde", artifact["services"], [current]
        )
    assert summary(with_records([]))["iac_status"] == "no compared records"
    # Limits are presentation-only; all IDs and members remain retrievable.
    base = dict(
        records[2000],
        service="glue",
        category="difference",
        reason="value mismatch",
        stack="shared",
        iac={"path": "infra/shared.yaml"},
        resource="shared",
        property="Setting",
    )
    independent = [dict(base, resource=str(i)) for i in range(20)]
    report20 = iac_report("dev", "cde", ["glue"], independent)
    assert len(re.findall(r"^\| ISSUE-", report20, re.M)) == 20
    assert "### ISSUE-" not in report20 and "／省略" not in report20
    common = [
        dict(
            base,
            resource=str(i),
            service="glue" if i % 2 else "s3",
            cause={
                "kind": "template-missing",
                "path": "infra/shared.yaml",
                "relationship": "direct",
            },
        )
        for i in range(50)
    ]
    small = with_records(common, ["glue", "s3"])
    units = detail_payload(small, "iac_issues")["items"]
    assert len(units) == 1 and len(units[0]["members"]) == 50
    pages = [
        item
        for offset in range(0, 50, 10)
        for item in detail_payload(small, "iac", offset, 10, issue_id=units[0]["id"])[
            "items"
        ]
    ]
    assert len(pages) == 50 and {item["record_index"] for item in pages} == set(
        range(50)
    )
    compact = iac_summary(common, "dev", "cde", small["services"])["groups"][0]
    assert len(compact["examples"]) == 10 and compact["omitted_examples"] == 40
    twelve = with_records(common[:12], small["services"])
    assert (
        len(detail_payload(twelve, "iac", 10, 10, issue_id=units[0]["id"])["items"])
        == 2
    )
    expect_error(
        lambda: iac_report("dev", "cde", ["glue"], common), "outside selected services"
    )
    left, right = (
        {f"field{i}": i for i in range(12)},
        {f"field{i}": i + 1 for i in range(12)},
    )
    record = dict(base, desired=left, actual=right)
    shown = {identifier(record): value_differences(left, right, "Setting")}
    twelve_fields = with_records([record], ["glue"], shown)
    report12 = iac_report("dev", "cde", ["glue"], [record], shown)
    assert "相違項目:" not in report12 and "省略相違フィールド" not in report12
    assert (
        len(detail_payload(twelve_fields, "iac")["items"][0]["value_differences"]) == 12
    )
    diagnostic = dict(
        path="field",
        model="model",
        iac="iac",
        identity="unknown",
        allowed_forms="Arn",
        format="unknown",
        reason="unresolved",
    )
    deferred = dict(
        record,
        category="uncompared",
        deferred_children=[
            dict(property=f"child{i}", reason="unresolved", category="uncompared")
            for i in range(12)
        ],
        reference_diagnostics=[dict(diagnostic, path=f"field{i}") for i in range(12)],
    )
    example = iac_summary([deferred], "dev", "cde", ["glue"])["groups"][0]["examples"][
        0
    ]
    assert (
        len(example["deferred_children"]) == len(example["reference_diagnostics"]) == 10
    )
    assert (
        example["omitted_deferred_children"] == example["omitted_reference_fields"] == 2
    )
    # Empty/single/large ordinary lists and compact diagnostic channels use synthetic inputs.
    empty = iac_report("dev", "cde", ["glue"], [], stamp="fixed")
    assert len(empty.splitlines()) == 8 and "## " not in empty and "| ---" not in empty
    assert "分類:" not in empty and "omitted" not in empty
    single = iac_report("dev", "cde", ["glue"], [base], stamp="fixed")
    assert len(re.findall(r"^\| ISSUE-", single, re.M)) == 1
    assert "value mismatch" in single and "／省略" not in single
    current = dict(
        artifact,
        environment="dev",
        target="cde",
        services=["glue"],
        ordinary=[],
        information=[{"code": "internal", "details": {"hidden_metadata": True}}],
        warnings=[],
        unverified=[],
        processing_errors=[],
    )
    root = Path("/synthetic")
    ordinary_empty = ordinary_report(root, current)
    assert "未解決issueなし" in ordinary_empty and "### " not in ordinary_empty
    assert "## 情報" not in ordinary_empty and "hidden_metadata" not in ordinary_empty
    finding = dict(
        service="glue",
        key="formal-issue",
        resource="001",
        property="Glue.Job.Role",
        message="参照先が不正",
        source={"path": "model/dev/cde/glue.properties", "line": 12},
    )
    current["ordinary"] = [finding]
    one = ordinary_report(root, current)
    assert "### glue" in one and f"<!-- issue-id: {issue_key(root, finding)} -->" in one
    assert "001 / Glue.Job.Role: 参照先が不正" in one
    assert (
        "[model/dev/cde/glue.properties:12](../../../model/dev/cde/glue.properties)"
        in one
    )
    for source in (
        "model/dev/cde/glue.properties",
        str(root / "model/dev/cde/glue.properties"),
    ):
        current["ordinary"] = [dict(finding, source=source)]
        assert (
            "[model/dev/cde/glue.properties](../../../model/dev/cde/glue.properties)"
            in ordinary_report(root, current)
        )
    current["ordinary"] = [dict(finding, source="/outside/glue.properties")]
    assert "根拠:" not in ordinary_report(root, current)
    current["ordinary"] = [
        dict(finding, key=str(i), message=f"問題{i}") for i in range(1001)
    ]
    many = ordinary_report(root, current)
    assert many.count("<!-- issue-id:") == 1001
    assert all(issue_key(root, item) in many for item in current["ordinary"])
    failure = dict(
        diagnostic_id="internal-failure-id",
        service="glue",
        resource="001",
        phase="mechanical.models",
        message="モデル読取失敗",
        source_path="model/dev/cde/glue.properties",
    )
    current["ordinary"] = []
    current["processing_errors"] = [failure]
    current["unverified"] = [dict(failure, complete=False)]
    current["warnings"] = [
        dict(
            service="glue",
            resource="001",
            property="Glue.Job.Role",
            function="Fn::Sub",
            pointer="/Role",
            code="json.intrinsic.unresolved",
            reason="参照値が未確定",
            source={"path": "model/dev/cde/glue.properties", "line": 12},
            metadata={"hidden_metadata": True},
        )
    ]
    before_notices = deepcopy(current)
    notices = ordinary_report(root, current)
    assert "未完了" in notices and "AWS未検証" in notices
    assert notices.count("モデル読取失敗") == 1 and "## 未検証範囲" not in notices
    assert "## 処理エラー" in notices and "## 警告" in notices
    assert all(
        text in notices
        for text in (
            "glue",
            "001",
            "mechanical.models",
            "Fn::Sub",
            "/Role",
            "参照値が未確定",
            "glue.properties:12",
        )
    )
    assert all(
        text not in notices
        for text in (
            "internal-failure-id",
            "hidden_metadata",
            "<!-- issue-id:",
            "{'",
            '{"',
        )
    )
    assert detail_payload(current, "unverified")["items"] == current["unverified"]
    assert detail_payload(current, "processing_errors")["items"] == [failure]
    assert detail_payload(current, "warnings")["items"] == current["warnings"]
    lint_warning = dict(
        code="cfn_lint.W3001",
        service="glue",
        message="警告の根拠",
        diagnostic=dict(
            Filename=str(root / "infra/job.yaml"),
            Location=dict(
                Start=dict(LineNumber=7),
                Path=["Resources", "Job", "Properties", "Role"],
            ),
        ),
    )
    current["warnings"].append(lint_warning)
    lint_report = ordinary_report(root, current)
    assert "Resources/Job/Properties/Role" in lint_report
    assert "[infra/job.yaml:7](../../../infra/job.yaml)" in lint_report
    assert detail_payload(current, "warnings")["items"][-1] == lint_warning
    current["warnings"].pop()
    assert current == before_notices and notices == ordinary_report(root, current)
    current["unverified"].append(
        dict(service="glue", check="reference", reason="別検査は未実施")
    )
    assert "## 未検証範囲" in ordinary_report(root, current)
    assert "別検査は未実施" in ordinary_report(root, current)
    view_failure = dict(
        code="mechanical.view_read",
        service="glue",
        path="docs/designs/dev/cde/glue.md",
        phase="review-prose",
        exception="UnicodeDecodeError",
        message="saved View could not be read; dependent checks not run",
    )
    current["processing_errors"] = [view_failure]
    current["unverified"] = [dict(view_failure, code="mechanical.view_unverified")]
    view_report = ordinary_report(root, current)
    assert view_report.count(view_failure["message"]) == 1
    assert "## 未検証範囲" not in view_report and "未完了" in view_report
    assert "[docs/designs/dev/cde/glue.md]" in view_report
    assert (
        detail_payload(current, "unverified")["items"][0]["code"]
        == "mechanical.view_unverified"
    )
    coverage = dict(
        artifact, service_results=[dict(service="glue", status="unverified")]
    )
    incomplete_report = iac_report(
        "dev", "cde", ["glue"], [], stamp="fixed", artifact=coverage
    )
    assert "未検証Service: glue" in incomplete_report
    print(
        f"IaC bounded output: PASS ({len(report.splitlines())} lines; stdout {len(stdout)} characters; 2193 records / 1194 action units)"
    )


check_summary_scale = summary_scale_cases


def add_task_during_mechanical(root, **kwargs):
    contract_snapshot(root)
    (root / "tasks/other.md").write_text(
        "## Task contract\n- Task type: `migration`\n- Task status: `completed`\n"
    )


def check_mechanical_accepts_contract_catalog_changes(tmp_path):
    validator = Validator(tmp_path, set())
    with (
        _exports_support_issues_scan_fixtures.task(tmp_path, ["s3"]),
        patch.object(
            scan_runner,
            "module",
            return_value=SimpleNamespace(Validator=Mock(return_value=validator)),
        ),
        patch.multiple(
            validator,
            **dict.fromkeys(
                (
                    "check_project_topology",
                    "check_validation_scope",
                    "check_model_files",
                    "check_iac_selection",
                ),
                Mock(return_value=None),
            ),
        ),
        patch.object(
            validator,
            "check_scoped_designs",
            side_effect=partial(add_task_during_mechanical, tmp_path),
        ),
    ):
        assert scan_runner.mechanical(tmp_path, {("dev", "123456789012", "s3")})[
            :2
        ] == ([], 0)


def check_comparison_input_tracking_is_report_only(tmp_path):
    from_report = scan_runner.Comparison.__new__(scan_runner.Comparison)
    from_report.inputs = set()
    from_report.model_reads = SimpleNamespace(contents={tmp_path / "input": b"first"})
    from_report.retain_reads()
    from_report.model_reads.contents[tmp_path / "input"] = b"changed"
    from_report.retain_reads()
    with patch.object(
        Path, "read_bytes", side_effect=AssertionError("tracking must not read bytes")
    ):
        from_report.track(tmp_path / "absent")
    assert from_report.inputs == {tmp_path / "input", tmp_path / "absent"}
    ordinary = SimpleNamespace(inputs=set(), read_hashes={}, root=tmp_path)
    Inputs.retain_hash(ordinary, tmp_path / "input", "first")
    with pytest.raises(ValueError, match="contradictory input observations"):
        Inputs.retain_hash(ordinary, tmp_path / "input", "changed")


def change_scan_input(comparison, path, validator, *args, **kwargs):
    comparison.track(path)
    path.write_bytes(b"changed")
    comparison.track(path)
    comparison.model_reads.contents[path] = b"changed"
    comparison.retain_reads()
    return mechanical_result(validator, *args, **kwargs)


@pytest.mark.parametrize(
    "input_name",
    [
        "docs/designs/dev/team/s3.md",
        "model/dev/team/s3.properties",
        "infra/cloudformation/templates/s3.yaml",
    ],
)
def check_scan_accepts_input_changes(tmp_path, input_name):
    path = tmp_path / input_name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"original")
    comparison = scan_runner.Comparison.__new__(scan_runner.Comparison)
    comparison.environment, comparison.directory = "dev", "team"
    comparison.root, comparison.inputs, comparison.read_hashes = tmp_path, set(), {}
    comparison.model_reads = SimpleNamespace(contents={path: b"original"})
    comparison.view_errors, comparison.warnings, comparison.results = {}, [], []
    comparison.catalog, comparison.metrics, comparison.display_differences = (
        None,
        {},
        {},
    )
    comparison.models = {"s3": SimpleNamespace(values={})}
    comparison.redacted, comparison.run = (
        Mock(side_effect=deepcopy),
        Mock(return_value=[]),
    )
    validator = SimpleNamespace(
        checks=1,
        findings=Findings(tmp_path),
    )
    lint = dict(
        jobs=[],
        coverage=[],
        status="checked",
        **{
            name: []
            for name in (
                "ordinary",
                "judgments",
                "warnings",
                "information",
                "unverified",
                "processing_errors",
            )
        },
    )
    with (
        patch.object(scan_runner, "Comparison", return_value=comparison),
        patch.object(
            scan_runner,
            "mechanical",
            side_effect=partial(change_scan_input, comparison, path, validator),
        ),
        patch.object(scan_runner, "naming_materials", return_value=({"names": []}, [])),
        patch.object(
            scan_runner,
            "human_confirmations",
            return_value=dict(
                version=2, environment="dev", target="team", confirmations=[]
            ),
        ),
        patch.object(scan_runner, "target_services", return_value=["s3"]),
        patch("issues.cfn_lint.run_lint", return_value=lint) as lint_call,
    ):
        artifact = scan_runner.scan(tmp_path, "dev", "team", ["s3"])
    assert not artifact["processing_errors"] and comparison.read_hashes == {}
    assert comparison.run.call_count == lint_call.call_count == 1
    assert path.read_bytes() == b"changed"


def _check_view_read_failure_policy_service(instance):
    assert instance.scope == {("dev", "team", "sqs")}
    instance.check(False, "independent sqs diagnostic")
    instance.check_design_links({})


def _callback_check_view_read_failure_policy_ownership(bad, /, instance, paths):
    if bad in paths:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad input")
    return {}, set(), {}, {}


def _callback_check_view_read_failure_policy_generation(generated, /, instance):
    generated.append(instance.scope)
    instance.findings.result(
        "framework.generated-service-model", instance.scope
    ).status = "PASS"


def check_view_read_failure_policy(tmp_path):
    real_load_model = sources.load_model
    assert sync_runtime.load_model is real_load_model

    root = tmp_path
    docs = root / "docs/designs/dev/team"
    docs.mkdir(parents=True)
    bad, good = docs / "s3.md", docs / "sqs.md"
    bad.write_bytes(b"\xff private body")
    good.write_text("independent view")
    comparison = SimpleNamespace(
        root=root,
        inputs=set(),
        read_hashes={},
        view_errors={},
        unreadable_inputs=False,
        services=["s3", "sqs"],
        environment="dev",
        directory="team",
    )
    assert view_text(comparison, bad, phase="view-preflight") is None
    assert view_text(comparison, good, phase="view-preflight") == "independent view"
    assert comparison.view_errors[bad]["exception"] == "UnicodeDecodeError"
    assert "private body" not in json.dumps(comparison.view_errors[bad])
    cache = SimpleNamespace(
        common="common",
        service_key=lambda entry: str(entry),
        load=lambda _: None,
        save=Mock(),
    )
    validator = Validator(
        root, {("dev", "team", "s3"), ("dev", "team", "sqs")}, workers=1
    )
    validator.cache = cache
    generated = []
    source_checks = Mock(
        return_value=SimpleNamespace(
            errors=[],
            warnings=[],
            reference_errors=[],
            diagnostics=[],
            diagnostic_errors={},
            error_contexts={},
            processing_errors=[],
            unverified=[],
            information=[],
            checks=7,
        )
    )
    ownership = _bind_framework_callback(
        _callback_check_view_read_failure_policy_ownership, bad
    )
    generation = _bind_framework_callback(
        _callback_check_view_read_failure_policy_generation, generated
    )
    service = _check_view_read_failure_policy_service
    with (
        patch.object(Validator, "check_design_service_ownership", ownership),
        patch.object(Validator, "check_stack_designs", return_value={}),
        patch.object(Validator, "check_generated_service_models", generation),
        patch.object(Validator, "check_designs", service),
        patch.object(Validator, "check_observed_values"),
        patch(
            "model.sources.load_model",
            return_value=SimpleNamespace(authoritative={}, warnings=[]),
        ),
        patch("model.validation.check_model_inputs", source_checks),
    ):
        validator.check_scoped_designs(view_errors=comparison.view_errors)
        assert "independent sqs diagnostic" in validator.errors
        assert source_checks.call_count == 1 and generated == [{("dev", "team", "sqs")}]
        assert validator.checks >= 8 and validator.findings.unverified
        assert not validator.service_cache_pending
        assert (
            validator.findings.result("design.service", {("dev", "team", "s3")}).status
            == "NOT_RUN"
        )
        assert (
            validator.findings.result(
                "framework.generated-service-model", validator.scope
            ).status
            == "NOT_RUN"
        )
        default = Validator(root, validator.scope, workers=1)
        default.check_scoped_designs()
        assert any(
            error["exception"] == "UnicodeDecodeError"
            for error in default.findings.processing_errors
        )
        assert any("independent sqs diagnostic" in error for error in default.errors)
    assert sources.load_model is sync_runtime.load_model is real_load_model
    bad.write_bytes(b"changed bytes")
    assert view_text(comparison, bad, phase="review-prose") == "changed bytes"
    with patch.object(
        Path, "read_bytes", side_effect=PermissionError("private exception body")
    ):
        assert view_text(comparison, good, phase="review-prose") is None


def dependency_read_failure(bad, original, path):
    if path == bad:
        raise PermissionError("private dependency body")
    return original(path)


def compare_with_unreadable_view(comparison, bad, source, validator, dependent):
    if dependent:
        assert (
            view_text(comparison, bad, phase="design-links-reference", consumer=source)
            is None
        )
        # Repeated consumers are deduplicated while the independent service continues.
        view_text(comparison, bad, phase="design-links-reference", consumer=source)
        validator.findings.unverified.append(
            dict(code="design.links_unavailable", service="sqs")
        )
    return [
        dict(
            category="difference",
            service="cloudwatch-logs",
            resource="001",
            property="Setting",
            reason="value mismatch",
            desired=1,
            actual=2,
        )
    ]


@pytest.mark.parametrize(
    "failure", ["utf8", "missing", "permission", "selected-missing"]
)
def check_dependency_view_failure_branches(tmp_path, monkeypatch, failure):
    docs = tmp_path / "docs/designs/dev/team"
    docs.mkdir(parents=True)
    dependent = failure != "selected-missing"
    bad, source = docs / ("s3.md" if dependent else "sqs.md"), docs / "sqs.md"
    if dependent:
        source.write_text("")
    (docs / "cloudwatch-logs.md").write_text("")
    (tmp_path / "project.json").write_text("{}")
    if failure not in ("missing", "selected-missing"):
        bad.write_bytes(b"\xff private dependency body")
    if failure == "permission":
        monkeypatch.setattr(
            Path,
            "read_bytes",
            _bind_framework_callback(dependency_read_failure, bad, Path.read_bytes),
        )
    comparison = SimpleNamespace(
        root=tmp_path,
        environment="dev",
        directory="team",
        services=["sqs", "cloudwatch-logs"],
        inputs={tmp_path / "project.json"},
        read_hashes={},
        view_errors={},
        unreadable_inputs=False,
        warnings=[],
        catalog=None,
        models={},
        results=[],
        metrics={},
        display_differences={},
        redacted=lambda value, prop="": value,
    )
    comparison.track = partial(Inputs.track, comparison)
    comparison.retain_hash = partial(Inputs.retain_hash, comparison)
    cache = SimpleNamespace(
        common=None, common_key=Mock(return_value="common"), save=Mock()
    )
    validator = SimpleNamespace(
        checks=3,
        check=Mock(),
        cache=cache,
        service_cache_pending=[("pending", 3)] if dependent else [],
        findings=Findings(tmp_path),
    )
    validator.finalize_service_cache = partial(
        Validator.finalize_service_cache, validator
    )
    comparison.run = partial(
        compare_with_unreadable_view, comparison, bad, source, validator, dependent
    )
    lint = dict(
        jobs=[dict(completed=True)],
        coverage=[],
        status="checked",
        **{
            name: []
            for name in (
                "ordinary",
                "judgments",
                "warnings",
                "information",
                "unverified",
                "processing_errors",
            )
        },
    )
    with (
        patch.object(scan_runner, "Comparison", return_value=comparison),
        patch.object(
            scan_runner, "mechanical", side_effect=partial(mechanical_result, validator)
        ),
        patch.object(scan_runner, "naming_materials", return_value=({"names": []}, [])),
        patch.object(
            scan_runner,
            "human_confirmations",
            return_value=dict(
                version=2, environment="dev", target="team", confirmations=[]
            ),
        ),
        patch.object(scan_runner, "target_services", return_value=["s3"]),
        patch("issues.cfn_lint.run_lint", return_value=lint) as lint_call,
    ):
        artifact = scan_runner.scan(tmp_path, "dev", "team", comparison.services)
    errors = artifact["processing_errors"]
    if dependent:
        assert len(errors) == 1 and errors[0]["code"] == "mechanical.view_read"
        assert (
            errors[0]["exception"]
            == {
                "utf8": "UnicodeDecodeError",
                "missing": "FileNotFoundError",
                "permission": "PermissionError",
            }[failure]
        )
        assert errors[0]["phase"] == "design-links-reference" and errors[0][
            "consumers"
        ] == ["docs/designs/dev/team/sqs.md"]
        assert any(
            e["code"] == "design.links_unavailable" and e["service"] == "sqs"
            for e in artifact["unverified"]
        )
    else:
        assert not errors
        assert any(
            e["code"] == "mechanical.view_missing" and e["service"] == "sqs"
            for e in artifact["unverified"]
        )
    assert (
        artifact["iac"][0]["service"] == "cloudwatch-logs"
        and artifact["cfn_lint"]["jobs"][0]["completed"]
    )
    assert lint_call.call_count == 1 and not cache.save.called
    assert (
        artifact["validation_status"] == ("ERROR" if dependent else "INCOMPLETE")
        and artifact["checks"] == 3
    )
    assert "private dependency body" not in json.dumps(artifact)


def interrupt_comparison(comparison, exception):
    comparison.sensitive_values.add("exception-secret")
    for index in range(5):
        comparison.record(
            "difference",
            "s3",
            str(index),
            "Setting",
            "value mismatch",
            desired=1,
            actual=2,
        )
    raise exception("interrupted exception-secret")


@pytest.mark.parametrize(
    "exception",
    [
        ReferenceResolutionError,
        OSError,
        ValueError,
        KeyError,
        ImportError,
        TypeError,
        RuntimeError,
    ],
)
def check_scan_exception_classification(tmp_path, exception):
    comparison = Comparison.__new__(Comparison)
    comparison.root, comparison.environment, comparison.directory = (
        tmp_path,
        "dev",
        "team",
    )
    comparison.sensitive_values, comparison.results, comparison.warnings = set(), [], []
    comparison.view_errors, comparison.read_hashes, comparison.metrics = {}, {}, {}
    comparison.models, comparison.display_differences, comparison.catalog = {}, {}, None
    comparison.source = Mock(return_value=None)
    comparison.track = Mock()
    validator = SimpleNamespace(
        checks=1,
        findings=Findings(tmp_path),
        finalize_service_cache=Mock(),
    )
    lint = dict(
        jobs=[],
        coverage=[],
        status="not_applicable",
        **{
            name: []
            for name in (
                "ordinary",
                "judgments",
                "warnings",
                "information",
                "unverified",
                "processing_errors",
            )
        },
    )
    with (
        patch.object(scan_runner, "Comparison", return_value=comparison),
        patch.object(scan_runner, "view_text", return_value=None),
        patch.object(
            scan_runner, "mechanical", side_effect=partial(mechanical_result, validator)
        ),
        patch.object(scan_runner, "naming_materials", return_value=({"names": []}, [])),
        patch.object(
            scan_runner,
            "human_confirmations",
            return_value=dict(
                version=2, environment="dev", target="team", confirmations=[]
            ),
        ),
        patch.object(scan_runner, "target_services", return_value=["s3"]),
        patch("issues.cfn_lint.run_lint", return_value=lint),
        patch.object(
            comparison,
            "run",
            side_effect=partial(interrupt_comparison, comparison, exception),
        ) as invoked,
    ):
        artifact = scan_runner.scan(tmp_path, "dev", "team", ["s3"])
    invoked.assert_called_once_with()
    assert artifact["iac"][:5] == comparison.results and len(artifact["iac"]) == 6
    tail = artifact["iac"][-1]
    category = "uncompared" if exception is ReferenceResolutionError else "error"
    assert tail["category"] == category and tail["comparison_incomplete"]
    status = summary(artifact)
    assert status["iac_differences"] == 5 and status["comparison_incomplete"]
    assert status["iac_status"] == ("partial" if category == "uncompared" else "error")
    report = iac_report("dev", "team", ["s3"], artifact["iac"], artifact["iac_display"])
    assert "比較途中終了" in report
    assert "exception-secret" not in json.dumps(artifact) + report + json.dumps(
        detail_payload(artifact, "iac")
    )
    assert sum(len(group["members"]) for group in artifact["iac_issues"]) == 6
    assert any(
        warning["code"] == "reference.unresolved" for warning in artifact["warnings"]
    ) == (exception is ReferenceResolutionError)
    assert any(
        item["code"] == "iac.comparison_unverified" for item in artifact["unverified"]
    )
    assert any(
        result["check_id"] == "iac.comparison"
        and result["status"] == "NOT_RUN"
        and not result["complete"]
        for result in artifact["check_results"]
    )


def mechanical_result(validator, *args, **kwargs):
    kwargs["validator_out"].append(validator)
    return [], 1, ""


def interrupted_mechanical(root, scope, *, validator_out, **kwargs):
    validator = Validator(root, scope)
    validator_out.append(validator)
    validator.check(False, "model/dev/123456789012/s3.properties: retained diagnostic")
    raise RuntimeError("interrupted mechanical stage")


def retained_mechanical(original, *args, **kwargs):
    result = original(*args, **kwargs)
    kwargs["validator_out"][0].check(
        False, "model/dev/123456789012/s3.properties: retained diagnostic"
    )
    return result


def diagnostic_mechanical(validator, *args, validator_out, **kwargs):
    validator_out.append(validator)
    return validator.errors, validator.checks, "retained machine output"


def fail_diagnostic(original, failed, value, *args, **kwargs):
    if value == failed or (
        failed == "reference-message" and isinstance(value, list) and "REF_BAD" in value
    ):
        raise ValueError("injected diagnostic conversion failure")
    return original(value, *args, **kwargs)


@pytest.mark.parametrize(
    "stage",
    [
        "references",
        "reference-message",
        "candidate-message",
        "normal",
    ],
)
def check_reference_diagnostic_isolation(tmp_path, stage):
    _exports_support_issues_scan_fixtures.fixture(tmp_path, services=("s3",))
    scope = {("dev", "123456789012", "s3")}
    validator = Validator(tmp_path, scope)
    for code in ("REF_FIRST", "REF_BAD", "REF_LAST"):
        validator.findings.warn(
            dict(
                category="MODEL_NEEDS_FIX",
                code=code,
                model=str(tmp_path / "model/dev/123456789012/s3.properties"),
                message=code,
                fixModels=[str(tmp_path / "model/dev/123456789012/s3.properties")],
            )
        )
    messages = [
        "model/dev/123456789012/s3.properties: " + label
        for label in ("first diagnostic", "bad diagnostic", "last diagnostic")
    ]
    for message in [*messages, messages[0]]:
        validator.check(False, message)
    view = tmp_path / "docs/designs/dev/123456789012/s3.md"
    view.write_text(
        view.read_text(encoding="utf-8") + "\nRetained review prose\n",
        encoding="utf-8",
    )
    report = tmp_path / "issues/dev/123456789012/issues.md"
    write(report, "# Issues\n\n### s3\n\n1. Keep existing Issue\n")
    report_before = report.read_bytes()
    expected_references = json.loads(
        json.dumps(
            scan_runner.reference_issues(
                validator.findings,
                Comparison(tmp_path, "dev", "123456789012", ["s3"]),
                ["s3"],
            )
        )
    )
    artifact_path = tmp_path.parent / "reference-failure.json"
    order = Mock()
    lint_result = dict(
        status="checked",
        completed=True,
        decode_complete=True,
        matches=[
            dict(Rule={"Id": "W3001"}, Level="Warning", Message="retained lint warning")
        ],
        unverified=[],
        processing_errors=[],
    )
    with (
        patch.object(
            scan_runner,
            "mechanical",
            side_effect=partial(diagnostic_mechanical, validator),
        ),
        patch.object(
            scan_runner, "reference_issues", wraps=scan_runner.reference_issues
        ) as references,
        patch.object(
            scan_runner,
            "identifier",
            side_effect=partial(
                fail_diagnostic,
                identifier,
                "reference-message"
                if stage == "reference-message"
                else validator.findings.error_contexts[4].identity
                if stage == "candidate-message"
                else None,
            ),
        ),
        patch.object(
            scan_runner, "naming_materials", wraps=scan_runner.naming_materials
        ) as naming,
        patch.object(
            scan_runner, "review_materials", wraps=scan_runner.review_materials
        ) as review,
        patch.object(
            Comparison, "run", autospec=True, side_effect=Comparison.run
        ) as compare,
        patch.object(
            scan_runner._imports_issues_cfn_lint,
            "run_lint",
            wraps=scan_runner._imports_issues_cfn_lint.run_lint,
        ) as lint,
        patch("issues.cfn_lint.lint_session", return_value=nullcontext(None)),
        patch(
            "issues.cfn_lint.validate_template", return_value=lint_result
        ) as raw_lint,
        patch.object(
            sys,
            "argv",
            [
                "issues",
                "--repository-root",
                str(tmp_path),
                "scan",
                "--environment",
                "dev",
                "--target-directory",
                "123456789012",
                "--service",
                "s3",
                "--artifact",
                str(artifact_path),
            ],
        ),
    ):
        for name, mock in (
            ("references", references),
            ("naming", naming),
            ("review", review),
            ("compare", compare),
            ("lint", lint),
        ):
            order.attach_mock(mock, name)
        if stage == "references":
            references.side_effect = ValueError("injected reference failure")
        assert issues_main() == (1 if stage == "normal" else 2)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    validate_artifact(artifact)
    assert artifact["version"] == 6
    assert artifact["validation_status"] == ("FAIL" if stage == "normal" else "ERROR")
    phases = {
        "references": "diagnostics.references",
        "reference-message": "diagnostics.references",
        "candidate-message": "diagnostics.issue-candidates",
    }
    if stage != "normal":
        phase = phases[stage]
        assert any(
            item["phase"] == phase
            and item["exception"] == "ValueError"
            and item["scope"] == ["dev/123456789012/s3"]
            for item in artifact["processing_errors"]
        )
        assert any(
            item.get("phase") == phase and not item["complete"]
            for item in artifact["unverified"]
        )
        assert any(
            item["check_id"] == phase
            and item["status"] == "FAIL"
            and not item["complete"]
            for item in artifact["check_results"]
        )
        assert all(message in artifact["machine_diagnostics"] for message in messages)
        assert "REF_BAD" in artifact["machine_diagnostics"]
    else:
        assert not artifact["processing_errors"]
    assert "retained machine output" in artifact["machine_diagnostics"]
    candidates = [
        *artifact["ordinary"],
        *(item for item in artifact["judgments"] if "message" in item),
    ]
    assert len({item["id"] for item in candidates}) == len(candidates)
    for message in (messages[0], messages[-1]):
        assert (
            sum(
                item["message"] == message and item["service"] is None
                for item in candidates
            )
            == 1
        )
    if stage == "candidate-message":
        assert all(item["message"] != messages[1] for item in candidates)
    if stage != "references":
        assert all(
            item in candidates
            for item in expected_references
            if stage != "reference-message" or item["diagnostic"]["code"] != "REF_BAD"
        )
    assert artifact["naming"]["names"]
    assert any(
        "Retained review prose" in item.get("materials", [])
        for item in artifact["judgments"]
    )
    compare.assert_called_once()
    lint.assert_called_once()
    raw_lint.assert_called_once()
    assert any(record["category"] == "matched" for record in artifact["iac"])
    assert artifact["cfn_lint"]["jobs"][0]["completed"]
    assert artifact["cfn_lint"]["coverage"][0]["status"] == "completed"
    assert any(
        item.get("message") == "retained lint warning" for item in artifact["warnings"]
    )
    names = [call[0] for call in order.mock_calls]
    assert names[0] == "references" and names.index("naming") < names.index(
        "review"
    ) < names.index("compare") < names.index("lint")
    assert report.read_bytes() == report_before


@pytest.mark.parametrize(
    "stage",
    [
        "mechanical",
        "models",
        "lint",
        "naming",
        "review",
        "preflight",
    ],
)
def check_scan_stage_failures(tmp_path, stage):
    _exports_support_issues_scan_fixtures.fixture(tmp_path, services=("s3",))
    owner, method = {
        "mechanical": (scan_runner, "mechanical"),
        "models": (Validator, "check_model_files"),
        "lint": (scan_runner._imports_issues_cfn_lint, "run_lint"),
        "naming": (scan_runner, "naming_materials"),
        "review": (scan_runner, "review_materials"),
        "preflight": (scan_runner, "view_text"),
    }[stage]
    failure = (
        interrupted_mechanical
        if stage == "mechanical"
        else RuntimeError("interrupted stage")
    )
    artifact_path = tmp_path.parent / "partial-scan.json"
    report = tmp_path / "issues/dev/123456789012/issues.md"
    write(report, "# Issues\n\n### s3\n\n1. Keep this existing Issue\n")
    with (
        patch.object(
            scan_runner,
            "mechanical",
            side_effect=partial(retained_mechanical, scan_runner.mechanical),
        )
        if stage != "mechanical"
        else nullcontext(),
        patch.object(owner, method, side_effect=failure),
        patch.object(
            sys,
            "argv",
            [
                "issues",
                "--repository-root",
                str(tmp_path),
                "scan",
                "--environment",
                "dev",
                "--target-directory",
                "123456789012",
                "--service",
                "s3",
                "--artifact",
                str(artifact_path),
            ],
        ),
    ):
        assert issues_main() == 2
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    validate_artifact(artifact)
    assert artifact["validation_status"] == "ERROR"
    assert artifact["processing_errors"]
    assert artifact["unverified"]
    assert any(
        result["status"] == "FAIL" and not result["complete"]
        for result in artifact["check_results"]
    )
    assert any(record["category"] == "matched" for record in artifact["iac"])
    if stage != "lint":
        assert artifact["cfn_lint"]["jobs"][0]["completed"]
    assert any(
        "retained diagnostic" in item["message"]
        for item in artifact["judgments"]
        if "message" in item
    )
    assert not any(
        "interrupted" in record["message"] for record in artifact["ordinary"]
    )


def fail_service_materials(original, comparison, service=None, **kwargs):
    if service == "s3":
        comparison.sensitive_values.add("material-secret")
        raise ValueError("material-secret collection failure")
    return original(comparison, service=service, **kwargs)


@pytest.mark.parametrize("stage", ["naming", "review", "normal"])
def check_material_service_isolation(tmp_path, stage):
    _exports_support_issues_scan_fixtures.fixture(tmp_path, services=("s3", "sqs"))
    services = ["cloudformation-stacks", "s3", "sqs"]
    human = tmp_path / "issues/dev/123456789012/human-confirmations.yaml"
    original_human = human.read_bytes()
    doc = tmp_path / "docs/designs/dev/123456789012/sqs.md"
    doc.write_text(
        doc.read_text(encoding="utf-8") + "\nIndependent review prose\n",
        encoding="utf-8",
    )
    method = "naming_materials" if stage == "naming" else "review_materials"
    original = getattr(scan_runner, method)
    with (
        patch.object(
            scan_runner, method, side_effect=partial(fail_service_materials, original)
        )
        if stage != "normal"
        else nullcontext()
    ):
        artifact = scan_runner.scan(tmp_path, "dev", "123456789012", services)
    validate_artifact(artifact)
    failures = [
        item
        for item in artifact["processing_errors"]
        if item.get("phase", "").startswith("materials.")
    ]
    assert len(failures) == (0 if stage == "normal" else 1)
    if failures:
        assert failures[0]["scope"] == ["dev/123456789012/s3"]
    assert "material-secret" not in json.dumps(artifact)
    assert any(record["service"] == "sqs" for record in artifact["iac"])
    if stage == "naming":
        assert any(item["service"] == "sqs" for item in artifact["naming"]["names"])
    assert any(
        item.get("kind") == "nonmechanical-design-prose" and item["service"] == "sqs"
        for item in artifact["judgments"]
    )
    assert artifact["cfn_lint"]["jobs"][0]["completed"]
    if stage == "normal":
        comparison = scan_runner.Comparison(
            tmp_path, "dev", "123456789012", ["s3", "sqs"]
        )
        material, _ = scan_runner.naming_materials(comparison)
        assert artifact["naming_context"] == comparison.redacted(
            {key: value for key, value in material.items() if key != "names"}
        )
        assert artifact["naming"]["names"] == [
            dict(item, naming_context_id=artifact["naming_context_id"])
            for item in material["names"]
        ]
        with _exports_support_issues_scan_fixtures.task(tmp_path, services):
            outputs, _, _ = publication.save_scan(
                tmp_path,
                artifact,
                _exports_support_issues_scan_fixtures.review_for(artifact),
            )
        assert [path.name for path in outputs] == ["issues.md", "iac-issues.md"]
    assert human.read_bytes() == original_human


def interrupted_service(instance):
    service = next(iter(instance.scope))[2]
    instance.check(
        False, f"model/dev/team/{service}.properties: retained {service} diagnostic"
    )
    if service == "s3":
        raise RuntimeError("unexpected service failure")


def interrupted_worker(original, instance, snapshot, scope):
    if next(iter(scope))[2] == "s3":
        raise RuntimeError("unexpected worker failure")
    return original(instance, snapshot, scope)


@pytest.mark.parametrize("failure", ["service", "worker"])
def check_service_worker_isolation(tmp_path, failure):
    scope = {("dev", "team", service) for service in ("s3", "sqs")}
    validator = Validator(tmp_path, scope, workers=2)
    validator.cache = SimpleNamespace(service_key=str, load=lambda _: None)
    original = validation_runner._callback_Validator_check_scoped_designs_validate
    source = Mock(
        return_value=SimpleNamespace(
            errors=[],
            warnings=[],
            reference_errors=[],
            diagnostics=[],
            diagnostic_errors={},
            error_contexts={},
            processing_errors=[],
            unverified=[],
            information=[],
            checks=3,
        )
    )
    with (
        patch.object(Validator, "check_design_service_ownership"),
        patch.object(Validator, "check_stack_designs", return_value={}),
        patch.object(Validator, "check_generated_service_models"),
        patch.object(Validator, "check_designs", interrupted_service),
        patch.object(Validator, "check_observed_values") as observed,
        patch.object(
            sources,
            "load_model",
            return_value=SimpleNamespace(authoritative={}, warnings=[]),
        ),
        patch("model.validation.check_model_inputs", source),
        patch.object(
            validation_runner,
            "_callback_Validator_check_scoped_designs_validate",
            original if failure == "service" else partial(interrupted_worker, original),
        ),
    ):
        validator.check_scoped_designs()
    assert any("retained sqs diagnostic" in error for error in validator.errors)
    assert any("retained s3 diagnostic" in error for error in validator.errors) == (
        failure == "service"
    )
    assert observed.call_count == 2 and source.call_count == 1
    assert len(validator.findings.processing_errors) == 1
    assert validator.findings.unverified and not validator.service_cache_pending
    assert (
        validator.findings.result("design." + failure, {("dev", "team", "s3")}).status
        == "FAIL"
    )


@pytest.mark.parametrize(
    "state,scope,allowed,saveonly",
    [
        ("completed", True, True, True),
        ("suspend", True, True, True),
        ("running", False, True, True),
        ("running", True, False, True),
        ("running", True, True, False),
    ],
)
def check_save_authority_rejections(tmp_path, state, scope, allowed, saveonly):
    text = "## Task contract\n- Task status: `" + state + "`\n"
    with (
        patch.object(
            publication, "task_snapshot", return_value=SimpleNamespace(text=text)
        ),
        patch.object(
            publication,
            "active_scope",
            return_value={("dev", "team", "s3")} if scope else set(),
        ),
        patch.object(
            publication,
            "paths_in",
            return_value=["issues/dev/team/issues.md"] if allowed else [],
        ),
        patch.object(publication, "issues_save_only", return_value=saveonly),
        patch.object(
            publication,
            "atomic_files",
            side_effect=AssertionError("rejected save wrote outputs"),
        ),
    ):
        with pytest.raises(ValueError):
            publication.save_authority(tmp_path, "dev", "team", ["s3"], ["issues.md"])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "filename",
    ["other.md", "../issues.md", "../../other/issues.md", "human-confirmations.yaml"],
)
def check_save_authority_limits_real_destinations(tmp_path, filename):
    with _exports_support_issues_scan_fixtures.task(tmp_path, ["s3"]):
        with pytest.raises(ValueError):
            publication.save_authority(
                tmp_path, "dev", "123456789012", ["s3"], [filename]
            )
        allowed, task_name = publication.save_authority(
            tmp_path, "dev", "123456789012", ["s3"], ["issues.md", "iac-issues.md"]
        )
        assert [path.name for path in allowed] == ["issues.md", "iac-issues.md"]
        assert task_name == "tasks/save.md"
    with _exports_support_issues_scan_fixtures.task(
        tmp_path,
        ["s3"],
        allowed=[
            "issues/dev/123456789012/issues.md",
            "issues/dev/123456789012/human-confirmations.yaml",
        ],
    ):
        with pytest.raises(ValueError, match="save-only exception"):
            publication.save_authority(
                tmp_path, "dev", "123456789012", ["s3"], ["issues.md"]
            )


def check_causal_report_grouping():
    direct = dict(
        category="difference",
        service="datazone",
        resource="001",
        property="*",
        reason="template missing",
        stack="stack",
        cause=dict(
            kind="template-missing",
            path="missing.yaml",
            stack="stack",
            relationship="direct",
        ),
    )
    cascade = dict(
        category="uncompared",
        service="s3",
        resource="001",
        property="Setting",
        reason="search incomplete",
        cause=dict(direct["cause"], relationship="export-search-incomplete"),
    )
    records = [direct, cascade]
    entries, actions, _ = iac_dataset(records, "dev", "team", ["datazone", "s3"])
    assert len(actions) == 1 and len(actions[0]["members"]) == 2
    assert (
        actions[0]["category"] == "要対応"
        and actions[0]["repair_direction"] == "入力修正"
    )
    reversed_actions = iac_dataset(records[::-1], "dev", "team", ["datazone", "s3"])[1]
    assert reversed_actions == actions
    assert (
        iac_dataset([cascade], "dev", "team", ["s3"])[1][0]["category"] == "比較未完了"
    )
    assert actions[0]["id"] != iac_actions(entries, "stg", "team")[0]["id"]
    other = dict(
        cascade, resource="other", cause=dict(cascade["cause"], path="other.yaml")
    )
    unknown = dict(cascade, resource="unknown")
    unknown.pop("cause")
    parameter = dict(
        cascade,
        resource="parameter",
        cause=dict(cascade["cause"], kind="parameters-missing"),
    )
    _, separated, _ = iac_dataset(
        records + [other, unknown, parameter, dict(unknown, resource="unknown2")],
        "dev",
        "team",
        ["datazone", "s3"],
    )
    assert len(separated) == 5
    base = dict(
        category="difference",
        service="s3",
        resource="001",
        property="S3.Bucket.BucketName",
        stack="stack1",
        iac={"path": "shared.yaml"},
        reason="value mismatch",
        desired="a",
        actual="b",
    )
    distinct = [
        base,
        dict(base, stack="stack2"),
        dict(base, resource="002"),
        dict(base, property="S3.Bucket.Tags"),
        dict(base, reason="property missing"),
        dict(base, iac={"path": "other.yaml"}),
    ]
    assert len(iac_dataset(distinct, "dev", "team", ["s3"])[1]) == 6
    assert len(iac_dataset([base, base], "dev", "team", ["s3"])[1]) == 1
    assert len(iac_dataset([base, base], "dev", "team", ["s3"])[0]) == 2
    for invalid in (True, "false", None, 0):
        forged = dict(base, cause=dict(kind="condition-disabled", result=invalid))
        assert iac_summary([forged], "dev", "team", ["s3"])["proven_causes"] == 0


def check_model_part_bytes_and_legacy_rows(tmp_path):
    source = tmp_path / "model/dev/team/s3.properties"
    write(
        tmp_path / "project.json",
        json.dumps(
            {
                "projectName": "fixture",
                "targets": [
                    dict(
                        environment="dev",
                        alias="team",
                        awsAccountId="123456789012",
                        awsRegion="ap-northeast-1",
                        iacEngine="cloudformation",
                    )
                ],
            }
        ),
    )
    values = {
        "desired.service.s3.serviceId": "s3",
        "desired.resource.legacy-id.resourceType": "S3.Bucket",
        "desired.row.legacy-id-001.property": "S3.Bucket.BucketName",
        "desired.row.legacy-id-001.value": "`bucket`",
        "desired.row.legacy-id-001.comment": "fixture",
        "desired.resource.legacy.resourceType": "S3.Bucket",
    }
    values.update(
        {
            "desired.resource.legacy-id.logicalId": "S3_Bucket_001",
            "desired.resource.legacy.logicalId": "S3_Bucket_002",
            "desired.service.identity.lastAllocated": '{"S3.Bucket":2}',
        }
    )
    outputs = split(source, values, limit=3)
    assert len(outputs) > 1
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    with (
        input_context(read_only=True),
        patch.object(sources, "_read_model", wraps=sources._read_model) as parser,
    ):
        one, two = real_load(source), real_load(source)
        assert one is two and parser.call_count == 1
    assert one.values == values
    assert all(
        text.encode("utf-8") == path.read_bytes() for path, text in one.files.items()
    )
    assert all(
        path.read_text(encoding="utf-8").splitlines()[line - 1].partition("=")[0] == key
        for key, (path, line) in one.locations.items()
    )
    assert resource_row_index(one.values)["legacy"] == []
    assert len(resource_row_index(one.values)["legacy-id"]) == 1


def check_missing_template_report():
    record = dict(
        category="difference",
        service="s3",
        resource="001",
        property="*",
        stack="stack",
        reason="モデルに対応するtemplateが存在しない（CREATE未実装）",
        iac={"path": "infra/cloudformation/templates/shared.yaml"},
        cause=dict(
            kind="template-missing",
            path="infra/cloudformation/templates/shared.yaml",
            stack="stack",
            relationship="direct",
        ),
    )
    report = iac_report("dev", "team", ["s3"], [record])
    assert "difference 1件" in report and "uncompared 0" not in report
    assert (
        "infra/cloudformation/templates/shared.yaml" in report
        and "修正対象" not in report
    )
    assert "[infra/cloudformation/templates/shared.yaml]" not in report


@pytest.mark.parametrize(
    "reason",
    [
        "value mismatch",
        "property missing",
        "resource missing",
        "inline CREATE child missing",
        "property omitted by AWS::NoValue",
    ],
)
@pytest.mark.parametrize("mapped", [True, False])
def check_confirmed_difference_direction(reason, mapped):
    record = dict(
        category="difference",
        service="iam",
        resource="001",
        property="IAM.Role.AssumeRolePolicyDocument",
        reason=reason,
        desired={
            "Statement": [
                {"Condition": {"StringEquals": {"aws:SourceAccount": "123456789012"}}}
            ]
        },
        actual={"Statement": [{}]},
        stack="stack" if mapped else None,
        iac={"path": "infra/role.yaml"} if mapped else None,
    )
    display = {
        identifier(record): value_differences(
            record["desired"], record["actual"], record["property"]
        )
    }
    data = aggregate([record, record], "dev", "team", ["iam"], display)
    (action,) = data["iac_issues"]
    direction = "IaC修正" if mapped else "修正先要確認"
    old_key = (
        [
            "dev",
            "team",
            "infra/role.yaml",
            "stack",
            "iam",
            "001",
            record["property"],
            reason,
            "sync-model-iac",
        ]
        if mapped
        else [
            "dev",
            "team",
            "unresolved",
            iac_key(record),
            "difference",
            reason,
            None,
            None,
        ]
    )
    assert action["id"] == "ISSUE-" + identifier(old_key)
    assert action["members"] == [0, 1] and data["iac"] == [record, record]
    assert (
        action["category"]
        == action["status"]
        == action["compact"]["category"]
        == "要修正"
    )
    assert (
        action["repair_direction"] == action["compact"]["repair_direction"] == direction
    )
    (group,) = data["overview"]["groups"]
    assert group["category"] == "要修正" and group["repair_direction"] == direction
    assert (
        data["overview"]["issue_count"] == 1 and data["overview"]["record_count"] == 2
    )
    artifact = dict(version=6, ordinary=[], judgments=[], naming={"names": []}, **data)
    assert scan_exit_code(artifact) == 0
    assert detail_payload(artifact, "iac_issues", category="要修正")["items"] == [
        action
    ]
    assert detail_payload(artifact, "iac", category="要修正")["total"] == 2
    report = iac_report(
        "dev", "team", ["iam"], data["iac"], artifact=artifact, stamp="fixed"
    )
    assert report == iac_report(
        "dev", "team", ["iam"], [record, record], display, stamp="fixed"
    )
    assert "| 要修正 |" in report and record["property"] in report
    assert action["id"] in report
    assert all(
        text not in report
        for text in ("修正対象", "必要な対応", "確認事項", "相違項目")
    )


@pytest.mark.parametrize(
    "model_format,iac_format,direction",
    [
        ("allowed", "outside allowed forms", "IaC修正"),
        ("outside allowed forms", "allowed", "Model修正"),
        ("outside allowed forms", "outside allowed forms", "修正先要確認"),
        ("unproven", "outside allowed forms", "修正先要確認"),
        ("allowed", "allowed", "修正先要確認"),
    ],
)
def check_format_violation_direction(model_format, iac_format, direction):
    diagnostic = dict(
        path="Logs.LogGroup.KmsKeyId",
        model="key",
        iac="alias",
        identity="unproven",
        allowed_forms=["AliasArn"],
        format=dict(model=model_format, iac=iac_format),
        reason="format violation",
    )
    record = dict(
        category="difference",
        service="cloudwatch-logs",
        resource="001",
        property=diagnostic["path"],
        reason="KMS format mismatch: model=KeyArn, iac=AliasArn",
        stack="stack",
        model={"path": "model/dev/team/cloudwatch-logs.properties"},
        iac={"path": "infra/log.yaml"},
        reference_diagnostics=[diagnostic],
    )
    data = aggregate([record], "dev", "team", ["cloudwatch-logs"])
    (action,) = data["iac_issues"]
    assert action["id"] == "ISSUE-" + identifier(
        ["dev", "team", "kms-format", iac_key(record)]
    )
    assert action["category"] == "要修正" and action["repair_direction"] == direction
    report = iac_report("dev", "team", ["cloudwatch-logs"], [record], artifact=data)
    assert "| 要修正 |" in report and action["id"] in report
    assert "修正対象" not in report and "必要な対応" not in report


@pytest.mark.parametrize(
    "category,reason,cause,expected",
    [
        (
            "difference",
            "resource missing",
            dict(
                kind="condition-disabled",
                result=False,
                path="role.yaml",
                stack="stack",
                logical="Role",
                condition="Enabled",
                inputs=[],
            ),
            "要判断",
        ),
        (
            "uncompared",
            "Fn::ImportValue unresolved",
            dict(kind="import-unresolved", export="RoleArn"),
            "比較未完了",
        ),
        ("error", "comparison failed", {}, "処理エラー"),
        ("difference", "cause unknown", {}, "原因未確定"),
        ("uncompared", "value mismatch", {}, "比較未完了"),
        ("difference", "KMS format is unproven", {}, "原因未確定"),
        (
            "uncompared",
            "API only",
            dict(kind="cloudformation-unsupported", resource_type="Macie.Job"),
            "CFn非対応・比較対象外",
        ),
        (
            "difference",
            "parameters missing",
            dict(
                kind="parameters-missing",
                path="parameters.json",
                relationship="stack-input",
            ),
            "要対応",
        ),
        (
            "uncompared",
            "parameters missing",
            dict(
                kind="parameters-missing",
                path="parameters.json",
                relationship="export-search-incomplete",
            ),
            "比較未完了",
        ),
    ],
)
def check_unconfirmed_classifications(category, reason, cause, expected):
    record = dict(
        category=category,
        service="iam",
        resource="001",
        property="Setting",
        reason=reason,
        cause=cause,
        stack="stack",
        iac={"path": "role.yaml"},
    )
    data = aggregate([record], "dev", "team", ["iam"])
    (action,) = data["iac_issues"]
    assert action["category"] == action["compact"]["category"] == expected
    assert (
        data["overview"]["categories"][expected] == 1
        and data["overview"]["categories"]["要修正"] == 0
    )
    assert action["repair_direction"] == (
        "入力修正" if cause.get("kind") == "parameters-missing" else "未確定"
    )


@pytest.mark.parametrize("section", ["iac", "iac_issues"])
def check_cli_repair_category(tmp_path, capsys, section):
    records = [
        dict(
            category=category,
            service="iam",
            resource=f"{i:03}",
            property="Setting",
            reason=reason,
            stack="stack",
            iac={"path": "role.yaml"},
            desired=1,
            actual=2,
        )
        for i, (category, reason) in enumerate(
            [
                ("difference", "value mismatch"),
                ("difference", "property missing"),
                ("uncompared", "Fn::ImportValue unresolved"),
            ]
        )
    ]
    artifact = dict(
        version=6,
        scan_id="a" * 32,
        naming_context={},
        naming_context_id=identifier({}),
        **aggregate(records, "dev", "team", ["iam"]),
    )
    validate_artifact(artifact)
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with patch.object(
        sys,
        "argv",
        [
            "issues_scan.py",
            "--repository-root",
            str(tmp_path / "project"),
            "detail",
            "--artifact",
            str(path),
            "--section",
            section,
            "--category",
            "要修正",
            "--offset",
            "1",
            "--limit",
            "1",
        ],
    ):
        assert issues_main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 2 and result["offset"] == 1 and len(result["items"]) == 1
    if section == "iac_issues":
        assert result["items"][0]["category"] == "要修正"
        assert result["items"][0]["repair_direction"] == "IaC修正"
    else:
        assert result["items"][0]["record_index"] == 1
        assert result["items"][0]["issue_id"] == artifact["record_meta"][1]["issue_id"]


def deferred_artifact(count=13, phase="unobserved"):
    cause = ImportReferenceDeferred(
        phase,
        "vpc",
        "004",
        "EC2.Subnet",
        "SubnetId",
        "CodeBuild.Project.VpcConfig.Subnets[]",
    ).iac_cause
    records = [
        dict(
            category="excluded" if phase == "pending_deploy" else "deferred",
            service="codebuild",
            resource=f"{i:03}",
            property="CodeBuild.Project.VpcConfig.Subnets[]",
            reason="approved handoff required",
            cause=deepcopy(cause),
        )
        for i in range(count)
    ]
    return dict(
        version=6,
        scan_id="a" * 32,
        naming_context={},
        naming_context_id=identifier({}),
        ordinary=[],
        judgments=[],
        naming={"names": []},
        **aggregate(records, "dev", "team", ["codebuild"]),
    )


def check_deferred_artifact_summary_report_and_gate(tmp_path):
    artifact = deferred_artifact()
    validate_artifact(artifact)
    view = summary(artifact)
    assert (
        view["iac_deferred"] == 13
        and view["iac_uncompared"] == 0
        and view["iac_status"] == "partial"
    )
    assert view["validation_status"] == "CHECKED" and scan_exit_code(artifact) == 0
    assert (
        artifact["overview"]["record_count"]
        == sum(artifact["overview"]["records"].values())
        == 13
    )
    assert artifact["overview"]["issue_count"] == 0 and not artifact["iac_issues"]
    assert all(item["issue_id"] is None for item in artifact["record_meta"])
    assert (
        detail_payload(artifact, "iac", 10, 5, record_category="deferred")["total"]
        == 13
    )
    page = detail_payload(artifact, "iac", 10, 5, record_category="deferred")["items"]
    assert (
        len(page) == 3
        and page[0]["record_index"] == 10
        and all(item["issue_id"] is None for item in page)
    )
    report = iac_report(
        "dev", "team", ["codebuild"], artifact["iac"], artifact=artifact
    )
    assert "問題: 0件" in report and "deferred 13件" in report
    assert "今回の判定: partial" in report
    assert all(
        text not in report
        for text in (
            "Producer Resource",
            "保留解除条件",
            "--record-category",
            "## ",
            "| ISSUE-",
        )
    )


@pytest.mark.parametrize("count", [1, 2])
def check_pending_deploy_is_count_only_exclusion(count):
    artifact = deferred_artifact(count, "pending_deploy")
    validate_artifact(artifact)
    view = summary(artifact)
    assert view["iac_status"] == "no compared records"
    assert view["iac_excluded"] == view["iac_pending_deploy_excluded"] == count
    assert view["iac_matched"] == view["iac_uncompared"] == view["iac_deferred"] == 0
    assert view["validation_status"] == "CHECKED" and scan_exit_code(artifact) == 0
    overview = artifact["overview"]
    assert overview["pending_deploy_excluded"] == count
    assert overview["issue_count"] == sum(overview["categories"].values()) == 0
    assert overview["categories"]["CFn非対応・比較対象外"] == 0
    assert not artifact["iac_issues"] and all(
        item["issue_id"] is None for item in artifact["record_meta"]
    )
    page = detail_payload(artifact, "iac", record_category="excluded")
    assert page["total"] == count
    assert all(
        item["cause"]["kind"] == "import-reference-excluded"
        and item["cause"]["phase"] == "pending_deploy"
        for item in page["items"]
    )
    assert not detail_payload(artifact, "iac_issues")["items"]
    for report in (
        iac_report("dev", "team", ["codebuild"], artifact["iac"], artifact=artifact),
        iac_report("dev", "team", ["codebuild"], artifact["iac"]),
    ):
        (classification,) = [
            line for line in report.splitlines() if line.startswith("PENDING_DEPLOY")
        ]
        assert classification.endswith(f"PENDING_DEPLOY（比較対象外） {count}件")
        assert report.count("PENDING_DEPLOY") == 1
        assert all(
            text not in report
            for text in (
                "Producer Resource",
                "SubnetId",
                "vpc/004",
                "VpcConfig",
                "approved handoff",
                "保留解除条件",
                "## 想定内保留",
                "| ISSUE-",
                "### ISSUE-",
            )
        )


@pytest.mark.parametrize(
    "category,status",
    [
        (None, "no compared records"),
        ("matched", "complete match"),
        ("difference", "differences"),
        ("uncompared", "partial"),
        ("error", "error"),
        ("deferred", "partial"),
    ],
)
def check_pending_deploy_does_not_change_comparison_status(category, status):
    records = deferred_artifact(1, "pending_deploy")["iac"]
    if category == "deferred":
        records += deferred_artifact(1)["iac"]
    elif category:
        records += [
            dict(
                category=category,
                service="codebuild",
                resource="other",
                property="Setting",
                reason="known result",
            )
        ]
    data = aggregate(records, "dev", "team", ["codebuild"])
    artifact = dict(deferred_artifact(0), **data)
    validate_artifact(artifact)
    assert summary(artifact)["iac_status"] == status
    assert data["overview"]["pending_deploy_excluded"] == 1
    assert data["overview"]["records"]["matched"] == (1 if category == "matched" else 0)
    expected_issues = 1 if category in {"difference", "uncompared", "error"} else 0
    assert (
        data["overview"]["issue_count"]
        == sum(data["overview"]["categories"].values())
        == expected_issues
    )


def check_pending_deploy_parent_child_count_and_issue_separation():
    records = deferred_artifact(2, "pending_deploy")["iac"]
    # One cause propagated to a parent is counted once; another consumer is independent.
    records.append(dict(records[0], property="CodeBuild.Project.VpcConfig"))
    issue = dict(
        category="uncompared",
        service="codebuild",
        resource="issue",
        property="Setting",
        reason="unproven",
    )
    unsupported = dict(
        issue,
        resource="api",
        cause=dict(
            kind="cloudformation-unsupported", resource_type="Macie.ClassificationJob"
        ),
    )
    data = aggregate(records + [issue, unsupported], "dev", "team", ["codebuild"])
    artifact = dict(deferred_artifact(0), **data)
    validate_artifact(artifact)
    view = data["overview"]
    assert view["pending_deploy_excluded"] == 2 and view["records"]["excluded"] == 3
    assert view["issue_count"] == sum(view["categories"].values()) == 2
    assert (
        view["categories"]["比較未完了"]
        == view["categories"]["CFn非対応・比較対象外"]
        == 1
    )
    assert view["records"]["uncompared"] == 2 and view["records"]["deferred"] == 0
    assert all(meta["issue_id"] is None for meta in data["record_meta"][:3])
    report = iac_report(
        "dev", "team", ["codebuild"], artifact["iac"], artifact=artifact
    )
    assert (
        "PENDING_DEPLOY（比較対象外） 2件" in report
        and "CFn非対応・比較対象外 1件" in report
    )
    assert "unproven" in report and "Macie.ClassificationJob" in report
    assert all(
        text not in report
        for text in ("vpc/004", "VpcConfig", "SubnetId", "approved handoff")
    )


def direct_pending_artifact(count=1):
    records = [
        dict(
            category="excluded",
            service="route53",
            resource="003",
            property="Route53.RecordSet.AliasTarget." + prop,
            reason="desired value comparison excluded: pending_deploy",
            cause=DesiredPendingDeployExcluded(
                "Route53.RecordSet.AliasTarget." + prop
            ).iac_cause,
        )
        for prop in ("DNSName", "HostedZoneId")[:count]
    ]
    return dict(deferred_artifact(0), **aggregate(records, "dev", "cde", ["route53"]))


@pytest.mark.parametrize("count", [1, 2])
def check_direct_pending_deploy_reports_and_dedup(count, tmp_path):
    artifact = direct_pending_artifact(count)
    records = artifact["iac"]
    records.append(dict(records[0], property="Route53.RecordSet.AliasTarget"))
    records += deferred_artifact(1, "pending_deploy")["iac"]
    artifact.update(aggregate(records, "dev", "cde", ["route53", "codebuild"]))
    validate_artifact(artifact)
    view = summary(artifact)
    assert artifact["version"] == 6
    assert view["iac_pending_deploy_excluded"] == count + 1
    assert view["iac_excluded"] == count + 2
    assert view["iac_uncompared"] == view["iac_deferred"] == 0
    assert not artifact["overview"]["comparison_incomplete"]
    assert (
        artifact["overview"]["issue_count"]
        == sum(artifact["overview"]["categories"].values())
        == 0
    )
    assert not artifact["iac_issues"]
    assert all(meta["issue_id"] is None for meta in artifact["record_meta"])
    for saved_artifact in (None, artifact):
        report = iac_report(
            "dev", "cde", ["route53", "codebuild"], records, artifact=saved_artifact
        )
        assert f"PENDING_DEPLOY（比較対象外） {count + 1}件" in report
        assert "問題: 0件" in report and "uncompared" not in report
        assert all(
            text not in report
            for text in ("DNSName", "HostedZoneId", "### ISSUE-", "| ISSUE-")
        )
    ordinary = ordinary_report(
        tmp_path,
        dict(
            artifact,
            environment="dev",
            target="cde",
            services=["route53"],
            executed_at="2026-10-25T00:00:00Z",
            unverified=[],
            processing_errors=[],
            information=[],
            warnings=[],
        ),
    )
    assert "未解決issueなし" in ordinary and "比較未完了" not in ordinary


@pytest.mark.parametrize(
    "fault",
    [
        "phase",
        "missing-property",
        "empty-property",
        "property-type",
        "extra-field",
        "category",
        "count",
        "kind",
    ],
)
def check_direct_pending_deploy_artifact_rejects_invalid_causes(fault):
    artifact = direct_pending_artifact()
    cause = artifact["iac"][0]["cause"]
    if fault == "phase":
        cause["phase"] = "unobserved"
    elif fault == "missing-property":
        del cause["consumer_property"]
    elif fault == "empty-property":
        cause["consumer_property"] = ""
    elif fault == "property-type":
        cause["consumer_property"] = []
    elif fault == "extra-field":
        cause["producer"] = {}
    elif fault == "category":
        artifact["iac"][0]["category"] = "uncompared"
    elif fault == "count":
        artifact["overview"]["pending_deploy_excluded"] = 0
    else:
        cause["kind"] = "import-reference-excluded"
    with pytest.raises(ValueError):
        validate_artifact(artifact)


@pytest.mark.parametrize("phase", ["unobserved", "pending_deploy"])
@pytest.mark.parametrize(
    "fault",
    [
        "old_version",
        "category",
        "counts",
        "issue-count",
        "cause",
        "phase",
        "meta",
        "record-id",
        "deferred-membership",
        "missing-membership",
        "pending-count",
        "cause-category",
    ],
)
def check_artifact_v6_rejects_invalid_indexes(fault, phase):
    artifact = deferred_artifact(1, phase)
    if fault == "old_version":
        artifact["version"] = 5
    elif fault == "category":
        artifact["iac"][0]["category"] = "unknown"
    elif fault == "counts":
        artifact["overview"]["records"]["deferred"] = 2
    elif fault == "issue-count":
        artifact["overview"]["issue_count"] = 1
    elif fault == "cause":
        del artifact["iac"][0]["cause"]
    elif fault == "phase":
        artifact["iac"][0]["cause"]["phase"] = "unknown"
    elif fault == "pending-count":
        artifact["overview"]["pending_deploy_excluded"] += 1
    elif fault == "cause-category":
        artifact["iac"][0]["category"] = (
            "deferred" if phase == "pending_deploy" else "excluded"
        )
    elif fault == "meta":
        artifact["record_meta"][0]["category"] = "matched"
    elif fault == "record-id":
        artifact["record_meta"][0]["record_id"] = "0" * 20
    elif fault == "deferred-membership":
        artifact["record_meta"][0]["issue_id"] = "ISSUE-forbidden"
        artifact["iac_issues"] = [
            dict(id="ISSUE-forbidden", members=[0], compact={"records": 1})
        ]
        artifact["overview"]["issue_count"] = 1
    elif fault == "missing-membership":
        artifact = dict(
            version=6,
            scan_id="a" * 32,
            naming_context={},
            naming_context_id=identifier({}),
            **aggregate(
                [
                    dict(
                        category="uncompared",
                        service="s3",
                        resource="001",
                        property="Setting",
                        reason="unknown",
                    )
                ],
                "dev",
                "team",
                ["s3"],
            ),
        )
        artifact["iac_issues"] = []
        artifact["overview"]["issue_count"] = 0
        artifact["record_meta"][0]["issue_id"] = None
    with pytest.raises(ValueError):
        validate_artifact(artifact)
    if fault == "old_version":
        with pytest.raises(ValueError, match="version"):
            detail_payload(artifact, "iac")
        with pytest.raises(ValueError, match="version"):
            summary(artifact)


def check_cli_deferred_pagination_and_filter_separation(tmp_path, capsys):
    artifact = deferred_artifact()
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    arguments = [
        "issues_scan.py",
        "--repository-root",
        str(tmp_path / "project"),
        "detail",
        "--artifact",
        str(path),
        "--section",
        "iac",
        "--record-category",
        "deferred",
        "--offset",
        "10",
        "--limit",
        "5",
    ]
    with patch.object(sys, "argv", arguments):
        assert issues_main() == 0
    result = json.loads(capsys.readouterr().out)
    assert (
        result["total"] == 13 and result["offset"] == 10 and len(result["items"]) == 3
    )
    for extra in (["--category", "要判断"], ["--issue-id", "ISSUE-absent"]):
        with patch.object(sys, "argv", arguments + extra):
            assert issues_main() == 2
        assert "cannot be combined" in capsys.readouterr().err
    expect_error(
        lambda: detail_payload(artifact, "iac_issues", record_category="deferred"),
        "requires section iac",
    )


def check_six_categories_and_comparison_priority():
    records = deferred_artifact(1)["iac"]
    records += [
        dict(
            category=category,
            service="codebuild",
            resource=category,
            property="Setting",
            reason=category,
        )
        for category in CATEGORIES
        if category != "deferred"
    ]
    data = aggregate(records, "dev", "team", ["codebuild"])
    assert data["overview"]["records"] == dict.fromkeys(CATEGORIES, 1)
    assert data["overview"]["issue_count"] == 3
    counts = dict.fromkeys(CATEGORIES, 0)
    for category, expected in [
        ("excluded", "no compared records"),
        ("matched", "complete match"),
        ("difference", "differences"),
        ("deferred", "partial"),
        ("uncompared", "partial"),
        ("error", "error"),
    ]:
        counts[category] = 1
        assert comparison_status(counts) == expected


@pytest.fixture
def reference_design(tmp_path):
    fixture = _exports_support_issues_scan_fixtures
    fixture.fixture(tmp_path, stacks=2, services=("s3",))
    model = tmp_path / "model/dev/123456789012/s3.properties"
    values = dict(real_load(model).authoritative)
    key = "desired.row.001-900.value"
    values.update(
        {
            "desired.row.001-900.property": "S3.Bucket.LoggingConfiguration.DestinationBucketName",
            key: '`{"$modelRef":{"logicalId":"S3_Bucket_002","attribute":"BucketName"}}`',
            "desired.row.001-900.comment": "合成参照",
        }
    )
    fixture.write_model(model, values)
    view = tmp_path / "docs/designs/dev/123456789012/s3.md"
    text = fixture.markdown_for(view, values, tmp_path)
    view.write_text(text, encoding="utf-8")
    return model, view, values, key


@pytest.mark.parametrize("display", ["link", "plain", "label", "extra-prose"])
def check_issues_checks_saved_display_without_generation(
    tmp_path, reference_design, display
):
    _, view, _, _ = reference_design
    text = view.read_text(encoding="utf-8")
    if display == "plain":
        text = text.replace(
            "| LoggingConfiguration.DestinationBucketName | [bucket-app-dev-data2](#s3-bucket-app-dev-data2) |",
            "| LoggingConfiguration.DestinationBucketName | `bucket-app-dev-data2` |",
        )
    elif display == "label":
        text = text.replace(
            "| LoggingConfiguration.DestinationBucketName | [bucket-app-dev-data2](#s3-bucket-app-dev-data2) |",
            "| LoggingConfiguration.DestinationBucketName | [saved-label](#s3-bucket-app-dev-data2) |",
        )
    elif display == "extra-prose":
        text += "\n追加の説明文。\n"
    view.write_text(text, encoding="utf-8")
    validators, warnings = [], []
    with (
        patch.object(
            sync_runtime,
            "compare_generation",
            side_effect=AssertionError("generation equality must not run"),
        ),
    ):
        errors, checks, _ = scan_runner.mechanical(
            tmp_path,
            {("dev", "123456789012", "s3")},
            jobs=1,
            validator_out=validators,
            warnings=warnings,
        )
    assert checks > 0 and not warnings, (errors, warnings)
    if display in {"plain", "label"}:
        assert errors and validators[0].findings.unverified
        assert not validators[0].findings.processing_errors
        assert any(
            "indexed array display requires Model source rows" in error
            for error in errors
        ), errors
    else:
        assert not errors and not validators[0].findings.unverified, errors
    assert not any(
        item.code == "design.display.mismatch"
        for item in validators[0].findings.diagnostics
    )
    assert not validators[0].findings.processing_errors
    assert not any(
        check_id == "framework.generated-service-model"
        for check_id, _, _ in validators[0].findings.results
    )
    dependency_index.rebuild(tmp_path)
    strict = Validator(tmp_path, {("dev", "123456789012", "s3")}, workers=1)
    strict.check_project_topology()
    strict.check_scoped_designs()
    assert any(
        d.code == "generation.mismatch" for d in strict.findings.diagnostics
    ) == (display == "extra-prose")
    assert any(
        d.code == "design.display.mismatch" for d in strict.findings.diagnostics
    ) == (display != "link")
    assert bool(strict.errors) == (display != "link")


@pytest.mark.parametrize(
    "fault",
    [
        "logicalId",
        "attribute",
        "syntax",
        "link-target",
        "link-anchor",
        "schema",
        "required",
    ],
)
def check_issues_keeps_independent_validation(tmp_path, reference_design, fault):
    model, view, values, key = reference_design
    if fault in {"logicalId", "attribute", "syntax"}:
        reference = {"logicalId": "S3_Bucket_002", "attribute": "BucketName"}
        if fault == "syntax":
            reference["unexpected"] = "invalid"
        else:
            reference[fault] = "Missing"
        values[key] = "`" + json.dumps({"$modelRef": reference}) + "`"
    elif fault == "schema":
        values["desired.row.001-003.value"] = "`invalid-status`"
    elif fault == "required":
        for suffix in ("property", "value", "comment"):
            values.pop("desired.row.001-001." + suffix)
    else:
        target = "missing.md#absent" if fault == "link-target" else "#absent"
        text = view.read_text(encoding="utf-8") + f"\n[参照先]({target})\n"
        view.write_text(text, encoding="utf-8")
    _exports_support_issues_scan_fixtures.write_model(model, values)
    validators = []
    errors, _, _ = scan_runner.mechanical(
        tmp_path,
        {("dev", "123456789012", "s3")},
        jobs=1,
        validator_out=validators,
    )
    warnings = validators[0].warnings
    assert errors or warnings, validators[0].findings.reference_errors
    messages = "\n".join([*errors, *(str(warning) for warning in warnings)])
    assert "generation.mismatch" not in messages
    if fault == "logicalId":
        assert "TARGET_MISSING" in messages
    elif fault == "attribute":
        assert "ATTRIBUTE" in messages
    elif fault == "syntax":
        assert "SYNTAX" in messages
    elif fault.startswith("link-"):
        assert (
            "broken design link" if fault == "link-target" else "missing design anchor"
        ) in messages
    elif fault == "schema":
        assert "provider schema violation" in messages
    else:
        assert "required" in messages


def save_with_changed_selection(save, monkeypatch, root, artifact, review):
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/authorized.md")
    result = save(root, artifact, review)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/missing.md")
    return result


@pytest.mark.parametrize("processing", [False, True])
@pytest.mark.parametrize(
    "selection", ["cli", "environment", "implicit", "space", "missing", "changed"]
)
def check_save_cli_keeps_publication_scan_and_pending_validation_separate(
    tmp_path, capsys, monkeypatch, processing, selection
):
    root = tmp_path / ("repository space" if selection == "space" else "repository")
    root.mkdir()
    artifact, review = tmp_path / "scan.json", tmp_path / "review.json"
    data = _exports_support_issues_scan_fixtures.snapshot_artifact(root)
    artifact.write_text(json.dumps(data), encoding="utf-8")
    review.write_text(
        json.dumps(_exports_support_issues_scan_fixtures.review_for(data)),
        encoding="utf-8",
    )
    name = "save"
    task_name = f"tasks/{name}.md"
    with _exports_support_issues_scan_fixtures.task(root, ["s3"], name=name):
        text = (root / task_name).read_text(encoding="utf-8")
    if selection != "missing":
        write(root / task_name, text)
    if selection == "changed":
        write(
            root / "tasks/authorized.md", text.replace(task_name, "tasks/authorized.md")
        )
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "")
    if selection in {"environment", "changed"}:
        monkeypatch.setenv("BLUEPRINT_TASK_FILE", task_name)
    options = ["--task-file", task_name] if selection in {"cli", "space"} else []
    with (
        task_reads(root),
        patch(
            "issues.publication.save_scan",
            wraps=publication.save_scan,
            side_effect=partial(
                save_with_changed_selection, publication.save_scan, monkeypatch
            )
            if selection == "changed"
            else None,
        ) as saved,
        patch(
            "issues.artifact.summary",
            return_value={"validation_status": "ERROR" if processing else "FAIL"},
        ),
        patch("issues.artifact.has_processing_errors", return_value=processing),
        patch.object(
            sys,
            "argv",
            [
                "issues",
                "--repository-root",
                str(root),
                *options,
                "save",
                "--artifact",
                str(artifact),
                "--review",
                str(review),
            ],
        ),
    ):
        if selection == "changed":
            assert task_snapshot(root).name == task_name
        assert issues_main() == (2 if processing or selection == "missing" else 0)
    if selection == "missing":
        saved.assert_called_once()
        captured = capsys.readouterr()
        assert not captured.out and "selected task contract required" in captured.err
        return
    result = json.loads(capsys.readouterr().out)
    assert result["publication_status"] == "SAVED"
    assert result["validation_status"] == ("ERROR" if processing else "FAIL")
    assert result["post_save_validation"] == "NOT_RUN"
    assert result["post_save_validation_command"] == (
        "blueprint-loop.py --mode local --task-file "
        + ("tasks/authorized.md" if selection == "changed" else task_name)
    )


@pytest.mark.parametrize("heading", ["QuickSight", "Quicksight"])
@pytest.mark.parametrize("row", ["QuickSight", "Quicksight"])
def check_issues_quicksight_name_difference(tmp_path, heading, row):
    with validation_runner._imports_utils_aws_mappings.mapping_alias(
        reference_fixtures.FRAMEWORK, tmp_path
    ):
        reference_fixtures.project(tmp_path)
        scope, values = reference_fixtures.resource(
            tmp_path,
            "quicksight",
            "QuickSight.DataSource",
            attribute="Name",
        )
        values["desired.resource.001.resourceMode"] = "IMPORT"
        values.pop("desired.resource.001.cfn-logicalId")
        values["desired.row.001-001.value"] = "`QuickSight`"
        values["desired.row.001-002.property"] = "QuickSight.DataSource.Type"
        values["desired.row.001-002.value"] = "`S3`"
        values["desired.row.001-002.comment"] = "合成データソース種別"
        reference_fixtures.save(scope, values)
        view = tmp_path / "docs/designs/qa/team/quicksight.md"
        text = _exports_support_issues_scan_fixtures.markdown_for(
            view, values, tmp_path
        )
        write(view, text)
        selected = {("qa", "team", "quicksight")}
        write(
            view,
            text.replace("`QuickSight`", f"`{row}`").replace(
                "### QuickSight.DataSource: QuickSight",
                f"### QuickSight.DataSource: {heading}",
            ),
        )
        after, _, _ = scan_runner.mechanical(tmp_path, selected, jobs=1)
        strict = Validator(tmp_path, selected, workers=1)
        strict.design_sources = {view: values}
        strict.check_resource_names(
            {view: ("quicksight", ("QuickSight.DataSource",))}, [view]
        )
    assert any("heading must display" in error for error in after) == (heading != row)
    assert any(
        "display" in error or "differs" in error or "generation" in error
        for error in strict.errors
    ) == (heading != "QuickSight" or row != "QuickSight")


if __name__ == "__main__":
    raise SystemExit(run(__file__))
