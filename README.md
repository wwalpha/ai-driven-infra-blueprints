# ai-driven-infra-blueprints

human、chatbot、Codexが役割を分け、特定のsystem architectureに依存せずAWS infrastructureを設計・実装・検証するためのrepository blueprintです。配布状態ではprojectやIaC implementationを持ちません。

## Initial setup

1. `framework/prompts/codex/01_initialize.md`をCodexへ渡す。Codexが初期化に必要なproject、environment、必要な場合だけalias、AWS account、region、IaC engineを一問一答で順番に確認する。
2. 現時点で必要値が確定しているtargetだけを回答する。未作成または必要値が未確定のenvironment／logical targetは初期化対象に含めない。
3. Codexが回答から`project.json`と定義済みtarget pathを作成し、全targetで未選択のIaC engine directoryを削除する。
4. 未確定だったtargetは、必要値の確定後に`framework/prompts/codex/02_add-target.md`をCodexへ渡して追加する。
5. initializationまたはmigration taskの完了後は終了し、design taskを自動作成または自動実行しない。

`docs/system-overview.md`は初期化とは独立した任意の背景資料です。初期化前でも後でも、分かる範囲だけを記入できます。初期化後のproject topologyのmachine-readable source of truthは、Codexが生成する`project.json`です。humanがJSONを直接作成・編集する手順はありません。environment名、environment数、AWS account数はblueprintで固定しません。

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
- `framework/scripts/sync-model.py`: human-readable詳細設計からdesired/observedを含むservice modelを決定的に生成する
- `project.json`: Codexがinitialization時に生成するmachine-readable project topology
- `tasks/active.md`: 現在実行する一つのtask contract。次のtask開始時に上書きする

## Task transition

repositoryを変更する新しい依頼を受けた場合、Codexは最新依頼のtask type、target、Goalを現在の`tasks/active.md`と比較します。いずれかが異なる場合は新しいtaskとして扱い、最初のrepository changeで`tasks/active.md`を上書きします。

read-only調査と`framework/prompts/chatbot/service-design.md`によるchat-only設計相談はrepository taskではありません。前taskの契約が残っていても質問や設計相談のblockerにしません。確定設計をrepositoryへ保存する時点で、chatbotが出力した自己完結型Codex promptを実行し、新しい`design` taskへ切り替えます。

active taskの`Required changes`は一意なRequirement IDを持ち、同じIDの`Acceptance checks`へ対応させます。local loopはglobal invariant、task type固有check、active taskのAcceptance check、focused check scriptを実行し、未対応または未実行のrequirementがある場合はFAILします。

## Context priority

1. `README.md`
2. `project.json`（存在する場合）
3. `docs/system-overview.md`
4. `docs/designs/**/*.md`
5. taskに関係する`framework/rules/*.md`
6. taskに関係する`framework/materials/aws/*.properties`
7. taskに関係する`framework/materials/cloudformation-schema/ap-northeast-1/*.json`
8. `model/`
9. userが明示的に許可した外部情報

`docs/system-overview.md`はsystem背景のreference、`project.json`は初期化後のproject target設定、`docs/designs/**/*.md`はenvironment/target directory別・AWS service別の詳細設計の正本とする。必要な情報が不足または矛盾する場合は推測せず、humanへ確認する。

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
4. humanが決める設計値だけで完成できる場合は、完成形の詳細設計Markdownと必要なJSON artifactをfile単位で出力する。
5. 既存AWS resourceの現在値を使用する場合は、chatbotが対象service、resource type、propertyを確定し、完成Markdownの代わりにread-only取得を含む自己完結型Codex promptを出力する。
6. Codexのdesign taskはtarget contextを検証し、resource候補をhumanが選択した後、選択済みpropertyを詳細設計へ直接差分反映して`model/**`を生成する。

chatの完了報告と保存対象Markdownは分離します。chatとMarkdownの説明文は日本語とし、保存対象Markdownの正本形式は`framework/rules/detailed-design.md`に従います。policyなどJSON documentが必要な確定設計は、同ruleのservice-owned JSON artifactとしてMarkdownから参照します。service modelはMarkdownから生成し、design taskはCloudFormation/Terraform、AWS mutation、scenario、scenario resultを変更しません。既存resource取得では必要な非ARN current identifierだけをobserved valueへ反映できます。

## Post-design SDD

新規設計では、`framework/prompts/chatbot/service-design.md`が出力したCodex promptで詳細設計とmodelを生成し、`03_implement.md`でIaCを作成・検証し、別taskの`04_deploy.md`でdeploy/applyする。

既存詳細設計をhumanが直接変更し、未commit差分をIaCへ反映してdeploy/applyまで行う場合は、`framework/prompts/codex/05_update.md`だけを使用する。`03_implement.md`、`04_deploy.md`を個別に実行しない。

