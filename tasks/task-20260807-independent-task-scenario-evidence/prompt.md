# Codex Task: Separate execution stages and make scenario evidence scenario-scoped

## Task contract

- Task ID: `task-20260807-independent-task-scenario-evidence`
- Task type: `migration`
- Goal: separate design, infrastructure, deployment, and scenario testing into independently executed tasks, and replace task-scoped test results with scenario-scoped current evidence
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation deploy/update/delete: forbidden
- Terraform apply/destroy/import: forbidden
- Network access: not required

## Confirmed requirements

以下は確定事項であり、別案へ変更しないこと。

1. 詳細設計、IaC作成・deploy、scenario testは、それぞれ独立したtaskとして実行する。
2. 1つのtaskが完了しても、次のtaskを自動作成または自動実行しない。
3. infrastructure taskの完了後にscenario testを自動実行しない。
4. infrastructure behaviorが変わったことを理由にscenario testへ自動的に進まない。
5. CloudFormationのsyntax/static check、`aws cloudformation validate-template`、change set確認、Terraformの`fmt`、`validate`、`plan`はscenario testではなく、infrastructure task内の安全確認として扱う。
6. deploy/applyがactive promptで許可されたinfrastructure taskでは、成功後のcurrent actuals更新までを同じtaskで行ってよい。
7. actuals更新後もscenario testへ進まず、そのinfrastructure taskを終了する。
8. 複数の必要なresourceが作成された後、別のscenario-test taskでscenario作成・更新、test実装、test実行、result更新を行う。
9. scenario-test taskでtestが失敗しても、設計変更、IaC修正、redeploy、次task作成へ自動的に進まない。
10. scenario testの修正対応は、別のdesign taskまたはinfrastructure taskとして明示的に開始する。
11. scenario evidenceはtask IDではなく、安定したscenario IDにひも付ける。
12. 同じscenarioを同じenvironmentとAWS accountで再実行した場合は、同じresultを更新する。
13. task ID別または実行日時別のresult directoryを追加しない。
14. 過去のscenario evidenceはGit履歴で追跡する。
15. `tasks/<task-id>/`をevidence置場にしない。
16. `tests/results/`を一般taskのvalidation結果やdeployment結果の保存先として使わない。

## Required repository model

### Task types

active task promptの`## Task contract`に、次の形式でtask typeを必須とする。

```md
- Task type: `<task-type>`
```

許可するtask typeは次だけとする。

```text
initialization
design
infrastructure
scenario-test
governance
catalog-maintenance
migration
```

各taskの基本責務を次のように定義する。

### `design`

実施可能な内容:

- `docs/designs/**`の詳細設計作成・変更
- 対応する`llm/designs/**`のmachine-readable mirror作成・変更
- local validation
- active promptに明記された設計関連作業

自動的に実施しない内容:

- CloudFormationまたはTerraformの作成・変更
- AWS API実行
- deploy/apply
- `llm/actuals/**`更新
- scenario作成
- scenario test実行
- scenario result更新
- 次task作成または実行

### `infrastructure`

実施可能な内容:

- 承認済みの詳細設計とLLM designの参照
- active promptに明記された一部または全部のCloudFormation/Terraform作成・変更
- IaC syntax/static validation
- CloudFormation change setまたはTerraform planの確認
- active promptが明示的に許可した場合だけdeploy/apply
- 成功したAWS mutation後の必要最小限のactuals更新
- detailed design内のgenerated current value更新
- local validation

自動的に実施しない内容:

- intended designの変更
- `llm/designs/**`の変更
- scenario作成・変更
- scenario test実装・実行
- scenario result更新
- 次のstack、module、resource groupまたはtest taskへの自動進行

設計不足や設計変更が必要な場合は、値を補完せず停止し、別のdesign taskが必要であることを報告すること。

### `scenario-test`

実施可能な内容:

- 既存のSystem Overview、詳細設計、IaC、actualsの読み取り
- `tests/scenarios/<scenario-id>/`の作成・更新
- test implementation
- active promptで指定されたenvironment/AWS accountに対するtest実行
- 対応する`tests/results/<scenario-id>/<environment>/<aws-account-id>/`の更新

実施しない内容:

