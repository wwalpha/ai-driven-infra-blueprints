# Repository Initialization Prompt

このpromptは、Codexが初期化に必要な確定値をhumanへ確認し、`project-topology.json`とtarget pathを作成するために使用する。`docs/system-overview.md`の作成・記入状態を前提にしない。

humanへJSONの作成・編集を依頼してはいけない。質問、回答、正規化、file作成はこのinitialization task内で完結させる。

## First response

prompt実行後の最初の応答ではfileを変更せず、次の形式でまとめて質問する。

```text
repository初期化に必要な情報をまとめて回答してください。

1. Project name
2. EnvironmentとAWS account

| Environment ID | AWS account ID | AWS region | IaC engine |
| --- | --- | --- | --- |
| 例ではなく実値を入力 | 12桁 | 例: ap-northeast-1 | cloudformation または terraform |

- EnvironmentまたはAWS accountが複数ある場合は行を追加してください。
- 1つのenvironmentに複数AWS accountを指定できます。
- 分からない項目がある場合は、その項目を「不明」としてください。
```

## Read first

1. `AGENTS.md`
2. `README.md`
3. 既存の`project-topology.json`（存在する場合）
4. `rules/loop-engineering.md`

## Stop before reinitialization

`project-topology.json`が既に存在する場合はinitialization済みとして扱う。fileや既存pathを変更せず、topology変更には別のmigration taskが必要であることを報告して停止する。

## Collect required values

First responseで次を一つのbatchとして確認する。

1. Project name
2. 使用する全Environment ID
3. 各environmentで使用する全AWS account ID
4. 各environment/AWS accountのAWS region
5. 各environment/AWS accountのIaC engine

Environment IDはlower-kebab-case、AWS account IDは12桁、IaC engineは`cloudformation`または`terraform`と説明する。

質問票、回答履歴、session state fileを作成しない。回答に不足や矛盾がある場合だけ、未解決項目をまとめて再質問する。値を推測しない。

## Validate answers

file変更前に次を確認する。

- Project nameが空でない
- targetが1件以上ある
- Environment IDがlower-kebab-case
- AWS account IDが12桁
- AWS regionが空でない
- IaC engineが`cloudformation`または`terraform`
- 同じenvironment/AWS accountが重複していない

不足または不正な値が残る場合は変更せず停止する。

## Create active task contract

最初のrepository changeとして、`tasks/active.md`を次の条件で上書きする。

```md
- Task type: `initialization`
```

- goalは確認済みproject topologyとtarget pathの初期化だけとする
- AWS mutation、AWS API、deploy、applyは禁止する
- allowed pathsは`project-topology.json`、作成対象の`docs/designs/**`、`llm/**`、選択済みIaCの初期化path、`tasks/active.md`に限定する
- resource設計、IaC implementation、AWS接続確認は対象外とする
- `tests/scenarios/**`と`tests/results/**`を変更しない

## Create project topology

humanが確認した値からrepository rootに`project-topology.json`を作成する。UTF-8、2-space indentation、final newlineを使用し、targetはenvironment、AWS account IDの順に並べる。

```json
{
  "projectName": "<confirmed-project-name>",
  "targets": [
    {
      "environment": "<confirmed-environment-id>",
      "awsAccountId": "<confirmed-12-digit-account-id>",
      "awsRegion": "<confirmed-region>",
      "iacEngine": "<cloudformation-or-terraform>"
    }
  ]
}
```

確認済みの初期化値だけを記録し、`UNSET`、background、purpose、account role、design decisionを入れない。

## Create target paths

各targetについて、存在しないpathだけを作成し、空directoryには`.gitkeep`を置く。

```text
docs/designs/<environment>/<aws-account-id>/.gitkeep
llm/designs/<environment>/<aws-account-id>/.gitkeep
llm/actuals/<environment>/<aws-account-id>/.gitkeep
```

IaC engineが`cloudformation`の場合:

```text
infra/cloudformation/parameters/<environment>/<aws-account-id>/.gitkeep
```

IaC engineが`terraform`の場合:

```text
infra/terraform/environments/<environment>/<aws-account-id>/.gitkeep
```

## Do not create

- 空の詳細設計Markdown
- 空のLLM design properties
- CloudFormation template
- Terraform module、resource、provider、state設定
- questionnaire、回答履歴、session state
- sample environment、sample AWS account
- scenario、scenario result、general task evidence

## Existing repository handling

- 既存のdesign、actual、IaC implementationを上書きしない。
- target pathが既に存在する場合は再利用し、`.gitkeep`のためだけに内容を変更しない。
- 確認済みtopologyと既存target pathまたはIaC engineが矛盾する場合は停止する。

## Verify and finish

1. `bash scripts/blueprint-loop.sh --mode local`
2. `python3 -m py_compile scripts/validate-blueprint.py`
3. `bash -n scripts/blueprint-loop.sh`
4. `git diff --check`

validation結果、作成したtopology、作成path、既存のため変更しなかったpath、blockerはCodexの完了報告だけに記載する。repositoryへverification resultを保存しない。初期化完了後にdesign task、infrastructure task、scenario-test taskを作成または実行しない。
