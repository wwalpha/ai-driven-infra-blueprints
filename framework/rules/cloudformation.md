# CloudFormation Rules

対象environment/target/serviceに未解決issueがある間は通常taskを開始・継続しない。`framework/rules/loop-engineering.md`のUnresolved issue gateに従い、issue調査とhumanが明示したIssue remediationだけを許可する。

- CloudFormationは`infrastructure` taskでのみ作成・変更・実行する。
- infrastructure taskは承認済みの詳細設計とservice modelをinputとして読み取る。
- intended designの変更が必要な場合は値を補完せず停止し、別の`design` taskが必要であることを報告する。
- active projectと対象environment/target directoryがCloudFormationを選択した場合だけ使用する。
- 対象targetの`awsProfile`があればpreflightとcontrollerが自動使用する。直接のAWS CLI（validate-template、list/get/describe、observed値取得を含む）にも同じ`--profile`と対象regionを渡す。設定と異なる明示profileは実行前に拒否し、認証失敗時に別profileへfallbackしない。
- CloudFormation templateをYAMLで記載する際、AWSが短縮記法を提供する組み込み関数は全種類で`!`形式を使い、対応する`Ref:`や`Fn::...:`の長形式を禁止する。`ImportValue`の値に`!Sub`を使用しない。配列引数も`JobId: !Select [0, !Split ['|', !Ref GlueJobDefinition075]]`のように短縮記法のフロー形式で記載する。
- CloudFormation YAMLではYAML anchor/aliasとhash merge（`<<:`）を使用しない。同一の信頼ポリシー、IAM/KMSなどの権限Policy、その他の設定ブロックは各resourceに元の値を明示する。同一内容を理由に共有を要求せず、Roleごとの設計JSON artifactと参照を維持する。
- CloudFormation YAMLの`Resources`配下は、resourceと次のresourceの間に1行以上の空行を入れる。
- nested stackは使用しない。
- stack/template boundaryはAWS service単位ではなく、change unit、rollback unit、dependency direction、deploy responsibilityで決める。
- `1 template = 1 deploy responsibility`をdefaultとするが、同じtemplateを複数stack instanceで使用できる。deploy/updateの実行単位はtemplate pathではなく`cloudformation-stacks.md`のStackNameとする。
- CloudFormation targetのstack作成・更新には`framework/rules/detailed-design.md`のstack詳細設計を必須とする。各stack instanceのStackName、templateのファイル名、個別parameterのファイル名、DeployOrderとtargetのMaxConcurrentStacksを正本propertiesから解決し、生成Markdownと一致を確認する。templateとparameterの配置先はこのruleのpath規約に従う。templateやparameterのファイル名だけからStackNameを推測しない。
- deploy前に対象account/regionのstackをread-onlyで照合し、設計済みstackの現存・状態・parameter・resource所有を確認する。設計外stack、同名だが設計と異なるstack、設計済みでAWSに存在しないstackを区別し、設計外stackを自動採用・変更・削除しない。stackのcurrent statusはAWSから都度取得し、Gitへstatus snapshotを保存しない。
- 設計からStackNameが消えたり別名へ変わったりしても、既存stackのdeleteまたはrenameとして解釈しない。既存stackの管理終了・削除は対象と影響が明示された別の許可scopeで判断し、現在のdeploy/updateへ暗黙に含めない。
- CloudWatch Logs resource（`AWS::Logs::*`）とSecurity Group（`AWS::EC2::SecurityGroup*`）だけを所有する単独template/stackは作らず、利用するresourceのtemplateに含める。IAM Roleは同じtargetで直接利用するresourceがあればそのtemplateに含める。直接利用するresourceがないRole（cross-account switch roleなど）は、同targetの設計resourceからRoleへの直接参照がないこととRoleのtrust policyのPrincipalを確認し、用途とAssumeRole元を設計に記録してから、Roleと付随するIAM Policy/ManagedPolicyだけを所有する専用template/stackに置く。このtemplateには`Metadata`直下の`RolePlacement: standalone`を宣言する。宣言は設計判断を表し、AWS上の未利用を証明しない。InstanceProfileを加えてRole専用templateとはみなさない。
- cross-stack referenceはdownstreamが必要とするstable valueだけを公開し、不要なcouplingを避ける。
- template外のresourceを`!Ref`、`!GetAtt`、`!Sub`、policy/設定値の文字列などで使う場合は、実際のresourceとその所有stackを特定する。文字列の一致だけでresource参照と判断しない。同一AWS account・regionの別CloudFormation stackが所有するresourceなら、producer templateのOutputsとdeploy済みstackのexportsを照合し、必要な値をexport済みか確認する。所有stack、参照する値、export名が一意に確認できなければ推測せず停止する。
- 必要なexportがなく、producerが本frameworkのCREATE管理対象の場合はproducer templateに必要な値だけのOutput/Exportを追加し、許可されたinfrastructure taskでproducer stackを先にdeployする。terminal successと実際のexport名・値をread-onlyで確認するまでconsumer templateを変更・deployしない。既存importが使うexport名・値を命名形式だけで変更しない。producerとconsumerを同じtaskで扱えない場合はtask boundaryを守って順に実施する。
- producerのexport確認後、consumer templateではそのexport名を`!ImportValue`で参照する。参照値を文字列の一部に使う場合は`!Sub`のvariable mapまたは`!Join`へ`!ImportValue`を渡し、physical IDやgenerated ARNをliteralに残さない。import先は同じAWS account・regionとし、producer成功後にconsumerのchange setを作成する。cross-stack用のARN exportが必要な場合もgenerated ARNをobserved valueとして保存しない。
- templateの`Resources` key（resource logical ID）と`Outputs.*.Export.Name`の最終値はPascalCaseとする。先頭はASCII大文字、以降はASCII英数字だけを使い、hyphen、underscore、空白を含めない。exportしないOutputのkeyやAWS生成のphysical IDにはこのruleを適用しない。
- CREATEを参照する詳細設計のidentifier参照はMarkdown linkのanchorからlogical IDを解決して`!Ref`を生成する。link表示textの`PENDING_DEPLOY`またはphysical IDをtemplateへ直書きしない。
- 詳細設計のlogical IDとCloudFormation resource logical IDは一意に対応付け、template内の`!Ref`、`!GetAtt`、OutputsにはCloudFormation側のPascalCase IDを使用する。設計IDやanchor、確定済みresource名は命名形式だけを理由に変更しない。PascalCaseへの変換で衝突する場合、またはtarget別parameterを含むExport Nameの最終値を確認できない場合は推測せず停止する。既存stackのlogical IDやExport Nameの変更はresourceの削除・再作成やcross-stack参照の切断を伴い得るため、命名形式だけを理由に自動変更しない。
- 詳細設計の表を統合しても、CREATEのKMS KeyとAliasはそれぞれ正式なCloudFormation resourceとして実装する。IMPORTは生成しない。grouped Aliasのlogical IDとanchorを保持し、modelの`parentProperty`へ`parentReference`が指すKeyの`!Ref`を設定する。S3からAliasへの参照は該当Aliasの`!Ref`とし、Keyの参照に置換しない。表示変更だけを理由に既存IaC logical IDを変更しない。
- 後続resourceまたは別stackが必要とするCREATEのcatalog `IDENTIFIER_OUTPUT`はCloudFormation `Outputs`へlogical resource参照で公開する。generated ARNはoutput収集またはobserved value永続化の対象にしない。
- aliasなしの共通templateは`infra/cloudformation/templates/`、alias別templateは`infra/cloudformation/templates/<alias>/`に置く。同じaliasのtemplateをenvironment間で共用し、異なるaliasのtemplateを共用しない。
- target固有parameterは`infra/cloudformation/parameters/<environment>/<target-directory>/`に置く。target directoryはaliasがあればalias、なければAWS account IDとする。
- resourceの正式な名前propertyまたは`Name` tagにEnvironment IDを含める場合、templateの`Parameters`に独立した`Environment`を宣言し、target別parameter fileでは`Environment`に`project.json`の対象Environment IDを設定する。名前はresourceのproperty／tag valueで`!Sub`、`!Join`、`!Ref`などから合成し、AWS account ID等の独立したcomponentと同様に扱う。詳細設計にある確定済みの完成名は変更しない。
- target別parameter fileの`Environment`以外のparameter value（resource名、prefix、suffix等）に対象Environment IDを名称componentとして含めない。例えば`Environment=dev`、`NamePrefix=app`から`app-dev-role`をtemplate内で作る。`NamePrefix=app-dev`は`Environment` parameterの有無にかかわらず違反とする。templateに完成名を固定したり、別parameterにEnvironmentを埋め込んで二重に付加したりしない。
- 1 environment/AWS accountは1 IaC engineだけで管理し、同じAWS account IDを持つalias間でもengineを統一する。
- authorized operationはAWS CLIで行う。

