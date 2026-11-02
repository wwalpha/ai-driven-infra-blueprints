"""Preparation corrections preserve Task authority and local progress without AWS."""

import copy
import json
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import task_contract_core as tasks
import task_contract_runtime as runtime
from deploy import contract_correction as correction
from deploy import steps, worktree
from model.dependency_index import revision
from support.pytest_cli import run
from support.repository_fixtures import transition_contract
from utils import file_operations
from utils.json_format import fingerprint
from utils.local_evidence import write_sealed

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def read_state(root, name):
    path = root.parent / "state.json"
    return root.parent, None, path, json.loads(path.read_text(encoding="utf-8"))


def read_deploy_state(root, name, **kwargs):
    return "head", read_state(root, name)[3]


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv(tasks.SELECTOR, raising=False)
    primary = tmp_path / "primary"
    root = primary / "candidate"
    root.mkdir(parents=True)
    name = "tasks/deploy.md"
    source = root / "model/dev/team/logs.properties"
    source.parent.mkdir(parents=True)
    source.write_text("synthetic Model\n", encoding="utf-8")
    view = "docs/designs/dev/team/logs.md"
    template = root / "infra/cloudformation/templates/team/a.yaml"
    parameters = root / "infra/cloudformation/parameters/dev/team/a.json"
    for file in (template, parameters):
        file.parent.mkdir(parents=True)
        file.write_text("{}", encoding="utf-8")
    text = transition_contract(
        name,
        [source.relative_to(root).as_posix()],
        kind="infrastructure",
        scope="dev/team/logs",
    )
    text = text.replace(
        "- Target: test",
        "- Infrastructure phase: `deploy`\n- Target environment: `dev`\n- Target AWS account: `123456789012`\n- Target alias: `team`\n- Deployment scope: `A`\n- AWS API execution: `allowed`\n- AWS mutation: `allowed`\n- Deploy/apply: `allowed`\n- Authorized delete/replacement: `none`",
    )
    tasks.start(root, name, text)
    tasks.suspend(root, name, "omitted generated view")
    task = tasks.read_task_snapshot(root, name, live=True)
    candidate = task.text.replace(
        "## Modified files\n", f"## Modified files\n- `{view}`\n"
    ).replace("## Allowed paths\n", f"## Allowed paths\n- `{view}`\n")
    external = tmp_path / "candidate.md"
    external.write_text(candidate, encoding="utf-8")
    target = dict(
        awsAccountId="123456789012",
        awsRegion="ap-northeast-1",
        alias="team",
        iacEngine="cloudformation",
    )
    identity = dict(
        taskFile=name,
        taskDigest=tasks.task_digest(text),
        target=target,
        environment="dev",
        stacks=["A"],
        snapshot="head",
    )
    units = [dict(name="A", template="a.yaml", parameters="a.json")]
    manifest = {
        p.relative_to(root).as_posix(): file_operations.sha(p)
        for p in (template, parameters)
    }
    context = dict(
        repository=str(root),
        taskFile=name,
        taskDigest=identity["taskDigest"],
        target=target,
        environment="dev",
        directory="team",
        stepUnits=units,
        consumedInputs=manifest,
        inputDigests={"A": fingerprint(list(manifest.values()))},
        inputDigest=fingerprint([str(root), target, "dev", units]),
        inputIdentities={
            p.relative_to(root).as_posix(): revision(p) for p in (template, parameters)
        },
        modelInputs={source.relative_to(root).as_posix(): file_operations.sha(source)},
        states={
            "A": dict(
                status="SUCCESS",
                clientToken="original-token",
                endedRequest={"token": "original-token"},
                currentStack={"StackStatus": "UPDATE_COMPLETE"},
                observedSynced=False,
                changeSetId="original-change-set",
            )
        },
        snapshotValidation="FAIL",
    )
    state = dict(
        task_id="deploy",
        task_file=name,
        primary=str(primary),
        worktree=str(root),
        branch="codex/worktree/deploy",
        start="head",
        tip="head",
        merged=None,
        python_setup={"status": "ready"},
        deployIdentity=identity,
        deployContract=text,
    )
    path = primary / "state.json"
    correction.wt.save(path, state)
    progress_path = worktree.progress_path(root, create=True)
    write_sealed(root, progress_path, dict(identity=identity, runContext=context))
    monkeypatch.setattr(correction.ws, "load", read_state)
    monkeypatch.setattr(correction.ws, "deploy_task_state", read_deploy_state)
    monkeypatch.setattr(correction.wt, "lifecycle_lock", Mock(side_effect=nullcontext))
    monkeypatch.setattr(correction.wt, "output", Mock(return_value="head"))
    monkeypatch.setattr(
        correction.ws,
        "git",
        Mock(return_value=SimpleNamespace(stdout="index", returncode=0)),
    )
    monkeypatch.setattr(
        correction.contracts,
        "validation_snapshot",
        Mock(
            return_value={
                source.relative_to(root).as_posix(): file_operations.sha(source)
            }
        ),
    )
    monkeypatch.setattr(correction, "load_target_directory", Mock(return_value=target))
    monkeypatch.setattr(correction.inputs, "load_units", Mock(return_value=(1, units)))
    monkeypatch.setattr(
        correction,
        "load_model",
        Mock(
            return_value=SimpleNamespace(
                dependencies={source: source.read_bytes()}, values={}
            )
        ),
    )
    monkeypatch.setattr(correction, "owned_artifacts", Mock(return_value=[]))
    scope = Mock()
    monkeypatch.setattr(correction, "TaskValidation", scope)
    aws = Mock(side_effect=AssertionError("contract correction must not use AWS"))
    monkeypatch.setattr(correction.current_request, "settled", aws)
    return SimpleNamespace(
        root=root,
        name=name,
        path=path,
        state=state,
        task=task,
        source=external,
        candidate=candidate,
        progress_path=progress_path,
        context=context,
        target=target,
        units=units,
        scope=scope,
        aws=aws,
    )


