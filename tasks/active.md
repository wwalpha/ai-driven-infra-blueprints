# 詳細設計のresource名表示

## Task contract

- Task type: `governance`
- Target: framework共通 / 詳細設計のheading・resource link・model生成
- Goal: resource headingと表示用linkに確定済みresource名を使用し、内部logical IDを非表示情報として分離する。

## Required changes

- [R1] 全service共通の表示ルール、chatbot prompt、sampleをresource名表示へ揃える。
- [R2] 非表示logical IDをmodel生成で保持し、heading・anchor・一覧の名前を検証する。
- [R3] Schedulerの実名表示、内部ID保持、誤表示拒否と既存表示の回帰を機械検証する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/rules/detailed-design-samples.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/security_group_tables.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/detailed-design-samples.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/security_group_tables.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/*.checks.py`

## Out of scope

- catalog、project設定、target設計、generated model、IaC、AWS操作、scenarioは変更しない。
- 実resource名や未確定値を推測しない。別repositoryの設計移行は行わない。
