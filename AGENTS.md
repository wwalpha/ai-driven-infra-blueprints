# AGENTS.md

このリポジトリは、リポジトリルートを作業ディレクトリとしてCodexで運用する。

## 常時適用ルール

- repository変更では`tasks/<task-name>.md`をtaskごとの契約として使用する。複数taskの同時進行を許可する。契約のないclean repositoryはidleとし、変更前に今回の契約を登録する。
- 許可するtask typeは`initialization`、`design`、`infrastructure`、`scenario-test`、`governance`、`catalog-maintenance`、`migration`だけとする。
- active promptは今回の変更契約であり、長期的な設計の正本ではない。
- active taskに明記されていない次工程、別taskの作成、別taskの実行へ進まない。
- 対象environment/target/serviceに未解決issueがある間、設計相談・設計保存・implement・deploy/apply・scenarioなど他taskを開始または継続しない。issue調査とhumanが明示した修復、およびdesiredの環境比較・diff.md保存だけを行うtaskを許可する。`framework/rules/loop-engineering.md`のUnresolved issue gateと保存限定taskの免除条件に従い、保存限定taskに設計・model・IaC変更を混ぜず、修復taskに修復以外の変更を混ぜない。
- target directoryは`project.json`のtargetにaliasがあればalias、なければAWS account IDとする。
- 人間向けの現行設計は`docs/designs/<environment>/<target-directory>/`、同じserviceのdesired/observedを保持する機械可読modelは`model/<environment>/<target-directory>/`に置く。
- `docs/system-overview.md`は背景情報のreferenceとし、`UNSET`を一律blockerにしない。
- initialization後のproject、environment、AWS account/region、IaC engineのmachine-readable source of truthは`project.json`とする。
- `project.json`の各targetは任意の`awsProfile`を持てる。設定時はそのprofileを対象targetのAWS CLI／SDK、Terraformのprovider／AWS backendに使用する。未設定時は明示profile、それもなければdefault credential chainを維持する。設定値と異なる明示profileは実行前に拒否し、認証失敗時に別profileへfallbackしない。
- `framework/materials/aws/`は読み取り専用の不変カタログであり、通常taskでは変更しない。
- 変更前にactive promptとtask typeに関係する`framework/rules/*.md`を読む。
- 人間が決めていないresource選択やparameter値を推測しない。不足値は明示して停止する。
- 1 environment/AWS accountにつきCloudFormationまたはTerraformのどちらか一方だけを変更する。同じenvironment/AWS accountに複数aliasがある場合もIaC engineを統一する。
- validate/plan後に全deploymentを一律停止するrepository独自のhuman reviewは設けない。未承認のdelete/replacementを検出した場合だけ、対象、理由、影響、現在の実行状態を説明してhuman確認待ちとし、承認後は同じtaskと同じchange setまたは保存済みplanで継続する。
- deploy/applyは`infrastructure` taskのactive promptが明示的に許可した場合だけ実行する。
- `design` taskのAWS APIはdefaultで禁止し、chatbotが指定した既存resourceの現在値取得をactive promptが明示する場合だけlist/get/describe相当のread-only operationを許可する。AWS mutationは許可しない。
- 生成ARNをobserved valueとして永続化しない。
- task typeに対応するlocal loopを完了前に実行する。

## Task transition

