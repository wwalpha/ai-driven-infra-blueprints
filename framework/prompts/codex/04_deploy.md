# Infrastructure Deployment Prompt

## Normal startup

独立DeployはHumanに`/worktree`の追加指定を要求せず、[Managed Deploy snapshot](../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication)に従い`worktree_task.py deploy-start --task-id <id>`で作成/同一Task再利用する。返されたrootでTask登録・Preparation・実行を行う。再開時は元Snapshot/progress/current requestを保持し、未完了操作のRecoverと新規Deployを区別する。

承認済みIaCをTask範囲でDeployし、AWS・Observed・生成物を確認する。Human指定のenvironment・Target・Region/profile・StackName・service IDsを確定し、`project.json`の同一Targetと`tasks/<task-name>.md`を確認する。認証失敗時に別credentialへ切り替えない。DeployはIaC、意図した設計、scenarioを変更しない。

CloudFormationは現在入力とAWS実状態から独立実行する。現在Taskを明示選択し、type/phase/status、AWS許可、Deployment scopeと出力Allowed pathsの不足は停止する。実行・案内はPython CLI、権限と安全制約はRulesを正本とする。

## Read before changing files

AGENTSのセクション読込規則に従い、各段階の操作前に原本を読む。現在のTaskと`project.json`を確認し、新Taskは最初の変更として登録する。Preparationの契約候補は原本を直接確認し、target-summaryは表示用として扱う。

