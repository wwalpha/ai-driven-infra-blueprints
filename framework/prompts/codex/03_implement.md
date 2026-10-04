# Infrastructure Implementation Prompt

契約は`tasks/<task-name>.md`へtaskごとに登録する。Task statusを`running`とし、`## Modified files`へ今回変更する具体的なfile path（契約自身、新規file、生成artifact、model part、削除対象を含む）を列挙する。Allowed pathsのglobは予約fileの代わりにしない。repository外の候補から`task_contract.py --task-file tasks/<task-name>.md --source <候補file>`で登録し、進行中taskとのfile重複があれば新規taskを停止する。既存taskの契約を上書きしない。以後のcommandは`BLUEPRINT_TASK_FILE`で同じ契約を選択し、local loopには`--task-file`を指定する。成功後に今回のstatusだけを`completed`へ変更する。詳細は`framework/rules/loop-engineering.md`に従う。

このpromptは、承認済みの詳細設計の正本であるauthoritative model propertiesを`project.json`で選択済みのCloudFormationまたはTerraformへ変換し、local static validationまでを行う`infrastructure` taskに使用する。AWS API、change set、plan、deploy/applyは実行しない。deploy/applyは別taskで`framework/prompts/codex/04_deploy.md`を使用する。

## Unresolved issue gate

対象environment／target／serviceを確定した時点で、通常taskの開始前と再開時に`issues/<environment>/<target-directory>/issues.md`を確認し、`framework/rules/loop-engineering.md`のUnresolved issue gateを適用する。関係する全serviceについて`python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>`を実行する。未解決issueがあれば設計質問、設計保存、IaC変更、deploy/apply、scenarioなど他taskへ進まず、対象issueと停止理由を示す。issue調査とhumanが明示した修復だけを許可し、修復taskには対象serviceだけのValidation scopeとIssue remediationを記載する。AWS mutation直前にも再確認し、既存のtask boundaryとAWS execution許可は維持する。

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

environment、alias、AWS accountは`project.json`の同じtargetに存在する候補だけを提示し、自動選択しない。environmentにtargetが1件だけの場合はaliasを質問しない。`project.json`または対象の承認済み詳細設計の正本model propertiesが存在しない場合は、値を推測せず停止する。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. 存在する場合は`tasks/<task-name>.md`。ない場合はidle状態として扱い、Create active task contractで最初に作成する。
4. `project.json`
5. implementation scopeに対応する正本`model/<environment>/<target-directory>/<service>.properties`（読取範囲は下記に従う）
6. `framework/rules/detailed-design.md`
7. `framework/rules/aws-resource-naming.md`
8. `framework/rules/model-information.md`
9. 選択済みengineに対応する`framework/rules/cloudformation.md`または`framework/rules/terraform.md`
10. `framework/rules/observed-values.md`
11. `framework/rules/loop-engineering.md`
12. 対象resourceに関係する`framework/materials/aws/*.properties`と`framework/materials/api/*.properties`および同名API設計schema
13. CloudFormationの場合は`framework/materials/cloudformation-schema/ap-northeast-1/index.json`と対象resourceのprovider schema

Implementの設計inputはauthoritative model propertiesだけとする。generated `docs/designs/<environment>/<target-directory>/*.md`（`cloudformation-stacks.md`を含む）の本文はImplement開始時・IaC生成時・参照解決時に読まず、値を再取得しない。propertiesとgenerated Markdownの事前二重比較をAgentへ要求しない。必要なdesired value、resource、reference、stack assignment、human decisionがpropertiesに不足する場合は、下記の実装前確認の不足一覧へ含め、design taskが必要として停止する。Markdown／JSONの生成・保存とlocal loopの整合性検証は既存どおり維持する。

Implementation scopeに詳細設計の`.md` fileが指定された場合はscope selectorとして扱う。本文を読まず、`docs/designs/<environment>/<target-directory>/<service>.md`のpath／file stemから同じenvironment／target／serviceの`model/<environment>/<target-directory>/<service>.properties`へ対応付け、選択済みproject targetとの一致を確認する。対応するmodelを一意に特定できない場合は推測せず停止する。

resource限定scopeでは次の既存commandで正本を部分読み取りする。selectorはresource number（`001`など）、logical ID、anchorの完全一致とし、未一致・曖昧な選択は停止する。

```console
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service>.properties --resource <resource-selector>
```

対象resourceと既存仕様上必要な同じgroupの親・子・兄弟、service metadata／notesだけを取得し、独自の抽出処理を追加しない。単一fileと分割入口indexの両方に同じcommandを使い、無関係なresourceや全partをcontextへ取り込まない。service全体のscopeならservice properties全体、「対象accountの承認済み設計すべて」なら対象service model群を使用できる。分割modelは既存`model_files.py`の入口indexとpart構成に従い、必要なpartだけを読む。

