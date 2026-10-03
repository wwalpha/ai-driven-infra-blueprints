# Loop Engineering Rules

loop engineeringはmandatoryとする。「各change」はeditor saveごとではなく、active task内のcoherent logical change setごとを意味する。

## Task boundary

- repository変更前に`tasks/active.md`があれば最新依頼のtask type、target、Goalと比較する。変更のないclean repositoryでの`active.md`不在はidle状態として許容する。idle状態から変更を始める場合は、最初のcoherent changeで`tasks/active.md`を作成または上書きする。
- `active.md`がない状態で`tasks/active.md`以外の変更がある場合は、task contract不在としてlocal loopを失敗させる。
- read-only調査とchat-only設計相談はactive taskの切替を要求せず、残っている前taskをblockerにしない。
- loopはactive taskのtask typeとAllowed paths内だけで完結する。
- loop成功後に別taskを作成または実行しない。
- retry中にtask typeまたは作業段階を変更しない。
- infrastructure behaviorの変更を理由にscenario testへ進まない。
- test failureをdesign変更、IaC変更、redeployで自動修正しない。

## Unresolved issue gate

- issue一覧は`issues/<environment>/<target-directory>/issues.md`とする。target directoryはproject.jsonのalias、aliasなしはAWS account IDとする。fileがない場合または空の場合は未解決issueなしとして扱う。
- 一覧に残っている番号付きissue（`1. ...`）はすべて未解決とする。修復・再検証が成功したissueだけを明示された修復scope内で一覧から除去する。解決履歴はGitで保持し、一覧削除・書換えだけで修復済みと扱わない。issueが0件なら`未解決issueなし`と記載してよい。
- serviceは`### <service-id>`、`<!-- issue-service: <service-id> -->`、または同じtargetのmodel properties／詳細設計Markdownへの根拠linkで特定する。AWS serviceの表示名だけでは推測しない。所属を特定できないissueや番号付きissue／0件宣言のない不正な一覧はtarget全体を停止する。
- 対象environment/target/serviceに未解決issueがある間、設計相談・設計保存・implement・deploy/apply・scenario・target migrationなど他taskを開始・継続しない。別environment、別target、別serviceは停止しない。複数serviceを変更・実装・deployする場合は関係する全serviceをValidation scopeへ明記し、一件でもblockedならそのtaskを停止する。全体validationとtask対象を混同しない。
- issue調査のread-only操作と、humanが明示したissue修復だけを許可する。新しいtask typeは作らず、design／infrastructureなど既存task boundaryとAWS execution許可を維持する。frameworkだけのgovernance／catalog-maintenanceはservice対象taskではないため、consumer issueでは停止しない。
- 修復taskのGoalとRequired changesに対象issue、原因、修復scopeを記載する。同じactive contractに次のsectionを置く。entryは明示されたValidation scopeの部分集合だけとし、`all`／`framework`による修復例外は禁止する。例外はそのserviceのissue修復と再検証だけに適用し、機能追加・通常の設計・別issueの修復などを混ぜない。修復task完了後に停止中の他taskを自動再開しない。

```md
## Issue remediation

- `dev/cde/ec2`
```

- 対象を確定した時点、task開始前、再開時、設計保存前、AWS mutation前に最新のissue一覧を確認する。開始前は次のcheckを実行する。このcheckは古いactive contractの修復例外を使わない。修復依頼なら停止理由を確認し、humanの依頼scopeに限った修復contractを作成して既存workflowで処理する。既存のactive contractが残っていても、chat-only設計相談のissue停止を解除しない。

```text
python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>
```

`--service`は関係する全serviceについて繰り返す。task validator、`sync-model.py --write`、deploy contextは共通issue判定を実行する。AWS read-only contextはissue調査に使用できるが、通常taskの続行許可を意味しない。deploy/applyは既存preflightに加え、実行直前にも同じissue checkを再実行する。実行直前のcheckには`--task`を付け、同じactive contractのIssue remediationを用いる。通常taskは修復例外なしで再確認する。

