#!/usr/bin/env python3
"""Whole-target snapshot, Human review and atomic publication boundaries."""

import json
import os
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import issues.publication as publication
import pytest
from comparison import Comparison
from design.catalog import DesignSchemaCatalog
from issues.artifact import summary
from issues.integrity import target_services
from issues.materials import naming_materials
from issues.publication import render_snapshot, save_scan
from issues.records import identifier
from issues.review import (
    human_confirmations,
    naming_decision,
    review_names,
    review_snapshot,
)
from issues.runner import scan_stage
from model.validations.naming import (
    naming_rule_files,
    naming_rule_rows,
    provider_naming_errors,
)
from support.issues_scan_fixtures import (
    fixture,
    forbid_report_text,
    review_for,
    snapshot_artifact,
    task,
    write,
)
from support.pytest_cli import run
from task_contract_core import active_scope, selected_task, task_reads, task_snapshot
from utils.function_wrapper import BoundCallback
from utils.project_targets import select_target
from validation.findings import Findings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def confirmation():
    return dict(
        id="human-1",
        service="s3",
        fact="Human approved an existing name",
        scope=dict(resource="001", property="S3.Bucket.BucketName"),
        exceptions=[
            dict(
                rule="design.service",
                diagnostic_id="current",
                condition="Existing name is permitted",
            )
        ],
        evidence="Explicit Human decision",
    )


def reviewed_artifact(root):
    data = snapshot_artifact(
        root,
        ordinary=[
            dict(
                id="current",
                service="s3",
                resource="001",
                property="S3.Bucket.BucketName",
                rule="design.service",
                message="latest naming diagnostic",
            )
        ],
    )
    data["human_confirmations"]["confirmations"] = [confirmation()]
    return data


def human_decision(data, outcome="excluded"):
    review = review_for(data)
    review["diagnostic_decisions"] = [
        dict(
            id="current",
            outcome=outcome,
            reason="Reviewed the explicit exception",
            confirmation_id="human-1",
            target=dict(resource="001", property="S3.Bucket.BucketName"),
            evidence="Current Resource 001 BucketName matches the confirmed exception",
        )
    ]
    return review


def check_snapshot_replaces_inventory(tmp_path):
    data = snapshot_artifact(
        tmp_path,
        services=["s3", "sqs"],
        ordinary=[dict(id="current", service="s3", message="latest finding")],
    )
    for name in ("issues.md", "iac-issues.md"):
        write(
            tmp_path / "issues/dev/123456789012" / name, "old issue and old Human prose"
        )
    original = deepcopy(data)
    with (
        task(tmp_path, data["services"]),
        patch.object(
            Path, "read_text", BoundCallback(forbid_report_text, Path.read_text)
        ),
    ):
        outputs, snapshot, _ = save_scan(tmp_path, data, review_for(data))
    text = outputs[0].read_text()
    assert (
        "old issue" not in text
        and "old Human prose" not in text
        and "latest finding" in text
    )
    snapshot = review_snapshot(data, review_for(data))
    first = render_snapshot(tmp_path, snapshot)
    assert first == render_snapshot(tmp_path, snapshot)
    with pytest.raises(FrozenInstanceError):
        snapshot.data = "changed"
    data["ordinary"].clear()
    assert render_snapshot(tmp_path, snapshot) == first
    with task(tmp_path, data["services"]):
        save_scan(tmp_path, data, review_for(data))
    assert "latest finding" not in outputs[0].read_text()
    assert original["ordinary"][0]["message"] == "latest finding"


def check_review_additions_have_stable_ids_and_save(tmp_path):
    data = snapshot_artifact(
        tmp_path,
        ordinary=[
            dict(id=f"machine-{i}", service="s3", message=f"Machine finding {i}")
            for i in range(16)
        ],
    )
    review = review_for(data)
    review["issues"] = [
        dict(
            service="s3",
            resource=f"{i:03d}",
            property="S3.Bucket.BucketName",
            rule="review.general",
            source=dict(path="model/dev/123456789012/s3.properties", line=i + 1),
            message=f"Review finding {i}",
        )
        for i in range(9)
    ]
    original_data, original_review = deepcopy(data), deepcopy(review)
    with task(tmp_path, ["s3"]):
        outputs, snapshot, _ = save_scan(tmp_path, data, review)
    ordinary = json.loads(snapshot.data)["ordinary"]
    assert len(ordinary) == 25
    assert all(isinstance(item["id"], str) and item["id"].strip() for item in ordinary)
    assert len({item["id"] for item in ordinary}) == 25
    assert ordinary[:16] == original_data["ordinary"]
    assert data == original_data and review == original_review
    assert review_snapshot(data, review) == snapshot
    review["issues"] = [
        dict(reversed(item.items())) for item in reversed(review["issues"])
    ]
    reordered = review_snapshot(data, review)
    assert {
        item["message"]: item["id"] for item in json.loads(reordered.data)["ordinary"]
    } == {item["message"]: item["id"] for item in ordinary}
    rendered = render_snapshot(tmp_path, snapshot)
    assert render_snapshot(tmp_path, reordered) == rendered
    assert [path.name for path in outputs] == ["issues.md", "iac-issues.md"]
    assert tuple(path.read_text(encoding="utf-8") for path in outputs) == rendered
    for item in ordinary[16:]:
        assert item["message"] in rendered[0]
        assert f"<!-- issue-id: {item['id']} -->" in rendered[0]
    data["scan_id"] = review["scan_id"] = "b" * 32
    data["executed_at"] = "2026-10-26T00:00:00Z"
    assert (
        json.loads(review_snapshot(data, review).data)["ordinary"]
        == json.loads(reordered.data)["ordinary"]
    )


def check_naming_review_contract(tmp_path):
    data = snapshot_artifact(tmp_path)
    pattern = "bucket-{{application}}-{{environment}}"
    data["naming_context"] = {
        "rules": {
            "S3": [dict(text=f"| X | X | `S3.Bucket` | `Name` | `{pattern}` |")],
            "common": [dict(path="framework/rules/aws-resource-naming.md")],
        },
        "target_context": {"environment": "dev"},
    }
    data["naming_context_id"] = identifier(data["naming_context"])
    data["naming"]["names"] = [
        dict(
            id="n1",
            service="s3",
            resource="001",
            property="Name",
            resourceType="S3.Bucket",
            resourceMode="CREATE",
            value="wrong-app-dev",
            value_available=True,
            required_missing=False,
        )
    ]
    review = review_for(data)
    assert not json.loads(review_snapshot(data, review).data)["ordinary"]
    assert not json.loads(review_snapshot(data, review).data)["unverified"]
    issue = dict(
        service="s3",
        resource="001",
        property="Name",
        rule="review.naming",
        naming_item_id="n1",
        applied_rule=pattern,
        violation="format",
        evidence="The fixed prefix differs",
        message="Incorrect prefix",
    )
    review["issues"] = [issue]
    assert len(json.loads(review_snapshot(data, review).data)["ordinary"]) == 1
    for changes in (
        {"rule": "naming", "naming_item_id": "bad"},
        {"naming_item_id": "bad"},
        {"resource": "002"},
        {"property": "Other"},
        {"violation": "human_unknown"},
        {"evidence": ""},
        {"applied_rule": ""},
        {"applied_rule": "unregistered"},
        {"violation": "confirmed_mismatch"},
    ):
        review["issues"] = [dict(issue, **changes)]
        with pytest.raises(ValueError):
            review_snapshot(data, review)
    data["naming"]["names"][0]["resourceMode"] = "IMPORT"
    review["issues"] = [issue]
    with pytest.raises(ValueError):
        review_snapshot(data, review)
    data["naming"]["names"][0]["provider_errors"] = ["Name: invalid"]
    review["issues"] = [
        dict(issue, violation="provider_constraint", applied_rule="Name: invalid")
    ]
    assert len(json.loads(review_snapshot(data, review).data)["ordinary"]) == 1
    review["issues"] = []
    review["unverified"] = [
        dict(service="s3", check="naming", reason="Human component unknown")
    ]
    with pytest.raises(ValueError):
        review_snapshot(data, review)
    review["unverified"] = [
        dict(
            service="s3",
            check="naming",
            reason="Failed to read rule",
            failure_kind="read_failure",
        )
    ]
    with pytest.raises(ValueError, match="recorded scan failure"):
        review_snapshot(data, review)
    findings = Findings(tmp_path)
    with scan_stage(findings, "materials.naming", {("dev", "123456789012", "s3")}):
        (tmp_path / "missing-naming-rule").read_text(encoding="utf-8")
    data["processing_errors"] = findings.processing_errors
    data["unverified"] = findings.unverified
    assert (
        json.loads(review_snapshot(data, review).data)["unverified"]
        == findings.unverified + review["unverified"]
    )
    data["processing_errors"][0]["scope"] = ["dev/123456789012/other"]
    with pytest.raises(ValueError, match="recorded scan failure"):
        review_snapshot(data, review)


