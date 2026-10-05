# Scenario Test

契約登録・予約・停止／再開は[task-contract](../../rules/task-contract.md)に従う。

このpromptは、deployとは独立した`scenario-test` taskとしてapplication behaviorを検証し、current resultを更新するために使用する。infrastructureの作成、修正、deploy、redeployは行わない。

account／profileの共通選択は[Credentials and account](../../rules/project-configuration.md#credentials-and-account)に従い、policy固有条件は[Policy account selection](../../rules/detailed-design.md#policy-account-selection)を適用する。

## Unresolved issue gate

対象serviceの開始・再開・mutation前の停止判定と例外は[issue-gate](../../rules/issue-gate.md)を適用する。

## User input

- Scenario ID: `{{lower-kebab-case ID}}`
- Target environment: `{{project.jsonのenvironment}}`
- Target alias: `{{project.jsonのalias。aliasなしの場合は省略}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Expected behavior: `{{検証するapplication behavior}}`
- AWS mutation: `forbidden`
- Destructive operation: `forbidden`

## Resolve missing input

placeholder、空、不明な必須inputは、Scenario ID、Target environment、Target alias（選択済みenvironmentに複数targetがある場合だけ）、Target AWS account、Expected behaviorの順で一回の応答につき一つだけ質問する。environment、alias、accountは`project.json`の同じtargetに存在する候補だけを提示し、自動選択しない。environmentにtargetが1件だけの場合はaliasを質問しない。

AWS mutationまたはdestructive operationが必要なscenarioは、対象operation、resource、cleanup、許可範囲がUser inputに明記されるまで実行しない。

## Read before changing files

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. `project.json`
4. [scenario-testing](../../rules/scenario-testing.md)
5. [Local loop](../../rules/loop-engineering.md#local-loop)と[Validation scope](../../rules/loop-engineering.md#validation-scope)と[Scenario-test task completion](../../rules/loop-engineering.md#scenario-test-task-completion)
6. 対象の`tests/scenarios/<scenario-id>/`
7. 対象の`tests/results/<scenario-id>/<environment>/<target-directory>/`
8. [Model authority](../../rules/model-information.md#model-authority)、[Resource management mode](../../rules/model-information.md#resource-management-mode)、[Properties format](../../rules/model-information.md#properties-format)。生成する場合は[Properties先行更新と表示生成](../../rules/model-information.md#properties先行更新と表示生成)、CloudFormationは[CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy)を追加する。
9. 必要な`model/<environment>/<target-directory>/<service-id>.properties`を正本のread-only design inputとして読む
- [project-configuration](../../rules/project-configuration.md)と[issue-gate](../../rules/issue-gate.md)。

設計値は`desired.*`、必要なcurrent identifierは`observed.*`から取得する。入口indexを確認し、既存の`model_files.py --find`で必要なproperty／identifierの位置を特定し、`model_files.py --resource`で対象resourceと必要な参照先resourceだけを部分読み取りする。分割modelは必要なpartの該当箇所だけをLLM contextへ読み込み、生成済み`docs/designs/**`のMarkdown本文を通常のdesign inputとして事前読込しない。

Markdown／JSON artifactの生成と正本propertiesとの整合性検証は既存script／local loopで維持する。LLMの事前読込を省くことを理由に、Validation scopeや検証項目を縮小しない。

`<target-directory>`は、選択targetにaliasがあればalias、なければAWS account IDとする。result metadataのAWS accountにはdirectory名ではなく`project.json`の実際のAWS account IDを記録する。

指定sectionの読取範囲と条件付き規則はAGENTS.mdの「必要な規則の読み方」に従う。

### Conditional rule readings

framework変更時は[Framework regression](../../rules/loop-engineering.md#framework-regression)、検証の再利用時は[Validation cache](../../rules/loop-engineering.md#validation-cache)、停止・長時間実行時はloopの該当診断sectionを追加する。README全文と非該当sectionを追加読込せず、schema／参照／account／issue／task固有checkは維持する。

## Create active task contract

最初のrepository changeとして`tasks/<task-name>.md`を次の条件で新規登録する。

- Task typeは`scenario-test`とする。
- goalにscenario ID、environment、aliasがある場合はalias、AWS account、expected behaviorを記載する。
- `Required changes`は一意なRequirement ID付きで、scenario定義／implementationと同じtargetのcurrent result更新を分けて記載する。
- `Acceptance checks`は各Requirement IDへ対象scenario fileとresult fileの`changed:`を対応付ける。
- AWS mutationとdestructive operationは確認済みUser inputの値をそのまま記載する。
- Allowed pathsは対象の`tests/scenarios/<scenario-id>/**`、`tests/results/<scenario-id>/<environment>/<target-directory>/**`、`tasks/<task-name>.md`だけに限定する。
- `docs/**`、`model/**`、`infra/**`は変更禁止とする。

## Define and execute

AWS実行前に`check-deploy-context.py --environment <environment>`へ`--alias <alias>`または`--aws-account-id <account-id>`と`--read-only`を渡し、target、caller account、regionを確認する。targetの`awsProfile`があればpreflightが自動使用する。scenarioのすべてのAWS CLI／SDKと子processでも同じprofileを使用し、`scenario-testing.md`の実行ルールに従う。未設定時は従来の認証方法を維持する。

1. `framework/rules/scenario-testing.md`に従い、scenario definitionと必要最小限のtest implementationを作成または更新する。
2. expected behaviorを実際に観測できる手順を使用し、deploy完了statusや静的設定だけをPASS根拠にしない。
3. prerequisites不足またはcredential/permission不足は`BLOCKED`、実行して合格条件を満たさない場合は`FAIL`とする。
4. 許可されたcleanupだけを実行し、結果を記録する。
5. stableなcurrent resultとevidenceだけを同じresult directoryへ更新する。

failure時もdesign変更、IaC修正、redeploy、別task作成を行わない。根本原因と観測事実を簡潔に報告してscenario-test taskを終了する。

## Verify and finish

1. `python framework/scripts/blueprint-loop.py --mode task`
2. `git diff --check`

scenario ID、target、実行手順、status、expected/actual behavior、evidence、cleanup、blockerを完了報告に記載する。
