# Task Contract Rules
IMPORT desired configuration changes are exclusive to `/import`; follow [IMPORT configuration authority](model-information.md#import-configuration-authority). Read/compare remains allowed. Value-preserving source refactors are allowed; CREATE workflow is unchanged. Ordinary design, aws-check and update must delegate substantive IMPORT changes to import and cannot bypass the mechanical evidence guard.


## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
replaces the design validation/completion rules below: source and display transactions
are separate, and issues runs only when explicitly requested. Other workflows retain these rules.


## Task transition

### Managed worktree authority

A linked worktree created by `worktree_task.py` uses authorization without file
reservation conflicts only when its lifecycle JSON, canonical worktree path,
branch, Worktree identity, Task ID and selected `task_file` agree. Another local
contract prevents this mode; foreign contracts cannot grant authority. Invalid
managed state stops safely. Ordinary checkouts and manually created worktrees
without lifecycle metadata retain the reservation/Active/Deferred rules below.
No environment variable enables this mode.

`authorizations()` separates validated task scope from `reservations()` conflict
calculation. In managed worktrees, the validated exact Modified files are the
write allowlist. Status, Allowed paths, identity, ownership and safe paths still
apply. Existing incomplete Active/Deferred grants require explicit refresh;
readers and ordinary writes never promote them. Registration and explicit refresh
revalidate the full scope and publish grants atomically under the registration lock.

Each process retains one managed authority snapshot. Normal `require_writable()`
checks detect changes using file identity, mode, size, mtime and ctime, validate
requested paths (including symlinks), and test allowlist membership. They perform
no contract-content scan, conflict calculation, Git subprocess or JSON parsing.
Changes to contract files/task-directory membership, lifecycle metadata, Git
administrative state or Git environment invalidate the snapshot. Start, refresh,
suspend, resume and complete are detected through their atomic contract updates;
other processes' changes are detected too. Revalidation failure denies writes.
Contract-free explicit-target generation keeps its existing behavior.

Managed `reserved_batches()` yields each authorized job intact, without refresh,
reservation acquisition, Deferred waiting or sleep; `wait_deferred()` never waits.
Publication locks, atomic save/rollback, validation, Acceptance and all existing
finalize/commit/rebase/ff-only merge/cleanup checks remain mandatory. The following
reservation-specific rules apply to ordinary/manual checkouts; their authorization,
task boundary and completion requirements also apply to managed worktrees.

### Ordinary check boundaries

Task selection (`task_path()`), IMPORT scope selection, Model expansion, generated
Markdown/JSON and link readers do not calculate reservation conflicts or inspect
historical reservation paths. Selection still checks current Task identity, status,
local ownership and declared scope/Allowed paths; it never grants write permission.
IMPORT source selection uses contract ownership without conflicts; the mechanical
configuration-authority guard is unchanged. Explicit Validation through
`task_changes()` and `authorizations()` retains full contract/path/ownership checks.
Completed contracts are validated but never claim running reservations.

Registration validates the combined current-checkout contracts once under
`registration_lock()`. `start()`, `validate_registration()` and `acquire()` reuse that
result to publish all available Active grants and only conflicting Deferred grants
atomically. Invalid admission creates no partial contract.

Ordinary saves use `writable_batch()` at the publication boundary. One transaction
reads the latest reservations once and reuses that result for its exact destinations;
separate successful transactions each take a new snapshot. Only actual destinations
(and explicitly coupled output permissions) receive filesystem safety checks during
saving; old unrelated reservation paths are not repeatedly checked with `safe_path()`.
Allowed paths, status, identity, current grants, symlink/root/directory checks and
contract-change detection remain mandatory. An unchanged job needs no conflict scan;
any newly discovered output change is authorized at its actual save boundary.

Lock order is publication mutex, then registration mutex. Retain the registration
mutex through atomic publication, verification and rollback so another Task cannot
acquire an output between permission checking and saving. Nested save guards reuse
only the current thread's locked transaction; `require_writable()` alone is an
immediate check and does not lock a later write. Model expansion and candidate
validation run before this short registration-lock interval. Release both locks
before Deferred waiting, and reacquire fresh reservations on every attempt.
Planning snapshots exclude only refreshable Active/Deferred grant sections; Task,
scope or contract changes invalidate the plan. No permission snapshot survives a
transaction. Managed worktrees retain their existing authority snapshot and immediate
`reserved_batches()` behavior with zero reservation conflict scans.
Only reservation workers refresh grants automatically; direct publication checks the
existing grants without rewriting the contract or changing a pinned session digest.

### Common transitions and ordinary reservations

- Only `initialization`, `design`, `infrastructure`, `scenario-test`, `governance`, `catalog-maintenance`, and `migration` are permitted task types. The active prompt is the contract for this change, not the long-term design authority.

- Before repository changes, select this task's `tasks/<task-name>.md` and match its task type, target, and Goal to the latest request. A clean repository without a contract is idle. Register a separate contract as the first change of a new task; do not overwrite existing contracts.
- Record Task status (`running` / `suspend` / `completed`) in the Task contract and enumerate exact file paths under `## Modified files`. Globs, directories, and other tasks' contracts are prohibited. Reserve only paths within Allowed paths, including your own contract, not-yet-created files, generated artifacts, model parts, and deletion targets.
- Register with `task_contract.py --task-file tasks/<task-name>.md --source <repository外の契約候補file>`. The existing registration lock serializes changes within the current worktree. Conflict keys are the worktree identity plus exact repository-relative file path. A same-worktree overlap defers only that file; save the new contract and continue its non-conflicting Active files. Do not change existing contracts.
- Apply the same file reservation policy to `issues/**`. For IaC saves, reserve only `iac-issues.md` (and ordinary `issues.md` when saving both). Retain Scope checks, the shared publication lock, reservations, and indivisible atomic publication/rollback. Do not reserve `iac-issues.state.json`; saving ignores existing state without updating or deleting it. Deferred report writers acquire the whole batch before saving; unrelated files can proceed.

- Each process selects the contract with `BLUEPRINT_TASK_FILE`; the local loop/validator can also use `--task-file`. Explicit selection is mandatory only when multiple current-worktree tasks are running. Before adding or changing planned files, update Modified files/Allowed paths and run `task_contract.py --task-file tasks/<task-name>.md`. This refresh acquires available files under the registration lock, reports Active/Deferred paths and their owners, and leaves conflicts Deferred without stopping the task. Do not write Deferred files; process Active files separately. A Deferred write denial is pending work, not a task-wide check failure; do not suspend solely for deferral. Keep indivisible multi-file publications intact when one of their files is Deferred.
- Registration records a `Worktree identity` fingerprint from the canonical worktree-specific `git rev-parse --absolute-git-dir`. It distinguishes main and linked worktrees, does not use branch names, and supports detached HEAD. Do not store machine-specific absolute paths in contracts. Before Git initialization, use a canonical directory fingerprint; refresh binds it to Git metadata after initialization. Unbound legacy contracts belong to their containing checkout until registration/resume/refresh binds them; bind before carrying running legacy contracts to another worktree. Git owns merge conflicts between worktrees.
- `## Modified files` remains the requested scope. Registration/refresh maintains `## Active files` (acquired paths) and `## Deferred files` (remaining paths); do not manually grant files. New requested paths have no write permission until refresh. A file has at most one running owner in one worktree; inconsistent manual/legacy overlapping claims deny only the overlapping file to every contender. Read-only ownership checks never acquire files implicitly; normal write workers acquire available grants automatically at the locked save boundary. Existing contracts without grant sections retain legacy grants until refresh. Staged validation rebinds source-local contracts only inside its disposable snapshot; original and foreign contracts remain unchanged.
- Process all runnable Active work before waiting. The shared `task_contract.reserved_batches()` helper enters each independent write transaction with `writable_batch()` and keeps existing indivisible output batches together. `require_writable()` remains an immediate file-level guard; a `DeferredWrite` is pending work, not validation failure. Never write a Deferred file or retry a whole operation that has already performed external mutations.
- After Active work is exhausted, automatically refresh Deferred reservations every **30 seconds**, for at most **20 waiting attempts** (approximately **10 minutes**). Each attempt refreshes reservation state under the existing registration mutex, retains it only for a ready publication, and releases it before sleeping or further Model processing. Acquire any free files atomically; process newly Active work immediately, including partial acquisitions, before returning to the remaining Deferred work. Different-worktree reservations cause no Deferred state, retry, sleep or warning.
- Python write workers use `reserved_batches()` and continue each yielded unit in the same invocation. For agent-driven edits, the agent itself runs `task_contract.py --task-file tasks/<task-name>.md --wait` after finishing Active work, then immediately processes the acquired files. This command returns on any acquisition so work precedes further waiting; call it again only after the new Active work is done. Do not ask the human to monitor ownership, run resume, or run an acquire command during the retry period. Registration and ordinary refresh do not wait while Active work is still available.
- Python workers use one total 20-attempt budget across their waiting phases; progress always runs immediately even on attempt 20. Agent waiting permits 20 attempts per Deferred-only phase, returning as soon as acquisition makes progress; each successful phase reduces the finite unfinished file set. Do not reset a budget merely because ownership remains unchanged. Retry exhaustion exits the current execution cleanly, preserves Deferred files and `running`, and marks neither failure nor completion. The next normal write execution refreshes available grants automatically. Exhaustion must not produce a saved-output claim or a full-task success claim for unfinished work.
- Reservation waiting is separate from the implementation-error retry limit below. Real validation/input/I/O/ownership errors retain existing failure handling. Do not rerun generation, investigation or framework validation at every poll. Log entering wait, acquired files and exhaustion; avoid a log every 30 seconds. Never forcibly steal or release a reservation because ten minutes elapsed. There is no automatic stale-owner or crashed-registration-lock recovery; preserve ownership until a safe explicit status transition/recovery.
- Read-only investigation and chat-only design consultation do not require contract registration or switching.
- Reservation, task selection, running counts, ownership, output checks, resume, and local loops consider only current-worktree contracts. Foreign contracts do not reserve or authorize current-worktree outputs. Explicit selection or status transitions of a foreign task fail with a clear error. Ignore foreign contract files when attributing changes; retain rejection of local output changes without a local reservation. Apply task type, issue gate, and Acceptance checks only to this task's Active changes; a Deferred file cannot count as its achievement. Generation and model splitting check output reservations before saving.
- Generated views whose publication bytes are unchanged need no individual output reservation and are excluded from publication. For ordinary workflows retain candidate validation; recheck inputs, output differences and writable reservations under the publication lock before saving. If an excluded sidecar changes or disappears, its resulting write still requires a reservation. This does not exempt authoritative Model inputs or changed/generated/deleted files from ordinary reservations.
- For isolated worktree Git integration only, explicit human approval of concrete validation failures may permit commit/rebase/merge/cleanup through `worktree_task.py finalize --human-approved-validation-failure "<approval and accepted failures>"`. Keep the task `suspend` and its current Suspension reason; do not use `--complete` or claim validation PASS. All requested work/inputs must otherwise be finished; Deferred files, scope/ownership errors, Git safety blocks, and AWS permission boundaries remain in force. See [worktree skill](../../.agents/skills/worktree/SKILL.md).
- Complete only after successful final validation under [Validation policy](loop-engineering.md#validation-policy) and after all requested work is finished. Use `task_contract.py --task-file tasks/<task-name>.md --complete`; it checks remaining Deferred files under the registration lock. A task with any Deferred file remains `running`, even when Active checks pass. Deferred path-based Acceptance checks are reported as pending, never passed; other required validation remains in force. Completed contracts release reservations and retain acquired-file ownership only while uncommitted changes remain. Delete them when the diff disappears; do not retain task history or evidence.
- When stopping for a check error, set only this task's Task status to `suspend`, whether the cause is this task, another task, unregistered changes, or the baseline. `## Suspension reason` is mandatory and must name the failed check, target file, concrete error, and any necessary log path outside the repository. Retain only the current stop reason; do not add execution history or evidence. The local loop automatically suspends after all checks finish or child processes stop, including precheck failures. Do not infer which of multiple running tasks to suspend without an explicit selector. Staged validation status changes apply only within the snapshot.
- When stopping for a standalone check outside the local loop or an error during work, also suspend this contract with `task_contract.py --task-file tasks/<task-name>.md --suspend-reason '<具体的な問題>'`. Preserve other tasks' contracts and uncommitted changes; do not repair unrelated failures within this task.
- Suspended contracts release reservations and retain ownership of acquired uncommitted changes. Reject generation, deploy, and loops while suspended. Resume explicitly with `task_contract.py --task-file tasks/<task-name>.md --resume`: acquire available files, return to running, clear the stop reason and leave conflicting files Deferred. The same command can refresh a running task. Completion/suspension of a predecessor releases its reservation; a running waiter acquires it automatically on its next locked retry. Never automatically resume a suspended task.
- Permit the legacy `tasks/active.md` contract only when it is the sole contract. Before concurrent operation, migrate it to a separate contract and record Task status and Modified files. Reject non-contract changes when no contract exists.
- Do not create or execute another task after the loop succeeds.
- Do not change task type or work phase during retry.
- Do not proceed to scenario tests because infrastructure behavior changed.
- Do not automatically fix test failures by changing design, changing IaC, or redeploying.

- A change with a different task type, target, or Goal is a new task.
- A request to save a chat-only design in the repository is a new `design` task; switch the active task before saving.
- Do not treat a task as complete if an Acceptance check for a Requirement ID or a task-type-specific check is unimplemented, unexecuted, or failing.

## Task boundary

- [Service source authority](model-templates.md) applies to every task type. Reserve exact
  template entry/parts, parameters.yaml, bindings.json, observed.json and generated
  Markdown/JSON paths before writing. Common template changes require every registered
  direct consumer in Validation scope; environment inputs require their environment/service.
  Downstream scope follows changed active resource-reference results/identities under
  Model templates; unproven or unresolved dependencies remain conservative. Source
  impact never expands Deployment scope or AWS permission. Design may edit
  template/parameters/fixed bindings; infrastructure observed writers may edit observed.json
  and generated views. Destroy cannot edit templates/parameters/bindings. Update treats
  human service input diffs as immutable intended-design inputs; retain generated-view
  equality checks and reject ambiguous/multiple deployment target handoffs.

- `design`: Update authoritative `model/templates/**` / `model/parameters/**` inputs and generate `docs/designs/**`, then finish after local validation. Existing-resource retrieval may reflect only properties selected by the chatbot and necessary non-ARN current identifiers. Do not proceed to IaC, AWS mutation, or scenarios.
- `infrastructure`: Read the approved design; perform only the IaC specified by the active prompt, safety checks, authorized deploy/apply, and, after success, updates to `observed.json` in `model/parameters/**` and Markdown generation, then finish. The `destroy` phase permits only explicit designed CloudFormation Stack deletion, necessary post-success `observed.*` changes and corresponding generated Markdown/JSON, and the active task contract. IaC, desired/display design, scenarios and results must not change. It is independent of deploy; explicit `/destroy <StackName>` scope is authorized without a second confirmation. The `update` phase permits the uncommitted intended design manually edited by the human in authoritative service Model inputs before task start as immutable input; Codex must not change intended design or scenarios.
- `scenario-test`: Create/update only `tests/scenarios/**` and `tests/results/<scenario-id>/<environment>/<target-directory>/`. After test failure, do not proceed to design changes, IaC repair, redeploy, or remediation task creation/execution.
- `initialization`, `governance`, `catalog-maintenance`, `migration`: Execute only the active prompt's Allowed paths and explicit scope; do not proceed to another task.
- Do not automatically create or execute a scenario-test task even when infrastructure behavior changes.
- Only scenario-test tasks may change `tests/scenarios/**` and scenario results under `tests/results/**`.
- `/model-test` generation is an offline migration (framework implementation: governance), writing only `tests/<environment>/<target-directory>/<service>.py`. Human manual execution of these standalone read-only audits writes timestamped logs under `tests/results/<environment>/<target-directory>/<service>-YYYYMMDD-HHMMSS[-ffffff].log`; these are audit evidence, not scenario records. Environment directory names in results are reserved for audits. Generation and automated validation never execute AWS or save mock logs in the repository.
- Do not save non-scenario task validation/deployment results under `tests/results/**`. As a rule, verification output belongs only in the completion report.
- Place only independent contracts in `tasks/`; do not save task history or evidence. Task status is `running`, `suspend`, or `completed`. The current stop reason may be recorded in a suspended contract. Change only this contract to completed after the required final validation succeeds under [Validation policy](loop-engineering.md#validation-policy). Retain suspended contracts for resume and ownership of uncommitted diffs; retain completed contracts only while retaining ownership of uncommitted diffs, and delete them when the diff disappears.
- Track earlier scenario evidence versions in Git history; do not add directories per execution or timestamp.

## Controlled deploy repair contract

The CloudFormation deploy phase permits IaC repair only under [Controlled deploy repair](cloudformation.md#controlled-deploy-repair). Specify the values of `- Controlled repair: ` and `- Deploy repair session: ` in backticks as `allowed` and an absolute session path outside the repository, respectively; reserve only target templates/parameters/declared artifacts as exact Modified files/Allowed paths. Intended design, scope, and task type are immutable; file additions follow existing scope expansion/reservation checks. Repair authorization does not permit arbitrary editing: the validator requires matching AUTO_REPAIRABLE history and file digests in the same session. Human approval updates for existing change sets remain permitted as before.

## Acceptance contract

The active task's `## Required changes` must have unique Requirement IDs, with one or more checks mapped to each same ID in `## Acceptance checks`.

```md
- [R1] 実施内容
- [R1] `changed:path/to/file`
```

Only `changed:`, `exists:`, `absent:`, and validator-registered `check:` are permitted Acceptance checks. Reject arbitrary commands, unregistered checks, checks without a corresponding Requirement ID, and Requirement IDs without checks.

## Retry and stop

- Automatic correction for the same active task, task type, and logical failure class is limited to 3 iterations.
- Stop if the same error occurs twice consecutively without material progress.
- Do not fix missing human input by inventing values.
- Stop on out-of-scope file changes.
- Treat unapproved delete/replacement as waiting for human confirmation with an explanation, not as failure or automatic retry. If not approved, stop without executing deploy/apply.
- Stop if `framework/materials/aws/` differs from the baseline.
- Do not suppress failing checks to obtain a pass.

Human review that uniformly stops every deployment after validate/plan is not required. Plan-specific human confirmation for unapproved delete/replacement and Codex sandbox/OS permission control are separate mechanisms; operations requiring permission follow platform control regardless of repository rules.
