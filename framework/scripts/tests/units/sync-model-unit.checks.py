#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, nullcontext
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import io
import threading
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

import import_guard
import model.validation as model_validation
import pytest
import sync_progress as progress
import sync_runtime
import sync_views
import task_contract_runtime
import utils.aws_mappings as aws_mappings
import utils.aws_schemas as aws_schemas
import utils.input_cache as _imports_input_cache
import validation.design_links as _imports_validation_design_links
from design.catalog import property_paths_with_parents
from model.format import serialize
from model.identity import COUNTERS
from model.sources import runtime_values
from support.issues_scan_fixtures import task as issue_task
from support.pytest_cli import run
from support.validator import load
from sync_files import changed_files, markdown_newlines
from task_contract_core import selected_task
from utils.aws_mappings import definition_root, mapping_alias
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.input_cache import (
    input_bytes,
    input_context,
    input_scope,
    memo_table,
    recording_inputs,
)
from utils.script_loader import module
from validation.findings import CheckResult, Findings
from validation.task import TaskValidation
from validation_cache import PassCache

from model import projection

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

_CALLBACK_DEFAULT = object()


def check_property_path_parents():
    paths = {
        "ConnectionInput.PhysicalConnectionRequirements.SubnetId",
        "Rules[].Target.Name",
        "ConnectionInputName",
    }
    assert property_paths_with_parents(paths) == {
        *paths,
        "ConnectionInput",
        "ConnectionInput.PhysicalConnectionRequirements",
        "Rules",
        "Rules[]",
        "Rules[].Target",
    }
    assert "ConnectionInput" not in property_paths_with_parents({"ConnectionInputName"})
    assert not property_paths_with_parents(set())


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("final", [False, True])
def check_markdown_newlines(tmp_path, newline, final):
    path = tmp_path / "design.md"
    expected = ("# 日本語" + newline + "value" + (newline if final else "")).encode(
        "utf-8"
    )
    path.write_bytes(expected)
    assert markdown_newlines(path, "# 日本語\nvalue\n").encode() == expected
    assert changed_files({path: "# 日本語\nvalue\n"}) == {}
    assert set(changed_files({path: "# 日本語\nchanged\n"})) == {path}
    path.write_bytes(b"one\r\ntwo\n")
    with pytest.raises(ValueError, match="mixed Markdown newlines"):
        markdown_newlines(path, "one\ntwo\n")
    path.write_bytes(b"one\rtwo")
    with pytest.raises(ValueError, match="unsupported Markdown newline"):
        markdown_newlines(path, "one\ntwo\n")


def _callback_check_internal_sync_concurrent_output_execute(
    barrier, reports, /, root, write, **kwargs
):
    memo = memo_table()
    memo["root"] = root
    reports.append(progress._current.get()[0])
    barrier.wait()
    assert memo == {"root": root}
    print(str(root), file=progress.output_file())
    with progress.phase("isolated-heartbeat"):
        reporter = progress._current.get()[0]
        with patch.object(reporter.stop, "wait", side_effect=[False, True]):
            reporter.heartbeat()
    raise ValueError("invalid generation at " + str(root))


def check_internal_sync_concurrent_output(tmp_path, capsys):
    runner = module("sync-model.py", "blueprint_sync_model")
    barrier = threading.Barrier(2, timeout=10)
    reports = []
    execute = (input_scope)(
        _bind_framework_callback(
            _callback_check_internal_sync_concurrent_output_execute, barrier, reports
        )
    )
    roots = [tmp_path / "first", tmp_path / "second"]
    with (
        patch.object(runner, "sync", side_effect=execute),
        ThreadPoolExecutor(2) as executor,
    ):
        futures = [
            executor.submit(runner.run, ["--all"], repository_root=root)
            for root in roots
        ]
        results = [future.result() for future in futures]
    for root, other, (code, text) in zip(roots, reversed(roots), results, strict=False):
        assert code == 1 and str(root) in text and str(other) not in text
        assert "heartbeat" in text and "invalid generation at" in text
    assert len({id(report) for report in reports}) == 2
    assert all(report.stop.is_set() and not report.states for report in reports)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "arguments,code,diagnostic",
    [
        (["--help"], 0, "usage:"),
        (["--jobs", "3"], 2, "invalid choice"),
        (["--environment", "dev"], 2, "exactly one"),
        (["--scope", "../team/config"], 1, "invalid generation scope"),
    ],
)
def check_internal_sync_arguments(tmp_path, arguments, code, diagnostic, capsys):
    runner = module("sync-model.py", "blueprint_sync_model")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks/example.md").write_text(
        "## Task contract\n- Task type: `governance`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n## Validation scope\n- `all`\n"
    )
    result, text = runner.run(arguments, repository_root=tmp_path)
    assert result == code and diagnostic in text, text
    assert progress._current.get() is None and progress._output.get() is None
    assert capsys.readouterr() == ("", "")


def _callback_check_progress_heartbeat_and_waits_ReleasedLock_release(self, lock, /):
    lock.release()


class ReleasedLock:
    def __init__(self, lock, acquire):
        self.lock = lock
        self.original_acquire = acquire

    def acquire(self, blocking=True):
        if not blocking:
            return False
        self.lock.release()
        return self.original_acquire()

    def release(self):
        self.lock.release()


def check_progress_heartbeat_and_waits():
    output = io.StringIO()
    reporter = progress.Progress(interval=0.01)
    with redirect_stderr(output), reporter.worker("dev/team/iam"):
        progress.consumers({("dev", "team", "iam")})
        with progress.phase("dependency-model", total=2):
            progress.advance()
            # Trigger exactly one heartbeat without sleeping or changing production interval.
            with patch.object(reporter.stop, "wait", side_effect=[False, True]):
                reporter.heartbeat()
        lock = threading.Lock()
        lock.acquire()
        original_acquire = lock.acquire
        with progress.thread_lock(ReleasedLock(lock, original_acquire)):
            pass
        with progress.phase("generation", status="running"):
            pass
        progress.completed(("dev", "team", "iam"))
        with pytest.raises(ValueError), progress.phase("candidate-validation"):
            raise ValueError("injected")
    text = output.getvalue()
    for expected in [
        "heartbeat",
        "items=1/2",
        "completed=1/1",
        "lock-wait",
        "stage-failed",
        "remaining=unknown",
        "not proof of progress",
    ]:
        assert expected in text
    assert reporter.states == []


