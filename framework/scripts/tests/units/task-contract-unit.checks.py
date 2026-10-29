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
from unittest.mock import Mock, patch

import model.sources as _imports_model_sources
import pytest
import task_contract as transitions
import task_contract_core as tasks
import task_contract_runtime as task_runtime
import utils.input_cache as _imports_input_cache
from generation_inputs import GenerationInputs
from issues.publication import save_scan
from model.format import FORMAT, INDEX
from model.importing import scope as import_scope
from support.import_model_fixtures import dependency_contract
from support.issues_scan_fixtures import review_for, snapshot_artifact
from support.model_v2_fixtures import logs_fixture
from support.pytest_cli import run
from support.repository_fixtures import contract, git, transition_contract
from support.repository_fixtures import fixture as repository_fixture
from sync_runtime import publish_generation
from utils.input_cache import input_scope
from validation import acceptance
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
    text = contract("example", ["docs/designs/dev/team/iam.md"]).replace(
        "- `framework`", "- `dev/team/iam`"
    )
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
    file = tmp_path / "docs/designs/dev/team/iam.md"
    file.parent.mkdir(parents=True)
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
        with pytest.raises(ValueError, match="outside task scope"):
            publish_generation(
                generation_plan(tmp_path, {file.with_name("other.md"): "denied"})
            )
        assert not file.with_name("other.md").exists()
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


def check_normal_final_model_classification():
    model = "model/dev/team/iam.properties"
    view = "docs/designs/dev/team/iam.md"
    text = (
        "## Task contract\n- Task type: `design`\n- Workflow: `update`\n"
        "- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n"
        "## Modified files\n- `tasks/example.md`\n"
        f"- `{model}`\n- `{view}`\n"
    )
    assert tasks.final_model_task(text, {model, view})
    assert not tasks.final_model_task(text, {view})
    for changed in ("infrastructure", "import", "governance"):
        bad = text.replace(
            "`design`" if changed != "import" else "`update`", f"`{changed}`"
        )
        assert not tasks.final_model_task(bad, {model})
    for field in ("AWS API execution", "deploy/apply"):
        assert not tasks.final_model_task(
            text.replace(f"- {field}: `forbidden`", f"- {field}: `allowed`"), {model}
        )
        assert not tasks.final_model_task(
            text.replace(
                f"- {field}: `forbidden`",
                f"- {field}: `forbidden`\n- {field}: `allowed`",
            ),
            {model},
        )
    assert not tasks.final_model_task(text, {model, "iac/template.yaml"})
    assert not tasks.final_model_task(text, {model, "framework/scripts/example.py"})
    assert not tasks.final_model_task(
        text, {model, "model/dev/team/undeclared.properties"}
    )
    assert not tasks.final_model_task(
        text.replace(f"- `{view}`", "- `framework/script.py`"), {model}
    )
    with pytest.raises(ValueError):
        tasks.final_model_task(text.replace(f"- `{model}`", "invalid"), {model})


def check_framework_final_classification():
    source = "framework/scripts/worktree_task.py"
    text = (
        "## Task contract\n- Task type: `governance`\n"
        "## Validation scope\n- `framework`\n"
        "## Modified files\n- `tasks/example.md`\n" + f"- `{source}`\n"
    )
    for owned in (
        source,
        ".agents/skills/worktree/SKILL.md",
        ".github/workflows/framework-it.yml",
        ".github/workflows/python-quality.yml",
        "pyproject.toml",
        "README.md",
        "AGENTS.md",
        "CMD.md",
        "docs/system-overview.md",
        ".gitignore",
        ".gitattributes",
    ):
        assert tasks.final_framework_task(text.replace(source, owned), {owned})
        if owned != source:
            assert not tasks.final_framework_task(text, {owned})
    assert tasks.final_framework_task(text, {source})
    assert not tasks.final_model_task(text, {source})
    for kind in ("catalog-maintenance", "migration"):
        assert tasks.final_framework_task(text.replace("governance", kind), {source})
    assert not tasks.final_framework_task(text, set())
    assert not tasks.final_framework_task(
        text.replace("`governance`", "`design`"), {source}
    )
    assert not tasks.final_framework_task(
        text.replace("`framework`", "`dev/team/iam`"), {source}
    )
    for consumer in (
        "project.json",
        "model/dev/team/iam.properties",
        "infra/template.yaml",
        "tests/dev/team/iam.py",
        ".github/workflows/consumer.yml",
        "unknown.txt",
    ):
        assert not tasks.final_framework_task(text, {consumer})
        assert not tasks.final_framework_task(text, {source, consumer})
        assert not tasks.final_framework_task(
            text + f"- `{consumer}`\n", {source, consumer}
        )
        assert not tasks.final_framework_task(
            text.replace(source, consumer), {consumer}
        )


