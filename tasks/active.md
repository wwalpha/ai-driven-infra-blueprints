# Codex Task: Require Name tags and identifier-first design rows

## Task contract

- Task type: `governance`
- Goal: root-level tag containerを持つresourceのName tagを必須化し、generated identifierを詳細設計tableの先頭へ配置するframework契約を定義する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] root-level tag containerを持つ全catalog resource typeでName tagを必須化し、詳細設計からIaCへ反映する。
- [R2] catalogの`IDENTIFIER_OUTPUT` rowを各resource-detail tableの先頭へ決定的に配置する。
- [R3] Name tagとidentifier-first契約をgeneric validatorとfocused checksで検証する。

## Acceptance checks

- [R1] `exists:framework/rules/aws-resource-naming.md`
- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R1] `changed:framework/prompts/codex/03_implement.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/rules/loop-engineering.md`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- 既存projectの詳細設計、model、IaC、AWS resourceのmigration
- `framework/materials/**`とcatalog lockの変更
- CloudFormation／Terraform rule、deploy prompt、scenarioの変更
- AWS API、deploy、applyの実行