@pytest.mark.parametrize(
    "filename,mutation",
    [
        (None, None),
        ("entry", "change"),
        ("entry", "delete"),
        ("part", "change"),
        ("part", "delete"),
        ("other-model", "change"),
        ("other-model", "delete"),
        ("part", "add"),
        ("other-model", "add"),
        ("sidecar", "add"),
        ("task", "add"),
        ("sidecar", "change"),
        ("task", "change"),
    ],
)
def check_snapshot_conflict(tmp_path, filename, mutation):
    if filename is None:
        input_bytes = _imports_input_cache.input_bytes
        input_is_file = _imports_input_cache.input_is_file
        input_select = _imports_input_cache.input_select
        recording_inputs = _imports_input_cache.recording_inputs
        snapshot = sync_runtime.GenerationInputs(tmp_path)
        path = tmp_path / "project.json"
        assert snapshot.read(path) is None
        with pytest.raises(ValueError, match="inputs changed while reading"):
            snapshot.record(path, b"different")
        with pytest.raises(ValueError, match="inputs changed before publication"):
            snapshot.verify()
        snapshot.close()
        snapshot = sync_runtime.GenerationInputs(tmp_path)
        with recording_inputs(snapshot):
            assert not input_is_file(path)
            with pytest.raises(FileNotFoundError):
                input_bytes(path)
            assert input_select(tmp_path, "*.json") == ()
            snapshot.seal()
            path.write_bytes(b"new")
            assert not input_is_file(
                path
            )  # Sealed reads retain the recorded missing state.
            with pytest.raises(ValueError, match="after seal"):
                snapshot.read(tmp_path / "new-dependency")
            with pytest.raises(ValueError, match="inputs changed before publication"):
                snapshot.verify()
        snapshot.close()
        return

    paths = {
        "entry": "model/dev/team/iam.properties",
        "part": "model/dev/team/iam/part-001.properties",
        "other-model": "model/stg/team/kms.properties",
        "sidecar": "docs/designs/dev/team/iam/policy.json",
        "task": "tasks/concurrent.md",
    }
    target = tmp_path / paths[filename]
    target.parent.mkdir(parents=True, exist_ok=True)
    if mutation != "add":
        target.write_bytes(
            b"## Task contract\n- Task type: `governance`\n- Task status: `running`\n"
            b"## Modified files\n- `tasks/concurrent.md`\n"
            b"## Allowed paths\n- `tasks/concurrent.md`\n## Validation scope\n- `framework`\n"
            if filename == "task"
            else b"original\r\n"
        )
    snapshot = sync_runtime.GenerationInputs(tmp_path)
    try:
        if filename == "task" and mutation != "add":
            assert target in snapshot.contents, (
                "Task capture belongs to snapshot construction"
            )
        original = None if mutation == "add" else snapshot.read(target)
        if filename != "task":
            base = tmp_path / ("docs/designs" if filename == "sidecar" else "model")
            snapshot.select(base, "*", recursive=True)
        snapshot.seal()
        snapshot.verify()
        if mutation == "delete":
            target.unlink()
        else:
            target.write_bytes(b"concurrent\n")
        with pytest.raises(
            ValueError, match="inputs changed before publication"
        ) as error:
            snapshot.verify()
        assert target.relative_to(tmp_path).as_posix() in str(error.value)
        if mutation == "add":
            assert target not in snapshot.contents
        else:
            assert snapshot.read(target) == original
        assert (
            not target.exists()
            if mutation == "delete"
            else target.read_bytes() == b"concurrent\n"
        )
    finally:
        snapshot.close()


@pytest.mark.parametrize("mutation", ["change", "delete"])
def check_snapshot_project_common_inputs(tmp_path, mutation):
    root, definitions = tmp_path / "repo", tmp_path / "definitions"
    project = root / "project.json"
    project.parent.mkdir()
    project.write_bytes(b"{}")
    distributed = definitions / "README.md"
    distributed.parent.mkdir()
    distributed.write_bytes(b"distributed")
    framework = definitions / "framework/mapping.json"
    framework.parent.mkdir()
    framework.write_bytes(b"{}")
    snapshot = sync_runtime.GenerationInputs(root, definitions)
    cache = PassCache(root, definitions_root=definitions)
    with patch.object(snapshot, "live_select", wraps=snapshot.live_select) as select:
        cache.common_key(snapshot=snapshot)
        cache.common_key(snapshot=snapshot)
        assert select.call_count == 1
    with recording_inputs(snapshot):
        assert input_bytes(framework) == b"{}"
    assert snapshot.read(project) == b"{}"
    assert framework not in snapshot.contents and distributed not in snapshot.contents
    snapshot.seal()
    snapshot.verify()
    if mutation == "delete":
        project.unlink()
    else:
        project.write_bytes(b'{"changed": true}')
    with pytest.raises(ValueError, match="inputs changed before publication") as error:
        snapshot.verify()
    assert "project.json" in str(error.value) and snapshot.read(project) == b"{}"
    assert (
        not project.exists()
        if mutation == "delete"
        else project.read_bytes() == b'{"changed": true}'
    )
    snapshot.close()


def check_planned_outputs_and_boundary(tmp_path):
    path, created = tmp_path / "view.md", tmp_path / "new.json"
    path.write_bytes(b"original\r\n")
    snapshot = sync_runtime.GenerationInputs(tmp_path)
    expected = {path: markdown_newlines(path, "original\n"), created: "{}\n"}
    plan = SimpleNamespace(expected_outputs={path: expected}, snapshot=snapshot)
    assert sync_runtime.planned_outputs(plan) == {created}
    expected[path] = markdown_newlines(path, "changed\n")
    assert sync_runtime.planned_outputs(plan) == {path, created}
    findings = Findings(tmp_path)
    task = TaskValidation(tmp_path, findings)
    task.task_type = "scenario-test"
    task.changed_paths = {"tests/scenarios/allowed/scenario.md"}
    task.check_task_boundary(tmp_path / "tasks/test.md")
    assert not findings.errors
    task.check_task_boundary(
        tmp_path / "tasks/test.md", {"docs/designs/dev/team/iam.md"}
    )
    assert (
        len(findings.errors) == 1
        and "scenario-test task boundary" in findings.errors[0]
    )
    assert task.changed_paths == {"tests/scenarios/allowed/scenario.md"}
    snapshot.close()


def _callback_check_stage_dependency_selection_loaded(
    authority, inputs, values, /, path, read_context=None
):
    assert read_context is None or read_context is inputs
    return SimpleNamespace(
        values=values,
        files={authority: input_bytes(authority).decode()},
        dependencies={authority: input_bytes(authority)},
    )


@pytest.mark.parametrize("write", [False, True])
def check_stage_dependency_selection(tmp_path, write):
    root, stage = tmp_path / "root", tmp_path / "stage"
    _ = root / "docs/designs/dev/team/iam.md"
    files = {
        "docs/designs/dev/team/iam.md": "# selected\n",
        "docs/designs/dev/team/iam/policy.json": "{}\n",
        "docs/designs/dev/team/other.md": "# unrelated\n",
        "docs/designs/dev/team/out.md": "# reference\n",
        "docs/designs/dev/team/in.md": "<!-- reference-rows: obsolete -->\n[incoming](iam.md#id)\n",
        "model/dev/team/iam.properties": "# model-format: 2\n# required\n",
        "model/dev/team/unrelated.properties": "# model-format: 2\n# unused\n",
        "project.json": "{}\n",
        "tests/results/unrelated.log": "unrelated\n",
    }
    for relative, text in files.items():
        file = root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    model = root / "model/dev/team/iam.properties"
    authority = root / "model/dev/team/iam.properties"
    inputs = sync_runtime.GenerationInputs(root)
    # Caller-owned snapshots are reused, including readers, without inner cleanup.
    values = {"link": "[out](out.md#id)"}
    loaded = _bind_framework_callback(
        _callback_check_stage_dependency_selection_loaded, authority, inputs, values
    )
    inputs.stage = stage
    with (
        patch.object(
            sync_runtime.GenerationInputs,
            "__init__",
            side_effect=AssertionError("duplicate recorder"),
        ),
        patch.object(inputs, "close", wraps=inputs.close) as close,
        patch(
            "validation_cache.PassCache.common_inputs",
            side_effect=AssertionError("duplicate common registration"),
        ),
        patch.object(sync_runtime, "registered_models", return_value=[model]),
        patch.object(
            sync_runtime,
            "model_exists",
            side_effect=lambda path, read_context: path == authority
            and read_context is inputs,
        ),
        patch.object(sync_runtime, "load_model", side_effect=loaded),
        patch.object(sync_runtime, "generate_views", return_value={}),
    ):
        plan = sync_runtime.prepare_generation(
            root, {("dev", "team", "iam")}, snapshot=inputs, write=write
        )
        assert bool(plan.baseline_links) == write
        plan.close()
        assert not close.called
    assert inputs.contents[authority] == b"# model-format: 2\n# required\n"
    present = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()}
    excluded = {
        "docs/designs/dev/team/other.md",
        "model/dev/team/unrelated.properties",
        "tests/results/unrelated.log",
    }
    if not write:
        excluded.add("docs/designs/dev/team/in.md")
    assert present == set(files) - excluded
    assert root / "tests/results/unrelated.log" not in inputs.contents
    inputs.close()


