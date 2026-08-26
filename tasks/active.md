# Codex Task: Split infrastructure implementation and deployment prompts

## Task contract

- Task type: `governance`
- Goal: IaC作成・検証とdeploy/applyを別々のCodex promptへ分離する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] IaC作成専用promptとdeploy/apply専用promptを分離する。
- [R2] phaseごとのworkflowとCloudFormation/Terraform ruleを明確にする。
- [R3] infrastructure phaseと新しいdeploy promptをlocal validatorで検証する。

## Acceptance checks

- [R1] `changed:framework/prompts/codex/implement-infrastructure.md`
- [R1] `changed:framework/prompts/codex/deploy-infrastructure.md`
- [R2] `changed:README.md`
- [R2] `changed:framework/rules/loop-engineering.md`
- [R2] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/rules/terraform.md`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `README.md`
- `framework/prompts/codex/implement-infrastructure.md`
- `framework/prompts/codex/deploy-infrastructure.md`
- `framework/rules/loop-engineering.md`
- `framework/rules/cloudformation.md`
- `framework/rules/terraform.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- 既存projectのIaC、詳細設計、model、scenarioの変更
- AWS API、deploy、apply
- 新しいtask typeの追加
