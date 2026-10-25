#!/usr/bin/env python3
"""Task snapshot I/O budgets and live authorization/publication boundaries."""

import hashlib
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
from dataclasses import FrozenInstanceError
from functools import partial, partialmethod
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import sync_runtime
import task_contract_core as tasks
from deploy import guards, session
from generation_inputs import GenerationInputs
from import_guard import workflow
from model.adapters.task import source_write_context
from model.importing import scope as import_scope
from model.sources import load_model
from support.import_model_fixtures import operation_contract, operation_fixture
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked
from utils.input_cache import input_context, memo_table, recording_inputs
from validation import runner

from model import prepare_edit, publish_edit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

READ_BYTES = Path.read_bytes
READ_TEXT = Path.read_text
GLOB = Path.glob


def counted_read(path, counts, method, *args, **kwargs):
    if path.parent.name == "tasks":
        counts["reads"] += 1
    return method(path, *args, **kwargs)


def counted_glob(path, counts, *args, **kwargs):
    if path.name == "tasks":
        counts["scans"] += 1
    return GLOB(path, *args, **kwargs)


class TaskIO:
    def __init__(self):
        self.counts = Counter()
        self.patches = [
            patch.object(
                Path, "read_bytes", partialmethod(counted_read, self.counts, READ_BYTES)
            ),
            patch.object(
                Path, "read_text", partialmethod(counted_read, self.counts, READ_TEXT)
            ),
            patch.object(Path, "glob", partialmethod(counted_glob, self.counts)),
        ]

    def __enter__(self):
        for item in self.patches:
            item.start()
        return self.counts

    def __exit__(self, *exc):
        for item in reversed(self.patches):
            item.stop()


def task_text(name, *, state="running", workflow_name="update"):
    return (
        f"## Task contract\n- Task type: `infrastructure`\n- Task status: `{state}`\n"
        "- AWS API execution: `allowed`\n- Deploy/apply: `allowed`\n"
        "- Target environment: `dev`\n- Target AWS account: `123456789012`\n- Target alias: `cde`\n"
        "- Infrastructure phase: `deploy`\n- Deployment scope: `A`\n"
        f"- Workflow: `{workflow_name}`\n## Validation scope\n- `dev/cde/s3`\n"
        f"## Modified files\n- `tasks/{name}.md`\n## Allowed paths\n- `tasks/{name}.md`\n"
    )


def make_tasks(root):
    (root / "tasks").mkdir()
    for name in ("one", "two", "three"):
        (root / f"tasks/{name}.md").write_text(
            task_text(name, state="running" if name == "one" else "completed")
        )


def check_fresh_input_context_restores_parent():
    assert memo_table() is None
    with input_context():
        parent = memo_table()
        parent["sentinel"] = "parent"
        with input_context(fresh=True):
            assert memo_table() == {} and memo_table() is not parent
            memo_table()["sentinel"] = "candidate"
        assert memo_table() is parent and parent == {"sentinel": "parent"}
    assert memo_table() is None


def check_explicit_single_read(tmp_path):
    make_tasks(tmp_path)
    # Intentional change: unrelated malformed Tasks do not block explicit selection.
    (tmp_path / "tasks/BAD.txt").write_text("malformed unrelated task")
    (tmp_path / "tasks/two.md").write_text("invalid status")
    with (
        tasks.selected_task(tmp_path, "tasks/one.md"),
        TaskIO() as io,
        tasks.task_reads(tmp_path),
    ):
        snapshot = tasks.task_snapshot(tmp_path)
        assert tasks.task_path(tmp_path) == snapshot.path
        assert tasks.contract_path(tmp_path) == snapshot.path
        assert tasks.task_revision(tmp_path) == (snapshot.name, snapshot.text)
        assert tasks.active_scope(tmp_path) == {("dev", "cde", "s3")}
        assert snapshot.raw_digest == hashlib.sha256(snapshot.raw).hexdigest()
        assert snapshot.task_digest == tasks.task_digest(snapshot.text)
        assert io == {"reads": 1}
        with pytest.raises(FrozenInstanceError):
            snapshot.text = "changed"
    with pytest.raises(ValueError):
        tasks.task_snapshot(tmp_path)


