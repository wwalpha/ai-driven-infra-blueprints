---
name: worktree
description: Run a repository change task in an isolated linked Git worktree, then integrate only its completed result into the latest local base with rebase and fast-forward merge. Read-only investigation, analysis and review usually need no worktree.
---

# Isolated task execution

Use `/worktree <task-id> <child skill/task and its inputs>` for a task that changes repository files. This skill wraps the selected task; it does not replace its logic, authorize another phase, or authorize AWS operations. Existing task types do not encode read-only intent: decide from the requested outputs. Investigation/review without saved changes runs in the current checkout; `/issues` with saved reports is a change task.

Read [Task Contract](../../../framework/rules/task-contract.md) and applicable [local loop/completion rules](../../../framework/rules/loop-engineering.md). Read only the selected child skill and its required references; do not reread every skill. Use the Python 3 launcher required by that workflow (`python3` below).

## Create and execute

From the current repository root:

```console
python3 -B framework/scripts/worktree_task.py create --task-id <task-id>
```

Task IDs follow existing lower-kebab-case contract names. The helper resolves the base from repository-local `blueprint.baseBranch`, otherwise the existing `origin/HEAD` symbolic default, then local `main`, then `master`. A configured but absent local branch stops creation. It neither fetches/pulls nor creates a missing base or uses the current feature branch as a fallback.

The helper returns JSON containing `worktree`, `branch`, `base`, and `task_file`. It creates `codex/worktree/<task-id>` and `<primary>/.worktrees/<task-id>` from the base; collisions/stale entries stop without overwrite/pruning. Keep `/.worktrees/` ignored. Lifecycle recovery metadata lives in the common Git directory, outside tracked files and `tasks/`.

**Set the working directory of every subsequent change/child command to the returned `worktree` root.** Execute the original child skill/task there, including its preflight, issue gate, contract registration, exact Modified files, reservations, validation and completion. Register `tasks/<task-id>.md` there as its first repository change; pass that selector to child commands or set `BLUEPRINT_TASK_FILE` per process. Do not copy running contracts from other checkouts. Worktree identity and Deferred behavior remain owned by existing Task Contract code; identical relative paths in different worktrees are independent.

The worktree contains committed base inputs only. Do not silently copy/stash the source checkout's dirty files. In particular, `/update` needs the human's intended uncommitted model diff **in the new worktree** before child execution. If that input is only in the original checkout, retain both checkouts and request explicit input placement; do not run update with missing input or infer/copy unrelated changes.

## Complete and integrate

Finish all requested Active/Deferred work and all required inputs/approvals under the child's existing workflow. Only after its successful local loop and all other mandatory completion conditions:

```console
python3 -B framework/scripts/task_contract.py --task-file tasks/<task-id>.md --complete
python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id>
```

`finalize` reads the existing completed status/reservations, rejects outside-task changes, unresolved Git operations and unexpected branch commits, and stages only exact non-ignored task paths (including newly added files). It never force-adds `tasks/**`. Commit messages use `task(<task-id>): completed task`; zero changes create no empty commit.

It then checks a clean worktree holding the local base, rebases the task onto its latest local commit, rechecks the base, merges with `--ff-only`, verifies the expected task tip is included, and removes the worktree/branch without force. Have the local base checked out in an available worktree before finalize; the helper does not switch anyone's branch. Helpers serialize Git integration through one common-directory lifecycle mutex; file reservations and AWS locks remain separate. No remote push or PR is created.

## Failures and cleanup

Exit 0 and JSON `status: ok` indicate success; exit 1 and `status: blocked` give the reason and retained branch/worktree/commit/merge state when available (invalid CLI arguments exit 2). Do not parse long Git stdout or construct ad hoc recovery shells.

For failed validation/loop, suspended, unfinished Deferred, missing input, approval waits or conflicts, stop before finalize/commit. Keep worktree and branch; use the child's existing suspension/resume rules. Finalize itself never completes or resumes a task. A dirty base is never stashed/reset/overwritten. Rebase failure runs `rebase --abort`, preserves the task commit and worktree, and requires human review; do not guess conflict resolutions. A base change during integration stops safely; rerun finalize only after reviewing the reported state.

Cleanup runs only after verified merge. Dirty worktrees, unmerged/changed branches, locked/stale entries and ignored user artifacts are retained. If cleanup fails, report the merged commit and remaining worktree/branch; do not roll back the merge. From a surviving repository root, retry only the helper:

```console
python3 -B framework/scripts/worktree_task.py cleanup --task-id <task-id>
```

Different worktrees still share AWS resources. Cross-worktree AWS mutation locking is a separate responsibility; this skill adds none and does not relax existing deployment controls.
