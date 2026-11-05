"""Real scoped publication and normal Worktree checkpoint while a peer is running."""

import hashlib
import json
import sys
import tempfile
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import model.format as model_format
import sync_runtime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import task_contract_runtime as transitions
import worktree_checkpoint as checkpoints
import worktree_task as wt
from deploy import worktree
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
    git,
    invoke,
)
from support.pytest_cli import run
from support.worktree_deploy_fixtures import seed
from support.worktree_task_fixtures import fixture as task_fixture
from support.worktree_task_fixtures import start as start_task
from task_contract_core import selected_task, status, task_digest

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

FIRST = "cfn-stack-app-dev-first"
SECOND = "cfn-stack-app-dev-second"


@pytest.fixture(autouse=True)
def private_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    for name in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(name, str(tmp_path))


def step(target, report, aws, action, names=(), final=False):
    with selected_task(target, "tasks/deploy.md"):
        return invoke(
            target,
            report,
            aws,
            [
                "--action",
                action,
                *[arg for n in names for arg in ("--sync-stack", n)],
                *(["--final"] if final else []),
            ],
        )


def first_success(target, report, aws):
    for _ in range(5):
        provider = json.loads(aws.read_text(encoding="utf-8"))
        provider["knobs"]["defer_peer"] = True
        if SECOND in provider["stacks"]:
            provider["stacks"][SECOND]["status"] = "CREATE_IN_PROGRESS"
        aws.write_text(json.dumps(provider), encoding="utf-8")
        assert step(target, report, aws, "advance") == 0
        saved = json.loads(report.read_text(encoding="utf-8"))
        if saved["states"][FIRST]["status"] == "SUCCESS":
            assert saved["states"][SECOND]["status"] == "RUNNING"
            return
    raise AssertionError("first Stack never completed")


def finish_peer(aws):
    provider = json.loads(aws.read_text(encoding="utf-8"))
    provider["stacks"][SECOND]["status"] = "CREATE_COMPLETE"
    aws.write_text(json.dumps(provider), encoding="utf-8")


def check_parallel_checkpoint_and_restart(tmp_path, monkeypatch):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(tmp_path / "project", report, same_group=True)
    monkeypatch.chdir(target)
    aws_state(aws)
    primary = Path(wt.load(target, "deploy")[3]["primary"])
    base = git(primary, "rev-parse", "HEAD").strip()
    models_before = {
        p: p.read_bytes() for p in (target / "model").rglob("*.properties")
    }
    first_success(target, report, aws)
    assert all(p.read_bytes() == raw for p, raw in models_before.items())
    before_status = worktree.progress_path(target).read_bytes()
    assert step(target, report, aws, "status") == 0
    assert worktree.progress_path(target).read_bytes() == before_status
    assert step(target, report, aws, "sync", [FIRST]) == 0
    after_sync = {p: p.read_bytes() for p in models_before}
    TestCase().assertEqual(step(target, report, aws, "sync", [FIRST]), 0)
    TestCase().assertTrue(all(p.read_bytes() == raw for p, raw in after_sync.items()))
    assert step(target, report, aws, "checkpoint", [FIRST]) == 0
    sha = git(primary, "rev-parse", "HEAD").strip()
    assert sha != base
    assert git(primary, "rev-list", "--count", base + "..HEAD").strip() == "2"
    assert status((target / "tasks/deploy.md").read_text(encoding="utf-8")) == "running"
    assert step(target, report, aws, "checkpoint", [FIRST]) == 0
    assert git(primary, "rev-parse", "HEAD").strip() == sha
    assert (
        json.loads(aws.read_text(encoding="utf-8"))["stacks"][SECOND]["status"]
        == "CREATE_IN_PROGRESS"
    )
    finish_peer(aws)
    assert step(target, report, aws, "advance") == 0
    assert step(target, report, aws, "sync", [SECOND]) == 0
    assert step(target, report, aws, "checkpoint", [SECOND]) == 0
    assert step(target, report, aws, "status") == 0
    assert not report.with_suffix(".operations.json").exists()
    provider = json.loads(aws.read_text(encoding="utf-8"))
    executions = [
        args["StackName"]
        for _, op, args in provider["calls"]
        if op == "execute_change_set"
    ]
    assert sorted(executions) == sorted(
        provider["stacks"][name]["id"] for name in (FIRST, SECOND)
    )
    assert git(primary, "rev-list", "--count", base + "..HEAD").strip() == "4"
    assert step(target, report, aws, "sync", final=True) == 0
    with selected_task(target, "tasks/deploy.md"):
        transitions.complete(target, "tasks/deploy.md")
    assert (
        status((target / "tasks/deploy.md").read_text(encoding="utf-8")) == "completed"
    )
    assert "`subnet-fixture`" in (
        primary / f"model/dev/{ACCOUNT}/ec2.properties"
    ).read_text(encoding="utf-8")