- 契約登録は`framework/scripts/task_contract.py --task-file tasks/<task-name>.md --source <repository外の契約候補file>`を使用する。同時登録を直列化し、競合時は候補を保存しない。既存taskの変更予定fileを追加・変更する場合も、実変更前に同じ競合検査を通す。
- 各chat/processは`BLUEPRINT_TASK_FILE=tasks/<task-name>.md`を指定する。local loopとvalidatorは`--task-file`でも選べる。running taskが複数ある場合は未指定で停止し、別taskへ推測で切り替えない。
- 他taskの登録済み変更は今回のtask type判定とAcceptance checksから分離する。未登録の変更file、変更予定外の生成先、進行中task間の重複は拒否する。
- repository変更前に今回の`tasks/<task-name>.md`を選び、最新依頼のtask type、target、Goalと照合する。別taskの契約を上書きしない。
- task type、target、Goalのいずれかが異なる変更は新しいtaskとする。変更予定fileを`## Modified files`へrepository-relativeの具体的pathで列挙し、既存のrunning taskとの重複を登録前に検査する。未作成fileと契約自身も列挙し、glob、directory、別taskの契約を指定しない。重複があれば新規taskを停止し、既存taskと対象fileを報告する。既存taskを停止・上書きしない。
- read-only調査とchat-only設計相談はrepository taskを開始しない。完了済みtaskの契約はchat-only作業のblockerにしない。
- chat-only設計をrepositoryへ保存する依頼は新しい`design` taskとし、保存前にactive taskを切り替える。
- `## Required changes`の各項目には一意なRequirement IDを付け、`## Acceptance checks`で同じIDへ一つ以上の機械検証を対応付ける。
- Acceptance checkは`changed:<path-or-glob>`、`exists:<path-or-glob>`、`absent:<path-or-glob>`、またはvalidatorへ登録済みの`check:<check-id>`だけを使用する。任意commandをactive taskから実行しない。
- Requirement IDに対応するAcceptance checkまたはtask type固有checkが未実装、未実行、失敗の場合はtaskを完了扱いにしない。
- task実行中にcheck errorで停止する場合は、自task／他task／baselineのどの原因でも今回の契約だけを`suspend`へ変更し、`## Suspension reason`へ失敗check、対象file、具体的errorと必要なrepository外log pathを記載する。local loopは失敗・事前検査error・中断時に自動で行い、単独checkなどでは`task_contract.py --task-file tasks/<task-name>.md --suspend-reason '<具体的な問題>'`を使う。子processの停止後に予約を解放し、他taskの契約や未commit変更は維持する。
- `suspend`契約はfile予約を持たず、他taskの登録を妨げない。再開前に`task_contract.py --task-file tasks/<task-name>.md --resume`でrunning taskとの競合を検査し、成功した場合だけ`running`へ戻す。競合時は理由と`suspend`を保持し、他taskを停止・上書きしない。

## Task boundary

- `design`: `docs/designs/**`と対応する`model/**`を更新し、local validation後に終了する。既存resource取得ではchatbotが選択したpropertyと必要な非ARN current identifierだけを反映できる。IaC、AWS mutation、scenarioへ進まない。
- `infrastructure`: 承認済みdesignを読み、active promptで指定されたIaC、安全確認、許可されたdeploy/apply、成功後の`model/**`のobserved namespace更新とMarkdown生成までを行って終了する。`update` phaseではhumanがtask開始前にmodel propertiesへ手動修正した未commitのintended designをimmutable inputとして許可するが、Codexはintended designやscenarioを変更しない。
- `scenario-test`: `tests/scenarios/**`と`tests/results/<scenario-id>/<environment>/<target-directory>/`だけを作成・更新する。test失敗後に設計変更、IaC修正、redeploy、remediation task作成・実行へ進まない。
- `initialization`、`governance`、`catalog-maintenance`、`migration`: active promptのAllowed pathsと明示scopeだけを実行し、別taskへ進まない。
- infrastructure behaviorが変わってもscenario-test taskを自動作成または自動実行しない。
- scenario-test taskだけが`tests/scenarios/**`と`tests/results/**`を変更できる。
- non-scenario taskのvalidation/deployment結果を`tests/results/**`へ保存しない。verification outputは原則として完了報告だけに記載する。
- `tasks/`には独立した契約だけを置き、task履歴やevidenceを保存しない。Task statusは`running`、`suspend`、`completed`。現在の停止理由はsuspend契約に記載してよい。local loop成功後に今回の契約だけをcompletedへ変更する。suspend契約は再開と未commit差分の所属のため保持し、完了済み契約は未commit差分の所属を保持する間だけ残し、差分がなくなれば削除する。
- scenario evidenceの過去版はGit履歴で追跡し、実行別・timestamp別directoryを追加しない。

## 詳細ルール

- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/cloudformation.md`
- `framework/rules/terraform.md`
- `framework/rules/observed-values.md`
- `framework/rules/scenario-testing.md`
- `framework/rules/loop-engineering.md`

## Project configuration

- 未初期化の配布状態では`project.json`を置かない。
- `docs/system-overview.md`の作成・記入状態に関係なく、`framework/prompts/codex/01_initialize.md`を使用できる。Codexが必要な確定値を質問し、`project.json`とtarget pathを作成する。
- initializationでは現時点で必要値が確定しているtargetだけを登録する。未作成または必要値が未確定のtargetは推測やplaceholderで登録せず、確定後に`framework/prompts/codex/02_add-target.md`のmigrationで追加する。
- environment数、environment名、AWS account数を固定しない。
- 一つのenvironmentにtargetが一件だけならaliasを持たせない。複数targetがある場合は全targetにhuman-confirmed aliasを必須とし、同じAWS account IDを複数aliasへ設定してよい。aliasは同じenvironment内で一意なlower-kebab-caseとし、12桁の数字だけの値を禁止する。
- 1 environment/AWS accountの`IaC engine`は`cloudformation`または`terraform`のどちらか一つとし、同じAWS account IDを持つalias間で統一する。
- humanへ`project.json`の直接編集を要求しない。topology変更は明示されたinitializationまたはmigration taskでCodexが行う。
- `awsProfile`は確定済みの空でない文字列とし、前後の空白、改行、NUL、`UNSET`を禁止する。指定しない場合はkey自体を省略し、credential値を保存しない。profileはtargetごとに設定でき、alias／account／region／IaC engineの制約を変更しない。
- `awsAccountId`はresource作成時の明示的なaccount ID設定・名称componentとtarget identityの正本とする。target directory、selector、task scopeは従来どおりalias、aliasなしは`awsAccountId`を使用する。
- 各targetは任意の`awsExecutionAccountId`を持てる。指定時はASCII数字12桁の文字列とし、未指定時はkeyを省略して`awsAccountId`を実行accountとして使用する。AWS CLI／SDK、CloudFormation、Terraform、既存resource取得、observed値取得、model対AWS比較、scenarioのcaller account検証には実行accountを使用し、不一致・認証失敗ではAWS操作前に停止する。ID設定だけでcredentialは切り替わらず、既存の`awsProfile`／明示profile／default credential chainを使用し、AssumeRoleや別accountへのfallbackを自動追加しない。
- AWS APIの暗黙のaccount context／owner検証とCloudFormationの`AWS::AccountId`は実行accountを使用する。設計に明示したaccount propertyやcross-account参照は書き換えない。名前等に`awsAccountId`が必要で両IDが異なる場合は、`AWS::AccountId`へ置換せず独立した明示parameter／設定値として渡す。通常のresourceの所属accountは実際のAWS実行先で決まり、`awsAccountId`設定だけでは変更できない。
- 同じenvironment/実行accountを持つtargetでもIaC engineを統一する。初期化・target追加では任意の実行account IDを確認し、既存targetへの追加・変更・解除はhumanが明示した`migration` taskでCodexが行う。`awsAccountId`やalias、path、設計、IaCを暗黙に変更せず、AWS接続を行わずlocal validationする。
- `project.json`と一致しないpath/IaC implementationはlocal loopを通さない。

## Generated service model

- catalog propertiesを項目の正本、`model/**/*.properties`をintended designとobserved valueの正本とする。`docs/designs/**`のMarkdown／JSON artifactはmodelから生成する。
- 設計変更は最初に`model/**`へ反映し、`framework/scripts/sync-model.py --write`でMarkdown／JSON artifactを生成する。Markdownを先に修正してmodelへ逆反映しない。
- CloudFormation stackの管理対象はtarget別`model/<environment>/<target-directory>/cloudformation-stacks.properties`を詳細設計の正本とし、同名のMarkdownを生成する。templateとstackは一対一に限定しない。deploy時はStackNameでAWS実体を照合し、設計外stackを自動採用しない。
- 一つのservice propertiesにintended designを`desired.*`、generated current valueを`observed.*`として保持する。
- service propertiesは1 file最大600行、600行超は約550行ずつに分割する（末尾fileは短くてよい）。`<service-id>.properties`をindex入口、`<service-id>/part-001.properties`以降を本文とし、一つの論理service modelとして扱う。保存形式・分割・key/identifier検索は`framework/rules/model-information.md`に従い、入口indexから必要なpartだけを読む。catalog propertiesは分割しない。
- design task、infrastructure `update` phase、成功したAWS mutation後は先に同じservice modelを更新し、service単位で生成・検証し、成功したserviceのMarkdown／JSON artifactを保存する。失敗serviceの生成物は維持し、他serviceの処理を続ける。design taskで既存resourceを取得した場合は確認済みcurrent identifierを`observed.*`へ反映してよい。
- local loopはpropertiesから生成したMarkdown／JSON artifactが保存済み表示と一致しない場合に失敗する。