読取対象はimplementation scopeのresource/propertyと参照解決に必要なproducer側propertiesへ絞る。追加取得にもproducerの`model_files.py --resource`を使い、変更scopeを広げない。target全Markdownをfallbackとして読むことは禁止する。同じtaskで確認済みの資料は、内容変更・検証失敗・未解決の依存がなければ再読しない。

`<target-directory>`は、選択targetにaliasがあればalias、なければAWS account IDとする。

## Read-only implementation preflight

User inputとissue gateの確認後、active contract作成・IaC生成より前に、下記のCheck implementation support、Resolve implementation units、既存IaCとの照合をすべてread-onlyで行う。AWS API、IaC生成、deployは実行しない。既存のschema検証と依存関係確認を再利用し、新しい検証エンジンや承認工程を追加しない。

1. 対象resourceの正本propertiesからCREATE／IMPORT、正式CFn型、必須property、未確定値を確認する。既存`model_design.validate_required_properties`と`DesignSchemaCatalog.literal_errors`などpropertiesに適用できるschema検証を再利用し、型・enum・pattern・長さ・範囲と補完されたAWS文字制約を確認する。前taskのValidation scopeを流用せず、対象serviceと必要な参照先を明示して検証する。日本語の表示用Commentは正式property値と区別し、不正値を自動翻訳・置換しない。
2. properties内のresource/propertyの参照をたどり、必要な依存先のproperties・anchor・logical/current identifier、受渡し値を確認し、利用するpropertyにも同じschema検証を適用する。下記のpropertiesによるreference解決とResolve implementation unitsの依存確認を使い、参照先は必要なresource/propertyだけ読む。依存先調査で変更scopeや全service検証へ自動拡張しない。
3. CloudFormationでは正本stack登録のpropertiesから対象resourceの所有stack、template・parameterの対応、DeployOrder、共有templateの各stack instanceを確認する。既存templateのResources・Parameters・Outputs／Export／ImportValueとpropertiesのdesired rowの対応、parameter値／defaultの不足、参照先不明、dependency cycleを確認する。新規IaC fileの未作成自体は不足とせず、配置先と入力の設計が未確定なら不足にする。Terraformでは既存module・environment入力・outputの対応を確認する。
既存CloudFormation templateがあるstackは、共通local read-only検証を実装前に実行する。`desired.mapping.*`のStackName／CFn logical ID → service／model logical IDを優先し、対応表を持つstackの対応漏れ・不正対応を従来照合で補わない。対応表がないstackだけ型＋既存IDの一意な照合を維持する。stack固有parameter/defaultでConditionを評価し、有効resourceのCREATE区分・正式型・対応先・二重所有・identifier行・必要Outputsの不足をまとめて報告する。falseのresourceは処理せず、未解決Conditionは停止する。新規templateの未作成はこの段階で不足とせず、modelのidentifier行と配置先の確定を確認する。

```console
python framework/scripts/cloudformation_observed.py --environment <environment> --target-directory <target-directory> --stack <StackName> --stack <another-StackName>
```

4. 確認可能な全対象と依存先の診断を集約し、`対象file | resource（logical ID）/stack | property/parameter | 不足・違反理由`の不足一覧を一回でまとめて提示する。読取不能の対象はその理由を記載して他の確認を続け、最初の不足だけで報告を終えない。不足0件ならその結果と実装対象差分を報告し、追加承認を要求せず契約作成・実装へ進む。不足があれば実装せず、別のdesign taskが必要であることと未確認事項を示して停止する。設計・model・IaCをここで修正せず、別taskを自動作成・実行しない。

## Compare existing IaC before creating the contract

file変更前に、下記の実装対応確認とimplementation unit解決を行い、対象propertyの確定済み設計値を既存template/moduleとparameterへ照合する。一致する箇所は変更不要の確認対象とし、差分がある箇所だけを実装対象にする。既存IaCが正しい場合は同値の書換えや命名だけの変更を作らない。

全箇所が一致する場合は、対象IaCのstatic validationを一回行い、変更不要と結果を報告して終了する。repository変更のない確認では新しいactive contractを作成せず、IaC変更必須のimplement taskを完了したと扱わない。明示issue修復のためmodel変更が必要な場合は、既存task boundaryに従い修復範囲だけを扱い、ここでmodelを変更しない。

## Create active task contract

最初のrepository changeとして`tasks/<task-name>.md`を今回の対象だけを許可する内容へ新規登録する。