def check_combined_checkpoint_after_peer_completion(tmp_path, monkeypatch):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(tmp_path / "project", report, same_group=True)
    monkeypatch.chdir(target)
    aws_state(aws)
    first_success(target, report, aws)
    finish_peer(aws)
    TestCase().assertEqual(step(target, report, aws, "advance"), 0)
    TestCase().assertEqual(step(target, report, aws, "sync", [FIRST, SECOND]), 0)
    TestCase().assertEqual(step(target, report, aws, "checkpoint", [FIRST, SECOND]), 0)
    saved = json.loads(report.read_text(encoding="utf-8"))
    TestCase().assertTrue(
        all(saved["states"][name]["status"] == "SUCCESS" for name in (FIRST, SECOND))
    )
    assert not report.with_suffix(".operations.json").exists()


def check_update_receipt_rewritten_base():
    scenarios = (
        "normal", "advance", "rewrite", "same-tree", "other-model", "model", "view", "missing", "task", "stack",
        "input", "unit", "commit", "other-task", "zero", "zero-other-model",
        "zero-unverifiable", "zero-no-parent", "forged-evidence", "forged-empty",
        "forged-other-task", "forged-empty-loss", "zero-reused", "missing-intent",
    )
    for scenario in scenarios:
        with task_fixture(branch="master") as root:
            model = "model/dev/team/test.properties"
            view = "docs/designs/dev/team/test.md"
            for relative in (model, view):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("before\n", encoding="utf-8")
            git(root, "add", "model", "docs")
            git(root, "commit", "-qm", "model and view")
            unrelated = git(root, "rev-parse", "HEAD").strip()
            with patch("support.worktree_task_fixtures.dependency_index.rebuild"):
                target, state = start_task(root, files=(model, view))
            text = (target / state["task_file"]).read_text(encoding="utf-8")
            before = checkpoints.contracts.validation_snapshot(target)
            if not scenario.startswith("zero"):
                for relative in (model, view):
                    (target / relative).write_text("checkpoint\n", encoding="utf-8")
            context = {
                "checkpointPending": {
                    "stacks": ["A"], "before": before,
                    "after": checkpoints.contracts.validation_snapshot(target),
                },
                "taskDigest": task_digest(text),
                "inputDigests": {"A": "input"},
                "stepUnits": [{"name": "A"}],
                "consumedInputs": {},
            }
            backend = SimpleNamespace(
                root=target, phase="update", run_context=context,
                guard=lambda: None, save=lambda: None,
                states={"A": {
                    "observedSynced": True, "stackId": "stack-id",
                    "stackStatus": "COMPLETE", "status": "SUCCESS",
                }},
            )
            with patch.object(checkpoints, "validate"):
                receipt = checkpoints.update_checkpoint(backend, ["A"])["A"]
                assert checkpoints.update_checkpoint(backend, ["A"])["A"] == receipt
                _, _, path, state = wt.load(root, "example")
                if scenario in {"rewrite", "same-tree"}:
                    git(root, "commit", "--amend", "-qm", "rewritten checkpoint")
                if scenario in {"advance", "other-model", "zero-other-model", "model", "view", "missing", "forged-empty-loss"}:
                    relative = {
                        "model": model, "view": view, "missing": model, "forged-empty-loss": model,
                        "advance": "unrelated.txt",
                    }.get(scenario, "model/dev/team/other.properties")
                    if scenario == "missing":
                        (root / relative).unlink()
                    else:
                        (root / relative).write_text("other\n", encoding="utf-8")
                    git(root, "add", "-A", relative)
                    git(root, "commit", "-qm", "task(other): deploy checkpoint A")
                    if scenario in {"other-model", "zero-other-model"}:
                        git(target, "merge", "--ff-only", git(root, "rev-parse", "HEAD").strip())
                if scenario in {"other-task", "forged-other-task"}:
                    other_model = "model/dev/team/other.properties"
                    with patch("support.worktree_task_fixtures.dependency_index.rebuild"):
                        other, other_state = start_task(root, task_id="other", files=(other_model,))
                    other_before = checkpoints.contracts.validation_snapshot(other)
                    (other / other_model).write_text("other task\n", encoding="utf-8")
                    other_text = (other / other_state["task_file"]).read_text(encoding="utf-8")
                    other_context = {
                        "checkpointPending": {
                            "stacks": ["A"], "before": other_before,
                            "after": checkpoints.contracts.validation_snapshot(other),
                        },
                        "taskDigest": task_digest(other_text),
                        "inputDigests": {"A": "input"},
                        "stepUnits": [{"name": "A"}], "consumedInputs": {},
                    }
                    other_backend = SimpleNamespace(
                        root=other, phase="update", run_context=other_context,
                        guard=lambda: None, save=lambda: None,
                        states={"A": dict(backend.states["A"])},
                    )
                    checkpoints.update_checkpoint(other_backend, ["A"])
                if scenario == "zero-reused":
                    context["stepUnits"].append({"name": "B"})
                    context["inputDigests"]["B"] = "input-b"
                    backend.states["B"] = dict(backend.states["A"])
                    snapshot = checkpoints.contracts.validation_snapshot(target)
                    context["checkpointPending"] = {
                        "stacks": ["B"], "before": snapshot, "after": snapshot,
                    }
                    second = checkpoints.update_checkpoint(backend, ["B"])["B"]
                    assert second["commit"] == receipt["commit"]
                    assert second["checkpointEvidence"]["changed"] == []
                    assert checkpoints.update_checkpoint(backend, ["B"])["B"] == second
                if scenario in {"forged-evidence", "forged-empty", "forged-other-task", "forged-empty-loss"}:
                    if scenario != "forged-empty-loss":
                        receipt["commit"] = (
                            git(root, "rev-parse", "HEAD").strip()
                            if scenario == "forged-other-task" else unrelated
                        )
                    evidence = receipt["checkpointEvidence"]
                    if scenario in {"forged-empty", "forged-empty-loss"}:
                        evidence["changed"] = []
                    evidence["tree"] = git(
                        root, "rev-parse", receipt["commit"] + "^{tree}"
                    ).strip()
                    evidence["digest"] = checkpoints.update_receipt_digest(
                        receipt, evidence["changed"]
                    )
                    state["deployCheckpoints"]["A"] = receipt
                    wt.save(path, state)
                if scenario == "missing-intent":
                    state.pop("stackCheckpointIntents")
                    wt.save(path, state)
                if scenario == "zero-no-parent":
                    receipt["commit"] = git(root, "rev-list", "--max-parents=0", "HEAD").strip()
                    receipt["checkpointEvidence"]["tree"] = git(
                        root, "rev-parse", receipt["commit"] + "^{tree}"
                    ).strip()
                    receipt["checkpointEvidence"]["digest"] = checkpoints.update_receipt_digest(receipt, [])
                    state["deployCheckpoints"]["A"] = receipt
                    wt.save(path, state)
                if scenario in {"task", "stack", "input", "unit", "commit", "other-task", "zero-unverifiable"}:
                    key = {
                        "task": "taskDigest", "stack": "stackId", "input": "inputDigest",
                        "unit": "unit", "commit": "commit", "other-task": "commit",
                        "zero-unverifiable": "checkpointEvidence",
                    }[scenario]
                    receipt[key] = (
                        unrelated if scenario == "commit"
                        else git(root, "rev-parse", "HEAD").strip() if scenario == "other-task"
                        else {} if scenario == "zero-unverifiable"
                        else "tampered"
                    )
                    state["deployCheckpoints"]["A"] = receipt
                    wt.save(path, state)
                if scenario in {"model", "view", "missing", "task", "stack", "input", "unit", "commit", "other-task", "zero-unverifiable", "zero-no-parent", "forged-evidence", "forged-empty", "forged-other-task", "forged-empty-loss", "missing-intent"}:
                    with pytest.raises(ValueError, match="receipt|content"):
                        checkpoints.update_checkpoint(backend, ["A"])
                else:
                    assert checkpoints.update_checkpoint(backend, ["A"]) == {"A": receipt}
                    assert checkpoints.update_checkpoint(backend, ["A"]) == {"A": receipt}


