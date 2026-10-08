#!/usr/bin/env python3
"""Regression checks for independent task selection, admission and ownership."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import sync_runtime
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import shutil
from threading import Barrier
from unittest.mock import patch

import task_contract as tasks
from validation_scope import active_scope


def contract(name, files, state="running", kind="governance", scope="framework"):
    paths = [name, *files]
    listed = "\n".join(f"- `{path}`" for path in paths)
    return f"""# Task
## Task contract
- Task type: `{kind}`
- Task status: `{state}`
- Target: test
- Goal: test
## Validation scope
- `{scope}`
## Required changes
- [R1] Test
## Acceptance checks
- [R1] `changed:{files[0]}`
## Modified files
{listed}
## Allowed paths
{listed}
"""


def blocked(callback, message):
    try:
        callback()
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError(f"expected rejection: {message}")


def check_admission_selection():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        first = "tasks/first.md"
        second = "tasks/second.md"
        tasks.start(root, first, contract(first, ["new/file.md"]))
        assert tasks.task_path(root) == root / first
        assert active_scope(root) == set()
        # Admission reserves files that do not exist yet, without touching the existing task.
        before = (root / first).read_bytes()
        tasks.start(root, second, contract(second, ["new/file.md", "other.md"], kind="design", scope="dev/cde/ec2"))
        assert (root / first).read_bytes() == before
        entry = tasks.reservations(root, tasks.contracts(root))[second]
        assert entry.active == {second, "other.md"} and entry.deferred == {"new/file.md": (first,)}
        blocked(lambda: tasks.task_path(root), "multiple running tasks")
        with patch.dict(os.environ, {tasks.SELECTOR: second}):
            assert active_scope(root) == {("dev", "cde", "ec2")}
            tasks.require_writable(root, [root / "other.md"])
            blocked(lambda: tasks.require_writable(root, [root / "new/file.md"]), "Deferred file")
        blocked(lambda: tasks.task_path(root, "tasks/missing.md"), "missing")
        blocked(lambda: tasks.task_path(root, "../first.md"), "invalid task selector")
        changed = {first, second, "new/file.md", "other.md"}
        assert tasks.task_changes(root, changed, second) == {second, "other.md"}
        blocked(lambda: tasks.task_changes(root, changed | {"unowned.md"}, first), "no task reservation")
        # Any later scope expansion is checked again by readers, before writing.
        text = (root / second).read_text().replace("## Modified files\n", "## Modified files\n- `later.md`\n").replace("## Allowed paths\n", "## Allowed paths\n- `later.md`\n")
        (root / second).write_text(text)
        assert tasks.task_path(root, first) == root / first
        with patch.dict(os.environ, {tasks.SELECTOR: second}):
            blocked(lambda: tasks.require_writable(root, [root / "later.md"]), "awaiting reservation refresh")
        tasks.refresh(root, second)
        with patch.dict(os.environ, {tasks.SELECTOR: second}):
            tasks.require_writable(root, [root / "later.md"])
        assert "new/file.md" in tasks.reservations(root, tasks.contracts(root))[second].deferred
        blocked(lambda: tasks.complete(root, second), "Deferred files")
        blocked(lambda: tasks.set_status((root / second).read_text(), "completed"), "Deferred files")
        tasks.complete(root, first)
        # Release alone cannot assign the previous owner's dirty output to the waiter.
        assert tasks.task_changes(root, changed, second) == {second, "other.md"}
        tasks.refresh(root, second)
        saved = (root / second).read_bytes()
        tasks.refresh(root, second)
        assert (root / second).read_bytes() == saved, "refresh must preserve unchanged contract digests"
        assert not tasks.reservations(root, tasks.contracts(root))[second].deferred
        with patch.dict(os.environ, {tasks.SELECTOR: second}):
            tasks.require_writable(root, [root / "new/file.md"])
        tasks.complete(root, second)


def check_completed_legacy_and_paths():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        old = "tasks/old.md"
        new = "tasks/new.md"
        tasks.start(root, old, contract(old, ["README.md", "old.md"]))
        (root / old).write_text(contract(old, ["README.md", "old.md"], state="completed"))
        tasks.start(root, new, contract(new, ["README.md"]))
        assert tasks.task_path(root) == root / new
        changed = {old, new, "README.md", "old.md", "tasks/removed.md"}
        assert tasks.task_changes(root, changed, new) == {new, "README.md"}
        assert tasks.task_changes(root, changed, old) == {old, "old.md"}
        with patch.dict(os.environ, {tasks.SELECTOR: old}):
            blocked(lambda: tasks.require_writable(root, [root / "old.md"]), "completed task")
        for name in (old, new):
            (root / name).unlink()
        legacy = contract("tasks/active.md", ["README.md"])
        legacy = legacy.replace("- Task status: `running`\n", "")
        legacy = legacy[:legacy.index("## Modified files")] + "## Allowed paths\n- `README.md`\n- `tasks/active.md`\n"
        (root / "tasks/active.md").write_text(legacy)
        assert tasks.task_path(root) == root / "tasks/active.md"
        assert tasks.task_changes(root, {"README.md"}, "tasks/active.md") == {"README.md"}
        blocked(lambda: tasks.start(root, new, contract(new, ["new.md"])), "migrate tasks/active.md")
        tasks.suspend(root, "tasks/active.md", "legacy check failed: README.md")
        blocked(lambda: tasks.task_path(root), "suspend task cannot execute")
        tasks.resume(root, "tasks/active.md")
        assert tasks.task_path(root) == root / "tasks/active.md"
        (root / "tasks/active.md").unlink()
        for value in ("../escape", "/tmp/escape", "./file", "a//file", "a/../file", "*.md", "a/**", ".git/config", "."):
            blocked(lambda value=value: tasks.start(root, new, contract(new, [value])), "exact repository-relative path")
        (root / "linked").symlink_to(root / "elsewhere")
        blocked(lambda: tasks.start(root, new, contract(new, ["linked/file.md"])), "symlinks")
        blocked(lambda: tasks.start(root, new, contract(new, [old])), "another contract")
        blocked(lambda: tasks.start(root, new, contract(new, ["file.md", "file.md"])), "duplicate paths")
        blocked(lambda: tasks.start(root, new, contract(new, ["file.md"], state="paused")), "Task status")


def check_shared_issue_files():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        first, second = "tasks/first.md", "tasks/second.md"
        reports = ["issues/issue.md", "issues/dev/cde/issues.md", "issues/dev/cde/diff.md",
                   "issues/deep/nested/result.json"]
        tasks.start(root, first, contract(first, [*reports, "first.md"]))
        before = (root / first).read_bytes()
        tasks.start(root, second, contract(second, [*reports, "second.md"]))
        assert (root / first).read_bytes() == before
        changed = {first, second, *reports, "first.md", "second.md"}
        assert tasks.task_changes(root, changed, first) == {first, "first.md", *reports}
        assert tasks.task_changes(root, changed, second) == {second, "second.md"}
        with patch.dict(os.environ, {tasks.SELECTOR: second}):
            tasks.require_writable(root, [root / "second.md"])
            for path in reports:
                blocked(lambda path=path: tasks.require_writable(root, [root / path]), "Deferred file")
            blocked(lambda: tasks.require_writable(root, [root / "issues/unlisted.md"]), "no selected task reservation")
        blocked(lambda: tasks.task_changes(root, changed | {"issues/unlisted.md"}, first), "no task reservation")
        tasks.suspend(root, first, "report check failed: issues/issue.md")
        tasks.refresh(root, second)
        tasks.resume(root, first)
        assert set(tasks.reservations(root, tasks.contracts(root))[first].deferred) == set(reports)
        with patch.dict(os.environ, {tasks.SELECTOR: second}):
            tasks.require_writable(root, [root / path for path in reports])
        third = "tasks/third.md"
        tasks.start(root, third, contract(third, [*reports, "first.md"]))
        assert set(tasks.reservations(root, tasks.contracts(root))[third].deferred) == {*reports, "first.md"}

    # Report merge/publication retains its existing lock, content retention and save-only gate.
    from issues_reports import save
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        report = "issues/dev/cde/issues.md"
        tasks.start(root, first, contract(first, [report], kind="migration", scope="dev/cde/ec2"))
        tasks.start(root, second, contract(second, [report], kind="migration", scope="dev/cde/s3"))
        with patch.dict(os.environ, {tasks.SELECTOR: first}):
            save(root, "dev", "cde", ["ec2"], additions=[{"service": "ec2", "message": "retained issue"}])
        before = (root / report).read_bytes()
        with patch.dict(os.environ, {tasks.SELECTOR: second}), patch.object(tasks.time, "sleep") as sleep:
            try:
                save(root, "dev", "cde", ["s3"])
            except tasks.DeferredExhausted:
                assert sleep.call_count == 20
            else:
                raise AssertionError("busy report must remain unfinished")
        assert (root / report).read_bytes() == before
        tasks.complete(root, first)
        with patch.dict(os.environ, {tasks.SELECTOR: second}), patch.object(tasks.time, "sleep", side_effect=AssertionError("released report must not wait")):
            save(root, "dev", "cde", ["s3"], additions=[{"service": "s3", "message": "second issue"}])
        assert all(value in (root / report).read_text() for value in ("retained issue", "second issue"))

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        blocked(lambda: tasks.start(root, first, contract(first, ["issues/../escape.md"])), "exact repository-relative path")
        (root / "issues").symlink_to(root / "elsewhere")
        blocked(lambda: tasks.start(root, first, contract(first, ["issues/issue.md"])), "symlinks")
        (root / "issues").unlink()
        outside = contract(first, ["issues/issue.md"]).replace(
            "## Allowed paths\n- `tasks/first.md`\n- `issues/issue.md`", "## Allowed paths\n- `tasks/first.md`")
        blocked(lambda: tasks.start(root, first, outside), "outside Allowed paths")


def check_simultaneous_registration():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        def register(name):
            try:
                tasks.start(root, name, contract(name, ["future.md"]))
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(register, ["tasks/one.md", "tasks/two.md"]))
        assert 1 <= sum(results) <= 2  # A busy registration remains retryable.
        for name in ("tasks/one.md", "tasks/two.md"):
            if not (root / name).exists():
                tasks.start(root, name, contract(name, ["future.md"]))
        entries = tasks.reservations(root, tasks.contracts(root))
        assert sum("future.md" in entry.active for entry in entries.values()) == 1
        assert sum("future.md" in entry.deferred for entry in entries.values()) == 1


def check_suspend_and_resume():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        first, second = "tasks/first.md", "tasks/second.md"
        tasks.start(root, first, contract(first, ["shared.md", "own.md"]))
        blocked(lambda: tasks.suspend(root, first, " "), "concrete reason")
        assert tasks.suspend(root, first, "other task: schema failure in model/dev/cde/ec2.properties")
        saved = (root / first).read_bytes()
        assert tasks.status(saved.decode()) == "suspend"
        assert "schema failure in model/dev/cde/ec2.properties" in saved.decode()
        assert tasks.task_path(root) == root / "tasks/active.md"
        assert active_scope(root) == set()
        assert tasks.task_changes(root, {"shared.md", "own.md"}) == set()
        with patch.dict(os.environ, {tasks.SELECTOR: first}):
            blocked(lambda: tasks.require_writable(root, [root / "own.md"]), "suspend task cannot execute")
        tasks.start(root, second, contract(second, ["shared.md"]))
        assert tasks.task_path(root) == root / second
        assert tasks.task_changes(root, {"shared.md", "own.md"}, second) == {"shared.md"}
        tasks.resume(root, first)
        entry = tasks.reservations(root, tasks.contracts(root))[first]
        assert entry.active == {first, "own.md"} and entry.deferred == {"shared.md": (second,)}
        assert "## Suspension reason" not in (root / first).read_text()
        with patch.dict(os.environ, {tasks.SELECTOR: first}):
            tasks.require_writable(root, [root / "own.md"])
            blocked(lambda: tasks.require_writable(root, [root / "shared.md"]), "Deferred file")
        tasks.suspend(root, first, "own check failed")
        saved = (root / first).read_bytes()
        other = (root / second).read_bytes()
        assert not tasks.suspend(root, first, "overwrite")
        assert (root / first).read_bytes() == saved and (root / second).read_bytes() == other
        tasks.suspend(root, second, "own acceptance check failed: changed:shared.md")
        tasks.resume(root, first)
        assert tasks.status((root / first).read_text()) == "running"
        assert "## Suspension reason" not in (root / first).read_text()
        tasks.resume(root, second)
        assert tasks.reservations(root, tasks.contracts(root))[second].deferred == {"shared.md": (first,)}
        # Invalid other contracts cannot prevent suspension of the explicitly selected task.
        (root / second).write_text("invalid contract")
        assert tasks.suspend(root, first, "invalid contract: tasks/second.md")
        blocked(lambda: tasks.status(contract(first, ["shared.md"], state="suspend")), "Suspension reason")
        # A reason is diagnostic text, even if an error contains Markdown headings.
        (root / second).unlink()
        tasks.resume(root, first)
        tasks.suspend(root, first, "error\n## Modified files\n- `unexpected.md`")
        assert tasks.paths_in((root / first).read_text(), "## Modified files") == {first, "shared.md", "own.md"}


def check_validator_isolation():
    spec = importlib.util.spec_from_file_location("validator", Path(__file__).with_name("validate-blueprint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        first, second = "tasks/one.md", "tasks/two.md"
        tasks.start(root, first, contract(first, ["README.md", "日本語 file.md"]))
        tasks.start(root, second, contract(second, ["tests/scenarios/a/scenario.md"], kind="scenario-test", scope="dev/cde/ec2"))
        (root / "README.md").write_text("changed")
        (root / "日本語 file.md").write_text("changed")
        scenario = root / "tests/scenarios/a/scenario.md"
        scenario.parent.mkdir(parents=True)
        scenario.write_text("scenario")
        with patch.dict(os.environ, {tasks.SELECTOR: first}):
            validator = module.Validator(root)
            validator.check_task_scope()
            validator.check_task_type_requirements()
            validator.check_acceptance_checks()
            assert not validator.errors, validator.errors
            assert validator.changed_paths == {first, "README.md", "日本語 file.md"}
            assert validator.acceptance_results == ["R1:changed:README.md"]
            # Another task's file cannot satisfy this task's acceptance.
            (root / first).write_text((root / first).read_text().replace("changed:README.md", "changed:tests/scenarios/**"))
            validator = module.Validator(root)
            validator.check_task_scope()
            validator.check_acceptance_checks()
            assert any("required changed path missing" in error for error in validator.errors)
        for name in (first, second):
            path = root / name
            path.write_text(path.read_text().replace("- Task status: `running`", "- Task status: `completed`"))
        assert active_scope(root) == set()
        validator = module.Validator(root)
        validator.check_task_scope()
        validator.check_task_type_requirements()
        assert not validator.errors and not validator.task_type, validator.errors
        (root / "unowned.md").write_text("changed")
        blocked(lambda: module.Validator(root).check_task_scope(), "no task reservation")


def check_deploy_update_ownership():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        dev, stg = "tasks/dev-deploy.md", "tasks/stg-update.md"
        dev_path = "infra/cloudformation/parameters/dev/cde/a.json"
        stg_path = "infra/cloudformation/parameters/stg/cde/other.json"
        for name, path, phase, scope in ((dev, dev_path, "deploy", "dev/cde/ec2"),
                                         (stg, stg_path, "update", "stg/cde/ec2")):
            text = contract(name, [path], kind="infrastructure", scope=scope)
            text = text.replace("- Task type: `infrastructure`", f"- Task type: `infrastructure`\n- Infrastructure phase: `{phase}`")
            tasks.start(root, name, text)
        entries = tasks.reservations(root, tasks.contracts(root))
        assert all(entry.state == "running" and not entry.deferred for entry in entries.values())
        def no_wait(seconds):
            raise AssertionError("non-overlapping work must not wait")
        for name, path in ((dev, dev_path), (stg, stg_path)):
            assert list(tasks.reserved_batches(root, {"write": [root / path]}, no_wait, name)) == ["write"]
        changed = {dev, stg, dev_path, stg_path}
        assert tasks.task_changes(root, changed, dev) == {dev, dev_path}
        assert tasks.task_changes(root, changed, stg) == {stg, stg_path}
        blocked(lambda: tasks.task_changes(root, changed | {"infra/unowned.json"}, dev), "no task reservation")
        (root / stg).write_text((root / stg).read_text().replace("## Modified files\n", f"## Modified files\n- `{dev_path}`\n").replace("## Allowed paths\n", f"## Allowed paths\n- `{dev_path}`\n"))
        tasks.refresh(root, stg)
        assert tasks.task_changes(root, changed, dev) == {dev, dev_path}
        assert tasks.task_changes(root, changed, stg) == {stg, stg_path}
        with patch.dict(os.environ, {tasks.SELECTOR: stg}):
            blocked(lambda: tasks.require_writable(root, [root / dev_path]), "Deferred file")
    print("Deploy/update ownership: PASS (F isolation, unowned changes and reservation conflicts blocked)")


def check_worktree_isolation():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        base = Path(directory).resolve()
        root, linked = base / "main", base / "linked"
        root.mkdir()
        def git(where, *args):
            return subprocess.run(["git", *args], cwd=where, check=True, capture_output=True, text=True).stdout.strip()
        git(root, "init", "-q")
        git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "fixture")
        git(root, "worktree", "add", "--detach", str(linked), "HEAD")
        first, second = "tasks/first.md", "tasks/second.md"
        try:
            identities = tasks.worktree_identity(root), tasks.worktree_identity(linked)
            assert identities[0] != identities[1]
            tasks.start(root, first, contract(first, ["a.md", "b.yaml"]))
            (linked / "tasks").mkdir()
            shutil.copyfile(root / first, linked / first)
            # A lock held in WT1 cannot prevent admission in WT2.
            with tasks.registration_lock(root):
                tasks.start(linked, second, contract(second, ["b.yaml", "c.md"]))
            assert tasks.task_path(root) == root / first
            assert tasks.task_path(linked) == linked / second
            assert len(tasks.contracts(linked)) == 1
            assert len(tasks.contracts(linked, include_foreign=True)) == 2
            assert tasks.reservations(root, tasks.contracts(root))[first].active == {first, "a.md", "b.yaml"}
            assert tasks.reservations(linked, tasks.contracts(linked, include_foreign=True))[second].active == {second, "b.yaml", "c.md"}
            assert tasks.task_changes(linked, {first, second, "b.yaml", "c.md"}, second) == {second, "b.yaml", "c.md"}
            for where, own, foreign in ((root, first, second), (linked, second, first)):
                if not (where / foreign).exists():
                    shutil.copyfile(linked / foreign, where / foreign)
                with patch.dict(os.environ, {tasks.SELECTOR: own}):
                    tasks.require_writable(where, [where / "b.yaml"])
                    with patch.object(tasks.time, "sleep", side_effect=AssertionError("foreign owner must never wait")), patch.object(tasks, "refresh", wraps=tasks.refresh) as refresh:
                        assert list(tasks.reserved_batches(where, {"write": [where / "b.yaml"]})) == ["write"]
                        assert refresh.call_count == 1  # startup refresh, zero retry
                for callback in (lambda: tasks.task_path(where, foreign),
                                 lambda: tasks.task_changes(where, {"b.yaml"}, foreign),
                                 lambda: tasks.refresh(where, foreign), lambda: tasks.resume(where, foreign),
                                 lambda: tasks.wait_deferred(where, foreign),
                                 lambda: list(tasks.reserved_batches(where, {"write": [where / "b.yaml"]}, task_file=foreign)),
                                 lambda: tasks.suspend(where, foreign, "failure"), lambda: tasks.complete(where, foreign)):
                    blocked(callback, "another worktree")
                with patch.dict(os.environ, {tasks.SELECTOR: foreign}):
                    blocked(lambda: tasks.require_writable(where, [where / "b.yaml"]), "another worktree")
                assert str(where) not in (where / own).read_text()
            # Branch rename and detached HEAD have no effect on either identity.
            git(root, "branch", "-m", "renamed")
            git(linked, "checkout", "-qb", "linked-branch")
            git(linked, "checkout", "--detach", "-q")
            assert identities == (tasks.worktree_identity(root), tasks.worktree_identity(linked))
            tasks.resume(linked, second)
            # Foreign execution errors and validation metadata must not affect local readers.
            (linked / first).write_text((linked / first).read_text().replace("`running`", "`invalid`", 1))
            assert tasks.task_path(linked) == linked / second
            tasks.complete(linked, second)
            (linked / second).unlink()
            assert tasks.task_path(linked) == linked / "tasks/active.md"
            assert active_scope(linked) == set()
            assert tasks.task_changes(linked, {first}) == set()
            blocked(lambda: tasks.task_changes(linked, {"unowned.md"}), "no task reservation")
            blocked(lambda: tasks.require_writable(linked, [linked / "b.yaml"]), "active task prompt missing")
        finally:
            git(root, "worktree", "remove", "--force", str(linked))
    print("Worktree isolation: PASS (main/linked, detached/renamed, foreign selection/ownership, independent locks)")


def check_deferred_acquisition_race():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        owner, one, two = "tasks/owner.md", "tasks/one.md", "tasks/two.md"
        tasks.start(root, owner, contract(owner, ["shared.md"]))
        for name in (one, two):
            tasks.start(root, name, contract(name, ["shared.md", name.removeprefix("tasks/")]))
        tasks.complete(root, owner)
        barrier = Barrier(2)
        def acquire(name):
            barrier.wait()
            try:
                tasks.resume(root, name)
                return True
            except ValueError as error:
                assert "registration is busy" in str(error)
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(acquire, (one, two)))
        for name, success in zip((one, two), results):
            if not success:
                tasks.resume(root, name)
        entries = tasks.reservations(root, tasks.contracts(root))
        assert sum("shared.md" in entries[name].active for name in (one, two)) == 1
        assert sum("shared.md" in entries[name].deferred for name in (one, two)) == 1
        assert all(entries[name].state == "running" for name in (one, two))

    # The automatic worker path uses the same mutex: two waiting workers cannot
    # both acquire, even when their retries race after an owner's completion.
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        tasks.start(root, owner, contract(owner, ["shared.md"]))
        for name in (one, two):
            tasks.start(root, name, contract(name, ["shared.md"]))
        tasks.complete(root, owner)
        barrier = Barrier(2)
        def work(name):
            barrier.wait()
            try:
                return list(tasks.reserved_batches(root, {"write": [root / "shared.md"]}, lambda seconds: None, name))
            except tasks.DeferredExhausted:
                return []
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(work, (one, two)))
        assert sorted(results) == [[], ["write"]], results
        entries = tasks.reservations(root, tasks.contracts(root))
        assert sum("shared.md" in entries[name].active for name in (one, two)) == 1
        assert sum("shared.md" in entries[name].deferred for name in (one, two)) == 1


def check_deferred_validation():
    spec = importlib.util.spec_from_file_location("validator", Path(__file__).with_name("validate-blueprint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
        first, second = "tasks/first.md", "tasks/second.md"
        tasks.start(root, first, contract(first, ["b.yaml"]))
        text = contract(second, ["b.yaml", "c.md"])
        text = text.replace("## Acceptance checks\n", "## Acceptance checks\n- [R1] `changed:c.md`\n- [R1] `exists:b.yaml`\n- [R1] `absent:b.yaml`\n")
        tasks.start(root, second, text)
        (root / "b.yaml").write_text("belongs to first")
        (root / "c.md").write_text("belongs to second")
        with patch.dict(os.environ, {tasks.SELECTOR: second}):
            validator = module.Validator(root)
            validator.check_task_scope()
            validator.check_task_type_requirements()
            validator.check_acceptance_checks()
            assert not validator.errors, validator.errors
            assert validator.acceptance_results == ["R1:changed:c.md"]
            assert len(validator.deferred_acceptance) == 3
            assert validator.changed_paths == {second, "c.md"}
        blocked(lambda: tasks.complete(root, second), "Deferred files")
        # Even a manual completed status cannot pass the reservation validator.
        path = root / second
        text = path.read_text()
        path.write_text(text.replace("`running`", "`completed`", 1))
        blocked(lambda: tasks.reservations(root, tasks.contracts(root)), "completed task has Deferred files")
        path.write_text(text)
        tasks.complete(root, first)
        tasks.refresh(root, second)
        assert not tasks.reservations(root, tasks.contracts(root))[second].deferred



def check_automatic_retry():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        one, two, worker = "tasks/one.md", "tasks/two.md", "tasks/worker.md"
        tasks.start(root, one, contract(one, ["a.md"]))
        tasks.start(root, two, contract(two, ["b.md"]))
        tasks.start(root, worker, contract(worker, ["a.md", "b.md", "c.md"]))
        events, sleeps = [], []
        def sleep(seconds):
            assert events[0] == "c.md", "Active work must finish before waiting"
            sleeps.append(seconds)
            if len(sleeps) == 3:
                tasks.complete(root, one)
            if len(sleeps) == 5:
                assert events == ["c.md", "a.md"], "partial acquisition must execute immediately"
                tasks.complete(root, two)
        jobs = {file: [root / file] for file in ("a.md", "b.md", "c.md")}
        for file in tasks.reserved_batches(root, jobs, sleep, worker):
            tasks.require_writable(root, jobs[file], worker)
            (root / file).write_text(file)
            events.append(file)
            if file == "a.md":
                entry = tasks.reservations(root, tasks.contracts(root))[worker]
                assert "b.md" in entry.deferred
                blocked(lambda: tasks.complete(root, worker), "Deferred files")
        assert events == ["c.md", "a.md", "b.md"] and sleeps == [30] * 5
        assert not tasks.reservations(root, tasks.contracts(root))[worker].deferred
        tasks.complete(root, worker)

    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        owner, worker = "tasks/owner.md", "tasks/worker.md"
        tasks.start(root, owner, contract(owner, ["busy.md"]))
        tasks.start(root, worker, contract(worker, ["busy.md", "ready.md"]))
        owner_before = (root / owner).read_bytes()
        jobs = {file: [root / file] for file in ("busy.md", "ready.md")}
        with patch.object(tasks, "refresh", wraps=tasks.refresh) as refresh, patch.object(tasks.time, "sleep") as sleep:
            try:
                for file in tasks.reserved_batches(root, jobs, task_file=worker):
                    assert file == "ready.md"
                    (root / file).write_text("finished Active work")
            except tasks.DeferredExhausted as error:
                assert "unfinished" in str(error) and "20 retries" in str(error)
            else:
                raise AssertionError("must cleanly exhaust, without yielding a Deferred write")
            assert sleep.call_count == 20 and all(call.args == (30,) for call in sleep.call_args_list)
            # Startup and post-Active refresh, then exactly 20 waiting attempts.
            assert refresh.call_count == 22
        entry = tasks.reservations(root, tasks.contracts(root))[worker]
        assert entry.state == "running" and entry.deferred == {"busy.md": (owner,)}
        assert (root / owner).read_bytes() == owner_before and not (root / "busy.md").exists()
        blocked(lambda: tasks.complete(root, worker), "Deferred files")
        tasks.complete(root, owner)
        with patch.object(tasks.time, "sleep", side_effect=AssertionError("free file must not wait")):
            assert list(tasks.reserved_batches(root, {"busy": [root / "busy.md"]}, task_file=worker)) == ["busy"]
        assert not tasks.reservations(root, tasks.contracts(root))[worker].deferred
        # Invalid outputs remain real failures, with no retry or status change.
        with patch.object(tasks.time, "sleep", side_effect=AssertionError("invalid output must fail immediately")):
            blocked(lambda: list(tasks.reserved_batches(root, {"bad": [root / "unreserved.md"]}, task_file=worker)), "no selected task reservation")
        assert tasks.status((root / worker).read_text()) == "running"

    # An indivisible output group must wait as a unit; independent jobs proceed.
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        tasks.start(root, owner, contract(owner, ["generated.json"]))
        tasks.start(root, worker, contract(worker, ["generated.json", "generated.md", "independent.md"]))
        events = []
        def release(seconds):
            assert seconds == 30 and events == ["independent"]
            tasks.complete(root, owner)
        for job in tasks.reserved_batches(root, {"bundle": [root / "generated.json", root / "generated.md"],
                                                 "independent": [root / "independent.md"]}, release, worker):
            events.append(job)
        assert events == ["independent", "bundle"]

    # Agent waiting returns on partial acquisition so acquired work precedes more waiting.
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        tasks.start(root, one, contract(one, ["a.md"]))
        tasks.start(root, two, contract(two, ["b.md"]))
        tasks.start(root, worker, contract(worker, ["a.md", "b.md"]))
        def release(seconds):
            assert seconds == 30
            tasks.complete(root, one)
        assert tasks.wait_deferred(root, worker, release) == {"a.md"}
        assert "b.md" in tasks.reservations(root, tasks.contracts(root))[worker].deferred
        with patch.object(tasks.time, "sleep") as sleep, patch.dict(os.environ, {tasks.SELECTOR: worker}), patch("sys.argv", ["task_contract.py", "--repository-root", str(root), "--task-file", worker, "--wait"]):
            assert tasks.main() == 0 and sleep.call_count == 20
        assert tasks.status((root / worker).read_text()) == "running"
    # Waiting must not weaken the one-time import's existing no-overwrite rule.
    spec = importlib.util.spec_from_file_location("retry_sync", Path(__file__).with_name("sync-model.py"))
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        output = "model/dev/cde/ec2.properties"
        source = root / "docs/designs/dev/cde/ec2.md"
        source.parent.mkdir(parents=True)
        source.write_text("# source")
        tasks.start(root, owner, contract(owner, [output], kind="migration", scope="dev/cde/ec2"))
        tasks.start(root, worker, contract(worker, [output], kind="migration", scope="dev/cde/ec2"))
        def create_model(seconds):
            assert seconds == 30
            (root / output).parent.mkdir(parents=True)
            (root / output).write_text("owner's authoritative model")
            tasks.complete(root, owner)
        with patch.dict(os.environ, {tasks.SELECTOR: worker}), patch.object(tasks.time, "sleep", side_effect=create_model), patch.object(sync_runtime, "imported_model", return_value="desired.service.ec2.serviceId=ec2\n"):
            blocked(lambda: sync.sync(root, True, "dev", "cde", import_markdown=True, services=["ec2"]), "must not overwrite")
        assert (root / output).read_text() == "owner's authoritative model"
    print("Automatic Deferred retry: PASS (Active first, partial work, 30 sec x 20, clean exhaustion, restart, atomic groups, agent continuation)")


if __name__ == "__main__":
    check_automatic_retry()
    check_worktree_isolation()
    check_deferred_acquisition_race()
    check_deferred_validation()
    check_deploy_update_ownership()
    check_admission_selection()
    check_completed_legacy_and_paths()
    check_shared_issue_files()
    check_simultaneous_registration()
    check_suspend_and_resume()
    check_validator_isolation()
    print("task-contract: PASS (worktree isolation, Active/Deferred, issue publication, concurrent acquisition, ownership, compatibility)")
