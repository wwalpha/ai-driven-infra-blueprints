#!/usr/bin/env python3
"""Three business boundaries: Scan/Save, process-loss resume, complete large Review."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from issues.publication import render_snapshot, save_scan
from issues.records import identifier
from issues.review import naming_decision, review_names, review_snapshot
from issues.review_progress import ReviewController
from issues.runner import scan
from support.issues_review_progress_fixtures import (
    ROOT,
    cli,
    controller,
    finish,
    submission,
)
from support.issues_scan_fixtures import (
    fixture,
    review_for,
    snapshot_artifact,
    stamp_naming_scan,
    task,
)
from support.issues_scan_fixtures import pytestmark as pytestmark
from support.pytest_cli import run
from utils.json_format import fingerprint

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def publish(review, tmp_path):
    output = tmp_path / "review.json"
    review.export(output)
    exported = json.loads(output.read_text(encoding="utf-8"))
    expected = render_snapshot(review.root, review_snapshot(review.artifact, exported))
    with task(review.root, review.artifact["services"]):
        paths, snapshot, _ = save_scan(review.root, review.artifact, exported)
    assert tuple(path.read_text(encoding="utf-8") for path in paths) == expected
    assert render_snapshot(review.root, snapshot) == expected
    return exported, expected


def check_scan_review_export_save_and_local_loop(tmp_path):
    root = tmp_path / "repository"
    fixture(root, services=["s3"])
    data = scan(root, "dev", "123456789012", ["cloudformation-stacks", "s3"], jobs=1)
    review = controller(tmp_path, data)
    review.initialize()
    finish(review)
    exported, expected = publish(review, tmp_path)
    assert exported == review_for(data)
    assert expected == render_snapshot(root, review_snapshot(data, review_for(data)))
    with task(root, data["services"], name="save-loop"):
        path = root / "tasks/save-loop.md"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n## Required changes\n- [R1] Save current reports\n\n## Acceptance checks\n- [R1] `exists:issues/dev/123456789012/issues.md`\n- [R1] `exists:issues/dev/123456789012/iac-issues.md`\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "framework/scripts/blueprint-loop.py"),
                "--mode",
                "local",
                "--task-file",
                "tasks/save-loop.md",
            ],
            cwd=root,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "PASS" in result.stdout
    multiple_target_naming_scan_review_save(tmp_path / "multiple")


def multiple_target_naming_scan_review_save(tmp_path):
    check = TestCase()
    tmp_path.mkdir()
    root = tmp_path / "repository"
    fixture(root, services=["s3"])
    project_path = root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    original = project["targets"][0]
    project["targets"] = [
        dict(original, alias=alias, suffix=suffix)
        for alias, suffix in (("cde", "p4x8r2"), ("non-cde", "skbm1r"))
    ]
    project_path.write_text(json.dumps(project), encoding="utf-8")
    for alias, suffix in (("cde", "p4x8r2"), ("non-cde", "skbm1r")):
        for base in (
            "model/dev",
            "docs/designs/dev",
            "issues/dev",
            "infra/cloudformation/parameters/dev",
        ):
            parent = root / base
            shutil.copytree(parent / "123456789012", parent / alias)
        confirmations = root / "issues/dev" / alias / "human-confirmations.yaml"
        confirmations.write_text(
            json.dumps(
                dict(version=2, environment="dev", target=alias, confirmations=[])
            ),
            encoding="utf-8",
        )
        templates = root / "infra/cloudformation/templates"
        (templates / alias).mkdir()
        shutil.copy2(templates / "shared.yaml", templates / alias / "shared.yaml")
        data = scan(root, "dev", alias, ["cloudformation-stacks", "s3"], jobs=1)
        target = data["naming_context"]["target_context"]
        check.assertEqual(
            (target["environment"], target["alias"], target["suffix"]),
            ("dev", alias, suffix),
        )
        if alias == "non-cde":
            name = next(
                item
                for item in data["naming"]["names"]
                if item["resourceType"] == "S3.Bucket"
                and item["property"] == "BucketName"
            )
            name["value"] = "venusinf-dev-data-123456789012-skbm1r-p4x8r2"
            name["decision"] = naming_decision(data, name)
            check.assertEqual(name["decision"]["status"], "VIOLATION_CANDIDATE")
            check.assertIn(name, review_names(data))
        artifact_path = tmp_path / (alias + "-scan.json")
        artifact_path.write_text(json.dumps(data), encoding="utf-8")
        review = ReviewController(
            root, artifact_path, tmp_path / (alias + "-progress.json")
        )
        review.initialize()
        finish(review)
        output = tmp_path / (alias + ".json")
        review.export(output)
        exported = json.loads(output.read_text(encoding="utf-8"))
        snapshot = json.loads(review_snapshot(data, exported).data)
        check.assertEqual(snapshot["naming_context"]["target_context"], target)
        reports = [f"issues/dev/{alias}/issues.md", f"issues/dev/{alias}/iac-issues.md"]
        with task(root, data["services"], name="save-" + alias, allowed=reports):
            path = root / "tasks" / ("save-" + alias + ".md")
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "dev/123456789012/", "dev/" + alias + "/"
                ),
                encoding="utf-8",
            )
            paths, saved, _ = save_scan(root, data, exported)
        check.assertEqual(
            json.loads(saved.data)["naming_context"]["target_context"], target
        )
        check.assertEqual(
            [path.relative_to(root).as_posix() for path in paths], reports
        )


def check_process_exit_resume_from_checkpoint_and_save(tmp_path):
    data = snapshot_artifact(
        tmp_path / "repository",
        ordinary=[dict(id="current", service="s3", message="Current issue")],
    )
    review = controller(tmp_path, data)
    review.initialize()
    batch = review.next_batch()
    payload = tmp_path / "submission.json"
    payload.write_text(json.dumps(submission(batch)), encoding="utf-8")
    interrupted = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import json,os,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from issues.review_progress import ReviewController; r=ReviewController(*map(Path,sys.argv[2:5])); r.submit(json.loads(Path(sys.argv[5]).read_text(encoding='utf-8'))); os._exit(17)",
            str(ROOT / "framework/scripts"),
            str(review.root),
            str(review.artifact_path),
            str(review.path),
            str(payload),
        ],
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True,
        check=False,
    )
    assert interrupted.returncode == 17, interrupted.stderr
    reloaded = cli(review, "status")
    assert reloaded.returncode == 0, reloaded.stderr
    status = json.loads(reloaded.stdout)
    assert status["sections"]["naming_context"]["reviewed"] == 1
    assert status["next_section"] == "diagnostics" and not status["complete"]
    resumed = ReviewController(review.root, review.artifact_path, review.path)
    assert resumed.status() == status
    finish(resumed)
    output = tmp_path / "review.json"
    resumed.export(output)
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert exported == review_for(data)
    expected = render_snapshot(review.root, review_snapshot(data, exported))
    with task(review.root, data["services"]):
        paths, snapshot, _ = save_scan(review.root, data, exported)
    assert "Current issue" in paths[0].read_text(encoding="utf-8")
    assert tuple(path.read_text(encoding="utf-8") for path in paths) == expected
    assert render_snapshot(review.root, snapshot) == expected


def check_process_revision_resume_export_and_save(tmp_path: Path) -> None:
    data = snapshot_artifact(
        tmp_path / "repository",
        ordinary=[dict(id="known", service="s3", message="Retained Issue")],
    )
    data["judgments"] = [
        dict(id="owner", message="Needs owner", cause_kind="input_invalid")
    ]
    review = controller(tmp_path, data)
    review.initialize()
    finish(review)
    output = tmp_path / "review.json"
    review.export(output)
    old_export = output.read_bytes()
    previous = review.inspect("judgments", "owner")
    assert previous["result_digest"] == fingerprint(previous["result"])
    result = dict(
        previous["result"],
        assignment=dict(status="unresolved", reason="Source evidence insufficient"),
    )
    revision = dict(
        scan_id=data["scan_id"],
        section="judgments",
        id="owner",
        expected_digest=previous["result_digest"],
        reason="Correct ownership after checking source evidence",
        result=result,
    )
    path = tmp_path / "revision.json"
    path.write_text(json.dumps(revision), encoding="utf-8")
    interrupted = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import json,os,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from issues.review_progress import ReviewController; r=ReviewController(*map(Path,sys.argv[2:5])); r.revise(json.loads(Path(sys.argv[5]).read_text(encoding='utf-8'))); os._exit(17)",
            str(ROOT / "framework/scripts"),
            str(review.root),
            str(review.artifact_path),
            str(review.path),
            str(path),
        ],
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True,
        check=False,
    )
    assert interrupted.returncode == 17, interrupted.stderr
    inspected = cli(review, "inspect", "--section", "judgments", "--id", "owner")
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["result"] == result
    resumed = ReviewController(review.root, review.artifact_path, review.path)
    before = review.path.read_bytes()
    status = resumed.revise(revision)
    assert review.path.read_bytes() == before
    assert status["sections"]["diagnostics"]["reviewed"] == 1
    assert status["sections"]["judgments"]["reviewed"] == 1
    assert status["next_section"] == "additions" and not status["exportable"]
    with pytest.raises(ValueError, match="incomplete"):
        resumed.export(output)
    assert output.read_bytes() == old_export
    batch = resumed.next_batch()
    assert batch["expected_ids"] == ["final"]
    resumed.submit(submission(batch))
    resumed.export(output)
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert len(exported) == 9 and output.read_bytes() != old_export
    assert exported["diagnostic_decisions"] == [
        dict(id="known", outcome="issue", reason="Current diagnostic confirmed")
    ]
    assert exported["diagnostic_assignments"]["owner"] == result["assignment"]
    expected = render_snapshot(review.root, review_snapshot(data, exported))
    with task(review.root, data["services"]):
        paths, snapshot, _ = save_scan(review.root, data, exported)
    assert "Retained Issue" in paths[0].read_text(encoding="utf-8")
    assert tuple(path.read_text(encoding="utf-8") for path in paths) == expected
    assert render_snapshot(review.root, snapshot) == expected


def check_large_review_complete_id_coverage_and_equivalent_reports(tmp_path):
    data = snapshot_artifact(
        tmp_path / "repository",
        ordinary=[
            dict(id=f"diag-{i}", service="s3", message=f"Issue {i}") for i in range(67)
        ],
    )
    data["naming"]["names"] = [
        dict(
            id=f"name-{i}",
            service="s3",
            resource=str(i),
            resourceType="S3.Bucket",
            property="S3.Bucket.BucketName",
            value=f"`bucket-{i}`",
            resourceMode="CREATE",
        )
        for i in range(1223)
    ]
    data["human_confirmations"]["confirmations"] = [
        dict(
            id=f"human-{i}",
            service="s3",
            fact="application=app",
            scope=dict(resource=str(i), property="S3.Bucket.BucketName"),
            exceptions=[],
            evidence="Explicit fixture Human confirmation",
        )
        for i in range(532)
    ]
    data["judgments"] = [
        dict(
            id=identifier(["note", i]),
            service="s3",
            kind="nonmechanical-design-prose",
            materials="Review business note",
        )
        for i in range(43)
    ]
    stamp_naming_scan(data)
    review = controller(tmp_path, data)
    review.initialize()
    status = finish(review)
    assert all(value["remaining"] == 0 for value in status["sections"].values())
    assert status["sections"]["naming"]["reviewed"] == 1223
    assert status["sections"]["human_confirmations"]["reviewed"] == 532
    exported, rendered = publish(review, tmp_path)
    expected = review_for(data)
    assert exported == expected
    assert review_snapshot(data, exported) == review_snapshot(data, expected)
    assert rendered == render_snapshot(review.root, review_snapshot(data, expected))


def check_scan_automatic_pass_resume_review_export_save(tmp_path):
    root = tmp_path / "repository"
    fixture(root, services=["cloudwatch-logs", "sqs"])
    human = root / "issues/dev/123456789012/human-confirmations.yaml"
    facts = json.loads(human.read_text(encoding="utf-8"))
    facts["confirmations"] = [
        dict(
            id="environment-conflict",
            service="sqs",
            fact="environment=stg",
            scope=dict(resource="001", property="QueueName"),
            exceptions=[],
            evidence="Explicit synthetic Human fact conflicts with target",
        )
    ]
    human.write_text(json.dumps(facts), encoding="utf-8")
    data = scan(
        root,
        "dev",
        "123456789012",
        ["cloudformation-stacks", "cloudwatch-logs", "sqs"],
        jobs=1,
    )
    automatic = [
        n for n in data["naming"]["names"] if n["decision"]["status"] == "AUTO_PASS"
    ]
    required = review_names(data)
    assert any(n["service"] == "cloudwatch-logs" for n in automatic)
    assert any(n["service"] == "sqs" for n in required)
    review = controller(tmp_path, data)
    status = review.initialize()
    assert status["sections"]["naming"]["total"] == len(required)
    review.submit(submission(review.next_batch(1)))
    # A fresh process verifies persisted progress against the unchanged Scan.
    assert cli(review, "status").returncode == 0
    reviewed_names = []
    while not review.status()["complete"]:
        batch = review.next_batch()
        if batch["section"] == "naming":
            reviewed_names.extend(batch["expected_ids"])
        review.submit(submission(batch))
    assert set(reviewed_names) == {n["id"] for n in required}
    exported, _ = publish(review, tmp_path)
    assert set(exported["reviewed_names"]) == {n["id"] for n in required}
    assert exported["reviewed_confirmations"] == ["environment-conflict"]
    snapshot = json.loads(review_snapshot(data, exported).data)
    assert set(snapshot["automatically_reviewed_names"]) == {n["id"] for n in automatic}
    assert len(snapshot["naming"]["names"]) == len(data["naming"]["names"])


def check_100_automatic_names_excluded_from_review_payload(tmp_path):
    root = tmp_path / "repository"
    fixture(root, services=["cloudwatch-logs"])
    data = scan(
        root,
        "dev",
        "123456789012",
        ["cloudformation-stacks", "cloudwatch-logs"],
        jobs=1,
    )
    source = next(
        n for n in data["naming"]["names"] if n["service"] == "cloudwatch-logs"
    )
    data["naming"]["names"] = []
    for i in range(100):
        name = dict(
            source,
            id=f"log-{i}",
            resource=f"{i:04d}",
            value=f"/aws-glue/jobs/security-{i}-role/ExecutionRole-{i}/"
            + ("error" if i % 2 else "output"),
        )
        data["naming"]["names"].append(name)
    stamp_naming_scan(data)
    assert all(n["decision"]["status"] == "AUTO_PASS" for n in data["naming"]["names"])
    assert review_names(data) == []
    review = controller(tmp_path, data)
    review.initialize()
    naming_batches = 0
    while not review.status()["complete"]:
        batch = review.next_batch()
        naming_batches += batch["section"] == "naming"
        review.submit(submission(batch))
    assert naming_batches == 0
    assert review.status()["automatically_reviewed_names"] == 100
    exported, _ = publish(review, tmp_path)
    assert exported["reviewed_names"] == []
    snapshot = json.loads(review_snapshot(data, exported).data)
    ids = [name["id"] for name in data["naming"]["names"]]
    assert snapshot["naming"]["names"] == data["naming"]["names"]
    assert len(ids) == len(set(ids)) == 100
    assert len(snapshot["automatically_reviewed_names"]) == 100
    assert set(snapshot["automatically_reviewed_names"]) == set(ids)
    assert not snapshot["ordinary"]
    assert not any(
        name["decision"]["violations"] for name in snapshot["naming"]["names"]
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
