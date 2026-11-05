"""Temporary input retention and cleanup boundaries."""

import json
import os
import sys
from argparse import Namespace
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deploy import operation_journal as J
from deploy import run_context, steps, temporary
from deploy.timing import Timing
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked
from utils.local_evidence import evidence_store, write_sealed

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def setup_case(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    journal = tmp_path / "task" / "journal.json"
    journal.parent.mkdir(mode=0o700)
    directory = temporary.create(journal, ["App"])
    template = directory / "App.json"
    template.write_text("{}", encoding="utf-8")
    backend = SimpleNamespace(run_context={"states": {}}, states={}, workdir=directory)
    return root, journal, directory, template, backend


def cleanup(root, journal, directory, backend, saved=None):
    with (
        patch.object(temporary, "task_snapshot"),
        patch.object(temporary.deploy_progress, "read_task", return_value=saved),
    ):
        temporary.reclaim(
            journal, root, directory=directory, backend=backend, stacks=["App"]
        )


@pytest.mark.parametrize(
    "status", ["BLOCKED", "FAILED", "UNKNOWN", "RUNNING", "SUCCESS"]
)
def check_saved_delivery_is_retained(tmp_path, status):
    root, journal, directory, template, backend = setup_case(tmp_path)
    saved = {
        "runContext": {
            "states": {"App": {"status": status, "delivery": {"path": str(template)}}}
        }
    }
    cleanup(root, journal, directory, backend, saved)
    assert template.exists()


@pytest.mark.parametrize(
    "pending",
    [
        "currentFailure",
        "pendingObserved",
        "pendingGeneration",
        "generationError",
        "checkpointPending",
    ],
)
def check_pending_work_retains_inputs(tmp_path, pending):
    root, journal, directory, template, backend = setup_case(tmp_path)
    backend.run_context[pending] = {"pending": True}
    cleanup(root, journal, directory, backend)
    assert template.exists()


def check_invalid_template_names_rejected(tmp_path):
    root, journal, directory, template, backend = setup_case(tmp_path)
    with pytest.raises(Blocked):
        temporary.create(journal, ["../outside"])


def check_unreferenced_current_directory_removed(tmp_path):
    root, journal, directory, template, backend = setup_case(tmp_path)
    prior = temporary.create(journal, ["App"])
    cleanup(root, journal, directory, backend)
    assert not directory.exists() and prior.exists()


@pytest.mark.parametrize("kind", ["unknown", "symlink", "hardlink", "permissions"])
def check_unsafe_files_retained(tmp_path, kind):
    root, journal, directory, template, backend = setup_case(tmp_path)
    if kind == "unknown":
        (directory / "unknown").write_text("keep")
    elif kind == "symlink":
        template.unlink()
        template.symlink_to(root)
    elif kind == "hardlink":
        (root / "hardlink").hardlink_to(template)
    elif os.name != "nt":
        template.chmod(0o666)
    else:
        pytest.skip("POSIX permissions")
    cleanup(root, journal, directory, backend)
    assert directory.exists()


def check_failure_evidence_and_repair_lock_retain_inputs(tmp_path):
    root, journal, directory, template, backend = setup_case(tmp_path)
    store = temporary.evidence_store(root)
    failure = store / "deploy-failure-current.json"
    failure.write_text("unverified")
    cleanup(root, journal, directory, backend)
    assert template.exists()
    failure.unlink()
    with temporary.handoff.repair_lock(root):
        cleanup(root, journal, directory, backend)
    assert template.exists()


def check_diagnostic_paths_are_task_local(tmp_path):
    root, journal, directory, template, backend = setup_case(tmp_path)
    backend.states = {"App": {"delivery": {"path": str(root / "App.json")}}}
    assert temporary.diagnostic_paths(journal, backend, ["App"]) == {str(template)}


@pytest.mark.parametrize("missing", ["none", "file", "directory"])
def check_saved_template_diagnostic_when_missing(tmp_path, missing):
    root, journal, directory, template, backend = setup_case(tmp_path)
    backend.workdir = None
    backend.states = {"App": {"delivery": {"path": str(template)}}}
    if missing != "none":
        template.unlink()
    if missing == "directory":
        directory.rmdir()
    assert temporary.diagnostic_paths(journal, backend, ["App"]) == {str(template)}


def check_diagnostic_rejects_symlinks_and_foreign_paths(tmp_path):
    root, journal, directory, template, backend = setup_case(tmp_path)
    backend.workdir = None
    foreign = root / "App.json"
    backend.states = {"App": {"delivery": {"path": str(foreign)}}}
    assert not temporary.diagnostic_paths(journal, backend, ["App"])
    template.unlink()
    directory.rmdir()
    directory.symlink_to(root, target_is_directory=True)
    backend.states["App"]["delivery"]["path"] = str(template)
    assert not temporary.diagnostic_paths(journal, backend, ["App"])


def check_diagnostic_rejects_untrusted_task_directory(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permissions")
    root, journal, directory, template, backend = setup_case(tmp_path)
    journal.parent.chmod(0o777)
    assert not temporary.diagnostic_paths(journal, backend, ["App"])


@pytest.mark.parametrize("status", ["RUNNING", "BLOCKED"])
@pytest.mark.parametrize("exceptional", [False, True])
def check_unreferenced_empty_directory_removed(tmp_path, status, exceptional):
    root, journal, directory, template, backend = setup_case(tmp_path)
    template.unlink()
    backend.run_context["states"] = {"App": {"status": status}}
    (temporary.evidence_store(root) / "deploy-failure-current.json").write_text(
        "unverified"
    )
    if exceptional:
        try:
            raise ValueError("failure")
        except ValueError:
            cleanup(root, journal, directory, backend)
    else:
        cleanup(root, journal, directory, backend)
    assert not directory.exists()


def check_empty_directory_referenced_in_progress_is_retained(tmp_path):
    root, journal, directory, template, backend = setup_case(tmp_path)
    template.unlink()
    saved = {"runContext": {"states": {"App": {"delivery": {"path": str(template)}}}}}
    cleanup(root, journal, directory, backend, saved)
    assert directory.exists()


def check_exception_retains_nonempty_directory(tmp_path):
    root, journal, directory, template, backend = setup_case(tmp_path)
    try:
        raise ValueError("failure")
    except ValueError:
        cleanup(root, journal, directory, backend)
    assert template.exists()


TARGET = {
    "awsAccountId": "123456789012",
    "awsRegion": "ap-northeast-1",
    "iacEngine": "cloudformation",
}


def workspace(tmp_path):
    root, journal, _, _, _ = setup_case(tmp_path)
    task = SimpleNamespace(
        name="tasks/deploy.md", task_digest="task", status="running", text=""
    )
    return root, journal, task


def reclaim_under_progress_lock(actual, target_backend, *args, **kwargs):
    progress = steps.deploy_progress.progress_path(target_backend.root)
    with pytest.raises(Blocked, match="lock busy"):
        with J.locked(progress):
            raise AssertionError("cleanup ran after releasing progress lock")
    actual(*args, **kwargs)


@pytest.mark.parametrize("blocked", [False, True, "missing"])
def check_controller_closes_lock_and_cleans_workdir_on_return_or_error(
    tmp_path, blocked, capsys
):
    root, journal, task = workspace(tmp_path)
    args = Namespace(
        environment="dev",
        aws_account_id=TARGET["awsAccountId"],
        alias=None,
        stack=["App"],
        profile=None,
        approve_change_set=[],
        action="advance",
        sequential=False,
    )
    prior_directory = temporary.create(journal, ["App"])
    prior_template = prior_directory / "App.json"
    prior_template.write_text("{}", encoding="utf-8")
    failure = evidence_store(root) / "deploy-failure-prior.json"
    write_sealed(
        root,
        failure,
        {
            "repository": str(root),
            "target": TARGET,
            "taskFile": "tasks/prior.md",
            "taskDigest": "prior",
            "states": {"App": {"delivery": {"path": str(prior_template)}}},
        },
    )
    current_directory = temporary.create(journal, ["App"])
    backend = SimpleNamespace(
        root=root,
        target=TARGET,
        workdir=current_directory,
        states={},
        task=task,
        run_context={"states": {}},
        aws=Mock(),
    )
    report = (
        Mock(
            side_effect=FileNotFoundError(
                2, "private secret", str(current_directory / "App.json")
            )
        )
        if blocked == "missing"
        else Mock(side_effect=Blocked("unconfirmed AWS operation"))
        if blocked
        else Mock(return_value={"result": "PENDING"})
    )
    with (
        patch.object(temporary, "create", return_value=current_directory),
        patch.object(temporary.deploy_progress, "read_task", return_value=None),
        patch.object(steps.context, "load_target", return_value=TARGET),
        patch.object(steps.context, "check_deploy_context", return_value=TARGET),
        patch.object(steps, "task_snapshot", return_value=task),
        patch.object(temporary, "task_snapshot", return_value=task),
        patch.object(steps, "selected_task", return_value=nullcontext()),
        patch.object(run_context, "active_scope", return_value="deploy"),
        patch.object(steps, "recover_local_publication"),
        patch.object(steps, "restore"),
        patch.object(
            run_context, "new_context", return_value={"states": {}, "inputDigests": {}}
        ),
        patch.object(
            steps.inputs,
            "stack_snapshot",
            return_value=SimpleNamespace(authoritative={}),
        ),
        patch.object(steps.current_state, "refresh"),
        patch.object(steps, "describe", report),
        patch.object(steps, "run_group", return_value="ACTIVE"),
        patch.object(steps, "save"),
        patch.object(
            temporary,
            "reclaim",
            side_effect=partial(
                reclaim_under_progress_lock, temporary.reclaim, backend
            ),
        ),
        patch.object(run_context, "_callback_run_guard"),
        patch.object(J, "location", return_value=journal),
    ):
        TestCase().assertEqual(
            steps.run(
                args,
                root,
                Timing(root),
                Mock(return_value=backend),
                Mock(return_value=(1, [])),
            ),
            2 if blocked else 0,
        )
    assert not current_directory.exists()
    assert prior_directory.exists()
    if blocked == "missing":
        output = json.loads(capsys.readouterr().out)
        assert output["cause"]["path"] == str(current_directory / "App.json")
        assert output["cause"]["errno"] == 2
        assert "private secret" not in json.dumps(output)
        backend.aws.assert_not_called()
    with J.locked(steps.deploy_progress.progress_path(root)):
        pass
    TestCase().assertTrue(failure.exists() and prior_template.exists())
    with J.locked(journal):
        pass


if __name__ == "__main__":
    raise SystemExit(run(__file__))
