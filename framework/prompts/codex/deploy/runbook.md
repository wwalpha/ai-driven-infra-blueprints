# Deploy operation runbook

Read only the selected section when its operation applies; do not reread unchanged sections for every Stack. Current AWS state is always refreshed when required. If applicability is uncertain, read the relevant exception and stop on missing evidence.

## Prepare

Confirm the Human's environment, Target, Region/profile, StackNames and authority against `project.json`; never substitute credentials after failure. Use the managed Worktree and its registered Python wrapper. Review the Task's type, status, scope, allowed outputs and approved Model, Template and Parameters; Deploy cannot change IaC, intended design or scenarios. Fix and preserve the execution Snapshot and full Stack scope; resolve dependencies and DeployOrder without expanding scope.

For SDK, offline preparation produces a candidate and target summary. Review the original candidate, resolved StackNames, ownership and output paths before registration; a summary is not authority. Use confirmed values:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> --task-file tasks/<task-id>.md
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --register <absolute-preparation.json>
```

Repeat `--stack` for the selected scope; alternatively use inclusive `--order-from` and `--order-to`, never both forms. Use `--aws-account-id` instead of `--alias` for a target without an alias. Optional `--service` checks discovered owners; `--profile` must match configuration. Read `--help` for other supported options. Resume with the existing Task and its fixed full Stack scope; do not relaunch its old preparation. Read [DeployOrder selection and synchronization scope](../../../rules/cloudformation.md#deployorder-selection-and-synchronization-scope) for resolved scope, deferred consumers and dependencies. For CLI read [method and local lifecycle](../../../rules/cloudformation.md#method-and-local-lifecycle) and [preflight and fixed Snapshot](../../../rules/cloudformation.md#preflight-and-fixed-snapshot), not SDK preparation.

## SDK Stack

Use the current Task selector, target and every fixed StackName on every operation; use `--aws-account-id` instead of `--alias` where applicable and the configured `--profile` when needed:

```console
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action advance
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action sync --sync-stack <StackName>
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action checkpoint --sync-stack <StackName>
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action status
```

Repeat `--stack` for the full fixed scope and `--sync-stack` for an indivisible selected candidate. `advance` already reads current AWS before a bounded turn; do not mechanically precede it with `status`. Use `status` for independent inspection or when current request/recovery evidence requires it. `sync` saves current observations and publishes; `checkpoint` resumes an already saved candidate without another observation or AWS execution. Inspect returned stage, cause and `nextAction`/`nextActions`; a null or missing command is not permission to guess. Approval uses `--approve-change-set <actual-approved-ID>` only after the entire current ChangeSet receives required Human consent. Follow [LLM-controlled short operations](../../../rules/cloudformation.md#llm-controlled-short-operations) and [Explicit operations](../../../rules/cloudformation.md#explicit-operations).

## CLI Stack

Read [Preflight and fixed Snapshot](../../../rules/cloudformation.md#preflight-and-fixed-snapshot) once at preparation; before each relevant operation read [Order, dependencies and S3 delivery](../../../rules/cloudformation.md#order-dependencies-and-s3-delivery), [ChangeSet review and execution](../../../rules/cloudformation.md#changeset-review-and-execution), and, for observations, [Observations, validation and publication](../../../rules/cloudformation.md#observations-validation-and-publication). These are the command and argument authority, including complete paginated Changes, S3 integrity, current identity and input rechecks, original tokens, events and no-resend rules. Read [Interruption and independent recovery](../../../rules/cloudformation.md#interruption-and-independent-recovery) on uncertainty or resume. Never invoke SDK Controller, sync, checkpoint or deploy-publish in CLI mode. The existing observation writer is a local API, not a documented standalone writer command; do not invent one. Stop and report if its guarded use cannot be established.

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

Terraform RulesとHelpに従い、設計済みRoot/workspace/backend/variable inputsと同一Targetを使い、許可されたrepository外の同一保存Planだけapplyする。失敗applyは部分反映を想定し、state/AWSをread-only確認して停止する。成功後は非機密Outputと必要時のstate属性からObservedと生成物を同期する。

## Verify and finish

AWS変更/No Change、Stack別SUCCESS/FAILED/BLOCKED/NOT_STARTED、未反映Output/Export、Observed同期、Markdown/JSON生成、未確定操作を区別する。原因未確定はHuman判断が必要と報告する。

Deploy 結果、現在 Stack 状態、Model 保存、Snapshot 検証、commit・merge、Task 状態を別々に報告する。PUBLICATION_PENDINGはAWS失敗ではなくGitのHuman判断/反映待ちであり、成功Stackを再Deployしない。AWS完了だけでTask全体の完了を報告しない。Task scope/Acceptanceと許可差分を確認し、[Validation policy](../../../rules/loop-engineering.md#validation-policy)の最終検証と全保存/反映の成功後にのみTask完了とする。通常Deployはscoped task loopを使う。offline UTから実AWS成功を主張せず、次phase・scenarioを開始しない。

## 最終保存

以下はSDK方式専用。CLI方式はRulesの非AWS保存・検証・完了・通常finalize手順に従い、これらのController actionへ切り替えない。

LLMがTask終了を決めたときだけ、managed CloudFormationの `--action sync --final` を使う。

```console
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action sync --final
python3 -B framework/scripts/worktree_task.py deploy-publish --task-id <task-id>
python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id>
```

Repeat `--stack` for the entire fixed scope; use `--aws-account-id` instead of `--alias` when applicable, and the configured `--profile` when needed. Use `deploy-publish` only to retry saved Git commits after publication fails; use `finalize` after verified publication.
完全な `--stack` はTask Scopeのまま、 `--sync-stack` は今回観測・保存する対象だけを指定する。
必要観測が保存済みなら省略できる。通常syncはrunningを維持する。
completed契約をModel/Viewと同じprivate候補で検証し、PASS後にだけlive Taskへ採用する。
FAILではrunningと保存済みModel・生成成功物を保持する。失敗・未実行理由・UNKNOWN結果は成功へ変えない。
保存途中は `--action checkpoint` で同じ最終意図を再開し、commit後のGit失敗は
`worktree_task.py deploy-publish` でGitだけを再開する。finalizeは最終候補と公開を確認してcleanupする。
旧要求の追跡終了は正しい対象identityのAWS証拠によって判断し、progress保存後に同じ要求だけを解放する。
状態ファイルの手動削除、Reset、UNKNOWNだけを理由にした旧要求の復活を通常手順にしない。

## DeployOrder selection and synchronization scope

SDK offline Preparation supports repeated `--stack` or inclusive numeric
`--order-from` / `--order-to` bounds. `--service` is optional and only checks the
automatically discovered owner services. Review the resolved StackNames, Resource
ownership and output paths before registration. Resume uses the Task's full fixed
StackName scope for every Controller action, never the original Order selector.
External consumer services are deferred without Model/View writes. Follow
[DeployOrder selection and synchronization scope](../../../rules/cloudformation.md#deployorder-selection-and-synchronization-scope)
for diagnostics, selected validation, external dependencies and CLI boundaries.
