# CloudTrail data event対象の1リソース1行表示

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudTrail.Trail詳細設計
- Goal: CloudTrail DataResourcesの対象を1リソース1行、1からの連番、短いType名、resource linkで表示できるFW契約にする。

## Required changes

- [R1] CloudTrail DataResourcesの表示、正式propertyへの対応、modelへの反映をFWルールに定義する。
- [R2] 共通parserとvalidatorで表示行を正式propertyへ展開し、連番・Type・resource linkを検証する。
- [R3] 展開と不正形式のfocused checkを追加する。

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
