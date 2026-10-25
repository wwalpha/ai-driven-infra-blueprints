# Task Contract Rules
Model correction does not require the old Model to be valid or unchanged. IMPORT Resources may be acquired repeatedly and updated or corrected. Safety is determined by Task change authority, necessary Human consent and the final Model integrity. AWS acquisition remains exclusive to `/import`; ordinary `/update` may correct only the Resources and fields explicitly requested by the Human, without AWS acquisition authority. Dedicated merge/delete/retarget and value-preserving operations retain their own raw-value preservation checks.


## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
replaces the design validation/completion rules below: source and display transactions
are separate, and issues runs only when explicitly requested. Other workflows retain these rules.


## Task transition

### Selection and publication

Humans select the worktree for concurrent tasks and IMPORT. Select a contract with
`BLUEPRINT_TASK_FILE` or `--task-file`; ordinary task status and declared scope apply.
Modified files describes planned work. Model publication retains its publication lock
and each service's rollback-protected output transaction.

Finish editing before running generation/validation; start the next edit only after
that command exits. While it runs, another LLM, sub-agent or command must not edit,
add or delete its inputs or generation destinations in the same worktree. The running
command's planned saves are permitted. Concurrent read-only investigation is allowed.
For parallel editing, use a separate worktree selected by the Human.

Ordinary generation prepares and validates all selected candidates in one stage and
compares the consumed input bytes, required file sets and selected contract once,
inside the publication lock before the first output save. On any input change, report
the paths and stop without saving any output or retrying automatically; preserve the
external edits. Even unchanged outputs require this comparison. This boundary and the
operating rule do not guarantee continuous detection of every concurrent edit.
IMPORT and other authority writers retain their dedicated publication checks and callbacks.

### Task registration

- Task typeはinitialization/design/infrastructure/scenario-test/governance/catalog-maintenance/migrationのみ。active promptが今回の変更契約であり永続設計正本ではない。
- 変更前にtasks/<task-name>.mdのtype/target/Goalを最新依頼と一致させ、新Taskの最初の変更として別契約を登録する。他契約/未commit変更は保持する。cleanかつ契約なしはidle。read-only調査/chat-only相談は登録不要。
- Task statusはrunning/suspend/completed。## Modified filesに自契約・新規file・生成物・parts・削除先を含む正確なfile pathを列挙し、Allowed paths内に制限する。glob/directory/他Task契約は禁止。
- task_contract.py --task-file tasks/<task-name>.md --source <repository外の契約候補file>で登録する。各processはBLUEPRINT_TASK_FILEまたは--task-fileで選択し、複数running時は明示必須。予定file変更前にModified files/Allowed pathsを更新し、同--task-fileでrefreshする。

### Common transitions

