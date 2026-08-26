# CloudFormation Rules

- CloudFormationは`infrastructure` taskでのみ作成・変更・実行する。
- infrastructure taskは承認済みの詳細設計とLLM design informationをinputとして読み取る。
- intended designの変更が必要な場合は値を補完せず停止し、別の`design` taskが必要であることを報告する。
- active projectと対象environment/AWS accountがCloudFormationを選択した場合だけ使用する。
- nested stackは使用しない。
- stack/template boundaryはAWS service単位ではなく、change unit、rollback unit、dependency direction、deploy responsibilityで決める。
- `1 template = 1 deploy responsibility`をdefaultとする。
- cross-stack referenceはdownstreamが必要とするstable valueだけを公開し、不要なcouplingを避ける。
- reusable templateは`infra/cloudformation/templates/`、AWS account固有parameterは`infra/cloudformation/parameters/<environment>/<aws-account-id>/`に置く。
- 1 environment/AWS accountは1 IaC engineだけで管理する。
- authorized operationはAWS CLIで行う。

## Validation and execution

1. target regionを指定した`cfn-lint`でCloudFormation provider schemaに基づくproperty、型、制約のstatic checkを実行する。
2. `aws cloudformation validate-template`でtemplate構文を検証する。このcommandだけをproperty validationの代替にしない。
3. change setまたは同等のchange summaryを作成してscope、delete、replacementを確認する。
4. repository-levelのmandatory human stopは設けない。
5. active promptがdeploy/updateを許可し、change scopeがpromptと一致する場合だけexecutionへ進む。

次の場合は停止する。

- validation failure
- required input missing
- AWS accountまたはregion mismatch
- task promptが許可していないdelete/replacement
- intended designの不足または変更が必要

active promptが対象を限定している場合は、一部のtemplate、stack、resourceだけを作成・deployして終了できる。残りのresource、別stack、scenario testへ自動的に進まない。

deploy/update後は必要な非ARN actualと詳細設計内のgenerated current valueだけを更新し、local loop後にinfrastructure taskを終了する。scenario testまたはscenario evidenceは作成・更新しない。
