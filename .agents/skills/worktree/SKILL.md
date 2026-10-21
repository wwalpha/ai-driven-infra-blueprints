---
name: worktree
description: Run a repository change task in an isolated linked Git worktree, then integrate only its completed result into the latest local base with rebase and fast-forward merge. Read-only investigation, analysis and review usually need no worktree.
---

# Isolated task execution

Use `/worktree <task-id> <child skill/task and its inputs>` for a task that changes repository files. This skill wraps the selected task; it does not replace its logic, authorize another phase, or authorize AWS operations. Existing task types do not encode read-only intent: decide from the requested outputs. Investigation/review without saved changes runs in the current checkout; `/issues` with saved reports is a change task.

For `/import`, use the worktree selected by the Human; follow [08_import](../../../framework/prompts/codex/08_import.md) for its contract, evidence and validation requirements. Other change tasks retain this workflow.

## Read before execution

Read [Task transition](../../../framework/rules/task-contract.md#task-transition), [Task boundary](../../../framework/rules/task-contract.md#task-boundary), [Acceptance contract](../../../framework/rules/task-contract.md#acceptance-contract), and [Retry and stop](../../../framework/rules/task-contract.md#retry-and-stop). For validation/integration, read [Local loop](../../../framework/rules/loop-engineering.md#local-loop), [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope), [Framework regression](../../../framework/rules/loop-engineering.md#framework-regression), [Conflict resolution and reproducible validation](../../../framework/rules/loop-engineering.md#conflict-resolution-and-reproducible-validation), and [Retry and stop](../../../framework/rules/loop-engineering.md#retry-and-stop).

Read only the selected child skill and its mandatory/conditional references, including its task-type completion section; these remain authoritative for child permissions and finish conditions. Read [Validation cache](../../../framework/rules/loop-engineering.md#validation-cache) when reusing results and [Timing and long-running execution](../../../framework/rules/loop-engineering.md#timing-and-long-running-execution) for long runs/recovery. Use the Python 3 launcher required by that workflow (`python3` below).

## Sandbox permission approval and continuation

Apply this procedure to **create, finalize and cleanup**, regardless of the Codex model. The agent requests permissions through its execution tool; the Python helper cannot open the platform's approval UI. Do not end the task merely because a sandboxed helper invocation returns `status: blocked` with a write denial.

1. **Identify the failure.** Read the execution tool's denial and the helper's JSON `error`. Sandbox write denials include `Operation not permitted` / `Permission denied` (`EPERM` / `EACCES`) for `<primary>/.worktrees/.blueprint/` lifecycle/setup lock creation/removal or state metadata, and Git's own worktree administration, refs/branches or index updates in the common Git directory. Confirm the denied operation/path against the execution environment's sandbox restrictions; a permission message alone does not prove a sandbox denial. `worktree lifecycle busy`, an existing Git lock (`File exists`), branch/path collisions, dirty worktrees, unresolved Git operations, rebase conflicts, task/ownership failures and validation failures are safety blocks, not permission requests. Never use escalation to bypass them.
2. **Inspect retained state before retrying.** From a surviving repository root, use read-only `git rev-parse --path-format=absolute --git-common-dir`, `git worktree list --porcelain`, `git status --porcelain --untracked-files=all` in each relevant surviving checkout, and branch/HEAD reads. Resolve `<primary>` from the first `git worktree list --porcelain` entry. Inspect `<primary>/.worktrees/.blueprint/tasks/<task-id>.json` and whether `<primary>/.worktrees/.blueprint/lifecycle.lock` or `tasks/<task-id>.setup-lock` exists; compare saved start/tip/commit/verified/merged state with the actual branches and worktree. Do not write recovery metadata or reconstruct the lifecycle with ad hoc Git commands. If inspection itself is denied, request only the permissions needed to inspect it first.
3. **Choose a safe continuation.** The approval call may execute the command immediately, so finish the state inspection before submitting a mutating retry. Retry `create` only if this task's branch, target path, registered worktree and lifecycle state are all absent. If creation already succeeded and valid lifecycle metadata matches the actual worktree/base/start, use that existing result instead of creating it again. For partial `finalize` / `cleanup`, use only the helper's existing retry path after verifying the retained state; a verified merge proceeds through `cleanup` from a surviving root. A commit/rebase/merge without matching saved state, an unverified commit, an unfinished Git operation, or a remaining lifecycle lock requires safe retention and review, not an automatic mutating retry. Never delete a lock, even when its removal was denied; approval does not establish lock ownership. These safety stops still apply after permission is granted.
4. **Request real execution permission.** For a confirmed sandbox denial, use the execution environment's native escalation/approval facility. With Codex `exec_command`, submit the helper invocation with `sandbox_permissions: "require_escalated"` and a `justification` naming the command (`create` / `finalize` / `cleanup`), repository/task, denied path and required temporary write access. Use the equivalent native facility in another environment; do not invent unsupported tool arguments. A chat question or a suggestion that the human rerun the command is not an approval request. Do not repeat the failed command with the same sandbox permissions. Keep the request limited to the necessary operation; do not request a blanket approval for unrelated commands.
5. **Continue automatically after success.** Keep the same task ID, contract selector, helper arguments and task scope (use a surviving root for cleanup). Allow at most **one escalated reexecution per denied invocation**; another denial or inconsistent state stops with the concrete error and retained state. On exit 0 with JSON `status: ok`, continue the original workflow immediately without asking for another instruction: creation returns to child execution, finalize returns to verified integration/cleanup, cleanup returns to completion reporting. If the native approval is denied/canceled, stop safely and preserve existing work. If the approval facility is unavailable, explicitly report that limitation and the blocked operation/path; do not pretend a chat confirmation grants permissions.

Permission approval changes execution access only. It never approves validation failures, expands Allowed paths, resumes a suspended task or authorizes AWS operations. Do not add `--human-approved-validation-failure` for sandbox approval. Never use `sudo`, `chmod 777`, permanent sandbox disabling, force Git operations, stash/reset to discard changes, or lock deletion as a workaround. Report which permission/retry steps were exercised and distinguish mocked retention checks from actual approval UI/model verification.

## Create and execute

Standard lifecycle: Create → Python Setup → Develop → Test → Local Merge → Cleanup.

From the current repository root:

```console
python3 -B framework/scripts/worktree_task.py create --task-id <task-id>
```

Task IDs follow existing lower-kebab-case contract names. The helper resolves the base from repository-local `blueprint.baseBranch`, otherwise the existing `origin/HEAD` symbolic default, then local `main`, then `master`. A configured but absent local branch stops creation. It neither fetches/pulls nor creates a missing base or uses the current feature branch as a fallback.

Create finishes Python Setup before returning success. Every managed worktree shares the fixed `<primary>/.worktrees/.blueprint/python-env/` environment, resolved through the existing primary repository lookup. Only the initial setup creates the venv at that final path, installs `framework/scripts/requirements.txt`, probes isolation and verifies core imports, pinned packages and `pip check`. Global Python is only the venv creation launcher; no global dependency fallback or global package installation occurs. No worktree-local venv is created.

Later Create/setup and runtime perform only lightweight ownership, completion, executable and registration-path checks: no pip, full imports, requirements hash/version or Python-version comparisons. JSON uses existing `python_setup` with `status: ready`, `kind: shared`, `interpreter`, `bin`, and `installed` (true only for the call that installs). The `.blueprint-owner` record identifies a directory created by this helper; `.blueprint-ready` is written last after successful initial verification. A completion marker alone cannot claim an unknown directory. Shared paths/markers/config/bin must not be symlinks; the normal venv Python executable symlink is allowed.

The existing per-task setup lock remains. A separate `<primary>/.worktrees/.blueprint/python-env.setup-lock/` serializes first installation across Tasks, without holding the Git lifecycle lock during venv/pip/verification. Contenders wait up to 300 seconds, then report a busy lock for review; retained or unknown locks are never deleted. Owned incomplete setups resume in place through setup; unknown directories, redirected paths and completed environments with missing Python stop for explicit maintenance. Task/worktree/branch remain available after failure.

### Explicit shared Python maintenance

Requirements and Python changes never trigger automatic reinstall/rebuild. Stop all running Tasks and Python children before maintenance: changing the shared environment affects every Task. After reviewing ownership and symlinks, an operator may explicitly install the desired requirements with the shared interpreter, run `pip check` and the required import/version checks. To rebuild a broken/completed environment, the operator must first review and preserve the old fixed directory outside the worktree/metadata tree, then run ordinary `worktree_task.py setup --task-id <existing-unmerged-task>` to build at the original fixed path. Do not run a relocated old venv. No lifecycle/cleanup command updates or deletes the shared environment. Setup failure before completion retains the owned partial directory for a setup retry; unknown directories/locks require operator review, never automatic deletion.

The selected environment's WeasyPrint package is version-checked, but its import/native library check is deferred to PDF export. PDF-free Model/Markdown/issue tasks require no GTK/Pango/GObject setup. Core imports and pip check block initial completion; reuse does not rescan dependencies. See [PDF dependencies](../../../README.md#pdf-dependencies) for PDF checks and Windows DLL lookup. No optional requirements file or setup skip flag is needed.

The helper returns JSON containing `worktree`, `branch`, `base`, and `task_file`. It creates `codex/worktree/<task-id>` and `<primary>/.worktrees/<task-id>` from the base; collisions/stale entries stop without overwrite/pruning. Keep `/.worktrees/` ignored. Only `/.worktrees/<task-id>` is accepted for creation, setup, validation, integration and cleanup. Git creates its own administrative entries under the common Git directory's `worktrees/`; these are separate from the working files. All custom lifecycle metadata and locks live in `<primary>/.worktrees/.blueprint/`: `tasks/<task-id>.json` stores recovery/Python setup state, `tasks/<task-id>.tmp` is its atomic-save temporary file, `tasks/<task-id>.setup-lock/` serializes setup, and `lifecycle.lock/` serializes Git integration. Every linked worktree resolves this same primary location; none uses a nested local metadata directory. Metadata directories must not be symlinks. The ignored `/.worktrees/` covers these files, separate from repository task contracts in `tasks/`. Git's own administration still requires writes in `.git`.

Setup failure returns exit 1 / `status: blocked`, with `python_setup.status: failed` and an error, preserving Git worktree, branch and task state. Do not repeat create with the same task ID. From a surviving repository root use the ordinary Python 3 launcher:

```console
python3 -B framework/scripts/worktree_task.py setup --task-id <task-id>
```

Setup is idempotent and serializes the same task's setup. It reuses the completed shared environment or finishes initial setup after releasing the Git lifecycle lock. Permission denials follow the same inspection/native approval policy as create. Retained setup locks require review; never delete them automatically. A failed or interrupted setup cannot enter normal task execution or integration.

On Windows, use `py -3 -B framework/scripts/worktree_task.py setup --task-id <task-id>` from the surviving checkout containing the updated helper. This recovers native-library-only setup failures without installing PDF DLLs. Setup uses that caller's helper and the retained worktree's requirements; it does not update code in existing linked worktrees. Update their code through the normal Git workflow before using their older helper again.

**Set the working directory of every subsequent change/child command to the returned `worktree` root.** Execute the original child skill/task there, including its preflight, issue gate, contract registration, exact Modified files, authorization, validation and completion. Register `tasks/<task-id>.md` there as its first repository change; pass that selector to child commands or set `BLUEPRINT_TASK_FILE` per process. Do not copy running contracts from other checkouts.

For every Python task/check/loop command in the returned worktree, use the common wrapper, even in a fresh shell. It selects the worktree's registered ready shared Interpreter and prepends its bin directory to PATH; subprocesses using `sys.executable` and Python CLIs inherit the same environment. Missing/failed/stale setup stops with the recovery command. The JSON `python_setup.interpreter` path can also be used directly, but the wrapper additionally sets PATH for CLI resolution; new worktrees reuse the same completed environment without package verification.

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-id>.md --source <external-contract>
python3 -B framework/scripts/run-python.py -B framework/scripts/blueprint-loop.py --mode full --task-file tasks/<task-id>.md
python3 -B framework/scripts/run-python.py --command cfn-lint --template <template>
```

Select validation mode under Validation policy; this example does not require Full for text-only work. Run lifecycle create/setup/finalize/cleanup with the ordinary launcher from a surviving checkout, so cleanup does not depend on the worktree-local Interpreter it removes. Pandoc and WeasyPrint native libraries remain OS prerequisites for PDF export; AWS CLI and Terraform remain external tools.

The worktree contains committed base inputs only. Do not silently copy/stash the source checkout's dirty files. In particular, infrastructure `/update` needs the human's intended uncommitted model diff **in the new worktree** before child execution. Explicit Model-only IMPORT merge/delete instead uses the Human-specified operation and IDs without pre-edits. If that input is only in the original checkout, retain both checkouts and request explicit input placement; do not run update with missing input or infer/copy unrelated changes.

## Complete and integrate

For a normal Model-only /update task (including standalone `import-retarget`), finalize is the final validation composition:
keep the parent running after leaf/view saves and invoke finalize directly. It prepares
the private commit/rebase, validates the actual latest-base candidate once in registered
Python, completes from that result and merges that exact HEAD. Completed Model-only tasks
also undergo that post-rebase check. The ordinary launcher cleans up after the child exits.
No separate pre-finalize complete or duplicate final loop is required in this branch.
Failure retains the candidate; never amend or discard it. For import-delete, explicit
same-parent repair/resume may create a corrected candidate and rerun final validation;
other Model-only operations retain their no-auto-regeneration/retry rule. Deletion leaves
never finalize separately: one parent Worktree contains all resource saves, followed by
one generation phase and one final-candidate validation/merge/cleanup on success. The commands
below describe other workflows and independent completion, not Model-only sequencing.

Finish all requested work and all required inputs/approvals under the child's existing workflow. Proceed only after successful final validation selected by [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy) and all other mandatory completion conditions:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-id>.md --complete
python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id>
```

If validation/local loop fails, report the concrete failures and stop by default. If the human explicitly approves commit and merge despite those failures, keep the contract `suspend` with its Suspension reason; do not run `--complete` or report validation PASS. With all requested work and inputs otherwise finished, use:

```console
python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id> --human-approved-validation-failure "<human approval identifying the accepted failures>"
```

Use this option only after actual human approval of this task's failures; a general request to run the task or this skill is not approval. The helper records the approval in lifecycle metadata and the commit message; Git integration success remains separate from validation FAIL. The approval permits only commit/rebase/merge/cleanup, without resuming the task or authorizing AWS operations. Missing inputs, unfinished work, and Git safety blocks still stop integration. A retained committed task may retry with its recorded approval; changed work needs renewed review and approval.

`finalize` reads the existing completed status (or the explicitly approved suspended status), rejects unresolved Git operations and unexpected branch commits, and stages only exact non-ignored task paths (including newly added files). It never force-adds `tasks/**`. Normal commit messages use `task(<task-id>): completed task`; approved failures use `task(<task-id>): human-approved validation failure`; zero changes create no empty commit.

Ordinary integration runs the shared candidate Model guard before commit and after rebase
in the target worktree’s registered Python,
with its Task explicitly selected. The launcher retains Git, lifecycle lock and cleanup ownership.
Framework-only changes do not load Models. Ordinary changes never expand or load old Git
Models; dedicated operations retain raw-field comparisons only. Cheap contract, HEAD, commit
and base checks precede analysis and required checks remain after
the guard; changed Task, files or index stop before staging. No runtime fallback or automatic
setup/retry occurs. Successful guard diagnostics use stderr so stdout remains CLI JSON; failures
retain the child return code, stdout and stderr separately in `diagnostics`.

It then checks a clean worktree holding the local base, rebases the task onto its latest local commit, rechecks the base, merges with `--ff-only`, verifies the expected task tip is included, and removes the worktree/branch without force. Have the local base checked out in an available worktree before finalize; the helper does not switch anyone's branch. Helpers serialize Git integration through the shared `<primary>/.worktrees/.blueprint/lifecycle.lock/` mutex; AWS locks remain separate. No remote push or PR is created.

## Failures and cleanup

Exit 0 and JSON `status: ok` indicate success; exit 1 and `status: blocked` give the reason and retained branch/worktree/commit/merge state when available (invalid CLI arguments exit 2). Apply [Sandbox permission approval and continuation](#sandbox-permission-approval-and-continuation) before stopping for a sandbox write denial. Do not parse long Git stdout or construct ad hoc recovery shells.

For failed validation/loop, stop before finalize/commit unless the human explicitly approves the exception above. Other suspended tasks, missing input, approval waits or conflicts still stop before finalize/commit. Keep worktree and branch; use the child's existing suspension/resume rules. Finalize itself never completes or resumes a task. A dirty base is never stashed/reset/overwritten. Rebase failure runs `rebase --abort`, preserves the task commit and worktree, and requires human review; do not guess conflict resolutions. A base change during integration stops safely; rerun finalize only after reviewing the reported state.

Cleanup runs only after verified merge. It removes only this task's state JSON after its worktree/branch are removed; the shared `.worktrees/.blueprint/` directory and other tasks' state remain. Dirty worktrees, unmerged/changed branches, locked/stale entries and ignored user artifacts are retained. The shared Python environment is never removed. Unknown ignored files and directories require preservation before cleanup. Import completion evidence lives in `evidence_store(worktree)` outside the repository. Finalize verifies it before integration; successful cleanup removes only this task's sealed receipt after checkout/branch removal. Failed or interrupted integration retains retry evidence. Unknown ignored artifacts remain blockers; `.worktrees/.blueprint` lifecycle state is unchanged. A merge followed by cleanup failure remains merged and can use the existing cleanup retry. If cleanup fails, report the merged commit and remaining worktree/branch; do not roll back the merge. From a surviving repository root, retry only the helper:

```console
python3 -B framework/scripts/worktree_task.py cleanup --task-id <task-id>
```

Different worktrees still share AWS resources. Cross-worktree AWS mutation locking is a separate responsibility; this skill adds none and does not relax existing deployment controls.

## Human-reviewed governance conflict recovery

For an explicitly authorized retained governance repair, use
[Reviewed governance recovery](../../../framework/rules/task-contract.md#reviewed-governance-recovery).
Run `recover` from the checkout containing the reviewed helper with full expected
commit/base hashes. It reopens only that contract, pins the recovery, and retains the
normal finalize guards. After its aborted rebase, the authorized manual rebase may
resolve the reviewed conflicts; `--finish-recovery` registers the clean exact-base
candidate through the helper. Do not hand-edit metadata. Then execute the required
IT/Full validation before completing and finalizing. This is not a failed-validation
integration exception and does not apply to Model tasks.

Standalone `import-retarget` uses the existing running-parent final-candidate path.
Require successful latest-base reference/preservation validation; failed-validation
approval cannot bypass it. Never demand transfer/deletion for this operation or add
automatic regeneration, validation retry or an IT requirement.
