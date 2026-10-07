#!/usr/bin/env python3
"""Regression checks for independent task selection, admission and ownership."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
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
        blocked(lambda: tasks.start(root, second, contract(second, ["new/file.md"])), "task file conflict")
        assert not (root / second).exists() and (root / first).read_bytes() == before
        tasks.start(root, second, contract(second, ["other.md"], kind="design", scope="dev/cde/ec2"))
        blocked(lambda: tasks.task_path(root), "multiple running tasks")
        with patch.dict(os.environ, {tasks.SELECTOR: second}):
            assert active_scope(root) == {("dev", "cde", "ec2")}
            tasks.require_writable(root, [root / "other.md"])
            blocked(lambda: tasks.require_writable(root, [root / "new/file.md"]), "no selected task reservation")
        blocked(lambda: tasks.task_path(root, "tasks/missing.md"), "missing")
        blocked(lambda: tasks.task_path(root, "../first.md"), "invalid task selector")
        changed = {first, second, "new/file.md", "other.md"}
        assert tasks.task_changes(root, changed, second) == {second, "other.md"}
        blocked(lambda: tasks.task_changes(root, changed | {"unowned.md"}, first), "no task reservation")
        # Any later scope expansion is checked again by readers, before writing.
        (root / second).write_text(contract(second, ["other.md", "new/file.md"]))
        blocked(lambda: tasks.task_path(root, first), "task file conflict")


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
        blocked(lambda: tasks.task_path(root), "multiple running tasks")
        changed = {first, second, *reports, "first.md", "second.md"}
        for name, own in [(first, "first.md"), (second, "second.md")]:
            assert tasks.task_changes(root, changed, name) == {name, own, *reports}
            with patch.dict(os.environ, {tasks.SELECTOR: name}):
                tasks.require_writable(root, [root / path for path in reports])
                blocked(lambda: tasks.require_writable(root, [root / "issues/unlisted.md"]),
                        "no selected task reservation")
        blocked(lambda: tasks.task_changes(root, changed | {"issues/unlisted.md"}, first),
                "no task reservation")
        # Report overlap is also allowed when resuming and when extending a contract.
        tasks.suspend(root, first, "report check failed: issues/issue.md")
        tasks.resume(root, first)
        assert tasks.task_path(root, first) == root / first
        (root / first).write_text(contract(first, [*reports, "first.md", "issues/new.txt"]))
        (root / second).write_text(contract(second, [*reports, "second.md", "issues/new.txt"]))
        tasks.reservations(root, tasks.contracts(root))
        # An exempt overlap cannot hide an ordinary conflict or appear in its diagnostic.
        third = "tasks/third.md"
        try:
            tasks.start(root, third, contract(third, [*reports, "first.md"]))
        except ValueError as error:
            assert "task file conflict" in str(error) and "first.md" in str(error)
            assert not any(path in str(error) for path in reports), str(error)
        else:
            raise AssertionError("ordinary file overlap must block mixed-report admission")
        assert not (root / third).exists()

    for path in ["issue.md", "issues.md", "issues-other/issue.md", "docs/issues/issue.md"]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks.start(root, first, contract(first, [path]))
            blocked(lambda: tasks.start(root, second, contract(second, [path])), "task file conflict")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        blocked(lambda: tasks.start(root, first, contract(first, ["issues/../escape.md"])),
                "exact repository-relative path")
        (root / "issues").symlink_to(root / "elsewhere")
        blocked(lambda: tasks.start(root, first, contract(first, ["issues/issue.md"])), "symlinks")
        (root / "issues").unlink()
        outside = contract(first, ["issues/issue.md"]).replace(
            "## Allowed paths\n- `tasks/first.md`\n- `issues/issue.md`",
            "## Allowed paths\n- `tasks/first.md`")
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
        assert sum(results) == 1
        assert len(tasks.contracts(root)) == 1


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
        blocked(lambda: tasks.resume(root, first), "task file conflict")
        assert (root / first).read_bytes() == saved, "failed resume must preserve status and reason"
        other = (root / second).read_bytes()
        assert not tasks.suspend(root, first, "overwrite")
        assert (root / first).read_bytes() == saved and (root / second).read_bytes() == other
        tasks.suspend(root, second, "own acceptance check failed: changed:shared.md")
        tasks.resume(root, first)
        assert tasks.status((root / first).read_text()) == "running"
        assert "## Suspension reason" not in (root / first).read_text()
        blocked(lambda: tasks.resume(root, second), "task file conflict")
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
        changed = {dev, stg, dev_path, stg_path}
        assert tasks.task_changes(root, changed, dev) == {dev, dev_path}
        assert tasks.task_changes(root, changed, stg) == {stg, stg_path}
        blocked(lambda: tasks.task_changes(root, changed | {"infra/unowned.json"}, dev), "no task reservation")
        (root / stg).write_text((root / stg).read_text().replace(stg_path, dev_path))
        blocked(lambda: tasks.task_changes(root, changed, dev), "task file conflict")
    print("Deploy/update ownership: PASS (F isolation, unowned changes and reservation conflicts blocked)")


if __name__ == "__main__":
    check_deploy_update_ownership()
    check_admission_selection()
    check_completed_legacy_and_paths()
    check_shared_issue_files()
    check_simultaneous_registration()
    check_suspend_and_resume()
    check_validator_isolation()
    print("task-contract: PASS (selection, conflict, shared issue files, future files, concurrent admission, ownership, compatibility)")
