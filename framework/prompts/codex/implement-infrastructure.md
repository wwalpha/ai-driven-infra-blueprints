# Infrastructure Implementation and Deployment Prompt

このpromptは、承認済みの詳細設計を`project.json`で選択済みのCloudFormationまたはTerraformへ変換し、安全確認、許可されたdeploy/apply、deploy完了確認までを一つの`infrastructure` taskで実行するために使用する。application behaviorの検証は別の`scenario-test` taskで行う。

## User input

- Target environment: `{{project.jsonのenvironment}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Implementation scope: `{{対象の詳細設計fileまたはresource group。複数可。「対象accountの承認済み設計すべて」も可}}`
- Deploy/apply: `{{allowedまたはforbidden}}`
- Authorized delete/replacement: `none`
- AWS profile: `{{使用するprofile名。default credential chainの場合は空}}`

## Resolve missing input

fileを変更する前にUser inputを確認する。placeholder、空、不明な値はmissingとして扱い、次の順序で一回の応答につき一つだけ質問する。

1. Target environment
2. Target AWS account
3. Implementation scope
4. Deploy/apply

environmentとAWS accountは`project.json`に存在する候補だけを提示し、自動選択しない。Deploy/applyは`allowed`が明示された場合だけ許可し、それ以外は`forbidden`とする。delete/replacementは、対象resourceと理由がUser inputに明記されていない限り許可しない。

AWS profileがplaceholderまたは空の場合はdefault credential chainを使用し、profile名を質問しない。

`project.json`、対象の承認済み詳細設計、または対応するservice modelが存在しない場合は、値を推測せず停止する。

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
10. `framework/rules/observed-values.md`
11. `framework/rules/loop-engineering.md`
12. 対象resourceに関係する`framework/materials/aws/*.properties`
13. `framework/materials/cloudformation-schema/ap-northeast-1/index.json`と対象resourceのCloudFormation provider schema

詳細設計とservice modelが矛盾する場合、またはIaC実装に必要なhuman decisionが不足する場合は、どちらかを推測して採用せず、別の`design` taskが必要であることを報告して停止する。

## Create active task contract

最初のrepository changeとして`tasks/active.md`を今回の対象だけを許可する内容へ上書きする。

- Task typeは`infrastructure`とする。
- goalにtarget environment、AWS account、implementation scope、選択済みIaC engineを記載する。
- `Required changes`は一意なRequirement ID付きで、IaC implementation、許可されたexecution、成功後に必要なobserved value更新を分けて記載する。
- `Acceptance checks`は各Requirement IDへ対象IaC fileの`changed:`、必要なoutputの`exists:`または登録済みcheckを対応付ける。deploy/applyの未許可または未実行をrepository fileで偽装しない。
- AWS API executionは対象account/regionのpreflight、validation、plan、許可されたdeploy/apply、deploy完了確認、observed value収集だけに許可する。
- Deploy/applyは確認済みUser inputの値をそのまま記載する。
- Authorized delete/replacementは確認済みUser inputの値をそのまま記載する。
- Allowed pathsは対象のIaC file、`model/<environment>/<aws-account-id>/**`、deploy後にgenerated current valueを更新する対象詳細設計file、`tasks/active.md`だけに限定する。
- 別targetの`model/**`、`tests/scenarios/**`、`tests/results/**`は変更禁止とする。

## Preflight

credential、deploy先account、AWS region、IaC engine、必要commandをLLMの推論で判定しない。repository rootから次を実行する。AWS profileが空の場合は`--profile`を省略する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --aws-account-id <12-digit-account-id> [--profile <profile>]
```

scriptが終了code 0を返した場合だけ、出力されたregionとIaC engineを使用して続行する。失敗時は推測、credential切替、account変更、check bypassを行わず、scriptの理由を簡潔に報告して停止する。secretやcredential値を表示または保存しない。

preflight成功後、unrelatedなworktree変更を上書きまたは巻き戻さず、CloudFormation stackまたはTerraform stateと既存resourceをread-onlyで確認する。engine切替、missing input、state/backendの不明点があれば停止する。

## Resolve CloudFormation deployment units

CloudFormationの場合、implementation scopeから対象template、stack、parameter file、dependencyを特定する。

- 既存templateとstack boundaryがある場合は再利用する。
- 新規templateは`framework/rules/cloudformation.md`の`1 template = 1 deploy responsibility`に従って必要最小限に分割する。
- AWS service単位で機械的にtemplateを分割しない。
- 各deployment unitについてtemplate path、stack name、parameter path、依存stackを確定する。
- cross-stack referenceからdependency順を決定する。
- dependencyがないunit同士はtemplate path順で実行する。
- dependency cycle、stack name不足、parameter不足、参照先不明がある場合は、根本原因と不足情報を簡潔に報告して停止する。

preflightはtarget environment／AWS accountにつき一回だけ実行する。

## Implement and validate

承認済みdesignと対応するservice modelだけをinputとして、選択済みengineの最小構成を実装する。未使用resource、将来用module、compatibility layerは作成しない。

CloudFormationの場合:

1. `infra/cloudformation/templates/`と対象の`infra/cloudformation/parameters/<environment>/<aws-account-id>/`だけを変更する。
2. 対象となる全templateへ`cfn-lint --regions <project.jsonのawsRegion> <template...>`を実行し、provider schemaに基づくproperty、型、制約を検証する。
3. 全templateへ`aws cloudformation validate-template`を実行して構文を検証する。これだけをschema validationの代替にしない。
4. validation failureは根本原因を調査し、確定済みdesign内で修正可能なら最小修正して再実行する。
5. validation完了後、dependency順にdeployment unitを一つずつ処理する。
6. 各unitで最新parameterを解決し、change setを作成してadd、change、delete、replacementがimplementation scopeと許可範囲内であることを確認する。
7. Deploy/applyが`allowed`の場合だけchange setを実行し、stackがterminal successになるまで待つ。
8. stack成功後に必要なobserved valueとgenerated current valueを更新してから、次のunitへ進む。
9. Deploy/applyが`forbidden`の場合はchange set結果までを報告し、実行しない。

Terraformの場合:

1. 必要な`infra/terraform/modules/`と対象の`infra/terraform/environments/<environment>/<aws-account-id>/`だけを変更する。
2. `terraform fmt -check`、`terraform validate`、`terraform plan`を実行する。
3. planのadd、change、destroy、replacementとsensitive outputを確認する。

plan/change setがimplementation scopeを超える、target account/regionと一致しない、または未許可のdelete/replacementを含む場合は実行せず停止する。

validation、change set作成、Terraform planが失敗した場合は、最初に根本原因を調査する。確定済みdesignの範囲内で直せるIaC implementation errorなら最小修正後にvalidationまたはplanを再実行する。自動修正は最大3 iterationとし、material progressなしで同じerrorが2回続いた場合は停止する。

必須情報、human decision、credential、permission、account、region、design変更、未許可のdelete/replacementが必要な場合は自動修正せず、不足内容と根本原因を簡潔に報告して停止する。

## Deploy and confirm completion

Deploy/applyが`allowed`の場合だけ、CloudFormationは各deployment unitの確認済みchange set、Terraformは確認済みplanを変更せず実行する。`forbidden`の場合はvalidationとplan/change set結果を報告して終了する。

CloudFormationのdeployment unitが失敗した場合はstack eventsとrollback状態から根本原因を調査する。rollbackがterminal stateとなり、確定済みdesignの範囲内で安全に直せるIaC implementation errorなら、同じunitだけを最小修正、validation、change set再作成、deployする。validation/planと同じretry上限を適用し、原因を確認せず同じdeployを再実行しない。

必須情報、human decision、credential、permission、account、region、design変更、未許可のdelete/replacement、rollback failureが原因の場合は簡潔に報告して停止する。

retry上限超過または停止条件に該当した場合は後続deployment unitを実行しない。既に成功したstackを自動rollback、delete、redeployせず、そのobserved valueをcurrent stateとして保持する。成功済み、失敗、未実行のdeployment unitを完了報告で区別する。

Terraform apply failureはpartial applyの可能性があるため、stateとAWS実体をread-onlyで確認し、apply、destroy、修正を自動実行せず簡潔に報告して停止する。

deploy/applyが成功した場合:

1. CloudFormation stack operationまたはTerraform applyがterminal successになるまで確認する。
2. 成功したAWS mutation後だけ、詳細設計の`PENDING_DEPLOY`などgenerated current valueを実値へ更新し、intended designは変更しない。
3. `framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>`を実行し、同じservice propertiesの`observed.*`へ反映する。

deploy完了status、resource存在、observed value収集をapplication behaviorの検証またはscenario PASSとして扱わない。

## Verify and finish

1. 選択済みIaCのsyntax/static validationを再確認する。
2. `python framework/scripts/blueprint-loop.py --mode local`
3. `git diff --check`

target、account、region、engine、preflight結果、変更file、deployment unitとdependency順、plan/change set summary、deploy完了status、observed value更新、retry、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

scenario、scenario result、別environment、別AWS account、次taskを作成または実行しない。application behaviorの検証には、humanが別taskとして`framework/prompts/codex/run-scenario-test.md`を使用する。