@pytest.mark.parametrize("write", [False, True])
def check_linked_attachments(tmp_path, write):
    check_design_links = _imports_validation_design_links.check_design_links
    root, stage = tmp_path / "root", tmp_path / "stage"
    design = root / "docs/designs/dev/team/service.md"
    reference = design.with_name("reference.md")
    payloads = {
        design.parent / "service/code.zip": b"PK\x03\x04\x00\xff\x80",
        design.parent / "service/nested/requirements.txt": b"package==1\r\n",
        design.parent / "shared/opaque": b"\x00\xfe",
        design.parent / "reference/attachment.bin": b"\x81\x00",
        design.parent / "service/extra.json": b"{}\n",
    }
    for path, data in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    saved = "[zip](service/code.zip) [txt](service/nested/requirements.txt)\n"
    design.write_text(saved, encoding="utf-8")
    reference.write_text("[attachment](reference/attachment.bin)\n", encoding="utf-8")
    values = {
        "note": saved + "[opaque](shared/opaque) [reference](reference.md) "
        "[missing](service/missing.txt) [web](https://example.com/file.zip)"
    }
    unrelated = design.parent / "service/unreferenced.bin"
    unrelated.write_bytes(b"unused")
    snapshot = sync_runtime.GenerationInputs(root) if write else None
    if snapshot:
        snapshot.stage = stage
    try:
        with recording_inputs(snapshot) if write else nullcontext():
            with (
                patch.object(sync_runtime, "registered_models", return_value=[]),
                patch.object(sync_views, "broken_design_links", return_value={}),
            ):
                sync_runtime.stage_inputs(
                    stage,
                    root,
                    {design: values},
                    [],
                    [design],
                    ["service"],
                    write,
                    snapshot,
                )
            for path, data in payloads.items():
                assert (stage / path.relative_to(root)).read_bytes() == data
            assert not (stage / unrelated.relative_to(root)).exists()
            staged = stage / design.relative_to(root)
            staged.write_text(values["note"], encoding="utf-8")
            findings = Findings(stage)
            check_design_links(
                {},
                [staged],
                design_sources={staged: {}},
                findings=findings,
                root=stage,
                scope=None,
            )
            assert (
                len(findings.errors) == 1 and "broken design link" in findings.errors[0]
            ), findings.errors
            assert "service/missing.txt" in findings.errors[0]
            generated = staged.with_suffix("") / "generated.json"
            generated.write_bytes(b"{}")
            sync_runtime.restore_view(stage, root, design)
            assert staged.read_bytes() == design.read_bytes()
            assert not generated.exists()
            for path, data in payloads.items():
                assert (stage / path.relative_to(root)).read_bytes() == data
            findings = Findings(stage)
            check_design_links(
                {},
                [staged],
                design_sources={staged: {}},
                findings=findings,
                root=stage,
                scope=None,
            )
            assert not findings.errors, findings.errors
            if snapshot:
                snapshot.seal()
                snapshot.verify()
                attachment = design.parent / "service/code.zip"
                attachment.write_bytes(b"changed")
                with pytest.raises(
                    ValueError, match="inputs changed before publication"
                ):
                    snapshot.verify()
    finally:
        if snapshot:
            snapshot.close()


def _callback_check_final_git_paths_git_paths(
    baseline, calls, committed, final, index, /, args
):
    calls.append(args)
    if args[0] == "ls-files":
        return final if "--cached" in args else set()
    if "--cached" in args:
        return index
    if "HEAD" in args:
        return committed
    return final if baseline in args else set()


@pytest.mark.parametrize(
    "baseline,final,index,committed",
    [
        ("start", {"view.md"}, set(), {"view.md"}),
        ("start", set(), {"view.md"}, {"view.md"}),
        ("start", set(), {"view.md"}, set()),
        (None, {"new.md"}, {"new.md"}, set()),
    ],
)
def check_final_git_paths(tmp_path, baseline, final, index, committed):
    task = TaskValidation(tmp_path, Findings(tmp_path))
    task.baseline, task.baseline_fixed = baseline, True
    if baseline is None:
        (tmp_path / "new.md").write_bytes(b"exists")
    calls = []
    git_paths = _bind_framework_callback(
        _callback_check_final_git_paths_git_paths,
        baseline,
        calls,
        committed,
        final,
        index,
    )
    task.git_paths = git_paths
    assert task.final_paths() == final
    assert all("--cached" not in call for call in calls if call[0] == "diff")
    # Permission scope preserves the independent index change.
    task.permission_paths = index | committed
    task.changed_paths = final
    task.acceptance_checks = [("R1", "changed", "view.md")]
    task.check_acceptance_checks({})
    assert bool(task.acceptance_results) == ("view.md" in final)


def check_git_baseline_fail_closed(tmp_path):
    task = TaskValidation(tmp_path, Findings(tmp_path))
    args = ["diff", "--name-only", "-z", "baseline", "--"]
    with patch("validation.task.read_paths", return_value={"file.txt"}) as read:
        assert task.git_paths(args) == {"file.txt"}
    read.assert_called_once_with(tmp_path, *args)
    error = ValueError("git failed")
    with (
        patch("validation.task.read_paths", side_effect=error),
        pytest.raises(ValueError) as caught,
    ):
        task.git_paths(args)
    assert caught.value is error


def _scope_git_paths(args):
    if args[0] == "ls-files":
        return (
            {"present.txt", "missing.txt", "broken-link", ".lock"}
            if "--cached" in args
            else {"new.txt", ".lock"}
        )
    if "--cached" in args:
        return {"index.txt", ".lock"}
    if "HEAD" in args:
        return {"committed.txt", ".lock"}
    return {"final.txt", ".lock"} if "start" in args else {"working.txt", ".lock"}


@pytest.mark.parametrize(
    "mode,count,final,permission",
    [
        (
            "baseline",
            5,
            {"final.txt", "new.txt"},
            {"working.txt", "index.txt", "new.txt", "committed.txt"},
        ),
        ("issues", 0, set(), set()),
        (
            "unborn",
            4,
            {"present.txt", "broken-link", "new.txt"},
            {"working.txt", "index.txt", "new.txt"},
        ),
        ("candidate", 0, {"candidate.txt", ".lock"}, {"candidate.txt", ".lock"}),
    ],
)
def check_scope_git_collection(tmp_path, mode, count, final, permission):
    candidate = (
        SimpleNamespace(base_commit="start", changed_paths=final)
        if mode == "candidate"
        else None
    )
    task = TaskValidation(tmp_path, Findings(tmp_path), final_candidate=candidate)
    task.baseline, task.baseline_fixed = ("start" if mode == "baseline" else None), True
    task.issues_only = mode == "issues"
    (tmp_path / "present.txt").write_text("exists")
    with (
        patch.object(task, "git_paths", side_effect=_scope_git_paths) as paths,
        patch.object(
            Path,
            "is_symlink",
            autospec=True,
            side_effect=lambda path: path.name == "broken-link",
        ),
        patch("validation.task.task_path", return_value=None),
    ):
        task.check_task_scope()
        assert paths.call_count == count
        assert task.changed_paths == final and task.permission_paths == permission
        assert task.changed_paths is not task.permission_paths
        assert task.findings.errors == (
            []
            if mode == "issues"
            else ["selected task contract missing while repository has changes"]
        )
        paths.reset_mock()
        task.check_task_scope()  # A second validation must collect again.
        assert paths.call_count == count
    if mode == "candidate":
        task.changed_paths.clear()
        assert candidate.changed_paths == final and task.permission_paths == permission


