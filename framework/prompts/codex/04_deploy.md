# Infrastructure Deployment Prompt

## Normal startup

独立DeployはHumanに`/worktree`の追加指定を要求せず、[Managed Deploy snapshot](../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication)に従い`worktree_task.py deploy-start --task-id <id>`で作成/同一Task再利用する。返されたrootでTask登録・Preparation・実行を行う。再開時は元Snapshot/progress/current requestを保持し、未完了操作のRecoverと新規Deployを区別する。

承認済みIaCをTask範囲でDeployし、AWS・Observed・生成物を確認する。Human指定のenvironment・Target・Region/profile・StackName・service IDsを確定し、`project.json`の同一Targetと`tasks/<task-name>.md`を確認する。認証失敗時に別credentialへ切り替えない。DeployはIaC、意図した設計、scenarioを変更しない。

CloudFormationは現在入力とAWS実状態から独立実行する。現在Taskを明示選択し、type/phase/status、AWS許可、Deployment scopeと出力Allowed pathsの不足は停止する。開始時にSDK方式またはCLI方式を明示し、Human指定があれば従い、指定がなければLLMが選択して報告する。既存呼出しはSDK方式を維持できる。SDKは既存Python Controller+boto3、CLIはLLMの実行ツールから直接AWS CLIを使う独立経路とし、途中・再開・保存障害で自動切替しない。権限と安全制約はRulesを正本とする。

## Read before changing files

AGENTSのセクション読込規則に従い、各段階の操作前に原本を読む。現在のTaskと`project.json`を確認し、新Taskは最初の変更として登録する。Preparationの契約候補は原本を直接確認し、target-summaryは表示用として扱う。

