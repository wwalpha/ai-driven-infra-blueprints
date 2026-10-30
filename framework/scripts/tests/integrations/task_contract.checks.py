#!/usr/bin/env python3
"""Task selection, ordinary transitions and atomic contract publication."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest
import task_contract_core as tasks
import task_contract_runtime as task_runtime
from issues.publication import save_scan
from support.issues_scan_fixtures import review_for, snapshot_artifact
from support.model_v2_fixtures import logs_fixture
from support.pytest_cli import run
from support.repository_fixtures import fixture, git
from support.repository_fixtures import transition_contract as contract
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from validation import acceptance
from validation.findings import Findings
from validation.task import TaskValidation

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_atomic_contract_reads_pause(paused, release, /):
    paused.set()
    assert release.wait(10), "reader did not release publication"


def _callback_check_atomic_contract_reads_replacing(
    destination, original_replace, pause, /, source, target
):
    if Path(target) == destination:
        pause()  # Atomic publication must still expose only the previous contract.
    return original_replace(source, target)


def _callback_check_atomic_contract_reads_opening(
    destination, original_open, pause, /, path, mode="r", *args, **kwargs
):
    stream = original_open(path, mode, *args, **kwargs)
    if path == destination and mode in {"w", "x"}:
        pause()  # The old implementation has already truncated/created the file.
    return stream


@pytest.mark.parametrize("transition", ["start", "complete", "suspend", "resume"])
def check_atomic_contract_reads(tmp_path, transition):
    root = tmp_path
    name = "tasks/writer.md"
    owner = "tasks/owner.md"
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(task_runtime, "Validator") as validator,
    ):
        validator.return_value.report.return_value = 0
        if transition != "start":
            tasks.start(root, owner, contract(owner, ["shared.md"]))
            tasks.start(root, name, contract(name, ["shared.md"]))
            task_runtime.complete(root, owner)
        if transition == "complete":
            task_runtime.refresh(root, name)
        if transition == "resume":
            tasks.suspend(root, name, "fixture stop")
        before = tasks.contracts(root)
        destination = root / name
        paused, release = Event(), Event()
        original_open, original_replace = Path.open, os.replace
        pause = _bind_framework_callback(
            _callback_check_atomic_contract_reads_pause, paused, release
        )
        opening = _bind_framework_callback(
            _callback_check_atomic_contract_reads_opening,
            destination,
            original_open,
            pause,
        )
        replacing = _bind_framework_callback(
            _callback_check_atomic_contract_reads_replacing,
            destination,
            original_replace,
            pause,
        )
        operations = {
            "start": lambda: tasks.start(root, name, contract(name, ["shared.md"])),
            "refresh": lambda: task_runtime.refresh(root, name),
            "complete": lambda: task_runtime.complete(root, name),
            "suspend": lambda: tasks.suspend(root, name, "fixture stop"),
            "resume": lambda: task_runtime.resume(root, name),
        }
        with (
            patch.object(task_runtime, "check_resume_scope"),
            patch.object(Path, "open", opening),
            patch.object(os, "replace", replacing),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            writer = executor.submit(operations[transition])
            try:
                assert paused.wait(10), "publication was not intercepted"
                during = tasks.contracts(root)
                for text in during.values():
                    tasks.status(text)
                assert during == before, "lock-free reader observed partial contract"
            finally:
                release.set()
                writer.result(timeout=10)


def check_shared_issue_files(tmp_path, monkeypatch):
    first, second = "tasks/first.md", "tasks/second.md"
    report = "issues/dev/cde/issues.md"
    tasks.start(
        tmp_path,
        first,
        contract(first, [report], kind="migration", scope="dev/cde/ec2"),
    )
    tasks.start(
        tmp_path,
        second,
        contract(second, [report], kind="migration", scope="dev/cde/s3"),
    )
    artifact = snapshot_artifact(tmp_path, services=["ec2", "s3"], target="cde")
    for name in (first, second):
        monkeypatch.setenv(tasks.SELECTOR, name)
        with pytest.raises(ValueError, match="explicit service scope"):
            save_scan(tmp_path, artifact, review_for(artifact))
    assert not (tmp_path / report).exists()


def check_self_recovery_resume():
    with fixture() as root:
        name = "tasks/recovery.md"
        tasks.start(root, name, contract(name, ["file.txt"]))
        (root / "file.txt").write_text("incorrect")
        git(root, "add", "file.txt")
        tasks.suspend(
            root, name, "scope: accidental staged change and Acceptance ID typo"
        )
        (root / name).write_text(
            (root / name)
            .read_text(encoding="utf-8")
            .replace("- [R1] `changed:file.txt`", "- [R2] `changed:file.txt`"),
            encoding="utf-8",
        )
        other = "tasks/other.md"
        tasks.start(root, other, contract(other, ["other.txt"]))
        other_contract = (root / other).read_bytes()
        suspended = (root / name).read_bytes()
        (root / "file.txt").write_text("original\n")
        # A worktree-only repair leaves the staged change present.
        with pytest.raises(ValueError, match="outside task scope"):
            # This independent out-of-scope change belongs to another task.
            (root / "other.txt").write_text("preserve")
            task_runtime.resume(root, name)
        assert (root / name).read_bytes() == suspended
        assert (root / "other.txt").read_text() == "preserve"
        assert (root / other).read_bytes() == other_contract
        (root / "other.txt").unlink()  # Fixture owner resolves its own change.
        git(root, "restore", "--staged", "file.txt")
        (root / name).write_text(
            suspended.decode()
            .replace("- [R2] `changed:file.txt`", "- [R1] `changed:file.txt`")
            .replace("- `file.txt`", "- `file.txt`\n- `needed.txt`"),
            encoding="utf-8",
        )
        (root / "needed.txt").write_text("authorized")
        repaired = (root / name).read_bytes()
        cli = Path(__file__).resolve().parents[2] / "task_contract.py"
        command = [
            sys.executable,
            str(cli),
            "--repository-root",
            str(root),
            "--task-file",
            name,
        ]
        preflight = subprocess.run(
            command + ["--check-resume-scope"], capture_output=True, text=True
        )
        assert preflight.returncode == 0, preflight.stdout + preflight.stderr
        assert (root / name).read_bytes() == repaired
        resumed = subprocess.run(command + ["--resume"], capture_output=True, text=True)
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert tasks.status((root / name).read_text()) == "running"
        assert "## Suspension reason" not in (root / name).read_text()
        with tasks.selected_task(root, name):
            findings = Findings(root)
            TaskValidation(root, findings).check_task_scope()
        assert not findings.errors, findings.errors


if __name__ == "__main__":
    raise SystemExit(run(__file__))


def check_task_acceptance_human_failure_review(tmp_path):
    with fixture() as root:
        source = logs_fixture(root)
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "baseline Model")
        name = "tasks/human-review.md"
        tasks.start(
            root,
            name,
            contract(
                name,
                ["file.txt"],
                kind="migration",
                scope="qa-synthetic/team-a/cloudwatch-logs",
            ),
        )
        (root / "file.txt").write_text("authorized candidate")
        findings = Findings(root)
        task = TaskValidation(root, findings, contract_file=name)
        task.check_task_scope()
        findings.evaluate(
            "model.literal.001-002",
            {("qa-synthetic", "team-a", "cloudwatch-logs")},
            lambda: findings.input_check(
                False, source, "existing RetentionInDays type is invalid"
            ),
            source_path=source,
        )
        (failure,) = findings.failures()
        assert task.acceptance()["status"] == "FAIL"
        dependencies = acceptance.unchanged_model_evidence(task, failure)
        record = dict(
            failure,
            task=name,
            dependencies=dependencies,
            candidate=acceptance.candidate(task, dependencies),
            assessment={
                key: "Reviewed baseline, unchanged Model and references; file.txt edit is independent"
                for key in (
                    "task_relevance",
                    "before_after",
                    "producer_consumer",
                    "regression",
                    "why_outside_task",
                    "risk",
                )
            },
            human_approval=dict(
                decision="exclude_this_task_only",
                diagnostic_id=failure["diagnostic_id"],
                reason=failure["reason"],
                statement="Human explicitly approves "
                + failure["diagnostic_id"]
                + " for this Task only",
            ),
        )
        review = tmp_path / "human-decision.json"
        review.write_text(json.dumps([record]))
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "task_contract.py"),
            "--repository-root",
            str(root),
            "--task-file",
            name,
            "--approve-out-of-task-failures",
            str(review),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        task.contract_text = (root / name).read_text()
        assert task.acceptance()["status"] == "PASS" and findings.status == "FAIL"
        assert tasks.status(task.contract_text) == "running"
        assert failure["reason"] in task.contract_text
        (root / "file.txt").write_text("changed candidate after Human review")
        assert task.acceptance()["status"] == "FAIL"
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 1 and "stale" in result.stdout
        assert findings.failures()[0]["reason"] == failure["reason"]


def check_registration_candidate_retry(tmp_path):
    with fixture() as root:
        name = "tasks/same-task.md"
        candidate = tmp_path / "candidate.md"
        good = contract(name, ["file.txt"])
        candidate.write_text(
            good.replace("`governance`", "`governnace`"), encoding="utf-8"
        )
        cli = Path(__file__).resolve().parents[2] / "task_contract.py"
        command = [
            sys.executable,
            str(cli),
            "--repository-root",
            str(root),
            "--task-file",
            name,
            "--source",
            str(candidate),
        ]
        rejected = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8"
        )
        assert rejected.returncode != 0
        assert "unknown Task type: governnace" in rejected.stdout + rejected.stderr
        assert not (root / name).exists()
        assert not (root / "tasks").exists()
        candidate.write_text(good, encoding="utf-8")
        accepted = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8"
        )
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert list((root / "tasks").iterdir()) == [root / name]
        assert (root / name).read_text(encoding="utf-8") == good
        (root / "file.txt").write_text("continued authorized work", encoding="utf-8")
        findings = Findings(root)
        task = TaskValidation(root, findings, contract_file=name)
        task.check_task_scope()
        task.check_acceptance_checks({})
        assert not findings.errors, findings.errors
