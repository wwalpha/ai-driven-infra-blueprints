"""Pure classification/authorization checks for durable observed publication plans."""

import copy
import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import base64
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from deploy import observed
from deploy import observed_resume as M
from deploy import run_context as controller
from support.cloudformation_deploy_fixtures import Fake, starts
from support.pytest_cli import run
from task_contract_core import selected_task
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize(
    "current,mixed,expected",
    [
        ({"a": "old", "b": "old"}, False, "PREPARED"),
        ({"a": "new", "b": "new"}, False, "MODEL_PUBLISHED"),
        ({"a": "new", "b": "old"}, True, "PARTIAL"),
        ({"a": "new", "b": "old"}, False, None),
        ({"a": "third", "b": "old"}, True, None),
        ({"a": "new"}, True, None),
        ({"a": "new", "b": "new", "dependency": None}, True, None),
        ({"a": "new", "b": None}, True, None),
    ],
)
def check_classification(current, mixed, expected):
    before, after = {"a": "old", "b": "old"}, {"a": "new", "b": "new"}
    if expected:
        assert M.classify(current, before, after, mixed=mixed) == expected
    else:
        with pytest.raises(Blocked, match="cannot explain"):
            M.classify(current, before, after, mixed=mixed)
    assert (
        M.classify(before, before, before) == "MODEL_PUBLISHED"
    )  # An exact no-op needs only generation.


@pytest.mark.parametrize(
    "field", ["StackId", "ChangeSetId", "changeDigest", "clientToken", "status"]
)
def check_execution_identity(field):
    state = {
        "status": "SUCCESS",
        "stackId": "stack",
        "stackStatus": "UPDATE_COMPLETE",
        "changeSetId": "change",
        "changeDigest": "digest",
        "clientToken": "token",
        "executionEvidence": {
            "StackId": "stack",
            "ChangeSetId": "change",
            "changeDigest": "digest",
            "clientToken": "token",
        },
    }
    saved = M.evidence({"A": state}, ["A"])
    if field == "status":
        state[field] = "RUNNING"
    else:
        state["executionEvidence"][field] = "other"
    with pytest.raises(Blocked):
        M.evidence({"A": state}, ["A"])
    assert saved["A"]["executionEvidence"]["StackId"] == "stack"


@pytest.mark.parametrize(
    "patches",
    [
        {"stackStatus": None},
        {"stackStatus": "UPDATE_IN_PROGRESS"},
        {"stackStatus": "UPDATE_ROLLBACK_COMPLETE"},
        {"stackId": None},
        {"stackId": ""},
        {"stackId": "  "},
        {"stackId": 123},
    ],
)
def check_incomplete_success_evidence_rejected(patches):
    state = {"status": "SUCCESS", "stackId": "stack", "stackStatus": "UPDATE_COMPLETE"}
    state.update(patches)
    with pytest.raises(Blocked, match="complete Stack success evidence"):
        M.evidence({"A": state}, ["A"])


@pytest.mark.parametrize(
    "problem",
    ["none", "foreign", "original", "third", "missing", "incomplete", "receipt"],
)
def check_journal_ownership(problem):
    plan = {
        "beforeManifest": {"a": "old", "b": "old"},
        "afterManifest": {"a": "new", "b": "new"},
        "originals": {"a": "raw-a", "b": "raw-b"},
    }
    record, current = {"originals": dict(plan["originals"])}, {"a": "new", "b": "old"}
    if problem == "foreign":
        record["originals"]["other"] = "raw"
    if problem == "original":
        record["originals"]["a"] = "foreign"
    if problem == "third":
        current["a"] = "external"
    if problem == "missing":
        current.pop("b")
    if problem == "incomplete":
        record["originals"].pop("a")
    if problem == "receipt":
        record["importReceipt"] = {}
    if problem == "none":
        M.verify_journal(plan, record, current)
    else:
        with pytest.raises(Blocked):
            M.verify_journal(plan, record, current)


