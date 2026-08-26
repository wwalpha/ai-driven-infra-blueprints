# ai-driven-infra-blueprints

human、chatbot、Codexが役割を分け、特定のsystem architectureに依存せずAWS infrastructureを設計・実装・検証するためのrepository blueprintです。配布状態ではprojectやIaC implementationを持ちません。

## Initial setup

1. `prompts/codex/initialize-repository.md`をCodexへ渡す。Codexが初期化に必要なproject、environment、AWS account、region、IaC engineを一問一答で順番に確認する。
2. 現時点で必要値が確定しているtargetだけを回答する。未作成または必要値が未確定のenvironment/AWS accountは初期化対象に含めない。
3. Codexが回答から`project.json`と定義済みtarget pathを作成し、全targetで未選択のIaC engine directoryを削除する。
4. 未確定だったtargetは、必要値の確定後に`prompts/codex/add-project-target.md`をCodexへ渡して追加する。
5. initializationまたはmigration taskの完了後は終了し、design taskを自動作成または自動実行しない。

`docs/system-overview.md`は初期化とは独立した任意の背景資料です。初期化前でも後でも、分かる範囲だけを記入できます。初期化後のproject topologyのmachine-readable source of truthは、Codexが生成する`project.json`です。humanがJSONを直接作成・編集する手順はありません。environment名、environment数、AWS account数はblueprintで固定しません。

## Repository instructions

- `README.md`: repository全体の役割、情報優先順位、workflow
- `prompts/chatbot/*.md`: 初期設計などで都度使用するAsk指示
- `prompts/codex/initialize-repository.md`: 必要値をhumanへ確認し、topologyとrepositoryを初期化する指示
- `prompts/codex/add-project-target.md`: 初期化後に確定したtargetを1件追加するmigration指示
- `prompts/codex/apply-design.md`: chatで確定した詳細設計を保存し、LLM mirrorを生成するdesign指示
- `prompts/codex/implement-infrastructure.md`: 承認済み詳細設計を選択済みIaCへ変換し、deterministic preflight、安全確認、許可されたdeploy/apply、deploy完了確認を実行する指示
- `prompts/codex/run-scenario-test.md`: deployとは別taskでapplication behaviorを検証する指示
- `scripts/check-deploy-context.py`: topology、credential、deploy先account、region、IaC engine、必要commandを確認するpreflight
- `scripts/sync-design-mirror.py`: human-readable詳細設計からLLM design mirrorを決定的に生成する
- `project.json`: Codexがinitialization時に生成するmachine-readable project topology
- `tasks/active.md`: 現在実行する一つのtask contract。次のtask開始時に上書きする

## Task transition

repositoryを変更する新しい依頼を受けた場合、Codexは最新依頼のtask type、target、Goalを現在の`tasks/active.md`と比較します。いずれかが異なる場合は新しいtaskとして扱い、最初のrepository changeで`tasks/active.md`を上書きします。

read-only調査と`prompts/chatbot/initial-service-design.md`によるchat-only設計相談はrepository taskではありません。前taskの契約が残っていても質問や設計相談のblockerにしません。確定設計をrepositoryへ保存する時点で`prompts/codex/apply-design.md`を使用し、新しい`design` taskへ切り替えます。

active taskの`Required changes`は一意なRequirement IDを持ち、同じIDの`Acceptance checks`へ対応させます。local loopはglobal invariant、task type固有check、active taskのAcceptance check、focused check scriptを実行し、未対応または未実行のrequirementがある場合はFAILします。

## Context priority

1. `README.md`
2. `project.json`（存在する場合）
3. `docs/system-overview.md`
4. `docs/designs/**/*.md`
5. taskに関係する`rules/*.md`
6. taskに関係する`materials/aws/*.properties`
7. taskに関係する`materials/cloudformation-schema/ap-northeast-1/*.json`
8. `llm/designs/`と`llm/actuals/`
9. userが明示的に許可した外部情報

`docs/system-overview.md`はsystem背景のreference、`project.json`は初期化後のproject target設定、`docs/designs/**/*.md`はenvironment/AWS account別・AWS service別の詳細設計の正本とする。必要な情報が不足または矛盾する場合は推測せず、humanへ確認する。

## Task contract and types

active promptの`## Task contract`には次を正確に1件記載します。

```md
- Task type: `<task-type>`
```

許可するtask type:

- `initialization`: 必要値をhumanへ確認し、project topologyとtarget pathを初期化する。
- `design`: 詳細設計と対応するLLM design mirrorを更新し、local validation後に終了する。
- `infrastructure`: 承認済みdesignをinputとしてIaCを変更し、安全確認、許可されたdeploy/apply、成功後のactuals更新までで終了する。
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
- design taskでは詳細設計とLLM design mirrorまでで終了する
- infrastructure taskではIaC safety check、許可されたexecution、actuals更新までで終了する
- scenario-test taskではscenarioとcurrent resultだけを変更する
- task完了後に次工程へ自動的に進まない

## Initial detailed design

初期設計はAsk workflowとし、実装は独立した`design` taskで行います。

1. system overview、既存設計、関連materialsを確認する。
2. 必須serviceの前提となる未設計serviceを優先する。
3. 通常5〜8個の設計判断を一つのbatchとして質問する。
4. 必須判断が揃ったら、完成形の詳細設計Markdownと必要なJSON artifactをfile単位で出力する。
5. `prompts/codex/apply-design.md`のdesign taskで`docs/designs/**`を保存し、`llm/designs/**`を生成してlocal validation後に終了する。

chatの完了報告と保存対象Markdownは分離します。chatとMarkdownの説明文は日本語とし、保存対象Markdownの正本形式は`rules/detailed-design.md`に従います。policyなどJSON documentが必要な確定設計は、同ruleのservice-owned JSON artifactとしてMarkdownから参照します。LLM mirrorはMarkdownから生成し、design taskはCloudFormation/Terraform、actuals、scenario、scenario resultを変更しません。

## Post-design SDD

- humanは`docs/designs/<environment>/<aws-account-id>/<service-id>.md`を現在設計として変更する。
- design taskは変更された詳細設計と対応するLLM design mirrorだけを同期して終了する。
- IaC反映が必要な場合は、別の`infrastructure` taskを明示的に開始する。
- scenario確認が必要な場合は、infrastructure task完了後に別の`scenario-test` taskを明示的に開始する。

IaC実装には`prompts/codex/implement-infrastructure.md`を使用する。対象environment、AWS account、implementation scope、deploy/apply許可を確認し、`scripts/check-deploy-context.py`がcredentialとdeploy contextを検証してから、選択済みのCloudFormationまたはTerraformだけを実装する。deploy完了確認とactual更新までで`infrastructure` taskを終了し、application behaviorは別taskで`prompts/codex/run-scenario-test.md`を使用して検証する。

## Operating model

1. humanが独立したtaskのtypeと対象scopeを決める。
2. Codexはactive prompt、`AGENTS.md`、関連rulesを読み、同じtask type内だけで作業する。
3. `design` taskはintended designとLLM mirrorを更新して終了する。
4. `infrastructure` taskはIaC syntax/static validation、CloudFormation change setまたはTerraform planを確認する。これらはscenario testではない。
5. active promptが許可した場合だけdeploy/applyし、成功後のcurrent actuals更新まででinfrastructure taskを終了する。
6. `scenario-test` taskは別途開始し、指定scenarioのtestとcurrent resultだけを更新する。
7. scenario testが失敗しても、同じtaskでdesign変更、IaC修正、redeploy、remediation task作成へ進まない。

non-scenario taskのverification outputはdefaultではrepositoryへ保存せず、Codexの完了報告に記載します。

## Repository structure

```text
AGENTS.md
project.json  # initialization後にCodexが生成
prompts/
  chatbot/
    initial-service-design.md
  codex/
    apply-design.md
    initialize-repository.md
    implement-infrastructure.md
    run-scenario-test.md
rules/
tasks/active.md
materials/
  catalog.properties
  catalog.sha256
  aws/
  cloudformation-schema.properties
  cloudformation-schema.sha256
  cloudformation-schema/ap-northeast-1/
docs/
  system-overview.md
  designs/<environment>/<aws-account-id>/
llm/
  designs/<environment>/<aws-account-id>/
  actuals/<environment>/<aws-account-id>/
infra/
  cloudformation/  # CloudFormationを選択したtargetがある場合だけ
    templates/
    parameters/<environment>/<aws-account-id>/
  terraform/  # Terraformを選択したtargetがある場合だけ
    environments/<environment>/<aws-account-id>/
scripts/
  blueprint-loop.py
  check-deploy-context.py
  sync-design-mirror.py
  update-catalog-lock.py
  validate-blueprint.py
tests/
  scenarios/<scenario-id>/
  results/<scenario-id>/<environment>/<aws-account-id>/
```

## Design information