def check_final_candidate_runs_model_guard(tmp_path):
    name = "tasks/example.md"
    model = "model/dev/team/iam.properties"
    text = contract("example", [model]).replace("`governance`", "`design`")
    tasks.start(tmp_path, name, text)
    candidate = SimpleNamespace(base_commit="base", changed_paths={model})
    findings = Findings(tmp_path)
    validator = TaskValidation(
        tmp_path, findings, final_candidate=candidate, contract_file=name
    )
    with (
        tasks.selected_task(tmp_path, name),
        patch(
            "import_guard.require_import_changes",
            side_effect=ValueError("invalid reference"),
        ) as guard,
    ):
        validator.check_task_scope()
    guard.assert_called_once_with(tmp_path, {model}, final_candidate=candidate)
    assert any("invalid reference" in error for error in findings.errors)


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
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(task_runtime, "check_resume_scope"),
    ):
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
    with patch.object(task_runtime, "Validator") as validator:
        validator.return_value.report.return_value = 0
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


@pytest.mark.parametrize("state", ["unstaged", "staged", "untracked"])
def check_suspended_scope_preflight(tmp_path, monkeypatch, state):
    git = _bind_framework_callback(
        _callback_check_report_commit_independence_git, tmp_path
    )
    git("init", "--quiet", "--initial-branch=master")
    (tmp_path / ".gitignore").write_text("tasks/\n")
    (tmp_path / "outside.txt").write_text("original")
    git("add", ".")
    git("commit", "--quiet", "-m", "initial")
    name, other = "tasks/self.md", "tasks/other.md"
    transitions.start(tmp_path, name, transition_contract(name, ["owned.txt"]))
    transitions.start(tmp_path, other, transition_contract(other, ["other.txt"]))
    transitions.suspend(tmp_path, name, "scope: outside.txt")
    before = (tmp_path / name).read_bytes()
    other_before = (tmp_path / other).read_bytes()
    path = tmp_path / ("untracked.txt" if state == "untracked" else "outside.txt")
    path.write_text("other task change")
    if state == "staged":
        git("add", path.name)
        path.write_text(
            "original"
        )  # Worktree restoration alone leaves the index dirty.
    with pytest.raises(ValueError, match="outside task scope"):
        transitions.check_resume_scope(tmp_path, name)
    with pytest.raises(ValueError, match="outside task scope"):
        transitions.resume(tmp_path, name)
    assert (tmp_path / name).read_bytes() == before
    assert (tmp_path / other).read_bytes() == other_before
    assert path.read_text() == (
        "original" if state == "staged" else "other task change"
    )
    if state == "staged":
        assert git("diff", "--cached", "--name-only") == path.name
        git("restore", "--staged", path.name)
    elif state == "untracked":
        path.unlink()
    else:
        path.write_text("original")
    transitions.check_resume_scope(tmp_path, name)
    assert (tmp_path / name).read_bytes() == before
    with monkeypatch.context() as context:
        context.setenv(transitions.SELECTOR, name)
        with pytest.raises(ValueError, match="suspend task cannot execute"):
            TaskValidation(tmp_path, Findings(tmp_path)).check_task_scope()
    (tmp_path / name).write_text(
        before.decode().replace("## Allowed paths", "## Allowed paths\n- `extra.txt`")
    )
    (tmp_path / "extra.txt").write_text("undeclared")
    with pytest.raises(ValueError, match="not in Modified files"):
        transitions.check_resume_scope(tmp_path, name)
    (tmp_path / "extra.txt").unlink()
    (tmp_path / name).write_text(
        before.decode().replace("- [R1] `changed:owned.txt`", "")
    )
    with pytest.raises(ValueError, match="no Acceptance check"):
        transitions.check_resume_scope(tmp_path, name)
    assert transitions.status((tmp_path / name).read_text()) == "suspend"