- `docs/designs/**`変更
- `llm/designs/**`変更
- `llm/actuals/**`変更
- `infra/**`変更
- test failureを理由としたIaC修正
- deploy/apply
- remediation taskの自動作成または自動実行

AWS mutationを伴うtestは、active promptに対象操作、対象resource、cleanup、許可範囲が明示されている場合だけ実行可能とする。

### Other task types

`initialization`、`governance`、`catalog-maintenance`、`migration`は、active promptのAllowed pathsと明示された作業範囲だけを実行し、完了後に別taskへ進まない。

## Scenario and result structure

scenarioとresultは次の構造に統一する。

```text
tests/
├── scenarios/
│   └── <scenario-id>/
│       ├── scenario.md
│       └── <test implementation files>
└── results/
    └── <scenario-id>/
        └── <environment>/
            └── <aws-account-id>/
                ├── result.md
                └── <stable evidence files>
```

例:

```text
tests/
├── scenarios/
│   └── private-subnet-s3-access/
│       ├── scenario.md
│       └── run.sh
└── results/
    └── private-subnet-s3-access/
        ├── dev/
        │   └── 111122223333/
        │       ├── result.md
        │       └── execution.log
        └── prod/
            └── 444455556666/
                ├── result.md
                └── execution.log
```

### Scenario ID

- lower-kebab-caseとする。
- task IDをscenario IDとして使用しない。
- 同じscenarioの更新時もscenario IDを変更しない。
- 同じscenarioの再実行時に新しいscenario directoryを作らない。
- `scenario.md`に次を正確に1件記載する。

```md
- Scenario ID: `<scenario-id>`
```

scenario definitionには最低限、次を記載する。

- purpose
- prerequisites
- required resources
- expected behavior
- execution procedure
- pass/fail criteria
- cleanup
- AWS mutationの有無
- destructive operationの有無

test implementationの形式は固定しない。Shell、Python、AWS CLIまたは手動確認手順を使用できるが、必要な実装は該当scenario directory内に置く。

### Result scope

resultの識別単位は次の組み合わせとする。

```text
scenario ID
environment
AWS account ID
```

AWS regionはSystem Overviewから決まり、directory segmentには追加せず、`result.md`のmetadataに記録する。

同じscenario、environment、AWS accountを再実行した場合は、次を更新する。

```text
tests/results/<scenario-id>/<environment>/<aws-account-id>/result.md
```

次の形式は禁止する。

```text
tests/results/<task-id>/
tests/results/<scenario-id>/<task-id>/
tests/results/<scenario-id>/<execution-date>/
tests/results/<scenario-id>/<environment>/<aws-account-id>/<task-id>/
tests/results/<scenario-id>/<environment>/<aws-account-id>/<timestamp>/
tasks/<task-id>/evidence/
```

追加のlogやoutputが必要な場合も、AWS account directory直下の安定したfile nameを更新する。実行ごとのdirectoryやfileを増やさない。

### Result metadata

各`result.md`に、次のmetadataを正確に1件ずつ記載する。

```md
- Scenario ID: `<scenario-id>`
- Environment: `<environment>`
- AWS account ID: `<12-digit-account-id>`
- AWS region: `<region>`
- Status: `<PASS|FAIL|BLOCKED|STALE|NOT_EXECUTED>`
- Executed at: `<RFC 3339 timestamp or NOT_EXECUTED>`
- Executed by task: `<task-id>`
```

本文には最低限、次を記載する。

- expected behavior
- actual behavior
- executed commandまたはprocedure
- evidence file一覧
- cleanup result
- blockerまたはfailure reason

statusの意味は次とする。

- `PASS`: testを実行し、合格条件を満たした
- `FAIL`: testを実行し、合格条件を満たさなかった
- `BLOCKED`: 実行を試みたが、前提不足や権限不足などで完了できなかった
- `STALE`: scenario変更により、以前のresultを現行scenarioの結果として利用できない
- `NOT_EXECUTED`: 対象は定義済みだが、まだ実行されていない

scenario definitionを変更した場合は、同じscenario IDに存在する全resultを次のいずれかにする。

1. 同じtaskで再実行し、最新resultへ更新する
2. 再実行しない対象の`result.md`を同じtaskで`STALE`または`NOT_EXECUTED`へ更新する

古い`PASS`を現行scenarioのresultとして残してはいけない。