def assert_preserved(case, task, progress, state):
    assert (case.root / case.name).read_bytes() == task
    assert case.progress_path.read_bytes() == progress
    assert case.path.read_bytes() == state
    case.aws.assert_not_called()


def check_correction_and_resume_preserve_execution(case, monkeypatch):
    before = copy.deepcopy(case.context)
    correction.correct(case.root, case.name, case.source)
    state = read_state(case.root, case.name)[3]
    assert state["deployIdentity"]["taskDigest"] == tasks.task_digest(case.candidate)
    assert state["deployContract"] == case.candidate
    assert "deployContractUpdate" not in state
    assert (
        tasks.status((case.root / case.name).read_text(encoding="utf-8")) == "suspend"
    )
    saved = worktree.read_progress(case.root, state)["runContext"]
    before.update(
        taskDigest=state["deployIdentity"]["taskDigest"], snapshotValidation="NOT_RUN"
    )
    assert saved == before
    monkeypatch.setattr(runtime, "TaskValidation", case.scope)
    runtime.resume(case.root, case.name)
    task = tasks.read_task_snapshot(case.root, case.name, live=True)
    assert task.status == "running" and "## Suspension reason" not in task.text
    backend = SimpleNamespace(
        root=case.root,
        target=case.target,
        units=case.units,
        phase="deploy",
        run_context={"inputIdentities": saved["inputIdentities"]},
        file_digest=Mock(side_effect=file_digest),
    )
    with tasks.selected_task(case.root, case.name):
        steps.restore(backend, task)
    assert backend.states == before["states"]
    assert backend.expected_digests == before["inputDigests"]
    case.aws.assert_not_called()


def file_digest(path, **kwargs):
    return file_operations.sha(path)


