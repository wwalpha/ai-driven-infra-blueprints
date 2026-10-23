# Infrastructure Deployment Prompt

## Normal startup

Human指定のenvironment/alias、resource/execution account、Region/profile、StackNameとservice IDsを確定する。未確定ならenvironment→複数target時のalias→account→scopeの順に一問ずつ確認し、同じproject.json targetの候補だけ示す。唯一targetにaliasを要求しない。configured awsProfileを使い、未設定時のみ明示profile/default chainを使う。不一致・認証失敗で別credentialへ切り替えない。

Read before changing filesの必須本文と対象入力、Task候補を漏れなく読む。hash一致を未読範囲の読了証明にしない。生成物の存在・内容hash・scope・変更検知・機械検証を維持し、generated viewへのfallbackや値の推測をしない。設計変更・scenario実行は禁止。

固定したworktree Python/PATH/PYTHONPATHで、明示serviceと全Stackを一度に準備する。load_units()が既存のStack Model/generated Stack view一致を確認する。

```console
<fixed-python> framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --service <service-id> [--service <service-id> ...] --task-file tasks/<task-name>.md [--profile <profile>] [--sequential]
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

Retain generated artifact existence verification, hash monitoring, machine generated artifact validation, and stop conditions. Only for explicit display defect/mismatch investigation, necessary artifact portions may be read. Classify model/generated artifact/IaC mismatches and deployment failures under [Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair). Repair only AUTO_REPAIRABLE, or let the same controller handle RUNTIME_BOOTSTRAP without repository changes, and continue after validation. Secrets Manager initial-value bootstrap classification, CREATE ownership/account/region/schema/value checks, intent/token persistence, AWS mutation and failed-stack retry belong exclusively to the controller; do not manually run put-secret-value.

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

CloudFormation failures proceed to controller Controlled deploy repair classification; AUTO_REPAIRABLE and RUNTIME_BOOTSTRAP automatically continue remaining units after their respective repair/bootstrap, validation, new change sets, and retries. Consult Human only for HUMAN_REQUIRED such as scope excess, account/region mismatch, unknown delete/replacement actions, unconfirmed designs, or missing external permissions. Terraform validation/plan/apply failures continue to stop as before. Only unapproved delete/replacement waits for human confirmation above rather than ending as failure. Do not change intended design or perform IaC changes without repair history or retries with unconfirmed causes. On CloudFormation stop conditions, do not start new units; confirm running stack terminal states and distinguish successful, failed, and unexecuted units. Do not automatically rollback/delete/redeploy successful stacks. Terraform apply failure may mean partial apply; check state and actual AWS resources read-only and stop.

## Resume

Resume the existing Task/session with --resume and only Human-approved --approve-change-set IDs. Preserve original intent/token, ChangeSet/approval and input evidence. Reacquire boundary AWS data; historical static validation metadata is never execution permission. Unsafe migration stops with its reason, retaining SUCCESS and unsynchronized work. Do not replace a session or rerun successful Stacks merely because modules/transport changed. Repair changes require exact persisted evidence, unchanged intended Model and scope.

## Terraform

Use project.json target, existing roots/workspaces/backend/variable inputs and the same Task/Issue/account/Region/profile checks. Run check-deploy-context.py with environment and alias (or aws-account-id) and optional profile. Retain Terraform fmt/init/validate/plan with a saved binary under terraform.md; explain and seek approval only for unapproved destruction/replacement. Apply only that identical authorized plan. A failed apply may be partial: inspect state/AWS read-only and stop. After success collect non-sensitive outputs, use read-only state attributes only if outputs are absent, and require agreement if both exist. Update permitted observations/references with the existing publication guard and generation.

## Verify and finish

AWS terminal SUCCESS and observedSynced are separate. Uniquely resolve only successful unsynchronized resources and necessary references, plan every update, then use the existing atomic Model/publication guard and service-scoped generation. Retain/DELETE_SKIPPED/unknown destruction and integrated children without identifiers never reset a parent. Preserve AWS SUCCESS on ambiguous synchronization, stop starts, drain peers, and resume only unsynchronized plans with original execution evidence. Do not store generated ARNs.

Confirm only authorized repair/observed diffs; run one classified final validation under loop-engineering. An ordinary deploy uses blueprint-loop.py --mode task --task-file tasks/<task-name>.md. Required Validation scope/Acceptance and Git diff checks remain; no automatic next phase or scenario tests. Report execution/approval/observed states, timing and blockers separately. Do not store verification reports in the repository or claim AWS success from offline checks.
