# ai-driven-infra-blueprints

human、chatbot、Codexが役割を分け、特定のsystem architectureに依存せずAWS infrastructureを設計・実装・検証するためのrepository blueprintです。配布状態ではprojectやIaC implementationを持ちません。

## Initial setup

1. `framework/prompts/codex/01_initialize.md`をCodexへ渡す。Codexが初期化に必要なproject、environment、必要な場合だけalias、AWS account、region、IaC engineを一問一答で順番に確認する。
2. 現時点で必要値が確定しているtargetだけを回答する。未作成または必要値が未確定のenvironment／logical targetは初期化対象に含めない。
3. Codexが回答から`project.json`と定義済みtarget pathを作成し、全targetで未選択のIaC engine directoryを削除する。
4. 未確定だったtargetは、必要値の確定後に`framework/prompts/codex/02_add-target.md`をCodexへ渡して追加する。
5. initializationまたはmigration taskの完了後は終了し、design taskを自動作成または自動実行しない。

`docs/system-overview.md`は初期化とは独立した任意の背景資料です。初期化前でも後でも、分かる範囲だけを記入できます。初期化後のproject topologyのmachine-readable source of truthは、Codexが生成する`project.json`です。humanがJSONを直接作成・編集する手順はありません。environment名、environment数、AWS account数はblueprintで固定しません。

`project.json`の各targetには任意の`awsProfile`を設定できます。initialization／target追加時にprofile名を指定し、不要なら項目を省略します。

```json
{
  "environment": "dev",
  "awsAccountId": "123456789012",
  "awsRegion": "ap-northeast-1",
  "iacEngine": "cloudformation",
  "awsProfile": "dev-admin"
}
```