@pytest.mark.parametrize("rule", ["EC2.VPC.Name", "review.other"])
def check_naming_target_cannot_bypass_evidence(tmp_path, rule):
    data = snapshot_artifact(tmp_path, services=["vpc"])
    data["naming"]["names"] = [
        dict(id="n1", service="vpc", resource="001", property="Name")
    ]
    review = review_for(data)
    review["issues"] = [
        dict(
            service="vpc",
            resource="001",
            property="Name",
            rule=rule,
            message="Human confirmation is unavailable",
        )
    ]
    with pytest.raises(ValueError, match="naming_item_id"):
        review_snapshot(data, review)


@pytest.mark.parametrize(
    "prop", ["Name tag", "Tags[].Value", "EC2.VPCEndpoint.Tags[].Value"]
)
@pytest.mark.parametrize(
    "same_source",
    [
        True,
        False,
        None,
        "key",
        "line",
        "path",
        "all",
        "contradiction",
        "other_key",
        "other_line",
        "missing_path",
    ],
)
def check_name_tag_review_identity(tmp_path, prop, same_source):
    data = snapshot_artifact(tmp_path, services=["vpc"])
    source = dict(
        path="model/dev/123456789012/vpc.properties",
        line=12,
        key="desired.row.001-002.value",
    )
    other = dict(source, line=14, key="desired.row.001-004.value")
    data["naming"]["names"] = [
        dict(
            id="n1",
            service="vpc",
            resource="001",
            resourceType="EC2.VPCEndpoint",
            property="Name tag",
            source=source,
            tag_values=[dict(property="Tags[].Value", is_name=False, source=other)],
        )
    ]
    issue = dict(
        service="vpc",
        resource="001",
        property=prop,
        rule="review.other",
        message="Human confirmation is unavailable",
    )
    if same_source in {"key", "line", "path"}:
        issue["source"] = dict(
            other,
            **{
                same_source: {
                    "key": "desired.row.001-999.value",
                    "line": 9999,
                    "path": "model/dev/missing/vpc.properties",
                }[same_source]
            },
        )
        if same_source == "line":
            issue["source"].pop("key")
    elif same_source in {"other_key", "other_line", "missing_path"}:
        issue["source"] = dict(other)
        issue["source"].pop(
            {"other_key": "line", "other_line": "key", "missing_path": "path"}[
                same_source
            ]
        )
    elif same_source == "all":
        issue["source"] = dict(
            path="model/dev/missing/vpc.properties",
            line=9999,
            key="desired.row.001-999.value",
        )
    elif same_source == "contradiction":
        issue["source"] = dict(other, line=9999)
    elif same_source is not None:
        issue["source"] = (
            dict(source)
            if same_source
            else dict(source, line=14, key="desired.row.001-004.value")
        )
    review = review_for(data)
    review["issues"] = [issue]
    if prop != "Name tag" and (
        same_source is False or same_source in {"other_key", "other_line"}
    ):
        issue["message"] = "Ordinary owner Tag value violates the reviewed policy"
        assert len(json.loads(review_snapshot(data, review).data)["ordinary"]) == 1
        with task(tmp_path, data["services"]):
            outputs, snapshot, _ = save_scan(tmp_path, data, review)
        assert len(json.loads(snapshot.data)["ordinary"]) == 1
        assert issue["message"] in outputs[0].read_text(encoding="utf-8")
    else:
        for filename in ("issues.md", "iac-issues.md"):
            write(tmp_path / "issues/dev/123456789012" / filename, "existing report")
        with pytest.raises(ValueError):
            review_snapshot(data, review)
        with task(tmp_path, data["services"]), pytest.raises(ValueError):
            save_scan(tmp_path, data, review)
        for filename in ("issues.md", "iac-issues.md"):
            assert (tmp_path / "issues/dev/123456789012" / filename).read_text(
                encoding="utf-8"
            ) == "existing report"


@pytest.mark.parametrize(
    "prop", ["Name tag", "Tags[].Value", "EC2.VPCEndpoint.Tags[].Value"]
)
def check_name_tag_valid_violation_aliases(tmp_path, prop):
    data = snapshot_artifact(tmp_path, services=["network"])
    pattern = "vpce-{{application}}-{{environment}}-{{service}}"
    data["naming_context"] = dict(
        rules=dict(
            EC2=[dict(text=f"| X | X | `EC2.VPCEndpoint` | `Name tag` | `{pattern}` |")]
        )
    )
    data["naming_context_id"] = identifier(data["naming_context"])
    source = dict(
        path="model/dev/123456789012/network.properties",
        line=12,
        key="desired.row.001-002.value",
    )
    data["naming"]["names"] = [
        dict(
            id="n1",
            service="network",
            resource="001",
            resourceType="EC2.VPCEndpoint",
            resourceMode="CREATE",
            property="Name tag",
            value="wrong-prefix",
            value_available=True,
            source=source,
        )
    ]
    review = review_for(data)
    review["issues"] = [
        dict(
            service="network",
            resource="001",
            property=prop,
            source=source,
            naming_item_id="n1",
            rule="review.naming",
            applied_rule=pattern,
            violation="format",
            evidence="Fixed prefix is wrong",
            message="Naming violation",
        )
    ]
    assert len(json.loads(review_snapshot(data, review).data)["ordinary"]) == 1
    with task(tmp_path, data["services"]):
        _, snapshot, _ = save_scan(tmp_path, data, review)
    assert len(json.loads(snapshot.data)["ordinary"]) == 1
    review["issues"][0]["source"] = dict(
        source, line=14, key="desired.row.001-004.value"
    )
    with pytest.raises(ValueError, match="match its naming item"):
        review_snapshot(data, review)
    with (
        task(tmp_path, data["services"]),
        pytest.raises(ValueError, match="match its naming item"),
    ):
        save_scan(tmp_path, data, review)