## Local loop

OSに依存しないentrypointは`framework/scripts/blueprint-loop.py`とする。command例の`python`は利用可能なPython 3 launcherを意味し、WindowsでPython Launcherだけがある場合は`py -3`、Unix系OSで`python3`だけがある場合は`python3`を使用する。

通常のlocal loopは`blueprint-loop.py --mode task`を使用し、実repository全体の共通checks、Validation scopeのserviceの設計/model checks、task type checks、active task Acceptance checks、必要なframework regression、unstaged/staged両方の`git diff --check`を実行する。変更がある場合はactive taskと有効なTask typeを要求し、変更のないidle状態では前taskのactive.mdが残っていてもtask固有checkを実行しない。一層でも失敗した場合はFAILとする。

active taskの`## Required changes`は一意なRequirement IDを持ち、`## Acceptance checks`で同じIDへ一つ以上のcheckを対応付ける。

```md
- [R1] 実施内容
- [R1] `changed:path/to/file`
```

Acceptance checkは`changed:`、`exists:`、`absent:`、validator登録済み`check:`だけを許可する。任意command、未登録check、対応先Requirement IDがないcheck、checkがないRequirement IDは拒否する。

各coherent logical change後に次を決定的に確認する。

- 変更がある場合はactive task promptと有効なTask typeが存在する。変更のないidle状態では`tasks/active.md`がなくてもよい
- changed pathsがTask type boundaryとAllowed paths内にある
- `tasks/`が存在する場合は`active.md`だけがある。idle状態では`tasks/`ごと省略してよい
- `framework/materials/aws/`が`framework/materials/catalog.sha256`と一致する
- 東京regionのCloudFormation provider schema snapshotがlockと一致し、`framework/materials/aws/`の全property pathを解決できる
- API設計catalog/schemaの固定snapshotとchecksum、選択リスト、CFn非対応定義が整合する。Macie Jobの型・nested値・条件付き必須と正本modelを検証し、CFn型解決で拒否する
- `bucketDefinitions`型Macie JobのMarkdown対応表が同JobのJSON artifactのaccount・bucket・順序と一致し、欠落・重複・別Jobへの所属を拒否する。`bucketCriteria`型には固定bucket対応表を置かない
- `framework/rules/resource-layout.json`がCFn/APIの全catalog resourceの表示方針を過不足なく保持し、統合する親・property・個数・識別方法が有効である。新規resourceの未判定を拒否する
- grouped childの識別、親への所属、schema、参照を検証し、KMSの複数AliasとS3からのAlias参照を失わない
- required directory/file structureが存在する
- `project.json`とenvironment/target directory pathが一致する
- `framework/rules/detailed-design.md`が定める最小Markdown構造、resource table、row numbering、service-based explicit anchorが有効
- service ownership、Markdown/model service metadata、catalog resource type ownershipが一貫し、異なるAWS service resourceが混在しない
- 禁止されたtopology/state file metadataとdesign decisions、out-of-scope、generated-values sectionが存在しない
- resource tableの`Source / Comment`が日本語で記載されている
- resource tableがproperties選択リスト外の設定項目を含まず、literal値が対応するCFn provider schemaまたはAPI設計schemaの型、enum、pattern、長さ、範囲に適合する
- JSONが必要なpolicy propertyが所有service配下の有効なJSON artifactを参照し、service modelのartifact pathと一致する
- 各serviceのpolicy anchorと所有resource、全Statement要素または全設定要素がリンク先JSONと一致し、派生表示をmodelへ重複保存していない。IAMを含む全policyでProperty、JSON、Version、Idの独立metadata行を省略する。信頼ポリシーのVersionはJSONに存在する場合だけ1列表へ表示し、JSONと照合する。元の設定rowの正式propertyとJSONリンク、JSON本文のVersion/Id、設定表内の同名key、全serviceの3列一覧を維持する。marker欠落、不正な所属、表だけの修正を拒否する。policy表示方式の登録は正式catalog propertyとprovider schemaに一致する
- IAM inline policyのStatement内のSidが存在する場合は文字列かつ16文字以内であり、超過を自動修正していない
- IAM Roleのtrust policyとinline policy artifactが、Role logical IDおよび明示された`PolicyName`に基づくsemantic filenameを使用する
- `IAM.Role.RoleName`が正確に1 rowあり、確定済みnon-empty literalである。一覧のResourceName、詳細heading、anchor、参照linkはRoleNameを使用し、Name tag・表示label・role path・内部logical IDで代替しない
- resource設定表のproperty順がmaterialsのproperties行順と一致する。未選択・非表示項目を無視し、配列要素とgrouped childの所属を維持する。design-only .Name／S3.Regionの特殊表示位置とSG横書き表示を維持し、名前・生成IDの別優先順を使わない
- CREATEの`EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`、`EC2.FlowLog`に1 rowの`.Name`とnon-empty valueが存在し、resource heading identifierと一致する
- CREATEの`EC2.VPCEndpoint`／`EC2.Instance`にcase-sensitiveな`Tags[].Key=Name`と直後の対応する確定済みnon-empty `Tags[].Value`が存在し、一覧・heading・通常の参照linkの表示名と一致する。設計検証・生成は共通helperで必須判定し、display labelによる代替を拒否する
- 名称propertyのない同型単一の独立resourceは、選択済みName tagと既存labelがなければ型名だけの詳細headingと型名由来anchorを生成する。一覧見出しと詳細headingを区別し、非表示logical ID・desired/observed分離を保持する。派生型名をlabelへ保存せず、同型複数件・名称propertyの省略・CREATEの必須Name tag不足への型名表示は拒否する
- resourceModeはCREATE／IMPORTのみ、未指定はCREATEとして検証する。IMPORTだけframework命名coverage・lower-kebab・mandatory Name policyを免除し、Name tagがなければ補完しない。metadataのmodel／表示一致とschema・catalog・参照・row構造の検証を維持する
- cross-service relative linkとexplicit anchorが解決でき、正本modelから同じreferenceが生成されている
- `CodeBuild.Project.Name`がresourceごとに1 rowだけ存在し、確定済みnon-empty literalである。設計検証とmodel生成の共通名称検証で欠落・空値・未確定値・重複を拒否し、Name tagや表示labelで代替していない
- CloudFormation stack詳細設計がある場合は、stack名・templateのファイル名・parameterのファイル名を検証し、generated stack modelとの一致を確認する
- generated ARNが`model/`に存在しない
- modelのservice入口indexと各partが600行以下であり、partの欠落・不正参照・未登録・重複keyがない。全partを同じserviceとしてscope・task境界・生成一致・observedを検証する
- scenario/result structureとmetadataが有効
- formatting/static checkが成功する