@pytest.mark.parametrize(
    "old,new",
    [
        ("`infrastructure`", "`design`"),
        ("- Goal: test", "- Goal: new work"),
        ("`dev`", "`stg`"),
        ("`123456789012`", "`999999999999`"),
        ("`team`", "`other`"),
        ("- Deployment scope: `A`", "- Deployment scope: `A`, `B`"),
        ("- AWS mutation: `allowed`", "- AWS mutation: `forbidden`"),
        ("- AWS API execution: `allowed`", "- AWS API execution: `forbidden`"),
        ("- Deploy/apply: `allowed`", "- Deploy/apply: `forbidden`"),
        (
            "- Authorized delete/replacement: `none`",
            "- Authorized delete/replacement: `all`",
        ),
        ("dev/team/logs", "dev/team/s3"),
        ("[R1] Test", "[R1] Different requirement"),
        ("`suspend`", "`running`"),
    ],
)
def check_authority_changes_refused(case, old, new):
    original = [p.read_bytes() for p in (case.task.path, case.progress_path, case.path)]
    case.source.write_text(case.candidate.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError):
        correction.correct(case.root, case.name, case.source)
    assert_preserved(case, *original)


@pytest.mark.parametrize(
    "added",
    [
        "infra/cloudformation/templates/team/a.yaml",
        "docs/designs/dev/team/s3.md",
        "docs/designs/dev/team/logs/guessed.json",
        "model/dev/team/logs/part-999.properties",
        "model/dev/team/*.properties",
        "tasks/other.md",
    ],
)
def check_unproven_paths_refused(case, added):
    original = [p.read_bytes() for p in (case.task.path, case.progress_path, case.path)]
    case.source.write_text(
        case.candidate.replace("docs/designs/dev/team/logs.md", added), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        correction.correct(case.root, case.name, case.source)
    assert_preserved(case, *original)


@pytest.mark.parametrize(
    "problem",
    [
        "missing-original",
        "bad-original",
        "wrong-progress",
        "missing-progress",
        "pendingObserved",
        "pendingGeneration",
        "generationError",
        "checkpointPending",
        "currentFailure",
        "deployCheckpointIntent",
        "stackCheckpointIntent",
        "deployIntegrationIntent",
        "iacRepair",
        "publication",
        "handoff",
        "request",
        "requestPending",
        "requestError",
        "createUnconfirmed",
        "running",
        "token",
        "region",
        "units",
        "input",
        "input-digest",
        "input-set",
        "model",
        "scope",
        "corrupt",
        "run-input-digest",
        "snapshot",
        "bound-account",
    ],
)
def check_inconsistent_states_refused(case, monkeypatch, problem):
    state = copy.deepcopy(case.state)
    progress = worktree.read_progress(case.root, state)
    context = progress["runContext"]
    if problem == "missing-original":
        state.pop("deployContract")
        monkeypatch.setattr(
            correction.ws,
            "git",
            Mock(
                return_value=SimpleNamespace(
                    stdout="not the old contract", returncode=1
                )
            ),
        )
    elif problem == "corrupt":
        state.pop("worktree")
    elif problem == "run-input-digest":
        context["inputDigest"] = "other"
    elif problem == "snapshot":
        state["deployIdentity"]["snapshot"] = "other"
        progress["identity"]["snapshot"] = "other"
    elif problem == "bound-account":
        target = dict(case.target, awsAccountId="999999999999")
        state["deployIdentity"]["target"] = progress["identity"]["target"] = context[
            "target"
        ] = target
    elif problem == "bad-original":
        state["deployContract"] += "new authority"
    elif problem == "wrong-progress":
        progress["identity"]["taskDigest"] = "other"
    elif problem in {
        "pendingObserved",
        "pendingGeneration",
        "generationError",
        "currentFailure",
    }:
        context[problem] = {"retained": True}
    elif problem == "checkpointPending":
        context[problem] = dict(stacks=["A"], before={}, after={})
    elif problem in {
        "deployCheckpointIntent",
        "stackCheckpointIntent",
        "deployIntegrationIntent",
        "iacRepair",
    }:
        state[problem] = {"retained": True}
    elif problem == "publication":
        state["deployPublication"] = {"status": "PENDING"}
    elif problem == "handoff":
        (case.progress_path.parent / "deploy-repair-retained").mkdir()
    elif problem == "request":
        monkeypatch.setattr(
            correction.current_request,
            "read",
            Mock(return_value={"token": "uncertain"}),
        )
    elif problem in {"requestPending", "requestError", "createUnconfirmed"}:
        context["states"]["A"][problem] = True
    elif problem == "running":
        context["states"]["A"]["currentStack"]["StackStatus"] = "UPDATE_IN_PROGRESS"
    elif problem == "token":
        context["states"]["A"].pop("endedRequest")
    elif problem == "region":
        monkeypatch.setattr(
            correction,
            "load_target_directory",
            Mock(return_value=dict(case.target, awsRegion="us-east-1")),
        )
    elif problem == "units":
        monkeypatch.setattr(
            correction.inputs,
            "load_units",
            Mock(return_value=(1, [dict(case.units[0], template="other.yaml")])),
        )
    elif problem == "input":
        (case.root / next(iter(context["consumedInputs"]))).write_text(
            "changed", encoding="utf-8"
        )
    elif problem == "input-digest":
        context["inputDigests"]["A"] = "other"
    elif problem == "input-set":
        context["inputIdentities"] = {}
    elif problem == "model":
        context["modelInputs"]["model/dev/team/logs.properties"] = "other"
    elif problem == "scope":
        monkeypatch.setattr(
            correction,
            "Findings",
            Mock(return_value=SimpleNamespace(errors=["outside Task scope"])),
        )
    correction.wt.save(case.path, state)
    write_sealed(case.root, case.progress_path, progress)
    if problem == "missing-progress":
        case.progress_path.unlink()
        with pytest.raises(ValueError, match="evidence is missing"):
            correction.correct(case.root, case.name, case.source)
        assert not case.progress_path.exists()
        return
    original = [p.read_bytes() for p in (case.task.path, case.progress_path, case.path)]
    if problem == "corrupt":
        with pytest.raises(ValueError, match="evidence is incomplete or corrupt"):
            runtime.correct_deploy_contract(case.root, case.name, case.source)
        assert_preserved(case, *original)
        return
    with pytest.raises(ValueError):
        runtime.correct_deploy_contract(case.root, case.name, case.source)
    assert_preserved(case, *original)


@pytest.mark.parametrize("file_number", [1, 2, 3])
def check_save_failure_rolls_back(case, monkeypatch, file_number):
    original = [p.read_bytes() for p in (case.task.path, case.progress_path, case.path)]
    replace = file_operations.os.replace
    fail = Mock(side_effect=[OSError("injected save failure")])
    monkeypatch.setattr(
        file_operations.os,
        "replace",
        SaveFailure(replace, fail, file_number, case.path),
    )
    with pytest.raises(OSError, match="injected save failure"):
        correction.correct(case.root, case.name, case.source)
    assert_preserved(case, *original)


class SaveFailure:
    def __init__(self, replace, fail, number, lifecycle):
        self.replace, self.fail, self.number, self.lifecycle = (
            replace,
            fail,
            number,
            lifecycle,
        )
        self.calls = 0

    def __call__(self, source, destination):
        if Path(source) != self.lifecycle.with_suffix(".tmp"):
            self.calls += 1
            if self.calls == self.number:
                return self.fail()
        return self.replace(source, destination)


@pytest.mark.parametrize(
    "changed", ["contract", "progress", "index", "lifecycle", "candidate"]
)
def check_concurrent_edits_preserved(case, monkeypatch, changed):
    save = correction.wt.save
    monkeypatch.setattr(
        correction.wt, "save", ConcurrentEdit(save, case, changed, monkeypatch)
    )
    with pytest.raises(ValueError):
        correction.correct(case.root, case.name, case.source)
    assert (
        read_state(case.root, case.name)[3]["deployIdentity"]["taskDigest"]
        == case.state["deployIdentity"]["taskDigest"]
    )
    if changed == "contract":
        assert (
            (case.root / case.name)
            .read_text(encoding="utf-8")
            .endswith("external edit\n")
        )
    elif changed == "progress":
        assert case.progress_path.read_text(encoding="utf-8").endswith(
            "external edit\n"
        )
    case.aws.assert_not_called()


class ConcurrentEdit:
    def __init__(self, save, case, changed, monkeypatch):
        self.save, self.case, self.changed, self.monkeypatch = (
            save,
            case,
            changed,
            monkeypatch,
        )

    def __call__(self, path, state):
        self.save(path, state)
        if "deployContractUpdate" not in state:
            return
        if self.changed in {"contract", "progress", "candidate"}:
            file = {
                "contract": self.case.task.path,
                "progress": self.case.progress_path,
                "candidate": self.case.source,
            }[self.changed]
            file.write_text(
                file.read_text(encoding="utf-8") + "external edit\n", encoding="utf-8"
            )
        elif self.changed == "index":
            self.monkeypatch.setattr(
                correction.ws,
                "git",
                Mock(
                    return_value=SimpleNamespace(stdout="changed index", returncode=0)
                ),
            )
        else:
            self.save(path, dict(state, externalEdit=True))


def check_old_git_evidence_and_live_candidate(case, monkeypatch):
    state = dict(case.state)
    state.pop("deployContract")
    correction.wt.save(case.path, state)
    monkeypatch.setattr(
        correction.ws,
        "git",
        Mock(
            return_value=SimpleNamespace(
                stdout=case.state["deployContract"], returncode=0
            )
        ),
    )
    case.task.path.write_text(case.candidate, encoding="utf-8")
    correction.correct(case.root, case.name, case.source)
    assert read_state(case.root, case.name)[3]["deployContract"] == case.candidate


@pytest.mark.parametrize("problem", [None, "digest", "files", "target", "save"])
def check_template_cleanup_owner_is_updated(case, monkeypatch, problem):
    directory = (
        correction.operation_journal.location(case.target).parent / "inputs-fixture"
    )
    directory.parent.mkdir(mode=0o700)
    directory.mkdir(mode=0o700)
    owner = dict(
        repository=str(case.root),
        taskFile=case.name,
        taskDigest=case.state["deployIdentity"]["taskDigest"],
        target=case.target,
        files=["A.json"],
    )
    if problem == "digest":
        owner.pop("taskDigest")
    elif problem == "files":
        owner["files"] = ["A.json", "A.json"]
    elif problem == "target":
        owner["target"] = dict(case.target, awsRegion="us-east-1")
    path = directory / "owner.json"
    write_sealed(case.root, path, owner)
    template = directory / "A.json"
    template.write_text("private input", encoding="utf-8")
    if problem:
        original = [
            p.read_bytes() for p in (case.task.path, case.progress_path, case.path)
        ]
        if problem == "save":
            monkeypatch.setattr(
                file_operations.os,
                "replace",
                SaveFailure(
                    file_operations.os.replace,
                    Mock(side_effect=OSError("injected save failure")),
                    3,
                    case.path,
                ),
            )
        with pytest.raises((ValueError, OSError)):
            correction.correct(case.root, case.name, case.source)
        assert_preserved(case, *original)
        assert correction.read_sealed(case.root, path) == owner
        return
    correction.correct(case.root, case.name, case.source)
    expected = dict(owner, taskDigest=tasks.task_digest(case.candidate))
    assert correction.read_sealed(case.root, path) == expected
    assert template.read_text(encoding="utf-8") == "private input"


@pytest.mark.parametrize("boundary", ["Task", "Progress", "both"])
def check_interrupted_correction_retries_same_operation(case, monkeypatch, boundary):
    atomic = correction.atomic_files
    monkeypatch.setattr(correction, "atomic_files", InterruptedSave(boundary))
    with pytest.raises(OSError, match="process interrupted"):
        correction.correct(case.root, case.name, case.source)
    assert read_state(case.root, case.name)[3].get("deployContractUpdate")
    with pytest.raises(ValueError, match="unfinished Deploy contract correction"):
        worktree.require(
            case.root, tasks.read_task_snapshot(case.root, case.name, live=True)
        )
    monkeypatch.setattr(correction, "atomic_files", atomic)
    correction.correct(case.root, case.name, case.source)
    state = read_state(case.root, case.name)[3]
    assert "deployContractUpdate" not in state
    assert (
        worktree.read_progress(case.root, state)["identity"] == state["deployIdentity"]
    )
    assert (
        tasks.status((case.root / case.name).read_text(encoding="utf-8")) == "suspend"
    )
    case.aws.assert_not_called()


class InterruptedSave:
    def __init__(self, boundary):
        self.boundary = boundary

    def __call__(self, contents):
        files = list(contents)
        selected = (
            files[:2]
            if self.boundary == "both"
            else files[:1]
            if self.boundary == "Task"
            else files[1:2]
        )
        for file in selected:
            file.write_text(contents[file], encoding="utf-8")
        raise OSError("process interrupted after partial save")


def check_closed_checkpoint_is_verified_before_rebinding(case, monkeypatch):
    state = copy.deepcopy(case.state)
    state["deployCheckpoints"] = {
        "A": dict(
            identity=state["deployIdentity"],
            taskDigest=state["deployIdentity"]["taskDigest"],
            commit="old-checkpoint",
            unit=case.units[0],
        )
    }
    state["deployPublication"] = dict(
        status="SUCCESS", publishedSource="head", commit="published"
    )
    correction.wt.save(case.path, state)
    check = Mock()
    monkeypatch.setattr(correction.git_publication, "checkpoint_source", check)
    correction.correct(case.root, case.name, case.source)
    check.assert_called_once()
    after = read_state(case.root, case.name)[3]
    receipt = after["deployCheckpoints"]["A"]
    assert receipt["identity"] == after["deployIdentity"]
    assert receipt["taskDigest"] == tasks.task_digest(case.candidate)
    assert receipt["commit"] == "old-checkpoint" and receipt["unit"] == case.units[0]
    assert after["deployPublication"] == state["deployPublication"]


def check_resume_cannot_adopt_unreconciled_digest(case, monkeypatch):
    case.task.path.write_text(case.candidate, encoding="utf-8")
    monkeypatch.setattr(runtime, "TaskValidation", case.scope)
    with pytest.raises(ValueError, match="fixed snapshot authority"):
        runtime.resume(case.root, case.name)
    assert tasks.read_task_snapshot(case.root, case.name, live=True).status == "suspend"


def check_active_controller_lock_prevents_correction(case):
    original = [p.read_bytes() for p in (case.task.path, case.progress_path, case.path)]
    with correction.operation_journal.locked(case.progress_path):
        with pytest.raises(correction.operation_journal.Blocked, match="lock busy"):
            correction.correct(case.root, case.name, case.source)
    assert_preserved(case, *original)


@pytest.mark.parametrize(
    "changed", ["progress", "inputs", "branch", "request", "handoff"]
)
def check_interrupted_correction_external_edit_is_retained(case, monkeypatch, changed):
    atomic = correction.atomic_files
    monkeypatch.setattr(correction, "atomic_files", InterruptedSave("Task"))
    with pytest.raises(OSError, match="process interrupted"):
        correction.correct(case.root, case.name, case.source)
    monkeypatch.setattr(correction, "atomic_files", atomic)
    if changed == "progress":
        case.progress_path.write_text("unknown external progress", encoding="utf-8")
    elif changed == "inputs":
        monkeypatch.setattr(
            correction.contracts,
            "validation_snapshot",
            Mock(return_value={"project.json": "external change"}),
        )
    elif changed == "request":
        monkeypatch.setattr(
            correction.current_request,
            "read",
            Mock(return_value={"token": "new uncertain request"}),
        )
    elif changed == "handoff":
        (case.progress_path.parent / "deploy-repair-new").mkdir()
    else:
        monkeypatch.setattr(
            correction.ws,
            "deploy_task_state",
            Mock(side_effect=ValueError("unexpected branch")),
        )
    original = [p.read_bytes() for p in (case.task.path, case.progress_path, case.path)]
    with pytest.raises(ValueError):
        correction.correct(case.root, case.name, case.source)
    assert_preserved(case, *original)


def model_for_file(source):
    return SimpleNamespace(dependencies={source: source.read_bytes()}, values={})


def omitted_service(case, monkeypatch):
    source = case.root / "model/dev/team/s3.properties"
    source.write_text("fixed original S3 Model\n", encoding="utf-8")
    candidate = case.candidate.replace(
        "## Validation scope\n", "## Validation scope\n- `dev/team/s3`\n"
    )
    for heading in ("## Modified files\n", "## Allowed paths\n"):
        candidate = candidate.replace(
            heading,
            heading
            + "- `model/dev/team/s3.properties`\n- `docs/designs/dev/team/s3.md`\n",
        )
    case.source.write_text(candidate, encoding="utf-8")
    monkeypatch.setattr(correction, "load_model", Mock(side_effect=model_for_file))
    monkeypatch.setattr(
        correction,
        "mapping_preflight",
        Mock(return_value=({}, {"A": {"Bucket": (source,)}})),
    )
    monkeypatch.setattr(
        correction.ws, "subprocess_bytes", Mock(return_value=source.read_bytes())
    )
    return source, candidate


def check_omitted_service_and_paths_can_resume(case, monkeypatch):
    source, candidate = omitted_service(case, monkeypatch)
    before = copy.deepcopy(case.context)
    runtime.correct_deploy_contract(case.root, case.name, case.source)
    state = read_state(case.root, case.name)[3]
    assert state["deployContract"] == candidate
    assert source.read_text(encoding="utf-8") == "fixed original S3 Model\n"
    progress = worktree.read_progress(case.root, state)["runContext"]
    before.update(taskDigest=tasks.task_digest(candidate), snapshotValidation="NOT_RUN")
    assert progress == before
    correction.mapping_preflight.assert_called_once_with(
        case.root, "dev", "team", ["A"]
    )
    correction.ws.subprocess_bytes.assert_called_once_with(
        case.root, "head", "model/dev/team/s3.properties"
    )
    monkeypatch.setattr(runtime, "TaskValidation", case.scope)
    runtime.resume(case.root, case.name)
    task = tasks.read_task_snapshot(case.root, case.name, live=True)
    assert task.status == "running" and ("dev", "team", "s3") in task.scope
    case.aws.assert_not_called()


@pytest.mark.parametrize(
    "problem",
    [
        "unbound",
        "changed-model",
        "mapping-error",
        "environment",
        "target",
        "stack",
        "scope-removal",
        "permission",
        "save",
    ],
)
def check_omitted_service_rejects_unproven_changes(case, monkeypatch, problem):
    source, candidate = omitted_service(case, monkeypatch)
    if problem == "unbound":
        monkeypatch.setattr(
            correction, "mapping_preflight", Mock(return_value=({}, {"A": {}}))
        )
    elif problem == "changed-model":
        source.write_text("unapproved changed Model\n", encoding="utf-8")
    elif problem == "mapping-error":
        monkeypatch.setattr(
            correction,
            "mapping_preflight",
            Mock(side_effect=ValueError("ambiguous ownership")),
        )
    elif problem in {"environment", "target"}:
        candidate = candidate.replace(
            "dev/team/s3", "stg/team/s3" if problem == "environment" else "dev/other/s3"
        )
    elif problem == "stack":
        candidate = candidate.replace(
            "- Deployment scope: `A`", "- Deployment scope: `A`, `B`"
        )
    elif problem == "scope-removal":
        candidate = candidate.replace("- `dev/team/logs`\n", "")
    elif problem == "permission":
        candidate = candidate.replace(
            "- AWS mutation: `allowed`", "- AWS mutation: `forbidden`"
        )
    else:
        monkeypatch.setattr(
            file_operations.os,
            "replace",
            SaveFailure(
                file_operations.os.replace,
                Mock(side_effect=OSError("injected save failure")),
                2,
                case.path,
            ),
        )
    case.source.write_text(candidate, encoding="utf-8")
    original = [p.read_bytes() for p in (case.task.path, case.progress_path, case.path)]
    with pytest.raises((OSError, ValueError)):
        runtime.correct_deploy_contract(case.root, case.name, case.source)
    assert_preserved(case, *original)


@pytest.mark.parametrize(
    "problem",
    [None, "executed", "unrelated", "similar-service", "approval", "issued", "save"],
)
def check_service_preparation_failure_keeps_evidence(case, monkeypatch, problem):
    _, candidate = omitted_service(case, monkeypatch)
    state = copy.deepcopy(case.state)
    progress = worktree.read_progress(case.root, state)
    current = progress["runContext"]
    item = current["states"]["A"]
    item.clear()
    item.update(
        status="BLOCKED",
        reason="Observed readiness: task scope violation: stack resource outside Validation scope: dev/team/s3",
        failure=dict(
            stage="PREPARATION",
            executionState="NOT_EXECUTED",
            classification="NEEDS_HUMAN",
        ),
    )
    if problem == "executed":
        item["failure"]["executionState"] = "UNKNOWN"
    if problem == "unrelated":
        item["reason"] = "unrelated operation failure"
    if problem == "similar-service":
        item["reason"] += "-extra"
    path = case.progress_path.parent / "deploy-failure-fixture.json"
    current["currentFailure"] = str(path)
    failure = dict(
        repository=str(case.root),
        taskFile=case.name,
        taskDigest=state["deployIdentity"]["taskDigest"],
        target=case.target,
        environment="dev",
        directory="team",
        states=copy.deepcopy(current["states"]),
        inputs={**current["consumedInputs"], **current["modelInputs"]},
    )
    if problem == "approval":
        failure["states"]["A"]["approvedChangeDigest"] = "must-not-transfer"
    write_sealed(case.root, path, failure)
    write_sealed(case.root, case.progress_path, progress)
    if problem == "issued":
        (case.progress_path.parent / "deploy-repair-fixture").mkdir()
    if problem == "save":
        monkeypatch.setattr(
            file_operations.os,
            "replace",
            SaveFailure(
                file_operations.os.replace,
                Mock(side_effect=OSError("injected save failure")),
                3,
                case.path,
            ),
        )
    original = [p.read_bytes() for p in (case.task.path, case.progress_path, case.path)]
    if problem:
        with pytest.raises((OSError, ValueError)):
            runtime.correct_deploy_contract(case.root, case.name, case.source)
        assert_preserved(case, *original)
        assert correction.read_sealed(case.root, path) == failure
        return
    runtime.correct_deploy_contract(case.root, case.name, case.source)
    state = read_state(case.root, case.name)[3]
    saved = worktree.read_progress(case.root, state)["runContext"]
    assert saved["states"] == current["states"] and saved["currentFailure"] == str(path)
    assert correction.read_sealed(case.root, path) == dict(
        failure, taskDigest=tasks.task_digest(candidate)
    )
    case.aws.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