def check_suspended_report_scope_exception(tmp_path):
    name = "tasks/report.md"
    report = "issues/dev/cde/issues.md"
    transitions.start(
        tmp_path,
        name,
        transition_contract(name, [report], kind="migration", scope="dev/cde/s3"),
    )
    transitions.suspend(tmp_path, name, "report check")
    (tmp_path / "other.txt").write_text("other task")
    before = (tmp_path / name).read_bytes()
    transitions.check_resume_scope(tmp_path, name)
    assert (tmp_path / name).read_bytes() == before
    assert (tmp_path / "other.txt").read_text() == "other task"


if __name__ == "__main__":
    raise SystemExit(run(__file__))


@pytest.fixture
def approval_task(request):
    with repository_fixture() as root:
        source = logs_fixture(root)
        if (
            getattr(getattr(request.node, "callspec", None), "params", {}).get("state")
            == "parts"
        ):
            part = source.with_suffix("") / "part-001.properties"
            part.parent.mkdir()
            part.write_bytes(source.read_bytes())
            source.write_text(
                FORMAT
                + "\n"
                + INDEX
                + "\n# part: "
                + source.stem
                + "/part-001.properties\n"
            )
        git(root, "add", "project.json", "model")
        git(root, "commit", "-qm", "existing Model")
        name = "tasks/model-acceptance.md"
        relative = source.relative_to(root).as_posix()
        transitions.start(
            root,
            name,
            transition_contract(
                name,
                ["file.txt", relative],
                kind="migration",
                scope="qa-synthetic/team-a/cloudwatch-logs",
            ),
        )
        (root / "file.txt").write_text("candidate\n")
        findings = Findings(root)
        task = TaskValidation(root, findings, contract_file=name)
        task.check_task_scope()
        assert not findings.errors
        scope = {("qa-synthetic", "team-a", "cloudwatch-logs")}
        findings.evaluate(
            "model.literal.001-002",
            scope,
            lambda: findings.input_check(
                False,
                source,
                "RetentionInDays is not a valid integer",
                location="desired.row.001-002.value",
            ),
            source_path=source,
        )
        (failure,) = findings.failures()
        dependencies = acceptance.unchanged_model_evidence(task, failure)
        record = dict(
            failure,
            task=name,
            dependencies=dependencies,
            candidate=acceptance.candidate(task, dependencies),
            assessment={
                key: "Reviewed unchanged baseline Model and producer/consumer contracts; unrelated to the file.txt goal"
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
                statement=f"Approve exclusion of {failure['diagnostic_id']} for this Task only",
            ),
        )
        yield root, task, record, source


@pytest.mark.parametrize(
    "state",
    [
        "unapproved",
        "approved",
        "registered",
        "retained",
        "parts",
        "partial",
        "candidate",
        "reason",
        "model",
        "dependency",
        "generic",
        "other-task",
        "incomplete",
    ],
)
def check_task_failure_approval(approval_task, state):
    root, task, record, source = approval_task
    if state == "generic":
        record["human_approval"]["statement"] = "続けて"
        with pytest.raises(ValueError, match="explicit Human"):
            acceptance.approve(task, [record])
        return
    if state == "other-task":
        record["task"] = "tasks/other.md"
        with pytest.raises(ValueError, match="another Task"):
            acceptance.approve(task, [record])
        return
    if state != "unapproved":
        acceptance.approve(task, [record])
        task.contract_text = (root / task.contract_file).read_text()
    if state == "partial":
        task.findings.evaluate(
            "model.second",
            task.findings.check_scope,
            lambda: task.findings.input_check(
                False, source, "second independent Model error"
            ),
            source_path=source,
        )
    elif state == "candidate":
        (root / "file.txt").write_text("changed after approval")
    elif state == "reason":
        task.findings.errors[0] = "different failure cause"
    elif state == "model":
        source.write_text(source.read_text().replace("`30`", "`999`"))
    elif state == "dependency":
        project = root / "project.json"
        project.write_text(project.read_text().replace("123456789012", "123456789013"))
    elif state == "incomplete":
        task.findings.result("required.not-started", task.findings.check_scope)
    if state == "retained":
        fresh = TaskValidation(root, Findings(root), contract_file=task.contract_file)
        fresh.check_task_scope()
        retained = fresh.acceptance()
        assert retained["status"] == "PASS" and retained["validation_status"] == "FAIL"
        assert retained["approved"][0]["retained"]
        return
    if state == "registered":
        task.acceptance_checks = [("R1", "check", record["check_id"])]
        task.check_acceptance_checks(
            {record["check_id"]: lambda: None}, {tuple(s) for s in record["scope"]}
        )
        assert task.acceptance_results
    result = task.acceptance()
    assert result["status"] == (
        "PASS" if state in {"approved", "registered", "parts"} else "FAIL"
    ), result
    assert task.findings.status == "FAIL" and result["validation_status"] == "FAIL"
    assert all(f["reason"] and f["status"] == "FAIL" for f in task.findings.failures())
    if state in {"approved", "partial", "incomplete"}:
        assert result["approved"][0]["diagnostic_id"] == record["diagnostic_id"]
    if state in {"partial", "incomplete"}:
        assert len(result["unapproved"]) == 1