scenarioが存在してもresultがまだない状態は許可する。resultだけが存在し、対応するscenarioがない状態は禁止する。

## File-specific changes

### `README.md`

次を修正する。

1. design、infrastructure、scenario-testを一連のfull loopとして説明している箇所を削除する。
2. 各taskは独立して明示的に開始されることをOperating modelに記載する。
3. Codexの役割から、無条件のIaC同期およびscenario test実行を削除する。
4. design taskは詳細設計とLLM design mirrorまでで終了すると記載する。
5. infrastructure taskはIaC validation、許可されたdeploy/apply、actuals更新までで終了すると記載する。
6. scenario-test taskは別途明示的に開始すると記載する。
7. task完了後に次taskを自動作成または自動実行しないことを記載する。
8. repository structureを次へ変更する。

```text
tasks/<task-id>/prompt.md
tests/scenarios/<scenario-id>/
tests/results/<scenario-id>/<environment>/<aws-account-id>/
```

9. `tests/results/<task-id>/`への参照をすべて削除する。
10. validation、plan、change setはscenario testではないことを明記する。
11. non-scenario taskのverification outputは、defaultではrepositoryへ永続化せず、Codexの完了報告に記載すると定義する。
12. scenario evidenceの履歴はGit履歴で追跡すると記載する。
13. task typeと各taskの責務を簡潔に説明する。
14. unrelatedなSystem Overview、design table、catalog、IaC engineの既存仕様は変更しない。

### `AGENTS.md`

次を修正する。

1. universalな「詳細設計、LLM設計、IaCの順にすべて更新する」という指示を削除し、task typeごとの責務へ変更する。
2. active promptに`Task type`が必要であることを追加する。
3. active taskに明記されていない次工程へ進むことを禁止する。
4. infrastructure taskからscenario testへ自動的に進むことを禁止する。
5. scenario-test taskだけが`tests/scenarios/**`と`tests/results/**`を作成・更新すると定義する。
6. scenario resultの保存先を次へ変更する。

```text
tests/results/<scenario-id>/<environment>/<aws-account-id>/
```

7. task directoryをevidence置場として使用しないことを追加する。
8. non-scenario taskの結果を`tests/results/**`に保存しないことを追加する。
9. scenario test failure後の自動修正、redeploy、remediation task実行を禁止する。
10. 詳細ルール一覧に`rules/scenario-testing.md`を追加する。

### `rules/loop-engineering.md`

`## Full task loop`を廃止し、task-localなcompletion ruleへ変更する。

最低限、次のsectionを設ける。

```text
## Task boundary
## Local loop
## Design task completion
## Infrastructure task completion
## Scenario-test task completion
## Other task completion
## Retry and stop
```

次を明記する。

- loopはactive task内でのみ完結する
- loop成功後に別taskへ進まない
- design taskはdesignとLLM design mirrorを更新し、local loop後に終了
- infrastructure taskはIaC validation、許可されたexecution、actuals更新、local loop後に終了
- scenario-test taskはscenario、implementation、execution、result更新後に終了
- non-scenario taskはscenario evidenceを保存しない
- retryは同じactive taskの同じfailure class内だけで行う
- retry中にtask typeまたは作業段階を変更しない
- test failureをIaC変更で自動修正しない
- genericな`tests/results/<task-id>/`へのevidence保存を削除する

既存のbounded retry、missing input stop、out-of-scope stop、unauthorized delete/replacement stopは維持する。

### `rules/cloudformation.md`

次を修正する。

1. CloudFormation変更をdesign taskと同じtaskで必ず実施する記述を削除する。
2. CloudFormationは`infrastructure` taskでのみ作成・変更・実行すると定義する。
3. infrastructure taskは承認済みの詳細設計とLLM designをinputとして読み取ると定義する。
4. intended designの変更が必要な場合は停止し、別design taskを要求する。
5. active promptが対象を限定している場合、一部のtemplate、stack、resourceだけを作成・deployして終了できると明記する。
6. 一部のresourceを作成した後、残りのresourceやscenario testへ自動的に進まないことを明記する。
7. deploy/update後は必要な非ARN actualとgenerated current valueを更新して終了する。
8. deploy/update後のscenario testとscenario evidence記録を削除する。
9. syntax/static check、`validate-template`、change set確認は維持する。
10. account、region、delete、replacement、missing inputのstop条件は維持する。