- 登録前: [Task transition](../../rules/task-contract.md#task-transition) (including its required common and conditional reads)、[Task boundary](../../rules/task-contract.md#task-boundary)、[Acceptance contract](../../rules/task-contract.md#acceptance-contract)、[Topology](../../rules/project-configuration.md#topology)、[Credentials and account](../../rules/project-configuration.md#credentials-and-account)。
- CloudFormation AWS実行前: [Common rules](../../rules/cloudformation.md#common-rules)、[AWS execution context](../../rules/cloudformation.md#aws-execution-context)、[Resource mode boundary](../../rules/cloudformation.md#resource-mode-boundary)、[Deployment validation and execution](../../rules/cloudformation.md#deployment-validation-and-execution)、[LLM-controlled short operations](../../rules/cloudformation.md#llm-controlled-short-operations)、[Managed Deploy snapshot and Git publication](../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication)、[Model authority](../../rules/model-information.md#model-authority)、[Resource management mode](../../rules/model-information.md#resource-management-mode)、[CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy)、[Policy account selection](../../rules/detailed-design.md#policy-account-selection)、[CloudFormation Stack detailed design](../../rules/detailed-design.md#cloudformation-stack-detailed-design)、[Properties format](../../rules/model-information.md#properties-format)。
- Observed・生成前: [Identifier lifecycle](../../rules/observed-values.md#identifier-lifecycle)、[Collection and propagation](../../rules/observed-values.md#collection-and-propagation)、[Observation publication](../../rules/observed-values.md#observation-publication)、[Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation)。必要なservice Modelと参照Producerのみ確認し、権限を推測で拡張しない。
- 完了前: [Validation policy](../../rules/loop-engineering.md#validation-policy)、[Validation scope](../../rules/loop-engineering.md#validation-scope)、[Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)。
- 該当時は操作前に[Delete and replacement confirmation](../../rules/cloudformation.md#delete-and-replacement-confirmation)、[S3 deployment artifacts](../../rules/cloudformation.md#s3-deployment-artifacts)、[Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair)、[Independent controller runs and execution timing](../../rules/cloudformation.md#independent-controller-runs-and-execution-timing)を読む。
- Terraformは[Terraform Rules](../../rules/terraform.md)、[Properties format](../../rules/model-information.md#properties-format)、[Local loop](../../rules/loop-engineering.md#local-loop)と上記共通のTask・Model・Observed・完了条件を読む。

CLI選択時はさらに[Direct AWS CLI deployment](../../rules/cloudformation.md#direct-aws-cli-deployment)を操作前に全て読む。上のSDK Controller専用実装手順はCLIへの呼出し命令ではない。共通の安全要件・Snapshot・Model正本・Observed・Validation・Gitの意味を維持し、AWS取得/変更は直接CLIで行う。次節から「Unfinished AWS operation recovery」までのController/Preparation/共有要求記録の手順、およびExternal IaC repair handoffと最終保存のSDK手順はSDK方式に限定する。

## Direct AWS CLI method

RulesのCLI手順を正本とし、各AWS JSON応答と終了コードを確認してからLLM自身が次の操作を決める。`cloudformation-deploy.py`の全action、SDK Preparation、boto3/botocore呼出し、PythonからのAWS CLI起動、SDK Scheduler/Journal/共有AWS排他は使わない。共通backend/interface/Journal/lockを作らない。

1. `aws --version`、必要option、Task、Profile/Region/Accountを確認し、`aws sts get-caller-identity`で認証する。IaC/parameters/artifact/Model/Taskの開始Snapshotを固定し、Stack/依存・DeployOrder/MaxConcurrentStacksを確認する。AWS CLI runtimeはPython SDKの別途導入を要求しないが、CLI Taskに確認済みAccount/Region/Partitionを宣言し、ローカルModel参照でもSDKメタデータを使わない。
2. 対象だけを`describe-stacks` / `list-change-sets` / `list-stack-resources`で確認する。固定Template/Parametersをローカル検証し、必要S3 objectを規則どおり配置・再確認する。`validate-template`にはCreateと同じ固定bytes/URLを渡す。
3. 元tokenと送信意図を先に保持して`create-change-set`する。`describe-change-set`で作成完了と全Changes/入力を確認し、未承認Remove/Replacement=True/ConditionalはHumanの全体承認を待つ。ChangeSet確認前のExecuteや`aws cloudformation deploy`による迂回は禁止する。
4. 同じStackId/ChangeSetIdの状態・承認内容・固定入力・配送/依存・競合を直前再確認し、元ClientRequestTokenで`execute-change-set`する。各Stackの`describe-stacks`と`describe-stack-events`を直接取得し、今回tokenのroot eventsと現在状態から成功/失敗/rollback/未確定を区別する。送信成功はDeploy成功ではない。
5. LLMが同Orderの独立Stackだけを並列上限内で進める。失敗時は後Orderを進めず、停止が必要な場合も受付済み要求を追跡する。中断時は元Stack/ChangeSet/token、全eventsと未完了操作を再確認する。応答喪失を理由に無条件再送せず、証拠不足/他主体の競合で停止する。SDKとの同一Stack同時変更は保証しない。
6. 現在Outputs/Physical IDを直接取得し、既存の非AWS Model writerで許可されたobserved Rowだけ保存する。View生成、Snapshot Validation、最新base候補検証、Git publication、Task完了を別々に判定する。SDK `sync`/`checkpoint`は代用しない。全AWS要求の確定と必要な保存・生成・scoped task loopの成功後に`task_contract.py --complete`、通常のWorktree `finalize`を使用する。CLI分岐はSDK進捗・証跡を要求せず、completedを含む実際の最新base候補を検証して公開する。SDK-bound TaskをCLIへ変換しない。

CLIでrollback/delete/bootstrapや署名付きSDK修復handoffを推測で実行しない。安全に復旧できないときはAWS現在状態・元要求・不足証拠・必要なHuman判断を報告して停止する。AWS成功後の保存/生成/Git障害を理由に再Deployしない。実行例と全停止条件はRulesのCLI節に集約する。

## CLI entrypoints

ここからのPython CLI entrypointは既存SDK方式用。直接AWS CLI方式は前節とRulesの実行例を使用する。

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

この節はSDK方式専用。

同じ Task・Target・完全な `--stack` 範囲を使い、LLM が操作を選ぶ。

1. `--action status` は最新 AWS と今回の試行・保存状況を別々に表示する。
2. `--action advance` は最新状態から限定された AWS 操作を一回進める。固定入力、DeployOrder と並列数、未承認 delete/replacement の承認境界を守る。同 Order の独立 Stack は失敗した peer によって一律停止しない。後 Order の開始には前 Order の成功が必要。
3. `--action sync --sync-stack <StackName>` は成功・失敗・rollback・部分適用・未実行・実行中・取得不能の現在事実を保存し、生成・必須 Snapshot 検証・commit・Git publication まで行う。LLM が時機と対象を決め、不可分な候補は全対象を繰り返す。別の checkpoint 操作は通常不要。
4. `--action checkpoint --sync-stack <StackName>` は保存済み候補の検証・commit・統合だけを再開する互換操作。AWS を再実行せず、再観測も要求しない。

Model は原子的に先に保存する。View 生成失敗でも古い Model に戻さず、生成可能なサービスを保存し、失敗 View と原因を報告する。未確認識別子は observed 値を削除し、古いラベル・cache・実行入力に戻さない。Desired と実行済 Consumer の実設定を推測で変更しない。

途中 sync 後は同じ running Task/Worktree と固定 IaC・parameters・artifact で継続する。全体の必要生成・Snapshot 検証が済み AWS 要求が確定した最終候補には completed を含め、その同じ候補を検証・commit・merge する。Deploy FAIL は FAIL のまま保存し、Snapshot PASS と Git 完了なら Task を終了できる。AWS 実行中・送信不確定は追跡を残して running を維持する。個別 checkpoint や全 Stack SUCCESS は終了条件ではない。

Git PENDING/CONFLICT は AWS 結果と独立する。保存済み commit のみを `worktree_task.py deploy-publish --task-id <id>` で再開する。commit 成功・merge 失敗でローカル Task が completed でも、AWS 再実行や元観測のやり直しは不要。競合は file/base/source/影響を示して既存の Human 明示判断を受け、最新統合先を含む候補を検証する。強制統合・自動競合解決はしない。

Sub Agent、Model 背景 writer、固定間隔同期、Python によるエージェント制御は使わない。同じ Worktree の入力を保存中に編集しない。`--action` を明示し、状態確認には `status`、保存・公開には `sync` / `checkpoint` を選ぶ。

## Correct this Task's preparation omissions

この節はSDK方式で固定済みの契約訂正専用。CLI方式の不足証拠をSDK progressで補わない。

固定後の契約訂正は[Self recovery](../../rules/task-contract.md#self-recovery)と
[Deploy correction conditions](../../rules/cloudformation.md#managed-deploy-contract-correction)を読む。
元Human依頼と固定時の原文を比較し、同じ対象serviceの観測保存・生成に必要だった
Modified files／Allowed pathsの記載漏れだけを判断する。Goal・対象・実行入力・AWS権限・
Human同意の拡大は訂正扱いしない。ハッシュ一致は意味判断や承認の証明ではない。

同じTaskを既存操作でsuspendし、現在のstatus／Suspension reasonを保った外部候補を作る。
内部状態を手動変更せず、次を使う。

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-name>.md --correct-deploy-contract <absolute-candidate.md>
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-name>.md --check-resume-scope
```

成功してもsuspendを維持する。全停止原因が安全に訂正済みの自分の準備ミスだけであり、
他の阻害がないと確認したときだけ、既存の`--resume`を使い失敗した検査から再開する。
AWS再実行やTask完了は訂正の結果として行わない。元契約原文や固定入力証拠の不足、未確定要求、
保存途中のObserved／生成／checkpoint、未完了Git公開、修復handoff、同時変更はその理由で停止・保持する。
保存中断のintentが残った場合だけ同じ候補・同じ訂正コマンドで安全性を再検証する。
未対応の契約訂正や状態を別Taskへの付け替え・無条件再固定・進捗削除で回避しない。

## Confirm unapproved delete/replacement

[Delete and replacement confirmation](../../rules/cloudformation.md#delete-and-replacement-confirmation)とTerraformの[Validation and execution](../../rules/terraform.md#validation-and-execution)が正本。Remove、Replacement=True/Conditional等の未承認変更がある場合だけHuman承認を待つ。Stack/ChangeSet IDまたは保存Plan、全対象・Action・Replacement・PolicyAction、既知の物理Resourceとデータ/アクセス/可用性への影響を説明する。不明な影響は未確認と明示する。部分承認で実行しない。

同じTask・Target・入力と今回承認された実IDを使う。実行時再検証を省略せず、変更・再作成・期限切れ・中断後に旧承認を流用しない。変更のない通常Deployを一律に承認待ちにしない。

## Unfinished AWS operation recovery

この節の共有要求記録・ロック・ResolverはSDK方式専用。CLIはRulesの独立した再開手順で同じ現在AWS/identity要件を確認する。

通常開始・再開は対象 Stack の最新 AWS 状態を先に取得する。旧 Task、mode、StackStatus、expectedOutputs、Observed、checkpoint/Git、特定の修復経路の証明は現在状態の採用・次の試行の条件にしない。UPDATE_COMPLETE だけで今回の Desired 適用済みとは判断せず、固定入力から ChangeSet を判定する。

共有記録は account/Region/StackName ごとの現在の未確定要求だけ。送信直前に同一 Stack ロック下で intent を保存し、応答喪失時は元の StackId・ChangeSetId・token を維持する。直前 Execute が不確定なら、単一の古い COMPLETE 読み取りで新 token の Execute を許可しない。現在 ChangeSet・token event を確認し、AWS 要求が決着したら Model/Git を待たず記録を終了する。破損時は当該 Stack の新しい変更だけを保留し、独立 Stack や Model 保存・Git 統合を止めない。

REVIEW_IN_PROGRESS は ChangeSet と合わせて判断する。UPDATE_ROLLBACK_COMPLETE は今回失敗と次回更新可否を分ける。ROLLBACK_COMPLETE、rollback failed は AWS 制約に従う。構造化された不存在だけ ABSENT、取得不能は UNKNOWN。Output 欠落、削除履歴、不完全な一覧、保持リソースを不存在と混同しない。


Export は共通 Resolver で必要名だけを解決する。既知 Producer は scoped DescribeStacks、未知だけ必要な ListExports を使う。古い Task の Outputs 一致を現在値保存条件にしない。同期や Git 障害を理由に AWS を再実行しない。

## External IaC repair handoff

この署名付きhandoffはSDK方式専用。CLI失敗からSDK証跡を作り直す経路ではない。

[Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair)と[Worktree repair lifecycle](../../../.agents/skills/worktree/SKILL.md#explicit-cloudformation-repair-handoff)が権限・ライフサイクルの正本。CloudFormationの現在Taskに`External IaC repair: allowed`がある場合だけ、今回の署名付き失敗証拠、正確なIaCと承認済Modelから原因を診断する。`repairFailure`の存在は修復の証明ではない。

承認待ち・認証/権限・設計不足・依存待ち・送信不明は修復依頼の根拠にしない。未完了操作/publicationの確定後、原因と入力/Model証拠が揃った場合だけ`deploy_handoff.py --help`所定の単発依頼を作る。親をsuspendし、別Implement Worktreeにexact IaC pathsだけを許可する。子のAWS API execution/AWS mutation/Deploy/applyは禁止。同一child/requestのstatic検証は最大3回、検証済みexact commit/paths/bytesだけff-only統合する。

親の明示resume後は最新IaC/AWSによる独立Deployとし、必要なHuman承認も新しく取る。無制限の修復・Deploy連続起動は禁止。証拠の保持・明示破棄・cleanupは既存CLI/Worktree規則に従い、秘密値や推測原因を記録しない。

## Terraform

Terraform RulesとHelpに従い、設計済みRoot/workspace/backend/variable inputsと同一Targetを使い、許可されたrepository外の同一保存Planだけapplyする。失敗applyは部分反映を想定し、state/AWSをread-only確認して停止する。成功後は非機密Outputと必要時のstate属性からObservedと生成物を同期する。

## Verify and finish

AWS変更/No Change、Stack別SUCCESS/FAILED/BLOCKED/NOT_STARTED、未反映Output/Export、Observed同期、Markdown/JSON生成、未確定操作を区別する。原因未確定はHuman判断が必要と報告する。

Deploy 結果、現在 Stack 状態、Model 保存、Snapshot 検証、commit・merge、Task 状態を別々に報告する。PUBLICATION_PENDINGはAWS失敗ではなくGitのHuman判断/反映待ちであり、成功Stackを再Deployしない。AWS完了だけでTask全体の完了を報告しない。Task scope/Acceptanceと許可差分を確認し、[Validation policy](../../rules/loop-engineering.md#validation-policy)の最終検証と全保存/反映の成功後にのみTask完了とする。通常Deployはscoped task loopを使う。offline UTから実AWS成功を主張せず、次phase・scenarioを開始しない。

## 最終保存

以下はSDK方式専用。CLI方式はRulesの非AWS保存・検証・完了・通常finalize手順に従い、これらのController actionへ切り替えない。

LLMがTask終了を決めたときだけ、managed CloudFormationの `--action sync --final` を使う。
完全な `--stack` はTask Scopeのまま、 `--sync-stack` は今回観測・保存する対象だけを指定する。
必要観測が保存済みなら省略できる。通常syncはrunningを維持する。
completed契約をModel/Viewと同じprivate候補で検証し、PASS後にだけlive Taskへ採用する。
FAILではrunningと保存済みModel・生成成功物を保持する。失敗・未実行理由・UNKNOWN結果は成功へ変えない。
保存途中は `--action checkpoint` で同じ最終意図を再開し、commit後のGit失敗は
`worktree_task.py deploy-publish` でGitだけを再開する。finalizeは最終候補と公開を確認してcleanupする。
旧要求の追跡終了は正しい対象identityのAWS証拠によって判断し、progress保存後に同じ要求だけを解放する。
状態ファイルの手動削除、Reset、UNKNOWNだけを理由にした旧要求の復活を通常手順にしない。
