---
name: worktree
description: Run a repository change task in an isolated linked Git worktree, then fast-forward merge its validated result into the latest local base by default. Publish a PR only when the Human explicitly requests one for that Task. Read-only investigation, analysis and review usually need no worktree.
---

# Isolated task execution

Use `/worktree <task-id> <child skill/task and its inputs>` for a task that changes repository files. This skill wraps the selected task; it does not replace its logic, authorize another phase, or authorize AWS operations. Existing task types do not encode read-only intent: decide from the requested outputs. Investigation/review without saved changes runs in the current checkout; `/issues` with saved reports is a change task.

**Default integration is local fast-forward merge followed by cleanup.** After the child workflow's required checks and completion conditions pass, continue through ordinary `finalize` without asking the Human to choose between merge and PR. Select `--create-pr` only when the Human explicitly requests PR publication for this Task; mentioning PRs, reviewing PR behavior or changing PR support does not select it. Retain the existing safety stops and recovery rules, including no automatic mode conversion for a Task already in PR mode.

For `/import`, use the worktree selected by the Human; follow [08_import](../../../framework/prompts/codex/08_import.md) for its contract, evidence and validation requirements. Other change tasks retain this workflow.

## Read before execution

At start read [Task transition](../../../framework/rules/task-contract.md#task-transition) (including its required common and conditional reads), [Task boundary](../../../framework/rules/task-contract.md#task-boundary), [Acceptance contract](../../../framework/rules/task-contract.md#acceptance-contract), [Self recovery](../../../framework/rules/task-contract.md#self-recovery), [Retry and stop](../../../framework/rules/task-contract.md#retry-and-stop), and [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy). Read only the selected child skill and its mandatory/conditional references, including its task-type completion section; these remain authoritative for child permissions and finish conditions.

When performing validation/integration, read [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope), [Conflict resolution and reproducible validation](../../../framework/rules/loop-engineering.md#conflict-resolution-and-reproducible-validation), and [Retry and stop](../../../framework/rules/loop-engineering.md#retry-and-stop). Read [Local loop](../../../framework/rules/loop-engineering.md#local-loop) when a loop is required, [Framework regression](../../../framework/rules/loop-engineering.md#framework-regression) only when the validation classification requires it, [Validation cache](../../../framework/rules/loop-engineering.md#validation-cache) when reusing results, and [Timing and long-running execution](../../../framework/rules/loop-engineering.md#timing-and-long-running-execution) for long runs/recovery. Read the applicable recovery sections when entering those procedures. Use the Python 3 launcher required by that workflow (`python3` below). Do not unconditionally reread unchanged material already confirmed in the same Task; revisit necessary sections when inputs, classification or dependencies change or evidence is insufficient.

## Sandbox permission approval and continuation

Apply this procedure to **create, deploy-start, setup (when needed), normal Deploy checkpoint, base synchronization, finalize, PR operations, orphan branch deletion and cleanup**, regardless of the Codex model. The agent requests permissions through its execution tool; the Python helper cannot open the platform's approval UI. Do not end the task merely because a sandboxed helper invocation returns `status: blocked` with a write denial.

Before **each operation**, inspect the relevant Git/Task/lock state and the execution environment's effective Sandbox restrictions using read-only information. Determine the actual write destinations for that operation, including the Git common directory, linked worktree administration/index, lifecycle metadata and, for create/setup when needed, the shared Python environment. Compare resolved paths with the effective policy, including protected exceptions and symlinks. Do not probe by writing or infer a denial from ordinary filesystem permissions alone. If the policy confirms a required destination is protected, request native permission on the **first invocation**, including for a new Task; a prior denial is not required. If normal access is allowed, run normally without an unnecessary approval. If restrictions or destinations are unknown, do not assume either access or denial: use the ordinary invocation and identify any failure below. Keep knowledge only in the current execution context; add no persistent permission-state file. Permission approval does not relax the Python helper's guards.

**Deploy entry only (`deploy-start`):** in the inspection below, relevant checkouts are the current checkout and the exact selected Task Worktree if it already exists. Read the worktree registration list only as ownership/collision metadata and to identify the primary root; do not enter unrelated checkouts, run their `git status`, search their files or inspect their Task/branch history. Inspect only this Task's lifecycle record/locks and the required common Git/shared Python destinations. Existing helper guards perform the actual ownership, lock and fixed-Task checks; an ambiguous identity stops for Human review. Adopt the returned `worktree` and `task_file`, without a second manual Task/Git inventory. This entry-specific limit does not change checkpoint, publication, finalize or cleanup inspection and recovery.

1. **Inspect state and restrictions.** From a surviving repository root, use read-only `git rev-parse --path-format=absolute --git-common-dir`, `git worktree list --porcelain`, `git --no-optional-locks status --porcelain --untracked-files=all` in each relevant surviving checkout, and branch/HEAD reads. Resolve `<primary>` from the first worktree entry. Inspect `<primary>/.worktrees/.blueprint/tasks/<task-id>.json` and whether `<primary>/.worktrees/.blueprint/lifecycle.lock` or `tasks/<task-id>.setup-lock` exists; for setup also inspect the shared Python setup lock and environment state as applicable. Compare saved start/tip/commit/verified/merged state with actual branches and worktree. Consult the execution tool's actual permission schema and effective Sandbox policy; do not invent unsupported capabilities. If inspection itself is denied, request only the permissions needed to inspect it first.
2. **Choose a safe continuation.** The approval call may execute immediately, so finish inspection first. For create, verify this task's branch, target path, registered worktree and lifecycle state are absent. If creation already succeeded and valid lifecycle metadata matches the actual worktree/base/start, use that existing result instead of creating again. For partial finalize/cleanup, use only the helper's existing retry path after verifying retained state; a verified merge proceeds through automatic cleanup from a surviving root; explicit disposal does not require a merge. A commit/rebase/merge without matching saved state, an unverified commit, an unfinished Git operation, or a remaining lifecycle lock requires safe retention and review, not an automatic mutating retry. Never delete a lock, even when its removal was denied. Git lock contention, lifecycle busy, branch/worktree collisions, unexpected dirty worktrees during integration/automatic cleanup, rebase conflicts, Task violations, Validation FAIL and inconsistent Git/Task state are safety blocks; never use escalation to bypass them. Do not write recovery metadata or reconstruct lifecycle with ad hoc Git commands.
3. **Request real execution permission when needed.** If supported by the execution tool, prefer `sandbox_permissions: "with_additional_permissions"` with `additional_permissions.file_system.write` restricted to the actual required paths. Avoid granting the entire repository. If that facility is unavailable, use the supported native escalation, such as Codex `exec_command` with `sandbox_permissions: "require_escalated"` and a `justification` naming the operation, repository/task, protected paths and required temporary write access. Do not invent tool arguments or assume approval. Keep permission limited to the operation; a chat confirmation does not grant execution permission. If the native facility is unavailable or approval is denied/canceled, stop safely and preserve state.
4. **Identify unexpected failure.** If an ordinary invocation fails, read the execution tool's denial and helper JSON `error`; confirm the operation and path against the effective Sandbox restrictions. `Operation not permitted` / `Permission denied` (`EPERM` / `EACCES`) alone do not prove a Sandbox denial. `File exists`, lifecycle busy, collisions and the other safety blocks above do not justify escalation. For a confirmed Sandbox denial, repeat the read-only inspection and safe continuation above before requesting permission; do not repeat the denied command under the same permissions. Partial success uses only the existing recovery path.
5. **Continue automatically after success.** Keep the same task ID, contract selector, helper arguments and task scope (use a surviving root for cleanup). Allow at most **one escalated reexecution per denied invocation**; if a permission-granted invocation is denied again or state is inconsistent, stop with the concrete error and retained state. On exit 0 with JSON `status: ok`, continue the original workflow immediately without another instruction: creation returns to child execution, finalize returns to verified integration/cleanup, cleanup returns to completion reporting. If approval is unavailable, report the blocked operation and path; do not pretend chat confirmation grants permissions.

Permission approval changes execution access only. It never approves validation failures, expands Allowed paths, resumes a suspended task or authorizes AWS operations. Do not add `--human-approved-validation-failure` for sandbox approval. Never use `sudo`, `chmod 777`, permanent sandbox disabling, force Git operations outside the explicit local disposal described below, stash/reset to discard changes, or lock deletion as a workaround. Report which permission/retry steps were exercised and distinguish mocked retention checks from actual approval UI/model verification.

## Create and execute

Standard lifecycle: Create → Python Setup → Develop → Test → Local Merge → Cleanup.

From the current repository root:

```console
python3 -B framework/scripts/worktree_task.py create --task-id <task-id>
```

Task IDs follow existing lower-kebab-case contract names. The helper resolves the base from repository-local `blueprint.baseBranch`, otherwise the existing `origin/HEAD` symbolic default, then local `main`, then `master`. A configured but absent local branch stops creation. It neither fetches/pulls nor creates a missing base or uses the current feature branch as a fallback.

Create finishes Python Setup before returning success. Every managed worktree shares the fixed `<primary>/.worktrees/.blueprint/python-env/` environment, resolved through the existing primary repository lookup. Initial setup creates the venv at that final path, installs the primary checkout’s `framework/scripts/requirements.txt`, probes isolation and verifies core imports, pinned packages and `pip check`. Global Python is only the venv creation launcher; no global dependency fallback or global package installation occurs. No worktree-local venv is created.

Later Create/setup and runtime retain ownership, completion, executable and registration-path checks, and compare the primary requirements SHA-256 with `.blueprint-requirements-sha256`. A match starts no dependency-check Python child, pip or imports. A changed/missing hash queries installed versions once; if all match, only the hash is recorded. Otherwise the existing pip installation and `verify()` run before recording success. Installation/verification failure retains the environment and leaves the hash invalid for retry; pending verification must succeed even when partial installation already supplied all requested versions. Python changes do not trigger rebuilds. JSON uses existing `python_setup` with `status: ready`, `kind: shared`, `interpreter`, `bin`, and `installed` (true only for the call that installs). The `.blueprint-owner` record identifies a directory created by this helper; `.blueprint-ready` is written last after successful initial verification. A completion marker alone cannot claim an unknown directory. Shared paths/markers/config/bin must not be symlinks; the normal venv Python executable symlink is allowed.

The existing per-task setup lock remains. A separate `<primary>/.worktrees/.blueprint/python-env.setup-lock/` serializes first installation and dependency synchronization across Tasks, rechecking requirements/hash after lock acquisition, without holding the Git lifecycle lock during venv/pip/verification. Contenders wait up to 300 seconds, then report a busy lock for review; retained or unknown locks are never deleted. Owned incomplete setups resume in place through setup; unknown directories, redirected paths and completed environments with missing Python stop for explicit maintenance. Task/worktree/branch remain available after failure.

### Explicit shared Python maintenance

The primary checkout’s requirements are the unique canonical source for all shared installs and verification. An older worktree may omit new primary packages; different requested versions or worktree-only packages raise a conflict before installation. Reconcile and merge requirements into primary before use; never install a task worktree’s requirements into the shared environment. Helpers predating this policy must be updated through the normal Git workflow before use; older setup code cannot enforce this guard. Stop all running Tasks and Python children before changing canonical requirements or explicit maintenance: changing the shared environment affects every Task. The setup lock serializes installers and waiting launchers, but cannot protect Python processes already running when an update begins. Requirements changes synchronize automatically; Python interpreter changes and rebuilds require explicit maintenance. To rebuild a broken/completed environment, the operator must first review and preserve the old fixed directory outside the worktree/metadata tree, then run ordinary `worktree_task.py setup --task-id <existing-unmerged-task>` to build at the original fixed path. Do not run a relocated old venv. No lifecycle/cleanup command updates or deletes the shared environment. Setup failure before completion retains the owned partial directory for a setup retry; unknown directories/locks require operator review, never automatic deletion.

The selected environment's WeasyPrint package is version-checked, but its import/native library check is deferred to PDF export. PDF-free Model/Markdown/issue tasks require no GTK/Pango/GObject setup. Core imports and pip check block initial completion and post-install verification; unchanged-hash reuse does not rescan dependencies. See [PDF dependencies](../../../README.md#pdf-dependencies) for PDF checks and Windows DLL lookup. No optional requirements file or setup skip flag is needed.

The helper returns JSON containing `worktree`, `branch`, `base`, and `task_file`. It creates `codex/worktree/<task-id>` and `<primary>/.worktrees/<task-id>` from the base; collisions/stale entries stop without overwrite/pruning. Keep `/.worktrees/` ignored. Only `/.worktrees/<task-id>` is accepted for creation, setup, validation, integration and cleanup. Git creates its own administrative entries under the common Git directory's `worktrees/`; these are separate from the working files. All custom lifecycle metadata and locks live in `<primary>/.worktrees/.blueprint/`: `tasks/<task-id>.json` stores recovery/Python setup state, `tasks/<task-id>.tmp` is its atomic-save temporary file, `tasks/<task-id>.setup-lock/` serializes setup, and `lifecycle.lock/` serializes Git integration. Every linked worktree resolves this same primary location; none uses a nested local metadata directory. Metadata directories must not be symlinks. The ignored `/.worktrees/` covers these files, separate from repository task contracts in `tasks/`. Git's own administration still requires writes in `.git`.

Setup failure returns exit 1 / `status: blocked`, with `python_setup.status: failed` and an error, preserving Git worktree, branch and task state. Do not repeat create with the same task ID. From a surviving repository root use the ordinary Python 3 launcher:

```console
python3 -B framework/scripts/worktree_task.py setup --task-id <task-id>
```

Setup is idempotent and serializes the same task's setup. It reuses the completed shared environment or finishes initial setup after releasing the Git lifecycle lock. Permission denials follow the same inspection/native approval policy as create. Retained setup locks require review; never delete them automatically. A failed or interrupted setup cannot enter normal task execution or integration.

On Windows, use `py -3 -B framework/scripts/worktree_task.py setup --task-id <task-id>` from the surviving checkout containing the updated helper. This recovers native-library-only setup failures without installing PDF DLLs. Setup uses that caller's helper and the primary checkout’s canonical requirements, checking the retained worktree’s compatibility; it does not update code in existing linked worktrees. Update their code through the normal Git workflow before using their older helper again.

**Set the working directory of every subsequent change/child command to the returned `worktree` root.** Execute the original child skill/task there, including its preflight, contract registration, exact Modified files, authorization, validation and completion. Register `tasks/<task-id>.md` there as its first repository change; pass that selector to child commands or set `BLUEPRINT_TASK_FILE` per process. Do not copy running contracts from other checkouts.

For every Python task/check/loop command in the returned worktree, use the common wrapper, even in a fresh shell. It selects the worktree's registered ready shared Interpreter and prepends its bin directory to PATH; subprocesses using `sys.executable` and Python CLIs inherit the same environment. Missing/failed/stale setup stops with the recovery command. The JSON `python_setup.interpreter` path can also be used directly, but the wrapper additionally sets PATH for CLI resolution; new worktrees reuse the same completed environment without package verification when the requirements hash matches.

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-id>.md --source <external-contract>
```

### Correcting this Task's own declaration errors

If `--source` rejects a contract candidate, compare the concrete error with the
original Human request. Correct only the LLM's own declaration mistake within the
unchanged Goal, target and authority, then rerun `--source` with the same Task ID,
selector and worktree. Continue the original work after registration succeeds.
Pre-registration rejection creates no contract: do not suspend it or create another
Task/worktree to retry. A simple pre-registration Task type typo may be corrected;
changing the substantive Task type, Goal or target requires a new Human request.

For errors after registration or Validation/local-loop failure, first assess
[Self recovery](../../../framework/rules/task-contract.md#self-recovery). Inspect
ownership, Git diff, index and Task baseline before correcting only safely repairable
LLM mistakes. Requirement/Acceptance ID typos, necessary file omissions justified by
the original Goal, unnecessary LLM-owned edits and declaration inconsistencies within
the same authority may be repaired. Register exact necessary paths before editing;
never broaden Allowed paths merely to pass Validation or add unauthorized files.
Validate the repaired contract and actual change scope. While suspended, run only
the existing `--check-resume-scope`; if it passes, all stopping causes were safely
repaired LLM errors and no blocker remains, use existing `--resume`, then rerun the
failed checks and continue. Ordinary Validation, generation and Deploy remain forbidden
while suspended. Python validates and transitions status; the LLM decides corrections.

Never infer ownership or Human consent, discard Human/other-Task edits, bypass a
conflict or safety boundary, omit failed checks, or recreate a Task to evade retry
limits. Retain at most 3 correction iterations per logical failure class and stop on
the same error twice consecutively without material progress. If safe recovery does
not apply or fails within those limits, preserve state and follow Retry and stop.

Select validation solely under [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy): text-only Skill/Prompt/Markdown changes require diff, reference and `git diff --check`; Model changes use Change Validation; View-only regeneration retains scoped generation, synchronization and migration checks; IaC and Framework changes retain their scoped and applicable static or regression checks. Do not automatically promote ordinary tasks to Full. Explicit Full/release requests and special recovery retain their existing required Full/IT checks. Generated views are not independent text-only changes. Run lifecycle create/setup/finalize/cleanup with the ordinary launcher from a surviving checkout, so cleanup does not depend on the worktree-local Interpreter it removes. Pandoc and WeasyPrint native libraries remain OS prerequisites for PDF export; AWS CLI and Terraform remain external tools.

The worktree contains committed base inputs only. Do not silently copy/stash the source checkout's dirty files. In particular, infrastructure `/update` needs the human's intended uncommitted model diff **in the new worktree** before child execution. Explicit Model-only IMPORT merge/delete instead uses the Human-specified operation and IDs without pre-edits. If that input is only in the original checkout, retain both checkouts and request explicit input placement; do not run update with missing input or infer/copy unrelated changes.

## Independent Deploy lifecycle

`/deploy` automatically uses this lifecycle through `worktree_task.py deploy-start --task-id <id>`; no explicit Human `/worktree` invocation is needed. Every Skill invocation starts a new Task with an unused Task ID; operations within that invocation use its Worktree and Snapshot. Follow [Managed Deploy snapshot and Git publication](../../../framework/rules/cloudformation.md#managed-deploy-snapshot-and-git-publication) for the Deploy-only fixed baseline, per-Stack checkpoints, delta publication, Human conflict review and Git-only `deploy-publish` recovery. These publication commands require the same permission inspection above. After required Snapshot validation and publication, run ordinary `finalize`; the final Deploy candidate already includes its completed contract. Its Deploy branch verifies publication and uses existing guarded cleanup. Other Tasks retain the sequence below.

## Complete and integrate

For a normal Model-only /update task (including standalone `import-retarget`) or a
Framework-only governance/catalog-maintenance/migration task with explicit
`framework` Validation scope, finalize is the final validation composition:
keep the Task running after its changes and required related checks, and invoke finalize directly. It prepares
the private commit, validates the candidate once in registered Python, completes from
that result and integrates that exact HEAD. Local FF integration uses the latest-base candidate;
PR publication uses its original validation baseline without synchronizing the base. Completed Model-only/Framework tasks
also undergo that final-candidate check. The ordinary launcher cleans up after the child exits.
No separate pre-finalize complete or duplicate final loop is required in this branch.
Framework tasks use the existing Framework scoped validator, without Consumer
environment/target/service inputs or Model loading. Run dependency-selected UTs,
necessary IT cases and applicable static checks through existing entrypoints under
Validation policy; reassess changed dependencies after base synchronization before integration.
The scoped final loop does not replace those tests or automatically select regression.
Failure retains the candidate; never amend or discard it. For model-delete, explicit
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

If validation/local loop fails, first assess and, when applicable, perform existing Self recovery as described above. If unresolved or outside its safety boundaries, report the concrete failures and stop. If the human explicitly approves commit and merge despite those failures, keep the contract `suspend` with its Suspension reason; do not run `--complete` or report validation PASS. With all requested work and inputs otherwise finished, use:

```console
python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id> --human-approved-validation-failure "<human approval identifying the accepted failures>"
```

Use this option only after actual human approval of this task's failures; a general request to run the task or this skill is not approval. The helper records the approval in lifecycle metadata and the commit message; Git integration success remains separate from validation FAIL. The approval permits only commit/merge/cleanup, without resuming the task or authorizing AWS operations. Missing inputs, unfinished work, and Git safety blocks still stop integration. A retained committed task may retry with its recorded approval; changed work needs renewed review and approval.

Outside the Model-only/Framework final-candidate branch, `finalize` reads the existing completed status (or the explicitly approved suspended status), rejects unresolved Git operations and unexpected branch commits, and stages only exact non-ignored task paths (including newly added files). It never force-adds `tasks/**`. Normal commit messages use `task(<task-id>): completed task`; approved failures use `task(<task-id>): human-approved validation failure`; zero changes create no empty commit.

Task differences include all committed changes and staged/unstaged/untracked changes.
For PR mode the recorded Task validation baseline identifies the Task diff independently
of the current base; direct integration uses its recorded Task baseline and synchronization checks.
Undeclared Task changes are never filtered through Modified files.

Ordinary integration runs the shared candidate Model guard before commit and after synchronization
in the target worktree’s registered Python,
with its Task explicitly selected. The launcher retains Git, lifecycle lock and cleanup ownership.
Framework-only changes do not load Models. Ordinary Model changes compare only changed-service
before/after snapshots through the Change Plan, never target-wide Full quality validation;
dedicated operations retain their raw-field preservation checks. Cheap contract, HEAD, commit
and base checks precede analysis and required checks remain after
the guard; changed Task, files or index stop before staging. No runtime fallback or automatic
setup/retry occurs. Successful guard diagnostics use stderr so stdout remains CLI JSON; failures
retain the child return code, stdout and stderr separately in `diagnostics`.

It checks a clean worktree holding the local base and the candidate/base identity, merges with `--ff-only`, verifies the expected task tip is included, and removes the clean owned worktree and its verified local branch. If the base advanced, follow [Base synchronization and revalidation](#base-synchronization-and-revalidation) first. Branch deletion uses `-D` only after ownership and automatic-cleanup checks. Have the local base checked out in an available worktree before finalize; the helper does not switch anyone's branch. Helpers serialize Git integration through the shared `<primary>/.worktrees/.blueprint/lifecycle.lock/` mutex; AWS locks remain separate. Default finalize creates no remote push or PR. Only an explicit Human PR request selects the PR exit below.

## Base synchronization and revalidation

An ordinary local finalize may return exit 0 with `status: needs_sync` and the newer base SHA in `base`. PR creation and updates do not require base synchronization. This is a continuation request, not Validation PASS or Task suspension. Inspect the exact Task, candidate, base history, relevant diff and Sandbox permissions before the appropriate operation:

```console
python3 -B framework/scripts/worktree_task.py sync-latest-base --task-id <task-id> --expected-base <reviewed-local-base-sha>
python3 -B framework/scripts/worktree_task.py pr-sync-base --task-id <task-id> --expected-base <reviewed-remote-base-sha>
```

The local operation is for ordinary running/completed Tasks; the PR operation is for the same published PR and Worktree. The local operation replays only the proven linear Task history from its recorded boundary onto the reviewed local base, including a rewritten base, changing commit SHAs. Git combines nonconflicting changes even in the same file; changes already present in the base are not applied twice. A real conflict retains the Task candidate for review; merge histories that cannot be proven safe stop for review. A Task with no changes does not need to be redone when the base changes. The PR operation retains history with a Git merge. Both return `needs_validation` after a new candidate is prepared. An unchanged local base returns `ok` without a new candidate. A failed or unfinished rebase, an unknown outcome, or a changed Task or HEAD retains the Worktree for review; never automatically abort or reset it. An interrupted successful rebase resumes only when its recorded intent and Git history match. The PR operation checks GitHub and Git refs, published HEAD and intent; it fetches the target base without changing local master or pushing. Reconcile an uncertain push through `pr-update` before synchronization when required. For a published PR whose GitHub conflict requires resolution, explicitly select `pr-sync-base` for the reviewed remote base. If its merge conflicts, retain the recorded merge, resolve and commit the conflict in the same worktree, then retry the same command. The helper verifies both merge parents and the Task scope against that base, then requires validation before `pr-update`. Unexpected HEAD or inconsistent state stops for review; do not reset, force push or edit lifecycle metadata.

After synchronization, the LLM reviews the inherited changes and selects and runs the relevant UT/IT and other checks under Validation policy; revalidate the updated candidate when its contents change. Confirm their results, then resume the same `finalize` or `pr-update`; the existing final-candidate guard and Validation remain separate mandatory checks. The Python helper does not select or run UT/IT or record their PASS. If an ordinary local integration base advances again, repeat synchronization and reassess the tests; stop and report persistent churn or an actual failure instead of an unlimited automatic retry. Do not switch to a new PR or alter Deploy checkpoint/repair lifecycles.

## Explicit PR publication

When the Human explicitly requests a Pull Request, select its mode after Task registration
and before Task validation with `python3 -B framework/scripts/worktree_task.py pr-select --task-id <task-id>`.
This records the existing PR mode without checking or synchronizing the base, committing,
or publishing. It lets Task validation use its recorded Task baseline even if the base
history changes before finalize. It does not select PR mode for a task that merely changes
PR support. For a Task already selected as PR, retrying selection is idempotent.

Use `python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id> --create-pr`
only when the Human explicitly requests a Pull Request. A feature implementation request
about PR support is not itself a request to publish that Task as a PR. Default finalize
retains FF Merge → Cleanup. Append `--draft` to create a Draft PR; without it creation remains a normal PR. Re-running finalize never changes an existing PR's Draft/Ready state. `--draft` requires `finalize --create-pr`.

`--create-pr` is finalize-only and is rejected for Deploy or
Deploy Repair Child before their publication/parent integration begins.

Initial PR publication shares existing candidate, ownership, scope, guards and completion checks. It does not synchronize the base or require its SHA to match the validation baseline; conflicts are handled by GitHub. Model/Framework
final-candidate validation still runs once. It never merges, commits, checks out or resets
the local base, never sets `merged`, and never runs cleanup. Zero diff is refused.
Validation-failure approval remains independently explicit: where the existing exception
permits publication, retain Task `suspend`, the approval and Validation FAIL; never claim PASS.

The helper requires `gh`, authentication/write permission and a single identical `origin`
fetch/push URL in HTTPS/SSH form without credentials. It verifies repository identity and the existence of the GitHub/Git base branch. It refuses URL rewrites,
unknown/mismatched remote branches, changed candidate/Task, duplicate or closed/merged
PRs. Git transport uses a 60-second deadline and SSH batch mode. A temporary creation-only
pre-push guard rejects a remote branch that appears between discovery and push, including
a normally fast-forwardable branch. An existing pre-push hook is preserved and requires
review instead of replacement. Push uses only the candidate SHA and Task head without force; an existing matching
open PR is reused without editing its title/body. Publication title/body use the Task ID
and confirmed contract content.

`integrationMode: "pr"` and `prPublication` retain base/head/candidate/Task identity,
remote/repository, PREPARED/PUSHED/OPEN progress and PR URL/number/state plus `isDraft`. GitHub `state: OPEN` is separate from Draft status. The verified intent
is atomically saved before remote effects. A task OS lock serializes publication before
short lifecycle sections; network calls never hold the common lifecycle lock. Its owned
lock file stays at the same inode and the OS releases exclusion on process exit.

After failure, retain Worktree/branch/lifecycle and retry the same Task with `--create-pr`.
Reconcile remote refs and the matching PR after a push/API or creation/state-save interruption;
never silently create a second PR or fall back to FF Merge. A prior create intent with no
matching PR has an uncertain outcome and requires Human review. After explicit Human
approval to retry that exact Task, verify repository, base/head, candidate SHA, current
remote head, and absence of a matching PR, then use:

```console
python3 -B framework/scripts/worktree_task.py pr-retry-create --task-id <task-id> --expected-commit <reviewed-candidate-sha>
```

The helper rechecks these boundaries and records a single retry intent before the request.
It reconciles an existing matching PR without another request. A second uncertain retry,
changed head, foreign PR, or failed check retains state for review. Plain finalize on a PR Task
stops with explicit guidance. Candidate/authority changes and unsafe Git state require
review; do not hand-edit lifecycle metadata or overwrite remote refs. PR success returns
`prPublication.url`, `number`, `prState` and `status: OPEN`; worktree and branch remain.
PR creation and Push success retain the Worktree and branch.

### Independent PR operations

These operations are Git tools; the caller chooses their timing and order. They add no
reviewer, external orchestrator, Task archive, watcher or scheduled workflow.

```console
python3 -B framework/scripts/worktree_task.py pr-update --task-id <task-id>
python3 -B framework/scripts/worktree_task.py pr-ready --task-id <task-id>
python3 -B framework/scripts/worktree_task.py pr-draft --task-id <task-id>
python3 -B framework/scripts/worktree_task.py pr-merge --task-id <task-id> --merge-method squash
python3 -B framework/scripts/worktree_task.py pr-status --task-id <task-id>
python3 -B framework/scripts/worktree_task.py pr-close --task-id <task-id>
python3 -B framework/scripts/worktree_task.py pr-close --pr <number-or-url>
```

`pr-update` prepares and validates a descendant candidate in the same Task/Worktree.
Neither an advanced base nor a GitHub conflict prevents the update; no base synchronization
or temporary integration is required. `pr-sync-base` remains available only when explicitly
chosen. The saved intent retains the previous published HEAD, candidate, validation baseline,
Task hash, validation result and Push state. The existing remote HEAD must equal the
recorded previous HEAD; only an ordinary non-force Push is permitted. An uncertain Push
is reconciled against the old and candidate HEAD before another attempt; a third HEAD
stops for review. After Push, confirm the PR identity and published HEAD against the
saved validated intent. Published commits are never rebased or reset. Retry `pr-update`
without editing management JSON or discarding the intent. Update never recreates the PR
or cleans up the Worktree.

Draft/Ready transitions are explicit. `pr-merge` supports `squash` (default), `merge` and
`rebase`, matching the published HEAD before requesting GitHub merge. `pr-status` explicitly
reconciles external or uncertain merges and reports GitHub's `mergeable` result; `UNKNOWN`
means GitHub has not determined mergeability. Use that result to decide whether conflict
resolution is needed. Both clean up automatically only after GitHub
confirms MERGED with the same repository, number/URL, base/head and published HEAD, and a
known merge commit. Squash/Rebase do not require that original HEAD be a local-base ancestor.
Merge failure/unknown result retains lifecycle state for reconciliation. Automatic cleanup
still preserves unexpected dirty worktrees/artifacts; use explicit disposal when intended.
`pr-close` never cleans up and never deletes the remote branch. After local cleanup use
`pr-close --pr <number-or-url>` against this checkout's origin repository. PR Close and
Worktree Cleanup are separate; either may run first. No PR operation deletes remote branches.

## Failures and cleanup

Exit 0 and JSON `status: ok` indicate success; `needs_sync` and `needs_validation` require the continuation above. Exit 1 and `status: blocked` give the reason and retained branch/worktree/commit/merge state when available (invalid CLI arguments exit 2). Apply [Sandbox permission approval and continuation](#sandbox-permission-approval-and-continuation) before stopping for a sandbox write denial. Do not parse long Git stdout or construct ad hoc recovery shells.

For failed validation/loop, assess Self recovery first; if unresolved, stop before finalize/commit unless the human explicitly approves the exception above. Other suspended tasks, missing input, approval waits or conflicts still stop before finalize/commit. Keep worktree and branch; use the child's existing suspension/resume rules. Ordinary finalize never completes or resumes a task; the Model-only/Framework final-candidate path completes only after validation passes. A dirty base is never stashed/reset/overwritten. Reviewed recovery rebase failure runs `rebase --abort`, preserves the task commit and worktree, and requires human review; do not guess conflict resolutions. A normal base advance follows [Base synchronization and revalidation](#base-synchronization-and-revalidation).

Automatic cleanup follows a verified local FF merge or a GitHub merge confirmed by
`pr-merge`/`pr-status`. It retains the existing completion/cleanliness checks and Import,
Deploy and Repair evidence finalization. Merge success remains recorded if cleanup fails;
never roll it back. Automatic cleanup uses the already-held task publication lock, followed
by the common lifecycle lock; it does not recursively acquire the publication lock.

Explicit Cleanup is a local disposal operation, independent of merge, PR existence/state,
Draft/Ready, Task running/suspend/completed, commits and uncommitted/ignored/untracked files.
No extra merge confirmation or Task completion consent is required. From a surviving root:

```console
python3 -B framework/scripts/worktree_task.py cleanup --task-id <task-id>
```

It verifies Task/path/branch/Git registration ownership and excludes operation conflicts,
then removes only the owned checkout and Git registration (`git worktree remove --force`
when explicit), its local `codex/worktree/<task-id>` branch (`git branch -D` after ownership
checks), and finally its state JSON. Symlink redirection, switched/foreign worktrees,
locked registrations, setup/publication/lifecycle/Git locks and unfinished Git operations
stop removal. No force Push, reset, foreign-worktree removal or repository-wide prune is
permitted. A missing checkout is recoverable from uniquely matching Git administration,
HEAD/branch and lock checks; explicit disposal does not require a clean retained index or
merge receipt. A branch-delete failure retains state so the same Cleanup retries after
checkout removal. Verify actual remaining resources before reporting completion.

Explicit disposal does not finalize uncertain Import/Deploy/Repair evidence. External
evidence is retained and reported under `retained_external_evidence`; it never becomes
successful publication evidence. Physical cleanup does not depend on workflow completion.
Neither cleanup mode changes GitHub PRs, remote branches, other Tasks, the shared Python
environment or AWS. Only verified post-merge automatic cleanup removes owned receipts.

### Orphan local branches

```console
python3 -B framework/scripts/worktree_task.py branches
python3 -B framework/scripts/worktree_task.py branch-delete --branch codex/worktree/<task-id>
```

`branches` is read-only and returns local branch ↔ Worktree registration ↔ Task-state
associations with an `orphan` flag. It requires no `--task-id`. `branch-delete` requires one
explicit branch, no Task state and no Worktree using that branch (including stale/locked
registrations). Tasks with management state use normal explicit Cleanup. No bulk deletion,
remote deletion, shared-environment removal or automatic pruning is provided.

Cleanup success and failure JSON include `cleanup.phase`, `cleanup.remaining` (checkout, Git registration, branch and task-state presence), `cleanup.stop_reason`, `cleanup.retry_command` and `cleanup.next_action`. A blocked result requires resolving its stop reason before retrying; the retry command is not permission to bypass a guard. A missing checkout alone does not mean cleanup completed. After a partial removal, use the same official cleanup command from a surviving checkout containing this recovery implementation.

Different worktrees still share AWS resources. Cross-worktree AWS mutation locking is a separate responsibility; this skill adds none and does not relax existing deployment controls.

## Normal Deploy Stack checkpoints

`cloudformation-deploy.py --action sync --sync-stack <StackName>` saves the adopted
current Model, generates available Views, validates and uses
`worktree_task.deploy_stack_checkpoint` plus Git publication in the same operation.
Success, failure, rollback, unexecuted, running and unknown Stack observations are
permitted. Receipts prove saved candidates, never AWS SUCCESS. `--action checkpoint`
resumes an already saved candidate, not a required second stage.
Snapshot structure/reference/scope/View and actual latest-base validation remain required.
A failed attempt may finish as completed with Deploy FAIL after its consistent Snapshot
is committed/merged. Include the final Task status in that same candidate. Active/uncertain
AWS requests keep Task running; intermediate publication may continue in the same Worktree.
Fixed IaC/parameters/artifacts remain unchanged across self-authored checkpoint commits.
Git-only retry of a saved (possibly locally completed) candidate requires no new AWS
execution or observation. Finalize verifies publication and performs guarded cleanup.
No old Task/Journal/Fence/Output or all-Stack-success prerequisite is reintroduced.

## Explicit CloudFormation repair handoff

Follow [Controlled deploy repair](../../../framework/rules/cloudformation.md#controlled-deploy-repair) and the AI judgment in [External IaC repair handoff](../../../framework/prompts/codex/deploy/runbook.md#external-iac-repair-handoff) only for the preauthorized one-shot request. Use `deploy_handoff.py --help` for the executable CLI and diagnosis format; the lifecycle below remains authoritative. `deploy_handoff.py --failure <current-failure.json> --diagnosis <diagnosis.json> --path <IaC-path>` verifies/checkpoints current parent authority and issues request.json. Suspend only that parent, then use `create --task-id <child> --repair-request <absolute request.json>` from its exact pinned tip. No Deploy Session or Workflow Ledger participates.

The child is infrastructure/implement with exact request IaC paths plus its contract, identical Validation scope, and AWS API execution/AWS mutation/Deploy/apply forbidden. `repair-validate --task-id <child> --repair-request <request.json>` runs the existing static task loop with registered Python, validates dependencies and permits at most 3 static cycles in that same child. After successful completion, finalize verifies the exact commit/paths/bytes and ff-only integrates into the suspended parent using recoverable commit/merge intents. Failure approval cannot issue a repair result. Cleanup removes the child; temporary handoff evidence is discarded after verified integration, retaining only active-Task commit attribution until its completion.

The LLM explicitly resumes the named parent and starts an independent Deploy with current target/Stack arguments. There is no --resume/--repair-result or history inheritance. No automatic unlimited new Deploy loop, parent IaC permission expansion, force/stash/reset, baseline reset or metadata hand edit is allowed.

## Reviewed fresh governance base sync

When explicitly asked to merge the latest local base before tests in a fresh governance Task, read that exact base diff and reconcile overlapping uncommitted candidates first. With an unstaged index and no Task commits, use `worktree_task.py sync-base --task-id <task-id> --expected-base <full-reviewed-base-hash>`. A Task that selected PR mode but has no publication record or verified candidate may use the same operation under the PR publication lock; it retains PR mode, and any recorded publication or update remains blocked. It preserves exact reviewed candidates/deletions in external backups, fast-forwards only the proven named base, restores candidates, and records the inherited validation base without completing/committing the Task. Existing start history is retained. Subsequent proven base advances use the same procedure; unexpected commits, scope changes or unknown dirty bytes stop. An interrupted sync retains its intent/backups for the same helper retry, never manual lifecycle reconstruction. Reconcile upstream changes in overlapping candidates before invocation; preservation alone does not prove a semantic merge.

## Human-reviewed governance conflict recovery

For an explicitly authorized retained governance repair, use
[Reviewed governance recovery](../../../framework/rules/task-contract.md#reviewed-governance-recovery).
Run `recover` from the checkout containing the reviewed helper with full expected
commit/base hashes. It reopens only that contract, pins the recovery, and retains the
normal finalize guards. After its aborted rebase, the authorized manual rebase may
resolve the reviewed conflicts; `--finish-recovery` registers the clean exact-base
candidate through the helper. Do not hand-edit metadata. Then execute the required
IT/Full validation before completing and finalizing. This does not apply to Model tasks.

If the base advances during recovery, resume a suspended contract and review the
clean candidate first. Run `recover --repin-recovery` with the full current candidate
hash as `--expected-commit` and full latest base hash as `--expected-base`. The helper
retains the old receipt and checks the old-base history/count/scope plus descendant
base before re-pinning. Manually rebase onto that pinned base, then use those new
commit/base arguments for `--finish-recovery`. Re-pinning grants no validation PASS;
rerun IT/Full on the final candidate before normal completion/finalize/cleanup.

For a governance task with a recorded Human validation-failure approval, the same
reviewed recovery accepts only a clean verified task and preserves its suspended
contract, reason and approval. Human review must identify the conflict resolution.
After `--finish-recovery`, use normal finalize with the recorded approval; do not
complete the Task or report the accepted failures as PASS. Any further change beyond
the reviewed resolution requires renewed Human review and approval.

Standalone `import-retarget` uses the existing running-parent final-candidate path.
Require successful latest-base reference/preservation validation; failed-validation
approval cannot bypass it. Never demand transfer/deletion for this operation or add
automatic regeneration, validation retry or an IT requirement.

## Task Acceptance with unrelated Model FAILs

Follow [Task Acceptance exclusions](../../../framework/rules/task-contract.md#task-acceptance-exclusions).
Keep diagnostic Validation FAIL separate from Task Acceptance. Only individually
Human-approved, evidenced pre-existing Model failures can leave Acceptance PASS;
required corrections, regressions and incomplete checks must be repaired to PASS.
Normal completion and final integration recheck the exact approved failures, candidate
and dependencies. A changed review requires renewed approval; no broad skip is added.
Report raw Validation, required checks, Acceptance, approved FAIL IDs/reasons and
unapproved FAILs separately. Existing suspended Git-integration approval retains its
separate semantics and is not an Acceptance approval.
