# Codex Task: Add manual design update deployment workflow

## Task contract

- Task type: `governance`
- Goal: 人間が手動修正した未commitの詳細設計をIaCへ反映してdeployする専用promptと使い分けを追加する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 手動修正した詳細設計のmodel同期、IaC反映、deployを一つのtaskで行う`06_update.md`を追加する。
- [R2] `update` phaseがhuman-owned design diffをimmutable inputとして扱うruleを追加する。
- [R3] 新規作成と手動修正のprompt使い分けをREADMEへ記載する。
- [R4] 新prompt、番号、`update` phaseをlocal validatorで検証する。

## Acceptance checks

- [R1] `exists:framework/prompts/codex/06_update.md`
- [R1] `exists:framework/prompts/codex/07_scenario-test.md`
- [R1] `absent:framework/prompts/codex/06_scenario-test.md`
- [R2] `changed:AGENTS.md`
- [R2] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/rules/loop-engineering.md`
- [R2] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/rules/terraform.md`
- [R3] `changed:README.md`
- [R3] `changed:framework/prompts/README.md`
- [R4] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `AGENTS.md`
- `README.md`
- `framework/prompts/README.md`
- `framework/prompts/chatbot/initial-service-design.md`
- `framework/prompts/codex/**`
- `framework/rules/loop-engineering.md`
- `framework/rules/cloudformation.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/terraform.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- 既存projectのIaC、詳細設計、model、scenarioの変更
- AWS API、deploy、apply
- chatbotが生成する新規設計反映workflowの変更
- 新しいtask typeの追加
