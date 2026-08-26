# Add Project Target Prompt

このpromptは、初期化済みrepositoryの`project.json`へ、必要値が確定したenvironment/AWS account targetを1件追加するmigrationに使用する。

humanへJSONの作成・編集を依頼してはいけない。値を推測せず、質問、確認、file変更はこのmigration task内で完結させる。

## First response

prompt実行後の最初の応答ではfileを変更せず、追加するEnvironment IDだけを質問する。

```text
project target追加を始めます。

Step 1: Environment
追加するEnvironment IDを入力してください。
```

## Read first

1. `AGENTS.md`
2. `README.md`
3. `project.json`
4. `framework/rules/loop-engineering.md`

`project.json`が存在しない場合はfileを変更せず、`framework/prompts/codex/01_initialize.md`によるinitializationが必要であることを報告して停止する。

## Collect required values

次の順序で、一回の応答につき一つだけ質問する。

1. Environment ID
2. AWS account ID
3. AWS region
4. IaC engine

Environment IDはlower-kebab-case、AWS account IDは12桁、IaC engineは`cloudformation`または`terraform`と説明する。

- 不明または未確定の値は推測せず、fileを変更しない。同じpromptを必要値の確定後に再実行できることを説明して停止する。
- humanが自発的に複数の確定値を回答した場合は採用し、次の未解決項目を一つだけ質問する。
- 回答を受けるたびに形式、既存targetとの重複、既存pathまたはIaC engineとの矛盾を確認する。
- 質問票、回答履歴、session state fileを作成せず、進行中の回答はconversation contextだけで保持する。

すべての値が揃ったら、追加するtargetを提示し、追加してよいか一つだけ確認する。humanが明示的に承認するまでfileを変更しない。

## Validate answers

file変更前に次を確認する。

- `project.json`が現在のschemaで有効
- Environment IDがlower-kebab-case
- AWS account IDが12桁
- AWS regionが空でない
- IaC engineが`cloudformation`または`terraform`
- 同じenvironment/AWS accountが`project.json`に存在しない
- 対象pathに`.gitkeep`以外の既存fileがない

不足、不正、重複、矛盾がある場合は変更せず停止する。

## Create active task contract

最初のrepository changeとして、`tasks/active.md`を次の条件で上書きする。

```md
- Task type: `migration`
```

- goalは確認済みtarget 1件の追加だけとする
- AWS mutation、AWS API、deploy、applyは禁止する
- `Required changes`は一意なRequirement ID付きで、`project.json`更新、target path作成、選択IaC path作成を分けて記載する
- `Acceptance checks`は各Requirement IDへ`changed:project.json`、作成対象pathの`exists:`または`changed:`を対応付ける
- Allowed pathsは`project.json`、追加対象の`docs/designs/**`、`model/**`、選択済みIaCのtarget path、`tasks/active.md`に限定する
- 既存target、design、model、IaC implementation、scenario、scenario resultの変更を禁止する

## Add project target

確認済みtargetを`project.json`の`targets`へ追加し、environment、AWS account IDの順に並べる。既存targetと`projectName`は変更しない。UTF-8、2-space indentation、final newlineを維持する。

```json
{
  "environment": "<confirmed-environment-id>",
  "awsAccountId": "<confirmed-12-digit-account-id>",
  "awsRegion": "<confirmed-region>",
  "iacEngine": "<cloudformation-or-terraform>"
}
```

## Create target paths

存在しない対象pathだけを作成し、空directoryには`.gitkeep`を置く。

```text
docs/designs/<environment>/<aws-account-id>/.gitkeep
model/<environment>/<aws-account-id>/.gitkeep
```

IaC engineが`cloudformation`の場合:

```text
infra/cloudformation/parameters/<environment>/<aws-account-id>/.gitkeep
```

IaC engineが`terraform`の場合:

```text
infra/terraform/environments/<environment>/<aws-account-id>/.gitkeep
```

既存directoryを削除しない。target pathが既に存在しても`.gitkeep`だけなら再利用し、内容を変更しない。

## Do not change

- 既存targetの値またはpath
- project name
- design、model、IaC implementation
- IaC engine rootの削除
- scenario、scenario result
- questionnaire、回答履歴、session state

## Verify and finish

1. `python framework/scripts/blueprint-loop.py --mode local`
2. `python -m py_compile framework/scripts/blueprint-loop.py framework/scripts/validate-blueprint.py`
3. `git diff --check`

validation結果、追加したtargetとpath、再利用したpath、blockerはCodexの完了報告だけに記載する。repositoryへverification resultを保存しない。完了後にdesign、infrastructure、scenario-test taskを作成または実行しない。
