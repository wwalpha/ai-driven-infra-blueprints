# Infrastructure Deployment Prompt

契約は`tasks/<task-name>.md`へtaskごとに登録する。Task statusを`running`とし、`## Modified files`へ今回変更する具体的なfile path（契約自身、新規file、生成artifact、model part、削除対象を含む）を列挙する。Allowed pathsのglobは予約fileの代わりにしない。repository外の候補から`task_contract.py --task-file tasks/<task-name>.md --source <候補file>`で登録し、進行中taskとのfile重複があれば新規taskを停止する。既存taskの契約を上書きしない。以後のcommandは`BLUEPRINT_TASK_FILE`で同じ契約を選択し、local loopには`--task-file`を指定する。成功後に今回のstatusだけを`completed`へ変更する。詳細は`framework/rules/loop-engineering.md`に従う。

このpromptは、承認済みの詳細設計から作成・検証済みのCloudFormationまたはTerraformを変更せずにdeploy/applyし、deploy完了確認と必要なobserved value更新を行う`infrastructure` taskに使用する。IaC修正とapplication behavior検証は行わない。

## Unresolved issue gate

対象environment／target／serviceを確定した時点で、通常taskの開始前と再開時に`issues/<environment>/<target-directory>/issues.md`を確認し、`framework/rules/loop-engineering.md`のUnresolved issue gateを適用する。関係する全serviceについて`python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>`を実行する。未解決issueがあれば設計質問、設計保存、IaC変更、deploy/apply、scenarioなど他taskへ進まず、対象issueと停止理由を示す。issue調査とhumanが明示した修復だけを許可し、修復taskには対象serviceだけのValidation scopeとIssue remediationを記載する。AWS mutation直前にも再確認し、既存のtask boundaryとAWS execution許可は維持する。

## User input