def check_implicit_and_catalog_once(tmp_path, monkeypatch):
    monkeypatch.delenv(tasks.SELECTOR, raising=False)
    make_tasks(tmp_path)
    with TaskIO() as io, tasks.task_reads(tmp_path):
        assert tasks.task_path(tmp_path).name == "one.md"
        tasks.task_revision(tmp_path)
        tasks.active_scope(tmp_path)
        assert len(tasks.contracts(tmp_path)) == 3
        assert io == {"reads": 3, "scans": 1}
        tasks.verify_contract_reads(tmp_path)
        assert io == {"reads": 6, "scans": 2}
    (tmp_path / "tasks/two.md").write_text(task_text("two"))
    with pytest.raises(ValueError, match="multiple running"):
        tasks.task_path(tmp_path)


def check_catalog_after_selection_reuses_bytes(tmp_path):
    make_tasks(tmp_path)
    with (
        tasks.selected_task(tmp_path, "tasks/one.md"),
        TaskIO() as io,
        tasks.task_reads(tmp_path),
    ):
        tasks.task_path(tmp_path)
        captured = tasks.contract_snapshot(tmp_path)
        assert io == {"reads": 3, "scans": 1}
        with tasks.contract_reads(tmp_path, snapshot=captured, verify=False):
            assert len(tasks.contracts(tmp_path)) == 3
        assert io == {"reads": 3, "scans": 1}


@pytest.mark.parametrize(
    "change", ["content", "status", "line-endings", "addition", "deletion", "selector"]
)
def check_live_change_detection(tmp_path, monkeypatch, change):
    make_tasks(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, "tasks/one.md")
    with tasks.contract_reads(tmp_path, verify=False) as captured:
        inputs = GenerationInputs(tmp_path)
        path = tmp_path / "tasks/one.md"
        if change == "content":
            path.write_text(task_text("one") + "\n## Changed\ncontent\n")
        elif change == "status":
            path.write_text(task_text("one", state="completed"))
        elif change == "line-endings":
            path.write_bytes(task_text("one").replace("\n", "\r\n").encode())
        elif change == "addition":
            (tmp_path / "tasks/four.md").write_text(
                task_text("four", state="completed")
            )
        elif change == "deletion":
            (tmp_path / "tasks/two.md").unlink()
        else:
            monkeypatch.setenv(tasks.SELECTOR, "tasks/two.md")
        try:
            # A fixed GenerationInputs recorder cannot hide the live comparison.
            with (
                recording_inputs(inputs),
                pytest.raises(ValueError, match="changed during validation"),
            ):
                tasks.verify_snapshot(captured)
            with pytest.raises(ValueError, match="changed"):
                inputs.verify()
        finally:
            inputs.close()


def check_status_paths_and_invalidation(tmp_path):
    make_tasks(tmp_path)
    with tasks.selected_task(tmp_path, "tasks/one.md"), tasks.task_reads(tmp_path):
        original = tasks.task_snapshot(tmp_path)
        assert tasks.suspend(tmp_path, original.name, "test stopped")
        assert tasks.contract_path(tmp_path) == original.path
        with pytest.raises(ValueError, match="suspend task cannot execute"):
            tasks.task_path(tmp_path)
        assert tasks.task_snapshot(tmp_path, executable=False).status == "suspend"
    with pytest.raises(ValueError, match="invalid task selector"):
        tasks.task_snapshot(tmp_path, "../one.md")
    original.path.unlink()
    original.path.symlink_to(tmp_path / "tasks/two.md")
    with pytest.raises(ValueError, match="symlinks"):
        tasks.task_snapshot(tmp_path, original.name)