- Issues saves retain Scope checks and indivisible atomic publication/rollback. Saving ignores existing `iac-issues.state.json` without updating or deleting it.
- The explicit service-scoped, report-only issues `migration` described in [Snapshot and publication](issues-investigation.md#snapshot-and-publication) runs without a worktree. Identify it with `issues_save_only()`; do not collect or compare HEAD/commit, worktree, index or untracked changes for its validation/completion or attribute other Tasks' changes to it. Retain contract/scope/Acceptance, actual report destination Allowed paths, whole-target Snapshot/Review integrity and atomic publication/rollback. Human confirmations are read-only; only issues.md and iac-issues.md join the report transaction. Input changes during or after a scan do not stop execution or require rescan/review. Ordinary Tasks and worktree integration retain their Git and input safety rules.

- Generated views whose publication bytes are unchanged are excluded from publication. Retain candidate validation and the single all-target input comparison in Selection and publication; publish only the validated changed bytes.
- For isolated worktree Git integration only, explicit human approval of concrete validation failures may permit commit/rebase/merge/cleanup through `worktree_task.py finalize --human-approved-validation-failure "<approval and accepted failures>"`. Keep the task `suspend` and its current Suspension reason; do not use `--complete` or claim validation PASS. All requested work/inputs must otherwise be finished; scope errors, Git safety blocks, and AWS permission boundaries remain in force. See [worktree skill](../../.agents/skills/worktree/SKILL.md).
- Complete only after successful final validation under [Validation policy](loop-engineering.md#validation-policy) and all requested work is finished. Use `task_contract.py --task-file tasks/<task-name>.md --complete`; IMPORT completion retains its evidence check. Delete completed contracts when the diff disappears; do not retain task history or evidence.
- When stopping for a check error, set only this task's Task status to `suspend`, whether the cause is this task, another task, unregistered changes, or the baseline. `## Suspension reason` is mandatory and must name the failed check, target file, concrete error, and any necessary log path outside the repository. Retain only the current stop reason; do not add execution history or evidence. The local loop automatically suspends after all checks finish or child processes stop, including precheck failures. Do not infer which of multiple running tasks to suspend without an explicit selector. Staged validation status changes apply only within the snapshot.
- When stopping for a standalone check outside the local loop or an error during work, also suspend this contract with `task_contract.py --task-file tasks/<task-name>.md --suspend-reason '<具体的な問題>'`. Preserve other tasks' contracts and uncommitted changes; do not repair unrelated failures within this task.
- Reject generation, deploy, and loops while suspended. Resume explicitly with `task_contract.py --task-file tasks/<task-name>.md --resume` to return to running and clear the stop reason. The same command can refresh a running task.
- Read-only calls may explicitly select no contract; updates require a selected current contract.
- Do not create or execute another task after the loop succeeds.
- Do not change task type or work phase during retry.
- Do not proceed to scenario tests because infrastructure behavior changed.
- Do not automatically fix test failures by changing design, changing IaC, or redeploying.

- A change with a different task type, target, or Goal is a new task.
- A request to save a chat-only design in the repository is a new `design` task; switch the active task before saving.
- Do not treat a task as complete if an Acceptance check for a Requirement ID or a task-type-specific check is unimplemented, unexecuted, or failing.

## Task boundary

- [Service source authority](model-templates.md) applies to every Task type. Declare
  exact properties entrance/parts and generated Markdown/JSON paths before writing.
  Include changed environment/target/services and affected reference consumers in
  Validation scope. Read-only producer discovery never expands Allowed paths, Deployment
  scope or AWS permission. Validate final identities and references; only dedicated operations require preservation outside their declarations.
  Infrastructure observation writers patch only permitted observed.value in the same
  properties. Destroy cannot change desired/display/reference design. Infrastructure
  update keeps Human intended-design inputs immutable; retain generated-view equality
  and unambiguous deployment-target handoff checks.

- `design`: Edit explicit environment/service properties candidates and generate
  docs/designs through the shared guarded APIs, then finish after classified validation.
  AWS acquisition and acquired add/refresh/bind/replace remain exclusive to /import; explicit ordinary IMPORT corrections use the guarded Model edit API.
  Do not proceed to IaC, AWS mutation or scenarios.
- `infrastructure`: Read the approved design, perform only explicitly authorized IaC,
  checks and deploy/apply, then synchronize permitted observations/generated views after
  success. Independent destroy changes only explicit designed Stacks, post-success
  observations, corresponding generated Markdown/JSON and its Task. IaC, desired/display/
  reference design, scenarios and results must not change. Explicit /destroy scope
  authorizes that action without a second confirmation. Infrastructure update treats
  Human intended design as immutable input.

- `scenario-test`: Create/update only `tests/scenarios/**` and `tests/results/<scenario-id>/<environment>/<target-directory>/`. After test failure, do not proceed to design changes, IaC repair, redeploy, or remediation task creation/execution.
- `initialization`, `governance`, `catalog-maintenance`, `migration`: Execute only the active prompt's Allowed paths and explicit scope; do not proceed to another task.
- Do not automatically create or execute a scenario-test task even when infrastructure behavior changes.
- Only scenario-test tasks may change `tests/scenarios/**` and scenario results under `tests/results/**`.
- `/model-test` generation is an offline migration (framework implementation: governance), writing only `tests/<environment>/<target-directory>/<service>.py`. Human manual execution of these standalone read-only audits writes timestamped logs under `tests/results/<environment>/<target-directory>/<service>-YYYYMMDD-HHMMSS[-ffffff].log`; these are audit evidence, not scenario records. Environment directory names in results are reserved for audits. Generation and automated validation never execute AWS or save mock logs in the repository.
- Do not save non-scenario task validation/deployment results under `tests/results/**`. As a rule, verification output belongs only in the completion report.
- Place only independent contracts in `tasks/`; do not save task history or evidence. Task status is `running`, `suspend`, or `completed`. The current stop reason may be recorded in a suspended contract. Change only this contract to completed after the required final validation succeeds under [Validation policy](loop-engineering.md#validation-policy). Retain suspended contracts for resume; retain completed contracts only while their uncommitted diffs remain, and delete them when the diff disappears.
- Track earlier scenario evidence versions in Git history; do not add directories per execution or timestamp.

## Model-only IMPORT operation contract

The parent uses Task type design, Workflow update, Model operation import-merge or
import-delete, running status during editing, and forbidden AWS API execution/deploy/apply.
Within merge/delete, transfer/retarget/delete are internal leaves, not new Task types.
Standalone import-retarget follows its separate contract below.
Declare exact sources, generated views, permission paths, requirements and Validation scope.
Do not switch contracts between leaves. The parent alone controls status/completion.

For merge, use nonempty `## Model merge pairs` with JSON object lines containing exactly
source/destination complete environment/target/service/fixed-ID addresses. Sources and
destinations must be unique, disjoint and in one service scope; cycles/chains are rejected.
Optional `## Model reference changes` records contain consumer/field/source/destination,
plus property for value/document, and pointer only for document. parentReference has neither.
The consumer remains in the same environment/target, including explicit other services.
References must match a pair or D→D for a registered destination's derived reevaluation.
Use complete formal numbered Properties and non-root RFC 6901 scalar-leaf pointers.
Unknown/missing/duplicate keys, duplicate sections/positions, empty/malformed declarations,
NaN/Infinity and unconsumed section lines fail closed. Existence, typed
ownership and operation-position overlap are checked against raw before inputs at final
validation. Reference-target mismatch, semantic ambiguity and unused reference declarations
are warnings under [Reference diagnostics](model-information.md#reference-diagnostics). Ordinary Goal prose remains unrestricted.

Declare `## Model delete sources` with one exact address bullet per source. All sources
remain in the same environment/target; multiple services are permitted. No destination
resource or merge pairs are allowed. For example:

```md
## Model delete sources
- `stg/cde/vpc/001`
- `stg/cde/vpc/002`
- `stg/cde/cloudtrail/001`
```

For deletion, optional Model reference changes use the existing record syntax: source
must be a deleted producer, destination a retained same-target producer, and consumer a
retained same-target resource. Optional `Model refactor: value-preserving` plus existing
Model dependency detach records may coexist only with import-delete. Each detach must
name a deleted producer and a retained consumer. Register the exact relevant fields;
unrelated properties/resources, identities and observations remain immutable.
The normalized delete_sources, source_scopes and scopes are shared by authorization
and final checks; the normalized operation carries all delete_sources.
The LLM orders and executes one resource leaf at a time, inspecting each result.
One Parent Task = one Worktree = one transaction. Leaves may save unfinished raw sources,
but never generate final views, validate the parent, complete, commit, rebase, merge or
clean up. After every leaf succeeds the parent generates once, then explicitly invokes
finalize for the existing final-candidate validation and one merge/cleanup. Python only
provides atomic APIs and guards, never a resource execution scheduler.
Final resources per service must equal original resources minus declared deletions.
Every shared-template consumer is checked for preservation; raw repair Definitions may
be added/rebound only for registered consumers, retaining their fixed Resource/Row maps.
Reference-only diagnostics remain warnings; unrelated changes and malformed Models fail.
Incomplete source removals reject finalize before private commit preparation. A failed
leaf rolls back only its current save and retains earlier saves. Failed final validation
retains the parent and candidate without merge. Explicit same-parent resume/repair and
revalidation is allowed for deletion; preserve the prior candidate commit rather than
amending/discarding it. Failed-validation approval cannot bypass deletion final checks.
`task_contract.model_operation` returns immutable named MergePair,
ReferenceChange and ModelOperation data for every consumer of the contract.

Managed worktree intermediate saves enforce running Task/worktree ownership, revision,
raw registered paths, scope, syntax and input bytes/file sets without requiring expansion
or complete transfer/deletion. Each context is one-use; each leaf takes a new snapshot.
Final validation, independent completion and integration still prove the entire operation
against versioned before. Rebase integration uses latest base→candidate, not creation start.
The normal Model-only finalize accepts running/completed tasks, validates after private
commit/rebase, then completes only running tasks and merges the exact validated HEAD.
No persistent PASS receipt, public skip flag, automatic repair or workflow rollback exists.

## Standalone Model reference retarget

Explicit Human `/update` authorization may use a running design Task with
`Model operation: import-retarget`, forbidden AWS API execution and deploy/apply.
This independent operation has no merge pairs,
setting transfer, deletion, producer reevaluation or Subnet association changes.
Keep every producer/consumer service in Validation scope. Retain naming checks,
exact Modified files/Allowed paths and managed-worktree ownership.
It grants no permission to acquire/refresh/replace IMPORT values or to change IaC/AWS.
Do not disguise a retarget as a merge or combine it with value-preserving refactoring.

```markdown
## Task contract
- Task type: `design`
- Task status: `running`
- Workflow: `update`
- Model operation: `import-retarget`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`

## Model reference changes
- {"consumer":"stg/cde/vpc-endpoint/001","field":"value","property":"EC2.VPCEndpoint.RouteTableIds[1]","source":"stg/cde/vpc/009","destination":"stg/cde/vpc/022"}
- {"consumer":"stg/cde/vpc-endpoint/001","field":"value","property":"EC2.VPCEndpoint.RouteTableIds[2]","source":"stg/cde/vpc/010","destination":"stg/cde/vpc/023"}
```

Addresses include environment/target/service/fixed Resource ID; use numbered formal
Properties from `operation_rows` for repeated rows, never a bare ambiguous array name.
`field` is `value` or `document`. Document references require a non-root RFC 6901 scalar
leaf `pointer`; JSON array/object value containers may also supply `pointer` (zero-based
JSON array indexes). Complete scalar references only: no partial strings, containers,
wildcards, structural parentReference or rendered-literal substitutions. Unknown/missing
keys, duplicate/overlapping operation positions and invalid operation Resources/Properties
stop. Before-producer mismatch, reference type mismatch and unused semantic declarations
are warnings. Declared operation producers must be distinct existing IMPORT Resources
in the consumer's environment/target. Producers may
not also be edited consumers. CREATE consumers retain ordinary design validation.

Save all declared changes through a fresh one-use
`model.adapters.task.source_write_context` and model.prepare_edit/model.publish_edit.
Source and view publication are separate. Before retarget publication compare the
versioned full authority and candidate using fixed producers and saved occurrences.
Equal names, physical IDs or renderings never establish identity. Preserve undeclared
values/types/structure, fixed Resource/Row IDs, observations, JSON siblings/array order,
reference kind/format/Property/label policy and literal string affixes. Preserve refids,
part names/order/layout, file sets and project bytes. Only the declared occurrence may
change; context and other producers in the same leaf remain unchanged. No new expression
language, unbound selector or generic force/skip path is permitted.

Retain Task revision/ownership, complete input snapshot and file sets, publication lock,
final input comparison before save and per-write journal rollback. Any success/no-op/failure
consumes the context. Keep concurrent edits on conflict; do not retry automatically.
Generate required Markdown/JSON separately with existing generation APIs; direct edits of
generated views are forbidden. Generation does not prove operation completion.

Finalize the running parent using the existing Model-only composition: private commit,
rebase onto latest local base, one classified read-only final candidate validation of
base→candidate, completion and ff-only merge of that exact HEAD, then cleanup. The final
meaning check verifies authorized non-reference preservation and reports reference
mismatches/unused declarations as warnings; it requires
neither setting transfer nor source deletion. Independent complete also verifies meaning.
No failure-approval bypass, automatic regeneration, validation retry, repair or PASS receipt.
A failed candidate remains retained without merge. IT is governed by the active Human
scope; this operation does not introduce an IT completion requirement.

## Value-preserving Model refactor

An explicit dependency detach is a separate ordinary design Task, not a new Model
operation and never combined with import-merge/import-retarget. Deletion-related detach
may instead be registered in the same import-delete parent as specified above. Declare:

```markdown
## Task contract
- Task type: `design`
- Task status: `running`
- Workflow: `update`
- Model refactor: `value-preserving`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`

## Model dependency detach
- {"consumer":"stg/cde/service-b/002","producer":"stg/cde/service-a/001","key":"desired.row.002-001.value"}
```

Use exact fixed Resource addresses and expanded Model keys returned by the read-only
reference API. Optional `pointer` selects one JSON document scalar leaf (RFC 6901);
without it, the declaration covers that producer's usages at the entire key. Require
nonempty, unique, nonoverlapping declarations; reject unknown keys, malformed sections,
invalid JSON, mixed operations and unconsumed lines. All named Resources must exist.
Report missing-before, remaining-after and undeclared reference differences as warnings;
none makes the original Model operation incomplete. Non-reference changes remain prohibited.

Keep ordinary Modified files, Allowed paths, service Validation scope and naming. Include directly changed consumers and their required reference impact scope.
The guard compares all effective Resource/Property values and types, fixed Resource/Row
composition, resourceMode/type, anchors/Logical IDs, structural metadata,
observations and unchanged consumers across those targets/environments. CREATE
reference changes and structural metadata detach are not authorized by value equality.
Unresolved references report their cause as warnings. This declaration grants no AWS permission.

Save complete properties candidates through ordinary design
model.adapters.task.edit_write_context and the public prepare_edit/publish_edit API.
The shared IMPORT guard verifies before publication; failed comparisons never rewrite
inputs automatically. Related deletion repairs use their limited source context.
Generate views with existing
generation APIs. Keep the Task running and call worktree finalize, which reuses the
Model-only candidate composition: private commit, latest-base rebase, one read-only
final loop on base→candidate, completion and ff-only merge of that exact HEAD, cleanup.
No separate pre-finalize completion/final loop, PASS receipt or new integration engine.
Failure retains the candidate without merge; a failure-approval flag cannot bypass this
refactor's final verification. Ordinary design Tasks without this declaration retain
all existing behavior. Dependency repair/refactor completion is not a prerequisite for
a separately authorized deletion. No remaining Resource edit is permitted inside its deletion Task.


## Controlled deploy repair contract

CloudFormation deploy never edits authoritative templates, parameters or artifact sources. An explicitly authorized original contract may contain `- External IaC repair: ` with backtick value `allowed`, an absolute external `- Deploy repair session: `, and a positive `- Repair cycle budget: ` (default 20). `- Runtime recovery: ` separately authorizes the existing guarded AWS recovery. Parent Modified files/Allowed paths remain its own permitted observation/view outputs and contract.

The supervising LLM follows [External IaC repair handoff](../prompts/codex/04_deploy.md#external-iac-repair-handoff): preserve failures/operations, issue one durable attempt/request, checkpoint permitted parent changes, suspend it, create a distinct implement child from the pinned parent, validate and ff-only integrate, then explicitly resume only that request's original Task. The LLM records SAME/NEW/UNKNOWN with current/prior evidence; shared cause histories and reservations survive Task changes. Closing does not release unresolved overlapping workflows. Arbitrary Human-authorization text cannot extend the budget: without external verifiable approval the budget command stops WAITING_HUMAN. This is the sole preauthorized same-workflow transition; the general prohibition on automatically resuming other Tasks or starting unrelated phases remains. Child AWS API execution/mutation/deploy are forbidden; approved design is immutable. Exact child contract, validation dependencies, before/after bytes and commit order remain verifiable externally after cleanup. Parent validation attributes only those proved transitions and rejects unrecorded additions to the same files; never widen parent permissions or reset its start baseline. Human failure approval cannot issue a repair result.

## Acceptance contract

The active task's `## Required changes` must have unique Requirement IDs, with one or more checks mapped to each same ID in `## Acceptance checks`.

```md
- [R1] 実施内容
- [R1] `changed:path/to/file`
```

Only `changed:`, `exists:`, `absent:`, and validator-registered `check:` are permitted Acceptance checks. Reject arbitrary commands, unregistered checks, checks without a corresponding Requirement ID, and Requirement IDs without checks.

## Retry and stop

- Automatic correction for the same active task, task type, and logical failure class is limited to 3 iterations. The explicitly authorized external CloudFormation workflow retains its per-problem limit across Tasks and its separate approval-interval budget (default 20); distinct evidenced problems do not share a global three-failure stop. Static FAILs remain in the same child/attempt.
- Stop if the same error occurs twice consecutively without material progress.
- Do not fix missing human input by inventing values.
- Stop on out-of-scope file changes.
- Treat unapproved delete/replacement as waiting for human confirmation with an explanation, not as failure or automatic retry. If not approved, stop without executing deploy/apply.
- Stop if `framework/materials/aws/` differs from the baseline.
- Do not suppress failing checks to obtain a pass.

Human review that uniformly stops every deployment after validate/plan is not required. Plan-specific human confirmation for unapproved delete/replacement and Codex sandbox/OS permission control are separate mechanisms; operations requiring permission follow platform control regardless of repository rules.

## Reviewed governance recovery

After explicit Human authorization to repair a retained, verified governance task,
`worktree_task.py recover --task-id <id> --expected-commit <full-old-hash>
--expected-base <full-current-base-hash>` reopens its completed contract and prepares
only declared corrections. It pins both hashes and preserves a recovery receipt;
normal finalize is blocked until recovery finishes. A failed rebase is aborted.
If the base advances during recovery, explicitly resume any suspended contract and
review the clean candidate against the previous pinned base. Use `recover
--repin-recovery --expected-commit <full-current-candidate-hash> --expected-base
<full-latest-base-hash>` before rebasing again. This retains the previous receipt,
requires the existing linear commit count and declared paths, and accepts only a
descendant base. It never rebases, merges or grants validation PASS. The new receipt's
commit/base become the arguments for the subsequent `--finish-recovery`.
After reviewing conflicts, rebase manually onto that exact base, resolve and continue,
then run the same command with `--finish-recovery`. This accepts only a clean linear
candidate on the unchanged base, with the expected commit count and declared paths.
The verified recovery base becomes the Task validation baseline; retain the original
lifecycle start separately, excluding inherited base changes from this Task scope.
No hand-written lifecycle metadata is permitted. Recovery never merges or grants a
validation PASS. Run the required IT and Full checks, complete the contract, and use
normal finalize/cleanup. Model tasks and approved-validation-failure tasks are excluded.