def check_issue_task_ignores_other_task_git_changes(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "fixture@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Fixture"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-qm", "initial"],
        check=True,
    )
    with issue_task(tmp_path, ["s3"]):
        contract = tmp_path / "tasks/save.md"
        contract.write_text(
            contract.read_text() + "\n## Required changes\n- [R1] Save reports\n"
            "\n## Acceptance checks\n- [R1] `exists:issues/dev/123456789012/issues.md`\n"
        )
        report = tmp_path / "issues/dev/123456789012/issues.md"
        report.parent.mkdir(parents=True)
        report.write_text("未解決issueなし")
        for relative in ("model/dev/123456789012/s3.properties", "infra/app.yaml"):
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("other Task input")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "model", "infra"], check=True
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-qm", "other Task advanced HEAD"],
            check=True,
        )
        (tmp_path / "model/dev/123456789012/s3.properties").write_text(
            "other staged change"
        )
        subprocess.run(["git", "-C", str(tmp_path), "add", "model"], check=True)
        (tmp_path / "infra/app.yaml").write_text("other unstaged change")
        (tmp_path / "other-untracked").write_text("other new file")
        task = TaskValidation(tmp_path, Findings(tmp_path))
        with (
            selected_task(tmp_path, "tasks/save.md"),
            patch(
                "validation.task.collect_working_paths",
                side_effect=AssertionError("Issue must not collect Git changes"),
            ),
            patch.object(
                task,
                "git_paths",
                side_effect=AssertionError("Issue must not inspect Git paths"),
            ),
        ):
            task.check_task_scope()
            task.check_acceptance_checks({})
            assert task.changed_paths == task.permission_paths == set()
            assert not task.findings.errors, task.findings.errors
            task_contract_runtime.complete(tmp_path, "tasks/save.md")
        assert "- Task status: `completed`" in contract.read_text()
        assert (tmp_path / "infra/app.yaml").read_text() == "other unstaged change"


def add_other_issue_task(root):
    (root / "tasks/other.md").write_text(
        "## Task contract\n- Task type: `migration`\n- Task status: `completed`\n"
        "## Modified files\n- `tasks/other.md`\n## Allowed paths\n- `tasks/other.md`\n"
    )


def check_issue_validation_ignores_contract_catalog_changes(tmp_path):
    with issue_task(tmp_path, ["s3"]):
        contract = tmp_path / "tasks/save.md"
        contract.write_text(
            contract.read_text() + "\n## Required changes\n- [R1] Save report\n"
            "\n## Acceptance checks\n- [R1] `exists:issues/dev/123456789012/issues.md`\n"
        )
        report = tmp_path / "issues/dev/123456789012/issues.md"
        report.parent.mkdir(parents=True)
        report.write_text("未解決issueなし")
        validator = load("validate-blueprint").Validator(tmp_path, set(), cache=True)
        methods = (
            "check_structure",
            "check_project_topology",
            "check_validation_scope",
            "check_model_files",
            "check_initialized_paths",
            "check_resource_layout",
            "check_iac_selection",
        )
        with (
            selected_task(tmp_path, "tasks/save.md"),
            patch.multiple(
                validator, **dict.fromkeys(methods, Mock(return_value=None))
            ),
            patch.object(
                validator,
                "check_catalog",
                side_effect=_bind_framework_callback(add_other_issue_task, tmp_path),
            ),
        ):
            assert validator.run() == 0, validator.errors
        assert validator.cache is None and len(validator.acceptance_results) == 1


@pytest.mark.parametrize("scope,contract_scope", [(set(), None), (None, set())])
def check_framework_write_does_not_discover(tmp_path, scope, contract_scope):
    module = load("validate-blueprint")
    with (
        patch.object(Path, "rglob", side_effect=AssertionError("Model discovery")),
        patch.object(
            sync_runtime,
            "prepare_generation",
            side_effect=AssertionError("Model generation"),
        ),
    ):
        validator = module.Validator(tmp_path, scope, contract_scope, write=True)
        assert validator.run() == 1
        assert "framework scope" in validator.errors[0]


@pytest.mark.parametrize("inventory", ["### iam\n1. 未解決Issue\n", "未解決issueなし"])
@pytest.mark.parametrize("outcome", ["success", "partial", "not_run", "common"])
def check_integrated_generation_with_issues(tmp_path, inventory, outcome, capsys):
    good = tmp_path / "docs/designs/dev/123456789012/iam.md"
    rejected = good.with_name("kms.md")
    good.parent.mkdir(parents=True)
    good.write_bytes(b"old IAM\n")
    rejected.write_bytes(b"old KMS\n")
    issue = tmp_path / "issues/dev/123456789012/issues.md"
    issue.parent.mkdir(parents=True)
    issue.write_text(inventory, encoding="utf-8")
    scope = {("dev", "123456789012", service) for service in ("iam", "kms")}
    outputs = [path.relative_to(tmp_path).as_posix() for path in (good, rejected)]
    with (
        issue_task(tmp_path, ["iam", "kms"], allowed=outputs),
        closing(sync_runtime.GenerationInputs(tmp_path)) as snapshot,
    ):
        stage = snapshot.open_stage()
        staged = stage / good.relative_to(tmp_path)
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"new IAM\n")
        plan = sync_runtime.Generation(
            tmp_path, stage, scope, [], [good, rejected], snapshot, ExitStack()
        )
        plan.baseline_links, plan.saved_paths = {}, [good, rejected]
        plan.generated = {good: [staged]}
        plan.expected_outputs = {good: {good: "new IAM\n"}}
        snapshot.read(good)
        snapshot.read(rejected)
        if outcome == "success":
            second = stage / rejected.relative_to(tmp_path)
            second.write_bytes(b"new KMS\n")
            plan.generated[rejected] = [second]
            plan.expected_outputs[rejected] = {rejected: "new KMS\n"}
        elif outcome == "partial":
            sync_runtime.generation_failure(
                tmp_path,
                plan.failure_records,
                "generation.render",
                rejected,
                f"{rejected.relative_to(tmp_path)}: missing required property",
            )
        elif outcome == "not_run":
            plan.unavailable[rejected] = {
                "reason": "reference",
                "status": "NOT_RUN",
                "retainedView": str(rejected),
            }
        common = Findings(stage)
        common.result("framework.policy-tables", plan.generated_scope).status = "PASS"
        plan.validation[None] = common
        validator = load("validate-blueprint").Validator(tmp_path, scope, write=True)
        validator.task_type = "migration"
        validator.task.contract_text = snapshot.expected_task[1]
        validator.changed_paths = set(outputs)
        methods = (
            "check_structure",
            "check_task_scope",
            "check_project_topology",
            "check_validation_scope",
            "check_initialized_paths",
            "check_catalog",
            "check_resource_layout",
            "check_iac_selection",
            "check_task_boundary",
            "check_task_type_requirements",
            "check_acceptance_checks",
        )
        with ExitStack() as patches, recording_inputs(snapshot):
            patches.enter_context(patch.object(validator.task, "check_task_scope"))
            patches.enter_context(
                patch.object(validator.task, "final_paths", return_value=set(outputs))
            )
            for method in methods:
                patches.enter_context(patch.object(validator, method))
            if outcome == "common":
                patches.enter_context(
                    patch.object(
                        validator,
                        "check_structure",
                        side_effect=_bind_framework_callback(
                            validator.check, False, "common integrity error"
                        ),
                    )
                )
            prepare = patches.enter_context(
                patch.object(sync_runtime, "prepare_generation", return_value=plan)
            )
            patches.enter_context(patch.object(sync_runtime, "validate_generation"))
            result = validator._run(snapshot)
        assert result == int(outcome != "success"), validator.errors
        assert good.read_bytes() == (
            b"old IAM\n" if outcome == "common" else b"new IAM\n"
        )
        assert rejected.read_bytes() == (
            b"new KMS\n" if outcome == "success" else b"old KMS\n"
        )
        assert prepare.call_count == (0 if outcome == "common" else 1)
        assert issue.read_text(encoding="utf-8") == inventory
        assert (
            issue not in snapshot.contents
        )  # Issue reports are outside the sealed generation inputs.
        output = capsys.readouterr().out
        if outcome == "success":
            assert (
                "2 services succeeded; 0 services failed; 0 services NOT_RUN" in output
            )
        elif outcome == "partial":
            assert (
                "1 services succeeded; 1 services failed; 0 services NOT_RUN" in output
            )
            assert any(
                "kms.md: missing required property" in error
                for error in validator.errors
            )
        elif outcome == "not_run":
            assert (
                "1 services succeeded; 0 services failed; 1 services NOT_RUN" in output
            )
            assert any(
                "NOT_RUN: docs/designs/dev/123456789012/kms.md: reference" in error
                for error in validator.errors
            )


