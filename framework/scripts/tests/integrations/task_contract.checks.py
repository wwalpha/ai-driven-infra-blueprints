#!/usr/bin/env python3
"""Task selection, ordinary transitions and atomic contract publication."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest
import task_contract as tasks
from issues.publication import save_scan
from support.issues_scan_fixtures import review_for, snapshot_artifact
from support.pytest_cli import run
from support.repository_fixtures import transition_contract as contract
from utils.function_wrapper import BoundCallback as _bind_framework_callback

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
    with patch.dict(os.environ, {}, clear=True):
        if transition != "start":
            tasks.start(root, owner, contract(owner, ["shared.md"]))
            tasks.start(root, name, contract(name, ["shared.md"]))
            tasks.complete(root, owner)
        if transition == "complete":
            tasks.refresh(root, name)
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
            "refresh": lambda: tasks.refresh(root, name),
            "complete": lambda: tasks.complete(root, name),
            "suspend": lambda: tasks.suspend(root, name, "fixture stop"),
            "resume": lambda: tasks.resume(root, name),
        }
        with (
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


if __name__ == "__main__":
    raise SystemExit(run(__file__))
