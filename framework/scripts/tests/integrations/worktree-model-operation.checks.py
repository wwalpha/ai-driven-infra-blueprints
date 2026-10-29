#!/usr/bin/env python3
"""Parent deletion transactions use synthetic sources; no consumer checkout or AWS."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

import pytest
import task_contract_core as tasks
import worktree_task as wt
from import_guard import require_import_changes
from model.adapters.task import source_write_context
from model.sources import load_model
from support.model_sources import write_model
from support.worktree_task_fixtures import fixture as git_fixture
from support.worktree_task_fixtures import git
from utils.function_wrapper import BoundCallback as _bind_framework_callback

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.resource_delete_fixtures import (
    contract,
    deletion,
    fixture,
    write_candidate,
)


def _callback_check_one_parent_merge_and_failed_candidate_repair_final_check(
    name, /, repository, options, *, final_candidate
):
    try:
        with tasks.selected_task(repository, name):
            require_import_changes(repository, final_candidate=final_candidate)
    except ValueError:
        return 1
    return 0


def check_one_parent_merge_and_failed_candidate_repair():
    with git_fixture() as root:
        sources = fixture(root, True)
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "synthetic sources")
        with patch.object(wt.python_env, "setup", return_value={"status": "ready"}):
            state = wt.create(root, "parent")
        target = Path(state["worktree"])
        dependency_index.rebuild(target)
        name = state["task_file"]
        paths = sorted(
            {
                path.relative_to(target).as_posix()
                for source in sources
                for path in deletion(target, source)
            }
        )
        listed = "\n".join("- `" + path + "`" for path in [name, *paths])
        text = (
            contract(sources)
            + "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n"
            + (
                "## Validation scope\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n"
                "## Modified files\n" + listed + "\n## Allowed paths\n" + listed + "\n"
            )
        )
        tasks.start(target, name, text)
        for source in sources:
            with source_write_context(target, name) as context:
                write_candidate(context, deletion(target, source))
        final_check = _bind_framework_callback(
            _callback_check_one_parent_merge_and_failed_candidate_repair_final_check,
            name,
        )
        original_git = wt.git
        with (
            patch.object(wt, "git", wraps=original_git) as calls,
            patch("validation.loop.run_loop", side_effect=final_check) as validation,
        ):
            path = target / "model/stg/cde/service-a.properties"
            original = path.read_text()
            values = dict(load_model(path).authoritative)
            values["observed.row.006-001.value"] = "unauthorized"
            write_model(path, values)
            candidate = wt.prepare_integration(target, "parent")
            result = wt.validate_final_candidate(candidate)
            assert result.returncode == 1
            with pytest.raises(wt.Blocked, match="no merge"):
                wt.merge_validated_candidate(result)
            first_head = git(target, "rev-parse", "HEAD")
            assert git(root, "rev-parse", "HEAD") == candidate.base_commit
            assert target.is_dir()
            path.write_text(original)
            wt._integrate_model(target, "parent")
            assert (
                sum(call.args[1:2] == ("merge",) for call in calls.call_args_list) == 1
            )
            assert git(target, "rev-parse", "HEAD^") == first_head
            assert validation.call_count == 2
            assert tasks.status((target / name).read_text()) == "completed"
            assert git(root, "rev-parse", "HEAD") == git(target, "rev-parse", "HEAD")
        wt.cleanup(root, "parent")
        assert not target.exists()


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