どちらのworkflowでもapplication behavior確認が必要な場合だけ、deploy完了後に別taskで`framework/prompts/codex/06_scenario-test.md`を使用する。詳細な使い分けは`framework/prompts/README.md`を参照する。

## Operating model

1. humanが独立したtaskのtypeと対象scopeを決める。
2. Codexはactive prompt、`AGENTS.md`、関連rulesを読み、同じtask type内だけで作業する。
3. `design` taskはintended designとservice modelを更新して終了する。既存resource取得が明示された場合だけ、read-only AWS APIによる現在値の直接差分反映を含める。
4. `infrastructure` taskの`implement` phaseはIaC作成とlocal static validationまでで終了する。
5. 別の`infrastructure` taskの`deploy` phaseは既存IaCを変更せず、CloudFormation change setまたはTerraform planを確認してdeploy/applyし、成功後のobserved value更新までで終了する。
6. `infrastructure` taskの`update` phaseはhumanの未commit詳細設計を変更せず、model同期、IaC反映、deploy/apply、observed value更新までを一つのtaskで行う。
7. `scenario-test` taskは別途開始し、指定scenarioのtestとcurrent resultだけを更新する。
8. scenario testが失敗しても、同じtaskでdesign変更、IaC修正、redeploy、remediation task作成へ進まない。

non-scenario taskのverification outputはdefaultではrepositoryへ保存せず、Codexの完了報告に記載します。

## Framework distribution

`framework/`だけを共通資産の配布単位とします。既存repositoryへ同期する場合は、配布元repositoryのrootで次を実行します。

```console
python framework/scripts/sync-existing-files.py --target <target-repository>
```

このcommandは`<target-repository>/framework/**`だけを追加・更新します。projectごとに変わる`project.json`、`docs/`、`infra/`、`model/`、`tasks/`、`tests/`はコピーまたは変更しません。`AGENTS.md`と`README.md`は各repositoryのentrypointとしてrootに残します。

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
tasks/active.md
docs/
  system-overview.md
  designs/<environment>/<target-directory>/
model/
  <environment>/<target-directory>/<service-id>.properties
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

- `docs/designs/<environment>/<target-directory>/`はhuman-readable current designの正本。
- `model/<environment>/<target-directory>/<service-id>.properties`は同じserviceのdesired/observedを保持するmachine-readable model。手動編集しない。
- 一つのMarkdownとproperties pairは一つのAWS service ownership boundaryだけを所有し、同じservice ID、相対path、file stemを使う。
- service間dependencyはfile統合やdesign valueの複製ではなく、relative Markdown linkとexplicit anchorで表し、generated modelへ同じreferenceを保持する。
- policy JSONは`docs/designs/<environment>/<target-directory>/<service-id>/<artifact-id>.json`へ保存し、Markdownの参照をgenerated modelへそのまま反映する。
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

## Materials catalog

`framework/materials/aws/`はAWS CloudFormation Resource Specificationから作成したcurated partial catalogで、詳細設計へ載せる候補項目を選択します。廃止せず、provider schemaの全項目を設計書へ機械的に掲載する用途には使いません。

- provenanceと件数: `framework/materials/catalog.properties`
- file integrity: `framework/materials/catalog.sha256`
- check: `python framework/scripts/update-catalog-lock.py`
- authorized catalog maintenance後のlock更新: `python framework/scripts/update-catalog-lock.py --write`

通常のproject taskでは`framework/materials/aws/*.properties`を変更しません。不足resourceがある場合は、source specification versionと対象resourceを明示した専用catalog-maintenance taskで更新します。

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

## Required changes

- [R1] 確定済み詳細設計を保存する。
- [R2] service modelを生成する。

## Acceptance checks

- [R1] `changed:docs/designs/<environment>/<target-directory>/**`
- [R2] `changed:model/<environment>/<target-directory>/**`

## Allowed paths

- `docs/designs/**`
- `model/**`
- `tasks/active.md`
```

local loop:

```console
python framework/scripts/blueprint-loop.py --mode local
```

command例はPython 3 launcherを`python`と表記する。WindowsでPython Launcherだけがある場合は`py -3`、Unix系OSで`python3`だけがある場合は`python3`へ、各command先頭の`python`を置き換える。

local loopはtask type、infrastructure phase、task scope、project topology、catalog/schema integrity、schema-backed design value、service model、observed ARN、IaC engine selection、scenario/result structureを検証します。System Overviewの`UNSET`は検証失敗にしません。通常はIaC作成とdeploy/applyを別taskにし、humanが手動修正した設計の反映だけは専用`update` phaseで一つのtaskとして実行します。
