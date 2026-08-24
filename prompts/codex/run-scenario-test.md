# Scenario Test Prompt

このpromptは、deployとは独立した`scenario-test` taskとしてapplication behaviorを検証し、current resultを更新するために使用する。infrastructureの作成、修正、deploy、redeployは行わない。

## User input

- Scenario ID: `{{lower-kebab-case ID}}`
- Target environment: `{{project-topology.jsonのenvironment}}`
- Target AWS account: `{{project-topology.jsonの12桁AWS account ID}}`
- Expected behavior: `{{検証するapplication behavior}}`
- AWS mutation: `forbidden`
- Destructive operation: `forbidden`

## Resolve missing input

placeholder、空、不明な必須inputは、Scenario ID、Target environment、Target AWS account、Expected behaviorの順で一回の応答につき一つだけ質問する。environmentとaccountは`project-topology.json`に存在する候補だけを提示し、自動選択しない。

AWS mutationまたはdestructive operationが必要なscenarioは、対象operation、resource、cleanup、許可範囲がUser inputに明記されるまで実行しない。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. `project-topology.json`
4. `rules/scenario-testing.md`
5. `rules/loop-engineering.md`
6. 対象の`tests/scenarios/<scenario-id>/`
7. 対象の`tests/results/<scenario-id>/<environment>/<aws-account-id>/`
8. 必要な`docs/designs/**`と`llm/actuals/**`をread-only inputとして読む

## Create active task contract

最初のrepository changeとして`tasks/active.md`を次の条件で上書きする。

- Task typeは`scenario-test`とする。
- goalにscenario ID、environment、AWS account、expected behaviorを記載する。
- AWS mutationとdestructive operationは確認済みUser inputの値をそのまま記載する。
- Allowed pathsは対象の`tests/scenarios/<scenario-id>/**`、`tests/results/<scenario-id>/<environment>/<aws-account-id>/**`、`tasks/active.md`だけに限定する。
- `docs/**`、`llm/**`、`infra/**`は変更禁止とする。

## Define and execute

1. `rules/scenario-testing.md`に従い、scenario definitionと必要最小限のtest implementationを作成または更新する。
2. expected behaviorを実際に観測できる手順を使用し、deploy完了statusや静的設定だけをPASS根拠にしない。
3. prerequisites不足またはcredential/permission不足は`BLOCKED`、実行して合格条件を満たさない場合は`FAIL`とする。
4. 許可されたcleanupだけを実行し、結果を記録する。
5. stableなcurrent resultとevidenceだけを同じresult directoryへ更新する。

failure時もdesign変更、IaC修正、redeploy、別task作成を行わない。根本原因と観測事実を簡潔に報告してscenario-test taskを終了する。

## Verify and finish

1. `python scripts/blueprint-loop.py --mode local`
2. `git diff --check`

scenario ID、target、実行手順、status、expected/actual behavior、evidence、cleanup、blockerを完了報告に記載する。