### `rules/terraform.md`

CloudFormationと同じ独立task modelへ変更する。

1. Terraformは`infrastructure` taskでのみ作成・変更・実行する。
2. 承認済みdesignをinputとして使用する。
3. intended designの変更が必要な場合は別design taskを要求する。
4. active promptの対象environment/module/resourceだけを変更して終了できる。
5. `fmt -check`、`validate`、`plan`は維持する。
6. 許可された場合だけapplyする。
7. apply後は必要なactuals更新までで終了する。
8. scenario testとscenario evidence記録を自動実行しない。
9. 次のmodule、environment、scenario-test taskへ自動的に進まない。
10. state、plan binary、sensitive outputに関する既存ルールは維持する。

### `rules/post-deploy-actuals.md`

次を修正する。

1. actualsはscenario evidenceではないことを明記する。
2. actualsは成功したinfrastructure taskのAWS mutation後に更新すると定義する。
3. scenario-test taskは`llm/actuals/**`を読み取れるが変更しないと定義する。
4. `historical value は task result evidence だけに残す`を削除する。
5. obsoleteなphysical IDや過去actualは、Git履歴およびCloudFormation、Terraform、AWS側のdeployment historyで追跡すると定義する。
6. 過去actualをscenario evidenceへ転記しない。
7. current actual、`PENDING_DEPLOY`、`NOT_DEPLOYED`、generated ARNの既存ルールは維持する。
8. actual metadataにtask IDを記録する既存ルールは維持してよい。task IDはmetadataであり、evidence pathではないことを明記する。

### `rules/detailed-design.md`

次を修正する。

1. design taskではintended designとLLM design mirrorを更新し、IaCへ自動的に進まないことを明記する。
2. infrastructure taskではintended designを変更せず、deploy/apply成功後のgenerated current valueだけを更新できると明記する。
3. `old value は historical evidence だけに残す`を削除する。
4. old physical valueはGit履歴およびAWS/IaC deployment historyで追跡し、scenario evidenceへ保存しないと記載する。
5. grouping、table、link、anchor、generated valueに関する既存仕様は変更しない。

### `rules/scenario-testing.md`

新規作成し、本promptの次の内容をrepository ruleとして整理する。

- scenario-testは独立taskでのみ実施
- scenario IDの安定性
- scenario directory structure
- result directory structure
- environment/AWS account別result
- stable evidence fileの更新
- task ID別・timestamp別resultの禁止
- result metadata
- result status
- scenario更新時の再実行またはSTALE化
- orphan result禁止
- scenarioなしresult禁止
- scenario resultをcurrent actualの正本にしない
- failure後の自動remediation禁止
- AWS mutationを伴うtestの明示許可
- cleanupとdestructive testの扱い
- behavior-oriented test
- Git履歴による過去result追跡

### `prompts/codex/initialize-repository.md`

次を修正する。

1. initialization用active task promptに次を含める。

```md
- Task type: `initialization`
```

2. initialization taskのAllowed pathsから`tests/results/**`を削除する。
3. initialization taskで`tests/scenarios/**`と`tests/results/**`を変更しない。
4. `tests/results/{{task-id}}/initialization.txt`の作成指示を削除する。
5. validation結果、作成path、既存path、blockerはCodexの完了報告にだけ記載する。
6. initialization完了後にdesign taskやIaC taskへ進まないことを明記する。
7. topology、target path、既存repository handlingの既存仕様は維持する。

### `scripts/validate-blueprint.py`

Python標準ライブラリだけを使用して、次を実装する。

#### Required rule

`REQUIRED_RULES`へ次を追加する。

```text
scenario-testing.md
```

#### Task type parsing

active task promptの`## Task contract`から、次の形式を解析する。

```md
- Task type: `<task-type>`
```

次を検証する。

- Task typeが正確に1件存在する
- 許可されたtask typeのいずれかである
- Task typeがない、重複している、未知の値の場合はFAIL

#### Task boundary validation

既存のAllowed paths検証に加えて、次を検証する。

- `design`
  - `infra/**`変更禁止
  - `llm/actuals/**`変更禁止
  - `tests/scenarios/**`変更禁止
  - `tests/results/**`変更禁止
