# Infrastructure Implementation Prompt

このpromptは、承認済みの詳細設計を`project.json`で選択済みのCloudFormationまたはTerraformへ変換し、local static validationまでを行う`infrastructure` taskに使用する。AWS API、change set、plan、deploy/applyは実行しない。deploy/applyは別taskで`framework/prompts/codex/04_deploy.md`を使用する。

## User input

- Target environment: `{{project.jsonのenvironment}}`
- Target alias: `{{project.jsonのalias。aliasなしの場合は省略}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Implementation scope: `{{対象の詳細設計fileまたはresource group。複数可。「対象accountの承認済み設計すべて」も可}}`

## Resolve missing input

fileを変更する前にUser inputを確認する。placeholder、空、不明な値はmissingとして扱い、次の順序で一回の応答につき一つだけ質問する。

1. Target environment
2. Target alias（選択済みenvironmentに複数targetがある場合だけ）
3. Target AWS account
4. Implementation scope

environment、alias、AWS accountは`project.json`の同じtargetに存在する候補だけを提示し、自動選択しない。environmentにtargetが1件だけの場合はaliasを質問しない。`project.json`、対象の承認済み詳細設計、または対応するservice modelが存在しない場合は、値を推測せず停止する。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. `tasks/active.md`
4. `project.json`
5. 対象の`docs/designs/<environment>/<target-directory>/*.md`
6. 対応する`model/<environment>/<target-directory>/*.properties`
7. `framework/rules/detailed-design.md`
8. `framework/rules/aws-resource-naming.md`
9. `framework/rules/model-information.md`
10. 選択済みengineに対応する`framework/rules/cloudformation.md`または`framework/rules/terraform.md`
11. `framework/rules/observed-values.md`
12. `framework/rules/loop-engineering.md`
13. 対象resourceに関係する`framework/materials/aws/*.properties`と`framework/materials/api/*.properties`および同名API設計schema
14. CloudFormationの場合は`framework/materials/cloudformation-schema/ap-northeast-1/index.json`と対象resourceのprovider schema

詳細設計とservice modelが矛盾する場合、またはIaC実装に必要なhuman decisionが不足する場合は、別の`design` taskが必要であることを報告して停止する。

`<target-directory>`は、選択targetにaliasがあればalias、なければAWS account IDとする。

## Create active task contract

最初のrepository changeとして`tasks/active.md`を今回の対象だけを許可する内容へ上書きする。

- Task typeは`infrastructure`とする。
- Infrastructure phaseは`implement`とする。
- goalにtarget environment、aliasがある場合はalias、AWS account、implementation scope、選択済みIaC engineを記載する。
- AWS mutation、AWS API execution、deploy/applyを`forbidden`とする。
- `Required changes`は一意なRequirement ID付きでIaC implementationとstatic validationを記載する。
- `Acceptance checks`は各Requirement IDへ対象IaC fileの`changed:`または必要なpathの`exists:`を対応付ける。
- Allowed pathsは対象のIaC fileと`tasks/active.md`だけに限定する。詳細設計、model、scenarioは変更禁止とする。

## Check implementation support

詳細設計に載るresourceと選択済みengineで実装可能なresourceを分けて確認する。CloudFormationでは実装scope内の各typeに`python framework/scripts/design_catalog.py --cloudformation-type <catalog-resource-type>`を実行し、成功した正式型だけを使う。`Macie.ClassificationJob`はCFn非対応であり、Jobをtemplate、Outputs、`!Ref`へ変換しない。

Jobが要求scopeに含まれる場合は未実装対象として明示し、対応resourceだけの実装を要求全体の完了としない。既にCFn対応範囲へ限定されたtaskはその範囲で終了できる。非対応を理由にCustom Resource、別engine、API mutationを追加しない。

## Resolve implementation units

対象scopeから必要なtemplate/module、parameter、dependencyを特定する。既存boundaryと共通部品があれば再利用し、未使用resource、将来用module、compatibility layerは作成しない。

CloudFormationでは`framework/rules/cloudformation.md`の`1 template = 1 deploy responsibility`に従う。AWS service単位で機械的に分割しない。dependency cycle、parameter不足、参照先不明がある場合は、不足情報を報告して停止する。

対象resourceへの`!Ref`、`!GetAtt`、`!Sub`と、policy/設定値の文字列に含まれるresource参照を確認する。template外のresourceなら、設計linkと既存IaCから実際の所有stack、必要な値、producer Output/Exportを特定する。producer exportがまだdeployされていない場合は、scope内のproducer templateに必要なOutput/Exportだけを追加し、consumerの`!ImportValue`変更はproducer deploy後のtaskへ残す。implement phaseではAWS APIやdeployを実行せず、deploy済みexportの確認が必要な場合はその前提を報告する。producerがscope外または所有先が不明なら変更を広げず停止する。

## Implement and validate

承認済みdesignと対応するservice modelだけをinputとして、選択済みengineの最小構成を実装する。

詳細設計に記載されたtagはCloudFormation／Terraformへそのまま反映する。`EC2.VPC.Name`、`EC2.Subnet.Name`、`EC2.RouteTable.Name`、`EC2.FlowLog.Name`はprovider propertyとして出力せず、case-sensitiveな`Name` keyと同じvalueを持つtagへ変換する。対象resourceに対応する`.Name`とnon-empty valueがない場合だけ、値を推測せず別の`design` taskが必要であることを報告して停止する。

identifierを参照するMarkdown linkはanchorから参照先resourceのlogical IDを解決する。link表示textの`PENDING_DEPLOY`またはphysical IDをIaCへ直書きしない。後続resourceが必要とするcatalog `IDENTIFIER_OUTPUT`だけをCloudFormation OutputsまたはTerraform outputへ追加し、logical resource参照／resource attribute参照を維持する。generated ARNはobserved value用outputにしない。

CloudFormationの場合:

1. aliasがあるtargetでは`infra/cloudformation/templates/<alias>/`、aliasがないtargetでは共通の`infra/cloudformation/templates/`を使用し、対象の`infra/cloudformation/parameters/<environment>/<target-directory>/`だけを変更する。
2. 新規resourceの`Resources` logical IDと`Outputs.*.Export.Name`のtarget別最終値を`framework/rules/cloudformation.md`のPascalCaseにし、設計logical IDとの対応、template内参照、export/importの一致と一意性を確認する。deploy済みproducer exportを確認したconsumerでは、参照値全体と文字列中の参照箇所を`!ImportValue`へ置き換える。既存IDを命名形式だけで変更しない。
3. 対象となる全templateへ`cfn-lint --regions <project.jsonのawsRegion> <template...>`を実行する。
4. `aws cloudformation validate-template`、change set作成、AWS APIは実行しない。

Terraformの場合:

1. aliasがあるtargetでは`infra/terraform/modules/<alias>/`、aliasがないtargetでは共通の`infra/terraform/modules/`を使用し、対象の`infra/terraform/environments/<environment>/<target-directory>/`だけを変更する。
2. `terraform fmt -check`、freshな`TF_DATA_DIR`を使った`terraform init -backend=false`、`terraform validate`を実行する。
3. `terraform plan`、`terraform apply`、AWS APIは実行しない。state fileとplan binaryを作成または保存しない。

static validationが失敗した場合は根本原因を調査する。確定済みdesign内で修正可能なIaC implementation errorだけを最小修正し、最大3 iterationまで再実行する。material progressなしで同じerrorが2回続く、またはhuman decisionやdesign変更が必要な場合は停止する。

## Verify and finish

1. 選択済みIaCのlocal static validationを再確認する。
2. `python framework/scripts/blueprint-loop.py --mode local`
3. `git diff --check`

target、account、region、engine、変更file、implementation unitとdependency、validation結果、retry、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

AWS API、change set、plan、deploy/apply、observed value更新、scenario、別target、次taskを作成または実行しない。deploy/applyはhumanが別taskとして`framework/prompts/codex/04_deploy.md`を明示的に使用した場合だけ行う。
