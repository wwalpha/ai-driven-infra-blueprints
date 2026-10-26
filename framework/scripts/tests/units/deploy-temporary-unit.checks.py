"""Owned temporary inputs, retained delivery references and controller exit cleanup."""

import sys
from argparse import Namespace
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import operation_journal as J
from deploy import run_context, temporary
from deploy.timing import Timing
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked
from utils.sealed_evidence import write_sealed

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

TARGET = {
    "awsAccountId": "123456789012",
    "awsRegion": "ap-northeast-1",
    "iacEngine": "cloudformation",
}


def workspace(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    journal = tmp_path / "journal/journal.json"
    journal.parent.mkdir(mode=0o700)
    task = SimpleNamespace(name="tasks/deploy.md", task_digest="task")
    return root, journal, task


def pin_template(journal, path, root):
    write_sealed(
        root,
        journal,
        {
            "target": TARGET,
            "operations": {
                "App": {
                    "unit": {"name": "App"},
                    "inputDigest": "input",
                    "state": {"status": "RUNNING", "delivery": {"path": str(path)}},
                }
            },
            "publication": {"repository": str(root), "target": TARGET},
        },
    )


@pytest.mark.parametrize(
    "state",
    [
        "normal",
        "blocked",
        "journal",
        "recovered",
        "orphan",
        "other-task",
        "other-root",
        "unknown",
        "symlink",
        "tampered-marker",
    ],
)
def check_owned_directory_cleanup(tmp_path, state):
    root, journal, task = workspace(tmp_path)
    owner_root = root if state != "other-root" else tmp_path / "another-repo"
    owner_task = (
        task
        if state != "other-task"
        else SimpleNamespace(name="tasks/another.md", task_digest="other")
    )
    directory = temporary.create(journal, owner_root, owner_task, TARGET, ["App"])
    template = directory / "App.json"
    template.write_text("{}", encoding="utf-8")
    if state in {"journal", "recovered"}:
        pin_template(journal, template, root)
    if state == "unknown":
        (directory / "Human.txt").write_text("keep", encoding="utf-8")
    elif state == "symlink":
        template.unlink()
        template.symlink_to(root)
    elif state == "tampered-marker":
        (directory / "owner.json").write_text("unreadable", encoding="utf-8")
    with J.locked(journal):
        temporary.reclaim(journal, root, task, TARGET)
        retained = state in {
            "journal",
            "recovered",
            "other-task",
            "other-root",
            "unknown",
            "symlink",
            "tampered-marker",
        }
        assert directory.exists() == retained
        if state == "recovered":
            prior = temporary.references(J.read(journal))
            journal.unlink()
            next_task = SimpleNamespace(name="tasks/next.md", task_digest="next")
            temporary.reclaim(journal, root, next_task, TARGET, prior=prior)
            assert not directory.exists()
    assert journal.with_suffix(".lock").is_file()


@pytest.mark.parametrize("blocked", [False, True])
def check_controller_closes_lock_and_cleans_workdir_on_return_or_error(
    tmp_path, blocked
):
    root, journal, task = workspace(tmp_path)
    args = Namespace(
        environment="dev",
        aws_account_id=TARGET["awsAccountId"],
        alias=None,
        stack=["App"],
        profile=None,
        approve_change_set=[],
        recover_operations=True,
        pause_after_group=False,
    )
    backend = SimpleNamespace(root=root, workdir=None, pending_publication={})
    recovery = (
        Mock(side_effect=Blocked("unconfirmed AWS operation")) if blocked else Mock()
    )
    with (
        patch.object(run_context.context, "load_target", return_value=TARGET),
        patch.object(run_context.context, "check_deploy_context", return_value=TARGET),
        patch.object(run_context, "task_snapshot", return_value=task),
        patch.object(run_context, "task_reads", return_value=nullcontext()),
        patch.object(run_context, "active_scope", return_value="deploy"),
        patch.object(J, "location", return_value=journal),
        patch.object(J, "recover", recovery),
        patch.object(J, "publication_conflicts"),
        patch.object(run_context.handoff, "discard_unused_failures"),
    ):
        assert run_context.run(
            args, root, Timing(root), root, Mock(return_value=backend), Mock()
        ) == (2 if blocked else 0)
    assert not backend.workdir.exists()
    with J.locked(journal):
        pass


if __name__ == "__main__":
    raise SystemExit(run(__file__))
