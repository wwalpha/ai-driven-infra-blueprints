"""Synthetic Review batches; acknowledgements are fixtures, never a production reviewer."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from issues.review_progress import ReviewController
from support.issues_scan_fixtures import snapshot_artifact

ROOT = Path(__file__).resolve().parents[4]


def controller(
    tmp_path: Path, artifact: dict[str, Any] | None = None
) -> ReviewController:
    root = tmp_path / "repository"
    root.mkdir(exist_ok=True)
    artifact = artifact if artifact is not None else snapshot_artifact(root)
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    return ReviewController(root, path, tmp_path / "progress.json")


def submission(batch: dict[str, Any]) -> dict[str, Any]:
    results = []
    for material in batch["items"]:
        item = material["item"]
        result = dict(
            id=item["id"],
            reviewed=True,
            reason="Fixture explicitly reviewed",
            evidence="Synthetic Scan item " + item["id"],
            issues=[],
            unverified=[],
        )
        if batch["section"] == "judgments" and "message" in item:
            result["assignment"] = dict(
                status="assigned",
                service="s3",
                evidence="Fixture proves source ownership",
            )
        if batch["section"] == "diagnostics":
            result["decision"] = dict(
                id=item["id"], outcome="issue", reason="Current diagnostic confirmed"
            )
        results.append(result)
    return dict(batch_id=batch["batch_id"], section=batch["section"], results=results)


def finish(review: ReviewController, limit: int = 20) -> dict[str, Any]:
    status = review.status()
    while not status["complete"]:
        batch = review.next_batch(limit)
        if batch.get("blocked"):
            raise ValueError(batch)
        status = review.submit(submission(batch))
    return status


def cli(
    review: ReviewController, operation: str, *args: str
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "framework/scripts/issues_scan.py"),
            "--repository-root",
            str(review.root),
            "review",
            operation,
            "--artifact",
            str(review.artifact_path),
            "--state",
            str(review.path),
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