@pytest.fixture
def proposal(tmp_path):
    source = tmp_path / "model/dev/team/service.properties"
    source.parent.mkdir(parents=True)
    old = "# model-format: 2\ndesired.row.001-001.value=`desired`\nobserved.row.001-001.value=`old`\n"
    new = old.replace("value=`old`", "value=`new`")
    source.write_text(old)
    task = tmp_path / "tasks/deploy.md"
    task.parent.mkdir()
    relative = source.relative_to(tmp_path).as_posix()
    listed = "- `tasks/deploy.md`\n- `" + relative + "`\n"
    task.write_text(
        "## Task contract\n- Task status: `running`\n## Modified files\n"
        + listed
        + "## Allowed paths\n"
        + listed
    )
    before, after = (
        M.manifest({relative: old.encode()}),
        M.manifest({relative: new.encode()}),
    )
    session = {
        "inputRevision": 0,
        "modelInputs": before,
        "states": {
            "A": {
                "status": "SUCCESS",
                "stackId": "stack",
                "stackStatus": "UPDATE_COMPLETE",
            }
        },
        "pendingObserved": {
            "identity": {"target": "pinned"},
            "evidence": M.evidence(
                {
                    "A": {
                        "status": "SUCCESS",
                        "stackId": "stack",
                        "stackStatus": "UPDATE_COMPLETE",
                    }
                },
                ["A"],
            ),
            "beforeManifest": before,
            "afterManifest": after,
            "outputs": {relative: new},
            "originals": {relative: base64.b64encode(old.encode()).decode()},
            "directories": ["model/dev/team/service"],
            "inventory": [],
            "stage": "PREPARED",
        },
    }
    with selected_task(tmp_path, "tasks/deploy.md"):
        yield tmp_path, session, source, old, new


@pytest.mark.parametrize(
    "problem",
    [
        "none",
        "identity-extra",
        "task",
        "evidence",
        "manifest",
        "candidate",
        "desired",
        "bytes",
        "file-set",
        "allowed",
        "stage",
        "original-set",
        "manifest-set",
    ],
)
def check_plan_validation(proposal, problem):
    root, session, source, old, new = proposal
    plan = session["pendingObserved"]
    relative = source.relative_to(root).as_posix()
    if problem == "identity-extra":
        plan["identity"]["unexpected"] = True
    if problem == "task":
        plan["identity"] = {"target": "changed"}
    if problem == "evidence":
        session["states"]["A"]["stackId"] = "other"
    if problem == "manifest":
        session["modelInputs"] = {}
    if problem == "candidate":
        plan["outputs"][relative] = new.replace("`new`", "`other`")
    if problem == "desired":
        plan["outputs"][relative] = new.replace("`desired`", "`other`")
    if problem == "bytes":
        plan["outputs"][relative] = "# unrelated\n" + new
    if problem == "file-set":
        source.with_suffix("").mkdir()
        (source.with_suffix("") / "extra.properties").write_text(old)
    if problem == "allowed":
        (root / "tasks/deploy.md").write_text("## Modified files\n## Allowed paths\n")
    if problem == "stage":
        plan["stage"] = "UNKNOWN"
    if problem == "original-set":
        plan["originals"]["project.json"] = base64.b64encode(b"foreign").decode()
    if problem == "manifest-set":
        plan["afterManifest"]["extra"] = None
    with patch.object(M, "_identity", return_value={"target": "pinned"}):
        if problem == "none":
            assert M.validate_plan(root, session, {}, "dev", "team") is plan
        else:
            with pytest.raises((ValueError, Blocked)):
                M.validate_plan(root, session, {}, "dev", "team")


def check_intent_save_failure(proposal):
    root, session, source, old, new = proposal
    session.pop("pendingObserved")
    backend = SimpleNamespace(
        root=root,
        run_context=session,
        environment="dev",
        directory="team",
        target={},
        save=lambda: (_ for _ in ()).throw(OSError("intent write failed")),
    )
    with (
        patch.object(M, "_identity", return_value={}),
        patch.object(M, "source_snapshot", return_value={source: old.encode()}),
        patch.object(M, "generated_plan", return_value={}),
    ):
        with pytest.raises(OSError, match="intent write failed"):
            M.prepare(backend, [{"name": "A"}], {source: new}, ["service"], set())
    assert source.read_text() == old