@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
@pytest.mark.parametrize(
    "kind, tags",
    [("EC2.VPCEndpoint", "Tags"), ("Route53.HostedZone", "HostedZoneTags")],
)
def check_scan_tag_sources(tmp_path, mode, kind, tags):
    fixture(tmp_path, services=("sqs",))
    comparison = Comparison(tmp_path, "dev", "123456789012", ["sqs"])
    comparison.resources["sqs"]["001"].update(resourceType=kind, resourceMode=mode)
    rows = [
        (
            f"001-{number:03d}",
            dict(property=f"{kind}.{tags}[].{prop}", value=value, comment="Tag row"),
        )
        for number, (prop, value) in enumerate(
            [
                ("Key", "`Name`"),
                ("Value", "`existing-name`"),
                ("Key", "`owner`"),
                ("Value", "`invalid-owner`"),
                ("Key", "`UNSET`"),
                ("Value", "`unknown`"),
            ],
            1,
        )
    ]
    comparison.rows["sqs"]["001"] = rows
    material, _ = naming_materials(comparison)
    name = next(item for item in material["names"] if item["property"] == "Name tag")
    assert name["tag_values"] == [
        dict(
            property=tags + "[].Value",
            is_name=is_name,
            source=comparison.source("sqs", f"desired.row.{rid}.value"),
        )
        for rid, is_name in [("001-002", True), ("001-004", False)]
    ]
    data = snapshot_artifact(tmp_path, services=["sqs"])
    data["naming"]["names"] = material["names"]
    review = review_for(data)
    review["issues"] = [
        dict(
            service="sqs",
            resource="001",
            property=kind + "." + tags + "[].Value",
            source=name["tag_values"][1]["source"],
            rule="review.owner",
            message="Owner Tag is invalid",
        )
    ]
    # Review and publication consume the Scan data, never reread the Model.
    (tmp_path / "model/dev/123456789012/sqs.properties").unlink()
    with task(tmp_path, data["services"]):
        outputs, snapshot, _ = save_scan(tmp_path, data, review)
    assert len(json.loads(snapshot.data)["ordinary"]) == 1
    assert "Owner Tag is invalid" in outputs[0].read_text(encoding="utf-8")
    for rid in ("001-002", "001-006"):
        review["issues"][0]["source"] = comparison.source(
            "sqs", f"desired.row.{rid}.value"
        )
        with pytest.raises(ValueError, match="naming_item_id"):
            review_snapshot(data, review)
        with (
            task(tmp_path, data["services"]),
            pytest.raises(ValueError, match="naming_item_id"),
        ):
            save_scan(tmp_path, data, review)


@pytest.mark.parametrize("kind", ["reference", "display"])
@pytest.mark.parametrize("prop", ["Name", "CidrBlock"])
def check_independent_issue_on_naming_property(tmp_path, kind, prop):
    data = snapshot_artifact(tmp_path, services=["vpc"])
    data["naming"]["names"] = [
        dict(
            id="n1",
            service="vpc",
            resource="001",
            property="Name",
            resourceType="EC2.VPC",
        )
    ]
    code = "REF_TARGET_MISSING" if kind == "reference" else "design.display.mismatch"
    diagnostic = (
        dict(
            code=code,
            model="model/dev/123456789012/vpc.properties",
            modelKey="desired.row.001-001.value",
            property=prop,
            category="MODEL_NEEDS_FIX",
        )
        if kind == "reference"
        else dict(code=code, check_id="design.tables", cause_kind="input_invalid")
    )
    data["ordinary"] = [
        dict(
            id="independent",
            service="vpc",
            resource="001",
            property=prop,
            rule=code,
            cause_kind="input_invalid",
            diagnostic=diagnostic,
            message="Independent violation",
        )
    ]
    review = review_for(data)
    issue = dict(
        service="vpc",
        resource="001",
        property=prop,
        rule=code,
        diagnostic_id="independent",
        message="Independent violation",
    )
    review["issues"] = [issue]
    with pytest.raises(ValueError, match="diagnostic_decisions"):
        review_snapshot(data, review)
    with (
        task(tmp_path, data["services"]),
        pytest.raises(ValueError, match="diagnostic_decisions"),
    ):
        save_scan(tmp_path, data, review)
    for changes in (
        dict(diagnostic_id="missing"),
        dict(rule="review.other"),
        dict(resource="002"),
        dict(property="Other"),
        dict(naming_item_id="n1"),
        dict(violation="human_unknown"),
        dict(expected="dev", actual="stg"),
    ):
        review["issues"] = [dict(issue, **changes)]
        with pytest.raises(ValueError):
            review_snapshot(data, review)
    review["issues"] = []
    independent = deepcopy(data["ordinary"][0])
    independent.update(
        id="another",
        rule="another.violation",
        diagnostic=dict(code="another.violation", category="MODEL_NEEDS_FIX"),
    )
    data["ordinary"].append(independent)
    review = review_for(data)
    snapshot = json.loads(review_snapshot(data, review).data)
    assert [item["id"] for item in snapshot["ordinary"]] == ["independent", "another"]
    assert not snapshot["unverified"]
    with task(tmp_path, data["services"]):
        outputs, saved, _ = save_scan(tmp_path, data, review)
    assert len(json.loads(saved.data)["ordinary"]) == 2
    text = outputs[0].read_text(encoding="utf-8")
    assert text.count("<!-- issue-id: independent -->") == 1
    assert text.count("<!-- issue-id: another -->") == 1
    # Omitting the ID or changing the message must not duplicate a known violation.
    duplicate = {key: value for key, value in issue.items() if key != "diagnostic_id"}
    duplicate["message"] = "Different wording for the same structured violation"
    review["issues"] = [duplicate]
    with pytest.raises(ValueError, match="diagnostic_decisions"):
        review_snapshot(data, review)
    with (
        task(tmp_path, data["services"]),
        pytest.raises(ValueError, match="diagnostic_decisions"),
    ):
        save_scan(tmp_path, data, review)


@pytest.mark.parametrize(
    (
        "pattern",
        "value",
        "confirmations",
        "expected",
        "observed",
        "accepted",
        "extra_pattern",
    ),
    [
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-other-stg",
            {"application": "venusinf"},
            "venusinf",
            "invented",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-other-stg",
            {"application": "venusinf"},
            "unconfirmed",
            "other",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-other-dev",
            {},
            "venusinf",
            "other",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-venusinf-dev",
            {"application": "venusinf"},
            "dev",
            "stg",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}[-{{suffix}}]",
            "vpc-other-stg-x",
            {"application": "venusinf", "suffix": "confirmed"},
            "dev",
            "stg",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-other-stg",
            {"application": "venusinf"},
            "venusinf",
            "other",
            True,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-other-stg",
            {"application": "venusinf"},
            "dev",
            "stg",
            True,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-venusinf-test-dev",
            {"application": "venusinf"},
            "dev",
            "test-dev",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-other-dev",
            {"application": "venusinf"},
            "venusinf",
            "other",
            True,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-other-dev",
            {},
            "dev",
            "other",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}[-{{suffix}}]",
            "vpc-venusinf-test-dev",
            {"application": "venusinf"},
            "dev",
            "test-dev",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}[-{{suffix}}]",
            "vpc-venusinf-dev-extra",
            {"application": "venusinf"},
            "dev",
            "dev-extra",
            False,
            None,
        ),
        (
            "vpc-{{application}}-{{environment}}",
            "vpc-venusinf-test-dev",
            {"application": "venusinf"},
            "dev",
            "test-dev",
            False,
            "vpc-{{application}}-test-{{environment}}",
        ),
    ],
)
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def check_confirmed_components_together(
    tmp_path,
    pattern,
    value,
    confirmations,
    expected,
    observed,
    accepted,
    extra_pattern,
    mode,
):
    data = snapshot_artifact(tmp_path, services=["vpc"])
    patterns = [pattern] + ([extra_pattern] if extra_pattern else [])
    data["naming_context"] = {
        "target_context": {"environment": "dev"},
        "rules": {
            "EC2": [
                dict(
                    text="\n".join(
                        f"| X | X | `EC2.VPC` | `Name` | `{p}` |" for p in patterns
                    )
                )
            ]
        },
    }
    data["naming_context_id"] = identifier(data["naming_context"])
    data["naming"]["names"] = [
        dict(
            id="n1",
            service="vpc",
            resource="001",
            property="Name",
            resourceType="EC2.VPC",
            resourceMode=mode,
            value=value,
            value_available=True,
        )
    ]
    data["human_confirmations"]["confirmations"] = [
        dict(
            id=key,
            service="vpc",
            fact=f"{key}={val}",
            scope=dict(resource="001", property="Name"),
            exceptions=[],
            evidence="Human confirmation",
        )
        for key, val in confirmations.items()
    ]
    review = review_for(data)
    review["issues"] = [
        dict(
            service="vpc",
            resource="001",
            property="Name",
            rule="review.naming",
            naming_item_id="n1",
            violation="confirmed_mismatch",
            applied_rule=pattern,
            expected=expected,
            actual=observed,
            evidence="Confirmed values and name",
            message="Mismatch",
        )
    ]
    if accepted:
        assert len(json.loads(review_snapshot(data, review).data)["ordinary"]) == 1
    else:
        with pytest.raises(ValueError, match="mismatch"):
            review_snapshot(data, review)