## Design coverage and CloudFormation support

- 詳細設計とmodelにはCFn非対応resourceも含まれる。実装対象の各resource typeについて`python framework/scripts/design_catalog.py --cloudformation-type <catalog-resource-type>`で正式CFn型を解決する。未知の型または`cloudFormationType: null`は失敗とし、resource typeの文字列置換だけで`AWS::`型を発明しない。
- `Macie.Session`は既存CFn schemaを使用する。`Macie.ClassificationJob`はCFn非対応として扱い、JobをCFn template、Outputs、`!Ref`の対象にしない。
- active taskがCFn対応範囲だけを指定していれば、その範囲を実装して終了する。Jobが実装要求に含まれる場合は未実装対象として明示し、scopeを黙って縮小せず、その要求を完了扱いにしない。JobのためのCustom Resourceや別engineを自動追加しない。
- CFn resourceからAPI resourceのidentifierが必要な場合も架空の`!Ref`を生成しない。承認済みの外部入力の受渡し設計がなければ、不足する依存関係を報告して停止する。link表示textのcurrent IDから実装方法を推測しない。

## Resource mode boundary

- 正本modelのresourceMode=CREATE（未指定を含む）だけをCloudFormation生成対象とする。IMPORTは詳細設計・propertiesに保持するがIaC生成対象外で、AWS resourceを変更しない。IMPORTを`Resources`へ生成しない。CloudFormation Resource Import、Import change setの作成・実行、既存resourceのStack管理への移行を行わない。
- IMPORTはframework上の設計管理区分であり、CloudFormationのimport機能ではない。値をframework命名へ修正せず、Name tagを追加・変更しない。
- 本ruleのresource実装・logical ID対応・identifier参照・Outputs／output生成はCREATEに限る。grouped childも独立identityがあれば自身のresourceModeで判定する。inline設定は包含resourceの区分に従う。
- CREATEからIMPORTへの参照は架空のresource参照を生成しない。既存の承認済み受渡し設計がなければ不足を報告して停止し、新しいexternal input mechanismを設計しない。IMPORTを所有する外部stack／stateへ変更を加えない。
- 既にIaC管理中のresourceをIMPORTへ切り替えることを、template／configurationからの自動削除や管理解除の許可と解釈しない。検出時は影響を報告して停止する。

