# Prompt Guide

このdirectoryは、AWS infrastructureを設計・実装・deploy・検証するためのpromptを保持する。各prompt本文を実行時の正本とし、このREADMEはpromptの選択、使用順、開始条件を確認するindexとして使用する。

## Basic usage

1. 実行したい作業に対応するpromptを一つ選ぶ。
2. promptを対象のchatbotまたはCodexへ渡し、`User input`の確定値を依頼文に含める。
3. 値が不足している場合は、promptに従って一問ずつ回答する。値を推測させない。
4. 一つのpromptが完了したら結果を確認して終了する。次のpromptは必要な場合だけ別taskとして明示的に開始する。

一つのenvironmentにtargetが1件だけならaliasは使用しない。複数targetがあるenvironmentでは各targetのhuman-defined aliasを指定し、設計・model・parameter／Terraform root・scenario resultのtarget directoryとして使用する。aliasがあるtargetを実行するpromptにはTarget aliasと、そのtargetに対応する実際のAWS account IDを渡す。

Codexでは、次のように対象promptと値を指定する。

```text
framework/prompts/codex/03_implement.mdを使ってください。
Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Implementation scope: docs/designs/dev/cde/vpc.md
```

## Choose the workflow

| Situation | Use |
| --- | --- |
| chatbotとの設計で新しい詳細設計を作成する | `chatbot/service-design.md` → chatbotが出力したCodex prompt → `03_implement.md` → `04_deploy.md` |
| chatbotが選んだ既存AWS resourceの現在値を詳細設計へ反映する | `chatbot/service-design.md` → chatbotが出力したread-only取得用Codex prompt |
| humanが既存の詳細設計Markdownを直接修正し、未commitのままIaC反映とdeployまで行う | `05_update.md` |
| deploy後にapplication behaviorを確認する | どちらのworkflowでも必要な場合だけ`06_scenario-test.md` |

新規設計では、`service-design.md`が完成したMarkdown／JSONと、それらをrepositoryへ作成する自己完結型Codex promptを出力する。既存AWS resourceの現在値を使用する場合は完成Markdownを出力せず、対象service、resource type、propertyを含むread-only取得用Codex promptを出力する。Codexはresource候補をhumanが選択した後、現在値を詳細設計へ直接差分反映する。どちらも設計保存専用の固定promptは使用しない。

手動修正時はimplementとdeployへ分割しない。`05_update.md`がhumanの設計差分をimmutable inputとして受け取り、model同期、IaC反映、deploy/applyまでを一つのtaskで行う。

## Workflow order

| Order | Prompt | Use when | Result |
| ---: | --- | --- | --- |
| 1 | [`codex/01_initialize.md`](codex/01_initialize.md) | `project.json`がないrepositoryを初期化するとき | project topologyとtarget pathを作成する |
| 2 | [`codex/02_add-target.md`](codex/02_add-target.md) | 初期化後にenvironment／logical targetを1件追加するとき | `project.json`と追加target pathを更新する |
| Design | [`chatbot/service-design.md`](chatbot/service-design.md) | 新しいsystem、機能、serviceの詳細設計値をhumanと確定するとき | 完成したMarkdown／JSON、または既存resource取得用の自己完結型Codex promptを出力する |
| 3 | [`codex/03_implement.md`](codex/03_implement.md) | repositoryへ作成済みの詳細設計をCloudFormation／Terraformへ反映するとき | IaCを作成・変更し、local static validationまで行う |
| 4 | [`codex/04_deploy.md`](codex/04_deploy.md) | 作成・検証済みIaCをAWSへdeploy/applyするとき | IaCを変更せず実行し、必要なobserved valueを更新する |
| 5 | [`codex/05_update.md`](codex/05_update.md) | humanが既存詳細設計を手動修正し、未commitのままIaC反映とdeployまで行うとき | model同期、IaC変更、deploy/apply、observed value更新を一つのtaskで行う |
| 6 | [`codex/06_scenario-test.md`](codex/06_scenario-test.md) | deploy後にapplication behaviorを確認する必要があるとき | scenarioと同じtargetのcurrent resultを更新する |

`02_add-target.md`、`05_update.md`、`06_scenario-test.md`は該当する場合だけ使用する。`05_update.md`は通常の新規設計workflowとは別の分岐である。

## Prompt details

### `chatbot/service-design.md`

- Description: AWS service ownership boundaryごとに、新規詳細設計に必要なhuman decision、または既存AWS resourceから取得するresource type／propertyをchatで確定する。
- Timing: 新しいsystem、機能、serviceを設計し、まだ保存対象Markdown／JSON artifactが確定していないとき。
- How to use: Design target、environment、AWS accountを渡し、質問batchへ回答する。既存resourceの現在値を使用する場合はその旨を回答する。完成後は、chatbotが出力した`Codex反映依頼`をそのままCodexで実行する。既存resource取得ではCodexがread-only AWS contextを検証して候補を提示し、humanがresourceを選択した後、選択済みpropertyだけを詳細設計へ直接差分反映する。

使用例:

```text
framework/prompts/chatbot/service-design.mdを使ってください。

Design target: 社内向けWeb APIのnetwork構成
Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Candidate AWS services: 未定
Expected design files: 未定
```

既存VPCの現在値を詳細設計へ反映する場合:

```text
framework/prompts/chatbot/service-design.mdを使ってください。

Design target: 既存VPCの設定を詳細設計書へ反映
Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Candidate AWS services: vpc
Expected design files: docs/designs/dev/cde/vpc.md
Existing AWS values: EC2.VPCの現在値を使用
```

### `codex/01_initialize.md`