def check_reference_not_run_is_not_generation_pass(tmp_path, capsys):
    view = tmp_path / "docs/designs/dev/team/iam.md"
    plan = sync_runtime.Generation(
        tmp_path,
        tmp_path / "stage",
        {("dev", "team", "iam")},
        [],
        [view],
        None,
        ExitStack(),
    )
    plan.baseline_links = {}
    plan.unavailable[view] = {
        "reason": "reference",
        "status": "NOT_RUN",
        "retainedView": None,
    }
    with (
        patch.object(sync_runtime, "prepare_generation", return_value=plan),
        patch.object(sync_runtime, "validate_generation"),
        patch.object(sync_runtime, "publish_generation"),
    ):
        with pytest.raises(
            ValueError,
            match="0 services succeeded; 0 services failed; 1 services NOT_RUN",
        ):
            sync_runtime.run_generation(tmp_path, plan.scope)
    output = capsys.readouterr().out
    assert "Design Markdown sync: PASS" not in output


def _callback_check_result_reuse_is_scoped_fail(calls, findings, /):
    calls.append("fail")
    findings.check(False, "content failed")


def check_result_reuse_is_scoped(tmp_path):
    findings = Findings(tmp_path)
    task = TaskValidation(tmp_path, findings)
    first, second = {("dev", "team", "iam")}, {("stg", "team", "iam")}
    calls = []
    fail = _bind_framework_callback(
        _callback_check_result_reuse_is_scoped_fail, calls, findings
    )
    task.acceptance_checks = [("R1", "check", "content"), ("R2", "check", "content")]
    findings.evaluate("content", first, fail)
    task.check_acceptance_checks({"content": fail}, first)
    assert calls == ["fail"] and not task.acceptance_results
    task.acceptance_checks = [("R3", "check", "content")]
    task.check_acceptance_checks(
        {"content": lambda: calls.append("other scope")}, second
    )
    assert calls[-1] == "other scope" and len(task.acceptance_results) == 1
    key = ("content", frozenset(first), object())
    findings.candidate = key[2]
    findings.results[key] = CheckResult(*key)
    task.check_acceptance_checks({"content": lambda: calls.append("not run")}, first)
    assert calls[-1] == "not run"
    stack = findings.result("design.stacks", first)
    stack.status, stack.metadata = "PASS", {"stack_definitions": {"candidate": []}}
    findings.bind_candidate(object(), set())
    stale = findings.result("design.stacks", first)
    assert stale.status == "NOT_RUN" and stale.metadata == {}


def _callback_check_resource_row_reuse_and_edits_rows_444(
    _default_mapping,
    _default_identity,
    /,
    mapping=_CALLBACK_DEFAULT,
    identity=_CALLBACK_DEFAULT,
):
    if mapping is _CALLBACK_DEFAULT:
        mapping = _default_mapping
    if identity is _CALLBACK_DEFAULT:
        identity = _default_identity
    return projection.resource_rows(mapping, identity, "IAM.Role", Path("/synthetic"))


def check_resource_row_reuse_and_edits():
    values = {
        f"desired.row.role-001.{key}": value
        for key, value in dict(
            property="IAM.Role.Description", value="first", comment="fixture"
        ).items()
    }
    rows = _bind_framework_callback(
        _callback_check_resource_row_reuse_and_edits_rows_444, values, "role"
    )
    with (
        input_context(),
        patch.object(projection, "catalog_outputs", return_value=set()),
        patch.object(projection, "entries", wraps=projection.entries) as parse,
    ):
        with projection.resource_row_scope():
            assert parse.call_count == 0  # Lazy, even for an empty generation.
            first = rows()
            first[0][2] = "caller edit"
            first.clear()
            assert rows()[0][2] == "first" and parse.call_count == 1
            other = dict(values)
            assert rows(other) == rows() and parse.call_count == 2
            values["desired.row.role-001.value"] = "edited"
            assert rows()[0][2] == "edited" and parse.call_count == 3
            for key, value in dict(
                property="IAM.Role.Path", value="/fixture/", comment="added"
            ).items():
                values[f"desired.row.role-002.{key}"] = value
            assert len(rows()) == 2 and parse.call_count == 4
            del values["desired.row.role-002.comment"]
            with pytest.raises(ValueError, match="invalid resource row: role-002"):
                rows()
            for key in list(values):
                if key.startswith("desired.row.role-002."):
                    del values[key]
            assert len(rows()) == 1 and parse.call_count == 6
            values["observed.row.role-001.value"] = "invalid observation"
            with pytest.raises(ValueError, match="observed value requires"):
                rows()
            del values["observed.row.role-001.value"]
            assert rows()[0][2] == "edited"
            # Reordering an otherwise identical mapping must also invalidate it.
            key = next(iter(values))
            values[key] = values.pop(key)
            before = parse.call_count
            rows()
            assert parse.call_count == before + 1
            values.clear()
            assert rows() == []
            before = parse.call_count
            assert rows() == [] and parse.call_count == before
        assert projection._resource_row_cache.get() is None
        with projection.resource_row_scope():
            rows()
            assert parse.call_count == before + 1


def check_resource_row_legacy_and_invalid_entries():
    values = {}
    for identity in ("legacy-001", "legacy-child-001", "legacyish-001"):
        values.update(
            {
                f"desired.row.{identity}.{key}": value
                for key, value in dict(
                    property="IAM.Role.Description", value=identity, comment="fixture"
                ).items()
            }
        )
    with (
        patch.object(projection, "catalog_outputs", return_value=set()),
        projection.resource_row_scope(),
    ):
        rows = projection.resource_rows(
            values, "legacy", "IAM.Role", Path("/synthetic")
        )
        assert [row[0] for row in rows] == ["legacy-001", "legacy-child-001"]
        # An unrelated malformed row is validated only when its resource is requested.
        values["desired.row.unrelated-001.extra"] = "invalid"
        assert (
            projection.resource_rows(values, "legacy", "IAM.Role", Path("/synthetic"))
            == rows
        )
        with pytest.raises(ValueError, match="invalid resource row: unrelated-001"):
            projection.resource_rows(
                values, "unrelated", "IAM.Role", Path("/synthetic")
            )
        values["desired.row.missing-field"] = "invalid entry"
        with pytest.raises(
            ValueError, match="invalid model entry: desired.row.missing-field"
        ):
            projection.resource_rows(values, "legacy", "IAM.Role", Path("/synthetic"))
        del values["desired.row.missing-field"]
        assert (
            projection.resource_rows(values, "legacy", "IAM.Role", Path("/synthetic"))
            == rows
        )


