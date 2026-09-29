# GuardDuty Detector Featureの1行表示

## Task contract

- Task type: `governance`
- Target: framework共通 / GuardDuty.Detector詳細設計
- Goal: GuardDuty DetectorのFeatureをNameごとの1行とStatus値で表示し、正式propertyをmodelへ保持する。

## Required changes

- [R1] GuardDuty Featureの表示形式とmodelへの対応を設計ルールとchatbot手順に明記する。
- [R2] 表示行を正式なFeatures[].Name/Statusへ復元し、構造・値・順序を検証する。
- [R3] 複数Feature、重複名、不正Status、正式propertyの個別表示をfocused checkで確認する。

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

- catalog、schema、target設計、IaC、AWS操作、scenarioは変更しない。
