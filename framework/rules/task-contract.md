# Task Contract Rules
Model correction does not require the old Model to be valid or unchanged. IMPORT Resources may be acquired repeatedly and updated or corrected. Safety is determined by Task change authority, necessary Human consent and the final Model integrity. AWS acquisition remains exclusive to `/import`; ordinary `/update` may correct only the Resources and fields explicitly requested by the Human, without AWS acquisition authority. Dedicated merge/delete/retarget and value-preserving operations retain their own raw-value preservation checks.

## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
replaces the design validation/completion rules below: source and display transactions
are separate, and issues runs only when explicitly requested. Other workflows retain these rules.

## Task transition

Before choosing a prompt, read [Workflow selection](#workflow-selection).
For changes, also read [Selection and publication](#selection-and-publication),
[Task registration](#task-registration), [Common transitions](#common-transitions),
[Conditional transitions](#conditional-transitions), [Task boundary](#task-boundary)
and [Acceptance contract](#acceptance-contract), even when linked only here.
Read-only investigation/chat-only consultation needs no contract. Execute only the
selected workflow and active Human scope.

## Selection and publication

Humans select worktrees for concurrent tasks and IMPORT. Use the selected Task status, scope and Modified files.
Finish edits before generation/validation; resume only after it exits. No concurrent
input, contract or output edits in that worktree, except the command's planned saves.
Read-only review is allowed; parallel edits need a separate Human-selected worktree.

Use guarded publication APIs with the publication lock and per-service rollback.
For ordinary generation, the final all-target comparison must confirm unchanged consumed
inputs, required file sets and selected contract before any save, even for unchanged outputs. On change,
report paths, preserve external edits and stop all saves without automatic retry.
Publish only changed generated outputs. IMPORT/other authority writers retain their
own publication checks; this is no continuous concurrent-edit guarantee.

## Workflow selection

Select from the Human's request before loading a prompt. IaC-only work loads implement without reading `05_update.md`. Model design changes cannot be performed by implement. Retain update branches and one-shot repair/AWS boundaries.

| Request | Skill |
| --- | --- |
| Implement IaC from approved Model | implement |
| Correct IaC without changing Model, including Model/IaC mismatches on the IaC side | implement |
| Change Model design values | applicable update branch |
| Reflect an explicitly requested Model change into IaC and AWS | update infrastructure branch |
| Deploy only | deploy |
| Approved IaC repair after Deploy failure | implement through the existing repair handoff |

## Task registration

- Types: `initialization`, `design`, `infrastructure`, `scenario-test`, `governance`, `catalog-maintenance`, `migration`. The active prompt is the change contract, not permanent design authority.
- Register `tasks/<task-name>.md` as the first repository change with the requested type/target/Goal. Preserve other contracts and uncommitted changes; clean without a contract is idle.
- Status: `running`/`suspend`/`completed`. `## Modified files` lists exact paths within Allowed paths for this contract, new files, generated outputs, parts and deletions. No globs, directories or other Task contracts.
- Register with `task_contract.py --task-file tasks/<task-name>.md --source <external-contract-file>`. Select per process with `BLUEPRINT_TASK_FILE` or `--task-file`; selection is mandatory with multiple running Tasks. Before changing a necessary new path, update Modified files/Allowed paths and refresh with the same selector.

## Common transitions

- Finish requested work, successful final validation under [Validation policy](loop-engineering.md#validation-policy), all Requirement ID Acceptance checks and workflow completion conditions before `task_contract.py --task-file tasks/<task-name>.md --complete`. IMPORT retains its evidence check; contract retention follows Task boundary.
- On a stopping check error, suspend only the explicitly selected Task, regardless of cause/ownership. `## Suspension reason` must name the check, file, concrete error and necessary external log path; keep only the current reason. The loop suspends after all checks finish or children stop, including precheck failures. Staged status changes apply only to the snapshot.
- Outside the loop, suspend unresolved stopping errors with `task_contract.py --task-file tasks/<task-name>.md --suspend-reason '<concrete problem>'`. Preserve other contracts/changes; do not repair unrelated failures. Safely resolved operation errors may continue under [Self recovery](#self-recovery).
- While suspended, do not run generation, deploy or loops. `task_contract.py --task-file tasks/<task-name>.md --resume` performs read-only Scope preflight; success sets running/clears the reason, failure retains status/reason. Autonomous resume requires [Self recovery](#self-recovery); other Human approval boundaries remain. It also refreshes a running Task.
- Read-only calls may select no contract; updates need a selected current contract. Different type/target/Goal means a new Task; saving a chat-only design needs a new `design` Task before writing.
- Do not change type/phase during retry, start another Task after success, automatically proceed to scenarios after infrastructure changes, or repair failed tests by changing design/IaC or redeploying. Follow [Retry and stop](#retry-and-stop).

## Conditional transitions

Before operating, read applicable rows in addition to Common transitions.
If applicability is unknown, read the section before omitting it.

| Condition | Required read |
| --- | --- |
| Any Issues report save | [Issues report publication](#issues-report-publication) |
| Independent Deploy or CloudFormation completion | [Deploy task transitions](#deploy-task-transitions) |
| Framework-only governance/catalog-maintenance/migration with `framework` Validation scope | [Framework final candidates](#framework-final-candidates) |
| Human-approved concrete validation failures for isolated Git integration | [Human-approved validation failures](#human-approved-validation-failures) |
| IMPORT acquisition/publication/completion | [Dedicated import boundary](#dedicated-import-boundary) |
| Operation/check failure, retry or resume | [Self recovery](#self-recovery) and [Retry and stop](#retry-and-stop) |

## Issues report publication

Retain Scope checks, atomic publication/rollback and read-only Human confirmations.
Save only issues.md/iac-issues.md; ignore `iac-issues.state.json` without updating or deleting it.

Service-scoped report-only issues `migration` follows [Snapshot and publication](issues-investigation.md#snapshot-and-publication)
without a worktree. Do not collect/compare HEAD, commits, worktree, index or untracked
changes for validation/completion or attribute other Tasks' changes to it. Retain
contract/scope/Acceptance, report destination Allowed paths and whole-target Snapshot/Review integrity.
Input changes during/after scanning require no stop, rescan or renewed review.
Ordinary Tasks/worktree integration retain Git/input safety rules.

## Deploy task transitions

Independent `/deploy` uses `worktree_task.py deploy-start`, without extra Human `/worktree`;
follow [Managed Deploy snapshot and Git publication](cloudformation.md#managed-deploy-snapshot-and-git-publication).
CloudFormation completion concerns the current Snapshot: preserve AWS FAIL; validate
Model/reference/scope/View and the latest-base candidate; include completed in its publication.
No additional Human failure approval or force is required. Active/uncertain AWS requests retain tracking.
Other Task baseline/integration/completion rules remain.

## Framework final candidates

For Framework-only governance/catalog-maintenance/migration with `framework` Validation scope,
finish edits, required dependency-selected UTs, necessary IT and static checks under
[Validation policy](loop-engineering.md#validation-policy), then invoke finalize while running.
[Complete and integrate](../../.agents/skills/worktree/SKILL.md#complete-and-integrate) owns latest-base
candidate validation/completion and exact-HEAD ff-only integration; no Consumer service tuple
is required. Other Task types/approved suspended failures keep their completion order.

## Explicit PR integration

Only a Human request for a PR selects Worktree `finalize --create-pr`; append `--draft`
for initial Draft publication. Local FF Merge → automatic Cleanup remains the default.
Existing completion, validation, scope and failure-approval checks apply before initial
publication. The verified candidate is published without local-base merge or cleanup;
`integrationMode: "pr"` and publication intent retain candidate/base/Task/repository identity,
PR number/URL, GitHub state and separate Draft state. Retry the same operation and saved
intent; plain finalize never falls back to merge or implicitly changes Draft status.

The same Task/Worktree may explicitly `pr-update`: validate a new descendant candidate,
retain old published HEAD/new candidate in the update intent, and use ordinary FF Push
only when the remote HEAD equals the expected old HEAD. No force Push, published-history
rebase, new PR or cleanup follows Push. Remote drift or an unconfirmed creation without a
matching PR requires review; do not discard intents or edit lifecycle JSON to recover.
`pr-ready`/`pr-draft`, `pr-merge`, `pr-status` and `pr-close` are independent explicit tools.
Confirmed GitHub merge (including squash/rebase) triggers guarded automatic Cleanup through
merge/status, using PR identity and GitHub result rather than original-commit ancestry.
Failed/unknown merges retain state. Close retains the Worktree and remote branch; after
Cleanup a PR number/URL may be supplied to `pr-close --pr`.

Explicit `cleanup --task-id` discards the owned local Worktree, registration, branch and
management state regardless of merge, PR or Task status and dirty/uncommitted/ignored files.
Ownership, symlink and competing-operation locks remain mandatory. State survives partial
physical removal for retry. Unfinished Import/Deploy/Repair evidence is retained/reported,
not falsely finalized or made a prerequisite for physical removal. Automatic post-merge
cleanup retains its cleanliness and owned-evidence finalization checks. Cleanup never
changes PRs, remote branches, other Tasks, shared Python or AWS. `branches` provides read-only
associations/orphan discovery; `branch-delete --branch` removes only an explicitly named
orphan `codex/worktree/*` local branch without Task state or any Worktree registration.

Deploy and repair-child PR publication remain separate and reject PR mode before their
existing operations. See [Worktree PR publication](../../.agents/skills/worktree/SKILL.md#explicit-pr-publication).

## Human-approved validation failures

Only explicit Human approval of concrete failures permits isolated Git integration with
`worktree_task.py finalize --human-approved-validation-failure "<approval and accepted failures>"`.
Keep `suspend` and its current Suspension reason; do not use `--complete` or claim validation PASS.
All requested work/inputs must otherwise be finished. Scope errors,
Git safety blocks and AWS permission boundaries still stop integration.
Follow [Complete and integrate](../../.agents/skills/worktree/SKILL.md#complete-and-integrate).

## Task boundary

- [Service source authority](model-templates.md) applies to every Task type. Declare
  exact properties entrance/parts and generated Markdown/JSON paths before writing.
  Include changed environment/target/services and actually changed generated Consumer
  outputs in Validation scope. Read-only reference dependencies do not require whole-service
  quality validation or write authority. Read-only producer discovery never expands Allowed paths, Deployment
  scope or AWS permission. Validate final identities and references; only dedicated operations require preservation outside their declarations.
  Infrastructure observation writers patch only permitted observed Row values in the same
  properties. Destroy cannot change desired/display/reference design. Infrastructure
  update keeps Human intended-design inputs immutable; retain generated-view equality
  and unambiguous deployment-target handoff checks.

- `design`: Edit explicit environment/service properties candidates and generate
  docs/designs through the shared guarded APIs, then finish after classified validation.
  AWS acquisition and acquired add/refresh/bind/replace remain exclusive to /import; explicit ordinary IMPORT corrections use the guarded Model edit API.
  Do not proceed to IaC, AWS mutation or scenarios.
- `infrastructure`: Read the approved design, perform only explicitly authorized IaC,
  checks and deploy/apply. CloudFormation Deploy synchronizes current permitted observations/generated views regardless of attempt success; other phases retain their success rules. Independent destroy changes only explicit designed Stacks, post-success
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
model-delete, running status during editing, and forbidden AWS API execution/deploy/apply.
Only the canonical operation names import-merge, model-delete, and import-retarget are accepted; unsupported names are rejected.
Deletion permits explicit CREATE, implicit CREATE, and IMPORT Resources; it does not
authorize AWS deletion, deploy, apply, or IaC changes. Merge sources remain IMPORT.
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
Model dependency detach records may coexist only with model-delete. Each detach must
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
`task_contract_core.model_operation` returns an immutable `ModelOperation` or
`None` when no operation is declared. Its pairs and references contain immutable
`MergePair` and `ReferenceChange` values, respectively.

Python consumers import contract parsing, shared data types, and the `start` and
`suspend` transitions from `task_contract_core`, and validation-backed Task transitions
such as `refresh`, `resume`, and `complete` from `task_contract_runtime`;
`task_contract.py` remains the Task transition CLI. Validation consumers import
from `validation.runner` or `validation.loop` rather than their CLI wrappers.
Import acquisition and receipt operations belong to `model.importing.evidence`,
resource configuration to `model.configuration.resource_configuration`, and
source write authority to `model.adapters.task.source_write_context`.

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
may instead be registered in the same model-delete parent as specified above. Declare:

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

CloudFormation deploy never edits authoritative templates, parameters or artifact sources. An explicitly authorized current contract may contain `- External IaC repair: ` with backtick value `allowed`. `- Runtime recovery: ` independently authorizes guarded AWS recovery. No Deploy repair session or cumulative repair budget is required. Parent Allowed paths remain its permitted observations/generated views and contract.

The supervising LLM follows [External IaC repair handoff](../prompts/codex/04_deploy.md#external-iac-repair-handoff): analyze current failure evidence, settle unknown operations/publication, issue one pinned request/checkpoint, suspend the parent, create/validate a separate implement child and ff-only integrate exact permitted IaC transitions. Child AWS APIs/mutation/deploy are forbidden. Current Task and one-shot commit/byte evidence replace Workflow Ledger attribution; other Task authority checks remain mandatory. Keep at most 3 static cycles within that child. Discard temporary evidence after integration and active Task attribution after completion; no historical attempts or approvals survive to the next Deploy. Explicit parent resumption starts an independent new run with current IaC and fresh ChangeSet approval. Do not automatically chain unlimited new Deploy invocations.

## Acceptance contract

The active task's `## Required changes` must have unique Requirement IDs, with one or more checks mapped to each same ID in `## Acceptance checks`.

```md
- [R1] 実施内容
- [R1] `changed:path/to/file`
```

Only `changed:`, `exists:`, `absent:`, and validator-registered `check:` are permitted Acceptance checks. Reject arbitrary commands, unregistered checks, checks without a corresponding Requirement ID, and Requirement IDs without checks.

## Self recovery

When an operation error is the LLM's own and can be safely resolved within the
current Task authority, identify the operation and inspect the Git diff, index and
Task baseline before correcting it. Restore only the LLM's own erroneous changes,
including unnecessary files; never discard Human or other Task changes. Correct this
Task's contract omissions or mistakes. Before editing a necessary file, establish that
it is justified by the current Goal and authority, then register its exact path in
Modified files and Allowed paths. Do not expand authority merely to make a check pass.
Validate the contract and actual change scope after repair. If resolved, continue the
same Task with its existing validation and Acceptance checks.

The local loop still suspends on failure. If already suspended, inspect the recorded
reason and current state. Restore the erroneous changes and register each necessary
file in Modified files and Allowed paths only when justified by the unchanged Task Goal.
Run `task_contract.py --task-file tasks/<task-name>.md --check-resume-scope` for a
read-only contract and Git Scope preflight while still suspended. It uses the normal
Task baseline and scope exceptions, including staged, unstaged and untracked changes;
it does not perform overall quality validation or AWS operations. Ordinary Validator,
generation, deploy and loops remain forbidden while suspended. Only when the preflight
passes, all stopping causes were the LLM's own safely repairable operation errors and
are resolved, and no other blocking condition remains, the LLM may use the existing
`--resume` without Human instruction. Resume repeats the preflight and leaves the
existing status and Suspension reason unchanged if it fails. After resume rerun the
failed checks before completion, then perform the required final validation and
Acceptance checks. Keep the same Task type, Goal and target and do not bypass Retry
limits. A Human approval requirement, AWS or other safety boundary, unresolved check,
unknown ownership or original content, conflict with another Task or Human change, or
work beyond the current authority prevents autonomous resumption. Do not infer approval
from recovery or from a valid contract. No recovery history or approval ledger is recorded.

For a fixed managed CloudFormation Deploy, use
`task_contract.py --task-file tasks/<task-name>.md --correct-deploy-contract <external-candidate.md>`
while suspended to add proven missing owner services to Validation scope and omitted
exact Modified files/Allowed paths. Preserve existing Validation entries. First compare the original
Human request and the actual fixed contract text; the LLM must establish that each added
file was necessary to the original requested observation/generation, not new work. The CLI
checks exact additions against fixed Execution scope, saved execution inputs, existing
service Models and generated artifacts. Same-target non-owner consumers additionally
require retained typed reference evidence and explicit Human consent, recorded with
`--approve-deferred-consumer <environment/target-directory/service>` on this operation.
Other Target consumers cannot be added. Consumer authority permits only proven reference
Rows and necessary Views, never arbitrary observations or Desired changes.
It preserves all other contract content, including type/phase, Goal, environment/Account,
Stack/Resource Execution scope, Requirements/Acceptance, AWS permissions and delete/replacement consent. It does
not approve a request or infer Human consent from matching hashes. Other declaration edits
are outside this narrow correction path.

The fixed text is retained in the existing managed lifecycle at bind. Older Tasks require
matching text already available at their recorded Git tip/start; missing or inconsistent
original evidence stops without guessing. The candidate is outside the repository and must
retain the current suspended status/reason. A live contract already containing only those
same additions is also accepted. See [Deploy correction conditions](cloudformation.md#managed-deploy-contract-correction)
for progress, locks and interruption handling. Success keeps the Task suspended, retains
execution evidence and verified pending save candidates, and requires Snapshot validation
again. Missing fixed Resource evidence on legacy Tasks, unknown manifests, active requests
and unresolved Git/failure evidence stop without erasing progress. Then use the ordinary
`--check-resume-scope` and, only under Self recovery above, `--resume`; rerun failed checks,
final validation and Acceptance. Correction never runs AWS, clears progress or completes a Task.

## Retry and stop

- Automatic correction for the same active task, task type, and logical failure class is limited to 3 iterations. The explicitly authorized one-shot CloudFormation Implement handoff keeps static FAILs in the same child, limited to 3 static cycles. No repair count or SAME/NEW history carries across Deploy runs.
- Stop if the same error occurs twice consecutively without material progress.
- Do not fix missing human input by inventing values.
- Stop on unresolved out-of-scope file changes. An LLM-owned operation error may be repaired first under Self recovery; preserve other changes, verify scope while suspended, and do not resume or proceed while a scope violation remains.
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
normal finalize/cleanup. Model tasks are excluded. A governance task with a recorded
Human validation-failure approval may use this recovery only after Human review of the
concrete conflict resolution. Start from its clean verified commit; preserve the exact
suspended contract, reason and approval throughout recovery and re-pinning. The receipt
checks those bytes and approval, scope, base and history before registering the candidate.
The accepted failures remain FAIL; recovery grants no Validation PASS or completion.
After the reviewed resolution, use the recorded approval for normal finalize/cleanup.
Any further change beyond the reviewed resolution requires renewed Human review and approval.

## Reviewed rewritten base recovery

For an explicitly authorized fresh, uncommitted running governance Task whose base
history was rewritten, first review the full old tip and current base diff and the
Task candidate. From the checkout containing the reviewed helper run
`worktree_task.py rewrite-base --task-id <id> --expected-commit <full-old-tip>
--expected-base <full-current-base>`. It only accepts declared, unstaged changes to
existing regular tracked files with no overlap with the base diff. It preserves their
bytes in external backups, records an intent before moving the branch, restores the
candidate, and records the new validation base. It refuses PR and Deploy Tasks,
commits, unregistered changes, overlap and changed inputs. An interrupted intent may
be retried with the same hashes only while the base, contract, index, candidate and
backup still match; otherwise retain everything for review. It never grants validation
PASS or completes the Task. Run all required checks again against the recovered base,
then use ordinary finalize. Never hand-edit lifecycle metadata or discard a backup.

## Task Acceptance exclusions

Investigate every FAIL against Goal, Required changes, Allowed paths, concrete Model
differences, the baseline, producer/consumer references and regression risk. Classify
required corrections, new failures and broken reference contracts as repair-required:
fix and revalidate to PASS. When unrelated pre-existing Model failure is evidenced,
the LLM may propose an out-of-task candidate. Unproven relevance remains blocking.
File paths and fixed scopes alone never establish the LLM judgment.

Present each candidate to the Human with diagnostic ID, Model, Check ID, concrete
reason, LLM rationale, before/after and producer/consumer evidence, impact and choices:
approve exclusion for this Task only, include in repair scope, or hold. Do not interpret
“continue” or “implement” as approval. Partial approval leaves every other FAIL blocking.

Use the existing Task contract and transition CLI; do not create a parallel approval
store. `validation.acceptance.unchanged_model_evidence(task, failure)` checks baseline
source/context and reference dependencies, while `candidate(task, dependencies)` binds
exact Task text, candidate bytes, baseline and dependencies. These eligibility guards
are conservative: changed Models, affected contracts, changed dependencies, Framework
regressions, processing failures and incomplete mandatory checks cannot be excluded.
They never replace the LLM investigation or Human decision.

After explicit Human decision, prepare an external JSON list and execute
`task_contract.py --task-file tasks/<id>.md --approve-out-of-task-failures <external.json>`.
Each record contains task, diagnostic_id, reason, check_id, source_path, scope,
dependencies and candidate; assessment contains task_relevance, before_after,
producer_consumer, regression, why_outside_task and risk with concrete evidence.
human_approval contains decision=exclude_this_task_only, the exact diagnostic_id and
reason, and the Human statement naming that diagnostic ID. Generic permission is
insufficient. The CLI saves the current decisions under `## Out-of-task FAIL approvals`;
this is live acceptance authority, not Task history. It preserves other decisions and
suspension; approval itself neither resumes nor completes a Task.

At completion and before/after rebase, compare current raw failures, Task identity,
reasons, candidate differences and dependency evidence with each approval. Changed
cause, target, scope, diff or dependencies requires renewed LLM evaluation and Human
approval. Approval applies only to this Task and only to Acceptance; never rewrite
Model, generated Views, Issues or diagnostic FAILs as PASS or warning. Necessary
Change Validation, affected references, Git/scope/permission/publication and destructive
change safeguards remain mandatory. A Task can have Acceptance PASS while raw
Validation remains FAIL; reports must state both and list accepted and unapproved FAILs.

`--human-approved-validation-failure` retains its different meaning: explicitly
approved Git integration of a suspended, failed Task. It does not complete the Task or
serve as an Acceptance exclusion, and cannot bypass required Model corrections.
