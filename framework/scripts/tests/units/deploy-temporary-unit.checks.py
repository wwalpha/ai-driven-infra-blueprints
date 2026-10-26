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
from utils.sealed_evidence import evidence_store, write_sealed

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
        "same-repository",
        "request",
        "unknown-request",
        "peer-journal",
        "generation-producer",
        "hardlink",
        "writable",
        "active-handoff",
        "other-target",
        "unknown",
        "symlink",
        "tampered-marker",
    ],
)
def check_owned_directory_cleanup(tmp_path, state):
    root, journal, task = workspace(tmp_path)
    owner_root = (
        tmp_path / "worktree"
        if state == "same-repository"
        else root
        if state != "other-root"
        else tmp_path / "another-repo"
    )
    owner_task = (
        task
        if state != "other-task"
        else SimpleNamespace(name="tasks/another.md", task_digest="other")
    )
    owner_target = (
        {**TARGET, "awsRegion": "other"} if state == "other-target" else TARGET
    )
    directory = temporary.create(journal, owner_root, owner_task, owner_target, ["App"])
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
    if state in {"request", "unknown-request"}:
        store = evidence_store(root)
        failure = store / "deploy-failure-old.json"
        write_sealed(
            root, failure, {"states": {"App": {"delivery": {"path": str(template)}}}}
        )
        request = store / "deploy-repair-active/request.json"
        request.parent.mkdir(mode=0o700)
        write_sealed(root, request, {"failureEvidence": str(failure)})
        if state == "unknown-request":
            request.write_text("unreadable")
    elif state in {"peer-journal", "generation-producer"}:
        pin_template(journal, template, root)
        records = J.read(journal)
        if state == "peer-journal":
            peer = records[0]
            record = {
                "target": TARGET,
                "operations": {},
                "publication": {"repository": str(root), "target": TARGET},
                "peers": [peer],
            }
        else:
            record = records[0]
            record["publication"]["generationProducers"] = record.pop("operations")
            record["operations"] = {}
            record["publication"]["generationProducers"]["App"]["state"].update(
                status="SUCCESS", observedSynced=True
            )
        write_sealed(root, journal, record)
    elif state == "hardlink":
        (root / "linked").hardlink_to(template)
    elif state == "writable":
        template.chmod(0o666)
    with (
        temporary.handoff.repair_lock(root)
        if state == "active-handoff"
        else nullcontext(),
        J.locked(journal),
        patch.object(J, "same_repository", return_value=state != "other-root"),
    ):
        temporary.reclaim(journal, root, TARGET)
        retained = state in {
            "journal",
            "recovered",
            "other-root",
            "request",
            "unknown-request",
            "peer-journal",
            "generation-producer",
            "hardlink",
            "writable",
            "active-handoff",
            "other-target",
            "unknown",
            "symlink",
            "tampered-marker",
        }
        assert directory.exists() == retained
        if state == "recovered":
            journal.unlink()
            temporary.reclaim(journal, root, TARGET)
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
