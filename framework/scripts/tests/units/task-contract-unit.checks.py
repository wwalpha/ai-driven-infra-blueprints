#!/usr/bin/env python3
"""Task selection, declaration checks and publication consistency with synthetic inputs."""

import json
import sys
from dataclasses import FrozenInstanceError
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import os
import subprocess
from unittest.mock import patch

import model.sources as _imports_model_sources
import pytest
import task_contract as transitions
import task_contract_core as tasks
import utils.input_cache as _imports_input_cache
from generation_inputs import GenerationInputs
from issues.publication import save_scan
from model.importing import scope as import_scope
from support.import_model_fixtures import dependency_contract
from support.issues_scan_fixtures import review_for, snapshot_artifact
from support.pytest_cli import run
from support.repository_fixtures import contract, transition_contract
from sync_runtime import publish_generation
from utils.input_cache import input_scope
from validation.findings import Findings
from validation.task import TaskValidation
from validation_scope import active_scope

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def selection_contract(name, allowed="output.txt", workflow=""):
    return (
        f"## Task contract\n- Task type: `migration`\n- Task status: `running`\n{workflow}"
        "## Validation scope\n- `dev/team/iam`\n"
        f"## Modified files\n- `{name}`\n- `output.txt`\n"
        f"## Allowed paths\n- `{name}`\n- `{allowed}`\n"
    )


@pytest.mark.parametrize(
    "allowed,accepted",
    [("output.txt", True), ("*.txt", True), ("out*", True), ("other.txt", False)],
)
def check_allowed_paths(tmp_path, allowed, accepted):
    name = "tasks/test.md"
    records = {name: selection_contract(name, allowed)}
    if accepted:
        tasks.validate_contract(tmp_path, name, records[name])
        if allowed == "output.txt":
            with patch.object(
                tasks,
                "matches",
                side_effect=AssertionError("exact matches need no pattern scan"),
            ):
                tasks.validate_contract(tmp_path, name, records[name])
    else:
        with pytest.raises(ValueError, match="outside Allowed paths"):
            tasks.validate_contract(tmp_path, name, records[name])
    external = tmp_path / "external"
    external.write_text("safe")
    (tmp_path / "output.txt").symlink_to(external)
    with pytest.raises(ValueError, match="symlinks"):
        tasks.validate_contract(tmp_path, name, records[name])