def check_approval_rejects_change_regression(approval_task):
    root, task, record, source = approval_task
    source.write_text(source.read_text().replace("`30`", "`999`"))
    with pytest.raises(ValueError, match="changed Model|changed"):
        acceptance.approve(task, [record])
    assert (
        "## Out-of-task FAIL approvals" not in (root / task.contract_file).read_text()
    )


def check_completion_requires_acceptance(approval_task):
    root, task, _, _ = approval_task
    with patch.object(task_runtime, "Validator") as validator:
        validator.return_value.run.return_value = 1
        validator.return_value.report.return_value = 1
        validator.return_value.findings.failures.return_value = task.findings.failures()
        with pytest.raises(ValueError, match="Task Acceptance FAIL"):
            transitions.complete(root, task.contract_file)
    assert tasks.status((root / task.contract_file).read_text()) == "running"


def check_import_completion_skips_common_validator():
    with repository_fixture() as root:
        name = "tasks/import.md"
        text = transition_contract(
            name, ["file.txt"], kind="design", scope="dev/team/vpc"
        )
        text = text.replace(
            "## Task contract\n",
            "## Task contract\n- Workflow: `import`\n- IMPORT target: `dev/team/vpc`\n",
        )
        transitions.start(root, name, text)
        (root / "file.txt").write_text("changed", encoding="utf-8")
        with (
            patch.object(task_runtime._imports_import_guard, "require_import_changes"),
            patch.object(
                task_runtime,
                "Validator",
                side_effect=AssertionError("common Validator invoked"),
            ),
        ):
            transitions.complete(root, name)
        assert tasks.status((root / name).read_text(encoding="utf-8")) == "completed"


@pytest.mark.parametrize(
    "case", ["scope", "missing", "outside", "acceptance", "suspend"]
)
def check_import_completion_rejects_invalid_task(case):
    with repository_fixture() as root:
        name = "tasks/import.md"
        text = transition_contract(
            name, ["file.txt"], kind="design", scope="dev/team/vpc"
        )
        text = text.replace(
            "## Task contract\n",
            "## Task contract\n- Workflow: `import`\n- IMPORT target: `dev/team/vpc`\n",
        )
        if case == "scope":
            text = text.replace("- `dev/team/vpc`", "- `dev/team/vpc-endpoint`")
        transitions.start(root, name, text)
        if case != "acceptance":
            (root / "file.txt").write_text("changed", encoding="utf-8")
        if case == "outside":
            (root / "outside.txt").write_text("outside", encoding="utf-8")
        if case == "suspend":
            transitions.suspend(root, name, "synthetic failure")
        failure = ValueError("missing sealed evidence") if case == "missing" else None
        with patch.object(
            task_runtime._imports_import_guard,
            "require_import_changes",
            side_effect=failure,
        ):
            with pytest.raises(ValueError):
                transitions.complete(root, name)
        assert tasks.status((root / name).read_text()) == (
            "suspend" if case == "suspend" else "running"
        )


