# Manual Design Update and Deployment Prompt

契約は`tasks/<task-name>.md`へtaskごとに登録する。Task statusを`running`とし、`## Modified files`へ今回変更する具体的なfile path（契約自身、新規file、生成artifact、model part、削除対象を含む）を列挙する。Allowed pathsのglobは予約fileの代わりにしない。repository外の候補から`task_contract.py --task-file tasks/<task-name>.md --source <候補file>`で登録し、進行中taskとのfile重複があれば新規taskを停止する。既存taskの契約を上書きしない。以後のcommandは`BLUEPRINT_TASK_FILE`で同じ契約を選択し、local loopには`--task-file`を指定する。成功後に今回のstatusだけを`completed`へ変更する。詳細は`framework/rules/loop-engineering.md`に従う。

このpromptは、人間が既存のmodel propertiesを手動修正し、まだcommitしていない差分を確定済みdesignとして受け取り、Markdown生成、選択済みIaCへの反映、deploy/apply、完了確認までを一つの`infrastructure` taskで行うために使用する。新規詳細設計の作成には使用しない。

## Check applicability and finish point first

最初に依頼の対象environment／target／service、property、修復対象issueと、終了地点（model修復まで、IaCまで、AWS反映まで）を確定する。依頼に明記された範囲を再質問せず、不足する判断だけを確認する。

- humanの手動model差分をAWSへ反映する依頼だけを、以下の通常update手順で扱う。IaCまでの依頼へpreflight、change set／plan、deploy/applyを追加しない。
- humanが明示したissue修復は手動model差分を前提とするupdateと区別する。修復値を対象modelと既存IaC・parameterへ変更前に照合し、既存IaCが一致していれば確認対象とする。model修復と生成設計書・該当issueの解消だけが必要なら、design boundaryの修復contractへ対象serviceのValidation scopeとIssue remediationを記載する。手動model差分がないことを理由に修復を止めたり、IaCの同値書換えを要求しない。
- 実際にIaC変更が必要なら既存のinfrastructure boundaryに従う。model修復とIaC変更を混ぜてupdateのimmutable input制約を解除せず、別taskを自動作成・実行しない。

契約のRequired changesとAllowed pathsは必要な変更だけに絞り、既存IaCの確認対象と区別する。以下の通常updateの適用条件を満たさない依頼に、その契約・AWS許可を流用しない。明示issue修復は対象serviceの生成、依頼された対象IaCの静的検証、local loopを各一回実行して指定の終了地点で終える。task type固有checkとissue gateは省略しない。

## Unresolved issue gate

対象environment／target／serviceを確定した時点で、通常taskの開始前と再開時に`issues/<environment>/<target-directory>/issues.md`を確認し、`framework/rules/loop-engineering.md`のUnresolved issue gateを適用する。同じtargetの関係する全serviceは、既存CLIの`--service`を繰り返して一回のprocessで確認する。単一serviceなら一つだけ指定する。

```console
python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id> [--service <service-id> ...]
```

未解決issueがあれば設計質問、設計保存、IaC変更、deploy/apply、scenarioなど他taskへ進まず、対象issueと停止理由を示す。issue調査とhumanが明示した修復だけを許可し、修復taskには対象serviceだけのValidation scopeとIssue remediationを記載する。AWS mutation直前にも同じ全serviceを`--task`付きで再確認し、controller内のtask／issue guardも維持する。

## Optional user input

- Authorized delete/replacement: 省略時は`none`
- AWS profile: 任意。省略時はtargetの`awsProfile`、未設定ならdefault credential chain。設定と異なる明示profileは拒否する

通常はどちらも入力不要とする。delete/replacementは対象resourceと理由が明記されている場合だけ事前承認済みとして扱う。事前承認がなくてもchange setまたはplanは作成し、未承認のdelete/replacementを検出した場合だけ下記のhuman確認待ちへ進む。

## Resolve target and scope from repository state

fileを変更する前に、次の順序でtargetとscopeを特定する。

