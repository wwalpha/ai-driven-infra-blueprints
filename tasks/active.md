# Resource modeによるCREATE / IMPORTの管理区分

## Task contract
- Task type: `governance`
- Target: framework resource model / detailed design / naming / IaC rules
- Goal: IMPORTの既存値とName tag不存在を保持し、CREATEの既存検証を維持する。

## Validation scope
- `framework`

## Required changes
- [R1] resourceMode=CREATE|IMPORTをresource metadataとして生成・再解析・検証し、省略時CREATEを維持する。
- [R2] IMPORTだけframework命名とmandatory Name policyを免除し、schema・構造検証を維持する。
- [R3] 設計・取得・IaC rulesとpromptの矛盾を修正し、IMPORTをIaC生成・AWS変更から除外する。
- [R4] 必須5ケースと不正metadata・非命名validation・roundtripの回帰を検証する。

## Acceptance checks
- [R1] `changed:framework/scripts/model_design.py`
- [R1] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/aws-resource-naming.md`
- [R3] `changed:framework/rules/cloudformation.md`
- [R3] `changed:framework/rules/terraform.md`
- [R3] `changed:framework/prompts/chatbot/service-design.md`
- [R4] `changed:framework/scripts/resource_mode.checks.py`

## Allowed paths
- `tasks/active.md`
- `README.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/model_design.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/resource_mode.checks.py`
- `framework/rules/model-information.md`
- `framework/rules/detailed-design.md`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/cloudformation.md`
- `framework/rules/terraform.md`
- `framework/rules/observed-values.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`

## Out of scope
- REFERENCE、CloudFormation Resource Import、Terraform import、AWS取得・変更、consumer同期、実model・設計・IaC・catalog変更。
- 新しいexternal input mechanism、無関係なrefactor、scenario、別task、commit、push。
- 完了前にframework scopeのfull local loopとdiff自己レビューを実施する。
