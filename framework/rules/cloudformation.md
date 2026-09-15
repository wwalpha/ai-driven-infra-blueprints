# CloudFormation Rules

- CloudFormationは`infrastructure` taskでのみ作成・変更・実行する。
- infrastructure taskは承認済みの詳細設計とservice modelをinputとして読み取る。
- intended designの変更が必要な場合は値を補完せず停止し、別の`design` taskが必要であることを報告する。
- active projectと対象environment/target directoryがCloudFormationを選択した場合だけ使用する。
- CloudFormation templateをYAMLで記載する際、AWSが短縮記法を提供する組み込み関数は全種類で`!`形式を使い、対応する`Ref:`や`Fn::...:`の長形式を禁止する。`ImportValue`の値に`!Sub`を使用しない。配列引数も`JobId: !Select [0, !Split ['|', !Ref GlueJobDefinition075]]`のように短縮記法のフロー形式で記載する。
- CloudFormation YAMLではYAML anchor/aliasとhash merge（`<<:`）を使用しない。信頼ポリシー、IAM/KMSなどの権限Policy、その他の設定ブロックが同じ場合も各resourceに元の値を明示し、Roleごとの設計JSON artifactと参照を維持する。
- nested stackは使用しない。
- stack/template boundaryはAWS service単位ではなく、change unit、rollback unit、dependency direction、deploy responsibilityで決める。
- `1 template = 1 deploy responsibility`をdefaultとする。
- cross-stack referenceはdownstreamが必要とするstable valueだけを公開し、不要なcouplingを避ける。
- 詳細設計のidentifier参照はMarkdown linkのanchorからlogical IDを解決して`!Ref`を生成する。link表示textの`PENDING_DEPLOY`またはphysical IDをtemplateへ直書きしない。
- 詳細設計の表を統合しても、KMS KeyとAliasはそれぞれ正式なCloudFormation resourceとして実装する。grouped Aliasのlogical IDとanchorを保持し、modelの`parentProperty`へ`parentReference`が指すKeyの`!Ref`を設定する。S3からAliasへの参照は該当Aliasの`!Ref`とし、Keyの参照に置換しない。表示変更だけを理由に既存IaC logical IDを変更しない。
- 後続resourceまたは別stackが必要とするcatalog `IDENTIFIER_OUTPUT`はCloudFormation `Outputs`へlogical resource参照で公開する。generated ARNはoutput収集またはobserved value永続化の対象にしない。
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

複数stackではcross-stack referenceの依存元がterminal successとなり、必要なobserved valueの反映が終わったunitだけを実行可能とする。実行可能なunit同士は並列でchange setを実行し、各stackの完了を個別に確認する。他の独立unitが実行中でも、依存元の成功と必要なobserved valueの反映が終わったunitは次に進める。失敗または未承認のdelete/replacementを検出したら新たなunitを起動せず、実行中のstackの終状態を確認して成功済み・失敗・未実行を区別する。成功済みstackを自動rollback、delete、redeployしない。

`update` phase:

1. humanがtask開始前に手動修正した詳細設計を変更せず、service modelを同期する。
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

deploy/update後は`framework/rules/observed-values.md`の優先順位で必要なnon-ARN identifierをOutputs、必要な場合だけstack resourceから取得し、詳細設計の正式なidentifier output rowと全参照元を更新する。service model同期とlocal loop後にinfrastructure taskを終了する。scenario testまたはscenario evidenceは作成・更新しない。