def _callback_check_resource_row_scope_restoration_fail(outer, /, _):
    assert projection._resource_row_cache.get() is not outer
    raise RuntimeError("generation failed")


def check_resource_row_scope_restoration():
    assert projection._resource_row_cache.get() is None
    with projection.resource_row_scope():
        outer = projection._resource_row_cache.get()
        with pytest.raises(RuntimeError, match="generation failed"):
            with projection.resource_row_scope():
                assert projection._resource_row_cache.get() is not outer
                raise RuntimeError("generation failed")
        assert projection._resource_row_cache.get() is outer
        fail = _bind_framework_callback(
            _callback_check_resource_row_scope_restoration_fail, outer
        )
        with (
            patch.object(sync_runtime, "total", side_effect=fail),
            pytest.raises(RuntimeError),
        ):
            sync_runtime.generate_views(
                Path("/stage"),
                Path("/root"),
                {},
                [],
                definitions_root=Path("/definitions"),
            )
        assert projection._resource_row_cache.get() is outer
        with patch.object(sync_runtime, "total"):
            assert (
                sync_runtime.generate_views(
                    Path("/stage"),
                    Path("/root"),
                    {},
                    [],
                    definitions_root=Path("/definitions"),
                )
                == {}
            )
        assert projection._resource_row_cache.get() is outer
    assert projection._resource_row_cache.get() is None


