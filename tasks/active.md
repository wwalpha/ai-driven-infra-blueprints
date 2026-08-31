# Codex Task: Use one-row Name properties in detailed designs

## Task contract

- Task type: `governance`
- Goal: 詳細設計の`Name` tagを`<catalog-resource-type>.Name`の1 rowで表し、必須対象のresource headingとanchorをその値へ一致させる
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] `Name` tagを1 rowのdesign-only `Name` propertyで表し、必須3種類ではheading identifierとanchorを同じ値から生成するruleを定義する。
- [R2] chatbot、model example、IaC implementation promptを1 row表現とAWS tag変換へ統一する。
- [R3] generic validatorとfocused checksで1 row、non-empty value、heading一致を検証し、従来の2 row表現を必須対象として受理しない。

## Acceptance checks

- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R1] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/prompts/codex/03_implement.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/rules/loop-engineering.md`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design.md`
- `framework/rules/loop-engineering.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- 既存projectの詳細設計、model、IaC、AWS resourceのmigration
- `framework/materials/**`とcatalog lockの変更
- identifier-first契約の変更
- AWS API、deploy、applyの実行