def mutation_guard(root, session_record):
    backend = SimpleNamespace(
        root=root, target={}, file_digest=lambda p: "f", input_digest=lambda unit: "u"
    )
    context = SimpleNamespace(load_target=lambda *args: {})
    args = SimpleNamespace(
        stack=["A"], environment="dev", alias="cde", aws_account_id="123456789012"
    )
    return session._callback_run_guard(
        args,
        backend,
        context,
        root,
        {"awsAccountId": "123456789012"},
        session_record,
        {},
    )


def check_deploy_mutation_io_and_live_denial(tmp_path, monkeypatch):
    make_tasks(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, "tasks/one.md")
    issues = tmp_path / "issues/dev/cde/issues.md"
    issues.parent.mkdir(parents=True)
    issues.write_text("未解決issueなし")
    record = {
        "taskDigest": tasks.task_digest(task_text("one")),
        "modelInputManifest": {},
        "infraManifest": {},
    }
    runtime = SimpleNamespace(
        root=tmp_path,
        environment="dev",
        directory="cde",
        guard=partial(mutation_guard, tmp_path, record),
        timing=SimpleNamespace(phase=lambda *args, **kw: input_context()),
        connection=object(),
    )
    with (
        patch.object(guards.SERVICES["s3"], "put_object", return_value={}) as mutation,
        TaskIO() as io,
    ):
        for _ in range(10):
            guards.call(runtime, "s3", "put_object", {})
        assert io == {"reads": 10}
        issues.write_text("### s3\n1. unresolved issue\n")
        guards.call(runtime, "s3", "put_object", {})
        assert io == {"reads": 11} and mutation.call_count == 11
        issues.write_text("未解決issueなし")
        for replacement in ["`completed`", "`suspend`"]:
            text = task_text("one").replace("`running`", replacement)
            if replacement == "`suspend`":
                text += "\n## Suspension reason\nreason\n"
            (tmp_path / "tasks/one.md").write_text(text)
            with pytest.raises((Blocked, ValueError)):
                guards.call(runtime, "s3", "put_object", {})
        for old, new in [
            ("`allowed`", "`forbidden`"),
            ("`A`", "`B`"),
            ("`123456789012`", "`999999999999`"),
        ]:
            (tmp_path / "tasks/one.md").write_text(task_text("one").replace(old, new))
            with pytest.raises(Blocked):
                guards.call(runtime, "s3", "put_object", {})
        (tmp_path / "tasks/one.md").write_text(task_text("one"))
        with tasks.task_reads(tmp_path):
            fixed = GenerationInputs(tmp_path)
            (tmp_path / "tasks/one.md").write_text(task_text("one", state="completed"))
            try:
                with (
                    recording_inputs(fixed),
                    pytest.raises(Blocked, match="completed task"),
                ):
                    guards.call(runtime, "s3", "put_object", {})
            finally:
                fixed.close()
        assert mutation.call_count == 11


def worker_designs(validator):
    assert tasks.task_revision(validator.root)[0] == "tasks/one.md"
    assert tasks.active_scope(validator.root) == {("dev", "cde", "s3")}
    validator.worker_memo = memo_table()
    validator.worker_memo["worker"] = validator


def worker_observed(validator, files):
    assert validator.worker_memo["worker"] is validator


def check_validation_workers_share_immutable_snapshot(tmp_path, monkeypatch):
    make_tasks(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, "tasks/one.md")
    parent = SimpleNamespace(
        root=tmp_path,
        definitions_root=tmp_path,
        accounts={},
        schema_catalog=None,
        unavailable_views={},
        view_reader=None,
        check_display=True,
    )
    with (
        tasks.contract_reads(tmp_path, verify=False) as captured,
        patch.object(runner.Validator, "check_designs", worker_designs),
        patch.object(runner.Validator, "check_observed_values", worker_observed),
        TaskIO() as io,
    ):
        validate = partial(
            runner._callback_Validator_check_scoped_designs_validate, parent, captured
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    validate, [{("dev", "cde", "s3")}, {("dev", "cde", "iam")}]
                )
            )
        assert io == {}  # Workers perform no Task reads or enumeration.
        assert results[0].worker_memo is not results[1].worker_memo
        tasks.verify_contract_reads(tmp_path)
        assert io == {"reads": 3, "scans": 1}