def check_non_naming_unverified_contract(tmp_path):
    data = snapshot_artifact(tmp_path)
    review = review_for(data)
    review["issues"] = [dict(service="s3", rule="review.other", message="Other issue")]
    review["unverified"] = [dict(service="s3", check="other", reason="Not run")]
    snapshot = json.loads(review_snapshot(data, review).data)
    assert snapshot["ordinary"][0]["message"] == "Other issue"
    assert snapshot["unverified"] == review["unverified"]


@pytest.mark.parametrize(
    ("kind", "pattern", "value", "violation", "expected", "actual"),
    [
        (
            "EC2.VPC",
            "vpc-{{application}}-{{environment}}",
            "vpc-example-dev",
            None,
            None,
            None,
        ),
        (
            "EC2.Subnet",
            "sbnt-{{application}}-{{environment}}-{{subnet_type}}-{{route_type}}-{{zone}}-{{number}}",
            "sbnt-example-dev-data-private-1a-01",
            None,
            None,
            None,
        ),
        (
            "EC2.RouteTable",
            "rtb-{{application}}-{{environment}}-{{subnet_type}}-{{route_type}}[-{{zone}}]-{{number}}",
            "rtb-example-dev-data-private-1a-01",
            None,
            None,
            None,
        ),
        (
            "EC2.FlowLog",
            "flowlog-{{application}}-{{environment}}[-{{target_alias}}]",
            "flowlog-example-dev",
            None,
            None,
            None,
        ),
        (
            "EC2.VPCEndpoint",
            "vpce-{{application}}-{{environment}}-{{service}}",
            "vpce-example-dev-s3-gateway",
            None,
            None,
            None,
        ),
        (
            "EC2.VPC",
            "vpc-{{application}}-{{environment}}",
            "wrong-example-dev",
            "format",
            None,
            None,
        ),
        (
            "EC2.VPC",
            "vpc-{{application}}-{{environment}}",
            "vpc-example-stg",
            "confirmed_mismatch",
            "dev",
            "stg",
        ),
        (
            "EC2.VPC",
            "vpc-{{application}}-{{environment}}",
            None,
            "required_missing",
            None,
            None,
        ),
        (
            "EC2.VPC",
            "vpc-{{application}}-{{environment}}",
            "vpc-other-dev",
            "confirmed_mismatch",
            "example",
            "other",
        ),
    ],
)
def check_naming_review_real_patterns_and_confirmed_values(
    tmp_path, kind, pattern, value, violation, expected, actual
):
    # The reviewer supplies the decision; this exercises the real Scan/Review boundary.
    rule_file = (
        Path(__file__).resolve().parents[4]
        / "framework/rules/aws-resource-naming/EC2.md"
    )
    assert any(
        f"`{kind}`" in line and f"`{pattern}`" in line
        for line in rule_file.read_text(encoding="utf-8").splitlines()
    )
    assert "{{purpose}}" not in pattern
    data = snapshot_artifact(tmp_path, services=["vpc"])
    data["naming_context"] = {
        "target_context": {"environment": "dev"},
        "rules": {"EC2": [dict(text=rule_file.read_text(encoding="utf-8"))]},
    }
    data["naming_context_id"] = identifier(data["naming_context"])
    prop = "Name tag" if kind == "EC2.VPCEndpoint" else "Name"
    item = dict(
        id="name-1",
        service="vpc",
        resource="001",
        resourceType=kind,
        resourceMode="CREATE",
        property=prop,
        value=value,
        value_available=value is not None,
        required_missing=value is None,
    )
    data["naming"]["names"] = [item]
    if expected == "example":
        data["human_confirmations"]["confirmations"] = [
            dict(
                id="app",
                service="vpc",
                fact="application=example",
                evidence="Human confirmed application",
                scope=dict(resource="001", property=prop),
                exceptions=[],
            )
        ]
    review = review_for(data)
    if violation:
        issue = dict(
            service="vpc",
            resource="001",
            property=prop,
            rule="review.naming",
            naming_item_id="name-1",
            applied_rule=pattern,
            violation=violation,
            evidence="Pattern and confirmed target values demonstrate the violation",
            message="Naming rule violation",
        )
        if expected is not None:
            issue.update(expected=expected, actual=actual)
        review["issues"] = [issue]
    snapshot = json.loads(review_snapshot(data, review).data)
    assert len(snapshot["ordinary"]) == (1 if violation else 0)
    assert snapshot["unverified"] == []
    if violation:
        assert snapshot["ordinary"][0]["violation"] == violation


@pytest.mark.parametrize("fault", ["review_duplicate", "machine_collision"])
def check_review_duplicate_ids_rejected_before_rendering(tmp_path, fault):
    data = snapshot_artifact(tmp_path)
    review = review_for(data)
    review["issues"] = [dict(service="s3", message="Review finding")]
    if fault == "review_duplicate":
        review["issues"].append(deepcopy(review["issues"][0]))
    else:
        issue = json.loads(review_snapshot(data, review).data)["ordinary"][0]
        data["ordinary"] = [dict(issue, message="Machine finding")]
        review["diagnostic_decisions"] = review_for(data)["diagnostic_decisions"]
    directory = tmp_path / "issues/dev/123456789012"
    reports = [directory / name for name in ("issues.md", "iac-issues.md")]
    for report in reports:
        write(report, "original-" + report.name)
    before = {report: report.read_bytes() for report in reports}
    with (
        task(tmp_path, ["s3"]),
        patch("issues.publication.render_snapshot") as render,
        patch("issues.publication.atomic_files") as publish,
    ):
        with pytest.raises(ValueError, match="duplicate current diagnostic ID"):
            save_scan(tmp_path, data, review)
        render.assert_not_called()
        publish.assert_not_called()
    assert {report: report.read_bytes() for report in reports} == before


@pytest.mark.parametrize(
    "change",
    ["unchanged", "completed", "allowed", "modified", "scope", "type", "grant"],
)
def check_save_authority_ignores_cached_task(tmp_path, change):
    data = snapshot_artifact(tmp_path)
    reports = [
        tmp_path / "issues/dev/123456789012" / name
        for name in ("issues.md", "iac-issues.md")
    ]
    for report in reports:
        write(report, "existing report\n")
    before = {report: report.read_bytes() for report in reports}
    with task(tmp_path, ["sqs" if change == "grant" else "s3"]), task_reads(tmp_path):
        cached = task_snapshot(tmp_path)
        assert active_scope(tmp_path) == {
            ("dev", "123456789012", "sqs" if change == "grant" else "s3")
        }
        text = cached.text
        if change == "completed":
            text = text.replace("`running`", "`completed`")
        elif change in {"allowed", "modified"}:
            heading = "## " + (
                "Allowed paths" if change == "allowed" else "Modified files"
            )
            head, tail = text.split(heading, 1)
            text = (
                head
                + heading
                + tail.replace("- `issues/dev/123456789012/issues.md`\n", "", 1)
            )
        elif change in {"scope", "grant"}:
            text = text.replace(
                "/sqs`" if change == "grant" else "/s3`",
                "/s3`" if change == "grant" else "/sqs`",
            )
        elif change == "type":
            text = text.replace("`migration`", "`governance`")
        cached.path.write_text(text, encoding="utf-8")
        with patch.object(
            publication, "atomic_files", wraps=publication.atomic_files
        ) as saved:
            if change in {"unchanged", "grant"}:
                paths, _, task_name = save_scan(tmp_path, data, review_for(data))
                assert paths == reports and task_name == cached.name
                saved.assert_called_once()
                assert all(report.read_bytes() != before[report] for report in reports)
            else:
                with pytest.raises(ValueError):
                    save_scan(tmp_path, data, review_for(data))
                saved.assert_not_called()
                assert {report: report.read_bytes() for report in reports} == before
        assert task_snapshot(tmp_path) is cached


