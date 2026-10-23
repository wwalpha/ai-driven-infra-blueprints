# Infrastructure Deployment Prompt

## Normal startup

Human指定のenvironment/alias、resource/execution account、Region/profile、StackNameとservice IDsを確定する。未確定ならenvironment→複数target時のalias→account→scopeの順に一問ずつ確認し、同じproject.json targetの候補だけ示す。唯一targetにaliasを要求しない。configured awsProfileを使い、未設定時のみ明示profile/default chainを使う。不一致・認証失敗で別credentialへ切り替えない。

Read before changing filesの必須本文と対象入力、Task候補を漏れなく読む。hash一致を未読範囲の読了証明にしない。生成物の存在・内容hash・scope・変更検知・機械検証を維持し、generated viewへのfallbackや値の推測をしない。設計変更・scenario実行は禁止。

固定したworktree Python/PATH/PYTHONPATHで、明示serviceと全Stackを一度に準備する。load_units()が既存のStack Model/generated Stack view一致を確認する。

```console
<fixed-python> framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --service <service-id> [--service <service-id> ...] --task-file tasks/<task-name>.md [--profile <profile>] [--sequential] [--allow-external-repair] [--repair-budget 20]
```

aliasなしは--aws-account-id。preparation.jsonのdocuments（<=6,000文字/chunk）、対象要約、契約候補を漏れなく確認する。確認済みの同一範囲だけ再読込を省略できる。inputs/generatedViewsのhashは読了やPASS証明ではない。欠損・不一致では停止する。Do not newly reregister already registered tasks. 新Taskは次の登録を最初の変更とし、runtime/hash/Task競合/最新Issuesを再確認する。

```console
<fixed-python> framework/scripts/deploy_preparation.py --register <external-preparation.json>
<fixed-python> framework/scripts/deploy_preparation.py --run-controller <external-preparation.json>
```

全Stackに一つのcontroller/sessionを使う。preparationはAWSなし。controllerが認証、Task/Issue/入力guard、既存Stack所有権、配送barrier、ValidateTemplate、ChangeSet、承認・実行・poll・drain・成功後同期を担当する。同じpreflight/APIをAgent側で重複実行しない。通常起動/Create/ExecuteはRemoveを含め全体mapping/lintなし。失敗修復/bootstrap/未同期SUCCESSだけ必要ownerと参照を解決する。DeployOrder/並行数を保ち、失敗時は新規開始を止めpeerをdrainする。SUCCESSは再実行しない。