task type固有checkはactive taskから省略できず、少なくとも次を確認する。

- `initialization`: `project.json`が変更され、target pathとIaC selectionが有効
- `design`: 対象の正本model propertiesを先に変更し、Markdown／JSON artifactがその決定的生成結果と一致
- `infrastructure`: `implement` phaseではIaCが変更され、`deploy` phaseではIaCが未変更。`update` phaseではhuman-changed model properties、生成Markdown、IaCが同じ差分に含まれる。全phaseでscenarioは未変更
- `scenario-test`: scenarioと同じtargetのcurrent resultが変更
- `governance`: active task以外のframework fileが変更
- `catalog-maintenance`: catalog fileと`framework/materials/catalog.sha256`が変更
- `migration`: active task以外のrequired outputが変更

### 生成・検証scope

active taskに`## Validation scope`を置き、各entryを``- `<environment>/<target-directory>/<service-id>` ``とする。aliasがあればtarget directoryはalias、なければAWS account IDを使う。サービスはmodelのfile stem（EC2なら`ec2`）で指定する。environmentだけ、accountだけ、serviceだけの指定、未知target、欠落model/Markdownは停止する。Allowed pathsや変更fileから検証対象を推測しない。scope外の設計変更も拒否する。

```md
## Validation scope

- `dev/cde/ec2`
- `dev/non-cde/ec2`
- `stg/cde/ec2`
- `stg/non-cde/ec2`
```