1. `git status --short`と`git diff --name-only HEAD -- model/`を確認する。
2. humanが変更した既存model propertiesのpathからenvironmentとtarget directoryを取得する。単一fileは`model/<environment>/<target-directory>/<service-id>.properties`、分割modelのpartは既存`model_files.service_model_path`で同じservice入口へ対応付ける。
3. 取得したenvironment／target directoryの組み合わせが正確に1件で、`project.json`のtargetと一致することを確認し、aliasがある場合はalias、常に実際のAWS account IDを取得する。手動修正済みmodel propertiesがない場合、複数targetの差分が混在する場合、または未登録targetの場合はfileを変更せず停止する。
4. 同じtargetでhumanが変更した既存model propertiesをすべてDesign scopeとする。policy／設定JSON本文はmodel rowのdocumentをinputとし、Markdown／JSON artifactの手動diffを設計値として採用しない。
5. 対応する正本service propertiesと既存IaC・parameterを照合し、差分があるpropertyだけを実装対象にする。CloudFormationのstack scopeは同じtargetの正本`cloudformation-stacks.properties`だけから解決する。`desired.stack.*.name`、`.template`、`.parameters`、`.deployOrder`と`desired.deployment.maxConcurrentStacks`を使用し、MaxConcurrentStacks省略時の実効値は1とする。resource所有、共有templateの各stack instanceとparameterの対応はservice propertiesと既存IaCから確認し、曖昧なら停止する。変更済みdesignが同じaccount・regionの別stack所有resourceを参照する場合は、そのproducer stackも必要なOutput/Export追加の候補とする。
6. 上記のStackName、template／parameter、またはTerraform root／resourceとdependencyをDeployment scopeとする。CloudFormationではDeployOrderが未設定なら推測・migrationせず停止し、順序と並列上限はcontrollerが強制する。DeployOrderをtemplateのDependsOnへ変換しない。Terraformでは既存IaCからroot、workspace、backend、variable input、module/resourceとdependencyを解決し、不足・不一致なら停止する。同じtemplateを使う別StackNameは別unitとし、変更された設計resourceを所有するstackだけをscopeへ含める。cross-stack exportが必要なproducerとconsumerを同じtaskで扱う場合は両stackをscopeへ含める。

scope外のuncommitted changeがある場合は取り込まず停止する。repository内の情報からdeployment unitを一意に特定できない場合だけ、stack名など不足している項目を一回の応答につき一つ質問する。repositoryから特定できるtarget、file path、scope全体をuserへ再入力させず、値を推測しない。
既存StackNameの削除・改名をstack詳細設計の差分から自動的にstack削除と解釈しない。対象stackの管理終了または削除が必要なら、現在のupdate phaseで実行せず対象と影響を報告して停止する。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. 存在する場合は`tasks/<task-name>.md`。ない場合はidle状態として扱い、Create active task contractで最初に作成する。
4. `project.json`
5. `git status --short`と、repository差分から特定したDesign scopeのdiff
6. Design scopeの正本`model/<environment>/<target-directory>/<service-id>.properties`と必要なpart。CloudFormationではstack scope解決に必要な同targetの`cloudformation-stacks.properties`
7. `framework/rules/detailed-design.md`と`framework/rules/aws-resource-naming.md`
8. `framework/rules/model-information.md`
9. 選択済みengineに対応する`framework/rules/cloudformation.md`または`framework/rules/terraform.md`
10. `framework/rules/observed-values.md`
11. `framework/rules/loop-engineering.md`
12. 対象resourceに関係する`framework/materials/aws/*.properties`と`framework/materials/api/*.properties`および同名API設計schema
13. CloudFormationの場合は対象resourceのprovider schema

Updateの設計inputはauthoritative model propertiesだけとする。generated Markdown本文とgenerated JSON artifactは開始時・IaC生成時・参照解決時のinputとして読まない。`cloudformation-stacks.md`も表示用生成物であり、同じstack scope情報をAgentが再取得・二重比較しない。JSON本文は`desired.row.*.document`を使う。03/04 prompt全文の読込は不要とし、Updateに必要な手順はこのprompt、共通契約は上記の既存rulesに従う。Markdown／JSONの生成・保存、controllerとlocal loopによる整合性検証は維持する。

resourceが限定される場合は、単一file／分割入口indexの両方で既存部分読込を使用する。selectorはresource number、logical ID、anchorの完全一致とし、未一致・曖昧なら停止する。

```console
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service-id>.properties --resource <resource-selector>
```

対象resourceと同じgroupの親・子・兄弟、service metadata／notesだけをcontextへ入れる。service全体の変更なら対象service properties全体を読めるが、全service／全modelへ無条件に広げない。propertiesのlogical referenceは`desired.resource.*.anchor`／`.logicalId`と`parentReference`から解決する。別serviceの`.md#anchor` linkはpath／file stemからproducer propertiesへ対応付け、必要なresourceだけ同じ`model_files.py --resource`で追加取得する。generated Markdown本文をfallbackとして読まない。参照先不明、必要なdesired value、stack assignment、human decisionの不足は推測せず停止する。

