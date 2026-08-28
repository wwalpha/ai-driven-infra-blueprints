# Scenario Testing Rules

## Task boundary

- scenario testは独立した`scenario-test` taskでのみ作成、変更、実装、実行する。
- infrastructure task完了後やbehavior変更後にscenario-test taskを自動作成または自動実行しない。
- scenario-test taskは`docs/**`、`model/**`、`infra/**`を変更しない。
- test failure後にdesign変更、IaC修正、redeploy、remediation task作成・実行へ進まない。
- scenario resultはcurrent observed valueの正本にしない。

## Scenario definition

- scenario IDはstableなlower-kebab-caseとする。
- scenarioは`tests/scenarios/<scenario-id>/`に置く。
- 各scenario directoryに`scenario.md`を置き、`- Scenario ID: <scenario-id>`を正確に1件記載する。
- scenario definitionにはpurpose、prerequisites、required resources、expected behavior、execution procedure、pass/fail criteria、cleanup、AWS mutationの有無、destructive operationの有無を記載する。
- test implementationはShell、Python、AWS CLI、manual procedureなど必要な形式をscenario directory内で使用できる。
- scenario testは静的設定だけでなくexpected behaviorを検証する。

## Current result

- result scopeはscenario ID、environment、AWS account IDの組み合わせとする。
- target directoryは`project.json`のtargetにaliasがあればalias、なければAWS account IDとする。
- current resultは`tests/results/<scenario-id>/<environment>/<target-directory>/result.md`に置く。result metadataのAWS account IDはdirectory名ではなく、対応する`project.json` targetの実値と一致させる。
- AWS regionはdirectoryに追加せず、`project.json`と一致する値をresult metadataに記録する。
- 同じscopeの再実行では同じ`result.md`とtarget directory直下のstable evidence fileを更新する。
- execution date別、timestamp別のdirectoryまたはfileを追加しない。
- target directory配下に追加directoryを作らない。
- scenarioが存在しresultがまだない状態は許可する。対応scenarioがないorphan resultは禁止する。
- 過去resultはGit履歴で追跡し、active treeにcopyやarchiveを残さない。

## Result metadata

各`result.md`に次を正確に1件ずつ記載する。

```md
- Scenario ID: `<scenario-id>`
- Environment: `<environment>`
- AWS account ID: `<12-digit-account-id>`
- AWS region: `<region>`
- Status: `<PASS|FAIL|BLOCKED|STALE|NOT_EXECUTED>`
- Executed at: `<RFC 3339 timestamp or NOT_EXECUTED>`
```

本文にはexpected behavior、actual behavior、executed command/procedure、evidence file一覧、cleanup result、blocker/failure reasonを記載する。

- `PASS`: testを実行し、合格条件を満たした。
- `FAIL`: testを実行し、合格条件を満たさなかった。
- `BLOCKED`: 実行を試みたが前提不足や権限不足で完了できなかった。
- `STALE`: scenario変更により以前のresultを現行結果として利用できない。
- `NOT_EXECUTED`: 対象は定義済みだがまだ実行されていない。

## Scenario changes

- scenario definitionまたはimplementationを変更した場合、同じscenario IDの全resultを同じtaskで再実行結果へ更新するか、`STALE`または`NOT_EXECUTED`へ更新する。
- 古い`PASS`を変更後scenarioのcurrent resultとして残さない。
- scenario削除時にresultを残さない。

## AWS mutation and cleanup

- AWS mutationを伴うtestはactive promptに対象operation、対象resource、cleanup、許可範囲が明示されている場合だけ実行できる。
- destructive operationはactive promptの明示許可が必要であり、対象を事前確認する。
- cleanup resultをresult本文へ記録する。
- failure時もactive prompt外のcleanup、repair、redeployを推測して実行しない。