`sync-model.py --write`と`--mode task`／`--mode local`／`--mode full`は同じValidation scopeを使用する。validatorからmodel照合まで対象serviceを維持し、暗黙に`--all`へ広げない。対象serviceのmodel、生成Markdown/JSON一致、catalog/schema、命名、policy、参照linkを検証する。参照先はlink解決に必要なanchor、名称、logical/current identifier情報だけを読む。参照先service全体のschema・命名・生成物検証を行わず、prodなど対象外の既存設計エラーをtask失敗理由にしない。task契約、Requirement/Acceptance、変更範囲、project topology、catalog/schema snapshotの完全性、framework構造は共通checkとして維持する。通常design taskでIaC内容やscenario/resultの全面検証を行わない。

複数targetと同一target内の複数serviceは最大4並列で検証し、全workerの終了を待ってscope順で診断を集約する。生成用の候補が揃ってからread-only照合を並列化し、targetとserviceのworker数を掛け合わせない。`--validation-jobs 1`で直列比較できる。別serviceの生成を避けるため、`sync-model.py --write`もactive taskのscopeを使用する。明示した単一target/serviceには`--environment <env> --alias <alias> --service <service-id>`（aliasなしは`--aws-account-id`）を使用できる。

frameworkだけのgovernance/catalog-maintenance/migrationでは``- `framework` ``を明示できる。全serviceの実設計検証は明示した`--all`またはValidation scopeの単独``- `all` ``だけで行う。scopeが欠落している場合は`full`でも停止し、全体検証へfallbackしない。日次の全体検証は別途設定したscheduleで実行する。対象限定検証の後に「念のため」の全体検証を追加しない。


### 成功した検証結果の再利用

通常のtask/localではcatalogとserviceの成功結果だけをrepository外のOS一時directory `blueprint-validation-cache`へ保存し、内容hashが一致する場合に再利用する。`BLUEPRINT_VALIDATION_CACHE_DIR`でrepository外の保存先を指定できる。file名・file集合・SHA-256、Python/OS、framework全入力（validator/generator/rule/catalog/schemaを含む）、projectとAGENTS、対象modelの入口・part、Markdown・JSON・参照先のmodel/表示をkeyへ含める。参照先の内容は無効化判定に読み取るだけで、scope外serviceのschema検証を追加しない。mtimeだけで判定しない。

新規入力、内容変更、追加・削除file、cache欠落/破損、不明dependency、symlinkでは成功結果を再利用せず、明示scope内を再検証する。検証中の入力変更はFAILとし、そのservice結果を保存しない。task契約、Requirement/Acceptance、issue gate、変更範囲、project topology、model part構造、scope全体のresource所有権とstack重複、IaC/deploy安全確認、Git差分checkは毎回実行する。scopeを変更pathから推測したり、scope外の全体検証へfallbackしない。cacheはAWS現在値、change set、plan、account/region確認を代替しない。

`--fresh`は成功結果の再利用を無効化する。`--mode full`と`--all`もfresh検証する。実行中だけのカタログ一覧/model行/path再利用はfreshでも使用し、次の実行へ持ち越さない。再利用service数・実行service数を表示し、再利用した検証件数も成功件数へ含める。60秒を超えた検証を打ち切ってPASSにしない。

### 通常taskとframework regression