@pytest.mark.parametrize("selection", ["environment", "api", "implicit"])
def check_save_authority_reselects_live_task(tmp_path, monkeypatch, selection):
    data = snapshot_artifact(tmp_path)
    with (
        task(tmp_path, ["s3"]),
        task_reads(tmp_path),
        monkeypatch.context() as selection_env,
    ):
        cached = task_snapshot(tmp_path)
        name = "tasks/authorized.md"
        write(tmp_path / name, cached.text.replace(cached.name, name))
        if selection == "environment":
            selection_env.setenv("BLUEPRINT_TASK_FILE", name)
        else:
            selection_env.setenv("BLUEPRINT_TASK_FILE", "")
        if selection == "implicit":
            cached.path.write_text(
                cached.text.replace("`running`", "`completed`"), encoding="utf-8"
            )
        with selected_task(tmp_path, name if selection == "api" else None):
            _, _, task_name = save_scan(tmp_path, data, review_for(data))
        assert task_name == name


def check_human_exception_and_conflict(tmp_path):
    data = reviewed_artifact(tmp_path)
    path = tmp_path / "issues/dev/123456789012/human-confirmations.yaml"
    write(
        path, "# Human facts are read-only\n" + json.dumps(data["human_confirmations"])
    )
    assert (
        human_confirmations(tmp_path, "dev", "123456789012")
        == data["human_confirmations"]
    )
    original = path.read_bytes()
    with task(tmp_path, ["s3"]):
        outputs, snapshot, _ = save_scan(tmp_path, data, human_decision(data))
        assert [output.name for output in outputs] == ["issues.md", "iac-issues.md"]
        assert "latest naming diagnostic" not in outputs[0].read_text()
        assert "未解決issueなし" in outputs[0].read_text()
        assert summary(json.loads(snapshot.data))["validation_status"] == "CHECKED"
        assert summary(json.loads(snapshot.data))["review_required"] is False
        outputs, snapshot, _ = save_scan(
            tmp_path, data, human_decision(data, "conflict")
        )
    assert "human.confirmation_conflict" in outputs[0].read_text()
    assert "latest naming diagnostic" in outputs[0].read_text()
    assert "検証: 未完了" in outputs[0].read_text()
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "fault",
    [
        "id",
        "service",
        "resource",
        "property",
        "evidence",
        "exceptions",
        "missing_resource",
        "missing_property",
        "missing_rule",
        "wildcard_resource",
        "wildcard_property",
        "wrong_property",
        "wrong_rule",
        "wrong_diagnostic",
        "public_access",
    ],
)
def check_exclusion_scope(tmp_path, fault):
    data = reviewed_artifact(tmp_path)
    review = human_decision(data)
    if fault == "id":
        review["diagnostic_decisions"][0]["confirmation_id"] = "unknown"
    elif fault in {"service", "exceptions"}:
        data["human_confirmations"]["confirmations"][0][fault] = (
            "sqs" if fault == "service" else []
        )
    elif fault == "evidence":
        review["diagnostic_decisions"][0][fault] = ""
    elif fault.startswith("missing_"):
        data["ordinary"][0].pop(fault.removeprefix("missing_"))
    elif fault.startswith("wildcard_"):
        data["ordinary"][0][fault.removeprefix("wildcard_")] = "*"
    elif fault == "wrong_property":
        data["ordinary"][0]["property"] = "S3.Bucket.PublicAccessBlockConfiguration"
    elif fault == "wrong_rule":
        data["ordinary"][0]["rule"] = "other.rule"
    elif fault == "wrong_diagnostic":
        data["human_confirmations"]["confirmations"][0]["exceptions"][0][
            "diagnostic_id"
        ] = "other"
    elif fault == "public_access":
        data["ordinary"][0] = dict(
            id="current", service="s3", message="Public access restriction violation"
        )
    else:
        review["diagnostic_decisions"][0]["target"][fault] = "other"
    with pytest.raises(ValueError):
        review_snapshot(data, review)
    retained = json.loads(review_snapshot(data, review_for(data)).data)
    assert retained["ordinary"] == data["ordinary"]


@pytest.mark.parametrize(
    "fault,field",
    [
        ("exception_text", "rule/diagnostic_id/condition"),
        ("wildcard", "resource"),
        ("missing_rule", "rule"),
        ("empty_condition", "condition"),
        ("missing_fact", "fact"),
        ("old_related", "related_issues"),
        ("old_version", "version 2"),
    ],
)
def check_human_contract_refuses_unsupported_records(tmp_path, fault, field):
    data = reviewed_artifact(tmp_path)
    human = data["human_confirmations"]
    confirmed = human["confirmations"][0]
    if fault == "exception_text":
        confirmed["exceptions"] = ["old unrestricted exception"]
    elif fault == "wildcard":
        confirmed["scope"]["resource"] = "*"
    elif fault == "missing_rule":
        confirmed["exceptions"][0]["rule"] = ""
    elif fault == "missing_fact":
        confirmed.pop("fact")
    elif fault == "old_related":
        confirmed["related_issues"] = []
    elif fault == "old_version":
        human["version"] = 1
    else:
        confirmed["exceptions"][0]["condition"] = ""
    path = tmp_path / "issues/dev/123456789012/human-confirmations.yaml"
    write(path, json.dumps(human))
    before = path.read_bytes()
    with pytest.raises(ValueError, match=field):
        human_confirmations(tmp_path, "dev", "123456789012")
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "kind", ["unverified", "processing_errors", "service", "review"]
)
def check_incomplete_is_not_pass(tmp_path, kind):
    data = snapshot_artifact(tmp_path)
    if kind == "service":
        data["service_results"] = [
            dict(service="s3", status="unverified", reason="not executed")
        ]
    elif kind != "review":
        data[kind] = [dict(code="fixture.failure", message="check unavailable")]
    data["warnings"] = [dict(code="warning", message="warning only")]
    review = review_for(data)
    if kind == "review":
        data["processing_errors"].append(
            dict(
                phase="materials.naming",
                cause_kind="check_failure",
                scope=["dev/123456789012/s3"],
                exception="OSError",
            )
        )
        review["unverified"] = [
            dict(
                service="s3",
                check="naming",
                reason="Unable to read naming rules",
                failure_kind="read_failure",
            )
        ]
    with task(tmp_path, ["s3"]):
        outputs, snapshot, _ = save_scan(tmp_path, data, review)
    text = outputs[0].read_text()
    assert "未完了" in text and "未解決issueなし（検証未完了）" in text
    if kind == "service":
        assert "今回の判定: partial" in outputs[1].read_text()
        assert summary(json.loads(snapshot.data))["iac_status"] == "partial"


@pytest.mark.parametrize(
    "fault", ["partial", "missing_result", "duplicate", "reason", "scope"]
)
def check_partial_scope_refused(tmp_path, fault):
    data = snapshot_artifact(tmp_path, services=["s3", "sqs"])
    if fault == "partial":
        data["services"] = ["s3"]
    elif fault == "missing_result":
        data["service_results"].pop()
    elif fault == "duplicate":
        data["service_results"][1] = data["service_results"][0]
    elif fault == "reason":
        data["service_results"][0] = dict(service="s3", status="unverified")
    else:
        data["target_services"] = []
    with (
        task(tmp_path, ["s3", "sqs"]),
        patch("issues.publication.atomic_files") as publish,
    ):
        with pytest.raises(ValueError):
            save_scan(tmp_path, data, review_for(data))
        publish.assert_not_called()