読取対象はDesign scopeのresource/propertyと参照解決に必要な箇所へ絞る。分割modelは入口indexから必要なpartだけを読む。同じtaskで確認済みの資料は、内容変更・検証失敗・未解決の依存がなければ再読しない。

`<target-directory>`は、選択targetにaliasがあればalias、なければAWS account IDとする。

## Validate human design diff

- 特定したDesign scopeは、対象environment／target directory配下でhumanが変更した既存model propertiesだけとする。
- Design scopeのmodel propertiesにhumanが作成したuncommitted diffが存在しなければ停止する。
- 特定したDesign scope外のuncommitted changeがある場合は、今回のtaskへ取り込まず停止する。
- IaCまたは生成物Markdown／JSONにtask開始前からuncommitted changeがある場合は停止する。正本model propertiesのhuman diffは許可する。
- humanが変更したintended designをこのtaskで修正、補完、巻き戻ししない。
- 詳細設計の不足、矛盾、placeholder、schema violation、未確定のhuman decisionがあれば停止する。
- 対象propertiesに既存`model_design.validate_required_properties`と`DesignSchemaCatalog.literal_errors`などのschema検証を適用し、CREATE／IMPORT、正式型、必須property、型・制約と必要な依存先を確認する。scopeやintended designを自動補完しない。
- CloudFormationでは対象typeを`design_catalog.py --cloudformation-type <catalog-resource-type>`で解決する。CFn非対応の`Macie.ClassificationJob`等を黙って除外してupdate完了とせず、未反映を報告して停止する。CFnへの誤変換、API実行、Custom Resource追加、旧Jobのキャンセルを行わない。resourceModeの境界はengine ruleを維持する。

task開始時のDesign scope diffを保持し、deploy成功後のgenerated current value更新を除いて完了時まで同じであることを確認する。

## Create active task contract

Codexによる最初のrepository changeとして`tasks/<task-name>.md`を今回の対象だけを許可する内容へ新規登録する。

- Task typeは`infrastructure`とする。
- Infrastructure phaseは`update`とする。
- goalにtarget environment、aliasがある場合はalias、AWS account、自動特定したDesign scopeとDeployment scope、選択済みIaC engineを記載する。
- `Validation scope`はDesign scopeと実装・deploymentに関係するserviceを`<environment>/<target-directory>/<service-id>`で明記する。target全体へ広げない。
- AWS API executionとdeploy/applyは自動特定したDeployment scopeに限り`allowed`とする。
- Authorized delete/replacementは明示された値、入力がなければ`none`を記載する。change setまたはplan作成後にhumanが承認した場合は、同じtaskのまま対象resource、action、確認済み理由へ更新する。
- `Required changes`は一意なRequirement ID付きで、human design diffの検証、Markdown生成、IaC implementation、deployment、必要なobserved value更新を分けて記載する。
- `Acceptance checks`はDesign scope、対応するmodel、対象IaCへ`changed:`を対応付け、deployment unitへ`exists:`を対応付ける。deploy未実行や失敗をrepository fileで完了扱いにしない。
- Allowed pathsはDesign scopeのmodel properties、生成先Markdown／JSON artifact、対象IaC、`tasks/<task-name>.md`だけに限定する。別targetと`tests/**`は変更禁止とする。

## Generate Markdown and implement IaC

1. aliasがあるtargetは`framework/scripts/sync-model.py --write --environment <environment> --alias <alias> --service <service-id>`、aliasがないtargetは`framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id> --service <service-id>`を実行し、human design diffを入力としてMarkdown／JSON artifactを生成する。同じtargetの複数対象serviceは`--service`を繰り返して一回で指定し、modelのintended designを変更しない。
2. Markdown／JSON生成失敗またはvalidation failureではdesignを修正せず停止する。
3. 上記のpropertiesと既存engine ruleから、自動特定したDeployment scopeに必要なIaCだけを最小変更する。tag、Name、policy document、logical referenceはdesired rowから反映し、physical IDを直書きしない。CloudFormationのcross-stack参照は下記のread-only確認でdeploy済みexportを調べるまでproducer Output/Exportとconsumer `!ImportValue`の変更を保留する。
4. CloudFormationは対象全templateに`cfn-lint --regions <project.jsonのawsRegion> <template...>`を実行する。Terraformは`terraform fmt -check`、freshな`TF_DATA_DIR`を使った`terraform init -backend=false`、`terraform validate`を実行する。IaC implementation errorは確定済みdesign内で修正可能な場合だけ最大3 iterationまで修正する。material progressなしで同じerrorが2回続く、human decisionまたはdesign変更が必要なら停止する。validation失敗を残してdeployへ進まない。

