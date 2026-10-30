"""Owned temporary inputs, retained delivery references and controller exit cleanup."""

import sys
from argparse import Namespace
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import operation_journal as J
from deploy import run_context, steps, temporary
from deploy.timing import Timing
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked
from utils.local_evidence import evidence_store, read_sealed, write_sealed

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
    task = SimpleNamespace(name="tasks/deploy.md", task_digest="task", status="running")
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
        "failure",
        "tampered-failure",
        "foreign-failure",
        "missing-template",
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
    if state in {
        "failure",
        "tampered-failure",
        "foreign-failure",
        "missing-template",
        "request",
        "unknown-request",
    }:
        store = evidence_store(root)
        failure = store / "deploy-failure-old.json"
        write_sealed(
            root,
            failure,
            {
                "repository": str(root) if state != "foreign-failure" else "unknown",
                "target": TARGET,
                "states": {"App": {"delivery": {"path": str(template)}}},
            },
        )
        if state == "tampered-failure":
            failure.write_text("unreadable")
        elif state == "missing-template":
            template.unlink()
        if state in {"request", "unknown-request"}:
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
            "failure",
            "tampered-failure",
            "foreign-failure",
            "missing-template",
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
        action="status",
        sequential=False,
        recover_operations=True,
        pause_after_group=False,
    )
    prior_directory = temporary.create(journal, root, task, TARGET, ["App"])
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
    current_directory = temporary.create(journal, root, task, TARGET, ["App"])
    backend = SimpleNamespace(
        root=root, target=TARGET, workdir=current_directory, states={}, aws=Mock()
    )
    report = (
        Mock(side_effect=Blocked("unconfirmed AWS operation"))
        if blocked
        else Mock(return_value={"result": "PENDING"})
    )
    with (
        patch.object(steps.context, "load_target", return_value=TARGET),
        patch.object(steps.context, "check_deploy_context", return_value=TARGET),
        patch.object(steps, "task_snapshot", return_value=task),
        patch.object(steps, "selected_task", return_value=nullcontext()),
        patch.object(run_context, "active_scope", return_value="deploy"),
        patch.object(steps.worktree, "bind"),
        patch.object(steps, "recover_local_publication"),
        patch.object(steps, "restore"),
        patch.object(
            run_context, "new_context", return_value={"states": {}, "inputDigests": {}}
        ),
        patch.object(steps, "refresh_requests"),
        patch.object(steps, "checkpoint_receipts"),
        patch.object(steps, "describe", report),
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
    TestCase().assertFalse(current_directory.exists())
    TestCase().assertTrue(failure.exists() and prior_template.exists())
    with J.locked(journal):
        pass


@pytest.mark.parametrize(
    "consume", ["discard", "request", "interrupted", "unknown-cleanup"]
)
def check_failure_survives_new_task_and_templates_live_until_consumed(
    tmp_path, consume
):
    root, journal, task = workspace(tmp_path)
    directory = temporary.create(journal, root, task, TARGET, ["App"])
    template = directory / "App.json"
    template.write_text("{}", encoding="utf-8")
    backend = SimpleNamespace(
        root=root,
        target=TARGET,
        environment="dev",
        directory="team",
        states={
            "App": {
                "status": "BLOCKED",
                "delivery": {"path": str(template)},
                "approvedChangeDigest": "never-retain",
            }
        },
        run_context={
            "taskFile": task.name,
            "taskDigest": task.task_digest,
            "consumedInputs": {},
            "modelInputs": {},
        },
    )
    with J.locked(journal):
        failure = Path(temporary.handoff.record_failure(backend))
        original = failure.read_bytes()
        assert "approvedChangeDigest" not in read_sealed(root, failure)["states"]["App"]
        backend.run_context.update(taskFile="tasks/another.md", taskDigest="another")
        second = Path(temporary.handoff.record_failure(backend))
        temporary.reclaim(journal, root, TARGET)
        assert (
            failure.read_bytes() == original and second.exists() and template.exists()
        )
    with patch.object(J, "location", return_value=journal):
        temporary.handoff.discard_failure(root, second)
        if consume == "discard":
            temporary.handoff.discard_failure(root, failure)
        else:
            request = evidence_store(root) / "deploy-repair-current/request.json"
            request.parent.mkdir(mode=0o700)
            identity = {
                "repository": str(root),
                "requestId": "current",
                "taskFile": task.name,
                "taskDigest": task.task_digest,
                "failureEvidence": str(failure),
            }
            write_sealed(root, request, identity)
            with J.locked(journal):
                temporary.reclaim(journal, root, TARGET)
            assert template.exists() and failure.exists()
            write_sealed(
                root,
                request.with_name("result.json"),
                {"requestId": "current", "commit": "commit"},
            )
            write_sealed(
                root, request.with_name("validation.json"), {"requestId": "current"}
            )
            state = {
                "deployRepair": str(request),
                "verified": True,
                "merged": "commit",
                "commit": "commit",
            }
            if consume in {"interrupted", "unknown-cleanup"}:
                with (
                    patch.object(
                        temporary.handoff,
                        "__finish_discard",
                        side_effect=SystemExit("interrupted"),
                    ),
                    pytest.raises(SystemExit),
                ):
                    temporary.handoff.discard_request(state)
                receipt = request.parent.with_name("deploy-cleanup-current.json")
                original_receipt = receipt.read_bytes()
                if consume == "unknown-cleanup":
                    receipt.write_text("untrusted", encoding="utf-8")
                    # Even if a Failure is absent, unknown cleanup evidence retains inputs.
                    original_failure = failure.read_bytes()
                    failure.unlink()
                with J.locked(journal):
                    temporary.reclaim(journal, root, TARGET)
                assert template.exists()
                if consume == "unknown-cleanup":
                    receipt.write_bytes(original_receipt)
                    failure.write_bytes(original_failure)
                    failure.chmod(0o600)
            temporary.handoff.discard_request(state)
    assert not failure.exists()
    with J.locked(journal):
        temporary.reclaim(journal, root, TARGET)
    assert not directory.exists()


def check_inline_failure_template_does_not_block_reclamation(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    template = root / "template.yaml"
    template.write_text("Resources: {}", encoding="utf-8")
    failure = evidence_store(root) / "deploy-failure-inline.json"
    write_sealed(
        root,
        failure,
        {
            "repository": str(root),
            "target": TARGET,
            "states": {
                "App": {
                    "delivery": {"path": str(template), "arguments": {"inline": True}}
                }
            },
        },
    )
    assert temporary.handoff.failure_templates(root, TARGET) == set()
    assert template.exists() and failure.exists()
    external = tmp_path / "external.json"
    external.write_text("{}", encoding="utf-8")
    external.chmod(0o600)
    write_sealed(
        root,
        failure,
        {
            "repository": str(root),
            "target": TARGET,
            "states": {
                "App": {
                    "delivery": {"path": str(external), "arguments": {"inline": True}}
                }
            },
        },
    )
    assert temporary.handoff.failure_templates(root, TARGET) == {external}


if __name__ == "__main__":
    raise SystemExit(run(__file__))