def fail_replace(state, original, selected, after, source, destination):
    if Path(destination).name == selected and not state["failed"]:
        state["failed"] = True
        if after:
            original(source, destination)
        raise OSError("publication failure")
    return original(source, destination)


@pytest.mark.parametrize("selected", ["issues.md", "iac-issues.md"])
@pytest.mark.parametrize("after", [True, False])
def check_atomic_rollback(tmp_path, selected, after):
    data = reviewed_artifact(tmp_path)
    review = human_decision(data)
    directory = tmp_path / "issues/dev/123456789012"
    write(
        directory / "human-confirmations.yaml", json.dumps(data["human_confirmations"])
    )
    for name in ("issues.md", "iac-issues.md"):
        write(directory / name, "original-" + name)
    original = {path: path.read_bytes() for path in directory.iterdir()}
    state = dict(failed=False)
    with (
        task(tmp_path, ["s3"]),
        patch(
            "utils.file_operations.os.replace",
            partial(fail_replace, state, os.replace, selected, after),
        ),
    ):
        with pytest.raises(OSError, match="publication failure"):
            save_scan(tmp_path, data, review)
    assert (
        state["failed"]
        and {path: path.read_bytes() for path in directory.iterdir()} == original
    )


@pytest.mark.parametrize(
    "fault",
    [
        "scan_id",
        "context",
        "names",
        "judgments",
        "confirmations",
        "diagnostics",
        "resolved",
        "old_version",
        "cleanup_field",
    ],
)
def check_review_rejects_incomplete_and_old_inputs(tmp_path, fault):
    data = reviewed_artifact(tmp_path)
    review = review_for(data)
    data["naming"]["names"] = [dict(id="name")]
    data["judgments"] = [dict(id="judgment", kind="prose")]
    review.update(reviewed_names=["name"], reviewed_judgments=["judgment"])
    if fault == "scan_id":
        review["scan_id"] = "b" * 32
    elif fault == "context":
        review["reviewed_naming_context_id"] = "wrong"
    elif fault in {"names", "judgments", "confirmations"}:
        review["reviewed_" + fault] = []
    elif fault == "diagnostics":
        review["diagnostic_decisions"] = []
    elif fault == "resolved":
        review["resolved"] = []
    elif fault == "cleanup_field":
        review["confirmation_cleanup"] = []
    else:
        data["version"] = 5
    with pytest.raises(ValueError):
        save_scan(tmp_path, data, review)


def check_explicit_human_file_and_service_discovery(tmp_path):
    with pytest.raises(ValueError, match="required before switching"):
        human_confirmations(tmp_path, "dev", "123456789012")
    data = snapshot_artifact(tmp_path)["human_confirmations"]
    path = tmp_path / "issues/dev/123456789012/human-confirmations.yaml"
    write(path, json.dumps(data))
    assert human_confirmations(tmp_path, "dev", "123456789012") == data
    write(tmp_path / "model/dev/123456789012/s3.properties", "")
    write(tmp_path / "docs/designs/dev/123456789012/sqs.md", "")
    assert target_services(tmp_path, "dev", "123456789012") == ["s3", "sqs"]
    write(path, "version: 2\nversion: 2\n")
    with pytest.raises(ValueError, match="duplicate"):
        human_confirmations(tmp_path, "dev", "123456789012")


def check_reviewed_sources_are_not_reread(tmp_path):
    data = snapshot_artifact(
        tmp_path,
        ordinary=[
            dict(
                id="current",
                service="s3",
                message="Scan-time diagnostic",
                source=dict(path="model/dev/123456789012/s3.properties", line=20),
            )
        ],
    )
    source = tmp_path / "model/dev/123456789012/s3.properties"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("changed after Scan", encoding="utf-8")
    with (
        task(tmp_path, ["s3"]),
        patch(
            "subprocess.run", side_effect=AssertionError("saving must not inspect Git")
        ),
    ):
        outputs, snapshot, _ = save_scan(tmp_path, data, review_for(data))
    assert "s3.properties:20" in outputs[0].read_text()
    assert source.read_text() == "changed after Scan"


@pytest.mark.parametrize(
    "fault",
    [
        "diagnostic_service",
        "iac_service",
        "naive_time",
        "source_path",
        "source_line",
        "unverified_owner",
        "missing_id",
        "empty_id",
        "non_string_id",
        "duplicate_id",
        "review_id",
    ],
)
def check_snapshot_rejects_invalid_current_values(tmp_path, fault):
    data = reviewed_artifact(tmp_path)
    review = review_for(data)
    if fault == "diagnostic_service":
        data["ordinary"][0]["service"] = "sqs"
    elif fault == "iac_service":
        record = dict(
            service="s3",
            category="matched",
            resource="001",
            property="Name",
            reason="match",
        )
        data = snapshot_artifact(tmp_path, records=[record])
        data["iac"][0]["service"] = "sqs"
        data["record_meta"][0]["record_id"] = identifier(data["iac"][0])
        review = review_for(data)
    elif fault == "naive_time":
        data["executed_at"] = "2026-10-25T00:00:00"
    elif fault == "source_path":
        data["ordinary"][0]["source"] = dict(path="../outside", line=1)
    elif fault == "source_line":
        data["ordinary"][0]["source"] = dict(path="model/s3.properties", line=0)
    elif fault == "missing_id":
        data["ordinary"][0].pop("id")
    elif fault in {"empty_id", "non_string_id"}:
        data["ordinary"][0]["id"] = " " if fault == "empty_id" else 42
    elif fault == "duplicate_id":
        data["ordinary"].append(deepcopy(data["ordinary"][0]))
    elif fault == "review_id":
        review["issues"] = [dict(id="not-allowed", service="s3", message="Finding")]
    else:
        review["unverified"] = [dict(service="sqs", check="naming", reason="unknown")]
    with task(tmp_path, ["s3"]), patch("issues.publication.atomic_files") as publish:
        with pytest.raises(ValueError):
            save_scan(tmp_path, data, review)
        publish.assert_not_called()


def decision_artifact(root, kind, prop, value, mode="CREATE"):
    data = snapshot_artifact(root, services=["naming"])
    definitions = Path(__file__).resolve().parents[4]
    files = naming_rule_files(definitions, kind.partition(".")[0])
    data["naming_context"] = dict(
        target_context=dict(
            environment="dev", awsAccountId="123456789012", suffix=None
        ),
        rules={
            "common": [
                dict(
                    path=files[0].relative_to(definitions).as_posix(),
                    text=files[0].read_text(encoding="utf-8"),
                )
            ],
            kind.partition(".")[0]: [
                dict(
                    path=path.relative_to(definitions).as_posix(),
                    text=path.read_text(encoding="utf-8"),
                )
                for path in files[1:]
            ],
        },
    )
    data["naming_context_id"] = identifier(data["naming_context"])
    errors = []
    if value is not None:
        if prop != "Name tag" and (prop != "Name" or not kind.startswith("EC2.")):
            errors = DesignSchemaCatalog(definitions).literal_errors(kind, prop, value)
        errors.extend(provider_naming_errors(kind, prop, value))
    name = dict(
        id="n1",
        service="naming",
        resource="001",
        resourceType=kind,
        property=prop,
        value=value,
        value_available=value is not None,
        required_missing=value is None,
        provider_errors=errors,
        provider_checked=True,
        resourceMode=mode,
    )
    data["naming"]["names"] = [name]
    name["decision"] = naming_decision(data, name)
    return data, name