def _callback_check_live_selection_exercise(one, original, other, tmp_path, two, /):
    with patch.dict(os.environ, {tasks.SELECTOR: one}):
        assert import_scope.selected(tmp_path) is None
        assert import_scope.selected(tmp_path) is None  # cached negative parsing result
        memo_table = _imports_input_cache.memo_table
        assert (
            import_scope._selection.__wrapped__,
            (tmp_path, one, original),
        ) in memo_table()
        empty = tmp_path / "stage-without-contracts"
        empty.mkdir()
        assert import_scope.selected(empty) is None
        assert import_scope.selected(other) == ("dev", "team", "iam")
        stat = (tmp_path / one).stat()
        (tmp_path / one).write_text(
            selection_contract(one, workflow="- Workflow: `import`\n")
        )
        os.utime(tmp_path / one, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert import_scope.selected(tmp_path) == ("dev", "team", "iam")
        (tmp_path / one).write_text(original)
        assert import_scope.selected(tmp_path) is None
        (tmp_path / two).write_text(
            selection_contract(
                two,
                workflow="- Workflow: `import`\n- IMPORT target: `stg/team/config`\n",
            )
        )
        with patch.dict(os.environ, {tasks.SELECTOR: two}):
            assert import_scope.selected(tmp_path) == ("stg", "team", "config")
        assert import_scope.selected(tmp_path) is None
        with import_scope.restrict(("dev", "team", "vpc")):
            assert import_scope.selected(tmp_path) == ("dev", "team", "vpc")
            FileReads = _imports_model_sources.FileReads
            edit_base = _imports_model_sources.edit_base
            with pytest.raises(ValueError, match="outside selected"):
                edit_base(tmp_path / "model/dev/team/config.properties", FileReads())
        assert import_scope.selected(tmp_path) is None
        (tmp_path / two).unlink()
        (tmp_path / one).write_text(selection_contract(one, "denied"))
        with pytest.raises(ValueError, match="outside Allowed paths"):
            import_scope.selected(tmp_path)
        (tmp_path / one).write_text(original)
        (tmp_path / "external").write_text("safe")
        (tmp_path / "output.txt").symlink_to(tmp_path / "external")
        assert import_scope.selected(tmp_path) is None
        with pytest.raises(ValueError, match="symlinks"):
            tasks.safe_path(tmp_path, "output.txt")
        (tmp_path / "output.txt").unlink()
        (tmp_path / one).write_text(
            original.replace("`running`", "`suspend`")
            + "## Suspension reason\nExplicit test stop\n"
        )
        assert (
            import_scope.selected(tmp_path) is None
        )  # Scope reads do not resume execution.
        with pytest.raises(ValueError, match="suspend task"):
            tasks.task_path(tmp_path)


def check_live_selection(tmp_path):
    (tmp_path / "tasks").mkdir()
    one, two = "tasks/one.md", "tasks/two.md"
    original = selection_contract(one)
    (tmp_path / one).write_text(original)
    other = tmp_path / "other"
    other.mkdir()
    (other / "tasks").mkdir()
    (other / one).write_text(selection_contract(one, workflow="- Workflow: `import`\n"))

    exercise = (input_scope)(
        _bind_framework_callback(
            _callback_check_live_selection_exercise, one, original, other, tmp_path, two
        )
    )
    exercise()


def generation_plan(root, output):
    """Unit candidate fixture; real Model/view preparation is exercised by IT."""

    snapshot = GenerationInputs(root)
    for path in output:
        snapshot.read(path)
    return SimpleNamespace(
        root=root,
        stage=root,
        snapshot=snapshot,
        expected_outputs={next(iter(output)): output},
        saved={},
        failures=[],
        generated={},
    )


@pytest.mark.parametrize("change", ["scope", "completed", "suspend"])
def check_task_change_rolls_back_publication(tmp_path, monkeypatch, change):
    name = "tasks/owner.md"
    file = tmp_path / "file.txt"
    file.write_text("original")
    tasks.start(tmp_path, name, contract("owner", ["file.txt"]))
    monkeypatch.setenv(tasks.SELECTOR, name)
    plan = generation_plan(tmp_path, {file: "candidate"})
    own = tmp_path / name
    text = own.read_text()
    own.write_text(
        text.replace("- `framework`", "- `dev/team/iam`")
        if change == "scope"
        else text.replace("`running`", f"`{change}`")
        + ("## Suspension reason\nExplicit test stop\n" if change == "suspend" else "")
    )
    with pytest.raises(ValueError, match="inputs changed"):
        publish_generation(plan)
    assert file.read_text() == "original"
    assert ("dev/team/iam" if change == "scope" else f"`{change}`") in own.read_text()


@pytest.mark.parametrize("state", ["running", "completed", "suspend"])
def check_publication_preserves_contract(tmp_path, monkeypatch, state):
    name = "tasks/example.md"
    text = contract("example", ["file.txt"])
    if state is None:
        text = text.replace("- Task status: `running`\n", "")
    else:
        text = text.replace("`running`", f"`{state}`")
        if state == "suspend":
            text += "## Suspension reason\nExplicit test stop\n"
    own = tmp_path / name
    own.parent.mkdir()
    own.write_text(text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    file = tmp_path / "file.txt"
    file.write_text("original")
    new = tmp_path / "new.txt"
    obsolete = tmp_path / "obsolete.txt"
    obsolete.write_text("keep")
    if state in ("completed", "suspend"):
        if state == "completed":
            assert tasks.task_path(tmp_path) == own
            assert tasks.task_revision(tmp_path) == (name, text)
        with pytest.raises(ValueError, match="task cannot write|suspend task"):
            publish_generation(generation_plan(tmp_path, {file: "saved", new: "new"}))
        assert (
            file.read_text() == "original"
            and not new.exists()
            and obsolete.read_text() == "keep"
        )
    else:
        assert tasks.task_path(tmp_path) == own
        publish_generation(generation_plan(tmp_path, {file: "saved"}))
        assert file.read_text() == "saved"
    assert own.read_text() == text
    monkeypatch.delenv(tasks.SELECTOR)
    standalone = tmp_path / "standalone"
    standalone.mkdir()
    publish_generation(
        generation_plan(standalone, {standalone / "file.txt": "without contract"})
    )
    assert (standalone / "file.txt").read_text() == "without contract"


def check_source_guard_keeps_plan_consistency(tmp_path, monkeypatch):
    name = "tasks/owner.md"
    source = tmp_path / "model/dev/team/iam.properties"
    tasks.start(
        tmp_path, name, contract("owner", [source.relative_to(tmp_path).as_posix()])
    )
    monkeypatch.setenv(tasks.SELECTOR, name)
    plan = generation_plan(tmp_path, {source: "# model-format: 2\n"})
    own = tmp_path / name
    own.write_text(own.read_text().replace("- `framework`", "- `dev/team/iam`"))
    with pytest.raises(ValueError, match="inputs changed"):
        publish_generation(plan)
    assert not source.exists()


def check_scope_change_during_planning(tmp_path, monkeypatch):
    name = "tasks/example.md"
    tasks.start(tmp_path, name, contract("example", ["file.txt"]))
    monkeypatch.setenv(tasks.SELECTOR, name)
    plan = generation_plan(tmp_path, {tmp_path / "file.txt": "candidate"})
    own = tmp_path / name
    own.write_text(own.read_text().replace("- `framework`", "- `dev/team/iam`"))
    with pytest.raises(ValueError, match="inputs changed"):
        publish_generation(plan)
    assert not (tmp_path / "file.txt").exists()
    own.write_text(own.read_text().replace("`running`", "`completed`"))
    assert tasks.task_path(tmp_path) == own
    expected = tasks.task_revision(tmp_path)
    assert expected[1] == own.read_text()
    with pytest.raises(ValueError, match="completed task cannot write"):
        publish_generation(
            generation_plan(tmp_path, {tmp_path / "file.txt": "candidate"})
        )
    assert not (tmp_path / "file.txt").exists()


def check_batch_operation_contract():
    base = (
        "## Task contract\n- Task type: `design`\n- Workflow: `update`\n"
        "- Model operation: `import-merge`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n"
    )
    pairs = [
        {
            "source": "test/primary/network/" + left,
            "destination": "test/primary/network/" + right,
        }
        for left, right in [
            ("022", "009"),
            ("023", "010"),
            ("024", "011"),
            ("025", "012"),
            ("028", "013"),
        ]
    ]
    pair_text = "## Model merge pairs\n" + "".join(
        "- " + json.dumps(pair) + "\n" for pair in pairs
    )
    reference = {
        "consumer": "test/primary/subnet/020",
        "field": "document",
        "property": "EC2.Subnet.Policy",
        "pointer": "/Statement/0/Resource",
        **pairs[0],
    }
    ref_text = "## Model reference changes\n- " + json.dumps(reference) + "\n"
    operation = tasks.model_operation(base + pair_text + ref_text)
    assert (
        operation.scope == ("test", "primary", "network") and len(operation.pairs) == 5
    )
    assert operation.references[0].pointer == "/Statement/0/Resource"
    with pytest.raises(FrozenInstanceError):
        operation.action = "import-delete"
    deletion = (
        base.replace("import-merge", "import-delete")
        + "## Model delete sources\n- `"
        + pairs[0]["source"]
        + "`\n"
    )
    assert tasks.model_operation(deletion).delete_sources == (pairs[0]["source"],)
    malformed = [
        base + "## Model merge pairs\n",
        base + pair_text + pair_text,
        pair_text,
        base + pair_text + "trailing junk\n",
        base + pair_text.replace('"022"', '"009"') + ref_text + ref_text,
        base + pair_text.replace("network/023", "network/009"),
        base + pair_text.replace("network/023", "network/022"),
        base + pair_text.replace("network/010", "network/009"),
        base + pair_text.replace('"source":', '"source": null, "source":', 1),
        base + pair_text.replace('"source":', '"extra": NaN, "source":', 1),
        base + pair_text + ref_text.replace("/Statement/0/Resource", ""),
        base + pair_text + ref_text.replace("/Statement/0/Resource", "/bad~2"),
        base + pair_text + ref_text.replace("subnet/020", "network/022"),
        deletion + "## Model reference changes\n",
        base.replace("- Model operation:", "- Model operation :") + pair_text,
    ]
    for text in malformed:
        with pytest.raises(ValueError):
            tasks.model_operation(text)
    assert (
        tasks.model_operation(
            "## Goal\nFree prose with Model merge pairs is unrestricted.\n"
        )
        is None
    )


def check_dependency_detach_contract():
    text = dependency_contract()
    parsed = tasks.model_refactor(text)
    assert len(parsed) == 1 and parsed[0].key == "desired.row.002-001.value"
    assert tasks.final_model_task(text) and tasks.model_operation(text) is None
    assert tasks.model_refactor("## Task contract\n- Task type: `design`\n") is None
    for bad in [
        text.replace("forbidden", "allowed", 1),
        text.replace("design", "infrastructure"),
        text.replace("value-preserving", "automatic"),
        text.replace("Model refactor:", "Model refactor :"),
        text.replace("service-a/001", "service-a/999/001"),
        text.replace("002-001", "003-001"),
        text + text[text.index("## Model dependency detach") :],
        text.replace('"key":', '"key": null, "key":'),
        text.replace('"key":', '"unknown": NaN, "key":'),
        text.replace('"key":', '"pointer": "/bad~2", "key":'),
        text.replace("## Model dependency detach", "## Model dependency detach extra"),
        text.replace(
            "## Model dependency detach",
            "- Model operation: `import-merge`\n## Model dependency detach",
        ),
        text.split("## Model dependency detach")[0] + "## Model dependency detach\n",
        text + "unconsumed junk\n",
    ]:
        with pytest.raises(ValueError):
            tasks.model_refactor(bad)


def blocked(callback, message):
    with pytest.raises(ValueError) as error:
        callback()
    assert message in str(error.value), str(error.value)


def check_completed_legacy_and_paths(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
        old = "tasks/old.md"
        new = "tasks/new.md"
        transitions.start(root, old, transition_contract(old, ["README.md", "old.md"]))
        (root / old).write_text(
            transition_contract(old, ["README.md", "old.md"], state="completed")
        )
        transitions.start(root, new, transition_contract(new, ["README.md"]))
        assert transitions.task_path(root) == root / new
        _ = {old, new, "README.md", "old.md", "tasks/removed.md"}
        for name in (old, new):
            (root / name).unlink()
        assert transitions.task_path(root, required=False) is None
        assert transitions.task_revision(root) == (None, None)
        blocked(lambda: transitions.task_path(root), "selected task contract required")
        blocked(lambda: transitions.status("## Task contract\n"), "Task status")
        for value in (
            "../escape",
            "/tmp/escape",
            "./file",
            "a//file",
            "a/../file",
            "*.md",
            "a/**",
            ".git/config",
            ".",
        ):
            blocked(
                lambda value=value: transitions.start(
                    root, new, transition_contract(new, [value])
                ),
                "exact repository-relative path",
            )
        (root / "linked").symlink_to(root / "elsewhere")
        blocked(
            lambda: transitions.start(
                root, new, transition_contract(new, ["linked/file.md"])
            ),
            "symlinks",
        )
        blocked(
            lambda: transitions.start(root, new, transition_contract(new, [old])),
            "another contract",
        )
        blocked(
            lambda: transitions.start(
                root, new, transition_contract(new, ["file.md", "file.md"])
            ),
            "duplicate paths",
        )
        blocked(
            lambda: transitions.start(
                root, new, transition_contract(new, ["file.md"], state="paused")
            ),
            "Task status",
        )


def check_suspend_and_resume(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
        first, second = "tasks/first.md", "tasks/second.md"
        transitions.start(
            root, first, transition_contract(first, ["shared.md", "own.md"])
        )
        blocked(lambda: transitions.suspend(root, first, " "), "concrete reason")
        assert transitions.suspend(
            root, first, "other task: schema failure in model/dev/cde/ec2.properties"
        )
        saved = (root / first).read_bytes()
        assert transitions.status(saved.decode()) == "suspend"
        assert "schema failure in model/dev/cde/ec2.properties" in saved.decode()
        assert transitions.task_path(root, required=False) is None
        assert active_scope(root) == set()
        with patch.dict(os.environ, {transitions.SELECTOR: first}):
            blocked(lambda: transitions.task_path(root), "suspend task cannot execute")
        assert transitions.contract_path(root, first) == root / first
        assert active_scope(root, contract_file=first) == set()
        blocked(
            lambda: active_scope(root, task_file=first), "suspend task cannot execute"
        )
        blocked(
            lambda: transitions.task_revision(root, first),
            "suspend task cannot execute",
        )
        blocked(
            lambda: transitions.contract_path(root, "../first.md"),
            "invalid task selector",
        )
        blocked(lambda: transitions.contract_path(root, "tasks/missing.md"), "missing")
        saved = (root / first).read_bytes()
        (root / "shared.md").symlink_to(root / "elsewhere")
        blocked(lambda: transitions.contract_path(root, first), "symlinks")
        (root / "shared.md").unlink()
        (root / first).write_text(
            saved.decode().replace("## Modified files", "## Missing files")
        )
        blocked(
            lambda: transitions.contract_path(root, first), "missing or duplicate paths"
        )
        (root / first).write_bytes(saved)
        transitions.start(root, second, transition_contract(second, ["shared.md"]))
        assert transitions.task_path(root) == root / second
        transitions.resume(root, first)
        assert "## Suspension reason" not in (root / first).read_text()
        with patch.dict(os.environ, {transitions.SELECTOR: first}):
            transitions.task_path(root)
        transitions.suspend(root, first, "own check failed")
        saved = (root / first).read_bytes()
        other = (root / second).read_bytes()
        assert not transitions.suspend(root, first, "overwrite")
        assert (root / first).read_bytes() == saved and (
            root / second
        ).read_bytes() == other
        transitions.suspend(
            root, second, "own acceptance check failed: changed:shared.md"
        )
        transitions.resume(root, first)
        assert transitions.status((root / first).read_text()) == "running"
        assert "## Suspension reason" not in (root / first).read_text()
        transitions.resume(root, second)
        # Invalid other contracts cannot prevent suspension of the explicitly selected task.
        (root / second).write_text("invalid contract")
        assert transitions.suspend(root, first, "invalid contract: tasks/second.md")
        blocked(
            lambda: transitions.status(
                transition_contract(first, ["shared.md"], state="suspend")
            ),
            "Suspension reason",
        )
        # A reason is diagnostic text, even if an error contains Markdown headings.
        (root / second).unlink()
        transitions.resume(root, first)
        transitions.suspend(root, first, "error\n## Modified files\n- `unexpected.md`")
        assert transitions.paths_in(
            (root / first).read_text(), "## Modified files"
        ) == {first, "shared.md", "own.md"}


def check_admission_selection(tmp_path, monkeypatch):
    monkeypatch.delenv(transitions.SELECTOR, raising=False)
    first, second = "tasks/first.md", "tasks/second.md"
    transitions.start(tmp_path, first, transition_contract(first, ["new/file.md"]))
    assert transitions.task_path(tmp_path) == tmp_path / first
    assert active_scope(tmp_path) == set()
    before = (tmp_path / first).read_bytes()
    transitions.start(
        tmp_path,
        second,
        transition_contract(
            second, ["new/file.md", "other.md"], kind="design", scope="dev/cde/ec2"
        ),
    )
    assert (tmp_path / first).read_bytes() == before
    blocked(lambda: transitions.task_path(tmp_path), "multiple running tasks")
    monkeypatch.setenv(transitions.SELECTOR, second)
    assert active_scope(tmp_path) == {("dev", "cde", "ec2")}
    blocked(lambda: transitions.task_path(tmp_path, "tasks/missing.md"), "missing")
    blocked(
        lambda: transitions.task_path(tmp_path, "../first.md"), "invalid task selector"
    )
    before = (tmp_path / second).read_bytes()
    transitions.refresh(tmp_path, second)
    assert (tmp_path / second).read_bytes() == before
    transitions.complete(tmp_path, first)
    transitions.complete(tmp_path, second)


def _callback_check_report_commit_independence_git(tmp_path, /, *args):
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            *args,
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize("kind", ["reports", "migration", "design"])
def check_report_commit_independence(tmp_path, monkeypatch, kind):
    name = "tasks/investigation.md"
    reports = {"issues/dev/cde/issues.md", "issues/dev/cde/iac-issues.md"}
    permitted = reports | {name}
    text = (
        "## Task contract\n- Task type: `"
        + ("design" if kind == "design" else "migration")
        + "`\n- Task status: `running`\n## Validation scope\n- `dev/cde/s3`\n"
        "## Required changes\n- [R1] Save reports\n## Acceptance checks\n"
        + "".join(f"- [R1] `exists:{path}`\n" for path in sorted(reports))
        + "## Modified files\n"
        + "".join(f"- `{path}`\n" for path in sorted(permitted))
        + "## Allowed paths\n"
        + "".join(f"- `{path}`\n" for path in sorted(permitted))
    )
    if kind == "migration":
        text += "- `infra/**`\n"  # An ordinary migration must retain its Git baseline.
    git = _bind_framework_callback(
        _callback_check_report_commit_independence_git, tmp_path
    )
    git("init", "--quiet", "--initial-branch=master")
    for path in reports | {"outside.txt"}:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("")
    git("add", ".")
    git("commit", "--quiet", "-m", "initial")
    baseline = git("rev-parse", "HEAD")
    tasks.start(tmp_path, name, text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    findings = Findings(tmp_path)
    task = TaskValidation(tmp_path, findings)
    with patch(
        "model.importing.repository.task_start_commit", return_value=baseline
    ) as start:
        task.fix_baseline()
        assert start.call_count == (0 if kind == "reports" else 1)
        git("commit", "--quiet", "--allow-empty", "-m", "advance HEAD")
        if kind == "reports":
            artifact = snapshot_artifact(tmp_path, target="cde")
            save_scan(tmp_path, artifact, review_for(artifact))
        else:
            for path in reports:
                (tmp_path / path).write_text("ordinary Task change")
        task.check_task_scope()
        assert not findings.errors, findings.errors
        (tmp_path / "committed.txt").write_text("unrelated committed input")
        git("add", "committed.txt")
        git("commit", "--quiet", "-m", "unrelated change")
        assert git("rev-parse", "HEAD") != baseline
        task.check_task_scope()
    assert active_scope(tmp_path) == {("dev", "cde", "s3")}
    assert (tmp_path / name).read_text() == text  # No suspension or replacement Task.
    for state in ("unstaged", "staged", "untracked"):
        outside = tmp_path / (
            "untracked.txt" if state == "untracked" else "outside.txt"
        )
        outside.write_text(state)
        if state == "staged":
            git("add", "outside.txt")
            outside.write_text("")
        blocked = TaskValidation(tmp_path, Findings(tmp_path))
        blocked.check_task_scope()
        if kind == "reports":
            assert not blocked.findings.errors, blocked.findings.errors
            assert blocked.changed_paths == blocked.scope_paths == set()
        else:
            assert any(
                f"outside task scope: {outside.name}" in error
                for error in blocked.findings.errors
            )
    (tmp_path / "outside.txt").write_text("")
    git("add", "outside.txt")
    (tmp_path / "untracked.txt").unlink()
    if kind != "reports":
        assert any(
            "outside task scope: committed.txt" in error for error in findings.errors
        )
        assert "committed.txt" in task.changed_paths and task.baseline == baseline
        return
    assert not findings.errors, findings.errors
    assert task.changed_paths == task.scope_paths == set()
    task.check_acceptance_checks({})
    assert not findings.errors, findings.errors
    # Preserve independent index changes, including a file restored only in the worktree.
    git("add", "issues/dev/cde/issues.md")
    (tmp_path / "issues/dev/cde/issues.md").write_text("")
    assert task.final_paths() == set()
    task.check_task_scope()
    assert not findings.errors, findings.errors
    with patch(
        "model.importing.repository.task_start_commit",
        side_effect=AssertionError("report completion used a baseline"),
    ):
        transitions.complete(tmp_path, name)
    assert tasks.status((tmp_path / name).read_text()) == "completed"


if __name__ == "__main__":
    raise SystemExit(run(__file__))