def check_import_model_operation_reuse_and_publication(tmp_path, monkeypatch):
    make_tasks(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, "tasks/one.md")
    path = tmp_path / "tasks/one.md"
    text = task_text("one", workflow_name="import").replace(
        "`infrastructure`", "`design`"
    )
    path.write_text(text)
    with tasks.task_reads(tmp_path), TaskIO() as io:
        assert workflow(tmp_path) == "tasks/one.md"
        assert import_scope.selected(tmp_path) == ("dev", "cde", "s3")
        inputs = GenerationInputs(tmp_path)
        assert tasks.task_revision(tmp_path) == inputs.expected_task
        assert io == {"reads": 1}
        path.write_text(text + "\n## Changed\nchanged\n")
        try:
            with pytest.raises(ValueError, match="inputs changed"):
                inputs.verify()
            assert tasks.task_revision(tmp_path, live=True) != inputs.expected_task
        finally:
            inputs.close()


def skip_validation(*args, **kwargs):
    return None


def change_during_catalog(validator):
    validator.cache.common = "common"
    validator.catalog_pending = ("catalog", 1)
    validator.service_cache_pending = [("service", 1)]
    path = validator.root / "tasks/one.md"
    if validator.contract_change == "content":
        path.write_text(task_text("one") + "\n## External change\nchanged\n")
    elif validator.contract_change == "selector":
        os.environ[tasks.SELECTOR] = "tasks/two.md"
    else:
        (validator.root / "tasks/four.md").write_text(
            task_text("four", state="completed")
        )


@pytest.mark.parametrize("change", ["content", "selector", "catalog"])
def check_parent_rejects_changes_before_success_cache(tmp_path, monkeypatch, change):
    make_tasks(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, "tasks/one.md")
    validator = runner.Validator(tmp_path, set())
    validator.contract_change = change
    validator.cache = SimpleNamespace(
        common=None, common_key=lambda: "common", save=Mock()
    )
    methods = (
        "check_structure",
        "check_task_scope",
        "check_project_topology",
        "check_validation_scope",
        "check_model_files",
        "check_initialized_paths",
        "check_resource_layout",
        "check_iac_selection",
        "check_acceptance_checks",
    )
    with ExitStack() as stack:
        for name in methods:
            stack.enter_context(patch.object(validator, name, skip_validation))
        stack.enter_context(
            patch.object(validator.task, "fix_baseline", skip_validation)
        )
        stack.enter_context(
            patch.object(
                validator, "check_catalog", partial(change_during_catalog, validator)
            )
        )
        with pytest.raises(ValueError, match="changed during validation"):
            validator.run()
    validator.cache.save.assert_not_called()


def check_selected_verify_reads_live_once(tmp_path, monkeypatch):
    make_tasks(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, "tasks/one.md")
    with tasks.task_reads(tmp_path), TaskIO() as io:
        snapshot = tasks.task_snapshot(tmp_path)
        tasks.verify_snapshot(snapshot)
        assert io == {"reads": 2}
        monkeypatch.setenv(tasks.SELECTOR, "tasks/two.md")
        with pytest.raises(ValueError, match="selection changed"):
            tasks.verify_snapshot(snapshot)
        assert io == {"reads": 2}


def worker_views(stage, root, files, destinations, **kwargs):
    assert tasks.active_scope(root) == {("dev", "cde", "s3")}
    return None


