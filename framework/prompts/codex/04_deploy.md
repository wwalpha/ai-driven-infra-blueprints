# Infrastructure Deployment Prompt

## Normal startup

Human指定のenvironment/alias、resource/execution account、Region/profile、StackNameとservice IDsを確定する。未確定ならenvironment→複数target時のalias→account→scopeの順に一問ずつ確認し、同じproject.json targetの候補だけ示す。唯一targetにaliasを要求しない。configured awsProfileを使い、未設定時のみ明示profile/default chainを使う。不一致・認証失敗で別credentialへ切り替えない。

Skill開始UTC epochを直ちに記録する。最初のExecuteChangeSet成功応答まで120秒を目標とし、preparation/controller/Create開始を実行開始にしない。実測なしに達成を報告しない。

Read宣言の該当本文、対象要約、Task候補を読む。inputsは全入力・内容・file集合の監視、documentsは当段階のAI読込本文である。Model/IaC/parameters、generated Markdown/JSON、ZIPの全文は通常提示しない。省略してもexistence verification、hash、scope、入力変更検知、既存local loopでの生成物検証は維持する。未読範囲をhash一致だけで読了にせず、generated viewへのfallbackや値の推測をしない。設計変更・scenario実行は禁止。

固定したworktree Python/PATH/PYTHONPATHで、明示serviceと全Stackを一度に準備する。load_units()が既存のStack Model/generated Stack view一致を確認する。

```console
<fixed-python> framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --service <service-id> [--service <service-id> ...] --task-file tasks/<task-name>.md --skill-started-at <UTC-epoch> [--profile <profile>] [--sequential]
```

aliasなしは--aws-account-id。preparation.jsonのdocuments（<=6,000文字/chunk）、対象要約、契約候補を漏れなく確認する。確認済みの同一範囲だけ再読込を省略できる。inputs/generatedViewsのhashは読了やPASS証明ではない。欠損・不一致では停止する。Do not newly reregister already registered tasks. 新Taskは次の登録を最初の変更とし、runtime/hash/Task競合/最新Issuesを再確認する。

```console
<fixed-python> framework/scripts/deploy_preparation.py --register <external-preparation.json>
<fixed-python> framework/scripts/deploy_preparation.py --run-controller <external-preparation.json>
```

全Stackに一つのcontroller/sessionを使う。preparationはAWSなし。controllerが認証、Task/Issue/入力guard、既存Stack所有権、配送barrier、ValidateTemplate、ChangeSet、承認・実行・poll・drain・成功後同期を担当する。同じpreflight/APIをAgent側で重複実行しない。通常起動/Create/ExecuteはRemoveを含め全体mapping/lintなし。失敗修復/bootstrap/未同期SUCCESSだけ必要ownerと参照を解決する。DeployOrder/並行数を保ち、失敗時は新規開始を止めpeerをdrainする。SUCCESSは再実行しない。S3が最初の実行に必要なら初回固定本文に含める。他段階の追加本文は別集計し、該当操作前に読む。

## Read

This single finite declaration selects canonical files/anchors. Startup always applies. Add s3-required for any required artifact or execution template >51,200 bytes; destructive-change before Remove/Replace approval; execution-failed only for repair/bootstrap; resume for existing sessions; aws-success before observed synchronization/generation/completion; terraform for that engine. For Terraform, skip CloudFormation-only rule files from startup. Hash whole files while reading only selected sections. Missing/ambiguous anchors stop.

<!-- deploy-read-plan -->
```json
{"startup":{"when":"always","documents":["../../../AGENTS.md","../../../.agents/skills/deploy/SKILL.md","#normal-startup","#read","../../rules/task-contract.md#task-registration","../../rules/task-contract.md#acceptance-contract","../../rules/task-contract.md#retry-and-stop","../../rules/issue-gate.md#unresolved-issue-gate","../../rules/issue-gate.md#check-timing","../../rules/project-configuration.md#credentials-and-account","../../rules/cloudformation.md#deployment-execution"]},"s3":{"when":"s3-required","documents":["../../rules/cloudformation.md#s3-deployment-artifacts"]},"approval":{"when":"destructive-change","documents":["#confirm-unapproved-deletereplacement","../../rules/cloudformation.md#delete-and-replacement-confirmation"]},"repair":{"when":"execution-failed","documents":["../../rules/cloudformation.md#controlled-deploy-repair","../../rules/task-contract.md#controlled-deploy-repair-contract","../../rules/model-information.md#resource-level-cloudformation-identity","../../rules/model-information.md#resource-management-mode"]},"resume":{"when":"resume","documents":["#resume","../../rules/cloudformation.md#controller-sessions-and-execution-timing"]},"success":{"when":"aws-success","documents":["#verify-and-finish","../../rules/observed-values.md#identifier-lifecycle","../../rules/observed-values.md#collection-and-propagation","../../rules/observed-values.md#compact-observation-persistence","../../rules/model-information.md#properties-first-updates-and-display-generation","../../rules/loop-engineering.md#local-loop","../../rules/loop-engineering.md#validation-scope","../../rules/loop-engineering.md#infrastructure-task-completion","../../rules/task-contract.md#selection-and-publication","../../rules/task-contract.md#task-boundary"]},"terraform":{"when":"terraform","documents":["#terraform","../../rules/terraform.md","../../rules/task-contract.md#task-boundary"]}}
```

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