- 登録前: [Task transition](../../rules/task-contract.md#task-transition)、[Task boundary](../../rules/task-contract.md#task-boundary)、[Acceptance contract](../../rules/task-contract.md#acceptance-contract)、[Topology](../../rules/project-configuration.md#topology)、[Credentials and account](../../rules/project-configuration.md#credentials-and-account)。
- CloudFormation AWS実行前: [Common rules](../../rules/cloudformation.md#common-rules)、[AWS execution context](../../rules/cloudformation.md#aws-execution-context)、[Resource mode boundary](../../rules/cloudformation.md#resource-mode-boundary)、[Deployment validation and execution](../../rules/cloudformation.md#deployment-validation-and-execution)、[LLM-controlled short operations](../../rules/cloudformation.md#llm-controlled-short-operations)、[Managed Deploy snapshot and Git publication](../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication)、[Model authority](../../rules/model-information.md#model-authority)、[Resource management mode](../../rules/model-information.md#resource-management-mode)、[CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy)、[Policy account selection](../../rules/detailed-design.md#policy-account-selection)、[CloudFormation Stack detailed design](../../rules/detailed-design.md#cloudformation-stack-detailed-design)、[Properties format](../../rules/model-information.md#properties-format)。
- Observed・生成前: [Identifier lifecycle](../../rules/observed-values.md#identifier-lifecycle)、[Collection and propagation](../../rules/observed-values.md#collection-and-propagation)、[Observation publication](../../rules/observed-values.md#observation-publication)、[Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation)。必要なservice Modelと参照Producerのみ確認し、権限を推測で拡張しない。
- 完了前: [Validation policy](../../rules/loop-engineering.md#validation-policy)、[Validation scope](../../rules/loop-engineering.md#validation-scope)、[Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)。
- 該当時は操作前に[Delete and replacement confirmation](../../rules/cloudformation.md#delete-and-replacement-confirmation)、[S3 deployment artifacts](../../rules/cloudformation.md#s3-deployment-artifacts)、[Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair)、[Independent controller runs and execution timing](../../rules/cloudformation.md#independent-controller-runs-and-execution-timing)を読む。
- Terraformは[Terraform Rules](../../rules/terraform.md)、[Properties format](../../rules/model-information.md#properties-format)、[Local loop](../../rules/loop-engineering.md#local-loop)と上記共通のTask・Model・Observed・完了条件を読む。

## CLI entrypoints

Worktreeでは登録済み共通Pythonをwrapperで使用する。同じPython・PATH/PYTHONPATHを維持し、別Pythonで依存不足を回避しない。

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --help
python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --help
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_handoff.py --help
python3 -B framework/scripts/run-python.py -B framework/scripts/check-deploy-context.py --help
```

Helpの例示Target・パス・IDは今回の確定値へ置換する。JSONの`stage`・`cause`・`nextAction`を確認し、`command: null`では操作を推測しない。案内は権限・承認を与えない。

Preparationはoffline。AIが契約候補と出力範囲を確認してから登録する。登録済みWorktreeでは起動先は短時間の`--action advance`。認証、Stack対応、入力検証、AWS取得、Observed同期・生成は既存Pythonを使い、AIが同種の処理を再実装しない。

## LLM-controlled Stack checkpoints

同じ Task・Target・完全な `--stack` 範囲を使い、LLM が操作を選ぶ。

1. `--action status` は最新 AWS と今回の試行・保存状況を別々に表示する。
2. `--action advance` は最新状態から限定された AWS 操作を一回進める。固定入力、DeployOrder と並列数、未承認 delete/replacement の承認境界を守る。同 Order の独立 Stack は失敗した peer によって一律停止しない。後 Order の開始には前 Order の成功が必要。
3. `--action sync --sync-stack <StackName>` は成功・失敗・rollback・部分適用・未実行・実行中・取得不能の現在事実を保存し、生成・必須 Snapshot 検証・commit・Git publication まで行う。LLM が時機と対象を決め、不可分な候補は全対象を繰り返す。別の checkpoint 操作は通常不要。
4. `--action checkpoint --sync-stack <StackName>` は保存済み候補の検証・commit・統合だけを再開する互換操作。AWS を再実行せず、再観測も要求しない。

Model は原子的に先に保存する。View 生成失敗でも古い Model に戻さず、生成可能なサービスを保存し、失敗 View と原因を報告する。未確認識別子は observed 値を削除し、古いラベル・cache・実行入力に戻さない。Desired と実行済 Consumer の実設定を推測で変更しない。

途中 sync 後は同じ running Task/Worktree と固定 IaC・parameters・artifact で継続する。全体の必要生成・Snapshot 検証が済み AWS 要求が確定した最終候補には completed を含め、その同じ候補を検証・commit・merge する。Deploy FAIL は FAIL のまま保存し、Snapshot PASS と Git 完了なら Task を終了できる。AWS 実行中・送信不確定は追跡を残して running を維持する。個別 checkpoint や全 Stack SUCCESS は終了条件ではない。

Git PENDING/CONFLICT は AWS 結果と独立する。保存済み commit のみを `worktree_task.py deploy-publish --task-id <id>` で再開する。commit 成功・merge 失敗でローカル Task が completed でも、AWS 再実行や元観測のやり直しは不要。競合は file/base/source/影響を示して既存の Human 明示判断を受け、最新統合先を含む候補を検証する。強制統合・自動競合解決はしない。

Sub Agent、Model 背景 writer、固定間隔同期、Python によるエージェント制御は使わない。同じ Worktree の入力を保存中に編集しない。`--action` を明示し、状態確認には `status`、保存・公開には `sync` / `checkpoint` を選ぶ。

## Confirm unapproved delete/replacement

[Delete and replacement confirmation](../../rules/cloudformation.md#delete-and-replacement-confirmation)とTerraformの[Validation and execution](../../rules/terraform.md#validation-and-execution)が正本。Remove、Replacement=True/Conditional等の未承認変更がある場合だけHuman承認を待つ。Stack/ChangeSet IDまたは保存Plan、全対象・Action・Replacement・PolicyAction、既知の物理Resourceとデータ/アクセス/可用性への影響を説明する。不明な影響は未確認と明示する。部分承認で実行しない。

同じTask・Target・入力と今回承認された実IDを使う。実行時再検証を省略せず、変更・再作成・期限切れ・中断後に旧承認を流用しない。変更のない通常Deployを一律に承認待ちにしない。

## Unfinished AWS operation recovery

通常開始・再開は対象 Stack の最新 AWS 状態を先に取得する。旧 Task、mode、StackStatus、expectedOutputs、Observed、checkpoint/Git、特定の修復経路の証明は現在状態の採用・次の試行の条件にしない。UPDATE_COMPLETE だけで今回の Desired 適用済みとは判断せず、固定入力から ChangeSet を判定する。

共有記録は account/Region/StackName ごとの現在の未確定要求だけ。送信直前に同一 Stack ロック下で intent を保存し、応答喪失時は元の StackId・ChangeSetId・token を維持する。直前 Execute が不確定なら、単一の古い COMPLETE 読み取りで新 token の Execute を許可しない。現在 ChangeSet・token event を確認し、AWS 要求が決着したら Model/Git を待たず記録を終了する。破損時は当該 Stack の新しい変更だけを保留し、独立 Stack や Model 保存・Git 統合を止めない。

REVIEW_IN_PROGRESS は ChangeSet と合わせて判断する。UPDATE_ROLLBACK_COMPLETE は今回失敗と次回更新可否を分ける。ROLLBACK_COMPLETE、rollback failed は AWS 制約に従う。構造化された不存在だけ ABSENT、取得不能は UNKNOWN。Output 欠落、削除履歴、不完全な一覧、保持リソースを不存在と混同しない。


Export は共通 Resolver で必要名だけを解決する。既知 Producer は scoped DescribeStacks、未知だけ必要な ListExports を使う。古い Task の Outputs 一致を現在値保存条件にしない。同期や Git 障害を理由に AWS を再実行しない。

## External IaC repair handoff

[Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair)と[Worktree repair lifecycle](../../../.agents/skills/worktree/SKILL.md#explicit-cloudformation-repair-handoff)が権限・ライフサイクルの正本。CloudFormationの現在Taskに`External IaC repair: allowed`がある場合だけ、今回の署名付き失敗証拠、正確なIaCと承認済Modelから原因を診断する。`repairFailure`の存在は修復の証明ではない。

承認待ち・認証/権限・設計不足・依存待ち・送信不明は修復依頼の根拠にしない。未完了操作/publicationの確定後、原因と入力/Model証拠が揃った場合だけ`deploy_handoff.py --help`所定の単発依頼を作る。親をsuspendし、別Implement Worktreeにexact IaC pathsだけを許可する。子のAWS API execution/AWS mutation/Deploy/applyは禁止。同一child/requestのstatic検証は最大3回、検証済みexact commit/paths/bytesだけff-only統合する。

親の明示resume後は最新IaC/AWSによる独立Deployとし、必要なHuman承認も新しく取る。無制限の修復・Deploy連続起動は禁止。証拠の保持・明示破棄・cleanupは既存CLI/Worktree規則に従い、秘密値や推測原因を記録しない。

## Terraform

Terraform RulesとHelpに従い、設計済みRoot/workspace/backend/variable inputsと同一Targetを使い、許可されたrepository外の同一保存Planだけapplyする。失敗applyは部分反映を想定し、state/AWSをread-only確認して停止する。成功後は非機密Outputと必要時のstate属性からObservedと生成物を同期する。

## Verify and finish

AWS変更/No Change、Stack別SUCCESS/FAILED/BLOCKED/NOT_STARTED、未反映Output/Export、Observed同期、Markdown/JSON生成、未確定操作を区別する。原因未確定はHuman判断が必要と報告する。

Deploy 結果、現在 Stack 状態、Model 保存、Snapshot 検証、commit・merge、Task 状態を別々に報告する。PUBLICATION_PENDINGはAWS失敗ではなくGitのHuman判断/反映待ちであり、成功Stackを再Deployしない。AWS完了だけでTask全体の完了を報告しない。Task scope/Acceptanceと許可差分を確認し、[Validation policy](../../rules/loop-engineering.md#validation-policy)の最終検証と全保存/反映の成功後にのみTask完了とする。通常Deployはscoped task loopを使う。offline UTから実AWS成功を主張せず、次phase・scenarioを開始しない。

## 最終保存

LLMがTask終了を決めたときだけ、managed CloudFormationの `--action sync --final` を使う。
完全な `--stack` はTask Scopeのまま、 `--sync-stack` は今回観測・保存する対象だけを指定する。
必要観測が保存済みなら省略できる。通常syncはrunningを維持する。
completed契約をModel/Viewと同じprivate候補で検証し、PASS後にだけlive Taskへ採用する。
FAILではrunningと保存済みModel・生成成功物を保持する。失敗・未実行理由・UNKNOWN結果は成功へ変えない。
保存途中は `--action checkpoint` で同じ最終意図を再開し、commit後のGit失敗は
`worktree_task.py deploy-publish` でGitだけを再開する。finalizeは最終候補と公開を確認してcleanupする。
旧要求の追跡終了は正しい対象identityのAWS証拠によって判断し、progress保存後に同じ要求だけを解放する。
状態ファイルの手動削除、Reset、UNKNOWNだけを理由にした旧要求の復活を通常手順にしない。