- `docs/designs/<environment>/<aws-account-id>/`はhuman-readable current designの正本。
- `llm/designs/<environment>/<aws-account-id>/`は同じintended designから生成されるmachine-readable mirror。手動編集しない。
- 一つのMarkdownとproperties pairは一つのAWS service ownership boundaryだけを所有し、同じservice ID、相対path、file stemを使う。
- service間dependencyはfile統合やdesign valueの複製ではなく、relative Markdown linkとexplicit anchorで表し、generated mirrorへ同じreferenceを保持する。
- policy JSONは`docs/designs/<environment>/<aws-account-id>/<service-id>/<artifact-id>.json`へ保存し、Markdownの参照をgenerated mirrorへそのまま反映する。
- topology/state metadataを詳細設計Markdownへ重複させない。Markdownの構造と禁止sectionは`rules/detailed-design.md`を正本とする。
- `llm/actuals/<environment>/<aws-account-id>/`は対象AWS accountから取得した必要最小限のcurrent actual情報。
- 必要なnon-ARN generated current valueは該当resource tableの個別行に置き、deploy前とdestroy後は`PENDING_DEPLOY`とする。
- `llm/designs/**`はintended designとstable referenceだけを保持し、machine-readable current IDは`llm/actuals/**`へ置く。
- generated ARNはcurrent actualとして保存しない。

## Scenario evidence

- scenarioは`tests/scenarios/<scenario-id>/`に置き、stableなlower-kebab-case IDを使う。
- current resultは`tests/results/<scenario-id>/<environment>/<aws-account-id>/`に置く。
- 同じscenario/environment/AWS accountの再実行では同じ`result.md`とstable evidence fileを更新する。
- 実行別またはtimestamp別のresult directory/fileを作らない。
- scenario変更時は既存resultを再実行結果へ更新するか、`STALE`または`NOT_EXECUTED`へ更新する。
- scenario evidenceの過去版はGit履歴で追跡する。
- scenario resultはcurrent actualの正本ではない。

## Materials catalog

`materials/aws/`はAWS CloudFormation Resource Specificationから作成したcurated partial catalogで、詳細設計へ載せる候補項目を選択します。廃止せず、provider schemaの全項目を設計書へ機械的に掲載する用途には使いません。

- provenanceと件数: `materials/catalog.properties`
- file integrity: `materials/catalog.sha256`
- check: `python scripts/update-catalog-lock.py`
- authorized catalog maintenance後のlock更新: `python scripts/update-catalog-lock.py --write`

通常のproject taskでは`materials/aws/*.properties`を変更しません。不足resourceがある場合は、source specification versionと対象resourceを明示した専用catalog-maintenance taskで更新します。

`materials/cloudformation-schema/ap-northeast-1/`は、propertiesで選択した82 resource typeについて公式CloudFormation provider schemaのfull propertyと型・制約を保持します。設計値とCloudFormation templateのproperty名、`type`、`enum`、`pattern`、長さ、範囲、`required`の検証元です。

- provenance: `materials/cloudformation-schema.properties`
- file integrity: `materials/cloudformation-schema.sha256`
- offline check: `python scripts/cloudformation_schema.py`
- 公式regional schemaからの明示的なrefresh: `python scripts/cloudformation_schema.py --write`

通常のlocal loopはnetworkへ接続せずsnapshotとpropertiesの対応を検証します。refreshは公式schema更新を取り込む明示的なgovernanceまたはcatalog-maintenance taskだけで実行します。CloudFormation template自体は、target regionを指定した`cfn-lint`でprovider schema validationを行い、続けて`aws cloudformation validate-template`で構文を検証します。

## Validation

active promptには`Task type`と`## Allowed paths`を記載します。Allowed pathsはtask type boundaryを拡張できません。

```md
## Task contract

- Task type: `design`

## Required changes

- [R1] 確定済み詳細設計を保存する。
- [R2] LLM design mirrorを生成する。

## Acceptance checks

- [R1] `changed:docs/designs/<environment>/<aws-account-id>/**`
- [R2] `changed:llm/designs/<environment>/<aws-account-id>/**`

## Allowed paths

- `docs/designs/**`
- `llm/designs/**`
- `tasks/active.md`
```

local loop:

```console
python scripts/blueprint-loop.py --mode local
```

command例はPython 3 launcherを`python`と表記する。WindowsでPython Launcherだけがある場合は`py -3`、Unix系OSで`python3`だけがある場合は`python3`へ、各command先頭の`python`を置き換える。

local loopはtask type、task scope、project topology、catalog/schema integrity、schema-backed design value、design/LLM mirror、actual ARN、IaC engine selection、scenario/result structureを検証します。System Overviewの`UNSET`は検証失敗にしません。IaC validation/planはinfrastructure task、scenario executionはscenario-test taskで別々に実行します。
