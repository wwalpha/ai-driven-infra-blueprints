#!/usr/bin/env python3
"""Review progress mechanics; naming/Human/diagnostic semantics stay in their own UTs."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from issues.materials import rule_section
from issues.records import identifier
from issues.review_progress import ReviewController, encoded
from model.sources import publication_lock
from support.issues_review_progress_fixtures import cli, controller, finish, submission
from support.issues_scan_fixtures import review_for, snapshot_artifact
from support.pytest_cli import run
from utils.json_format import fingerprint

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def named_artifact(tmp_path, count=23):
    data = snapshot_artifact(tmp_path / "repository")
    data["naming"]["names"] = [
        dict(
            id=f"name-{i}",
            service="s3",
            resource=str(i),
            resourceType="S3.Bucket",
            property="S3.Bucket.BucketName",
            value="`bucket`",
            resourceMode="CREATE",
        )
        for i in range(count)
    ]
    return data


def naming_controller(tmp_path, count=23):
    review = controller(tmp_path, named_artifact(tmp_path, count))
    review.initialize()
    review.submit(submission(review.next_batch()))
    return review


@pytest.mark.parametrize("namespaces", [("S3",), ("S3", "SQS")])
def check_real_naming_rules_shared_with_complete_twenty_item_batch(
    tmp_path: Path, namespaces: tuple[str, ...]
) -> None:
    root = Path(__file__).resolve().parents[4]
    data = named_artifact(tmp_path, 20)
    common = root / "framework/rules/aws-resource-naming.md"
    rules = {
        "common": [
            dict(
                path=common.relative_to(root).as_posix(),
                text="\n\n".join(
                    rule_section(common.read_text(encoding="utf-8"), heading)
                    for heading in (
                        "## Scope",
                        "## General rules",
                        "## Name tag policy",
                    )
                ),
            )
        ]
    }
    for namespace in (*namespaces, "EC2"):
        path = root / f"framework/rules/aws-resource-naming/{namespace}.md"
        rules[namespace] = [
            dict(
                path=path.relative_to(root).as_posix(),
                text=path.read_text(encoding="utf-8"),
            )
        ]
    for i, name in enumerate(data["naming"]["names"]):
        namespace = namespaces[i % len(namespaces)]
        name["resourceType"] = namespace + (
            ".Bucket" if namespace == "S3" else ".Queue"
        )
    data["naming_context"] = dict(
        target_context=dict(environment="dev", awsAccountId="123456789012"),
        review_policy="Review every applicable rule and fixed component",
        rules=rules,
    )
    data["naming_context_id"] = identifier(data["naming_context"])
    review = controller(tmp_path, data)
    review.initialize()
    while review.status()["next_section"] == "naming_context":
        review.submit(submission(review.next_batch()))
    batch = review.next_batch(limit=20)
    assert len(batch["items"]) == 20
    assert len(encoded(batch).encode("utf-8")) <= 32768
    shared = batch["naming_context"]
    assert shared == dict(
        data["naming_context"], rules={k: rules[k] for k in ("common", *namespaces)}
    )
    for material in batch["items"]:
        kind = material["item"]["resourceType"].partition(".")[0]
        assert material["naming_rule_refs"] == ["common", kind]
        assert "naming_context" not in material
    for items in shared["rules"].values():
        for rule in items:
            assert (
                encoded(batch).count(json.dumps(rule["text"], ensure_ascii=False)) == 1
            )
    # Compare the previous per-item payload under the same complete-JSON byte budget.
    legacy = {k: v for k, v in batch.items() if k != "naming_context"}
    legacy["items"] = []
    for material in batch["items"]:
        context = dict(
            shared, rules={k: rules[k] for k in material["naming_rule_refs"]}
        )
        legacy["items"].append(
            {k: v for k, v in material.items() if k != "naming_rule_refs"}
            | {"naming_context": context}
        )
        legacy["expected_ids"] = [m["item"]["id"] for m in legacy["items"]]
        if len(encoded(legacy).encode("utf-8")) > 32768:
            break
    print(
        f"Naming {namespaces}: {len(legacy['items']) - 1} -> 20 items, {len(encoded(batch).encode('utf-8'))} bytes"
    )
    review.submit(submission(batch))
    assert review.status()["sections"]["naming"]["reviewed"] == 20


def revision_for(
    review: ReviewController, section: str, key: str, **updates: Any
) -> dict[str, Any]:
    previous = review.inspect(section, key)
    return dict(
        scan_id=previous["scan_id"],
        section=section,
        id=key,
        expected_digest=previous["result_digest"],
        reason="New evidence corrects the earlier judgment",
        result=dict(previous["result"], reason="Corrected judgment", **updates),
    )


def revision_controller(tmp_path: Path) -> ReviewController:
    data = named_artifact(tmp_path, 2)
    data["ordinary"] = [dict(id="known", service="s3", message="Proven diagnostic")]
    data["judgments"] = [dict(id="note", service="s3", kind="note")]
    data["human_confirmations"]["confirmations"] = [
        dict(
            id="human",
            service="s3",
            fact="application=app",
            scope=dict(resource="0", property="Name"),
            exceptions=[],
            evidence="Human fact",
        )
    ]
    review = controller(tmp_path, data)
    review.initialize()
    finish(review)
    return review


@pytest.mark.parametrize(
    "section,key",
    [
        ("naming_context", None),
        ("human_confirmations", "human"),
        ("naming", "name-0"),
        ("judgments", "note"),
        ("diagnostics", "known"),
        ("additions", "final"),
    ],
)
def check_explicit_revision_revalidates_and_preserves_other_results(
    tmp_path: Path, section: str, key: str | None
) -> None:
    review = revision_controller(tmp_path)
    key = key or review.identity["naming_context_id"]
    before = json.loads(review.path.read_text(encoding="utf-8"))["state"]["results"]
    request = revision_for(
        review,
        section,
        key,
        issues=[dict(service="s3", message="Corrected current finding")],
        unverified=[dict(service="s3", check="manual", reason="Remaining scope")],
    )
    status = review.revise(request)
    after = json.loads(review.path.read_text(encoding="utf-8"))["state"]["results"]
    assert after[section][key] == request["result"]
    for name, results in before.items():
        for other_id, result in results.items():
            if (name, other_id) != (section, key) and name != "additions":
                assert after[name][other_id] == result
    checkpoint = review.path.read_bytes()
    assert review.revise(request) == status and review.path.read_bytes() == checkpoint
    if section != "additions":
        assert status["next_section"] == "additions" and not status["exportable"]
        with pytest.raises(ValueError, match="incomplete"):
            review.export(tmp_path / "review.json")
        finish(review)
    review.export(tmp_path / "review.json")
    exported = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert len(exported) == 9
    assert exported["issues"] == request["result"]["issues"]
    assert exported["unverified"] == request["result"]["unverified"]


@pytest.mark.parametrize(
    "fault",
    [
        "digest",
        "scan",
        "section",
        "id",
        "reason",
        "result-id",
        "result",
        "issues",
        "unverified",
        "extra",
    ],
)
def check_revision_conflict_or_invalid_payload_is_atomic(
    tmp_path: Path, fault: str
) -> None:
    review = revision_controller(tmp_path)
    request = revision_for(review, "naming", "name-0")
    if fault == "digest":
        request["expected_digest"] = "0" * 64
    elif fault in {"scan", "section", "id"}:
        request["scan_id" if fault == "scan" else fault] = "unknown"
    elif fault == "reason":
        request["reason"] = " "
    elif fault == "result-id":
        request["result"]["id"] = "name-1"
    elif fault == "result":
        request["result"]["reviewed"] = False
    elif fault in {"issues", "unverified"}:
        request["result"][fault] = [dict(service="outside", message="Invalid")]
    else:
        request["extra"] = "unexpected"
    before = review.path.read_bytes()
    with pytest.raises(ValueError):
        review.revise(request)
    assert review.path.read_bytes() == before


def check_revision_atomic_replace_and_full_validation_failure(tmp_path: Path) -> None:
    review = revision_controller(tmp_path)
    request = revision_for(review, "additions", "final")
    before = review.path.read_bytes()
    with (
        patch(
            "issues.review_progress.review_snapshot",
            side_effect=ValueError("invalid final Review"),
        ),
        pytest.raises(ValueError, match="invalid final"),
    ):
        review.revise(request)
    assert review.path.read_bytes() == before
    with (
        patch(
            "utils.file_operations.os.replace", side_effect=OSError("rename failure")
        ),
        pytest.raises(OSError),
    ):
        review.revise(request)
    assert review.path.read_bytes() == before
    review.revise(request)
    stale = deepcopy(request)
    stale["result"]["reason"] = "Conflicting writer"
    before = review.path.read_bytes()
    with pytest.raises(ValueError, match="conflict"):
        review.revise(stale)
    assert review.path.read_bytes() == before


def check_revision_invalidates_pending_batch_and_preserves_final_findings(
    tmp_path: Path,
) -> None:
    review = revision_controller(tmp_path)
    issue = dict(service="s3", message="Existing final finding")
    review.revise(revision_for(review, "additions", "final", issues=[issue]))
    before = review.path.read_bytes()
    inspected = review.inspect("additions", "final")
    assert review.path.read_bytes() == before and inspected["result"]["issues"] == [
        issue
    ]
    # Cumulative validation also covers findings retained in other results.
    with pytest.raises(ValueError, match="duplicate"):
        review.revise(revision_for(review, "naming", "name-0", issues=[issue]))
    assert review.path.read_bytes() == before
    review.revise(revision_for(review, "naming", "name-0"))
    stale = submission(review.next_batch())
    review.revise(revision_for(review, "naming", "name-1"))
    before = review.path.read_bytes()
    with pytest.raises(ValueError, match="stale"):
        review.submit(stale)
    assert review.path.read_bytes() == before
    batch = review.next_batch()
    assert batch["items"][0]["previous_result"]["issues"] == [issue]
    stale["results"] = [dict(batch["items"][0]["previous_result"], reviewed=True)]
    review.submit(stale)
    output = tmp_path / "review.json"
    review.export(output)
    assert json.loads(output.read_text(encoding="utf-8"))["issues"] == [issue]


@pytest.mark.parametrize(
    "initial,new", [(None, "s3"), ("s3", "sqs"), ("s3", None), ("s3", "s3")]
)
def check_owner_revision_invalidates_only_affected_decisions(
    tmp_path: Path, initial: str | None, new: str | None
) -> None:
    data = snapshot_artifact(
        tmp_path / "repository",
        services=("s3", "sqs"),
        ordinary=[dict(id="known", service="s3", message="Known diagnostic")],
    )
    data["judgments"] = [
        dict(id=key, message="Needs owner", service=None, cause_kind="input_invalid")
        for key in ("owner", "other-owner")
    ]
    review = controller(tmp_path, data)
    review.initialize()
    review.submit(submission(review.next_batch()))
    batch = submission(review.next_batch())
    if initial is None:
        batch["results"][0]["assignment"] = dict(
            status="unresolved", reason="Owner unknown"
        )
    review.submit(batch)
    finish(review)
    final = revision_for(
        review,
        "additions",
        "final",
        issues=[dict(service="s3", message="Retain final finding")],
    )
    review.revise(final)
    previous = json.loads(review.path.read_text(encoding="utf-8"))["state"]["results"]
    assignment = (
        dict(status="unresolved", reason="Owner unknown")
        if new is None
        else dict(status="assigned", service=new, evidence="New source evidence")
    )
    request = revision_for(review, "judgments", "owner", assignment=assignment)
    status = review.revise(request)
    current = json.loads(review.path.read_text(encoding="utf-8"))["state"]["results"]
    assert current["diagnostics"] == {
        k: v
        for k, v in previous["diagnostics"].items()
        if k != "owner" or initial == new
    }
    assert current["judgments"]["other-owner"] == previous["judgments"]["other-owner"]
    assert current["naming_context"] == previous["naming_context"]
    assert current["additions"]["final"] == dict(
        previous["additions"]["final"], reviewed=False
    )
    assert not status["exportable"]
    with pytest.raises(ValueError, match="incomplete"):
        review.export(tmp_path / "review.json")
    batch = review.next_batch()
    if new is not None and initial != new:
        assert batch["section"] == "diagnostics" and batch["expected_ids"] == ["owner"]
        assert batch["items"][0]["item"]["service"] == new
        review.submit(submission(batch))
        batch = review.next_batch()
    assert batch["section"] == "additions"
    assert batch["items"][0]["previous_result"] == current["additions"]["final"]
    result = submission(batch)
    result["results"] = [dict(batch["items"][0]["previous_result"], reviewed=True)]
    review.submit(result)
    review.export(tmp_path / "review.json")
    exported = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert len(exported) == 9 and exported["issues"] == final["result"]["issues"]
    assert {d["id"] for d in exported["diagnostic_decisions"]} == (
        {"known", "other-owner", "owner"} if new else {"known", "other-owner"}
    )


def check_inventory_context_order_and_fetch_is_not_review(tmp_path):
    data = named_artifact(tmp_path, 23)
    data["naming_context"] = dict(
        target_context=dict(environment="dev"),
        rules=dict(S3=[dict(path="rules/s3.md", text="rule body")]),
    )
    data["naming_context_id"] = identifier(data["naming_context"])
    review = controller(tmp_path, data)
    status = review.initialize()
    assert status["sections"]["naming_context"]["total"] == 2
    assert status["sections"]["naming"]["remaining"] == 23
    batch = review.next_batch()
    assert [m["item"].get("rule") for m in batch["items"]][1] == data["naming_context"][
        "rules"
    ]["S3"][0]
    assert review.status() == status == review.initialize()
    review.submit(submission(batch))
    batch = review.next_batch()
    assert batch["section"] == "naming" and len(batch["items"]) == 20
    review.submit(submission(batch))
    assert review.status()["sections"]["naming"] == dict(
        total=23, reviewed=20, remaining=3, pending_dependency=False
    )
    assert len(review.next_batch()["items"]) == 3


def check_batch_size_bytes_and_oversize_item(tmp_path):
    review = naming_controller(tmp_path)
    first = review.next_batch(limit=1)
    size = len(encoded(first).encode("utf-8"))
    batch = review.next_batch(limit=20, max_bytes=size)
    assert len(batch["items"]) == 1 and len(encoded(batch).encode("utf-8")) <= size
    before = review.path.read_bytes()
    blocked = review.next_batch(max_bytes=size - 1)
    assert (
        blocked["blocked"]
        and blocked["id"] == "name-0"
        and blocked["required_bytes"] == size
    )
    assert review.path.read_bytes() == before
    assert review.status()["sections"]["naming"]["reviewed"] == 0


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "unknown",
        "batch",
        "unreviewed",
        "reason",
        "evidence",
        "issues",
        "unverified",
        "extra",
        "unissued",
    ],
)
def check_invalid_batch_is_atomic_and_retryable(tmp_path, fault):
    review = naming_controller(tmp_path)
    batch = review.next_batch(limit=2)
    result = submission(batch)
    if fault == "missing":
        result["results"].pop()
    elif fault == "duplicate":
        result["results"][1] = deepcopy(result["results"][0])
    elif fault == "unknown":
        result["results"][0]["id"] = "unknown"
    elif fault == "batch":
        result["batch_id"] = "wrong"
    elif fault == "unissued":
        envelope = json.loads(review.path.read_text())
        envelope["state"]["pending"] = None
        envelope["digest"] = fingerprint(envelope["state"])
        review.path.write_text(encoded(envelope), encoding="utf-8")
    elif fault == "unreviewed":
        result["results"][0]["reviewed"] = False
    elif fault in {"reason", "evidence"}:
        result["results"][0][fault] = ""
    elif fault in {"issues", "unverified"}:
        result["results"][1][fault] = [
            dict(service="outside", check="test", reason="bad")
        ]
    else:
        result["results"][0]["assignment"] = {}
    before = review.path.read_bytes()
    with pytest.raises(ValueError):
        review.submit(result)
    assert review.path.read_bytes() == before
    assert review.status()["sections"]["naming"]["reviewed"] == 0
    if fault != "unissued":
        review.submit(submission(batch))
        assert review.status()["sections"]["naming"]["reviewed"] == 2


def check_reordered_batch_results_and_human_context_references(tmp_path):
    data = named_artifact(tmp_path, 2)
    data["human_confirmations"]["confirmations"] = [
        dict(
            id="related",
            service="s3",
            fact="application=app",
            scope=dict(resource="0", property="S3.Bucket.BucketName"),
            exceptions=[],
            evidence="Human confirmed",
        ),
        dict(
            id="unrelated",
            service="s3",
            fact="different setting",
            scope=dict(resource="999", property="Other"),
            exceptions=[],
            evidence="Human confirmed",
        ),
    ]
    review = controller(tmp_path, data)
    review.initialize()
    for _ in range(2):
        review.submit(submission(review.next_batch()))
    batch = review.next_batch(limit=2)
    assert [h["id"] for h in batch["items"][0]["human_confirmations"]] == ["related"]
    assert not batch["items"][1]["human_confirmations"]
    assert (
        batch["items"][0]["reviewed_human_context"]["section"] == "human_confirmations"
    )
    result = submission(batch)
    result["results"].reverse()
    review.submit(result)
    assert review.submit(result)["sections"]["naming"]["reviewed"] == 2
    finish(review)
    output = tmp_path / "review.json"
    review.export(output)
    assert json.loads(output.read_text())["reviewed_names"] == ["name-0", "name-1"]


def reject_additions(artifact, additions):
    if additions:
        raise ValueError("invalid structured Naming Issue")
    return []


def check_invalid_shared_validation_never_advances_results(tmp_path):
    review = naming_controller(tmp_path, 1)
    batch = review.next_batch()
    before = review.path.read_bytes()
    result = submission(batch)
    result["results"][0]["issues"] = [dict(service="s3", message="Current finding")]
    with (
        patch(
            "issues.review_progress.review_additions",
            side_effect=reject_additions,
        ),
        pytest.raises(ValueError, match="name-0"),
    ):
        review.submit(result)
    assert review.path.read_bytes() == before
    review.submit(submission(batch))
    batch = review.next_batch()
    before = review.path.read_bytes()
    with (
        patch(
            "issues.review_progress.review_snapshot",
            side_effect=ValueError("final review invalid"),
        ),
        pytest.raises(ValueError, match="final review invalid"),
    ):
        review.submit(submission(batch))
    assert review.path.read_bytes() == before and not review.status()["complete"]
    review.submit(submission(batch))


def check_retry_idempotence_overwrite_and_stale_batch(tmp_path):
    review = naming_controller(tmp_path)
    batch = review.next_batch(limit=2)
    stale = submission(batch)
    batch = review.next_batch(limit=1)
    with pytest.raises(ValueError, match="stale"):
        review.submit(stale)
    result = submission(batch)
    status = review.submit(result)
    before = review.path.read_bytes()
    assert review.submit(result) == status and review.path.read_bytes() == before
    altered = deepcopy(result)
    altered["results"][0]["reason"] = "another judgment"
    with pytest.raises(ValueError, match="overwrite"):
        review.submit(altered)
    assert review.path.read_bytes() == before


@pytest.mark.parametrize("fault", ["scan", "artifact", "context", "scope"])
def check_scan_identity_mismatch_preserves_checkpoint(tmp_path, fault):
    review = naming_controller(tmp_path)
    data = deepcopy(review.artifact)
    if fault == "scan":
        data["scan_id"] = "b" * 32
    elif fault == "artifact":
        data["executed_at"] = "2026-10-26T00:00:00Z"
    elif fault == "context":
        data["naming_context"] = {"review_policy": "different"}
        data["naming_context_id"] = identifier(data["naming_context"])
    else:
        data["target"] = data["human_confirmations"]["target"] = "other"
    review.artifact_path.write_text(encoded(data), encoding="utf-8")
    before = review.path.read_bytes()
    other = ReviewController(review.root, review.artifact_path, review.path)
    with pytest.raises(ValueError, match="mismatch"):
        other.initialize()
    assert review.path.read_bytes() == before


@pytest.mark.parametrize(
    "fault",
    [
        "syntax",
        "schema",
        "checksum",
        "missing",
        "result",
        "complete",
        "order",
        "pending",
    ],
)
def check_checkpoint_corruption_rejected(tmp_path, fault):
    review = naming_controller(tmp_path)
    data = json.loads(review.path.read_text())
    if fault == "syntax":
        review.path.write_text("{broken", encoding="utf-8")
    else:
        if fault == "schema":
            data["schema"] = True
        elif fault == "checksum":
            data["digest"] = "broken"
        elif fault == "missing":
            data["state"].pop("pending")
        elif fault == "result":
            result = next(iter(data["state"]["results"]["naming_context"].values()))
            result["reviewed"] = False
        elif fault == "complete":
            data["state"]["complete"] = True
        elif fault == "order":
            data["state"]["results"]["additions"] = {"final": {}}
        else:
            data["state"]["pending"] = dict(
                batch_id="bad", section="naming", ids=["missing"]
            )
        if fault != "checksum":
            data["digest"] = fingerprint(data["state"])
        review.path.write_text(encoded(data), encoding="utf-8")
    before = review.path.read_bytes()
    with pytest.raises(ValueError):
        review.status()
    assert review.path.read_bytes() == before


def check_atomic_replace_failure_retains_valid_checkpoint(tmp_path):
    review = naming_controller(tmp_path)
    batch = review.next_batch()
    before = review.path.read_bytes()
    with (
        patch(
            "utils.file_operations.os.replace",
            side_effect=OSError("injected rename failure"),
        ),
        pytest.raises(OSError),
    ):
        review.submit(submission(batch))
    assert review.path.read_bytes() == before
    assert {p.name for p in tmp_path.iterdir()} == {
        "repository",
        "scan.json",
        "progress.json",
    }
    review.submit(submission(batch))


def check_owner_decision_dependency_and_existing_export(tmp_path):
    data = snapshot_artifact(
        tmp_path / "repository",
        ordinary=[dict(id="known", service="s3", message="Proven diagnostic")],
    )
    data["judgments"] = [
        dict(id=kind, message="Needs owner proof", service=None, cause_kind=kind)
        for kind in (
            "input_invalid",
            "check_failure",
            "dependency_wait",
            "unclassified",
        )
    ]
    review = controller(tmp_path, data)
    review.initialize()
    review.submit(submission(review.next_batch()))
    assert review.next_batch()["section"] == "judgments"
    assert review.status()["sections"]["diagnostics"]["pending_dependency"]
    review.submit(submission(review.next_batch()))
    batch = review.next_batch()
    assert batch["section"] == "diagnostics" and batch["expected_ids"] == [
        "known",
        "input_invalid",
    ]
    assert "assignment" not in submission(batch)["results"][0]
    review.submit(submission(batch))
    finish(review)
    output = tmp_path / "review.json"
    review.export(output)
    exported = json.loads(output.read_text())
    assert set(exported) == set(review_for(data)) and len(exported) == 9
    assert {d["id"] for d in exported["diagnostic_decisions"]} == {
        "known",
        "input_invalid",
    }
    assert set(exported["diagnostic_assignments"]) == {
        j["id"] for j in data["judgments"]
    }


def check_unresolved_owner_creates_no_decision(tmp_path):
    data = snapshot_artifact(tmp_path / "repository")
    data["judgments"] = [
        dict(id="unknown", message="Shared source", cause_kind="input_invalid")
    ]
    review = controller(tmp_path, data)
    review.initialize()
    review.submit(submission(review.next_batch()))
    result = submission(review.next_batch())
    result["results"][0]["assignment"] = dict(
        status="unresolved", reason="No source ownership proof"
    )
    review.submit(result)
    assert review.next_batch()["section"] == "additions"
    finish(review)


def check_incomplete_export_rejected_and_final_validation_used(tmp_path):
    review = naming_controller(tmp_path)
    output = tmp_path / "review.json"
    with pytest.raises(ValueError, match="incomplete"):
        review.export(output)
    assert not output.exists()
    finish(review)
    with patch(
        "issues.review_progress.review_snapshot",
        side_effect=ValueError("bad final evidence"),
    ):
        assert not review.status()["exportable"]
        with pytest.raises(ValueError, match="bad final evidence"):
            review.export(output)
    assert not output.exists()
    review.export(output)
    assert json.loads(output.read_text()) == review_for(review.artifact)


@pytest.mark.parametrize(
    "channel", ["naming", "judgments", "human_confirmations", "ordinary"]
)
def check_duplicate_inventory_rejected(tmp_path, channel):
    data = named_artifact(tmp_path, 1)
    if channel == "naming":
        data["naming"]["names"] *= 2
    elif channel == "judgments":
        data["judgments"] = [dict(id="same", kind="note")] * 2
    elif channel == "ordinary":
        data["ordinary"] = [dict(id="same", service="s3", message="bad")] * 2
    else:
        human = dict(
            id="same",
            service="s3",
            fact="fact",
            scope=dict(resource="1", property="Name"),
            exceptions=[],
            evidence="Human",
        )
        data["human_confirmations"]["confirmations"] = [human, human]
    with pytest.raises(ValueError):
        controller(tmp_path, data)


def check_cli_commands_external_paths_and_byte_limit(tmp_path):
    review = controller(tmp_path)
    assert cli(review, "init").returncode == 0
    batch = json.loads(cli(review, "next").stdout)
    path = tmp_path / "submission.json"
    path.write_text(encoded(submission(batch)), encoding="utf-8")
    assert cli(review, "submit", "--submission", str(path)).returncode == 0
    assert cli(review, "status").returncode == 0
    assert (
        cli(review, "export", "--review", str(tmp_path / "review.json")).returncode == 2
    )
    assert cli(review, "next", "--max-bytes", "256").returncode == 2
    with pytest.raises(ValueError, match="outside"):
        ReviewController(
            review.root, review.artifact_path, review.root / "checkpoint.json"
        )
    with pytest.raises(ValueError, match="differ"):
        ReviewController(review.root, review.artifact_path, review.artifact_path)
    with pytest.raises(ValueError, match="differ"):
        review.export(review.path)


@pytest.mark.parametrize("value", [[], None, "invalid", "{broken"])
def check_invalid_scan_reports_explicit_error(tmp_path, value):
    review = controller(tmp_path)
    review.artifact_path.write_text(
        value if value == "{broken" else encoded(value), encoding="utf-8"
    )
    result = cli(review, "init")
    assert result.returncode == 2 and "Local issues: ERROR:" in result.stderr
    assert "Traceback" not in result.stderr and not review.path.exists()


def check_process_lock_serializes_checkpoint_updates(tmp_path):
    review = controller(tmp_path)
    review.initialize()
    with publication_lock(review.path, read_only=True):
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-c",
                "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from issues.review_progress import ReviewController; ReviewController(*map(Path, sys.argv[2:])).next_batch()",
                str(Path(__file__).resolve().parents[2]),
                str(review.root),
                str(review.artifact_path),
                str(review.path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.5)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, (stdout, stderr)
    assert review.status()["sections"]["naming_context"]["reviewed"] == 0
    review.submit(submission(review.next_batch()))


if __name__ == "__main__":
    raise SystemExit(run(__file__))
