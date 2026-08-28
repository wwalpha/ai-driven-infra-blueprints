# Infrastructure Deployment Prompt

このpromptは、承認済みの詳細設計から作成・検証済みのCloudFormationまたはTerraformを変更せずにdeploy/applyし、deploy完了確認と必要なobserved value更新を行う`infrastructure` taskに使用する。IaC修正とapplication behavior検証は行わない。

## User input

- Target environment: `{{project.jsonのenvironment}}`
- Target alias: `{{project.jsonのalias。aliasなしの場合は省略}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Deployment scope: `{{対象のtemplate/stackまたはTerraform root/resource。複数可}}`
- Authorized delete/replacement: `none`
- AWS profile: `{{使用するprofile名。default credential chainの場合は空}}`

## Resolve missing input

AWS APIを実行する前にUser inputを確認する。placeholder、空、不明な値はmissingとして扱い、次の順序で一回の応答につき一つだけ質問する。

1. Target environment
2. Target alias（選択済みenvironmentに複数targetがある場合だけ）
3. Target AWS account
4. Deployment scope

environment、alias、AWS accountは`project.json`の同じtargetに存在する候補だけを提示し、自動選択しない。environmentにtargetが1件だけの場合はaliasを質問しない。delete/replacementは、対象resourceと理由がUser inputに明記されていない限り許可しない。AWS profileがplaceholderまたは空の場合はdefault credential chainを使用し、profile名を質問しない。

`project.json`、対象の承認済み詳細設計、対応するservice model、または対象IaCが存在しない場合は、値を推測せず停止する。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. `tasks/active.md`
4. `project.json`
5. 対象の`docs/designs/<environment>/<target-directory>/*.md`
6. 対応する`model/<environment>/<target-directory>/*.properties`
7. `framework/rules/detailed-design.md`
8. `framework/rules/model-information.md`
9. 選択済みengineに対応する`framework/rules/cloudformation.md`または`framework/rules/terraform.md`
10. `framework/rules/observed-values.md`
11. `framework/rules/loop-engineering.md`
12. 対象IaC file

詳細設計、service model、IaCが矛盾する場合は、値やIaCを修正せず停止する。

`<target-directory>`は、選択targetにaliasがあればalias、なければAWS account IDとする。

## Create active task contract

最初のrepository changeとして`tasks/active.md`を今回の対象だけを許可する内容へ上書きする。

- Task typeは`infrastructure`とする。
- Infrastructure phaseは`deploy`とする。
- goalにtarget environment、aliasがある場合はalias、AWS account、deployment scope、選択済みIaC engineを記載する。
- AWS API executionとdeploy/applyは今回のdeployment scopeに限り`allowed`とする。
- Authorized delete/replacementは確認済みUser inputの値をそのまま記載する。
- `Required changes`は一意なRequirement ID付きでdeploymentと、必要な場合だけ成功後のobserved value更新を記載する。
- `Acceptance checks`はdeployment unitの`exists:`と、observed value更新が必要な場合だけ対象詳細設計/modelの`changed:`を対応付ける。deploy未実行や失敗をrepository fileで完了扱いにしない。
- Allowed pathsは、generated current value更新が必要な対象詳細設計、対応する`model/<environment>/<target-directory>/**`、`tasks/active.md`だけに限定する。`infra/**`と`tests/**`は変更禁止とする。

## Preflight

対象IaCにuncommitted changeがある場合はdeploy対象revisionが一意でないため停止する。unrelatedなworktree変更は上書きまたは巻き戻さない。

credential、deploy先account、AWS region、IaC engine、必要commandをLLMの推論で判定しない。repository rootから次を実行する。AWS profileが空の場合は`--profile`を省略する。

aliasがあるtargetでは次を実行する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --alias <alias> [--profile <profile>]
```

aliasがないtargetでは次を実行する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --aws-account-id <12-digit-account-id> [--profile <profile>]
```

scriptが終了code 0を返した場合だけ、出力されたregionとIaC engineを使用して続行する。失敗時は推測、credential切替、account変更、check bypassを行わず停止する。secretやcredential値を表示または保存しない。

preflight成功後、対象stackまたはTerraform stateと既存resourceをread-onlyで確認する。engine切替、state/backendの不明点、対象IaCと承認済みdesignの不一致があれば停止する。

## Resolve deployment units

CloudFormationでは対象template、stack、parameter file、dependencyを既存IaCから特定する。cross-stack referenceからdependency順を決定し、dependencyがないunit同士はtemplate path順とする。dependency cycle、stack name不足、parameter不足、参照先不明がある場合は停止する。

Terraformでは対象root、workspace、backend、variable inputを既存IaCから特定する。不足または不一致があれば停止する。

preflightはtargetにつき一回だけ実行する。

## Validate and deploy

CloudFormationの場合:

1. 対象全templateへ`cfn-lint --regions <project.jsonのawsRegion> <template...>`を実行する。
2. 対象全templateへ`aws cloudformation validate-template`を実行する。
3. dependency順に各unitのchange setを作成し、add、change、delete、replacementがdeployment scopeと許可範囲内であることを確認する。
4. 確認済みchange setだけを実行し、stackがterminal successになるまで待つ。
5. 成功後、必要なnon-ARN identifierをstack Outputsから取得し、対象outputがない場合だけstack resourceの`PhysicalResourceId`を使用する。両方が存在する場合は一致を確認し、正式なidentifier output rowと全参照元を更新してから次のunitへ進む。

Terraformの場合:

1. `terraform fmt -check`、`terraform validate`、`terraform plan -out=<repository外の一時path>`を実行する。
2. planのadd、change、destroy、replacementとsensitive outputを確認する。
3. 確認済みplan binaryだけを`terraform apply`で実行する。
4. 成功後、必要なnon-sensitive identifierをTerraform outputから取得し、対象outputがない場合だけstateのresource attributeをread-onlyで参照する。両方が存在する場合は一致を確認し、正式なidentifier output rowと全参照元を更新する。

scope超過、account/region不一致、未許可のdelete/replacement、validation/plan failure、credential/permission不足、またはdeployment failureでは停止する。IaCやintended designをこのtaskで修正せず、同じdeployを原因未確認で再実行しない。CloudFormationは成功済み、失敗、未実行のunitを区別し、成功済みstackを自動rollback、delete、redeployしない。Terraform apply failureはpartial applyの可能性があるため、stateとAWS実体をread-onlyで確認して停止する。

deploy/applyが成功した場合:

1. terminal successとresource存在を確認する。
2. `framework/rules/observed-values.md`に従い、取得した値をcatalogの正式な`IDENTIFIER_OUTPUT` propertyへ一意に対応付ける。identifier output rowと、同じanchorを参照する全propertyのMarkdown link表示textだけを同じphysical IDへ更新し、link先path、anchor、`Source / Comment`、その他のintended designは変更しない。
3. aliasがあるtargetは`framework/scripts/sync-model.py --write --environment <environment> --alias <alias>`、aliasがないtargetは`framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>`を実行する。

必要なoutputがIaCに存在しない、catalog propertyとの対応が一意でない、または参照元と参照先の値が一致しない場合は推測やIaC修正をせず停止する。replacement後は新しいIDへ更新し、destroy後はidentifier output rowと全参照元を`PENDING_DEPLOY`へ戻す。generated ARNは保存しない。

deploy完了status、resource存在、observed value収集をapplication behaviorの検証またはscenario PASSとして扱わない。

## Verify and finish

1. 対象IaCに変更がないことを確認する。
2. `python framework/scripts/blueprint-loop.py --mode local`
3. `git diff --check`

target、account、region、engine、preflight結果、deployment unitとdependency順、plan/change set summary、deploy完了status、observed value更新、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

IaC、intended design、scenario、scenario result、別target、次taskを変更、作成、実行しない。application behaviorの検証には、humanが別taskとして`framework/prompts/codex/06_scenario-test.md`を使用する。