- 通常のdesign、implement、deploy、update、scenario/evidence、initialization、target migrationは`python framework/scripts/blueprint-loop.py --mode task`を使用する。Validation scopeを引き継ぐ`validate-blueprint.py`と、その内部のservice指定`sync-model.py`によるpropertiesとgenerated Markdown／JSONの一致、active task contract、task固有check、`git diff --check`を維持する。
- framework script、rule、validator/generator、共通処理の変更taskは`python framework/scripts/blueprint-loop.py --mode full`を使用する。指定scopeのvalidationに加え、`framework/scripts/*.checks.py`全件を最大2並列で実行し、診断と失敗一覧を名前順に集約する。fixture、mock、固定catalog入力のframework自身のregressionだけを通常taskから分離する。
- `task`／`local`でも、unstaged、staged、untrackedの変更pathが`framework/**`、`.agents/**`、`AGENTS.md`、`README.md`にあれば全regressionを自動追加する。scriptsだけでなくrules、materials（catalog/schema snapshot）、将来のschema/catalog directory、promptと配布skillも対象にする。削除・rename元も検出する。Gitで変更を判定できなければ停止し、regressionを省略しない。commit済み変更の再検証には明示的な`full`を使用する。
- `--mode local`も`task`と同じ対象限定検証として有効とする。skillが`local`を指定する場合はその実行でよく、追加の`task`／`full`を要求しない。明示`--all`は全体検証＋全regression、`local`のscope `all`も従来どおり全体検証＋全regressionとする。`full`単独やframework変更によるregression追加は実設計scopeを広げない。
- validatorが失敗してもregressionと差分checkを継続する。Python最適化によるassert無効化を防ぐ。選択したcheckの失敗・未実行はFAILとする。
- CloudFormationの`cfn-lint`、deploy context、`aws cloudformation validate-template`、change set／change summary、delete/replacement確認、AWS account/region確認、およびTerraformのfmt/init/validate/plan/applyの既存必須手順は各phaseのrules/promptどおり維持する。loopはこれらの実IaC/deployment手順を代替せず、implementとdeployを統合しない。

### 競合解消と再現可能な検証

- 起動は`python -X utf8 framework/scripts/blueprint-loop.py --mode task`を推奨する。通常起動でもrunnerはUTF-8 modeで再起動し、子processへ`PYTHONUTF8=1`と`PYTHONIOENCODING=utf-8`を継承する。検証前に日本語のfile読書きと子process出力を確認し、失敗時は回帰を開始しない。text入出力ではUTF-8を明記する。
- 競合解消後、検証したいfileと今回の`tasks/active.md`をstageしたうえで、`--staged --base <比較元commit>`を指定する。比較元はhumanの変更範囲に合うcommitを明示し、incomingも比較元との差分に含める。未解決のindex conflictは停止する。通常modeは従来どおりunstaged/staged/untrackedを検証する。
- staged modeは比較元commit、HEAD、index treeを固定し、repository外の独立Git repositoryへ展開して、そのsnapshotにあるrunner、契約、入力を検証する。元workspaceの未stage変更やuntracked fileは含めず、元indexは書き換えない。snapshot内のHEADを比較元にすることで契約・変更path・差分checkも同じ基準を使う。終了時に元HEAD/index treeが変わっていればstaleとして非zero終了し、旧treeの結果を最新状態のPASSと扱わない。直後の編集までロックするものではない。
- 選択検証は`--mode task --affected`（`local`も可）で明示する。通常の全回帰自動追加に対する例外とし、runner内の明示対応表だけでcheckを選ぶ。現在の限定対象は既存の回帰script自身の変更とstandalone loop runnerの変更だけとする。共通validator/generator、rule、catalog、prompt、削除・rename元など対応不明のframework変更は全回帰へfallbackする。incomingであることだけを理由に省略しない。
- `--affected`は`full`／`--all`と併用できない。共通validation、task固有check、Acceptance checks、差分checkは省略しない。選択理由・選択check・未実行checkを表示する。framework開発taskの完了には従来どおり`--mode full`を使う。
- 回帰fixtureは必要なframework入力とテスト内生成のproject/task/modelだけで構成し、実consumerのissues、project、model、設計、active taskをコピーしない。filesystem pathは`Path`で比較し、Markdown linkなどPOSIX表記が契約の値だけ`as_posix()`で検証する。
- 独立した回帰scriptだけ最大2並列とし、validatorとGit差分checkは直列にする。`--jobs 1`で直列比較できる。checkごとに一時fixtureを所有し、共有workspaceへ書き込まない。失敗後も残りを実行し、中断時は実行中の子processを停止する。