- Description: project、environment、必要な場合はtarget alias、AWS account、region、IaC engineを一問ずつ確認し、repository topologyを初期化する。
- Timing: `project.json`が存在しない最初の一回だけ。既に初期化済みの場合は使用しない。
- How to use: promptをCodexへ渡し、Project nameから順に回答する。全値の最終確認へ明示的に同意するまでrepositoryは変更されない。

使用例:

```text
framework/prompts/codex/01_initialize.mdを使ってください。
```

CodexからProject name、Environment ID、environment内のlogical target数、必要な場合はTarget alias、AWS account ID、AWS region、IaC engineを一つずつ質問されるため、順番に回答する。

### `codex/02_add-target.md`

- Description: 初期化済みrepositoryへ、確定済みのenvironment／alias（必要な場合）／AWS account targetを1件追加する。
- Timing: `project.json`は存在するが、必要なtargetがまだ登録されていないとき。
- How to use: promptをCodexへ渡し、Environment ID、既存environmentがalias方式の場合はTarget alias、AWS account ID、region、IaC engineを順に回答する。一回の実行で追加するtargetは1件だけとする。

使用例:

```text
framework/prompts/codex/02_add-target.mdを使ってください。

Environment ID: dev
Target alias: cde
AWS account ID: 123456789012
AWS region: ap-northeast-1
IaC engine: cloudformation
```

### `codex/03_implement.md`

- Description: 承認済み詳細設計とservice modelから、選択済みCloudFormation／Terraformを作成・変更する。
- Timing: chatbotが出力したCodex promptによる設計反映が完了し、IaCへ反映すべき設計差分があるとき。
- How to use: environment、aliasがある場合はalias、AWS account、implementation scopeを渡す。CloudFormationは`cfn-lint`、Terraformはbackendを使わないlocal validationまで行い、AWS APIやdeploy/applyは実行しない。

使用例:

```text
framework/prompts/codex/03_implement.mdを使ってください。

Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Implementation scope:
- docs/designs/dev/cde/vpc.md
- docs/designs/dev/cde/cloudwatch-logs.md
```

### `codex/04_deploy.md`

- Description: 作成・検証済みIaCを変更せず、対象AWS accountへdeploy/applyする。
- Timing: `03_implement.md`のIaCが確定し、対象IaCにuncommitted changeがないとき。
- How to use: environment、aliasがある場合はalias、AWS account、deployment scope、許可するdelete/replacement、必要ならAWS profileを渡す。preflight、change set／plan確認、実行、完了確認、必要なobserved value更新までを行う。

使用例:

```text
framework/prompts/codex/04_deploy.mdを使ってください。

Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Deployment scope:
- CloudFormation template: infra/cloudformation/templates/vpc.yaml
- Parameter file: infra/cloudformation/parameters/dev/cde/vpc.json
- Stack name: example-dev-cde-vpc
Authorized delete/replacement: none
AWS profile:
```

### `codex/05_update.md`

- Description: humanが既存詳細設計Markdownへ作成したuncommitted diffを確定済みdesignとして受け取り、model同期、IaC反映、deploy/applyまでを行う。
- Timing: 既存詳細設計をhumanが直接修正し、その差分をcommit前にCloudFormation／TerraformとAWS resourceへ反映するとき。
- How to use: promptの使用だけを指示する。Codexが変更済み詳細設計のpathからenvironment、AWS account、Design scopeを取得し、対応する既存IaCからDeployment scopeを特定する。delete/replacement許可の省略時は`none`、AWS profileの省略時はdefault credential chainを使用する。複数targetの設計差分が混在する場合は変更せず停止し、deployment unitの不足項目だけ必要に応じて質問する。

使用例:

```text
framework/prompts/codex/05_update.mdを使ってください。
```

### `codex/06_scenario-test.md`

- Description: deployとは別taskでapplication behaviorを検証し、current resultとevidenceを更新する。
- Timing: deploy後にresource存在では確認できないbehaviorを検証するとき。
- How to use: Scenario ID、environment、aliasがある場合はalias、AWS account、expected behaviorを渡す。失敗しても同じtaskで設計変更、IaC修正、redeployへ進まない。

使用例:

```text
framework/prompts/codex/06_scenario-test.mdを使ってください。

Scenario ID: private-api-connectivity
Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Expected behavior: 社内networkからprivate APIへ接続し、HTTP 200が返ること
AWS mutation: forbidden
Destructive operation: forbidden
```

## SDD iteration

新規設計をchatbotで作成する場合:

```text
chatbot/service-design.md
  -> chatbotが出力したCodex prompt（詳細設計とmodelを作成）
  -> 03_implement.md
  -> 04_deploy.md
  -> 06_scenario-test.md（behavior確認が必要な場合だけ）
```

既存詳細設計をhumanが直接修正する場合:

```text
humanがdocs/designs/**/*.mdを修正（未commit）
  -> 05_update.md
  -> 06_scenario-test.md（behavior確認が必要な場合だけ）
```

設計変更に新しいhuman decisionが必要な場合は、repositoryを変更する前にchatで判断を確定する。未確定値、placeholder、推測値をCodexへ渡さない。

## Task boundaries

- `service-design.md`が出力したCodex promptは詳細設計とmodelだけを変更する。
- `03_implement.md`はIaCだけを変更し、AWS APIを実行しない。
- `04_deploy.md`はIaCを変更せず、許可されたdeploy/applyだけを実行する。
- `05_update.md`はhumanの詳細設計差分を変更せず、model、IaC、generated current valueだけを更新してdeploy/applyする。
- `06_scenario-test.md`はscenarioとresultだけを変更し、設計やIaCを修正しない。
- deploy成功をapplication behaviorのPASSとして扱わない。
