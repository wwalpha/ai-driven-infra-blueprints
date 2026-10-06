# Task Contract Rules

## Task transition

- Only `initialization`, `design`, `infrastructure`, `scenario-test`, `governance`, `catalog-maintenance`, and `migration` are permitted task types. The active prompt is the contract for this change, not the long-term design authority.

- Before repository changes, select this task's `tasks/<task-name>.md` and match its task type, target, and Goal to the latest request. A clean repository without a contract is idle. Register a separate contract as the first change of a new task; do not overwrite existing contracts.
- Record Task status (`running` / `suspend` / `completed`) in the Task contract and enumerate exact file paths under `## Modified files`. Globs, directories, and other tasks' contracts are prohibited. Reserve only paths within Allowed paths, including your own contract, not-yet-created files, generated artifacts, model parts, and deletion targets.
- Register with `task_contract.py --task-file tasks/<task-name>.md --source <repository外の契約候補file>`. Registration serializes concurrent executions and compares Modified files of all running tasks. If any file outside the repository root's `issues/` overlaps, stop the new task and report the conflicting file and existing task. Do not save the candidate or target files in the repository; continue the existing task.
- All files under `issues/`, regardless of filename or hierarchy, are excluded from conflict stops at registration, contract update, resume, and local loop. This includes `issues/issue.md`, `issues/<environment>/<target-directory>/issues.md`, and `diff.md`. Each task must enumerate files it changes in Modified files and retain checks for Allowed paths, unregistered changes, task boundary, issue gate, and Acceptance checks.
- Each process selects the contract with `BLUEPRINT_TASK_FILE`; the local loop/validator can also use `--task-file`. Explicit selection is mandatory when multiple tasks are running. Before actually adding or changing planned files, update the contract and recheck with `task_contract.py --task-file tasks/<task-name>.md`. Revert a conflicting contract update and stop this task.
- Read-only investigation and chat-only design consultation do not require contract registration or switching.
- The loop checks conflicts among all contracts and unregistered changes, and applies task type, issue gate, and Acceptance checks only to changes in this task's reserved files. Do not count other tasks' changes as achievements or violations. Generation and model splitting also check this task's reserved files before saving.
- Change this task's Task status to completed only after the local loop succeeds. Completed contracts release file reservations and remain only while retaining ownership of uncommitted changes. Delete them when the diff disappears; do not retain task history or evidence.
- When stopping for a check error, set only this task's Task status to `suspend`, whether the cause is this task, another task, unregistered changes, or the baseline. `## Suspension reason` is mandatory and must name the failed check, target file, concrete error, and any necessary log path outside the repository. Retain only the current stop reason; do not add execution history or evidence. The local loop automatically suspends after all checks finish or child processes stop, including precheck failures. Do not infer which of multiple running tasks to suspend without an explicit selector. Staged validation status changes apply only within the snapshot.
- When stopping for a standalone check outside the local loop or an error during work, also suspend this contract with `task_contract.py --task-file tasks/<task-name>.md --suspend-reason '<具体的な問題>'`. Preserve other tasks' contracts and uncommitted changes; do not repair unrelated failures within this task.
- Suspended contracts release reservations, allowing other tasks using the same files to register. Retain ownership of uncommitted changes; do not reuse them for other tasks' Acceptance checks. Reject task execution such as generation, deploy, and loop while suspended. Before resuming repair/revalidation, run `task_contract.py --task-file tasks/<task-name>.md --resume` to serialize and check reservation conflicts with all running tasks. Return to running and remove the current stop reason only on success; retain suspend and its reason on conflict. Do not automatically resume.
- Permit the legacy `tasks/active.md` contract only when it is the sole contract. Before concurrent operation, migrate it to a separate contract and record Task status and Modified files. Reject non-contract changes when no contract exists.
- Do not create or execute another task after the loop succeeds.
- Do not change task type or work phase during retry.
- Do not proceed to scenario tests because infrastructure behavior changed.
- Do not automatically fix test failures by changing design, changing IaC, or redeploying.

- A change with a different task type, target, or Goal is a new task.
- A request to save a chat-only design in the repository is a new `design` task; switch the active task before saving.
- Do not treat a task as complete if an Acceptance check for a Requirement ID or a task-type-specific check is unimplemented, unexecuted, or failing.

## Task boundary

- `design`: Update `docs/designs/**` and the corresponding `model/**`, then finish after local validation. Existing-resource retrieval may reflect only properties selected by the chatbot and necessary non-ARN current identifiers. Do not proceed to IaC, AWS mutation, or scenarios.
- `infrastructure`: Read the approved design; perform only the IaC specified by the active prompt, safety checks, authorized deploy/apply, and, after success, updates to the observed namespace in `model/**` and Markdown generation, then finish. The `update` phase permits the uncommitted intended design manually edited by the human in model properties before task start as immutable input; Codex must not change intended design or scenarios.
- `scenario-test`: Create/update only `tests/scenarios/**` and `tests/results/<scenario-id>/<environment>/<target-directory>/`. After test failure, do not proceed to design changes, IaC repair, redeploy, or remediation task creation/execution.
- `initialization`, `governance`, `catalog-maintenance`, `migration`: Execute only the active prompt's Allowed paths and explicit scope; do not proceed to another task.
- Do not automatically create or execute a scenario-test task even when infrastructure behavior changes.
- Only scenario-test tasks may change `tests/scenarios/**` and `tests/results/**`.
- Do not save non-scenario task validation/deployment results under `tests/results/**`. As a rule, verification output belongs only in the completion report.
- Place only independent contracts in `tasks/`; do not save task history or evidence. Task status is `running`, `suspend`, or `completed`. The current stop reason may be recorded in a suspended contract. Change only this contract to completed after the local loop succeeds. Retain suspended contracts for resume and ownership of uncommitted diffs; retain completed contracts only while retaining ownership of uncommitted diffs, and delete them when the diff disappears.
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
