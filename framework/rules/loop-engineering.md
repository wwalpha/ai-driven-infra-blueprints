# Loop Engineering Rules

loop engineeringはmandatoryとする。「各change」はeditor saveごとではなく、active task内のcoherent logical change setごとを意味する。

## Task boundary

- repository変更前に最新依頼のtask type、target、Goalをactive taskと比較し、異なる場合は最初のrepository changeで`tasks/active.md`を上書きする。
- read-only調査とchat-only設計相談はactive taskの切替を要求せず、残っている前taskをblockerにしない。
- loopはactive taskのtask typeとAllowed paths内だけで完結する。
- loop成功後に別taskを作成または実行しない。
- retry中にtask typeまたは作業段階を変更しない。
- infrastructure behaviorの変更を理由にscenario testへ進まない。
- test failureをdesign変更、IaC変更、redeployで自動修正しない。

## Local loop

OSに依存しないentrypointは`framework/scripts/blueprint-loop.py`とする。command例の`python`は利用可能なPython 3 launcherを意味し、WindowsでPython Launcherだけがある場合は`py -3`、Unix系OSで`python3`だけがある場合は`python3`を使用する。

local loopはglobal checks、task type checks、active task Acceptance checks、focused check scriptsの順で実行する。一層でも未実行または失敗の場合はFAILとする。

active taskの`## Required changes`は一意なRequirement IDを持ち、`## Acceptance checks`で同じIDへ一つ以上のcheckを対応付ける。

```md
- [R1] 実施内容
- [R1] `changed:path/to/file`
```

Acceptance checkは`changed:`、`exists:`、`absent:`、validator登録済み`check:`だけを許可する。任意command、未登録check、対応先Requirement IDがないcheck、checkがないRequirement IDは拒否する。

各coherent logical change後に次を決定的に確認する。

- active task promptと有効なTask typeが存在する
- changed pathsがTask type boundaryとAllowed paths内にある
- `tasks/`には`active.md`だけがある
- `framework/materials/aws/`が`framework/materials/catalog.sha256`と一致する
- 東京regionのCloudFormation provider schema snapshotがlockと一致し、`framework/materials/aws/`の全property pathを解決できる
- required directory/file structureが存在する
- `project.json`とenvironment/AWS account pathが一致する
- `framework/rules/detailed-design.md`が定める最小Markdown構造、resource table、row numbering、service-based explicit anchorが有効
- service ownership、Markdown/model service metadata、catalog resource type ownershipが一貫し、異なるAWS service resourceが混在しない
- 禁止されたtopology/state file metadataとdesign decisions、out-of-scope、generated-values sectionが存在しない
- resource tableの`Source / Comment`が日本語で記載されている
- resource tableがproperties選択リスト外の設定項目を含まず、literal値がprovider schemaの型、enum、pattern、長さ、範囲に適合する
- JSONが必要なpolicy propertyが所有service配下の有効なJSON artifactを参照し、service modelのartifact pathと一致する
- IAM Roleのtrust policyとinline policy artifactが、Role logical IDおよび明示された`PolicyName`に基づくsemantic filenameを使用する
- 必要なgenerated current identifierが独立sectionではなく該当resource tableの行に存在する
- cross-service relative linkとexplicit anchorが解決でき、generated modelへ同じreferenceが反映されている
- generated ARNが`model/`に存在しない
- scenario/result structureとmetadataが有効
- formatting/static checkが成功する

task type固有checkはactive taskから省略できず、少なくとも次を確認する。

- `initialization`: `project.json`が変更され、target pathとIaC selectionが有効
- `design`: 対象Markdownとgenerated service modelが同じ変更に含まれ、内容が決定的生成結果と一致
- `infrastructure`: 選択済みIaC implementationが変更され、intended designとscenarioは未変更
- `scenario-test`: scenarioと同じtargetのcurrent resultが変更
- `governance`: active task以外のframework fileが変更
- `catalog-maintenance`: catalog fileと`framework/materials/catalog.sha256`が変更
- `migration`: active task以外のrequired outputが変更

`framework/scripts/blueprint-loop.py`はrepository validator成功後、`framework/scripts/*.checks.py`を名前順に全件実行する。focused checkが一件でも失敗または未実行ならlocal loopをPASSにしない。

## Design task completion

1. active promptで指定された`docs/designs/**`を更新する。
2. `framework/scripts/sync-model.py --write`で対応する`model/**`を同じcoherent changeに生成する。
3. local loopを実行する。
4. IaC、observed value、scenario、resultを変更せずtaskを終了する。

## Infrastructure task completion

1. 承認済みdesignとservice modelをinputとして読む。
2. active promptで指定されたIaCだけを作成または変更する。
3. CloudFormationはtarget region指定の`cfn-lint`と`aws cloudformation validate-template`、Terraformはsyntax/static validationを実行し、CloudFormation change setまたはTerraform planを確認する。
4. active promptが明示許可した場合だけdeploy/applyする。
5. 成功したAWS mutationがある場合だけ詳細設計のgenerated current valueを更新し、同じservice modelを再生成する。
6. local loopを実行し、scenario testへ進まずtaskを終了する。

## Scenario-test task completion

1. active promptで指定されたscenario definitionとtest implementationを作成または更新する。
2. 指定されたenvironment/AWS accountに対してtestを実行する。
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
- unauthorized delete/replacementで停止する。
- `framework/materials/aws/`がbaselineと異なる場合は停止する。
- passのためにfailing checkを抑制しない。

validate/plan後にhuman reviewを要求しないrepository ruleと、Codex sandbox/OS permission controlは別の仕組みである。permissionが必要な操作はrepository ruleにかかわらずplatform controlに従う。

local loopのPASSは実行済みRequirement ID、Acceptance check件数、task type、focused check script件数を表示する。これらを表示できないgeneric validation結果をtask完了の証明として扱わない。