def check_generate_views_missing_authoritative_json(tmp_path, shared_framework):
    root, stage = tmp_path / "root", tmp_path / "stage"
    root.mkdir()
    (root / "project.json").write_text(
        '{"targets":[{"environment":"dev","alias":"team","awsAccountId":"111111111111",'
        '"awsRegion":"ap-northeast-1","iacEngine":"cloudformation"}]}',
        encoding="utf-8",
    )
    values = {
        COUNTERS: '{"IAM.ManagedPolicy":1}',
        "desired.service.iam.serviceId": "iam",
        "desired.service.iam.ownedCatalogResourceTypes": "IAM.ManagedPolicy",
        "display.service.title": "# Policy",
        "desired.resource.009.resourceType": "IAM.ManagedPolicy",
        "desired.resource.009.logicalId": "IAM_ManagedPolicy_001",
        "desired.resource.009.resourceMode": "IMPORT",
        "desired.resource.009.anchor": "saved-policy",
        "display.resource.009.comment": "Policy",
        "desired.row.009-001.property": "IAM.ManagedPolicy.ManagedPolicyName",
        "desired.row.009-001.value": "`confirmed-policy`",
        "desired.row.009-001.comment": "Policy name",
        "desired.row.009-002.property": "IAM.ManagedPolicy.PolicyDocument",
        "desired.row.009-002.value": "[Policy](iam/policy.json)",
        "desired.row.009-002.comment": "Policy document",
        "desired.row.009-002.document": '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:ListBucket","Resource":"*"}]}',
    }
    design = root / "docs/designs/dev/team/iam.md"
    artifact = design.with_suffix("") / "policy.json"
    artifact.parent.mkdir(parents=True)
    design.write_text("# Saved policy\n[Policy](iam/policy.json)\n", encoding="utf-8")
    artifact.write_text(values["desired.row.009-002.document"] + "\n", encoding="utf-8")
    del values["desired.row.009-002.document"]
    assert values["desired.row.009-002.value"] == "[Policy](iam/policy.json)"
    source = root / "model/dev/team/iam.properties"
    source.parent.mkdir(parents=True)
    source.write_text(serialize(values), encoding="utf-8")
    original = dict(values)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    failures = []
    with mapping_alias(shared_framework.parent, root):
        generated = sync_runtime.generate_views(
            stage,
            root,
            {design: runtime_values(values)},
            failures,
            definitions_root=shared_framework.parent,
        )
    assert generated == {}
    assert [d.message for d in failures] == [
        "docs/designs/dev/team/iam.md: authoritative JSON document missing: iam.md: 009-002"
    ]
    assert {
        path.relative_to(stage): path.read_bytes()
        for path in stage.rglob("*")
        if path.is_file()
    } == {path.relative_to(root): before[path] for path in (design, artifact)}
    assert {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == before
    assert values == original


def check_readonly_stale_views(tmp_path):
    path = tmp_path / "docs/designs/dev/team/logs.md"
    source = tmp_path / "model/dev/team/logs.properties"
    path.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    source.write_bytes(b"authoritative source")
    expected = "| RetentionInDays | `14` | 保持日数 |\n"
    for content in (
        expected,
        expected.replace("`14`", "`31`"),
        "",
        expected.replace("RetentionInDays", "UnknownField"),
        "<!-- reference-rows: obsolete -->\n" + expected,
    ):
        path.write_text(content, encoding="utf-8")
        before = {file: file.read_bytes() for file in (path, source)}
        plan = SimpleNamespace(
            root=tmp_path,
            read_inputs={source: before[source]},
            expected_outputs={path: {path: expected}},
            failure_records=[],
            saved={},
        )
        sync_runtime._compare_generation(plan)
        if content == expected:
            assert plan.saved == {path: {}} and not plan.failure_records
        else:
            assert [d.message for d in plan.failure_records] == [
                "generated Markdown is stale or missing: docs/designs/dev/team/logs.md"
            ]
            assert not plan.saved
        assert {file: file.read_bytes() for file in before} == before
    path.unlink()
    plan = SimpleNamespace(
        root=tmp_path,
        read_inputs={},
        expected_outputs={path: {path: expected}},
        failure_records=[],
        saved={},
    )
    sync_runtime._compare_generation(plan)
    assert plan.failure_records and not path.exists()


def check_saved_link_snapshot_and_new_warnings(tmp_path, capsys):
    root = tmp_path / "root"
    source = root / "docs/designs/dev/team/codepipeline.md"
    target = source.with_name("kms.md")
    source.parent.mkdir(parents=True)
    source.write_text(
        "<!-- reference-rows: obsolete -->\n[old](kms.md#missing)\n"
        "[new](kms.md#key)\n<!-- [hidden](absent.md#hidden) -->\n",
        encoding="utf-8",
    )
    target.write_text('<a id="key"></a>\n', encoding="utf-8")
    before = source.read_bytes()
    with patch.object(
        sync_views,
        "view_validator",
        side_effect=AssertionError("strict validator used"),
    ):
        baseline = sync_views.broken_design_links(root, root, [source])
        assert baseline == {
            "docs/designs/dev/team/codepipeline.md: kms.md#missing": target
        }
        target.write_text('<a id="renamed"></a>\n', encoding="utf-8")
        final = sync_views.broken_design_links(root, root, [source])
    assert source.read_bytes() == before
    plan = SimpleNamespace(
        root=root,
        saved={target: {}},
        failure_records=[],
        failures=[],
        reference_warnings=[],
        unavailable={},
        pending_artifacts={},
        warnings=final,
        baseline_links=baseline,
        model_paths=[],
        markdown_paths=[target],
    )
    sync_runtime.report_generation(plan)
    warnings = capsys.readouterr().err
    assert (
        warnings.count("saved reference needs repair") == 1 and "kms.md#key" in warnings
    )
    assert "#missing" not in warnings
    # A changed target that was rolled back is not a successfully saved service.
    plan.saved = {}
    plan.markdown_paths = []
    sync_runtime.report_generation(plan)
    assert not capsys.readouterr().err


def _fail_publication_artifact(original, failed, /, path, text, *args, **kwargs):
    if path == failed and text == '{"new":true}\n':
        raise OSError("fixture artifact write failure")
    return original(path, text, *args, **kwargs)


@pytest.mark.parametrize("reject_saved", [False, True])
def check_publication_legacy_fallback(tmp_path, reject_saved):
    root, stage = tmp_path / "root", tmp_path / "stage"
    good = root / "docs/designs/dev/team/kms.md"
    failed = good.with_name("iam.md")
    artifact = failed.with_suffix("") / "policy.json"
    original = {
        good: '<a id="old-key"></a>\n',
        failed: "<!-- reference-rows: obsolete -->\n[old](kms.md#old-key)\n",
        artifact: '{"old":true}\n',
    }
    expected = {
        good: {good: '<a id="new-key"></a>\n'},
        failed: {failed: "# candidate\n", artifact: '{"new":true}\n'},
    }
    for path, text in original.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        staged = stage / path.relative_to(root)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(
            expected[failed].get(path, expected[good].get(path)), encoding="utf-8"
        )
    with closing(sync_runtime.GenerationInputs(root)) as snapshot:
        for path in original:
            snapshot.read(path)
        plan = sync_runtime.Generation(
            root=root,
            stage=stage,
            snapshot=snapshot,
            scope=None,
            model_paths=[],
            markdown_paths=[],
            lifetime=ExitStack(),
            expected_outputs=expected,
            saved={},
            generated={good: [], failed: []},
            failure_records=[],
            validation={},
            candidate=object(),
            destinations={good: {}, failed: {}},
            accounts={},
            definitions_root=root,
            warnings={},
            reference_warnings=[],
        )
        fail_write = _bind_framework_callback(
            _fail_publication_artifact, Path.write_text, artifact
        )
        context = SimpleNamespace(errors=[], findings=Findings(stage))
        checked = Findings(stage)
        checked.warn(
            False,
            "fixture saved reference semantics unavailable",
            code="design.links_unverified",
        )
        validation = (
            ValueError("fixture dependent candidate invalid") if reject_saved else None
        )
        plan.saved_paths, plan.baseline_links = [good, failed], {}
        with (
            patch.object(Path, "write_text", autospec=True, side_effect=fail_write),
            patch.object(sync_views, "validation_context", return_value=context),
            patch.object(
                sync_views,
                "validate_views",
                side_effect=validation,
                return_value=checked,
            ) as validate,
        ):
            sync_runtime.publish_generation(plan)
        assert validate.call_args.kwargs["candidate_paths"] == {
            stage / good.relative_to(root)
        }
        assert (
            failed.read_bytes() == original[failed].encode()
            and artifact.read_bytes() == original[artifact].encode()
        )
        assert (stage / failed.relative_to(root)).read_bytes() == failed.read_bytes()
        assert (
            stage / artifact.relative_to(root)
        ).read_bytes() == artifact.read_bytes()
        if reject_saved:
            assert not plan.saved and not plan.warnings
            assert good.read_bytes() == original[good].encode()
        else:
            assert (
                set(plan.saved) == {good}
                and good.read_text(encoding="utf-8") == expected[good][good]
            )
            assert plan.warnings == {
                "docs/designs/dev/team/iam.md: kms.md#old-key": good
            }
            assert plan.reference_warnings == checked.warnings
        assert len(plan.failures) == (2 if reject_saved else 1)


@pytest.mark.parametrize("location", ["file", "parent"])
def check_snapshot_symlink_safety(tmp_path, location):
    external = tmp_path / "external"
    external.mkdir()
    (external / "policy.json").write_bytes(b"{}\n")
    directory = tmp_path / "iam"
    if location == "parent":
        directory.symlink_to(external, target_is_directory=True)
    else:
        directory.mkdir()
        (directory / "policy.json").symlink_to(external / "policy.json")
    path = directory / "policy.json"
    snapshot = sync_runtime.GenerationInputs(tmp_path)
    try:
        if location == "file":
            with pytest.raises(
                ValueError, match=r"unsafe generation input \(symlink\)"
            ):
                snapshot.read(path)
        else:
            snapshot.read(path)
            snapshot.seal()
            directory.unlink()
            directory.mkdir()
            path.write_bytes(b"{}\n")
            with pytest.raises(ValueError, match="inputs changed before publication"):
                snapshot.verify()
        assert (external / "policy.json").read_bytes() == b"{}\n"
    finally:
        snapshot.close()


@pytest.mark.parametrize(
    "arguments,jobs,all_scope",
    [
        (["--scope", "dev/team/config", "--scope", "stg/team/config"], 1, False),
        (["--scope", "dev/team/config", "--scope", "stg/team/config"], 4, False),
        (["--all"], 1, True),
        (["--all"], 4, True),
    ],
)
def check_internal_sync_selection(tmp_path, arguments, jobs, all_scope):
    runner = module("sync-model.py", "blueprint_sync_model")
    with (
        patch.object(runner, "sync", return_value=0) as sync,
        patch.object(runner, "active_scope", return_value=None),
        patch("model.impact.task_impact", return_value=SimpleNamespace(services=set())),
    ):
        code, text = runner.run(
            ["--jobs", str(jobs), *arguments], repository_root=tmp_path
        )
    assert code == 0, text
    if all_scope:
        sync.assert_called_once_with(tmp_path, False, jobs=jobs, definitions_root=None)
    else:
        assert sync.call_count == 2
        assert {
            (call.args[2], call.args[3], tuple(call.args[4]))
            for call in sync.call_args_list
        } == {("dev", "team", ("config",)), ("stg", "team", ("config",))}
        assert all(call.kwargs["jobs"] == 1 for call in sync.call_args_list)


@pytest.mark.parametrize(
    "extra_inputs,write", [(False, False), (False, True), (True, False), (True, True)]
)
@pytest.mark.parametrize("unavailable", [False, True])
def check_failure_counts(tmp_path, capsys, extra_inputs, write, unavailable):
    docs = tmp_path / "docs/designs/dev/team"
    models = tmp_path / "model/dev/team"
    paths = [docs / f"service-{n:02d}.md" for n in range(17)]
    saved = {path: {} for path in paths[9:]}
    failures = [f"{path.name}: fixture render failure" for path in paths[:9]]
    model_paths = [models / path.with_suffix(".properties").name for path in paths]
    if extra_inputs:
        model_paths.append(models / "invalid.properties")
        paths.append(docs / "orphan.md")
        failures += [
            "invalid or duplicate model property",
            "properties Model inputs missing",
        ]
    warnings = {f"reference-{n}": paths[9] for n in range(5)} if write else {}
    plan = SimpleNamespace(
        root=tmp_path,
        saved=saved,
        failures=failures,
        failure_records=[],
        model_paths=model_paths,
        markdown_paths=paths,
        reference_warnings=[],
        unavailable={},
        pending_artifacts={},
        warnings=warnings,
        baseline_links={},
        generated_scope={("dev", "team", path.stem) for path in saved},
    )
    if unavailable:
        reference = docs / "unresolved.md"
        plan.markdown_paths.append(reference)
        # A separate literal error remains FAILED even with unresolved references.
        plan.failures[0] = f"{paths[0].relative_to(tmp_path)}: fixture render failure"
        plan.unavailable = {
            path: {"reason": "reference", "status": "NOT_RUN", "retainedView": None}
            for path in (reference, paths[0])
        }
    for path, message in zip(paths, plan.failures, strict=False):
        sync_runtime.generation_failure(
            tmp_path, plan.failure_records, "generation.render", path, message
        )
    metadata = sync_runtime.generation_metadata(plan)
    assert metadata["status"] == "FAIL"
    assert set(metadata["unavailable_services"]) == (
        {"dev/team/unresolved"} if unavailable else set()
    )
    with pytest.raises(ValueError) as error:
        sync_runtime.report_generation(plan)
    failed = 11 if extra_inputs else 9
    not_run = int(unavailable)
    assert (
        str(error.value).splitlines()[0]
        == f"8 services succeeded; {failed} services failed; {not_run} services NOT_RUN; {failed + not_run} diagnostics"
    )
    assert len(str(error.value).splitlines()) == failed + not_run + 1
    assert "saved reference" not in str(error.value)
    output = capsys.readouterr()
    assert output.err.count("saved reference needs repair") == (5 if write else 0)
    assert output.out.count("Design Markdown sync: PASS") == 8
    assert "generation: 8 services succeeded" in output.out
    assert (
        "NOT_RUN: docs/designs/dev/team/unresolved.md: reference" in str(error.value)
    ) is unavailable
    if extra_inputs:
        assert all(message in str(error.value) for message in failures[-2:])


def _snapshot_archive(root, base, paths, destination):
    assert base == "baseline" and paths == ["model", "project.json"]
    (destination / "project.json").write_bytes(b"baseline project")


def check_guard_snapshot_candidates(tmp_path):
    project = tmp_path / "project.json"
    project.write_bytes(b"live project")
    source = tmp_path / "model/dev/team/service.properties"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"live Model")
    with patch.object(
        import_guard, "archive_sources", side_effect=_snapshot_archive
    ) as archive:
        for output in ({}, {project: "{}\n"}):
            with import_guard.snapshots(tmp_path, "baseline", output) as (
                before,
                after,
            ):
                assert (
                    before.joinpath("project.json").read_bytes() == b"baseline project"
                )
                assert (after == tmp_path) == (not output)
                assert after.joinpath("project.json").read_bytes() == (
                    b"{}\n" if output else b"live project"
                )
                assert (
                    after.joinpath(source.relative_to(tmp_path)).read_bytes()
                    == b"live Model"
                )
                assert (
                    not (before / "framework").exists()
                    and not (after / "framework").exists()
                )
                assert project.read_bytes() == b"live project"
        assert archive.call_count == 2