def check_new_plan_rejects_missing_stack_status(proposal):
    root, session, source, old, new = proposal
    session.pop("pendingObserved")
    session["states"]["A"].pop("stackStatus")
    backend = SimpleNamespace(
        root=root,
        run_context=session,
        environment="dev",
        directory="team",
        target={},
        save=Mock(),
    )
    with (
        patch.object(M, "_identity", return_value={}),
        patch.object(M, "source_snapshot", return_value={source: old.encode()}),
        patch.object(M, "generated_plan", return_value={}),
        pytest.raises(Blocked, match="complete Stack success evidence"),
    ):
        M.prepare(backend, [{"name": "A"}], {source: new}, ["service"], set())
    backend.save.assert_not_called()
    assert "pendingObserved" not in session and source.read_text() == old


def check_direct_writer_keeps_noop_source_snapshot(tmp_path):
    source = tmp_path / "model/dev/team/changed.properties"
    noop = source.with_name("unchanged.properties")
    backend = SimpleNamespace(root=tmp_path, environment="dev", directory="team")
    states = {"A": {"status": "SUCCESS"}}
    sync = SimpleNamespace(sync=lambda *args, **kwargs: 0)
    with (
        patch.object(
            observed,
            "collect_successful",
            return_value=({source: "candidate"}, ["changed", "unchanged"], sync),
        ),
        patch.object(
            observed, "input_snapshot", side_effect=lambda path: {path: b"original"}
        ) as snapshot,
        patch.object(observed, "publish_observed") as publish,
    ):
        observed.sync_successful(backend, [{"name": "A"}], states)
    assert {call.args[0] for call in snapshot.call_args_list} == {source, noop}
    assert publish.call_args.args[2] == {source: b"original", noop: b"original"}
    assert states["A"]["observedSynced"]


def check_exact_task_bytes_bound(proposal):
    root, session, _, _, _ = proposal
    task = root / "tasks/deploy.md"
    task.write_text(
        task.read_text().replace(
            "## Task contract",
            "## Task contract\n- Authorized delete/replacement: `none`",
        )
    )
    session.update(
        repository=str(root),
        taskFile="tasks/deploy.md",
        taskDigest=M.task_digest(task.read_text()),
        inputDigest="inputs",
        consumedInputs={},
    )
    original = M._identity(root, session, {}, "dev", "team")
    task.write_text(
        task.read_text().replace(
            "Authorized delete/replacement: `none`",
            "Authorized delete/replacement: `all`",
        )
    )
    changed = M._identity(root, session, {}, "dev", "team")
    assert original["taskDigest"] == changed["taskDigest"]
    assert original["taskBytes"] != changed["taskBytes"]


def _callback_check_pending_plan_drained_peer_barrier_sync(
    calls, session, /, backend, units, states
):
    pending = session.get("pendingObserved")
    names = list(pending["evidence"]) if pending else [u["name"] for u in units]
    calls.append(names)
    for name in names:
        states[name]["observedSynced"] = True


def _callback_check_pending_plan_drained_peer_barrier_save(saves, session, /):
    saves.append(
        [
            name
            for name, state in session["states"].items()
            if state.get("observedSynced")
        ]
    )


def check_pending_plan_drained_peer_barrier():
    units = [{"name": name, "deployOrder": 10} for name in ("A", "B")]
    session = {
        "states": {name: {"status": "SUCCESS"} for name in ("A", "B")},
        "pendingObserved": {"evidence": {"A": {}}},
        "metrics": {"observedSyncSeconds": 0},
    }
    calls, saves = [], []
    sync = _bind_framework_callback(
        _callback_check_pending_plan_drained_peer_barrier_sync, calls, session
    )
    save = _bind_framework_callback(
        _callback_check_pending_plan_drained_peer_barrier_save, saves, session
    )
    with (
        patch.object(controller, "sync_successful", sync),
        patch.object(controller, "run_group", return_value="COMPLETE"),
    ):
        assert (
            controller.run_deploy(units, 2, session, SimpleNamespace(), save)
            == "COMPLETE"
        )
    assert calls == [["A"], ["B"]] and saves == [["A"], ["A", "B"]]


