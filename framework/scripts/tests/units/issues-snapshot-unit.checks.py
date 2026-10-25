#!/usr/bin/env python3
"""Whole-target snapshot, Human review and atomic publication boundaries."""

import json
import os
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError
from functools import partial
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from issue_gate import issue_errors
from issues.artifact import summary
from issues.integrity import target_services
from issues.publication import render_snapshot, save_scan
from issues.records import identifier
from issues.review import human_confirmations, review_snapshot
from support.issues_scan_fixtures import (
    forbid_report_text,
    review_for,
    snapshot_artifact,
    task,
    write,
)
from support.pytest_cli import run
from utils.function_wrapper import BoundCallback

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def confirmation():
    return dict(
        id="human-1",
        service="s3",
        fact="Human approved an existing name",
        scope=dict(resource="001", property="BucketName"),
        exceptions=["Existing name is permitted"],
        evidence="Explicit Human decision",
        related_issues=[dict(id="obsolete", message="old related record")],
    )


def reviewed_artifact(root):
    data = snapshot_artifact(
        root,
        ordinary=[
            dict(
                id="current",
                service="s3",
                resource="001",
                property="BucketName",
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
            target=dict(resource="001", property="BucketName"),
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
        patch.object(Path, "read_text", BoundCallback(forbid_report_text, Path.read_text)),
    ):
        outputs, snapshot = save_scan(tmp_path, data, review_for(data))
    text = outputs[0].read_text()
    assert (
        "old issue" not in text
        and "old Human prose" not in text
        and "latest finding" in text
    )
    assert issue_errors(tmp_path, {("dev", "123456789012", "s3")})
    assert not issue_errors(tmp_path, {("dev", "123456789012", "sqs")})
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
    assert not issue_errors(tmp_path, {("dev", "123456789012", "s3")})
    assert original["ordinary"][0]["message"] == "latest finding"


def check_human_exception_and_conflict(tmp_path):
    data = reviewed_artifact(tmp_path)
    with task(tmp_path, ["s3"]):
        outputs, snapshot = save_scan(tmp_path, data, human_decision(data))
        assert "latest naming diagnostic" not in outputs[0].read_text()
        assert "未解決issueなし" in outputs[0].read_text()
        assert summary(json.loads(snapshot.data))["validation_status"] == "CHECKED"
        assert summary(json.loads(snapshot.data))["review_required"] is False
        outputs, snapshot = save_scan(tmp_path, data, human_decision(data, "conflict"))
    assert "human.confirmation_conflict" in outputs[0].read_text()
    assert "latest naming diagnostic" in outputs[0].read_text()
    assert "検証: 未完了" in outputs[0].read_text()
    assert issue_errors(tmp_path, {("dev", "123456789012", "s3")})


@pytest.mark.parametrize(
    "fault", ["id", "service", "resource", "property", "evidence", "exceptions"]
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
    else:
        review["diagnostic_decisions"][0]["target"][fault] = "other"
    with pytest.raises(ValueError):
        review_snapshot(data, review)


def check_human_cleanup_preserves_facts(tmp_path):
    data = reviewed_artifact(tmp_path)
    data["services"] = data["target_services"] = ["s3", "sqs"]
    data["service_results"].append(
        dict(service="sqs", status="unverified", reason="not executed")
    )
    data["unverified"] = [dict(service="sqs", code="not_run")]
    data["processing_errors"] = [dict(service="sqs", code="processing")]
    data["ordinary"].append(
        dict(
            id="unrelated",
            service="s3",
            resource="002",
            property="BucketName",
            message="independent current problem",
        )
    )
    review = human_decision(data)
    review["diagnostic_decisions"].append(
        dict(id="unrelated", outcome="issue", reason="independent current problem")
    )
    review["confirmation_cleanup"] = [
        dict(
            confirmation_id="human-1",
            record_id="obsolete",
            reason="No remaining current problem",
            check_id="check",
            evidence="The current check completed; the exception excludes the naming diagnostic",
        )
    ]
    path = tmp_path / "issues/dev/123456789012/human-confirmations.yaml"
    human = deepcopy(data["human_confirmations"])
    # Raw facts are retained even if the Scan has masked the displayed fact.
    human["confirmations"][0]["fact"] += " raw value"
    write(path, json.dumps(human))
    reports = [
        "issues/dev/123456789012/" + name for name in ("issues.md", "iac-issues.md")
    ]
    with task(tmp_path, data["services"]):
        with pytest.raises(ValueError, match="Allowed paths"):
            save_scan(tmp_path, data, review)
    assert human_confirmations(tmp_path, "dev", "123456789012") == human
    with task(
        tmp_path,
        data["services"],
        allowed=[*reports, path.relative_to(tmp_path).as_posix()],
    ):
        outputs, snapshot = save_scan(tmp_path, data, review)
    assert len(outputs) == 3
    expected = deepcopy(human)
    expected["confirmations"][0]["related_issues"] = []
    assert human_confirmations(tmp_path, "dev", "123456789012") == expected
    assert data["human_confirmations"]["confirmations"][0]["related_issues"]


@pytest.mark.parametrize(
    "fault",
    [
        "not_run",
        "failed",
        "wrong_service",
        "unverified",
        "current_issue",
        "duplicate",
        "unknown_record",
        "fact_edit",
    ],
)
def check_cleanup_requires_evidence(tmp_path, fault):
    data = reviewed_artifact(tmp_path)
    review = human_decision(data)
    cleanup = dict(
        confirmation_id="human-1",
        record_id="obsolete",
        reason="obsolete",
        check_id="check",
        evidence="completed check",
    )
    review["confirmation_cleanup"] = [cleanup]
    if fault == "not_run":
        data["check_results"][0]["complete"] = False
    elif fault == "failed":
        data["check_results"][0]["status"] = "FAIL"
    elif fault == "wrong_service":
        data["check_results"][0]["scope"] = ["dev/123456789012/sqs"]
    elif fault == "unverified":
        data["unverified"] = [dict(code="not_run")]
    elif fault == "current_issue":
        review["diagnostic_decisions"] = [
            dict(id="current", outcome="issue", reason="still present")
        ]
    elif fault == "duplicate":
        review["confirmation_cleanup"].append(deepcopy(cleanup))
    elif fault == "unknown_record":
        cleanup["record_id"] = "other"
    else:
        cleanup["fact"] = "changed fact"
    with pytest.raises(ValueError):
        review_snapshot(data, review)


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
        review["unverified"] = [
            dict(service="s3", check="naming", reason="Human component unknown")
        ]
    with task(tmp_path, ["s3"]):
        outputs, snapshot = save_scan(tmp_path, data, review)
    text = outputs[0].read_text()
    assert "未完了" in text and "未解決issueなし（検証未完了）" in text
    if kind == "service":
        assert "今回の判定: partial" in outputs[1].read_text()
        assert summary(json.loads(snapshot.data))["iac_status"] == "partial"
    assert not issue_errors(tmp_path, {("dev", "123456789012", "s3")})


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


@pytest.mark.parametrize(
    "selected", ["issues.md", "iac-issues.md", "human-confirmations.yaml"]
)
@pytest.mark.parametrize("after", [True, False])
def check_atomic_rollback(tmp_path, selected, after):
    data = reviewed_artifact(tmp_path)
    review = human_decision(data)
    review["confirmation_cleanup"] = [
        dict(
            confirmation_id="human-1",
            record_id="obsolete",
            reason="obsolete",
            check_id="check",
            evidence="completed check",
        )
    ]
    directory = tmp_path / "issues/dev/123456789012"
    write(
        directory / "human-confirmations.yaml", json.dumps(data["human_confirmations"])
    )
    for name in ("issues.md", "iac-issues.md"):
        write(directory / name, "original-" + name)
    original = {path: path.read_bytes() for path in directory.iterdir()}
    state = dict(failed=False)
    with (
        task(
            tmp_path,
            ["s3"],
            allowed=[path.relative_to(tmp_path).as_posix() for path in original],
        ),
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
    else:
        data["version"] = 3
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
    write(path, "version: 1\nversion: 1\n")
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
        outputs, snapshot = save_scan(tmp_path, data, review_for(data))
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
    else:
        review["unverified"] = [dict(service="sqs", check="naming", reason="unknown")]
    with task(tmp_path, ["s3"]), patch("issues.publication.atomic_files") as publish:
        with pytest.raises(ValueError):
            save_scan(tmp_path, data, review)
        publish.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