def _update_candidate_validate(root, tree, base, task, context):
    assert wt.output(root, "rev-parse", tree + "^{tree}") == tree


def _update_reject_validation(root, tree, base, task, context):
    raise ValueError("candidate validation failed")


def _update_advance_during_validation(primary, calls, root, tree, base, task, context):
    _update_candidate_validate(root, tree, base, task, context)
    calls.append(base)
    if len(calls) == 1:
        (primary / "during-validation.txt").write_text("new base\n", encoding="utf-8")
        git(primary, "add", "during-validation.txt")
        git(primary, "commit", "-qm", "base during validation")


def _update_interrupt_rebase(original, root, *args, **kwargs):
    result = original(root, *args, **kwargs)
    if "rebase" in args:
        raise RuntimeError("interrupted after rebase")
    return result


def check_update_checkpoint_latest_base():
    for scenario in (
        "advance",
        "rewrite",
        "same-tree",
        "different-lines",
        "task-overlap",
        "add",
        "delete",
        "conflict",
        "interrupt",
        "race",
        "input-change",
        "validation-fail",
        "already-applied",
        "ack-interrupt",
        "ack-pending",
    ):
        with task_fixture(branch="master") as root:
            relative = "model/dev/team/test.properties"
            model = root / relative
            model.parent.mkdir(parents=True)
            if scenario != "add":
                model.write_text("old\n" + ("middle\n" * 8) + "end\n", encoding="utf-8")
            input_path = "infra/input.yaml"
            (root / input_path).parent.mkdir(parents=True)
            (root / input_path).write_text("fixed input\n", encoding="utf-8")
            git(root, "add", "model", input_path)
            git(root, "commit", "-qm", "baseline")
            with patch("support.worktree_task_fixtures.dependency_index.rebuild"):
                target, state = start_task(root, files=(relative,))
            if scenario == "task-overlap":
                (target / relative).write_text("task\n" + ("middle\n" * 8) + "end\n", encoding="utf-8")
                git(target, "add", relative)
                git(target, "commit", "-qm", "saved Task change")
                _, _, state_path, state = wt.load(root, "example")
                state["tip"] = git(target, "rev-parse", "HEAD").strip()
                wt.save(state_path, state)
            before = checkpoints.contracts.validation_snapshot(target)
            observed = (
                "task\n" + ("middle\n" * 4) + "observed\n" + ("middle\n" * 3) + "end\n"
                if scenario == "task-overlap" else "observed\n" + ("middle\n" * 8) + "end\n"
            )
            if scenario == "delete":
                (target / relative).unlink()
            else:
                (target / relative).parent.mkdir(parents=True, exist_ok=True)
                (target / relative).write_text(observed, encoding="utf-8")
            after = checkpoints.contracts.validation_snapshot(target)
            text = (target / state["task_file"]).read_text(encoding="utf-8")
            context = {
                "checkpointPending": {
                    "stacks": ["A"],
                    "before": before,
                    "after": after,
                },
                "taskDigest": task_digest(text),
                "inputDigests": {"A": "input"},
                "stepUnits": [{"name": "A"}],
                "consumedInputs": {
                    input_path: hashlib.sha256(b"fixed input\n").hexdigest()
                },
            }
            stack = {
                "observedSynced": True,
                "stackId": "stack-id",
                "stackStatus": "COMPLETE",
                "status": "SUCCESS",
            }
            backend = SimpleNamespace(
                root=target,
                phase="update",
                run_context=context,
                states={"A": stack},
                guard=lambda: None,
                save=lambda: None,
            )
            if scenario in {"rewrite", "same-tree"}:
                git(root, "commit", "--amend", "-qm", "rewritten base")
            if scenario != "same-tree":
                base_path = (
                    relative
                    if scenario in {"different-lines", "task-overlap", "conflict", "already-applied"}
                    else input_path
                    if scenario == "input-change"
                    else "upstream.txt"
                )
                base_value = (
                    observed if scenario == "already-applied"
                    else "old\n" + ("middle\n" * 8) + "upstream\n"
                    if scenario in {"different-lines", "task-overlap"} else "upstream\n"
                )
                (root / base_path).write_text(base_value, encoding="utf-8")
                git(root, "add", base_path)
                git(root, "commit", "-qm", "advance base")
            latest = git(root, "rev-parse", "HEAD").strip()
            if scenario in {"ack-interrupt", "ack-pending"}:
                backend.save = Mock(side_effect=[OSError("save interrupted"), None])
            with (
                patch.object(checkpoints, "validate"),
                patch.object(
                    checkpoints,
                    "validate_update_candidate",
                    side_effect=partial(_update_advance_during_validation, root, [])
                    if scenario == "race"
                    else _update_reject_validation
                    if scenario == "validation-fail"
                    else _update_candidate_validate,
                ),
            ):
                if scenario in {"conflict", "input-change", "validation-fail"}:
                    error = {
                        "conflict": "conflict",
                        "input-change": "input differs",
                        "validation-fail": "candidate validation failed",
                    }[scenario]
                    with pytest.raises(ValueError, match=error):
                        checkpoints.update_checkpoint(backend, ["A"])
                    assert (target / relative).read_text() == observed
                    assert git(root, "rev-parse", "HEAD").strip() == latest
                    continue
                if scenario == "interrupt":
                    with patch.object(
                        wt, "git", side_effect=partial(_update_interrupt_rebase, wt.git)
                    ):
                        with pytest.raises(RuntimeError, match="interrupted"):
                            checkpoints.update_checkpoint(backend, ["A"])
                    assert (target / relative).read_text() == observed
                    (root / "after-interruption.txt").write_text(
                        "base advanced\n", encoding="utf-8"
                    )
                    git(root, "add", "after-interruption.txt")
                    git(root, "commit", "-qm", "base after interruption")
                if scenario == "race":
                    with pytest.raises(
                        ValueError, match="changed during candidate validation"
                    ):
                        checkpoints.update_checkpoint(backend, ["A"])
                    assert (target / relative).read_text() == observed
                if scenario in {"ack-interrupt", "ack-pending"}:
                    with pytest.raises(OSError, match="save interrupted"):
                        checkpoints.update_checkpoint(backend, ["A"])
                    context["checkpointPending"] = {
                        "stacks": ["A"],
                        "before": before,
                        "after": after,
                    }
                    if scenario == "ack-pending":
                        context["pendingGeneration"] = {"ec2": True}
                        with pytest.raises(
                            ValueError, match="generation remains pending"
                        ):
                            checkpoints.update_checkpoint(backend, ["A"])
                        context.pop("pendingGeneration")
                result = checkpoints.update_checkpoint(backend, ["A"])
                assert result["A"]["commit"] == git(root, "rev-parse", "HEAD").strip()
                expected = observed.replace("end\n", "upstream\n") if scenario in {"different-lines", "task-overlap"} else observed
                if scenario == "delete":
                    assert not (root / relative).exists()
                else:
                    assert (root / relative).read_text() == expected
                assert checkpoints.update_checkpoint(backend, ["A"]) == result