@pytest.mark.parametrize("guard", [False, True])
@pytest.mark.parametrize("pending_stage", [None, "MODEL_PUBLISHED"])
def check_original_failure_retained(guard, pending_stage):
    units = [{"name": "A", "deployOrder": 10}]
    session = {
        "states": {"A": {"status": "SUCCESS"}},
        "metrics": {"observedSyncSeconds": 0},
        "observedError": "original design I/O failure",
        "observedFailures": [
            {"stage": "MODEL_PUBLISHED", "cause": "original design I/O failure"}
        ],
        "pendingGeneration": {"view": {"generated": {"outputs": None}}},
    }
    if pending_stage:
        session["pendingObserved"] = {"stage": pending_stage}
    backend = SimpleNamespace()
    if guard:
        backend.guard = Mock(side_effect=Blocked("later guard refusal"))
    with patch.object(
        controller, "sync_successful", side_effect=Blocked("later guard refusal")
    ):
        assert (
            controller.run_deploy(units, 1, session, backend, lambda: None) == "STOPPED"
        )
    assert session["observedError"] == "original design I/O failure"
    assert session["observedRecoveryError"] == "later guard refusal"
    assert session["observedFailures"][0]["stage"] == "MODEL_PUBLISHED"
    assert session["observedFailures"][1] == {
        "stage": pending_stage or "PLANNING",
        "cause": "later guard refusal",
    }
    assert "generationError" not in session
    assert not session["states"]["A"].get("observedSynced")
    assert backend.sync_failed


@pytest.mark.parametrize(
    "state",
    [
        "before",
        "after",
        "append",
        "value",
        "empty",
        "missing",
        "add",
        "partial",
        "no-proof",
        "candidate",
        "json-delete",
    ],
)
def check_generated_classification(tmp_path, state):
    view = "docs/designs/dev/team/service.md"
    artifact = "docs/designs/dev/team/service/policy.json"
    paths = [view, artifact]
    before, after = {view: b"old\n", artifact: None}, {view: "new\n", artifact: "{}\n"}
    generated = {
        "groups": {view: paths},
        "originals": {
            p: None if raw is None else base64.b64encode(raw).decode()
            for p, raw in before.items()
        },
        "outputs": after,
        "stage": "CANDIDATE",
    }
    plan = {"generated": generated}
    for p, raw in (
        before if state == "before" else {p: s.encode() for p, s in after.items()}
    ).items():
        file = tmp_path / p
        file.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            file.write_bytes(raw)
    task = tmp_path / "tasks/deploy.md"
    task.parent.mkdir()
    listed = "".join("- `" + p + "`\n" for p in ["tasks/deploy.md", *paths])
    task.write_text(
        "## Task contract\n- Task status: `running`\n## Modified files\n"
        + listed
        + "## Allowed paths\n"
        + listed
    )
    if state == "append":
        (tmp_path / view).write_bytes(b"new\nexternal\n")
    if state == "value":
        (tmp_path / artifact).write_bytes(b'{"external":true}')
    if state == "empty":
        (tmp_path / artifact).write_bytes(b"")
    if state == "json-delete":
        (tmp_path / artifact).unlink()
    if state == "missing":
        (tmp_path / view).unlink()
    if state == "add":
        (tmp_path / artifact).with_name("extra.json").write_bytes(b"{}")
    if state == "partial":
        (tmp_path / view).write_bytes(before[view])
    if state == "no-proof":
        plan.clear()
    if state == "candidate":
        generated["outputs"][artifact] = '{"other":true}'
    retained = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with selected_task(tmp_path, "tasks/deploy.md"):
        if state in {"before", "after"}:
            current = M.check_generated(tmp_path, plan)
            assert current == M.generated_manifests(tmp_path, plan)[state == "after"]
        else:
            with pytest.raises(Blocked):
                M.check_generated(tmp_path, plan)
    assert {p: p.read_bytes() for p in retained} == retained


