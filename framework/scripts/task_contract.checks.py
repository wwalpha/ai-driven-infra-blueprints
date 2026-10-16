#!/usr/bin/env python3
"""Regression checks for independent task selection, admission and ownership."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import pytest
from test_support.pytest_cli import run
import sync_runtime
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import hashlib
import os
from pathlib import Path
import subprocess
import shutil
from threading import Barrier, Event
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
    with pytest.raises(ValueError) as error:
        callback()
    assert message in str(error.value), str(error.value)


def git_identity(root, fallback=False):
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"}}
    result = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=root,
                            env=environment, capture_output=True, text=True, encoding="utf-8")
    with patch.object(tasks.subprocess, "run", wraps=subprocess.run) as run_git:
        if result.returncode:
            blocked(lambda: tasks.worktree_identity(root), "cannot determine Git worktree identity")
        else:
            expected = hashlib.sha256(str(Path(result.stdout.strip()).resolve()).encode()).hexdigest()
            assert tasks.worktree_identity(root) == expected
        if os.name != "posix" or os.geteuid() == 0:
            fallback = True
        assert run_git.call_count == int(fallback)


def check_identity_changes(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
        assert tasks.worktree_identity(root) == tasks.directory_identity(root)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        git_identity(root)
        shutil.rmtree(root / ".git")
        with patch.object(tasks.subprocess, "run", side_effect=AssertionError("non-Git compatibility")):
            assert tasks.worktree_identity(root) == tasks.directory_identity(root)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        git_identity(root)
        nested = root / "nested"
        nested.mkdir()
        assert tasks.worktree_identity(nested) == tasks.directory_identity(nested)
        (root / ".git").rename(root / "one")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".git").rename(root / "two")
        identities = []
        for reference in ("one", str(root / "two"), "one"):
            (root / ".git").write_text("gitdir: " + reference + "\n")
            git_identity(root)
            identities.append(tasks.worktree_identity(root))
        assert identities[0] == identities[2] != identities[1]
        (root / ".git").unlink()
        (root / ".git").symlink_to(root / "one", target_is_directory=True)
        git_identity(root, fallback=True)


@pytest.mark.parametrize("damage", ["gitfile", "encoding", "missing-target", "empty-target", "HEAD", "HEAD-symlink", "objects", "refs", "commondir", "config", "format", "boolean", "user-boolean", "include", "extensions", "valid-extension"])
def check_identity_fallback(tmp_path, damage):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        if damage in {"gitfile", "encoding", "missing-target", "empty-target"}:
            shutil.rmtree(root / ".git")
            content = b"not a gitfile\n"
            if damage == "encoding":
                content = b"gitdir: \xff\n"
            if damage in {"missing-target", "empty-target"}:
                content = b"gitdir: target\n"
            if damage == "empty-target":
                (root / "target").mkdir()
            (root / ".git").write_bytes(content)
        elif damage in {"objects", "refs"}:
            shutil.rmtree(root / ".git" / damage)
        elif damage == "HEAD":
            (root / ".git/HEAD").write_text("invalid\n")
        elif damage == "HEAD-symlink":
            target = root / "head"
            target.write_text("ref: refs/heads/main\n")
            (root / ".git/HEAD").unlink()
            (root / ".git/HEAD").symlink_to(target)
        elif damage == "commondir":
            (root / ".git/commondir").write_text("missing\n")
        elif damage == "config":
            (root / ".git/config").write_text("invalid!\n")
        elif damage == "format":
            (root / ".git/config").write_text("[core]\nrepositoryformatversion = 999\n")
        elif damage == "boolean":
            (root / ".git/config").write_text("[core]\nbare = invalid\n")
        elif damage == "user-boolean":
            (root / ".git/config").write_text("[user]\nuseconfigonly = invalid\n")
        elif damage == "include":
            (root / ".git/config").write_text("[include]\npath = ../bad-config\n")
            (root / "bad-config").write_text("invalid!\n")
        elif damage == "extensions":
            (root / ".git/config").write_text("[core]\nrepositoryformatversion = 1\n[extensions]\nunknown = true\n")
        elif damage == "valid-extension":
            (root / ".git/config").write_text("[core]\nrepositoryformatversion = 1\n[extensions]\nworktreeconfig = true\n")
        git_identity(root, fallback=True)


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_PAGER"])
def check_identity_environment(tmp_path, variable):
    with patch.dict(os.environ, {}, clear=True):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        override = tmp_path / "override"
        override.write_text("invalid!\n")
        with patch.dict(os.environ, {variable: str(override)}):
            git_identity(tmp_path, fallback=variable != "GIT_PAGER")
        git_identity(tmp_path)


def check_admission_selection(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
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


def check_completed_legacy_and_paths(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
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


def check_shared_issue_files(tmp_path):
    directory = tmp_path / "case-0"
    directory.mkdir()
    with patch.dict(os.environ, {}, clear=True):
        root = directory
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
    directory = tmp_path / "case-1"
    directory.mkdir()
    with patch.dict(os.environ, {}, clear=True):
        root = directory
        report = "issues/dev/cde/issues.md"
        tasks.start(root, first, contract(first, [report], kind="migration", scope="dev/cde/ec2"))
        tasks.start(root, second, contract(second, [report], kind="migration", scope="dev/cde/s3"))
        with patch.dict(os.environ, {tasks.SELECTOR: first}):
            save(root, "dev", "cde", ["ec2"], additions=[{"service": "ec2", "message": "retained issue"}])
        before = (root / report).read_bytes()
        with patch.dict(os.environ, {tasks.SELECTOR: second}), patch.object(tasks.time, "sleep") as sleep:
            with pytest.raises(tasks.DeferredExhausted):
                save(root, "dev", "cde", ["s3"])
            assert sleep.call_count == 20
        assert (root / report).read_bytes() == before
        tasks.complete(root, first)
        with patch.dict(os.environ, {tasks.SELECTOR: second}), patch.object(tasks.time, "sleep", side_effect=AssertionError("released report must not wait")):
            save(root, "dev", "cde", ["s3"], additions=[{"service": "s3", "message": "second issue"}])
        assert all(value in (root / report).read_text() for value in ("retained issue", "second issue"))

    directory = tmp_path / "case-2"
    directory.mkdir()
    root = directory
    blocked(lambda: tasks.start(root, first, contract(first, ["issues/../escape.md"])), "exact repository-relative path")
    (root / "issues").symlink_to(root / "elsewhere")
    blocked(lambda: tasks.start(root, first, contract(first, ["issues/issue.md"])), "symlinks")
    (root / "issues").unlink()
    outside = contract(first, ["issues/issue.md"]).replace(
        "## Allowed paths\n- `tasks/first.md`\n- `issues/issue.md`", "## Allowed paths\n- `tasks/first.md`")
    blocked(lambda: tasks.start(root, first, outside), "outside Allowed paths")


def check_simultaneous_registration(tmp_path):
    root = tmp_path
    def register(name):
        try:
            tasks.start(root, name, contract(name, ["future.md"]))
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, ["tasks/one.md", "tasks/two.md"]))
    assert 1 <= sum(results) <= 2  # A busy service_source remains retryable.
    for name in ("tasks/one.md", "tasks/two.md"):
        if not (root / name).exists():
            tasks.start(root, name, contract(name, ["future.md"]))
    entries = tasks.reservations(root, tasks.contracts(root))
    assert sum("future.md" in entry.active for entry in entries.values()) == 1
    assert sum("future.md" in entry.deferred for entry in entries.values()) == 1


def check_suspend_and_resume(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
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


def check_validator_isolation(tmp_path):
    spec = importlib.util.spec_from_file_location("validator", Path(__file__).with_name("validate-blueprint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
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


def check_deploy_update_ownership(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
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


def check_worktree_isolation(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        base = tmp_path
        root, linked = base / "main", base / "linked"
        root.mkdir()
        def git(where, *args):
            return subprocess.run(["git", *args], cwd=where, check=True, capture_output=True, text=True).stdout.strip()
        git(root, "init", "-q")
        git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "fixture")
        git(root, "worktree", "add", "--detach", str(linked), "HEAD")
        first, second = "tasks/first.md", "tasks/second.md"
        try:
            git_identity(root)
            git_identity(linked)
            dotgit = linked / ".git"
            reference = dotgit.read_text()
            directory = reference.removeprefix("gitdir: ").strip()
            dotgit.write_text("gitdir: " + os.path.relpath(directory, linked) + "\n")
            git_identity(linked)
            dotgit.write_text(reference)
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
            git_identity(root)
            git_identity(linked)
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



@pytest.mark.parametrize("transition", ["start", "refresh", "complete", "suspend", "resume"])
def check_atomic_contract_reads(tmp_path, transition):
    root = tmp_path
    name = "tasks/writer.md"
    owner = "tasks/owner.md"
    with patch.dict(os.environ, {}, clear=True):
        if transition != "start":
            tasks.start(root, owner, contract(owner, ["shared.md"]))
            tasks.start(root, name, contract(name, ["shared.md"]))
            tasks.complete(root, owner)
        if transition == "complete":
            tasks.refresh(root, name)
        if transition == "resume":
            tasks.suspend(root, name, "fixture stop")
        before = tasks.contracts(root)
        destination = root / name
        paused, release = Event(), Event()
        original_open, original_replace = Path.open, os.replace
        def pause():
            paused.set()
            assert release.wait(10), "reader did not release publication"
        def opening(path, mode="r", *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            if path == destination and mode in {"w", "x"}:
                pause()  # The old implementation has already truncated/created the file.
            return stream
        def replacing(source, target):
            if Path(target) == destination:
                pause()  # Atomic publication must still expose only the previous contract.
            return original_replace(source, target)
        operations = {
            "start": lambda: tasks.start(root, name, contract(name, ["shared.md"])),
            "refresh": lambda: tasks.refresh(root, name),
            "complete": lambda: tasks.complete(root, name),
            "suspend": lambda: tasks.suspend(root, name, "fixture stop"),
            "resume": lambda: tasks.resume(root, name),
        }
        with patch.object(Path, "open", opening), patch.object(os, "replace", replacing), ThreadPoolExecutor(max_workers=1) as executor:
            writer = executor.submit(operations[transition])
            try:
                assert paused.wait(10), "publication was not intercepted"
                during = tasks.contracts(root)
                for text in during.values():
                    tasks.status(text)
                assert during == before, "lock-free reader observed partial contract"
                tasks.reservations(root, during)
            finally:
                release.set()
                writer.result(timeout=10)
        tasks.reservations(root, tasks.contracts(root))
        assert not list(root.glob("tmp*")), "publication left a temporary file"


def check_deferred_acquisition_race(tmp_path):
    directory = tmp_path / "case-0"
    directory.mkdir()
    with patch.dict(os.environ, {}, clear=True):
        root = directory
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
                assert "service_source is busy" in str(error)
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
    directory = tmp_path / "case-1"
    directory.mkdir()
    with patch.dict(os.environ, {}, clear=True):
        root = directory
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


def check_deferred_validation(tmp_path):
    spec = importlib.util.spec_from_file_location("validator", Path(__file__).with_name("validate-blueprint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.dict(os.environ, {}, clear=True):
        root = tmp_path
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



def check_automatic_retry(tmp_path):
    directory = tmp_path / "case-0"
    directory.mkdir()
    with patch.dict(os.environ, {}, clear=True):
        root = directory
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

    directory = tmp_path / "case-1"
    directory.mkdir()
    with patch.dict(os.environ, {}, clear=True):
        root = directory
        owner, worker = "tasks/owner.md", "tasks/worker.md"
        tasks.start(root, owner, contract(owner, ["busy.md"]))
        tasks.start(root, worker, contract(worker, ["busy.md", "ready.md"]))
        owner_before = (root / owner).read_bytes()
        jobs = {file: [root / file] for file in ("busy.md", "ready.md")}
        with patch.object(tasks, "refresh", wraps=tasks.refresh) as refresh, patch.object(tasks.time, "sleep") as sleep:
            with pytest.raises(tasks.DeferredExhausted) as error:
                for file in tasks.reserved_batches(root, jobs, task_file=worker):
                    assert file == "ready.md"
                    (root / file).write_text("finished Active work")
            assert "unfinished" in str(error.value) and "20 retries" in str(error.value)
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
    directory = tmp_path / "case-2"
    directory.mkdir()
    with patch.dict(os.environ, {}, clear=True):
        root = directory
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
    directory = tmp_path / "case-3"
    directory.mkdir()
    with patch.dict(os.environ, {}, clear=True):
        root = directory
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
    print("Automatic Deferred retry: PASS (Active first, partial work, 30 sec x 20, clean exhaustion, restart, atomic groups, agent continuation)")




def main():
    return run(__file__, ['check_identity_changes', 'check_identity_fallback', 'check_identity_environment', 'check_atomic_contract_reads', 'check_automatic_retry', 'check_worktree_isolation', 'check_deferred_acquisition_race', 'check_deferred_validation', 'check_deploy_update_ownership', 'check_admission_selection', 'check_completed_legacy_and_paths', 'check_shared_issue_files', 'check_simultaneous_registration', 'check_suspend_and_resume', 'check_validator_isolation'], 'task-contract: PASS (worktree isolation, Active/Deferred, issue publication, concurrent acquisition, ownership, compatibility)')


if __name__ == "__main__":
    raise SystemExit(main())