## Validation and execution

`implement` phase:

1. target regionを指定した`cfn-lint`でCloudFormation provider schemaに基づくproperty、型、制約のstatic checkを実行する。
2. AWS API、`aws cloudformation validate-template`、change set、deploy/updateを実行しない。

`deploy` phase:

1. 対象templateを変更せず、target regionを指定した`cfn-lint`を再実行する。
2. `aws cloudformation validate-template`でtemplate構文を検証する。このcommandだけをproperty validationの代替にしない。
3. change setを作成してscope、delete、replacementを確認する。
4. 全change setを一律停止するhuman reviewは設けない。未承認のdelete/replacementがある場合だけ`framework/prompts/codex/04_deploy.md`に従って説明付きhuman確認待ちにする。
5. active promptがdeploy/updateを許可し、change scopeがpromptと一致し、delete/replacementが事前承認済みまたはchange set作成後にhuman承認された場合だけexecutionへ進む。
6. IaC修正が必要な場合はこのphaseで変更せず停止する。

複数stackのqueue、順序、並列上限、failure stopは`framework/scripts/cloudformation-deploy.py`で強制する。Deployment scopeのStackNameだけをDeployOrder数値昇順、同group内StackName順に処理する。同一DeployOrder groupだけが並列実行可能であり、RUNNING数はMaxConcurrentStacks以下とする。空いたslotを同groupのqueueへ再利用し、固定batchにしない。group全体のterminal successとobserved value反映後だけ次groupへ進む。値は連番でなくてよい。DeployOrderをCloudFormation resourceの`DependsOn`へ変換せず、stack modelにdependency fieldを追加しない。