@pytest.mark.parametrize(
    "problem", ["none", "third", "foreign", "incomplete", "empty-original", "receipt"]
)
def check_generated_journal(tmp_path, problem):
    view, artifact = (
        "docs/designs/dev/team/service.md",
        "docs/designs/dev/team/service/policy.json",
    )
    files = {view: b"old", artifact: None}
    generated = {
        "groups": {view: list(files)},
        "originals": {
            p: None if raw is None else base64.b64encode(raw).decode()
            for p, raw in files.items()
        },
        "outputs": {view: "new", artifact: "{}"},
        "stage": "CANDIDATE",
    }
    plan = {"generated": generated}
    (tmp_path / view).parent.mkdir(parents=True)
    (tmp_path / view).write_bytes(b"new")
    record = {"originals": dict(generated["originals"])}
    if problem == "third":
        (tmp_path / view).write_bytes(b"external")
    if problem == "foreign":
        record["originals"]["other"] = None
    if problem == "incomplete":
        record["originals"].pop(view)
    if problem == "empty-original":
        record["originals"][artifact] = ""
    if problem == "receipt":
        record["importReceipt"] = {}
    task = tmp_path / "tasks/deploy.md"
    task.parent.mkdir()
    listed = "".join("- `" + p + "`\n" for p in ["tasks/deploy.md", *files])
    task.write_text(
        "## Task contract\n- Task status: `running`\n## Modified files\n"
        + listed
        + "## Allowed paths\n"
        + listed
    )
    with selected_task(tmp_path, "tasks/deploy.md"):
        if problem == "none":
            M.verify_generated_journal(tmp_path, plan, record)
        else:
            with pytest.raises(Blocked):
                M.verify_generated_journal(tmp_path, plan, record)


def check_generated_plan_snapshot(proposal):
    root, _, _, _, _ = proposal
    view = root / "docs/designs/dev/team/service.md"
    view.parent.mkdir(parents=True)
    view.write_bytes(b"")
    artifact = view.with_suffix("") / "policy.json"
    artifact.parent.mkdir()
    extra = artifact.with_name("extra.json")
    extra.write_bytes(b"{}\n")
    plan = M.generated_plan(root, {view, artifact})
    assert plan["outputs"] is None and plan["stage"] == "PREPARED"
    assert plan["originals"] == {
        view.relative_to(root).as_posix(): "",
        artifact.relative_to(root).as_posix(): None,
        extra.relative_to(root).as_posix(): base64.b64encode(b"{}\n").decode(),
    }
    assert plan["groups"] == {
        view.relative_to(root).as_posix(): sorted(plan["originals"])
    }


@pytest.fixture
def owned_proposal(proposal):
    root, session, source, old, new = proposal
    task = root / "tasks/deploy.md"
    view = root / "docs/designs/dev/team/service.md"
    view.parent.mkdir(parents=True)
    view.write_text("", encoding="utf-8")
    relative = view.relative_to(root).as_posix()
    text = task.read_text(encoding="utf-8").replace(
        "## Task contract",
        "## Task contract\n- Task type: `infrastructure`\n- Infrastructure phase: `deploy`\n"
        "- AWS API execution: `allowed`\n- Deploy/apply: `allowed`\n"
        "- Target environment: `dev`\n- Target AWS account: `123456789012`\n- Deployment scope: `A`",
    )
    text = text.replace("## Modified files", "## Modified files\n- `" + relative + "`")
    text = text.replace("## Allowed paths", "## Allowed paths\n- `" + relative + "`")
    task.write_text(text, encoding="utf-8")
    session.update(
        repository=str(root),
        taskFile="tasks/deploy.md",
        taskDigest=M.task_digest(text),
        inputDigest="inputs",
        consumedInputs={},
        inputDigests={"A": "unit"},
    )
    state = session["states"]["A"]
    state.update(
        stackStatus="CREATE_COMPLETE",
        stackId="stack",
        changeSetId="change",
        changeDigest="digest",
        approvedChangeDigest="digest",
        clientToken="token",
        executionEvidence={
            "StackId": "stack",
            "ChangeSetId": "change",
            "changeDigest": "digest",
            "clientToken": "token",
            "inputDigest": "unit",
        },
    )
    plan = session["pendingObserved"]
    plan["evidence"] = M.evidence(session["states"], ["A"])
    plan["identity"] = M._identity(root, session, {}, "dev", "team")
    plan["generated"] = {
        "groups": {relative: [relative]},
        "originals": {relative: ""},
        "outputs": None,
        "stage": "PREPARED",
    }
    return root, session, source, old, new