def check_suspended_import_guard_is_read_only():
    with repository_fixture() as root:
        name = "tasks/import.md"
        text = transition_contract(
            name, ["file.txt"], kind="design", scope="dev/team/vpc"
        )
        text = text.replace(
            "## Task contract\n",
            "## Task contract\n- Workflow: `import`\n- IMPORT target: `dev/team/vpc`\n",
        )
        transitions.start(root, name, text)
        (root / "file.txt").write_text("changed", encoding="utf-8")
        transitions.suspend(root, name, "synthetic failure")
        with patch.object(
            task_runtime._imports_import_guard, "require_import_changes"
        ) as guard:
            task_runtime.check_import(root, name, integration=True)
            guard.assert_called_once_with(root, contract_file=name)
        with pytest.raises(ValueError, match="suspend task cannot execute"):
            tasks.task_snapshot(root, name)
        assert tasks.status((root / name).read_text()) == "suspend"


@pytest.mark.parametrize("available", [True, False])
def check_import_registered_acceptance(available):
    with repository_fixture() as root:
        name = "tasks/import.md"
        text = transition_contract(
            name, ["file.txt"], kind="design", scope="dev/team/vpc"
        )
        text = text.replace(
            "## Task contract\n",
            "## Task contract\n- Workflow: `import`\n- IMPORT target: `dev/team/vpc`\n",
        )
        text = text.replace("`changed:file.txt`", "`check:framework.rule-readings`")
        transitions.start(root, name, text)
        (root / "file.txt").write_text("changed")
        handler = Mock(return_value=None)
        registered = {"framework.rule-readings": handler} if available else {}
        with (
            patch.object(task_runtime._imports_import_guard, "require_import_changes"),
            patch.object(
                task_runtime.Validator, "registered_checks", return_value=registered
            ),
        ):
            if available:
                transitions.complete(root, name)
                handler.assert_called_once()
            else:
                with pytest.raises(
                    ValueError, match="unknown registered Acceptance check"
                ):
                    transitions.complete(root, name)


@pytest.mark.parametrize("change", ["none", "candidate", "dependency", "human"])
def check_import_rechecks_approved_failures(approval_task, change):
    root, old_task, record, source = approval_task
    name = old_task.contract_file
    contract = root / name
    text = (
        contract.read_text()
        .replace("`migration`", "`design`")
        .replace(
            "## Task contract\n",
            "## Task contract\n- Workflow: `import`\n- IMPORT target: `dev/team/vpc`\n",
        )
        .replace("qa-synthetic/team-a/cloudwatch-logs", "dev/team/vpc")
    )
    contract.write_text(text)
    task = TaskValidation(root, Findings(root), contract_file=name)
    task.check_task_scope()
    record["candidate"] = acceptance.candidate(task, record["dependencies"])
    with import_scope.read_consumers({("qa-synthetic", "team-a", "cloudwatch-logs")}):
        acceptance.approve(task, [record])
    if change == "candidate":
        (root / "file.txt").write_text("changed after approval")
    elif change == "dependency":
        source.write_text(source.read_text() + "\n# changed dependency\n")
    elif change == "human":
        contract.write_text(
            contract.read_text().replace("exclude_this_task_only", "unapproved")
        )
    with patch.object(task_runtime._imports_import_guard, "require_import_changes"):
        if change == "none":
            task_runtime.check_import(root, name, integration=True)
        else:
            with pytest.raises(ValueError):
                task_runtime.check_import(root, name, integration=True)


@pytest.mark.parametrize("check", ["exists:missing.txt", "absent:file.txt"])
def check_import_path_acceptance_is_enforced(check):
    with repository_fixture() as root:
        name = "tasks/import.md"
        text = transition_contract(
            name, ["file.txt"], kind="design", scope="dev/team/vpc"
        )
        text = text.replace(
            "## Task contract\n",
            "## Task contract\n- Workflow: `import`\n- IMPORT target: `dev/team/vpc`\n",
        )
        text = text.replace("changed:file.txt", check)
        transitions.start(root, name, text)
        (root / "file.txt").write_text("changed")
        with patch.object(task_runtime._imports_import_guard, "require_import_changes"):
            with pytest.raises(
                ValueError, match="required path missing|forbidden path exists"
            ):
                transitions.complete(root, name)
        assert tasks.status((root / name).read_text()) == "running"
