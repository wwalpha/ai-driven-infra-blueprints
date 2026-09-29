# CodeBuild VPC参照の1リソース1行表示

## Task contract

- Task type: `governance`
- Target: framework共通 / CodeBuild.Project詳細設計
- Goal: CodeBuildのSubnetとSecurity Group参照を、1件1行、1からの連番、resource linkで表示できるFW契約にする。

## Required changes

- [R1] `VpcConfig.Subnets[N]`と`VpcConfig.SecurityGroupIds[N]`の表示、正式propertyとの対応、modelへの反映をFWルールに定義する。
- [R2] 共通parserとvalidatorで連番、resource link、参照先resource typeを検証する。
- [R3] 正常系と不正形式のfocused checkを追加する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/design_layout.checks.py`

## Out of scope

- target設計、model、IaC、AWS操作、scenario、catalogは変更しない。
