# Infrastructure Implementation Prompt

このpromptは、承認済みの詳細設計を`project.json`で選択済みのCloudFormationまたはTerraformへ変換し、local static validationまでを行う`infrastructure` taskに使用する。AWS API、change set、plan、deploy/applyは実行しない。deploy/applyは別taskで`framework/prompts/codex/deploy-infrastructure.md`を使用する。

## User input

- Target environment: `{{project.jsonのenvironment}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Implementation scope: `{{対象の詳細設計fileまたはresource group。複数可。「対象accountの承認済み設計すべて」も可}}`

## Resolve missing input

fileを変更する前にUser inputを確認する。placeholder、空、不明な値はmissingとして扱い、次の順序で一回の応答につき一つだけ質問する。

1. Target environment
2. Target AWS account
3. Implementation scope

environmentとAWS accountは`project.json`に存在する候補だけを提示し、自動選択しない。`project.json`、対象の承認済み詳細設計、または対応するservice modelが存在しない場合は、値を推測せず停止する。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. `tasks/active.md`
4. `project.json`
5. 対象の`docs/designs/<environment>/<aws-account-id>/*.md`
6. 対応する`model/<environment>/<aws-account-id>/*.properties`
7. `framework/rules/detailed-design.md`
8. `framework/rules/model-information.md`
9. 選択済みengineに対応する`framework/rules/cloudformation.md`または`framework/rules/terraform.md`
10. `framework/rules/loop-engineering.md`
11. 対象resourceに関係する`framework/materials/aws/*.properties`
12. CloudFormationの場合は`framework/materials/cloudformation-schema/ap-northeast-1/index.json`と対象resourceのprovider schema

詳細設計とservice modelが矛盾する場合、またはIaC実装に必要なhuman decisionが不足する場合は、別の`design` taskが必要であることを報告して停止する。

## Create active task contract

最初のrepository changeとして`tasks/active.md`を今回の対象だけを許可する内容へ上書きする。

- Task typeは`infrastructure`とする。
- Infrastructure phaseは`implement`とする。
- goalにtarget environment、AWS account、implementation scope、選択済みIaC engineを記載する。
- AWS mutation、AWS API execution、deploy/applyを`forbidden`とする。
- `Required changes`は一意なRequirement ID付きでIaC implementationとstatic validationを記載する。
- `Acceptance checks`は各Requirement IDへ対象IaC fileの`changed:`または必要なpathの`exists:`を対応付ける。
- Allowed pathsは対象のIaC fileと`tasks/active.md`だけに限定する。詳細設計、model、scenarioは変更禁止とする。

## Resolve implementation units

対象scopeから必要なtemplate/module、parameter、dependencyを特定する。既存boundaryと共通部品があれば再利用し、未使用resource、将来用module、compatibility layerは作成しない。

CloudFormationでは`framework/rules/cloudformation.md`の`1 template = 1 deploy responsibility`に従う。AWS service単位で機械的に分割しない。dependency cycle、parameter不足、参照先不明がある場合は、不足情報を報告して停止する。

## Implement and validate

承認済みdesignと対応するservice modelだけをinputとして、選択済みengineの最小構成を実装する。

CloudFormationの場合:

1. `infra/cloudformation/templates/`と対象の`infra/cloudformation/parameters/<environment>/<aws-account-id>/`だけを変更する。
2. 対象となる全templateへ`cfn-lint --regions <project.jsonのawsRegion> <template...>`を実行する。
3. `aws cloudformation validate-template`、change set作成、AWS APIは実行しない。

Terraformの場合:

1. 必要な`infra/terraform/modules/`と対象の`infra/terraform/environments/<environment>/<aws-account-id>/`だけを変更する。
2. `terraform fmt -check`、freshな`TF_DATA_DIR`を使った`terraform init -backend=false`、`terraform validate`を実行する。
3. `terraform plan`、`terraform apply`、AWS APIは実行しない。state fileとplan binaryを作成または保存しない。

static validationが失敗した場合は根本原因を調査する。確定済みdesign内で修正可能なIaC implementation errorだけを最小修正し、最大3 iterationまで再実行する。material progressなしで同じerrorが2回続く、またはhuman decisionやdesign変更が必要な場合は停止する。

## Verify and finish

1. 選択済みIaCのlocal static validationを再確認する。
2. `python framework/scripts/blueprint-loop.py --mode local`
3. `git diff --check`

target、account、region、engine、変更file、implementation unitとdependency、validation結果、retry、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

AWS API、change set、plan、deploy/apply、observed value更新、scenario、別target、次taskを作成または実行しない。deploy/applyはhumanが別taskとして`framework/prompts/codex/deploy-infrastructure.md`を明示的に使用した場合だけ行う。
