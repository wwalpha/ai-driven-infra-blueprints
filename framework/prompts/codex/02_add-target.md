# Add Project Target Prompt

契約は`tasks/<task-name>.md`へtaskごとに登録する。Task statusを`running`とし、`## Modified files`へ今回変更する具体的なfile path（契約自身、新規file、生成artifact、model part、削除対象を含む）を列挙する。Allowed pathsのglobは予約fileの代わりにしない。repository外の候補から`task_contract.py --task-file tasks/<task-name>.md --source <候補file>`で登録し、進行中taskとのfile重複があれば新規taskを停止する。既存taskの契約を上書きしない。以後のcommandは`BLUEPRINT_TASK_FILE`で同じ契約を選択し、local loopには`--task-file`を指定する。成功後に今回のstatusだけを`completed`へ変更する。詳細は`framework/rules/loop-engineering.md`に従う。

このpromptは、初期化済みrepositoryの`project.json`へ、必要値が確定したenvironment／logical targetを1件追加するmigrationに使用する。

humanへJSONの作成・編集を依頼してはいけない。値を推測せず、質問、確認、file変更はこのmigration task内で完結させる。

## Unresolved issue gate

対象environment／target／serviceを確定した時点で、通常taskの開始前と再開時に`issues/<environment>/<target-directory>/issues.md`を確認し、`framework/rules/loop-engineering.md`のUnresolved issue gateを適用する。関係する全serviceについて`python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>`を実行する。未解決issueがあれば設計質問、設計保存、IaC変更、deploy/apply、scenarioなど他taskへ進まず、対象issueと停止理由を示す。issue調査とhumanが明示した修復だけを許可し、修復taskには対象serviceだけのValidation scopeとIssue remediationを記載する。AWS mutation直前にも再確認し、既存のtask boundaryとAWS execution許可は維持する。

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
2. 既存environmentがalias targetを持つ場合だけ、新しいalias
3. resource作成時のID設定・名称とtarget identityに使うAWS account ID（`awsAccountId`）
4. AWS region
5. IaC engine
6. AWS profile（任意。不要なら省略してtarget追加を進める）
7. AWS実行account ID（`awsExecutionAccountId`、任意。省略時は`awsAccountId`で認証照合する）

Environment IDとaliasはlower-kebab-case、AWS account IDは12桁、IaC engineは`cloudformation`または`terraform`と説明する。

- 不明または未確定の値は推測せず、fileを変更しない。同じpromptを必要値の確定後に再実行できることを説明して停止する。
- humanが自発的に複数の確定値を回答した場合は採用し、次の未解決項目を一つだけ質問する。
- 回答を受けるたびに形式、既存targetとの重複、既存pathまたはIaC engineとの矛盾を確認する。
- 新しいenvironmentへ一件だけ追加する場合はaliasを省略する。既存environmentの全targetにaliasがある場合だけ新しい一意なaliasを追加できる。
- aliasなしの既存environmentへ二件目を追加すると既存targetの変更が必要になるため、このpromptでは変更せず停止する。
- 質問票、回答履歴、session state fileを作成せず、進行中の回答はconversation contextだけで保持する。

すべての値が揃ったら、追加するtargetを提示し、追加してよいか一つだけ確認する。humanが明示的に承認するまでfileを変更しない。

## Validate answers

file変更前に次を確認する。

- `project.json`が現在のschemaで有効
- Environment IDがlower-kebab-case
- AWS account IDが12桁
- 任意のAWS実行account IDはASCII数字12桁の文字列。同じenvironment/実行accountのtarget間でもIaC engineを統一する。認証の自動切替は行わず、AWS接続はこのtaskで行わない
- AWS regionが空でない
- IaC engineが`cloudformation`または`terraform`
- 任意のAWS profileを指定した場合は、前後の空白、改行、NUL、`UNSET`を含まない空でない文字列。profileの存在確認やAWS接続はこのtaskでは行わない
- target directoryとなるaliasまたはAWS account IDが同じenvironmentに存在しない
- aliasは同じenvironment内で一意なlower-kebab-caseで、12桁の数字だけではない
- 同じenvironment/AWS account IDの既存targetがある場合はIaC engineが一致する
- 対象pathに`.gitkeep`以外の既存fileがない

不足、不正、重複、矛盾がある場合は変更せず停止する。

## Create active task contract

最初のrepository changeとして、`tasks/<task-name>.md`を次の条件で新規登録する。

```md
- Task type: `migration`
```

- goalは確認済みtarget 1件の追加だけとする
- AWS mutation、AWS API、deploy、applyは禁止する
- `Required changes`は一意なRequirement ID付きで、`project.json`更新、target path作成、選択IaC path作成を分けて記載する
- `Acceptance checks`は各Requirement IDへ`changed:project.json`、作成対象pathの`exists:`または`changed:`を対応付ける
- Allowed pathsは`project.json`、追加対象の`docs/designs/**`、`model/**`、選択済みIaCのtarget path、`tasks/<task-name>.md`に限定する
- 既存target、design、model、IaC implementation、scenario、scenario resultの変更を禁止する

## Add project target

確認済みtargetを`project.json`の`targets`へ追加し、environment、target directoryの順に並べる。target directoryはaliasがあればalias、なければAWS account IDとする。既存targetと`projectName`は変更しない。UTF-8、2-space indentation、final newlineを維持する。

```json
{
  "environment": "<confirmed-environment-id>",
  "alias": "<confirmed-optional-alias>",
  "awsAccountId": "<confirmed-12-digit-account-id>",
  "awsExecutionAccountId": "<confirmed-optional-12-digit-execution-account-id>",
  "awsRegion": "<confirmed-region>",
  "iacEngine": "<cloudformation-or-terraform>",
  "awsProfile": "<confirmed-optional-profile>"
}
```

aliasなしのtargetでは`alias` key自体を省略する。
AWS実行account IDを指定しないtargetでは`awsExecutionAccountId` key自体を省略する。selectorとpathは`awsAccountId`を維持する。
AWS profileを指定しないtargetでは`awsProfile` key自体を省略する。credentialは記録しない。

## Create target paths

存在しない対象pathだけを作成し、空directoryには`.gitkeep`を置く。

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

既存directoryを削除しない。target pathが既に存在しても`.gitkeep`だけなら再利用し、内容を変更しない。

## Do not change

- 既存targetの値またはpath
- project name
- design、model、IaC implementation
- IaC engine rootの削除
- scenario、scenario result
- questionnaire、回答履歴、session state

## Verify and finish

1. `python framework/scripts/blueprint-loop.py --mode task`
2. `python -m py_compile framework/scripts/blueprint-loop.py framework/scripts/validate-blueprint.py`
3. `git diff --check`

validation結果、追加したtargetとpath、再利用したpath、blockerはCodexの完了報告だけに記載する。repositoryへverification resultを保存しない。完了後にdesign、infrastructure、scenario-test taskを作成または実行しない。