### 時間計測と長時間実行

- local loopは実行ごとにrepository外のOS一時directoryへ`blueprint-loop-*`directoryを作成し、絶対pathを開始時に表示する。`--log-dir <repository外のdirectory>`で保存先の親directoryを指定できる。同時・再実行時も既存ログを上書きしない。一時directoryはOSの清掃対象なので、継続保存が必要な場合はrepository外の保存先を指定する。
- `--profile`指定時は`validate-blueprint.py`とその`sync-model.py`子process、`model_design.checks.py`と`design_catalog.checks.py`をstdlib cProfileで計測し、同じrun directoryへ`.prof`とcheck log内の累積時間上位25件を保存する。cold検証の計測には`--fresh`も指定する。fixture copy、catalog読込、生成・検証の関数別内訳を確認する。計測自体のoverheadがあるため、通常実行の時間と直接比較しない。thread worker内部の関数はcProfileの主thread計測に含まれないため、詳細比較には`--validation-jobs 1`を使う。
- `timing.jsonl`へUTC時刻、repository、Python launcher、loop/checkのPID、開始・終了、check別・全体の経過秒数、終了code、成否を逐次記録する。所要時間にはmonotonic clockを使用し、失敗後も全checkを実行する。checkのstdout/stderrはcheck別`.log`へ直接保存し、check終了時にterminalへ表示する。
- checkが30秒以上動いている場合は30秒ごとにcheck名・経過時間・PIDをterminalと`timing.jsonl`へ表示・保存する。これは子プロセスが未終了であることを示す稼働表示であり、処理の進捗率やCopilot sessionの延命を保証しない。
- エージェントはlocal loopを一度だけ起動し、既存実行のログとPIDを追跡する。toolの待機・追跡timeoutだけで再起動しない。check終了までrepositoryのinputを変更せず、同じrepositoryのloopを重複起動しない。無変更・未完了の実行へfocused checkやfull loopを追加しない。
- session切断時は同じactive taskを読み直し、開始時のログpathを確認する。`loop_end`の成否・check終了code・全checkの実行と検証中のinput不変を確認する。`loop_end`欠落は未完了であり、heartbeatがあるだけではPASSにしない。PIDは再利用されるためcommand・実行開始時刻も照合する。実プロセスが終了済みで、完了記録がない場合だけ全loopを再実行する。inputが変わった場合は以前のPASSを流用しない。
- VS Code Copilotのコマンド追跡が長時間実行に追いつかない場合は、humanが通常のterminalから同じlocal loopを実行し、エージェントは保存済みログを確認する。設定・session error・terminal追跡の切り分けはREADMEの手順に従い、検証を省略して回避しない。
- この時間計測ログはnon-scenario taskで明示的に許可されたローカル診断出力として扱い、`tasks/`や`tests/results/`へ保存・commitしない。

## Design task completion

1. active promptで指定された`model/**`の正本propertiesを更新する。既存resource取得が指定された場合だけ、repository変更前にread-only AWS contextを検証し、humanが選択したresourceの選択済みpropertyを現在値へ直接差分反映する。
2. 既存resource取得では必要な非ARN current identifierだけをmodelのobserved rowへ反映する。secret、generated ARN、resource出自を保存しない。
3. 確定済み設計値を対応する`model/**`へ先に保存する。`framework/scripts/sync-model.py --write`はservice単位に正本propertiesのschema/catalog必須root propertyを生成前に検証し、不足serviceのMarkdown／JSON artifactとpolicy表は一時fileも生成しない。propertiesは入力として保持し、不足するresource／propertyを報告する。必須項目が揃ったserviceだけ一時生成・検証し、成功したserviceを同じcoherent changeへ保存する。`bucketDefinitions`型Macie Jobの対応表もmodelのdocumentから生成する。失敗serviceの保存済みMarkdown／JSONを維持し、他serviceの処理を続ける。失敗が残る場合は完了扱いにせず、正本propertiesから修正・再実行する。
4. local loopを実行する。
5. IaC、AWS mutation、scenario、resultを変更せずtaskを終了する。