consumerのchange set作成直前に、既存cfn-lint decoderで`!ImportValue`を解釈し、stack固有parameter/defaultとaccount/regionを使って参照するExport名を解決し、targetの`list-exports`で実在を確認する。未解決式、未存在Export、scope内の未成功producerはBLOCKEDとする。誤ったDeployOrderとImport/Exportの矛盾を説明し、scope外producer追加、順序変更、IaC/intended designの自動修正を行わない。scope外producerのExportが既に存在すればconsumer単独deployを許可する。Transformで動的生成されるimportは事前解決できないため停止する。

failure/rollbackまたはblocker/未承認delete/replacementを検出したら新たなunitを起動せず、実行中のstackだけterminalまで確認する。StackName単位でSUCCESS、FAILED、BLOCKED、NOT_STARTEDを区別する。status API errorはterminal failureとみなさず、queueを止めて実行中stackの取得だけ再試行する。成功済みstackを自動rollback、delete、redeployしない。controller自身はrollback/delete APIを呼ばない。

`update` phase:

1. humanがtask開始前に手動修正したmodel propertiesを変更せず、Markdownを生成する。
2. implement phaseと同じ`cfn-lint`を実行して対象templateを作成・変更する。
3. deploy phaseと同じpreflight、`aws cloudformation validate-template`、change set確認、execution、完了確認を続けて実行する。
4. このphase内で生成した対象templateのuncommitted diffだけをdeploy対象として許可する。

## Delete and replacement confirmation

- `Remove`、`Replacement: True`、`Replacement: Conditional`をresource typeに関係なく確認対象とする。`Action`または`Replacement`の値を確定できない場合は承認可能な変更として扱わず停止する。
- 未承認のdelete/replacementはdeployment failureまたはtask完了として扱わず、作成済みchange setを実行しないままhuman確認待ちにする。
- human承認後は同じtaskで同じchange set IDを再取得し、statusが`CREATE_COMPLETE`、execution statusが`AVAILABLE`、承認対象のlogical ID、action、replacement、`PolicyAction`が一致する場合だけそのchange setを実行する。
- change setが失効、再作成、変更されている場合は以前の承認を使用せず、新しいchange setの内容を説明して再確認する。
- 一部の変更だけが承認された場合はchange setを実行しない。template修正、resource保持、CloudFormation管理外化が必要な場合は現在のdeploy/update phaseでIaCを変更せず停止する。

次の場合は停止する。

- validation failure
- required input missing
- AWS accountまたはregion mismatch
- delete/replacementのactionを確定できない
- intended designの不足または変更が必要

active promptが対象を限定している場合は、implement phaseでは一部のtemplate、deploy phaseでは一部のstack/resourceだけを処理して終了できる。残りのresource、別stack、scenario testへ自動的に進まない。

deploy/update後は`framework/rules/observed-values.md`の優先順位で必要なnon-ARN identifierをOutputs、必要な場合だけstack resourceから取得し、詳細設計のmodelのidentifier output／全参照元のobserved valueを先に更新し、Markdownを生成する。表示同期とlocal loop後にinfrastructure taskを終了する。scenario testまたはscenario evidenceは作成・更新しない。
