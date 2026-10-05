# Repository Initialization Prompt

契約は`tasks/<task-name>.md`へtaskごとに登録する。Task statusを`running`とし、`## Modified files`へ今回変更する具体的なfile path（契約自身、新規file、生成artifact、model part、削除対象を含む）を列挙する。Allowed pathsのglobは予約fileの代わりにしない。repository外の候補から`task_contract.py --task-file tasks/<task-name>.md --source <候補file>`で登録し、進行中taskとのfile重複があれば新規taskを停止する。既存taskの契約を上書きしない。以後のcommandは`BLUEPRINT_TASK_FILE`で同じ契約を選択し、local loopには`--task-file`を指定する。成功後に今回のstatusだけを`completed`へ変更する。詳細は`framework/rules/loop-engineering.md`に従う。

このpromptは、Codexが初期化に必要な確定値をhumanへ確認し、`project.json`とtarget pathを作成するために使用する。`docs/system-overview.md`の作成・記入状態を前提にしない。

humanへJSONの作成・編集を依頼してはいけない。質問、回答、正規化、file作成はこのinitialization task内で完結させる。

## Unresolved issue gate

対象environment／target／serviceを確定した時点で、通常taskの開始前と再開時に`issues/<environment>/<target-directory>/issues.md`を確認し、`framework/rules/loop-engineering.md`のUnresolved issue gateを適用する。関係する全serviceについて`python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>`を実行する。未解決issueがあれば設計質問、設計保存、IaC変更、deploy/apply、scenarioなど他taskへ進まず、対象issueと停止理由を示す。issue調査とhumanが明示した修復だけを許可し、修復taskには対象serviceだけのValidation scopeとIssue remediationを記載する。AWS mutation直前にも再確認し、既存のtask boundaryとAWS execution許可は維持する。

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
4. 各targetについてresource作成時のID設定・名称とtarget identityに使うAWS account ID（`awsAccountId`）を一つずつ確認する。同じAWS account IDを異なるaliasへ設定してよい
5. 各targetについてAWS regionを一つずつ確認する
6. 各targetについてIaC engineを一つずつ確認する
7. 各targetについてAWS profileを任意項目として一つずつ確認する。不要なら省略でき、未設定でも初期化を進める
8. 各targetについてAWS実行account ID（`awsExecutionAccountId`）を任意項目として一つずつ確認する。省略時は`awsAccountId`で認証照合する
9. 各targetについて命名suffixを任意項目として一つずつ確認する。不要なtargetは省略し、指定する場合は確定済みnon-empty lower-kebab-case文字列を採用する

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
- 任意のtarget suffixはnon-empty lower-kebab-case文字列。一部targetのみの設定を許可し、未確定値を保存しない
- targetが1件以上ある
- Environment IDがlower-kebab-case
- AWS account IDが12桁
- 任意のAWS実行account IDはASCII数字12桁の文字列。同じenvironment/実行accountのtarget間でもIaC engineを統一する。認証の自動切替は行わず、AWS接続はこのtaskで行わない
- AWS regionが空でない
- IaC engineが`cloudformation`または`terraform`
- 一件だけのenvironmentではaliasがなく、複数targetのenvironmentでは全targetに一意で有効なaliasがある
- target directoryとなる`alias`または`awsAccountId`が同じenvironment内で重複していない
- 同じenvironment/AWS account IDのtargetは同じIaC engineを使用する
- 任意のAWS profileを指定した場合は、前後の空白、改行、NUL、`UNSET`を含まない空でない文字列。profileの存在確認やAWS接続はこのtaskでは行わない

不足または不正な値が残る場合は変更せず停止する。

## Create active task contract

最初のrepository changeとして、`tasks/<task-name>.md`を次の条件で新規登録する。

```md
- Task type: `initialization`
```

- goalは確認済みproject topologyとtarget pathの初期化だけとする
- AWS mutation、AWS API、deploy、applyは禁止する
- `Required changes`は一意なRequirement ID付きで、`project.json`作成、target path作成、IaC engine選択を分けて記載する
- `Acceptance checks`は各Requirement IDへ`changed:project.json`、作成対象pathの`exists:`、未選択IaC rootの`absent:`を対応付ける
- allowed pathsは`project.json`、作成対象の`docs/designs/**`、`model/**`、選択済みIaCの初期化path、全targetで未選択のIaC engine root、`tasks/<task-name>.md`に限定する
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
      "awsExecutionAccountId": "<confirmed-optional-12-digit-execution-account-id>",
      "awsRegion": "<confirmed-region>",
      "iacEngine": "<cloudformation-or-terraform>",
      "awsProfile": "<confirmed-optional-profile>",
      "suffix": "<confirmed-optional-suffix>"
    }
  ]
}
```

aliasなしのtargetでは`alias` key自体を省略する。確認済みの初期化値だけを記録し、`UNSET`、background、purpose、account role、design decisionを入れない。
suffixを指定しないtargetでは`suffix` key自体を省略する。suffixは`framework/rules/aws-resource-naming.md`に従って`{{suffix}}`を持つpatternだけに使用する。
AWS実行account IDを指定しないtargetでは`awsExecutionAccountId` key自体を省略する。selectorとpathは`awsAccountId`を維持する。
AWS profileを指定しないtargetでは`awsProfile` key自体を省略する。credentialは記録しない。

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

1. `python framework/scripts/blueprint-loop.py --mode task`
2. `python -m py_compile framework/scripts/blueprint-loop.py framework/scripts/validate-blueprint.py`
3. `git diff --check`

validation結果、作成したtopology、作成path、既存のため変更しなかったpath、blockerはCodexの完了報告だけに記載する。repositoryへverification resultを保存しない。初期化完了後にdesign task、infrastructure task、scenario-test taskを作成または実行しない。