def check_generation_workers_reuse_task_snapshot(tmp_path, monkeypatch):
    make_tasks(tmp_path)
    monkeypatch.setenv(tasks.SELECTOR, "tasks/one.md")
    paths = [
        tmp_path / "docs/designs/dev/cde/s3.md",
        tmp_path / "docs/designs/dev/cde/iam.md",
    ]
    state = SimpleNamespace(design_index=None, candidate_paths=None)
    with tasks.task_reads(tmp_path):
        captured = tasks.task_snapshot(tmp_path)
        with (
            patch.object(sync_runtime.sync_views, "validate_views", worker_views),
            TaskIO() as io,
        ):
            validate = partial(
                sync_runtime._callback_validate_candidates_validate,
                state,
                tmp_path,
                paths,
                tmp_path,
                tmp_path / "stage",
                None,
                captured,
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(validate, paths))
            assert all(error is None for _, error in results)
            assert io == {}


def check_model_publication_task_revision_reuses_original_read(tmp_path):
    operation_fixture(tmp_path)
    path = tmp_path / "model/stg/cde/vpc.properties"
    name = "tasks/parent.md"
    listed = "\n".join(
        "- `" + value + "`" for value in [name, path.relative_to(tmp_path).as_posix()]
    )
    text = (
        operation_contract("import-merge") + "## Validation scope\n- `stg/cde/vpc`\n"
        "## Modified files\n" + listed + "\n## Allowed paths\n" + listed + "\n"
    )
    tasks.start(tmp_path, name, text)
    original = path.read_bytes()
    with TaskIO() as io, source_write_context(tmp_path, name) as context:
        plan = prepare_edit(
            load_model(path, context.snapshot),
            {path: original.decode() + "# candidate\n"},
            context,
        )
        assert io == {"reads": 1}
        (tmp_path / name).write_text(text + "\n## New authority\nchanged\n")
        with pytest.raises(ValueError, match="inputs changed"):
            publish_edit(plan, context)
        assert io == {"reads": 2}
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="explicit running parent"):
        with source_write_context(tmp_path, None):
            pass


def check_session_initialization_reuses_task_fields(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()
    make_tasks(root)
    monkeypatch.setenv(tasks.SELECTOR, "tasks/one.md")
    monkeypatch.setattr(session.tempfile, "gettempdir", lambda: str(tmp_path))
    state = tmp_path / "session.json"
    text = (
        task_text("one").replace("`deploy`", "`update`") + "\n## Repair options\n"
        "- Repair cycle budget: `7`\n- External IaC repair: `allowed`\n"
        f"- Deploy repair session: `{state}`\n"
    )
    (root / "tasks/one.md").write_text(text)
    target = {
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "iacEngine": "cloudformation",
    }
    args = SimpleNamespace(
        state=state,
        stack=["A"],
        environment="dev",
        alias="cde",
        aws_account_id="123456789012",
        profile=None,
        pause_after_group=False,
        resume=False,
        sequential=False,
        approve_change_set=[],
    )
    backend = SimpleNamespace(
        profile=None,
        input_digest=lambda unit: "unit",
        paths=lambda unit: [],
        deployment_input_paths=lambda units: [],
        file_digest=lambda path: "file",
    )
    timing = SimpleNamespace(phase=lambda *a, **kw: nullcontext())
    units = [{"name": "A", "deployOrder": 1}]
    with (
        patch.object(
            session._imports_deploy_context, "load_target", return_value=target
        ),
        patch.object(
            session._imports_deploy_context, "check_deploy_context", return_value=target
        ),
        patch.object(session.handoff, "locked", return_value=nullcontext()),
        patch.object(session.handoff, "effective", return_value={}),
        patch.object(
            session.handoff, "bind", side_effect=Blocked("initialized")
        ) as bind,
        TaskIO() as io,
    ):
        assert (
            session.run(
                args, root, timing, root, lambda *a: backend, lambda *a: (1, units)
            )
            == 2
        )
        saved = bind.call_args.args[2]
        assert saved["taskFile"] == "tasks/one.md" and saved[
            "taskDigest"
        ] == tasks.task_digest(text)
        assert saved["version"] == 5 and saved["repairBudget"] == 7
        assert saved["validationScope"] == ["dev/cde/s3"]
        assert io == {"reads": 1}


if __name__ == "__main__":
    raise SystemExit(run(__file__))