- Task typeは`infrastructure`とする。
- Infrastructure phaseは`implement`とする。
- goalにtarget environment、aliasがある場合はalias、AWS account、implementation scope、選択済みIaC engineを記載する。
- AWS mutation、AWS API execution、deploy/applyを`forbidden`とする。
- `Required changes`は一意なRequirement ID付きで、事前照合で差分があったIaC implementationと対象のstatic validationだけを記載する。変更不要の既存IaCは確認対象として記載する。
- `Acceptance checks`は各Requirement IDへ変更対象IaC fileの`changed:`、変更不要の確認対象には`exists:`を対応付ける。task type固有checkは省略しない。
- Allowed pathsは対象のIaC fileと`tasks/<task-name>.md`だけに限定する。詳細設計、model、scenarioは変更禁止とする。

## Check implementation support

正本propertiesに載るresourceと選択済みengineで実装可能なresourceを分けて確認する。CloudFormationでは実装scope内の各typeに`python framework/scripts/design_catalog.py --cloudformation-type <catalog-resource-type>`を実行し、成功した正式型だけを使う。`Macie.ClassificationJob`はCFn非対応であり、Jobをtemplate、Outputs、`!Ref`へ変換しない。

Jobが要求scopeに含まれる場合は未実装対象として明示し、対応resourceだけの実装を要求全体の完了としない。既にCFn対応範囲へ限定されたtaskはその範囲で終了できる。非対応を理由にCustom Resource、別engine、API mutationを追加しない。

## Resolve implementation units

対象scopeから必要なtemplate/module、parameter、dependencyを特定する。既存boundaryと共通部品があれば再利用し、未使用resource、将来用module、compatibility layerは作成しない。

CloudFormationでは`framework/rules/cloudformation.md`の`1 template = 1 deploy responsibility`に従う。AWS service単位で機械的に分割しない。dependency cycle、parameter不足、参照先不明がある場合は、不足情報を報告して停止する。
CloudFormationでは対象targetの正本`model/<environment>/<target-directory>/cloudformation-stacks.properties`だけを読む。既存`desired.stack.*.name`からStackName、`.template`からtemplateのファイル名、`.parameters`から個別parameterのファイル名、`.deployOrder`からDeployOrder、`desired.deployment.maxConcurrentStacks`からMaxConcurrentStacksを取得する。省略時のMaxConcurrentStacksの実効値は既存契約どおり1とし、DeployOrderを推測しない。`cloudformation-stacks.md`は表示用generated artifactでありImplement inputとして読まない。DeployOrderをIaC resource dependencyへ変換せず、この機能のためにtemplateへDependsOnを追加しない。scope内resourceをどのtemplateへ配置するかは承認済みservice propertiesと既存IaCから確認し、曖昧な場合は推測で作らずdesign taskが必要であることを報告する。同じtemplateを複数stackで共用する場合もstackごとのparameterと生成resource名・Export名の一意性を確認する。
CloudWatch Logs resourceとSecurity Groupは利用するresourceのtemplateへ含め、これらだけの単独templateを作らない。IAM Roleは同じtargetで直接利用するresourceがあればそのtemplateへ含める。同targetの設計resourceからRoleへの直接参照がなく、用途とAssumeRole元がservice propertiesで確認できる場合は、Roleと付随するIAM Policy/ManagedPolicyだけの専用templateに置き、`Metadata`直下へ`RolePlacement: standalone`を宣言する。利用側resourceまたはRole専用stackの設計が不明なら推測せず停止する。

対象resourceへの`!Ref`、`!GetAtt`、`!Sub`と、policy/設定値の文字列に含まれるresource参照を確認する。template外のresourceなら、properties内のlogical referenceと既存IaCから実際の所有stack、必要な値、producer Output/Exportを特定する。producer exportがまだdeployされていない場合は、scope内のproducer templateに必要なOutput/Exportだけを追加し、consumerの`!ImportValue`変更はproducer deploy後のtaskへ残す。implement phaseではAWS APIやdeployを実行せず、deploy済みexportの確認が必要な場合はその前提を報告する。producerがscope外または所有先が不明なら変更を広げず停止する。

## Implement and validate

承認済みdesignの機械可読inputであるauthoritative model propertiesだけを使用し、選択済みengineの最小構成を実装する。resource設定、tag、Name、policy document、identifier referenceはpropertiesの`desired.row.*`（JSON本文は`.document`）から取得し、generated Markdown／JSON artifactから値を再取得しない。