@pytest.mark.parametrize(
    "problem",
    [
        "none",
        "task-body",
        "task-merged",
        "worktree-moved",
        "worktree-deleted",
        "tampered-session",
        "foreign-journal",
        "external-model",
    ],
)
def check_owned_resume_boundaries(owned_proposal, problem):
    root, session, source, old, new = owned_proposal
    saved_identity = copy.deepcopy(session["pendingObserved"]["identity"])
    restored = copy.deepcopy(session)
    if problem == "tampered-session":
        restored["pendingObserved"]["outputs"] = {}
    if problem == "tampered-session":
        with pytest.raises(Blocked, match="file sets differ"):
            M.validate_plan(root, restored, {}, "dev", "team")
        return
    task = root / "tasks/deploy.md"
    if problem == "task-body":
        task.write_text(
            task.read_text(encoding="utf-8") + "\nchanged authority\n", encoding="utf-8"
        )
    if problem == "task-merged":
        task.write_text(
            task.read_text(encoding="utf-8").replace("`running`", "`completed`"),
            encoding="utf-8",
        )
        with pytest.raises(Blocked, match="completed task"):
            controller.active_scope(root, ["A"], "dev", "123456789012")
    if problem == "worktree-moved":
        moved = root.with_name(root.name + "-moved")
        root.rename(moved)
        try:
            with (
                selected_task(moved, "tasks/deploy.md"),
                pytest.raises(Blocked, match="repository changed"),
            ):
                M.validate_plan(moved, restored, {}, "dev", "team")
        finally:
            moved.rename(root)
        return
    if problem == "worktree-deleted":
        removed = root.with_name(root.name + "-removed")
        root.rename(removed)
        try:
            with pytest.raises((Blocked, ValueError, OSError)):
                M.validate_plan(root, restored, {}, "dev", "team")
        finally:
            removed.rename(root)
        return
    if problem in {"task-body", "task-merged", "worktree-deleted"}:
        with pytest.raises((Blocked, ValueError, OSError)):
            M.validate_plan(root, restored, {}, "dev", "team")
        return
    if problem == "external-model":
        source.write_text(old + "# external edit\n", encoding="utf-8")
    before = source.read_bytes()
    with patch.object(M, "source_snapshot", return_value={source: before}):
        if problem == "external-model":
            with pytest.raises(Blocked, match="cannot explain"):
                M.reconcile(root, restored, {}, "dev", "team")
        elif problem == "foreign-journal":
            record = {"originals": {"model/dev/team/foreign.properties": None}}
            with pytest.raises(Blocked, match="not owned"):
                M._callback_reconcile_recovery(
                    "team", "dev", root, restored, {}, record
                )
        else:
            assert M.reconcile(root, restored, {}, "dev", "team") == "PREPARED"
    assert source.read_bytes() == before
    assert restored["pendingObserved"]["identity"] == saved_identity


@pytest.mark.parametrize("stage", ["PREPARED", "MODEL_PUBLISHED"])
def check_owned_interrupted_stages(owned_proposal, stage):
    root, session, source, old, new = owned_proposal
    source.write_text(old if stage == "PREPARED" else new, encoding="utf-8")
    # On disk the intent may still say PREPARED after the Model transaction committed.
    with patch.object(M, "source_snapshot", return_value={source: source.read_bytes()}):
        assert M.reconcile(root, session, {}, "dev", "team") == stage
    assert session["pendingObserved"]["stage"] == stage
    assert (
        session["modelInputs"]
        == session["pendingObserved"][
            "beforeManifest" if stage == "PREPARED" else "afterManifest"
        ]
    )


