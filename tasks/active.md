# Codex Task: Simplify design handoff prompt flow

## Task contract

- Task type: `governance`
- Goal: `service-design.md`が自己完結したCodex promptを出力する形へ統一し、不要な`apply-design`を廃止して後続promptを繰り上げる
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] chatbot promptを`service-design.md`へ短縮し、完成した詳細設計をrepositoryへ直接反映できる自己完結型Codex promptを出力させる。
- [R2] `03_apply-design.md`を廃止し、implement、deploy、update、scenario-testを`03`から`06`へ繰り上げる。
- [R3] 新規設計と手動修正の正しい使い分け、実行順、filenameをREADMEと関連referenceへ反映する。
- [R4] 新しいdesign handoffとprompt構成をlocal validatorとfocused checkで検証する。

## Acceptance checks

- [R1] `exists:framework/prompts/chatbot/service-design.md`
- [R1] `absent:framework/prompts/chatbot/initial-service-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `absent:framework/prompts/codex/03_apply-design.md`
- [R2] `exists:framework/prompts/codex/03_implement.md`
- [R2] `exists:framework/prompts/codex/04_deploy.md`
- [R2] `exists:framework/prompts/codex/05_update.md`
- [R2] `exists:framework/prompts/codex/06_scenario-test.md`
- [R2] `absent:framework/prompts/codex/04_implement.md`
- [R2] `absent:framework/prompts/codex/05_deploy.md`
- [R2] `absent:framework/prompts/codex/06_update.md`
- [R2] `absent:framework/prompts/codex/07_scenario-test.md`
- [R3] `changed:README.md`
- [R3] `changed:framework/prompts/README.md`
- [R4] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`
- [R4] `check:framework.design-handoff`

## Allowed paths

- `AGENTS.md`
- `README.md`
- `framework/prompts/README.md`
- `framework/prompts/chatbot/**`
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
- 新しいtask typeの追加