## Preflight and deploy

このtaskでDesign scopeから生成した対象IaCのuncommitted diffだけはdeploy対象として許可する。task開始前から存在したIaC diffまたはDeployment scope外のdiffは許可しない。engine切替、state/backend不明、designとの不一致、required input missingは停止する。

### CloudFormation read-only dependency check

IaC変更判断にlive AWS stateが必要なcross-stack参照だけ、既存`check-deploy-context.py`の`--read-only`でidentity／account／region／profileを確認してから必要な`describe-stacks`／`list-exports`を実行できる。引数は下記Terraform例と同じtarget selectorへ`--read-only`を加える。この例外は実装判断のread-only確認であり、通常のCloudFormation updateでは実行しない。mutation許可やcontroller final preflightの代替にはしない。不一致・認証失敗では停止し、別profileへfallbackしない。

producer Outputsと同じaccount・regionの実Export名・値・ExportingStackIdを照合する。既存exportがあればconsumer templateの参照と文字列中の該当箇所を`!ImportValue`へ変更し、static validationからcontrollerへ進む。exportがなければproducer templateに必要なOutput/Exportだけを追加し、static validationとcontrollerでproducer deploy、terminal successと実Export確認を先に行う。その後に初めて未着手NOT_STARTEDのconsumer templateを`!ImportValue`へ変更し、`--pause-after-group`で停止した同じcontroller sessionをresumeする。両stackがDeployment scopeに含まれない場合はscopeを推測で広げず停止する。

### CloudFormation controller

最終preflight責任者は`cloudformation-deploy.py`とする。controllerが既存`check-deploy-context.py` helperでAWS identity、project target、profile、account、region、engine、必要commandを確認し、task scope、issue gate、immutable inputを強制する。同じ最終deploy-context checkをAgentからstandaloneで先に実行しない。明示account／regionはprojectの同targetと照合し、明示profileはcontrollerの`--profile`へ渡す。不一致・credential/permission不足では停止する。cfn-lintと同じPython環境からcontrollerを起動する。

```console
python framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --state <repository外の同task専用session.json> [--profile <profile>]
# aliasなしでは --alias の代わりに --aws-account-id <aws-account-id>
```

通常は一回のcontroller起動で全DeployOrderを完了する。controllerは全scopeのcfn-lint、input hash、StackNameごとの現存・parameter・resource ownership、ImportValueの実Export確認、validate-template、change set作成・分類・再確認・実行・terminal確認を担当する。change set作成・実行をcontroller外へ分散しない。宣言済みS3成果物配置とtemplateサイズ別送信、group barrier、MaxConcurrentStacks queue、session validation再利用、immutable guard、failure stopとRUNNING stackのdrainは`cloudformation.md`の既存契約を維持する。producer成功前にconsumer change setを作らず、設計外stackを採用・変更・削除しない。

通常成功ではcontroller内でobserved更新とservice指定のsync-modelを完了してから次groupへ進み、最終groupも同期してCOMPLETEとなる。明示producer/consumer IaC変更用途だけ`--pause-after-group`を使い、同期後のGROUP_COMPLETEから同じsessionを`--resume`する。準備済み・実行済みunitのIaC変更を拒否し、成功済みstackを再実行しない。scope超過、account/region不一致、validationまたはdeployment failureでは新規unitを起動せず、RUNNING stackの終状態を確認して停止する。成功済みstackを自動rollback/delete/redeployしない。

### Terraform preflight and apply

credential、deploy先account、AWS region、IaC engine、必要commandをLLMの推論で判定せず、repository rootから次を実行する。追加inputがなければ`--profile`を省略してよい。scriptはtargetの`awsProfile`を自動使用する。

aliasがあるtargetでは次を実行する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --alias <alias> [--profile <profile>]
```

aliasがないtargetでは次を実行する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --aws-account-id <12-digit-account-id> [--profile <profile>]
```

scriptが終了code 0を返した場合だけ、出力されたprofile（設定時）をすべての後続AWS実行で使用して続行する。CLI／SDKにはprofileを明示し、Terraformのprovider／AWS backendには`terraform.md`に従いprocess単位で同じ`AWS_PROFILE`を渡す。失敗時はcredential切替、account変更、check bypassを行わず停止する。secretやcredential値を表示または保存しない。