def check_update_candidate_real_validation(tmp_path, monkeypatch):
    target = seed(tmp_path / "project", tmp_path / "run.json")
    task_path = target / "tasks/deploy.md"
    iac = "infra/cloudformation/templates/first.yaml"
    text = task_path.read_text().replace(
        "Infrastructure phase: `deploy`", "Infrastructure phase: `update`"
    )
    for heading in ("Modified files", "Allowed paths"):
        text = text.replace(
            "## " + heading + "\n", "## " + heading + "\n- `" + iac + "`\n"
        )
    task_path.write_text(text)
    template = target / iac
    template.write_text(
        template.read_text() + "\n# selected update\n", encoding="utf-8"
    )
    git(target, "add", iac)
    git(target, "commit", "-qm", "selected update IaC")
    model = target / f"model/dev/{ACCOUNT}/ec2.properties"
    document = model_format.parse(model.read_text(encoding="utf-8"))
    model.write_text(
        model_format.patch(
            document, {"observed.row.001-001.value": "`vpc-fixture-verified`"}
        ),
        encoding="utf-8",
    )
    with selected_task(target, "tasks/deploy.md"):
        assert sync_runtime.sync(target, True, "dev", ACCOUNT, services=["ec2"]) == 0
    task = checkpoints.tasks.read_task_snapshot(target, "tasks/deploy.md", live=True)
    head = wt.output(target, "rev-parse", "HEAD")
    wt.git(target, "add", "model", "docs/designs")
    tree = wt.output(target, "write-tree")
    assert tree != wt.output(target, "rev-parse", "HEAD^{tree}")
    context = {
        "taskDigest": task.task_digest,
        "inputDigests": {"A": "input"},
        "stepUnits": [{"name": "A"}],
    }
    checkpoints.validate_update_candidate(target, tree, head, task, context)
    _, _, state_path, state = wt.load(target, "deploy")
    state["deployCheckpoints"] = {
        "A": {
            "taskBase": state["start"],
            "taskHead": head,
            "taskDigest": task.task_digest,
            "unit": {"name": "A"},
            "inputDigest": "input",
        }
    }
    state["validation_base"] = head
    wt.save(state_path, state)
    checkpoints.validate_update_candidate(target, tree, head, task, context)
    context["taskFile"] = task.name
    context["checkpointPending"] = {
        "after": checkpoints.contracts.validation_snapshot(target),
        "stacks": ["A"],
    }
    backend = SimpleNamespace(
        root=target,
        environment="dev",
        directory=ACCOUNT,
        run_context=context,
        states={"A": {"observedServices": ["ec2"]}},
    )
    with selected_task(target, task.name):
        checkpoints.validate(
            backend,
            task_paths=checkpoints.update_task_iac_paths(target, state, task, context),
        )
    for key in ("taskBase", "taskHead", "taskDigest", "inputDigest", "unit"):
        original = state["deployCheckpoints"]["A"][key]
        state["deployCheckpoints"]["A"][key] = "tampered"
        with pytest.raises(ValueError, match="evidence"):
            checkpoints.update_task_iac_paths(target, state, task, context)
        state["deployCheckpoints"]["A"][key] = original