@pytest.mark.parametrize("stage", ["PREPARED", "MODEL_PUBLISHED"])
def check_finish_guard_precedes_publication(owned_proposal, stage):
    root, session, source, old, new = owned_proposal
    source.write_text(old if stage == "PREPARED" else new, encoding="utf-8")
    backend = SimpleNamespace(
        root=root,
        run_context=session,
        target={},
        environment="dev",
        directory="team",
        save=lambda: None,
        guard=lambda: (_ for _ in ()).throw(Blocked("live guard refused")),
    )
    before = source.read_bytes()
    with (
        patch.object(M, "source_snapshot", return_value={source: before}),
        patch.object(
            observed,
            "collect_successful",
            return_value=({source: new}, ["service"], None),
        ),
        patch("model.adapters.observed.publish_observed") as publish,
        patch("sync_runtime.prepare_generation") as generate,
    ):
        with pytest.raises(Blocked, match="live guard refused"):
            M.finish(backend, [{"name": "A"}])
    publish.assert_not_called()
    generate.assert_not_called()
    assert source.read_bytes() == before


def read_proposal_source(source, *args):
    return {source: source.read_bytes()}


@pytest.mark.parametrize("stage", ["PREPARED", "MODEL_PUBLISHED"])
def check_finish_io_failure(owned_proposal, stage):
    root, session, source, old, new = owned_proposal
    plan = session["pendingObserved"]
    plan.update(services=["service"], stage=stage)
    source.write_text(old if stage == "PREPARED" else new, encoding="utf-8")
    session["modelInputs"] = plan[
        "beforeManifest" if stage == "PREPARED" else "afterManifest"
    ]
    before, proof = (
        copy.deepcopy(plan),
        copy.deepcopy(session["states"]["A"]["executionEvidence"]),
    )
    assert proof["clientToken"] and proof["inputDigest"] == session["inputDigests"]["A"]
    backend = SimpleNamespace(
        root=root,
        run_context=session,
        target={},
        environment="dev",
        directory="team",
        save=lambda: None,
        guard=lambda: None,
    )
    with (
        patch.object(
            M,
            "source_snapshot",
            side_effect=_bind_framework_callback(read_proposal_source, source),
        ),
        patch.object(
            observed,
            "collect_successful",
            return_value=({source: new}, ["service"], None),
        ),
        patch(
            "model.adapters.observed.publish_observed", side_effect=OSError("model I/O")
        ) as publish,
        patch("sync_runtime.prepare_generation") as generate,
    ):
        if stage == "PREPARED":
            with pytest.raises(OSError, match="model I/O"):
                M.finish(backend, [{"name": "A"}])
            publish.assert_called_once()
            assert session["pendingObserved"] == before
        else:
            assert M.finish(backend, [{"name": "A"}]) == {source: new}
            publish.assert_not_called()
            assert "pendingObserved" not in session
            assert session["states"]["A"]["observedSynced"]
            assert session["pendingGeneration"]
        generate.assert_not_called()
    assert session["states"]["A"]["executionEvidence"] == proof
    assert source.read_text() == (old if stage == "PREPARED" else new)


@pytest.mark.parametrize("committed", ["model-committed", "design-committed"])
def check_finish_transfers_v16_candidates(owned_proposal, committed):
    root, session, source, _, new = owned_proposal
    source.write_text(new, encoding="utf-8")
    plan = session["pendingObserved"]
    plan["services"] = ["service"]
    view = root / next(iter(plan["generated"]["originals"]))
    if committed == "design-committed":
        view.write_text("published design\n", encoding="utf-8")
        plan["generated"].update(
            outputs={view.relative_to(root).as_posix(): "published design\n"},
            stage="CANDIDATE",
        )
    generated = copy.deepcopy(plan["generated"])
    saved = []
    backend = SimpleNamespace(
        root=root,
        run_context=session,
        target={},
        environment="dev",
        directory="team",
        save=lambda: saved.append(copy.deepcopy(session)),
        guard=lambda: None,
    )
    with (
        patch.object(
            M,
            "source_snapshot",
            side_effect=_bind_framework_callback(read_proposal_source, source),
        ),
        patch.object(
            observed,
            "collect_successful",
            return_value=({source: new}, ["service"], None),
        ),
        patch("model.adapters.observed.publish_observed") as publish,
        patch("sync_runtime.prepare_generation") as prepare,
    ):
        assert M.finish(backend, [{"name": "A"}]) == {source: new}
    publish.assert_not_called()
    prepare.assert_not_called()
    assert len(saved) == 1 and "pendingObserved" not in saved[0]
    assert saved[0]["states"]["A"]["observedSynced"]
    assert (
        saved[0]["pendingGeneration"][view.relative_to(root).as_posix()]["generated"]
        == generated
    )