- `infrastructure`
  - `llm/designs/**`変更禁止
  - `tests/scenarios/**`変更禁止
  - `tests/results/**`変更禁止
- `scenario-test`
  - active task prompt自身を除き、変更可能なrepository pathは`tests/scenarios/**`と`tests/results/**`だけ
  - `docs/**`、`llm/**`、`infra/**`、`rules/**`、`prompts/**`、`materials/**`変更禁止
- `initialization`
  - `tests/scenarios/**`変更禁止
  - `tests/results/**`変更禁止
- `governance`
  - `tests/scenarios/**`変更禁止
  - `tests/results/**`変更禁止
- `catalog-maintenance`
  - `tests/scenarios/**`変更禁止
  - `tests/results/**`変更禁止
- `migration`
  - 追加のpath matrix制限は設けず、Allowed pathsを正本とする

task boundary validationは、Allowed pathsの代わりではなく追加条件とする。

#### Task directory validation

`tasks/<task-id>/`はtask contractの置場とし、各task directoryに永続化できるfileを`prompt.md`だけに限定する。

次をFAILにする。

```text
tasks/<task-id>/evidence/
tasks/<task-id>/result.md
tasks/<task-id>/execution.log
```

既存のtask directoryも同じ条件で検証する。

#### Scenario validation

`tests/scenarios/`について次を検証する。

- root直下は`.gitkeep`またはscenario directoryだけ
- scenario directory名はlower-kebab-case
- 各scenario directoryに`scenario.md`が存在する
- `scenario.md`の`Scenario ID`がdirectory名と一致する
- scenario implementation fileはscenario directory配下に置かれている
- scenario directory内の追加subdirectoryは許可する

#### Result validation

`tests/results/`について次を検証する。

- root直下は`.gitkeep`またはscenario ID directoryだけ
- `tests/results/task-*`形式を明示的に拒否する
- resultのscenario IDはlower-kebab-case
- 対応する`tests/scenarios/<scenario-id>/scenario.md`が存在する
- result pathは正確に次のscopeを持つ

```text
tests/results/<scenario-id>/<environment>/<aws-account-id>/
```

- environmentとAWS accountの組み合わせがSystem Overviewに存在する
- AWS account IDが12桁
- account directoryに`result.md`が存在する
- account directory配下に追加directoryを作ることを禁止する
- account directory直下のstable evidence fileは許可する
- template modeではscenario result fileを禁止する
- scenarioが存在しresultがない状態は許可する
- resultが存在しscenarioがない状態はFAIL

#### Result metadata validation

各`result.md`で、次のmetadataが正確に1件ずつ存在することを確認する。

```text
Scenario ID
Environment
AWS account ID
AWS region
Status
Executed at
Executed by task
```

次を検証する。

- Scenario IDがpathと一致
- Environmentがpathと一致
- AWS account IDがpathと一致
- AWS regionがSystem Overviewと一致
- Statusが`PASS`、`FAIL`、`BLOCKED`、`STALE`、`NOT_EXECUTED`のいずれか
- `Executed by task`が空でなく、task ID形式である
- `PASS`または`FAIL`の場合、`Executed at`が`NOT_EXECUTED`ではない
- `NOT_EXECUTED`の場合、`Executed at`が`NOT_EXECUTED`

#### Scenario change and stale result validation

active taskのchanged pathsを使用して、次を検証する。

- `tests/scenarios/<scenario-id>/**`が変更された場合、同じscenario IDの既存`result.md`もすべて同じtaskで変更または削除されている
- scenarioを変更したのに既存resultが未変更の場合はFAIL
- result更新後のstatusは、再実行結果の`PASS`、`FAIL`、`BLOCKED`、または未実行を示す`STALE`、`NOT_EXECUTED`のいずれかとする
- scenario削除後にresultが残る場合はorphan resultとしてFAIL

過去resultの履歴保存用copy、task ID directory、timestamp directoryを許可しない。

#### Validator output

PASS時のsummaryを、task scope、task type、scenario/result structureを確認したことが分かる内容へ更新する。

### Existing task-based results

現在存在する次のようなtask-based result directoryをactive treeから削除する。

```text
tests/results/task-20260807-aws-account-scope/
tests/results/task-20260807-copilot-instruction-separation/
tests/results/task-20260807-generic-blueprint/
tests/results/task-20260807-system-overview-initialization/
```