propertiesのdesired rowに記載されたtagはCloudFormation／Terraformへそのまま反映する。`EC2.VPC.Name`、`EC2.Subnet.Name`、`EC2.RouteTable.Name`、`EC2.FlowLog.Name`はprovider propertyとして出力せず、case-sensitiveな`Name` keyと同じvalueを持つtagへ変換する。対象resourceに対応する`.Name`とnon-empty valueがない場合だけ、値を推測せず別の`design` taskが必要であることを報告して停止する。

propertiesのdesired row／reference valueに保存された`[表示値](#anchor)`形式のlogical referenceは、同じmodelの`desired.resource.*.anchor`と`desired.resource.*.logicalId`から参照先を一意に解決する。`[表示値](<service>.md#anchor)`形式の別service参照もpath／file stemを対応するproducer model propertiesへ対応付け、必要なresourceだけを追加取得して同じmetadataから解決する。grouped resourceの`parentReference`もproperties内のanchorで解決する。参照先が不明・曖昧なら推測せず停止し、generated Markdown本文を読まない。link表示textの`PENDING_DEPLOY`またはphysical IDをIaCへ直書きしない。後続resourceが必要とするcatalog `IDENTIFIER_OUTPUT`だけをCloudFormation OutputsまたはTerraform outputへ追加し、logical resource参照／resource attribute参照を維持する。generated ARNはobserved value用outputにしない。

CloudFormationの場合:

1. aliasがあるtargetでは`infra/cloudformation/templates/<alias>/`、aliasがないtargetでは共通の`infra/cloudformation/templates/`を使用する。stack propertiesに記載されたparameterのファイル名を`infra/cloudformation/parameters/<environment>/<target-directory>/`に配置し、その個別fileだけを変更する。template `Resources`のlogical IDと対象service propertiesのresourceの対応を全stack instanceで照合する。生成・変更後も上記`cloudformation_observed.py`でdeployと同じ共通検証を必ず実行する。identifier行の不足を自動補完せず、model不足とIaC Outputs不足を区別して報告する。
2. 新規resourceの`Resources` logical IDと`Outputs.*.Export.Name`のtarget別最終値を`framework/rules/cloudformation.md`のPascalCaseにし、設計logical IDとの対応、template内参照、export/importの一致と一意性を確認する。`Resources`配下のresource間には1行以上の空行を入れる。deploy済みproducer exportを確認したconsumerでは、参照値全体と文字列中の参照箇所を`!ImportValue`へ置き換える。既存IDを命名形式だけで変更しない。
3. 対象となる全templateへ`cfn-lint --regions <project.jsonのawsRegion> <template...>`を実行する。
4. `aws cloudformation validate-template`、change set作成、AWS APIは実行しない。

Terraformの場合:

1. aliasがあるtargetでは`infra/terraform/modules/<alias>/`、aliasがないtargetでは共通の`infra/terraform/modules/`を使用し、対象の`infra/terraform/environments/<environment>/<target-directory>/`だけを変更する。
2. `terraform fmt -check`、freshな`TF_DATA_DIR`を使った`terraform init -backend=false`、`terraform validate`を実行する。
3. `terraform plan`、`terraform apply`、AWS APIは実行しない。state fileとplan binaryを作成または保存しない。

static validationが失敗した場合は根本原因を調査する。確定済みdesign内で修正可能なIaC implementation errorだけを最小修正し、最大3 iterationまで再実行する。material progressなしで同じerrorが2回続く、またはhuman decisionやdesign変更が必要な場合は停止する。

## Verify and finish

1. 選択済みIaCのlocal static validation結果を確認する。成功後に対象IaC・parameter・依存入力が変わっていなければ再実行しない。
2. `python framework/scripts/blueprint-loop.py --mode task`を一回実行する。propertiesとgenerated Markdown／JSON artifactの一致は、この既存local loopが`validate-blueprint.py`とread-onlyの`sync-model.py`で確認し、不一致ならFAILとする。既存`check_design_tables`・`check_design_links`・`check_stack_designs`による表示・参照・stack検証も維持する。AgentがMarkdownを事前読込・比較しなくても、これらのvalidationを省略・弱体化せず、不一致を無視して完了しない。差分checkもこのloopに含まれる。

成功した対象検証の後に追加の全体検証を行わない。再実行は修正、新しい失敗、未解決の懸念がある場合だけとし、tool待機timeoutでは同じ実行を追跡する。

target、account、region、engine、変更file、implementation unitとdependency、validation結果、retry、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

AWS API、change set、plan、deploy/apply、observed value更新、scenario、別target、次taskを作成または実行しない。deploy/applyはhumanが別taskとして`framework/prompts/codex/04_deploy.md`を明示的に使用した場合だけ行う。
