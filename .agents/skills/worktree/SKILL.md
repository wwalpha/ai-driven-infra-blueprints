---
name: worktree
description: Run a repository change task in an isolated linked Git worktree, then fast-forward merge its validated result into the latest local base by default. Publish a PR only when the Human explicitly requests one for that Task. Read-only investigation, analysis and review usually need no worktree.
---

# Isolated task execution

Use `/worktree <task-name> <child skill/task and its inputs>` for a task that changes repository files. This skill wraps the selected task; it does not replace its logic, authorize another phase, or authorize AWS operations. Existing task types do not encode read-only intent: decide from the requested outputs. Investigation/review without saved changes runs in the current checkout; `/issues` with saved reports is a change task.

**Default integration is local fast-forward merge followed by cleanup.** After the child workflow's required checks and completion conditions pass, continue through ordinary `finalize` without asking the Human to choose between merge and PR. Select `--create-pr` only when the Human explicitly requests PR publication for this Task; mentioning PRs, reviewing PR behavior or changing PR support does not select it. A Task selected for PR publication keeps that integration mode.

For `/import`, use the worktree selected by the Human; follow [08_import](../../../framework/prompts/codex/08_import.md) for its contract, evidence and validation requirements. Other change tasks retain this workflow.

## Read before execution

At start read [Task transition](../../../framework/rules/task-contract.md#task-transition) (including its required common and conditional reads), [Task boundary](../../../framework/rules/task-contract.md#task-boundary), [Acceptance contract](../../../framework/rules/task-contract.md#acceptance-contract), [Retry and stop](../../../framework/rules/task-contract.md#retry-and-stop), and [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy). Read only the selected child skill and its mandatory/conditional references, including its task-type completion section; these remain authoritative for child permissions and finish conditions.

When performing validation/integration, read [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope), [Conflict resolution and reproducible validation](../../../framework/rules/loop-engineering.md#conflict-resolution-and-reproducible-validation), and [Retry and stop](../../../framework/rules/loop-engineering.md#retry-and-stop). Read [Local loop](../../../framework/rules/loop-engineering.md#local-loop) when a loop is required, [Framework regression](../../../framework/rules/loop-engineering.md#framework-regression) only when the validation classification requires it, [Validation cache](../../../framework/rules/loop-engineering.md#validation-cache) when reusing results, and [Timing and long-running execution](../../../framework/rules/loop-engineering.md#timing-and-long-running-execution) for long runs. Do not unconditionally reread unchanged material already confirmed in the same Task; revisit necessary sections when inputs, classification or dependencies change or evidence is insufficient.

The examples use `python3` for macOS and Linux. On Windows, use `python` when it runs the intended Python 3 interpreter, including in an activated virtual environment. Use `py -3` when selecting an installed Python 3 through the Windows launcher. This substitution applies to both lifecycle commands and commands using `run-python.py`.

## Sandbox permission approval and continuation

Apply this procedure to **create, setup (when needed), base synchronization, finalize, PR operations, orphan branch deletion and cleanup**, regardless of the Codex model. The agent requests permissions through its execution tool; the Python helper cannot open the platform's approval UI. Do not end the task merely because a sandboxed helper invocation returns `status: blocked` with a write denial.

Before each operation, identify its actual write destinations and compare them with the effective Sandbox policy, including protected paths and symlinks. This includes the Git common directory, linked worktree administration/index, lifecycle metadata and, when applicable, the shared Python environment. Do not probe by writing or infer a denial from filesystem permissions alone. If a required destination is protected, request native permission on the first invocation, restricting write access to the necessary paths where supported; if access is allowed, run normally. If restrictions or destinations are unknown, use the ordinary invocation and identify any failure. Permission does not relax Python's guards.

For normal execution, determine the requested scope, workflow, any Human uncommitted input needed, and required Human approvals. Review and carry over the specific uncommitted input when needed; unrelated uncommitted changes alone do not stop the Task. Delegate Task ID and collision checks, base resolution, worktree/setup, lifecycle and lock integrity, final Git/Task checks and cleanup ownership to the existing helper. Do not enumerate unrelated worktrees, branches, Tasks or locks before normal operations.

If the helper reports an error, investigate only the affected state. Confirm a write denial against the effective policy and use the supported native escalation (such as `sandbox_permissions: "require_escalated"`) for the required destinations. A denied invocation that made no changes permits at most one escalated reexecution. On partial work, unknown state, conflicts, busy locks, contract violations or Validation FAIL, retain resources and stop; never escalate to bypass a guard or delete a lock. Keep no permission-state file. A successful approved call continues the ordinary lifecycle.

## Create and execute

Standard lifecycle: Create and setup → Execute → Validate → Local FF Merge or PR → Cleanup after confirmed merge.

From the current repository root:

```console
python3 -B framework/scripts/worktree_task.py create --task-name <task-name>
```

Task names follow the existing lower-kebab-case rule. Each create generates a Task ID by appending a random six-digit suffix, including leading zeroes. The helper checks only that candidate’s lifecycle state, branch, Worktree path, Task contract and Git registration under the lifecycle lock. It tries up to 20 candidates and stops on any error other than a confirmed collision. The helper resolves the base from repository-local `blueprint.baseBranch`, otherwise the existing `origin/HEAD` symbolic default, then local `main`, then `master`. A configured but absent local branch stops creation. It neither fetches/pulls nor creates a missing base or uses the current feature branch as a fallback.

Create finishes Python Setup before returning success. Every managed worktree shares the fixed `<primary>/.worktrees/.blueprint/python-env/` environment, resolved through the existing primary repository lookup. Initial setup creates the venv at that final path, installs the primary checkout’s `framework/scripts/requirements.txt`, probes isolation and verifies core imports, pinned packages and `pip check`. Global Python is only the venv creation launcher; no global dependency fallback or global package installation occurs. No worktree-local venv is created.

Later Create/setup and runtime retain ownership, completion, executable and registration-path checks, and compare the primary requirements SHA-256 with `.blueprint-requirements-sha256`. A match starts no dependency-check Python child, pip or imports. A changed/missing hash queries installed versions once; if all match, only the hash is recorded. Otherwise the existing pip installation and `verify()` run before recording success. Installation/verification failure retains the environment and leaves the hash invalid for retry; pending verification must succeed even when partial installation already supplied all requested versions. Python changes do not trigger rebuilds. JSON uses existing `python_setup` with `status: ready`, `kind: shared`, `interpreter`, `bin`, and `installed` (true only for the call that installs). The `.blueprint-owner` record identifies a directory created by this helper; `.blueprint-ready` is written last after successful initial verification. A completion marker alone cannot claim an unknown directory. Shared paths/markers/config/bin must not be symlinks; the normal venv Python executable symlink is allowed.

The existing per-task setup lock remains. A separate `<primary>/.worktrees/.blueprint/python-env.setup-lock/` serializes first installation and dependency synchronization across Tasks, rechecking requirements/hash after lock acquisition, without holding the Git lifecycle lock during venv/pip/verification. Contenders wait up to 300 seconds, then report a busy lock for review; retained or unknown locks are never deleted. Explicit shared Python maintenance can finish an owned incomplete environment; unknown directories, redirected paths and completed environments with missing Python stop for explicit maintenance. Task/worktree/branch remain available after failure.

### Explicit shared Python maintenance

The primary checkout’s requirements are the unique canonical source for all shared installs and verification. An older worktree may omit new primary packages; different requested versions or worktree-only packages raise a conflict before installation. Reconcile and merge requirements into primary before use; never install a task worktree’s requirements into the shared environment. Helpers predating this policy must be updated through the normal Git workflow before use; older setup code cannot enforce this guard. Stop all running Tasks and Python children before changing canonical requirements or explicit maintenance: changing the shared environment affects every Task. The setup lock serializes installers and waiting launchers, but cannot protect Python processes already running when an update begins. Requirements changes synchronize automatically; Python interpreter changes and rebuilds require explicit maintenance. To rebuild a broken/completed environment, the operator must first review and preserve the old fixed directory outside the worktree/metadata tree, then run ordinary `worktree_task.py setup --task-id <existing-unmerged-task>` to build at the original fixed path. Do not run a relocated old venv. No lifecycle/cleanup command updates or deletes the shared environment. Setup failure before completion retains the owned partial directory for a setup retry; unknown directories/locks require operator review, never automatic deletion.

The selected environment's WeasyPrint package is version-checked, but its import/native library check is deferred to PDF export. PDF-free Model/Markdown/issue tasks require no GTK/Pango/GObject setup. Core imports and pip check block initial completion and post-install verification; unchanged-hash reuse does not rescan dependencies. See [PDF dependencies](../../../README.md#pdf-dependencies) for PDF checks and Windows DLL lookup. No optional requirements file or setup skip flag is needed.

The helper returns JSON containing `task_name`, `task_id`, `worktree`, `branch`, `base`, and `task_file`. Use the returned Task ID for all later commands. It creates `codex/worktree/<task-id>` and `<primary>/.worktrees/<task-id>` from the base; existing Worktrees and branches are preserved. Keep `/.worktrees/` ignored. Only `/.worktrees/<task-id>` is accepted for creation, setup, validation, integration and cleanup. Git creates its own administrative entries under the common Git directory's `worktrees/`; these are separate from the working files. All custom lifecycle metadata and locks live in `<primary>/.worktrees/.blueprint/`: `tasks/<task-id>.json` stores lifecycle/Python setup state, `tasks/<task-id>.tmp` is its atomic-save temporary file, `tasks/<task-id>.setup-lock/` serializes setup, and `lifecycle.lock/` serializes Git integration. Every linked worktree resolves this same primary location; none uses a nested local metadata directory. Metadata directories must not be symlinks. The ignored `/.worktrees/` covers these files, separate from repository task contracts in `tasks/`. Git's own administration still requires writes in `.git`.

Setup failure returns exit 1 / `status: blocked`, with `python_setup.status: failed` and an error, preserving Git worktree, branch and task state. Report the returned Task ID and retained resources. For explicit shared Python maintenance, use the ordinary Python 3 launcher from a surviving repository root:

```console
python3 -B framework/scripts/worktree_task.py setup --task-id <task-id>
```

Setup is idempotent and serializes the same task's setup. It reuses the completed shared environment or finishes initial setup after releasing the Git lifecycle lock. Permission denials follow the same inspection/native approval policy as create. Retained setup locks require review; never delete them automatically. A failed or interrupted setup cannot enter normal task execution or integration.

On Windows, run setup from the surviving checkout containing the updated helper. PDF DLLs are optional for ordinary setup. Setup uses that caller's helper and the primary checkout’s canonical requirements, checking the retained worktree’s compatibility; it does not update code in existing linked worktrees. Update their code through the normal Git workflow before using their older helper again.

**Set the working directory of every subsequent change/child command to the returned `worktree` root.** Execute the original child skill/task there, including its preflight, contract registration, exact Modified files, authorization, validation and completion. Register `tasks/<task-id>.md` there as its first repository change; pass that selector to child commands or set `BLUEPRINT_TASK_FILE` per process. Do not copy running contracts from other checkouts.

For every Python task/check/loop command in the returned worktree, use the common wrapper, even in a fresh shell. It selects the worktree's registered ready shared Interpreter and prepends its bin directory to PATH; subprocesses using `sys.executable` and Python CLIs inherit the same environment. Missing, failed or stale setup blocks execution. The JSON `python_setup.interpreter` path can also be used directly, but the wrapper additionally sets PATH for CLI resolution; new worktrees reuse the same completed environment without package verification when the requirements hash matches.

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-id>.md --source <external-contract>
```

### Contract and validation

If contract registration is rejected, report the error and retain the Task Worktree. Register exact necessary paths before editing. Select validation under [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy), including dependency-selected checks for Framework changes. Run lifecycle commands with the ordinary launcher from a surviving checkout. Worktrees start from committed base inputs. Place the Human’s intended input in the selected Worktree before starting a child workflow that needs an uncommitted Model diff.

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
Failure retains the candidate; never amend or discard it. For model-delete, an authorized correction in the same parent may produce a new candidate for final validation. Deletion leaves
never finalize separately: one parent Worktree contains all resource saves, followed by
one generation phase and one final-candidate validation/merge/cleanup on success. The commands
below describe other workflows and independent completion, not Model-only sequencing.

For infrastructure/implement, use the child workflow’s `--complete-on-pass` final loop; on PASS proceed directly to `finalize` without a separate `--complete`.

Finish all requested work and all required inputs/approvals under the child's existing workflow. Proceed only after successful final validation selected by [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy) and all other mandatory completion conditions:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-id>.md --complete
python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id>
```

If validation fails, report the concrete failures and retain the candidate and contract. Outside the Model-only/Framework final-candidate path, `finalize` requires a completed contract. It rejects unfinished Git operations and unexpected branch commits, then stages only exact non-ignored Task paths. Normal commits use `task(<task-id>): completed task`. Zero changes create no empty commit.

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

It checks that the clean primary checkout holds the local base and the candidate/base identity, merges with `--ff-only`, verifies the expected task tip is included, and removes the clean owned worktree and its verified local branch. If the base advanced, follow [Base synchronization and revalidation](#base-synchronization-and-revalidation) first. Branch deletion uses `-D` only after ownership and automatic-cleanup checks. Have the local base checked out in primary before finalize. Helpers serialize Git integration through the shared `<primary>/.worktrees/.blueprint/lifecycle.lock/` mutex; AWS locks remain separate. Default finalize creates no remote push or PR. Only an explicit Human PR request selects the PR exit below.

## Base synchronization and revalidation

An ordinary local finalize may return exit 0 with `status: needs_sync` and the newer base SHA in `base`. PR creation and updates do not require base synchronization. This is a continuation request, not Validation PASS or Task suspension. Inspect the exact Task, candidate, base history, relevant diff and Sandbox permissions before the appropriate operation:

```console
python3 -B framework/scripts/worktree_task.py sync-latest-base --task-id <task-id> --expected-base <reviewed-local-base-sha>
python3 -B framework/scripts/worktree_task.py pr-sync-base --task-id <task-id> --expected-base <reviewed-remote-base-sha>
```

The local operation is for ordinary running/completed Tasks; the PR operation is for the same published PR and Worktree. The local operation replays only the proven linear Task history from its recorded boundary onto the reviewed local base, including a rewritten base, changing commit SHAs. Git combines nonconflicting changes even in the same file; changes already present in the base are not applied twice. A real conflict retains the Task candidate for review; merge histories that cannot be proven safe stop for review. A Task with no changes does not need to be redone when the base changes. The PR operation retains history with a Git merge. Both return `needs_validation` after a new candidate is prepared. An unchanged local base returns `ok` without a new candidate. A failed or unfinished rebase, an unknown outcome, or a changed Task or HEAD retains the Worktree for review; never automatically abort or reset it. A retained incomplete local sync stops for review. The PR operation checks GitHub and Git refs, published HEAD and intent; it fetches the target base without changing local master or pushing. An uncertain push requires review of the recorded and remote HEADs before synchronization. For a published PR whose GitHub conflict requires resolution, explicitly select `pr-sync-base` for the reviewed remote base. If its merge conflicts, retain the recorded merge, resolve and commit the conflict in the same worktree, then retry the same command. The helper verifies both merge parents and the Task scope against that base, then requires validation before `pr-update`. Unexpected HEAD or inconsistent state stops for review; do not reset, force push or edit lifecycle metadata.

After synchronization, the LLM reviews the inherited changes and selects and runs the relevant UT/IT and other checks under Validation policy; revalidate the updated candidate when its contents change. Confirm their results, then invoke `finalize` or `pr-update` for that Task; the existing final-candidate guard and Validation remain separate mandatory checks. The Python helper does not select or run UT/IT or record their PASS. If an ordinary local integration base advances again, repeat synchronization and reassess the tests; stop and report persistent churn or an actual failure instead of an unlimited automatic retry. Do not switch to a new PR.

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

`--create-pr` is finalize-only and is rejected for Deploy tasks.

Initial PR publication shares existing candidate, ownership, scope, guards and completion checks. It does not synchronize the base or require its SHA to match the validation baseline; conflicts are handled by GitHub. Model/Framework
final-candidate validation still runs once. It never merges, commits, checks out or resets
the local base, never sets `merged`, and never runs cleanup. Zero diff is refused.

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

A failed or uncertain publication retains the Worktree, branch and intent for review.
A confirmed matching PR can be reported without another create request. If a create
intent exists and no matching PR is visible, publication stops. Plain finalize keeps
the selected PR mode. PR success returns `prPublication.url`, `number` and `prState`.


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
recorded previous HEAD; only an ordinary non-force Push is permitted. An uncertain Push retains the old and candidate HEADs for verification. After Push, confirm the PR identity and published HEAD against the
saved validated intent. Published commits and the recorded intent are retained on failure. Update never recreates the PR
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

Exit 0 with `status: ok` indicates success. `needs_sync` and `needs_validation` request the normal base synchronization and validation steps. Exit 1 with `status: blocked` reports the error and retained resources when available. Invalid arguments exit 2. On failure, report the concrete error and retain the Task contract, Worktree, branch and unmerged changes. Worktree-managed Task checks preserve the current Task status and do not automatically suspend, resume or recover. Report errors and incomplete checks; preserve the Worktree, branch, Task contract and changed files. Apply necessary corrections and revalidation under the existing Task authority and Validation rules.

Automatic cleanup follows a verified local FF merge or a GitHub merge confirmed by `pr-merge` or `pr-status`. It checks completion, ownership, locks, and cleanliness. Merge success stays recorded if cleanup fails. The task publication lock precedes the lifecycle lock.

Explicit `cleanup --task-id <task-id>` authorizes local disposal of the owned checkout, registration, branch and lifecycle state, including uncommitted and ignored files. Git ownership and lock checks still apply. A missing checkout whose exact registration cannot be proved stops cleanup. Cleanup reports the phase and remaining resources.

Use `branch-delete --branch codex/worktree/<task-id>` only for one explicitly named branch without Task state. Git refuses deletion of a branch in use. Cleanup and branch deletion are local Git operations. Deploy permissions and AWS locks are separate.

## Reviewed fresh governance base sync

When explicitly asked to merge the latest local base before tests in a fresh governance Task, read that exact base diff and reconcile overlapping uncommitted candidates first. With an unstaged index and no Task commits, use `worktree_task.py sync-base --task-id <task-id> --expected-base <full-reviewed-base-hash>`. A Task that selected PR mode but has no publication record or verified candidate may use the same operation under the PR publication lock; it retains PR mode, and any recorded publication or update remains blocked. It preserves exact reviewed candidates/deletions in external backups, fast-forwards only the proven named base, restores candidates, and records the inherited validation base without completing/committing the Task. Existing start history is retained. Subsequent proven base advances use the same procedure; unexpected commits, scope changes or unknown dirty bytes stop. An interrupted sync preserves its intent and backups and stops for review. Reconcile upstream changes in overlapping candidates before invocation; preservation alone does not prove a semantic merge.

## Task Acceptance with unrelated Model FAILs

Follow [Task Acceptance exclusions](../../../framework/rules/task-contract.md#task-acceptance-exclusions).
Keep diagnostic Validation FAIL separate from Task Acceptance. Only individually
Human-approved, evidenced pre-existing Model failures can leave Acceptance PASS;
required corrections, regressions and incomplete checks must be repaired to PASS.
Normal completion and final integration recheck the exact approved failures, candidate
and dependencies. A changed review requires renewed approval; no broad skip is added.
Report raw Validation, required checks, Acceptance, approved FAIL IDs/reasons and
unapproved FAILs separately.
