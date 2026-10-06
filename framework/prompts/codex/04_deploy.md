# Infrastructure Deployment Prompt

契約登録・予約・停止／再開は[task-contract](../../rules/task-contract.md)に従う。

このpromptは、承認済みの詳細設計から作成・検証済みのCloudFormationまたはTerraformを変更せずにdeploy/applyし、deploy完了確認と必要なobserved value更新を行う`infrastructure` taskに使用する。IaC修正とapplication behavior検証は行わない。

account／profileの共通選択は[Credentials and account](../../rules/project-configuration.md#credentials-and-account)に従い、policy固有条件は[Policy account selection](../../rules/detailed-design.md#policy-account-selection)を適用する。

## Unresolved issue gate

対象serviceの開始・再開・mutation前の停止判定と例外は[issue-gate](../../rules/issue-gate.md)を適用する。CloudFormationではcontrollerへ確認を委譲し、同じpreflightを外側で重ねない。

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

`project.json`、対象の承認済み正本service model、対応する生成Markdown／JSON、または対象IaCが存在しない場合は、値を推測せず停止する。生成物の存在確認はAIの本文読込を要求しない。

## Read before changing files

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. 存在する場合は`tasks/<task-name>.md`。ない場合はidle状態として扱い、Create active task contractで最初に作成する。
4. `project.json`
5. deployment scopeが所有・参照するserviceの正本`model/<environment>/<target-directory>/<service-id>.properties`入口と必要なpart、参照解決に必要な参照先model
6. CloudFormationは同targetの`cloudformation-stacks.properties`。StackName対応と生成stack Markdownの照合は既存controllerの`load_units()`へ委ね、AIが同じ値を手動で二重比較しない
7. [Policy account selection](../../rules/detailed-design.md#policy-account-selection)。CloudFormationは[CloudFormation stack詳細設計](../../rules/detailed-design.md#cloudformation-stack詳細設計)、設計表示を変更・調査する場合だけ関連する表示sectionを追加する。
8. [Model authority](../../rules/model-information.md#model-authority)、[Resource management mode](../../rules/model-information.md#resource-management-mode)、[Properties format](../../rules/model-information.md#properties-format)。生成する場合は[Properties先行更新と表示生成](../../rules/model-information.md#properties先行更新と表示生成)、CloudFormationは[CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy)を追加する。
9. 選択済みengineに対応する[cloudformation](../../rules/cloudformation.md)または[terraform](../../rules/terraform.md)
10. [observed-values](../../rules/observed-values.md)
11. [Local loop](../../rules/loop-engineering.md#local-loop)と[Validation scope](../../rules/loop-engineering.md#validation-scope)。[Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)
12. 対象IaC fileとstack固有parameter、宣言済み実行入力

- [project-configuration](../../rules/project-configuration.md)と[issue-gate](../../rules/issue-gate.md)。

必須文書はfile／指定sectionごとに読む。tool出力の上限を超える場合は同じfileを行範囲または後述の6,000文字chunkで分割し、指定された読取範囲を省略なしで確認する。複数の大きなfileを一つの出力へ連結しない。同じ準備中に実際に確認済みの必要範囲だけは内容hashが同じなら再読しない。未読sectionをhash一致だけで確認済みにしない。変更・追加・削除があれば変更内容と必要な入力範囲を確認して再準備する。生成物変更を理由に全文再読を要求しない。

Python launcherは準備開始時に既存の利用可能な一つの環境へ固定し、以後の準備・契約登録・controller・local loopへ同じ絶対pathとPATH/PYTHONPATHを使う。依存不足は一度に列挙して同じ環境で解消し、別Pythonを順番に試したり認証確認を重ねたりしない。credential値をログへ保存しない。

通常deployのAI向け設計入力はauthoritative model propertiesとする。設計値は`desired.row.*`、JSON本文は`desired.row.*.document`、resource identity／参照は`desired.resource.*`等の既存metadata、current non-ARN identifierは`observed.*`、stack設定は`cloudformation-stacks.properties`から取得する。生成service Markdown、`cloudformation-stacks.md`、service-owned生成JSON、ビルド済みZIPは通常の本文入力から除外する。

`.md#anchor`形式の参照はMarkdown本文を開く指示ではない。path／file stemから参照先propertiesへ対応付け、既存`model_files.py --resource <resource-selector>`とanchor等のmetadataで必要resourceを確認する。不明・未一致・曖昧なら停止し、生成Markdown本文をfallbackにしない。

生成物の存在確認、hash監視、予約、機械的生成物検証と停止条件は維持する。明示された表示不具合・不一致調査に限り、必要な生成物の該当箇所を読める。model、生成物、IaCの不一致を検出した場合はdeployを継続せず、IaC／intended designを自動修復しない。

`<target-directory>`は、選択targetにaliasがあればalias、なければAWS account IDとする。

指定sectionの読取範囲と条件付き規則はAGENTS.mdの「必要な規則の読み方」に従う。

### Conditional rule readings

framework変更時は[Framework regression](../../rules/loop-engineering.md#framework-regression)、検証の再利用時は[Validation cache](../../rules/loop-engineering.md#validation-cache)、停止・長時間実行時はloopの該当診断sectionを追加する。README全文と非該当sectionを追加読込せず、schema／参照／account／issue／task固有checkは維持する。

## CloudFormation offline preparation

対象の全StackNameと、所有・参照する全service IDを既存properties readerで確認して明示する。service、resource、parameter、参照先の選択を推測しない。CloudFormationでは即席scriptによる契約・予約生成を行わず、次の準備処理を一回実行する。Terraformは既存の契約作成手順を使用する。

```console
<fixed-python> framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --service <service-id> [--service <service-id> ...] --task-file tasks/<task-name>.md [--profile <profile>] [--sequential] [--log-dir <external-directory>]
# aliasなしでは --aws-account-id <aws-account-id>
```

この処理はAWS API、account認証、対応付け検証、lint、controllerを起動せず、repositoryも変更しない。依存をまとめて確認し、既存`load_target`／`load_units`／`read_model`／`model_parts`でtarget・正本StackNameと生成stack設計の一致を解決し、既存の予約検査で競合を確認する。`cloudformation-stacks`を含む明示serviceのmodel入口・part・observed追加時の分割候補・生成Markdown/JSONを具体的pathで予約する。scope外の参照元が必要ならcontrollerの安全確認で停止し、scopeを暗黙に広げない。

出力のrepository外`preparation.json`に、全入力pathと内容hashを`inputs`へ、AIが読む必須ruleの指定sectionとfile別の6,000文字以内のchunkを`documents`へ、本文を省略した生成物pathをソート・重複除去した`generatedViews`へ、契約候補、固定Pythonとtool path、全StackNameを含む一つのcontroller argv／sessionを保存する。`documents`のchunkをfileごとに省略なしで確認し、同じhashで指定範囲を確認済みのfileは再読しない。これは文書確認用であり、modelから生成した設計の整合性検証を代替しない。生成Markdown／JSONとbinary ZIPは`inputs`のhashと予約に残し、`documents`と本文chunk fileを作らない。`generatedViews`は説明用metadataであり、検証済み／PASSの根拠や入力guard省略の理由にしない。一般serviceの生成物一致は既存sync-model／local loopの実行時点で検証し、準備やcontrollerがすべてdeploy前に検証するとは扱わない。

全必須文書と候補が今回のhuman依頼に一致したら、次を実行する。追加のhuman review gateを設けない。

```console
<fixed-python> framework/scripts/deploy_preparation.py --register <external-preparation.json>
```

登録時は入力hash・runtime・最新issue・競合を再確認し、同じPythonで既存`task_contract.py --task-file ... --source ...`を一回使用する。候補の変更・入力変更・競合では登録せず停止する。変更内容と必要な入力だけを再確認して準備を作り直し、既存task／sessionの再開では新規準備・契約を作らず既存resume手順を使用する。新しい本文出力形式が必要な未登録候補は再準備する。`generatedViews`のない従来形式でも`inputs`全件のguardは維持する。登録済みtaskを新規登録し直さない。生成された契約と出力だけでdeploy完了とは扱わない。

`timing.jsonl`は環境確認、契約準備、文書のI/O、文書snapshot作成後から登録までの経過、登録を分けて記録する。snapshot以後の経過にはエージェントの確認・tool待ち時間も含まれる。通常準備は60秒以内を目標にし、`within60Seconds=false`なら遅い工程を実測で報告する。60秒超過だけで打切り、PASS、確認省略を行わない。認証・通信はcontroller側の別工程として測定する。fixtureによるAWS変更なしの計測は実deploy時の所要時間と区別する。

## Create active task contract

最初のrepository changeとして`tasks/<task-name>.md`を今回の対象だけを許可する内容へ新規登録する。CloudFormationは上記`--register`でこの契約を作成するため、手動で二重登録しない。

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

CloudFormationの最終preflight責任者は`cloudformation-deploy.py`とする。controllerがproject target、profile、account、region、engine、active task scope、issue gate、immutable inputを確認する。同じSTS／context checkをpromptから別途実行しない。明示account/regionはprojectの同targetと照合し、明示profileはcontrollerの`--profile`へ渡す。不一致は停止する。

Terraformではcredential、deploy先account、AWS region、IaC engine、必要commandをLLMの推論で判定せず、repository rootから次を実行する。追加inputがなければ`--profile`を省略してよい。scriptはtargetの`awsProfile`を自動使用する。

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

CloudFormationはcontrollerがscopeの既知StackNameへ`describe-stacks`を実行し、必要な対象だけ`get-template`／`list-stack-resources`でtemplate、parameter、所有resource、terminal statusを照合する。通常deployで全stackの`list-stacks`探索を行わない。外部importの既存owner確認が必要な場合は既存ruleを維持する。設計済みで未作成、設計済みで現存、設計外、同名だが内容不一致を区別する。設計外stackや内容不一致を自動採用・変更・削除せず、scopeとの衝突がある場合は停止する。StackId/ARNやstatus snapshotをrepositoryへ保存しない。

## Resolve deployment units

CloudFormationでは既存`load_units()`が正本stack propertiesと生成Markdownの一致を確認し、AIは正本propertiesからStackNameをdeployment identityとしてTemplate、stack固有Parameters、DeployOrder、MaxConcurrentStacksを解決する。同じtemplateの全StackNameを個別unitとして保持する。resource所有、parameter、既存stackとの照合は既存設計とIaCから確認し、曖昧なら停止する。Deployment scopeを自動拡張しない。順序と並列数はcontrollerで強制し、LLMがdependency順を再計算しない。

同stack modelの任意TemplateBucket／TemplateKeyPrefixとartifact対応表を`cloudformation.md`のS3 deployment artifactsに従って読む。配置先は同targetのS3 modelの確定済みBucketNameから解決する。sourceは事前にビルドしたローカルfileとし、deploy中にビルド・対応表・元IaCを変更しない。今回のscopeの宣言済み成果物配置はAWS execution許可に含む。必要bucketが未作成なら停止し、bucket作成やscope拡張を自動実行しない。

Terraformでは対象root、workspace、backend、variable inputを既存IaCから特定する。不足または不一致があれば停止する。

CloudFormationはcontroller起動内でcheck-deploy-contextを一回使用し、再開時もAWS contextを再確認する。mutation直前のtask／issue／input guardは省略しない。

## Validate and deploy

CloudFormationの場合:

1. controllerが`check-deploy-context.py` helperによる最終preflightと、StackNameごとのAWS現存・parameter・resource ownership照合を行う。scopeとtarget、許可はactive taskに次の形式で明記する。

```md
- Deployment scope: `stack-a`, `stack-b`
- AWS API execution: `allowed`
- Deploy/apply: `allowed`
- Target environment: `<environment>`
- Target AWS account: `<account>`
```

aliasがある場合はTarget alias行も追加し、その値をbacktickで囲む。

2. cfn-lintと同じPython環境からcontrollerを起動する。全scopeの入力読込とresource／identifier対応を先に確認する。対応付け不一致は全stack・resource分を一括報告し、cfn-lintとchange set作成前に停止する。対応が一意な場合だけ全scopeのcfn-lintとsource／入力hashを確認し、各unitの順番でImportValue実Export確認、宣言済み成果物のS3配置、実行用template検証、validate-template、個別change set作成、add/change/delete/replacement分類、同一change set再確認、実行、terminal確認を行う。templateは51,200 bytes以下なら直接送信、超過〜1 MiBなら指定bucketへ配置して同じS3 URLをvalidate-templateとchange setへ渡す。上限超過または必要設定不足・upload失敗ではchange setを作成しない。これらのCLIをpromptから別方式で実行して二重管理しない。

```console
<fixed-python> framework/scripts/deploy_preparation.py --run-controller <external-preparation.json>
# 全StackName、固定Python、同task専用sessionとtiming-logを一回のcontroller起動へ渡す
```

準備済みargvを一回だけ起動し、別途のSTS/context、対応付け、lintを重ねない。再開時は`preparation.json`の同じcontroller argv／sessionへ既存の`--resume`と承認済みの場合だけ`--approve-change-set`を追加し、同じtask selectorとruntimeを維持する。

3. controllerは通常一回の起動で全DeployOrderを実行する。順次実行は`--sequential`で実行上限を1にし、設計のMaxConcurrentStacksを変更しない。全対象を繰り返し`--stack`で渡し、順次指定や失敗一覧の収集を理由に1stackずつ別controller／sessionへ分割しない。通常は同group内だけMaxConcurrentStacksまで実行し、空いたslotへ次stackを開始する。producer成功前にconsumerのchange setを作成しない。停止条件後は外側のloopで別stackを起動せず、依存consumerを含む未着手stackをNOT_STARTEDとして報告する。全件の対応付け診断は実行前チェックで収集する。list-exportsに必要なExportがない場合やscope内producerが未成功ならBLOCKEDとし、設計された順序とImport/Export関係の矛盾を報告する。scope外のproducerを自動追加しない。
4. 未承認delete/replacementがあればcontrollerはBLOCKEDとして同じchange set IDと変更のfingerprintをrepository外sessionへ保持し、他のRUNNING stackをterminalまで確認する。次の`Confirm unapproved delete/replacement`の影響説明・human確認を行う。`--approve-change-set`は人間がそのchange set全体を承認した場合だけ渡す。事前承認も実change setの全破壊変更との一致を確認してから同じ方法で再開する。
5. 承認後は同じtaskと同じsessionへ`--resume --approve-change-set <保存されたchange-set-id>`を追加する。controllerが同一ID、CREATE_COMPLETE/AVAILABLE、変更fingerprintを再取得・照合して実行する。変更/失効なら以前の承認で実行しない。成功済みstackを再実行しない。
6. 各groupの成功後、controller内の`cloudformation_observed.py`が実行templateのLogicalId、正式CFn型、catalog IDENTIFIER_OUTPUT、OutputsとPhysicalResourceIdを照合し、必要なnon-ARN identifierと全参照元のobserved rowを更新する。既存sync-modelのservice指定生成・検証が成功してから同process内で次DeployOrderへ進む。最終groupも同期してCOMPLETEとなり、通常成功で追加resumeを要求しない。曖昧な対応は`AMBIGUOUS_OBSERVED_MAPPING`で停止し、LLMが補完しない。failure/blocker時は後続groupへ進まず、成功分のobservedだけ同期する。

7. session v2はinputDigest、validationDigest、validationStatus、検証済み入力digestと計測値を保持する。同一入力／frameworkで前回PASSなら全scope cfn-lintを再実行しない。実AWS context、Export、change set、execute前のimmutable artifact照合は毎回行う。v1 sessionは旧入力hashを照合し、初回の再開で再validation／observed同期してv2へ移行する。sessionはtarget/design/scopeとstackごとのtemplate/parameter/sourceのdigestと配置先bucket/key/version/checksum、実行用template hashを保持する。元IaCを変更しない実行用copyはrepository外sessionに隣接する`.files` directoryへ保存する。配置済みobjectとcopyも再開・execution前に再照合し、以前の承認で変更済み成果物を実行しない。deploy phaseではIaCの変更を一切許さず、update phaseでは未着手NOT_STARTED stackの承認済み設計内のIaC変更だけを再検証して受け付ける。準備済み・実行済みstackのIaCとtarget/design/scopeの変更は再開を拒否する。status/StackId/ARN/履歴はmodelやGitへ保存しない。sessionは同taskの継続用であり成功済みstackを自動rollback/delete/redeployしない。RUNNING取得エラーでは新規起動を止めterminal確認を続ける。controllerへの割り込み後は同じsessionだけで再開し、別sessionの同時実行を行わない。target lockで重複controllerを拒否する。異常終了でlockが残った場合は実行中controllerがないことを確認してからlockだけを除去し、同じsessionを再開する。

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

CloudFormationのobserved収集・生成はcontroller内で完了する。以下の手動収集手順はTerraformに適用する。

deploy/applyが成功した場合:

1. terminal successとresource存在を確認する。
2. `framework/rules/observed-values.md`に従い、取得した値をcatalogの正式な`IDENTIFIER_OUTPUT` propertyへ一意に対応付ける。model propertiesのidentifier output rowと、同じanchorを参照する全propertyのobserved valueだけを同じphysical IDへ先に更新し、link先path、anchor、`Source / Comment`、その他のintended designは変更しない。
3. aliasがあるtargetは`framework/scripts/sync-model.py --write --environment <environment> --alias <alias>`、aliasがないtargetは`framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>`を実行する。

必要なoutputがIaCに存在しない、catalog propertyとの対応が一意でない、または参照元と参照先の値が一致しない場合は推測やIaC修正をせず停止する。replacement後は新しいIDへ更新し、destroy後はidentifier output rowと全参照元を`PENDING_DEPLOY`へ戻す。generated ARNは保存しない。

deploy完了status、resource存在、observed value収集をapplication behaviorの検証またはscenario PASSとして扱わない。

## Verify and finish

1. 対象IaCに変更がないことを確認する。
2. `python framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-name>.md`を一回実行する。task scope、Acceptance checks、Git差分checkを含む。framework regressionの既存条件（full／--all／framework変更）を維持し、framework開発taskとdeploy taskを混在させない。

target、account、region、engine、preflight結果、deployment unitとdependency順、plan/change set summary、human確認待ちと承認結果、deploy完了status、observed value更新、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

IaC、intended design、scenario、scenario result、別target、次taskを変更、作成、実行しない。application behaviorの検証には、humanが別taskとして`framework/prompts/codex/06_scenario-test.md`を使用する。