def check_target_and_naming_regressions(tmp_path):
    check = TestCase()
    common = dict(
        environment="dev",
        awsAccountId="123456789012",
        awsRegion="ap-northeast-1",
        iacEngine="cloudformation",
    )
    topology = {
        "targets": [
            dict(common, alias="cde", suffix="p4x8r2"),
            dict(common, alias="non-cde", suffix="skbm1r"),
            dict(common, alias="plain"),
        ]
    }
    for alias, suffix in (("cde", "p4x8r2"), ("non-cde", "skbm1r"), ("plain", None)):
        target = select_target(topology, "dev", alias=alias)
        check.assertEqual((target["environment"], target["suffix"]), ("dev", suffix))
    for purpose in (
        "ApplicationBuild",
        "AwsInfrastructureValidation",
        "Package",
        "PrimaryQuarantineAndSign",
        "Quarantine",
        "QuarantineSign",
        "SignVerify",
        "ApplicationRelease",
        "GlueConnection",
        "VulnerabilityScan",
    ):
        data, name = decision_artifact(
            tmp_path, "IAM.Role", "RoleName", f"venusinf-dev-{purpose}Role-p4x8r2"
        )
        data["naming_context"]["target_context"]["suffix"] = "p4x8r2"
        check.assertEqual(naming_decision(data, name)["status"], "AUTO_PASS")
    data, name = decision_artifact(
        tmp_path, "Macie.ClassificationJob", "name", "macie-venusinf-dev-sad-p4x8r2"
    )
    data["naming_context"]["target_context"]["suffix"] = "skbm1r"
    check.assertEqual(naming_decision(data, name)["status"], "VIOLATION_CANDIDATE")
    name["value"] = "macie-venusinf-dev-sad-skbm1r"
    check.assertEqual(naming_decision(data, name)["status"], "AUTO_PASS")
    data, name = decision_artifact(tmp_path, "EC2.VPC", "Name", "vpc-app-stg")
    check.assertEqual(naming_decision(data, name)["status"], "VIOLATION_CANDIDATE")
    for kind in ("EC2.TransitGatewayVpcAttachment", "EC2.TransitGatewayRouteTable"):
        data, name = decision_artifact(tmp_path, kind, "Name tag", "wrong")
        check.assertNotEqual(naming_decision(data, name)["status"], "AUTO_PASS")
    for kind, prop, condition in (
        ("SQS.Queue", "QueueName", "FifoQueue"),
        ("SNS.Topic", "TopicName", "FifoTopic"),
    ):
        for value in (True, "true", "True"):
            check.assertTrue(
                provider_naming_errors(kind, prop, "queue", {condition: value})
            )
        for value in (False, "false", "False"):
            check.assertFalse(
                provider_naming_errors(kind, prop, "queue", {condition: value})
            )
        data, name = decision_artifact(tmp_path, kind, prop, "queue", "IMPORT")
        name["conditions"] = {condition: "unknown"}
        check.assertEqual(naming_decision(data, name)["status"], "REVIEW_REQUIRED")
    data, name = decision_artifact(
        tmp_path, "IAM.Role", "RoleName", "arbitrary", "IMPORT"
    )
    check.assertEqual(naming_decision(data, name)["status"], "AUTO_PASS")
    data, name = decision_artifact(tmp_path, "IAM.Role", "RoleName", "app-dev-DataRole")
    del data["naming_context"]["target_context"]["suffix"]
    with pytest.raises(ValueError, match="rescan"):
        review_names(data)


@pytest.mark.parametrize(
    "kind,prop,value,status",
    [
        ("EC2.VPC", "Name", "vpc-app-dev", "AUTO_PASS"),
        ("EC2.VPC", "Name", "vpc-app-dev-extra", "AUTO_PASS"),
        ("EC2.VPC", "Name", "vpc-app-dev_extra", "AUTO_PASS"),
        ("EC2.VPC", "Name", "prefix_vpc-_app-dev", "AUTO_PASS"),
        ("EC2.VPC", "Name", "prefix-vpc-app-dev-001", "AUTO_PASS"),
        ("EC2.VPC", "Name", "vpc-app", "VIOLATION_CANDIDATE"),
        ("EC2.VPC", "Name", "wrong-app-dev", "VIOLATION_CANDIDATE"),
        ("EC2.VPC", "Name", "vpc-app-stg", "VIOLATION_CANDIDATE"),
        ("EC2.VPC", "Name", None, "VIOLATION_CANDIDATE"),
        ("IAM.Role", "RoleName", "app-dev-DataRole", "AUTO_PASS"),
        ("IAM.Role", "RoleName", "app-dev-dataRole", "VIOLATION_CANDIDATE"),
        ("IAM.Role", "RoleName", "app-dev-DataRole-" + "x" * 64, "VIOLATION_CANDIDATE"),
        ("S3.Bucket", "BucketName", "app-dev-data-123456789012-extra", "AUTO_PASS"),
        ("S3.Bucket", "BucketName", "Invalid_Bucket", "VIOLATION_CANDIDATE"),
        ("SQS.Queue", "QueueName", "sqs-app-dev-data", "AUTO_PASS"),
        ("SQS.Queue", "QueueName", "sqs-app-dev-data.fifo", "AUTO_PASS"),
        ("SQS.Queue", "QueueName", "x" * 81, "VIOLATION_CANDIDATE"),
        ("Glue.Job", "Name", "glue-app-dev-data-extra", "AUTO_PASS"),
        ("Logs.LogGroup", "LogGroupName", "/aws/lambda/MyFunction", "AUTO_PASS"),
        ("Logs.LogGroup", "LogGroupName", "/aws/codebuild/MyProject", "AUTO_PASS"),
        (
            "Logs.LogGroup",
            "LogGroupName",
            "/aws/vendedlogs/states/MyStateMachine",
            "AUTO_PASS",
        ),
        ("Logs.LogGroup", "LogGroupName", "Custom/operations_logs", "AUTO_PASS"),
        (
            "Logs.LogGroup",
            "LogGroupName",
            "/aws-glue/jobs/glsc-p4x8r2-role/venusinf-dev-IfOutbound29Role-p4x8r2/error",
            "AUTO_PASS",
        ),
        (
            "Logs.LogGroup",
            "LogGroupName",
            "/aws-glue/jobs/glsc-other-role/OtherRole/output",
            "AUTO_PASS",
        ),
        ("Logs.LogGroup", "LogGroupName", "invalid:logs", "VIOLATION_CANDIDATE"),
    ],
)
def check_mandatory_naming_decisions(tmp_path, kind, prop, value, status):
    data, name = decision_artifact(tmp_path, kind, prop, value)
    assert name["decision"]["status"] == status
    assert bool(review_names(data)) == (status != "AUTO_PASS")
    assert name["decision"]["basis"]
    review = review_for(data)
    snapshot = json.loads(review_snapshot(data, review).data)
    assert snapshot["automatically_reviewed_names"] == (
        ["n1"] if status == "AUTO_PASS" else []
    )