## Read before changing files

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. `tasks/<task-name>.md` if present. Otherwise treat as idle and create it first under Create active task contract.
4. `project.json`
5. Runtime `model/<environment>/<target-directory>/<service-id>.properties` selectors and their source inputs for services owned/referenced by deployment scope, and referenced models needed for reference resolution
6. For CloudFormation, same-target `cloudformation-stacks.properties`. Delegate StackName mappings/generated stack Markdown matching to existing controller `load_units()`; AI must not manually compare the same values twice
7. [Policy account selection](../../rules/detailed-design.md#policy-account-selection). For CloudFormation, add [CloudFormation stack detailed design](../../rules/detailed-design.md#cloudformation-stack-detailed-design); add related display sections only when changing/investigating design display.
8. [Model authority](../../rules/model-information.md#model-authority), [Resource management mode](../../rules/model-information.md#resource-management-mode), [Properties format](../../rules/model-information.md#properties-format). For generation, add [Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation); for CloudFormation, add [CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy).
9. [cloudformation](../../rules/cloudformation.md) or [terraform](../../rules/terraform.md) for the selected engine
10. [observed-values](../../rules/observed-values.md)
11. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope). [Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)
12. Target IaC files, stack-specific parameters, and declared execution inputs

- [project-configuration](../../rules/project-configuration.md) and [issue-gate](../../rules/issue-gate.md).

Read mandatory documents per file/specified section. If tool output limits are exceeded, split the same file by line ranges or 6,000-character chunks described below, reviewing the specified range without omissions. Do not concatenate multiple large files into one output. Only necessary ranges actually reviewed during the same preparation need not be reread if content hashes match. Do not treat unread sections as reviewed merely from matching hashes. On changes/additions/deletions, review changes and necessary input ranges and prepare again. Do not require full rereads due to generated artifact changes.

At preparation start, fix the Python launcher to one existing available environment; use the same absolute path and PATH/PYTHONPATH for subsequent preparation, contract registration, controllers, and local loops. List missing dependencies together and resolve in the same environment; do not try different Pythons sequentially or duplicate authentication checks. Do not save credential values in logs.

Ordinary deploy AI design inputs are authoritative model properties. Obtain design values from `desired.row.*`, JSON bodies from `desired.row.*.document`, resource identity/references from existing metadata such as `desired.resource.*`, current non-ARN identifiers from `observed.*`, and stack settings from `cloudformation-stacks.properties`. Exclude generated service Markdown, `cloudformation-stacks.md`, service-owned generated JSON, and built ZIPs from ordinary body inputs.

Markdown Resource links are internal Model addresses. Resolve them through the common scope-checked resolver and read only necessary producer groups; use the producer Model saved anchor as selector; never use generated Markdown as authority. No generated Markdown fallback is permitted.

Retain generated artifact existence verification, hash monitoring, machine generated artifact validation, and stop conditions. Only for explicit display defect/mismatch investigation, necessary artifact portions may be read. Classify model/generated artifact/IaC mismatches and deployment failures under [Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair). The supervising LLM handles proven IaC defects through the separate implement handoff below. The same controller handles authorized RUNTIME_BOOTSTRAP without repository changes. Secrets Manager initial-value bootstrap classification, CREATE ownership/account/region/schema/value checks, intent/token persistence, AWS mutation and failed-stack retry belong exclusively to the controller; do not manually run put-secret-value.

`<target-directory>` is the selected target's alias if present, otherwise AWS account ID.

Follow AGENTS.md “How to read required rules” for specified section read ranges and conditional rules.

### Conditional rule readings

Add [Framework regression](../../rules/loop-engineering.md#framework-regression) for framework changes, [Validation cache](../../rules/loop-engineering.md#validation-cache) for validation reuse, and applicable loop diagnostic sections for stops/long execution. Do not additionally read full README or inapplicable sections; retain schema/reference/account/issue/task-specific checks.


## Confirm unapproved delete/replacement

If only unapproved delete/replacement is detected, do not treat it as deployment failure/task completion; wait for human confirmation in the same task. Do not uniformly hold all deployment for confirmation.

In the following order, display explanations humans can decide from, not just technical summaries.

1. Detected changes: Show stack names or Terraform roots/workspaces and add, change, delete/destroy, and replacement counts.
2. Direct stop reason: Show which delete/replacement does not match preapproval.
3. Target resources: For CloudFormation, show logical IDs, physical IDs, resource types, Remove/Replace, `Replacement`, `PolicyAction`, `DeletionPolicy` / `UpdateReplacePolicy`, and known change reasons. For Terraform, show resource addresses, resource types, destroy/replacement actions, and known change reasons without sensitive values.
4. Execution impacts: Explain known impacts on physical resources, stored data, settings, access, and availability plainly. Do not guess; explicitly mark unconfirmed impacts as `未確認`.
5. Current execution state: Explicitly state that target change sets/saved plans are unexecuted; distinguish other successful, failed, or unexecuted units in the same task, accurately stating whether AWS resources changed.
6. Available responses: Present options to approve all targets and continue the same deployment, perform additional read-only confirmation needed for decisions, decline and stop execution, or change IaC in a separate task for resource retention/releasing management. Do not imply that only part of the current change set/plan can be executed.
7. Human confirmation question: In one question, ask whether to approve all listed delete/replacement in the same change set/saved plan for the stated reasons.

If the human requests more information, execute only list/get/describe-equivalent read-only operations within the same task's deployment scope to supplement explanations, then present the same question again. Do not delete data, change resources, or repair IaC.

If the human approves all targets/reasons, update Authorized delete/replacement in `tasks/<task-name>.md` to approved resources, actions, and reasons, confirm the following, and resume the same task.

- For CloudFormation, retrieve the same change set ID again and execute only if status is `CREATE_COMPLETE`, execution status is `AVAILABLE`, and approved logical IDs, actions, replacements, and `PolicyAction` match.
- For Terraform, reconfirm the same saved plan and apply that plan binary only if approved resource addresses, resource types, and actions match.
- If change sets/plans expired, were recreated, or changed, do not use previous approval; explain new contents and reconfirm.

If the human does not approve or approves only a subset, stop without executing change sets/plans. Even if resource retention, removal from CloudFormation management, or configuration changes are needed, do not change IaC/intended design in this deploy phase.

CloudFormation failure stops new starts, drains accepted peers and synchronizes successful observations. The LLM investigates the preserved failure set and uses the external handoff below only when explicitly authorized. Keep runtime recovery independent. Approval waits resume the saved ChangeSet; auth/read/guard/unknown-submission/observed errors are never converted automatically to IaC repair. Terraform failures retain their existing stop and partial-state investigation rules.

## Resume

Resume the existing Task/session with --resume and only Human-approved --approve-change-set IDs. Preserve original intent/token, ChangeSet/approval and input evidence. Reacquire boundary AWS data; historical static validation metadata is never execution permission. Unsafe migration stops with its reason, retaining SUCCESS and unsynchronized work. Do not replace a session or rerun successful Stacks merely because modules/transport changed. External changes require --resume --repair-result, signed child validation/integration evidence, unchanged intended Model/scope/execution definitions and the original workflow ledger.

For v3/definition migration, use the explicit procedure in [Controller sessions](../../rules/cloudformation.md#controller-sessions-and-execution-timing). --resume --observe-only observes/drains existing identities without mutation, Model publication or accepting new execution definitions.

## External IaC repair handoff

This CloudFormation-only workflow requires the original Human-authorized contract
`External IaC repair: allowed`, an absolute external `Deploy repair session`, and
separate `Runtime recovery: allowed` when runtime recovery is authorized. Preparation
adds the external-loop permission only with `--allow-external-repair`; the optional
`--repair-budget N` sets the initial positive cycle budget (default 20 per approval
interval, a safety bound rather than a measured optimum). Parent Modified files and
Allowed paths contain its contract and authorized observed/generated outputs; never
add templates, parameters or artifact sources for repair.

After STOPPED, the supervising LLM investigates the saved `failureObservations` and
exact approved Model/input locations. No Python deploy process starts an LLM or
implement. Keep execution status independent of cause: safe terminal failed executions
and proven unexecuted IaC failures can be diagnosed; approval waits resume the same
ChangeSet without a repair attempt. Authentication/authorization, guards, reads,
unknown submission, observed publication, deficient design and scope expansion need
their own investigation/Human decision. BLOCKED alone grants no repair authority.

Write non-secret external diagnosis JSON with `revision` and `problems`. The LLM
compares AWS events/execution state, exact input IaC, approved Model, and all retained
diagnoses/repairs. Each entry requires `relation: SAME | NEW | UNKNOWN`,
`relatedProblemIds`, a concrete `reason` (at least 32 characters, explaining observed
facts and the causal comparison rather than boilerplate), and `evidenceRefs` containing
`{observationId, revision, eventIndices}` for the current and related historical failures.
These reuse saved observations; `inputRefs`/`modelRefs`/optional `constraintRefs` below
pin the corresponding source revisions. Do not put raw secrets or AWS prose in JSON.

SAME names existing IDs for one common cause and reuses that cause's attempts, even
across Resources. NEW compares all retained prior IDs (conservatively including other
Resources), explains the specific difference and cites corresponding observations.
Examples: another Property with a newly observed Property failure, or the same Property
with a different observed constraint code, may support the LLM's NEW analysis. They do
not prove a new cause by themselves. The same IAM permission deficiency across Resources
can be SAME; identical error codes can still hide distinct constraints. After correcting A,
explain whether B became observable and why it differs. Python never makes these causal
judgments. It only rejects absent/inconsistent evidence and unsafe repeated observations.

For SAME/NEW also supply `observationId`, `eventIndices`, `resourcePath`, formal
`resourceType`, `operation`, `property`, confirmed `constraint`, `cause`, `inputRefs`
and `modelRefs`. Input references identify exact `path`, `sha256`, and JSON `pointer`
(empty for a whole unparseable input/artifact); Model references identify exact `path`,
`sha256`, and authoritative `key` belonging to the failed resource. Supported causes
remain IAC_PROPERTY, IAC_SYNTAX, IAC_PARAMETER, IAC_ARTIFACT and IAC_PERMISSION.
IAC_PROPERTY must reference its claimed template Property and approved Model row.
Optional provider `constraintRefs` identify path/hash/pointer and matching ResourceType.
Cover the entire failure set, including rollback/delete peers.

UNKNOWN is a valid saved diagnosis. Omit unproved cause/constraint/property fields;
never fill them with dummy strings. Cite known observations and available source locations,
perform additional authorized read-only investigation, and defer to Human if unprovable.
No repair request is allowed while any failure is UNKNOWN or insufficiently distinguished.
A changed label, invalid value, schema pointer, Task, RequestId, time or hash never buys a
new cause/attempt. NEW with an already known structured target/operation/code/Property
observation stays NEEDS_DIAGNOSIS even if a different schema pointer exists. If genuine
causes cannot be distinguished structurally, stop for Human; do not invent evidence or
relabel the problem. SAME also cannot transfer known observations to another cause.
Reference existence/revision and structural differences are mechanical safety conditions,
never Python confirmation that the semantic diagnosis is correct.

The LLM runs these commands explicitly from the original managed Worktree, using its
registered Python for task commands and the ordinary launcher for lifecycle commands:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_handoff.py diagnose --state <session.json> --diagnosis <external-diagnosis.json>
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_handoff.py request --state <session.json> --problem <problemId> [--problem <problemId>] --path <exact-IaC-path> [--path <exact-IaC-path>] --expectation <external-expectation.json>
python3 -B framework/scripts/worktree_task.py repair-checkpoint --task-id <original-task-id> --state <session.json>
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<original-task-id>.md --suspend-reason "authorized implement repair request <requestId>"
python3 -B framework/scripts/worktree_task.py create --task-id <repair-task-id> --repair-request <request.json>
```

The expectation JSON is a nonempty list of `{stack, resourcePath, operation, status}`
objects covering exactly the target problem operations. Resource statuses are
CREATE_COMPLETE/UPDATE_COMPLETE/IMPORT_COMPLETE; a successful unexecuted preparation
operation uses status SUCCEEDED. Reuse the request/attempt on interruption. Reservation
occurs once; multiple target problems each get one attempt while the global budget
uses one cycle. One attempt owns one child Task, including static failures.

Checkpoint validates the parent's permitted differences and observed barrier without
completing deploy. The sealed request fixes parent Worktree/branch/start/tip, integration
destination, Task/target/scope, original input/design/execution digests, failure evidence,
problem IDs and exact permitted IaC paths. Create with `--repair-request` starts at that
suspended parent tip; ordinary Create still uses the configured base. In the returned
child Worktree register a new infrastructure/implement contract with target fields,
`Deploy repair request: <absolute request.json>`, identical Validation scope, and
AWS API execution/AWS mutation/Deploy/apply all forbidden. Allowed paths are exactly
the request's IaC paths plus its own contract. Never edit the parent contract or Model.
Follow /implement, correct only defects repairable from the existing approved design,
and use the existing same-child static repair limit of 3.

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<repair-task-id>.md --source <external-child-contract.md>
python3 -B framework/scripts/worktree_task.py repair-validate --task-id <repair-task-id> --repair-request <request.json>
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<repair-task-id>.md --complete
python3 -B framework/scripts/worktree_task.py finalize --task-id <repair-task-id>
```

repair-validate executes the existing scoped task loop in registered Python, records
its real command/result and all tracked/dependent input hashes, and seals the receipt
outside Git. Static PASS means a candidate for retry; it is not AWS resolution.
finalize rechecks contract/snapshot, commits exact bytes, and ff-only integrates into
the pinned suspended parent. Its durable intent supports retry after commit/merge
interruption. Its result preserves child contract, blob/hash transitions, effective
inputs, validation snapshot and integration commit after child cleanup. A handwritten
PASS, a failure-approval exception, stale validation, extra files/commits, or a changed
parent tip cannot produce an accepted result. No AWS or deploy/apply runs in child.

From a surviving root, clean up the child before continuing the parent. The supervising
LLM explicitly resumes only the original Task named by this preauthorized request:

```console
python3 -B framework/scripts/worktree_task.py cleanup --task-id <repair-task-id>
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<original-task-id>.md --resume
python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py <original-target-and-stack-arguments> --state <same-session.json> --resume --repair-result <result.json>
```

The dedicated result entrance plans and seals one input revision under exclusion before
AWS recovery/execution. Normal --resume accepts no external IaC change. InputDigest,
intended design/Model dependencies and executionDigest retain their authority; only
verified child IaC manifests/unit digests/caches advance. Unknown commits/bytes and
post-validation dependency changes are rejected. Final parent validation attributes
only actual ordered before/after child transitions; it does not exempt whole files or
expand parent permissions. Same-result replay recovers that acceptance without resetting
RUNNING/SUCCESS or sending Execute again. Old/unrelated/out-of-order results fail closed.

Affected unexecuted units and declared consumers discard old delivery, ChangeSets,
client tokens and approvals. Input-unchanged SUCCESS/observed synchronization is retained.
Shared-input or dependency impact on SUCCESS waits for scope confirmation. Failed
executions first recheck original StackId/token, original failure safety and live state;
unknown operations are observed through their existing identity before another execute.
A failed, empty REVIEW_IN_PROGRESS CREATE shell is cleaned only with original
Stack/ChangeSet ownership, FAILED/UNAVAILABLE, no execution, empty inventory and live
protection checks; its status is never rewritten as rollback. Runtime cleanup requires
the original separate recovery authorization. Each retry uses a new ChangeSet and new
destructive approval when applicable.

Python issues stable opaque problem IDs per common cause and request target
(logical target/Stack/resource/type/operation); `causeId` links the common LLM-diagnosed
cause across targets. Display/property/constraint labels are evidence, not identity keys.
Task IDs, request IDs, time/token and changed hashes are evidence only. SAME retains
IDs for existing targets and shares attempts/stops across all targets of that cause.
Observation sets and the repaired subset remain separate; diagnosis rewrites never
refund reservations. All diagnoses are retained in the signed workflow ledger.

A→repair→A without observable target progress stops on the second distinct execution;
A→B continues with distinct evidence; A→B→A stops as a cycle/regression. Untargeted B in
A+B does not consume a B failure. Only confirmed target/nested operation successes count
as progress, with at most 3 cycles per problem. File changes, static PASS, LLM claims,
peer success and absence of A before its validation point are not resolution. Existing
decoding excludes template comments/formatting from effective inputs; parameters and
artifact content join the fingerprint. Unchanged or known failed effective input is
rejected before redeploy. Unchanged-IaC runtime recovery remains a separate route.

At the global limit retain all history and WAITING_HUMAN. There is currently no
machine-verifiable external Human budget approval boundary. `deploy_handoff.py budget`
always refuses extension, persists WAITING_HUMAN and returns nonzero; arbitrary
`--authorization` text, handwritten JSON, environment variables or LLM declarations are
not approval. Do not edit sessions/contracts to expand an existing interval. Even a future
authentic extension must bind workflow/interval/count/single use and cannot release
per-cause no-progress/cycle stops or authorize delete/replacement or elevated permissions.

Signed workflow ledger/save intents prevent rollback/new-file resets. The Worktree
helper's sealed account/Region/overlapping-Stack registry retains the original workflow.
Closing drained/synchronized state archives any pending request and counts but cannot
release an unresolved workflow to a new Task, even with another label. Only COMPLETE
with all successful observations synchronized releases overlapping scope. CLOSED never
re-executes. Resume the original session rather than resetting history. Close never
cleans unknown AWS operations or unfinished children.

The v5 implementation used session v4. This change retains that outer format and adds
`workflow.diagnosisVersion: 1`. Existing IDs, observations, attempts, budget, consumed
results, execution tokens and pending child evidence remain intact. A legacy workflow
with problems/reservations but no relation marker is conservatively `legacyUncertain`
and WAITING_HUMAN, never a fresh zero-attempt cause. Explicit `migrate` with the existing
old/new execution digests is still required for changed execution definitions; the
relation marker does not grant migration or AWS authority. No automatic semantic
reclassification or clearing of legacy uncertainty is provided.

After an interrupted writer exits, retain/review locks using existing ownership rules;
never delete unknown locks. `deploy_handoff.py recover-session --state <original-path>`
restores the same Task's latest signed state including cause links/diagnoses and attempts.

## Terraform

Use project.json target, existing roots/workspaces/backend/variable inputs and the same Task/Issue/account/Region/profile checks. Run check-deploy-context.py with environment and alias (or aws-account-id) and optional profile. Retain Terraform fmt/init/validate/plan with a saved binary under terraform.md; explain and seek approval only for unapproved destruction/replacement. Apply only that identical authorized plan. A failed apply may be partial: inspect state/AWS read-only and stop. After success collect non-sensitive outputs, use read-only state attributes only if outputs are absent, and require agreement if both exist. Update permitted observations/references with the existing publication guard and generation.

## Verify and finish

AWS terminal SUCCESS and observedSynced are separate. Uniquely resolve only successful unsynchronized resources and necessary references, plan every update, then use the existing atomic Model/publication guard and service-scoped generation. Retain/DELETE_SKIPPED/unknown destruction and integrated children without identifiers never reset a parent. Preserve AWS SUCCESS on ambiguous synchronization, stop starts, drain peers, and resume only unsynchronized plans with original execution evidence. Do not store generated ARNs.

Confirm only authorized repair/observed diffs; run one classified final validation under loop-engineering. An ordinary deploy uses blueprint-loop.py --mode task --task-file tasks/<task-name>.md. Required Validation scope/Acceptance and Git diff checks remain; no automatic next phase or scenario tests. Report execution/approval/observed states, timing and blockers separately. Do not store verification reports in the repository or claim AWS success from offline checks.
