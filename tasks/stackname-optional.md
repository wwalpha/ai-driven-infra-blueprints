# CloudFormation StackNameのnumberをoptionalにする

## Task contract
- Task type: `governance`
- Task status: `completed`
- Target: CloudFormation StackNameの共通命名規則と標準例
- Goal: StackNameは通常numberを省略し、同じ用途の複数stackを区別する場合だけoptionalなnumberを使えるようにする。

## Validation scope
- `framework`

## Required changes
- [R1] CloudFormation Stackの命名patternを`cfn-stack-{{application}}-{{environment}}-{{purpose}}[-{{number}}]`へ変更し、通常はnumberなし、必要な場合だけnumberを付ける規則を明記する。
- [R2] 標準例をnumberなしに揃え、複数stackのnumber付き例はoptionalな使用例として保持する。
- [R3] 番号なし・番号ありのStackNameが既存のmodel生成・表示解析で保持されることを既存回帰で確認する。

## Acceptance checks
- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R2] `changed:framework/rules/detailed-design-samples.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:README.md`
- [R3] `changed:framework/scripts/model_design.checks.py`

## Modified files
- `tasks/stackname-optional.md`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design-samples.md`
- `framework/rules/model-information.md`
- `framework/scripts/model_design.checks.py`
- `README.md`

## Allowed paths
- `tasks/stackname-optional.md`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design-samples.md`
- `framework/rules/model-information.md`
- `framework/scripts/model_design.checks.py`
- `README.md`

## Out of scope
- 他resourceの命名規則、既存consumerのstack rename、model、設計、IaC、catalog、project.json、AWS API、deploy/apply、scenario、commit、push、別task。

## Completion
- framework scopeのfull local loopでtask固有check、Acceptance checks、全framework回帰を実行する。