設定時はpreflightとCloudFormation controllerが自動使用し、直接のAWS CLIにも`--profile`を付けます（[AWS CLIのnamed profile](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html)）。SDKにはprofileを明示し、Terraformは対象processの`AWS_PROFILE`へ渡します（[AWS providerの認証設定](https://registry.terraform.io/providers/hashicorp/aws/latest/docs#authentication-and-configuration)）。profile未設定時は従来の明示profile／default credential chainを維持します。設定済みprofileと異なる明示profileは実行前に停止します。account／regionの確認も引き続き行います。

一つのenvironmentにtargetが一件だけならaliasを使用しません。複数の論理配置先がある場合は全targetへhuman-confirmed aliasを設定し、異なるaliasへ同じAWS account IDを設定できます。aliasは同じenvironment内で一意なlower-kebab-caseとし、12桁の数字だけの値は禁止します。target directoryはaliasがあればalias、なければAWS account IDです。

## Repository instructions

- `README.md`: repository全体の役割、情報優先順位、workflow
- `framework/`: project間で共通利用するprompt、rule、catalog、validation scriptの一括コピー単位
- `framework/prompts/README.md`: promptの説明、使用時期、使用方法、実行順をまとめたguide
- `framework/prompts/chatbot/*.md`: 初期設計などで都度使用するAsk指示
- `framework/prompts/codex/01_initialize.md`: 必要値をhumanへ確認し、topologyとrepositoryを初期化する指示
- `framework/prompts/codex/02_add-target.md`: 初期化後に確定したtargetを1件追加するmigration指示
- `framework/prompts/chatbot/service-design.md`: 詳細設計fileと、それをrepositoryへ作成する自己完結型Codex promptを出力するAsk指示
- `framework/prompts/codex/03_implement.md`: 承認済み詳細設計を選択済みIaCへ変換し、local static validationまでを行う指示
- `framework/prompts/codex/04_deploy.md`: 作成・検証済みIaCを変更せず、安全確認、deploy/apply、deploy完了確認を行う指示
- `framework/prompts/codex/05_update.md`: humanが手動修正した未commitの詳細設計をIaCへ反映し、deploy/applyまで行う指示
- `framework/prompts/codex/06_scenario-test.md`: deployとは別taskでapplication behaviorを検証する指示
- `framework/scripts/check-deploy-context.py`: topology、credential、deploy先account、region、IaC engine、必要commandを確認するpreflight
- `framework/scripts/sync-model.py`: 設計値の正本model propertiesからMarkdown／JSON artifactを決定的に生成・検証する
- `framework/scripts/model_files.py`: 600行超のmodel propertiesを約550行のpartとservice入口indexへ分割する。`<service.properties> --find '<key-or-logical-id>'`で対象fileと行を検索する。物理分割は明示design/migration taskで`<service.properties> --split`を実行する
- `docs/designs/<environment>/<target-directory>/cloudformation-stacks.md`: CloudFormation targetの管理対象stack、templateと個別parameterのファイル名を記す詳細設計
- `project.json`: Codexがinitialization時に生成するmachine-readable project topology
- `tasks/active.md`: 現在実行する一つのtask contract。次のtask開始時に上書きする。変更のないidle状態では省略できる

## Task transition

repositoryを変更する新しい依頼を受けた場合、Codexは`tasks/active.md`があれば最新依頼のtask type、target、Goalと比較します。`active.md`がないclean repositoryはidle状態です。いずれかが異なる場合、またはidle状態から変更を始める場合は新しいtaskとして扱い、最初のcoherent changeで`tasks/active.md`を今回の契約として作成または上書きします。`active.md`がない状態で他のpathだけを変更した場合はvalidatorが失敗します。

read-only調査と`framework/prompts/chatbot/service-design.md`によるchat-only設計相談はrepository taskではありません。前taskの契約が残っていても質問や設計相談のblockerにしません。確定設計をrepositoryへ保存する時点で、chatbotが出力した自己完結型Codex promptを実行し、新しい`design` taskへ切り替えます。

active taskの`Required changes`は一意なRequirement IDを持ち、同じIDの`Acceptance checks`へ対応させます。local loopはglobal invariant、task type固有check、active taskのAcceptance check、必要なframework regressionと差分checkを実行し、未対応または未実行のrequirementがある場合はFAILします。

## 未解決issueによるtask停止

対象environment／target／serviceの`issues/<environment>/<target-directory>/issues.md`に未解決issueがある間、設計相談・設計保存・implement・deploy/apply・scenarioなど他taskは実施できません。issue調査とhumanが明示した修復だけを許可します。別環境・別target・別serviceは停止しません。task開始前に`framework/scripts/issue_gate.py`で関係する全serviceを確認します。修復契約、一覧形式と停止条件は[Unresolved issue gate](framework/rules/loop-engineering.md#unresolved-issue-gate)に従います。

## Context priority

1. `README.md`
2. `project.json`（存在する場合）
3. `docs/system-overview.md`
4. `docs/designs/**/*.md`
5. taskに関係する`framework/rules/*.md`
6. taskに関係する`framework/materials/aws/*.properties`と`framework/materials/api/*.properties`
7. CFn由来resourceは`framework/materials/cloudformation-schema/ap-northeast-1/*.json`、API resourceは`framework/materials/api/`の同名JSON設計schema
8. `model/`
9. userが明示的に許可した外部情報

`docs/system-overview.md`はsystem背景のreference、`project.json`は初期化後のproject target設定、`model/**/*.properties`はenvironment/target directory別の設計値の正本、`docs/designs/**/*.md`はその生成表示とする。service resourceはAWS service別file、CloudFormation stackはtarget別`cloudformation-stacks.md`に記載する。必要な情報が不足または矛盾する場合は推測せず、humanへ確認する。

## Task contract and types

active promptの`## Task contract`には次を正確に1件記載します。

```md
- Task type: `<task-type>`
```

`infrastructure` taskでは、同じTask contractへ次も正確に1件記載します。

```md
- Infrastructure phase: `<implement-or-deploy-or-update>`
```

許可するtask type:

- `initialization`: 必要値をhumanへ確認し、project topologyとtarget pathを初期化する。
- `design`: 詳細設計と対応するservice modelを更新し、local validation後に終了する。
- `infrastructure`: `implement` phaseでIaCを作成・検証するか、`deploy` phaseで既存IaCをdeploy/applyするか、`update` phaseでhumanの未commit設計差分をIaCへ反映してdeploy/applyする。
- `scenario-test`: scenario、test implementation、実行、scenario-scoped current resultを更新して終了する。
- `governance`: repository ruleやworkflowを変更する。
- `catalog-maintenance`: materials catalogを明示scopeで保守する。
- `migration`: active promptで定義されたmigrationだけを実行する。

各taskは独立してhumanが明示的に開始します。task完了後に次taskを自動作成または自動実行しません。

各active taskは次のmachine-readable completion contractを持ちます。

```md
## Required changes

- [R1] 実施内容

## Acceptance checks

- [R1] `changed:path/to/file`
- [R1] `check:registered-check-id`
```

許可するAcceptance checkは`changed:`、`exists:`、`absent:`、validatorへ登録済みの`check:`だけです。全Requirement IDに一つ以上のcheckが必要です。

## Roles

### Human

- system overviewを必要に応じて記入する
- Ask形式の質問へ回答し、設計判断を承認する
- 実行するtask typeとscopeを決める
- deploy/apply許可を明示する
- 必要なscenario-test taskを別途開始する

### Codex

- active prompt、task type、repository ruleの範囲だけを実行する
- design taskでは詳細設計とservice modelまでで終了する。chatbotが既存resource取得を指定した場合だけread-only AWS APIで選択済みpropertyと必要な非ARN current identifierを反映できる
- infrastructure taskでは`implement`、`deploy`、`update`のいずれか一つだけを実行する
- scenario-test taskではscenarioとcurrent resultだけを変更する
- task完了後に次工程へ自動的に進まない

## Initial detailed design

初期設計はAsk workflowとし、実装は独立した`design` taskで行います。

1. system overview、既存設計、関連materialsを確認する。
2. 必須serviceの前提となる未設計serviceを優先する。
3. 通常5〜8個の設計判断を一つのbatchとして質問する。
4. humanが決める設計値だけで完成できる場合は、完成したmodel propertiesをfile単位で出力し、Markdown／JSON artifactの生成先を示す。
5. 既存AWS resourceの現在値を使用する場合は、chatbotが対象service、resource type、propertyを確定し、完成Markdownの代わりにread-only取得を含む自己完結型Codex promptを出力する。
6. Codexのdesign taskはtarget contextを検証し、resource候補をhumanが選択した後、選択済みpropertyを`model/**`へ直接差分反映してMarkdown／JSON artifactを生成する。

chatの完了報告と保存対象Markdownは分離します。chatとMarkdownの説明文は日本語とし、保存対象Markdownの正本形式は`framework/rules/detailed-design.md`に従います。policyなどJSON documentが必要な確定設計は、同ruleのservice-owned JSON artifactとしてMarkdownから参照します。model propertiesを先に更新してMarkdownとJSON artifactを生成し、design taskはCloudFormation/Terraform、AWS mutation、scenario、scenario resultを変更しません。既存resource取得では必要な非ARN current identifierだけをobserved valueへ反映できます。

## Post-design SDD

新規設計では、`framework/prompts/chatbot/service-design.md`が出力したCodex promptでmodel propertiesを保存して詳細設計Markdownを生成し、`03_implement.md`でIaCを作成・検証し、別taskの`04_deploy.md`でdeploy/applyする。

既存詳細設計をhumanが直接変更し、未commit差分をIaCへ反映してdeploy/applyまで行う場合は、`framework/prompts/codex/05_update.md`だけを使用する。`03_implement.md`、`04_deploy.md`を個別に実行しない。

どちらのworkflowでもapplication behavior確認が必要な場合だけ、deploy完了後に別taskで`framework/prompts/codex/06_scenario-test.md`を使用する。詳細な使い分けは`framework/prompts/README.md`を参照する。

## Operating model

1. humanが独立したtaskのtypeと対象scopeを決める。
2. Codexはactive prompt、`AGENTS.md`、関連rulesを読み、同じtask type内だけで作業する。
3. `design` taskはintended designとservice modelを更新して終了する。既存resource取得が明示された場合だけ、read-only AWS APIによる現在値の直接差分反映を含める。
4. `infrastructure` taskの`implement` phaseはIaC作成とlocal static validationまでで終了する。
5. 別の`infrastructure` taskの`deploy` phaseは既存IaCを変更せず、CloudFormation change setまたはTerraform planを確認してdeploy/applyし、成功後のobserved value更新までで終了する。
6. `infrastructure` taskの`update` phaseはhumanの未commit model propertiesを変更せず、Markdown生成、IaC反映、deploy/apply、observed value更新までを一つのtaskで行う。
7. `scenario-test` taskは別途開始し、指定scenarioのtestとcurrent resultだけを更新する。
8. scenario testが失敗しても、同じtaskでdesign変更、IaC修正、redeploy、remediation task作成へ進まない。

non-scenario taskのverification outputはdefaultではrepositoryへ保存せず、Codexの完了報告に記載します。

## Framework distribution

`framework/`、`.agents/`、rootの`AGENTS.md`と`README.md`を共通資産の配布単位とします。既存repositoryへ同期する場合は、配布元repositoryのrootで次を実行します。

```console
python framework/scripts/sync-existing-files.py --target <target-repository>
```

このcommandは`<target-repository>/framework/**`、`<target-repository>/.agents/**`、rootの`AGENTS.md`と`README.md`を追加・更新します。projectごとに変わる`project.json`、`docs/`、`infra/`、`model/`、`tasks/`、`tests/`はコピーまたは変更しません。`--dry-run`で保存前の差分を確認できます。同期件数はコピー先との内容差分で数えるため、同期対象外の`tasks/active.md`などを含むローカル未commit件数とは一致しない場合があります。summaryに同期範囲と対象外のpathを表示します。

## Repository structure

```text
AGENTS.md
README.md
project.json  # initialization後にCodexが生成
framework/
  chatbot/
  prompts/
    README.md
    chatbot/
      service-design.md
    codex/
      01_initialize.md
      02_add-target.md
      03_implement.md
      04_deploy.md
      05_update.md
      06_scenario-test.md
  rules/
  materials/
    catalog.properties
    catalog.sha256
    aws/
    cloudformation-schema.properties
    cloudformation-schema.sha256
    cloudformation-schema/ap-northeast-1/
  scripts/
    blueprint-loop.py
    check-deploy-context.py
    sync-model.py
    sync-existing-files.py
    update-catalog-lock.py
    validate-blueprint.py
tasks/active.md  # task実行中だけ必要。idle状態では省略可
docs/
  system-overview.md
  designs/<environment>/<target-directory>/
model/
  <environment>/<target-directory>/<service-id>.properties
  <environment>/<target-directory>/cloudformation-stacks.properties  # stack設計がある場合
infra/
  cloudformation/  # CloudFormationを選択したtargetがある場合だけ
    templates/  # aliasなしの共通template
    templates/<alias>/  # alias別template
    parameters/<environment>/<target-directory>/
  terraform/  # Terraformを選択したtargetがある場合だけ
    modules/  # aliasなしの共通module
    modules/<alias>/  # alias別module
    environments/<environment>/<target-directory>/
tests/
  scenarios/<scenario-id>/
  results/<scenario-id>/<environment>/<target-directory>/
```

## Design information

- `docs/designs/<environment>/<target-directory>/`はpropertiesから生成するhuman-readable current design。
- CloudFormation targetでstackをdeployする場合は対応するmodelの`cloudformation-stacks.properties`をstack管理の正本とし、`cloudformation-stacks.md`を生成する。同じtemplateを複数StackNameへ適用でき、各stackに個別parameterのファイル名を記す。stack current statusはAWSで確認し、設計やmodelへ複製しない。
- `model/<environment>/<target-directory>/<service-id>.properties`は同じserviceのdesired/observedを保持するmachine-readableな設計値の正本。確定済み設計はここへ先に反映する。
- service用の一つのMarkdownとproperties pairは一つのAWS service ownership boundaryだけを所有し、同じservice ID、相対path、file stemを使う。stack詳細設計pairはtarget内のdeployment unitを所有する。
- service間dependencyはfile統合やdesign valueの複製ではなく、正本modelのrelative Markdown linkとexplicit anchorで保持し、Markdownへ同じreferenceを生成する。
- policy JSON本文と参照先は正本modelに保持し、`docs/designs/<environment>/<target-directory>/<service-id>/<artifact-id>.json`とMarkdownの参照を生成する。
- topology/state metadataを詳細設計Markdownへ重複させない。Markdownの構造と禁止sectionは`framework/rules/detailed-design.md`を正本とする。
- `desired.*`は確定済みのintended design、`observed.*`は対象AWS accountから取得した必要最小限のgenerated current valueを保持する。
- 必要なnon-ARN generated current valueは該当resource tableの個別行に置き、deploy前とdestroy後は`PENDING_DEPLOY`とする。
- Markdownとservice modelはservice ID、相対path、file stemを一致させ、一対一で生成する。
- generated ARNはobserved valueとして保存しない。

## Scenario evidence

- scenarioは`tests/scenarios/<scenario-id>/`に置き、stableなlower-kebab-case IDを使う。
- current resultは`tests/results/<scenario-id>/<environment>/<target-directory>/`に置く。
- 同じscenario/environment/target directoryの再実行では同じ`result.md`とstable evidence fileを更新する。
- 実行別またはtimestamp別のresult directory/fileを作らない。
- scenario変更時は既存resultを再実行結果へ更新するか、`STALE`または`NOT_EXECUTED`へ更新する。
- scenario evidenceの過去版はGit履歴で追跡する。
- scenario resultはcurrent observed valueの正本ではない。

## CFn非対応resourceの詳細設計

詳細設計に記載できる対象と、選択済みIaC engineで作成できる対象を分離します。`Macie.ClassificationJob`は公式API仕様に基づいて設計し、CFn対応の`Macie.Session`と同じ`macie.md`へ通常のリソース一覧・詳細表で記載できます。両方を同じservice modelに保持します。

- APIの選択リストと固定schema: `framework/materials/api/Macie_ClassificationJob.properties`と同名`.json`
- schema内に公式仕様URL、API version、元SDK modelのhash、確認日、CFn非対応を保持します。clientTokenと生成jobArnは設計項目にしません。
- root propertyを一つのrowにし、nested設定はJSONで保持します。長いobjectはservice配下JSON artifactへ分けられます。型、必須、未知のnested field、単発／定期などの条件をoffline検証します。
- jobIdは`IDENTIFIER_OUTPUT`としてdesiredのlogical referenceとobservedのcurrent IDを分離します。未作成は既存の`PENDING_DEPLOY`を使用します。
- CFn型解決: `python framework/scripts/design_catalog.py --cloudformation-type Macie.Session`は成功し、`Macie.ClassificationJob`は非対応として失敗します。Jobを含む実装要求を、CFn部分だけの実装で完了扱いにしません。
- checksum確認: `python framework/scripts/design_catalog.py`。API catalog/schemaの保守は明示scopeの`governance` taskで行い、仕様・選択リスト・表示定義・focused checksを揃えた後、`python framework/scripts/design_catalog.py --write-lock`で`framework/materials/api-catalog.sha256`を更新します。通常taskでは変更せず、未知のresourceを自動登録しません。

この対応は詳細設計・検証・model生成までです。Job作成の自動化、Custom Resource、Terraformへの切替、consumerへの同期は別の明示依頼で扱います。

## Materials catalog

`framework/materials/aws/`はAWS CloudFormation Resource Specificationから作成したcurated partial catalogで、詳細設計へ載せる候補項目を選択します。廃止せず、provider schemaの全項目を設計書へ機械的に掲載する用途には使いません。

- provenanceと件数: `framework/materials/catalog.properties`
- file integrity: `framework/materials/catalog.sha256`
- check: `python framework/scripts/update-catalog-lock.py`
- authorized catalog maintenance後のlock更新: `python framework/scripts/update-catalog-lock.py --write`

通常のproject taskでは`framework/materials/aws/*.properties`を変更しません。不足resourceがある場合は、source specification versionと対象resourceを明示した専用catalog-maintenance taskで更新します。

resource追加・削除時は`framework/rules/resource-layout.json`の表示方針も同じtaskのAllowed pathsへ含めて更新します。全catalog resourceに独立表示または親への統合を明示し、未判定をlocal loopで拒否します。所属先、複数の子、共有・複数対象、外部参照を確認し、条件付き統合が必要ならその判定と検証を先にframeworkへ実装します。現在はS3 BucketPolicyとKMS Aliasを親の詳細表へ統合し、その他は独立表示を維持します。KMS Aliasの識別marker、参照とmodelは`framework/rules/detailed-design.md`と`framework/rules/model-information.md`に従います。

`framework/materials/cloudformation-schema/ap-northeast-1/`は、propertiesで選択したresource typeについて公式CloudFormation provider schemaのfull propertyと型・制約を保持します。対象件数は`framework/materials/cloudformation-schema.properties`を正本とします。設計値とCloudFormation templateのproperty名、`type`、`enum`、`pattern`、長さ、範囲、`required`の検証元です。

- provenance: `framework/materials/cloudformation-schema.properties`
- file integrity: `framework/materials/cloudformation-schema.sha256`
- offline check: `python framework/scripts/cloudformation_schema.py`
- 公式regional schemaからの明示的なrefresh: `python framework/scripts/cloudformation_schema.py --write`

通常のlocal loopはnetworkへ接続せずsnapshotとpropertiesの対応を検証します。refreshは公式schema更新を取り込む明示的なgovernanceまたはcatalog-maintenance taskだけで実行します。CloudFormation template自体は、target regionを指定した`cfn-lint`でprovider schema validationを行い、続けて`aws cloudformation validate-template`で構文を検証します。

## Validation

active promptには`Task type`と`## Allowed paths`を記載します。Allowed pathsはtask type boundaryを拡張できません。

```md
## Task contract

- Task type: `design`

## Validation scope

- `<environment>/<target-directory>/<service-id>`

## Required changes

- [R1] 確定済み詳細設計を保存する。
- [R2] 正本model propertiesを先に更新し、Markdown／JSON artifactを生成する。

## Acceptance checks

- [R1] `changed:docs/designs/<environment>/<target-directory>/**`
- [R2] `changed:model/<environment>/<target-directory>/**`

## Allowed paths

- `docs/designs/**`
- `model/**`
- `tasks/active.md`
```

通常taskはValidation scopeに指定したserviceの設計/model、生成Markdown/JSON一致、ownership、stack、catalog/schema、命名、policy、reference/link、artifact、active task contractとtask固有checkを検証します。validatorからmodel照合まで指定serviceを引き継ぎます。共通の契約・変更範囲・project topology・catalog整合性チェックは維持します。参照先はlink解決に必要な情報だけを読み、参照先service全体は検証しません。unstaged/staged両方の`git diff --check`もloop内で実行します。CloudFormation/Terraformとdeployの既存必須手順は各phaseのrules/promptどおり別途維持します。

```console
python framework/scripts/blueprint-loop.py --mode task
```

frameworkが未変更なら`*.checks.py`のself-testを省略します。`framework/**`全体（scripts/rules/materials/schema/catalog/prompts等）、`.agents/**`、`AGENTS.md`、`README.md`のunstaged/staged/untracked変更がある場合は全self-testを自動追加します。framework変更taskやcommit済みframework変更の再検証は明示的に次を実行します。

```console
python framework/scripts/blueprint-loop.py --mode full
```

`full`は通常taskのvalidationに加え、全`framework/scripts/*.checks.py`を実行します。実設計の全体検証とframework regressionは別の責務です。framework未変更の`task`はValidation scopeが`all`でもself-testを実行しません。

生成と検証の対象はactive taskの`## Validation scope`で統一します。`task`／`local`／`full`はいずれもそのscopeを使用し、`full`単独では全serviceへ広げません。`local`を指定するskillも対象限定検証だけで完了できます。scope欠落時は停止します。全体検証は明示した`--all`またはscopeの`all`だけで実行します。`--all`と`local`のscope `all`は全self-testも実行します。日次の全体検証は別途設定済みのscheduleに任せ、対象限定検証の後に「念のため」の全体検証を追加しません。

command例はPython 3 launcherを`python`と表記する。WindowsでPython Launcherだけがある場合は`py -3`、Unix系OSで`python3`だけがある場合は`python3`へ、各command先頭の`python`を置き換える。

### Local loopの時間計測

追加指定なしでも、実行ごとにOS一時directoryの`blueprint-loop-*`へ計測ログを保存し、開始時に絶対pathを表示します。継続保存したい場合はrepository外の親directoryを指定します。

```console
python framework/scripts/blueprint-loop.py --mode task --log-dir /tmp/blueprint-loop-logs
```

Windowsでは保存先を例として`C:\Temp\blueprint-loop-logs`へ置き換えてください。一時directoryはOSが削除する場合があるため、長期保存にはrepository外の専用directoryを使用します。各実行は別directoryを作り、以前のログを上書きしません。

| File | 内容 |
| --- | --- |
| `timing.jsonl` | loopとcheckの開始・終了UTC時刻、経過秒数、PID、終了code、成否。30秒ごとの稼働記録も含む |
| `01-validate-blueprint.py.log`など | check別のstdout/stderr。実行中から直接fileへ保存し、check終了時にterminalにも表示 |

所要時間はmonotonic clockで計測します。terminalにはcheckの開始・終了と、30秒ごとのcheck名・経過秒数・PIDが表示されます。稼働表示は子プロセスの未終了を示し、処理の進捗率を示しません。強制終了やOS停止では`loop_end`を残せない場合があります。`loop_end`がなければ未完了として扱います。

2026-10-02にこのframework repository（Mac、未初期化template、既存の全15 focused check）で変更前のlocal loopを計測した結果は、全体38.6秒、repository validator 0.56秒でした。主な内訳は`design_catalog.checks.py`が14.2秒、`model_design.checks.py`が9.6秒、`policy_tables.checks.py`が5.0秒です。別のprofile実行では、`design_catalog.checks.py`の42ケースがmodel検証を子プロセスで繰り返し起動し、その待機が12.8秒を占めました。30〜60分の現象はこの環境では未再現です。consumer repositoryや別OSの時間とは区別してください。

同日の`viewcard-code`の読み取り計測では、全体202.2秒、repository validator 164.6秒、17 focused checkの合計37.7秒でした。設計Markdownは97 file、modelは99 fileあり、変更前は変更対象以外も含めて全targetを検証していました。この時点のvalidatorは既存1451件の診断でFAILし、focused checkも3件がFAILしました（consumer側の2 checkのassert guard不足、IAM fixture不整合、当該PythonのPyYAML不足）。性能調査でこれらは修正していません。計測前後のrepository file内容は一致しました。30〜60分の現象はこの計測でも未再現です。

`viewcard-code`のdev/cdeだけを別途read-onlyでprofileすると、`validate_views`が33回、`linked_resource`が6306回、`expanded_design`が1757回呼ばれ、参照先Markdownの再解析が繰り返されていました。`formal_property`は496495回呼ばれ、Pythonで全resource prefixを順番に調べる処理がprofile上で26.1秒を占めました（profileの計測負荷を含み、これらの時間は親子関係があるため合算できません）。このprefix判定だけを、起動時に構築したtupleに対する標準の`str.startswith(tuple)`へ変更しました。未知prefix・display alias・完全修飾propertyの扱いを維持し、全体の検証結果をcacheで省略しません。参照先の再解析を減らす変更は未実施です。

prefix判定の176入力×500回×3試行の比較では、中央値が0.517秒から0.028秒となり、この判定部分だけ約18.5倍速くなりました。loop全体の高速化倍率やconsumerへ同期後の所要時間を示す値ではありません。

Python checkの処理にはLLMのmodel/reasoning設定を渡していません。luna/maxで遅く見える場合も、まず`timing.jsonl`の実行時間とCopilot側のmodel request・tool待機・再実行の時間を分けて確認します。特定checkだけが遅ければ、例えば次のように標準のprofilerでそのcheckを計測できます。check名とrepository外の保存先は実測結果に合わせて置き換えます。元のloopが終了してから実行してください。

```console
python -B -m cProfile -o /tmp/design-catalog.prof framework/scripts/design_catalog.checks.py
python -m pstats /tmp/design-catalog.prof
```

### VS Code GitHub Copilot Autopilotで待機が止まる場合

1. **実行中のloopを増やさない。** 起動時のログdirectoryを控え、同じ実行の`timing.jsonl`とcheck別`.log`を確認します。toolのtimeoutだけではPythonの停止と断定しません。PIDを確認する際はcommandと開始時刻も照合します。実行中は検証inputを編集しません。
2. **コマンド追跡の終了を切り分ける。** VS Codeの`chat.tools.terminal.enforceTimeoutFromModel`（Experimental）は、agent指定timeoutでコマンドの追跡を終了し、それまでの出力を返す設定です。利用中の版にこの設定があれば、追跡timeoutが原因と確認できた場合に限りworkspace単位で`false`を比較検証し、確認後は元へ戻します。session切断を直す設定ではありません。[公式設定一覧](https://code.visualstudio.com/docs/agents/reference/ai-settings#agent-tools)
3. **通常のterminalから実行する。** 長時間checkはhumanがVS Codeの通常terminalまたはOSのterminalで上記commandを実行し、Copilotには表示されたログpathの確認を依頼します。これでagentのtool待機への依存を減らします。OSのsleepやterminal終了に対する存続は別途確認が必要です。
4. **session停止の証拠を確認する。** `Developer: Set Log Level`でGitHub Copilot / GitHub Copilot Chatを一時的にTraceにし、`Output: Show Output Channels`から同じ時刻のerrorを確認します。Agent Debug Logsがある版ではmodel requestとtool callも照合し、request limit、通信error、extension/terminal異常を分けます。`chat.agent.maxRequests`はrequest回数の上限であり、実行時間の上限ではありません。回数上限が実際に報告された場合だけ設定を見直します。[公式診断手順](https://code.visualstudio.com/docs/agents/agent-troubleshooting/troubleshooting)、[request設定](https://code.visualstudio.com/docs/agents/reference/ai-settings#agent-behavior)
5. **同じtaskで結果を確認する。** 切断後は`tasks/active.md`と保存済みログを読み直します。`loop_end`と全checkの終了があり、検証inputも変わっていないことを確認して成否を報告します。`loop_end`欠落で実プロセスも終了済みの場合は全loopを再実行します。途中ログだけでPASSにせず、別taskへ進みません。

local loopはtask type、infrastructure phase、task scope、project topology、catalog/schema integrity、IaC engine selectionの共通checkと、Validation scope内のdesign value・service model・observed ARNを検証します。IaC内容とscenario/resultのrepository整合性も全体検証に含み、実IaC/deploymentの必須validationは各phaseで別途実行します。System Overviewの`UNSET`は検証失敗にしません。通常はIaC作成とdeploy/applyを別taskにし、humanがmodel propertiesへ手動修正した設計の反映だけは専用`update` phaseで一つのtaskとして実行します。

設計更新の順序は「catalog選択項目と命名ルールを確認 → model propertiesを更新 → 全対象のMarkdown／JSONを一時生成・検証 → 全件成功後に保存」です。生成失敗時は保存済み表示を変更せず、propertiesを正本として修正・再実行します。通常のsyncでMarkdownからmodelを上書きしません。旧形式の採用は明示されたmigration taskの`sync-model.py --import-markdown --write`だけに限定し、既存modelを上書きしません。