preflight成功後、同じroot／workspace／backendのstateと既存resourceをread-onlyで照合する。`terraform fmt -check`、`terraform validate`、`terraform plan -out=<repository外の一時path>`を実行し、scope、add、change、destroy、replacementとsensitive outputを確認する。事前承認済みまたは下記でhumanが承認した同じ保存済みplan binaryだけを`terraform apply`する。plan failure、wrong workspace/account/region、sensitive output、不足・不一致では停止する。apply failureはpartial applyの可能性があるため、stateとAWS実体をread-onlyで確認して停止する。state／plan binaryをcommitしない。

## Confirm unapproved delete/replacement

未承認delete/replacementだけはfailureまたはtask完了とせず、change set／planを未実行のままhuman確認待ちにする。engine ruleのDelete and replacement confirmation／Validation and executionを適用し、この場合だけ`04_deploy.md`の`Confirm unapproved delete/replacement` sectionを参照する。対象、action、理由、データ・access・availability等への判明した影響、未確認事項、成功済み／実行中／未実行unitの現在状態を説明し、同じchange set／保存済みplanの全破壊変更を承認するか確認する。一部だけの承認では実行しない。全deploymentを一律停止するreviewは追加しない。

承認後は同じtaskのAuthorized delete/replacementへ対象resource、action、理由を記載する。CloudFormationは同じsessionへ`--resume --approve-change-set <保存されたchange-set-id>`を渡し、controllerの同一ID、CREATE_COMPLETE/AVAILABLE、変更fingerprint再確認を維持する。Terraformは同じplanのresource address/type/actionを再確認する。失効・再作成・変更されたchange set／planへ以前の承認を流用しない。action不明は停止する。承認されない場合は実行せず、resource保持・管理外化のためのIaC/design変更をこの確認工程に混ぜない。

## Post-deployment model sync

### CloudFormation

observed収集・model更新・generated artifact同期はcontroller所有とする。`cloudformation_observed.py`が実templateのLogicalId、正式型、catalog IDENTIFIER_OUTPUT、Outputs／PhysicalResourceIdを照合し、必要なnon-ARN identifierと全参照元のobserved rowを更新してservice指定のsync-model生成・検証を行う。COMPLETEと同期結果を確認し、Agentは同じAWS値取得や`sync-model.py --write`を再実行しない。曖昧な対応はAMBIGUOUS_OBSERVED_MAPPINGで停止し、LLMが補完しない。同期失敗では完了扱いにせず、blocker解消後も同じcontroller sessionで再試行する。

### Terraform

applyが成功した場合はAgentが既存post-apply手順を行う。

1. terminal successとresource存在を確認し、必要なnon-sensitive identifierをTerraform outputから取得する。対象outputがない場合だけstateのresource attributeをread-only参照し、両方がある場合は一致を確認する。
2. `observed-values.md`に従いcatalogの正式なIDENTIFIER_OUTPUTへ一意に対応付け、identifier output rowと全参照元のobserved valueを先に更新する。replacement後は新しいID、destroy後はPENDING_DEPLOYを反映する。humanが変更したintended design、link先path／anchor、Source / Commentを変更しない。必要output不足・曖昧な対応・参照不一致は推測せず停止し、generated ARN／secretを保存しない。
3. 上記のservice指定付き`sync-model.py --write`を、observed valueを更新したserviceだけに実行する。

deploy完了status、resource存在、observed value収集をapplication behaviorの検証またはscenario PASSとして扱わない。

## Verify and finish

1. task開始時のhuman design diffと比較し、generated current value以外のintended designをCodexが変更していないことを確認する。
2. 選択済みIaCのsyntax/static validation結果を確認する。成功後に対象IaC・parameter・依存入力が変わっていなければ再実行しない。deploy phaseの必須validation・AWS安全確認は維持する。
3. `python framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-name>.md`を一回実行する。Validation scope、task固有check、Acceptance checks、差分checkと、read-onlyの`sync-model.py`によるpropertiesとgenerated Markdown／JSONの一致を維持し、不一致ならFAILとする。既存validation cache／service parallelismを使用し、Agentの初期読込削減を理由に検証を省略・弱体化しない。framework regressionの実行条件は`loop-engineering.md`の既存ポリシーを維持し、通常Updateにframework全回帰を追加しない。

成功した対象検証の後に追加の全体検証を行わない。生成・検証の再実行は入力変更、新しい失敗、未解決の懸念がある場合だけとし、tool待機timeoutでは同じ実行を追跡する。

target、Design scope、表示生成、IaC変更、deployment unitとdependency順、plan/change set summary、human確認待ちと承認結果、deploy完了status、observed value更新、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

scenario、scenario result、別target、次taskを変更、作成、実行しない。application behaviorの検証が必要な場合は、humanが別taskとして`framework/prompts/codex/06_scenario-test.md`を使用する。
