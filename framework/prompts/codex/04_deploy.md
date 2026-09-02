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

environment、alias、AWS accountは`project.json`の同じtargetに存在する候補だけを提示し、自動選択しない。environmentにtargetが1件だけの場合はaliasを質問しない。delete/replacementは、対象resourceと理由がUser inputに明記されている場合だけ事前承認済みとして扱う。事前承認がない場合は`none`のままchange setまたはplanを作成し、未承認のdelete/replacementを検出した場合だけ作成後にhumanへ確認する。AWS profileがplaceholderまたは空の場合はdefault credential chainを使用し、profile名を質問しない。

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
- Authorized delete/replacementは確認済みUser inputの値、入力がない場合は`none`を記載する。change setまたはplan作成後にhumanが承認した場合は、同じtaskのまま対象resource、action、確認済み理由へ更新する。
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
4. 未承認のdelete/replacementがある場合は次の`Confirm unapproved delete/replacement`に従い、change setを実行せずhuman確認待ちにする。
5. 事前承認済みまたはchange set作成後にhuman承認された同じchange setだけを実行し、stackがterminal successになるまで待つ。
6. 成功後、必要なnon-ARN identifierをstack Outputsから取得し、対象outputがない場合だけstack resourceの`PhysicalResourceId`を使用する。両方が存在する場合は一致を確認し、正式なidentifier output rowと全参照元を更新してから次のunitへ進む。

Terraformの場合:

1. `terraform fmt -check`、`terraform validate`、`terraform plan -out=<repository外の一時path>`を実行する。
2. planのadd、change、destroy、replacementとsensitive outputを確認する。
3. 未承認のdestroy/replacementがある場合は次の`Confirm unapproved delete/replacement`に従い、保存済みplanをapplyせずhuman確認待ちにする。
4. 事前承認済みまたはplan作成後にhuman承認された同じplan binaryだけを`terraform apply`で実行する。
5. 成功後、必要なnon-sensitive identifierをTerraform outputから取得し、対象outputがない場合だけstateのresource attributeをread-onlyで参照する。両方が存在する場合は一致を確認し、正式なidentifier output rowと全参照元を更新する。

## Confirm unapproved delete/replacement

未承認のdelete/replacementだけを検出した場合はdeployment failureまたはtask完了として扱わず、同じtaskをhuman確認待ちにする。全deploymentを一律に確認待ちにしない。

次の順序で、technical summaryだけでなく人間が判断できる説明を表示する。

1. 検出した変更: stack名またはTerraform root/workspaceと、add、change、delete/destroy、replacementの件数を示す。
2. 停止した直接理由: どのdelete/replacementが事前承認と一致しないかを示す。
3. 対象resource: CloudFormationはlogical ID、physical ID、resource type、Remove/Replace、`Replacement`、`PolicyAction`、`DeletionPolicy`／`UpdateReplacePolicy`、判明した変更理由を示す。Terraformはresource address、resource type、destroy/replacement action、判明した変更理由を示し、sensitive valueを表示しない。
4. 実行した場合の影響: physical resource、保存データ、設定、access、availabilityへの判明している影響を平易に説明する。推測せず、確認できない影響は`未確認`と明記する。
5. 現在の実行状態: 対象change setまたは保存済みplanが未実行であることを明記し、同じtask内に成功済み、失敗、未実行の別unitがあれば区別してAWS resource変更の有無を正確に示す。
6. 選択可能な対応: 全対象を承認して同じdeploymentを継続、判断に必要な追加read-only確認、承認せず実行中止、または別taskでIaCを変更してresource保持／管理外化を行う選択肢を示す。現在のchange setまたはplanの一部だけを実行できるように表現しない。
7. Humanへの確認質問: 同じchange setまたは保存済みplanの列挙した全delete/replacementを、示した理由で承認するかを一つの質問で確認する。

humanが追加情報を求めた場合は、同じtaskのdeployment scope内でlist/get/describe相当のread-only operationだけを実行して説明を補い、同じ質問を再提示する。データ削除、resource変更、IaC修正は行わない。

humanが全対象と理由を承認した場合は、`tasks/active.md`のAuthorized delete/replacementを承認済みresource、action、理由へ更新し、次を確認して同じtaskを再開する。

- CloudFormationは同じchange set IDを再取得し、statusが`CREATE_COMPLETE`、execution statusが`AVAILABLE`、承認対象のlogical ID、action、replacement、`PolicyAction`が一致する場合だけそのchange setを実行する。
- Terraformは同じ保存済みplanを再確認し、承認対象のresource address、resource type、actionが一致する場合だけそのplan binaryをapplyする。
- change setまたはplanが失効、再作成、変更されている場合は以前の承認を使用せず、新しい内容を説明して再確認する。

humanが承認しない、または一部だけを承認した場合はchange setまたはplanを実行せず停止する。resource保持、CloudFormation管理外化、configuration変更が必要でも、このdeploy phaseでIaCやintended designを変更しない。

scope超過、account/region不一致、delete/replacementのactionを確定できない、validation/plan failure、credential/permission不足、またはdeployment failureでは停止する。未承認のdelete/replacementだけは上記のhuman確認待ちとし、failureとして終了しない。IaCやintended designをこのtaskで修正せず、同じdeployを原因未確認で再実行しない。CloudFormationは成功済み、失敗、未実行のunitを区別し、成功済みstackを自動rollback、delete、redeployしない。Terraform apply failureはpartial applyの可能性があるため、stateとAWS実体をread-onlyで確認して停止する。

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

target、account、region、engine、preflight結果、deployment unitとdependency順、plan/change set summary、human確認待ちと承認結果、deploy完了status、observed value更新、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

IaC、intended design、scenario、scenario result、別target、次taskを変更、作成、実行しない。application behaviorの検証には、humanが別taskとして`framework/prompts/codex/06_scenario-test.md`を使用する。