## Infrastructure task completion

infrastructure taskのTask contractには`Infrastructure phase`を正確に1件記載し、`implement`、`deploy`、`update`のいずれかだけを許可する。

`implement` phase:

1. 承認済みdesignとservice modelをinputとして、active promptで指定されたIaCだけを作成または変更する。
2. CloudFormationはtarget region指定の`cfn-lint`、Terraformは`terraform fmt -check`、`terraform init -backend=false`、`terraform validate`でlocal static validationする。
3. AWS API、CloudFormation change set、Terraform plan、deploy/apply、observed value更新を行わない。
4. local loopを実行して終了する。

`deploy` phase:

1. 作成・検証済みIaCを変更せず、deterministic preflightを実行する。
2. CloudFormationは`cfn-lint`、`aws cloudformation validate-template`、change set、Terraformはvalidationと保存済みplanでscopeを確認する。
3. 未承認のdelete/replacementがなければactive promptが許可した対象だけをdeploy/applyする。未承認のdelete/replacementがあれば、対象、理由、影響、現在の実行状態を説明してhuman確認待ちとし、承認後に同じtaskと同じchange setまたは保存済みplanで再開する。
4. 成功したAWS mutationがある場合だけmodelのobserved valueを更新し、Markdownを再生成する。
5. local loopを実行し、scenario testへ進まず終了する。

`update` phase:

1. humanがtask開始前に手動修正した未commitのmodel propertiesだけをimmutable intended-design inputとして確定する。
2. propertiesからMarkdownを生成し、対象IaCを作成・変更してlocal static validationする。
3. deterministic preflight、change setまたはplanのscope確認を行う。未承認のdelete/replacementは説明付きhuman確認待ちとし、承認後に同じtaskと同じchange setまたは保存済みplanで許可されたdeploy/applyを再開する。
4. 成功したAWS mutation後だけmodelのobserved valueを更新し、Markdownを再生成する。
5. humanのintended-design diffをCodexが変更していないことを確認し、local loop後にscenario testへ進まず終了する。

## Scenario-test task completion

1. active promptで指定されたscenario definitionとtest implementationを作成または更新する。
2. 指定されたenvironment/target directoryに対応するAWS accountに対してtestを実行する。
3. 同じscenario-scoped current resultとstable evidence fileを更新する。
4. scenario変更後に再実行しないresultを`STALE`または`NOT_EXECUTED`へ更新する。
5. local loopを実行し、failure remediationや別taskへ進まず終了する。

## Other task completion

- `initialization`、`governance`、`catalog-maintenance`、`migration`はactive promptのscopeだけを検証して終了する。
- non-scenario taskは`tests/scenarios/**`または`tests/results/**`へverification outputを保存しない。
- non-scenario taskのverification結果はdefaultではCodexの完了報告だけに記載する。

## Retry and stop

- 同じactive task、同じtask type、同じlogical failure classのautomatic correctionは最大3 iterationとする。
- material progressなしで同じerrorが2回続いた場合は停止する。
- missing human inputを値の発明で直さない。
- out-of-scope file changeで停止する。
- 未承認のdelete/replacementはfailureまたはautomatic retryとして扱わず、説明付きhuman確認待ちにする。承認されない場合はdeploy/applyを実行せず停止する。
- `framework/materials/aws/`がbaselineと異なる場合は停止する。
- passのためにfailing checkを抑制しない。

validate/plan後に全deploymentを一律停止するhuman reviewは要求しない。未承認のdelete/replacementに対するplan固有のhuman確認と、Codex sandbox/OS permission controlは別の仕組みであり、permissionが必要な操作はrepository ruleにかかわらずplatform controlに従う。

local loopのPASSは実行済みRequirement ID、Acceptance check件数、task type、framework regression script件数を表示する。これらを表示できないgeneric validation結果をtask完了の証明として扱わない。
