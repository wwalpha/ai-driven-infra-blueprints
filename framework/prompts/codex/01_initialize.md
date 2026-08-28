# Repository Initialization Prompt

このpromptは、Codexが初期化に必要な確定値をhumanへ確認し、`project.json`とtarget pathを作成するために使用する。`docs/system-overview.md`の作成・記入状態を前提にしない。

humanへJSONの作成・編集を依頼してはいけない。質問、回答、正規化、file作成はこのinitialization task内で完結させる。

## First response

prompt実行後の最初の応答ではfileを変更せず、Project nameだけを質問する。

```text
repository初期化を始めます。

Step 1: Project
Project nameを入力してください。
```

## Read first

1. `AGENTS.md`
2. `README.md`
3. 既存の`project.json`（存在する場合）
4. `framework/rules/loop-engineering.md`

## Stop before reinitialization

`project.json`が既に存在する場合はinitialization済みとして扱う。fileや既存pathを変更せず、target追加には`framework/prompts/codex/02_add-target.md`のmigration taskが必要であることを報告して停止する。

## Collect required values

次の順序で、一回の応答につき一つだけ質問する。複数の質問、質問一覧、入力tableを一度に提示しない。

1. Project name
2. Environment IDを一つ確認し、別のenvironmentを追加するか確認する。追加がなくなるまで繰り返す
3. 各environmentについて論理配置先が一件か複数かを確認する。複数の場合だけaliasを一つずつ確認し、追加がなくなるまで繰り返す
4. 各targetについてAWS account IDを一つずつ確認する。同じAWS account IDを異なるaliasへ設定してよい
5. 各targetについてAWS regionを一つずつ確認する
6. 各targetについてIaC engineを一つずつ確認する

Environment IDとaliasはlower-kebab-case、AWS account IDは12桁、IaC engineは`cloudformation`または`terraform`と説明する。aliasはhumanが入力した値だけを使用し、`cde`、`non-cde`などの固定候補を持たない。

- 現時点でEnvironment ID、AWS account ID、AWS region、IaC engineがすべて確定しているtargetだけを収集する。
- 未作成または必要値が未確定のtargetは今回の初期化対象から除外し、placeholderや`UNSET`を記録しない。確定後に`framework/prompts/codex/02_add-target.md`で追加できることを説明する。
- 回答を受けるたびに形式と既存回答との矛盾を確認してから次へ進む。
- 不正または不明な回答は理由を短く説明し、同じ項目だけを再質問する。
- humanが自発的に複数の確定値を回答した場合は採用し、次の未解決項目を一つだけ質問する。
- humanが修正を求めた場合は該当値を更新し、依存する未解決項目へ戻る。
- 一つのenvironmentにtargetが一件だけならoptional `alias`を省略する。複数targetがある場合は全targetでaliasを必須とし、aliasあり／なしを混在させない。
- aliasは同じenvironment内で一意とし、12桁の数字だけの値を禁止する。
- 同じenvironment/AWS account IDを持つ複数aliasではIaC engineを統一する。
- 質問票、回答履歴、session state fileを作成せず、進行中の回答はconversation contextだけで保持する。
- 値を推測しない。

すべての値が揃ったら、projectと全targetを一覧で提示し、repositoryを初期化してよいか一つだけ確認する。humanが明示的に承認するまでfileを変更しない。

## Validate answers

file変更前に次を確認する。

- Project nameが空でない
- targetが1件以上ある
- Environment IDがlower-kebab-case
- AWS account IDが12桁
- AWS regionが空でない
- IaC engineが`cloudformation`または`terraform`
- 一件だけのenvironmentではaliasがなく、複数targetのenvironmentでは全targetに一意で有効なaliasがある
- target directoryとなる`alias`または`awsAccountId`が同じenvironment内で重複していない
- 同じenvironment/AWS account IDのtargetは同じIaC engineを使用する

不足または不正な値が残る場合は変更せず停止する。

## Create active task contract

最初のrepository changeとして、`tasks/active.md`を次の条件で上書きする。

```md
- Task type: `initialization`
```

- goalは確認済みproject topologyとtarget pathの初期化だけとする
- AWS mutation、AWS API、deploy、applyは禁止する
- `Required changes`は一意なRequirement ID付きで、`project.json`作成、target path作成、IaC engine選択を分けて記載する
- `Acceptance checks`は各Requirement IDへ`changed:project.json`、作成対象pathの`exists:`、未選択IaC rootの`absent:`を対応付ける
- allowed pathsは`project.json`、作成対象の`docs/designs/**`、`model/**`、選択済みIaCの初期化path、全targetで未選択のIaC engine root、`tasks/active.md`に限定する
- resource設計、IaC implementation、AWS接続確認は対象外とする
- `tests/scenarios/**`と`tests/results/**`を変更しない

## Create project topology

humanが確認した値からrepository rootに`project.json`を作成する。UTF-8、2-space indentation、final newlineを使用し、targetはenvironment、target directoryの順に並べる。target directoryはaliasがあればalias、なければAWS account IDとする。

```json
{
  "projectName": "<confirmed-project-name>",
  "targets": [
    {
      "environment": "<confirmed-environment-id>",
      "alias": "<confirmed-optional-alias>",
      "awsAccountId": "<confirmed-12-digit-account-id>",
      "awsRegion": "<confirmed-region>",
      "iacEngine": "<cloudformation-or-terraform>"
    }
  ]
}
```

aliasなしのtargetでは`alias` key自体を省略する。確認済みの初期化値だけを記録し、`UNSET`、background、purpose、account role、design decisionを入れない。

## Create target paths

各targetについて、存在しないpathだけを作成し、空directoryには`.gitkeep`を置く。

```text
docs/designs/<environment>/<target-directory>/.gitkeep
model/<environment>/<target-directory>/.gitkeep
```

IaC engineが`cloudformation`の場合:

```text
infra/cloudformation/parameters/<environment>/<target-directory>/.gitkeep
```

IaC engineが`terraform`の場合:

```text
infra/terraform/environments/<environment>/<target-directory>/.gitkeep
```

全targetの`iacEngine`を確認し、1件も選択されていないIaC engineのrootを削除する。

- CloudFormationを選択したtargetがなければ`infra/cloudformation/`を削除する。
- Terraformを選択したtargetがなければ`infra/terraform/`を削除する。
- 両方が選択されている場合だけ両方のrootを残す。
- 削除対象に`.gitkeep`以外のfileがある場合は、既存implementationとして削除せず停止する。

## Do not create

- 空の詳細設計Markdown
- 空のservice model properties
- CloudFormation template
- Terraform module、resource、provider、state設定
- 全targetで未選択のIaC engine directory
- questionnaire、回答履歴、session state
- sample environment、sample AWS account
- scenario、scenario result、general task evidence

## Existing repository handling

- 既存のdesign、model、IaC implementationを上書きしない。
- target pathが既に存在する場合は再利用し、`.gitkeep`のためだけに内容を変更しない。
- 確認済みtopologyと既存target pathまたはIaC engineが矛盾する場合は停止する。

## Verify and finish

1. `python framework/scripts/blueprint-loop.py --mode local`
2. `python -m py_compile framework/scripts/blueprint-loop.py framework/scripts/validate-blueprint.py`
3. `git diff --check`

validation結果、作成したtopology、作成path、既存のため変更しなかったpath、blockerはCodexの完了報告だけに記載する。repositoryへverification resultを保存しない。初期化完了後にdesign task、infrastructure task、scenario-test taskを作成または実行しない。