- Target environment: `{{project.jsonのenvironment}}`
- Target alias: `{{project.jsonのalias。aliasなしの場合は省略}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Deployment scope: `{{対象のStackNameまたはTerraform root/resource。複数可}}`
- Authorized delete/replacement: `none`
- AWS profile: `{{任意。省略時はtargetのawsProfile、未設定ならdefault credential chain}}`

## Resolve missing input

AWS APIを実行する前にUser inputを確認する。placeholder、空、不明な値はmissingとして扱い、次の順序で一回の応答につき一つだけ質問する。

1. Target environment
2. Target alias（選択済みenvironmentに複数targetがある場合だけ）
3. Target AWS account
4. Deployment scope

environment、alias、AWS accountは`project.json`の同じtargetに存在する候補だけを提示し、自動選択しない。environmentにtargetが1件だけの場合はaliasを質問しない。delete/replacementは、対象resourceと理由がUser inputに明記されている場合だけ事前承認済みとして扱う。事前承認がない場合は`none`のままchange setまたはplanを作成し、未承認のdelete/replacementを検出した場合だけ作成後にhumanへ確認する。AWS profileがplaceholderまたは空の場合はtargetの`awsProfile`を使用し、未設定ならdefault credential chainを使用する。profile名を質問しない。設定と異なる明示profileは実行前に拒否する。

`project.json`、対象の承認済み詳細設計、対応するservice model、または対象IaCが存在しない場合は、値を推測せず停止する。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. 存在する場合は`tasks/<task-name>.md`。ない場合はidle状態として扱い、Create active task contractで最初に作成する。
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

最初のrepository changeとして`tasks/<task-name>.md`を今回の対象だけを許可する内容へ新規登録する。

- Task typeは`infrastructure`とする。
- Infrastructure phaseは`deploy`とする。
- goalにtarget environment、aliasがある場合はalias、AWS account、deployment scope、選択済みIaC engineを記載する。
- AWS API executionとdeploy/applyは今回のdeployment scopeに限り`allowed`とする。
- Authorized delete/replacementは確認済みUser inputの値、入力がない場合は`none`を記載する。change setまたはplan作成後にhumanが承認した場合は、同じtaskのまま対象resource、action、確認済み理由へ更新する。
- `Required changes`は一意なRequirement ID付きでdeploymentと、必要な場合だけ成功後のobserved value更新を記載する。
- `Acceptance checks`はdeployment unitの`exists:`と、observed value更新が必要な場合だけ対象詳細設計/modelの`changed:`を対応付ける。deploy未実行や失敗をrepository fileで完了扱いにしない。
- Allowed pathsは、generated current value更新が必要な対象詳細設計、対応する`model/<environment>/<target-directory>/**`、`tasks/<task-name>.md`だけに限定する。`infra/**`と`tests/**`は変更禁止とする。

## Preflight

対象IaCにuncommitted changeがある場合はdeploy対象revisionが一意でないため停止する。unrelatedなworktree変更は上書きまたは巻き戻さない。

credential、deploy先account、AWS region、IaC engine、必要commandをLLMの推論で判定しない。repository rootから次を実行する。追加inputがなければ`--profile`を省略してよい。scriptはtargetの`awsProfile`を自動使用する。

aliasがあるtargetでは次を実行する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --alias <alias> [--profile <profile>]
```

aliasがないtargetでは次を実行する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --aws-account-id <12-digit-account-id> [--profile <profile>]
```

scriptが終了code 0を返した場合だけ、出力されたregion、profile（設定時）、IaC engineを使用して続行する。直接のAWS CLIにも同じ`--profile`を渡し、SDKにも同じprofileを明示する。Terraformのprovider／AWS backendには`terraform.md`に従いprocess単位で同じ`AWS_PROFILE`を渡す。失敗時は推測、credential切替、account変更、check bypassを行わず停止する。secretやcredential値を表示または保存しない。

preflight成功後、対象stackまたはTerraform stateと既存resourceをread-onlyで確認する。CloudFormationのcross-stack参照では`describe-stacks`でproducerのOutputs、`list-exports`で同じaccount・regionのdeploy済みexportsを調べ、export名、値、`ExportingStackId`を照合する。engine切替、state/backendの不明点、対象IaCと承認済みdesignの不一致があれば停止する。

CloudFormationでは`list-stacks`でtarget account/regionのstackを確認し、stack詳細設計のStackNameごとに`describe-stacks`、必要な場合だけ`get-template`と`list-stack-resources`でtemplate、parameter、所有resource、terminal statusを照合する。設計済みで未作成、設計済みで現存、設計外、同名だが内容不一致を区別する。設計外stackや内容不一致を自動採用・変更・削除せず、scopeとの衝突がある場合は停止する。StackId/ARNやstatus snapshotをrepositoryへ保存しない。

## Resolve deployment units

CloudFormationでは正本stack propertiesと生成Markdownの一致を確認し、StackNameをdeployment identityとしてTemplate、stack固有Parameters、DeployOrder、MaxConcurrentStacksを解決する。同じtemplateの全StackNameを個別unitとして保持する。resource所有、parameter、既存stackとの照合は既存設計とIaCから確認し、曖昧なら停止する。Deployment scopeを自動拡張しない。順序と並列数はcontrollerで強制し、LLMがdependency順を再計算しない。

同stack modelの任意TemplateBucket／TemplateKeyPrefixとartifact対応表を`cloudformation.md`のS3 deployment artifactsに従って読む。配置先は同targetのS3 modelの確定済みBucketNameから解決する。sourceは事前にビルドしたローカルfileとし、deploy中にビルド・対応表・元IaCを変更しない。今回のscopeの宣言済み成果物配置はAWS execution許可に含む。必要bucketが未作成なら停止し、bucket作成やscope拡張を自動実行しない。

Terraformでは対象root、workspace、backend、variable inputを既存IaCから特定する。不足または不一致があれば停止する。

初回のpreflightはtargetにつき一回だけ実行する。CloudFormation controllerは起動ごとに同じcheck-deploy-contextの結果を再確認する。

## Validate and deploy

CloudFormationの場合:

1. `check-deploy-context.py`のpreflightと、StackNameごとのAWS現存・parameter・resource ownership照合を行う。controllerも同じpreflight helperを使い、mutationと再開の直前にaccount/region/engineを再確認する。scopeとtarget、許可はactive taskに次の形式で明記する。

```md
- Deployment scope: `stack-a`, `stack-b`
- AWS API execution: `allowed`
- Deploy/apply: `allowed`
- Target environment: `<environment>`
- Target AWS account: `<account>`
```

aliasがある場合はTarget alias行も追加し、その値をbacktickで囲む。

2. cfn-lintと同じPython環境からcontrollerを起動する。全scopeのcfn-lintとsource／入力hashを先に確認し、各unitの順番でImportValue実Export確認、宣言済み成果物のS3配置、実行用template検証、validate-template、個別change set作成、add/change/delete/replacement分類、同一change set再確認、実行、terminal確認を行う。templateは51,200 bytes以下なら直接送信、超過〜1 MiBなら指定bucketへ配置して同じS3 URLをvalidate-templateとchange setへ渡す。上限超過または必要設定不足・upload失敗ではchange setを作成しない。これらのCLIをpromptから別方式で実行して二重管理しない。

```console
python framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --state <repository外の同task専用session.json> [--profile <profile>]
# aliasなしでは --alias の代わりに --aws-account-id <aws-account-id>
```

3. controllerは1 DeployOrder groupずつ実行する。同group内だけMaxConcurrentStacksまで実行し、空いたslotへ次stackを開始する。producer成功前にconsumerのchange setを作成しない。list-exportsに必要なExportがない場合やscope内producerが未成功ならBLOCKEDとし、設計された順序とImport/Export関係の矛盾を報告する。scope外のproducerを自動追加しない。
4. 未承認delete/replacementがあればcontrollerはBLOCKEDとして同じchange set IDと変更のfingerprintをrepository外sessionへ保持し、他のRUNNING stackをterminalまで確認する。次の`Confirm unapproved delete/replacement`の影響説明・human確認を行う。`--approve-change-set`は人間がそのchange set全体を承認した場合だけ渡す。事前承認も実change setの全破壊変更との一致を確認してから同じ方法で再開する。
5. 承認後は同じtaskと同じsessionへ`--resume --approve-change-set <保存されたchange-set-id>`を追加する。controllerが同一ID、CREATE_COMPLETE/AVAILABLE、変更fingerprintを再取得・照合して実行する。変更/失効なら以前の承認で実行しない。成功済みstackを再実行しない。
6. GROUP_COMPLETEでは同groupのSUCCESS stackごとに既存`observed-values.md`のOutputs優先・PhysicalResourceId fallback・catalog対応・全参照伝播を行い、sync-modelで生成・検証する。必要なExportの実名・値を確認する。controllerはobserved値の対応付けやmodel更新を再実装しない。これらが完了した場合だけ同じcommandへ`--resume`を追加し次groupへ進む。failure/blockerがあれば後続groupへ進まず、成功分のobservedだけ反映する。
7. sessionはtarget/design/scopeとstackごとのtemplate/parameter/sourceのdigestと配置先bucket/key/version/checksum、実行用template hashを保持する。元IaCを変更しない実行用copyはrepository外sessionに隣接する`.files` directoryへ保存する。配置済みobjectとcopyも再開・execution前に再照合し、以前の承認で変更済み成果物を実行しない。deploy phaseではIaCの変更を一切許さず、update phaseでは未着手NOT_STARTED stackの承認済み設計内のIaC変更だけを再検証して受け付ける。準備済み・実行済みstackのIaCとtarget/design/scopeの変更は再開を拒否する。status/StackId/ARN/履歴はmodelやGitへ保存しない。sessionは同taskの継続用であり成功済みstackを自動rollback/delete/redeployしない。RUNNING取得エラーでは新規起動を止めterminal確認を続ける。controllerへの割り込み後は同じsessionだけで再開し、別sessionの同時実行を行わない。target lockで重複controllerを拒否する。異常終了でlockが残った場合は実行中controllerがないことを確認してからlockだけを除去し、同じsessionを再開する。

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

humanが全対象と理由を承認した場合は、`tasks/<task-name>.md`のAuthorized delete/replacementを承認済みresource、action、理由へ更新し、次を確認して同じtaskを再開する。

- CloudFormationは同じchange set IDを再取得し、statusが`CREATE_COMPLETE`、execution statusが`AVAILABLE`、承認対象のlogical ID、action、replacement、`PolicyAction`が一致する場合だけそのchange setを実行する。
- Terraformは同じ保存済みplanを再確認し、承認対象のresource address、resource type、actionが一致する場合だけそのplan binaryをapplyする。
- change setまたはplanが失効、再作成、変更されている場合は以前の承認を使用せず、新しい内容を説明して再確認する。

humanが承認しない、または一部だけを承認した場合はchange setまたはplanを実行せず停止する。resource保持、CloudFormation管理外化、configuration変更が必要でも、このdeploy phaseでIaCやintended designを変更しない。

scope超過、account/region不一致、delete/replacementのactionを確定できない、validation/plan failure、credential/permission不足、またはdeployment failureでは停止する。未承認のdelete/replacementだけは上記のhuman確認待ちとし、failureとして終了しない。IaCやintended designをこのtaskで修正せず、同じdeployを原因未確認で再実行しない。CloudFormationで停止条件が発生したら新たなunitを起動せず、実行中stackの終状態を確認して成功済み、失敗、未実行を区別する。成功済みstackを自動rollback、delete、redeployしない。Terraform apply failureはpartial applyの可能性があるため、stateとAWS実体をread-onlyで確認して停止する。

deploy/applyが成功した場合:

1. terminal successとresource存在を確認する。
2. `framework/rules/observed-values.md`に従い、取得した値をcatalogの正式な`IDENTIFIER_OUTPUT` propertyへ一意に対応付ける。model propertiesのidentifier output rowと、同じanchorを参照する全propertyのobserved valueだけを同じphysical IDへ先に更新し、link先path、anchor、`Source / Comment`、その他のintended designは変更しない。
3. aliasがあるtargetは`framework/scripts/sync-model.py --write --environment <environment> --alias <alias>`、aliasがないtargetは`framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>`を実行する。

必要なoutputがIaCに存在しない、catalog propertyとの対応が一意でない、または参照元と参照先の値が一致しない場合は推測やIaC修正をせず停止する。replacement後は新しいIDへ更新し、destroy後はidentifier output rowと全参照元を`PENDING_DEPLOY`へ戻す。generated ARNは保存しない。

deploy完了status、resource存在、observed value収集をapplication behaviorの検証またはscenario PASSとして扱わない。

## Verify and finish

1. 対象IaCに変更がないことを確認する。
2. `python framework/scripts/blueprint-loop.py --mode task`
3. `git diff --check`

target、account、region、engine、preflight結果、deployment unitとdependency順、plan/change set summary、human確認待ちと承認結果、deploy完了status、observed value更新、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

IaC、intended design、scenario、scenario result、別target、次taskを変更、作成、実行しない。application behaviorの検証には、humanが別taskとして`framework/prompts/codex/06_scenario-test.md`を使用する。
