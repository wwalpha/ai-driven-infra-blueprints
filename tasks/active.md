# リソース詳細のProperty表示を短縮

## Task contract

- Task type: `governance`
- Target: framework共通 / 全serviceのリソース詳細
- Goal: resource headingで分かる型の接頭辞をProperty列から省き、正式propertyをmodelと検証で維持する。

## Required changes

- [R1] 詳細設計ルール、サンプル、設計promptに短縮表示を定める。
- [R2] 詳細表の短縮表示を共通処理で正式propertyへ復元し、model・検証・policy表示を維持する。
- [R3] 短縮表示のfocused checkを追加する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/detailed-design-samples.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/policy_tables.py`
- [R2] `changed:framework/scripts/security_group_tables.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`
- [R3] `changed:framework/scripts/security_group_tables.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/detailed-design-samples.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/policy_tables.py`
- `framework/scripts/security_group_tables.py`
- `framework/scripts/security_group_tables.checks.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/validate-blueprint.py`

## Out of scope

- target設計、IaC、AWS操作、scenario、catalogは変更しない。
