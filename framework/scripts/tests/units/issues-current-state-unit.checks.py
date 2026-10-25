#!/usr/bin/env python3
"""Current ordinary Issue decisions, evidence and conservative publication."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from issue_gate import issue_errors
from issues.aggregate import aggregate
from issues.artifact import detail_payload, validate_artifact
from issues.materials import existing_materials
from issues.publication import save_scan
from issues.records import identifier
from issues.reports import issue_content, issue_marker
from issues.review import existing_decisions
from support.issues_scan_fixtures import review_for, task, write
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def verification_target():
    return dict(
        service="s3",
        check_id="design.service",
        rule="framework/rules/model-information.md#model-authority",
        resource="001",
        property="S3.Bucket.BucketName",
        scope="dev/123456789012/s3",
        path="model/dev/123456789012/s3.properties",
    )


def scan_fixture(root, messages=("old problem",), *, managed=True):
    path = root / "issues/dev/123456789012/issues.md"
    write(
        path,
        "# 問題一覧\n\nHuman確認: application=app\n\n## dev／123456789012\n\n"
        "### s3\n\nHuman確認: selected exception\n\n"
        + "\n\n".join(
            f"{i}. "
            + (
                issue_content(
                    root,
                    path,
                    dict(
                        service="s3",
                        message=message,
                        verification_targets=[verification_target()],
                    ),
                )
                if managed
                else message
            )
            for i, message in enumerate(messages, 1)
        )
        + "\n\n### sqs\n\n1. outside issue\n\n"
        "## 警告（非ブロッキング）\n\n1. outside warning\n",
    )
    existing, _ = existing_materials(root, "dev", "123456789012", ["s3"])
    check = dict(
        id="check",
        check_id="design.service",
        scope=["dev/123456789012/s3"],
        status="PASS",
        complete=True,
        verification_targets=[verification_target()],
    )
    artifact = dict(
        version=3,
        root=str(root),
        scan_id="a" * 32,
        naming_context={},
        naming_context_id=identifier({}),
        environment="dev",
        target="123456789012",
        services=["s3"],
        ordinary=[],
        naming={"names": []},
        judgments=[
            dict(
                id=item["id"],
                service=item["service"],
                kind="existing-issue-correspondence",
                materials=item,
            )
            for item in existing
        ],
        check_results=[check],
        human_confirmations=[],
        **aggregate([], "dev", "123456789012", ["s3"]),
    )
    return path, artifact, existing


def decision(item, status="resolved"):
    return dict(
        id=item["id"],
        service=item["service"],
        status=status,
        reason="Rechecked the same resource and rule",
        verification="local",
        evidence=[
            dict(
                kind="scan",
                section="check_results",
                id="check",
                subject="S3.Bucket 001",
                details="The relevant check completed with no mismatch",
            )
        ],
    )


def revalidation(outcome="absent", verification="local", completed=True):
    return dict(
        kind="revalidation",
        verification=verification,
        completed=completed,
        outcome=outcome,
        check="design.service",
        subject="S3.Bucket 001",
        details="Checked the same property against the applicable rule",
        source=dict(path="model/dev/123456789012/s3.properties", line=12),
        rule="framework/rules/model-information.md#model-authority",
        target=verification_target(),
    )


def check_all_three_states_and_scope(tmp_path):
    path, artifact, old = scan_fixture(
        tmp_path, ("stale resolved", "stale continuing", "unchecked AWS")
    )
    diagnostic = dict(
        id="current",
        service="s3",
        key="same-problem",
        message="current mismatch",
        source=dict(path="model/dev/123456789012/s3.properties", line=23),
    )
    artifact["ordinary"] = [diagnostic]
    continuing = dict(
        decision(old[1], "continuing"),
        diagnostic_id="current",
        evidence=[dict(kind="scan", section="ordinary", id="current")],
    )
    unverified = dict(
        decision(old[2], "unverified"),
        verification="aws",
        not_checked_reason="AWS API not executed",
        evidence=[
            dict(
                kind="not_run",
                check="AWS current setting",
                details="AWS API not executed",
            )
        ],
    )
    review = dict(
        review_for(artifact),
        existing_issue_judgments=[decision(old[0]), continuing, unverified],
    )
    outside = path.read_text().split("### sqs", 1)[1].split("## 警告", 1)[0]
    with task(tmp_path, ["s3"]):
        outputs = save_scan(tmp_path, artifact, review)
    text = path.read_text()
    assert (
        len(outputs) == 2
        and "stale resolved" not in text
        and "stale continuing" not in text
    )
    assert (
        text.count("current mismatch") == 2
    )  # Issue body and its current diagnostic evidence.
    assert "今回の状態: 継続" in text and "s3.properties:23" in text
    assert (
        "unchecked AWS" in text
        and "今回の状態: 未検証" in text
        and "AWS API not executed" in text
    )
    assert (
        "Human確認: application=app" in text and "Human確認: selected exception" in text
    )
    assert text.split("### sqs", 1)[1].startswith(outside.rstrip())
    assert "outside warning" in text
    assert issue_errors(tmp_path, {("dev", "123456789012", "s3")})
    assert issue_errors(tmp_path, {("dev", "123456789012", "sqs")})
    current, _ = existing_materials(tmp_path, "dev", "123456789012", ["s3"])
    assert len(current) == 2
    assert {item["marker"] for item in current} == {old[1]["marker"], old[2]["marker"]}


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "duplicate",
        "unknown",
        "service",
        "scope",
        "status",
        "reason",
        "evidence",
        "evidence-id",
        "incomplete",
        "failed",
        "aws",
        "not-checked",
        "resolved-conflict",
        "resolved-invented",
        "review-duplicate",
        "bare-evidence",
        "present",
        "source-line",
        "incomplete-external",
        "current-diagnostic",
        "check-details",
    ],
)
def check_invalid_decisions_do_not_publish(tmp_path, failure):
    path, artifact, items = scan_fixture(tmp_path)
    current = decision(items[0])
    review = dict(review_for(artifact), existing_issue_judgments=[current])
    if failure == "missing":
        review.pop("existing_issue_judgments")
    elif failure == "duplicate":
        review["existing_issue_judgments"].append(deepcopy(current))
    elif failure == "unknown":
        current["id"] = "other-service-issue"
    elif failure == "service":
        current["service"] = "sqs"
    elif failure == "scope":
        artifact["check_results"][0]["scope"] = ["stg/123456789012/s3"]
    elif failure in {"status", "reason", "evidence"}:
        current[failure] = "" if failure != "evidence" else []
    elif failure == "evidence-id":
        current["evidence"][0]["id"] = "old-scan-check"
    elif failure == "incomplete":
        artifact["check_results"][0]["complete"] = False
    elif failure == "failed":
        artifact["check_results"][0]["status"] = "FAIL"
    elif failure == "aws":
        current["verification"] = "aws"
    elif failure == "not-checked":
        current.update(
            status="unverified",
            evidence=[dict(kind="not_run", check="check", details="not run")],
        )
    elif failure == "resolved-conflict":
        current.update(
            status="unverified",
            not_checked_reason="not run",
            evidence=[dict(kind="not_run", check="check", details="not run")],
        )
        review["resolved"] = [dict(id=current["id"], reason="wrong", evidence="wrong")]
    elif failure == "resolved-invented":
        review["resolved"] = [dict(id="unknown", reason="wrong", evidence="wrong")]
    elif failure == "review-duplicate":
        review["reviewed_judgments"] *= 2
    elif failure == "bare-evidence":
        current["evidence"] = ["no longer detected"]
    elif failure == "present":
        current["evidence"] = [revalidation("present")]
    elif failure == "source-line":
        current["evidence"] = [revalidation()]
        current["evidence"][0]["source"]["line"] = 0
    elif failure == "incomplete-external":
        current["evidence"] = [revalidation(completed=False)]
    elif failure == "current-diagnostic":
        artifact["judgments"][0]["materials"]["current_diagnostic_ids"] = [
            "still-failing"
        ]
    elif failure == "check-details":
        current["evidence"][0].pop("details")
    before = path.read_bytes()
    with (
        task(tmp_path, ["s3"]),
        patch(
            "issues.publication.save", side_effect=AssertionError("invalid publication")
        ),
    ):
        with pytest.raises(ValueError):
            save_scan(tmp_path, artifact, review)
    assert path.read_bytes() == before


@pytest.mark.parametrize("verification", ["local", "aws"])
def check_explicit_revalidation_and_legacy_v3(tmp_path, verification):
    path, artifact, items = scan_fixture(tmp_path)
    artifact.pop(
        "check_results"
    )  # Existing v3 artifacts retain their CLI/data contract.
    validate_artifact(artifact)
    assert detail_payload(artifact, "check_results")["items"] == []
    current = dict(
        decision(items[0]),
        verification=verification,
        evidence=[revalidation(verification=verification)],
    )
    with task(tmp_path, ["s3"]):
        save_scan(
            tmp_path,
            artifact,
            dict(review_for(artifact), existing_issue_judgments=[current]),
        )
    text = path.read_text()
    assert "old problem" not in text and "outside issue" in text
    assert not issue_errors(tmp_path, {("dev", "123456789012", "s3")})


def check_repeat_updates_keep_marker_and_replace_state(tmp_path):
    path, artifact, items = scan_fixture(tmp_path)
    current = dict(
        decision(items[0], "unverified"),
        not_checked_reason="not run",
        evidence=[dict(kind="not_run", check="check", details="not run")],
    )
    with task(tmp_path, ["s3"]):
        save_scan(
            tmp_path,
            artifact,
            dict(review_for(artifact), existing_issue_judgments=[current]),
        )
        old, _ = existing_materials(tmp_path, "dev", "123456789012", ["s3"])
        artifact["judgments"] = [
            dict(
                id=old[0]["id"],
                service="s3",
                kind="existing-issue-correspondence",
                materials=old[0],
            )
        ]
        current = dict(
            decision(old[0], "continuing"),
            evidence=[revalidation("present")],
            issue=dict(message="rechecked current problem"),
        )
        save_scan(
            tmp_path,
            artifact,
            dict(review_for(artifact), existing_issue_judgments=[current]),
        )
    text = path.read_text()
    assert "今回の状態: 未検証" not in text and text.count("今回の状態: 継続") == 1
    assert "old problem" not in text
    assert issue_marker(text.split("### sqs")[0]) == items[0]["marker"]


def check_stale_decision_preserves_all_reports(tmp_path):
    path, artifact, items = scan_fixture(tmp_path)
    path.write_text(path.read_text().replace("old problem", "Human revised problem"))
    before = path.read_bytes()
    with task(tmp_path, ["s3"]), pytest.raises(ValueError, match="stale"):
        save_scan(
            tmp_path,
            artifact,
            dict(review_for(artifact), existing_issue_judgments=[decision(items[0])]),
        )
    assert path.read_bytes() == before and not path.with_name("iac-issues.md").exists()


def check_legacy_projection_and_assigned_diagnostic(tmp_path):
    path, artifact, items = scan_fixture(tmp_path)
    review = dict(review_for(artifact), existing_issue_judgments=[decision(items[0])])
    review["resolved"] = existing_decisions(artifact, review)[1]
    assert existing_decisions(artifact, review)[1] == review["resolved"]
    diagnostic = dict(
        id="assigned", service=None, message="current ambiguous diagnostic"
    )
    artifact["judgments"].append(diagnostic)
    current = dict(
        decision(items[0], "continuing"),
        diagnostic_id="assigned",
        evidence=[dict(kind="scan", section="ordinary", id="assigned")],
    )
    review = dict(
        review_for(artifact),
        existing_issue_judgments=[current],
        diagnostic_assignments={"assigned": "s3"},
    )
    with task(tmp_path, ["s3"]):
        save_scan(tmp_path, artifact, review)
    assert "old problem" not in path.read_text()
    assert len(existing_materials(tmp_path, "dev", "123456789012", ["s3"])[0]) == 1


def check_unverified_annotation_replaces_only_its_suffix(tmp_path):
    path, artifact, items = scan_fixture(tmp_path)
    for reason in ("first unavailable check", "second unavailable check"):
        current = dict(
            decision(items[0], "unverified"),
            not_checked_reason=reason,
            evidence=[dict(kind="not_run", check="specific check", details=reason)],
        )
        with task(tmp_path, ["s3"]):
            save_scan(
                tmp_path,
                artifact,
                dict(review_for(artifact), existing_issue_judgments=[current]),
            )
        items, _ = existing_materials(tmp_path, "dev", "123456789012", ["s3"])
        artifact["judgments"] = [
            dict(
                id=items[0]["id"],
                service="s3",
                kind="existing-issue-correspondence",
                materials=items[0],
            )
        ]
    text = path.read_text()
    assert "old problem" in text and "first unavailable check" not in text
    assert text.count("今回の状態: 未検証") == 1


def check_all_items_in_repeated_service_blocks(tmp_path):
    path, artifact, items = scan_fixture(
        tmp_path, ("first scoped problem", "second scoped problem")
    )
    path.write_text(
        path.read_text().replace(
            "2. <!-- issue-generated:start --> second scoped problem",
            "### s3\n\n1. <!-- issue-generated:start --> second scoped problem",
        )
    )
    items, _ = existing_materials(tmp_path, "dev", "123456789012", ["s3"])
    artifact["judgments"] = [
        dict(
            id=item["id"],
            service="s3",
            kind="existing-issue-correspondence",
            materials=item,
        )
        for item in items
    ]
    with task(tmp_path, ["s3"]):
        save_scan(
            tmp_path,
            artifact,
            dict(
                review_for(artifact),
                existing_issue_judgments=[decision(item) for item in items],
            ),
        )
    assert (
        "scoped problem" not in path.read_text() and "outside issue" in path.read_text()
    )


@pytest.mark.parametrize(
    "mismatch",
    [
        "check_id",
        "rule",
        "resource",
        "property",
        "scope",
        "missing",
        "incomplete",
        "unbound",
    ],
)
def check_resolution_requires_corresponding_complete_target(tmp_path, mismatch):
    path, artifact, items = scan_fixture(tmp_path)
    check = artifact["check_results"][0]
    if mismatch == "missing":
        check.pop("verification_targets")
    elif mismatch == "unbound":
        items[0]["verification_targets"] = []
    elif mismatch == "incomplete":
        check["complete"] = False
    else:
        check["verification_targets"][0][mismatch] = "unrelated"
        if mismatch == "check_id":
            check["check_id"] = "framework.policy-tables"
            check["verification_targets"][0]["check_id"] = check["check_id"]
    review = dict(review_for(artifact), existing_issue_judgments=[decision(items[0])])
    before = path.read_bytes()
    with pytest.raises(ValueError, match="contradicts"):
        existing_decisions(artifact, review)
    assert path.read_bytes() == before
    review["existing_issue_judgments"][0].update(
        status="unverified",
        not_checked_reason="Corresponding complete verification unavailable",
    )
    with task(tmp_path, ["s3"]):
        save_scan(tmp_path, artifact, review)
    assert (
        "old problem" in path.read_text() and "今回の状態: 未検証" in path.read_text()
    )


@pytest.mark.parametrize(
    "missing",
    [
        "target",
        "check",
        "rule",
        "resource",
        "property",
        "completed",
        "unbound",
        "source",
    ],
)
def check_individual_absence_needs_bound_evidence(tmp_path, missing):
    _, artifact, items = scan_fixture(tmp_path)
    proof = revalidation()
    if missing == "target":
        proof.pop("target")
    elif missing == "unbound":
        items[0]["verification_targets"] = []
    elif missing == "completed":
        proof["completed"] = False
    elif missing == "source":
        proof["source"]["path"] = "model/dev/123456789012/sqs.properties"
    elif missing in {"check", "rule"}:
        proof[missing] = "unrelated"
    else:
        proof["target"][missing] = "unrelated"
    current = dict(decision(items[0]), evidence=[proof])
    review = dict(review_for(artifact), existing_issue_judgments=[current])
    with pytest.raises(ValueError, match="contradicts"):
        existing_decisions(artifact, review)
    current.update(
        status="unverified", not_checked_reason="Insufficient individual evidence"
    )
    assert existing_decisions(artifact, review)[0][0]["status"] == "unverified"


@pytest.mark.parametrize("location", ["preamble", "section"])
def check_unknown_service_retained_while_scoped_issue_resolves(tmp_path, location):
    path, _, _ = scan_fixture(tmp_path)
    unknown = "1. Unknown ownership with Human exception\n\n"
    text = path.read_text()
    if location == "preamble":
        text = text.replace("### s3", unknown + "### s3", 1)
    else:
        text = text.replace("### sqs", "### 未確定\n\n" + unknown + "### sqs", 1)
    path.write_text(text)
    items, _ = existing_materials(tmp_path, "dev", "123456789012", ["s3"])
    unresolved = next(item for item in items if item["service"] is None)
    scoped = next(item for item in items if item["service"] == "s3")
    assert unresolved["ownership_reason"]
    # Reuse the v3 review fixture without overwriting the report being reviewed.
    _, artifact, _ = scan_fixture(tmp_path / "artifact")
    artifact["root"] = str(tmp_path)
    artifact["judgments"] = [
        dict(
            id=item["id"],
            service=item["service"],
            kind="existing-issue-correspondence",
            materials=item,
        )
        for item in items
    ]
    validate_artifact(artifact)
    retained = dict(
        decision(unresolved, "unverified"),
        not_checked_reason=unresolved["ownership_reason"],
        evidence=[
            dict(
                kind="not_run",
                check="ownership",
                details=unresolved["ownership_reason"],
            )
        ],
    )
    review = dict(
        review_for(artifact), existing_issue_judgments=[decision(scoped), retained]
    )
    with task(tmp_path, ["s3"]):
        save_scan(tmp_path, artifact, review)
    saved = path.read_text()
    assert unknown in saved and "old problem" not in saved
    assert "### sqs\n\n1. outside issue\n\n" in saved
    after, _ = existing_materials(tmp_path, "dev", "123456789012", ["s3"])
    assert len(after) == 1 and after[0]["id"] == unresolved["id"]
    retained.update(status="resolved", evidence=[revalidation()])
    with pytest.raises(ValueError, match="ownership"):
        existing_decisions(artifact, review)


@pytest.mark.parametrize("managed", [True, False])
def check_continuing_preserves_human_and_replaces_only_machine_text(tmp_path, managed):
    path, artifact, items = scan_fixture(tmp_path, managed=managed)
    human = "\n\n   Human確認: accepted exception\n   注記: keep judgment and scope\n"
    path.write_text(path.read_text().replace("\n\n### sqs", human + "\n### sqs"))
    for index in range(3):
        items, _ = existing_materials(tmp_path, "dev", "123456789012", ["s3"])
        artifact["judgments"] = [
            dict(
                id=items[0]["id"],
                service="s3",
                kind="existing-issue-correspondence",
                materials=items[0],
            )
        ]
        current = dict(
            decision(items[0], "continuing"),
            evidence=[revalidation("present")],
            issue=dict(
                message=f"latest problem {index}",
                verification_targets=[verification_target()],
            ),
        )
        with task(tmp_path, ["s3"]):
            save_scan(
                tmp_path,
                artifact,
                dict(review_for(artifact), existing_issue_judgments=[current]),
            )
        saved = path.read_text()
        assert human.rstrip() in saved
        assert saved.count("<!-- issue-review:start -->") == 1
        assert saved.count("<!-- issue-targets:") == 1
        assert saved.count("Human確認: accepted exception") == 1
        assert issue_marker(saved.split("### sqs")[0]) == (
            items[0]["marker"] or items[0]["id"]
        )
        assert ("old problem" in saved) is not managed
        assert f"latest problem {index}" in saved
        if index:
            assert f"latest problem {index - 1}" not in saved


def check_unmarked_metadata_is_not_machine_correspondence(tmp_path):
    path, artifact, _ = scan_fixture(tmp_path, managed=False)
    note = " <!-- issue-targets: " + json.dumps([verification_target()]) + " -->"
    path.write_text(path.read_text().replace("old problem", "old problem" + note))
    items, _ = existing_materials(tmp_path, "dev", "123456789012", ["s3"])
    assert items[0]["verification_targets"] == []
    artifact["judgments"] = [
        dict(
            id=items[0]["id"],
            service="s3",
            kind="existing-issue-correspondence",
            materials=items[0],
        )
    ]
    with pytest.raises(ValueError, match="contradicts"):
        existing_decisions(
            artifact,
            dict(review_for(artifact), existing_issue_judgments=[decision(items[0])]),
        )
    assert note in path.read_text()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