実際のrepositoryに他の`tests/results/task-*`が存在する場合も、内容を確認したうえですべて削除する。

これらはscenario test resultではないため、scenario IDへrenameまたは移行しない。Git履歴を過去記録として使用する。

次は維持する。

```text
tests/results/.gitkeep
tests/scenarios/.gitkeep
```

今回のtask用verification resultを`tests/results/`へ作成しない。

## Non-goals

次は行わない。

- AWS API呼び出し
- CloudFormation validation
- CloudFormation deploy/update/delete
- Terraform command実行
- actual AWS resourceの確認
- sample scenario作成
- sample result作成
- project固有environmentまたはAWS accountの追加
- `docs/system-overview.md`の変更
- design fileの変更
- LLM design/actual fileの変更
- IaC implementationの変更
- `materials/aws/**`の変更
- `scripts/blueprint-loop.sh`の不要な変更
- dependency追加
- CI/CD workflow追加
- general task evidence用の新しいdirectory追加

## Allowed paths

- `AGENTS.md`
- `README.md`
- `prompts/codex/initialize-repository.md`
- `rules/cloudformation.md`
- `rules/detailed-design.md`
- `rules/loop-engineering.md`
- `rules/post-deploy-actuals.md`
- `rules/scenario-testing.md`
- `rules/terraform.md`
- `scripts/validate-blueprint.py`
- `tasks/task-20260807-independent-task-scenario-evidence/**`
- `tests/results/**`

## Verification

変更後、最低限次を実行する。

```bash
python3 -m py_compile scripts/validate-blueprint.py
bash -n scripts/blueprint-loop.sh
python3 scripts/update-catalog-lock.py
bash scripts/blueprint-loop.sh \
  --task-id task-20260807-independent-task-scenario-evidence \
  --mode local
git diff --check
```

AWS APIまたはnetwork accessを必要とするcommandは実行しない。

一時directoryまたは一時repository copyを使用し、commitしないfixtureで次を確認する。

1. Task typeがないactive promptはFAIL
2. 未知のTask typeはFAIL
3. `design` taskが`infra/**`を変更した場合はFAIL
4. `design` taskが`tests/**`を変更した場合はFAIL
5. `infrastructure` taskが`tests/**`を変更した場合はFAIL
6. `scenario-test` taskが`infra/**`または`docs/**`を変更した場合はFAIL
7. 有効なscenarioと有効なenvironment/AWS account resultはPASS
8. `tests/results/task-*`はFAIL
9. orphan resultはFAIL
10. invalid scenario IDはFAIL
11. System Overviewにないenvironment/AWS account resultはFAIL
12. result metadataとpathが不一致の場合はFAIL
13. scenario変更時に既存resultを変更しない場合はFAIL
14. scenario変更時に既存resultを`STALE`へ更新した場合はPASS
15. scenarioだけが存在し、resultがまだない場合はPASS
16. task directoryに`prompt.md`以外のevidence fileがある場合はFAIL

fixtureやverification outputをrepositoryへ保存しない。

## Completion criteria

次をすべて満たした場合だけ完了とする。

1. design、infrastructure、scenario-testの独立実行がREADME、AGENTS、rules間で一貫している
2. infrastructure taskからscenario testへ自動的に進む記述が残っていない
3. `tests/results/<task-id>/`への参照が残っていない
4. scenario/result pathが全fileで次に統一されている

```text
tests/scenarios/<scenario-id>/
tests/results/<scenario-id>/<environment>/<aws-account-id>/
```

5. 同じscenario resultを更新するルールが明記されている
6. task ID別またはtimestamp別resultが禁止されている
7. scenario変更時のresult再実行またはSTALE化が定義されている
8. task-based result directoryがactive treeから削除されている
9. validatorがtask type、task boundary、scenario/result structureを検証する
10. 既存のSystem Overview、catalog、design format、IaC engine selectionの仕様を壊していない
11. local loop、syntax check、fixture verification、`git diff --check`がPASSする
12. AWS APIを一度も呼んでいない
13. verification resultを`tests/results/**`または`tasks/**`へ保存していない

完了報告には、変更file、削除したlegacy result directory、実行したverification commandと結果、残ったblockerだけを簡潔に記載する。