def failing_session_sync(backend, units, states):
    raise OSError("design publication failed")


@pytest.mark.parametrize("pending", [False, True])
def check_run_context_owns_observed_publication(proposal, pending):
    root, context, source, _, new = proposal
    if not pending:
        context.pop("pendingObserved")
    backend = SimpleNamespace(root=root, run_context=context)
    units = [{"name": "A"}]
    with (
        patch.object(
            observed,
            "collect_successful",
            return_value=({source: new}, ["service"], None),
        ) as collect,
        patch.object(M, "prepare") as prepare,
        patch.object(M, "finish", return_value={source: new}) as finish,
        patch.object(observed, "publish_observed") as direct_publish,
    ):
        assert observed.sync_successful(backend, units, context["states"]) == {
            source: new
        }
    finish.assert_called_once_with(backend, units)
    direct_publish.assert_not_called()
    assert collect.call_count == prepare.call_count == int(not pending)


def check_session_sync_failure_drains_and_resumes():
    units = [
        {
            "name": name,
            "deployOrder": order,
            "template": "app.yaml",
            "parameters": name + ".json",
        }
        for name, order in [("A", 10), ("B", 10), ("D", 10), ("C", 20)]
    ]
    session = {
        "states": {
            "A": {"status": "SUCCESS", "executionEvidence": {"clientToken": "a"}},
            "B": {"status": "RUNNING", "executionEvidence": {"clientToken": "b"}},
            "D": {"status": "SUCCESS", "observedSynced": True},
            "C": {"status": "NOT_STARTED"},
        },
        "pendingObserved": {"stage": "MODEL_PUBLISHED", "evidence": {"A": {}}},
        "metrics": {"observedSyncSeconds": 0},
    }
    backend = Fake({"B": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]})
    backend.running.add("B")
    proof = {
        name: copy.deepcopy(session["states"][name]["executionEvidence"])
        for name in ("A", "B")
    }
    with patch.object(controller, "sync_successful", side_effect=failing_session_sync):
        assert (
            controller.run_deploy(
                units, 2, session, backend, lambda: None, sleep=lambda _: None
            )
            == "STOPPED"
        )
    assert all(
        session["states"][name]["status"] == "SUCCESS"
        and not session["states"][name].get("observedSynced")
        for name in proof
    )
    assert (
        session["states"]["C"]["status"] == "NOT_STARTED"
        and not starts(backend)
        and not backend.running
    )
    assert session["observedFailures"] == [
        {"stage": "MODEL_PUBLISHED", "cause": "design publication failed"}
    ]
    assert session["pendingObserved"]["evidence"] == {"A": {}}
    calls = []
    sync = _bind_framework_callback(
        _callback_check_pending_plan_drained_peer_barrier_sync, calls, session
    )
    with patch.object(controller, "sync_successful", side_effect=sync):
        assert (
            controller.run_deploy(
                units, 2, session, backend, lambda: None, sleep=lambda _: None
            )
            == "COMPLETE"
        )
    assert calls == [["A"], ["B"], ["C"]] and starts(backend) == ["C"]
    assert {
        name: session["states"][name]["executionEvidence"] for name in proof
    } == proof
    assert (
        "pendingObserved" not in session
        and session["observedFailures"][0]["cause"] == "design publication failed"
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