def check_update_repeated_checkpoint_validation(tmp_path):
    target = seed(tmp_path / "project", tmp_path / "run.json")
    _, _, state_path, state = wt.load(target, "deploy")
    primary = Path(state["primary"])
    iac = "infra/cloudformation/templates/first.yaml"
    task_path = target / state["task_file"]
    text = task_path.read_text().replace(
        "Infrastructure phase: `deploy`", "Infrastructure phase: `update`"
    )
    for heading in ("Modified files", "Allowed paths"):
        text = text.replace(
            "## " + heading + "\n", "## " + heading + "\n- `" + iac + "`\n"
        )
    task_path.write_text(text)
    template = target / iac
    template.write_text(
        template.read_text() + "\n# selected update\n", encoding="utf-8"
    )
    git(target, "add", iac)
    git(target, "commit", "-qm", "selected update IaC")
    state["tip"] = wt.output(target, "rev-parse", "HEAD")
    wt.save(state_path, state)
    git(primary, "merge", "--ff-only", state["branch"])
    git(primary, "commit", "--amend", "-qm", "rewritten base")
    task = checkpoints.tasks.read_task_snapshot(target, state["task_file"], live=True)
    context = {
        "taskFile": task.name,
        "taskDigest": task.task_digest,
        "inputDigests": {"A": "input"},
        "stepUnits": [{"name": "A"}],
        "consumedInputs": {},
    }
    stack = {
        "observedSynced": True,
        "observedServices": ["ec2"],
        "stackId": "stack-id",
        "stackStatus": "COMPLETE",
        "status": "SUCCESS",
    }
    backend = SimpleNamespace(
        root=target,
        phase="update",
        environment="dev",
        directory=ACCOUNT,
        run_context=context,
        states={"A": stack},
        guard=lambda: None,
        save=lambda: None,
    )
    model = target / f"model/dev/{ACCOUNT}/ec2.properties"
    for count in (1, 2, 3):
        before = checkpoints.contracts.validation_snapshot(target)
        document = model_format.parse(model.read_text(encoding="utf-8"))
        model.write_text(
            model_format.patch(
                document, {"observed.row.001-001.value": f"`vpc-checkpoint-{count}`"}
            ),
            encoding="utf-8",
        )
        with selected_task(target, task.name):
            assert (
                sync_runtime.sync(target, True, "dev", ACCOUNT, services=["ec2"]) == 0
            )
            context["checkpointPending"] = {
                "stacks": ["A"],
                "before": before,
                "after": checkpoints.contracts.validation_snapshot(target),
            }
            if count == 3:
                (primary / "upstream.txt").write_text("latest\n", encoding="utf-8")
                git(primary, "add", "upstream.txt")
                git(primary, "commit", "-qm", "advance base")
            receipt = checkpoints.update_checkpoint(backend, ["A"])["A"]
            assert checkpoints.update_checkpoint(backend, ["A"])["A"] == receipt
        assert (
            f"`vpc-checkpoint-{count}`"
            in (primary / model.relative_to(target)).read_text()
        )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
