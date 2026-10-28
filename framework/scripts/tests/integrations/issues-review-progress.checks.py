#!/usr/bin/env python3
"""Three business boundaries: Scan/Save, process-loss resume, complete large Review."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from issues.publication import render_snapshot, save_scan
from issues.records import identifier
from issues.review import review_snapshot
from issues.runner import scan
from support.issues_review_progress_fixtures import (
    ROOT,
    cli,
    controller,
    finish,
    submission,
)
from support.issues_scan_fixtures import fixture, review_for, snapshot_artifact, task
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


def check_process_exit_resume_from_checkpoint_and_save(tmp_path):
    data = snapshot_artifact(
        tmp_path / "repository",
        ordinary=[dict(id="current", service="s3", message="Current issue")],
    )
    review = controller(tmp_path, data)
    assert cli(review, "init").returncode == 0
    batch = json.loads(cli(review, "next").stdout)
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
    status = json.loads(cli(review, "status").stdout)
    assert status["sections"]["naming_context"]["reviewed"] == 1
    assert status["next_section"] == "diagnostics" and not status["complete"]
    while not status["complete"]:
        batch = json.loads(cli(review, "next").stdout)
        payload.write_text(json.dumps(submission(batch)), encoding="utf-8")
        accepted = cli(review, "submit", "--submission", str(payload))
        assert accepted.returncode == 0, accepted.stderr
        status = json.loads(accepted.stdout)
    output = tmp_path / "review.json"
    assert cli(review, "export", "--review", str(output)).returncode == 0
    with task(review.root, data["services"]):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "framework/scripts/issues_scan.py"),
                "--repository-root",
                str(review.root),
                "--task-file",
                "tasks/save.md",
                "save",
                "--artifact",
                str(review.artifact_path),
                "--review",
                str(output),
            ],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    assert result.returncode == 0, result.stderr
    saved = json.loads(result.stdout)
    assert (
        saved["publication_status"] == "SAVED"
        and saved["post_save_validation_execution"] == "NOT_STARTED"
    )
    assert "Current issue" in (review.root / saved["saved"][0]).read_text(
        encoding="utf-8"
    )


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
    inspected = cli(review, "inspect", "--section", "judgments", "--id", "owner")
    assert inspected.returncode == 0, inspected.stderr
    previous = json.loads(inspected.stdout)
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
    before = review.path.read_bytes()
    retry = cli(review, "revise", "--revision", str(path))
    assert retry.returncode == 0, retry.stderr
    assert review.path.read_bytes() == before
    status = json.loads(cli(review, "status").stdout)
    assert status["sections"]["diagnostics"]["reviewed"] == 1
    assert status["sections"]["judgments"]["reviewed"] == 1
    assert status["next_section"] == "additions" and not status["exportable"]
    assert cli(review, "export", "--review", str(output)).returncode == 2
    assert output.read_bytes() == old_export
    batch = json.loads(cli(review, "next").stdout)
    assert batch["expected_ids"] == ["final"]
    path.write_text(json.dumps(submission(batch)), encoding="utf-8")
    assert cli(review, "submit", "--submission", str(path)).returncode == 0
    assert cli(review, "export", "--review", str(output)).returncode == 0
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert len(exported) == 9 and output.read_bytes() != old_export
    assert exported["diagnostic_decisions"] == [
        dict(id="known", outcome="issue", reason="Current diagnostic confirmed")
    ]
    assert exported["diagnostic_assignments"]["owner"] == result["assignment"]
    with task(review.root, data["services"]):
        saved = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "framework/scripts/issues_scan.py"),
                "--repository-root",
                str(review.root),
                "--task-file",
                "tasks/save.md",
                "save",
                "--artifact",
                str(review.artifact_path),
                "--review",
                str(output),
            ],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    assert saved.returncode == 0, saved.stderr
    paths = json.loads(saved.stdout)["saved"]
    assert "Retained Issue" in (review.root / paths[0]).read_text(encoding="utf-8")
    assert tuple(
        (review.root / p).read_text(encoding="utf-8") for p in paths
    ) == render_snapshot(review.root, review_snapshot(data, exported))


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
    review = controller(tmp_path, data)
    review.initialize()
    status = finish(review)
    assert all(value["remaining"] == 0 for value in status["sections"].values())
    assert status["sections"]["naming"]["reviewed"] == 1223
    assert status["sections"]["human_confirmations"]["reviewed"] == 532
    exported, rendered = publish(review, tmp_path)
    legacy = review_for(data)
    assert exported == legacy
    assert review_snapshot(data, exported) == review_snapshot(data, legacy)
    assert rendered == render_snapshot(review.root, review_snapshot(data, legacy))


if __name__ == "__main__":
    raise SystemExit(run(__file__))