@pytest.mark.parametrize(
    "fault",
    [
        "forged",
        "omitted",
        "duplicate",
        "provider_unchecked",
        "value_unavailable",
        "confirmed_conflict",
        "suffix",
        "fifo",
        "import",
        "recommendation",
        "spoofed_duplicate",
        "duplicate_naming_cause",
        "source_spoof",
        "configured_optional_suffix",
        "required_suffix",
        "standard_prefix_suffix",
        "alternative_scope",
        "glue_number",
        "import_fifo",
        "forged_available",
    ],
)
def check_automatic_naming_integrity(tmp_path, fault):
    data, name = decision_artifact(tmp_path, "EC2.VPC", "Name", "vpc-app-dev")
    if fault == "forged_available":
        data, name = decision_artifact(
            tmp_path, "Logs.LogGroup", "LogGroupName", "UNSET"
        )
        assert name["value_available"] is True
        assert name["decision"]["status"] == "VIOLATION_CANDIDATE"
        name["provider_errors"] = []
        assert naming_decision(data, name)["status"] == "REVIEW_REQUIRED"
        name["value"] = "<masked:secret>"
        assert naming_decision(data, name)["status"] == "REVIEW_REQUIRED"
        return
    if fault == "configured_optional_suffix":
        data, name = decision_artifact(
            tmp_path, "CodeBuild.Project", "Name", "cbld-app-dev-build"
        )
        data["naming_context"]["target_context"]["suffix"] = "blue"
        assert naming_decision(data, name)["status"] == "VIOLATION_CANDIDATE"
        name["value"] += "-blue-extra"
        assert naming_decision(data, name)["status"] == "AUTO_PASS"
        return
    if fault == "required_suffix":
        data["naming_context"]["rules"]["EC2"] = [
            dict(
                text="| X | X | `EC2.VPC` | `Name` | `vpc-{{application}}-{{environment}}-{{suffix}}` |"
            )
        ]
        name["value"] = "vpc-app-dev-token"
        assert naming_decision(data, name)["status"] == "REVIEW_REQUIRED"
        return
    if fault == "standard_prefix_suffix":
        data, name = decision_artifact(
            tmp_path, "Logs.LogGroup", "LogGroupName", "/aws/vpc/flow-logs"
        )
        data["naming_context"]["target_context"]["suffix"] = "blue"
        assert naming_decision(data, name)["status"] == "VIOLATION_CANDIDATE"
        name["value"] += "/blue"
        assert naming_decision(data, name)["status"] == "AUTO_PASS"
        return
    if fault == "alternative_scope":
        data["naming_context"]["rules"]["EC2"] = [
            dict(
                text="| X | X | `EC2.VPC` | `Name` | `vpc-{{application}}-{{environment}}` | alternative |"
            )
        ]
        name["value"] = "human-custom-name"
        assert naming_decision(data, name)["status"] == "AUTO_PASS"
        return
    if fault == "glue_number":
        data, name = decision_artifact(
            tmp_path, "Glue.SecurityConfiguration", "Name", "glsc"
        )
        name["same_type_count"] = 2
        assert naming_decision(data, name)["status"] == "VIOLATION_CANDIDATE"
        name["value"] = "glsc-01"
        assert naming_decision(data, name)["status"] == "AUTO_PASS"
        return
    if fault == "import_fifo":
        data, name = decision_artifact(
            tmp_path, "SQS.Queue", "QueueName", "Human_Actual", "IMPORT"
        )
        name["conditions"] = {"FifoQueue": "true"}
        assert naming_decision(data, name)["status"] == "VIOLATION_CANDIDATE"
        return
    if fault == "source_spoof":
        name["source"] = dict(
            path="model/dev/123456789012/naming.properties", key="desired.row.001.value"
        )
        review = review_for(data)
        review["issues"] = [
            dict(
                service="naming",
                resource="001",
                property="Other",
                source=name["source"],
                rule="fake-rule",
                message="Spoofed Naming issue",
            )
        ]
        with pytest.raises(ValueError, match="naming_item_id"):
            review_snapshot(data, review)
        return
    if fault == "duplicate_naming_cause":
        name["value"] = "wrong-app-dev"
        name["decision"] = naming_decision(data, name)
        review = review_for(data)
        issue = dict(
            service="naming",
            resource="001",
            property="Name",
            rule="review.naming",
            naming_item_id="n1",
            applied_rule="vpc-{{application}}-{{environment}}",
            violation="format",
            evidence="Mandatory structure is absent",
            message="Wrong prefix",
        )
        review["issues"] = [issue, dict(issue, message="Same cause, different prose")]
        with pytest.raises(ValueError, match="duplicate Naming"):
            review_snapshot(data, review)
        return
    if fault == "forged":
        name["value"] = "vpc-app-stg"
        with pytest.raises(ValueError, match="decision"):
            review_snapshot(data, review_for(data))
        return
    if fault == "duplicate":
        data["naming"]["names"].append(deepcopy(name))
        with pytest.raises(ValueError, match="duplicate naming"):
            review_names(data)
        return
    if fault in {"provider_unchecked", "value_unavailable", "confirmed_conflict"}:
        if fault == "confirmed_conflict":
            data["human_confirmations"]["confirmations"] = [
                dict(
                    id="conflict",
                    service="naming",
                    fact="environment=stg",
                    scope=dict(resource="001", property="Name"),
                    exceptions=[],
                    evidence="Human fact contradicts target",
                )
            ]
        else:
            name[
                "provider_checked"
                if fault == "provider_unchecked"
                else "value_available"
            ] = False
        name["decision"] = naming_decision(data, name)
        assert name["decision"]["status"] == "REVIEW_REQUIRED"
        assert review_names(data) == [name]
        return
    if fault == "suffix":
        data, name = decision_artifact(
            tmp_path, "IAM.Role", "RoleName", "app-dev-DataRole"
        )
        data["naming_context"]["target_context"]["suffix"] = "blue"
        assert naming_decision(data, name)["status"] == "VIOLATION_CANDIDATE"
        return
    if fault == "fifo":
        data, name = decision_artifact(
            tmp_path, "SQS.Queue", "QueueName", "sqs-app-dev-data"
        )
        name["conditions"] = {"FifoQueue": "true"}
        assert naming_decision(data, name)["status"] == "VIOLATION_CANDIDATE"
        name["conditions"]["FifoQueue"] = None
        assert naming_decision(data, name)["status"] == "REVIEW_REQUIRED"
        return
    if fault == "import":
        data, name = decision_artifact(
            tmp_path, "SQS.Queue", "QueueName", "Human_Actual", "IMPORT"
        )
        assert name["decision"]["status"] == "AUTO_PASS"
        name["provider_errors"] = ["AWS constraint violation"]
        assert naming_decision(data, name)["status"] == "VIOLATION_CANDIDATE"
        return
    if fault == "omitted":
        name["value"] = "vpc-app-stg"
        name["decision"] = naming_decision(data, name)
        review = review_for(data)
        review["reviewed_names"] = []
        with pytest.raises(ValueError, match="naming IDs"):
            review_snapshot(data, review)
        return
    issue = dict(
        service="naming",
        resource="001",
        property="Name",
        rule="review.naming",
        naming_item_id="n1",
        applied_rule="vpc-{{application}}-{{environment}}",
        violation="format",
        evidence="Current naming evidence",
        message="Naming finding",
    )
    if fault == "recommendation":
        review = review_for(data)
        review["issues"] = [issue]
        with pytest.raises(ValueError, match="mandatory"):
            review_snapshot(data, review)
    else:
        name["value"] = "vpc-app-stg"
        name["decision"] = naming_decision(data, name)
        data["ordinary"] = [
            dict(
                id="machine",
                service="naming",
                resource="001",
                property="EC2.VPC.Name",
                rule="existing.provider",
                message="Existing diagnostic",
            )
        ]
        issue.update(
            violation="confirmed_mismatch",
            expected="dev",
            actual="stg",
            rule="review.naming",
        )
        review = review_for(data)
        review["issues"] = [issue]
        with pytest.raises(ValueError, match="Existing diagnostics"):
            review_snapshot(data, review)


def check_glue_naming_table_alternatives():
    path = (
        Path(__file__).resolve().parents[4]
        / "framework/rules/aws-resource-naming/Logs.md"
    )
    patterns = {
        pattern
        for kind, prop, pattern in naming_rule_rows(path.read_text(encoding="utf-8"))
        if (kind, prop) == ("Logs.LogGroup", "LogGroupName")
    }
    assert "/aws-glue/jobs/error" in patterns and "/aws-glue/jobs/output" in patterns
    assert "{{prefix}}/{{security_configuration}}-role/{{role_name}}/output" in patterns


if __name__ == "__main__":
    raise SystemExit(run(__file__))
