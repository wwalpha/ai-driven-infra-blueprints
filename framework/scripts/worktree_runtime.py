"""Registered-Python guards for Model and Framework integration."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from types import SimpleNamespace

import model.sources as _imports_model_sources
import task_contract_core as tasks
import validation.loop as _imports_validation_loop
import validation_scope as _imports_validation_scope
import worktree_task as wt

import model as _model_api


def prepare_integration(where: Path, task_id: str) -> wt.FinalCandidate:
    """Commit/rebase a private Model or Framework candidate before final validation."""
    root, _, path, state = wt.load(where, task_id)
    with wt.lifecycle_lock(root):
        root, _, path, state = wt.load(root, task_id)
        if (
            path.with_suffix(".setup-lock").exists()
            or state.get("python_setup", {}).get("status") != "ready"
            or state["merged"]
        ):
            raise wt.Blocked(
                "final integration requires ready unmerged lifecycle state"
            )
        target = wt.task_worktree(root, state)
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        changed = partial(wt.integration_changed_paths, target, state["task_file"])
        framework = tasks.final_framework_task(text, changed)
        declared = tasks.paths_in(text, "## Modified files")
        if (
            not framework
            and tasks.model_operation(text) is None
            and tasks.model_refactor(text) is None
            and tasks.final_model_task(text, changed() & declared)
            and changed() - declared
        ):
            raise wt.Blocked(
                "integration changes are outside the exact task contract: "
                + ", ".join(sorted(changed() - declared))
            )
        if not (framework or tasks.final_model_task(text, changed)) or tasks.status(
            text
        ) not in {
            "running",
            "completed",
        }:
            raise wt.Blocked(
                "final integration requires a running/completed Model-only or Framework task"
            )
        if tasks.section(text, "## Suspension reason"):
            raise wt.Blocked(
                "running/completed task has an unexpected suspension reason"
            )
        operation = tasks.model_operation(text)
        if operation is not None and operation.action == "model-delete":
            Scope = _imports_model_sources.Scope
            load_model = _imports_model_sources.load_model
            for scope in sorted(operation.source_scopes):
                remaining = set(
                    dict(
                        _model_api.ModelView(
                            load_model(Scope(target, *scope)).authoritative
                        ).resources()
                    )
                )
                requested = {
                    source.rsplit("/", 1)[1]
                    for source in operation.delete_sources
                    if tuple(source.split("/")[:3]) == scope
                }
                if remaining & requested:
                    raise wt.Blocked(
                        "deletion leaves incomplete: "
                        + "/".join(scope)
                        + ": "
                        + ", ".join(sorted(remaining & requested))
                    )
        latest = wt._prepare_commit(root, path, state, target)
        active_scope = _imports_validation_scope.active_scope
        scope = (
            set() if framework else active_scope(target, task_file=state["task_file"])
        )
        if not framework and not scope:
            raise wt.Blocked("Model final candidate requires explicit service scope")
        head = wt.output(target, "rev-parse", "HEAD")
        return wt.FinalCandidate(
            target,
            target,
            state["task_file"],
            text,
            latest,
            head,
            frozenset(
                wt.paths(
                    target, "diff", "--no-renames", "--name-only", "-z", latest, head
                )
            ),
            frozenset(scope),
        )


def validate_final_candidate(candidate: wt.FinalCandidate) -> wt._ValidatedCandidate:
    """Run the existing read-only final loop once, without holding the lifecycle lock."""
    run_loop = _imports_validation_loop.run_loop

    options = SimpleNamespace(
        mode="task",
        all=False,
        task_file=candidate.task_file,
        log_dir=None,
        profile=False,
        jobs=2,
        validation_jobs=4,
        fresh=True,
        write=False,
        staged=False,
        base=None,
        affected=False,
    )
    if (
        wt.changed_paths(candidate.root)
        or wt.output(candidate.root, "rev-parse", "HEAD") != candidate.candidate_head
        or tasks.read_task_snapshot(candidate.root, candidate.task_file, live=True).text
        != candidate.task_text
    ):
        raise wt.Blocked("final candidate changed before validation")
    code = run_loop(candidate.root, options, final_candidate=candidate)
    return wt._ValidatedCandidate(candidate, code)
