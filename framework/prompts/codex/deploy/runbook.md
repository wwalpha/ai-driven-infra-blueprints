# Deploy operation runbook

Select the operation from the router; read its section and explicitly required Rules before acting. Reuse unchanged documents in this Task. Fresh AWS identity, inputs, dependencies, ChangeSets and token events must still be checked at their specified boundaries. Unknown applicability means read the relevant exception, then stop if evidence remains insufficient. The route matrix at the end is an operation index, not an instruction to read every route.

## Managed entry

Resolve the Task ID and Target; follow the Worktree [permission inspection and continuation procedure](../../../../.agents/skills/worktree/SKILL.md#sandbox-permission-approval-and-continuation), then use the existing lifecycle entry from a surviving root:

```console
python3 -B framework/scripts/worktree_task.py deploy-start --task-id <task-id>
```

Use its returned Worktree for registration/preparation/child commands. Reuse the same valid unfinished Task and preserve Snapshot/progress/current requests; ambiguous ownership stops, never create a replacement Task. Offline preparation/help/read-only diagnostics remain available outside managed Worktrees. Continue with [Prepare](#prepare).

## Prepare

Read [Task transition](../../../rules/task-contract.md#task-transition) (including its required common and conditional reads), [Task boundary](../../../rules/task-contract.md#task-boundary), [Acceptance contract](../../../rules/task-contract.md#acceptance-contract), [Topology](../../../rules/project-configuration.md#topology) and [Credentials and account](../../../rules/project-configuration.md#credentials-and-account). Confirm Human environment/Target, Engine, account/Region/profile, Stack scope and allowed actions against `project.json`. Never substitute credentials after failure. Use the root returned by the managed Worktree entry and its registered Python wrapper. Register the Task as the first repository change; Deploy cannot edit IaC, intended design or scenarios.

For Terraform select [Terraform](#terraform). For CloudFormation select only [SDK Prepare](#sdk-prepare) or [CLI Prepare](#cli-prepare), matching the fixed Task method. Before CloudFormation AWS operations read [Common rules](../../../rules/cloudformation.md#common-rules), [AWS execution context](../../../rules/cloudformation.md#aws-execution-context), [Resource mode boundary](../../../rules/cloudformation.md#resource-mode-boundary), [Deployment validation and execution](../../../rules/cloudformation.md#deployment-validation-and-execution), [Model authority](../../../rules/model-information.md#model-authority), [Resource management mode](../../../rules/model-information.md#resource-management-mode), [CloudFormation deployment policy](../../../rules/model-information.md#cloudformation-deployment-policy) and [Properties format](../../../rules/model-information.md#properties-format). Model, Template, Parameters and Stack definitions are authority; ordinary Deploy does not read generated detailed-design prose as execution input. Resolve ownership, Conditions and dependencies without guessing or expanding scope.

## SDK Prepare

Read [DeployOrder selection and synchronization scope](../../../rules/cloudformation.md#deployorder-selection-and-synchronization-scope) and [Managed Deploy snapshot and Git publication](../../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication). Offline preparation produces an external contract and summary; inspect the original contract, exact StackNames, Resource owners, Validation scope and Model/View paths before registering:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> --task-file tasks/<task-id>.md
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --register <absolute-preparation.json>
```

Repeat `--stack`, or use inclusive `--order-from`/`--order-to` instead; never combine the selectors. Optional `--service` checks the discovered owners and grants no additional services. Use `--aws-account-id` instead of `--alias` when no alias exists and the configured `--profile` when set. Missing/invalid scope, changed inputs or ambiguous ownership stop registration. Preserve the registered Snapshot and all fixed StackNames on resume; do not rerun old preparation to replace evidence. External consumers are deferred without Model/View authority. Then select [SDK Stack](#sdk-stack).

## CLI Prepare

Read [Method and local lifecycle](../../../rules/cloudformation.md#method-and-local-lifecycle) and [Preflight and fixed Snapshot](../../../rules/cloudformation.md#preflight-and-fixed-snapshot). These are the sole CLI preflight command authority: verify CLI v2/options, configured context with STS, declare confirmed account/Region/Partition, select/register the infrastructure/deploy Task and retain the original input manifest and immutable copies outside Git. Confirm exact StackNames, Model/View paths, DeployOrder and MaxConcurrentStacks. CLI uses no SDK Preparation, Controller, boto3/botocore or Python AWS wrapper. `model/cli.py observed` is an offline mapping check, not an observation-saving command.

Read current scoped Stacks, resources and ChangeSets as directed by that preflight. UNKNOWN is not absence; REVIEW_IN_PROGRESS needs ChangeSet classification. Missing inputs/context, competing activity or uncertain request evidence blocks new mutations. Resume through [CLI Recovery](#cli-recovery), preserving the original manifest and identities. Then select [CLI Delivery](#cli-delivery), even for inline templates, to check dependencies and whether S3 is required.

## SDK Stack

Read [LLM-controlled short operations](../../../rules/cloudformation.md#llm-controlled-short-operations) and [Explicit operations](../../../rules/cloudformation.md#explicit-operations) before the first Stack turn. Keep the same Task/Target and repeat `--stack` for **every fixed StackName** on all actions, including when saving only one Stack. Use `--aws-account-id` instead of `--alias` where applicable, configured `--profile` when set; `--sequential` can only lower concurrency.

```console
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action advance
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action sync --sync-stack <StackName>
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action checkpoint --sync-stack <StackName>
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action status
```

| Current need/result | Next operation or stop |
| --- | --- |
| First or continuing ordinary turn | `advance` reads current AWS and advances one bounded turn; no unconditional status-before-advance call. |
| Multiple Stacks | Retain full scope and configured concurrency; independent same-Order peers may continue after one failure, later Orders require earlier success. |
| Independent inspection, interruption or uncertain request | `status` and [SDK Recovery](#unfinished-aws-operation-recovery); retain original identity/token. |
| Current observations must be saved, including failure/running/unknown facts | Read [Observation reads](#observation-reads), then `sync --sync-stack`; repeat `--sync-stack` for an indivisible candidate. Intermediate sync keeps running. |
| Already saved candidate requires validation/commit/publication | `checkpoint`, with saved scope; no new AWS execution or recollection. A separate checkpoint is normally unnecessary after sync. |
| Required destructive change is unapproved | [Approval wait](#confirm-unapproved-deletereplacement); after full consent add `--approve-change-set <actual-approved-ID>` to the same target/scope turn. |
| Final observations/checks are ready, all requests settled | [SDK Finish](#sdk-finish). |
| Git publication pending/conflicted | [Git Recovery](#git-recovery); never redeploy because saving failed. |

Inspect `stage`, `cause`, `nextAction`/`nextActions` and actual result separately. A null or missing command means review; do not infer authority or a retry. Stop new starts on Task/context/input mismatch or unresolved dependencies, retaining accepted requests for observation. No Sub Agents, fixed-period sync or background Model writer.

## CLI Stack

This compatibility section routes to [CLI Delivery](#cli-delivery), [CLI ChangeSet](#cli-changeset), [CLI Execute](#cli-execute), [CLI Observe and save](#cli-observe-and-save) and [CLI Finish](#cli-finish) at their operation boundaries. Read only the current operation and its required rules. Never switch to SDK Controller, sync, checkpoint or deploy-publish.

## CLI Delivery

Read [Order, dependencies and S3 delivery](../../../rules/cloudformation.md#order-dependencies-and-s3-delivery) and, when S3 is needed, [S3 deployment artifacts](../../../rules/cloudformation.md#s3-deployment-artifacts) in full. Those Rules own the exact HeadObject/PutObject commands, checksum/size/version/owner checks and Artifact encryption requirements; do not duplicate or replace them here. Only declared fixed objects may be delivered. Inline templates at most 51,200 bytes skip template upload, not dependency or input checks. Larger templates require the designed destination; template-only bucket-preflight exceptions do not apply to Artifacts.

Count existing accepted/uncertain requests against MaxConcurrentStacks; run independent same-Order Stacks only. Confirm active ImportValue/Condition dependencies immediately before Create and Execute. Missing/changed producer evidence blocks the consumer; no out-of-scope producer deployment. For object conflict, lost response, 409/412 or changed encryption/checksum/version, reconcile by the Rules; never overwrite or resend blindly. On success go to [CLI ChangeSet](#cli-changeset); on uncertainty use [CLI Recovery](#cli-recovery).

## CLI ChangeSet

Read [ChangeSet review and execution](../../../rules/cloudformation.md#changeset-review-and-execution), which owns exact ValidateTemplate/CreateChangeSet/DescribeChangeSet commands and arguments for inline or pinned S3 URL. Use CREATE only for proven absence and UPDATE for an eligible existing Stack, pinning StackId. Preserve confirmed settings, parameters, capabilities/role/tags and fixed bytes. Record unique name, original Create token and request intent before submission. Inspect every response and every page; creation failure is not automatically no-change.

Review the complete Changes/input identity with CREATE_COMPLETE and ExecutionStatus AVAILABLE. For unapproved Remove or Replacement True/Conditional read [Approval wait](#confirm-unapproved-deletereplacement); partial approval and unknown actions stop. No uniform approval wait for ordinary non-destructive change. No IMPORT or high-level deploy/create-stack/update-stack bypass. After review/required consent select [CLI Execute](#cli-execute); lost Create response selects [CLI Recovery](#cli-recovery), not another Create.

## CLI Execute

Use the Execute and post-Execute commands in the already-read [ChangeSet review and execution](../../../rules/cloudformation.md#changeset-review-and-execution). Immediately re-read the same full ChangeSet/Stack identity, Task/context, fixed input hashes, S3 integrity, dependencies and absence of competitors. Changed/recreated/expired content invalidates consent. Record original Execute token and intent before submitting that exact ChangeSet. Exit 0 proves submission only.

Read current DescribeStacks and complete DescribeStackEvents; require root events for the original StackId/token and current terminal state. Old COMPLETE alone never proves this attempt succeeded. IN_PROGRESS means observe; uncertainty selects [CLI Recovery](#cli-recovery). Failure/rollback blocks dependent later Orders, permits proven independent peers within capacity, and never authorizes automatic rollback/delete/bootstrap or redeploy of successful Stacks. Preserve request tracking. Once observations are available select [CLI Observe and save](#cli-observe-and-save).

## Observation reads

Before either method saves observations or generates Views, read [Identifier lifecycle](../../../rules/observed-values.md#identifier-lifecycle), [Collection and propagation](../../../rules/observed-values.md#collection-and-propagation), [Observation publication](../../../rules/observed-values.md#observation-publication) and [Properties-first updates and display generation](../../../rules/model-information.md#properties-first-updates-and-display-generation). Preserve Desired/reference/placement, hidden/IMPORT identity and secret boundaries. Unavailable identifiers lose old observed values; never persist UNKNOWN or a reference-derived generated ARN as authority. Confirmed uncreated/deleted and retained resources follow their distinct rules. Stop ambiguous/out-of-scope Row writes. SDK saving is the existing sync action, not a reimplemented writer.

## CLI Observe and save

Read [Observation reads](#observation-reads) and [Observations, validation and publication](../../../rules/cloudformation.md#observations-validation-and-publication). Retrieve AWS values directly with CLI, match explicit cfn-logicalId, types, active Conditions and authorized Rows, then account for required resources and incoming references. A local save failure does not justify another AWS deployment.

There is no public observation-saving CLI: the existing non-AWS APIs are `model.sources.load_model(path)`, `model.observed.observed_outputs(path, values)` and `model.observed.publish_observed_candidates(root, outputs, inputs)`. The offline `model/cli.py observed` command does not save. For each exact service source, load its snapshot, copy `snapshot.values`, patch only confirmed allowed `observed.row.<RowId>.value` entries (remove the key for unavailable values), and produce candidate text with `observed_outputs`. Merge those candidate mappings and call `publish_observed_candidates` once under the selected Task, passing the **original consumed-input path→bytes map** retained before retrieval. Do not replace it with freshly read bytes. The existing API rechecks the Task, Row authority and byte preservation under its publication guard; it is not permission to save every observable Row.

API call shape, using the already verified source path, complete values mapping, candidate mapping and original input bytes (no AWS calls in this code):

```python
from model.observed import observed_outputs, publish_observed_candidates
outputs.update(observed_outputs(source_path, values))
publish_observed_candidates(repository_root, outputs, original_inputs)
```

Use registered Python with `framework/scripts` on its process-local import path for these existing APIs. Do not add a new writer CLI or fall back to direct properties writes/SDK sync. If the consumed input set, safe call context or exact Row mapping cannot be established, retain the evidence/candidate and stop; a dedicated public writer command is a separate follow-up, not part of this Issue.

After the guarded Model save, generate only authorized affected services and run the scoped task loop:

```console
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/sync-model.py --environment <environment> --alias <alias> --service <service-id> --write
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-id>.md
```

Repeat `--service` for exact affected services, or use confirmed `--scope <environment/target-directory/service>`; use `--aws-account-id` when no alias exists. Generation failure retains saved Model and successful Views; stale required Views/validation failure block completion. Intermediate saves keep running. Finish only through [CLI Finish](#cli-finish).

## Verify and finish

Read [Validation policy](../../../rules/loop-engineering.md#validation-policy), [Validation scope](../../../rules/loop-engineering.md#validation-scope) and [Infrastructure task completion](../../../rules/loop-engineering.md#infrastructure-task-completion). Check Task Acceptance and authorized differences. Report AWS attempt result, current Stack state, required observations/Model saves, View generation, Snapshot validation, Git commit/merge and Task status independently. A failed settled attempt can have a consistent Snapshot; Deploy FAIL remains FAIL. Unexecuted/incomplete checks never count as PASS. Active/uncertain requests or pending approval keep tracking and prevent completion. Use only [SDK Finish](#sdk-finish) or [CLI Finish](#cli-finish) for the fixed method. Do not proceed to scenarios or another task.

## SDK Finish

Read [Verify and finish](#verify-and-finish). When ending the Task, use the SDK command in [SDK Stack](#sdk-stack) with `--action sync --final`, retaining full Stack scope. Add only needed `--sync-stack` observations; omit when already saved. This privately validates completed with Model/Views and adopts only PASS. Failure retains running, saved Model and successful Views. `checkpoint` resumes the same saved final intent without another `--final` or recollection. No all-Stack SUCCESS or separate pre-final complete is required. After publication select [SDK Publication](#sdk-publication); unresolved Git work selects [Git Recovery](#git-recovery).

## SDK Publication

After verified final publication, use ordinary lifecycle finalization:

```console
python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id>
```

No finalization while requests remain active/uncertain, required saves/checks are incomplete or publication is pending. Never use cleanup to claim successful publication. Follow [Managed Deploy snapshot and Git publication](../../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication) and Worktree completion/permission guards.

## CLI Finish

Read [Verify and finish](#verify-and-finish) and [Observations, validation and publication](../../../rules/cloudformation.md#observations-validation-and-publication). Once all AWS requests are settled and required Model/View/loop work passed, follow that Rule's exact `task_contract.py --complete` and ordinary Worktree finalize commands. The actual completed latest-base candidate is validated without SDK receipts. CLI uses no sync/checkpoint/deploy-publish, PR mode or validation-failure bypass. Pending/conflicted Git work retains the candidate for Human review; do not force or redeploy.

## Git Recovery

Read [Managed Deploy snapshot and Git publication](../../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication) for SDK and [Observations, validation and publication](../../../rules/cloudformation.md#observations-validation-and-publication) for CLI; select only the fixed method. SDK retry of an existing saved commit uses:

```console
python3 -B framework/scripts/worktree_task.py deploy-publish --task-id <task-id>
```

This performs no AWS execution or recollection, including when Task completed locally. On conflict show file/base/source/impact and obtain explicit Human resolution; the existing `--publication-resolution <absolute-json-path>` option takes that approved resolution and revalidates the actual latest-base candidate. Never invent a resolution, force integration or edit lifecycle metadata. CLI instead retains its candidate and uses the ordinary same-Task recovery/finalize procedure; never switch it to deploy-publish. After verified SDK final publication use [SDK Publication](#sdk-publication).

## CLI Recovery

Read [Interruption and independent recovery](../../../rules/cloudformation.md#interruption-and-independent-recovery). Recheck fixed inputs/caller, original Stack/ChangeSet/name/tokens, full events and unfinished requests with direct CLI. Lost Create inspects the original unique name; lost Execute reconciles the same ID/token events. An old COMPLETE, AVAILABLE or missing event alone cannot settle a request. Missing evidence, replacement, UNKNOWN or competitor activity stops new mutations and retains tracking. No unconditional resend, replacement token, SDK recovery, rollback/delete or signed repair shortcut. Resume only the operation supported by current evidence, retaining original scope and consent boundaries.

## Correct this Task's preparation omissions

この節はSDK方式で固定済みの契約訂正専用。CLI方式の不足証拠をSDK progressで補わない。

固定後の契約訂正は[Self recovery](../../../rules/task-contract.md#self-recovery)と
[Deploy correction conditions](../../../rules/cloudformation.md#managed-deploy-contract-correction)を読む。
元Human依頼と固定時の原文を比較し、固定Execution scopeと保存入力で証明できるOwner serviceの
Validation scope追加と、必要なModified files／Allowed pathsの記載漏れを判断する。
同一TargetのConsumerはDeferredのProducer・Consumer・Reference Key・Stackを確認し、
Humanの明示承認を得たserviceだけ同じ訂正コマンドの
`--approve-deferred-consumer <environment/target-directory/service>`で追加する。
参照行の古いObserved除去と必要Viewに限定し、他Targetや無関係Resourceへ権限を追加しない。
他Targetは対象・参照根拠・未確認事項を提示し、別途承認された既存Model同期手順へ引き継ぐ。
後続Taskを自動作成しない。Goal・対象・実行入力・AWS権限・
Human同意の拡大は訂正扱いしない。ハッシュ一致は意味判断や承認の証明ではない。

同じTaskを既存操作でsuspendし、現在のstatus／Suspension reasonを保った外部候補を作る。
内部状態を手動変更せず、次を使う。

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-name>.md --correct-deploy-contract <absolute-candidate.md>
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-name>.md --check-resume-scope
```

成功してもsuspendを維持する。全停止原因が安全に訂正済みの自分の準備ミスだけであり、
他の阻害がないと確認したときだけ、既存の`--resume`を使い失敗した検査から再開する。
AWS再実行やTask完了は訂正の結果として行わない。元契約原文や固定入力証拠の不足、未確定要求は停止する。
原本・候補・現在値を検証できるObserved／生成Intentと未確定checkpointは既存復旧処理で保持・継続する。
証拠不整合、固定済みcheckpoint候補、未完了Git公開、修復Failure／handoff、同時変更は停止・保持する。
保存中断のintentが残った場合だけ同じ候補・同じ訂正コマンドで安全性を再検証する。
未対応の契約訂正や状態を別Taskへの付け替え・無条件再固定・進捗削除で回避しない。
再開は必要な`sync`／`checkpoint`を使い、確定済みStackを再Deployしない。
古い`preparation.json --run-controller`を再利用しない。DeferredはOwner保存とConsumer参照保存・生成を
別々に追跡し、未解決記録の削除や`sync-model`だけで同期完了にしない。

## Confirm unapproved delete/replacement

[Delete and replacement confirmation](../../../rules/cloudformation.md#delete-and-replacement-confirmation)とTerraformの[Validation and execution](../../../rules/terraform.md#validation-and-execution)が正本。Remove、Replacement=True/Conditional等の未承認変更がある場合だけHuman承認を待つ。Stack/ChangeSet IDまたは保存Plan、全対象・Action・Replacement・PolicyAction、既知の物理Resourceとデータ/アクセス/可用性への影響を説明する。不明な影響は未確認と明示する。部分承認で実行しない。

同じTask・Target・入力と今回承認された実IDを使う。実行時再検証を省略せず、変更・再作成・期限切れ・中断後に旧承認を流用しない。変更のない通常Deployを一律に承認待ちにしない。

## Unfinished AWS operation recovery

この節の共有要求記録・ロック・ResolverはSDK方式専用。CLIはRulesの独立した再開手順で同じ現在AWS/identity要件を確認する。

通常開始・再開は対象 Stack の最新 AWS 状態を先に取得する。旧 Task、mode、StackStatus、expectedOutputs、Observed、checkpoint/Git、特定の修復経路の証明は現在状態の採用・次の試行の条件にしない。UPDATE_COMPLETE だけで今回の Desired 適用済みとは判断せず、固定入力から ChangeSet を判定する。

共有記録は account/Region/StackName ごとの現在の未確定要求だけ。送信直前に同一 Stack ロック下で intent を保存し、応答喪失時は元の StackId・ChangeSetId・token を維持する。直前 Execute が不確定なら、単一の古い COMPLETE 読み取りで新 token の Execute を許可しない。現在 ChangeSet・token event を確認し、AWS 要求が決着したら Model/Git を待たず記録を終了する。破損時は当該 Stack の新しい変更だけを保留し、独立 Stack や Model 保存・Git 統合を止めない。

REVIEW_IN_PROGRESS は ChangeSet と合わせて判断する。UPDATE_ROLLBACK_COMPLETE は今回失敗と次回更新可否を分ける。ROLLBACK_COMPLETE、rollback failed は AWS 制約に従う。構造化された不存在だけ ABSENT、取得不能は UNKNOWN。Output 欠落、削除履歴、不完全な一覧、保持リソースを不存在と混同しない。


Export は共通 Resolver で必要名だけを解決する。既知 Producer は scoped DescribeStacks、未知だけ必要な ListExports を使う。古い Task の Outputs 一致を現在値保存条件にしない。同期や Git 障害を理由に AWS を再実行しない。

## External IaC repair handoff

この署名付きhandoffはSDK方式専用。CLI失敗からSDK証跡を作り直す経路ではない。

[Controlled deploy repair](../../../rules/cloudformation.md#controlled-deploy-repair)と[Worktree repair lifecycle](../../../../.agents/skills/worktree/SKILL.md#explicit-cloudformation-repair-handoff)が権限・ライフサイクルの正本。CloudFormationの現在Taskに`External IaC repair: allowed`がある場合だけ、今回の署名付き失敗証拠、正確なIaCと承認済Modelから原因を診断する。`repairFailure`の存在は修復の証明ではない。

承認待ち・認証/権限・設計不足・依存待ち・送信不明は修復依頼の根拠にしない。未完了操作/publicationの確定後、原因と入力/Model証拠が揃った場合だけ`deploy_handoff.py --help`所定の単発依頼を作る。親をsuspendし、別Implement Worktreeにexact IaC pathsだけを許可する。子のAWS API execution/AWS mutation/Deploy/applyは禁止。同一child/requestのstatic検証は最大3回、検証済みexact commit/paths/bytesだけff-only統合する。

親の明示resume後は最新IaC/AWSによる独立Deployとし、必要なHuman承認も新しく取る。無制限の修復・Deploy連続起動は禁止。証拠の保持・明示破棄・cleanupは既存CLI/Worktree規則に従い、秘密値や推測原因を記録しない。

## Terraform

Read [Terraform Rules](../../../rules/terraform.md), [Properties format](../../../rules/model-information.md#properties-format), [Local loop](../../../rules/loop-engineering.md#local-loop) and the common Task/Model/Observed/completion reads. Use `check-deploy-context.py --help` for the existing preflight command and saved-plan sequence; select only the designed Root/workspace/backend/variables and same account/Region/profile. Unapproved destroy/replacement requires full saved-plan consent; apply only that identical plan. Failed apply may be partial: inspect state/AWS read-only and stop, never blindly reapply. After success save non-sensitive observations and required Views; Terraform semantics are unchanged.

## 最終保存

Compatibility anchor: select [SDK Finish](#sdk-finish) or [CLI Finish](#cli-finish) for the Task's fixed method. Do not read both methods or convert a Task to finish it.

## DeployOrder selection and synchronization scope

Compatibility anchor: read [SDK Prepare](#sdk-prepare) for SDK selectors or [CLI Prepare](#cli-prepare) and [CLI Delivery](#cli-delivery) for explicit CLI scope/dependencies. Neither route gains authority over external consumers/producers.

## Operation routes

Use the row matching the current operation. Entry is Deploy Skill → Phase Router; Prepare/common authority reads are shared once per Task. “Reuse” means unchanged document text only; current AWS rechecks and input/identity/consent checks still apply. Every row's linked section owns its explicit commands and required Rule links.

| Route | Read next | Operation / branch | Reuse / stop |
| --- | --- | --- | --- |
| sdk-first | [SDK Prepare](#sdk-prepare) → [SDK Stack](#sdk-stack) | Offline review/register, then advance | Reuse common Prepare; changed candidate/authority stops |
| sdk-continue | [SDK Stack](#sdk-stack) | advance; no mechanical status call | Reuse unchanged reads; current AWS required |
| sdk-multiple | [SDK Stack](#sdk-stack) | Full repeated stack scope, Order/capacity | Failure blocks later Orders, not independent same-Order peers |
| sdk-sync | [SDK Stack](#sdk-stack) → [Observation reads](#observation-reads) | Selected sync; Task running | Reuse scope; no unsanctioned Consumer writes |
| sdk-final | [SDK Finish](#sdk-finish) → [SDK Publication](#sdk-publication) | Final sync, then finalize | All requests settled and required saves/checks PASS |
| sdk-checkpoint | [SDK Stack](#sdk-stack) | Resume saved candidate | No AWS replay/recollection; keep saved scope |
| sdk-git-retry | [Git Recovery](#git-recovery) | Saved commit deploy-publish | No AWS calls; conflict needs Human decision |
| cli-first | [CLI Prepare](#cli-prepare) → [CLI Delivery](#cli-delivery) | Context/Snapshot, scoped AWS inspection | No SDK preparation; missing context stops |
| cli-s3 | [CLI Delivery](#cli-delivery) | Verify/deliver required objects | Reuse Rules; recheck object integrity before Create/Execute |
| cli-create | [CLI ChangeSet](#cli-changeset) | Proven absent CREATE | Unique original token; lost response → recovery |
| cli-update | [CLI ChangeSet](#cli-changeset) | Eligible existing UPDATE | Pin StackId, fixed inputs/settings; full Changes |
| cli-approval | [Confirm unapproved delete/replacement](#confirm-unapproved-deletereplacement) → [CLI Execute](#cli-execute) | Wait for all destructive changes | Changed/recreated ChangeSet invalidates consent |
| cli-execute | [CLI Execute](#cli-execute) | Recheck exact identity/content, Execute, inspect events | Submission is not success; uncertain → recovery |
| cli-save | [CLI Observe and save](#cli-observe-and-save) | Direct CLI observation, guarded local API, generation/loop | No new writer; unknown inputs/Rows or failed Views stop |
| cli-finish | [CLI Finish](#cli-finish) | Local complete and ordinary finalize | No SDK receipts; active requests prevent completion |
| failure | [Verify and finish](#verify-and-finish); SDK: [Unfinished AWS operation recovery](#unfinished-aws-operation-recovery), CLI: [CLI Recovery](#cli-recovery) | Select only method-specific recovery | Preserve FAIL/current state; no automatic repair/redeploy |
| lost-response | SDK: [Unfinished AWS operation recovery](#unfinished-aws-operation-recovery), CLI: [CLI Recovery](#cli-recovery) | Select SDK status or direct CLI reconciliation | Original identity/token; no blind resend |
| task-resume | [Prepare](#prepare); SDK: [Unfinished AWS operation recovery](#unfinished-aws-operation-recovery), CLI: [CLI Recovery](#cli-recovery) | Reuse same Task; select fixed method | No rebaseline or replacement Task; current AWS required |
| contract-correction | [Correct this Task's preparation omissions](#correct-this-tasks-preparation-omissions) | Suspend/correct/check/resume same SDK Task | Only proven omissions; deferred Consumer needs consent |
| repair | [External IaC repair handoff](#external-iac-repair-handoff) | Authorized one-shot SDK child | Settle requests; exact IaC only, child AWS forbidden |
| git-conflict | [Git Recovery](#git-recovery) | Select method; retain candidate | Human exact resolution and latest-base validation |
| terraform | [Terraform](#terraform) | Preflight, reviewed identical saved plan, apply | No changed plan/credentials; partial failure stops |
