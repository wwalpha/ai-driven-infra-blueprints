# CloudFormation Rules

- CloudFormationは`infrastructure` taskでのみ作成・変更・実行する。
- infrastructure taskは承認済みの詳細設計とservice modelをinputとして読み取る。
- intended designの変更が必要な場合は値を補完せず停止し、別の`design` taskが必要であることを報告する。
- active projectと対象environment/target directoryがCloudFormationを選択した場合だけ使用する。
- nested stackは使用しない。
- stack/template boundaryはAWS service単位ではなく、change unit、rollback unit、dependency direction、deploy responsibilityで決める。
- `1 template = 1 deploy responsibility`をdefaultとする。
- cross-stack referenceはdownstreamが必要とするstable valueだけを公開し、不要なcouplingを避ける。
- 詳細設計のidentifier参照はMarkdown linkのanchorからlogical IDを解決して`!Ref`を生成する。link表示textの`PENDING_DEPLOY`またはphysical IDをtemplateへ直書きしない。
- 後続resourceまたは別stackが必要とするcatalog `IDENTIFIER_OUTPUT`はCloudFormation `Outputs`へlogical resource参照で公開する。generated ARNはoutput収集またはobserved value永続化の対象にしない。
- aliasなしの共通templateは`infra/cloudformation/templates/`、alias別templateは`infra/cloudformation/templates/<alias>/`に置く。同じaliasのtemplateをenvironment間で共用し、異なるaliasのtemplateを共用しない。
- target固有parameterは`infra/cloudformation/parameters/<environment>/<target-directory>/`に置く。target directoryはaliasがあればalias、なければAWS account IDとする。
- 1 environment/AWS accountは1 IaC engineだけで管理し、同じAWS account IDを持つalias間でもengineを統一する。
- authorized operationはAWS CLIで行う。

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