def _definition_read_failure(source, original, /, path, *args, **kwargs):
    if path == source:
        raise FileNotFoundError("unavailable Framework definition")
    return original(path, *args, **kwargs)


@pytest.mark.parametrize("definition", ["schema", "mapping", "naming", "layout"])
def check_definition_read_errors(tmp_path, definition):
    definitions = definition_root(tmp_path)
    source = (
        definitions
        / "framework"
        / {
            "schema": "materials/cloudformation-schema/ap-northeast-1/index.json",
            "mapping": "mappings/aws/owners.json",
            "naming": "rules/aws-resource-naming.md",
            "layout": "rules/resource-layout.json",
        }[definition]
    )
    fail = _bind_framework_callback(_definition_read_failure, source, Path.read_text)
    with input_context(fresh=True), patch.object(Path, "read_text", fail):
        if definition == "layout":
            validator = load("validate-blueprint").Validator(
                tmp_path, definitions_root=definitions
            )
            validator.check_resource_layout()
            assert any(
                "unavailable Framework definition" in error
                for error in validator.errors
            )
        else:
            with pytest.raises(
                FileNotFoundError, match="unavailable Framework definition"
            ):
                if definition == "mapping":
                    aws_mappings.Mappings(definitions)
                elif definition == "schema":
                    assert aws_schemas.Schemas(definitions).resource_types
                else:
                    model_validation.naming_errors(
                        definitions,
                        "IAM.Role",
                        [["1", "RoleName", "`app-dev-role`", "名前"]],
                    )


@pytest.mark.parametrize("state", ["stale", "missing"])
def check_sidecar_output_difference(tmp_path, state):
    view, artifact = tmp_path / "iam.md", tmp_path / "policy.json"
    view.write_bytes(b"unchanged\n")
    if state == "stale":
        artifact.write_bytes(b"{}\n")
    snapshot = sync_runtime.GenerationInputs(tmp_path)
    try:
        plan = SimpleNamespace(
            snapshot=snapshot,
            expected_outputs={view: {view: "unchanged\n", artifact: '{"new": true}\n'}},
        )
        assert sync_runtime.planned_outputs(plan) == {artifact}
        assert view.read_bytes() == b"unchanged\n"
    finally:
        snapshot.close()


@pytest.mark.parametrize("missing", ["model", "view"])
def check_missing_validation_inputs(tmp_path, missing):
    (tmp_path / "project.json").write_text(
        '{"projectName":"test","targets":[{"environment":"dev",'
        '"awsAccountId":"123456789012","awsRegion":"ap-northeast-1",'
        '"iacEngine":"cloudformation"}]}\n'
    )
    source = tmp_path / "model/dev/123456789012/iam.properties"
    if missing == "view":
        source.parent.mkdir(parents=True)
        source.write_text(
            serialize(
                {
                    "desired.service.iam.serviceId": "iam",
                    "desired.service.iam.ownedCatalogResourceTypes": "IAM.Role",
                }
            ),
            encoding="utf-8",
        )
    original = source.read_bytes() if source.exists() else None
    validator = load("validate-blueprint").Validator(
        tmp_path, {("dev", "123456789012", "iam")}
    )
    validator.check_project_topology()
    validator.check_validation_scope()
    expected = (
        "validation properties input missing"
        if missing == "model"
        else "validation input missing: docs/designs/dev/123456789012/iam.md"
    )
    assert any(expected in error for error in validator.errors), validator.errors
    assert not (tmp_path / "docs/designs/dev/123456789012/iam.md").exists()
    assert (source.read_bytes() if source.exists() else None) == original


@pytest.mark.parametrize("fault", ["model", "orphan"])
def check_generation_input_failures(tmp_path, fault):
    view = tmp_path / "docs/designs/dev/123456789012/iam.md"
    source = tmp_path / "model/dev/123456789012/iam.properties"
    view.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    view.write_bytes(b"saved Markdown\n")
    (tmp_path / "project.json").write_text(
        '{"projectName":"test","targets":[{"environment":"dev",'
        '"awsAccountId":"123456789012","awsRegion":"ap-northeast-1",'
        '"iacEngine":"cloudformation"}]}\n'
    )
    if fault == "model":
        source.write_bytes(b"malformed Model\n")
    with (
        patch.object(sync_runtime, "stage_inputs", return_value=([view], {})),
        patch.object(sync_runtime, "generate_views", return_value={}) as generate,
    ):
        plan = sync_runtime.prepare_generation(tmp_path, None, write=False)
        try:
            assert not plan.destinations and not plan.generated
            assert (
                len(plan.failures) == 1
                and (
                    "unsupported Model format"
                    if fault == "model"
                    else "properties Model inputs missing"
                )
                in plan.failures[0]
            ), plan.failures
            generate.assert_called_once()
            assert generate.call_args.args[2] == {}
        finally:
            plan.close()
    assert view.read_bytes() == b"saved Markdown\n"
    if fault == "model":
        assert source.read_bytes() == b"malformed Model\n"


if __name__ == "__main__":
    raise SystemExit(run(__file__))
