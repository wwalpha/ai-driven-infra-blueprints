# Loop Engineering Rules

loop engineeringはmandatoryとする。「各change」はeditor saveごとではなく、active task内のcoherent logical change setごとを意味する。

## Task boundary

- loopはactive taskのtask typeとAllowed paths内だけで完結する。
- loop成功後に別taskを作成または実行しない。
- retry中にtask typeまたは作業段階を変更しない。
- infrastructure behaviorの変更を理由にscenario testへ進まない。
- test failureをdesign変更、IaC変更、redeployで自動修正しない。

## Local loop

各coherent logical change後に次を決定的に確認する。

- active task promptと有効なTask typeが存在する
- changed pathsがTask type boundaryとAllowed paths内にある
- task directoryには`prompt.md`だけがある
- `materials/aws/`が`materials/catalog.sha256`と一致する
- required directory/file structureが存在する
- System Overviewのproject topologyとenvironment/AWS account pathが一致する
- resource design table、row numbering、relative link、explicit anchorが有効
- design/LLM groupingとreferenceが一貫する
- generated ARNが`llm/actuals/`に存在しない
- scenario/result structureとmetadataが有効
- formatting/static checkが成功する

## Design task completion

1. active promptで指定された`docs/designs/**`を更新する。
2. 対応する`llm/designs/**`を同じcoherent changeで更新する。
3. local loopを実行する。
4. IaC、actuals、scenario、resultを変更せずtaskを終了する。

## Infrastructure task completion

1. 承認済みdesignとLLM designをinputとして読む。
2. active promptで指定されたIaCだけを作成または変更する。
3. IaC syntax/static validationとCloudFormation change setまたはTerraform planを確認する。
4. active promptが明示許可した場合だけdeploy/applyする。
5. 成功したAWS mutationがある場合だけ必要なactualsとgenerated current valueを更新する。
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
- `materials/aws/`がbaselineと異なる場合は停止する。
- passのためにfailing checkを抑制しない。

validate/plan後にhuman reviewを要求しないrepository ruleと、Codex sandbox/OS permission controlは別の仕組みである。permissionが必要な操作はrepository ruleにかかわらずplatform controlに従う。
